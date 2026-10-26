"""SQLite database initialization and connection management."""
import os
import sqlite3
import time
from contextlib import contextmanager, closing
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
        existing_columns = {r["name"] for r in db.execute("PRAGMA table_info(reports)")}
        if existing_columns and ("issue_id" not in existing_columns or "verification_status" not in existing_columns):
            backups = DATA_DIR / "backups"
            backups.mkdir(exist_ok=True)
            with closing(sqlite3.connect(backups / f"before-issue-grouping-{time.time_ns()}.db")) as backup:
                db.backup(backup)
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
        CREATE TABLE IF NOT EXISTS municipal_accounts (
            user_id INTEGER PRIMARY KEY REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            representative_report_id INTEGER NOT NULL REFERENCES reports(id),
            issue_type TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            created_at INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            published INTEGER NOT NULL DEFAULT 0 CHECK(published IN (0,1))
        );
        CREATE TABLE IF NOT EXISTS duplicate_candidates (
            report_id INTEGER NOT NULL REFERENCES reports(id),
            issue_id INTEGER NOT NULL REFERENCES issues(id),
            reason TEXT NOT NULL,
            PRIMARY KEY(report_id, issue_id)
        );
        CREATE TABLE IF NOT EXISTS grouping_history (
            id INTEGER PRIMARY KEY,
            report_id INTEGER NOT NULL REFERENCES reports(id),
            from_issue INTEGER,
            to_issue INTEGER NOT NULL,
            actor_id INTEGER NOT NULL REFERENCES users(id),
            reason TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS analysis_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER UNIQUE NOT NULL REFERENCES reports(id),
            state TEXT NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','processing','completed','failed')),
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at INTEGER NOT NULL,
            lease_hash TEXT,
            lease_until INTEGER,
            worker_id TEXT,
            candidate_ids TEXT NOT NULL DEFAULT '[]',
            result_digest TEXT,
            report_revision INTEGER NOT NULL DEFAULT 0,
            error_code TEXT,
            updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS jobs_available ON analysis_jobs(state,available_at,lease_until);
        CREATE TABLE IF NOT EXISTS issue_history (
            id INTEGER PRIMARY KEY,
            issue_id INTEGER NOT NULL,
            actor_id INTEGER REFERENCES users(id),
            event TEXT NOT NULL,
            details TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS worker_heartbeats (
            worker_id TEXT PRIMARY KEY,
            last_seen INTEGER NOT NULL
        );
        """)
        # Additive migration: preserve all existing accounts, reports and photos.
        columns = {r["name"] for r in db.execute("PRAGMA table_info(reports)")}
        for name, declaration in {
            "issue_id": "INTEGER REFERENCES issues(id)",
            "image_sha256": "TEXT",
            "image_dhash": "TEXT",
            "submission_key": "TEXT",
            "submission_digest": "TEXT",
            "grouping_reason": "TEXT NOT NULL DEFAULT 'legacy_needs_review'",
            "verification_status": "TEXT NOT NULL DEFAULT 'pending'",
            "verification_reason": "TEXT NOT NULL DEFAULT 'Awaiting processing'",
            "image_width": "INTEGER",
            "image_height": "INTEGER",
            "processing_revision": "INTEGER NOT NULL DEFAULT 0",
        }.items():
            if name not in columns:
                db.execute(f"ALTER TABLE reports ADD COLUMN {name} {declaration}")
        db.execute("CREATE INDEX IF NOT EXISTS report_issue ON reports(issue_id)")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS report_submission ON reports(user_id, submission_key) WHERE submission_key IS NOT NULL")
        issue_columns = {r['name'] for r in db.execute('PRAGMA table_info(issues)')}
        for name, declaration in {
            'publication_mode': "TEXT NOT NULL DEFAULT 'legacy'",
            'priority_score': 'REAL NOT NULL DEFAULT 0',
            'priority_reason': "TEXT NOT NULL DEFAULT ''",
            'priority_policy_version': "TEXT NOT NULL DEFAULT 'demand-age-v1'",
        }.items():
            if name not in issue_columns:
                db.execute(f'ALTER TABLE issues ADD COLUMN {name} {declaration}')
        if 'verification_status' not in columns:
            db.execute("UPDATE reports SET verification_status='needs_review', verification_reason='Historical report: administrator review required'")
        try:
            from backend.grouping import new_issue, fingerprints
        except ImportError:
            from grouping import new_issue, fingerprints
        from PIL import Image, ImageOps
        historical_links = []
        for report in db.execute("""SELECT * FROM reports WHERE issue_id IS NULL
            AND NOT EXISTS(SELECT 1 FROM analysis_jobs j WHERE j.report_id=reports.id) ORDER BY id""").fetchall():
            if report["duplicate_of"] is not None:
                historical_links.append((report["id"], report["duplicate_of"]))
            issue_id = new_issue(db, report)
            # The old distance-only duplicate links are suggestions, never confirmed groups.
            db.execute("UPDATE reports SET issue_id=?, duplicate_of=NULL WHERE id=?", (issue_id, report["id"]))
            try:
                with Image.open(DATA_DIR / 'photos' / report['photo_name'], formats=['PNG', 'JPEG', 'WEBP']) as image:
                    sha, dhash = fingerprints(ImageOps.exif_transpose(image))
                db.execute("UPDATE reports SET image_sha256=?, image_dhash=? WHERE id=?", (sha, dhash, report["id"]))
            except (OSError, ValueError):
                pass  # Missing historical photos must not prevent startup or discard reports.
        for report_id, previous_root in historical_links:
            target = db.execute("SELECT issue_id FROM reports WHERE id=?", (previous_root,)).fetchone()
            if target:
                db.execute("INSERT OR IGNORE INTO duplicate_candidates VALUES(?,?,?)", (report_id, target["issue_id"], "legacy_distance_only"))
