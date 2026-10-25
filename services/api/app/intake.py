import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import Connection, text

from app.adapters.local_media import LocalMedia
from app.domain.geography import IssuePoint, assign_area
from app.intake_schemas import Actor, MediaSummary, ReportDetail, ReportSubmission, UploadReceipt
from app.jobs import enqueue
from app.settings import Settings


def upload_receipt(row: Any) -> UploadReceipt:
    return UploadReceipt(
        id=row["id"],
        state=row["processing_state"],
        expires_at=row["expires_at"],
        sha256=row["original_sha256"],
        byte_size=row["byte_size"],
        width=row["width"],
        height=row["height"],
    )


def verify_stored_media(storage: LocalMedia, row: Any) -> bytes:
    try:
        original = storage.read(row["storage_key"])
        display = storage.read(row["derivative_key"])
    except (OSError, ValueError) as error:
        raise HTTPException(503, "Photo storage is temporarily unavailable") from error
    if (
        hashlib.sha256(original).hexdigest() != row["original_sha256"]
        or hashlib.sha256(display).hexdigest() != row["derivative_sha256"]
    ):
        raise HTTPException(503, "Stored photo integrity check failed")
    return original


def report_detail(connection: Connection, report_id: UUID, actor: Actor) -> ReportDetail:
    row = (
        connection.execute(
            text("""
        SELECT r.*, a.code AS area_code,ST_X(confirmed_point::geometry) AS lon,
          ST_Y(confirmed_point::geometry) AS lat FROM reports r
        LEFT JOIN areas a ON a.id=r.area_id WHERE r.id=:id
    """),
            {"id": report_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or (row["reporter_id"] != actor.id and not actor.can_review(row["area_id"])):
        raise HTTPException(404, "Report not found")
    media = (
        connection.execute(
            text("""
        SELECT id,width,height,byte_size,original_sha256 AS sha256 FROM media
        WHERE report_id=:id ORDER BY created_at,id
    """),
            {"id": report_id},
        )
        .mappings()
        .all()
    )
    evidence = row["location_evidence"]
    issue = (
        connection.execute(
            text("""
        SELECT i.id,i.public_reference,i.status,l.method FROM issues i
        JOIN issue_report_links l ON l.issue_id=i.id WHERE l.report_id=:report AND l.active
    """),
            {"report": report_id},
        )
        .mappings()
        .one_or_none()
    )
    return ReportDetail(
        id=row["id"],
        public_reference=row["public_reference"],
        description=row["description"],
        claimed_category=row["claimed_category"],
        canonical_category=row["canonical_category"],
        state=row["state"],
        location=evidence.get("point", {}),
        location_source=row["location_source"] or "unknown",
        location_reason=evidence.get("reason", "location_not_recorded"),
        address_text=row["address_text"],
        area_code=row["area_code"],
        boundary_version=row["boundary_version"],
        received_at=row["received_at"],
        content_revision=row["content_revision"],
        synthetic=row["synthetic"],
        media=[
            MediaSummary(**dict(item), content_url=f"/api/v1/media/{item['id']}/content")
            for item in media
        ],
        validation_status=row["validation_status"],
        issue_id=issue["id"] if issue else None,
        issue_reference=issue["public_reference"] if issue else None,
        issue_status=issue["status"] if issue else None,
        link_method=issue["method"] if issue else None,
        trusted_asset_id=row["trusted_asset_id"],
        evidence_reused=row["evidence_reused"],
        reported_hazard=evidence.get("reported_hazard", False),
        review_reason=row["review_reason"],
        canonical_location=IssuePoint(longitude=row["lon"], latitude=row["lat"], confirmed=True)
        if row["area_id"] is not None
        else None,
    )


def submit_report(
    connection: Connection,
    actor: Actor,
    submission: ReportSubmission,
    key: str,
    settings: Settings,
    storage: LocalMedia,
) -> ReportDetail:
    digest = hashlib.sha256(
        json.dumps(
            submission.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    # Serialize retries of one principal/key; different keys still lock shared media below.
    lock = int.from_bytes(
        hashlib.sha256(f"{actor.id}:submit:{key}".encode()).digest()[:8],
        byteorder="big",
        signed=True,
    )
    connection.execute(text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": lock})
    existing = (
        connection.execute(
            text("""
        SELECT request_body_hash,resource_id FROM idempotency_records
        WHERE principal_id=:user AND operation='submit_report' AND key=:key
    """),
            {"user": actor.id, "key": key},
        )
        .mappings()
        .one_or_none()
    )
    if existing:
        if existing["request_body_hash"] != digest:
            raise HTTPException(409, "Idempotency key was already used with a different submission")
        return report_detail(connection, existing["resource_id"], actor)
    if not connection.execute(
        text("SELECT active FROM categories WHERE code=:code"),
        {"code": submission.claimed_category},
    ).scalar_one_or_none():
        raise HTTPException(422, "Choose an active category")
    media = (
        connection.execute(
            text("""
        SELECT * FROM media WHERE id=ANY(:ids) ORDER BY id FOR UPDATE
    """),
            {"ids": sorted(submission.media_ids)},
        )
        .mappings()
        .all()
    )
    if len(media) != len(submission.media_ids) or any(row["owner_id"] != actor.id for row in media):
        raise HTTPException(404, "Photo not found")
    for row in media:
        if row["report_id"] is not None or row["repair_issue_id"] is not None:
            raise HTTPException(409, "Photo is already attached to a report")
        if row["processing_state"] != "ready" or row["completed_at"] is None:
            raise HTTPException(409, "Complete the upload before submitting")
        if row["expires_at"] <= datetime.now(UTC):
            raise HTTPException(410, "Upload expired; upload the photo again")
        verify_stored_media(storage, row)
    if sum(row["byte_size"] for row in media) > settings.report_max_bytes:
        raise HTTPException(413, "Combined photos exceed the report byte limit")
    pilots = (
        connection.execute(
            text("""
        SELECT id,boundary_version,synthetic FROM pilots WHERE code=:code AND enabled
        ORDER BY boundary_version
    """),
            {"code": settings.pilot_code},
        )
        .mappings()
        .all()
    )
    if len(pilots) != 1:
        raise HTTPException(503, "Exactly one reviewed demo pilot version must be enabled")
    pilot = pilots[0]
    assignment = assign_area(connection, pilot["id"], submission.location)
    state = {
        "located": "submitted",
        "needs_review": "awaiting_review",
        "out_of_scope": "out_of_scope",
    }[assignment.state]
    report_id = uuid4()
    point = submission.location
    params = {
        "id": report_id,
        "reference": "NS-" + report_id.hex.upper(),
        "user": actor.id,
        "description": submission.description,
        "category": submission.claimed_category,
        "language": submission.language_hint,
        "state": state,
        "lon": point.longitude if point.confirmed else None,
        "lat": point.latitude if point.confirmed else None,
        "accuracy": point.uncertainty_m,
        "source": submission.location_source,
        "address": submission.address_text,
        "area": assignment.area_id,
        "version": pilot["boundary_version"],
        "pilot": pilot["id"],
        "synthetic": actor.synthetic or pilot["synthetic"],
        "evidence": json.dumps(
            {
                "point": point.model_dump(),
                "reason": assignment.reason,
                "reported_hazard": submission.reported_hazard,
                "suggested_issue_id": str(submission.suggested_issue_id)
                if submission.suggested_issue_id
                else None,
            }
        ),
    }
    connection.execute(
        text("""
        INSERT INTO reports (id,public_reference,reporter_id,description,claimed_category,
          language_hint,state,confirmed_point,location_accuracy_m,location_source,address_text,
          area_id,boundary_version,pilot_id,synthetic,location_evidence)
        VALUES (:id,:reference,:user,:description,:category,:language,:state,
          CASE WHEN CAST(:lon AS double precision) IS NULL
                 OR CAST(:lat AS double precision) IS NULL THEN NULL
               ELSE ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography END,
          :accuracy,:source,:address,:area,:version,:pilot,:synthetic,CAST(:evidence AS jsonb))
    """),
        params,
    )
    connection.execute(
        text("UPDATE media SET report_id=:report WHERE id=ANY(:ids)"),
        {"report": report_id, "ids": submission.media_ids},
    )
    connection.execute(
        text("""
        INSERT INTO location_decisions (report_id,submitted_point,method,accuracy_m,reason)
        SELECT id,confirmed_point,'submission',location_accuracy_m,:reason
        FROM reports WHERE id=:report
    """),
        {"report": report_id, "reason": assignment.reason},
    )
    connection.execute(
        text("""
        INSERT INTO idempotency_records (principal_id,operation,key,request_body_hash,resource_id)
        VALUES (:user,'submit_report',:key,:digest,:report)
    """),
        {"user": actor.id, "key": key, "digest": digest, "report": report_id},
    )
    enqueue(connection, report_id, 1)
    return report_detail(connection, report_id, actor)
