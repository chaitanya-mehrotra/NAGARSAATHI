"""Persistent complaints with image validation, safe pre-analysis storage, and YOLO detection."""
import io
import json
import logging
import math
import secrets
import time
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

_PIL_OPEN = Image.open  # Capture before the model's optional-format monkeypatch.
try:
    from backend.accounts import admin_user, current_user, bearer
    from backend.database import DATA_DIR, connect
except ImportError:
    from accounts import admin_user, current_user, bearer
    from database import DATA_DIR, connect

router = APIRouter(prefix="/reports", tags=["Complaints"])
logger = logging.getLogger("uvicorn.error")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB max size
MAX_MEGAPIXELS = 24_000_000


def distance_metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine formula to calculate distance in metres between two points."""
    a, b = math.radians(lat1), math.radians(lat2)
    h = math.sin((b - a) / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def serialize(row) -> dict:
    report = dict(row)
    photo_name = report.pop("photo_name", "")
    result_raw = report.pop("result_json", None)
    report["analysis"] = json.loads(result_raw) if result_raw else None
    report["photo_url"] = f"/reports/{row['id']}/photo"
    return report


def accessible_report(db, report_id: int, user: dict):
    row = db.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if row is None or (user["role"] != "admin" and row["user_id"] != user["id"]):
        raise HTTPException(404, "Report not found")
    return row


@router.post("", status_code=201)
def submit_report(
    request: Request,
    description: str = Form(..., min_length=1, max_length=2000),
    latitude: float = Form(..., ge=-90, le=90),
    longitude: float = Form(..., ge=-180, le=180),
    issue_type: str = Form("pothole"),
    image: UploadFile = File(...),
    user: dict = Depends(current_user)
):
    description = description.strip()
    if not description or not math.isfinite(latitude) or not math.isfinite(longitude):
        raise HTTPException(400, "Enter a valid description and coordinates")

    if issue_type not in ("pothole", "waterlogging", "both"):
        issue_type = "pothole"

    # Validate image upload size
    content = image.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Photo must be 10 MB or smaller")

    # Validate actual image content
    try:
        with _PIL_OPEN(io.BytesIO(content), formats=["JPEG", "PNG", "WEBP"]) as original:
            if original.format not in ("JPEG", "PNG", "WEBP"):
                raise ValueError("Unsupported format")
            if getattr(original, "n_frames", 1) != 1:
                raise ValueError("Animated images are unsupported")
            if original.width * original.height > MAX_MEGAPIXELS:
                raise ValueError("Image exceeds megapixel limit")

            # Remove EXIF/GPS/XMP metadata and standardize orientation
            corrected = ImageOps.exif_transpose(original).convert("RGB")
            canonical = Image.new("RGB", corrected.size)
            canonical.paste(corrected)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        logger.warning(f"Image validation rejected upload: {e}")
        raise HTTPException(400, "Upload a valid JPEG or PNG photo")

    # Create persistent storage folder
    photos_dir = DATA_DIR / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    photo_name = secrets.token_hex(16) + ".png"
    photo_path = photos_dir / photo_name
    now = int(time.time())

    # Save photo and record in SQLite BEFORE running AI model detection
    try:
        canonical.save(photo_path, format="PNG")
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # Suggest possible nearby duplicate within 30 metres from recent open reports
            candidates = db.execute(
                """SELECT id, latitude, longitude FROM reports
                WHERE duplicate_of IS NULL AND status IN ('open', 'in_progress') AND created_at >= ?
                ORDER BY id""",
                (now - 30 * 86400,)
            ).fetchall()

            nearby = [(distance_metres(latitude, longitude, r["latitude"], r["longitude"]), r["id"]) for r in candidates]
            nearest = min(nearby, default=(float("inf"), None))
            duplicate_id = nearest[1] if nearest[0] <= 30 else None

            cursor = db.execute(
                """INSERT INTO reports
                (user_id, description, latitude, longitude, photo_name, created_at, issue_type, duplicate_of)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (user["id"], description, latitude, longitude, photo_name, now, issue_type, duplicate_id)
            )
            report_id = cursor.lastrowid
    except Exception:
        photo_path.unlink(missing_ok=True)
        raise

    # Model detection: run after saving, never failing the saved complaint
    result = None
    analysis_status = "unavailable"
    model_ready = getattr(request.app.state, "model_ready", False)

    if model_ready:
        try:
            try:
                from backend.inference import detect_potholes
            except ImportError:
                from inference import detect_potholes

            result = detect_potholes(str(photo_path))
            analysis_status = "completed"
        except Exception:
            logger.exception("Analysis failed for report %s", report_id)
            analysis_status = "failed"

    with connect() as db:
        db.execute(
            "UPDATE reports SET analysis_status = ?, result_json = ? WHERE id = ?",
            (analysis_status, json.dumps(result) if result is not None else None, report_id)
        )
        saved = db.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        return serialize(saved)


