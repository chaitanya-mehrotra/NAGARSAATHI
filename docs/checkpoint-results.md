# Checkpoint results

## Checkpoint 0 — passed, 3 October 2026

Change reference: CP0 scaffold under `Civic AI/nagarsaathi` (new source files;
no Git commit created). Fixture version: `demo-identities-v1`, demo configuration
schema `1`, boundary version `demo-envelope-v1`.

### Implemented

- React/TypeScript/Vite shell with API-driven pilot/category information, a visible
  demo notice, accessible headings, loading/error/retry states and responsive layout.
- FastAPI modular project and separate worker entry point; liveness, real dependency
  readiness and public configuration endpoints. Generated request IDs and structured
  errors include a sanitized unexpected-error response.
- Report/issue/category/role/validation enums, evidence-bound validation schemas,
  and identity, validation, private storage and geocoding provider protocols.
- OpenAPI export and generated frontend TypeScript contracts, including lifecycle
  enums. No model or GPU dependency.
- Runtime environment example, public synthetic identities, proposed pilot config,
  pinned PostGIS Compose image, Python/Node lockfiles and formatting/type-check scripts.
- Production guards reject demo auth/fixture validation; production is additionally
  blocked until real adapters are implemented. No generic role-selection UI exists.
- README startup path, ADR for report/issue separation, API and local operations notes.

### Environment and results

Windows, Python 3.11.9, Node 24.19.0, npm 11.17.0, uv 0.11.3,
Docker Desktop Linux engine, Compose 5.1.1. Exact Python/Node dependencies are in
`uv.lock` and `package-lock.json`. Vite 8.3.2, Vitest 5.0.3, MapLibre 6.11.2,
FastAPI 0.142.2, Pydantic 2.13.5 and psycopg 3.3.6 were installed.

Database image: `postgis/postgis:17-3.5`, pinned to digest
`sha256:01a6a70e41e6c4467c8f55f6063555ed72db2d6662cd0d571040d42eadaeb6f6`.

- `uv sync --locked --python 3.11 --cache-dir .uv-cache`: passed.
- `npm.cmd ci`: passed from the final lockfile; audit reported zero vulnerabilities.
- `.venv/Scripts/python.exe -m pytest`: **9 passed**. Covers public config, truthful
  readiness, both demo-source production guards, blocked unwired production startup,
  structured 404/500 errors, human-review evidence constraints and synthetic fixtures.
- `.venv/Scripts/ruff.exe check .`: passed.
- `.venv/Scripts/ruff.exe format --check .`: passed.
- `.venv/Scripts/mypy.exe`: passed, 13 source files.
- API and worker import check: passed.
- OpenAPI export and `npm.cmd run contracts`: passed.
- `npm.cmd run typecheck`: passed; also checked by the production build.
- `npm.cmd test`: **2 passed**, covering API-driven demo rendering and API-failure retry.
- `npm.cmd run build`: passed, 69 modules, generated `apps/web/dist`.
- `npm.cmd run format:check`: passed.
- `docker compose config --quiet`: passed.
- `docker compose up -d --wait`: passed; real PostGIS container healthy.
- `.venv/Scripts/python.exe -m worker`: dependency check passed (no job handler claim).
- `.venv/Scripts/python.exe scripts/smoke_http.py`: passed against actual loopback
  servers: API liveness, PostGIS/storage readiness, web HTML and Vite's API proxy.

Frontend tests/build and Docker operations needed sandbox escalation for child
processes/engine access; the requested operations succeeded. Initial dependency
advisories were resolved by updating packages and aligning the workspace Vite version.

### Manual checks and limits

- Inspected the source/configuration to confirm demo labels, public-only config,
  no live identity secrets in fixtures, loopback listeners and a production startup gate.
- Browser preview requested at `http://127.0.0.1:5173`; no manual browser visual or
  end-to-end citizen-flow acceptance is claimed. Those journeys belong to checkpoint 3.
- The current UI is a scaffold. No submissions, persisted reports, spatial schema,
  authentication, uploads, scoring, actual job processing or repair lifecycle yet.
