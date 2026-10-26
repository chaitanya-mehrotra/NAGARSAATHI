# NAGARSAATHI V2 — Complete Build Plan

Date: 26 October 2026

Status: implementation started in V2 following the user's subsequent instruction on 26 October 2026. See `docs/BUILD_STATUS.md` for completed work and pending acceptance checks. Deployment, GitHub push, database reset and real-data migration remain outside the current instruction.

## 1. Objective and agreed requirements

Build a deployable civic reporting platform by retaining main's database integrity, validation/review, duplicate handling, prioritisation, and repair lifecycle, while selectively porting Chaitanya's user interface and Leaflet maps.

The latest requirements are:

- Citizens can create, recover, and manage their own accounts.
- Provide an easy Continue with Google option alongside ordinary account registration.
- Provide a separately provisioned administrator account and dashboard for reviewing, moderating, deleting/restoring complaints, and managing staff and complaint workflows.
- Use Docker Compose so friends can run the complete application on their computers without installing Python, Node, or PostgreSQL directly.
- Preserve data through inactivity, application restarts, container recreation, and ordinary software updates.
- Keep current human-review validation behaviour. No working validation model is assumed or required for the first V2 release.
- Prepare a future fine-tuned YOLOv8n provider, with Gemini API fallback/verification. Do not adopt the UI branch's YOLO11n model as V2's validation model.
- Prepare the API and mobile web experience for a later app.
- Do not push anything to GitHub without a subsequent explicit instruction.

The original planning task created only this document. The subsequent build instruction authorises application work inside V2; the original checkout and its data remain unchanged.

## 2. Reviewed baseline and review limitations

Local source: `../Civic AI/nagarsaathi`, main commit `07c3d40ce05e25279d77b5b4414a1b64153e89e2`.

UI reference: `chaitanya-mehrotra/NAGARSAATHI`, branch `chaitanya's-UI`, commit `a07610eebfbc406fabcac09ec5734622c8e79046`.

The GitHub comparison contains 123 removed files, 18 additions, and 5 modifications. The UI branch replaces main's architecture rather than simply improving its frontend. A normal merge would remove migrations, domain workflows, typed contracts, and tests. Start future implementation from main and selectively port UI components.

Review performed: read-only source, migrations/configuration inventory, API and worker paths, tests and historical release documentation, plus official provider documentation. Neither application was started and tests/load/security probes were not executed during planning. Previously recorded passing tests are historical evidence, not a fresh V2 certification. Failure hypotheses are identified separately below.

## 3. What the database is used for

PostgreSQL is the application's durable record system. PostGIS adds spatial data types and geographic queries. A database engine/connection pool being created when the API starts is not a new database being created.

### 3.1 Existing main responsibilities

1. **Accounts and permissions:** application user IDs, external identity subjects, active/disabled state, display names, roles, and service-area grants. Main does not yet provide public self-registration or a complete account-management interface.
2. **Citizen reports:** original descriptions, claimed and accepted categories, ownership, submission timestamps, locations, processing states, revisions, and receipt references.
3. **Physical issues:** a shared repair task that can have several supporting citizen reports. Five reports about one pothole remain five reports linked to one issue.
4. **Geography:** pilot polygons, service-area boundaries, boundary versions, confirmed points, uncertainty, and spatial ownership/distance checks.
5. **Media metadata:** file/object references, original/display hashes, dimensions, byte sizes, owner, attachment state, completion state, and expiry of unattached uploads.
6. **Review and validation:** photo/category/location decisions, provider versions, evidence bindings, reasons, and report revisions.
7. **Duplicate management:** candidate comparisons, active report-to-issue links, merge/split history, aliases, asset conflicts, and recurrence relationships.
8. **Prioritisation:** policy versions, scoring epochs, immutable score snapshots, severity/urgency decisions, trusted geographic context, and explanation inputs.
9. **Work and resolution:** assignments, work transitions, repair submissions, evidence references, independent verification, archive timestamps, and reopen history.
10. **Background processing:** durable jobs, attempts, leases, retry times, failure state, and deduplication keys.
11. **Retry safety and audit:** idempotency records, action requests, revisions, and retained events that make retries and concurrent staff actions safe.
12. **Temporary staff browsing:** queue captures that keep order/counts consistent while staff paginate.

### 3.2 Where photos actually live

The current main application stores original photos and metadata-free display JPEGs privately under `.local/media`. PostgreSQL stores their metadata and storage keys; it does not currently store the image bytes as database blobs.

V2 must preserve both the database and the corresponding media. A database-only backup cannot restore missing photographs. Identity-provider data also needs a backup when identity is self-hosted.

### 3.3 Does inactivity delete the database or create a new one?

**No. The inspected application does not delete the main database because nobody uses it. It does not create a new application database for each visit, login, or server startup.**

