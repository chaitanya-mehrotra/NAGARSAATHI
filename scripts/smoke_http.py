"""Check the real local API and Vite proxy after starting both servers."""

import httpx


def main() -> None:
    with httpx.Client(timeout=10) as client:
        live = client.get("http://127.0.0.1:8000/api/v1/health/live")
        live.raise_for_status()
        assert live.json()["status"] == "ok"
        ready = client.get("http://127.0.0.1:8000/api/v1/health/ready")
        ready.raise_for_status()
        assert ready.json()["checks"] == {"postgis": True, "storage": True}
        page = client.get("http://127.0.0.1:5173/")
        page.raise_for_status()
        assert 'id="root"' in page.text
        config = client.get("http://127.0.0.1:5173/api/v1/config/public")
        config.raise_for_status()
        assert config.json()["synthetic"] is True
        assert len(config.json()["categories"]) == 5
        assert len(config.json()["pilot"]["service_areas"]) == 6
    print("Real HTTP smoke passed: API liveness, PostGIS/storage readiness, web and API proxy.")


if __name__ == "__main__":
    main()