- Public pilot/service-area configuration is synthetic and unreviewed. It is not
  official ward data. Real model and paid/external integrations are absent.
- Pytest emitted one upstream Starlette/httpx deprecation warning; all tests passed.
  npm emitted a transitive jsdom `whatwg-encoding` deprecation notice on clean install.
- No reset/seed command was introduced before a dedicated persisted demo schema exists.

**Exit gate passed:** the documented local startup path works without a model,
GPU, paid provider or external identity account. API readiness checked real PostGIS.

Checkpoint 0 was paused for review, then checkpoint 1 was authorized by the user.

## Checkpoint 1 — passed, 3 October 2026

Change reference: CP1 geospatial foundation under `Civic AI/nagarsaathi` (no Git
commit created). This is cumulative with checkpoint 0. Boundary version:
`demo-envelope-v1`; category rules: `demo-category-rules-v1`; POIs: `demo-pois-v1`.

### Implemented

- Three Alembic revisions: PostGIS baseline, 22-table foundation, and strengthened
  link/boundary integrity. Tables cover identities/scopes, pilots/areas/categories,
  reports/evidence, validation/location decisions, issues/links, priority history,
  resolution/audit events, idempotency and jobs. Later checkpoints will implement
  the APIs and workflows using these tables.
- Foreign keys, uniqueness, state/version checks, one active link per report,
  compatible admitted-report links, immutable event/audit rows and merge-cycle guards.
  Spatial GiST indexes support area, issue and POI queries.
- Six versioned synthetic GeoJSON area polygons exactly partition the demo envelope.
  Confirmed points are assigned with `ST_Covers`; shared edges/corners use the first
  covering area code in PostgreSQL `C` order. Missing/unconfirmed coordinates or an
  uncertainty radius crossing a boundary require review; outside points stay outside.
- A metre-based nearby-issue query uses geography and crosses area borders. It only
  retrieves candidates; it does not merge or admit complaints.
- Editable category assumptions for five categories with automatic merging disabled.
  Fictional POI fixtures include a school outside the pilot but inside the 500 m
  snapshot margin; coverage is explicitly incomplete.
- A transactional, repeatable demo seed restricted to local demo/test databases.
  It rejects gaps, overlaps and changed polygons under an existing version.
- A new `Civic AI/Checkpoints` folder containing cumulative source ZIPs, integrity
  checks and SHA-256 manifests. Checkpoint 0 was archived before checkpoint 1 edits;
  checkpoint 1 includes both checkpoints. Runtime data and installed dependencies
  are excluded. Startup/migration/seed instructions are in the README.

### Validation

- Real local PostGIS: fresh migrations, populated upgrade from `0001` to `0002`,
  downgrade/re-upgrade, foreign keys/uniqueness, invalid state/category/version/area,
  link history and orphan admission, audit immutability and merge-cycle checks.
- Geometry fixtures: area centres, shared edges/corners, missing/swapped/outside
  coordinates, uncertainty, invalid/non-finite inputs, exact coverage without gaps
  or overlapping interiors, invalid seed rollback and idempotent seeds.
- Distance thresholds: 19.9 m included and 20.1 m excluded from a 20 m query;
  cross-area candidate retrieval and inactive issue exclusion.
- Query-plan smoke check over 5,000 synthetic issues confirms use of
  `issues_geom_gist` for the nearby query. This is an index smoke check, not a load
  test or a performance SLA.
- Python tests: **67 passed**; Ruff lint/format and strict mypy checks passed.
- Frontend regression tests: **2 passed**; TypeScript check and production build
  passed. Source formatting passed. Database migration and demo seed passed.
- Worker dependency check and real HTTP smoke passed: API liveness, PostGIS/storage
  readiness, frontend HTML and development API proxy.
- Same upstream Starlette/httpx deprecation warning as checkpoint 0; no test failure.

### Exit gate and limits

All confirmed valid fixture points receive one expected deterministic area; outside
points remain out of scope. Tests use disposable real PostGIS databases, not SQLite.
The checkpoint 1 exit gate passed.

