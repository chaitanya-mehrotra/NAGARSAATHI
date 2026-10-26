# NAGARSAATHI V2 — Build Status & Roadmap Tracker

**Updated:** 26 October 2026  
**Target:** Unified production-grade civic complaint & prioritisation platform with modernized UI and self-service citizen + admin lifecycle.  
**Constraint:** Strict read-only on original repository (`../Civic AI/nagarsaathi`). All new code, configuration, and artifacts created exclusively within `V2/`.

---

## 1. Phase Status Overview

| Phase | Description | Status | Acceptance Gate |
|---|---|---|---|
| **Phase 0** | Baseline & Decisions (Inventories, screen-to-API, decisions) | **COMPLETED** | Every main & UI capability mapped; no destructive git merge; baseline locked |
| **Phase 1** | Reproducible Docker Foundation (Compose, PostGIS, Web, API, Worker, Mailbox) | **COMPLETED** | Friends can run full stack with Docker Compose; persistent volumes; no host Python/Node needed |
| **Phase 2** | Backend Reliability, Data Integrity & API Contracts | **COMPLETED** | Fair job processing, citizen projections, cursor pagination, idempotent mutations |
| **Phase 3** | Citizen Self-Service, Auth & Admin Lifecycle | **COMPLETED** | Email/password auth, JWT verification, admin complaint soft-delete, audit & restore |
| **Phase 4** | UI & Leaflet Integration (Modular React, Style System, Maps) | **COMPLETED** | Chaitanya UI ported into typed components, Leaflet interactive map, audit views |
| **Phase 5** | Production Readiness & Data Retention | **PLANNED** | Scheduled cleanup runbook, secret management, backup & restore drill |
| **Phase 6** | Release Verification & Acceptance Tests | **PLANNED** | Full test matrix execution, Playwright journeys, cross-platform validation |
| **Phase 7** | Optional Future YOLOv8n / Gemini Verification | **DEFERRED** | Pluggable vision validation adapter (no GPU required for initial V2 release) |
| **Phase 8** | PWA & Native App Readiness | **DEFERRED** | Offline draft contract, background sync readiness |

---

## 2. Completed Milestones

### Phase 0: Baseline & Architecture Decisions
- [x] Complete inventory of `main` branch capabilities (FastAPI, PostGIS, Alembic migrations 0000–0009, 6-area pilot geometry, duplicate grouping, priority scoring, staff queues, repair lifecycle).
- [x] Complete inventory of `chaitanya's-UI` branch (Rich DM Sans/Manrope style system, multi-step intake wizard, interactive Leaflet map, Nigam/Admin review panel).
- [x] Documented architectural decisions in `docs/DECISIONS.md`.
- [x] Defined complete screen-to-API contract mapping in `docs/SCREEN_API_MAPPING.md`.
- [x] Formalized persistence and data preservation policy in `docs/PERSISTENCE_POLICY.md`.
- [x] Initialized clean directory scaffolding in `V2/` without touching original repository.

### Phase 1: Reproducible Docker Foundation
- [x] Packaged `compose.yaml` and `compose.dev.yaml` with:
  - `web`: Nginx / Vite frontend gateway with same-origin `/api/v1/` reverse proxy.
  - `api`: FastAPI service connecting to PostGIS and worker outbox.
  - `worker`: Python background processor for validation leases, admission, and scoring.
  - `db`: PostgreSQL 16 + PostGIS with persistent named volume `v2_postgres_data`.
  - `migrate`: Automated one-shot Alembic migration runner on startup.
  - `mailbox`: Inbucket development mailbox on port 9000 for email verification & reset flows.
- [x] Created `infrastructure/docker/web.Dockerfile`, `infrastructure/docker/api.Dockerfile`, `infrastructure/docker/worker.Dockerfile`, and `infrastructure/docker/nginx.conf`.
- [x] Created environment templates (`.env.example`) and comprehensive `README.md`.

