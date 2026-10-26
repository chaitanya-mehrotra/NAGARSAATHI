# NAGARSAATHI implementation plan

Prepared: 26 October 2026. This document describes the requested next version. It does not mean these changes are already implemented or publicly deployed.

Current scope update: priority work is deferred at the user's request. Implement duplicate grouping, counts, and separate platform-admin/Nagar Nigam views first. Priority sections below are future proposals only, not requirements for this iteration. See `DUPLICATE_GROUPING.md` for the implemented subset and its limits; the PC worker and cloud migration remain separate future work.

## 1. Your requirements in simple words

1. A citizen opens the website on a phone, signs in, takes or uploads a photo, supplies a location and description, and submits a complaint.
2. The website saves the complaint online immediately and returns a tracking number.
3. Your admin PC receives work from the online system. The combined pothole/waterlogging model runs on your PC.
4. AI records what it sees, including the category, boxes and confidence. Uncertain or missed detections still go to review.
5. If ten citizens report the same physical problem, the NAGARSAATHI platform admin can see all ten individual reports, their analysis and their grouping. Nagar Nigam sees only one consolidated issue marked with the report count and distinct-reporter count.
6. The system preserves the number of submissions and the number of different people reporting that issue.
7. The platform admin reviews submissions and grouping. Nagar Nigam receives a priority list of consolidated issues based on danger, public impact, independent reports and how long the issue has been waiting.
8. The Nagar Nigam reviews issues, assigns work, updates progress and records resolution. Each citizen can track their own complaint.
9. Use Chaitanya's interface; preserve its appearance. Do not change Saish's separate UI.

### Three different things we must count

| Term | Meaning | Example |
| --- | --- | --- |
| Report | One citizen's submission | Ten submissions about one pothole = ten reports |
| Issue | One physical problem to investigate or repair | Those ten reports can belong to one issue |
| Detection | A box predicted in a photo | Five boxes in one photo do not automatically mean five repair jobs |

Keep these counts separate. One photo can show several potholes, and one long flooded road can appear in many different photos. The first version groups reports into repair issues; it does not claim to count every individual physical pothole from unrelated photographs.

## 2. Overall pipeline

```text
Citizen's phone
    -> Public HTTPS website and API
    -> Save report + private photo + queued job online
    -> Return tracking number immediately

Admin PC worker connects OUT to the public API
    -> Claims a queued job
    -> Downloads photo securely
    -> Runs combined YOLO11n
    -> Calculates photo fingerprints/similarity features
    -> Sends results back to public API

Public backend
    -> Checks possible existing issues
    -> Links report or creates a new issue
    -> Updates counts and priority
    -> Platform admin sees all individual reports and grouping evidence
    -> Nagar Nigam sees one consolidated issue per physical problem
    -> Citizen sees updates for their own report

NAGARSAATHI platform admin
    -> Reviews AI evidence, individual submissions and grouping
    -> Makes the consolidated issue available to Nagar Nigam

Nagar Nigam officer
    -> Receives consolidated issues with reporter counts and priority
    -> Assigns issue -> work in progress -> resolved
```

The central database is the source of truth. Complaints are not sent directly to a folder on your PC. Your dashboard reads them from the online backend, and your worker downloads photos as needed.

If your PC is off, citizens can still submit. Jobs wait online until the worker returns. Processing around the clock requires keeping that PC awake and connected, or later moving the worker to an always-on machine.

## 3. Which component does what?

| Component | Responsibility |
| --- | --- |
| React frontend | Citizen forms/tracking, platform-admin dashboard and Nagar Nigam dashboard |
| Online FastAPI backend | Authentication, uploads, access checks, jobs, grouping, counts and priority |
| Online database | Users, reports, issues, jobs, AI results and history |
| Private photo storage | Persistent uploaded photos; temporary authorized download access |
| Windows worker on your PC | YOLO inference and image feature extraction |
| Platform admin | Inspect all reports; confirm category, grouping and triage; manage forwarding |
| Nagar Nigam officer | See consolidated issues within assigned jurisdiction; assign repairs and record progress/resolution |

