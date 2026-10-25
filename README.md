# NAGARSAATHI

A local civic complaint pilot for southeast Bengaluru. The implementation follows
`../CIVIC_COMPLAINT_PLATFORM_IMPLEMENTATION_PLAN.md`. Checkpoints 0–9 are available:
the app shell, configuration, contracts, provider interfaces, dependency health,
PostGIS schema, demo seed, geographic ownership checks, authentication, private
uploads, durable report APIs and citizen submission/tracking screens;
photo/category/location review, shared issues, duplicate comparisons and merge/split
history, explained priority scoring, a filtered staff queue/map, area/category comparisons
and scoped assignment controls are available. Operators can submit repair evidence for
independent verification, with archive/history and reopening available to reviewers.

The demo has no GPU, model, paid mapping provider or external account dependency.
It is not an official municipal complaint service. All identity fixtures and service
areas are synthetic. The proposed pilot boundary has not been reviewed.

## Local startup (Windows PowerShell)

Prerequisites: Python 3.11, uv, Node.js 20.19+ (or 22.12+), npm, Docker Desktop with
the Linux engine running. Tested with Python 3.11.9 and Node 24.19.0.

Run from this `nagarsaathi` folder:

```powershell
Copy-Item .env.example .env
uv sync --locked --python 3.11
npm.cmd ci
docker compose up -d --wait
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe scripts/seed_demo.py
```

Start the API in one terminal:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Start the frontend in another terminal, from the same folder:

```powershell
npm.cmd run dev
```

Open <http://127.0.0.1:5173>. API docs: <http://127.0.0.1:8000/docs>.
The frontend development proxy forwards `/api` to the API; no external network
service is needed after installing dependencies and downloading the database image.

Health endpoints:

- `/api/v1/health/live` checks that the API responds.
- `/api/v1/health/ready` checks a real PostGIS query and private local storage access.
  It returns HTTP 503 when either dependency is unavailable.
- `/api/v1/config/public` returns the configured pilot and categories without secrets.

Checkpoint 2 API endpoints require a bearer identity token. In demo mode, use
`demo-citizen` or `demo-citizen-2`. Pre-provisioned `demo-reviewer` and `demo-operator`
are scoped to Southwest; `demo-admin` has global read access. These are public
synthetic identities, not secure accounts. Roles are loaded from the database.
Use the **Authorize** button in API docs or the example in `docs/api.md`.
The browser's **Report a problem** and **My reports** links provide the citizen flow.
Choose a demo citizen, select photos, describe one problem, confirm its pin, review
and submit. Staff accounts cannot submit as a citizen without a citizen grant.

Submit through the upload → complete → report API flow. Reports are durable but
pending validation; no image/model approval is implied. Out-of-pilot reports remain
visible to their owner; missing/unconfirmed locations await review.

Start the validation and admission worker in a third terminal:

```powershell
.\.venv\Scripts\python.exe -m worker
```

`--once` processes one ready validation or admission job; `--check` checks dependencies.
Default uncatalogued photos await human review. On `/reviews`, sign in using a
pre-provisioned staff token (for the demo, `demo-reviewer` or `demo-admin`), inspect
the evidence and record a category/location decision with a reason. Southwest staff
cannot view another area's report; unassigned locations require the global admin.
Located acceptance queues admission. With no plausible candidate, a shared issue is
created; nearby candidates await a staff decision in `/reviews/duplicates`. The worker
must be running for queued processing. On `/issues`, inspect linked evidence/history,
merge into a surviving issue or split selected reports with a confirmed pin and reason.
Different trusted inventory assets cannot be linked/merged. Scoped staff need permission
over both areas for cross-area decisions. Report receipts show their linked issue reference.
Priority scores and hazard review are available on `/priority`; issue detail shows factor
contributions and accepts documented severity/urgency decisions. Global demo admins can
preview and activate a versioned scoring epoch on `/priority/policies`. The worker processes
score changes and 15-minute age refreshes. Scores show unknown context, pending urgency and
staleness explicitly. The proposed weights and targets are demonstration policy settings;
real pilot usefulness requires human review. `/staff` provides area/category/status/band,
overdue and map-bounds filters, stable cursor pages and matching numbered map/list order.
`/staff/areas` compares categories and counts within permitted areas. Open an issue for
evidence, score explanations and assignment to an active area-scoped operator. Starting
work is available at `/work` for the assigned operator. Reviewers verify, reject, archive
and reopen from shared issue details. Archive retains reports, evidence and history.

Stop API/frontend with Ctrl+C. `docker compose stop` stops the database while
preserving its volume. No reset or deletion command is provided at this checkpoint.

## Checks

The Python integration tests require the running local PostGIS database. They create
uniquely named disposable test databases, exercise migrations and spatial constraints,
then remove only those databases. They never reset the demo database.

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\mypy.exe
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
npm.cmd run format:check
npm.cmd run test:e2e
docker compose config --quiet
```

After starting both servers, verify the real HTTP startup path:

```powershell
.\.venv\Scripts\python.exe scripts/smoke_http.py
```

Python packages are locked in `uv.lock`; Node packages are locked in
`package-lock.json`. To regenerate the typed API/provider contract after changing
schemas, run:

```powershell
.\.venv\Scripts\python.exe scripts/export_contracts.py
npm.cmd run contracts
npm.cmd run format
```

Production startup rejects demo identity and fixture validation. Even a production
configuration with reviewed settings remains blocked until real providers are wired
in later checkpoints. Do not deploy this scaffold for real complaints.

Checkpoint results and limitations are recorded in `docs/checkpoint-results.md`.
Completed checkpoints are cumulative source ZIPs with SHA-256 manifests in
`../Checkpoints`. Dependencies, local media, secrets and database volumes are excluded.
After completing a checkpoint, archive it with
`.\.venv\Scripts\python.exe scripts/archive_checkpoint.py <number>`.
Continue only when the user commands the next checkpoint.
Checkpoints 8 and 9 are complete. Checkpoint 10 model integration remains deferred.

## Release checks and maintenance

`.venv/Scripts/python.exe scripts/release_validation.py` creates disposable test databases,
seeds fixed synthetic 1,000-report/300-issue fixtures, verifies database/photo restoration
and measures a real local API at 20-user concurrency. It requires development dependencies,
Docker CLI and free port 8002. It never seeds or restores the demo database. Results are in
`docs/release-validation.json`; private runtime backups stay under `.local/release-*`.
Load identities are restricted to the test harness. See `docs/release-validation.md` for
hardware, scope and remaining pilot gates.

`scripts/maintenance.py` previews expired unattached uploads, old orphan files and expired
queue captures. `--apply` removes those disposable entries; report/repair evidence and
archive history remain retained. Review the dry-run and keep backups before applying.
