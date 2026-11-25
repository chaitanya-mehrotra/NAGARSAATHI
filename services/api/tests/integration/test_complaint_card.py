from uuid import uuid4

import pytest
from app.main import create_app
from app.routes.complaints_routes import status_hint
from app.settings import Settings
from fastapi.testclient import TestClient
from sqlalchemy import text


def test_status_hint_is_a_coarse_code_never_the_raw_reason():
    assert status_hint("out_of_scope", "visual_accepted_location_outside_pilot") == "outside_pilot"
    assert status_hint("out_of_scope", "photo_needs_review") == "outside_pilot"
    assert status_hint("awaiting_review", "claimed_category_conflict_or_manual_category") == "category_conflict"
    assert status_hint("awaiting_review", "photo_needs_review") == "photo_unclear"
    assert status_hint("awaiting_review", "location_quality_requires_review") == "location_unclear"
    assert status_hint("awaiting_review", "provider_error") == "check_failed"
    assert status_hint("awaiting_review", None) == "waiting"
    assert status_hint("rejected", None) == "photo_rejected"
    assert status_hint("admitted", None) is None


@pytest.fixture
def card_api(spatial_database, tmp_path):
    engine, base = spatial_database
    settings = Settings(
        _env_file=None, app_mode="test", database_url=base.database_url, storage_root=tmp_path / "m"
    )
    with TestClient(create_app(settings, engine=engine)) as client:
        yield client, engine


def test_list_returns_area_name_and_hint_but_not_the_raw_reason(card_api):
    client, engine = card_api
    body = client.post("/api/v1/auth/demo-login", json={"account_type": "admin"}).json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    marker = "card-" + uuid4().hex[:8]
    with engine.begin() as connection:
        area = connection.execute(
            text("SELECT id, boundary_version, display_name FROM areas WHERE code='southwest'")
        ).mappings().one()
        connection.execute(
            text("""
                INSERT INTO reports (id, public_reference, reporter_id, description, claimed_category, state,
                    review_reason, confirmed_point, area_id, boundary_version)
                VALUES (:id, :ref, :u, :d, 'pothole', 'awaiting_review', 'photo_needs_review',
                    ST_SetSRID(ST_MakePoint(77.62, 12.92), 4326)::geography, :a, :bv)
            """),
            {"id": uuid4(), "ref": "NS-" + uuid4().hex.upper(), "u": body["user"]["id"], "d": marker,
             "a": area["id"], "bv": area["boundary_version"]},
        )
    items = client.get("/api/v1/complaints", params={"search": marker}, headers=headers).json()["items"]
    assert len(items) == 1
    assert items[0]["area_name"] == area["display_name"]
    assert items[0]["status_hint"] == "photo_unclear"
    assert "raw_review_reason" not in items[0] and "report_state" not in items[0]