- Current Compose stores PostgreSQL files in a named `postgres_data` volume.
- A normal stop/restart or container recreation reuses that volume.
- Logging out or an expired identity token does not delete the account or its reports.
- Archive retains complaint evidence/history; it is not deletion.
- Upload expiry makes an unattached upload unusable for attachment. Cleanup is a separate operation.
- The maintenance command is dry-run by default. Its apply mode removes expired unattached uploads, qualifying old orphan files, and expired temporary queue captures. It is designed to retain attached report and repair evidence.
- A first-page staff queue request also removes that caller's expired queue captures. These are temporary browsing records, not complaints or accounts.
- Integration/release tests deliberately create and remove isolated disposable test databases. This must remain restricted to test targets and credentials.
- Removing Docker volumes, resetting Docker Desktop storage, deleting disk files, using an explicit reset script, or pointing configuration at a different database can remove data or make a different empty database appear.
- Changing the Compose project name or volume configuration can select a different volume. Document stable project names and explicit backup/import steps.
- Hosting-provider suspension or retention policies are separate from application behaviour and must be checked when a host is selected. A suspended service is not necessarily a deleted database.

**V2 persistence rule:** no automatic account/report/issue/evidence deletion based only on inactivity. Define an explicit retention and account-deletion policy before public launch. Temporary cleanup must be bounded, auditable, and distinct from complaint retention.

### 3.4 Separate computers versus a shared service

Each friend's local Docker installation gets its own independent database, identities, and media volumes. Docker does not automatically synchronise data between computers.

For everyone to see the same reports, deploy one shared backend/database/media service and point clients at it. Never synchronise live PostgreSQL data directories through OneDrive or another file-sync service. Transfer local test data using deliberate export/restore procedures.

## 4. Target architecture and repository layout

Retain a modular FastAPI application, PostgreSQL/PostGIS, a separate Python worker, and a React/TypeScript frontend with generated OpenAPI types.

```text
Browser / future app
  -> web gateway (HTTPS in deployment)
     -> static React frontend
     -> /api/v1 -> FastAPI -> PostgreSQL/PostGIS
                         -> private media adapter
                         -> durable jobs -> worker
  -> OIDC identity service -> optional Google identity provider

Future only: worker -> YOLOv8n provider
                   -> Gemini verification/fallback provider
                   -> reviewer when inconclusive/unavailable
```

Proposed future source structure inside this V2 folder:

```text
V2/
  build plan.md
  README.md
  compose.yaml
  compose.dev.yaml
  .env.example
  apps/web/
  packages/contracts/
  services/api/
  services/worker/
  services/identity/       # realm/configuration, no secrets
  infrastructure/docker/  # Dockerfiles and gateway config
  config/
  scripts/
  tests/
  docs/
```

This is a proposed layout, not a scaffold created by this planning task. Implementation should copy reviewed source into V2 only when requested; exclude `.git`, `.env`, databases, private media, dependencies, caches, test artifacts, and bundled model weights. Keep the original project intact. The location of future version control for V2 must be explicit because this folder is outside the existing `nagarsaathi` Git repository.

## 5. Preserve, port, and replace

### Preserve from main

- PostGIS metre-based spatial checks and versioned boundaries.
- Alembic migrations and database integrity constraints.
- Reports versus shared issues.
- Database-controlled permissions and area scoping.
- Private evidence, metadata removal, hash verification, and upload completion.
- Idempotency, revisions, durable jobs, and audit history.
- Conservative duplicate review, merge/split, and asset safeguards.
- Explained, versioned priority scoring and stale/unknown-context indicators.
- Assignment, repair evidence, independent verification, archive, and reopen.
- Typed contracts and meaningful integration/end-to-end tests.

### Port from Chaitanya's UI

- Sidebar, dashboard composition, typography, colours, cards, filters, detail presentation, and reporting wizard.
- Leaflet map interactions, draggable pins, explicit location controls, popups, and fit-to-results.
- Useful photo-preview/overlay presentation patterns after adapting the data contracts.

### Replace or redesign

- SQLite backend, simplified direct status updates, shared demo auto-login, hardcoded photo URLs, and query-string bearer tokens.
- The old service layer, untyped report/status assumptions, and inaccurate Live indicators.
- Supabase instructions that do not describe the branch's actual SQLite runtime.
- YOLO11n integration: do not treat its weights or evaluation as the proposed YOLOv8n model.

## 6. Citizen accounts and Google sign-in

### 6.1 User-facing capabilities

- **Exclusively Sign In with Google:** Google Sign-In is the sole citizen sign-in and account registration method. Traditional standalone email/password account creation is omitted to prevent password credential sprawl and ensure verified identity subjects.
- Citizen accounts are auto-provisioned upon verified Google authentication.
- Sign in/out and manage active sessions across devices using Google credentials.
- Manage display name, language preference, and optional contact information.
- View reports across devices after signing into the same Google-authenticated account.
- Prevent duplicate accounts or link takeovers by locking account identity to Google's immutable provider subject identifier (`google:{sub}`).
- Keep staff and administrator access controlled via administrative grant; public Google sign-in always provisions citizen access only.

### 6.2 Proposed identity implementation

Use an OIDC identity service for passwords, verification, recovery, sessions, and Google federation. Proposed portable default: containerised Keycloak backed by its own persistent PostgreSQL database. This fits main's existing OIDC verification boundary and can run on friends' systems. Record the final choice in an architecture decision before implementation; a managed OIDC service is an alternative if self-hosting overhead is unsuitable.

