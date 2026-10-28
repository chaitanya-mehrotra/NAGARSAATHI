from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from app.main import create_app
from app.schemas import ValidationResult
from app.settings import PROJECT_ROOT, Settings
from fastapi.testclient import TestClient
from pydantic import ValidationError


def settings_for_test(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(_env_file=None, app_mode="test", storage_root=tmp_path / "media", **overrides)


def test_public_config_and_health(tmp_path: Path) -> None:
    app = create_app(settings_for_test(tmp_path), database_probe=lambda _: True)
    with TestClient(app) as client:
        assert client.get("/api/v1/health/live").json()["status"] == "ok"
        assert client.get("/api/v1/health/ready").status_code == 200
        response = client.get("/api/v1/config/public")
        assert response.headers["X-Request-ID"]
        config = response.json()
        assert config["synthetic"] is True
        assert config["pilot"]["boundary_reviewed"] is False
        assert len(config["pilot"]["service_areas"]) == 6
        assert len(config["categories"]) == 5


def test_readiness_does_not_claim_database_is_healthy(tmp_path: Path) -> None:
    app = create_app(settings_for_test(tmp_path), database_probe=lambda _: False)
    with TestClient(app) as client:
        assert client.get("/api/v1/health/live").status_code == 200
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.json()["checks"] == {"postgis": False, "storage": True}


@pytest.mark.parametrize("auth,validator", [("demo", "human_review"), ("oidc", "fixture")])
def test_production_rejects_demo_sources(auth: str, validator: str) -> None:
    with pytest.raises(ValidationError, match="Production forbids"):
        Settings(
            _env_file=None, app_mode="production", auth_provider=auth, validation_provider=validator
        )


def test_production_cannot_start_before_adapters_are_implemented(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        app_mode="production",
        auth_provider="oidc",
        validation_provider="human_review",
        oidc_issuer="https://identity.example.invalid",
        oidc_audience="nagarsaathi",
        oidc_jwks_url="https://identity.example.invalid/jwks",
        boundaries_reviewed=True,
        category_rules_reviewed=True,
        jwt_secret="x" * 48,
        storage_root=tmp_path,
    )
    with pytest.raises(RuntimeError, match="not implemented"):
        with TestClient(create_app(settings)):
            pass


def test_error_contract_does_not_expose_internal_details(tmp_path: Path) -> None:
    with TestClient(create_app(settings_for_test(tmp_path))) as client:
        response = client.get("/api/v1/not-an-endpoint")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"
        assert response.json()["request_id"] == response.headers["X-Request-ID"]
        assert "traceback" not in response.text.lower()


def test_human_review_requires_null_confidence_and_current_evidence_reference() -> None:
    result = dict(
        report_id=uuid4(),
        media_id=uuid4(),
        report_revision=1,
        media_sha256="a" * 64,
        request_id=uuid4(),
        provider="human_review",
        provider_version="review-policy-v1",
        decision="accepted",
        reviewer_id=uuid4(),
        completed_at=datetime.now(UTC),
        labels=[{"label": "pothole", "confidence": None}],
    )
    assert ValidationResult.model_validate(result).labels[0].confidence is None
    with pytest.raises(ValidationError, match="confidence must be null"):
        ValidationResult.model_validate(
            {**result, "labels": [{"label": "pothole", "confidence": 1}]}
        )
    with pytest.raises(ValidationError):
        ValidationResult.model_validate({**result, "media_sha256": "invalid"})


def test_demo_fixture_contains_no_live_credentials() -> None:
    import json

    fixture = json.loads((PROJECT_ROOT / "fixtures/identities.json").read_text())
    assert fixture["synthetic"] is True
    assert all(identity["subject"].startswith("demo-") for identity in fixture["identities"])
    for identity in fixture["identities"]:
        assert set(identity) == {"subject", "display_name", "roles"}


def test_unexpected_failure_is_structured_and_private(tmp_path: Path) -> None:
    def broken_dependency(_: Settings) -> bool:
        raise RuntimeError("private provider detail")

    app = create_app(settings_for_test(tmp_path), database_probe=broken_dependency)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 500
        assert response.json()["code"] == "internal_error"
        assert "private provider detail" not in response.text
        assert response.json()["request_id"] == response.headers["X-Request-ID"]
