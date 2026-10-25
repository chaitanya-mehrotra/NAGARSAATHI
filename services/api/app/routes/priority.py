import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import text

from app.domain.enums import Role
from app.domain.issue_locks import priority_lock
from app.domain.issues import event, summary
from app.domain.priority import (
    ACTIVE_SQL,
    activate,
    active_epoch,
    epoch,
    policy_from,
    preview,
    queue_refresh,
    refresh,
)
from app.intake import report_detail
from app.intake_schemas import ReportDetail
from app.issue_schemas import IssueSummary
from app.priority_schemas import ActivateEpoch, PolicyPreview, PriorityDecision
from app.routes.intake import CurrentActor
from app.routes.issues import staff

router = APIRouter(prefix="/api/v1/priority")


def global_admin(actor: CurrentActor) -> None:
    if not any(g.role == Role.ADMIN and g.area_id is None for g in actor.grants):
        raise HTTPException(403, "Global administrator permission is required")


@router.get("/ranking", response_model=list[IssueSummary])
def ranking(
    request: Request,
    actor: CurrentActor,
    area: str | None = None,
    category: str | None = None,
    overdue: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[IssueSummary]:
    staff(actor)
    grants = [g for g in actor.grants if g.role in {Role.REVIEWER, Role.ADMIN}]
    with (
        request.app.state.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection,
        connection.begin(),
    ):
        rows = (
            connection.execute(
                text(
                    f"""
          SELECT i.id FROM issues i JOIN areas a ON a.id=i.area_id
          JOIN priority_epochs e ON e.pilot_id=i.pilot_id AND e.state='active'
          JOIN priority_policies e_policy ON e_policy.id=e.policy_id
          LEFT JOIN priority_snapshots s ON s.id=i.current_priority_snapshot_id AND s.epoch_id=e.id
          WHERE i.status IN {ACTIVE_SQL} AND i.report_count>0
            AND (:global OR i.area_id=ANY(CAST(:areas AS uuid[])))
            AND (CAST(:area AS text) IS NULL OR a.code=:area)
            AND (CAST(:category AS text) IS NULL OR i.category_code=:category)
            AND (NOT :overdue OR i.first_accepted_at<=now()-make_interval(secs=>
                 (e_policy.category_parameters->i.category_code->>'target_hours')
                    ::double precision*3600))
          ORDER BY i.critical_override DESC,s.score DESC NULLS LAST,i.first_accepted_at,i.id
          LIMIT :limit
        """
                ),
                {
                    "global": any(g.area_id is None for g in grants),
                    "areas": [g.area_id for g in grants if g.area_id],
                    "area": area,
                    "category": category,
                    "overdue": overdue,
                    "limit": limit,
                },
            )
            .scalars()
            .all()
        )
        return [summary(connection, item) for item in rows]


@router.get("/rapid-review", response_model=list[ReportDetail])
def rapid_review(request: Request, actor: CurrentActor) -> list[ReportDetail]:
    staff(actor)
    grants = [g for g in actor.grants if g.role in {Role.REVIEWER, Role.ADMIN}]
    with request.app.state.engine.connect() as connection:
        ids = (
            connection.execute(
                text("""
          SELECT r.id FROM reports r LEFT JOIN issue_report_links l ON l.report_id=r.id AND l.active
          LEFT JOIN issues i ON i.id=l.issue_id
          WHERE ((r.location_evidence->>'reported_hazard'='true' AND i.urgency_override IS NULL)
                 OR (i.critical_override AND i.critical_review_due_at<=now()))
            AND r.state NOT IN ('rejected','out_of_scope')
            AND (:global OR r.area_id=ANY(CAST(:areas AS uuid[])))
          ORDER BY r.received_at,r.id LIMIT 50
        """),
                {
                    "global": any(g.area_id is None for g in grants),
                    "areas": [g.area_id for g in grants if g.area_id],
                },
            )
            .scalars()
            .all()
        )
        return [report_detail(connection, item, actor) for item in ids]


@router.post("/issues/{issue_id}/decision", response_model=IssueSummary)
def decision(
    issue_id: UUID, body: PriorityDecision, request: Request, actor: CurrentActor
) -> IssueSummary:
    staff(actor)
    with request.app.state.engine.begin() as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": int.from_bytes(body.request_id.bytes[:8], "big", signed=True)},
        )
        initial = (
            connection.execute(text("SELECT * FROM issues WHERE id=:id"), {"id": issue_id})
            .mappings()
            .one_or_none()
        )
        if initial is None or not actor.can_review(initial["area_id"]):
            raise HTTPException(404, "Issue outside your review scope")
        priority_lock(connection, initial["pilot_id"])
        issue = (
            connection.execute(
                text("SELECT * FROM issues WHERE id=:id FOR UPDATE"), {"id": issue_id}
            )
            .mappings()
            .one()
        )
        digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
        old = (
            connection.execute(
                text("SELECT * FROM audit_events WHERE request_id=:id"), {"id": body.request_id}
            )
            .mappings()
            .one_or_none()
        )
        if old:
            if (
                old["actor_id"] != actor.id
                or old["entity_id"] != issue_id
                or (old["changes"].get("request_hash") != digest)
            ):
                raise HTTPException(409, "Request ID reused with a different decision")
            return summary(connection, issue_id)
        if issue["row_version"] != body.expected_version:
            raise HTTPException(409, "Issue changed. Reload before reviewing priority.")
        if issue["status"] not in {
            "open",
            "assigned",
            "in_progress",
            "resolution_pending",
            "reopened",
        }:
            raise HTTPException(409, "Priority decisions require an active issue")
        if body.critical_override and (
            body.critical_review_due_at is None or body.critical_review_due_at <= datetime.now(UTC)
        ):
            raise HTTPException(422, "Choose a future critical review deadline")
        connection.execute(
            text("""
          UPDATE issues SET severity_override=:severity,urgency_override=:urgency,
            critical_override=:critical,critical_review_due_at=:due,
            row_version=row_version+1,updated_at=now() WHERE id=:id
        """),
            {
                "id": issue_id,
                "severity": body.severity_override,
                "urgency": body.urgency_override,
                "critical": body.critical_override,
                "due": body.critical_review_due_at if body.critical_override else None,
            },
        )
        event(
            connection,
            issue_id,
            "priority_reviewed",
            actor.id,
            body.reason,
            body.model_dump(mode="json"),
        )
        connection.execute(
            text("""
          INSERT INTO audit_events(actor_id,entity_type,entity_id,operation,revision,
                                   request_id,changes)
          VALUES(:actor,'issue',:issue,'review_priority',:revision,:request,CAST(:changes AS jsonb))
        """),
            {
                "actor": actor.id,
                "issue": issue_id,
                "revision": body.expected_version + 1,
                "request": body.request_id,
                "changes": json.dumps(
                    {"request_hash": digest, "decision": body.model_dump(mode="json")}
                ),
            },
        )
        updated = (
            connection.execute(text("SELECT * FROM issues WHERE id=:id"), {"id": issue_id})
            .mappings()
            .one()
        )
        queue_refresh(connection, updated)
        refresh(connection, issue_id, updated["row_version"])
        return summary(connection, issue_id)


