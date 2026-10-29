# Free deployment: UI on Vercel, API + YOLO worker on your PC, Supabase for data

```
Browser -> Vercel (UI) -> HTTPS tunnel -> API on your PC -> Supabase (DB + photos) <- YOLO worker on your PC
```

## 1. Supabase
Follow `docs/SUPABASE.md` (PostGIS, private `complaint-photos` bucket, session pooler on port 5432).

## 2. `.env` on your PC (never commit)
```
APP_MODE=demo
DATABASE_URL=postgresql+psycopg://postgres.<ref>:<password>@<pooler-host>:5432/postgres
STORAGE_BACKEND=supabase
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<secret key>
SUPABASE_STORAGE_BUCKET=complaint-photos
ALLOW_HOSTED_DEMO_SEED=true
VALIDATION_PROVIDER=yolo
JWT_SECRET=<long random string>
CORS_ORIGINS=https://<your-app>.vercel.app
GOOGLE_CLIENT_ID=
```

## 3. One-time database setup
```
python -m venv .venv
.venv\Scripts\pip install -e .[ml]
$env:PYTHONPATH="services/api;services/worker"
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\python.exe scripts/seed_demo.py
```

## 4. Run API + worker
Double-click `start.bat` (runs migrations, seeds, starts API + worker, and a Cloudflare tunnel if `cloudflared` is installed).

## 5. Expose the API
Use a tunnel with a stable URL (ngrok static domain or a Cloudflare named tunnel) pointing at `http://127.0.0.1:8000`.

## 6. Vercel
Import the repo (root directory = repo root; `vercel.json` sets the build). Set the environment variable
`VITE_API_BASE_URL=https://<your-tunnel-host>` (no trailing slash), plus `VITE_GOOGLE_CLIENT_ID` if used.
Redeploy after changing it. Then put the Vercel URL in `CORS_ORIGINS` and restart the API.

The app is in demo mode, so the one-click demo logins are public while the tunnel is up.

## Auto-connect (no redeploy when the tunnel URL changes)
`start.bat` runs `scripts/launch.py` in ONE window: migrations, seed, API, YOLO worker and a Cloudflare
tunnel. It then publishes the tunnel URL to a public Supabase file (`public-config/api-url.json`).
The Vercel build is made once with `VITE_CONFIG_URL=<SUPABASE_URL>/storage/v1/object/public/public-config/api-url.json`
and reads that file on every page load. If the laptop is off, the site shows an "offline" banner.
Logs: `logs/api.log`, `logs/worker.log`, `logs/tunnel.log`. Press Ctrl+C in the window to stop everything.
