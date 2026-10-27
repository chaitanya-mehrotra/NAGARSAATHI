# NAGARSAATHI — Collection (27/10)

Branch **`Collection-27-10`** combines selected main-branch features with Chaitanya's working UI, combined YOLO11n model and separate admin-PC worker. Read **[COLLECTION_27_10.md](COLLECTION_27_10.md)** for the current feature comparison, startup instructions, new APIs, validation and limitations. Both original branches are preserved.

The current application uses React/Leaflet, FastAPI, SQLite, local citizen/admin accounts and private photo storage. It does not use the earlier TypeScript/PostGIS demo, its background worker, or synthetic demo accounts. The older Supabase migration is retained only as historical source.

The API immediately stores submissions and queues work for the admin PC. Supported consolidated issues publish automatically, with explainable demand/age priority. Admins retain every individual report; Nagar Nigam sees only published consolidated issues. Collection adds audited archive/restore, repair-team assignments, private repair photos, independent repair approval, staff activity history and optional verified Google citizen sign-in. Duplicate reports remain linked and counted.

For step-by-step startup, account creation, report checking and expected outputs, read [COLLECTION_27_10.md](COLLECTION_27_10.md). Earlier plans and guides describe historical prototypes.

## Run the UI and intake API in Docker

With Docker Desktop running, execute from this folder:

```text
docker compose up -d --build --wait
```

Open http://127.0.0.1:5180 and register an account. The container serves the frontend/API and stores data in a persistent volume. **Inference still runs in the separate PC worker**, configured for `http://127.0.0.1:5180/api` and the matching worker credential. Stop the container with `docker compose stop`. Docker's database and the development database are separate; see the Collection guide before switching modes.

## Public deployment

Read [DEPLOY_PUBLIC.md](DEPLOY_PUBLIC.md) for the prepared Render deployment, expected cost, persistent storage, admin setup and verification steps. Hosting has not been created or billed automatically.

The public image serves the frontend at `/` and the API at `/api`, so no visitor's browser contacts localhost. `render.yaml` proposes a 1 CPU/2 GB service and a 1 GB persistent disk. Without persistent storage, saved SQLite accounts/complaints/photos would be lost on a cloud restart.

## Model behavior

The configured checkpoint is `backend/models/nagarsaathi-combined-v3.pt` with classes `0=pothole` and `1=waterlogging`. Its hash and settings are in `backend/combined_model_metadata.json`. Chaitanya's compatible `backend/best.pt` copy and `backend/model_metadata.json` are also preserved in Git, while the Docker image uses the explicitly configured combined checkpoint.

AI findings assist review. Missing detections or model failures never reject a saved complaint. Confidence is not overall accuracy, severity, depth, or physical size. Public registration creates citizens; admins are provisioned separately using `python -m backend.accounts` in a secure shell.

## Development

Use Python 3.13, Node 22+, and a project-local virtual environment. Install `backend/requirements.txt` with CPU PyTorch support and run `npm ci`. For a fresh clone copy `.env.example` to `.env` and run `python -m backend.configure_worker` once; reuse existing configuration on an existing installation. Start the API with `uvicorn backend.main:app --host 127.0.0.1 --port 8002`, the worker with `python -m backend.pc_worker`, and the frontend with `npm run dev -- --port 5174 --strictPort`, in three separate terminals.

Checks: `python -m unittest discover -s backend -p "test_*.py" -v`, `npm test`, and `npm run build`.

The layout and stylesheet remain Chaitanya's. Integration changes correct photo API URLs and report the actual detected class instead of labelling every result a pothole. Saish's separate interface is untouched.
