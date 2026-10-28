# Running NAGARSAATHI V2 locally (without Docker for the app)

Docker is used only for the database. The API, worker and web app run directly on your machine,
which is the fastest loop for development. For the all-in-Docker route see the README.

## One-time setup

You need Docker Desktop, Python 3.12 and Node 20+. Commands are for Git Bash or PowerShell from the
project root.

```bash
cp .env.example .env                   # then edit it, see "Settings" below
docker compose up -d --wait db         # PostGIS database on 127.0.0.1:5432

uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -e . --group dev
uv pip install --native-tls --python .venv/Scripts/python.exe "ultralytics>=8.3,<9"
npm install
```

Notes:

- `--native-tls` makes `uv` use the Windows certificate store. Without it the PyTorch download can
  fail with `invalid peer certificate: UnknownIssuer` on some networks. PyTorch is large; the
  first install takes several minutes.
- On macOS/Linux use `.venv/bin/python` and `.venv/bin/alembic` instead of `.venv/Scripts/...`.

## Create and seed the demo database

The seed script refuses to run on any database whose name does not end in `_demo` or `_test`, so
your data is never touched by accident. `.env.example` already uses `nagarsaathi_v2_demo`.

```bash
export PYTHONPATH=services/api:services/worker      # PowerShell: $env:PYTHONPATH="services/api;services/worker"
.venv/Scripts/alembic.exe upgrade head
.venv/Scripts/python.exe scripts/seed_demo.py       # pilot area, categories, demo identities
```

Optional demo complaints (needs the API and worker running, and any photo of a pothole):

```bash
.venv/Scripts/python.exe scripts/seed_demo_complaints.py --photo path/to/pothole.jpg
```

## Run the three processes

Open three terminals (all with `PYTHONPATH` set as above):

```bash
# 1. API on http://127.0.0.1:8000  (docs at /docs)
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2. Worker: validates photos with YOLO, admits reports, refreshes priority
.venv/Scripts/python.exe -m worker

# 3. Web app on http://localhost:5173 (proxies /api to the API)
cd apps/web && npx vite --host 127.0.0.1 --port 5173 --strictPort
```

Tips:

- Run the web app with `npx vite ...` from `apps/web`. `npm run dev -- --port 5173` loses the
  `--port` flag and Vite then treats `5173` as a folder.
- Do not use `uvicorn --reload` inside a OneDrive folder; file watching is unreliable there.
  Restart the API after code changes. The web app hot-reloads on its own.
- Stop the worker before dropping the database; it exits when its connection is cut.

## Settings (`.env`)

| Variable | Meaning |
|---|---|
| `APP_MODE` | `demo` (default, enables demo accounts), `test`, or `production`. |
| `DATABASE_URL` | Must point at a database ending in `_demo`/`_test` for seeding. |
| `JWT_SECRET` | Signs session tokens. Production refuses the default value. |
| `GOOGLE_CLIENT_ID` | Enables Google sign-in. See [GOOGLE_SIGN_IN.md](GOOGLE_SIGN_IN.md). |
| `VALIDATION_PROVIDER` | `yolo` (real detector), `fixture` (tests) or `human_review`. |
| `YOLO_DEVICE` | `cpu` (default) or a GPU such as `cuda:0`. |
| `STORAGE_ROOT` | Where photos are stored (default `.local/media`). |
| `CORS_ORIGINS` | Comma-separated allowed browser origins. |

## Tests

```bash
# Backend: needs a database named *_test, because the suite creates and drops temporary databases
docker compose exec -T db psql -U nagarsaathi -d postgres -c "CREATE DATABASE nagarsaathi_v2_test"
export DATABASE_URL="postgresql://nagarsaathi:nagarsaathi_secret_local@127.0.0.1:5432/nagarsaathi_v2_test"
export VALIDATION_PROVIDER=fixture
.venv/Scripts/python.exe -m pytest services/api/tests

# Frontend
npm run typecheck && npm test
```

## Trying the photo check

1. Sign in (Google, or Demo Citizen in demo mode) at http://localhost:5173.
2. Report an issue with a **pin inside the pilot area** (longitude 77.60–77.69, latitude 12.90–12.96,
   for example Silk Board or HSR Layout). Pins outside it are marked "out of scope".
3. Choose a category that matches the photo (pothole or waterlogging) and submit.
4. Within about 20 seconds the worker validates the photo. A photo that does not match the chosen
   category, or in which the detector finds nothing, is flagged "Suspicious" and held for human
   review. It is never rejected automatically.
5. Sign in as Demo Admin to review flagged reports.

The detector only knows potholes and waterlogging, so reports in other categories are always
flagged for human review.
