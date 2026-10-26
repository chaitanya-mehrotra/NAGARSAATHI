"""Add suspicious validation flags and zone traffic weights for prioritisation."""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add suspicious mismatch flags to reports
    op.execute("""
        ALTER TABLE reports ADD COLUMN IF NOT EXISTS is_suspicious boolean NOT NULL DEFAULT false;
        ALTER TABLE reports ADD COLUMN IF NOT EXISTS suspicious_reason text;
        CREATE INDEX IF NOT EXISTS reports_suspicious_idx ON reports (is_suspicious) WHERE is_suspicious = true;
    """)

    # 2. Add traffic weighting to areas
    op.execute("""
        ALTER TABLE areas ADD COLUMN IF NOT EXISTS traffic_weight double precision NOT NULL DEFAULT 1.0;
    """)

    # 3. Apply higher default traffic weights for high-congestion zones in Bengaluru pilot
    # South Central (Silk Board / Madiwala corridor): highest bottleneck (1.25x)
    # North Central (Koramangala 4th/5th Block hub): high density (1.15x)
    # Northeast (Sony World / Ejipura / Inner Ring Road): high density (1.15x)
    # Southeast (HSR Layout / Bellandur corridor): high density (1.15x)
    op.execute("""
        UPDATE areas SET traffic_weight = 1.25 WHERE code = 'south_central';
        UPDATE areas SET traffic_weight = 1.15 WHERE code IN ('north_central', 'northeast', 'southeast');
        UPDATE areas SET traffic_weight = 1.0 WHERE code IN ('southwest', 'northwest');
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE areas DROP COLUMN IF EXISTS traffic_weight;")
    op.execute("""
        DROP INDEX IF EXISTS reports_suspicious_idx;
        ALTER TABLE reports DROP COLUMN IF EXISTS suspicious_reason;
        ALTER TABLE reports DROP COLUMN IF EXISTS is_suspicious;
    """)
