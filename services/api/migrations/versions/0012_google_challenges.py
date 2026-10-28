"""One-use nonces that bind a Google sign-in to a challenge this server issued."""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE google_challenges (
            nonce_hash text PRIMARY KEY CHECK (nonce_hash ~ '^[0-9a-f]{64}$'),
            expires_at timestamptz NOT NULL
        );
        CREATE INDEX google_challenges_expiry ON google_challenges (expires_at);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS google_challenges;")
