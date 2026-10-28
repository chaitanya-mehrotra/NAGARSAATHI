from pathlib import Path
from tempfile import TemporaryFile

import psycopg

from app.database import effective_url, is_hosted
from app.settings import Settings


def check_database(settings: Settings) -> bool:
    try:
        # libpq URLs have no SQLAlchemy "+driver" suffix
        url = effective_url(settings).set(drivername="postgresql")
        timeout = 10 if is_hosted(url) else 2
        with psycopg.connect(url.render_as_string(hide_password=False), connect_timeout=timeout) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT PostGIS_Version()")
                return cursor.fetchone() is not None
    except psycopg.Error:
        return False


def check_storage(root: Path) -> bool:
    try:
        root.mkdir(parents=True, exist_ok=True)
        with TemporaryFile(dir=root) as probe:
            probe.write(b"readiness")
            probe.seek(0)
            return probe.read() == b"readiness"
    except OSError:
        return False


def check_media_backend(settings: Settings, storage: object) -> bool:
    """Readiness of whichever photo store is configured."""
    if settings.storage_backend == "supabase":
        return bool(getattr(storage, "ping")())
    return check_storage(settings.storage_root)