These boundaries, category policies and POIs remain unreviewed synthetic examples.
There is no new citizen submission/authentication/upload flow, scoring engine,
duplicate-review workflow, production provider or backup/restore claim. Concurrent
merge/workflow behavior will be tested when those workflows are implemented.

Checkpoint 1 was paused for review, then checkpoint 2 was authorized by the user.

## Checkpoint 2 — passed, 3 October 2026

Change reference: CP2 authenticated intake under `Civic AI/nagarsaathi` (no Git
commit created). Cumulative source snapshot: `../Checkpoints/checkpoint-02.zip`.
Migration revision: `0003`; demo identity/scopes fixtures: `demo-identities-v2` and
`demo-scopes-v1`. Python dependencies added and locked: PyJWT 2.15.1,
cryptography 50.0.2 and Pillow 12.3.0.

### Implemented

- Database-provisioned citizen/reviewer/operator/admin grants and area scopes, two
  public demo citizens and scoped demo staff. Existing users/grants are preserved
  when seeding, including revoked grants. Activity/permissions are loaded per request.
- An OIDC verifier checks signed RS256/ES256 tokens, configured HTTPS JWKS, issuer,
  audience, subject, issue time and expiry. It fails closed on invalid tokens/key
  lookup failure. Claims cannot grant a role. No hosted identity account was connected.
- Private owned JPEG/PNG upload → completion flow. Bounded byte reads, actual type
  and decoding checks, pixel/animation limits, SHA-256 hashes and server UUID keys.
  Correctly oriented display JPEGs omit EXIF; original bytes remain private.
- Durable submission and retrieval APIs, own-report cursor pagination, authenticated
  photo streams and scope checks. Uploads expire before attachment; attached report
  evidence survives expiry and restart. No private storage key/reporter identifier
  is exposed in report responses; authenticated responses forbid caching.
- Transactional idempotency, ordered upload row locks, category/ownership/completion/
  expiry checks and rollback-safe attachment. Same-key retries return the same
  report; changed payloads conflict; two different keys cannot reuse one upload.
- Raw claimed category/location retained independently from future review. Confirmed
  in-pilot reports remain submitted, unlocated reports await review, and outside
  reports remain visible to their owner as out of scope. Clients cannot forge approval.
- Migration `0003` adds expiry/completion and original location evidence. Deferred
  constraints prohibit incompatible media ownership/completion and admission without
  completed owned evidence. OpenAPI/TypeScript contracts and usage docs updated.

### Validation

- Python tests: **102 passed**, including all previous geospatial/integrity tests.
- Owner/other citizen, Southwest reviewer versus Northeast report/media, operator
  private-access restrictions, admin read access, missing/invalid identity, disabled
  account and client-forged roles/status/approval/category/priority.
- Locally signed OIDC tokens: valid identity, wrong issuer/audience/signature,
  expired/future/missing claims, unsupported algorithm, malformed token, unavailable
  JWKS and a forged admin claim that still receives database citizen permissions.
- Invalid/mismatched/undecodable/truncated/empty/animated images; byte, pixel and
  combined photo limits; EXIF removal/orientation; original retention; path traversal
  rejection; storage failure and corruption; incomplete/expired/cross-user/reused uploads.
- Four concurrent requests with one idempotency key create one report. Different
  keys competing for one upload yield one success and one conflict. Changed body
  conflicts. Injected failure after writes rolls back attachment/idempotency and
  permits retry. Admission without completed media fails and rolls back.
- **Actual API process restart with real loopback HTTP and PostGIS:** upload, complete,
  submit, terminate the API, start a new process, retrieve the identical report and
  display photo; a second citizen cannot retrieve either. All data used a uniquely
  created disposable test database and temporary private media directory.
- Ruff lint/format, strict mypy (25 source files), OpenAPI export/generated TypeScript,
  frontend type checking, **2 frontend regression tests**, production build and source
  formatting passed. Live demo migration/seed commands passed.
- Live API/frontend HTTP smoke, worker dependency check and demo authentication/
  own-report listing/no-cache checks passed against the updated running API.
- One upstream Starlette/httpx deprecation warning remains. A frontend command's
  automatic approval review timed out; its single permitted retry succeeded.

