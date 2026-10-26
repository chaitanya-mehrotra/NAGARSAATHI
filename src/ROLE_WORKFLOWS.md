# Person 2: role workflows and integration handoff

## Scope and baseline

Frontend changes only, on `feature/role-workflows`, based on published Chaitanya
integration commit `9eb86e6` (`codex/combined-model-public-ui`). This PC has no D: drive;
`D:/nagarsaathi-model/integrations/NAGARSAATHI-chaitanya-ui` and its newer local
grouping changes were not available. The checkout used here is
`C:/Users/lenovo/OneDrive/Desktop/NAGARSAATHI`.

Read the supplied TEAM_TASKS_AND_PROMPTS.md from Downloads. Its latest requirements
restore automatic priority; the earlier deferral is superseded. The source document
is not copied into the repository because it is team-wide, rather than frontend-owned.
No changes to backend/, backend tests/runtime, dependencies/build configuration,
model weights, or Saish's separate interface. The existing CSS, palette, typography,
sidebar, cards, form steps and map picker are reused. The former monolithic main.jsx
is split into citizen, staff, request/session and reusable UI modules.

**Integration status:** the document calls its interfaces proposed. There is no
backend-owner sample contract or updated common baseline in this checkout. This PR
implements those proposed routes with the explicit additions below, using test-only
fixtures. This is NOT a claim of contract agreement or live automation completion.
Person 1 must confirm these shapes/routes and merge the newer backend baseline before
joint acceptance. Do not merge this frontend onto the old inline-inference API and
call it a complete automated system.

## Screens

- Citizen: category/description, photo/location, review, direct submission and tracking
  number. No Check Photo, model evidence, confidence, boxes, grouping or priority UI.
  Own-report list and private report detail show verification separately from repair.
- Platform admin: paginated inbox of every individual submission, job states, shared
  issue links, service-supplied counts/grouping and automatic priority explanations.
  Exceptions is a server-filtered inbox; exception evidence review is optional.
  Processing health is fetched separately so an unavailable health route does not
  block the report list. Shared issues are accessible to admin as well.
- Nagar Nigam: API-published consolidated issues only, with service ordering, counts,
  evidence/location and repair updates. No report inbox requests, reporter identity
  rendering or grouping/verification controls.
- Sign-in obtains the role through /auth/me. Staff cannot self-select a role at
  registration. Existing localStorage user profiles are ignored. Account switches,
  logout, 401 and cross-tab storage changes unmount all old records and forms.
  Outstanding requests are aborted/ignored. Authenticated photo blobs are revoked;
  bearer tokens never appear in photo URLs.

Lists and details poll every 15 seconds, without overlapping requests. Visibility
changes refresh the active view. Loading/errors and explicit retries are provided.
The UI does not label polling as a live connection. Lists are cleared on request
failure rather than silently presenting old data as current. Report form data remains
on submission failure; unchanged retries reuse the same Idempotency-Key in that form.
Navigating away clears the unsaved form; drafts and photo files are not stored on disk.

## API contract dependencies for Person 1

API base: VITE_API_BASE_URL (trailing slash removed), default development
http://127.0.0.1:8002, default production /api. Existing local .env overrides defaults;
set the base explicitly for your environment. It must be reachable by the user's phone
in deployed use. Do not use a phone's 127.0.0.1 for a hosted backend.
All private JSON and photo requests use Authorization: Bearer <session>.

Lists must return `{ "items": [...], "total": 100 }`; totals count the full filtered
collection, not just the page. IDs may be numeric or UUID strings. Fields omitted by
an unfinished API show as pending/not supplied, never fabricated counts or priority.
No browser inference, worker API, /dev/detect or /metrics request exists in the new UI.

| Request | Response / required behavior |
| --- | --- |
| POST /auth/register | JSON name/email/password; server creates citizen only |
| POST /auth/login | JSON email/password; access_token in response |
| GET /auth/me | id, name, email, role: citizen/admin/nigam; verified server-side |
| POST /auth/logout | Revoke session; 204 supported; browser clears immediately even offline |
| POST /reports | Multipart image, description, latitude, longitude, issue_type; Idempotency-Key header; save immediately and return id, reference (optional), verification_status, status |
| GET /complaints?mine=true&limit=20&offset=0 | Citizen own-report page; server must enforce ownership even if mine is removed |
| GET /reports/{id} | Citizen own tracking record; admin individual record; role-filtered server response |
| GET /reports/{id}/photo | Authorized JPEG/PNG/WebP bytes; no token query string needed |
| GET /complaints?limit=20&offset=0 | Admin inbox with processing metadata; never Nigam |
| GET /complaints?limit=20&offset=0&needs_attention=true | Server-filtered admin exceptions page (query extension to confirm) |
| GET /issues?limit=20&offset=0&queue=active&sort=priority | Admin: shared issues; Nigam: eligible published issues only. Active excludes resolved/rejected. Backend supplies deterministic priority order |
| GET /issues?...&queue=resolved&sort=priority | Resolved consolidated issues, still role-filtered |
| GET /issues/{id} | Role-filtered issue, counts, priority, representative description/location |
| GET /issues/{id}/photo | Authorized representative image bytes |
| PATCH /issues/{id}/status | JSON status and note; authorize staff, audit decision and propagate to all linked citizen reports |
| GET /processing/health | **Provisional route**: admin only; queued_count, failed_count, worker_status, last_heartbeat_at, optional message. Confirm with Person 1 |
| PATCH /reports/{id}/review | **Provisional route**: admin exception review only; JSON verification_status and reason. Audit and re-evaluate publication; not a direct priority or manual-order setter |

