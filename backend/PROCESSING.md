# Backend and admin-PC processing

Backend and frontend role workflows are now integrated. Collection adds selected moderation and repair-work features from main; see [COLLECTION_27_10.md](../COLLECTION_27_10.md) for current startup instructions and the feature comparison. The original shared contract was approved on 26 October 2026.

## What runs where

```text
Phone -> HTTPS API -> photo + report + durable SQLite job -> immediate tracking response
Admin PC worker -> outbound claim -> private input -> YOLO + image matching -> result
API -> verification -> grouping/counts -> demand/age priority -> eligible Nigam issue
Nigam repair update -> shared issue -> every linked citizen's tracking status
```

The API does not import YOLO, Torch, OpenCV or NumPy. It checks upload safety with Pillow, saves normalized pixels and inserts the report/job in one database transaction. Readiness requires the database, not a running model. Uploaded photos are flushed before committing the record. A crash between saving a photo and committing the row can leave an unreferenced private file; do not delete files merely because their pictures look similar.

The separate worker loads the existing combined checkpoint once on the PC. There is no retraining and no inference in the phone. The public API continues accepting while the worker is stopped. SQLite/jobs/photos need persistent server storage; this is a single-instance initial implementation, not a multi-replica database design.

## Existing development environment — Windows CMD

From `D:\nagarsaathi-model\integrations\NAGARSAATHI-chaitanya-ui`:

```cmd
git switch Collection-27-10
.venv\Scripts\python.exe -m backend.configure_worker
```

This preserves other `.env` settings, stores only a fingerprint in `.env`, and writes the raw secret to ignored `.local/worker.env`. Do not share/commit that file. On Windows, protect the folder with your account's filesystem permissions; POSIX chmod is not a replacement for Windows ACLs. `--rotate` explicitly replaces a credential and requires restarting the API; an already running worker must also restart.

Terminal A — intake API, no model warmup:

```cmd
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8002
```

Terminal B — admin-PC worker:

```cmd
.venv\Scripts\python.exe -m backend.pc_worker
```

Terminal C — frontend stays the separately owned Chaitanya UI:

```cmd
npm run dev -- --port 5174 --strictPort
```

If a server already owns the port, stop that instance before restarting it. The integrated citizen workflow submits without preview; the server also denies preview access and filters model evidence.

For one queued job rather than continuous polling:

```cmd
.venv\Scripts\python.exe -m backend.pc_worker --once
```

The worker polls idle queues every five seconds, reconnects after transport errors, renews active leases in a background thread and shuts down on Ctrl+C. An interrupted job becomes claimable after its 180-second lease expires. Keep the PC awake for continuous processing. To launch at Windows sign-in, create a Task Scheduler task using the full `.venv\Scripts\python.exe` path, arguments `-m backend.pc_worker`, and this project folder as "Start in"; store configuration on the PC, not in the scheduler command line. Test the task under the same Windows account that owns the project.

## Fresh environments

API/server dependencies:

```cmd
python -m venv .venv-api
.venv-api\Scripts\python.exe -m pip install -r backend\requirements-api.txt
```

Worker/developer dependencies (CPU example; the existing CUDA training environment is unrelated):

```cmd
python -m venv .venv-worker
.venv-worker\Scripts\python.exe -m pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cpu
.venv-worker\Scripts\python.exe -m pip install -r backend\requirements-worker.txt
```

Use Python 3.13 for the tested runtime. `backend/requirements.txt` remains a compatibility entry point for the combined developer environment. Do not install worker dependencies in the cloud API just to make readiness pass.

## Public server and outbound PC worker

No public hosting or paid resources are provisioned by this branch. On an agreed HTTPS host:

1. Deploy the intake API with persistent database/photos and the generated `NAGARSAATHI_WORKER_TOKEN_SHA256` fingerprint in server-side configuration.
2. Set the PC's `.local/worker.env` API URL to the actual HTTPS API base, including `/api` if using the bundled image. Keep its raw key local.
3. Run the worker on the PC. No incoming PC port, router forwarding or direct public database connection is needed.
4. Use real account login for citizens/admin/Nigam; never send the worker key to the frontend.

The CLI rejects plain HTTP outside localhost. Redirects are disabled so credentials do not follow arbitrary destinations. Job/candidate downloads are bound to the active lease and to server-issued relative paths.

## Docker intake plus host PC worker

Configure the worker for the bundled API URL, then rebuild the intake image:

```cmd
.venv\Scripts\python.exe -m backend.configure_worker --api-url http://127.0.0.1:5180/api
docker compose up -d --build --wait
.venv\Scripts\python.exe -m backend.pc_worker
```

If a local worker configuration already exists, edit its API URL intentionally instead of regenerating the secret, or rotate explicitly with `--rotate`. Docker Compose reads the fingerprint from root `.env` and passes only that fingerprint to the container. Its API image installs `requirements-api.txt`, not Torch/Ultralytics. `/api/ready` stays healthy with worker off. Persistent data is the existing named volume; never use `down -v` to restart when you want to keep complaints.

## Queue correctness

