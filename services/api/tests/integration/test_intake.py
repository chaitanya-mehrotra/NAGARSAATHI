from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

import pytest
from app.adapters.local_media import LocalMedia
from app.demo_seed import seed_foundation
from app.main import create_app
from app.settings import Settings
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def auth(subject="demo-citizen"):
    return {"Authorization": "Bearer " + subject}


def photo_bytes(size=(12, 8), format="PNG", exif=None):
    output = BytesIO()
    image = Image.new("RGB", size, "red")
    image.save(output, format=format, **({"exif": exif} if exif else {}))
    return output.getvalue()


@pytest.fixture
def api(spatial_database, tmp_path):
    engine, base = spatial_database
    settings = Settings(
        _env_file=None,
        app_mode="test",
        database_url=base.database_url,
        storage_root=tmp_path / "private",
    )
    with TestClient(create_app(settings, engine=engine)) as client:
        yield client, engine, settings


def upload(client, subject="demo-citizen", content=None, complete=True):
    response = client.post(
        "/api/v1/uploads",
        content=content or photo_bytes(),
        headers={**auth(subject), "Content-Type": "image/png"},
    )
    assert response.status_code == 201, response.text
    media_id = response.json()["id"]
    if complete:
        response = client.post(f"/api/v1/uploads/{media_id}/complete", headers=auth(subject))
        assert response.status_code == 200, response.text
        assert response.json()["state"] == "ready"
    return media_id


def body(media_id, longitude=77.615, latitude=12.915):
    return {
        "description": "Synthetic road defect",
        "claimed_category": "pothole",
        "media_ids": [media_id],
        "location_source": "confirmed_pin",
        "location": {"longitude": longitude, "latitude": latitude, "confirmed": True},
        "address_text": "Fictional demo landmark",
    }


def submit(client, payload, subject="demo-citizen", key=None):
    return client.post(
        "/api/v1/reports",
        json=payload,
        headers={**auth(subject), "Idempotency-Key": key or uuid4().hex},
    )


def test_submit_survives_api_restart_and_private_media(api):
    client, engine, settings = api
    media_id = upload(client)
    response = submit(client, body(media_id))
    assert response.status_code == 201, response.text
    report = response.json()
    assert response.headers["cache-control"] == "private, no-store"
    assert report["state"] == "submitted" and report["canonical_category"] is None
    assert report["area_code"] == "southwest" and report["synthetic"]
    assert report["media"][0]["id"] == media_id
    assert "storage_key" not in response.text and "reporter_id" not in response.text
    # New app and independent SQL pool read only persisted rows and private files.
    restarted = create_app(settings)
    with TestClient(restarted) as second:
        retrieved = second.get(f"/api/v1/reports/{report['id']}", headers=auth())
        assert retrieved.status_code == 200 and retrieved.json() == report
        image = second.get(report["media"][0]["content_url"], headers=auth())
        assert image.status_code == 200 and image.headers["cache-control"] == "private, no-store"
        assert Image.open(BytesIO(image.content)).size == (12, 8)
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM media WHERE report_id=:id"), {"id": report["id"]}
            ).scalar_one()
            == 1
        )


def test_object_ownership_scoped_reviewer_and_operator(api):
    client, _, _ = api
    southwest = submit(client, body(upload(client))).json()
    northeast = submit(client, body(upload(client), 77.675, 12.945)).json()
    for report in [southwest, northeast]:
        url = f"/api/v1/reports/{report['id']}"
        assert client.get(url, headers=auth("demo-citizen-2")).status_code == 404
        assert (
            client.get(
                report["media"][0]["content_url"], headers=auth("demo-citizen-2")
            ).status_code
            == 404
        )
        assert client.get(url, headers=auth("demo-operator")).status_code == 404
        assert client.get(url, headers=auth("demo-admin")).status_code == 200
    assert (
        client.get(f"/api/v1/reports/{southwest['id']}", headers=auth("demo-reviewer")).status_code
        == 200
    )
    assert (
        client.get(southwest["media"][0]["content_url"], headers=auth("demo-reviewer")).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/reports/{northeast['id']}", headers=auth("demo-reviewer")).status_code
        == 404
    )
    assert (
        client.get(northeast["media"][0]["content_url"], headers=auth("demo-reviewer")).status_code
        == 404
    )
    mine = client.get("/api/v1/reports/mine", headers=auth("demo-citizen-2")).json()
    assert southwest["id"] not in {item["id"] for item in mine["items"]}


