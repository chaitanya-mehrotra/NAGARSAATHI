from typing import Any
from uuid import UUID

import yaml
from fastapi import HTTPException
from sqlalchemy import Connection, text

from app.schemas import ValidationResult
from app.settings import PROJECT_ROOT


def mapped_category(results: list[ValidationResult], claimed: str) -> tuple[str | None, str]:
    mapping = yaml.safe_load((PROJECT_ROOT / "config/label-mapping.yaml").read_text())["providers"]
    if not results or any(result.decision == "needs_review" for result in results):
        return None, "photo_needs_review"
    if any(result.decision == "error" for result in results):
        return None, "provider_error"
    if any(result.decision == "rejected" for result in results):
        return None, "photo_rejected" if all(
            r.decision == "rejected" for r in results
        ) else "contradictory_photos"
    categories: set[str] = set()
    for result in results:
        aliases = mapping.get(result.provider_version, {})
        if not result.labels:
            return None, "missing_label"
        for label in result.labels:
            category = aliases.get(label.label)
            if category is None:
                return None, "unknown_label_or_provider_version"
            categories.add(category)
    if len(categories) != 1:
        return None, "contradictory_photos"
    category = categories.pop()
    if category != claimed or category == "other_civic_issue":
        return None, "claimed_category_conflict_or_manual_category"
    return category, "visual_evidence_accepted"


def store_result(connection: Connection, result: ValidationResult) -> bool:
    """Caller holds the report lock. Ignore stale callbacks; never approve replaced media."""
    current = (
        connection.execute(
            text("""
        SELECT r.content_revision,m.original_sha256 FROM reports r JOIN media m ON m.report_id=r.id
        WHERE r.id=:report AND m.id=:media AND m.processing_state='ready'
    """),
            {"report": result.report_id, "media": result.media_id},
        )
        .mappings()
        .one_or_none()
    )
    if (
        current is None
        or current["content_revision"] != result.report_revision
        or current["original_sha256"] != result.media_sha256
    ):
        return False
    existing = (
        connection.execute(
            text("SELECT * FROM validation_results WHERE request_id=:id"), {"id": result.request_id}
        )
        .mappings()
        .one_or_none()
    )
    if existing:
        if (
            existing["report_id"] != result.report_id
            or existing["media_id"] != result.media_id
            or existing["media_sha256"] != result.media_sha256
            or existing["report_revision"] != result.report_revision
            or existing["decision"] != result.decision
            or existing["provider"] != result.provider
            or existing["provider_version"] != result.provider_version
            or existing["reviewer_id"] != result.reviewer_id
            or existing["reason"] != result.reason
            or existing["labels"] != [item.model_dump() for item in result.labels]
        ):
            raise HTTPException(409, "Validation request ID already has a different result")
        return True
    import json

    connection.execute(
        text("""
        INSERT INTO validation_results (report_id,media_id,report_revision,media_sha256,
            provider,provider_version,decision,labels,confidence,reviewer_id,request_id,completed_at,reason)
        VALUES (:report,:media,:revision,:hash,:provider,:version,:decision,CAST(:labels AS jsonb),
                NULL,:reviewer,:request,:completed,:reason)
    """),
        {
            "report": result.report_id,
            "media": result.media_id,
            "revision": result.report_revision,
            "hash": result.media_sha256,
            "provider": result.provider,
            "version": result.provider_version,
            "decision": result.decision,
            "labels": json.dumps([item.model_dump() for item in result.labels]),
            "reviewer": result.reviewer_id,
            "request": result.request_id,
            "completed": result.completed_at,
            "reason": result.reason,
        },
    )
    return True


def current_results(connection: Connection, report_id: UUID, revision: int) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            text("""
        SELECT DISTINCT ON (media_id) * FROM validation_results
        WHERE report_id=:id AND report_revision=:revision
        ORDER BY media_id,completed_at DESC,id DESC
    """),
            {"id": report_id, "revision": revision},
        )
        .mappings()
        .all()
    ]
