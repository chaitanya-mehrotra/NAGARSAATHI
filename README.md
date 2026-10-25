# NAGARSAATHI — Phase 2

React JavaScript, React Leaflet, Supabase and a FastAPI gateway. No invented records, metrics or predictions.

## Existing project
The provided Codex workspace contained no source. A separate Desktop NAGARSAATHI checkout was later found through local tooling and inspected (README, manifest, source inventory and PinMap). It uses TypeScript, MapLibre, PostGIS, synthetic identities and a broader staff workflow. No YOLO inference was found in the inspected frontend/API source. It is preserved in place. This deliverable is a separate implementation of the requested JavaScript/Supabase architecture, not an in-place migration. Do not import that project's synthetic fixtures into this dashboard.

## Setup
Requires Node 20.19+ / 22.12+ and Python 3.11+.

1. Create a Supabase project and run supabase/001_initial.sql once in its SQL editor.
2. Enable anonymous sign-ins in Supabase Authentication.
3. Copy .env.example to .env and set frontend project URL/public key and API URL.
4. Set backend SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY. Never prefix server secrets with VITE_ or commit them. Set ALLOWED_ORIGINS to exact comma-separated browser origins.
5. Install frontend dependencies with npm.cmd ci, then npm.cmd run dev.
6. Create a Python virtual environment, install backend/requirements.txt, and run uvicorn backend.main:app from this directory. Backend loads the local .env.
7. Host FastAPI separately for deployment; configure its HTTPS URL as VITE_API_BASE_URL and rebuild frontend.

For YOLO set YOLO_MODEL_PATH to your teammate's single YOLO11n weights file, optional MODEL_VERSION, and YOLO_CLASS_MAPPING as JSON mapping exact trained labels to pothole/waterlogging. Missing weights honestly disable inference; submissions still work. The API independently reruns requested analysis before storing trusted findings. It never trusts browser predictions. Failed inference does not block a complaint.

## Data and security
The API validates the bearer JWT with Supabase Auth, derives ownership server-side and returns an explicit shared field list without owner IDs or submission keys. My Reports is tied to the anonymous browser session; clearing it can lose access. No cross-device recovery is promised.

RLS is enabled. Browser complaint table grants are revoked, UPDATE policies are absent and the API has no status endpoint. The defensive insert policy enforces authenticated ownership, submitted status and no trusted AI fields. Server credentials stay in FastAPI.

The private complaint-photos bucket has no browser policies. Server validates actual JPEG/PNG/WebP bytes, limits reads and processed output to 10 MB, rejects decompression bombs above 24 megapixels, applies orientation and copies fresh RGB pixels before JPEG encoding. This strips EXIF/GPS/XMP. Stable paths are stored; only individually authorized 10-minute URLs are returned. Refresh to renew expired links.

Before submitting, users are told their photo, description and coordinates are shared with authenticated demo users. No fake timeline is shown.

A stable submission UUID and database uniqueness make racing retries idempotent. On failed save, the API checks whether insertion committed before deleting its upload. If database commit state is uncertain, the file is retained for reconciliation. Maintainers should compare bucket objects against complaints.photo_path, review unreferenced objects older than 24 hours, then remove only confirmed orphans. Cleanup failures must be monitored operationally.

Authorized maintainers update status in the secured Supabase SQL editor by full UUID:
UPDATE public.complaints SET status = 'under_review' WHERE id = '<full UUID>';
Allowed states: submitted, under_review, resolved. Trigger updates timestamps and signals clients. No admin interface is included.

## Realtime and map
The migration publishes complaint_events, containing only UUID and timestamp, to Supabase Realtime. Authenticated users can read signals but cannot write them. The secured trigger emits on saved complaint insert/update without disclosing owner IDs.

Frontend debounces invalidations, refetches records/aggregate counts/open details, cleans subscriptions, and refetches after SUBSCRIBED to recover missed events. Repeated signals cannot duplicate rows because data is fetched afresh. User filters, selection and viewport remain intact. Only SUBSCRIBED shows Live; failures show Reconnecting/Offline. There is no polling disguised as Live.

Map/list queries load 40 records per page and show the full matching total separately. Fit to results fits only that page. Both contributes to pothole and waterlogging counts. Bounded pages make clustering optional; it is not currently implemented. Date range uses inclusive submitted-from/through dates in UTC. Selected complaints use full UUID hash routes.

Tile URL and attribution are configurable. OSM standard tiles are the default, with visible linked attribution, normal browser caching and no prefetch/bulk/offline downloads. Preserve the browser referrer. Use a suitable commercial/provider plan for substantial traffic. Tile failure leaves list and numeric location entry usable. Geolocation runs only after a button click; it is never tracked continuously.

## Verification
Passed locally: Vite production build, four Node validation tests (file boundaries/types, malformed versus empty AI responses, bounding boxes, mismatch classification), Python compilation, HTTP 200 from frontend server.
Browser visual/interaction QA was blocked by a declined browser permission.

Not verified: running SQL migration, live Auth/RLS/storage integration, persistence after refresh, realtime reconnection, actual YOLO inference and mobile browser behavior. Supabase credentials and trained weights were not supplied. The hosted disconnected state is intentional.

After configuration, use a disposable test Supabase project to verify:
- Submit, refresh, confirm saved UUID, photo and coordinates; filters affect list and map.
- Two isolated browser sessions have distinct My Reports, while shared responses contain no owner IDs.
- Direct browser table writes/updates/deletes and bucket list/upload/read fail. Spoofed ownership and trusted predictions are rejected.
- Double submit/retry one submission_key creates one row. Simulate upload and database failure, review orphans.
- Deny location and manually pin or enter coordinates. Failed submit preserves form.
- Missing/failing model and zero detections never block submission. Check original-image bbox scaling and Both partial support.
- Two open clients show inserts/status changes in map/list/details/counts; reconnect recovers missed events and preserves viewport.
- Photo URLs expire and bucket remains private.
- At 360px and desktop, check overflow, keyboard controls, dialog focus, map/list switch and useful API/tile errors.

Run npm.cmd test, npm.cmd run build, python -m py_compile backend/main.py.
Add public-traffic abuse/rate limits and monitoring before unrestricted deployment.

Official references:
- https://supabase.com/docs/guides/auth/auth-anonymous
- https://supabase.com/docs/guides/database/postgres/row-level-security
- https://supabase.com/docs/guides/realtime/postgres-changes
- https://leafletjs.com/reference.html
- https://operations.osmfoundation.org/policies/tiles/


Backend unit checks also passed: actual-image rejection, EXIF removal, 10 MB enforcement, authentication on shared data routes, and partial/empty inference semantics. Run python -m unittest backend.test_main -v after installing backend dependencies.
