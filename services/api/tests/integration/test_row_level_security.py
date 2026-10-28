def test_every_public_table_has_row_level_security(spatial_database):
    engine, _ = spatial_database
    with engine.connect() as connection:
        unprotected = (
            connection.exec_driver_sql(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' AND NOT rowsecurity"
            )
            .scalars()
            .all()
        )
    # Add ENABLE ROW LEVEL SECURITY to any new table's migration; Supabase would expose it otherwise.
    assert unprotected == []
