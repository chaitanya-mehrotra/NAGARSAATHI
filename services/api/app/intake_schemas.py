from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.domain.enums import ReportState, Role
from app.domain.geography import IssuePoint
from app.schemas import Contract


class RoleGrant(Contract):
    role: Role
    area_id: UUID | None
    area_code: str | None


class Actor(Contract):
    id: UUID
    subject: str
    display_name: str
    grants: list[RoleGrant]
    synthetic: bool

    def has_role(self, role: Role) -> bool:
        return any(grant.role == role for grant in self.grants)

    def can_review(self, area_id: UUID | None) -> bool:
        return any(
            grant.role in {Role.ADMIN, Role.REVIEWER}
            and (grant.area_id is None or grant.area_id == area_id)
            for grant in self.grants
        )


class UploadReceipt(Contract):
    id: UUID
    state: Literal["uploaded", "ready"]
    expires_at: datetime
    sha256: str
    byte_size: int
    width: int
    height: int


class ReportSubmission(Contract):
    description: str = Field(min_length=5, max_length=2000)
    claimed_category: str = Field(min_length=1, max_length=64)
    media_ids: list[UUID] = Field(min_length=1, max_length=3)
    location: IssuePoint = Field(default_factory=IssuePoint)
    location_source: Literal["confirmed_pin", "browser", "exif", "unknown"] = "unknown"
    address_text: str | None = Field(default=None, max_length=500)
    language_hint: str | None = Field(default=None, max_length=35)
    suggested_issue_id: UUID | None = None
    reported_hazard: bool = False

    @model_validator(mode="after")
    def check_submission(self) -> "ReportSubmission":
        if len(set(self.media_ids)) != len(self.media_ids):
            raise ValueError("Attach each photo only once")
        if len(self.description.strip()) < 5:
            raise ValueError("Describe the problem in at least five non-space characters")
        return self


class MediaSummary(Contract):
    id: UUID
    width: int
    height: int
    byte_size: int
    sha256: str
    content_url: str


class ReportDetail(Contract):
    id: UUID
    public_reference: str
    description: str
    claimed_category: str
    canonical_category: str | None
    state: ReportState
    location: IssuePoint
    location_source: str
    location_reason: str
    address_text: str | None
    area_code: str | None
    boundary_version: str | None
    received_at: datetime
    content_revision: int
    synthetic: bool
    media: list[MediaSummary]
    validation_status: str = "pending"
    review_reason: str | None = None
    canonical_location: IssuePoint | None = None
    issue_id: UUID | None = None
    issue_reference: str | None = None
    issue_status: str | None = None
    link_method: str | None = None
    trusted_asset_id: UUID | None = None
    evidence_reused: bool = False
    reported_hazard: bool = False


class ReportPage(Contract):
    items: list[ReportDetail]
    next_cursor: UUID | None
