"""NAGARSAATHI FastAPI backend gateway. Run with uvicorn backend.main:app."""
import io
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

# Ultralytics patches Image.open after startup. Keep Pillow's original decoder
# for upload validation so malformed images cannot trigger optional HEIF imports.
_PIL_OPEN = Image.open
logger = logging.getLogger("uvicorn.error")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

try:
    from backend.accounts import current_user, router as accounts_router
    from backend.database import connect, init_db
    from backend.reports import router as reports_router
    from backend.issues import router as issues_router
except ImportError:
    from accounts import current_user, router as accounts_router
    from database import connect, init_db
    from reports import router as reports_router
    from issues import router as issues_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Safe database initialization
    await run_in_threadpool(init_db)
    app.state.model_ready = False

    try:
        try:
            from backend.inference import load_model
        except ImportError:
            from inference import load_model

        await run_in_threadpool(load_model)
        app.state.model_ready = True
        logger.info("YOLO11n pothole/waterlogging model loaded successfully")
    except Exception as e:
        logger.warning(f"Model could not be loaded: {e}. Submissions will remain available.")

    yield


app = FastAPI(
    title="NAGARSAATHI Backend",
    lifespan=lifespan,
)

# CORS middleware for local frontend development
allowed = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://127.0.0.1:5174,http://127.0.0.1:5173,http://localhost:5174,http://localhost:5173",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(accounts_router)
app.include_router(reports_router)
app.include_router(issues_router)


def error_response(status_code: int, code: str, message: str):
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request, exc):
    return error_response(
        400,
        "INVALID_REQUEST",
        "Check required fields, field lengths, and valid values.",
    )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_ready": getattr(app.state, "model_ready", False),
    }


@app.get("/metrics")
def metrics(user: dict = Depends(current_user)):
    with connect() as db:
        if user["role"] == "nigam":
            table, where, params, unit = "issues", "WHERE published=1", [], "issues"
        else:
            table, where, params, unit = "reports", "", [], "reports"
            if user["role"] != "admin":
                where, params = "WHERE user_id=?", [user["id"]]
        rows = db.execute(f"SELECT * FROM {table} {where}", params).fetchall()
        issue_count = len(rows) if unit == "issues" else len({r["issue_id"] for r in rows})
        status_counts = {name: sum(r["status"] == name for r in rows)
                         for name in ("open", "in_progress", "resolved", "rejected", "submitted", "under_review")}
        return {
            "total": len(rows), "pothole": sum(r["issue_type"] in ("pothole", "both") for r in rows),
            "waterlogging": sum(r["issue_type"] in ("waterlogging", "both") for r in rows),
            **status_counts, "unit": unit, "issue_count": issue_count,
        }


@app.get("/ready")
def ready():
    if not getattr(app.state, "model_ready", False):
        return error_response(503, "MODEL_UNAVAILABLE", "The model has not finished loading")
    with connect() as db:
        db.execute("SELECT 1").fetchone()
    return {"status": "ready", "model_ready": True}


@app.get("/complaints")
def list_complaints_alias(
    search: str = "",
    issue: str = "",
    status: str = "",
    since: str = "",
    until: str = "",
    sort: str = "newest",
    offset: int = 0,
    limit: int = 40,
    mine: bool = False,
    user: dict = Depends(current_user)
):
    if user["role"] == "nigam":
        raise HTTPException(403, "Use the consolidated issues endpoint")
    where_parts = []
    params = []
    if mine or user["role"] != "admin":
        where_parts.append("user_id = ?")
        params.append(user["id"])
    if issue:
        where_parts.append("issue_type IN (?, 'both')")
        params.append(issue)
    if status:
        where_parts.append("status = ?")
        params.append(status)
    if search:
        where_parts.append("description LIKE ?")
        params.append(f"%{search}%")

    where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    with connect() as db:
        count_row = db.execute(f"SELECT COUNT(*) AS c FROM reports {where_clause}", params).fetchone()
        total_count = count_row["c"] if count_row else 0

        rows = db.execute(
            f"""SELECT * FROM reports {where_clause}
            ORDER BY created_at {('DESC' if sort != 'oldest' else 'ASC')}, id DESC
            LIMIT ? OFFSET ?""",
            [*params, limit, offset]
        ).fetchall()

    try:
        from backend.reports import serialize
    except ImportError:
        from reports import serialize

    with connect() as db:
        return {"items": [serialize(r, db, user["role"] == "admin") for r in rows], "total": total_count}


@app.get("/complaints/{complaint_id}")
def get_complaint_alias(complaint_id: int, user: dict = Depends(current_user)):
    try:
        from backend.reports import get_report
    except ImportError:
        from reports import get_report
    return get_report(report_id=complaint_id, user=user)


@app.post("/dev/detect", tags=["Local model testing"])
def test_photo(image: UploadFile = File(...), user: dict = Depends(current_user)):
    if not getattr(app.state, "model_ready", False):
        return error_response(
            503,
            "MODEL_UNAVAILABLE",
            "The model is not ready. Check server logs.",
        )

    # Read at most 10 MB plus one byte
    image_bytes = image.file.read(10_000_000 + 1)
    if len(image_bytes) > 10_000_000:
        return error_response(
            413,
            "IMAGE_TOO_LARGE",
            "Upload an image smaller than or equal to 10 MB.",
        )

    try:
        with _PIL_OPEN(io.BytesIO(image_bytes), formats=["JPEG", "PNG", "WEBP"]) as original:
            if original.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Unsupported format")
            if getattr(original, "n_frames", 1) != 1:
                raise ValueError("Animated images are unsupported")
            if original.width * original.height > 24_000_000:
                raise ValueError("Image exceeds megapixel limit")

            corrected = ImageOps.exif_transpose(original).convert("RGB")
            canonical = Image.new("RGB", corrected.size)
            canonical.paste(corrected)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return error_response(
            400,
            "INVALID_IMAGE",
            "Upload a valid, single-frame JPEG or PNG image.",
        )

    try:
        try:
            from backend.inference import detect_potholes
        except ImportError:
            from inference import detect_potholes

        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / "test.png"
            canonical.save(temp_path, format="PNG")
            result = detect_potholes(str(temp_path))
        return result
    except Exception as e:
        logger.exception("Photo detection failed")
        return error_response(
            503,
            "ANALYSIS_UNAVAILABLE",
            "The photo could not be analysed. Please retry or submit for human review.",
        )
