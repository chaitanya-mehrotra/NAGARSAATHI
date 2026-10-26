"""Acceptance tests for report retention, consolidated counts and role separation."""
import io
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from backend import database, reports, inference
from backend.accounts import create_user
from backend.main import app


def photo(color):
    stream = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(stream, format="PNG")
    return stream.getvalue()


class GroupingTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(database, "DATA_DIR", self.directory))
        self.stack.enter_context(patch.object(reports, "DATA_DIR", self.directory))
        self.stack.enter_context(patch.object(inference, "load_model", return_value=None))
        self.detect = self.stack.enter_context(patch.object(inference, "detect_potholes", return_value={"detections": []}))
        self.client = self.stack.enter_context(TestClient(app))
        self.admin = self.account("admin", "admin")
        self.nigam = self.account("officer", "nigam")
        self.citizen = self.account("citizen")

    def account(self, name, role="citizen"):
        create_user(name, f"{name}@example.com", "test-password-123", role=role)
        login = self.client.post("/auth/login", json={"email": f"{name}@example.com", "password": "test-password-123"})
        self.assertEqual(login.json()["user"]["role"], role)
        return {"Authorization": "Bearer " + login.json()["access_token"]}

    def submit(self, headers=None, image=None, category="pothole", lat=12.9716, lon=77.5946, key=None):
        headers = dict(headers or self.citizen)
        if key:
            headers["Idempotency-Key"] = key
        return self.client.post("/reports", headers=headers,
            data={"description": "Road defect", "latitude": lat, "longitude": lon, "issue_type": category},
            files={"image": ("road.png", image or photo("grey"), "image/png")})

    def issue(self, issue_id):
        return self.client.get(f"/issues/{issue_id}", headers=self.admin).json()

    def group(self, report_id, issue_id):
        return self.client.patch(f"/issues/report/{report_id}/group", headers=self.admin,
                                 json={"issue_id": issue_id, "reason": "Reviewed same road defect"})

    def publish(self, issue_id):
        return self.client.patch(f"/issues/{issue_id}/publication", headers=self.admin, json={"published": True})

    def test_ten_reports_one_municipal_issue_and_eleven_reports_still_ten_reporters(self):
        citizens = [self.citizen] + [self.account(f"person{i}") for i in range(9)]
        submitted = [self.submit(headers=h).json() for h in citizens]
        issue_id = submitted[0]["issue_id"]
        self.assertEqual({r["issue_id"] for r in submitted}, {issue_id})
        self.assertEqual(len(self.client.get("/reports", headers=self.admin).json()), 10)
        self.assertEqual(self.client.get("/issues", headers=self.nigam).json()["total"], 0)
        self.publish(issue_id)
        municipal = self.client.get("/issues", headers=self.nigam).json()
        self.assertEqual(municipal["total"], 1)
        item = municipal["items"][0]
        self.assertEqual((item["report_count"], item["reporter_count"], item["unique_photo_count"]), (10, 10, 1))
        self.assertNotIn("user_id", item)
        self.assertNotIn("reports", item)
        self.assertEqual(self.client.get(item["photo_url"], headers=self.nigam).status_code, 200)
        self.submit()
        item = self.issue(issue_id)
        self.assertEqual((item["report_count"], item["reporter_count"]), (11, 10))
        self.assertEqual(self.client.get("/metrics", headers=self.nigam).json()["total"], 1)
        for endpoint in ("/reports", "/complaints", f"/reports/{submitted[0]['id']}", f"/reports/{submitted[0]['id']}/photo"):
            self.assertEqual(self.client.get(endpoint, headers=self.nigam).status_code, 403)
        # Citizens only receive counts, never another report's description/evidence URL.
        own = self.client.get(f"/reports/{submitted[-1]['id']}", headers=citizens[-1]).json()
        self.assertNotIn("description", own["issue_summary"])
        self.assertEqual(self.client.get("/issues", headers=self.citizen).status_code, 403)

    def test_different_photos_suggest_only_then_admin_can_group_and_undo(self):
        first = self.submit().json()
        second = self.submit(image=photo("blue")).json()
        self.assertNotEqual(first["issue_id"], second["issue_id"])
        detail = self.client.get(f"/reports/{second['id']}", headers=self.admin).json()
        self.assertEqual(detail["duplicate_candidates"][0]["issue_id"], first["issue_id"])
        self.assertEqual(self.group(second["id"], first["issue_id"]).status_code, 200)
        self.assertEqual(self.issue(first["issue_id"])["report_count"], 2)
        self.group(second["id"], first["issue_id"])  # Safe replay.
        self.assertEqual(self.issue(first["issue_id"])["report_count"], 2)
        self.assertEqual(self.issue(first["issue_id"])["unique_photo_count"], 2)
        split = self.group(second["id"], None)
        self.assertEqual(split.status_code, 200)
        self.assertEqual(split.json()["report_count"], 1)
        self.assertEqual(self.issue(first["issue_id"])["report_count"], 1)
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM grouping_history").fetchone()[0], 2)
        self.assertEqual(len(list((self.directory / "photos").glob("*.png"))), 2)

    def test_category_distance_and_closed_issue_prevent_automatic_grouping(self):
        first = self.submit().json()
        water = self.submit(category="waterlogging").json()
        distant = self.submit(lat=13.0).json()
        self.assertEqual(len({first["issue_id"], water["issue_id"], distant["issue_id"]}), 3)
        self.assertEqual(self.group(water["id"], first["issue_id"]).status_code, 400)
        with database.connect() as db:
            db.execute("UPDATE issues SET status='resolved' WHERE id=?", (first["issue_id"],))
        recurrent = self.submit().json()
        self.assertNotEqual(recurrent["issue_id"], first["issue_id"])

    def test_concurrent_idempotent_retry_counts_once_and_rejects_changed_payload(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            responses = list(pool.map(lambda _: self.submit(key="same-network-request"), range(3)))
        self.assertTrue(all(r.status_code == 201 for r in responses))
        self.assertEqual(len({r.json()["id"] for r in responses}), 1)
        self.assertEqual(self.issue(responses[0].json()["issue_id"])["report_count"], 1)
        self.assertEqual(self.detect.call_count, 1)
        self.assertEqual(self.submit(key="same-network-request", image=photo("red")).status_code, 409)
        self.assertEqual(len(list((self.directory / "photos").glob("*.png"))), 1)

    def test_public_registration_cannot_become_municipal_or_admin(self):
        for role in ("nigam", "admin"):
            response = self.client.post("/auth/register", json={"name": "Untrusted", "email": f"attempt-{role}@example.com",
                                        "password": "test-password-123", "role": role})
            self.assertEqual(response.json()["role"], "citizen")
        report = self.submit().json()
        self.assertEqual(self.client.patch(f"/issues/report/{report['id']}/group", headers=self.citizen,
                         json={"issue_id": None, "reason": "not allowed"}).status_code, 403)
        database.init_db()
        self.assertEqual(self.issue(report["issue_id"])["report_count"], 1)


class LegacyMigrationTests(unittest.TestCase):
    def test_old_distance_only_links_become_suggestions_without_data_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with closing(sqlite3.connect(root / "nagarsaathi.db")) as db:
                db.executescript("""
                CREATE TABLE users(id INTEGER PRIMARY KEY, email TEXT UNIQUE, name TEXT, password_hash TEXT, role TEXT);
                INSERT INTO users VALUES(1,'old@example.com','Old citizen','unused','citizen');
                CREATE TABLE reports(id INTEGER PRIMARY KEY,user_id INTEGER,description TEXT,latitude REAL,longitude REAL,
                photo_name TEXT,created_at INTEGER,issue_type TEXT,analysis_status TEXT,result_json TEXT,status TEXT,
                priority TEXT,priority_reason TEXT,duplicate_of INTEGER);
                INSERT INTO reports VALUES(1,1,'One',12,77,'missing.png',1,'pothole','completed',NULL,'open','normal','',NULL);
                INSERT INTO reports VALUES(2,1,'Two',12,77,'missing2.png',2,'pothole','completed',NULL,'open','normal','',1);
                """)
                db.commit()
            with patch.object(database, "DATA_DIR", root):
                database.init_db()
                database.init_db()
                with database.connect() as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM reports").fetchone()[0], 2)
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM issues").fetchone()[0], 2)
                    self.assertEqual(db.execute("SELECT reason FROM duplicate_candidates").fetchone()[0], "legacy_distance_only")
                    self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(len(list((root / "backups").glob("*.db"))), 1)
