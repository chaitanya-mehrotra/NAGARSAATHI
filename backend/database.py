"""SQLite database initialization and connection management."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

# Persistent path: works regardless of terminal's current working directory
DATA_DIR = Path(os.environ.get("NAGARSAATHI_DATA_DIR", Path(__file__).resolve().parent / "data"))


@contextmanager
def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATA_DIR / "nagarsaathi.db", timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('citizen', 'admin'))
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            description TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            photo_name TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            issue_type TEXT NOT NULL DEFAULT 'pothole',
            analysis_status TEXT NOT NULL DEFAULT 'pending',
            result_json TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            priority TEXT NOT NULL DEFAULT 'normal',
            priority_reason TEXT NOT NULL DEFAULT '',
            duplicate_of INTEGER REFERENCES reports(id)
        );
        CREATE INDEX IF NOT EXISTS reports_recent ON reports(created_at, status);
        """)