def test_authentication_and_role_escalation_rejected(api):
    client, _, _ = api
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me", headers=auth("made-up-admin")).status_code == 401
    assert client.get("/api/v1/me", headers=auth()).json()["grants"][0]["role"] == "citizen"
    assert (
        client.post(
            "/api/v1/uploads",
            content=photo_bytes(),
            headers={**auth("demo-reviewer"), "Content-Type": "image/png"},
        ).status_code
        == 403
    )
    payload = body(upload(client))
    for extra in [
        {"roles": ["admin"]},
        {"validated": True},
        {"state": "admitted"},
        {"canonical_category": "pothole"},
        {"priority": 100},
    ]:
        assert submit(client, {**payload, **extra}).status_code == 422
    assert submit(client, payload, "demo-admin").status_code == 403


@pytest.mark.parametrize(
    "content,mime,expected",
    [
        (b"<svg>bad</svg>", "image/svg+xml", 415),
        (b"plain text", "image/png", 422),
        (photo_bytes(), "image/jpeg", 415),
        (photo_bytes()[:30], "image/png", 422),
        (b"", "image/png", 413),
    ],
)
def test_invalid_image_type_and_decode(api, content, mime, expected):
    client, _, _ = api
    response = client.post(
        "/api/v1/uploads", content=content, headers={**auth(), "Content-Type": mime}
    )
    assert response.status_code == expected


def test_byte_pixel_and_total_limits(api):
    _, engine, settings = api
    small = settings.model_copy(
        update={"upload_max_bytes": 100, "image_max_pixels": 80, "report_max_bytes": 90}
    )
    with TestClient(create_app(small, engine=engine)) as client:
        assert (
            client.post(
                "/api/v1/uploads",
                content=b"x" * 101,
                headers={**auth(), "Content-Type": "image/png"},
            ).status_code
            == 413
        )
        assert (
            client.post(
                "/api/v1/uploads",
                content=photo_bytes((10, 10)),
                headers={**auth(), "Content-Type": "image/png"},
            ).status_code
            == 413
        )
        one = upload(client, content=photo_bytes((5, 5)))
        two = upload(client, content=photo_bytes((5, 5)))
        response = submit(client, {**body(one), "media_ids": [one, two]})
        assert response.status_code == 413


def test_expired_incomplete_cross_user_and_reused_upload(api):
    client, engine, _ = api
    incomplete = upload(client, complete=False)
    assert submit(client, body(incomplete)).status_code == 409
    assert (
        client.post(
            f"/api/v1/uploads/{incomplete}/complete", headers=auth("demo-citizen-2")
        ).status_code
        == 404
    )
    assert submit(client, body(incomplete), "demo-citizen-2").status_code == 404
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE media SET expires_at=now()-interval '1 second' WHERE id=:id"),
            {"id": incomplete},
        )
    assert client.post(f"/api/v1/uploads/{incomplete}/complete", headers=auth()).status_code == 410
    ready = upload(client)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE media SET expires_at=now()-interval '1 second' WHERE id=:id"),
            {"id": ready},
        )
    assert submit(client, body(ready)).status_code == 410
    another = upload(client)
    assert submit(client, body(another)).status_code == 201
    assert submit(client, body(another)).status_code == 409


def test_retry_and_concurrent_double_click_are_idempotent(api):
    client, engine, _ = api
    payload = body(upload(client))
    key = uuid4().hex
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: submit(client, payload, key=key), range(4)))
    assert all(response.status_code == 201 for response in responses), [r.text for r in responses]
    assert len({response.json()["id"] for response in responses}) == 1
    assert submit(client, {**payload, "description": "Changed body"}, key=key).status_code == 409
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM idempotency_records WHERE key=:key"), {"key": key}
            ).scalar_one()
            == 1
        )


