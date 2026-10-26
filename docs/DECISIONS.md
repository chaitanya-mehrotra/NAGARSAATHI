# NAGARSAATHI V2 — Phase 0 Architecture Decisions & Inventory

**Date:** 26 October 2026  
**Status:** Approved & Baseline Established

---

## 1. Baseline Summary & Source Repositories

### Source 1: `main` Branch (`Civic AI/nagarsaathi`)
- **Key Strengths:**
  - Robust domain model with clear separation between a citizen **Report** (individual submission with evidence) and a physical **Issue** (shared repair task aggregating reports).
  - PostGIS geospatial envelope for Bengaluru Southeast pilot, enforcing 6 synthetic operational areas (`ST_Covers`, meter-accurate distance).
  - 10 structured Alembic migrations maintaining full referential integrity and audit records.
  - Private media adapter with SHA-256 hash deduplication and display JPEG derivative generation.
  - Explainable priority scoring engine taking into account category, urgency, location context (schools, hospitals, transit), and duplicate counts.
  - Full staff workflow: reviewer triage, assignment, operator repair upload, independent verification, and archive/reopen.
  - Asynchronous background worker using durable database outbox and leases.
- **Identified Gaps in Main:**
  - Lacks public self-registration (used demo auto-provisioned accounts).
  - Minimal UI and basic Leaflet PinMap.
  - Queues lacked cursor pagination beyond 50 items.
  - Production gates strictly prevented non-demo runs.

### Source 2: `chaitanya's-UI` Branch (`chaitanya-mehrotra/NAGARSAATHI`)
- **Key Strengths:**
  - Modern, responsive civic design system (`style.css`) using DM Sans and Manrope typography, refined teal/navy color palette, status pills, and card layouts.
  - Interactive Leaflet map (`Map.jsx`) with custom SVG pin markers, real-time geolocation with fallback, bounds fitting, and pan/zoom synchronization.
  - 3-step citizen intake wizard (Details, Photo Upload & Verification, Location Confirmation).
  - Integrated Nigam/Staff dashboard with status filters, category pills, date pickers, and duplicate grouping inspector (`Grouping.jsx`).
  - Auth modal dialog supporting user sign-up and sign-in.
- **Architectural Gaps in UI Branch:**
  - Replaced PostgreSQL/PostGIS with simple SQLite, losing spatial calculations and Alembic migrations.
  - Hardcoded API base URL (`http://127.0.0.1:8001`) with query-string bearer token passing for photos (`?token=...`).
  - Lacks independent repair verification state machine (allowed direct arbitrary status changes).
  - Hardcoded "Live" status without an active WebSocket/SSE channel.

---

## 2. Definitive Architecture Decisions for V2

### ADR 01: Core Domain & Data Layer
- **Decision:** Retain `main`'s PostgreSQL + PostGIS schema, SQLAlchemy 2 models, and Alembic migrations as the canonical persistence engine.
- **Rationale:** Municipal civic data demands spatial accuracy (WGS84 EPSG:4326), multi-report deduplication, and auditable state transitions that SQLite cannot reliably provide for production.
- **Migration Strategy:** All new features (e.g., citizen profile fields, admin soft deletion, OIDC subjects) will be added via clean additive Alembic migrations starting from `0010_v2_features.py`.

### ADR 02: Frontend Architecture & UI Porting
- **Decision:** Migrate Chaitanya's UI from the monolithic `main.jsx` (2012 lines) and JavaScript into modular, strongly-typed React 18 + TypeScript components under `apps/web/src/`.
- **Styling:** Port and preserve the complete `style.css` design system (DM Sans/Manrope, glassmorphism cards, responsive mobile drawer, accessible focus states).
- **Map:** Replace `PinMap.tsx` and MapLibre with the Leaflet interactive map implementation (`Map.jsx`), fully adapted to consume GeoJSON coordinates `[lng, lat]` and typed API contracts.

### ADR 03: Identity & Session Management
- **Decision:** Dual-mode authentication:
  1. **Local & Container Portability:** A clean FastAPI JWT auth module for self-contained team trials (email/password registration, password reset token flow, session tokens) that requires zero external third-party dependencies for initial onboarding.
  2. **Production OIDC / Google Sign-In:** Configurable Keycloak / Google OAuth2 federation broker. First-time Google login safely auto-provisions a citizen account using `(issuer, subject)` mapping without overwriting roles or hijacking accounts.
- **Security Rule:** No tokens stored in URLs. All media endpoints require authenticated session headers.

### ADR 04: Complaint Soft Deletion & Admin Governance (Section 6.5)
- **Decision:** Add explicit `deleted_at`, `deleted_by`, and `deletion_reason` columns to the `reports` table.
- **Behavior:**
  - Soft-deleted complaints are excluded from public lists, citizen portals, and active worker queues.
  - Soft deletion recalculates linked issue counts and prioritisation scores transactionally.
  - Dedicated admin-only view allows authorized administrators to audit and restore deleted complaints.
  - Permanent purge is an explicit elevated action with tombstone audit logging.

### ADR 05: Initial Validation & AI Roadmap
- **Decision:** Initial V2 ships with the robust human-review validation adapter enabled by default. No external GPU, CUDA, or paid Gemini API keys are mandatory to run the complete platform.
- **Roadmap:** Section 8's YOLOv8n detector and Gemini fallback pipeline will be implemented behind a pluggable interface in Phase 7.

### ADR 06: Exclusively Google Sign-In for Citizens
- **Decision:** Remove local email/password registration and retain Google Sign-In as the sole citizen authentication method across web and API.
- **Rationale:** Prevents password storage risks, credential stuffing, and bot spam while tying civic reports to verified real-world Google identity subjects.
- **Implementation:** Backend endpoint `POST /api/v1/auth/google` verifies Google ID tokens / OAuth profile, auto-provisions citizen records locked to `google:{sub}`, and issues secure session tokens.

### ADR 07: Suspicious Mismatch Flagging in Model Validation
- **Decision:** If the automated vision detector's predicted category contradicts the citizen's claimed category (or model confidence is below threshold / ambiguous), the report is automatically flagged as **suspicious** (`is_suspicious = true`).
- **Rationale:** Prevents fraudulent category gaming (e.g., claiming emergency street hazards for unrelated debris) while protecting against model misclassification.
- **Behavior:** Suspicious reports are held in `awaiting_review` with an elevated triage badge (`⚠️ Suspicious Mismatch`) and audit reason for supervisor verification.

### ADR 08: Traffic-Heavy Zone Prioritisation Multipliers for Bengaluru
- **Decision:** Prioritisation scoring incorporates zone traffic multipliers from the `areas` table with higher weightage for high-congestion Bengaluru bottlenecks:
  - `south_central` (Silk Board / Madiwala junction): 1.25x priority boost.
  - `north_central` (Koramangala 4th/5th Block hub): 1.15x priority boost.
  - `northeast` (Sony World / Ejipura / Inner Ring Road): 1.15x priority boost.
  - `southeast` (HSR Layout / Bellandur corridor): 1.15x priority boost.
  - Residential baseline: 1.0x.
- **Explainability:** Zone traffic boosts are transparently logged in scoring contribution factors and flags (`traffic_heavy_zone_boost`).