### Exit gate and limits

The checkpoint 2 exit gate passed: a citizen can persist and retrieve a report and
private evidence after an actual API restart, with other-citizen access denied.

The frontend is still the checkpoint 0 shell; the submission/tracking screens arrive
in checkpoint 3. Reports are pending validation, not admitted physical issues.
No hosted identity account, production rollout, EXIF GPS extraction, photo validator,
worker processing, duplicate/scoring/repair flow or backup/restore claim is made.
Crash-orphan/expired-file cleanup and broader resource-abuse controls remain later
hardening work. The synthetic pilot/category/POI assumptions remain unreviewed.

**Paused after checkpoint 2 at the user's request.** Await the next command before
checkpoint 3: the minimal citizen UI.

The user subsequently authorized checkpoints 3, 4 and 5 together.

## Checkpoint 3 — passed, 3 October 2026

Implemented citizen sign-in using pre-provisioned identities, photo previews/removal,
description/category entry, local MapLibre outlines with an issue marker, coordinate
and denied-geolocation fallback, explicit pin confirmation, review/submit, receipt,
own-report pagination and report detail with authenticated photo display. English UI
preserves arbitrary Unicode text. No street tiles/geocoder account is required.

Draft metadata/completed uploads and an idempotency key survive browser-tab reload;
failed upload files remain selected for retry until reload. Failed file bytes must
be reselected after reload. A successful submission clears its draft. OIDC tokens
stay in memory; only public demo tokens persist in session storage. Changing users
clears cached private queries and keeps drafts separate by identity.

Validation: **102 Python tests**, **2 Vitest tests**, **8 Playwright tests** at desktop
1280×800 and mobile 390×844. Real API/PostGIS browser journeys cover upload without
EXIF, final review/receipt, reload and authenticated evidence, own reports, denied
geolocation, missing-description errors, offline upload/retry, keyboard metadata and
submission, repeated request, failed boundary map and draft reload. No horizontal
overflow or uncaught browser exception in the successful journey. Inspected mobile
capture. Geocoder is deliberately unavailable and a manually entered landmark works.
Ruff, strict mypy, TypeScript/contracts, formatting and production build passed.

MapLibre's worker URL was explicitly bundled after fixing a development optimizer
failure. The production map bundle still emits Vite's large-chunk warning; no bundle
size/performance SLA is claimed. Browser tests create clearly synthetic demo reports;
they do not modify roles or fabricate validation. Test screenshots/traces are excluded
from source archives. More browser/worker hardening belongs to checkpoint 9.

Exit gate passed: citizen submission/tracking works through real database-backed APIs
without database edits or a live mapping provider. Archived as `checkpoint-03.zip`.
Continuing to checkpoint 4 under the user's three-checkpoint authorization.

## Checkpoint 4 — passed, 3 October 2026

Implemented revision/hash-bound validation adapters, versioned exact-label mapping,
transactional job creation, a polling worker with short skip-locked claims, 30-second
leases and three bounded retries. Arbitrary photos default to human review; the
synthetic fixture catalog is intentionally empty. Fixture acceptance is forbidden
for production/non-synthetic reports. Human decisions record the real reviewer and
null confidence, preserve claimed values, and audit category/location corrections.

Staff screens show scoped pending reports, evidence, category/location decisions,
clarification/rejection and technical failures. Repeated identical decisions are
idempotent; stale edits and cross-area corrections are denied. Accepted photos with
missing location remain unadmitted. Located acceptance queues admission for the next
checkpoint. Validation results and stale jobs cannot overwrite a newer revision or
different photo hash. Lease ownership prevents an abandoned worker finishing/failing
a reclaimed job. No external validation callback endpoint is exposed.

