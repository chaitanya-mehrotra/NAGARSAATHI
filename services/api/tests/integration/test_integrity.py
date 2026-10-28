from typing import Any

import pytest
from app.domain.geography import IssuePoint, nearby_issue_ids
from app.settings import Settings
from conftest import migrate, temporary_database
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError


def test_fresh_migration_and_upgrade_preserve_data() -> None:
    with temporary_database() as (engine, _):
        migrate(engine, "0001")
        with engine.begin() as connection:
            user = connection.exec_driver_sql(
                "INSERT INTO users (auth_subject,display_name) "
                "VALUES ('baseline-user','Synthetic') "
                "RETURNING id"
            ).scalar_one()
        migrate(engine, "head")
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
                == "0013"
            )
            assert connection.exec_driver_sql("SELECT id FROM users").scalar_one() == user
        migrate(engine, "0000", "downgrade")
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT to_regclass('users')").scalar_one() is None
        migrate(engine, "head")
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT count(*) FROM users").scalar_one() == 0


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO user_roles (user_id,role) VALUES (gen_random_uuid(),'citizen')",
        "INSERT INTO users (auth_subject,display_name) VALUES ('test-citizen','Duplicate')",
        "UPDATE categories SET default_severity = 1.1 WHERE code='pothole'",
        "UPDATE reports SET state = 'unknown' WHERE public_reference='TEST-REPORT'",
        "UPDATE issues SET category_code = 'unknown' WHERE public_reference='TEST-ISSUE-1'",
        "UPDATE issues SET boundary_version = 'wrong' WHERE public_reference='TEST-ISSUE-1'",
        "UPDATE issues SET area_id=(SELECT id FROM areas WHERE code='northeast') "
        "WHERE public_reference='TEST-ISSUE-1'",
        "DELETE FROM users WHERE auth_subject='test-citizen'",
    ],
)
def test_foreign_keys_uniqueness_states_and_geographic_constraints(
    db: Connection, fixture_ids: dict[str, Any], statement: str
) -> None:
    with pytest.raises(IntegrityError), db.begin_nested():
        db.exec_driver_sql(statement)


def test_duplicate_unscoped_roles_rejected(db: Connection, fixture_ids: dict[str, Any]) -> None:
    insert = text("INSERT INTO user_roles (user_id,role) VALUES (:user,'citizen')")
    db.execute(insert, {"user": fixture_ids["user"]})
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(insert, {"user": fixture_ids["user"]})


def admit_with_link(db: Connection, ids: dict[str, Any]) -> None:
    db.execute(
        text("""
        INSERT INTO media (report_id,owner_id,storage_key,original_sha256,mime,width,height,
                           byte_size,processing_state,completed_at)
        VALUES (:report,:user,'fixture/'||gen_random_uuid(),repeat('a',64),'image/jpeg',
                1,1,1,'ready',now())
    """),
        ids,
    )
    db.execute(
        text("""UPDATE reports SET state='admitted',validation_status='accepted',
      validation_revision=content_revision WHERE id=:report"""),
        ids,
    )
    db.execute(
        text("""
        INSERT INTO issue_report_links (report_id,issue_id,method,rule_version)
        VALUES (:report,:issue,'new','test-v1')
    """),
        {"report": ids["report"], "issue": ids["issues"][0]},
    )
    db.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
    db.exec_driver_sql("SET CONSTRAINTS ALL DEFERRED")


def test_admission_cannot_leave_orphan_report(db: Connection, fixture_ids: dict[str, Any]) -> None:
    with pytest.raises(IntegrityError, match="requires an issue link"), db.begin_nested():
        db.execute(text("UPDATE reports SET state='admitted' WHERE id=:report"), fixture_ids)
        db.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")


def test_one_active_link_and_historical_link_retention(
    db: Connection, fixture_ids: dict[str, Any]
) -> None:
    admit_with_link(db, fixture_ids)
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            text("""
            INSERT INTO issue_report_links (report_id,issue_id,method,rule_version)
            VALUES (:report,:issue,'reviewed_duplicate','test-v1')
        """),
            {"report": fixture_ids["report"], "issue": fixture_ids["issues"][1]},
        )
    with pytest.raises(IntegrityError, match="current validation"), db.begin_nested():
        db.exec_driver_sql("UPDATE issue_report_links SET active=false,ended_at=now()")
        db.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
    db.exec_driver_sql("UPDATE reports SET state='awaiting_review'")
    db.exec_driver_sql("UPDATE issue_report_links SET active=false,ended_at=now()")
    db.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
    assert db.exec_driver_sql("SELECT count(*) FROM issue_report_links").scalar_one() == 1
    with pytest.raises(IntegrityError), db.begin_nested():
        db.exec_driver_sql("DELETE FROM issue_report_links")


def test_unreviewed_report_cannot_link_as_support(
    db: Connection, fixture_ids: dict[str, Any]
) -> None:
    with pytest.raises(IntegrityError, match="admitted compatible"), db.begin_nested():
        db.execute(
            text("""
            INSERT INTO issue_report_links (report_id,issue_id,method,rule_version)
            VALUES (:report,:issue,'new','test-v1')
        """),
            {"report": fixture_ids["report"], "issue": fixture_ids["issues"][0]},
        )
        db.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")


