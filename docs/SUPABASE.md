# Supabase (hosted Postgres + photo storage)

V2 is Postgres/PostGIS, and Supabase is hosted Postgres with PostGIS, so the move is a connection
string plus a storage switch. No application data model changes.

## What you create in Supabase (once)

1. **Project**, free plan, region Mumbai (`ap-south-1`) or the closest one. Use a database
   password of letters and digits only (special characters must be URL-encoded in the URL).
   In "Security" leave **Enable Data API** off and **Enable automatic RLS** on.
2. **Database → Extensions:** enable `postgis`.
3. **Storage → New bucket:** `complaint-photos`, **Public bucket off**. No policies are needed;
   only the backend (with the secret key) reads and writes it.
4. **Connect → Session pooler** connection string (port 5432). Do not use the transaction pooler
   (port 6543): V2 uses advisory locks and session state. The direct connection is IPv6-only on the
   free plan and often unreachable from Windows or Render.
5. **Project Settings → API Keys:** the **secret key** (older projects: `service_role`). Never use
   the publishable/`anon` key in the backend.

## `.env`

```
DATABASE_URL=postgresql+psycopg://postgres.<ref>:<password>@<pooler-host>:5432/postgres
STORAGE_BACKEND=supabase
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<secret key>
SUPABASE_STORAGE_BUCKET=complaint-photos
ALLOW_HOSTED_DEMO_SEED=true     # only while this is a DEMO database
```

Hosts ending in `.supabase.com` / `.supabase.co` automatically get `sslmode=require`.
Keep the old local URL in a comment so you can switch back.

## Create the schema and seed it

```bash
export PYTHONPATH=services/api:services/worker
.venv/Scripts/alembic.exe upgrade head            # creates every table, enables RLS (0013)
.venv/Scripts/python.exe scripts/seed_demo.py     # pilot area, categories, demo identities
```

`seed_demo.py` normally refuses any database not named `*_demo`/`*_test` on a local host. A
Supabase database is always named `postgres`, so `ALLOW_HOSTED_DEMO_SEED=true` is the explicit
opt-in. It still only works when `APP_MODE` is `demo` or `test`. Remove it for a real production
database and seed real boundaries and categories instead.

## Security notes

- Migration `0013` enables row-level security on every table and revokes the `anon` and
  `authenticated` roles. The backend connects as the database owner, which bypasses RLS, so the
  app is unaffected, but the public REST API can read nothing. A test fails if a new table is
  added without RLS.
- The secret key can do anything to your project. Keep it in `.env` or your host's environment
  settings. It must never reach browser code, logs or Git (`.env` is ignored). If it leaks, reset it
  in Project Settings → API Keys.
- Photos live in the private bucket under server-generated UUID paths. The API serves them only to
  authorized users and verifies their SHA-256 on every read.

## Free-plan limits to plan for

- About 500 MB of database and 1 GB of photo storage.
- Projects idle for about a week are paused and must be restarted from the dashboard.
- Limited connections: the pool is small by default (`DB_POOL_SIZE=5`, `DB_MAX_OVERFLOW=5`).
  The API plus the worker together use up to about 20.

## Known gap

`scripts/maintenance.py` (orphan-photo cleanup) only understands the local photo folder. With
`STORAGE_BACKEND=supabase`, remove orphaned objects from the bucket in the dashboard until it is
extended.