Validation: **116 Python tests**, **2 Vitest tests**, **10 Playwright desktop/mobile
journeys**, strict mypy, Ruff lint/format, TypeScript/contracts and production build.
Tests cover accepted/rejected/uncertain/error results, unknown/contradictory labels,
invalid missing-label results with bounded retry/failure, missing GPS, claimed-label
conflicts, forged citizen approval, current evidence binding, repeated callbacks,
human reclassification/reprocessing, scope/area guards, stale jobs, lease reclaim and
fixture production guard. Real browser staff review changes the accepted category
through authenticated APIs. Inspected mobile staff screenshot. Worker `--check` and
`--once` passed against real local PostGIS. Existing dependency/bundle warnings remain.

Exit gate passed: authoritative category/location decisions are auditable and the
photo validator uses an evidence-bound adapter contract, without a GPU/model/account.
Citizen clarification/media-replacement editing and a production identity/model
connection are not claimed. Admission and shared issue actions arrive next.
Archived as `checkpoint-04.zip`; continuing to checkpoint 5 as authorized.

## Checkpoint 5 — passed, 3 October 2026

Implemented shared issue admission and conservative duplicate rule `conservative-v1`.
Same-category geographic searches use metre radii across area borders, retain old
unresolved issues and include resolved recurrence suggestions. Known uncertainty expands
retrieval by a capped 25 metres; poor/unknown quality requires review. Different verified
inventory IDs are hard conflicts. Same-photo reuse never proves the same physical issue;
conflicting locations are flagged without exposing another reporter's private information.
Only an explicitly enabled trusted unique asset match with compatible location and no
uncertainty/reused-photo conflict can auto-link. All category defaults remain disabled.
Missing text/visual features stay null; receipt gap and location uncertainty are recorded.

The worker now processes admission as well as validation, with owned leases. All final
create/link/reclassify/merge/split paths use the same pilot/category advisory locks. Current
validation, geographic ownership and one active link are checked transactionally. Deferred
constraints inspect final transaction state, including ended links. Historical links may
only be ended; they cannot be rewritten/deleted. Issue events and request audit history
retain all decisions. Merge preserves the source alias; split moves a proper report subset
to a reviewed point. Reclassification detaches the old link before fresh admission and
leaves the earlier issue/category and original citizen evidence intact.

Staff screens provide side-by-side duplicate evidence, distance/asset/version context,
link/separate/clarification/recurrence decisions, shared issue details, merge and split.
Cross-area decisions require access to both candidate areas; out-of-scope evidence stays
hidden. Citizen selection of a nearby issue remains a claim, and linked receipts show the
shared issue reference. Reported immediate hazards remain visibly unconfirmed in staff
review. Clarification removes acceptance and advances the revision, preventing an old
queued admission. Distinct eligible reporter counts exclude repeated/reused evidence;
group changes refresh counts/timestamps, clear priority snapshots and queue recalculation.

Validation: full regression run **131 Python tests passed**, followed by **2 focused
checks** for concurrent submission/admission and added merge/split scope/version guards
(current suite contains **132 tests**). **2 Vitest tests**, **12 real Playwright desktop/mobile
journeys**, Ruff lint/format, strict mypy (36 source modules), TypeScript/contracts, formatting
and final production build passed. Browser tests run the real polling worker and exercise
linking, separate issues, merge aliases, split counts, photo access, receipt/reload/retry and
keyboard navigation. Mobile shared issue screenshot inspected; no horizontal overflow.
Live API/worker restarted; HTTP liveness, real PostGIS/private-storage readiness, frontend
and proxy smoke checks passed. Existing FastAPI TestClient deprecation and MapLibre large
bundle warnings remain; no production performance SLA is claimed.

Database tests cover ten concurrent report submissions followed by ten concurrent admission
transactions (one new issue, nine review candidates), nearby different defects, cross-border
ownership, trusted asset conflicts and guarded asset auto-linking, old active issues,
resolved recurrences, reused photos, repeated reporters, uncertain location, stale versions,
merge rollback, aliases/history, proper-subset split, cross-area scope, reclassification and
idempotent worker delivery. The four explicitly labelled synthetic fixture pairs retrieve
**2/2 known same pairs**, with **three manual decisions: two links and one separate issue**;
the distant different pair creates a separate issue. Candidate recall and reviewer decisions
are reported separately. This tiny fixture set establishes deterministic behaviour, not
real-world auto-link accuracy or a calibrated 98% precision claim.