### Phase 2 & Phase 3: Backend Reliability, Google Auth, Moderation & Prioritisation
- [x] Added Alembic migration `0010_v2_features.py`:
  - Added `email`, `password_hash`, `email_verified`, `role` to `users` table.
  - Added `deleted_at`, `deleted_by`, `deletion_reason` to `reports` table.
  - Added `moderation_events` table for auditable soft delete, restore, and status override logs.
- [x] Added Alembic migration `0011_suspicious_and_traffic_weights.py`:
  - Added `is_suspicious` (boolean) and `suspicious_reason` (text) to `reports` table.
  - Added `traffic_weight` (double precision) to `areas` table with Bengaluru high-congestion zone weighting (1.25x for Silk Board / South Central, 1.15x for Koramangala / North Central & Northeast, 1.15x for HSR / Southeast).
- [x] Implemented exclusive Google Sign-In:
  - Created `/api/v1/auth/google` in `routes/auth_routes.py` verifying Google credentials, auto-provisioning citizen accounts locked to `google:{sub}`, and issuing signed JWT sessions.
  - Removed traditional email/password registration to prevent credential stuffing and fake citizen accounts.
- [x] Implemented Model Validation Suspicious Mismatch Rule in `domain/validation.py` and `jobs.py`:
  - If visual detector category contradicts the citizen's claimed category (or model confidence is low / contradictory), the complaint is flagged with `is_suspicious = true` and `suspicious_reason = "Model detection mismatch..."`.
  - Exposed `is_suspicious` and `suspicious_reason` in `ReportDetail` and complaints list responses.
- [x] Implemented Bengaluru Traffic-Heavy Zone Prioritisation in `domain/scoring.py` and `domain/priority.py`:
  - Applied `zone_traffic_weight` multipliers to base priority scores, capped at 100.
  - Appended explainable `traffic_heavy_zone_boost` flag in priority snapshots.
- [x] Created `routes/complaints_routes.py` with:
  - Admin soft delete endpoint: `DELETE /api/v1/reports/{report_id}`.
  - Admin restore endpoint: `POST /api/v1/reports/{report_id}/restore`.
  - Admin deleted complaints view: `GET /api/v1/reports/deleted`.
  - Paginated & filtered complaints feed: `GET /api/v1/complaints`.

### Phase 4: UI & Leaflet Map Integration
- [x] Updated UI to support **Sign in with Google exclusively** with dedicated Google branding and one-click authentication.
- [x] Added visual `⚠️ Suspicious` badge in Overview table and an amber warning alert in Complaint Detail modal for model/claim mismatches.
- [x] Added "Flagged Suspicious" metric counter to Overview dashboard.
- [x] Ported complete design system from `chaitanya's-UI`: DM Sans and Manrope typography, teal/navy palette, responsive sidebar, cards, badges, modal dialogs into `apps/web/src/style.css`.
- [x] Ported Leaflet street map into typed component `apps/web/src/components/ComplaintMap.tsx`.
- [x] Ported duplicate grouping controls into `apps/web/src/components/Grouping.tsx`.
- [x] Unified frontend client in `apps/web/src/services.ts`.
- [x] **Faithful Chaitanya UI Restoration:**
  - Removed conflicting Tailwind CSS preflight to preserve Chaitanya's exact layout, fonts, cards, and modal drawer.
  - Interactive Leaflet street map on the left and recent complaints list on the right.
- [x] **Demo Admin & Demo Citizen Accounts:**
  - Added one-click Demo Admin (`admin@nagarsaathi.gov.in`) with review/moderation permissions and Demo Citizen (`citizen@gmail.com`).
  - Added `/api/v1/auth/demo-login` and `/api/v1/auth/login` endpoints with automatic role assignment.
- [x] **Role-Based Admin Protection:**
  - Restricted complaint review (status, priority), soft deletion, and duplicate management strictly to `admin` / `nigam` accounts.
  - Citizen accounts have clean, read-only receipt tracking without moderation controls.
- [x] **Deduplication: Delete All Duplicates & Keep Only 1:**
  - Added backend endpoint `POST /api/v1/reports/{report_id}/deduplicate-keep-one`.
  - Added "🗑️ Delete All Duplicates (Keep Only This Report)" button in the deduplication drawer with transactional soft-deletion, audit logging, and issue count refresh.
