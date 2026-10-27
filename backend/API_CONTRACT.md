# Automated processing API contract — Person 2 handoff

Baseline: `TEAM_TASKS_AND_PROMPTS.md`, authorized by the user on 26 October 2026. Frontend integration is complete on Collection-27-10. API paths below are relative to the configured base; development uses port 8002, bundled Docker uses `/api`. See [COLLECTION_27_10.md](../COLLECTION_27_10.md) for archive, assignment, repair evidence and optional Google endpoints.

This supersedes old startup guides that describe inline YOLO and citizen photo previews. Person 2 must remove the old Check Photo/model widgets; the server denies citizen access regardless of whether those widgets remain visible.

## Authentication and roles

Existing `/auth/register`, `/auth/login`, `/auth/me`, `/auth/logout` remain. Public registration creates citizens only. Staff roles returned by the API are `admin` and `nigam`. Use `Authorization: Bearer <session>` for browser API calls. Worker credentials are separate and must never enter the browser bundle or localStorage.

## Citizen contract

`POST /reports`: existing multipart `image`, `description`, `latitude`, `longitude`, `issue_type` (`pothole`, `waterlogging`, `both`). `Idempotency-Key` provides replay protection per account. Returns HTTP 201 after durable photo/report/job storage, with no inference call. Duplicate retries return the same report ID; changed content with the same key returns 409.

`GET /reports/{id}` and existing `/complaints/{id}` return the same citizen-visible shape. `GET /reports` lists own reports; `/complaints` keeps `{items,total}` pagination. Citizen responses are a server-side allowlist:

```json
{
  "id": 21,
  "reference": "NS-00000021",
  "description": "Road defect at the junction",
  "latitude": 12.97,
  "longitude": 77.59,
  "created_at": 1792990000,
  "issue_type": "pothole",
  "status": "open",
  "verification_status": "pending",
  "verification_reason": "Awaiting processing",
  "photo_url": "/reports/21/photo"
}
```

There is no `analysis`, confidence, bounding box, worker state, priority, duplicate candidate list, issue count or reporter identity in a citizen response. Poll report details every few seconds while pending; stop/back off when the screen is hidden or requests fail. Time values are Unix seconds.

Verification states: `pending`, `supported`, `needs_review`, `not_supported`. Supported means visual evidence, not proved authenticity. Missing detections, category disagreement, weak evidence or ambiguous grouping result in `needs_review`, never an automatic fake/rejected decision. `not_supported` is an audited admin review outcome with a safe explanation and follow-up path.

Repair states: `open`, `in_progress`, `resolved`, `rejected`. These are distinct from verification. Display them separately. A resolved issue's status propagates to every linked report without the citizen needing to know grouping details.

`POST /dev/detect` now returns 403 to citizens and 410 to admins: inline inference is removed, not moved into browser JavaScript.

## Platform-admin contract

Existing report endpoints return all submissions for `admin`, including stored `analysis`, `analysis_status`, `issue_id`, `grouping_reason`, `issue_summary`, `duplicate_candidates`, and `processing` (`state`, `attempts`, `error_code`, `updated_at`). No lease tokens or worker keys are returned.

Processing state is `queued`, `processing`, `completed` or `failed`. Historical records can retain old analysis states until explicitly retried/reviewed; do not assume every old record has a job.

- `GET /processing/health`: queue counts, worker heartbeats, worker_online, expired lease count and oldest wait. Worker online expires after 180 seconds.
- `GET /processing/exceptions?limit=40&offset=0`: `{items,total}` for needs-review reports, with admin detail.
- `POST /processing/reports/{id}/retry`: queue failed/completed processing again; 409 if already queued/processing or closed. Creates a new job identity so stale deliveries cannot affect a new attempt.
- `PATCH /processing/reports/{id}/review`: `{ "verification_status":"supported|not_supported|needs_review", "reason":"required" }`. Audited review; pending worker results cannot overwrite it.
- Existing `PATCH /issues/report/{id}/group`: `{ "issue_id":123, "reason":"required" }`; null separates. Pending processing cannot be regrouped. Counts/priority recompute. These are exception controls, not normal per-report steps.
- Existing `PATCH /issues/{id}/publication`: `{ "published":false }` explicitly withholds an issue from auto publication. Publishing requires supporting evidence. An explicit manual withholding is not undone by new reports.

