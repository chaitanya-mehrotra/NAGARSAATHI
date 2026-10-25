from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.adapters.validation import FixtureValidator, HumanReviewValidator
from app.domain.validation import store_result
from app.jobs import claim, fail_job, finish, process_once
from app.main import create_app
from app.schemas import ValidationResult
from app.settings import Settings
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_intake import auth, body, photo_bytes, submit, upload


@pytest.fixture
def validation_api(spatial_database, tmp_path):
    engine, base = spatial_database
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE jobs SET next_run_at=now()+interval '10 years' "
            "WHERE type='validate_report' AND status='pending'"
        )
    settings = Settings(
        _env_file=None,
        app_mode="test",
        database_url=base.database_url,
        storage_root=tmp_path / "media",
    )
    with TestClient(create_app(settings, engine=engine)) as client:
        yield client, engine, settings


def fixture_adapter(engine, settings, media_id, decision="accepted", labels=None):
    with engine.connect() as connection:
        digest = connection.execute(
            text("SELECT original_sha256 FROM media WHERE id=:id"), {"id": media_id}
        ).scalar_one()
    return FixtureValidator(
        settings,
        {
            "version": "demo-photos-v1",
            "photos": {
                digest: {
                    "decision": decision,
                    "labels": labels
                    if labels is not None
                    else [{"label": "D40", "confidence": 0.9}],
                    "reason": "Explicit synthetic fixture",
                }
            },
        },
    )


def report_response(client, report_id):
    return client.get(f"/api/v1/reports/{report_id}", headers=auth()).json()


@pytest.mark.parametrize(
    "decision,labels,status,reason",
    [
        (
            "accepted",
            [{"label": "D40", "confidence": 0.9}],
            "accepted",
            "validated_awaiting_issue_review",
        ),
        ("accepted", [{"label": "mystery", "confidence": 0.9}], "needs_review", "unknown_label"),
        (
            "accepted",
            [{"label": "garbage", "confidence": 0.8}],
            "needs_review",
            "claimed_category_conflict",
        ),
        ("needs_review", [], "needs_review", "photo_needs_review"),
        ("rejected", [], "rejected", "photo_rejected"),
        ("error", [], "error", "provider_error"),
    ],
)
def test_provider_paths(validation_api, decision, labels, status, reason):
    client, engine, settings = validation_api
    media = upload(client)
    report = submit(client, body(media)).json()
    assert process_once(engine, fixture_adapter(engine, settings, media, decision, labels))
    current = report_response(client, report["id"])
    assert current["validation_status"] == status
    assert reason in current["review_reason"]
    assert current["state"] != "admitted"


def test_contradictory_photos_and_default_human_path(validation_api):
    client, engine, settings = validation_api
    one = upload(client)
    two = upload(client, content=photo_bytes((13, 8)))
    report = submit(client, {**body(one), "media_ids": [one, two]}).json()
    with engine.connect() as connection:
        rows = (
            connection.execute(
                text("SELECT original_sha256,id FROM media WHERE id=ANY(:ids)"),
                {"ids": [UUID(one), UUID(two)]},
            )
            .mappings()
            .all()
        )
    catalog = {
        "version": "demo-photos-v1",
        "photos": {
            r["original_sha256"]: {
                "decision": "accepted",
                "labels": [
                    {"label": "pothole" if str(r["id"]) == one else "garbage", "confidence": 0.8}
                ],
            }
            for r in rows
        },
    }
    process_once(engine, FixtureValidator(settings, catalog))
    assert report_response(client, report["id"])["review_reason"] == "contradictory_photos"
    second = submit(client, body(upload(client))).json()
    process_once(engine, HumanReviewValidator())
    assert report_response(client, second["id"])["review_reason"] == "human_review_required"


def test_visual_acceptance_without_pin_does_not_admit(validation_api):
    client, engine, settings = validation_api
    media = upload(client)
    report = submit(client, {**body(media), "location": {}}).json()
    process_once(engine, fixture_adapter(engine, settings, media))
    current = report_response(client, report["id"])
    assert current["validation_status"] == "accepted" and current["area_code"] is None
    assert "missing_coordinates" in current["review_reason"]


def test_stale_hash_revision_and_repeated_callback(validation_api):
    client, engine, _ = validation_api
    media = upload(client)
    report = submit(client, body(media)).json()
    with engine.begin() as connection:
        digest = connection.execute(
            text("SELECT original_sha256 FROM media WHERE id=:id"), {"id": media}
        ).scalar_one()
        values = {
            "report_id": report["id"],
            "media_id": media,
            "report_revision": 1,
            "media_sha256": digest,
            "request_id": uuid4(),
            "provider": "fixture",
            "provider_version": "demo-photos-v1",
            "decision": "accepted",
            "completed_at": datetime.now(UTC),
            "labels": [{"label": "D40", "confidence": 0.9}],
        }
        good = ValidationResult.model_validate(values)
        assert not store_result(connection, good.model_copy(update={"media_sha256": "a" * 64}))
        assert store_result(connection, good) and store_result(connection, good)
        with pytest.raises(HTTPException):
            store_result(connection, good.model_copy(update={"decision": "rejected"}))
        connection.execute(
            text("UPDATE reports SET content_revision=2 WHERE id=:id"), {"id": report["id"]}
        )
        assert not store_result(connection, good)
        assert (
            connection.execute(
                text("SELECT count(*) FROM validation_results WHERE report_id=:id"),
                {"id": report["id"]},
            ).scalar_one()
            == 1
        )


