from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.issue_schemas import IssueSummary
from app.schemas import Contract


class QueueItem(Contract):
    issue: IssueSummary
    position: int
    changed_since_capture: bool


class QueuePage(Contract):
    items: list[QueueItem]
    next_cursor: str | None
    captured_at: datetime
    expires_at: datetime
    total_issues: int
    total_linked_reports: int
    eligible_reporter_issue_pairs: int
    epochs: dict[str, str]


class AreaCategorySummary(Contract):
    area_code: str
    area_name: str
    category: str
    active_issues: int
    linked_reports: int
    eligible_reporter_issue_pairs: int
    high_or_critical_issues: int
    confirmed_critical_issues: int
    overdue_issues: int
    high_and_overdue_issues: int
    oldest_age_hours: float | None
    oldest_overdue_age_hours: float | None


class Assignment(Contract):
    request_id: UUID
    expected_version: int = Field(ge=1)
    operator_id: UUID | None = None
    team: str | None = Field(default=None, max_length=100)
    reason: str = Field(min_length=5, max_length=1000)


class Assignee(Contract):
    id: UUID
    display_name: str


class QueueFilters(Contract):
    area: str | None = None
    category: str | None = None
    status: Literal[
        "active",
        "open",
        "assigned",
        "in_progress",
        "resolution_pending",
        "reopened",
        "resolved",
        "merged",
        "all",
    ] = "active"
    band: Literal["critical", "high", "medium", "low", "pending"] | None = None
    overdue: bool = False
    bbox: str | None = None
