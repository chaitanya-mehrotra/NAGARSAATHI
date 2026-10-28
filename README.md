# NAGARSAATHI V2 — Next-Generation Civic Complaint & Prioritisation Platform

NAGARSAATHI V2 bridges the high-integrity domain model, geospatial PostGIS calculations, duplicate grouping, and repair verification of `main` with the modern responsive UI, Leaflet street maps, and streamlined reporting wizard of Chaitanya's interface.

---

## 1. Quick Start with Docker (Friends & Team Onboarding)

Run the complete platform without installing Python, Node.js, or PostgreSQL directly on your computer:

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows / Mac) or Docker Engine with Compose (Linux).

### Steps
1. Open a terminal in this `V2/` directory:
   ```bash
   cp .env.example .env
   ```
2. Start the entire container stack:
   ```bash
   docker compose up --build -d
   ```
3. Open your browser:
   - **Web App & Citizen Portal:** [http://localhost:5173](http://localhost:5173)
   - **Interactive API Documentation:** [http://localhost:5173/docs](http://localhost:5173/docs)
   - **Local Development Mailbox:** [http://localhost:9000](http://localhost:9000)

   The first build downloads PyTorch (CPU) for the photo-validation worker and takes several
   minutes. Demo accounts are on by default (`APP_MODE=demo`). To enable Google sign-in, set
   `GOOGLE_CLIENT_ID` in `.env` first (see [`docs/GOOGLE_SIGN_IN.md`](docs/GOOGLE_SIGN_IN.md)).
   To run the API, worker and web app without Docker, see
   [`docs/RUN_LOCALLY.md`](docs/RUN_LOCALLY.md).

4. To stop the application:
   ```bash
   docker compose stop
   ```
   *(Data is securely preserved in named Docker volumes `v2_postgres_data` and `v2_media_data`. Starting up again preserves all accounts, complaints, and photos).*

---

## 2. Platform Architecture

```text
Browser / Mobile Web
  │
  ▼
[Nginx Web Gateway (Port 5173)]
  │
  ├── /api/v1/ ───────────────► [FastAPI Backend (Port 8000)]
  │                                   │
  │                                   ├── PostgreSQL 16 + PostGIS
  │                                   ├── Private Media Adapter (.local/media)
  │                                   └── Durable Outbox Jobs
  │                                                │
  │                                                ▼
  │                                      [Background Worker]
  │                                      - YOLO photo validation
  │                                      - Priority Engine
  │                                      - Duplicate Candidates
  │
  └── Static React App (DM Sans/Manrope, Leaflet Street Map, Reporting Wizard)
```

---

## 3. Preserved Strengths & Modernized Features

- **Geospatial Pilot Envelope:** Southeast Bengaluru (6 synthetic operational areas: Southwest, South Central, Southeast, Northwest, North Central, Northeast).
- **Report vs. Issue Distinction:** Multiple citizen reports about the same pothole or garbage accumulation are safely linked to a shared repair issue with independent eligible-reporter counts.
- **Explainable Priority Scoring:** Calculates weighted priority based on category severity, proximity to schools/hospitals/transit, urgency, and duplicate support.
- **Admin & Moderation Lifecycle:** Dedicated admin dashboard with complaint triage, duplicate grouping/splitting, work orders, independent repair verification, and audited soft delete / restore.
- **Photo Validation (YOLO11n):** A trained pothole/waterlogging detector runs on CPU in the worker (no GPU or paid API). A photo that does not match the chosen category, or in which nothing is detected, is flagged and held for human review; nothing is rejected automatically. The detector only knows potholes and waterlogging, so other categories always go to human review.
- **Google Sign-In:** Verified Google ID tokens with a one-use server nonce; demo accounts exist only in demo/test mode.

---

## 4. Phase Delivery Tracking

Detailed implementation milestones and architectural records are maintained in:
- [`docs/BUILD_STATUS.md`](docs/BUILD_STATUS.md): Current phase status and roadmap.
- [`docs/DECISIONS.md`](docs/DECISIONS.md): Architectural decision records (ADRs).
- [`docs/SCREEN_API_MAPPING.md`](docs/SCREEN_API_MAPPING.md): Detailed screen-to-API route specifications.
- [`docs/PERSISTENCE_POLICY.md`](docs/PERSISTENCE_POLICY.md): Data preservation and volume retention policy.
- [`docs/RUN_LOCALLY.md`](docs/RUN_LOCALLY.md): Running and testing without Docker for the app.
- [`docs/GOOGLE_SIGN_IN.md`](docs/GOOGLE_SIGN_IN.md): Setting up Google sign-in.
