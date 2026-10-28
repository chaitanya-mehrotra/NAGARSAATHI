import pytest
from app.main import create_app
from app.settings import Settings
from fastapi.testclient import TestClient
from sqlalchemy import text


@pytest.fixture
def google_api(spatial_database, tmp_path, monkeypatch):
    engine, base = spatial_database
    settings = Settings(
        _env_file=None,
        app_mode="test",
        database_url=base.database_url,
        storage_root=tmp_path / "media",
        google_client_id="client.apps.googleusercontent.com",
    )
    claims = {"email": "new.citizen@example.com", "name": "New Citizen", "sub": "google:123", "nonce": ""}
    monkeypatch.setattr(
        "app.routes.auth_routes.verify_google_credential", lambda credential, audience: dict(claims)
    )
    with TestClient(create_app(settings, engine=engine)) as client:
        yield client, engine, claims


def login(client, nonce=None, claims=None):
    if claims is not None and nonce is not None:
        claims["nonce"] = nonce
    return client.post("/api/v1/auth/google", json={"credential": "signed-by-google"})


def test_sign_in_needs_a_server_issued_one_use_nonce(google_api):
    client, engine, claims = google_api
    nonce = client.post("/api/v1/auth/google/challenge").json()["nonce"]
    first = login(client, nonce, claims)
    assert first.status_code == 200, first.text
    assert first.json()["user"]["role"] == "citizen"
    # The same nonce cannot be replayed with the same (or a stolen) token.
    assert login(client, nonce, claims).status_code == 401


def test_missing_unknown_and_expired_nonce_are_rejected(google_api):
    client, engine, claims = google_api
    assert login(client, "", claims).status_code == 401
    assert login(client, "never-issued", claims).status_code == 401
    nonce = client.post("/api/v1/auth/google/challenge").json()["nonce"]
    with engine.begin() as connection:
        connection.execute(text("UPDATE google_challenges SET expires_at=now()-interval '1 second'"))
    assert login(client, nonce, claims).status_code == 401


def test_challenge_requires_google_configuration(spatial_database, tmp_path):
    engine, base = spatial_database
    settings = Settings(
        _env_file=None, app_mode="test", database_url=base.database_url, storage_root=tmp_path / "m"
    )
    with TestClient(create_app(settings, engine=engine)) as client:
        assert client.post("/api/v1/auth/google/challenge").status_code == 503


def test_staff_cannot_sign_in_with_google(google_api):
    client, engine, claims = google_api
    claims["email"] = "staff@example.com"
    claims["sub"] = "google:staff"
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (auth_subject,display_name,email,role) "
                "VALUES ('staff-1','Staff','staff@example.com','admin')"
            )
        )
    nonce = client.post("/api/v1/auth/google/challenge").json()["nonce"]
    assert login(client, nonce, claims).status_code == 403
