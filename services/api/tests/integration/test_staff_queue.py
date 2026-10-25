from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.domain.priority import refresh
from sqlalchemy import text
from test_intake import auth
from test_issues import ADMIN, accepted, choose, issue
from test_issues import issue_api as issue_api
from test_priority import refresh_record


def queue(client, **params):
    response = client.get("/api/v1/staff/queue", params=params, headers=ADMIN)
    assert response.status_code == 200, response.text
    return response.json()


def test_counts_scope_filters_and_empty_areas(issue_api):
    client, engine = issue_api
    first = accepted(issue_api)
    second = accepted(issue_api)
    assert choose(client, second, "link", issue(client, first)).status_code == 200
    outside = accepted(issue_api, lon=77.65)
    refresh_record(engine, first)
    refresh_record(engine, outside)
    result = queue(client, area="southwest", category="pothole")
    assert (
        result["total_issues"],
        result["total_linked_reports"],
        result["eligible_reporter_issue_pairs"],
    ) == (1, 2, 1)
    assert result["items"][0]["issue"]["report_count"] == 2
    assert queue(client, bbox="77.60,12.90,77.63,12.93")["total_issues"] == 1
    assert queue(client, band="pending")["total_issues"] == 0
    assert queue(client, status="assigned")["total_issues"] == 0
    reviewer = auth("demo-reviewer")
    scoped = client.get("/api/v1/staff/queue", headers=reviewer).json()
    assert scoped["total_issues"] == 1
    overview = client.get("/api/v1/areas/summary", headers=reviewer).json()
    assert {r["area_code"] for r in overview} == {"southwest"}
    assert sum(r["active_issues"] for r in overview) == 1
    assert sum(r["linked_reports"] for r in overview) == 2
    assert any(r["active_issues"] == 0 for r in overview)
    assert client.get(f"/api/v1/issues/{outside['issue_id']}", headers=reviewer).status_code == 404
    outside_reference = issue(client, outside)["public_reference"]
    assert (
        client.get(
            "/api/v1/issues", params={"reference": outside_reference}, headers=reviewer
        ).json()
        == []
    )
    assert (
        client.get("/api/v1/issues", params={"reference": outside_reference}, headers=ADMIN).json()[
            0
        ]["id"]
        == outside["issue_id"]
    )
    for who in ["demo-citizen", "demo-operator"]:
        assert client.get("/api/v1/staff/queue", headers=auth(who)).status_code == 403
        assert client.get("/api/v1/areas/summary", headers=auth(who)).status_code == 403


def test_frozen_paging_survives_score_and_assignment_changes(issue_api):
    client, engine = issue_api
    first = accepted(issue_api)
    second = accepted(issue_api, lon=77.62)
    for record in [first, second]:
        refresh_record(engine, record)
    initial = queue(client, limit=1)
    captured = initial["items"][0]["issue"]
    other = second if captured["id"] == first["issue_id"] else first
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE issues SET severity_override=1,row_version=row_version+1 WHERE id=:id"),
            {"id": other["issue_id"]},
        )
    refresh_record(engine, other)
    next_page = queue(client, limit=1, cursor=initial["next_cursor"])
    assert next_page["items"][0]["issue"]["id"] == other["issue_id"]
    assert next_page["items"][0]["changed_since_capture"]
    assert next_page["next_cursor"] is None
    again = queue(client, limit=1, cursor=initial["next_cursor"])
    assert again["items"] == next_page["items"]
    assert (
        client.get(
            "/api/v1/staff/queue",
            params={"cursor": initial["next_cursor"], "overdue": True},
            headers=ADMIN,
        ).status_code
        == 409
    )
    assert (
        client.get(
            "/api/v1/staff/queue",
            params={"cursor": initial["next_cursor"]},
            headers=auth("demo-reviewer"),
        ).status_code
        == 404
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE staff_queue_sessions SET expires_at=now()-interval '1 second'"
        )
    assert (
        client.get(
            "/api/v1/staff/queue", params={"cursor": initial["next_cursor"]}, headers=ADMIN
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "params",
    [
        {"bbox": "NaN,0,1,1"},
        {"bbox": "0,0,1"},
        {"bbox": "2,0,1,1"},
        {"area": "unknown"},
        {"category": "unknown"},
        {"status": "invalid"},
        {"band": "invalid"},
        {"cursor": "invalid"},
        {"limit": 51},
    ],
)
def test_invalid_filters(issue_api, params):
    client, _ = issue_api
    assert client.get("/api/v1/staff/queue", params=params, headers=ADMIN).status_code == 422


def test_assignment_versions_permissions_idempotency_and_audit(issue_api):
    client, engine = issue_api
    first = accepted(issue_api)
    refresh_record(engine, first)
    current = issue(client, first)
    path = f"/api/v1/issues/{current['id']}"
    choices = client.get(path + "/assignees", headers=ADMIN)
    assert choices.status_code == 200, choices.text
    operator = choices.json()[0]["id"]
    body = {
        "request_id": str(uuid4()),
        "expected_version": current["row_version"],
        "operator_id": operator,
        "team": "Road maintenance",
        "reason": "Assign to scoped road operator",
    }
    saved = client.post(path + "/assign", json=body, headers=ADMIN)
    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == "assigned" and saved.json()["priority"]["stale"]
    assert saved.json()["assigned_operator_id"] == operator
    assert client.post(path + "/assign", json=body, headers=ADMIN).json() == saved.json()
    body["request_id"] = str(uuid4())
    assert client.post(path + "/assign", json=body, headers=ADMIN).status_code == 409
    body["expected_version"] = saved.json()["row_version"]
    body["operator_id"] = str(uuid4())
    assert client.post(path + "/assign", json=body, headers=ADMIN).status_code == 422
    body.update(operator_id=None, team=None, request_id=str(uuid4()))
    assert client.post(path + "/assign", json=body, headers=ADMIN).json()["status"] == "open"
    assert client.post(path + "/assign", json=body, headers=auth()).status_code == 403
    with engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM audit_events "
                    "WHERE entity_id=:id AND operation='assign_issue'"
                ),
                {"id": UUID(current["id"])},
            ).scalar_one()
            == 2
        )


