from uuid import uuid4

import pytest
from app.main import create_app
from app.settings import Settings
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


@pytest.fixture
def audit_api(spatial_database, tmp_path):
    engine, base = spatial_database
    settings = Settings(
        _env_file=None, app_mode="test", database_url=base.database_url, storage_root=tmp_path / "m"
    )
    with TestClient(create_app(settings, engine=engine)) as client:
        yield client, engine


def sign_in(client, kind):
    body = client.post("/api/v1/auth/demo-login", json={"account_type": kind}).json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


def make_report(engine, reporter_id, point=(77.62, 12.92)):
    report_id = uuid4()
    with engine.begin() as connection:
        area = connection.execute(
            text("SELECT id, boundary_version FROM areas WHERE code='southwest'")
        ).mappings().one()
        connection.execute(
            text("""
                INSERT INTO reports (id, public_reference, reporter_id, description, claimed_category,
                    state, confirmed_point, area_id, boundary_version, canonical_category)
                VALUES (:id, :ref, :reporter, 'Deep pothole near the signal', 'pothole', 'awaiting_review',
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :area, :boundary, NULL)
            """),
            {
                "id": report_id,
                "ref": "NS-" + uuid4().hex[:8],
                "reporter": reporter_id,
                "lon": point[0],
                "lat": point[1],
                "area": area["id"],
                "boundary": area["boundary_version"],
            },
        )
    return report_id


def test_admin_override_and_dedupe_are_logged_and_history_is_append_only(audit_api):
    client, engine = audit_api
    citizen_id, citizen = sign_in(client, "citizen")
    admin_id, admin = sign_in(client, "admin")
    # A spot of its own: the fallback duplicate search deletes every same-category report within
    # 50 m, so it must not reach reports other tests left in the shared database.
    lonely = (77.5001, 12.8001)
    keep = make_report(engine, citizen_id, lonely)
    dup = make_report(engine, citizen_id, lonely)

    # This insert used to violate the table's CHECK constraint and fail the whole request.
    response = client.post(f"/api/v1/reports/{keep}/deduplicate-keep-one", headers=admin)
    assert response.status_code == 200, response.text
    log = client.get("/api/v1/audit", params={"action": "deduplication_delete"}, headers=admin).json()
    assert [e["report_id"] for e in log["events"]] == [str(dup)]
    assert log["events"][0]["details"]["primary_report_id"] == str(keep)

    with engine.begin() as connection, pytest.raises(DBAPIError):
        connection.execute(text("UPDATE moderation_events SET reason='edited'"))
    with engine.begin() as connection, pytest.raises(DBAPIError):
        connection.execute(text("DELETE FROM moderation_events"))


def test_report_history_has_submission_and_status_change_with_actor_for_staff(audit_api):
    client, engine = audit_api
    citizen_id, citizen = sign_in(client, "citizen")
    _, admin = sign_in(client, "admin")
    report = make_report(engine, citizen_id)
    changed = client.patch(
        f"/api/v1/complaints/{report}", json={"status": "rejected"}, headers=admin
    )
    assert changed.status_code == 200, changed.text
    staff = client.get(f"/api/v1/reports/{report}/history", headers=admin).json()["events"]
    actions = [e["action"] for e in staff]
    assert actions[0] == "report_submitted"
    assert staff[0]["actor_name"]
    own = client.get(f"/api/v1/reports/{report}/history", headers=citizen).json()["events"]
    assert own[0]["action"] == "report_submitted"
    # Citizens never receive staff-only fields.
    assert all(set(e) == {"occurred_at", "action", "to_state"} for e in own)


def test_citizen_cannot_read_someone_elses_history_or_the_audit_log(audit_api):
    client, engine = audit_api
    owner_id, _ = sign_in(client, "citizen")
    _, admin = sign_in(client, "admin")
    report = make_report(engine, owner_id)
    with engine.begin() as connection:
        stranger = connection.execute(
            text("INSERT INTO users (auth_subject, display_name) VALUES ('stranger', 'Other') RETURNING id")
        ).scalar_one()
    from app.auth import create_access_token

    token = create_access_token(subject="stranger", secret=client.app.state.settings.jwt_secret)
    stranger_headers = {"Authorization": f"Bearer {token}"}
    assert client.get(f"/api/v1/reports/{report}/history", headers=stranger_headers).status_code == 404
    assert client.get("/api/v1/audit", headers=stranger_headers).status_code == 403
    assert client.get("/api/v1/audit/export.csv", headers=stranger_headers).status_code == 403
    assert client.get("/api/v1/audit").status_code in (401, 403)
    assert stranger  # created above so the token resolves to a real, non-owner account
    assert client.get("/api/v1/audit", headers=admin).status_code == 200


def test_audit_filters_pagination_and_csv_formula_protection(audit_api):
    client, engine = audit_api
    citizen_id, _ = sign_in(client, "citizen")
    _, admin = sign_in(client, "admin")
    report = make_report(engine, citizen_id)
    with engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO moderation_events (report_id, action, actor_id, reason)
                    VALUES (:r, 'restore', :a, '=HYPERLINK("http://x")')"""),
            {"r": report, "a": citizen_id},
        )
    page = client.get("/api/v1/audit", params={"limit": 1}, headers=admin).json()
    assert len(page["events"]) == 1 and page["next_before"]
    nxt = client.get(
        "/api/v1/audit", params={"limit": 1, "before": page["next_before"]}, headers=admin
    ).json()
    assert nxt["events"] and nxt["events"][0]["occurred_at"] < page["events"][0]["occurred_at"] + "Z"
    assert client.get("/api/v1/audit", params={"since": "bad"}, headers=admin).status_code == 422
    assert client.get("/api/v1/audit", params={"report_id": "x"}, headers=admin).status_code == 422
    csv_body = client.get(
        "/api/v1/audit/export.csv", params={"report_id": str(report), "action": "restore"}, headers=admin
    )
    assert csv_body.headers["content-type"].startswith("text/csv")
    assert "'=HYPERLINK" in csv_body.text and ",=HYPERLINK" not in csv_body.text