@router.get("")
def list_reports(
    limit: int = 50,
    offset: int = 0,
    user: dict = Depends(current_user)
):
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(400, "Limit must be 1–100 and offset non-negative")

    where, params = ("", []) if user["role"] == "admin" else ("WHERE user_id = ?", [user["id"]])
    with connect() as db:
        rows = db.execute(
            f"""SELECT * FROM reports {where}
            ORDER BY CASE priority
                WHEN 'urgent' THEN 0
                WHEN 'high' THEN 1
                WHEN 'normal' THEN 2
                ELSE 3
            END, created_at DESC, id DESC
            LIMIT ? OFFSET ?""",
            [*params, limit, offset]
        ).fetchall()
        return [serialize(row) for row in rows]


@router.get("/{report_id}")
def get_report(report_id: int, user: dict = Depends(current_user)):
    with connect() as db:
        return serialize(accessible_report(db, report_id, user))


def resolve_photo_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    token: str = Query(default="")
):
    tok = credentials.credentials if (credentials and credentials.credentials) else token
    if not tok:
        raise HTTPException(401, "Login required")
    try:
        from backend.accounts import token_hash
    except ImportError:
        from accounts import token_hash
    with connect() as db:
        row = db.execute(
            """SELECT u.id, u.name, u.email, u.role FROM users u
            JOIN sessions s ON s.user_id = u.id
            WHERE s.token_hash = ? AND s.expires_at > ?""",
            (token_hash(tok), int(time.time()))
        ).fetchone()
    if row is None:
        raise HTTPException(401, "Login required or session expired")
    return dict(row)


@router.get("/{report_id}/photo")
def get_report_photo(report_id: int, user: dict = Depends(resolve_photo_user)):
    with connect() as db:
        row = accessible_report(db, report_id, user)
    photo_file = DATA_DIR / "photos" / row["photo_name"]
    if not photo_file.is_file():
        raise HTTPException(404, "Photo not found")
    return FileResponse(photo_file, media_type="image/png")


class Review(BaseModel):
    priority: Literal["low", "normal", "high", "urgent"]
    priority_reason: str = Field(min_length=1, max_length=1000)
    status: Literal["open", "in_progress", "resolved", "rejected"]
    duplicate_of: int | None = Field(default=None, gt=0)


@router.patch("/{report_id}")
def update_report_status(report_id: int, body: Review, user: dict = Depends(admin_user)):
    if not body.priority_reason.strip():
        raise HTTPException(400, "Explain the priority decision")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        accessible_report(db, report_id, user)
        if body.duplicate_of is not None:
            target = db.execute("SELECT * FROM reports WHERE id=?", (body.duplicate_of,)).fetchone()
            children = db.execute("SELECT 1 FROM reports WHERE duplicate_of=? LIMIT 1", (report_id,)).fetchone()
            if target is None or body.duplicate_of == report_id or target["duplicate_of"] is not None or children:
                raise HTTPException(400, "Choose a root report; duplicate chains and cycles are not allowed")

        db.execute(
            """UPDATE reports
            SET priority = ?, priority_reason = ?, status = ?, duplicate_of = ?
            WHERE id = ?""",
            (body.priority, body.priority_reason.strip(), body.status, body.duplicate_of, report_id)
        )
        updated = db.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        return serialize(updated)
