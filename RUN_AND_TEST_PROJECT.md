# Run and test NAGARSAATHI — beginner guide

This guide is for `D:\nagarsaathi-model\integrations\NAGARSAATHI-chaitanya-ui` and the combined pothole/waterlogging model. It describes the current implementation, not future features.

## 1. Understand the three accounts

| Account | What it can see/do |
| --- | --- |
| Citizen | Submit photos; see only their own reports, AI findings and shared issue counts/status |
| Platform admin — you | See every individual report; compare photos and locations; group/separate reports; forward consolidated issues |
| Nagar Nigam | See only forwarded consolidated issues, counts, representative photo and location; cannot access the individual-report inbox |

Nagar Nigam's current view is read-only. Officer assignment and repair-status update controls are future work. The existing platform-admin review section can update status. Automatic priority scoring is outside this iteration; any old manual-priority controls are legacy UI, not a newly implemented scoring system.

## 2. Start the current development version

Use **Command Prompt (CMD)** for these commands. This is the version on port **5174**. Existing dependencies and the model are already in this checkout; you do not need to retrain the model.

### Window A — backend and model

```cmd
cd /d D:\nagarsaathi-model\integrations\NAGARSAATHI-chaitanya-ui
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8002
```

Wait for `Application startup complete`. This window runs the API and loads YOLO. Keep it open.

### Window B — frontend

```cmd
cd /d D:\nagarsaathi-model\integrations\NAGARSAATHI-chaitanya-ui
npm run dev -- --port 5174 --strictPort
```

Open **http://127.0.0.1:5174/**. Keep this window open too. If these services are already running, just open the website; do not launch duplicate processes. Stop a development server with Ctrl+C in its terminal.

### Window C — create staff accounts once

These example addresses identify local test accounts. Replace them with the addresses you want before creating real staff accounts. The app currently uses email/password login without sending an email verification message.

```cmd
cd /d D:\nagarsaathi-model\integrations\NAGARSAATHI-chaitanya-ui
.venv\Scripts\python.exe -m backend.accounts platform-admin@example.com --name "Platform Admin"
.venv\Scripts\python.exe -m backend.accounts nigam-officer@example.com --name "Nagar Nigam" --role nigam
```

Each command prompts for a password. Use 10–128 characters. Typing is hidden: the password is being entered even though you do not see dots or letters. Press Enter when finished. Remember the passwords you choose.

Create each address only once. If it is already registered, use its existing account; rerunning the command does not promote it or reset its password. Public **Register** always creates a citizen, never a staff account.

## 3. Submit a citizen complaint

1. Open the website. Click **Sign In**, then **Register** to create a citizen account. Do not use the staff-account addresses above for public registration.
2. Sign in and click **Report Issue**.
3. Choose Pothole, Waterlogging or Both, and write a description.
4. Click **Continue** and upload a supported photo.
5. Place the location pin at the actual problem. You can use location permission if you want; otherwise place the pin manually. Confirm the location.
6. **Check Photo** previews AI findings. It does not itself create a saved complaint.
7. Continue to **Review & submit**, check the details, then click **Submit Complaint**.
8. Record the returned **Report #**. Open **My Reports** to find it later.

If the AI finds nothing, the complaint can still be saved. Detection failure is not automatic rejection. The category and confidence are suggestions for review, not proof of authenticity or a measurement of severity.

### What the citizen receives

An illustrative result, not a guaranteed output:

```text
Report #21
Status: Open
AI: Pothole — 78% model confidence
Issue #7 — 1 report from 1 distinct account
```

Numbers and confidence depend on your database and photograph. One photo can produce multiple detection boxes; those boxes are not the report count.

Citizen report details show the saved photo and textual findings. The photo-check preview can show boxes; do not expect every saved photo to be permanently drawn with boxes.

## 4. Check reports as platform admin

Use a different browser profile/private window for the admin, or sign out of the citizen account and sign in using your staff email/password. Two tabs in the same browser profile share login storage; do not rely on them as independent accounts.

