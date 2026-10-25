from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url

from app.settings import Settings


def create_database_engine(settings: Settings) -> Engine:
    url = make_url(settings.database_url)
    if url.get_backend_name() != "postgresql":
        raise ValueError("PostgreSQL/PostGIS is required; SQLite is not a spatial substitute")
    return create_engine(
        url.set(drivername="postgresql+psycopg"),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
    )
