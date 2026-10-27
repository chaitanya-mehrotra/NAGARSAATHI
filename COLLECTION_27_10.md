# Collection (27/10)

Git branch: **`Collection-27-10`**. Git does not permit spaces in branch names; this is the valid spelling of the requested name. This is a selective feature integration into Chaitanya's working application, not two unrelated apps running side by side.

## Compared sources and decisions

Compared `chaitanya's-UI` at `23be30b` with `main` at `5d86561` (V2). Main's work lifecycle also derives from its original `07c3d40` domain implementation. Main's separate TypeScript/PostGIS runtime is not copied wholesale over the working React/FastAPI/SQLite app.

| Feature | Collection decision |
| --- | --- |
| Chaitanya overview, sidebar, colors, map, wizard and mobile layout | Preserved; existing stylesheets are unchanged |
| Trained combined YOLO11n pothole/waterlogging model | Preserved unchanged, including the committed weights |
| Immediate storage, durable queue, outbound admin-PC worker | Preserved; the intake API still cannot load the model |
| Conservative grouping, report/account counts, uncertainty queue | Preserved; duplicate reports remain stored and linked |
| Automatic publication and explainable demand/age priority | Preserved; no invented physical severity or traffic measurements |
| Main's soft delete and restore | Adapted as administrator-only archive/restore with reasons and history |
| Main's work assignments and repair records | Adapted to existing admin/Nigam roles, version checks, private repair photos and independent approval |
| Main's activity history | Added to issue details, with role-filtered work/repair events |
| Main's Google login | Reimplemented as optional verified citizen sign-in alongside password accounts |
| Demo admin login or privileges inferred from email text | Excluded: public login must not grant staff access |
| Unsigned Google JWT decoding / email-only login claims | Excluded: Google signature, audience, issuer, expiry, verified email and a one-use nonce are required |
| Delete duplicate reports and keep one | Excluded: contradicts preserving all submissions and counts |
| Calling a model mismatch suspicious/fake | Excluded: uncertain evidence stays in review |
| Synthetic Bengaluru boundaries, traffic weights and fictional POIs | Not applied to real reports; trustworthy local datasets and a validated policy are required |
| Other categories, PostGIS area grants, dedicated operators, field/SLA escalation and mail-server flows | Not exposed in this runtime; this release keeps two trained categories, three roles and single-instance storage. It is not full feature parity with main's domain engine |

## Workflow and views

1. **Citizen:** upload description/photo/location, receive tracking number, follow their own verification and repair statuses. No model, AI scores, grouping or priority controls run on the phone.
2. **Admin:** monitor all active submissions, worker/queue health, exceptions, shared issues, counts and automatic priority. Archived reports have their own private tab and can be restored. Admin can assign an eligible issue to an existing staff account and review repair evidence.
3. **Nagar Nigam:** see published consolidated issues only, counts and priority explanations. Assigned staff upload a repair photo. A different platform administrator verifies it, then every linked citizen sees resolved.

Analysis, grouping, publication and priority remain automatic. Assignments and independent repair approval are optional staff operations. No physical repair or team roster can be inferred from an upload. Existing unassigned issues retain the earlier audited status-update flow; once an assignment exists, direct resolution is blocked until independent approval.

## Counts and archives

`report_count`, `reporter_count` and `unique_photo_count` retain historical membership, including archived members. `active_report_count`, `active_reporter_count` and `archived_report_count` distinguish moderation effects. Priority uses supported, unarchived distinct accounts and the age of active reports. Groups with no active reports disappear from Nigam's queue; admins retain their history.

Archiving is not duplicate removal. It needs a reason, revokes in-flight worker access and preserves the original photo/membership. Repeated archive/restore requests do not duplicate audit entries. Restoring an interrupted submission creates a new job identity; stale results cannot overwrite it. Restoring supported reports recomputes publication/counts.

## Existing Windows installation — Command Prompt

```cmd
cd /d D:\nagarsaathi-model\integrations\NAGARSAATHI-chaitanya-ui
git switch Collection-27-10
git pull --ff-only origin Collection-27-10
uv pip install --python .venv\Scripts\python.exe -r backend\requirements-api.txt
npm ci
```

The existing environment uses uv. For a standard pip-enabled environment, use `python -m pip install -r backend\requirements-api.txt` instead. The PC already has model/worker dependencies; this adds Google's verification library without replacing Torch or the model.

Keep existing `.env` and `.local/worker.env`. For a fresh clone, copy `.env.example` to `.env`, install [backend/requirements-worker.txt](backend/requirements-worker.txt) in a Python 3.13 environment and run `python -m backend.configure_worker` once. See [backend/PROCESSING.md](backend/PROCESSING.md). Never put a raw worker key into frontend configuration or Git.

Run these in **three separate terminals** from the same project folder:

```cmd
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8002
```

```cmd
.venv\Scripts\python.exe -m backend.pc_worker
```

```cmd
npm run dev -- --port 5174 --strictPort
```

Open **http://127.0.0.1:5174**; API docs are **http://127.0.0.1:8002/docs**. Stop an older instance using the same port in its original terminal before starting another.

Reuse existing staff accounts. For a fresh database, provision them in a private terminal:

```cmd
.venv\Scripts\python.exe -m backend.accounts platform-admin@example.com --name "Platform Admin"
.venv\Scripts\python.exe -m backend.accounts nigam-officer@example.com --name "Nagar Nigam" --role nigam
```

Example emails are placeholders. Commands prompt for passwords; public registration never creates staff. If an admin personally submits repair evidence, a second admin must approve it. Normally Nigam submits and the platform admin verifies.