Keycloak owns credentials and linked Google identities. The application owns its user profile, complaint ownership, active state, and role/area grants. Do not duplicate password hashes in the civic database or import the UI branch's custom password/session implementation.

On first verified login, provision exactly one application user using the trusted `(issuer, subject)` pair and grant citizen access only. Use a uniqueness constraint/upsert to handle concurrent first logins. Existing `auth_subject` assumptions need an explicit compatible migration to issuer-aware identity mapping. Do not allow a newly provisioned citizen to resurrect a disabled application account.

If Keycloak brokers Google, the API trusts and verifies Keycloak-issued API access tokens; Google credentials terminate at the broker. Do not casually accept Google ID tokens as interchangeable API access tokens. Define API audience, issuer, algorithms, expiry, and claim requirements explicitly and test them against actual provider tokens.

### 6.3 Google configuration

- Register OAuth client configuration, consent information, authorised origins, and exact redirect URIs for local and deployed environments.
- Use minimum identity scopes: OpenID, email, and profile. Do not request Drive/Gmail permissions.
- Store client secrets only in server/identity configuration; do not place secrets in frontend `VITE_` variables.
- Validate callback state/nonce and use the chosen flow's PKCE/CSRF protections.
- Identify accounts with provider subject identifiers, not mutable email addresses.
- Require proof of control of both accounts/sign-in methods for linking. Never merge complaint ownership solely because email strings match.
- Handle Google cancellation, unverified or unavailable email, revoked access, duplicate-link attempts, and provider outages.
- Google sign-in needs internet and configured OAuth credentials. Ordinary local registration/login must remain usable when Google is not configured; hide/disable that option with a clear explanation.
- Friends can use a correctly configured shared development OAuth client where its origins/redirects permit it, or their own client. Do not claim every hostname/IP works automatically. Test consent/test-user restrictions before the team trial.

### 6.4 Sessions and account lifecycle

Prefer a same-origin backend-for-frontend session boundary: HttpOnly cookies, Secure in deployment, explicit SameSite policy, server-side session state, CSRF protection on mutations, and defined expiry/rotation/revocation. The backend validates identity-service tokens and retains database permission checks. Extending current bearer-only endpoints requires an explicit auth/contract design and tests; cookie sessions must not weaken CSRF protection.

Do not put production bearer/refresh tokens in localStorage, photo URLs, logs, or analytics. A later native client can use a documented bearer-token flow with platform secure storage and external-browser PKCE.

Account disablement must block app access immediately through the app's database checks. Logout-all must invalidate app sessions as well as the identity-service session. Password/email changes and provider linking require recent authentication. Local email verification/reset can use a Docker development mailbox; deployed email requires real SMTP/provider configuration.

An account deletion request is not a blanket cascading delete of reports, issues, or repair history. Specify staged deactivation, identity unlinking/deletion, profile anonymisation where appropriate, retention exceptions, and backup handling. Make retries safe across the app and identity service.

### 6.5 Administrator account and complaint management

V2 must include an administrator sign-in and dashboard, using Chaitanya's administrator-review interface as a presentation reference while retaining main's stronger permission and work-lifecycle rules. The reviewed UI branch supports administrator review/status/priority changes; a complaint-delete endpoint was not present in the inspected backend. Deletion is an explicit new V2 capability, not assumed existing functionality.

- Provision the first application administrator through an explicit local setup command or deployment bootstrap using a verified identity. Keep identity-service administration distinct from application administration. Do not ship a public default password or let ordinary registration/Google sign-in choose the admin role.
- Persist the administrator account and grants across normal Docker restarts and updates. Provide password/access recovery and require stronger authentication for deployed privileged accounts.
- Provide a searchable, paginated complaint dashboard with category, area, date, processing state, issue status, priority, and deleted-record filters; show complete backlog counts.
- Allow authorised administrators to inspect complaint evidence/history, review category/location, accept or reject with a reason, handle duplicate linking/merge/split, document priority changes, assign operators, and oversee repair verification/archive/reopen.
- Preserve valid state transitions, evidence requirements, area permissions, and independent repair verification. Administrator status must not permit verifying the administrator's own repair submission.
- Include citizen/staff account lookup, account suspension/reactivation, and controlled role/area grant management with an audit trail. Access does not permit viewing citizen passwords or provider secrets.

**Complaint deletion:** provide a clearly labelled Delete complaint action with a required reason and confirmation identifying the complaint and its linked issue impact. Default to reversible soft deletion using `deleted_at`, `deleted_by`, and `deletion_reason`, with an admin-only deleted-record view and Restore action. This is distinct from rejecting a report, archiving a resolved issue, or deleting a citizen account.

