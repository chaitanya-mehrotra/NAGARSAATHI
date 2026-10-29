from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url

from app.settings import Settings

HOSTED_SUFFIXES = (".supabase.com", ".supabase.co")


def is_hosted(url: URL) -> bool:
    return (url.host or "").endswith(HOSTED_SUFFIXES)


def effective_url(settings: Settings) -> URL:
    """The configured URL, with TLS required for hosted (Supabase) databases."""
    url = make_url(settings.database_url)
    if is_hosted(url) and "sslmode" not in url.query:
        url = url.update_query_dict({"sslmode": "require"})
    return url


def create_database_engine(settings: Settings) -> Engine:
    url = effective_url(settings)
    if url.get_backend_name() != "postgresql":
        raise ValueError("PostgreSQL/PostGIS is required; SQLite is not a spatial substitute")
    hosted = is_hosted(url)
    return create_engine(
        url.set(drivername="postgresql+psycopg"),
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=1800 if hosted else -1,
        connect_args=(
            # TCP keepalives keep idle pooled connections from being silently dropped.
            {
                "connect_timeout": 10,
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 5,
            }
            if hosted
            else {"connect_timeout": 3}
        ),
    )
