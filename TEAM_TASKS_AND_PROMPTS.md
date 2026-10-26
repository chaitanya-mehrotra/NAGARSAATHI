# NAGARSAATHI: two-person work split and prompts

Latest requirements, 26 October 2026. This document supersedes the earlier deferral of automatic priority. It assigns implementation work; the complete automated pipeline is not already built.

## Shared objective

Citizen submits a photo, description and location, then tracks verification and resolution. There is no citizen photo-check step, model output, duplicate grouping or priority control. The phone does not run inference.

An online API saves each report and queues work. A worker on the admin PC automatically runs the combined YOLO11n model, assesses supporting visual evidence, groups reports describing the same physical issue, maintains counts, calculates an explainable priority and exposes eligible consolidated issues to Nagar Nigam. Uncertain cases stay visible to the platform administrator. Nagar Nigam sees consolidated issues and updates repair progress; updates reach all linked citizens.

One hundred submissions do not necessarily mean twenty issues. Twenty is the desired example when they actually describe twenty physical problems; grouping must not force a target number.

## Before either person starts

1. Publish a common baseline containing the latest local grouping changes and these documents. They are currently local changes; the previously pushed branch alone is not this entire baseline.
2. Both people clone/pull that same baseline commit from `https://github.com/chaitanya-mehrotra/NAGARSAATHI`.
3. Continue Chaitanya's UI. Do not switch to Saish's interface or change its separate branch.
4. Create separate branches: `feature/automated-processing` and `feature/role-workflows`.
5. Agree on the proposed API contract below before either person builds against it. Backend owner publishes sample responses; frontend owner can work from those fixtures.
6. Keep model weights in the agreed baseline/package. Do not share `.env`, passwords, session tokens, private uploaded photos, databases or virtual environments through Git.

## Person 1 — backend and admin-PC automation

Owns: `backend/`, backend tests, worker scripts, backend dependency files, backend startup configuration and processing documentation. Any changes to Docker/Compose, deployment files or environment examples belong to this person after coordinating runtime needs with Person 2.

Deliverables:

- Fast report intake without waiting for model inference; persistent job queue and retry-safe submission.
- Protected worker claim/download/heartbeat/result APIs; scoped worker credential and outbound HTTPS polling from the PC.
- A persistent PC worker loading the existing combined checkpoint once, with leases, bounded retries and restart recovery.
- Evidence-based verification states without claiming a YOLO prediction proves authenticity.
- Automatic duplicate matching from category, location, time and visual evidence. Evaluate matching thresholds on labelled same-issue/different-issue examples. Do not blindly merge all nearby reports or arbitrary perceptual-hash matches.
- Counts derived from report membership: raw submissions, distinct reporting accounts, consolidated issues and distinct photographs. Retry results must not inflate any count.
- Automatic, versioned priority policy. Use supported inputs such as distinct reporting accounts and waiting time for the first version; describe its limitations. Do not infer physical depth/danger from confidence or invent hospital/road-impact data. No manual ordering is required for the normal path.
- Automatic publication of sufficiently supported, confidently grouped issues. Hold uncertain analysis/matching for exceptions rather than silently discarding complaints or sending ambiguous duplicates as confirmed work.
- Role-safe APIs for citizen tracking, admin monitoring and Nagar Nigam repair updates. Updates to an issue's repair status reach every linked report.
- Automated acceptance tests, migration/backup procedure, worker startup instructions and documentation of which automation is measured versus provisional.

Do not edit `src/`, CSS or map components. Do not retrain/replace the combined model without separate agreement. Do not deploy paid services merely to complete local work.

## Person 2 — citizen/admin/Nagar Nigam experience

Owns: `src/`, frontend tests, UI fixtures, frontend-specific documentation, `index.html` if required. Coordinate build configuration changes with Person 1. Preserve Chaitanya's visual design.

Deliverables:

- Citizen flow: choose category, describe, upload photo, set location, submit, receive tracking number. Remove citizen Check Photo, confidence, boxes, model details, grouping controls and priority controls.
- Tracking: citizen-facing verification and repair status, understandable pending/uncertain messages, polling/loading/retry states. No local inference package or direct worker access.
- Platform-admin view: all submissions and processing/verification states, worker/job health, shared issue links, counts, automatic grouping rationale and automatic priority rationale. Manual review/correction is an exception tool, not required for every report.
- Nagar Nigam view: one row per eligible consolidated issue, report/distinct-account counts, representative evidence, location, automatic priority and repair progress controls. Never render the citizen-report inbox or reporter identities for this role.
- Role-aware sign-in/navigation and session changes with no stale data displayed from the previous account.
- Mobile layouts and end-to-end tests using the backend owner's contract/fixtures. No citizen validation request may be needed to submit a report.

Do not edit backend files or calculate authoritative counts, grouping, priority or permissions in JavaScript. Hiding a control does not replace backend access checks; report any missing checks to Person 1.

## Proposed shared contract — agree first, then freeze for the first release

All paths below are relative to the API base. Existing Docker serves them under `/api`; development uses port 8002 directly. These are the target contract, not a claim that all these endpoints exist today.

| Operation | Proposed interface |
| --- | --- |
| Submit report | `POST /reports`, multipart image/description/latitude/longitude/issue_type; `Idempotency-Key` header; return report ID and pending status promptly |
| Citizen tracking | `GET /reports/{id}`, own report only; role-filtered response with verification/repair status, no technical AI evidence |
| Reports inbox | Existing `GET /complaints` list for platform admin, with pagination and processing metadata; citizens limited to their own reports |
| Consolidated issues | `GET /issues`, admin sees all, Nagar Nigam sees eligible published issues; deterministic priority ordering and pagination |
| Issue detail/photo | `GET /issues/{id}` and `/issues/{id}/photo`, authorized role-filtered evidence |
| Repair update | `PATCH /issues/{id}/status`, authorized Nigam/admin, body containing repair status and a note; audited |
| Worker operations | Separate `/worker/...` claim/input/heartbeat/result/failure routes, worker credential only; never used by the browser |
| Processing health | Admin-only queue/worker health endpoint, route chosen and documented by Person 1 |

