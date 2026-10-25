import json
from datetime import UTC, datetime
from typing import Any

from app.schemas import ValidationRequest, ValidationResult
from app.settings import PROJECT_ROOT, Settings


class FixtureValidator:
    """Only an explicitly catalogued synthetic hash can receive a fixture decision."""

    def __init__(self, settings: Settings, catalog: dict[str, Any] | None = None) -> None:
        if settings.app_mode not in {"demo", "test"}:
            raise ValueError("Fixture validation is forbidden outside demo/test mode")
        self.catalog = catalog or json.loads(
            (PROJECT_ROOT / "fixtures/photo-validation.json").read_text()
        )

    async def validate(self, request: ValidationRequest) -> ValidationResult:
        item = self.catalog["photos"].get(
            request.media_sha256,
            {
                "decision": "needs_review",
                "labels": [],
                "reason": "Photo is not an approved synthetic fixture",
            },
        )
        return ValidationResult(
            **request.model_dump(),
            provider="fixture",
            provider_version=self.catalog["version"],
            completed_at=datetime.now(UTC),
            **item,
        )


class HumanDecisionRequired(Exception):
    pass


class HumanReviewValidator:
    async def validate(self, request: ValidationRequest) -> ValidationResult:
        raise HumanDecisionRequired("A provisioned reviewer must inspect this photo")
