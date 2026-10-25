import hashlib
import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import Connection, text

from app.domain.geography import assign_area
from app.domain.issue_locks import category_locks
from app.domain.issues import (
    ACTIVE,
    candidates,
    event,
    hold,
    link,
    new_issue,
    refresh_aggregates,
    report_locked,
    summary,
)
from app.intake_schemas import Actor
from app.issue_schemas import IssueSummary, LinkDecision, MergeDecision, SplitDecision


def action_lock(connection: Connection, request: UUID) -> None:
    connection.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": int.from_bytes(request.bytes[:8], "big", signed=True)},
    )


def replay(
    connection: Connection, actor: Actor, entity: UUID, operation: str, body: Any
) -> UUID | None:
    old = (
        connection.execute(
            text("SELECT * FROM audit_events WHERE request_id=:id AND operation=:operation"),
            {"id": body.request_id, "operation": operation},
        )
        .mappings()
        .one_or_none()
    )
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    if old:
        if (
            old["actor_id"] != actor.id
            or old["entity_id"] != entity
            or old["changes"]["request_hash"] != digest
        ):
            raise HTTPException(409, "Request ID was reused with different content")
        return UUID(old["changes"]["result_id"])
    return None


def audit(
    connection: Connection,
    actor: Actor,
    entity: UUID,
    operation: str,
    body: Any,
    result: UUID,
    revision: int,
) -> None:
    connection.execute(
        text("""
      INSERT INTO audit_events(actor_id,entity_type,entity_id,operation,revision,request_id,changes)
      VALUES (:actor,'issue',:entity,:operation,:revision,:request,CAST(:changes AS jsonb))
    """),
        {
            "actor": actor.id,
            "entity": entity,
            "operation": operation,
            "revision": revision,
            "request": body.request_id,
            "changes": json.dumps(
                {
                    "reason": body.reason,
                    "request_hash": hashlib.sha256(body.model_dump_json().encode()).hexdigest(),
                    "result_id": str(result),
                }
            ),
        },
    )


def scope(actor: Actor, row: Any) -> None:
    if not actor.can_review(row["area_id"]):
        raise HTTPException(404, "Issue outside your review scope")


