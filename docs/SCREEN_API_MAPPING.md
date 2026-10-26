# NAGARSAATHI V2 — Screen to API Contract Mapping

This document provides a comprehensive mapping between user interface views (ported from Chaitanya UI) and the backend API endpoints (derived from `main` with V2 enhancements).

---

## 1. Citizen Screens

### 1.1 Overview & Dashboard (`/` or `#/overview`)
- **UI Elements:**
  - Metric counters (Total Complaints, Resolved, In Progress, Critical Urgency).
  - Recent public activity map & list.
  - Quick action buttons ("Report an Issue", "View My Reports").
- **Backend API Endpoints:**
  - `GET /api/v1/metrics`: Returns aggregated counts across categories and status.
  - `GET /api/v1/issues?limit=10&sort=newest`: Returns public issue summary projections (privacy-safe, excluding private citizen info).

### 1.2 Intake Wizard (`/report` or `#/report`)
- **Step 1: Problem Description & Category**
  - Form fields: Category select (`pothole`, `garbage_accumulation`, `sewage_overflow`, `streetlight_failure`, `other_civic_issue`), description (10–500 chars).
- **Step 2: Photo Upload & Verification**
  - Actions: Upload image, client validation (format, size < 10MB), optional client pre-check.
  - Endpoints:
    - `POST /api/v1/intake/uploads`: Uploads raw media, returns `upload_id` and SHA-256 hash.
- **Step 3: Location Pin & Landmark**
  - Interactive Leaflet map, GPS "Use my current location", draggable pin, manual latitude/longitude inputs, optional landmark text.
  - Boundary check: Real-time validation against Southeast Bengaluru pilot envelope.
- **Submission:**
  - `POST /api/v1/intake/reports`: Idempotent complaint submission with `idempotency_key`, `upload_id`, coordinates `[lng, lat]`, category, and description.

### 1.3 My Reports (`/my-reports` or `#/my-reports`)
- **UI Elements:**
  - Filterable list and map showing the citizen's own submitted reports.
  - Status badges (`submitted`, `under_review`, `assigned`, `in_progress`, `resolved`, `rejected`, `out_of_scope`).
  - Receipt card with issue reference, timeline, and repair verification photos when resolved.
- **Backend API Endpoints:**
  - `GET /api/v1/reports?mine=true`: Filtered query returning only reports authored by the current authenticated citizen.
  - `GET /api/v1/reports/{report_id}`: Detailed receipt view including linked issue progress.

---

## 2. Interactive Map Explorer (`/map` or `#/map`)
- **UI Elements:**
  - Full-screen / split Leaflet map with custom category pin markers.
  - Filter controls: Category pills, status dropdown, date range, pilot boundary toggle.
  - Selected issue popup / drawer with report counts, eligible reporters, and aggregated status.
- **Backend API Endpoints:**
  - `GET /api/v1/issues?bbox={min_lng},{min_lat},{max_lng},{max_lat}&category={category}&status={status}`: Bounded geospatial query returning issues inside viewport.
  - `GET /api/v1/pilot/boundary`: Returns pilot envelope GeoJSON polygon for boundary overlay.

---

## 3. Staff & Administrator Console

### 3.1 Triage & Queue Management (`/staff/queue`)
- **UI Elements:**
  - 6 Area queues (Southwest, South Central, Southeast, Northwest, North Central, Northeast).
  - Triage actions: Accept report, reject with reason, re-categorize, flag duplicate candidate.
- **Backend API Endpoints:**
  - `GET /api/v1/staff/queues/{area_id}`: Cursor-paginated queue items.
  - `POST /api/v1/reviews/{report_id}/triage`: Commit triage decision (category override, admission).

### 3.2 Duplicate Inspection & Grouping (`/admin/duplicates` or Modal)
- **UI Elements:**
  - Visual comparison of duplicate candidates (distance, time, category, photo similarity).
  - Actions: Attach report to existing issue, or separate report into a new issue.
- **Backend API Endpoints:**
  - `GET /api/v1/issues/{issue_id}/duplicates`: Lists candidate reports within spatial proximity.
  - `POST /api/v1/issues/{issue_id}/merge`: Merge reports into shared issue.
  - `POST /api/v1/issues/{issue_id}/split`: Split report into separate issue.

### 3.3 Priority & Work Orders (`/staff/priority` & `/staff/work`)
- **UI Elements:**
  - Priority breakdown (Severity, Context Score, Urgency, Reporter Multiplier).
  - Work assignment to field operators, status updates, repair photo upload.
- **Backend API Endpoints:**
  - `GET /api/v1/priority/scores`: Paginated priority backlog.
  - `POST /api/v1/work/{issue_id}/assign`: Assign operator team.
  - `POST /api/v1/work/{issue_id}/repair`: Submit repair evidence.
  - `POST /api/v1/work/{issue_id}/verify`: Independent supervisor verification (closes issue).

### 3.4 Complaint Moderation, Soft Deletion & Restoration (`/admin/complaints`)
- **UI Elements:**
  - Admin complaint manager with "Soft Delete" button (requires reason).
  - "Deleted Complaints Archive" tab visible exclusively to administrators.
  - "Restore Complaint" button with confirmation of issue impact.
- **Backend API Endpoints:**
  - `DELETE /api/v1/admin/reports/{report_id}`: Soft delete complaint with `reason` and audit record.
  - `GET /api/v1/admin/reports/deleted`: Paginated list of soft-deleted complaints.
  - `POST /api/v1/admin/reports/{report_id}/restore`: Restores soft-deleted complaint, recalculating issue counts.
