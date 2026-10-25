from enum import StrEnum


class Category(StrEnum):
    POTHOLE = "pothole"
    GARBAGE = "garbage_accumulation"
    SEWAGE = "sewage_overflow"
    STREETLIGHT = "streetlight_failure"
    OTHER = "other_civic_issue"


class Role(StrEnum):
    CITIZEN = "citizen"
    REVIEWER = "reviewer"
    OPERATOR = "operator"
    ADMIN = "admin"


class ReportState(StrEnum):
    SUBMITTED = "submitted"
    PROCESSING = "processing"
    AWAITING_REVIEW = "awaiting_review"
    OUT_OF_SCOPE = "out_of_scope"
    REJECTED = "rejected"
    ADMITTED = "admitted"
    PROCESSING_FAILED = "processing_failed"


class IssueState(StrEnum):
    OPEN = "open"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    RESOLUTION_PENDING = "resolution_pending"
    RESOLVED = "resolved"
    REOPENED = "reopened"
    MERGED = "merged"


class ValidationDecision(StrEnum):
    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"
    ERROR = "error"
