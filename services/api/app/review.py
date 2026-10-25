import hashlib
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid5

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import Connection, text

from app.domain.enums import ValidationDecision
from app.domain.geography import IssuePoint, assign_area
from app.domain.issue_locks import category_locks
from app.domain.issues import event, refresh_aggregates
from app.domain.validation import store_result
from app.intake import report_detail
from app.intake_schemas import Actor, ReportDetail
from app.jobs import enqueue
from app.schemas import Contract, ValidationResult


class ReviewDecision(Contract):
    expected_revision: int = Field(ge=1)
    request_id: UUID
    decision: Literal["accepted", "needs_review", "rejected"]
    category: str | None = Field(default=None, max_length=64)
    location: IssuePoint | None = None
    trusted_asset_id: UUID | None = None
    reason: str = Field(min_length=5, max_length=1000)


def decide(
    connection: Connection, report_id: UUID, actor: Actor, body: ReviewDecision
) -> ReportDetail:
    connection.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": int.from_bytes(body.request_id.bytes[:8], "big", signed=True)},
    )
    initial = (
        connection.execute(
            text("SELECT pilot_id,canonical_category,claimed_category FROM reports WHERE id=:id"),
            {"id": report_id},
        )
        .mappings()
        .one_or_none()
    )
    if initial is None:
        raise HTTPException(404, "Report not found")
    category_locks(
        connection,
        initial["pilot_id"],
        [
            initial["canonical_category"] or initial["claimed_category"],
            body.category or initial["claimed_category"],
        ],
    )
    row = (
        connection.execute(
            text("""
            SELECT *,ST_X(confirmed_point::geometry) AS lon,ST_Y(confirmed_point::geometry) AS lat
            FROM reports WHERE id=:id FOR UPDATE
        """),
            {"id": report_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or not actor.can_review(row["area_id"]):
        raise HTTPException(404, "Report not found in your review scope")
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    previous = (
        connection.execute(
            text("""
        SELECT * FROM audit_events WHERE request_id=:request AND operation='review_report'
    """),
            {"request": body.request_id},
        )
        .mappings()
        .one_or_none()
    )
    if previous:
        if (
            previous["actor_id"] != actor.id
            or previous["entity_id"] != report_id
            or previous["changes"]["request_hash"] != digest
        ):
            raise HTTPException(409, "Review request ID reused with a different decision")
        return report_detail(connection, report_id, actor)
    if row["content_revision"] != body.expected_revision:
        raise HTTPException(409, "Report changed. Reload before reviewing.")
    point = body.location or (
        IssuePoint(
            longitude=row["lon"],
            latitude=row["lat"],
            confirmed=True,
            uncertainty_m=row["location_accuracy_m"],
        )
        if row["lon"] is not None and row["lat"] is not None
        else IssuePoint.model_validate(row["location_evidence"].get("point", {}))
    )
    assignment = assign_area(connection, row["pilot_id"], point)
    if body.location is not None and not actor.can_review(assignment.area_id):
        raise HTTPException(403, "Location correction is outside your review scope")
    accepted = body.decision == "accepted"
    category = body.category if accepted else None
    if accepted and not category:
        raise HTTPException(422, "Accepted review requires a confirmed category")
    if (
        category
        and not connection.execute(
            text("SELECT active FROM categories WHERE code=:code"), {"code": category}
        ).scalar_one_or_none()
    ):
        raise HTTPException(422, "Choose an active confirmed category")
    if body.trusted_asset_id:
        asset = (
            connection.execute(
                text("""
          SELECT a.*,areas.pilot_id,
            ST_Distance(a.geom,ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography)
            AS distance_m FROM assets a JOIN areas ON areas.id=a.area_id WHERE a.id=:id
        """),
                {"id": body.trusted_asset_id, "lon": point.longitude, "lat": point.latitude},
            )
            .mappings()
            .one_or_none()
        )
        radius = connection.execute(
            text("SELECT duplicate_radius_m FROM categories WHERE code=:c"), {"c": category}
        ).scalar_one_or_none()
        if (
            not accepted
            or asset is None
            or asset["category_code"] != category
            or asset["pilot_id"] != row["pilot_id"]
            or not actor.can_review(asset["area_id"])
            or radius is None
            or asset["distance_m"] is None
            or asset["distance_m"] > radius
        ):
            raise HTTPException(422, "Trusted asset must match the confirmed category and location")
    linked = (
        connection.execute(
            text("""
      SELECT i.id,i.area_id FROM issues i JOIN issue_report_links l ON l.issue_id=i.id
      WHERE l.report_id=:id AND l.active ORDER BY i.id FOR UPDATE OF i
    """),
            {"id": report_id},
        )
        .mappings()
        .all()
    )
    for issue in linked:
        if not actor.can_review(issue["area_id"]):
            raise HTTPException(403, "Linked issue is outside your review scope")
        connection.execute(
            text("""UPDATE issue_report_links SET active=false,ended_at=now()
          WHERE report_id=:report AND issue_id=:issue AND active"""),
            {"report": report_id, "issue": issue["id"]},
        )
        event(
            connection,
            issue["id"],
            "report_reclassified",
            actor.id,
            body.reason,
            {"report_id": str(report_id), "previous_category": row["canonical_category"]},
        )
        refresh_aggregates(connection, issue["id"])
    revision = row["content_revision"] + 1
    photos = (
        connection.execute(
            text("SELECT * FROM media WHERE report_id=:id ORDER BY id"), {"id": report_id}
        )
        .mappings()
        .all()
    )
    if not photos:
        raise HTTPException(409, "Report has no evidence to review")
    state = (
        "out_of_scope"
        if assignment.state == "out_of_scope"
        else "rejected"
        if body.decision == "rejected"
        else "awaiting_review"
    )
    connection.execute(
        text("""
        UPDATE reports SET content_revision=:revision,canonical_category=:category,
          validation_status=:decision,validation_revision=:revision,review_reason=:reason,
          state=:state,area_id=:area,trusted_asset_id=:asset,
          confirmed_point=CASE WHEN CAST(:lon AS double precision) IS NULL
          OR CAST(:lat AS double precision) IS NULL THEN NULL
          ELSE ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography END,
          location_accuracy_m=:accuracy,updated_at=now() WHERE id=:id
    """),
        {
            "id": report_id,
            "revision": revision,
            "category": category,
            "decision": body.decision,
            "reason": body.reason,
            "state": state,
            "area": assignment.area_id,
            "asset": body.trusted_asset_id if accepted else None,
            "lon": point.longitude if point.confirmed else None,
            "lat": point.latitude if point.confirmed else None,
            "accuracy": point.uncertainty_m,
        },
    )
    for photo in photos:
        result = ValidationResult(
            report_id=report_id,
            media_id=photo["id"],
            report_revision=revision,
            media_sha256=photo["original_sha256"],
            request_id=uuid5(body.request_id, str(photo["id"])),
            provider="human_review",
            provider_version="review-policy-v1",
            decision=ValidationDecision(body.decision),
            labels=[{"label": category, "confidence": None}] if category else [],
            reviewer_id=actor.id,
            completed_at=datetime.now(UTC),
            reason=body.reason,
        )
        store_result(connection, result)
    connection.execute(
        text("""
        INSERT INTO location_decisions (report_id,submitted_point,approved_point,method,accuracy_m,
                                       reviewer_id,reason)
        SELECT id,confirmed_point,CASE WHEN :located THEN confirmed_point ELSE NULL END,
          'human_review',location_accuracy_m,:reviewer,:reason FROM reports WHERE id=:id
    """),
        {
            "id": report_id,
            "located": assignment.state == "located",
            "reviewer": actor.id,
            "reason": body.reason,
        },
    )
    connection.execute(
        text("""
        INSERT INTO audit_events (actor_id,entity_type,entity_id,operation,
                                 revision,request_id,changes)
        VALUES (:actor,'report',:id,'review_report',:revision,:request,CAST(:changes AS jsonb))
    """),
        {
            "actor": actor.id,
            "id": report_id,
            "revision": revision,
            "request": body.request_id,
            "changes": json.dumps(
                {
                    "decision": body.decision,
                    "category": category,
                    "reason": body.reason,
                    "request_hash": digest,
                    "previous_revision": row["content_revision"],
                }
            ),
        },
    )
    if accepted and assignment.state == "located":
        enqueue(connection, report_id, revision, "admit_report")
    return report_detail(connection, report_id, actor)
