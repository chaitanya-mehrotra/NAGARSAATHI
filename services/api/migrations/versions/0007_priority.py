"""Immutable scoring epochs, reproducible snapshots and reviewed context."""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      CREATE TABLE priority_epochs (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        pilot_id uuid NOT NULL REFERENCES pilots(id),
        policy_id uuid NOT NULL REFERENCES priority_policies(id),
        poi_snapshot_id uuid NOT NULL REFERENCES poi_snapshots(id),
        state text NOT NULL CHECK(state IN ('preview','active','retired')),
        as_of timestamptz NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),
        activated_at timestamptz,author_id uuid REFERENCES users(id),
        review_note text NOT NULL
      );
      CREATE UNIQUE INDEX one_active_priority_epoch ON priority_epochs(pilot_id)
        WHERE state='active';
      ALTER TABLE priority_snapshots ADD COLUMN epoch_id uuid REFERENCES priority_epochs(id);
      ALTER TABLE priority_snapshots ADD COLUMN computed_at timestamptz NOT NULL DEFAULT now();
      CREATE INDEX priority_snapshot_issue_epoch ON priority_snapshots(issue_id,epoch_id);
      ALTER TABLE issues ADD COLUMN severity_override double precision
        CHECK(severity_override IN (0.25,0.5,0.75,1));
      ALTER TABLE issues ADD COLUMN urgency_override double precision
        CHECK(urgency_override IN (0,0.5,1));
      ALTER TABLE issues ADD COLUMN critical_override boolean NOT NULL DEFAULT false;
      ALTER TABLE issues ADD COLUMN critical_review_due_at timestamptz;
      ALTER TABLE issues ADD CONSTRAINT critical_requires_deadline
        CHECK(NOT critical_override OR critical_review_due_at IS NOT NULL);
      CREATE TRIGGER priority_policy_immutable BEFORE UPDATE OR DELETE ON priority_policies
        FOR EACH ROW EXECUTE FUNCTION immutable_event_history();
      CREATE TRIGGER priority_snapshot_immutable BEFORE UPDATE OR DELETE ON priority_snapshots
        FOR EACH ROW EXECUTE FUNCTION immutable_event_history();
      CREATE TRIGGER poi_snapshot_immutable BEFORE UPDATE OR DELETE ON poi_snapshots
        FOR EACH ROW EXECUTE FUNCTION immutable_event_history();
      CREATE FUNCTION protect_poi_content() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP<>'INSERT' THEN
          RAISE EXCEPTION 'POI content is versioned and immutable' USING ERRCODE='23514';
        END IF;
        IF EXISTS(SELECT 1 FROM priority_epochs WHERE poi_snapshot_id=NEW.snapshot_id) THEN
          RAISE EXCEPTION 'POI snapshot is sealed by a scoring epoch' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
      END; $$;
      CREATE TRIGGER poi_content_immutable BEFORE INSERT OR UPDATE OR DELETE ON pois
        FOR EACH ROW EXECUTE FUNCTION protect_poi_content();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER poi_content_immutable ON pois")
    op.execute("DROP FUNCTION protect_poi_content()")
    op.execute("DROP TRIGGER poi_snapshot_immutable ON poi_snapshots")
    op.execute("DROP TRIGGER priority_policy_immutable ON priority_policies")
    op.execute("DROP TRIGGER priority_snapshot_immutable ON priority_snapshots")
    op.execute("ALTER TABLE issues DROP CONSTRAINT critical_requires_deadline")
    op.execute("""ALTER TABLE issues DROP COLUMN severity_override,DROP COLUMN urgency_override,
      DROP COLUMN critical_override,DROP COLUMN critical_review_due_at""")
    op.execute("ALTER TABLE priority_snapshots DROP COLUMN epoch_id,DROP COLUMN computed_at")
    op.execute("DROP TABLE priority_epochs")
