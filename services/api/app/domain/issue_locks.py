import hashlib
from uuid import UUID

from sqlalchemy import Connection, text


def category_locks(connection: Connection, pilot: UUID, categories: list[str]) -> None:
    priority_lock(connection, pilot)
    for category in sorted(set(categories)):
        key = int.from_bytes(
            hashlib.sha256(f"issue:{pilot}:{category}".encode()).digest()[:8], "big", signed=True
        )
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def priority_lock(connection: Connection, pilot: UUID, exclusive: bool = False) -> None:
    key = int.from_bytes(
        hashlib.sha256(f"priority:{pilot}".encode()).digest()[:8], "big", signed=True
    )
    function = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
    connection.execute(text(f"SELECT {function}(:key)"), {"key": key})
