from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from app.domain.issues import admit
from app.domain.priority import (
    activate,
    active_epoch,
    location_context,
    policy_from,
    preview,
    process_priority_once,
    refresh,
    schedule_age_refresh,
    snapshot,
    view,
)
from app.domain.scoring import score
from app.priority_schemas import CategoryPolicy, Policy, ScoreInputs
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from test_intake import auth, body, submit, upload
from test_issues import ADMIN, accepted, choose, issue, merge_body
from test_issues import issue_api as issue_api


def refresh_record(engine, record):
    with engine.begin() as connection:
        row = (
            connection.execute(
                text("SELECT * FROM issues WHERE id=:id"), {"id": record["issue_id"]}
            )
            .mappings()
            .one()
        )
        assert refresh(connection, row["id"], row["row_version"])
        return view(connection, row["id"])


def test_snapshot_explanation_reporter_abuse_and_model_independence(issue_api):
    client, engine = issue_api
    first = accepted(issue_api)
    initial = refresh_record(engine, first)
    assert initial is not None and initial.factors["R"] == 0
    assert initial.factors["L"] == 0.5 and initial.provisional
    with engine.connect() as connection:
        source = {k: v for k, v in initial.inputs.items() if k in ScoreInputs.model_fields}
        assert (
            score(
                ScoreInputs.model_validate(source), Policy.model_validate(initial.inputs["policy"])
            ).score
            == initial.score
        )
    again = accepted(issue_api)
    assert choose(client, again, "link", issue(client, first)).status_code == 200
    updated = refresh_record(engine, first)
    assert updated.factors["R"] == 0 and updated.inputs["eligible_reporters"] == 1
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE validation_results SET confidence=.01 WHERE provider<>'human_review'"
        )
    assert refresh_record(engine, first).factors["S"] == initial.factors["S"]


def test_incomplete_coverage_absence_and_school_outside_pilot_margin(issue_api):
    client, engine = issue_api
    first = accepted(issue_api, lon=77.6001, lat=12.925)
    with engine.begin() as connection:
        current = active_epoch(connection, UUID("48802b5c-8ad9-5089-b3ab-6d1eac37ffd8"))
        policy = policy_from(current)
        assert not location_context(
            connection, UUID(first["issue_id"]), current["poi_snapshot_id"], policy
        )["coverage_complete"]
        complete = connection.execute(
            text("""INSERT INTO poi_snapshots(version,coverage,source,
          source_date,synthetic,coverage_complete,coverage_notes)
          SELECT :version,coverage,'complete-test',source_date,true,true,'Explicit complete fixture'
          FROM poi_snapshots WHERE id=:id RETURNING id"""),
            {"version": uuid4().hex, "id": current["poi_snapshot_id"]},
        ).scalar_one()
        connection.execute(
            text("""INSERT INTO pois(snapshot_id,source_id,name,type,geom,synthetic)
          SELECT :id,source_id,name,type,geom,true FROM pois WHERE snapshot_id=:source"""),
            {"id": complete, "source": current["poi_snapshot_id"]},
        )
        context = location_context(connection, UUID(first["issue_id"]), complete, policy)
        assert context["coverage_complete"] and 0 < context["school_distance_m"] < 60
        empty = connection.execute(
            text("""INSERT INTO poi_snapshots(version,coverage,source,
          source_date,synthetic,coverage_complete,coverage_notes)
          SELECT :version,coverage,'empty-test',source_date,true,true,'Complete with no features'
          FROM poi_snapshots WHERE id=:id RETURNING id"""),
            {"version": uuid4().hex, "id": complete},
        ).scalar_one()
        context = location_context(connection, UUID(first["issue_id"]), empty, policy)
        assert context["coverage_complete"] and context["school_distance_m"] is None


def test_stale_job_requeues_keeps_last_score_and_age_refresh_is_bounded(issue_api):
    client, engine = issue_api
    record = accepted(issue_api)
    initial = refresh_record(engine, record)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE issues SET row_version=row_version+1 WHERE id=:id"),
            {"id": record["issue_id"]},
        )
        assert not refresh(connection, UUID(record["issue_id"]), initial.issue_revision)
        stale = view(connection, UUID(record["issue_id"]))
        assert stale.stale and stale.score == initial.score
        assert (
            connection.exec_driver_sql(
                "SELECT count(*) FROM jobs WHERE type='refresh_priority'"
            ).scalar_one()
            >= 2
        )
    assert schedule_age_refresh(engine, datetime.now(UTC) + timedelta(minutes=16), limit=1) == 1
    refresh_record(engine, record)
    assert view_after(engine, record).stale is False


def view_after(engine, record):
    with engine.connect() as connection:
        return view(connection, UUID(record["issue_id"]))


