"""Persistent complaints with image validation, safe pre-analysis storage, and YOLO detection."""
import io
import hashlib
import json
import logging
import math
import secrets
import time
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

_PIL_OPEN = Image.open  # Capture before the model's optional-format monkeypatch.
try:
    from backend.accounts import admin_user, current_user, bearer, effective_role
    from backend.database import DATA_DIR, connect
    from backend.grouping import fingerprints, assign_report, distance_metres, summary
except ImportError:
    from accounts import admin_user, current_user, bearer, effective_role
    from database import DATA_DIR, connect
    from grouping import fingerprints, assign_report, distance_metres, summary

router = APIRouter(prefix="/reports", tags=["Complaints"])
logger = logging.getLogger("uvicorn.error")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB max size
MAX_MEGAPIXELS = 24_000_000


def serialize(row, db=None, include_candidates=False) -> dict:
    report = dict(row)
    photo_name = report.pop("photo_name", "")
    result_raw = report.pop("result_json", None)
    report["analysis"] = json.loads(result_raw) if result_raw else None
    report["photo_url"] = f"/reports/{row['id']}/photo"
    for private_field in ("submission_key", "submission_digest", "image_sha256", "image_dhash"):
        report.pop(private_field, None)
    if db is not None and report.get("issue_id"):
        issue = summary(db, report["issue_id"])
        report["issue_summary"] = issue if include_candidates else {
            name: issue[name] for name in ("id", "report_count", "reporter_count", "unique_photo_count", "status")
        }
        if include_candidates:
            report["duplicate_candidates"] = [
                {"issue_id": candidate["issue_id"], "reason": candidate["reason"], "issue": summary(db, candidate["issue_id"])}
                for candidate in db.execute("SELECT * FROM duplicate_candidates WHERE report_id=?", (row["id"],))
            ]
    return report


def accessible_report(db, report_id: int, user: dict):
    if user["role"] == "nigam":
        raise HTTPException(403, "Municipal accounts access consolidated issues, not individual reports")
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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", min_length=1, max_length=128),
    user: dict = Depends(current_user)
):
    if user["role"] == "nigam":
        raise HTTPException(403, "Use a citizen account to submit reports")
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

    sha, dhash = fingerprints(canonical)
    submission_digest = hashlib.sha256(json.dumps([sha, description, latitude, longitude, issue_type]).encode()).hexdigest()
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
            if idempotency_key:
                previous = db.execute("SELECT * FROM reports WHERE user_id=? AND submission_key=?", (user["id"], idempotency_key)).fetchone()
                if previous:
                    photo_path.unlink(missing_ok=True)
                    if previous["submission_digest"] != submission_digest:
                        raise HTTPException(409, "Submission key was already used for a different report")
                    return serialize(previous, db)
            cursor = db.execute(
                """INSERT INTO reports
                (user_id, description, latitude, longitude, photo_name, created_at, issue_type,
                 image_sha256, image_dhash, submission_key, submission_digest)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user["id"], description, latitude, longitude, photo_name, now, issue_type, sha, dhash, idempotency_key, submission_digest)
            )
            report_id = cursor.lastrowid
            assign_report(db, report_id)
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
        return serialize(saved, db)


@router.get("")
def list_reports(
    limit: int = 50,
    offset: int = 0,
    user: dict = Depends(current_user)
):
    if user["role"] == "nigam":
        raise HTTPException(403, "Use the consolidated issues endpoint")
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
        return [serialize(row, db, user["role"] == "admin") for row in rows]


@router.get("/{report_id}")
def get_report(report_id: int, user: dict = Depends(current_user)):
    with connect() as db:
        return serialize(accessible_report(db, report_id, user), db, user["role"] == "admin")


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
        return {**dict(row), "role": effective_role(db, row)}


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
            raise HTTPException(400, "Use the dedicated grouping endpoint to change issue membership")

        db.execute(
            """UPDATE reports
            SET priority = ?, priority_reason = ?, status = ?
            WHERE id = ?""",
            (body.priority, body.priority_reason.strip(), body.status, report_id)
        )
        issue_id = db.execute("SELECT issue_id FROM reports WHERE id=?", (report_id,)).fetchone()["issue_id"]
        db.execute("UPDATE issues SET status=? WHERE id=?", (body.status, issue_id))
        db.execute("UPDATE reports SET status=? WHERE issue_id=?", (body.status, issue_id))
        updated = db.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        return serialize(updated, db, True)