1. Confirm the sidebar says **PLATFORM ADMIN WORKSPACE**.
2. Open **Overview**. The total counts individual reports, not consolidated issues.
3. Look at the report list beside the map. On a narrow window select **List** if the list is hidden.
4. Open a report. You can see its photo, category, location, date, AI findings, shared issue ID and counts.
5. Find **Duplicate grouping — platform admin**. This contains possible matches and grouping/forwarding controls.

Example admin inbox:

```text
Report #21 -> Issue #7
Report #22 -> Issue #7
Report #23 -> Issue #7

Three original submissions remain visible.
Issue #7: 3 reports from 3 distinct accounts.
```

There is no automatic deletion of citizen reports or uploaded photos.

## 5. Group duplicates

### Automatic case

The same normalized photograph can join an unresolved issue automatically when the category matches, the location is within 30 metres of both the matching report and issue anchor, and the matching report is within 30 days.

### Different photos of the same issue

These are suggestions requiring admin confirmation in this version. Similar-looking photographs alone do not prove it is the same physical pothole.

1. Open both reports from your admin inbox and compare their photos, categories and locations.
2. Note the **Issue #** you want to keep. Use the issue ID, not the report ID: they may be different numbers.
3. Open the report you want to attach to that issue.
4. Under **Duplicate grouping**, select a possible match or enter the existing issue ID.
5. Enter a grouping reason, for example `Same junction and same road defect, checked both photos`.
6. Click **Attach report to selected issue**.
7. Check that the issue ID and counts update. All original reports remain in the inbox.

If you made a mistake, enter a reason and click **Separate this report into a new issue**. Counts are recalculated. Do not group different problems solely because their coordinates are close.

## 6. Send one consolidated issue to Nagar Nigam

1. As platform admin, finish checking the grouping first.
2. Open any report in that issue.
3. Click **Send consolidated issue to Nagar Nigam**.
4. The panel changes to **Visible to Nagar Nigam**.
5. Sign in as the Nigam officer in another browser profile/private window, or sign out first.
6. Confirm **NAGAR NIGAM WORKSPACE** appears. Click Refresh if needed.

The municipal queue contains one item per forwarded issue. Example:

```text
Issue #7 — Pothole
10 reports from 10 distinct accounts
One representative photo
Location and current status
```

The municipal user cannot open all ten private citizen reports or see reporter identities. New reports attached to Issue #7 update this same item. A newly separated issue is not forwarded automatically; review and forward it separately if appropriate.

## 7. Test grouping and counts yourself

Use harmless test descriptions so you can distinguish test complaints from real ones. The following creates actual persistent test reports in the local database; no automatic cleanup or delete-report feature is provided.

| Test | What to do | Expected output |
| --- | --- | --- |
| First report | Citizen A submits a photo | One report; one issue; one reporter |
| Same issue, another reporter | Citizen B submits the same photo/category and same pin | Two admin reports; one shared issue; two reporters |
| Same reporter again | Citizen A starts a new submission with that photo | Three reports; one issue; two reporters |
| Different photograph | Submit a different photo near that pin | Separate issue initially; possible-match suggestion for admin |
| Confirm the match | Admin attaches that report to the first issue | One shared issue; counts reflect all linked reports |
| Correct a mistake | Admin separates one report | Separate issue; original group's counts decrease correctly |
| Municipal visibility | Forward only the first issue and log in as Nigam | Only that consolidated issue appears |
| Different problem | Same photo but far-away location, or another category | Does not automatically join the original issue |

To reproduce exactly "10 reports from 10 accounts", use ten citizen accounts and one submission per account. Ten submissions by one account mean "10 reports from 1 distinct account". Distinct accounts do not guarantee ten different humans.

The app protects an accidental network retry using a submission key. Starting a deliberately new submission is a separate report. A retry is not the same thing as a new citizen submission.

## 8. Check the model and API directly — optional

Development API documentation: **http://127.0.0.1:8002/docs**. Use this version's real account login, not the older app's `demo-citizen` token.

1. Open `POST /auth/login`, click **Try it out**, and enter your account email/password as JSON.
2. Execute. Copy the returned `access_token` privately.
3. Click **Authorize**, paste the token into the bearer field, and authorize. Do not share tokens or put them in screenshots.
4. Platform admin: execute `GET /reports` to inspect individual submissions.
5. Platform admin or Nigam: execute `GET /issues` to inspect consolidated summaries; Nigam sees only forwarded issues.

