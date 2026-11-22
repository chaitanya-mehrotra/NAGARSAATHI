"""Read-only history: a per-report timeline for the owner/staff and an admin audit log."""

import csv
import io
import json
from datetime import date, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import text

from app.domain.enums import Role
from app.routes.auth_routes import CurrentActor

router = APIRouter(prefix="/api/v1", tags=["Audit"])

# What a citizen may see of their own report's history: the step and the resulting state only.
# Staff notes, reviewer identities, model labels and moderation reasons never leave the staff views.
CITIZEN_ACTIONS = {
    "report_submitted", "photo_checked", "photo_reviewed", "review_report", "status_override",
}
# Issue lifecycle steps of the repair task the report supports.
CITIZEN_ISSUE_ACTIONS = {
    "created", "assigned", "start", "submit_repair", "verify", "reject", "reopen", "archive",
    "status_changed",
}

COLUMNS = (
    "occurred_at, source, actor_id, actor_name, action, report_id, issue_id, "
    "from_state, to_state, reason, details"
)


def _is_staff(actor: Any) -> bool:
    return actor.has_role(Role.ADMIN) or actor.has_role(Role.NIGAM) or actor.has_role(Role.REVIEWER)


def _is_admin(actor: Any) -> bool:
    return actor.has_role(Role.ADMIN) or actor.has_role(Role.NIGAM)


def _day(value: str, field: str) -> date | None:
    if not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise HTTPException(422, f"{field} must be a date like 2026-10-29") from None


def _row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for key in ("actor_id", "report_id", "issue_id"):
        out[key] = str(out[key]) if out[key] else None
    out["occurred_at"] = out["occurred_at"].isoformat()
    return out


def _citizen_row(row: dict[str, Any]) -> dict[str, Any]:
    state = row["to_state"]
    return {
        "occurred_at": row["occurred_at"].isoformat(),
        "action": row["action"],
        "to_state": state,
    }


@router.get("/reports/{report_id}/history")
def report_history(report_id: UUID, request: Request, actor: CurrentActor) -> dict[str, Any]:
    """Oldest-first timeline of one report, including the lifecycle of the issue it supports."""
    staff = _is_staff(actor)
    with request.app.state.engine.connect() as connection:
        report = connection.execute(
            text("SELECT reporter_id, deleted_at FROM reports WHERE id=:id"), {"id": report_id}
        ).mappings().one_or_none()
        # A citizen asking about someone else's report gets the same answer as for a missing one.
        if report is None or (not staff and report["reporter_id"] != actor.id):
            raise HTTPException(404, "Report not found")
        if report["deleted_at"] is not None and not staff:
            raise HTTPException(404, "Report not found")
        rows = connection.execute(
            text(f"""
                SELECT {COLUMNS} FROM (
                    SELECT l.*, u.display_name AS actor_name FROM audit_log l
                    LEFT JOIN users u ON u.id = l.actor_id
                    WHERE l.report_id = :id
                       OR (l.source = 'issue' AND l.issue_id IN (
                            SELECT issue_id FROM issue_report_links WHERE report_id = :id))
                ) t ORDER BY occurred_at, action
            """),
            {"id": report_id},
        ).mappings().all()
    if staff:
        return {"report_id": str(report_id), "events": [_row(dict(r)) for r in rows]}
    visible = [
        _citizen_row(dict(r))
        for r in rows
        if (r["source"] == "issue" and r["action"] in CITIZEN_ISSUE_ACTIONS)
        or (r["source"] != "issue" and r["action"] in CITIZEN_ACTIONS)
    ]
    return {"report_id": str(report_id), "events": visible}


