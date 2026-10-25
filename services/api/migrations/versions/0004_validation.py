"""Track current evidence-bound validation and review state."""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE reports ADD COLUMN validation_status text NOT NULL DEFAULT 'pending'
          CHECK (validation_status IN ('pending','accepted','needs_review','rejected','error'));
        ALTER TABLE reports ADD COLUMN validation_revision integer NOT NULL DEFAULT 0;
        ALTER TABLE reports ADD COLUMN review_reason text;
        CREATE INDEX reports_review_inbox ON reports (area_id,state,received_at,id);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX reports_review_inbox")
    op.execute(
        "ALTER TABLE reports DROP COLUMN validation_status, "
        "DROP COLUMN validation_revision, DROP COLUMN review_reason"
    )