def link_decision(
    connection: Connection, report_id: UUID, actor: Actor, body: LinkDecision
) -> UUID:
    action_lock(connection, body.request_id)
    initial = (
        connection.execute(text("SELECT * FROM reports WHERE id=:id"), {"id": report_id})
        .mappings()
        .one_or_none()
    )
    if initial is None or not actor.can_review(initial["area_id"]):
        raise HTTPException(404, "Report outside your review scope")
    category_locks(
        connection,
        initial["pilot_id"],
        [initial["canonical_category"] or initial["claimed_category"]],
    )
    report = report_locked(connection, report_id)
    old = replay(connection, actor, report_id, "duplicate_decision", body)
    if old:
        return old
    if report["content_revision"] != body.expected_revision or report["state"] == "admitted":
        raise HTTPException(409, "Report changed or is already linked. Reload before deciding.")
    if body.action == "clarify":
        hold(connection, report_id, body.reason)
        connection.execute(
            text("""UPDATE reports SET validation_status='needs_review',
          content_revision=content_revision+1 WHERE id=:id"""),
            {"id": report_id},
        )
        audit(
            connection,
            actor,
            report_id,
            "duplicate_decision",
            body,
            report_id,
            report["content_revision"] + 1,
        )
        return report_id
    if (
        report["validation_status"] != "accepted"
        or report["validation_revision"] != report["content_revision"]
        or report["canonical_category"] is None
        or report["area_id"] is None
    ):
        raise HTTPException(409, "Confirm current evidence, category and location first")
    if any(
        not actor.can_review(row["area_id"]) and not row["asset_conflict"]
        for row in candidates(connection, report)
    ):
        raise HTTPException(403, "Review requires permission over both candidate areas")
    issue = None
    if body.issue_id:
        issue = (
            connection.execute(
                text("SELECT * FROM issues WHERE id=:id FOR UPDATE"), {"id": body.issue_id}
            )
            .mappings()
            .one_or_none()
        )
        if issue is None:
            raise HTTPException(404, "Issue not found")
        scope(actor, issue)
        if body.expected_issue_version != issue["row_version"]:
            raise HTTPException(409, "Candidate issue changed. Reload candidates.")
        if (
            issue["category_code"] != report["canonical_category"]
            or issue["pilot_id"] != report["pilot_id"]
        ):
            raise HTTPException(409, "Issue category/pilot is incompatible")
        found = [row for row in candidates(connection, report) if row["id"] == body.issue_id]
        if not found or found[0]["asset_conflict"]:
            raise HTTPException(409, "Candidate conflicts with current location or trusted asset")
    if body.action == "link":
        if issue is None or issue["status"] not in ACTIVE:
            raise HTTPException(409, "Choose a current active compatible issue")
        created: UUID = UUID(str(issue["id"]))
        method = "reviewed_duplicate"
    else:
        if body.action == "recurrence" and (issue is None or issue["status"] != "resolved"):
            raise HTTPException(409, "Recurrence requires a resolved nearby predecessor")
        parent = None
        if body.action == "recurrence":
            assert issue is not None
            parent = UUID(str(issue["id"]))
        created = new_issue(
            connection,
            report,
            actor.id,
            body.reason,
            recurrence=parent,
        )
        method = "new"
    independent = not report["evidence_reused"] or body.independent_evidence
    link(connection, report, created, actor.id, method, body.reason, independent)
    connection.execute(
        text("""
      UPDATE duplicate_candidates SET state=CASE WHEN issue_id=:issue
        THEN 'accepted' ELSE 'rejected' END,
        reviewer_id=:actor,decided_at=now(),reason=:reason
      WHERE report_id=:report AND state='proposed' AND report_revision=:revision
    """),
        {
            "issue": body.issue_id if body.action == "recurrence" else created,
            "actor": actor.id,
            "reason": body.reason,
            "report": report_id,
            "revision": report["content_revision"],
        },
    )
    audit(
        connection,
        actor,
        report_id,
        "duplicate_decision",
        body,
        created,
        report["content_revision"],
    )
    return created


def merge(connection: Connection, source: UUID, actor: Actor, body: MergeDecision) -> IssueSummary:
    action_lock(connection, body.request_id)
    initial = (
        connection.execute(text("SELECT * FROM issues WHERE id=:id"), {"id": source})
        .mappings()
        .one_or_none()
    )
    if initial is None:
        raise HTTPException(404, "Issue not found")
    scope(actor, initial)
    category_locks(connection, initial["pilot_id"], [initial["category_code"]])
    old = replay(connection, actor, source, "merge_issue", body)
    if old:
        return summary(connection, old)
    rows = (
        connection.execute(
            text("SELECT * FROM issues WHERE id=ANY(:ids) ORDER BY id FOR UPDATE"),
            {"ids": sorted({source, body.target_id})},
        )
        .mappings()
        .all()
    )
    by_id = {row["id"]: row for row in rows}
    if source == body.target_id or len(rows) != 2:
        raise HTTPException(409, "Choose two distinct existing issues")
    a, b = by_id[source], by_id[body.target_id]
    scope(actor, a)
    scope(actor, b)
    if (
        a["row_version"] != body.expected_version
        or b["row_version"] != body.expected_target_version
    ):
        raise HTTPException(409, "Issue changed. Reload before merging.")
    if (
        a["category_code"] != b["category_code"]
        or a["pilot_id"] != b["pilot_id"]
        or a["status"] not in ACTIVE
        or b["status"] not in ACTIVE
    ):
        raise HTTPException(409, "Only active compatible issues can be merged")
    if a["asset_id"] and b["asset_id"] and a["asset_id"] != b["asset_id"]:
        raise HTTPException(409, "Different trusted assets cannot be merged")
    linked = (
        connection.execute(
            text("""
      SELECT r.*,l.independent_evidence FROM reports r JOIN issue_report_links l ON l.report_id=r.id
      WHERE l.issue_id=:id AND l.active ORDER BY r.id FOR UPDATE OF r
    """),
            {"id": source},
        )
        .mappings()
        .all()
    )
    if any(not actor.can_review(row["area_id"]) for row in linked):
        raise HTTPException(403, "Merge requires permission over every linked report area")
    connection.execute(
        text(
            "UPDATE issue_report_links SET active=false,ended_at=now() "
            "WHERE issue_id=:id AND active"
        ),
        {"id": source},
    )
    for report in linked:
        link(
            connection,
            report,
            body.target_id,
            actor.id,
            "reviewed_duplicate",
            body.reason,
            report["independent_evidence"],
        )
    connection.execute(
        text("""
      UPDATE issues SET status='merged',merged_into_issue_id=:target,updated_at=now() WHERE id=:id
    """),
        {"id": source, "target": body.target_id},
    )
    refresh_aggregates(connection, source)
    refresh_aggregates(connection, body.target_id)
    event(connection, source, "merged", actor.id, body.reason, {"survivor": str(body.target_id)})
    event(
        connection, body.target_id, "merge_received", actor.id, body.reason, {"source": str(source)}
    )
    audit(connection, actor, source, "merge_issue", body, body.target_id, a["row_version"] + 1)
    return summary(connection, body.target_id)


