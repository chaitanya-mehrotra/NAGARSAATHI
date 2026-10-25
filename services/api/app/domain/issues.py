import json
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import Connection, Engine, text

from app.domain.geography import IssuePoint, assign_area
from app.domain.issue_locks import category_locks
from app.issue_schemas import IssueSummary
from app.jobs import claim, fail_job, finish

ACTIVE = {"open", "assigned", "in_progress", "resolution_pending", "reopened"}


def summary(connection: Connection, issue_id: UUID) -> IssueSummary:
    from app.domain.priority import view

    row = (
        connection.execute(
            text("""
      SELECT i.*,a.code AS area_code,ST_X(i.geom::geometry) AS lon,ST_Y(i.geom::geometry) AS lat
      FROM issues i JOIN areas a ON a.id=i.area_id WHERE i.id=:id
    """),
            {"id": issue_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(404, "Issue not found")
    return summary_row(row, view(connection, issue_id))


def summary_row(row: Any, priority: Any) -> IssueSummary:
    return IssueSummary(
        id=row["id"],
        public_reference=row["public_reference"],
        category=row["category_code"],
        area_code=row["area_code"],
        status=row["status"],
        row_version=row["row_version"],
        point=IssuePoint(longitude=row["lon"], latitude=row["lat"], confirmed=True),
        report_count=row["report_count"],
        eligible_reporter_count=row["eligible_reporter_count"],
        first_accepted_at=row["first_accepted_at"],
        asset_id=row["asset_id"],
        recurrence_parent_id=row["recurrence_parent_issue_id"],
        merged_into_id=row["merged_into_issue_id"],
        priority=priority,
        assigned_operator_id=row["assigned_operator_id"],
        assigned_team=row["assigned_team"],
    )


def summaries(
    connection: Connection, snapshots: dict[UUID, UUID | None]
) -> dict[UUID, IssueSummary]:
    from app.domain.priority import views

    priorities = views(connection, snapshots)
    rows = connection.execute(
        text("""
      SELECT i.*,a.code AS area_code,ST_X(i.geom::geometry) AS lon,ST_Y(i.geom::geometry) AS lat
      FROM issues i JOIN areas a ON a.id=i.area_id WHERE i.id=ANY(CAST(:ids AS uuid[]))
    """),
        {"ids": list(snapshots)},
    ).mappings()
    return {row["id"]: summary_row(row, priorities.get(row["id"])) for row in rows}


def event(
    connection: Connection,
    issue_id: UUID,
    action: str,
    actor: UUID | None,
    reason: str,
    evidence: dict[str, Any] | None = None,
) -> None:
    connection.execute(
        text("""
      INSERT INTO issue_events(issue_id,action,actor_id,reason,evidence)
      VALUES (:issue,:action,:actor,:reason,CAST(:evidence AS jsonb))
    """),
        {
            "issue": issue_id,
            "action": action,
            "actor": actor,
            "reason": reason,
            "evidence": json.dumps(evidence or {}),
        },
    )


def refresh_aggregates(connection: Connection, issue_id: UUID) -> None:
    connection.execute(
        text("""
      UPDATE issues SET report_count=support.count,eligible_reporter_count=support.eligible,
        first_accepted_at=COALESCE(support.first,first_accepted_at),
        most_recent_accepted_at=COALESCE(support.last,most_recent_accepted_at),
        row_version=row_version+1,updated_at=now()
      FROM (SELECT count(*) AS count,count(DISTINCT r.reporter_id)
              FILTER(WHERE l.independent_evidence) AS eligible,
              min(r.received_at) AS first,max(r.received_at) AS last
            FROM issue_report_links l JOIN reports r ON r.id=l.report_id
            WHERE l.issue_id=:id AND l.active) support WHERE issues.id=:id
    """),
        {"id": issue_id},
    )
    revision: int = connection.execute(
        text("SELECT row_version FROM issues WHERE id=:id"), {"id": issue_id}
    ).scalar_one()
    connection.execute(
        text("""
      INSERT INTO jobs(type,payload,entity_revision,deduplication_key)
      VALUES ('refresh_priority',CAST(:payload AS jsonb),:version,:key)
      ON CONFLICT(deduplication_key) DO NOTHING
    """),
        {
            "payload": json.dumps({"issue_id": str(issue_id)}),
            "version": revision,
            "key": f"refresh_priority:{issue_id}:{revision}",
        },
    )


def candidates(connection: Connection, report: Any) -> list[dict[str, Any]]:
    rows = (
        connection.execute(
            text("""
      SELECT i.*,ST_Distance(i.geom,r.confirmed_point) AS distance_m,
        (i.asset_id IS NOT NULL AND r.trusted_asset_id IS NOT NULL
         AND i.asset_id<>r.trusted_asset_id) AS asset_conflict
      FROM issues i JOIN reports r ON r.id=:report JOIN categories c ON c.code=i.category_code
      WHERE i.pilot_id=r.pilot_id AND i.category_code=r.canonical_category AND i.report_count>0
        AND i.status IN ('open','assigned','in_progress','resolution_pending','reopened','resolved')
        AND ST_DWithin(i.geom,r.confirmed_point,
                       c.duplicate_radius_m+LEAST(COALESCE(r.location_accuracy_m,0),25))
      ORDER BY ST_Distance(i.geom,r.confirmed_point),i.id
    """),
            {"report": report["id"]},
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def record_candidates(connection: Connection, report: Any, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        features = {
            "distance_m": row["distance_m"],
            "asset_conflict": row["asset_conflict"],
            "kind": "recurrence" if row["status"] == "resolved" else "nearby",
            "asset_match": row["asset_id"] is not None
            and row["asset_id"] == report["trusted_asset_id"],
            "evidence_reused": report["evidence_reused"],
            "text_similarity": None,
            "visual_similarity": None,
            "uncertainty_m": report["location_accuracy_m"],
            "receipt_gap_seconds": (
                report["received_at"] - row["most_recent_accepted_at"]
            ).total_seconds(),
            "citizen_suggestion": report["location_evidence"].get("suggested_issue_id")
            == str(row["id"]),
        }
        connection.execute(
            text("""
          INSERT INTO duplicate_candidates(report_id,issue_id,report_revision,issue_revision,
                                           features,rule_version,state)
          VALUES (:report,:issue,:report_version,:issue_version,CAST(:features AS jsonb),
                  'conservative-v1','proposed') ON CONFLICT DO NOTHING
        """),
            {
                "report": report["id"],
                "issue": row["id"],
                "report_version": report["content_revision"],
                "issue_version": row["row_version"],
                "features": json.dumps(features),
            },
        )


def new_issue(
    connection: Connection,
    report: Any,
    actor: UUID | None,
    reason: str,
    recurrence: UUID | None = None,
    point: IssuePoint | None = None,
) -> UUID:
    issue_id = uuid4()
    if point is None:
        point = IssuePoint(longitude=report["lon"], latitude=report["lat"], confirmed=True)
    assignment = assign_area(connection, report["pilot_id"], point)
    if assignment.state != "located":
        raise HTTPException(422, "New issue needs an in-pilot confirmed point")
    connection.execute(
        text("""
      INSERT INTO issues(id,public_reference,pilot_id,category_code,geom,area_id,boundary_version,
         asset_id,address_text,first_accepted_at,most_recent_accepted_at,synthetic,recurrence_parent_issue_id)
      VALUES (:id,:reference,:pilot,:category,
         ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography,:area,:version,:asset,:address,
         :received,:received,:synthetic,:recurrence)
    """),
        {
            "id": issue_id,
            "reference": "NI-" + issue_id.hex.upper(),
            "pilot": report["pilot_id"],
            "category": report["canonical_category"],
            "lon": point.longitude,
            "lat": point.latitude,
            "area": assignment.area_id,
            "version": assignment.boundary_version,
            "asset": report["trusted_asset_id"],
            "address": report["address_text"],
            "received": report["received_at"],
            "synthetic": report["synthetic"],
            "recurrence": recurrence,
        },
    )
    event(
        connection,
        issue_id,
        "created",
        actor,
        reason,
        {"report_id": str(report["id"]), "rule": "conservative-v1"},
    )
    return issue_id


def link(
    connection: Connection,
    report: Any,
    issue_id: UUID,
    actor: UUID | None,
    method: str,
    reason: str,
    independent: bool,
) -> None:
    connection.execute(
        text("""
      UPDATE reports SET state='admitted',review_reason=NULL,updated_at=now() WHERE id=:id;
    """),
        {"id": report["id"]},
    )
    connection.execute(
        text("""
      INSERT INTO issue_report_links(report_id,issue_id,method,actor_id,rule_version,reason,
                                     independent_evidence)
      VALUES (:report,:issue,:method,:actor,'conservative-v1',:reason,:independent)
    """),
        {
            "report": report["id"],
            "issue": issue_id,
            "method": method,
            "actor": actor,
            "reason": reason,
            "independent": independent,
        },
    )
    event(
        connection,
        issue_id,
        "report_linked",
        actor,
        reason,
        {"report_id": str(report["id"]), "method": method},
    )
    refresh_aggregates(connection, issue_id)


def report_locked(connection: Connection, report_id: UUID) -> Any:
    return (
        connection.execute(
            text("""
      SELECT *,ST_X(confirmed_point::geometry) AS lon,ST_Y(confirmed_point::geometry) AS lat
      FROM reports WHERE id=:id FOR UPDATE
    """),
            {"id": report_id},
        )
        .mappings()
        .one()
    )


def admit(connection: Connection, report_id: UUID, revision: int) -> None:
    initial = (
        connection.execute(text("SELECT * FROM reports WHERE id=:id"), {"id": report_id})
        .mappings()
        .one()
    )
    category_locks(
        connection,
        initial["pilot_id"],
        [initial["canonical_category"] or initial["claimed_category"]],
    )
    report = report_locked(connection, report_id)
    if report["content_revision"] != revision or report["state"] == "admitted":
        return
    if (
        report["validation_status"] != "accepted"
        or report["validation_revision"] != revision
        or report["canonical_category"] is None
        or report["area_id"] is None
    ):
        return
    accuracy = report["location_accuracy_m"]
    reviewed: bool = connection.execute(
        text("""
      SELECT EXISTS(SELECT 1 FROM location_decisions WHERE report_id=:id
                    AND method='human_review' AND approved_point IS NOT NULL)
    """),
        {"id": report_id},
    ).scalar_one()
    if (accuracy is None and not reviewed) or (accuracy is not None and accuracy > 25):
        hold(connection, report_id, "location_quality_requires_review")
        return
    reused: bool = connection.execute(
        text("""
      SELECT EXISTS(SELECT 1 FROM media m JOIN media other
        ON other.original_sha256=m.original_sha256
        JOIN reports r ON r.id=other.report_id WHERE m.report_id=:id AND r.id<>:id)
    """),
        {"id": report_id},
    ).scalar_one()
    far: bool = connection.execute(
        text("""
      SELECT EXISTS(SELECT 1 FROM media m JOIN media other
        ON other.original_sha256=m.original_sha256
        JOIN reports r ON r.id=other.report_id JOIN reports current ON current.id=:id
        JOIN categories c ON c.code=current.canonical_category
        WHERE m.report_id=:id AND r.id<>:id AND r.confirmed_point IS NOT NULL
          AND NOT ST_DWithin(r.confirmed_point,current.confirmed_point,c.duplicate_radius_m))
    """),
        {"id": report_id},
    ).scalar_one()
    connection.execute(
        text("UPDATE reports SET evidence_reused=:reused WHERE id=:id"),
        {"id": report_id, "reused": reused},
    )
    report = report_locked(connection, report_id)
    rows = candidates(connection, report)
    plausible = [row for row in rows if not row["asset_conflict"]]
    record_candidates(connection, report, rows)
    if far:
        hold(connection, report_id, "reused_photo_conflicting_location")
        return
    category = (
        connection.execute(
            text("SELECT * FROM categories WHERE code=:code"),
            {"code": report["canonical_category"]},
        )
        .mappings()
        .one()
    )
    known = [
        row
        for row in plausible
        if row["status"] in ACTIVE
        and report["trusted_asset_id"]
        and row["asset_id"] == report["trusted_asset_id"]
    ]
    if (
        len(known) == 1
        and category["auto_merge_allowed"]
        and not reused
        and (accuracy is None or accuracy == 0)
    ):
        link(
            connection,
            report,
            known[0]["id"],
            None,
            "asset_match",
            "Trusted unique asset match",
            True,
        )
        return
    if plausible:
        hold(connection, report_id, "duplicate_or_recurrence_review_pending")
        return
    if category["requires_manual_categorisation"]:
        hold(connection, report_id, "manual_issue_review_required")
        return
    created = new_issue(
        connection, report, None, "Accepted evidence with no plausible existing candidate"
    )
    link(connection, report, created, None, "new", "New physical issue", not reused)


def hold(connection: Connection, report_id: UUID, reason: str) -> None:
    connection.execute(
        text("UPDATE reports SET state='awaiting_review',review_reason=:reason WHERE id=:id"),
        {"id": report_id, "reason": reason},
    )


def process_admission_once(engine: Engine, worker: str | None = None) -> bool:
    worker = worker or uuid4().hex
    job = claim(engine, worker, "admit_report")
    if job is None:
        return False
    try:
        with engine.begin() as connection:
            owned = connection.execute(
                text("""SELECT id FROM jobs WHERE id=:id AND worker_id=:owner
                  AND status='running' AND lease_expires_at>now() FOR UPDATE"""),
                {"id": job["id"], "owner": worker},
            ).scalar_one_or_none()
            if owned is None:
                return True
            admit(connection, UUID(job["payload"]["report_id"]), job["entity_revision"])
            finish(connection, job["id"], worker)
    except Exception:
        with engine.begin() as connection:
            fail_job(connection, job, worker, "admission_failed")
    return True