Exceptions can be reviewed but this PR does not invent an automatic grouping algorithm
or a regrouping API. Person 1 should expose audited group correction if needed; do not
reuse the old manual priority/review request shape for it.

### Citizen report example

```json
{
  "id": 21,
  "reference": "NS-21",
  "issue_type": "pothole",
  "description": "Pothole beside the bus stop",
  "latitude": 12.9716,
  "longitude": 77.5946,
  "verification_status": "needs_review",
  "verification_message": "Your report needs a closer look. No new upload is required.",
  "status": "in_progress",
  "status_note": "Repair crew scheduled"
}
```

Verification: pending/supported/needs_review/not_supported. Missing values remain
pending; the client never derives verification from detections. Safe messages must
come from the API. not_supported is not a fraud verdict and needs a follow-up policy
from Person 1; the UI explains that it remains available for review.
Repair: open/in_progress/resolved/rejected. Rejection requires audited explanation.

Admin report extends the record with processing_status (queued/processing/completed/
failed), needs_attention, exception_reason, grouping_reason, issue_id and optional
`issue` containing the authoritative issue summary. See src/workflow.fixtures.js.

Issue fields: id, issue_type, description, latitude, longitude, status, report_count,
reporter_count, unique_photo_count, priority_score, priority_reason,
priority_policy_version, optional admin-only grouping_reason. The frontend preserves
API order and values. It does not deduplicate, increment counts or compute ranking.

### Backend privacy/integration gaps in the published baseline

The older checked-out API still performs inline inference, uses two account roles,
and exposes technical fields in report serialization. It lacks the target issue,
health, exception and repair APIs. Person 1 must implement server role access checks,
strip AI/internal fields from citizen responses, restrict Nigam to published issues,
and omit reporter identities from Nigam payloads. Frontend allow-listed rendering and
hidden navigation are not security enforcement. UI fixture tests do not prove backend
privacy, authorization, queue durability or repair propagation.

Use the same maximum upload contract as the inspected baseline: JPEG/PNG/WebP,
10 MiB, with content/decompression limits enforced server-side. Current form uses
10-500 description characters. Configure exact CORS origins; allow Authorization,
Content-Type and Idempotency-Key headers, and GET/POST/PATCH/OPTIONS as appropriate.
Return safe JSON errors using `detail` or `error.message`. Expected authorization
failures: 401 session expired, 403 forbidden, 404 inaccessible record. Do not rely on
an ID or role coming from the client as authorization evidence.

## Running and testing

No new package.json/package-lock.json/vite.config.js changes were needed. Install
existing dependencies with npm ci (or npm install if a running Windows process locks
an unrelated pre-existing native binary). Do not kill someone else's server to fix a lock.

```powershell
# In the Chaitanya checkout, with Person 1's API running:
$env:VITE_API_BASE_URL = 'http://127.0.0.1:8002'
npm.cmd run dev -- --port 5176 --strictPort
npm.cmd test
npm.cmd run build
```

Browser tests intercept the contract at the network boundary; mocks are never enabled
by production application code. They use real React rendering, navigation, photo
upload, FormData requests, auth headers and repair updates. Fixtures intentionally
represent 100 individual reports and 20 actual shared issues (5 reports, 4 distinct
accounts, 3 photos per issue). This is not a measured grouping-accuracy claim.

Install browser tooling outside the repo to avoid changing shared dependencies:

```powershell
npm.cmd install --prefix "$env:TEMP\nagarsaathi-browser-tests" --no-package-lock playwright
$env:PLAYWRIGHT_MODULE = "$env:TEMP\nagarsaathi-browser-tests\node_modules\playwright\index.mjs"
# Start Vite on 5176 in another terminal first. Tests use installed Microsoft Edge.
node --test src/workflows.browser.test.mjs
```

UI_TEST_URL overrides the test URL. Optional UI_SCREENSHOT_DIR writes the mobile
citizen screenshot outside the repo. A current Playwright release and Microsoft Edge
are required. The ordinary npm test entry remains the existing validation.test.js,
which imports the workflow unit tests; browser checks are a separate command.

Browser acceptance coverage: mobile submission with tiles unavailable, failed save
and same-key retry, no analysis call, saved tracking, 15-second polling, pending/review/
repair states, admin pagination and health/offline message, shared issue links and
exceptions, Nigam issue-only view/server order/repeated-account counts, repair PATCH,
list failure/retry, cross-tab role switch during a slow request, logout, registration,
server-verified role and session expiry. Mobile/desktop no horizontal overflow checked.

Before joint acceptance, run against Person 1's real API with worker stopped/started,
real staff accounts, server-filtered photos/records, duplicate deliveries and actual
repair propagation. The frontend fixtures are not a replacement for these checks.
