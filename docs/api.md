# API and provider contracts through checkpoint 6

OpenAPI is committed in `packages/contracts/openapi.json`; generated TypeScript is
in `packages/contracts/src/api.d.ts`. Runtime API docs are served at `/docs`.

Citizen screens now provide upload, pin confirmation, review, receipt and tracking.
`GET /api/v1/config/boundaries` supplies the local synthetic outlines for MapLibre;
no external street tiles or geocoder is required.

## Validation and staff review

`GET /api/v1/reviews` returns up to 50 oldest pending reports in the actor's review
scope. `POST /api/v1/reviews/{report_id}/decision` requires reviewer/admin grants,
an `expected_revision`, UUID `request_id`, decision (`accepted`, `needs_review`,
`rejected`), reason, accepted category and optional confirmed location. Repeated
identical decisions are idempotent; stale revisions or altered retries return 409.
Moving a report outside the reviewer's scope returns 403. Unassigned locations are
visible only to a globally scoped reviewer/admin. Decisions preserve claimed values
and write human validation records with null confidence and immutable audit events.

Submission enqueues a revision-aware validation job transactionally. The worker uses
short claims, skip-locked rows, 30-second leases and three bounded retries. It releases
database locks before calling adapters. Results must match report, current revision,
media UUID/hash and request UUID; stale results cannot approve replaced evidence.
The default fixture catalog is empty: arbitrary photos require human review. Fixtures
are disabled outside demo/test and cannot accept non-synthetic reports. Known labels
map only under a declared provider version; unknown/multiple/conflicting labels go
to review. Provider failures retry and then remain visible as processing failures.

Responses include `validation_status`, `review_reason`, raw submitted `location` and
the current `canonical_location`. Visual acceptance with a missing/uncertain location
does not admit a report. Located acceptance enqueues `admit_report`, whose handler
arrives in checkpoint 5. No external callback endpoint exists; only the internal
worker and authenticated staff decision path write authoritative results.

Errors use `code`, `message`, `field_errors`, and `request_id`; responses include
`X-Request-ID`. Authenticated responses use `Cache-Control: private, no-store`.

## Identity and permissions

Send `Authorization: Bearer <token>`. In demo mode only, the fixture subjects
`demo-citizen`, `demo-citizen-2`, `demo-reviewer`, `demo-operator`, `demo-admin` are
public demo tokens. They must be provisioned by the demo seed. `GET /api/v1/me`
returns the active database identity and role grants. A token cannot supply roles.
There is no role-editing endpoint.

Citizens may upload, submit and retrieve their own evidence/reports. Reviewers may
read reports and attached evidence only in their assigned areas; the demo reviewer
is scoped to Southwest. Administrators have the seeded global read grant. Operators
do not receive private report access at this checkpoint. Missing/inaccessible objects
return 404; actions requiring a missing role return 403. Missing/invalid credentials
return 401. A scoped reviewer cannot read uploads before they are attached to a
report, or reports without a confirmed owning area.

