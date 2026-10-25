from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.domain.geography import IssuePoint
from app.intake_schemas import ReportDetail
from app.priority_schemas import PriorityView
from app.schemas import Contract


class IssueSummary(Contract):
    id: UUID
    public_reference: str
    category: str
    area_code: str
    status: str
    point: IssuePoint
    row_version: int
    report_count: int
    eligible_reporter_count: int
    first_accepted_at: datetime
    asset_id: UUID | None
    recurrence_parent_id: UUID | None
    merged_into_id: UUID | None
    priority: PriorityView | None = None
    assigned_operator_id: UUID | None = None
    assigned_team: str | None = None


class IssueDetail(IssueSummary):
    reports: list[ReportDetail]
    events: list[dict[str, object]]


class Candidate(Contract):
    id: UUID
    issue: IssueSummary
    distance_m: float
    kind: str
    asset_conflict: bool
    issue_revision: int
    report_revision: int


class DuplicateReview(Contract):
    report: ReportDetail
    candidates: list[Candidate]
    needs_cross_area_admin: bool


class LinkDecision(Contract):
    expected_revision: int = Field(ge=1)
    request_id: UUID
    action: Literal["link", "new", "recurrence", "clarify"]
    issue_id: UUID | None = None
    expected_issue_version: int | None = Field(default=None, ge=1)
    independent_evidence: bool = False
    reason: str = Field(min_length=5, max_length=1000)


class MergeDecision(Contract):
    request_id: UUID
    expected_version: int = Field(ge=1)
    target_id: UUID
    expected_target_version: int = Field(ge=1)
    reason: str = Field(min_length=5, max_length=1000)


class SplitDecision(Contract):
    request_id: UUID
    expected_version: int = Field(ge=1)
    report_ids: list[UUID] = Field(min_length=1, max_length=50)
    point: IssuePoint
    reason: str = Field(min_length=5, max_length=1000)