For the shared online version, use PostgreSQL with geographic indexing through PostGIS and private object storage. These are proposed components, not services already provisioned. Keep storage access behind the backend. Provider and cost selection comes after the design is agreed.

The cloud API should not load YOLO or require GPU/PyTorch. Training is separate from processing complaints. The PC worker loads the existing checkpoint once at startup; it does not train again for every photo.

## 4. AI checks and their limits

Use the existing combined YOLO11n checkpoint: `backend/models/nagarsaathi-combined-v3.pt`, classes `pothole` and `waterlogging`.

Store model version/hash, inference settings, input dimensions, detected class, confidence and bounding boxes with each result. Keep the actual category submitted by the citizen separately from the suggested category.

Possible outcomes:

- Target detected: evidence supports a possible pothole or waterlogging complaint; human review remains available.
- No target detected: manual review needed; do not reject the complaint automatically.
- Worker/model error: save the complaint and retry analysis.
- Both classes detected: preserve both; the admin can decide whether it is one repair issue or separate issues.

YOLO does not prove that a photograph is recent, taken at the claimed location, or genuine. Confidence is not a fraud score. It also does not measure pothole depth, flood depth or physical danger from a normal photo.

## 5. Duplicate grouping: one issue, many reports

### Preserve evidence instead of deleting reports

Every legitimate submission keeps its own tracking ID, owner, time, photo reference and analysis. Link related reports to a shared `issue_id`. The platform admin's report inbox lists every individual report and shows its linked issue. A separate grouping view helps the admin review matching. The Nagar Nigam work queue lists only consolidated issues, never ten separate work items for the same problem.

Example: Alice and Bob independently photograph the same pothole. Both keep their tracking IDs. The platform admin sees both submissions. Nagar Nigam sees one issue, labelled two submissions from two distinct reporters. If Alice submits again, the platform admin sees three submissions; Nagar Nigam still sees one issue with three submissions from two distinct reporters.

### Three user roles and forwarding

- Citizen: submit a report and track their own submission and its shared repair status.
- Platform admin: access individual reports, photos and AI results; resolve uncertain matches; merge/split groups; review priority; forward consolidated issues.
- Nagar Nigam officer: receive consolidated issue records with location, category, representative evidence, report count, distinct-reporter count and priority reasons; manage repair progress within their jurisdiction.

Default first-version forwarding is platform-admin approval after analysis/grouping review. A report remains visible to the platform admin while pending. New matching reports update the same forwarded issue's counts and priority; they do not create new Nagar Nigam work items or require the original issue to be forwarded again. Keep forwarding state separate from repair status. Any later automatic-forwarding policy must be explicit and auditable.

Nagar Nigam receives a representative photo/evidence summary rather than the platform's full individual-report inbox or reporter identities. Access separation must be enforced by backend permissions and response fields, not just by hiding frontend rows.

An accidental retry of the same network request should not create another submission at all: the phone sends an idempotency key and the server returns the original saved report.

### There are two separate duplicate problems

1. Duplicate files: an identical or re-encoded photograph appears more than once.
2. Duplicate real-world issues: different photos show the same physical problem.

Solving the first does not solve the second. YOLO identifies object classes; it does not identify a particular pothole across different photographs.

### Matching process

1. Normalize image orientation and remove metadata from served copies. Calculate a SHA-256 fingerprint of normalized pixels for exact image reuse.
2. Calculate a perceptual hash to find resized or lightly changed copies. It is a clue, not proof of the same physical issue.
3. Search nearby, unresolved issues with compatible categories and a relevant observation period. Use GPS accuracy when available. A 30-metre search radius is an initial candidate-search example, not an automatic merge rule.
4. Compare image embeddings: numerical descriptions of visual appearance generated by a separate image encoder. This introduces an additional model/dependency and must be evaluated on local road photos.
5. Combine location, category, time and visual evidence. When useful, compare defect crops as well as whole scenes so similar-looking roads do not dominate the decision.
6. Strong, tested agreement: link automatically. Ambiguous: show a possible-duplicate suggestion for admin review. Clearly different: create a new issue.