def test_policy_preview_atomic_activation_stale_epoch_and_immutable_data(issue_api):
    client, engine = issue_api
    one = accepted(issue_api)
    two = accepted(issue_api, lon=77.62)
    refresh_record(engine, one)
    refresh_record(engine, two)
    with engine.begin() as connection:
        current = active_epoch(connection, UUID("48802b5c-8ad9-5089-b3ab-6d1eac37ffd8"))
        policy = policy_from(current).model_copy(update={"version": "test-policy-v2"})
        policy.categories["pothole"] = CategoryPolicy(severity=0.8, target_hours=72)
        proposed = preview(
            connection,
            current["pilot_id"],
            policy,
            current["poi_snapshot_id"],
            datetime.now(UTC),
            None,
            "Review new policy fixture",
        )
        assert view(connection, UUID(one["issue_id"])).epoch_id == current["id"]
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("activation failed after first snapshot")
        return snapshot(*args, **kwargs)

    with patch("app.domain.priority.snapshot", side_effect=fail_second):
        with pytest.raises(RuntimeError), engine.begin() as connection:
            activate(connection, proposed, current["id"], None, "Fail atomically")
    assert view_after(engine, one).epoch_id == current["id"]
    with engine.begin() as connection:
        activate(connection, proposed, current["id"], None, "Reviewed synthetic ranking")
        assert view(connection, UUID(one["issue_id"])).epoch_id == proposed
        assert view(connection, UUID(two["issue_id"])).epoch_id == proposed
        assert view(connection, UUID(one["issue_id"])).factors["S"] == 0.8
        assert not refresh(
            connection,
            UUID(one["issue_id"]),
            view(connection, UUID(one["issue_id"])).issue_revision,
            current["id"],
        )
    for table in ("priority_policies", "priority_snapshots", "poi_snapshots"):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.exec_driver_sql(f"DELETE FROM {table}")
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql(
                "SELECT count(*) FROM priority_epochs WHERE state='active'"
            ).scalar_one()
            == 1
        )


def test_priority_decision_scope_critical_expiry_and_rapid_hazard_review(issue_api):
    client, engine = issue_api
    media = upload(client)
    payload = body(media)
    payload["reported_hazard"] = True
    submitted = submit(client, payload).json()
    urgent = client.get("/api/v1/priority/rapid-review", headers=ADMIN)
    assert urgent.status_code == 200 and urgent.json()[0]["id"] == submitted["id"]
    record = accepted(issue_api, lon=77.62)
    detail = issue(client, record)
    decision = {
        "request_id": str(uuid4()),
        "expected_version": detail["row_version"],
        "severity_override": 0.75,
        "urgency_override": 1,
        "critical_override": True,
        "critical_review_due_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "reason": "Inspected immediate physical danger in fixture",
    }
    endpoint = f"/api/v1/priority/issues/{record['issue_id']}/decision"
    assert client.post(endpoint, json=decision, headers=auth()).status_code == 403
    accepted_decision = client.post(endpoint, json=decision, headers=ADMIN)
    assert accepted_decision.status_code == 200, accepted_decision.text
    assert accepted_decision.json()["priority"]["band"] == "critical"
    assert client.post(endpoint, json=decision, headers=ADMIN).json() == accepted_decision.json()
    stale = dict(decision, request_id=str(uuid4()))
    assert client.post(endpoint, json=stale, headers=ADMIN).status_code == 409
    with engine.connect() as connection:
        expired = view(connection, UUID(record["issue_id"]), datetime.now(UTC) + timedelta(hours=2))
        assert expired.band == "critical" and "critical_review_overdue" in expired.flags
    queue = client.get("/api/v1/priority/ranking", headers=ADMIN)
    assert queue.status_code == 200, queue.text
    assert queue.json()[0]["id"] == record["issue_id"]
    assert (
        client.get(
            "/api/v1/priority/ranking?area=southwest&category=pothole", headers=ADMIN
        ).json()[0]["priority"]["score"]
        == accepted_decision.json()["priority"]["score"]
    )


def test_priority_worker_failure_preserves_snapshot_and_merge_refresh_changes_revision(issue_api):
    client, engine = issue_api
    first = accepted(issue_api)
    second = accepted(issue_api, lon=77.62)
    old = refresh_record(engine, first)
    with patch("app.domain.priority.refresh", side_effect=RuntimeError("provider error")):
        assert process_priority_once(engine, "failed-worker")
    assert view_after(engine, first).score == old.score
    a, b = issue(client, first), issue(client, second)
    response = client.post(f"/api/v1/issues/{b['id']}/merge", headers=ADMIN, json=merge_body(b, a))
    assert response.status_code == 200, response.text
    assert view_after(engine, first).stale
    new = refresh_record(engine, first)
    assert not new.stale and new.issue_revision > old.issue_revision


def test_split_and_reclassification_refresh_correct_issue_category_and_counts(issue_api):
    client, engine = issue_api
    one = accepted(issue_api)
    two = accepted(issue_api, lon=77.62)
    a, b = issue(client, one), issue(client, two)
    merged = client.post(
        f"/api/v1/issues/{b['id']}/merge", headers=ADMIN, json=merge_body(b, a)
    ).json()
    refresh_record(engine, one)
    split = client.post(
        f"/api/v1/issues/{a['id']}/split",
        headers=ADMIN,
        json={
            "request_id": str(uuid4()),
            "expected_version": merged["row_version"],
            "report_ids": [two["id"]],
            "point": {"longitude": 77.62, "latitude": 12.915, "confirmed": True},
            "reason": "Reviewed distinct physical defect",
        },
    )
    assert split.status_code == 200, split.text
    assert view_after(engine, one).stale
    refresh_record(engine, one)
    split_report = client.get(f"/api/v1/reports/{two['id']}", headers=auth()).json()
    assert refresh_record(engine, split_report).inputs["report_count"] == 1
    revised = client.post(
        f"/api/v1/reviews/{two['id']}/decision",
        headers=ADMIN,
        json={
            "request_id": str(uuid4()),
            "expected_revision": split_report["content_revision"],
            "decision": "accepted",
            "category": "garbage_accumulation",
            "reason": "Evidence is garbage rather than a road hole",
        },
    )
    assert revised.status_code == 200, revised.text
    with engine.begin() as connection:
        admit(connection, UUID(two["id"]), revised.json()["content_revision"])
    new_report = client.get(f"/api/v1/reports/{two['id']}", headers=auth()).json()
    assert refresh_record(engine, new_report).factors["S"] == 0.45
    ranked = client.get("/api/v1/priority/ranking", headers=ADMIN).json()
    assert split_report["issue_id"] not in [item["id"] for item in ranked]
