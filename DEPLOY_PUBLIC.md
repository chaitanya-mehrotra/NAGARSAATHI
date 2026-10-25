# Run the correct Chaitanya UI independently

This version starts from `chaitanya's-UI` commit
`a07610eebfbc406fabcac09ec5734622c8e79046`. The earlier integration used the
older commit `07c3d40` and is preserved in a separate folder. Do not mix their
databases or startup commands.

The current frontend is Chaitanya's React/Leaflet interface. Its layout and CSS
are preserved. Integration edits correct the photo API URL and show the actual
pothole/waterlogging labels. Saish's separate UI is not edited.
Hard-coded demo login attempts and quick-test credentials were removed; visitors
register and sign in using their own accounts.

## What runs together

The Docker image contains the built frontend, FastAPI, your combined YOLO11n v3
checkpoint and a CPU inference runtime. It serves the UI at `/` and the API at
`/api`. SQLite accounts, sessions, complaints and uploaded photos live under
`NAGARSAATHI_DATA_DIR` (default `/var/data` in Docker). This newer branch does not
use the old PostGIS database or background worker.

Weights are included at `backend/models/nagarsaathi-combined-v3.pt`.
SHA-256: `748e47702e7fa7068ab64a9005cbefb02873e0190eff67496dbd2ef2a8f6a676`.
Class 0 is pothole and class 1 is waterlogging. CPU serving does not need a GPU.
Missing detections and inference failures do not reject complaint submission.

## Run on a PC with one command

Open Docker Desktop, change into this folder, then run:

```bat
docker compose up -d --build --wait
```

Open `http://127.0.0.1:5180`. Register a new account using the app. Accounts from
the earlier project's synthetic demo are not imported. The named Docker volume
preserves this app's data across ordinary stops/restarts. Keep that volume when
updating the image. Use `docker compose stop` to stop the local app.

For development, the prepared Windows checkout also has its own `.venv` and
frontend dependencies. The current preview uses backend port 8002 and frontend
port 5174, separately from the older app's 8000/5173.

## Put it online on Render

The prepared `render.yaml` describes one Docker service in Singapore with one
CPU, 2 GB RAM, and a 1 GB persistent disk mounted at `/var/data`. The disk is
required: without it, SQLite and uploaded photos disappear on restart/redeploy.
There is no separate frontend service or localhost API dependency in the public
Docker build.

Current reference price: compute is approximately US$25/month and the 1 GB disk
US$0.25/month, before taxes and extra usage. Confirm the actual price displayed
by Render before creating resources:

- https://render.com/pricing
- https://render.com/docs/disks

Steps after approving the cost:

1. Push this prepared branch to GitHub (it must include the Dockerfile and model).
2. In Render, create a Blueprint from this repository and select the prepared
   branch, `codex/combined-model-public-ui`.
3. Review the service and disk from `render.yaml`, then create/deploy them in the
   intended workspace. If using New Web Service instead, choose Docker, the same
   branch, 1 CPU/2 GB and explicitly add a 1 GB disk at `/var/data` before accepting
   real complaints. The connector's basic service-creation tool cannot attach a disk.
4. Confirm `/api/ready` succeeds and the deployment is Live.
5. Open the HTTPS `onrender.com` URL, register a citizen account, upload a pothole
   and a waterlogging photo, and confirm actual model labels/confidences.
6. Restart the service and verify that the account and saved complaints still exist.

An online host keeps the app available when your laptop is off. A localhost link
or a tunnel to your laptop does not provide that independence.

## Administrator account

Public registration always creates citizens. To create an administrator, run this
inside the deployed service's secure shell and enter your own strong password at
the prompt:

```text
python -m backend.accounts your-email@example.com --name "Administrator"
```

Do not use public demo credentials or commit passwords, tokens, databases, or
uploaded photos to GitHub. The Docker build excludes local `.env` files and data.
For a growing service, keep regular SQLite/photo backups and plan a migration to
a managed database/object store before adding multiple app instances.

## Verification

Run the current backend and frontend checks with:

```bat
.venv\Scripts\python.exe -m unittest discover -s backend -p "test_*.py" -v
npm.cmd test
npm.cmd run build
```

The historical Supabase SQL file and older pothole-only weights remain in Git for
reference. They are not used by the configured combined-model Docker service.

Verified locally: all five backend tests, four frontend tests, frontend build,
and a real single-origin Docker HTTP check on 1 CPU/2 GB. That check registered a
disposable citizen, rejected a supplied admin role, saved pothole and waterlogging
complaints with real model inference, retrieved private photos and rejected malformed
images. Test records were kept in a disposable container, not the app's database.
