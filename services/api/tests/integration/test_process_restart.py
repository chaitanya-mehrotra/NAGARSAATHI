"""Real loopback HTTP and process restart, using the disposable PostGIS test database."""

import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from io import BytesIO
from uuid import uuid4

import httpx
from app.settings import PROJECT_ROOT
from PIL import Image


@contextmanager
def server(settings, storage, port, log_path):
    environment = {
        **os.environ,
        "APP_MODE": "test",
        "AUTH_PROVIDER": "demo",
        "VALIDATION_PROVIDER": "fixture",
        "DATABASE_URL": settings.database_url,
        "STORAGE_ROOT": str(storage),
    }
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            url = f"http://127.0.0.1:{port}"
            with httpx.Client(base_url=url, timeout=5) as client:
                for _ in range(100):
                    if process.poll() is not None:
                        raise AssertionError("Test API exited before becoming ready")
                    try:
                        if client.get("/api/v1/health/ready").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    raise AssertionError("Test API did not become ready")
                yield client
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_report_and_private_photo_survive_process_restart(spatial_database, tmp_path):
    _, settings = spatial_database
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    owner = {"Authorization": "Bearer demo-citizen"}
    output = BytesIO()
    Image.new("RGB", (9, 7), "red").save(output, format="PNG")
    with server(settings, tmp_path / "media", port, tmp_path / "first.log") as client:
        upload = client.post(
            "/api/v1/uploads",
            content=output.getvalue(),
            headers={**owner, "Content-Type": "image/png"},
        )
        assert upload.status_code == 201
        media_id = upload.json()["id"]
        assert client.post(f"/api/v1/uploads/{media_id}/complete", headers=owner).status_code == 200
        response = client.post(
            "/api/v1/reports",
            headers={**owner, "Idempotency-Key": uuid4().hex},
            json={
                "description": "Synthetic restart test",
                "claimed_category": "pothole",
                "media_ids": [media_id],
                "location": {"longitude": 77.615, "latitude": 12.915, "confirmed": True},
            },
        )
        assert response.status_code == 201
        report = response.json()
    with server(settings, tmp_path / "media", port, tmp_path / "second.log") as client:
        response = client.get(f"/api/v1/reports/{report['id']}", headers=owner)
        assert response.status_code == 200 and response.json() == report
        assert client.get(report["media"][0]["content_url"], headers=owner).status_code == 200
        other = {"Authorization": "Bearer demo-citizen-2"}
        assert client.get(f"/api/v1/reports/{report['id']}", headers=other).status_code == 404
        assert client.get(report["media"][0]["content_url"], headers=other).status_code == 404
