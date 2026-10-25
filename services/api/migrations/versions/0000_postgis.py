"""Baseline extension revision: checkpoint 0 had no application tables."""

from alembic import op

revision = "0000"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")


def downgrade() -> None:
    # Keep the shared extension; never remove spatial_ref_sys or external dependencies.
    pass
