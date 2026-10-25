"""Deferred link checks observe final transaction state, including ended links."""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      CREATE OR REPLACE FUNCTION check_admitted_validation() RETURNS trigger
      LANGUAGE plpgsql AS $$
      DECLARE rid uuid;
      BEGIN
        IF TG_TABLE_NAME='reports' THEN rid:=NEW.id; ELSE rid:=NEW.report_id; END IF;
        IF EXISTS (SELECT 1 FROM reports r WHERE r.id=rid AND r.state='admitted' AND
          (r.validation_status<>'accepted' OR r.validation_revision<>r.content_revision
           OR NOT EXISTS (SELECT 1 FROM issue_report_links l
                          WHERE l.report_id=r.id AND l.active))) THEN
          RAISE EXCEPTION 'admission requires current validation and an active issue link'
            USING ERRCODE='23514';
        END IF;
        RETURN NULL;
      END; $$;
      CREATE CONSTRAINT TRIGGER links_validation_integrity
        AFTER INSERT OR UPDATE ON issue_report_links DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION check_admitted_validation();
      CREATE FUNCTION preserve_issue_link_history() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP='DELETE' THEN
          RAISE EXCEPTION 'issue link history cannot be deleted' USING ERRCODE='23514';
        END IF;
        IF ROW(NEW.id,NEW.report_id,NEW.issue_id,NEW.method,NEW.actor_id,NEW.rule_version,
               NEW.created_at,NEW.reason,NEW.independent_evidence)
           IS DISTINCT FROM
           ROW(OLD.id,OLD.report_id,OLD.issue_id,OLD.method,OLD.actor_id,OLD.rule_version,
               OLD.created_at,OLD.reason,OLD.independent_evidence)
           OR NOT OLD.active OR NEW.active OR NEW.ended_at IS NULL THEN
          RAISE EXCEPTION 'issue links may only be ended; retain original history'
            USING ERRCODE='23514';
        END IF;
        RETURN NEW;
      END; $$;
      CREATE TRIGGER links_no_delete BEFORE DELETE OR UPDATE ON issue_report_links
        FOR EACH ROW EXECUTE FUNCTION preserve_issue_link_history();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER links_validation_integrity ON issue_report_links")
    op.execute("DROP TRIGGER IF EXISTS links_no_delete ON issue_report_links")
    op.execute("DROP FUNCTION IF EXISTS preserve_issue_link_history()")
