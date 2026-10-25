from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from app.database import create_database_engine
from app.demo_seed import require_local_demo, seed_foundation
from app.settings import PROJECT_ROOT, Settings
from psycopg import sql
from sqlalchemy import Connection, Engine
from sqlalchemy.engine import make_url


@contextmanager
def temporary_database() -> Iterator[tuple[Engine, Settings]]:
    local = Settings()
    require_local_demo(local)
    name = "nagarsaathi_cp1_" + uuid4().hex[:12] + "_test"
    with psycopg.connect(local.database_url, autocommit=True, connect_timeout=3) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        test_url = make_url(local.database_url).set(database=name)
        settings = Settings(
            app_mode="test", database_url=test_url.render_as_string(hide_password=False)
        )
        engine = create_database_engine(settings)
        try:
            yield engine, settings
        finally:
            engine.dispose()
            # Only the unique database created by this fixture is ever removed.
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def migrate(engine: Engine, revision: str, direction: str = "upgrade") -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        if direction == "upgrade":
            command.upgrade(config, revision)
        else:
            command.downgrade(config, revision)


@pytest.fixture(scope="session")
def spatial_database() -> Iterator[tuple[Engine, Settings]]:
    with temporary_database() as (engine, settings):
        # The baseline revision represents checkpoint 0's lack of application tables.
        migrate(engine, "0000")
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT PostGIS_Version()").scalar_one()
            assert connection.exec_driver_sql("SELECT to_regclass('users')").scalar_one() is None
        migrate(engine, "head")
        with engine.begin() as connection:
            seed_foundation(connection, settings)
        yield engine, settings


@pytest.fixture
def db(spatial_database: tuple[Engine, Settings]) -> Iterator[Connection]:
    engine, _ = spatial_database
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


@pytest.fixture
def fixture_ids(db: Connection) -> dict[str, Any]:
    user = db.exec_driver_sql(
        "INSERT INTO users (auth_subject,display_name) VALUES ('test-citizen','Synthetic citizen') "
        "RETURNING id"
    ).scalar_one()
    area = (
        db.exec_driver_sql("SELECT id,pilot_id,boundary_version FROM areas WHERE code='southwest'")
        .mappings()
        .one()
    )
    issues = []
    for reference in ("TEST-ISSUE-1", "TEST-ISSUE-2"):
        issue = db.exec_driver_sql(
            """
            INSERT INTO issues (public_reference,pilot_id,category_code,geom,area_id,
                                boundary_version,first_accepted_at,most_recent_accepted_at,synthetic)
            VALUES (%s,%s,'pothole',ST_GeogFromText('SRID=4326;POINT(77.615 12.915)'),
                    %s,%s,now(),now(),true) RETURNING id
        """,
            (reference, area["pilot_id"], area["id"], area["boundary_version"]),
        ).scalar_one()
        issues.append(issue)
    report = db.exec_driver_sql(
        """
        INSERT INTO reports (public_reference,reporter_id,description,claimed_category,
                             canonical_category,area_id,confirmed_point,synthetic)
        VALUES ('TEST-REPORT',%s,'Synthetic pothole','pothole','pothole',%s,
                ST_GeogFromText('SRID=4326;POINT(77.615 12.915)'),true) RETURNING id
    """,
        (user, area["id"]),
    ).scalar_one()
    return {
        "user": user,
        "area": area["id"],
        "pilot": area["pilot_id"],
        "issues": issues,
        "report": report,
    }
