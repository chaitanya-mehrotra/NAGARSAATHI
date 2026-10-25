import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import Connection, text

from app.domain.enums import Role
from app.domain.issues import summaries
from app.intake_schemas import Actor
from app.queue_schemas import AreaCategorySummary, QueueFilters, QueueItem, QueuePage

BASE = """
  FROM issues i JOIN areas a ON a.id=i.area_id
  JOIN priority_epochs e ON e.pilot_id=i.pilot_id AND e.state='active'
  JOIN priority_policies p ON p.id=e.policy_id
  LEFT JOIN priority_snapshots s ON s.id=i.current_priority_snapshot_id AND s.epoch_id=e.id
  WHERE (:global OR i.area_id=ANY(CAST(:areas AS uuid[])))
    AND (CAST(:area AS text) IS NULL OR a.code=:area)
    AND (CAST(:category AS text) IS NULL OR i.category_code=:category)
    AND (:status='all' OR (:status='active' AND i.status IN
      ('open','assigned','in_progress','resolution_pending','reopened') AND i.report_count>0)
      OR i.status=:status)
    AND (CAST(:band AS text) IS NULL OR
      (CASE WHEN i.critical_override THEN 'critical' ELSE s.band END)=:band
      OR (:band='pending' AND s.id IS NULL))
    AND (NOT :overdue OR i.first_accepted_at<=now()-make_interval(secs=>
      (p.category_parameters->i.category_code->>'target_hours')::double precision*3600))
    AND (NOT :bbox OR ST_Intersects(i.geom::geometry,
      ST_MakeEnvelope(:west,:south,:east,:north,4326)))
"""
ORDER = "i.critical_override DESC,s.score DESC NULLS LAST,i.first_accepted_at,i.id"


def parameters(connection: Connection, actor: Actor, filters: QueueFilters) -> dict[str, Any]:
    grants = [g for g in actor.grants if g.role in {Role.REVIEWER, Role.ADMIN}]
    result: dict[str, Any] = {
        **filters.model_dump(),
        "global": any(g.area_id is None for g in grants),
        "areas": [g.area_id for g in grants if g.area_id],
        "west": -180.0,
        "south": -90.0,
        "east": 180.0,
        "north": 90.0,
        "bbox": bool(filters.bbox),
    }
    if (
        filters.area
        and not connection.execute(
            text("SELECT code FROM areas WHERE code=:code"), {"code": filters.area}
        ).scalar_one_or_none()
    ):
        raise HTTPException(422, "Choose a configured area")
    if (
        filters.category
        and not connection.execute(
            text("SELECT code FROM categories WHERE code=:code"), {"code": filters.category}
        ).scalar_one_or_none()
    ):
        raise HTTPException(422, "Choose a configured category")
    if filters.bbox:
        try:
            west, south, east, north = [float(v) for v in filters.bbox.split(",")]
            if not (
                all(math.isfinite(v) for v in (west, south, east, north))
                and -180 <= west < east <= 180
                and -90 <= south < north <= 90
            ):
                raise ValueError
        except ValueError as error:
            raise HTTPException(
                422, "Bounding box must be west,south,east,north in degrees"
            ) from error
        result.update(west=west, south=south, east=east, north=north)
    return result


