# ADR 001: Reports, issues and the local application stack

Status: accepted for the development pilot, 3 October 2026.

A **report** preserves one citizen submission, its original evidence and decisions.
An **issue** represents a shared physical repair task. Five reports of one pothole
must remain five reports linked to one issue. Linked reports display the issue's
lifecycle; resolving a task archives its history rather than deleting evidence.

Use a modular FastAPI monolith with a separate Python worker and PostgreSQL/PostGIS.
Spatial ownership and duplicate queries need real metre-based geography, constraints
and transactions. SQLite will not replace geospatial integration tests. A React,
TypeScript and Vite frontend uses typed OpenAPI contracts and TanStack Query.
Tailwind, React Router, React Hook Form, Zod and MapLibre are installed for the later
screens. The checkpoint 0 shell loads public config from the API.

Adapters separate identity, photo validation, storage and reverse geocoding from the
domain. Checkpoint 2 verifies identity with a synchronous token verifier, then loads
role/area grants from the database for each request. Public fixture subjects serve
as demo bearer tokens only in demo/test mode. OIDC signatures/claims are verified
against configured JWKS; roles never come from JWT claims. Hosted identity signup
and administrative provisioning UI are not implemented. No YOLO/PyTorch dependency
is included in the application.

Runtime configuration reads the project `.env`; public pilot/category config is in
`config/demo.yaml`. Versioned polygons are migrated/seeded into PostGIS; persistent
upload/report APIs use transactional row locks and scoped idempotency keys. Priority
and repair workflows belong to later checkpoints. Public descriptions must never imply official ward
coverage, a live municipal integration, or AI-verified evidence in this demo.

Readiness queries `PostGIS_Version()` and probes private storage. Database outages
return not-ready without making liveness fail. Request IDs and structured HTTP errors
make failures traceable without exposing settings or stack traces to clients.

Uploads use bounded raw-byte requests rather than presigned external storage URLs.
The local adapter retains originals privately and creates an oriented JPEG without
EXIF; only authenticated display streams are exposed. Uploaded evidence expires
until attached. Completion checks decoding/hashes; report submission locks evidence
and rechecks availability before committing metadata, attachments, location decision
and idempotency reference together. Validation/admission remain separate operations.
An issue link and owned completed evidence are required for admission by deferred
database constraints. Production remains gated by later validation/rollout acceptance.

The user has explicitly requested a pause after every checkpoint. That instruction
overrides the plan's suggestion to proceed automatically after a passing checkpoint.