Old `PATCH /reports/{id}` now accepts `{ "status":"...", "note":"required" }` as an admin compatibility route for issue-level status. It no longer sets manual priority. Prefer the issue-level endpoint below.

## Consolidated issues — admin and Nagar Nigam

`GET /issues?sort=priority&limit=40&offset=0`: `{items,total}`. Default sort is priority descending, then oldest issue, then ID. Use `sort=priority` in the new UI rather than the old `newest` default. `sort=newest|oldest` are optional explicit alternatives. Default list excludes closed issues; `status=resolved` retrieves resolved issues. Search/category filters and pagination remain.

Admin can inspect all active consolidated issues. Nigam sees only published ones. Pending/ambiguous reports never independently appear in the Nigam queue. `GET /issues/{id}` and `/issues/{id}/photo` enforce the same roles/publication checks.

```json
{
  "id": 7,
  "issue_type": "pothole",
  "latitude": 12.97,
  "longitude": 77.59,
  "status": "open",
  "published": true,
  "report_count": 10,
  "reporter_count": 8,
  "unique_photo_count": 4,
  "priority_score": 56.0,
  "priority_reason": "Illustrative demand/age explanation; use the returned text",
  "priority_policy_version": "demand-age-v1",
  "description": "Representative road complaint",
  "photo_url": "/issues/7/photo"
}
```

Example is abbreviated; returned fields can also include dates and publication mode. No individual reporter identities or raw citizen report list are included. Counts are account-based, not a guarantee of unique humans.

Priority v1: `70 * min(supported_distinct_accounts/10,1) + 30 * min(waiting_days/7,1)`, rounded to two decimals. No confidence/depth/traffic/hospital assumptions. Computed by backend, refreshed when memberships/status change and on reads so age does not require a running PC. Closed issues have score 0.

`PATCH /issues/{id}/status`:

```json
{ "status":"in_progress", "note":"Repair team assigned" }
```

Nigam can update published issues to open/in_progress/resolved. Admin also can reject with a reason; evidence rejection is not a Nigam permission. Updates are transactional and visible through every linked citizen report. `GET /issues/{id}/history` returns audit events; Nigam receives repair events only. Parse `details` as JSON if rendering structured history.

`GET /metrics`: authenticated and role-scoped. Admin/citizen totals count reports; Nigam totals count published issues. `unit` identifies the count type. `issue_count` excludes unconsolidated pending reports. Repair-status counts are available.

## Worker interface — never call from frontend

`X-Worker-Key` authenticates against the API's configured SHA-256 fingerprint. Job input additionally requires `X-Lease-Token`. Tokens belong only on the PC/server, never in URL query strings or frontend fixtures.

- `POST /worker/jobs/claim` with `{worker_id}` -> `{job:null}` or scoped job/input/candidate metadata plus lease token.
- `POST /worker/jobs/{id}/heartbeat` with `{lease_token}` -> extends live lease.
- `GET /worker/jobs/{id}/input` and `/candidates/{report_id}` -> leased photos only.
- `POST /worker/jobs/{id}/result` -> validated model/photo/dimensions/boxes/candidate evidence; same result is idempotent, mismatched/stale results are 409.
- `POST /worker/jobs/{id}/failure` -> retry with bounded backoff, then admin exception queue.

## Person 2 integration checklist

1. Remove citizen preview request/model fields; post report without waiting for analysis.
2. Poll the simple tracking response and show both verification and repair statuses.
3. Use role-specific report versus issue list endpoints. Never fetch worker routes from browser code.
4. Set Nigam sort to `priority` and display backend reason/counts, not a JavaScript-derived rank.
5. Add Nigam repair controls using `/issues/{id}/status` and its required note.
6. Add admin health/exceptions and optional review/group corrections; no mandatory manual ranking or forwarding in the normal path.
7. Handle 401/403/404/409 and API failures without exposing raw model/worker errors to citizens.