Exit gate passed: uncertain cases remain reviewable and grouping does not lose reports.
Inventory import, production model/identity rollout, clarification photo replacement,
confirmed urgency/rapid-review prioritisation, priority scoring, full staff maps/filters,
assignment and repair verification remain later work. Priority jobs stay pending for
checkpoint 6. The demo remains local and synthetic. Archived as `checkpoint-05.zip`;
stopping here after the three checkpoints authorised by the user.

## Checkpoint 6 — implementation verified, 3 October 2026

Implemented deterministic `weighted-v1` scoring with explicit as-of time and the proposed
0.35 severity / 0.20 age / 0.15 independent reporters / 0.20 exposure / 0.10 urgency policy.
Every factor clamps to [0,1]; category baselines/targets stay versioned and separate from
reviewer severity/urgency overrides. Future timestamps contribute zero age and are flagged;
zero eligible reporters are guarded. Independent active authenticated accounts count once;
reused-photo evidence remains excluded unless reviewed. Five distinct eligible reporters in
60 seconds flag burst review without changing the score. Model confidence is not an input.

Exposure uses versioned school/hospital distances and trusted road geometry, taking the
maximum rather than summing. Complete coverage must include the entire search neighbourhood;
unknown/incomplete coverage uses L=0.50 and an explicit provisional flag. The outside-pilot
school fixture is still eligible through the snapshot's margin. Urgency defaults to a labelled
provisional 0.50. Critical scheduling overrides require an authorised reviewer, reason and
future review deadline; expiry keeps the override visible and flags re-review. Reported hazards
enter rapid review before validation/linkage, and expired critical issues return for review.

Immutable snapshots retain original inputs, policy/POI versions, factors, point contributions,
input hash and as-of/computed times. Revision/epoch-bound jobs refresh after grouping/review;
the worker schedules stale age scores in batches of 100 and deduplicates 15-minute buckets.
Stale jobs reschedule current revisions. Failures retry three times and retain the last score
with a stale indicator. Merge/split/reclassification preserve history and invalidate freshness.
Empty historical issues remain inspectable but do not become ranked tasks without current evidence.

Global administrators can preview a new version's scores before activation. The pilot's
activation lock coordinates with all grouping paths; activation recomputes current active
issues and switches the entire epoch transactionally. A failure after writing the first issue
rolls back every new pointer and epoch state. Only one active epoch exists per pilot. Ranking
uses repeatable-read consistency, identical scores under area/category filtering, critical-first
ordering and deterministic score/age/UUID ties. POI data sealed by an epoch cannot be appended
or rewritten; real imports require a new snapshot. Policy/snapshot history is immutable.

Screens now provide `/priority`, rapid hazard review, an overdue filter, issue factor
explanations, reviewer severity/urgency/critical decisions and `/priority/policies` previews
and activation for global admins. Inspected the mobile screenshot. Full staff map/filter
dashboards and cursor queue navigation remain checkpoint 7; repair/status workflows remain 8.

Validation: **148 tests passed in the full Python regression run**, followed by **18 focused
priority tests** including added split/reclassification and burst checks (current suite: **150
tests**). **14 real desktop/mobile Playwright journeys**, **2 Vitest tests**, strict mypy (40
source modules), Ruff lint/format, generated contracts/TypeScript, formatting and production
build passed. Exact 51/66/76 fixtures, bad weights, 500 seeded monotonicity cases, caps, future
age, missing-versus-absent POIs, outside-pilot school, overrides, overdue/critical expiry,
reporter abuse, stale revision/epoch, rollback after partial activation, immutable data,
filtered/global score equality and grouping refreshes are covered. Browser tests exercise
real worker processing, priority review, explanations and full epoch activation. Live API and
priority worker restarted; HTTP/PostGIS/private-storage/web/proxy smoke and worker dependency
checks passed. Re-running the seed preserved the selected policy. Existing TestClient
deprecation and large MapLibre bundle warnings remain; load/throughput measurements belong to 9.