- Intake idempotency key is scoped to the account and content. The same retry returns the existing report/job.
- Job claiming uses a write transaction, a random lease token stored hashed, and an attempt counter.
- Input/candidate endpoints require both worker credential and current job lease.
- Result checks model SHA, source image SHA, image dimensions, finite scores, valid boxes and the candidate allowlist. Accepted analysis records versioned verification/grouping evidence.
- Same lease/result delivery is idempotent; stale leases and changed result bodies return 409. New retries get new job identities.
- Expired leases recover on the next worker claim. Three failed/expired attempts enter the admin exception queue. Failure backoff is 10 then 20 seconds; admin can explicitly retry failed jobs.
- Late processing cannot overwrite an audited admin correction or a newer issue repair update.
- Health exposes failed jobs and expired leases without exposing credentials. Unexpected worker errors are logged by type, not arbitrary exception text that could contain private paths or tokens.

## Verification and grouping policy

`visual-evidence-v1` uses a provisional 0.55 score threshold to find evidence matching the submitted category. Both requires evidence for both classes. Missing/weak/mismatching detections require review. This threshold is not independently calibrated, and support does not prove date, location, authenticity, flood depth or pothole severity. No automatic fraud/rejection decision is made.

`grouping-v1` considers unresolved compatible reports within 30 days and 30 metres of the report and issue anchor. Exact normalized pixel copies can group automatically. A copied image at a different location is an exception. Multiple possible groups or nearby reports without strong visual agreement remain unmerged in review; the system never forces 100 reports into 20 groups.

`orb-defect-v1` is implemented on the PC using ORB features, ratio-filtered descriptor matches and RANSAC homography, restricted to one detected defect crop rather than matching the entire road background. It needs at least 20 inliers, 0.8 inlier ratio and 0.25 spatial coverage. Multiple-defect/low-texture photos do not auto-match geometrically. See [OpenCV's feature/homography documentation](https://docs.opencv.org/4.x/d7/dff/tutorial_feature_homography.html).

Geometric auto-merging defaults **off** (`NAGARSAATHI_VISUAL_AUTO_MERGE=0`). Controlled testing measures transformations of known sources, not real-road same-issue identity. Enable it only after evaluating a representative labelled road set; the flag is on the API, not chosen by workers or citizens. Exact-copy grouping and automatic handling of unambiguous new supported issues remain enabled by default. This is an honest limitation of arbitrary-angle automation, not a claim that the current YOLO identifies individual potholes across photos.

Evaluation:

```cmd
.venv\Scripts\python.exe -m backend.evaluate_matching --output backend\evaluation\controlled_visual_matching.json
.venv\Scripts\python.exe -m backend.evaluate_matching --manifest your-labelled-pairs.json --output road-matching-results.json
```

A manifest is a JSON list of `first`, `second` relative photo paths, `first_detections`, `second_detections`, and boolean `same_issue`. Each detection uses `label`, `confidence`, `bbox_xyxy`. Keep field evaluation data private and out of Git unless sharing is authorized. Do not tune and report final performance on the same pairs.

## Counts, automatic priority and publication

Every report remains stored. Counts are queried from membership, not increment-only counters. Distinct accounts are not guaranteed distinct humans. Shared photo file deletion/deduplication is not performed.

`demand-age-v1`: `70 * min(supported distinct accounts / 10, 1) + 30 * min(waiting days / 7, 1)`. Inputs, policy version and a textual breakdown are returned. Repeat submissions by one account do not add reporter points. Waiting time is based on the oldest linked report. Closed issues score zero and leave the default active queue. Scores update after regrouping/review/status changes and on list/detail reads; the PC need not stay online for waiting-time scores to change.

This is reporting-demand priority, not danger or road-impact prediction. Caps/weights are provisional policy. Account farming can still influence counts; email/human verification and institutional impact data are future improvements. No model confidence, invented hospital proximity or physical-depth estimate contributes to priority.

Confidently supported, unambiguous issues publish automatically. Uncertain evidence/matching stays visible to admin only. Explicit admin withholding is retained across subsequent worker results. Historic forwarded issues are preserved as legacy/manual decisions, not silently reclassified by a database migration.

## Preservation, testing and limitations

Existing database migration is additive and creates a SQLite backup before the first verification/queue schema migration. Accounts, photos, reports, existing issue links and history remain. Historical reports become review cases rather than being automatically replayed into the new queue or republished. Admin can retry them intentionally.

Before migration/upgrade, stop the API/worker and back up the whole data directory (database and photos together) or the Docker named volume. Restore both from the same backup if rolling back. SQLite backup alone does not copy photo files. The automatic backup is not a replacement for an operational backup/restore plan.

```cmd
.venv\Scripts\python.exe -m unittest discover -s backend -p "test_*.py" -v
```

Tests preserve the original account/session/photo regressions and add offline/restart persistence, no-ML API startup, safe retries, lease expiry, stale/repeated results, manual correction races, role isolation, model/photo binding, automatic grouping/publication, distinct counts, demand ranking and repair propagation. The 100-report/20-issue fixture uses known generated groups and stubbed detections; it is a workflow test, not measured model accuracy. Real-model smoke checks are reported separately in the PR.

Remaining limitations: no field-labelled arbitrary-view matching validation, single-instance SQLite/filesystem storage, no multi-ward Nigam scoping, no production hosting provisioned, no claim of fraud detection, and frontend integration still belongs to Person 2. This branch does not change `src/`, Saish's UI or the checkpoint.
