"""Add V2 user credentials, profile fields, soft deletion, and moderation audit."""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. User table enhancements for self-service auth and roles
    op.execute("""
        ALTER TABLE users ADD COLUMN IF NOT EXISTS email text UNIQUE;
        ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash text;
        ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified boolean NOT NULL DEFAULT false;
        ALTER TABLE users ADD COLUMN IF NOT EXISTS role text NOT NULL DEFAULT 'citizen'
            CHECK (role IN ('citizen', 'reviewer', 'operator', 'admin', 'nigam'));
        CREATE INDEX IF NOT EXISTS users_email_idx ON users (email);
    """)

    # 2. Report soft deletion fields
    op.execute("""
        ALTER TABLE reports ADD COLUMN IF NOT EXISTS deleted_at timestamptz;
        ALTER TABLE reports ADD COLUMN IF NOT EXISTS deleted_by uuid REFERENCES users(id);
        ALTER TABLE reports ADD COLUMN IF NOT EXISTS deletion_reason text;
        CREATE INDEX IF NOT EXISTS reports_deleted_at_idx ON reports (deleted_at);
    """)

    # 3. Moderation audit table for administrative actions
    op.execute("""
        CREATE TABLE IF NOT EXISTS moderation_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            report_id uuid REFERENCES reports(id) ON DELETE CASCADE,
            issue_id uuid REFERENCES issues(id) ON DELETE SET NULL,
            action text NOT NULL CHECK (action IN ('soft_delete', 'restore', 'status_override', 'priority_override', 'permanent_purge')),
            actor_id uuid NOT NULL REFERENCES users(id),
            reason text NOT NULL,
            details jsonb NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS moderation_report_idx ON moderation_events (report_id);
        CREATE INDEX IF NOT EXISTS moderation_actor_idx ON moderation_events (actor_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS moderation_events")
    op.execute("""
        ALTER TABLE reports DROP COLUMN IF EXISTS deletion_reason;
        ALTER TABLE reports DROP COLUMN IF EXISTS deleted_by;
        ALTER TABLE reports DROP COLUMN IF EXISTS deleted_at;
    """)
    op.execute("""
        ALTER TABLE users DROP COLUMN IF EXISTS role;
        ALTER TABLE users DROP COLUMN IF EXISTS email_verified;
        ALTER TABLE users DROP COLUMN IF EXISTS password_hash;
        ALTER TABLE users DROP COLUMN IF EXISTS email;
    """)