def split(connection: Connection, source: UUID, actor: Actor, body: SplitDecision) -> IssueSummary:
    action_lock(connection, body.request_id)
    initial = (
        connection.execute(text("SELECT * FROM issues WHERE id=:id"), {"id": source})
        .mappings()
        .one_or_none()
    )
    if initial is None:
        raise HTTPException(404, "Issue not found")
    scope(actor, initial)
    category_locks(connection, initial["pilot_id"], [initial["category_code"]])
    old = replay(connection, actor, source, "split_issue", body)
    if old:
        return summary(connection, old)
    issue = (
        connection.execute(text("SELECT * FROM issues WHERE id=:id FOR UPDATE"), {"id": source})
        .mappings()
        .one()
    )
    if issue["row_version"] != body.expected_version or issue["status"] not in ACTIVE:
        raise HTTPException(409, "Issue changed or is not active")
    if len(set(body.report_ids)) != len(body.report_ids):
        raise HTTPException(422, "Select each report only once")
    selected = (
        connection.execute(
            text("""
      SELECT r.*,ST_X(r.confirmed_point::geometry) AS lon,ST_Y(r.confirmed_point::geometry) AS lat,
             l.independent_evidence FROM reports r JOIN issue_report_links l ON l.report_id=r.id
      WHERE l.issue_id=:issue AND l.active AND r.id=ANY(:reports) ORDER BY r.id FOR UPDATE OF r
    """),
            {"issue": source, "reports": body.report_ids},
        )
        .mappings()
        .all()
    )
    if len(selected) != len(body.report_ids) or len(selected) >= issue["report_count"]:
        raise HTTPException(
            409, "Split must move linked reports and leave at least one on the source"
        )
    if any(not actor.can_review(row["area_id"]) for row in selected):
        raise HTTPException(403, "Selected report area is outside your review scope")
    location = assign_area(connection, issue["pilot_id"], body.point)
    if location.state != "located" or not actor.can_review(location.area_id):
        raise HTTPException(403, "Split point is outside your confirmed review scope")
    if issue["asset_id"] is not None:
        raise HTTPException(
            409, "Reconcile the trusted asset inventory before splitting an asset issue"
        )
    created = new_issue(connection, selected[0], actor.id, body.reason, point=body.point)
    connection.execute(
        text("""
      UPDATE issue_report_links SET active=false,ended_at=now()
      WHERE issue_id=:issue AND active AND report_id=ANY(:reports)
    """),
        {"issue": source, "reports": body.report_ids},
    )
    for report in selected:
        link(
            connection,
            report,
            created,
            actor.id,
            "reviewed_duplicate",
            body.reason,
            report["independent_evidence"],
        )
    refresh_aggregates(connection, source)
    event(connection, source, "split", actor.id, body.reason, {"new_issue": str(created)})
    event(connection, created, "split_from", actor.id, body.reason, {"source": str(source)})
    audit(connection, actor, source, "split_issue", body, created, issue["row_version"] + 1)
    return summary(connection, created)