@router.get("/policies")
def policies(request: Request, actor: CurrentActor) -> list[dict[str, Any]]:
    global_admin(actor)
    with request.app.state.engine.connect() as connection:
        rows = (
            connection.execute(
                text("""
          SELECT e.*,p.version,poi.version AS poi_version FROM priority_epochs e
          JOIN priority_policies p ON p.id=e.policy_id
          JOIN poi_snapshots poi ON poi.id=e.poi_snapshot_id
          ORDER BY e.created_at DESC LIMIT 50
        """)
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows]


@router.post("/policies/preview")
def preview_policy(body: PolicyPreview, request: Request, actor: CurrentActor) -> dict[str, Any]:
    global_admin(actor)
    now = datetime.now(UTC)
    if abs((body.as_of - now).total_seconds()) > timedelta(days=1).total_seconds():
        raise HTTPException(422, "Preview time must be within one day of server time")
    with request.app.state.engine.begin() as connection:
        if not connection.execute(
            text("SELECT id FROM pilots WHERE id=:id"), {"id": body.pilot_id}
        ).scalar_one_or_none():
            raise HTTPException(422, "Unknown pilot")
        if not connection.execute(
            text("SELECT id FROM poi_snapshots WHERE id=:id"), {"id": body.poi_snapshot_id}
        ).scalar_one_or_none():
            raise HTTPException(422, "Unknown versioned POI snapshot")
        new = preview(
            connection,
            body.pilot_id,
            body.policy,
            body.poi_snapshot_id,
            body.as_of,
            actor.id,
            body.reason,
        )
        return {"id": new}


@router.get("/policies/{epoch_id}")
def policy_detail(epoch_id: UUID, request: Request, actor: CurrentActor) -> dict[str, Any]:
    global_admin(actor)
    with request.app.state.engine.connect() as connection:
        if (
            connection.execute(
                text("SELECT id FROM priority_epochs WHERE id=:id"), {"id": epoch_id}
            ).scalar_one_or_none()
            is None
        ):
            raise HTTPException(404, "Epoch not found")
        proposed = epoch(connection, epoch_id)
        rows = (
            connection.execute(
                text("""
          SELECT DISTINCT ON (s.issue_id) s.issue_id,s.score,s.band,s.missing_data_flags,
                 i.public_reference,i.category_code,i.first_accepted_at FROM priority_snapshots s
          JOIN issues i ON i.id=s.issue_id WHERE s.epoch_id=:id
          ORDER BY s.issue_id,s.computed_at DESC,s.id
        """),
                {"id": epoch_id},
            )
            .mappings()
            .all()
        )
        current = active_epoch(connection, proposed["pilot_id"])
        return {
            "epoch": dict(proposed),
            "policy": policy_from(proposed).model_dump(),
            "active_epoch_id": current["id"] if current else None,
            "scores": sorted(
                [dict(r) for r in rows],
                key=lambda r: (
                    r["band"] != "critical",
                    -r["score"],
                    r["first_accepted_at"],
                    str(r["issue_id"]),
                ),
            ),
        }


@router.post("/policies/{epoch_id}/activate")
def activate_policy(
    epoch_id: UUID, body: ActivateEpoch, request: Request, actor: CurrentActor
) -> dict[str, Any]:
    global_admin(actor)
    with request.app.state.engine.begin() as connection:
        if (
            connection.execute(
                text("SELECT id FROM priority_epochs WHERE id=:id"), {"id": epoch_id}
            ).scalar_one_or_none()
            is None
        ):
            raise HTTPException(404, "Epoch not found")
        activate(connection, epoch_id, body.expected_active_epoch_id, actor.id, body.reason)
        return {"id": epoch_id, "state": "active"}