Illustrative consolidated JSON:

```json
{
  "id": 7,
  "issue_type": "pothole",
  "status": "open",
  "published": true,
  "report_count": 10,
  "reporter_count": 10,
  "unique_photo_count": 1,
  "photo_url": "/issues/7/photo"
}
```

This is a shortened example. `unique_photo_count=1` means all ten submissions reused identical normalized pixels; different photographs can give a larger unique-photo count without increasing the issue count.

Saved AI data includes model version, image dimensions, threshold and detections. Each detection has a class label, confidence and bounding-box coordinates. The model is `nagarsaathi-yolo11n-v3`, recognizing pothole and waterlogging.

## 9. Docker alternative — choose this OR the development setup

For a bundled local app, first open Docker Desktop and wait for its engine to run. Then:

```cmd
cd /d D:\nagarsaathi-model\integrations\NAGARSAATHI-chaitanya-ui
docker compose up -d --build --wait
```

Open **http://127.0.0.1:5180/**. This builds the latest source changes; an old container will not update merely because the development files changed.

Create Docker staff accounts inside that container:

```cmd
docker compose exec app python -m backend.accounts platform-admin@example.com --name "Platform Admin"
docker compose exec app python -m backend.accounts nigam-officer@example.com --name "Nagar Nigam" --role nigam
```

Follow the same citizen/admin/Nigam steps above. Docker API documentation is **http://127.0.0.1:5180/api/docs**.

**Development and Docker use separate databases.** Accounts/reports created on port 5174 do not automatically appear on port 5180. Create staff accounts using the commands for the mode you are actually using. A missing account or empty list after switching modes does not mean your original reports were deleted.

Useful Docker commands:

```cmd
docker compose ps
docker compose logs --tail 100 app
docker compose stop
docker compose up -d --wait
```

Ordinary stops/restarts preserve the named database/photo volume. Do not run `docker compose down -v` when you want to keep its data: `-v` removes the data volume.

## 10. Common problems

| Problem | Check |
| --- | --- |
| Cannot open 5174 | Start the frontend terminal; confirm Vite reports port 5174 |
| Frontend opens but reports fail | Start the backend on 8002 and sign in again if the session expired |
| Port already in use | An instance may already be running; use it or stop its terminal before starting another |
| Nigam sees no issues | Platform admin must forward an issue first; refresh after forwarding |
| Citizen sees only their reports | Expected privacy behavior; use platform-admin login for the complete inbox |
| Two nearby photos are not grouped | Different photos need admin confirmation; inspect suggested matches |
| Staff account says email exists | It was already registered; account creation is not a password reset or role promotion |
| Docker cannot connect to engine | Open Docker Desktop and wait until the engine is running |
| Old interface after a Docker change | Rebuild using `docker compose up -d --build --wait` and refresh the browser |
| Saved analysis is unavailable/failed | Complaint remains stored; check backend logs; this is not a "fake complaint" decision |

Developer checks, using CMD in the project folder:

```cmd
.venv\Scripts\python.exe -m unittest discover -s backend -p "test_*.py" -v
npm test
npm run build
```

## 11. What works locally versus what is still planned

Working: combined AI inference, authenticated complaints/photos, individual admin inbox, conservative duplicate grouping, reversible admin grouping, report/distinct-account counts, forwarding and a separate read-only municipal view.

Not implemented in this iteration: automatic matching across arbitrary camera angles, an online upload queue with a separate PC worker, public hosting, per-ward municipal isolation, automated priority scoring, and Nagar Nigam assignment/repair-update controls.

Currently the model runs inside the backend during submission. On the development setup that backend is on your PC; in Docker it runs in the container on your PC. This is not yet the proposed online queue-to-PC-worker architecture.

`127.0.0.1` only works on the device running the servers. A phone cannot use its own `127.0.0.1` to reach your laptop. Public phone access still needs deployment or a separately configured network demo. No public deployment is completed by these startup commands.
