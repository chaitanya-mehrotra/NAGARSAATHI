"""One-window launcher: migrate, seed, run the API, the YOLO worker and a Cloudflare tunnel,
then publish the tunnel URL so the Vercel site finds this laptop automatically.

Run via start.bat. Logs go to logs/. Ctrl+C (or closing the window) stops everything.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
LOGS = ROOT / "logs"
METRICS = "127.0.0.1:20241"
BUCKET = "public-config"
CONFIG_FILE = "api-url.json"


def run_step(name: str, args: list[str]) -> None:
    print(f"{name}...", flush=True)
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout[-1500:], result.stderr[-1500:], sep="\n")
        raise SystemExit(f"{name} failed - check DATABASE_URL in .env")


def spawn(name: str, args: list[str]) -> subprocess.Popen[bytes]:
    log = open(LOGS / f"{name}.log", "wb")
    return subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)


def tunnel_host(timeout: float = 60) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            host = httpx.get(f"http://{METRICS}/quicktunnel", timeout=2).json()["hostname"]
            if host:
                return f"https://{host}"
        except (httpx.HTTPError, KeyError, ValueError):
            pass
        time.sleep(1)
    raise SystemExit("The tunnel did not come up - see logs/tunnel.log")


def publish(supabase_url: str, key: str, api_base: str | None) -> None:
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    base = supabase_url.rstrip("/") + "/storage/v1"
    made = httpx.post(
        f"{base}/bucket",
        headers=headers,
        json={"id": BUCKET, "name": BUCKET, "public": True},
        timeout=15,
    )
    if made.status_code >= 400 and "exist" not in made.text.lower():
        raise SystemExit(f"Could not create the {BUCKET} bucket: {made.text[:200]}")
    uploaded = httpx.post(
        f"{base}/object/{BUCKET}/{CONFIG_FILE}",
        headers={**headers, "content-type": "application/json", "x-upsert": "true",
                 "cache-control": "max-age=0"},
        content=json.dumps({"apiBaseUrl": api_base}),
        timeout=15,
    )
    if uploaded.status_code >= 400:
        raise SystemExit(f"Could not publish the tunnel URL: {uploaded.text[:200]}")


def main() -> None:
    env = dotenv_values(ROOT / ".env")
    supabase_url = env.get("SUPABASE_URL") or ""
    key = env.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not (supabase_url and key):
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")
    cloudflared = ROOT / "tools" / "cloudflared.exe"
    if not cloudflared.exists():
        raise SystemExit("tools/cloudflared.exe is missing")
    LOGS.mkdir(exist_ok=True)

    run_step("Applying database migrations", [PY, "-m", "alembic", "upgrade", "head"])
    run_step("Seeding demo data", [PY, "scripts/seed_demo.py"])

    procs = [
        spawn("api", [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"]),
        spawn("worker", [PY, "-m", "worker"]),
        spawn("tunnel", [str(cloudflared), "tunnel", "--metrics", METRICS,
                         "--url", "http://127.0.0.1:8000"]),
    ]
    api_base = None
    try:
        print("Starting API, YOLO worker and tunnel...", flush=True)
        api_base = tunnel_host()
        for _ in range(60):
            try:
                if httpx.get("http://127.0.0.1:8000/api/v1/health/ready", timeout=2).is_success:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            raise SystemExit("The API did not become ready - see logs/api.log")
        publish(supabase_url, key, api_base)
        print(f"\nReady. Public API: {api_base}\nThe Vercel site is now connected to this laptop.\n"
              "Leave this window open while you demo. Press Ctrl+C to stop.", flush=True)
        while all(p.poll() is None for p in procs):
            time.sleep(2)
        print("A component exited - see logs/. Stopping.")
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        try:
            publish(supabase_url, key, None)  # tell the site the server is offline
        except (SystemExit, httpx.HTTPError):
            pass
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
