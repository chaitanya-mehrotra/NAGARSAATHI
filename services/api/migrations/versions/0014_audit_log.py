"""Make moderation history append-only and add one unified, read-only audit_log view.

Fixes: `deduplication_delete` was written by the API but rejected by the table's CHECK, and
moderation rows were deleted along with their report. The view reads the existing history tables
(it stores nothing itself), so no event is ever written twice.
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

ACTIONS = (
    "soft_delete",
    "restore",
    "status_override",
    "priority_override",
    "permanent_purge",
    "deduplication_delete",
)

VIEW = """
CREATE VIEW audit_log AS
SELECT r.received_at AS occurred_at, 'report'::text AS source, r.reporter_id AS actor_id,
       'report_submitted'::text AS action, r.id AS report_id, NULL::uuid AS issue_id,
       NULL::text AS from_state, 'submitted'::text AS to_state, NULL::text AS reason,
       jsonb_build_object('reference', r.public_reference, 'category', r.claimed_category) AS details
  FROM reports r
UNION ALL
SELECT v.completed_at, 'validation', v.reviewer_id,
       CASE WHEN v.provider = 'human_review' THEN 'photo_reviewed' ELSE 'photo_checked' END,
       v.report_id, NULL, NULL, v.decision, v.reason,
       jsonb_build_object('provider', v.provider, 'version', v.provider_version,
                          'labels', v.labels, 'confidence', v.confidence)
  FROM validation_results v
UNION ALL
SELECT m.created_at, 'moderation', m.actor_id, m.action, m.report_id, m.issue_id,
       NULL, NULL, m.reason, m.details
  FROM moderation_events m
UNION ALL
SELECT e.created_at, 'issue', e.actor_id, e.action, NULL, e.issue_id,
       e.from_state, e.to_state, e.reason, e.evidence
  FROM issue_events e
UNION ALL
SELECT a.created_at, 'audit', a.actor_id, a.operation,
       CASE WHEN a.entity_type = 'report' THEN a.entity_id END, NULL,
       NULL, NULL, a.changes ->> 'reason', a.changes
  FROM audit_events a
 WHERE a.entity_type <> 'issue'
UNION ALL
SELECT l.created_at, 'link', l.actor_id, 'report_linked', l.report_id, l.issue_id,
       NULL, NULL, l.reason, jsonb_build_object('method', l.method)
  FROM issue_report_links l
UNION ALL
SELECT l.ended_at, 'link', l.actor_id, 'report_unlinked', l.report_id, l.issue_id,
       NULL, NULL, l.reason, jsonb_build_object('method', l.method)
  FROM issue_report_links l
 WHERE l.ended_at IS NOT NULL
"""


def upgrade() -> None:
    allowed = ", ".join(f"'{name}'" for name in ACTIONS)
    op.execute(f"""
        ALTER TABLE moderation_events DROP CONSTRAINT IF EXISTS moderation_events_action_check;
        ALTER TABLE moderation_events
            ADD CONSTRAINT moderation_events_action_check CHECK (action IN ({allowed}));
        -- History must survive whatever happens to the report row.
        ALTER TABLE moderation_events DROP CONSTRAINT IF EXISTS moderation_events_report_id_fkey;
        ALTER TABLE moderation_events
            ADD CONSTRAINT moderation_events_report_id_fkey
            FOREIGN KEY (report_id) REFERENCES reports(id);
        CREATE TRIGGER moderation_events_immutable BEFORE UPDATE OR DELETE ON moderation_events
            FOR EACH ROW EXECUTE FUNCTION immutable_event_history();
        CREATE INDEX IF NOT EXISTS moderation_created_idx ON moderation_events (created_at);
        CREATE INDEX IF NOT EXISTS audit_events_created_idx ON audit_events (created_at);
        CREATE INDEX IF NOT EXISTS audit_events_entity_idx ON audit_events (entity_id);
        CREATE INDEX IF NOT EXISTS issue_events_created_idx ON issue_events (created_at);
        CREATE INDEX IF NOT EXISTS validation_results_report_idx ON validation_results (report_id);
        {VIEW};
        -- Same lockdown as the tables: the Supabase REST roles must not read history.
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON audit_log FROM anon;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                REVOKE ALL ON audit_log FROM authenticated;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        DROP VIEW IF EXISTS audit_log;
        DROP TRIGGER IF EXISTS moderation_events_immutable ON moderation_events;
        ALTER TABLE moderation_events DROP CONSTRAINT IF EXISTS moderation_events_action_check;
        ALTER TABLE moderation_events ADD CONSTRAINT moderation_events_action_check CHECK (
            action IN ('soft_delete','restore','status_override','priority_override','permanent_purge'));
        ALTER TABLE moderation_events DROP CONSTRAINT IF EXISTS moderation_events_report_id_fkey;
        ALTER TABLE moderation_events ADD CONSTRAINT moderation_events_report_id_fkey
            FOREIGN KEY (report_id) REFERENCES reports(id) ON DELETE CASCADE;
    """)