def test_failed_transaction_preserves_retryable_upload(api):
    client, engine, _ = api
    payload = body(upload(client))
    key = uuid4().hex
    from app import intake

    original = intake.report_detail
    with patch("app.intake.report_detail", side_effect=RuntimeError("failure after writes")):
        # A separate client suppresses the synthetic exception to inspect the 500 response.
        with TestClient(client.app, raise_server_exceptions=False) as failing:
            assert submit(failing, payload, key=key).status_code == 500
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT report_id FROM media WHERE id=:id"), {"id": payload["media_ids"][0]}
            ).scalar_one()
            is None
        )
        assert (
            connection.execute(
                text("SELECT count(*) FROM idempotency_records WHERE key=:key"), {"key": key}
            ).scalar_one()
            == 0
        )
    assert intake.report_detail is original
    assert submit(client, payload, key=key).status_code == 201


@pytest.mark.parametrize(
    "location,expected",
    [
        ({"longitude": 77.8, "latitude": 12.915, "confirmed": True}, "out_of_scope"),
        ({}, "awaiting_review"),
        ({"longitude": 77.615, "latitude": 12.915, "confirmed": False}, "awaiting_review"),
    ],
)
def test_unlocated_and_outside_reports_remain_visible_to_owner(api, location, expected):
    client, _, _ = api
    response = submit(client, {**body(upload(client)), "location": location})
    assert response.status_code == 201, response.text
    assert response.json()["state"] == expected
    assert response.json()["area_code"] is None
    assert response.json()["location"]["confirmed"] == location.get("confirmed", False)


def test_exif_removed_from_display_and_private_storage_paths(api):
    client, engine, settings = api
    exif = Image.Exif()
    exif[0x010E] = "Private camera description"
    exif[0x0112] = 6
    content = photo_bytes(format="JPEG", exif=exif)
    response = client.post(
        "/api/v1/uploads", content=content, headers={**auth(), "Content-Type": "image/jpeg"}
    )
    assert response.status_code == 201
    media_id = response.json()["id"]
    displayed = client.get(f"/api/v1/media/{media_id}/content", headers=auth())
    image = Image.open(BytesIO(displayed.content))
    assert image.size == (8, 12) and not image.getexif()
    with engine.connect() as connection:
        key = connection.execute(
            text("SELECT storage_key FROM media WHERE id=:id"), {"id": media_id}
        ).scalar_one()
    assert LocalMedia(settings.storage_root).read(key) == content
    with pytest.raises(ValueError):
        LocalMedia(settings.storage_root).read("../../private.txt")


def test_storage_failure_does_not_persist_upload_and_corruption_blocks_submission(api):
    client, engine, settings = api
    with patch.object(LocalMedia, "put", side_effect=OSError("offline")):
        with TestClient(client.app, raise_server_exceptions=False) as failing:
            response = failing.post(
                "/api/v1/uploads",
                content=photo_bytes(),
                headers={**auth(), "Content-Type": "image/png"},
            )
            assert response.status_code == 500
    media_id = upload(client)
    with engine.connect() as connection:
        key = connection.execute(
            text("SELECT storage_key FROM media WHERE id=:id"), {"id": media_id}
        ).scalar_one()
    LocalMedia(settings.storage_root).path(key).write_bytes(b"corrupted")
    assert submit(client, body(media_id)).status_code == 503


def test_mine_cursor_is_owner_scoped(api):
    client, _, _ = api
    reports = [submit(client, body(upload(client)), key=uuid4().hex).json() for _ in range(2)]
    page = client.get("/api/v1/reports/mine?limit=1", headers=auth()).json()
    assert len(page["items"]) == 1 and page["next_cursor"]
    next_page = client.get(
        f"/api/v1/reports/mine?limit=1&cursor={page['next_cursor']}", headers=auth()
    ).json()
    assert next_page["items"][0]["id"] != page["items"][0]["id"]
    assert (
        client.get(
            f"/api/v1/reports/mine?cursor={reports[0]['id']}", headers=auth("demo-citizen-2")
        ).status_code
        == 404
    )