Use distinct state fields:

```json
{
  "id": 21,
  "verification_status": "pending",
  "status": "open"
}
```

Proposed verification states: `pending`, `supported`, `needs_review`, `not_supported`. `not_supported` means the supplied evidence was not confirmed, not that the citizen is fraudulent. It must include a safe citizen-facing explanation and allow follow-up/review. Processing failures remain pending/retryable or visibly need review, never an automatic fraud verdict.

Processing states for admin only: `queued`, `processing`, `completed`, `failed`. Repair states retain `open`, `in_progress`, `resolved` and `rejected` where appropriate; rejection requires an auditable decision, not simply zero detection boxes.

Target consolidated response excerpt:

```json
{
  "id": 7,
  "issue_type": "pothole",
  "status": "open",
  "report_count": 10,
  "reporter_count": 8,
  "unique_photo_count": 4,
  "priority_score": 56,
  "priority_reason": "Example only: contribution from distinct accounts and waiting time",
  "priority_policy_version": "v1"
}
```

The number 56 is illustrative, not a prescribed formula. Agree on the first priority policy and sample outputs, then test it. Recompute when counts/membership/status change and as waiting time increases. Leave resolved issues out of the active work queue.

## Copyable prompt for Person 1

> You are implementing NAGARSAATHI's backend and admin-PC automation. Work from the team's common baseline in the NAGARSAATHI repository on branch feature/automated-processing. First read TEAM_TASKS_AND_PROMPTS.md and inspect the actual code; older documentation describes an incomplete inline-inference prototype. Preserve existing data and the combined YOLO11n pothole/waterlogging checkpoint. Own backend/, worker scripts, backend tests and backend runtime configuration; do not edit src/ or Saish's separate UI. Agree on the shared API contract with the frontend developer before changing public responses. Implement immediate report persistence and a durable queue, protected outbound PC-worker processing, leases/retries/idempotency, role-filtered responses, evidence-based verification, evaluated automatic duplicate grouping with accurate submission/distinct-account counts, automatic explainable priority and automatic publication of confidently supported consolidated issues. Keep uncertain cases in a visible admin exception queue; no detection is not proof of fraud. Use authentic inputs for priority and document provisional thresholds. Add authorized issue-level repair status updates so all linked citizens see progress. The API must not load YOLO or wait for inference to accept a complaint. Test PC offline, worker crash/retry, same issue from multiple accounts, separate nearby issues, privacy, migration and correct counts after regrouping. Produce API examples and startup instructions for Person 2. Do not deploy paid services or claim arbitrary-angle matching is reliable without evaluation. Submit a focused pull request with tests and limitations.

## Copyable prompt for Person 2

> You are implementing NAGARSAATHI's citizen, platform-admin and Nagar Nigam workflows. Work from the same common baseline on branch feature/role-workflows. First read TEAM_TASKS_AND_PROMPTS.md and inspect the actual Chaitanya UI. Own src/, frontend tests and UI fixtures/documentation; do not edit backend/ or Saish's separate UI. Coordinate the shared API contract and sample responses with the backend developer. Preserve Chaitanya's design. Make the citizen flow upload/location/description/submit plus simple verification and repair tracking only: remove Check Photo, technical model results, confidence, boxes, duplicate controls and priority controls from citizen views. Inference must never run in the phone/browser and submission must not wait for a preview request. Build an admin monitoring screen showing every submission, processing state, grouped issue links/counts, automatically computed priority and an exception-review workflow. Build the Nagar Nigam view with only consolidated published issues, counts, representative evidence, automatic priority order and repair progress actions through authorized APIs. Keep role navigation/session changes safe and do not compute authoritative counts, ranking, grouping or access permissions in the frontend. Use agreed fixtures while backend APIs are being built. Test mobile submission/tracking, admin seeing 100 reports, Nigam seeing 20 issues when fixtures represent 20 actual groups, repeated reporters, API failures and role isolation. Run frontend tests/build, document endpoint dependencies, and submit a separate pull request.

## Integration and teamwork rules

- Each person commits and pushes only their owned changes. Never both work directly on the shared base branch.
- Backend PR: include the agreed API contract and sample fixtures early so frontend work can proceed independently.
- Frontend PR: use a configurable API base and keep mocks in tests, not enabled in production.
- Review each other's PRs, integrate to a shared integration branch and run full acceptance checks before merging to the main working branch.
- After shared merges, both people pull/rebase their own branches to avoid working on stale assumptions.
- Share a short Git-tracked progress note with completed changes, remaining dependencies and test results; a chat snapshot is not live shared memory.

## Joint acceptance demonstration

1. With PC worker stopped, submit from a phone/mobile viewport: report is saved and pending without model UI.
2. Start worker: existing queue processes without reuploading photos.
3. Submit a labelled set of 100 reports describing 20 actual groups: admin retains 100 reports; validated matching determines whether it can confidently form 20 issues. Review uncertain cases instead of forcing the count.
4. Confirm raw-report/distinct-account counts and repeated-delivery idempotency.
5. Verify supported consolidated issues publish automatically and priority ordering does not require manual ranking.
6. Nagar Nigam sees consolidated issues only, updates a repair status, and linked citizens see that update.
7. Confirm unauthenticated/citizen clients cannot access AI internals, worker routes or another citizen's private reports.
