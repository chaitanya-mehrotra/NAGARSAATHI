# Duplicate grouping and counts

This implementation adds grouping and counting to Chaitanya's UI. Priority scoring, public hosting and the separate PC job worker are outside this change. The existing inline YOLO analysis continues to work.

## What each person sees

- Citizen: their own reports and the shared issue's counts/status. They cannot open another citizen's report.
- Platform admin (`admin`): every individual report, AI result, possible matches and grouping controls.
- Nagar Nigam (`nigam`): only issues the platform admin has forwarded. Each shared issue appears once with report count, distinct-account count and one representative photo. The individual report inbox and reporter identities are inaccessible.

Ten different accounts submit the same issue -> ten reports remain in the admin inbox -> one consolidated issue shows "10 reports from 10 distinct accounts" to Nagar Nigam. An eleventh report from an existing contributor changes that to eleven reports from ten accounts.

## What groups automatically?

The same normalized photo, the same submitted category, an unresolved issue, a supporting report within 30 days, and location within 30 metres of both the matching report and issue anchor. These are conservative prototype rules, not proof of authenticity. They do not decide whether a complaint is real.

Different photos near the same location are **suggestions for admin review**, not automatic merges. A difference hash highlights visually similar photos; it does not recognize the same pothole from arbitrary angles. Location alone never confirms a duplicate. Accurate fully automatic grouping across different views needs a labelled evaluation set and further image matching work.

Identical photos reused far away remain separate and raise a review suggestion. Categories are not mixed automatically. Closed issues do not absorb a new report automatically.

## Admin steps

1. Sign in with a platform-admin account and open a report from the normal report list.
2. Read its shared issue number and counts. Open the other reports from the inbox to compare their photos/locations.
3. In **Duplicate grouping**, choose a suggested issue ID or enter the issue ID from another report. Enter a reason and click **Attach report to selected issue**.
4. To undo a mistaken grouping, open that report, enter a reason and click **Separate this report into a new issue**.
5. When grouping is correct, click **Send consolidated issue to Nagar Nigam**. Before forwarding, the issue is hidden from municipal accounts.
6. Subsequent reports attached to that issue update its counts in place. They do not create another municipal work item.

The platform admin still sees every original report. Photos are retained; this change consolidates work items, not physical files. `unique_photo_count` counts distinct normalized images, so repeated copies count as one unique image while all submissions remain saved.

## Create staff accounts

Public registration always creates a citizen, regardless of a submitted role. Create staff accounts from a trusted terminal in this project folder:

```cmd
.venv\Scripts\python.exe -m backend.accounts your-admin@example.com --name "Platform Admin"
.venv\Scripts\python.exe -m backend.accounts officer@example.com --name "Nagar Nigam" --role nigam
```

Enter passwords at the hidden prompt. Use actual email addresses you control. Do not create these accounts using the public registration form. For Docker, run the same commands inside the running app container using `docker compose exec app python -m backend.accounts ...` so they use the container's database.

Municipal accounts currently share the forwarded queue; per-ward/jurisdiction assignment is future work. Do not use this version to separate multiple municipal authorities yet.

## Storage and migration

On first startup with an older database, an automatic SQLite backup is written under `DATA_DIR/backups/before-issue-grouping-*.db`. All existing reports get independent issue records. Old distance-only duplicate links become review suggestions; they are not silently accepted as confirmed groups. Existing accounts, uploaded files, model outputs and tracking IDs remain saved. No bulk retrospective visual merge runs automatically.

Counts are calculated from current database membership using `COUNT` and `COUNT(DISTINCT user_id)`. They are not increment-only counters and remain accurate after regrouping or retries. Distinct accounts are not guaranteed distinct humans.

The frontend sends an `Idempotency-Key` for a submission attempt. A retry with the same account, key and content returns the original report. Reusing a key with changed content returns HTTP 409. Deliberately starting a new submission creates a new report, even with the same photo. Direct API clients must supply this header to get retry protection.

Grouping operations are transactional and recorded in `grouping_history` with actor, old/new issue IDs and reason. A group with no remaining reports is removed from the issue queue; reports themselves are not deleted.

## API summary

| Endpoint | Access / purpose |
| --- | --- |
| `GET /reports`, `/complaints` | Platform admin: all submissions; citizen: own; Nagar Nigam: denied |
| `GET /issues` | Admin: all consolidated issues; Nagar Nigam: forwarded issues only |
| `GET /issues/{id}` | Consolidated summary and counts for staff |
| `GET /issues/{id}/photo` | Authorized representative evidence for staff |
| `PATCH /issues/report/{report_id}/group` | Admin only; `{ "issue_id": 123, "reason": "..." }`; null issue ID separates the report |
| `PATCH /issues/{id}/publication` | Admin only; `{ "published": true }` forwards an issue |

Under the combined Docker app, prepend `/api` to these paths.

## Run and verify

Restart the local API after changing backend code. Vite reloads frontend changes automatically. The complete Docker app needs a rebuild from this folder:

```cmd
docker compose up -d --build --wait
```

Then open `http://127.0.0.1:5180/`. The development frontend remains on port 5174 with its separately started API.

```cmd
.venv\Scripts\python.exe -m unittest discover -s backend -p "test_*.py" -v
npm test
npm run build
```

Acceptance coverage includes ten reports/one municipal issue, repeated reporters, concurrent submission retries, category/location exclusions, manual regrouping and separation, permissions, photo retention and repeat-safe migration.
