# NAGARSAATHI — Chaitanya UI

This is the latest `chaitanya's-UI` interface with the combined YOLO11n pothole/waterlogging model. It starts from commit `a07610eebfbc406fabcac09ec5734622c8e79046`.

The current application uses React/Leaflet, FastAPI, SQLite, local citizen/admin accounts and private photo storage. It does not use the earlier TypeScript/PostGIS demo, its background worker, or synthetic demo accounts. The older Supabase migration is retained only as historical source.

Duplicate grouping and report/reporter counts are documented in [DUPLICATE_GROUPING.md](DUPLICATE_GROUPING.md). Platform admins retain every individual submission; separately provisioned Nagar Nigam accounts see only forwarded consolidated issues. Priority scoring is deferred.

For step-by-step startup, account creation, report checking and expected outputs, read [RUN_AND_TEST_PROJECT.md](RUN_AND_TEST_PROJECT.md).

## Run the complete application

With Docker Desktop running, execute from this folder:

```text
docker compose up -d --build --wait
```

Open http://127.0.0.1:5180 and register an account. The container contains the frontend, API and model. Its named volume preserves the database and uploaded photos across ordinary stops and restarts. Stop it with `docker compose stop`.

## Public deployment

Read [DEPLOY_PUBLIC.md](DEPLOY_PUBLIC.md) for the prepared Render deployment, expected cost, persistent storage, admin setup and verification steps. Hosting has not been created or billed automatically.

The public image serves the frontend at `/` and the API at `/api`, so no visitor's browser contacts localhost. `render.yaml` proposes a 1 CPU/2 GB service and a 1 GB persistent disk. Without persistent storage, saved SQLite accounts/complaints/photos would be lost on a cloud restart.

## Model behavior

The configured checkpoint is `backend/models/nagarsaathi-combined-v3.pt` with classes `0=pothole` and `1=waterlogging`. Its hash and settings are in `backend/combined_model_metadata.json`. The original pothole-only `backend/best.pt` and metadata remain in Git for reference and are excluded from the deployment image.

AI findings assist review. Missing detections or model failures never reject a saved complaint. Confidence is not overall accuracy, severity, depth, or physical size. Public registration creates citizens; admins are provisioned separately using `python -m backend.accounts` in a secure shell.

## Development

Use Python 3.13, Node 22+, and a project-local virtual environment. Install `backend/requirements.txt` with CPU PyTorch support and run `npm ci`. Copy `.env.example` to `.env`. Start the backend with `uvicorn backend.main:app --host 127.0.0.1 --port 8002` and the frontend with `npm run dev` (port 5174).

Checks: `python -m unittest discover -s backend -p "test_*.py" -v`, `npm test`, and `npm run build`.

The layout and stylesheet remain Chaitanya's. Integration changes correct photo API URLs and report the actual detected class instead of labelling every result a pothole. Saish's separate interface is untouched.
