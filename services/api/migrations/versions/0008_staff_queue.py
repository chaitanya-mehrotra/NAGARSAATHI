"""Bounded, actor-bound frozen ordering for staff cursor browsing."""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      CREATE TABLE staff_queue_sessions (
        id uuid PRIMARY KEY,actor_id uuid NOT NULL REFERENCES users(id),
        grant_hash text NOT NULL,filter_hash text NOT NULL,epochs jsonb NOT NULL,
        captured_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL DEFAULT now()+interval '15 minutes'
      );
      CREATE TABLE staff_queue_items (
        session_id uuid NOT NULL REFERENCES staff_queue_sessions(id) ON DELETE CASCADE,
        position integer NOT NULL,issue_id uuid NOT NULL REFERENCES issues(id),
        issue_revision integer NOT NULL,snapshot_id uuid REFERENCES priority_snapshots(id),
        report_count integer NOT NULL,eligible_reporter_count integer NOT NULL,
        PRIMARY KEY(session_id,position),UNIQUE(session_id,issue_id)
      );
      CREATE INDEX staff_queue_expiry ON staff_queue_sessions(expires_at);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE staff_queue_items")
    op.execute("DROP TABLE staff_queue_sessions")
