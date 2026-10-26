import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import Connection, Engine, text

from app.domain.issue_locks import priority_lock
from app.domain.scoring import score
from app.jobs import claim, finish
from app.priority_schemas import CategoryPolicy, Policy, PriorityView, ScoreInputs

ACTIVE_SQL = "('open','assigned','in_progress','resolution_pending','reopened')"


def active_epoch(connection: Connection, pilot: UUID) -> Any:
    return (
        connection.execute(
            text("""
      SELECT e.*,p.version,p.weights,p.category_parameters,p.hazard_rules,
             s.version AS poi_version FROM priority_epochs e
      JOIN priority_policies p ON p.id=e.policy_id JOIN poi_snapshots s ON s.id=e.poi_snapshot_id
      WHERE e.pilot_id=:pilot AND e.state='active'
    """),
            {"pilot": pilot},
        )
        .mappings()
        .one_or_none()
    )


def epoch(connection: Connection, epoch_id: UUID) -> Any:
    return (
        connection.execute(
            text("""
      SELECT e.*,p.version,p.weights,p.category_parameters,p.hazard_rules,
             s.version AS poi_version FROM priority_epochs e
      JOIN priority_policies p ON p.id=e.policy_id JOIN poi_snapshots s ON s.id=e.poi_snapshot_id
      WHERE e.id=:id
    """),
            {"id": epoch_id},
        )
        .mappings()
        .one()
    )


def policy_from(row: Any) -> Policy:
    return Policy(
        version=row["version"],
        weights=row["weights"],
        categories=row["category_parameters"],
        **row["hazard_rules"],
    )


def location_context(
    connection: Connection, issue_id: UUID, snapshot: UUID, policy: Policy
) -> dict[str, Any]:
    row = (
        connection.execute(
            text("""
      SELECT s.coverage_complete AND ST_Covers(s.coverage,ST_Buffer(i.geom,:radius)::geometry)
               AS complete,
        (SELECT min(ST_Distance(p.geom,i.geom)) FROM pois p
         WHERE p.snapshot_id=s.id AND p.type='school') AS school,
        (SELECT min(ST_Distance(p.geom,i.geom)) FROM pois p
         WHERE p.snapshot_id=s.id AND p.type='hospital') AS hospital,
        EXISTS(SELECT 1 FROM pois p WHERE p.snapshot_id=s.id AND p.type='major_road'
               AND ST_DWithin(p.geom,i.geom,:road)) AS major_road
      FROM issues i CROSS JOIN poi_snapshots s WHERE i.id=:issue AND s.id=:snapshot
    """),
            {
                "issue": issue_id,
                "snapshot": snapshot,
                "radius": policy.poi_radius_m,
                "road": policy.major_road_distance_m,
            },
        )
        .mappings()
        .one()
    )
    return {
        "coverage_complete": row["complete"],
        "school_distance_m": row["school"],
        "hospital_distance_m": row["hospital"],
        "major_road": row["major_road"],
    }


