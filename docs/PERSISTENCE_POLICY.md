# NAGARSAATHI V2 — Persistence & Data Preservation Policy

**Date:** 26 October 2026  
**Status:** Approved Policy

---

## 1. Principles of Persistence

1. **No Inactivity Deletion:**
   The NAGARSAATHI V2 platform shall never delete, purge, or truncate citizen accounts, submitted complaints, physical issues, evidence photos, or audit trails solely due to periods of system or user inactivity.

2. **Container & Volume Lifecycle Isolation:**
   - Docker container teardown, rebuild, or image upgrades (`docker compose down && docker compose up`) MUST preserve all data stored in named Docker volumes:
     - `v2_postgres_data`: Stores PostgreSQL database records, PostGIS geospatial tables, users, and Alembic migration state.
     - `v2_media_data`: Stores original private uploaded photos and generated display JPEGs.
     - `v2_identity_data`: Stores identity configuration and user credentials.
   - Destructive volume removal (`docker compose down -v`) is strictly prohibited in standard operational and update scripts.

3. **Storage Decoupling:**
   - Image bytes and media files are stored on the filesystem / object storage adapter with content-addressed SHA-256 keys, NOT directly inside PostgreSQL database rows.
   - Database tables store metadata, ownership, SHA-256 digests, dimensions, and relative storage paths.
   - Backups must synchronize both database dumps AND media directories together to prevent orphaned records or missing photo files.

4. **Complaint Soft Deletion vs. Purge:**
   - Standard administrative deletion operates as a **Soft Deletion**:
     - Sets `deleted_at = NOW()`, `deleted_by = <admin_user_id>`, and records a mandatory `deletion_reason`.
     - Removes the complaint from public queries, citizen views, and active queue counts.
     - Transactionally decrements the associated physical issue's report count and recalculates priority.
     - Preserves original files and relational records so an administrator can perform an audited **Restore**.
   - **Permanent Purge**:
     - Available only through an explicit, elevated administrative workflow with double confirmation.
     - Cleans up media files, anonymizes personal data, and writes a minimal immutable audit tombstone.

5. **Local Portability vs. Shared Deployments:**
   - When running on a friend's personal computer via Docker Compose, that local instance maintains its own local named volumes.
   - For multi-user team evaluation where all friends share the same live reports, a single shared V2 backend instance must be hosted and shared via URL. Live database files are never synced over cloud file synchronizers (such as OneDrive or Dropbox).
