"""Complaint schema, integrity constraints and spatial indexes."""

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = "0000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = Path(__file__).resolve().parents[1] / "sql/0001_foundation.sql"
    op.execute(sql.read_text(encoding="utf-8"))


def downgrade() -> None:
    tables = (
        "jobs",
        "audit_events",
        "resolution_records",
        "issue_events",
        "duplicate_candidates",
        "issue_report_links",
        "priority_snapshots",
        "issues",
        "idempotency_records",
        "location_decisions",
        "validation_results",
        "media",
        "reports",
        "priority_policies",
        "pois",
        "poi_snapshots",
        "assets",
        "user_roles",
        "categories",
        "areas",
        "pilots",
        "users",
    )
    op.execute("ALTER TABLE issues DROP CONSTRAINT issues_priority_snapshot_fk")
    for table in tables:
        op.execute(f"DROP TABLE {table}")
    for function in (
        "check_admitted_report_link",
        "prevent_merge_cycle",
        "immutable_event_history",
    ):
        op.execute(f"DROP FUNCTION {function}()")
