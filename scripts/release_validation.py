"""Reproducible release checks in isolated disposable databases; never seed the demo DB."""

import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
from app.adapters.local_media import LocalMedia, decode_photo
from app.adapters.validation import HumanReviewValidator
from app.auth import DemoTokens
from app.demo_seed import require_local_demo, seed_foundation
from app.domain.issues import refresh_aggregates
from app.domain.priority import refresh, schedule_age_refresh
from app.jobs import process_once
from app.main import create_app
from app.settings import PROJECT_ROOT, Settings
from fastapi import FastAPI
from PIL import Image
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(PROJECT_ROOT / "services/api/tests/integration"))
from conftest import migrate, temporary_database  # type: ignore[import-not-found] # noqa: E402

AS_OF = datetime(2026, 10, 1, 12, tzinfo=UTC)


def fixed(kind: str, index: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"nagarsaathi-release-v1:{kind}:{index}")


class LoadTokens(DemoTokens):
    def subject(self, token: str) -> str:
        if re.fullmatch(r"load-citizen-(?:[0-9]|1[0-9])", token):
            return token
        return super().subject(token)


def load_app() -> FastAPI:
    settings = Settings()
    require_local_demo(settings)
    if settings.app_mode != "test" or not re.fullmatch(
        r"nagarsaathi_cp1_[0-9a-f]{12}_test", make_url(settings.database_url).database or ""
    ):
        raise RuntimeError(
            "Load identities are allowed only in this runner's disposable test database"
        )
    return create_app(settings, token_verifier=LoadTokens(settings))