## Docker mode

With Docker Desktop ready:

```cmd
docker compose up -d --build --wait
```

Open **http://127.0.0.1:5180**. This starts UI/API, not inference. The separate PC worker must point to `http://127.0.0.1:5180/api` with the matching server fingerprint. `python -m backend.configure_worker --help` documents `--api-url`; review existing configuration before repointing/rotating it.

Docker's `complaint_data` volume is mounted at `/var/data`. Local development uses `backend/data`. These are separate databases/accounts. Do not use `docker compose down -v` for ordinary restarts: it deletes the named volume. Docker startup is optional for local development. `render.yaml` is a proposed paid hosting configuration, not an existing public deployment; this work creates no cloud resources or charges.

## New API contract

Paths are relative to the API base: direct dev has no prefix, Docker uses `/api`. Browser requests carry `Authorization: Bearer <session>`.

| Operation | Request | Permission |
| --- | --- | --- |
| Archive | `POST /moderation/reports/21/archive`, `{"reason":"Off-topic photo after review"}` | Admin |
| Archive list | `GET /moderation/reports?limit=20&offset=0` | Admin |
| Restore | `POST /moderation/reports/21/restore`, required reason | Admin |
| Moderation history | `GET /moderation/reports/21/history` | Admin |
| Assignable accounts | `GET /work/accounts` | Admin, names/roles only |
| Assign | `PUT /issues/7/assignment`, `{"assigned_to":3,"team":"Road crew","note":"Inspect junction","expected_version":0}` | Admin, active published issue |
| Work detail | `GET /issues/7/work` | Authorized admin/Nigam |
| Repair submission | `POST /issues/7/repairs`, multipart image/note/expected_version, `Idempotency-Key` header | Assigned account |
| Repair photo | `GET /issues/7/repairs/4/photo` | Authorized staff |
| Repair review | `POST /issues/7/repairs/4/review`, `{"decision":"verified","note":"Independent inspection","expected_version":2}` | A different platform admin |
| Return for more work | Same review endpoint, `decision:"rejected"` | A different platform admin |
| Issue history | `GET /issues/7/history` | Admin; Nigam gets work/repair events only |

Read `assignment.version` from work detail before changing work; zero is only for initial assignment. Stale versions return 409. Same-key/same-payload repair uploads replay the same evidence; changed content returns 409. Assigned repairs remain in progress until approval. Changed membership after repair submission blocks verification until evidence is rejected/rechecked. Missing/changed repair photo bytes cannot be approved.

Compatibility fixes connect the existing frontend's `/reports/{id}/review` and `/retry` aliases, `needs_attention`, `queue=resolved`, processing health and report/issue summary fields to the backend.

## Optional Google citizen sign-in

1. Create a Google OAuth **Web application** client. Register exact JavaScript origins, for example `http://127.0.0.1:5174`, `http://127.0.0.1:5180` and the eventual HTTPS public origin.
2. Set backend `GOOGLE_CLIENT_ID` in `.env` or the hosting environment, then restart the API/container. Compose passes it through. It is a public client identifier, not a client secret.
3. The existing sign-in drawer gets the ID from `/auth/options` and displays Google's button. No frontend rebuild is needed to change that backend setting.
4. `google-auth` verifies signature/audience/expiry/issuer; the API checks verified email and consumes a five-minute one-use nonce before issuing a local session. No email-only payload or unsigned JWT is accepted.
5. Google creates citizens only. If the email already has a password/staff account, use that password. Automatic account linking is disabled; staff passwords remain required.

Reference: [Google's ID-token verification guide](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token). A live provider journey requires your own client ID. Tests use controlled claims and check the verifier's rejection path; no Google account/client was created for you.

## Checks and limits

```cmd
.venv\Scripts\python.exe -m unittest discover -s backend -p "test_*.py" -v
npm test
npm run build
```

Browser acceptance uses Playwright with Microsoft Edge. Install Playwright in a separate tools folder, set `PLAYWRIGHT_MODULE` to its absolute `index.mjs` path if needed, start Vite on port 5176, set `UI_TEST_URL=http://127.0.0.1:5176`, then run `npm run test:browser`. These tests intercept the API with fictional fixtures; separate backend HTTP tests cover authorization, transactions and state changes. Map tiles/fonts are blocked in fixtures to remove third-party dependencies.

The model is unchanged. Cross-view automatic grouping remains off until field evaluation; ambiguous nearby photos need review. Priority measures demand and age, not physical severity. Repair approval is a recorded human decision, not AI proof of a physical repair. There is no operator-area tenancy, Google account-linking/password-reset UI, API rate limiter, production mail delivery or multi-instance database support. Local passing tests do not establish production hardening.

Validated on this Windows PC for the 27 October integration: **40 backend tests**, **9 frontend unit tests**, **10 browser acceptance journeys**, production Vite build, Compose configuration validation and `git diff --check` all passed. The browser checks include archive/restore and assignment → Nigam repair photo → independent admin approval. Model SHA-256 remains `748e47702e7fa7068ab64a9005cbefb02873e0190eff67496dbd2ef2a8f6a676`. A new Docker image build, public deployment and live Google-provider account flow have not been verified in this task.

SQLite migrations are additive, with a pre-migration backup before archive columns are added. Existing accounts, sessions, report IDs, photos and memberships are retained. Back up the **entire data directory**, including `photos/` and new `repairs/`, before releases. Backups, databases, uploads and secrets stay out of Git. Older PostgreSQL installations require a separately planned migration; their data is neither imported nor discarded automatically.