Do not pick universal similarity cutoffs now. First label examples of the same issue from different angles and different nearby issues, then select cutoffs from measured matching performance. Start with admin-confirmed grouping before enabling automatic linking.

### Cases we must handle

- Two different potholes close together must not merge just because their coordinates are close.
- Pothole and waterlogging reports at the same location must not merge solely on distance. Preserve their categories and allow human grouping where appropriate.
- The same reused photo at distant locations should be flagged for review; it must not automatically create corroboration or merge those places.
- Missing or poor GPS means lower matching certainty; let the citizen pin a location and send uncertain cases to review.
- A repaired pothole reported again later may be a new occurrence. Resolved issues are excluded from ordinary automatic grouping; admins can explicitly reopen or relate them.
- A long flooded street may need an issue area rather than a single coordinate. Start with admin-controlled grouping and add geographic extent support later.
- One report containing several distinct problems may need multiple issue links later. The initial version uses one primary issue per report, with manual review for complex scenes.

### Counts and storage

Maintain total submitted reports, distinct reporters, eligible reporters used for priority, linked photo count, unique active issues and unresolved issues awaiting grouping. Label provisional dashboard counts clearly while jobs are pending.

Distinct reporters means different signed-in accounts, not guaranteed different humans. Prevent repeated reports from one account increasing priority; rate-limit abuse and allow admins to exclude spam from priority counts while retaining the audit trail.

Derive authoritative counts from report links in the database. Any cached totals must be updated transactionally and periodically reconciled. Do not increment a counter twice when a job retries.

If identical images share one stored object to save space, keep every report-to-photo reference. Never delete a shared file while another report references it. Apply a documented retention policy separately from duplicate grouping.

## 6. Priority: which issue should be handled first?

Repeated independent reports can increase priority, but popularity must not override danger. A dangerous issue reported once can outrank a minor issue reported many times.

Use an explainable initial score:

```text
Priority score = 40*S + 25*I + 20*R + 15*A

S = reviewed severity, between 0 and 1
I = public impact, between 0 and 1
R = min(U / 10, 1)
A = min(D / 7, 1)

U = distinct eligible reporters linked to this issue
D = days since the first unresolved report
```

These weights and caps are proposed starting policy, not a scientific measure or a trained model output. Nagar Nigam should approve and calibrate them using real cases.

Severity considers confirmed obstruction and danger. Impact considers information such as blocked access, road importance, nearby hospitals/schools and affected routes. Such information needs a reliable source or admin confirmation; do not invent it from image confidence. Display unknown severity/impact as unknown and send the issue for triage instead of silently treating missing data as low risk.

For illustration, an already-triaged issue with S=0.75, I=0.8, U=5 and D=2 scores approximately 64.3 out of 100. Ten repeat submissions from the same person do not make U=10.

Provisional bands: 70–100 high, 40–below 70 medium, below 40 low. An admin-confirmed emergency overrides the numeric order. These bands also require policy approval. Pending triage has a separate visible queue so unscored issues are not forgotten.

Show a breakdown: severity points, impact points, distinct-reporter points, waiting-time points and any manual override with its reason. Record policy version and score inputs. Recalculate after grouping, ungrouping, new eligible reporters, review and status changes, plus a daily age update. Resolved issues leave the active priority queue.

## 7. Database changes

| Table | Main purpose |
| --- | --- |
| users / sessions | Extend citizen/admin identity to citizen, platform_admin and nigam_officer; migrate existing admins to platform_admin and scope officers to jurisdiction |
| reports | Original submission, owner, claimed category, coordinates/accuracy, tracking ID, issue link and submission idempotency key |
| photos | Private object key, normalized-image hash, perceptual hash, dimensions and reference information |
| issues | Shared physical issue, location, category, lifecycle, triage fields, priority policy/score, override, jurisdiction, forwarding state and forwarded time/actor |
| analysis_jobs | Queue state, attempt count, next retry, lease owner/token, lease expiry and error summary |
| analysis_results | Report/photo binding, model identity, detections, embeddings version and completion time |
| duplicate_candidates | Suggested matches, evidence, decision and reviewer |
| issue_history | Status changes, grouping/ungrouping, reassignment, priority changes and actor/time |