def seed(engine: Engine, settings: Settings, storage: LocalMedia) -> None:
    with engine.begin() as c:
        seed_foundation(c, settings)
        areas = (
            c.execute(
                text(
                    "SELECT *,ST_X(ST_Centroid(geom)) AS lon,"
                    "ST_Y(ST_Centroid(geom)) AS lat FROM areas ORDER BY code"
                )
            )
            .mappings()
            .all()
        )
        admin: UUID = c.execute(
            text("SELECT id FROM users WHERE auth_subject='demo-admin'")
        ).scalar_one()
        for n in range(20):
            c.execute(
                text("INSERT INTO users(id,auth_subject,display_name) VALUES(:id,:subject,:name)"),
                {
                    "id": fixed("user", n),
                    "subject": f"load-citizen-{n}",
                    "name": f"Synthetic load citizen {n}",
                },
            )
            c.execute(
                text("INSERT INTO user_roles(user_id,role) VALUES(:id,'citizen')"),
                {"id": fixed("user", n)},
            )
            c.execute(
                text("INSERT INTO user_roles(user_id,role) VALUES(:id,'reviewer')"),
                {"id": fixed("user", n)},
            )
        categories = ["pothole", "garbage_accumulation", "sewage_overflow", "streetlight_failure"]
        for n in range(300):
            a = areas[n % 6]
            category = categories[(n // 6) % 4]
            c.execute(
                text("""INSERT INTO issues(id,public_reference,pilot_id,category_code,geom,
              area_id,boundary_version,first_accepted_at,most_recent_accepted_at,synthetic)
              VALUES(:id,:ref,:pilot,:category,ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography,
                :area,:boundary,:at,:at,true)"""),
                {
                    "id": fixed("issue", n),
                    "ref": f"LOAD-I-{n:04}",
                    "pilot": a["pilot_id"],
                    "category": category,
                    "lon": a["lon"] + (n // 24 % 5) * 0.001,
                    "lat": a["lat"] + (n // 120) * 0.001,
                    "area": a["id"],
                    "boundary": a["boundary_version"],
                    "at": AS_OF - timedelta(hours=n % 96),
                },
            )
        for n in range(1000):
            index = n % 300
            a = areas[index % 6]
            category = categories[(index // 6) % 4]
            state = (
                "admitted"
                if n < 970
                else ["rejected", "out_of_scope", "awaiting_review"][(n - 970) // 10]
            )
            at = AS_OF - timedelta(hours=index % 96) + timedelta(minutes=n // 300)
            c.execute(
                text("""INSERT INTO reports(id,public_reference,reporter_id,description,
              claimed_category,canonical_category,state,confirmed_point,area_id,boundary_version,
              pilot_id,received_at,synthetic,validation_status,validation_revision,location_evidence)
              VALUES(:id,:ref,:user,:description,:category,:category,:state,
                ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography,:area,:boundary,:pilot,:at,true,
                :validation,1,CAST(:evidence AS jsonb))"""),
                {
                    "id": fixed("report", n),
                    "ref": f"LOAD-R-{n:04}",
                    "user": fixed("user", n % 20),
                    "description": f"Synthetic release fixture {n}; not a real complaint",
                    "category": category,
                    "state": state,
                    "lon": 77.5
                    if state == "out_of_scope"
                    else a["lon"] + (index // 24 % 5) * 0.001,
                    "lat": 12.8 if state == "out_of_scope" else a["lat"] + (index // 120) * 0.001,
                    "area": None if state == "out_of_scope" else a["id"],
                    "boundary": a["boundary_version"],
                    "pilot": a["pilot_id"],
                    "at": at,
                    "validation": "accepted"
                    if state == "admitted"
                    else "rejected"
                    if state == "rejected"
                    else "needs_review",
                    "evidence": json.dumps({"synthetic_fixture": True}),
                },
            )
            output = BytesIO()
            Image.new("RGB", (12, 8), (n % 256, n // 256, 137)).save(output, "PNG")
            original = output.getvalue()
            photo = decode_photo(original, "image/png", settings)
            media = fixed("media", n)
            original_key = f"{media.hex}/original"
            display_key = f"{media.hex}/display.jpg"
            storage.put(original_key, original)
            storage.put(display_key, photo.derivative)
            c.execute(
                text("""INSERT INTO media(id,report_id,owner_id,storage_key,derivative_key,
              original_sha256,derivative_sha256,mime,width,height,byte_size,processing_state,
              completed_at,expires_at)
              VALUES(:id,:report,:user,:original,:display,:hash,:display_hash,
              'image/png',12,8,:size,'ready',:at,:expiry)"""),
                {
                    "id": media,
                    "report": fixed("report", n),
                    "user": fixed("user", n % 20),
                    "original": original_key,
                    "display": display_key,
                    "hash": photo.original_hash,
                    "display_hash": photo.derivative_hash,
                    "size": len(original),
                    "at": at,
                    "expiry": at + timedelta(hours=1),
                },
            )
            c.execute(
                text("""INSERT INTO validation_results(report_id,media_id,report_revision,
              media_sha256,provider,provider_version,decision,labels,reviewer_id,request_id,completed_at,reason)
              VALUES(:report,:media,1,:hash,'human_review','synthetic-release-v1',:decision,'[]',
                :admin,:request,:at,'Synthetic seeded decision; no real-world validation')"""),
                {
                    "report": fixed("report", n),
                    "media": media,
                    "hash": photo.original_hash,
                    "admin": admin,
                    "request": fixed("validation", n),
                    "at": at,
                    "decision": "accepted" if state == "admitted" else "needs_review",
                },
            )
            if state == "admitted":
                c.execute(
                    text("""INSERT INTO issue_report_links(id,report_id,issue_id,method,
                  actor_id,rule_version,reason,created_at,independent_evidence)
                  VALUES(:id,:report,:issue,'reviewed_duplicate',:admin,'release-v1',
                  'Synthetic reviewed fixture',:at,true)"""),
                    {
                        "id": fixed("link", n),
                        "report": fixed("report", n),
                        "issue": fixed("issue", index),
                        "admin": admin,
                        "at": at,
                    },
                )
        for n in range(300):
            refresh_aggregates(c, fixed("issue", n))
            revision: int = c.execute(
                text("SELECT row_version FROM issues WHERE id=:id"), {"id": fixed("issue", n)}
            ).scalar_one()
            refresh(c, fixed("issue", n), revision, as_of=AS_OF)
        c.exec_driver_sql("UPDATE jobs SET status='completed' WHERE type='refresh_priority'")
        operator_id: UUID = c.execute(
            text("SELECT id FROM users WHERE auth_subject='demo-operator'")
        ).scalar_one()
        media = fixed("media", 1000)
        original = storage.read(f"{fixed('media', 0).hex}/original")
        photo = decode_photo(original, "image/png", settings)
        storage.put(f"{media.hex}/original", original)
        storage.put(f"{media.hex}/display.jpg", photo.derivative)
        c.execute(
            text("""INSERT INTO media(id,owner_id,repair_issue_id,storage_key,derivative_key,
          original_sha256,derivative_sha256,mime,width,height,byte_size,processing_state,completed_at)
          VALUES(:id,:owner,:issue,:original,:display,:hash,:display_hash,'image/png',12,8,
            :size,'ready',:at)"""),
            {
                "id": media,
                "owner": operator_id,
                "issue": fixed("issue", 0),
                "original": f"{media.hex}/original",
                "display": f"{media.hex}/display.jpg",
                "hash": photo.original_hash,
                "display_hash": photo.derivative_hash,
                "size": len(original),
                "at": AS_OF,
            },
        )
        c.execute(
            text("""INSERT INTO resolution_records(id,issue_id,repaired_at,operator_id,notes,
          evidence_media_ids,verifier_id,verification_state,decided_at,issue_revision)
          VALUES(:id,:issue,:at,:operator,'Synthetic failed repair retained in history',
          CAST(:media AS jsonb),:admin,'failed',:at,2)"""),
            {
                "id": fixed("repair", 0),
                "issue": fixed("issue", 0),
                "at": AS_OF,
                "operator": operator_id,
                "admin": admin,
                "media": json.dumps([str(media)]),
            },
        )


def percentile(values: list[float]) -> float:
    return round(sorted(values)[max(0, int(len(values) * 0.95) - 1)] * 1000, 2)


def main() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 8002))
    root = PROJECT_ROOT / ".local" / f"release-{uuid4().hex}"
    root.mkdir(parents=True)
    results: dict[str, Any] = {
        "tested_at": datetime.now(UTC).isoformat(),
        "synthetic": True,
        "fixture_version": "release-v1",
        "fixture_as_of": AS_OF.isoformat(),
        "hardware": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpus": os.cpu_count(),
        },
        "concurrency": 20,
        "distinct_load_identities": 20,
        "reports": 1000,
        "issues": 300,
    }
    if os.name == "nt":
        results["hardware"]["physical_memory_bytes"] = int(
            subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory",
                ],
                text=True,
            ).strip()
        )
    with temporary_database() as (engine, settings):
        migrate(engine, "head")
        storage = LocalMedia(root / "media")
        seed(engine, settings, storage)
        print("Seeded 1000 reports / 300 issues in isolated database", flush=True)
        container = subprocess.check_output(
            ["docker", "compose", "ps", "-q", "db"], cwd=PROJECT_ROOT, text=True
        ).strip()
        database = make_url(settings.database_url).database
        assert database and database.endswith("_test")
        dump = subprocess.check_output(
            ["docker", "exec", container, "pg_dump", "-U", "nagarsaathi_demo", "-Fc", database]
        )
        (root / "database.dump").write_bytes(dump)
        with zipfile.ZipFile(root / "media.zip", "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in storage.root.rglob("*"):
                if path.is_file():
                    bundle.write(path, path.relative_to(storage.root).as_posix())
        with temporary_database() as (restored, restore_settings):
            restore_name = make_url(restore_settings.database_url).database
            subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    container,
                    "pg_restore",
                    "-U",
                    "nagarsaathi_demo",
                    "--no-owner",
                    "--exit-on-error",
                    "-d",
                    str(restore_name),
                ],
                input=dump,
                check=True,
                capture_output=True,
            )
            with zipfile.ZipFile(root / "media.zip") as bundle:
                assert bundle.testzip() is None
                bundle.extractall(root / "restored-media")
            restored_storage = LocalMedia(root / "restored-media")
            with restored.connect() as c:
                assert c.exec_driver_sql("SELECT count(*) FROM reports").scalar_one() == 1000
                repair = (
                    c.execute(
                        text("SELECT * FROM resolution_records WHERE id=:id"),
                        {"id": fixed("repair", 0)},
                    )
                    .mappings()
                    .one()
                )
                assert repair["verification_state"] == "failed"
                assert repair["evidence_media_ids"] == [str(fixed("media", 1000))]
                assert c.execute(
                    text("SELECT repair_issue_id FROM media WHERE id=:id"),
                    {"id": fixed("media", 1000)},
                ).scalar_one() == fixed("issue", 0)
                for m in c.exec_driver_sql("SELECT * FROM media").mappings():
                    assert (
                        hashlib.sha256(restored_storage.read(m["storage_key"])).hexdigest()
                        == m["original_sha256"]
                    )
                    assert (
                        hashlib.sha256(restored_storage.read(m["derivative_key"])).hexdigest()
                        == m["derivative_sha256"]
                    )
            results["backup_restore"] = {
                "passed": True,
                "media_originals_checked": 1001,
                "derivatives_checked": 1001,
                "repair_history_checked": True,
                "dump_sha256": hashlib.sha256(dump).hexdigest(),
            }
        env = {
            **os.environ,
            "DATABASE_URL": settings.database_url,
            "STORAGE_ROOT": str(storage.root),
            "APP_MODE": "test",
        }
        with (root / "api.log").open("w") as log:
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "scripts.release_validation:load_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8002",
                ],
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                with httpx.Client(base_url="http://127.0.0.1:8002", timeout=30) as client:
                    for _ in range(100):
                        try:
                            if client.get("/api/v1/health/ready").status_code == 200:
                                break
                        except httpx.ConnectError:
                            pass
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("Release test API did not become ready")

                    def read(index: int) -> float:
                        start = time.perf_counter()
                        response = client.get(
                            "/api/v1/staff/queue",
                            params={
                                "area": [
                                    "southwest",
                                    "northwest",
                                    "southeast",
                                    "northeast",
                                    "north_central",
                                    "south_central",
                                ][index % 6],
                                "category": "pothole",
                                "limit": 20,
                            },
                            headers={"Authorization": f"Bearer load-citizen-{index % 20}"},
                        )
                        response.raise_for_status()
                        return time.perf_counter() - start

                    with ThreadPoolExecutor(max_workers=20) as pool:
                        timings = list(pool.map(read, range(100)))
                    results["queue"] = {
                        "requests": 100,
                        "p95_ms": percentile(timings),
                        "target_ms": 500,
                        "passed": percentile(timings) < 500,
                    }
                    print("Queue load measured", results["queue"], flush=True)

                    def submit(index: int) -> float:
                        headers = {"Authorization": f"Bearer load-citizen-{index % 20}"}
                        photo = client.post(
                            "/api/v1/uploads",
                            headers={**headers, "Content-Type": "image/png"},
                            content=storage.read(f"{fixed('media', index).hex}/original"),
                        )
                        photo.raise_for_status()
                        media = photo.json()["id"]
                        client.post(
                            f"/api/v1/uploads/{media}/complete", headers=headers
                        ).raise_for_status()
                        start = time.perf_counter()
                        response = client.post(
                            "/api/v1/reports",
                            headers={**headers, "Idempotency-Key": str(uuid4())},
                            json={
                                "description": "Synthetic concurrent release submission",
                                "claimed_category": "pothole",
                                "media_ids": [media],
                                "location": {
                                    "longitude": 77.615,
                                    "latitude": 12.915,
                                    "confirmed": True,
                                },
                            },
                        )
                        response.raise_for_status()
                        return time.perf_counter() - start

                    with ThreadPoolExecutor(max_workers=20) as pool:
                        timings = list(pool.map(submit, range(40)))
                    results["metadata_submission"] = {
                        "requests": 40,
                        "p95_ms": percentile(timings),
                        "target_ms": 1000,
                        "passed": percentile(timings) < 1000,
                        "excludes_upload": True,
                    }
                    assert (
                        client.get(
                            "/api/v1/staff/queue", headers={"Authorization": "Bearer demo-citizen"}
                        ).status_code
                        == 403
                    )
                    assert client.get("/api/v1/staff/queue").status_code == 401
                start = time.perf_counter()
                while process_once(engine, HumanReviewValidator()):
                    if time.perf_counter() - start > 60:
                        raise RuntimeError("Processing exceeded validation budget")
                with engine.connect() as c:
                    rows = (
                        c.execute(
                            text(
                                "SELECT state,received_at FROM reports "
                                "WHERE public_reference NOT LIKE 'LOAD-%'"
                            )
                        )
                        .mappings()
                        .all()
                    )
                    assert len(rows) == 40 and all(r["state"] == "awaiting_review" for r in rows)
                    processing = [
                        (datetime.now(UTC) - r["received_at"]).total_seconds() for r in rows
                    ]
                results["processing_to_human_review"] = {
                    "reports": 40,
                    "p95_ms": percentile(processing),
                    "target_ms": 30000,
                    "passed": percentile(processing) < 30000,
                    "automatic_admission_measured": False,
                }
                start = time.perf_counter()
                for _ in range(10):
                    count = schedule_age_refresh(engine)
                    while process_once(engine, HumanReviewValidator()):
                        pass
                    if not count:
                        break
                with engine.connect() as c:
                    stale = c.exec_driver_sql(
                        "SELECT count(*) FROM issues i JOIN priority_snapshots s "
                        "ON s.id=i.current_priority_snapshot_id "
                        "WHERE s.as_of<now()-interval '15 minutes'"
                    ).scalar_one()
                results["age_refresh"] = {
                    "issues": 300,
                    "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
                    "remaining_stale": stale,
                    "passed": stale == 0 and time.perf_counter() - start < 900,
                }
            finally:
                server.terminate()
                server.wait(timeout=15)
    results["runtime_artifacts"] = str(root.relative_to(PROJECT_ROOT))
    (PROJECT_ROOT / "docs/release-validation.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(results, indent=2), flush=True)


if __name__ == "__main__":
    main()
