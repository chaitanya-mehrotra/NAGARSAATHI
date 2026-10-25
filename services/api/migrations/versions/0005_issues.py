"""Trusted asset decisions, independent support and materialized issue aggregates."""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE reports ADD COLUMN trusted_asset_id uuid REFERENCES assets(id);
        ALTER TABLE reports ADD COLUMN evidence_reused boolean NOT NULL DEFAULT false;
        ALTER TABLE issue_report_links ADD COLUMN independent_evidence
          boolean NOT NULL DEFAULT true;
        ALTER TABLE issues ADD COLUMN report_count integer NOT NULL DEFAULT 0
          CHECK(report_count>=0);
        ALTER TABLE issues ADD COLUMN eligible_reporter_count integer NOT NULL DEFAULT 0
          CHECK(eligible_reporter_count>=0);
        CREATE FUNCTION check_admitted_validation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.state='admitted' AND
            (NEW.validation_status<>'accepted' OR NEW.validation_revision<>NEW.content_revision
             OR NOT EXISTS (SELECT 1 FROM issue_report_links
                            WHERE report_id=NEW.id AND active)) THEN
            RAISE EXCEPTION 'admission requires current validation and an active issue link'
              USING ERRCODE='23514';
          END IF;
          RETURN NULL;
        END; $$;
        CREATE CONSTRAINT TRIGGER reports_validation_integrity AFTER INSERT OR UPDATE ON reports
          DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_admitted_validation();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER reports_validation_integrity ON reports")
    op.execute("DROP FUNCTION check_admitted_validation()")
    op.execute("ALTER TABLE reports DROP COLUMN trusted_asset_id, DROP COLUMN evidence_reused")
    op.execute("ALTER TABLE issue_report_links DROP COLUMN independent_evidence")
    op.execute("ALTER TABLE issues DROP COLUMN report_count, DROP COLUMN eligible_reporter_count")