Migrate existing reports without losing accounts, photos or tracking IDs. Review existing `duplicate_of` links rather than trusting them automatically, since the current heuristic uses location alone.

## 8. PC worker and reliable processing

Proposed API operations, all versioned under `/api`:

- Citizen: submit report, retrieve own report/analysis/photo and track its shared issue status.
- Worker: claim job, renew lease, fetch authorized job input, submit result, report retryable failure.
- Platform admin: list all individual reports and issues, inspect suggested matches, merge/split groups, update triage, forward issues and record reasons.
- Nagar Nigam officer: list forwarded consolidated issues within their jurisdiction, view permitted evidence/counts and update assignment/repair status; no access to the individual-report inbox or citizen identities.

The worker uses a dedicated limited credential. It cannot provision admins, browse unrelated user data or update repair statuses. Downloads and uploads use HTTPS. No public inbound connection or router port-forwarding to the PC is needed.

Implement atomic job claiming with a lease. If the PC crashes, the lease expires and the job becomes claimable again. Use bounded retries with backoff, then a visible failed-job queue with manual retry. Duplicate result delivery must not duplicate analysis records, grouping or counters.

Use database transactions/locking to prevent two workers processing nearby reports from creating duplicate issues at the same time. Version grouping decisions so a late worker result cannot overwrite an admin correction. Keep the model loaded once, limit parallel inference and clean temporary downloads after completion.

Package the worker with pinned dependencies, configuration example and a health command. Start it automatically with Windows Task Scheduler at sign-in/startup. Document sleep settings, credential rotation, model upgrades and rollback.

## 9. Frontend changes while preserving Chaitanya's design

Citizen view: clear submission confirmation, tracking ID, queued/processing/completed analysis state, AI suggestions and review state. If grouped, explain that the complaint is attached to an existing issue and still has its own tracking ID.

Platform-admin view: an inbox with one row per individual report, processing/review state and linked issue. Add a grouping view showing total reports, contributors, AI evidence, possible matches, merge/split controls, priority review and forwarding. All ten submissions remain inspectable here.

Nagar Nigam view: one row per forwarded consolidated issue with location, category, repair status, total reports, distinct reporters, priority and reason. Show representative evidence and assignment/progress controls. Ten reports of the same problem appear as one work item labelled, for example, "10 reports from 10 people".

Refresh results by polling initially; live push updates can come later. Preserve CSS, navigation and map appearance wherever possible. Do not expose reporters' names, contact details or exact private photos to other citizens.

## 10. Implementation order and completion checks

### Phase 1 — Protect current work and define policy

- Create an implementation branch, back up current database/photos and record working model hash.
- Agree on issue grouping examples, eligible-reporter rules, severity/impact definitions and who can override priority.
- Assemble a small labelled evaluation set: same issue/different photos, nearby different issues, copied images, poor GPS and resolved-then-recurring issues. Keep it separate from final evaluation examples.
- Done when terms and sample decisions are consistent and a restore procedure is documented.

### Phase 2 — Separate online intake from inference

- Add database migrations, persistent private photo storage, report idempotency and durable analysis jobs.
- Remove inline YOLO from submission and cloud startup readiness. Save first and return a tracking response promptly.
- Keep the existing app usable while analysis is queued. Handle interrupted uploads and abandoned stored objects safely.
- Done when a phone can submit while the PC worker is off, and the complaint survives a backend restart.

### Phase 3 — Implement and run the Windows worker

- Add protected claim/result endpoints, leases, retries and model/result identity checks.
- Move current inference into a reusable worker process. Add image hashes/features and worker heartbeat.
- Done when pothole and waterlogging jobs complete on the PC, failures retry safely, and killing/restarting the worker does not lose or double-count a job.

### Phase 4 — Group issues and maintain counts

- Introduce issues and report links, candidate search and visual comparisons.
- Start with suggested matches and manual approval. Add merge/split with audit history and transactional counts.
- Enable automatic linking only after testing shows an acceptable false-merge rate. Keep uncertain cases manual.
- Done when ten reports of one issue show one issue/ten reports, while nearby different issues stay separate and mistaken merges are reversible.