- Remove deleted complaints from ordinary lists, search, citizen-facing detail/media access, and report-derived counts. Show the submitting citizen a minimal unavailable/deleted receipt where appropriate without exposing moderation notes.
- Retain restricted evidence/history for restoration according to the configured retention policy. If retained evidence must be purged, expose a separate permanent-deletion workflow with elevated permission, recent authentication, explicit confirmation, and a documented retention check.
- Permanent deletion must reconcile private originals/derivatives, report fields, validation artifacts, and future provider caches. Keep a minimal audit tombstone without the purged complaint content, and document backup expiry and restore-time reapplication of deletion records.
- Do not cascade-delete the shared physical issue or other citizens' reports. Transactionally end/restore the report's active contribution, update issue counts and eligible reporters, queue priority recomputation, and handle a zero-support issue through a documented state/review rule.
- Prevent pending/retried worker jobs and old provider results from processing or resurrecting deleted complaints. Invalidate stale queue captures and caches as needed. Restore must recheck current category, location, issue linkage, and permissions rather than blindly replaying obsolete state.
- Enforce deletion, restore, and purge permissions on the backend, including area scope; hiding buttons is not authorisation. Use expected revisions and idempotent action IDs for concurrent/retried moderation.
- Audit review, delete, restore, purge, account suspension, and grant changes with actor, target, timestamp, reason, and outcome. Bulk deletion is outside the first release unless separately designed and tested.

## 7. Docker portability and data persistence

### 7.1 Services to package

- `web`: frontend build and gateway, routing same-origin `/api` requests.
- `api`: FastAPI using internal service addresses.
- `worker`: validation/review admission and priority processing, using the same reviewed application image where practical.
- `db`: PostgreSQL/PostGIS with an application data volume.
- `identity`: Keycloak with persisted identity database/configuration if the proposed default is adopted.
- `migrate`: one-shot controlled application migration service.
- `bootstrap`: idempotent initial configuration/provisioning, separate from destructive reset and never overwriting reviewed settings.
- Optional development mailbox and explicit demo/test profiles.
- Future model inference service/profile only when weights and acceptance criteria exist.

For local portability, the identity database may share the PostgreSQL server using a separate database and restricted owner; do not share application tables or credentials. Persist identity data in the database volume and back it up separately. Evaluate isolation needs for deployment.

### 7.2 Volumes and startup rules

- Use a stable V2 Compose project name distinct from V1.
- Persist application/identity databases and private media in named volumes; API and worker share the appropriate media volume locally.
- Use storage adapters so deployed multi-host installations can use private object storage without changing domain rules.
- Run migrations once after database health, then bootstrap, then dependent services. Handle startup ordering and dependency failure explicitly.
- Never recreate schema, drop tables, or reseed over existing users/reports during normal startup.
- Exclude model weights, private files, `.env`, development databases, and caches from image build contexts.
- Use lockfiles and pinned release image versions/digests. Provide non-root runtime images where supported and separate development/release targets.
- CPU-only operation is the default. No GPU, model download, or Gemini key is required for the initial build.
- Support Windows Docker Desktop/Linux containers, macOS Docker Desktop, and Linux Docker Engine/Compose. Check architecture support of the exact PostGIS/identity images before claiming ARM64 support; document any tested emulation path.
- Configure browser-visible identity URLs and container-internal networking correctly. Do not use `localhost` inside a container to refer to a different service. Validate issuer/JWKS hostnames against tokens on each supported setup.

### 7.3 Intended friend onboarding contract

The implementation should eventually provide this workflow (commands below are targets, not working commands provided by this planning-only folder):

1. Install Docker with Compose and obtain the V2 source bundle.
2. Copy `.env.example` to `.env`; a setup helper generates local secrets without committing them.
3. Run `docker compose up --build -d`.
4. Open the documented local URL and register a citizen account.
5. Access verification/reset emails in the local development mailbox.
6. Enable Google sign-in only after supplying the OAuth settings.
7. Stop with `docker compose stop`, then start again and see the same accounts/reports/photos.

Provide PowerShell and POSIX setup/health/backup helpers, port-conflict instructions, version prerequisites, tested resource requirements, and troubleshooting for Docker not running. Local demo data must be labelled and opt-in; no automatic shared citizen login.

Normal `docker compose down` preserves declared named volumes. `docker compose down -v` removes them and must be documented as destructive, never used by normal setup/update scripts. A reset helper, if added, must identify the exact V2 target and require a deliberate typed confirmation. Named volumes provide persistence, not backups.

## 8. Validation now and future YOLOv8n/Gemini

### 8.1 Initial V2 behaviour & Validation Mismatch Rule

Keep the existing human-review path and evidence/category/location rules. Ordinary submitted photos await reviewer decisions; synthetic fixtures remain restricted to isolated demo/test use. Do not return fabricated model results, label complaints AI-verified, or require model/API credentials.

**Suspicious Mismatch Flagging Rule:**
When the vision validation model runs (or in automated triage):
- If the model's detected category contradicts the citizen's claimed category (e.g. citizen claimed `pothole` but detector found `garbage_accumulation` or `unknown`), the report MUST be flagged as **suspicious** (`is_suspicious = true`, `suspicious_reason = "Model detection mismatch: claimed '{claimed}' but detector predicted '{detected}'"`).
- Suspicious complaints are assigned an `awaiting_review` status with an elevated triage priority and prominently badged in the administrative overview and detail views with a warning icon (`⚠️ Suspicious Mismatch`) so supervisors audit them before any admission to a physical repair issue.
- If the model returns no detections or low confidence on an image that the citizen claimed was a critical hazard, it is likewise flagged for manual audit.

