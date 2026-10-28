import asyncio
import json
from typing import Any
from uuid import UUID, uuid4, uuid5

from pydantic import ValidationError
from sqlalchemy import Connection, Engine, text

from app.adapters.interfaces import PhotoValidator
from app.adapters.validation import FixtureValidator, HumanDecisionRequired
from app.domain.geography import IssuePoint, assign_area
from app.domain.validation import mapped_category, store_result
from app.schemas import ValidationRequest, ValidationResult


def enqueue(
    connection: Connection, report_id: UUID, revision: int, job_type: str = "validate_report"
) -> None:
    connection.execute(
        text("""
        INSERT INTO jobs (type,payload,entity_revision,deduplication_key)
        VALUES (:type,CAST(:payload AS jsonb),:revision,:key)
        ON CONFLICT (deduplication_key) DO NOTHING
    """),
        {
            "type": job_type,
            "payload": json.dumps({"report_id": str(report_id)}),
            "revision": revision,
            "key": f"{job_type}:{report_id}:{revision}",
        },
    )


def claim(
    engine: Engine, worker_id: str, job_type: str = "validate_report"
) -> dict[str, Any] | None:
    with engine.begin() as connection:
        row = (
            connection.execute(
                text("""
            UPDATE jobs SET status='running',attempts=attempts+1,worker_id=:worker,
              lease_expires_at=now()+interval '30 seconds'
            WHERE id=(SELECT id FROM jobs WHERE type=:type AND next_run_at<=now()
              AND (status='pending' OR (status='running' AND lease_expires_at<now()))
              ORDER BY next_run_at,id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *
        """),
                {"worker": worker_id, "type": job_type},
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row else None


def process_once(
    engine: Engine, validator: PhotoValidator | None, worker_id: str | None = None
) -> bool:
    worker = worker_id or uuid4().hex
    job = claim(engine, worker)
    if job is None:
        from app.domain.issues import process_admission_once

        if process_admission_once(engine, worker):
            return True
        from app.domain.priority import process_priority_once

        return process_priority_once(engine, worker)
    report_id = UUID(job["payload"]["report_id"])
    try:
        with engine.begin() as connection:
            report = (
                connection.execute(
                    text("SELECT * FROM reports WHERE id=:id FOR UPDATE"), {"id": report_id}
                )
                .mappings()
                .one()
            )
            if report["content_revision"] != job["entity_revision"]:
                finish(connection, job["id"], worker)
                return True
            photos = (
                connection.execute(
                    text("SELECT * FROM media WHERE report_id=:id ORDER BY id"), {"id": report_id}
                )
                .mappings()
                .all()
            )
        # All adapter work happens after releasing the report/DB locks.
        results: list[ValidationResult] = []
        if validator is not None:
            if isinstance(validator, FixtureValidator) and not report["synthetic"]:
                raise ValueError("Non-synthetic reports cannot use fixture acceptance")
            for photo in photos:
                request = ValidationRequest(
                    report_id=report_id,
                    media_id=photo["id"],
                    report_revision=job["entity_revision"],
                    media_sha256=photo["original_sha256"],
                    request_id=uuid5(job["id"], f"{photo['id']}:{job['attempts']}"),
                )
                try:
                    result = asyncio.run(validator.validate(request))
                except HumanDecisionRequired:
                    results = []
                    validator = None
                    break
                if any(
                    getattr(result, name) != getattr(request, name)
                    for name in (
                        "report_id",
                        "media_id",
                        "report_revision",
                        "media_sha256",
                        "request_id",
                    )
                ):
                    raise ValueError("Validator returned mismatched evidence binding")
                results.append(result)
        with engine.begin() as connection:
            owned = connection.execute(
                text("""
                SELECT id FROM jobs WHERE id=:id AND worker_id=:worker AND status='running'
                  AND lease_expires_at>now() FOR UPDATE
            """),
                {"id": job["id"], "worker": worker},
            ).scalar_one_or_none()
            if owned is None:
                return True
            current = (
                connection.execute(
                    text("SELECT * FROM reports WHERE id=:id FOR UPDATE"), {"id": report_id}
                )
                .mappings()
                .one()
            )
            if current["content_revision"] != job["entity_revision"]:
                finish(connection, job["id"], worker)
                return True
            if any(not store_result(connection, result) for result in results):
                finish(connection, job["id"], worker)
                return True
            if any(result.decision == "error" for result in results):
                fail_job(connection, job, worker, "provider_error")
                return True
            category, reason = mapped_category(results, current["claimed_category"])
            is_suspicious = False
            suspicious_reason = None
            if results and any(r.labels for r in results):
                detected_labels = [label.label for r in results for label in r.labels]
                if reason == "claimed_category_conflict_or_manual_category" or (category is None and reason not in {"human_review_required", "photo_needs_review"}):
                    is_suspicious = True
                    suspicious_reason = f"Model detection mismatch: claimed '{current['claimed_category']}' but detector predicted '{', '.join(detected_labels)}'"
            elif any(r.provider == "model" and r.decision == "needs_review" for r in results):
                is_suspicious = True
                suspicious_reason = (
                    f"Photo does not appear to show the claimed '{current['claimed_category']}': "
                    "the detector found no pothole or waterlogging. Human review required."
                )
            if validator is None:
                reason = "human_review_required"
            point = IssuePoint.model_validate(current["location_evidence"].get("point", {}))
            location = assign_area(connection, current["pilot_id"], point)
            accepted = category is not None
            rejected = reason == "photo_rejected"
            status = "accepted" if accepted else "rejected" if rejected else "needs_review"
            state = (
                "out_of_scope"
                if location.state == "out_of_scope"
                else "rejected"
                if rejected
                else "awaiting_review"
            )
            if accepted and location.state != "located":
                reason = "visual_accepted_location_" + location.reason
            elif accepted:
                reason = "validated_awaiting_issue_review"
            connection.execute(
                text("""
                UPDATE reports SET canonical_category=:category,validation_status=:status,
                  validation_revision=content_revision,review_reason=:reason,state=:state,
                  is_suspicious=:is_suspicious,suspicious_reason=:suspicious_reason,updated_at=now()
                WHERE id=:id
            """),
                {
                    "id": report_id,
                    "category": category,
                    "status": status,
                    "state": state,
                    "reason": reason,
                    "is_suspicious": is_suspicious,
                    "suspicious_reason": suspicious_reason,
                },
            )
            if accepted and location.state == "located":
                enqueue(connection, report_id, current["content_revision"], "admit_report")
            finish(connection, job["id"], worker)
    except Exception as error:
        with engine.begin() as connection:
            fail_job(
                connection,
                job,
                worker,
                "invalid_provider_result"
                if isinstance(error, ValidationError)
                else "provider_unavailable",
            )
    return True


def finish(connection: Connection, job_id: UUID, worker: str) -> None:
    connection.execute(
        text("""
        UPDATE jobs SET status='completed',lease_expires_at=NULL,last_error=NULL
        WHERE id=:id AND worker_id=:worker AND status='running'
    """),
        {"id": job_id, "worker": worker},
    )


def fail_job(connection: Connection, job: dict[str, Any], worker: str, error: str) -> None:
    terminal = job["attempts"] >= 3
    owned = connection.execute(
        text("""
        UPDATE jobs SET status=:status,last_error=:error,lease_expires_at=NULL,
          next_run_at=now()+make_interval(secs=>:delay)
        WHERE id=:id AND worker_id=:worker AND status='running' AND lease_expires_at>now()
        RETURNING id
    """),
        {
            "id": job["id"],
            "worker": worker,
            "status": "failed" if terminal else "pending",
            "error": error,
            "delay": min(60, 2 ** job["attempts"]),
        },
    ).scalar_one_or_none()
    if owned is not None:
        connection.execute(
            text("""
            UPDATE reports SET state=:state,validation_status='error',
              review_reason='provider_error',
              updated_at=now() WHERE id=:id AND content_revision=:revision AND state<>'admitted'
        """),
            {
                "id": UUID(job["payload"]["report_id"]),
                "revision": job["entity_revision"],
                "state": "processing_failed" if terminal else "awaiting_review",
            },
        )