def test_seed_does_not_restore_revoked_demo_roles(db):
    user = db.execute(text("SELECT id FROM users WHERE auth_subject='demo-reviewer'")).scalar_one()
    db.execute(text("DELETE FROM user_roles WHERE user_id=:id"), {"id": user})
    seed_foundation(db, Settings(app_mode="test"))
    assert (
        db.execute(
            text("SELECT count(*) FROM user_roles WHERE user_id=:id"), {"id": user}
        ).scalar_one()
        == 0
    )


def test_admission_without_media_rolls_back(db, fixture_ids):
    with pytest.raises(IntegrityError, match="requires completed evidence"), db.begin_nested():
        db.execute(text("UPDATE reports SET state='admitted' WHERE id=:report"), fixture_ids)
        db.execute(
            text("""
            INSERT INTO issue_report_links (report_id,issue_id,method,rule_version)
            VALUES (:report,:issue,'new','test')
        """),
            {"report": fixture_ids["report"], "issue": fixture_ids["issues"][0]},
        )
        db.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
    assert (
        db.execute(text("SELECT state FROM reports WHERE id=:report"), fixture_ids).scalar_one()
        == "submitted"
    )


def test_oidc_claimed_admin_role_does_not_override_database(api):
    from datetime import UTC, datetime, timedelta
    from unittest.mock import Mock

    import jwt
    from app.auth import OIDCTokens
    from cryptography.hazmat.primitives.asymmetric import rsa

    _, engine, settings = api
    oidc = settings.model_copy(
        update={
            "auth_provider": "oidc",
            "oidc_issuer": "https://issuer.example.invalid",
            "oidc_audience": "nagarsaathi",
            "oidc_jwks_url": "https://issuer.example.invalid/jwks",
        }
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks = Mock()
    jwks.get_signing_key_from_jwt.return_value.key = key.public_key()
    now = datetime.now(UTC)
    signed = jwt.encode(
        {
            "sub": "demo-citizen",
            "iss": oidc.oidc_issuer,
            "aud": oidc.oidc_audience,
            "exp": now + timedelta(minutes=5),
            "iat": now,
            "roles": ["admin"],
        },
        key,
        algorithm="RS256",
    )
    with TestClient(
        create_app(oidc, engine=engine, token_verifier=OIDCTokens(oidc, jwks))
    ) as client:
        response = client.get("/api/v1/me", headers=auth(signed))
        assert response.status_code == 200
        assert response.json()["grants"][0]["role"] == "citizen"
        assert response.json()["synthetic"] is False


def test_permission_changes_apply_on_next_request(api):
    client, engine, _ = api
    with engine.begin() as connection:
        user = connection.execute(
            text("SELECT id FROM users WHERE auth_subject='demo-citizen-2'")
        ).scalar_one()
        connection.execute(text("UPDATE users SET active=false WHERE id=:id"), {"id": user})
    try:
        assert client.get("/api/v1/me", headers=auth("demo-citizen-2")).status_code == 401
    finally:
        with engine.begin() as connection:
            connection.execute(text("UPDATE users SET active=true WHERE id=:id"), {"id": user})


def test_two_different_keys_cannot_attach_one_photo_twice(api):
    client, _, _ = api
    payload = body(upload(client))
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: submit(client, payload), range(2)))
    assert sorted(response.status_code for response in responses) == [201, 409]


def test_missing_key_unknown_category_and_duplicate_photo(api):
    client, _, _ = api
    media_id = upload(client)
    payload = body(media_id)
    assert client.post("/api/v1/reports", json=payload, headers=auth()).status_code == 422
    assert submit(client, {**payload, "claimed_category": "unknown"}).status_code == 422
    assert submit(client, {**payload, "media_ids": [media_id, media_id]}).status_code == 422


def test_animated_photo_rejected(api):
    client, _, _ = api
    output = BytesIO()
    first = Image.new("RGB", (12, 8), "red")
    first.save(
        output, format="PNG", save_all=True, append_images=[Image.new("RGB", (12, 8), "blue")]
    )
    response = client.post(
        "/api/v1/uploads",
        content=output.getvalue(),
        headers={**auth(), "Content-Type": "image/png"},
    )
    assert response.status_code == 415
