"""NAGARSAATHI FastAPI backend gateway. Run with uvicorn backend.main:app."""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("uvicorn.error")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

try:
    from backend.accounts import current_user, router as accounts_router
    from backend.database import connect, init_db
    from backend.reports import router as reports_router
    from backend.issues import router as issues_router
    from backend.worker_api import router as worker_router
    from backend.moderation import router as moderation_router
    from backend.work_orders import router as work_router
    from backend.google_auth import router as google_router
except ImportError:
    from accounts import current_user, router as accounts_router
    from database import connect, init_db
    from reports import router as reports_router
    from issues import router as issues_router
    from worker_api import router as worker_router
    from moderation import router as moderation_router
    from work_orders import router as work_router
    from google_auth import router as google_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Safe database initialization
    await run_in_threadpool(init_db)
    logger.info('Report intake ready; model inference runs in the separate PC worker')
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
app.include_router(worker_router)
app.include_router(moderation_router)
app.include_router(work_router)
app.include_router(google_router)


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
        "processing_mode": "external_worker",
    }


@app.get("/metrics")
def metrics(user: dict = Depends(current_user)):
    with connect() as db:
        if user["role"] == "nigam":
            table, where, params, unit = "issues", "WHERE published=1 AND EXISTS(SELECT 1 FROM reports r WHERE r.issue_id=issues.id AND r.archived_at IS NULL)", [], "issues"
        else:
            table, where, params, unit = "reports", "WHERE archived_at IS NULL", [], "reports"
            if user["role"] != "admin":
                where, params = "WHERE archived_at IS NULL AND user_id=?", [user["id"]]
        rows = db.execute(f"SELECT * FROM {table} {where}", params).fetchall()
        issue_count = len(rows) if unit == "issues" else len({r["issue_id"] for r in rows if r['issue_id'] is not None})
        status_counts = {name: sum(r["status"] == name for r in rows)
                         for name in ("open", "in_progress", "resolved", "rejected", "submitted", "under_review")}
        return {
            "total": len(rows), "pothole": sum(r["issue_type"] in ("pothole", "both") for r in rows),
            "waterlogging": sum(r["issue_type"] in ("waterlogging", "both") for r in rows),
            **status_counts, "unit": unit, "issue_count": issue_count,
        }


@app.get("/ready")
def ready():
    with connect() as db:
        db.execute("SELECT 1").fetchone()
    return {"status": "ready", "processing_mode": "external_worker"}


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
    needs_attention: bool = False,
    mine: bool = False,
    user: dict = Depends(current_user)
):
    if user["role"] == "nigam":
        raise HTTPException(403, "Use the consolidated issues endpoint")
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(400, 'Limit must be 1–100 and offset non-negative')
    where_parts = ['archived_at IS NULL']
    params = []
    if needs_attention and user['role'] == 'admin':
        where_parts.append("(verification_status='needs_review' OR analysis_status='failed')")
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


@app.post("/dev/detect", deprecated=True)
def test_photo(user: dict = Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Citizen-side model preview is disabled")
    raise HTTPException(410, "Use the queued processing worker; inline inference has been removed")
