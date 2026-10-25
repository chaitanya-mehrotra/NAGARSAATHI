from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import Category, Role, ValidationDecision


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Principal(Contract):
    subject: str
    roles: list[Role]
    area_codes: list[str] = Field(default_factory=list)


class ValidationRequest(Contract):
    report_id: UUID
    media_id: UUID
    report_revision: int = Field(ge=1)
    media_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_id: UUID


class AcceptedLabel(Contract):
    label: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)


class ValidationResult(ValidationRequest):
    schema_version: Literal["1"] = "1"
    provider: Literal["fixture", "human_review", "model"]
    provider_version: str = Field(min_length=1)
    decision: ValidationDecision
    labels: list[AcceptedLabel] = Field(default_factory=list)
    reviewer_id: UUID | None = None
    completed_at: AwareDatetime
    reason: str | None = None

    @model_validator(mode="after")
    def check_decision_evidence(self) -> Self:
        if self.decision == ValidationDecision.ACCEPTED and not self.labels:
            raise ValueError("Accepted results require labels")
        if self.provider == "human_review":
            if self.reviewer_id is None:
                raise ValueError("Human review requires reviewer_id")
            if any(label.confidence is not None for label in self.labels):
                raise ValueError("Human review confidence must be null")
        return self


class CategoryConfig(Contract):
    code: Category
    label: str
    requires_manual_categorisation: bool


class BoundingBox(Contract):
    west: float
    south: float
    east: float
    north: float


class PilotConfig(Contract):
    code: str
    name: str
    timezone: str
    boundary_version: str
    boundary_reviewed: bool
    bbox_wgs84: BoundingBox
    service_areas: list[str]


class PublicConfig(Contract):
    schema_version: Literal["1"]
    synthetic: bool
    pilot: PilotConfig
    categories: list[CategoryConfig]
    auth_provider: Literal["demo", "oidc"] = "demo"


class HealthResponse(Contract):
    status: Literal["ok", "ready", "not_ready"]
    checks: dict[str, bool] = Field(default_factory=dict)


class ErrorResponse(Contract):
    code: str
    message: str
    field_errors: list[dict[str, str]] = Field(default_factory=list)
    request_id: str