def snapshot(
    connection: Connection, issue: Any, scoring_epoch: Any, as_of: datetime, publish: bool = False
) -> UUID:
    policy = policy_from(scoring_epoch)
    eligible: int = connection.execute(
        text("""
      SELECT count(DISTINCT r.reporter_id) FROM issue_report_links l
      JOIN reports r ON r.id=l.report_id JOIN users u ON u.id=r.reporter_id
      WHERE l.issue_id=:id AND l.active AND l.independent_evidence AND u.active
    """),
        {"id": issue["id"]},
    ).scalar_one()
    traffic_weight: float = connection.execute(
        text("SELECT COALESCE(traffic_weight, 1.0) FROM areas WHERE id=:area_id"),
        {"area_id": issue["area_id"]},
    ).scalar_one_or_none() or 1.0
    inputs = ScoreInputs(
        as_of=as_of,
        first_accepted_at=issue["first_accepted_at"],
        category=issue["category_code"],
        eligible_reporters=eligible,
        severity_override=issue["severity_override"],
        urgency_override=issue["urgency_override"],
        critical_override=issue["critical_override"],
        critical_review_due_at=issue["critical_review_due_at"],
        zone_traffic_weight=traffic_weight,
        **location_context(connection, issue["id"], scoring_epoch["poi_snapshot_id"], policy),
    )
    recent: int = connection.execute(
        text("""
      SELECT count(DISTINCT r.reporter_id) FROM issue_report_links l
      JOIN reports r ON r.id=l.report_id JOIN users u ON u.id=r.reporter_id
      WHERE l.issue_id=:id AND l.active AND l.independent_evidence AND u.active
        AND r.received_at>=:as_of-interval '60 seconds' AND r.received_at<=:as_of
    """),
        {"id": issue["id"], "as_of": as_of},
    ).scalar_one()
    inputs = inputs.model_copy(update={"recent_reporters": recent})
    result = score(inputs, policy)
    source = inputs.model_dump(mode="json")
    source["scoring_function_version"] = "weighted-v1"
    source["burst_review_rule"] = {"minimum_reporters": 5, "window_seconds": 60}
    source.update(
        policy=policy.model_dump(mode="json"),
        poi_version=scoring_epoch["poi_version"],
        severity_baseline=policy.categories[inputs.category].severity,
        report_count=issue["report_count"],
    )
    encoded = json.dumps(source, sort_keys=True, separators=(",", ":"))
    snapshot_id = uuid4()
    connection.execute(
        text("""
      INSERT INTO priority_snapshots(id,issue_id,policy_id,epoch_id,issue_revision,as_of,
        inputs,factors,contributions,score,band,urgency_source,missing_data_flags,input_hash)
      VALUES (:id,:issue,:policy,:epoch,:revision,:as_of,CAST(:inputs AS jsonb),
        CAST(:factors AS jsonb),CAST(:contributions AS jsonb),:score,:band,:urgency,
        CAST(:flags AS jsonb),:hash)
    """),
        {
            "id": snapshot_id,
            "issue": issue["id"],
            "policy": scoring_epoch["policy_id"],
            "epoch": scoring_epoch["id"],
            "revision": issue["row_version"],
            "as_of": as_of,
            "inputs": encoded,
            "factors": json.dumps(result.factors),
            "contributions": json.dumps(result.contributions),
            "score": result.score,
            "band": result.band,
            "urgency": result.urgency_source,
            "flags": json.dumps(result.flags),
            "hash": hashlib.sha256(encoded.encode()).hexdigest(),
        },
    )
    if publish:
        changed = connection.execute(
            text("""
          UPDATE issues SET current_priority_snapshot_id=:snapshot
          WHERE id=:id AND row_version=:revision RETURNING id
        """),
            {"id": issue["id"], "snapshot": snapshot_id, "revision": issue["row_version"]},
        ).scalar_one_or_none()
        if changed is None:
            raise HTTPException(409, "Issue changed while computing priority")
    return snapshot_id


def view(
    connection: Connection,
    issue_id: UUID,
    now: datetime | None = None,
    snapshot_id: UUID | None = None,
) -> PriorityView | None:
    now = now or datetime.now(UTC)
    row = (
        connection.execute(
            text("""
      SELECT s.*,p.version,e.poi_snapshot_id,poi.version AS poi_version,
             i.row_version,i.critical_override,i.critical_review_due_at,
             e.state AS epoch_state
      FROM issues i JOIN priority_snapshots s
        ON s.id=COALESCE(CAST(:snapshot AS uuid),i.current_priority_snapshot_id) AND s.issue_id=i.id
      JOIN priority_epochs e ON e.id=s.epoch_id JOIN priority_policies p ON p.id=s.policy_id
      JOIN poi_snapshots poi ON poi.id=e.poi_snapshot_id WHERE i.id=:id
    """),
            {"id": issue_id, "snapshot": snapshot_id},
        )
        .mappings()
        .one_or_none()
    )
    return snapshot_view(row, now)