def _filters(
    actor_id: str, action: str, source: str, report_id: str, since: str, until: str
) -> tuple[str, dict[str, Any]]:
    conditions = ["TRUE"]
    params: dict[str, Any] = {}
    if action.strip():
        conditions.append("l.action = :action")
        params["action"] = action.strip()
    if source.strip():
        conditions.append("l.source = :source")
        params["source"] = source.strip()
    if actor_id.strip():
        try:
            params["actor_id"] = UUID(actor_id.strip())
        except ValueError:
            raise HTTPException(422, "actor_id must be a UUID") from None
        conditions.append("l.actor_id = :actor_id")
    if report_id.strip():
        try:
            params["report_id"] = UUID(report_id.strip())
        except ValueError:
            raise HTTPException(422, "report_id must be a UUID") from None
        conditions.append("l.report_id = :report_id")
    first, last = _day(since, "since"), _day(until, "until")
    if first:
        conditions.append("l.occurred_at >= (CAST(:since AS date)::timestamp AT TIME ZONE 'Asia/Kolkata')")
        params["since"] = first
    if last:
        # Inclusive of the whole last day in the pilot's local time.
        conditions.append("l.occurred_at < (CAST(:until AS date)::timestamp AT TIME ZONE 'Asia/Kolkata')")
        params["until"] = last + timedelta(days=1)
    return " AND ".join(conditions), params


@router.get("/audit")
def audit_log(
    request: Request,
    actor: CurrentActor,
    actor_id: str = "",
    action: str = "",
    source: str = "",
    report_id: str = "",
    since: str = "",
    until: str = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: str = "",
) -> dict[str, Any]:
    """Newest-first audit log for administrators. `before` is the previous page's `next_before`."""
    if not _is_admin(actor):
        raise HTTPException(403, "Administrator permission required")
    where, params = _filters(actor_id, action, source, report_id, since, until)
    if before.strip():
        try:
            params["before"] = datetime.fromisoformat(before.strip())
        except ValueError:
            raise HTTPException(422, "before must be an ISO timestamp") from None
        where += " AND l.occurred_at < :before"
    params["limit"] = limit + 1
    with request.app.state.engine.connect() as connection:
        rows = connection.execute(
            text(f"""
                SELECT l.occurred_at, l.source, l.actor_id, u.display_name AS actor_name, l.action,
                       l.report_id, l.issue_id, l.from_state, l.to_state, l.reason, l.details
                FROM audit_log l LEFT JOIN users u ON u.id = l.actor_id
                WHERE {where} ORDER BY l.occurred_at DESC LIMIT :limit
            """),
            params,
        ).mappings().all()
    page = [_row(dict(r)) for r in rows[:limit]]
    return {
        "events": page,
        "next_before": page[-1]["occurred_at"] if len(rows) > limit and page else None,
    }


def _safe_cell(value: Any) -> str:
    cell = "" if value is None else str(value)
    # Spreadsheet programs run cells that start with these characters as formulas.
    return "'" + cell if cell[:1] in {"=", "+", "-", "@", "\t", "\r"} else cell


@router.get("/audit/export.csv")
def audit_export(
    request: Request,
    actor: CurrentActor,
    actor_id: str = "",
    action: str = "",
    source: str = "",
    report_id: str = "",
    since: str = "",
    until: str = "",
) -> Response:
    if not _is_admin(actor):
        raise HTTPException(403, "Administrator permission required")
    where, params = _filters(actor_id, action, source, report_id, since, until)
    with request.app.state.engine.connect() as connection:
        rows = connection.execute(
            text(f"""
                SELECT l.occurred_at, l.source, u.display_name AS actor_name, l.action,
                       l.report_id, l.issue_id, l.from_state, l.to_state, l.reason, l.details
                FROM audit_log l LEFT JOIN users u ON u.id = l.actor_id
                WHERE {where} ORDER BY l.occurred_at DESC LIMIT 20000
            """),
            params,
        ).mappings().all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    header = ["occurred_at", "source", "actor", "action", "report_id", "issue_id",
              "from_state", "to_state", "reason", "details"]
    writer.writerow(header)
    for r in rows:
        writer.writerow(
            [_safe_cell(v) for v in (
                r["occurred_at"].isoformat(), r["source"], r["actor_name"], r["action"],
                r["report_id"], r["issue_id"], r["from_state"], r["to_state"], r["reason"],
                json.dumps(r["details"], ensure_ascii=False) if r["details"] else None,
            )]
        )
    return Response(
        buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'},
    )