def test_issue_category_change_cannot_break_link(
    db: Connection, fixture_ids: dict[str, Any]
) -> None:
    admit_with_link(db, fixture_ids)
    with pytest.raises(IntegrityError, match="admitted compatible"), db.begin_nested():
        db.execute(
            text("UPDATE issues SET category_code='sewage_overflow' WHERE id=:issue"),
            {"issue": fixture_ids["issues"][0]},
        )
        db.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")


def test_merge_self_and_cycle_rejected(db: Connection, fixture_ids: dict[str, Any]) -> None:
    a, b = fixture_ids["issues"]
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            text("UPDATE issues SET status='merged',merged_into_issue_id=id WHERE id=:id"),
            {"id": a},
        )
    db.execute(
        text("UPDATE issues SET status='merged',merged_into_issue_id=:b WHERE id=:a"),
        {"a": a, "b": b},
    )
    with pytest.raises(IntegrityError, match="merge cycle"), db.begin_nested():
        db.execute(
            text("UPDATE issues SET status='merged',merged_into_issue_id=:a WHERE id=:b"),
            {"a": a, "b": b},
        )


def test_event_history_is_append_only(db: Connection, fixture_ids: dict[str, Any]) -> None:
    db.execute(
        text("INSERT INTO issue_events (issue_id,action) VALUES (:issue,'created')"),
        {"issue": fixture_ids["issues"][0]},
    )
    with pytest.raises(IntegrityError, match="append-only"), db.begin_nested():
        db.exec_driver_sql("DELETE FROM issue_events")


def test_priority_score_constraint(db: Connection, fixture_ids: dict[str, Any]) -> None:
    policy = db.exec_driver_sql("""
        INSERT INTO priority_policies (version,weights,category_parameters,hazard_rules)
        VALUES ('test','{}','{}','{}') RETURNING id
    """).scalar_one()
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            text("""
            INSERT INTO priority_snapshots (issue_id,policy_id,issue_revision,as_of,inputs,
                factors,contributions,score,band,urgency_source,missing_data_flags,input_hash)
            VALUES (:issue,:policy,1,now(),'{}','{}','{}',101,'high','test','[]',:hash)
        """),
            {"issue": fixture_ids["issues"][0], "policy": policy, "hash": "a" * 64},
        )


def test_spatial_retrieval_crosses_area_border_and_excludes_closed(
    db: Connection, fixture_ids: dict[str, Any]
) -> None:
    issue = fixture_ids["issues"][0]
    db.execute(
        text("""
        UPDATE issues SET geom=ST_GeogFromText('SRID=4326;POINT(77.63004 12.915)'),
        area_id=(SELECT id FROM areas WHERE code='south_central') WHERE id=:id
    """),
        {"id": issue},
    )
    point = IssuePoint(longitude=77.62996, latitude=12.915, confirmed=True)
    assert nearby_issue_ids(db, fixture_ids["pilot"], "pothole", point, 20) == [issue]
    db.execute(text("UPDATE issues SET status='resolved' WHERE id=:id"), {"id": issue})
    assert nearby_issue_ids(db, fixture_ids["pilot"], "pothole", point, 20) == []


def test_spatial_query_plan_uses_gist_on_representative_data(
    db: Connection, fixture_ids: dict[str, Any]
) -> None:
    db.execute(
        text("""
        INSERT INTO issues (public_reference,pilot_id,category_code,geom,area_id,
                            boundary_version,first_accepted_at,most_recent_accepted_at,synthetic)
        SELECT 'LOAD-'||g,:pilot,'pothole',
            ST_SetSRID(ST_MakePoint(
                77.601+(g % 100)*0.00027,12.901+(g/100)*0.0005),4326)::geography,
            :area,'demo-envelope-v1',now(),now(),true FROM generate_series(1,5000) g
    """),
        fixture_ids,
    )
    db.exec_driver_sql("ANALYZE issues")
    plan = str(
        db.exec_driver_sql("""
        EXPLAIN (FORMAT JSON) SELECT id FROM issues
        WHERE ST_DWithin(geom,ST_GeogFromText('SRID=4326;POINT(77.615 12.915)'),20)
    """).scalar_one()
    )
    assert "issues_geom_gist" in plan


def test_schema_has_all_foundation_tables(spatial_database: tuple[Engine, Settings]) -> None:
    engine, _ = spatial_database
    with engine.connect() as db:
        tables = set(
            db.exec_driver_sql(
                "SELECT tablename FROM pg_tables WHERE schemaname='public'"
            ).scalars()
        )
        assert {
            "users",
            "user_roles",
            "pilots",
            "areas",
            "categories",
            "assets",
            "poi_snapshots",
            "pois",
            "priority_policies",
            "reports",
            "media",
            "validation_results",
            "location_decisions",
            "idempotency_records",
            "issues",
            "issue_report_links",
            "duplicate_candidates",
            "issue_events",
            "resolution_records",
            "priority_snapshots",
            "audit_events",
            "jobs",
        } <= tables
