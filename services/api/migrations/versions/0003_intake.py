"""Persist expiring uploads and original submission location evidence."""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE media ADD COLUMN expires_at timestamptz")
    op.execute("ALTER TABLE media ADD COLUMN completed_at timestamptz")
    op.execute("ALTER TABLE reports ADD COLUMN pilot_id uuid REFERENCES pilots(id)")
    op.execute("ALTER TABLE reports ADD COLUMN location_evidence jsonb NOT NULL DEFAULT '{}'")
    op.execute("CREATE INDEX media_unattached_expiry ON media (expires_at) WHERE report_id IS NULL")
    op.execute("""
        CREATE FUNCTION check_report_media() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE targets uuid[]; target uuid;
        BEGIN
            IF TG_TABLE_NAME = 'reports' THEN targets := ARRAY[NEW.id];
            ELSIF TG_OP = 'INSERT' THEN targets := ARRAY[NEW.report_id];
            ELSIF TG_OP = 'DELETE' THEN targets := ARRAY[OLD.report_id];
            ELSE targets := ARRAY[NEW.report_id,OLD.report_id]; END IF;
            FOREACH target IN ARRAY COALESCE(targets, ARRAY[]::uuid[]) LOOP
                IF EXISTS (SELECT 1 FROM reports r JOIN media m ON m.report_id=r.id
                           WHERE r.id=target AND (m.owner_id<>r.reporter_id
                           OR m.completed_at IS NULL OR m.processing_state<>'ready')) THEN
                    RAISE EXCEPTION 'report media must be completed and owned by reporter'
                        USING ERRCODE='23514';
                END IF;
                IF EXISTS (SELECT 1 FROM reports WHERE id=target AND state='admitted')
                   AND NOT EXISTS (SELECT 1 FROM media WHERE report_id=target
                                   AND completed_at IS NOT NULL AND processing_state='ready') THEN
                    RAISE EXCEPTION 'admitted report requires completed evidence'
                        USING ERRCODE='23514';
                END IF;
            END LOOP;
            RETURN NULL;
        END; $$;
        CREATE CONSTRAINT TRIGGER reports_media_integrity AFTER INSERT OR UPDATE ON reports
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_report_media();
        CREATE CONSTRAINT TRIGGER media_report_integrity AFTER INSERT OR UPDATE OR DELETE ON media
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_report_media();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER reports_media_integrity ON reports")
    op.execute("DROP TRIGGER media_report_integrity ON media")
    op.execute("DROP FUNCTION check_report_media()")
    op.execute("DROP INDEX media_unattached_expiry")
    op.execute("ALTER TABLE reports DROP COLUMN location_evidence, DROP COLUMN pilot_id")
    op.execute("ALTER TABLE media DROP COLUMN expires_at, DROP COLUMN completed_at")
