"""Protect versioned ownership and both sides of report-link edits."""

from pathlib import Path

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    path = Path(__file__).resolve().parents[1] / "sql/0002_integrity.sql"
    op.execute(path.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TRIGGER issues_link_integrity ON issues")
    op.execute("DROP TRIGGER areas_boundary_version ON areas")
    op.execute("DROP TRIGGER issues_boundary_ownership ON issues")
    op.execute("DROP FUNCTION check_boundary_ownership()")
    # The stronger link function remains compatible with the earlier trigger/schema.