UI states must distinguish saved, awaiting review, admitted to an issue, rejected, out of scope, processing failure, suspicious mismatch, and linked repair status.

### 8.2 Future provider pipeline

1. Persist validated photo bytes and report metadata first.
2. Enqueue a revision-aware validation job with media ID/hash.
3. If configured and available, run the vision model (YOLOv8n / fine-tuned detector).
4. Apply calibrated rules for supported categories, confidence, image quality, and ambiguity.
5. If the detector disagrees with the claimed category, trigger the **Suspicious Mismatch Flag**.
6. Invoke Gemini for configured fallback or verification cases: unavailable/failed detector, unsupported or uncertain category, ambiguous findings, or a sampled quality check. Do not send every image twice by default.
7. Route provider disagreement, suspicious mismatch, malformed output, low confidence, no detection, quota exhaustion, timeout, or unavailable providers to human review.
8. Commit only results matching current report revision and evidence hash.

Initially even agreement remains reviewer assistance; automatic acceptance requires a separately approved, measured policy. No provider may autonomously resolve an issue, assign staff, change permissions, or infer physical severity/repair priority from confidence alone.

### 8.3 Future contracts, controls, and evaluation

- Store provider/model version, model checksum, prompt/schema version, evidence binding, canonical image dimensions, bounding boxes, class mapping, confidence where meaningful, timestamps, outcome, and human disposition.
- YOLOv8n weights must have their own evaluation; YOLO11n metadata is not transferable evidence.
- Standardise overlays against the orientation-corrected display coordinate system. Validate box bounds and dimensions server-side.
- Configure Gemini model ID rather than pinning an unverified future availability/pricing assumption now.
- Use server-side credentials, structured output and strict semantic/schema validation, bounded retries/timeouts, daily budgets, concurrency limits, and a circuit breaker.
- Treat photo text, descriptions, and model output as untrusted data. Images cannot instruct Gemini to change application policy or execute actions; no tools/actions are exposed in this verification task.
- Send only the minimum metadata-free image and necessary category context to Gemini. Provide an external-processing notice and review provider retention/data terms before enabling real evidence processing.
- Cache/deduplicate by evidence hash, provider/model/prompt version, and relevant context. Keep comparison histories without overwriting original evidence.
- Evaluate negative/unrelated images, hard negatives, night/rain, blur, rotation, false positives/negatives, unsupported categories, latency on CPU, cost, fallback frequency, provider agreement, and reviewer usefulness.
- Check weights, dataset, inference dependency, and distribution licensing before packaging the future model.

## 9. UI, maps, categories, and metrics

- Port the UI design into reusable typed components rather than retaining the approximately 79 KB `main.jsx` monolith.
- Preserve citizen, reviewer, operator, and administrator screens, not just the citizen dashboard.
- Retain generated API types, React Router, query caching, controlled forms, structured field errors, and request IDs.
- Build responsive navigation, keyboard/focus handling, touch-friendly controls, explicit empty/error/loading states, and realistic session-expiry recovery.
- Separate report count from physical issue count and verified repair count. Define scope, denominator, time range, and freshness for every metric.
- Keep citizen data private by default. A shared map returns a minimal reviewed issue projection, not other citizens' descriptions/photos or staff-only assignment data.
- Preserve main's categories. Add waterlogging only with explicit enum, database, policy, label, contract, UI, and test changes; it is distinct from sewage overflow. Do not import the UI's `both` category without a multi-category design.
- Replace both citizen PinMap and staff QueueMap with shared Leaflet components.
- Keep pilot boundaries, confirmed pins, GPS uncertainty, accessible numeric entry, map/list selection, queue numbering, and map failure fallback.
- Centralise Leaflet `[lat, lng]` versus GeoJSON `[lng, lat]` conversion and test round trips.
- Make viewport search explicit or carefully debounced to avoid fit/pan/refetch loops. Label loaded-page markers versus all matching results.
- Reset pin confirmation after movement and handle geolocation denial/timeouts. User-confirmed location is not independent proof that a photo was captured there.
- Configure tile URL, attribution, and provider capacity. Leaflet is a map library, not a bundled tile/geocoding service.
- Honour OSM tile policy if using public tiles; do not add offline tile prefetching. Public Nominatim is unsuitable for autocomplete. Choose a compatible provider if autocomplete is required.
- Show actual refresh/connection state. Do not display Live without an established realtime channel. Polling, if used initially, is labelled and backs off while offline/hidden.

## 10. Defects and risks to address

### 10.1 Confirmed source behaviour in the UI branch