The technical scoring gate is verified. The plan also says “Validate top-ranked fixture issues
with a small human review exercise; mathematical correctness alone does not validate policy
usefulness.” The proposed 51/66/76 ordering and critical-first rule were presented to the user
for that review; their response is pending at snapshot time. Demo defaults remain proposed:
no real-world priority usefulness, official SLA, complete POI coverage or distinct-person
verification is claimed. Local demo activation is tested, not production pilot acceptance.

Saved as cumulative `checkpoint-06.zip` with SHA-256 manifest; stopping before checkpoint 7.

## Checkpoint 7 — staff queue, maps and area/category views

Completed the staff work queue at `/staff` and service-area comparisons at `/staff/areas`.
Area, category, active/history status, priority band, overdue and map-bounds filters persist
in the URL and survive issue-detail navigation. Confirmed critical issues precede descending
score, oldest evidence and UUID ties. The map displays numbered pins from the identical
ordered page; no unbounded marker or photo fetch is performed. Failed maps leave filters and
the list usable, and retry is available. Mobile layouts wrap coordinates and long references;
the inspected 390-pixel screenshot and browser overflow assertions pass. Kannada descriptions
render in protected issue evidence. Details retain priority factors/contributions, original
inputs and stale/provisional states, with an explicit reload action.

The additive `/api/v1/staff/queue` captures ordering, immutable score pointers and totals
under repeatable-read isolation in migration `0008`. Actor-bound cursors expire after 15
minutes and require a refresh after filter, role-scope or active-epoch changes. This keeps
paging stable under score/assignment changes and exact score/age ties. Captures are limited
to 10,000 matching issues and response pages to 50 (UI default 20). Ownership is checked
again on every page. Changed issue versions or score pointers are marked; current details
remain available while the captured order stays stable. A refresh obtains current ranking
and totals. Expired captures are removed for the caller on first-page requests; global
retention cleanup and measured load performance remain checkpoint 9.

Counts explicitly distinguish active issues, linked reports and eligible reporter–issue
pairs; the latter is not a global distinct-person count. Scoped area/category summaries
include zeros, high/critical, confirmed critical, overdue, high-and-overdue and oldest age.
Citizens/operators cannot read staff queues or area counts; out-of-area evidence/details
remain denied. The existing `/issues` history API stays compatible.

Assignment controls on issue details list only active, area-permitted operators. Reviewer
or admin assignment requires a reason, expected version and idempotent request ID. Clearing
assignment is supported; optional team labels grant no access. Changes update status/version,
append audit/history and enqueue priority refresh while retaining the previous stale score.
Open/assigned/reopened issues are eligible; start-work and repair/resolution transitions are
deliberately left for checkpoint 8. The existing demo operator is scoped to Southwest.

Validation: **163 Python tests passed in the full regression run**, followed by the added
**exact-tie/grant/epoch test** (current suite **164 tests**, including **14 new checkpoint 7
cases**). All **18 distinct desktop/mobile browser journeys** passed across the regression
and corrected focused runs: the regression passed 16/18 while two new journeys needed a
selector correction, and the final focused staff run passed all 4/4 with API/UI count and
mobile overflow assertions. Initial browser fixture assumptions about URL comma encoding
and pre-existing merged history were also corrected. **2 Vitest tests**, generated API
contracts, TypeScript, strict mypy (43 source modules), Ruff lint/format, Prettier and the
production build passed. Real live API/PostGIS/private-storage/web/proxy smoke, worker
dependency checks, staff queue and 30 scoped area/category-summary rows passed after the
API/worker restart. Existing TestClient deprecation and MapLibre bundle-size warnings remain.

The demo exit gate is met: staff can select an area's potholes, inspect priority order and
evidence, compare all categories and assign a permitted operator through the app. Proposed
priority policy usefulness and real service boundaries remain subject to the checkpoint 6
human-review/pilot gates; no production or operational acceptance is claimed.

Saved as cumulative `checkpoint-07.zip` with SHA-256 manifest; stopping before checkpoint 8.

## Checkpoint 8 — work lifecycle and resolution