def grant_hash(actor: Actor) -> str:
    values = sorted(
        (g.role.value, str(g.area_id))
        for g in actor.grants
        if g.role in {Role.REVIEWER, Role.ADMIN}
    )
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def page(
    connection: Connection, actor: Actor, filters: QueueFilters, cursor: str | None, limit: int
) -> QueuePage:
    params = parameters(connection, actor, filters)
    digest = hashlib.sha256(filters.model_dump_json().encode()).hexdigest()
    roles = grant_hash(actor)
    current_epochs = {
        str(row["pilot_id"]): str(row["id"])
        for row in connection.execute(
            text("SELECT id,pilot_id FROM priority_epochs WHERE state='active'")
        ).mappings()
    }
    after = 0
    if cursor:
        try:
            value, offset = cursor.split(":")
            session_id = UUID(value)
            after = int(offset)
            if after < 0:
                raise ValueError
        except ValueError as error:
            raise HTTPException(422, "Invalid queue cursor") from error
        session = (
            connection.execute(
                text("SELECT * FROM staff_queue_sessions WHERE id=:id"), {"id": session_id}
            )
            .mappings()
            .one_or_none()
        )
        if session is None or session["actor_id"] != actor.id:
            raise HTTPException(404, "Queue cursor not found")
        if (
            session["filter_hash"] != digest
            or session["grant_hash"] != roles
            or session["epochs"] != current_epochs
            or session["expires_at"] <= datetime.now(UTC)
        ):
            raise HTTPException(409, "Queue context changed or expired. Refresh the first page.")
    else:
        # Only the caller's expired, disposable browsing metadata is removed.
        connection.execute(
            text("DELETE FROM staff_queue_sessions WHERE actor_id=:id AND expires_at<now()"),
            {"id": actor.id},
        )
        count: int = connection.execute(text("SELECT count(*) " + BASE), params).scalar_one()
        if count > 10000:
            raise HTTPException(422, "Narrow the filters to at most 10,000 issues")
        session_id = uuid4()
        connection.execute(
            text("""
          INSERT INTO staff_queue_sessions(id,actor_id,grant_hash,filter_hash,epochs)
          VALUES(:id,:actor,:roles,:filters,CAST(:epochs AS jsonb))
        """),
            {
                "id": session_id,
                "actor": actor.id,
                "roles": roles,
                "filters": digest,
                "epochs": json.dumps(current_epochs),
            },
        )
        connection.execute(
            text(
                """
          INSERT INTO staff_queue_items(session_id,position,issue_id,issue_revision,snapshot_id,
                                        report_count,eligible_reporter_count)
          SELECT :session,row_number() OVER(ORDER BY """
                + ORDER
                + """)::integer,
                 i.id,i.row_version,s.id,i.report_count,i.eligible_reporter_count
        """
                + BASE
            ),
            {**params, "session": session_id},
        )
        session = (
            connection.execute(
                text("SELECT * FROM staff_queue_sessions WHERE id=:id"), {"id": session_id}
            )
            .mappings()
            .one()
        )
    totals = (
        connection.execute(
            text("""
      SELECT count(*) AS issues,COALESCE(sum(report_count),0) AS reports,
             COALESCE(sum(eligible_reporter_count),0) AS pairs
      FROM staff_queue_items WHERE session_id=:id
    """),
            {"id": session_id},
        )
        .mappings()
        .one()
    )
    rows = (
        connection.execute(
            text("""
      SELECT q.*,i.area_id,i.current_priority_snapshot_id
      FROM staff_queue_items q JOIN issues i ON i.id=q.issue_id
      WHERE session_id=:id AND position>:after ORDER BY position LIMIT :limit
    """),
            {"id": session_id, "after": after, "limit": limit + 1},
        )
        .mappings()
        .all()
    )
    if any(not actor.can_review(row["area_id"]) for row in rows):
        raise HTTPException(409, "Issue ownership changed. Refresh the queue.")
    items = []
    records = summaries(connection, {row["issue_id"]: row["snapshot_id"] for row in rows[:limit]})
    for row in rows[:limit]:
        issue = records[row["issue_id"]]
        items.append(
            QueueItem(
                issue=issue,
                position=row["position"],
                changed_since_capture=issue.row_version != row["issue_revision"]
                or row["snapshot_id"] != row["current_priority_snapshot_id"],
            )
        )
    return QueuePage(
        items=items,
        next_cursor=f"{session_id}:{items[-1].position}" if len(rows) > limit else None,
        captured_at=session["captured_at"],
        expires_at=session["expires_at"],
        total_issues=totals["issues"],
        total_linked_reports=totals["reports"],
        eligible_reporter_issue_pairs=totals["pairs"],
        epochs=session["epochs"],
    )


def area_summary(connection: Connection, actor: Actor) -> list[AreaCategorySummary]:
    grants = [g for g in actor.grants if g.role in {Role.REVIEWER, Role.ADMIN}]
    rows = (
        connection.execute(
            text("""
      WITH scoped AS (
        SELECT a.* FROM areas a WHERE :global OR a.id=ANY(CAST(:areas AS uuid[]))
      ), active AS (
        SELECT i.*,CASE WHEN i.critical_override THEN 'critical' ELSE s.band END AS band,
          GREATEST(0,EXTRACT(epoch FROM now()-i.first_accepted_at)/3600) AS age,
          (p.category_parameters->i.category_code->>'target_hours')::double precision AS target
        FROM issues i JOIN priority_epochs e ON e.pilot_id=i.pilot_id AND e.state='active'
        JOIN priority_policies p ON p.id=e.policy_id
        LEFT JOIN priority_snapshots s ON s.id=i.current_priority_snapshot_id AND s.epoch_id=e.id
        WHERE i.report_count>0 AND i.status IN
          ('open','assigned','in_progress','resolution_pending','reopened')
      )
      SELECT a.code AS area_code,a.display_name AS area_name,c.code AS category,
        count(i.id) AS active_issues,COALESCE(sum(i.report_count),0) AS linked_reports,
        COALESCE(sum(i.eligible_reporter_count),0) AS eligible_reporter_issue_pairs,
        count(i.id) FILTER(WHERE i.band IN ('high','critical')) AS high_or_critical_issues,
        count(i.id) FILTER(WHERE i.critical_override) AS confirmed_critical_issues,
        count(i.id) FILTER(WHERE i.age>=i.target) AS overdue_issues,
        count(i.id) FILTER(WHERE i.age>=i.target AND i.band IN ('high','critical'))
          AS high_and_overdue_issues,
        max(i.age) AS oldest_age_hours,max(i.age) FILTER(WHERE i.age>=i.target)
          AS oldest_overdue_age_hours
      FROM scoped a CROSS JOIN categories c
      LEFT JOIN active i ON i.area_id=a.id AND i.category_code=c.code
      WHERE c.active GROUP BY a.code,a.display_name,c.code ORDER BY a.code,c.code
    """),
            {
                "global": any(g.area_id is None for g in grants),
                "areas": [g.area_id for g in grants if g.area_id],
            },
        )
        .mappings()
        .all()
    )
    return [AreaCategorySummary.model_validate(dict(row)) for row in rows]