- Automatic hardcoded shared-citizen login attempt: remove.
- `Live` set without a working realtime subscription: replace with measured status.
- Photo URLs hardcode `127.0.0.1:8001` and include bearer tokens: replace with same-origin authorised media retrieval.
- `/complaints` receives date filters but does not apply them: implement filters and test timezone boundaries.
- `/complaints` lacks the bounded limit/offset checks used by `/reports`: enforce bounded pagination.
- Nearby duplicate linking does not filter category: preserve main's conservative duplicate decisions.
- Direct administrator status changes bypass independent repair verification: preserve main's work state machine.
- Public `/dev/detect` exposes expensive inference: exclude development inference routes from production.
- Documentation describes Supabase behaviour that diverges from runtime SQLite: rewrite operational documentation.

### 10.2 Confirmed main limitations and deployment gaps

- API and worker explicitly reject production startup. Replace these gates only after production dependencies and acceptance checks exist.
- Worker always prioritises validation before admission before priority refresh. Add fairness/separate capacity and per-queue age monitoring.
- Validation jobs use fixed 30-second leases without renewal around provider work. Add deadlines, renewal/fencing, and slow-provider tests before future AI integration.
- Operator, reviewer, duplicate, and rapid-review queues have fixed caps without continuation. Add cursors/counts and apply scope filtering before pagination.
- Citizen nearby queries reuse a broad staff summary containing internal assignment/priority fields. Introduce a citizen-safe contract.
- Main lacks public account self-service and production identity provisioning: implement Section 6.
- Current storage/maintenance assumptions are local. Support production private media and safe scheduled cleanup.
- Public abuse controls, production deployment packaging, real boundary/POI/policy review, and realistic provider/photo load measurements remain incomplete.

### 10.3 Hypotheses requiring reproduction/decisions

- Upload persistence deletes written files on any exception. An uncertain database commit acknowledgement could leave a committed media row pointing at deleted files. Inject this failure and reconcile before deleting uncertain objects.
- Account-count scoring and exact-file-hash evidence checks are not sufficient anti-abuse controls. Re-encoded photos and multiple accounts need moderation-aware detection; perceptual similarity is advisory, not automatic rejection.
- Critical overrides remain flagged after the review deadline rather than automatically expiring. Define escalation and review ownership; do not silently downgrade potential hazards.
- Review multi-request permission changes, session invalidation, concurrent staff decisions, and cross-area transitions under real authentication and load.

## 11. Database changes and migration strategy

- Preserve existing report/issue IDs, ownership, history, and media mappings.
- Add issuer-aware identity mapping and profile/settings fields through additive migrations with unique constraints and indexes.
- If using backend sessions, persist only appropriately protected session identifiers/state and lifecycle metadata, with expiry and revocation.
- Plan account-deactivation/deletion-request records and idempotent identity-provider synchronisation.
- Add complaint soft-deletion metadata, moderation audit events, and minimal permanent-deletion tombstones through additive migrations. Update report/media access checks, issue contributions, queue queries, counts, and worker eligibility consistently.
- Add pagination indexes, operational job metadata, and future provider-result fields only where required.
- Avoid storing provider secrets in public configuration or ordinary API responses.
- Keep image bytes outside relational tables and use stable private storage references.
- Separate migration privileges from runtime application privileges. The runtime user must not create/drop databases.
- Run migrations in a controlled service, verify compatible schema version at readiness, and test upgrade from a V1 database copy.
- Bootstrap real configuration without importing synthetic users, POIs, or boundaries as official data.
- Do not transfer the UI branch's SQLite records without an explicit identity/category/status/media mapping and reconciliation. Fresh independent V2 development data is the default; any real-data import is a separate reviewed task.
- Back up and rehearse restoration before migrating meaningful data. Prefer backward-compatible changes and a clear application rollback window; destructive schema changes need a separate migration plan.

## 12. Delivery phases and acceptance criteria

### Phase 0 — Baseline and decisions

Deliver source/route/permission inventories, recorded baseline checks, category decisions, identity/session architecture decision, persistence policy, and screen-to-API mapping.

Acceptance: every main capability has an owner in the V2 plan; original checkout/data are preserved; no direct destructive branch merge is used.

### Phase 1 — Reproducible Docker foundation

Package web, API, worker, PostGIS, migration/bootstrap, and identity/development email services as applicable. Establish safe defaults, persistent volumes, health checks, local setup helpers, and an opt-in synthetic demo.

Acceptance: a friend starts the complete stack without host Python/Node/PostgreSQL; creates an account; submits a report; restarts/rebuilds normally; sees the same account, report, and photo. No model/API key is needed.

### Phase 2 — Backend reliability, Prioritisation Weights and API contracts

Fix fair job processing, bounded provider execution, citizen projection, pagination, filter/count consistency, uncertain-upload cleanup, error contracts, and operational visibility. Keep database state machines and idempotency.

**Prioritisation & Traffic Heavy Zone Weighting:**
- Incorporate default weights for traffic-heavy corridors (proximity to major arterial roads, bus stops, school/hospital zones).
- Assign higher weightage multipliers to high-congestion bottleneck zones in Bengaluru:
  - `south_central` (Silk Board / Madiwala junction): 1.25x priority multiplier.
  - `north_central` (Koramangala 4th/5th Block commercial hub): 1.15x multiplier.
  - `northeast` (Sony World / Ejipura / Inner Ring Road transit): 1.15x multiplier.
  - `southeast` (HSR Layout / Bellandur corridor): 1.15x multiplier.
  - Standard/residential zones: 1.0x baseline weight.