The OIDC adapter verifies signatures using the configured HTTPS JWKS endpoint,
RS256/ES256 algorithm allowlist, issuer, audience, expiry and issue time. It requires
a subject mapped to an active provisioned database user. Tests use locally signed
tokens; no hosted identity service is connected. See the
[PyJWT verification documentation](https://pyjwt.readthedocs.io/en/stable/usage.html).

## Upload and report flow

1. `POST /api/v1/uploads`: send raw JPEG or PNG bytes with matching `Content-Type`.
   No multipart form or remote image URL. Returns 201 with upload UUID, hash,
   dimensions, byte size, `uploaded` state and expiry.
2. `POST /api/v1/uploads/{id}/complete`: verifies owner, expiry, hashes and decoding;
   marks the upload `ready`. Repeating completion is safe.
3. `POST /api/v1/reports`: send metadata and completed media UUIDs, with an
   `Idempotency-Key` header (1–128 printable ASCII characters without spaces).
   Returns 201 with durable UUID/tracking reference, media URLs and ingestion state.
4. `GET /api/v1/reports/mine?limit=20&cursor=<uuid>`: own reports, newest first,
   up to 50 per page. `next_cursor` is null on the last page. Cursors are owner-scoped.
5. `GET /api/v1/reports/{id}`: retrieve own or authorised scoped-staff report.
6. `GET /api/v1/media/{id}/content`: authenticated display JPEG, correctly oriented
   and without EXIF. Originals remain private and are not exposed by this route.

Defaults: 1–3 photos, 10 MiB each, 25 MiB total, 25 million decoded pixels, one-hour
unattached upload expiry. Limits may be lowered in configuration. Animated files,
unsupported or mismatched types and invalid images are rejected. The implementation
fully decodes images and checks size before creating a clean derivative; see
[Pillow image decoding documentation](https://pillow.readthedocs.io/en/stable/reference/Image.html).

Report metadata includes `description` (5–2000 characters), an active
`claimed_category`, `media_ids`, optional address/language hint, `location_source`
and `location` containing longitude, latitude, confirmation and optional uncertainty.
Unknown fields, duplicate media IDs, client approval/status/category/priority/role
fields are rejected. Address text does not determine area ownership.

Located submissions remain `submitted` with a null canonical category, pending
validation. Missing/unconfirmed/uncertain pins become `awaiting_review`;
outside confirmed points become `out_of_scope`. These reports remain durable and
visible to the owner. Original submitted coordinates are preserved independently
from any future reviewer-approved position. EXIF GPS extraction is not implemented
at this checkpoint; original metadata is retained privately.

Same principal/key and same normalized payload returns the same report UUID; an
altered payload returns 409. Keys are scoped per principal/operation. Concurrent
retries are serialized transactionally, and media row locks prevent attachment to
two reports. A failed submission rolls back report, attachment, location decision
and idempotency writes, leaving the completed upload retryable. An expired upload
returns 410; configured byte/pixel limits return 413. Storage failure/corruption
blocks completion/submission. Clients never create admitted reports; database
constraints additionally require compatible links and completed owned evidence.

### Local PowerShell example

Start the API after migrations and seed, then use a downloaded local photo:

```powershell
$demoHeaders = @{ Authorization = 'Bearer demo-citizen' }
$upload = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/v1/uploads' `
  -Headers $demoHeaders -ContentType 'image/png' -InFile 'C:\path\to\photo.png'
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/uploads/$($upload.id)/complete" -Headers $demoHeaders
$submission = @{
  description = 'Demo pothole near a fictional landmark'
  claimed_category = 'pothole'
  media_ids = @($upload.id)
  location_source = 'confirmed_pin'
  location = @{ longitude = 77.615; latitude = 12.915; confirmed = $true }
} | ConvertTo-Json -Depth 5
$submitHeaders = @{ Authorization = 'Bearer demo-citizen'; 'Idempotency-Key' = [guid]::NewGuid().ToString() }
$report = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/v1/reports' `
  -Headers $submitHeaders -ContentType 'application/json' -Body $submission
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/reports/$($report.id)" -Headers $demoHeaders
```

Retry with the same `$submitHeaders` and `$submission` after a network failure.

## Public and future contracts

The public routes remain `/api/v1/config/public`, `/api/v1/health/live`, and
`/api/v1/health/ready`. Health readiness checks actual PostGIS and private storage.

Provider validation contracts include report/media UUIDs, report revision, media
SHA-256, request ID, provider/version, decision, labels, reviewer and UTC completion
time. A human decision requires a reviewer ID and null confidence. Acceptance
requires at least one label. Those contracts do not grant a citizen approval power:
the authoritative endpoints verify database reviewer grants on every request.

Identity, storage, photo validation and reverse-geocoding protocols are in
`services/api/app/adapters/interfaces.py`. No provider implementation is falsely
represented as a working external integration.

## Shared issues and duplicate decisions

`GET /api/v1/issues/nearby` requires authentication and a category/longitude/latitude.
It returns minimal active issue summaries without citizen identities, photos or descriptions.
Submission accepts an optional `suggested_issue_id` and `reported_hazard`; both remain
citizen claims. An immediate hazard flag is visible during validation/duplicate review;
confirmed urgency and rapid-review prioritisation arrive in checkpoint 6.

`GET /api/v1/reviews/duplicates` returns scoped pending accepted reports and current
nearby candidates, including metre distance, trusted asset conflicts, resolved recurrence
suggestions and current issue/report versions. Hidden cross-area candidates produce a
`needs_cross_area_admin` flag without exposing their private evidence. Candidate history
retains the original evaluated versions; a refreshed inbox re-evaluates current candidates.

`POST /api/v1/reviews/duplicates/{report_id}/decision` requires an expected report revision,
request UUID, reason and action `link`, `new`, `recurrence` or `clarify`. Link/recurrence
also require candidate issue ID/version and compatible category/location/asset. Recurrence
requires a resolved predecessor. Clarification advances the report revision and removes
acceptance so queued old admission cannot run. A reused photo is ineligible as independent
support unless an authorised reviewer explicitly confirms independence.

`GET /api/v1/issues` is a staff list with UUID cursor and limit 1–50. Issue details expose
linked reports only within the actor's report-area scope. `POST /issues/{id}/merge` requires
source/target versions, target ID, request UUID and reason. `POST /issues/{id}/split` requires
source version, a proper subset of linked report IDs, confirmed point, request UUID and
reason. Both preserve historical links/events and invalidate priority; request replay is
idempotent and conflicting versions return 409. Merge retains the old reference as an alias.
Splitting an inventory asset issue is blocked until the inventory is reconciled.

## Priority engine

Issue summaries now include optional `priority`: score/band, factor values, weighted point
contributions, policy/POI version, epoch, original inputs and input hash, as-of/computed times,
provisional flags, overdue status and staleness. New issues awaiting computation retain a null
score. Dirty issues keep the previous snapshot, visibly stale, until refresh succeeds.

`GET /api/v1/priority/ranking` is scoped to reviewer/admin grants and sorts confirmed critical
overrides, descending score, earliest accepted report and UUID. Optional `area`, `category`,
`overdue` and bounded `limit` use the identical global scores. Empty historical issues with
no current evidence are excluded from ranked tasks, while remaining in shared issue history.
Staff cursor/map queue browsing is described below. `GET /priority/rapid-review` shows
reported hazards awaiting confirmation even before validation/admission, plus expired critical
overrides requiring re-review. Expiry never automatically clears a critical hazard.

`POST /priority/issues/{id}/decision` requires reviewer scope, expected issue version, request
UUID and reason. Severity overrides are null/category baseline or 0.25/0.50/0.75/1; urgency
is null/pending or 0/0.50/1. A critical override requires a future aware review deadline.
The decision is audited, versioned and recomputed. Citizens/operators cannot set priority.

Global admins can `GET /priority/policies`, `POST /priority/policies/preview`, inspect
`GET /priority/policies/{epoch_id}` and `POST /priority/policies/{epoch_id}/activate`.
Preview supplies pilot, POI snapshot, versioned policy, as-of time and review reason; weights
must include S/A/R/L/U, be finite/nonnegative and sum to one, and every active category must
have a bounded severity and positive target. Activation requires the expected active epoch
and reason. Preview never changes current scores; activation recomputes current issue revisions
and switches the entire pilot transactionally. Changing settings under an existing policy
version returns 409. Scores are proposed demo scheduling settings, not emergency guarantees.

Re-reviewing an admitted report now detaches its active link and queues the corrected
category/location for fresh admission. The earlier issue and evidence links stay in history.
Optional `trusted_asset_id` must be an existing inventory asset in scope, within the
category radius and matching the accepted category/pilot; a citizen cannot set it.

## Staff work queue and assignment

`GET /api/v1/staff/queue` is an additive API; the existing `/issues` history array remains
compatible. Reviewer/admin scope applies before ordering, counts and pagination. Filters:
`area` (configured code), `category`, `status` (default active), `band`, `overdue`,
`bbox=west,south,east,north`, `cursor`, and `limit` (1–50, default 20). Active excludes
resolved/merged issues and historical issues without evidence. All/status-specific views
can inspect history. Bounding boxes must be finite, within world bounds and non-inverted.
Unknown filter codes and invalid values return 422.

Ordering is confirmed critical first, score descending with pending scores last, oldest
accepted evidence, then UUID. A repeatable-read capture freezes issue positions, score
snapshot pointers and totals for 15 minutes. This prevents skipped/repeated issues when
scores or assignments change between pages. The opaque cursor is actor-bound; filter,
grant, active epoch or expiry changes require a first-page refresh (409). Another actor's
cursor returns 404. Each page rechecks issue ownership. Captures are bounded to 10,000
matches; narrow filters above that size. Only this page's pins are loaded by the map.

Totals distinguish issues, linked reports and eligible reporter–issue pairs; the last is
not a count of unique people across the queue. Issue fields/details remain current; a
changed version or score pointer is marked `changed_since_capture`. Captured scores keep
their original inputs and show stale/provisional state. Refresh ranking recaptures order
and totals; it does not force synchronous score recomputation.

`GET /api/v1/areas/summary` returns current active issue counts for every configured category
in permitted areas, including zeros: linked reports, reporter–issue pairs, high/critical,
confirmed critical, overdue, high-and-overdue and oldest evidence age. It uses one database
snapshot and the same active-state and priority definitions as the queue.

`GET /issues/{id}/assignees` lists active operators with global or matching area permission.
`POST /issues/{id}/assign` requires reviewer/admin scope, `request_id`, `expected_version`,
`operator_id` (null clears assignment), optional `team`, and a reason. Team labels require
an operator and grant no access. Only open/assigned/reopened states permit assignment;
citizens/operators cannot assign. Reused requests are idempotent; changed versions return 409. Assignment updates state/version, appends issue/audit events and queues priority refresh
while retaining the previous stale score.

## Repair lifecycle

`GET /api/v1/work` lists up to 50 current assignments for the operator. `GET /work/{id}`
allows the assigned area operator or scoped reviewer and returns issue status, retained
resolution records and event history. It does not expose private citizen reports.
`POST /work/{id}` requires request UUID, expected version, reason and one action:
`start`, `submit_repair`, `verify`, `reject`, `archive` or `reopen`. Start requires assigned
or reopened state; repair submission requires in-progress and owned, completed, unexpired,
unattached media IDs (1–3). Operators may now upload/complete private repair photos through
the existing upload endpoints. Attachment verifies both stored hashes.

Only an assigned area operator starts/submits work. Verification/rejection requires a
reviewer and pending state. A different person must verify, with the exact revision captured
by repair submission; incoming evidence requires rejection and renewed inspection. Verification
resolves the shared issue and clears critical scheduling; rejection returns it to in-progress.
Archive/reopen requires resolved state, retains evidence/history and clears archive on reopen.
Forbidden transitions/stale versions return 409; access fails closed. Every action is audited
and idempotent. Citizen tracking reflects the shared issue status without rewriting reports.

`GET /issues?reference=<exact-public-reference>` performs scoped exact lookup for merge
targets beyond the first 50 rows. Verification rechecks repair originals/display hashes;
unavailable/corrupt evidence returns 503 and leaves the issue pending. Queue fetches batch
issue/snapshot reads while preserving captured scores, ordering and scope semantics.
