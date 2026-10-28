from pathlib import Path
from tempfile import TemporaryFile

import psycopg

from app.settings import Settings


def check_database(settings: Settings) -> bool:
    try:
        # libpq URLs have no SQLAlchemy "+driver" suffix
        url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        with psycopg.connect(url, connect_timeout=2) as connection:
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