- Multiply the composite score by the zone traffic weight (capped at 100) and append the explainable `traffic_heavy_zone_boost` flag in scoring snapshots.

Acceptance: all queues are reachable beyond 50 items; sustained validation does not indefinitely delay admission/scoring; retries preserve one outcome; traffic-heavy Bangalore zones rank higher than equivalent residential issues; permission tests pass.

### Phase 3 — Account self-service and Google

Implement registration, verification, recovery, Google federation, safe first-login provisioning/linking, account profile screens, session management, explicit first-admin/staff provisioning, and account deletion/deactivation workflow. Define backend admin permissions and audited complaint delete/restore/permanent-deletion actions from Section 6.5.

Acceptance: two independent citizens cannot access each other's private reports; returning users retain cross-device ownership; Google and local login resolve correctly without accidental duplicate/link takeover; disabled accounts lose access; recovery works in the local mailbox and configured deployment email service.

### Phase 4 — UI and Leaflet integration

Port the visual design to typed components; adapt all citizen/staff/workflow screens; implement the administrator complaint-management dashboard, review actions, deletion confirmation, deleted-record view, and restore controls; replace both maps; add truthful metrics and connection status; preserve form drafts and concurrency errors.

Acceptance: existing end-to-end workflows remain available; administrator review/delete/restore works with correct permissions and linked-issue counts; map/list/filter results agree; browser back/deep links, mobile layouts, keyboard controls, GPS failure, and tile outages work.

### Phase 5 — Production services and data integrity

Configure reviewed non-synthetic pilot data, private durable storage, scheduled reconciliation/cleanup, request/upload quotas, safe logging, HTTPS, secret management, backups, restore, and rollback.

Acceptance: fresh production-mode staging starts with real identity and human review, rejects demo identities/fixture validation, preserves evidence across instance recreation, and restores database/identity/media together. Do not launch by changing production to demo mode.

### Phase 6 — Release verification

Run the complete checks in Section 13, realistic load/failure tests, cross-platform friend onboarding, and a small reviewer/operator acceptance exercise.

Acceptance: no unresolved high-impact access-control/data-loss defects; all mandatory journeys pass; measured limits and known issues are documented; rollback/restore has been rehearsed.

### Phase 7 — Optional future YOLOv8n/Gemini

Implement Section 8 only after weights, evaluation data, provider credentials, cost/privacy decisions, and acceptance thresholds are available.

Acceptance: inference is asynchronous, bounded, evidence-bound, measured, and safely falls back to human review. This phase is not a dependency of the initial V2 launch.

### Phase 8 — PWA and later app

Add installability and selective public-shell caching after the web release is stable. Evaluate native packaging against camera/location/background-upload/notification requirements. Reuse API/domain contracts; do not assume browser Leaflet components run unchanged in a native UI.

Acceptance: private responses/evidence are not unintentionally cached; offline drafts are clearly unsent until acknowledged; retry identifiers prevent duplicate submissions; native sign-in uses external-browser PKCE and platform secure storage.

## 13. Verification matrix

### Accounts and privacy

- Concurrent first logins, duplicate identities, safe Google linking, wrong issuer/audience, expired tokens, key rotation, callback tampering, cancellation, logout-all, disabled accounts, and revoked grants.
- Registration cannot request reviewer/operator/admin access.
- Password recovery, email changes, last-method unlinking, stale sessions, and partial deletion workflows.
- Foreign report/photo IDs, cross-area access, citizen-safe nearby fields, session/cache clearing, and sensitive log/URL checks.
- First-admin setup cannot be invoked by an ordinary citizen; no public default admin credentials; role changes and account suspension are audited and enforced server-side.

### Database and persistence

- Restart, rebuild, ordinary Compose down/up, migration upgrade, volume/project naming, and stable identity subjects.
- Database/media/identity backup and restoration into an isolated target; validate ownership, hashes, links, and history.
- Disposable test databases cannot target application databases. Runtime accounts cannot create/drop databases.
- Cleanup retains attached evidence and respects report submission/repair attachment races.
- Inject commit-acknowledgement failure and storage failure before/after persistence.

### Workflow and concurrency

- Submission retry after lost response, expired uploads, concurrent photo attachment, and same-key/different-body conflicts.
- Category/location review, out-of-scope handling, duplicate/new decisions, cross-area candidates, merge/split, assignment, repair rejection/verification, archive/reopen.
- Two reviewers acting simultaneously, old versions, duplicate jobs, killed workers, slow providers, lease loss, backlog fairness, and failed-job replay.
- Scoring after policy/category/merge/split changes; burst/reuse safeguards; stale/unknown-context display.
- Admin delete/restore/purge permissions, required reasons, revision conflicts, repeated requests, restricted evidence access, shared-issue preservation, zero-support issues, counts/priority refresh, pending-job cancellation, restore revalidation, and deletion records after backup restoration.

