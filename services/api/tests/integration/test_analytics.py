from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.main import create_app
from app.settings import Settings
from fastapi.testclient import TestClient
from sqlalchemy import text


@pytest.fixture
def stats_api(spatial_database, tmp_path):
    engine, base = spatial_database
    settings = Settings(
        _env_file=None, app_mode="test", database_url=base.database_url, storage_root=tmp_path / "m"
    )
    with TestClient(create_app(settings, engine=engine)) as client:
        yield client, engine


def sign_in(client, kind):
    body = client.post("/api/v1/auth/demo-login", json={"account_type": kind}).json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


def add_report(connection, reporter, category, received, state="awaiting_review", suspicious=False):
    area = connection.execute(
        text("SELECT id, pilot_id, boundary_version FROM areas WHERE code='southwest'")
    ).mappings().one()
    report_id = uuid4()
    connection.execute(
        text("""
            INSERT INTO reports (id, public_reference, reporter_id, description, claimed_category, state,
                confirmed_point, area_id, boundary_version, received_at, is_suspicious)
            VALUES (:id, :ref, :u, 'Test complaint text', :cat, :state,
                ST_SetSRID(ST_MakePoint(77.62, 12.92), 4326)::geography, :area, :bv, :at, :sus)
        """),
        {"id": report_id, "ref": "NS-" + uuid4().hex[:8], "u": reporter, "cat": category, "state": state,
         "area": area["id"], "bv": area["boundary_version"], "at": received, "sus": suspicious},
    )
    return report_id, area


def add_resolved_issue(connection, area, category, hours):
    issue_id = uuid4()
    accepted = datetime.now(UTC) - timedelta(hours=hours + 1)
    connection.execute(
        text("""
            INSERT INTO issues (id, public_reference, pilot_id, category_code, geom, area_id, boundary_version,
                status, first_accepted_at, most_recent_accepted_at)
            VALUES (:id, :ref, :pilot, :cat, ST_SetSRID(ST_MakePoint(77.62, 12.92), 4326)::geography,
                :area, :bv, 'resolved', :at, :at)
        """),
        {"id": issue_id, "ref": "NI-" + uuid4().hex[:10], "pilot": area["pilot_id"], "cat": category,
         "area": area["id"], "bv": area["boundary_version"], "at": accepted},
    )
    connection.execute(
        text("INSERT INTO issue_events (issue_id, action, to_state, created_at) "
             "VALUES (:i, 'verify', 'resolved', :at)"),
        {"i": issue_id, "at": accepted + timedelta(hours=hours)},
    )


def test_summary_counts_fill_quiet_days_and_respect_filters(stats_api):
    client, engine = stats_api
    citizen_id, citizen = sign_in(client, "citizen")
    _, admin = sign_in(client, "admin")
    now = datetime.now(UTC)
    with engine.begin() as connection:
        base = connection.execute(text("SELECT count(*) FROM reports WHERE deleted_at IS NULL")).scalar_one()
        add_report(connection, citizen_id, "pothole", now)
        add_report(connection, citizen_id, "pothole", now - timedelta(days=2), suspicious=True)
        _, area = add_report(connection, citizen_id, "garbage_accumulation", now - timedelta(days=40))
        add_resolved_issue(connection, area, "pothole", hours=10)
        add_resolved_issue(connection, area, "pothole", hours=30)

    assert client.get("/api/v1/analytics/summary", headers=citizen).status_code == 403

    data = client.get("/api/v1/analytics/summary", headers=admin).json()
    assert data["range"]["granularity"] == "day"
    assert len(data["volume"]) == 30
    assert data["totals"]["reports"] - base == 2          # the 40-day-old report is outside 30 days
    assert data["totals"]["flagged"] >= 1
    assert sum(b["total"] for b in data["volume"]) == data["totals"]["reports"]
    assert sum(data["by_status"].values()) == data["totals"]["reports"]
    pothole = next(r for r in data["resolution"] if r["category"] == "pothole")
    assert pothole["resolved"] == 2 and 9.9 <= pothole["median_hours"] <= 30.1
    assert pothole["median_hours"] <= pothole["p90_hours"]
    assert pothole["within_target"] <= pothole["resolved"]

    longer = client.get(
        "/api/v1/analytics/summary",
        params={"since": (now - timedelta(days=60)).date().isoformat(), "category": "garbage_accumulation"},
        headers=admin,
    ).json()
    assert longer["range"]["granularity"] == "week"
    assert [c["category"] for c in longer["by_category"]] == ["garbage_accumulation"]
    assert longer["filters"]["category"] == "garbage_accumulation"


def test_summary_validates_the_range_and_agrees_with_the_list(stats_api):
    client, engine = stats_api
    _, admin = sign_in(client, "admin")
    for params in ({"since": "nope"}, {"since": "2026-02-01", "until": "2026-01-01"},
                   {"since": "2020-01-01", "until": "2026-01-01"}):
        assert client.get("/api/v1/analytics/summary", params=params, headers=admin).status_code == 422
    data = client.get("/api/v1/analytics/summary", headers=admin).json()
    assert set(data["notes"]) >= {"reports", "backlog", "resolution"}
    # The same status rule drives the list filter, so each count matches its list total.
    for status, count in data["by_status"].items():
        listed = client.get(
            "/api/v1/complaints",
            params={"status": status, "since": data["range"]["since"], "until": data["range"]["until"], "limit": 1},
            headers=admin,
        ).json()
        assert listed["total"] == count, status