def views(
    connection: Connection, snapshots: dict[UUID, UUID | None]
) -> dict[UUID, PriorityView | None]:
    rows = connection.execute(
        text("""
      SELECT s.*,p.version,e.poi_snapshot_id,poi.version AS poi_version,
        i.row_version,i.critical_override,i.critical_review_due_at,e.state AS epoch_state
      FROM issues i JOIN unnest(CAST(:issues AS uuid[]),CAST(:snapshots AS uuid[]))
        AS requested(issue_id,snapshot_id) ON i.id=requested.issue_id
      JOIN priority_snapshots s ON s.id=requested.snapshot_id AND s.issue_id=i.id
      JOIN priority_epochs e ON e.id=s.epoch_id JOIN priority_policies p ON p.id=s.policy_id
      JOIN poi_snapshots poi ON poi.id=e.poi_snapshot_id
    """),
        {"issues": list(snapshots), "snapshots": list(snapshots.values())},
    ).mappings()
    now = datetime.now(UTC)
    return {row["issue_id"]: snapshot_view(row, now) for row in rows}


def snapshot_view(row: Any, now: datetime) -> PriorityView | None:
    if row is None:
        return None
    flags = list(row["missing_data_flags"])
    if (
        row["critical_override"]
        and row["critical_review_due_at"] is not None
        and row["critical_review_due_at"] <= now
        and "critical_review_overdue" not in flags
    ):
        flags.append("critical_review_overdue")
    original = ScoreInputs.model_validate(
        {k: v for k, v in row["inputs"].items() if k in ScoreInputs.model_fields}
    )
    policy = Policy.model_validate(row["inputs"]["policy"])
    result = score(original, policy)
    stale = (
        row["issue_revision"] != row["row_version"]
        or row["epoch_state"] != "active"
        or row["as_of"] < now - timedelta(minutes=15)
    )
    return PriorityView(
        **{**result.model_dump(), "flags": flags},
        policy_version=row["version"],
        epoch_id=row["epoch_id"],
        poi_version=row["poi_version"],
        as_of=row["as_of"],
        computed_at=row["computed_at"],
        issue_revision=row["issue_revision"],
        stale=stale,
        provisional=bool(flags),
        inputs=row["inputs"],
        input_hash=row["input_hash"],
    )


def queue_refresh(connection: Connection, issue: Any, when: datetime | None = None) -> None:
    when = when or datetime.now(UTC)
    bucket = int(when.timestamp()) // 900
    current = active_epoch(connection, issue["pilot_id"])
    if current is None:
        return
    key = f"priority:{issue['id']}:{issue['row_version']}:{current['id']}:{bucket}"
    connection.execute(
        text("""
      INSERT INTO jobs(type,payload,entity_revision,deduplication_key)
      VALUES('refresh_priority',CAST(:payload AS jsonb),:revision,:key)
      ON CONFLICT(deduplication_key) DO NOTHING
    """),
        {
            "payload": json.dumps({"issue_id": str(issue["id"]), "epoch_id": str(current["id"])}),
            "revision": issue["row_version"],
            "key": key,
        },
    )


def refresh(
    connection: Connection,
    issue_id: UUID,
    revision: int,
    expected_epoch: UUID | None = None,
    as_of: datetime | None = None,
) -> bool:
    initial: UUID = connection.execute(
        text("SELECT pilot_id FROM issues WHERE id=:id"), {"id": issue_id}
    ).scalar_one()
    priority_lock(connection, initial)
    issue = (
        connection.execute(text("SELECT * FROM issues WHERE id=:id FOR UPDATE"), {"id": issue_id})
        .mappings()
        .one()
    )
    current = active_epoch(connection, initial)
    if current is None or issue["status"] not in {
        "open",
        "assigned",
        "in_progress",
        "resolution_pending",
        "reopened",
    }:
        return False
    if issue["row_version"] != revision or (expected_epoch and current["id"] != expected_epoch):
        queue_refresh(connection, issue)
        return False
    snapshot(connection, issue, current, as_of or datetime.now(UTC), publish=True)
    return True