### Frontend and geography

- All defined date/search/status filters, counts, cursors, deleted/expired browsing context, and direct links.
- Latitude/longitude conversion, borders/gaps, uncertain GPS, moving pins, changing categories, and outside-pilot locations.
- Mobile browsers, realistic camera photos, unsupported formats, corrupt bytes, decompression limits, rotation, keyboard navigation, screen-reader labels, focus/contrast, and reduced motion.
- Map failure, identity outage, API outage, interrupted uploads, session expiry, and draft recovery.

### Build, operations, and future providers

- Python tests/lint/type checks, TypeScript/contracts, frontend tests/build, browser journeys, Compose validation, migration tests, dependency/image/secret checks.
- Realistic image sizes, growing datasets, concurrent users, API/worker scaling, queue latency, stale-score recovery, CPU/memory/storage usage, and external-provider delays.
- Google configuration tested separately from credential-free local startup.
- Future YOLO/Gemini schema failures, prompt injection attempts, rate/quota limits, image orientation, no detections, provider disagreement, and model version/hash mismatch.

Historical V1 tests/load results must not be presented as fresh V2 results. Agree target user/report/photo volume, response-time objectives, maximum acceptable queue delay, recovery time, and recovery-point objective before load acceptance. Publish measured hardware, dataset, image sizes, and remaining limits.

## 14. Deployment and operational requirements

- Separate local, test, staging, and production modes with isolated databases/storage and secrets.
- HTTPS gateway, exact allowed origins/redirects, correct proxy headers, CSRF controls for cookie auth, security headers, and bounded request bodies.
- Structured request/job IDs, sanitised error reporting, no bearer tokens/private photo content in logs, and restricted staff operational endpoints.
- Monitor API errors, queue oldest age by type, worker heartbeat, failed jobs, scoring staleness, storage/identity health, database connections, disk space, and future Gemini spend.
- Back up application DB, identity DB, media, and required versioned configuration; store backups away from the host and test restoration.
- Protect staff accounts, audit grant changes, and verify independent repair verification.
- Limit upload frequency/storage and expensive provider work per account and at the service boundary. A Redis-backed distributed limiter is an option when needed, not a required new job queue.
- Document maintenance, emergency disablement of providers, account recovery, secret rotation, rollback, and who responds to incidents.
- Retain manual review and honest service scope; do not imply official municipal integration or approved ward coverage without the corresponding agreement/data review.

## 15. Definition of the first deployable V2

- Complete main workflows retained beneath the improved interface.
- Citizen self-registration/account management and configured Google sign-in.
- Persisted administrator account and complete complaint review/moderation dashboard, including audited delete/restore and controlled permanent deletion, without bypassing repair verification or affecting other citizens' reports.
- Docker startup tested on team systems with persistent databases and photos.
- Leaflet street maps and reliable list/coordinate fallback.
- Human-review validation works without model weights or Gemini credentials.
- Pagination, queue fairness, citizen data projection, safe media access, idempotency, and concurrency controls verified.
- Reviewed production configuration, startup path, private storage, quotas, monitoring, restore, and rollback.
- Documented privacy/retention/account-deletion behaviour and operational ownership.
- Future YOLOv8n/Gemini adapters have a documented contract, but their implementation is optional/deferred.
- No GitHub push, deployment, destructive reset, or real-data import is implicit in completion of this document.

## 16. Official references and source evidence

Reviewed 26 October 2026. Provider details/versions should be rechecked at implementation time.

- [Branch comparison](https://github.com/chaitanya-mehrotra/NAGARSAATHI/compare/07c3d40ce05e25279d77b5b4414a1b64153e89e2...a07610eebfbc406fabcac09ec5734622c8e79046)
- Local source evidence: `../Civic AI/nagarsaathi/compose.yaml`, `scripts/maintenance.py`, `services/api/tests/integration/conftest.py`, `services/api/app/auth.py`, `services/api/app/main.py`, `services/api/app/routes/intake.py`, `services/api/app/jobs.py`, and `services/api/app/routes/issues.py`.
- [Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect)
- [Google server-side ID-token verification](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token)
- [Keycloak container deployment](https://www.keycloak.org/server/containers)
- [Keycloak administration: registration, recovery, and identity providers](https://www.keycloak.org/docs/latest/server_admin/index.html)
- [Docker Compose down and volume removal](https://docs.docker.com/reference/cli/docker/compose/down/)
- [Docker volumes](https://docs.docker.com/engine/storage/volumes/)
- [Gemini image understanding](https://ai.google.dev/gemini-api/docs/image-understanding)
- [Gemini structured output](https://ai.google.dev/gemini-api/docs/structured-output)
- [Leaflet](https://leafletjs.com/)
- [React Leaflet lifecycle and mutable properties](https://react-leaflet.js.org/docs/start-introduction/)
- [OSM tile policy](https://operations.osmfoundation.org/policies/tiles/)
- [Nominatim public API policy](https://operations.osmfoundation.org/policies/nominatim/)
- [OAuth for native apps, RFC 8252](https://www.rfc-editor.org/info/rfc8252/)