def test_empty_queue_and_overdue_area_counts(issue_api):
    client, engine = issue_api
    assert queue(client)["items"] == []
    first = accepted(issue_api)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE issues SET first_accepted_at=now()-interval '120 hours' WHERE id=:id"),
            {"id": first["issue_id"]},
        )
    refresh_record(engine, first)
    assert queue(client, overdue=True)["total_issues"] == 1
    overview = client.get("/api/v1/areas/summary", headers=ADMIN).json()
    row = next(r for r in overview if r["area_code"] == "southwest" and r["category"] == "pothole")
    assert row["overdue_issues"] == 1 and row["oldest_age_hours"] >= 120


def test_tied_scores_use_uuid_order_and_grant_epoch_changes_require_refresh(issue_api):
    client, engine = issue_api
    records = [accepted(issue_api), accepted(issue_api, lon=77.62)]
    now = datetime.now(UTC)
    with engine.begin() as connection:
        for record in records:
            connection.execute(
                text("UPDATE issues SET first_accepted_at=:at WHERE id=:id"),
                {"id": record["issue_id"], "at": now - timedelta(hours=1)},
            )
            revision = connection.execute(
                text("SELECT row_version FROM issues WHERE id=:id"), {"id": record["issue_id"]}
            ).scalar_one()
            assert refresh(connection, UUID(record["issue_id"]), revision, as_of=now)
    full = queue(client)
    assert (
        full["items"][0]["issue"]["priority"]["score"]
        == full["items"][1]["issue"]["priority"]["score"]
    )
    assert [r["issue"]["id"] for r in full["items"]] == sorted(r["issue_id"] for r in records)
    reviewer = auth("demo-reviewer")
    captured = client.get("/api/v1/staff/queue?limit=1", headers=reviewer).json()
    with engine.begin() as connection:
        connection.exec_driver_sql("""INSERT INTO user_roles(user_id,role,area_id)
          SELECT u.id,'reviewer',a.id FROM users u CROSS JOIN areas a
          WHERE u.auth_subject='demo-reviewer' AND a.code='south_central'""")
    assert (
        client.get(
            "/api/v1/staff/queue", params={"cursor": captured["next_cursor"]}, headers=reviewer
        ).status_code
        == 409
    )
    captured = queue(client, limit=1)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE priority_epochs SET state='retired' WHERE state='active'"
        )
    assert (
        client.get(
            "/api/v1/staff/queue", params={"cursor": captured["next_cursor"]}, headers=ADMIN
        ).status_code
        == 409
    )
