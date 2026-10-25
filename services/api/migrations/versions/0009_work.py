"""Repair evidence, verification revisions and non-destructive archive."""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      ALTER TABLE issues ADD COLUMN archived_at timestamptz;
      ALTER TABLE resolution_records ADD COLUMN issue_revision integer NOT NULL DEFAULT 1;
      ALTER TABLE media ADD COLUMN repair_issue_id uuid REFERENCES issues(id);
      ALTER TABLE media ADD CONSTRAINT media_one_purpose CHECK
        (report_id IS NULL OR repair_issue_id IS NULL);
      CREATE INDEX media_repair_issue ON media(repair_issue_id);
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE media DROP COLUMN repair_issue_id CASCADE")
    op.execute("ALTER TABLE resolution_records DROP COLUMN issue_revision")
    op.execute("ALTER TABLE issues DROP COLUMN archived_at")