def test_provider_exception_and_missing_label_retry_then_failure(validation_api):
    client, engine, settings = validation_api
    media = upload(client)
    report = submit(client, body(media)).json()
    invalid = fixture_adapter(engine, settings, media, labels=[])
    for _ in range(3):
        process_once(engine, invalid)
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE jobs SET next_run_at=now() WHERE payload->>'report_id'=:id"),
                {"id": report["id"]},
            )
    assert report_response(client, report["id"])["state"] == "processing_failed"
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT attempts FROM jobs WHERE payload->>'report_id'=:id"),
                {"id": report["id"]},
            ).scalar_one()
            == 3
        )


def decision(report, **overrides):
    return {
        "expected_revision": report["content_revision"],
        "request_id": str(uuid4()),
        "decision": "accepted",
        "category": "pothole",
        "reason": "Reviewed explicit demo evidence",
        **overrides,
    }


def test_review_scope_audit_retry_reclassification_and_stale_job(validation_api):
    client, engine, settings = validation_api
    media = upload(client)
    report = submit(client, body(media)).json()
    payload = decision(report, category="garbage_accumulation")
    url = f"/api/v1/reviews/{report['id']}/decision"
    assert client.post(url, json=payload, headers=auth()).status_code == 403
    first = client.post(url, json=payload, headers=auth("demo-reviewer"))
    assert first.status_code == 200, first.text
    second = client.post(url, json=payload, headers=auth("demo-reviewer"))
    assert second.json() == first.json()
    assert first.json()["canonical_category"] == "garbage_accumulation"
    assert client.post(url, json=decision(report), headers=auth("demo-reviewer")).status_code == 409
    process_once(engine, fixture_adapter(engine, settings, media))
    assert report_response(client, report["id"])["canonical_category"] == "garbage_accumulation"
    with engine.connect() as connection:
        rows = (
            connection.execute(
                text("SELECT * FROM validation_results WHERE report_id=:id"), {"id": report["id"]}
            )
            .mappings()
            .all()
        )
        assert (
            len(rows) == 1
            and rows[0]["provider"] == "human_review"
            and rows[0]["confidence"] is None
        )
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM jobs WHERE type='admit_report' "
                    "AND payload->>'report_id'=:id"
                ),
                {"id": report["id"]},
            ).scalar_one()
            == 1
        )


def test_unassigned_location_review_admin_only_and_cross_area_guard(validation_api):
    client, _, _ = validation_api
    missing = submit(client, {**body(upload(client)), "location": {}}).json()
    payload = decision(
        missing, location={"longitude": 77.615, "latitude": 12.915, "confirmed": True}
    )
    url = f"/api/v1/reviews/{missing['id']}/decision"
    assert client.post(url, json=payload, headers=auth("demo-reviewer")).status_code == 404
    assert client.post(url, json=payload, headers=auth("demo-admin")).status_code == 200
    southwest = submit(client, body(upload(client))).json()
    payload = decision(
        southwest, location={"longitude": 77.675, "latitude": 12.945, "confirmed": True}
    )
    assert (
        client.post(
            f"/api/v1/reviews/{southwest['id']}/decision",
            json=payload,
            headers=auth("demo-reviewer"),
        ).status_code
        == 403
    )
    assert client.get("/api/v1/reviews", headers=auth()).status_code == 403


def test_lease_reclaim_and_stale_worker_cannot_finish(validation_api):
    client, engine, settings = validation_api
    media = upload(client)
    report = submit(client, body(media)).json()
    old = claim(engine, "abandoned")
    assert old
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE jobs SET lease_expires_at=now()-interval '1 second' WHERE id=:id"),
            {"id": old["id"]},
        )
    assert process_once(engine, fixture_adapter(engine, settings, media), "replacement")
    with engine.begin() as connection:
        finish(connection, old["id"], "abandoned")
        fail_job(connection, old, "abandoned", "late_failure")
    assert report_response(client, report["id"])["validation_status"] == "accepted"
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT worker_id FROM jobs WHERE id=:id"), {"id": old["id"]}
            ).scalar_one()
            == "replacement"
        )


def test_fixture_adapter_production_guard(validation_api):
    _, _, settings = validation_api
    with pytest.raises(ValueError, match="forbidden"):
        FixtureValidator(settings.model_copy(update={"app_mode": "production"}))