def activate(
    connection: Connection,
    epoch_id: UUID,
    expected_active: UUID | None,
    author: UUID | None,
    reason: str,
) -> None:
    proposed = epoch(connection, epoch_id)
    priority_lock(connection, proposed["pilot_id"], exclusive=True)
    current = active_epoch(connection, proposed["pilot_id"])
    if current and current["id"] == epoch_id:
        return
    if (current["id"] if current else None) != expected_active:
        raise HTTPException(409, "Active policy changed. Reload before activating.")
    if proposed["state"] != "preview":
        raise HTTPException(409, "Choose a preview epoch")
    as_of = datetime.now(UTC)
    issues = (
        connection.execute(
            text(f"""
      SELECT * FROM issues WHERE pilot_id=:pilot AND status IN {ACTIVE_SQL}
      ORDER BY id FOR UPDATE
    """),
            {"pilot": proposed["pilot_id"]},
        )
        .mappings()
        .all()
    )
    for issue in issues:
        snapshot(connection, issue, proposed, as_of, publish=True)
    connection.execute(
        text("""UPDATE priority_epochs SET state='retired'
      WHERE pilot_id=:pilot AND state='active'"""),
        {"pilot": proposed["pilot_id"]},
    )
    connection.execute(
        text("""UPDATE priority_epochs SET state='active',activated_at=:now,
      review_note=:note WHERE id=:id"""),
        {"id": epoch_id, "now": as_of, "note": reason},
    )
    connection.execute(
        text("""
      INSERT INTO audit_events(actor_id,entity_type,entity_id,operation,revision,request_id,changes)
      VALUES(:actor,'priority_epoch',:epoch,'activate_priority_epoch',1,:request,
             CAST(:changes AS jsonb))
    """),
        {
            "actor": author,
            "request": uuid4(),
            "epoch": epoch_id,
            "changes": json.dumps(
                {
                    "reason": reason,
                    "issue_count": len(issues),
                    "previous_epoch_id": str(expected_active),
                }
            ),
        },
    )


def insert_policy(connection: Connection, policy: Policy, author: UUID | None) -> UUID:
    existing = (
        connection.execute(
            text("SELECT * FROM priority_policies WHERE version=:v"), {"v": policy.version}
        )
        .mappings()
        .one_or_none()
    )
    rules = {
        "poi_radius_m": policy.poi_radius_m,
        "major_road_distance_m": policy.major_road_distance_m,
    }
    categories = {k: v.model_dump() for k, v in policy.categories.items()}
    if existing:
        if (
            existing["weights"] != policy.weights
            or existing["category_parameters"] != categories
            or existing["hazard_rules"] != rules
        ):
            raise HTTPException(409, "Changed policy settings require a new version")
        return UUID(str(existing["id"]))
    required: set[str] = set(
        connection.execute(text("SELECT code FROM categories WHERE active")).scalars()
    )
    if set(policy.categories) != required:
        raise HTTPException(422, "Policy must include every active category")
    return UUID(
        str(
            connection.execute(
                text("""
      INSERT INTO priority_policies(version,weights,category_parameters,hazard_rules,author_id)
      VALUES(:version,CAST(:weights AS jsonb),CAST(:categories AS jsonb),
             CAST(:rules AS jsonb),:actor)
      RETURNING id
    """),
                {
                    "version": policy.version,
                    "weights": json.dumps(policy.weights),
                    "categories": json.dumps(categories),
                    "rules": json.dumps(rules),
                    "actor": author,
                },
            ).scalar_one()
        )
    )


