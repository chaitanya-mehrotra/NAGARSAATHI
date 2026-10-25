import math
from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.schemas import Contract


class CategoryPolicy(Contract):
    severity: float = Field(ge=0, le=1, allow_inf_nan=False)
    target_hours: float = Field(gt=0, allow_inf_nan=False)


class Policy(Contract):
    version: str = Field(min_length=3, max_length=80)
    weights: dict[str, float] = Field(
        default_factory=lambda: {"S": 0.35, "A": 0.20, "R": 0.15, "L": 0.20, "U": 0.10}
    )
    categories: dict[str, CategoryPolicy]
    poi_radius_m: float = Field(default=200, gt=0, le=1000, allow_inf_nan=False)
    major_road_distance_m: float = Field(default=10, ge=0, le=50, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_weights(self) -> Self:
        if (
            set(self.weights) != {"S", "A", "R", "L", "U"}
            or any(not math.isfinite(v) or not 0 <= v <= 1 for v in self.weights.values())
            or not math.isclose(sum(self.weights.values()), 1, abs_tol=1e-9)
        ):
            raise ValueError("Exactly S/A/R/L/U weights must be finite, nonnegative and sum to 1")
        return self


class ScoreInputs(Contract):
    as_of: AwareDatetime
    first_accepted_at: AwareDatetime
    category: str
    eligible_reporters: int = Field(ge=0)
    recent_reporters: int = Field(default=0, ge=0)
    severity_override: float | None = Field(default=None, allow_inf_nan=False)
    urgency_override: float | None = Field(default=None, allow_inf_nan=False)
    school_distance_m: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    hospital_distance_m: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    major_road: bool = False
    coverage_complete: bool = False
    critical_override: bool = False
    critical_review_due_at: AwareDatetime | None = None


class Score(Contract):
    score: float
    band: str
    factors: dict[str, float]
    contributions: dict[str, float]
    flags: list[str]
    overdue: bool
    age_hours: float
    urgency_source: str


class PriorityView(Score):
    policy_version: str
    epoch_id: UUID
    poi_version: str
    as_of: datetime
    computed_at: datetime
    issue_revision: int
    stale: bool
    provisional: bool
    inputs: dict[str, object]
    input_hash: str


class PriorityDecision(Contract):
    expected_version: int = Field(ge=1)
    request_id: UUID
    severity_override: float | None = None
    urgency_override: float | None = None
    critical_override: bool = False
    critical_review_due_at: AwareDatetime | None = None
    reason: str = Field(min_length=5, max_length=1000)

    @model_validator(mode="after")
    def valid_levels(self) -> Self:
        if self.severity_override not in {None, 0.25, 0.5, 0.75, 1}:
            raise ValueError("Choose a documented severity level")
        if self.urgency_override not in {None, 0, 0.5, 1}:
            raise ValueError("Choose a documented urgency level")
        if self.critical_override and self.critical_review_due_at is None:
            raise ValueError("A critical override requires a review deadline")
        return self


class PolicyPreview(Contract):
    pilot_id: UUID
    poi_snapshot_id: UUID
    policy: Policy
    as_of: AwareDatetime
    reason: str = Field(min_length=5, max_length=1000)


class ActivateEpoch(Contract):
    expected_active_epoch_id: UUID
    reason: str = Field(min_length=5, max_length=1000)
