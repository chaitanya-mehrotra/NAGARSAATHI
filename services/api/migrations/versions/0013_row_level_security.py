"""Enable row-level security on every table and close the public data-API roles.

The API connects as the database owner (which bypasses RLS), so this changes nothing for the app.
It matters on hosted Supabase, where `anon` and `authenticated` could otherwise reach public
tables through the auto-generated REST API. With RLS on and no policies, those roles see nothing.
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

TABLES_SQL = """
    SELECT format('%I.%I', schemaname, tablename)
    FROM pg_tables
    WHERE schemaname = 'public'
"""


def upgrade() -> None:
    op.execute(f"""
        DO $$
        DECLARE tbl text;
        BEGIN
            FOR tbl IN {TABLES_SQL} LOOP
                EXECUTE 'ALTER TABLE ' || tbl || ' ENABLE ROW LEVEL SECURITY';
            END LOOP;
            -- Supabase's REST roles; absent on a plain local Postgres.
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon;
                REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon;
                REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM anon;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                REVOKE ALL ON ALL TABLES IN SCHEMA public FROM authenticated;
                REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM authenticated;
                REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM authenticated;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute(f"""
        DO $$
        DECLARE tbl text;
        BEGIN
            FOR tbl IN {TABLES_SQL} LOOP
                EXECUTE 'ALTER TABLE ' || tbl || ' DISABLE ROW LEVEL SECURITY';
            END LOOP;
        END $$;
    """)