### Phase 5 — Add triage and explainable priority

- Add admin severity/impact fields, eligible-reporter calculation, score breakdown and emergency override.
- Recalculate on relevant events and daily; exclude resolved issues from the active queue.
- Done when repeated submissions by one account do not inflate priority and a serious single-report issue can outrank a popular minor issue.

### Phase 6 — Connect the phone and admin experience

- Add processing/grouping/triage indicators, issue detail, tracking updates and priority sorting using the existing UI style.
- Test from a real phone on a different network using a staging HTTPS URL.
- Add separate platform-admin and Nagar Nigam permissions, dashboards and forwarding workflow.
- Done when the platform admin sees ten individual submissions, Nagar Nigam sees one consolidated issue with the correct counts, and citizens see only their own tracking details.

### Phase 7 — Deploy and operate

- Provision an agreed hosting plan for the light API/frontend, database and private storage. No paid hosting is authorized by this plan alone.
- Configure production authentication, worker credentials, HTTPS, backups, restore tests and basic monitoring.
- Install the worker on the admin PC and document startup, shutdown and recovery.
- Pilot with limited users; inspect false merges, missed detections and priority decisions before wider use.
- Done when submissions survive cloud restarts, processing resumes after a PC outage, backups restore correctly and the public phone-to-admin-to-citizen flow passes.

## 11. Minimum acceptance scenarios

| Scenario | Expected result |
| --- | --- |
| Ten citizens report one physical problem | Platform admin sees ten reports; Nagar Nigam sees one consolidated issue with ten reports from ten distinct accounts |
| Another report matches an already-forwarded issue | Admin inbox gains one report; existing Nagar Nigam issue counts/priority update without creating another work item |
| Nagar Nigam officer requests the individual-report inbox | Access denied; consolidated issue summary remains available within their jurisdiction |
| Issue has not been approved for forwarding | Visible to platform admin; absent from Nagar Nigam queue |
| Two people photograph the same issue from different angles | One shared issue after matching/review, two reports, two distinct reporters |
| One person repeatedly reports the same issue | Evidence retained, priority reporter contribution counted once |
| Phone retries the same request | Original tracking ID returned; no additional report |
| Two nearby but distinct potholes | Separate issues unless an admin intentionally groups repair work |
| Same photo reused at far-away locations | Review flag; no automatic geographic merge or added corroboration |
| Cartoon / clean road / YOLO misses a real pothole | Report retained, uncertain evidence goes to review |
| PC offline | Upload succeeds, job remains queued |
| Worker crashes after prediction | Job safely retries; one accepted result and correct counts |
| Admin splits a mistaken group | Reports reassigned; counts and priority recomputed with history |
| Resolved location reported again | New occurrence or explicit admin reopening; no silent old-issue merge |
| Citizen requests another person's report/photo | Access denied |
| AI confidence rises without other changes | Danger/priority does not automatically rise |

Measure AI precision/recall separately from duplicate-matching precision/recall. Track incorrect merges especially carefully, plus queue age, worker availability, processing failures, time to triage and time to resolution. Overall model confidence is not project accuracy.

## 12. Current code versus requested system

Already present: Chaitanya UI, citizen/admin authentication, photo/report storage, combined YOLO inference and basic admin report updates. This iteration adds shared issue records, report/distinct-account counts, exact-photo local grouping, reviewed grouping/separation, municipal accounts and a consolidated forwarded-issue view. See `DUPLICATE_GROUPING.md` for details and test instructions.

Not yet built: online queued processing on your PC, evaluated automatic matching across different camera views, explainable priority (deferred), production database/storage migration and the complete public deployment.

The original distance-only `duplicate_of` heuristic has been replaced with shared issue membership and conservative image/category/location checks. Historical distance-only links become suggestions for admin review. Inference still runs inside submission; queue-based processing is not part of this iteration.

The existing Docker/Render setup bundles YOLO with the backend. The requested PC-worker design needs a separate light cloud image and Windows worker package before deploying that architecture. Merely publishing the current image will not implement this plan.