def preview(
    connection: Connection,
    pilot: UUID,
    policy: Policy,
    poi: UUID,
    as_of: datetime,
    author: UUID | None,
    reason: str,
) -> UUID:
    priority_lock(connection, pilot, exclusive=True)
    policy_id = insert_policy(connection, policy, author)
    epoch_id = uuid4()
    connection.execute(
        text("""
      INSERT INTO priority_epochs(id,pilot_id,policy_id,poi_snapshot_id,state,as_of,
                                  author_id,review_note)
      VALUES(:id,:pilot,:policy,:poi,'preview',:as_of,:author,:reason)
    """),
        {
            "id": epoch_id,
            "pilot": pilot,
            "policy": policy_id,
            "poi": poi,
            "as_of": as_of,
            "author": author,
            "reason": reason,
        },
    )
    proposed = epoch(connection, epoch_id)
    issues = (
        connection.execute(
            text(f"""SELECT * FROM issues WHERE pilot_id=:pilot
      AND status IN {ACTIVE_SQL} ORDER BY id"""),
            {"pilot": pilot},
        )
        .mappings()
        .all()
    )
    for issue in issues:
        snapshot(connection, issue, proposed, as_of)
    return epoch_id


def seed_priority(connection: Connection, pilot: UUID, poi: UUID) -> None:
    if active_epoch(connection, pilot):
        return
    categories = connection.execute(text("SELECT * FROM categories WHERE active")).mappings().all()
    policy = Policy(
        version="demo-priority-v1",
        categories={
            row["code"]: CategoryPolicy(
                severity=row["default_severity"], target_hours=row["target_resolution_hours"]
            )
            for row in categories
        },
    )
    proposed = preview(
        connection,
        pilot,
        policy,
        poi,
        datetime.now(UTC),
        None,
        "Synthetic demonstration policy; pilot usefulness awaits human review",
    )
    activate(connection, proposed, None, None, "Initial synthetic demo policy")


def schedule_age_refresh(engine: Engine, now: datetime | None = None, limit: int = 100) -> int:
    now = now or datetime.now(UTC)
    with engine.begin() as connection:
        issues = (
            connection.execute(
                text(f"""
          SELECT i.* FROM issues i LEFT JOIN priority_snapshots s
            ON s.id=i.current_priority_snapshot_id
          WHERE i.status IN {ACTIVE_SQL} AND (s.id IS NULL OR s.issue_revision<>i.row_version
            OR s.as_of<:cutoff) ORDER BY s.as_of NULLS FIRST,i.id LIMIT :limit
        """),
                {"cutoff": now - timedelta(minutes=15), "limit": limit},
            )
            .mappings()
            .all()
        )
        for issue in issues:
            queue_refresh(connection, issue, now)
        return len(issues)


def process_priority_once(engine: Engine, worker: str) -> bool:
    job = claim(engine, worker, "refresh_priority")
    if job is None:
        return False
    try:
        with engine.begin() as connection:
            owned = connection.execute(
                text("""SELECT id FROM jobs WHERE id=:id AND worker_id=:worker
              AND status='running' AND lease_expires_at>now() FOR UPDATE"""),
                {"id": job["id"], "worker": worker},
            ).scalar_one_or_none()
            if owned is None:
                return True
            payload = job["payload"]
            refresh(
                connection,
                UUID(payload["issue_id"]),
                job["entity_revision"],
                UUID(payload["epoch_id"]) if payload.get("epoch_id") else None,
            )
            finish(connection, job["id"], worker)
    except Exception:
        with engine.begin() as connection:
            connection.execute(
                text("""
              UPDATE jobs SET status=:status,last_error='priority_refresh_failed',
                lease_expires_at=NULL,
                next_run_at=now()+make_interval(secs=>:delay) WHERE id=:id AND worker_id=:worker
                AND status='running' AND lease_expires_at>now()
            """),
                {
                    "id": job["id"],
                    "worker": worker,
                    "status": "failed" if job["attempts"] >= 3 else "pending",
                    "delay": min(60, 2 ** job["attempts"]),
                },
            )
    return True
