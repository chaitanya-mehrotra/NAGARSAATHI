import os
import subprocess
import sys
from unittest.mock import patch
from uuid import UUID, uuid4

from app.adapters.local_media import LocalMedia
from app.domain.issues import process_admission_once
from sqlalchemy import text
from test_intake import auth, upload
from test_issues import accepted, image
from test_issues import issue_api as issue_api

from scripts.maintenance import maintain


def test_killed_worker_lease_recovery_duplicate_delivery_and_old_revision(issue_api):
    client, engine = issue_api
    report = accepted(issue_api, admission=False)
    url = engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time; from app.settings import Settings; "
            "from app.database import create_database_engine; from app.jobs import claim; "
            "e=create_database_engine(Settings()); j=claim(e,'killed-worker','admit_report'); "
            "c=e.connect(); t=c.begin(); "
            "c.exec_driver_sql(\"UPDATE reports SET review_reason='uncommitted crash marker' "
            "WHERE id=%s\",(j['payload']['report_id'],)); "
            "print(j['id'],flush=True); time.sleep(60)",
        ],
        env={**os.environ, "DATABASE_URL": url},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        assert child.stdout is not None
        job_id = UUID(child.stdout.readline().strip())
    finally:
        child.kill()
        child.wait(timeout=5)
    with engine.begin() as connection:
        assert (
            connection.execute(
                text("SELECT review_reason FROM reports WHERE id=:id"), {"id": report["id"]}
            ).scalar_one()
            != "uncommitted crash marker"
        )
        assert (
            connection.execute(
                text("SELECT status FROM jobs WHERE id=:id"), {"id": job_id}
            ).scalar_one()
            == "running"
        )
        connection.execute(
            text("UPDATE jobs SET lease_expires_at=now()-interval '1 second' WHERE id=:id"),
            {"id": job_id},
        )
    assert process_admission_once(engine, "replacement-worker")
    linked = client.get(f"/api/v1/reports/{report['id']}", headers=auth()).json()
    assert linked["state"] == "admitted"
    with engine.begin() as connection:
        for revision in [report["content_revision"], report["content_revision"] - 1]:
            connection.execute(
                text("""INSERT INTO jobs(type,payload,entity_revision,deduplication_key)
              SELECT type,payload,:revision,:key FROM jobs WHERE id=:id"""),
                {"id": job_id, "revision": revision, "key": f"redelivery:{uuid4()}"},
            )
    assert process_admission_once(engine, "replacement-worker")
    assert process_admission_once(engine, "replacement-worker")
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM issue_report_links WHERE report_id=:id AND active"),
                {"id": report["id"]},
            ).scalar_one()
            == 1
        )
        assert (
            connection.execute(
                text("SELECT attempts FROM jobs WHERE id=:id"), {"id": job_id}
            ).scalar_one()
            == 2
        )


def test_storage_and_location_resolver_fail_without_false_admission(issue_api):
    client, engine = issue_api
    with patch(
        "app.adapters.local_media.LocalMedia.put", side_effect=OSError("storage unavailable")
    ):
        assert (
            client.post(
                "/api/v1/uploads", content=image(), headers={**auth(), "Content-Type": "image/png"}
            ).status_code
            == 500
        )
    record = accepted(issue_api, admission=False)
    with patch(
        "app.domain.issues.assign_area", side_effect=OSError("location resolver unavailable")
    ):
        assert process_admission_once(engine, "resolver-failure")
    current = client.get(f"/api/v1/reports/{record['id']}", headers=auth()).json()
    assert current["issue_id"] is None
    with engine.connect() as connection:
        job = (
            connection.execute(text("SELECT status,last_error FROM jobs WHERE type='admit_report'"))
            .mappings()
            .one()
        )
        assert job["status"] == "pending" and job["last_error"] == "admission_failed"


def test_maintenance_dry_run_keeps_report_evidence_and_removes_only_expired_unattached(issue_api):
    client, engine = issue_api
    record = accepted(issue_api)
    spare = upload(client, content=image())
    storage = LocalMedia(client.app.state.settings.storage_root)
    orphan = uuid4().hex
    storage.put(f"{orphan}/original", b"orphan")
    os.utime(storage.path(f"{orphan}/original"), (1, 1))
    with engine.begin() as c:
        c.exec_driver_sql("UPDATE media SET expires_at=now()-interval '1 hour'")
    dry = maintain(engine, storage)
    assert dry["expired_uploads"] == 1 and dry["orphan_files"] == 1
    assert client.get(f"/api/v1/media/{spare}/content", headers=auth()).status_code == 200
    result = maintain(engine, storage, apply=True)
    assert result["expired_uploads"] == 1
    assert client.get(f"/api/v1/media/{spare}/content", headers=auth()).status_code == 404
    assert not storage.path(f"{orphan}/original").exists()
    attached = client.get(f"/api/v1/reports/{record['id']}", headers=auth()).json()["media"][0][
        "id"
    ]
    assert client.get(f"/api/v1/media/{attached}/content", headers=auth()).status_code == 200