Migration `0009` adds repair-media ownership, resolution revision binding and an archive
timestamp. `/work` lists an operator's assigned tasks; `/work/{id}` exposes work status,
repair evidence and history without giving operators access to private citizen reports.
Assigned area operators can start work and submit one to three completed private photos.
Area reviewers/admins can verify or reject pending repairs. Verification requires a different
person and an unchanged issue revision; a new report during verification forces inspection
and a fresh repair submission. Failed verification returns the issue to in-progress. Pending
resolution remains active. All linked citizen reports read the shared issue's current status.

Resolved issues can be archived without deleting reports, photos or history, then reopened
for the same failed repair. A later recurrence remains a new linked issue through duplicate
review. Changes require expected versions, reasons and idempotent request IDs, and append an
audit timeline. Repair photos remain protected and retained; attached media cannot also be
used as citizen submission evidence. Only the assigned operator may work, and role/area checks
apply to work details, photos and transitions. Production startup remains gated.

Validation: **166 Python tests passed** in the full regression, **18 desktop/mobile browser
journeys passed**, including real photo upload, independent verification, archive and reopen.
Focused tests cover shared resolution, forbidden/citizen/unassigned transitions, stale
versions, pending-active state, incoming evidence, failed verification, recurrence and retained
evidence/history. **2 Vitest tests**, TypeScript/build, generated contracts, Ruff, strict mypy
and formatting pass. A stopped local PostGIS service interrupted the first broad run; it was
restarted with its volume retained and both full suites rerun successfully. Migration requires
stopping/restarting long-lived workers to clear prepared SQL plans after schema changes.

Saved as cumulative `checkpoint-08.zip` with SHA-256 manifest. Continuing to authorized
checkpoint 9; optional checkpoint 10 remains deferred.

## Checkpoint 9 — recovery, load and release candidate

Added an isolated release runner with fixed synthetic IDs/timestamps: 1,000 reports across
300 issues, six areas/four categories and rejected/out-of-scope/review cases. It tests a real
local API with 20 distinct synthetic identities, database dump/restore and 1,001 original/
display photo hashes including retained repair history. Only newly created disposable
databases are seeded/restored; the normal API rejects load tokens. Runtime backups stay
private under ignored `.local`; source snapshots contain scripts and measured results.

Recovery tests kill a leased worker with an uncommitted write, verify rollback, advance lease
expiry and recover without duplicate active links. Duplicate/old jobs and storage/location
failure are covered. Repair verification now rechecks retained photo hashes. Maintenance
previews expired unattached uploads, old orphan files and expired queue metadata; apply tests
retain admitted evidence. Live maintenance was previewed only.

Queue fetches now batch issue/snapshot reads. Explicit IPv4 defaults remove a three-second
IPv6 fallback on Docker's local binding. Exact-reference merge lookup fixes the old first-50
picker limit. Browser fixtures avoid previous data instead of resetting it.

Final results: queue p95 **238.68 ms**, metadata submission p95 **171.86 ms**, processing to
required human review p95 **1.194 s**, and **300 age refreshes in 7.141 s**, zero stale.
Measured targets pass on the recorded Windows/Ryzen 9 270/16 GB environment. Upload bytes,
reviewer wait and automatic admission are excluded; 10,000-report, multi-host and real-photo/
provider tests were not run. See `release-validation.md` and JSON for hardware and limits.

Validation: **169 full Python tests**, **18 desktop/mobile browser journeys**, **2 Vitest
tests**, generated contracts, TypeScript/build, strict mypy (46 modules), Ruff and formatting
pass. Enhanced crash/cleanup and photo checks also pass in **3 focused recovery tests** and
**4 staff browser journeys**. Live API/worker restart and readiness/private storage/web/proxy/
operator-task smoke pass. Existing TestClient/bundle warnings remain.

The local release-candidate gate is met with actual results and known limits recorded.
Production stays blocked pending real identity/providers, reviewed boundaries/policy usefulness
and operational backup/retention decisions. No municipal or real-world acceptance is claimed.
Saved as cumulative `checkpoint-09.zip` with SHA-256 manifest. Checkpoints 0–9 are compiled;
checkpoint 10 remains optional and deferred.
