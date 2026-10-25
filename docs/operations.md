# Local operations

Checkpoint 9 adds `scripts/release_validation.py` for isolated fixtures, restore and load
checks, plus `scripts/maintenance.py` (dry-run unless `--apply`). Cleanup retains attached
report/repair evidence and archive history. Orphan files must be over an hour old and use
server-generated UUID paths. See `release-validation.md` for commands and measured limits.
Default/example PostgreSQL URLs use `127.0.0.1` for the IPv4-only Docker binding; custom
environment URLs remain under user control. Stop/restart services around migrations.

Checkpoint 8 requires migration `0009`. Stop API/worker before applying migrations and
restart afterwards: prepared `SELECT *` plans on long-lived connections may become invalid
when columns are added. Operator uploads are private; `media.repair_issue_id` distinguishes
repair evidence from citizen evidence. Archive is a timestamp, not deletion. The Southwest
demo operator can use `/work`; the demo admin/reviewer independently verifies on issue details.

Checkpoint 7 requires migration `0008` and an API restart. It adds disposable staff queue
captures, filtered `/staff` browsing, `/staff/areas` counts and assignment on issue details.
No new provider or external map account is required. Maps show synthetic outlines and this
page's issue pins; the list continues working if map loading fails. Apply `alembic upgrade
head` before restarting. The priority worker continues its existing refresh responsibilities.

Queue captures expire after 15 minutes. A new first-page request removes the caller's expired
captures and their items; abandoned accounts' expired metadata needs the broader checkpoint 9
maintenance policy. Captures contain IDs/revisions/counts, not photos or citizen descriptions.
Database count/order materialization is capped at 10,000 matches; this is a correctness bound,
not a measured throughput guarantee. Load measurements remain checkpoint 9. Assignment to the
Southwest demo operator can be exercised now; operator work/resolution screens remain 8.

Through checkpoint 5, the worker handles validation and issue admission. Start it with
`.venv/Scripts/python.exe -m worker`; `--once` handles one ready job. Apply migrations
through `0006` before restarting the API/worker. Priority refresh jobs are intentionally
left pending for checkpoint 6. Demo automatic linking remains disabled in every category.

Checkpoint 6 adds priority refresh to that same worker; run migrations through `0007`,
rerun the non-destructive seed and restart API/worker. The seed creates the initial
`demo-priority-v1` epoch only when the pilot has no active epoch; it never resets a reviewed
policy. POI/policy/snapshot records are immutable. Re-running the seed skips sealed existing
POIs. A new POI dataset must be imported as a new snapshot before choosing it for preview.

The scheduler checks for pending/stale age scores in batches of at most 100. It enqueues
revision/epoch/15-minute-bucket jobs; the worker reschedules a changed revision/epoch and
retries failures three times. Last scores remain visible as stale; no issue disappears due
to a refresh failure. Policy activation recomputes all active issues in a single transaction
under a pilot lock and changes the complete epoch atomically. This is suitable for the local
pilot; larger-data activation duration and refresh throughput will be measured in checkpoint 9.
The ranking endpoint uses a repeatable-read transaction to avoid mixing epochs during a switch.

The fictional POI snapshot is explicitly incomplete, so its default exposure is 0.50 with
an unknown-context flag. Complete coverage must include the full configured 200-metre search
neighbourhood; a point inside the coverage polygon alone is insufficient. Major-road exposure
requires a trusted road geometry within the policy's 10-metre default tolerance. Five or more
eligible reporters received within 60 seconds flag burst review; the flag does not change
the score. Demo tokens identify accounts, not proven distinct people.

Duplicate rule `conservative-v1` uses category radii in `config/categories.yaml`. Known
uncertainty expands retrieval by at most 25 metres; positions worse than 25 metres require
review. Unknown quality requires an explicit human location decision. Nonzero uncertainty
disables asset auto-linking even if that category is explicitly enabled. Trusted inventory
IDs are assigned only through scoped human review; no inventory importer is connected.
Pilot/category advisory locks serialize admission/reclassification/link/merge/split.
Deferred final-state constraints reject orphan admissions; links can only be ended,
never rewritten or deleted. Source aliases and events retain every grouping decision.

Bind the development web/API servers to loopback. Compose exposes PostGIS on
`127.0.0.1:55432` and stores data in the named `postgres_data` volume. The development
password in `.env.example` is an explicitly public demo value; it is not a real secret.

The `.env`, local media, caches, build outputs and installed dependencies are ignored
by Git. Do not commit citizen images, tokens, provider keys or private database URLs.
All seeded geography and POIs are explicitly synthetic demo fixtures.

If readiness fails, inspect `/api/v1/health/ready`. Start Docker Desktop, then
`docker compose up -d --wait` for a failed PostGIS check. A failed storage check means
the configured private directory could not be written/read. The API shell can serve
configuration without database readiness, but future admission must require a
working database.

Run `.venv/Scripts/alembic.exe upgrade head`, then
`.venv/Scripts/python.exe scripts/seed_demo.py` after starting PostGIS. The seed
requires demo/test mode and a local demo/test database. It preserves existing rows;
changing a polygon requires a new boundary version. Its transaction rejects gaps
and overlapping area interiors. The six polygons are proposed test areas, not official
ward boundaries. Shared edges/corners belong to the covering area with the smallest
area code in PostgreSQL's `C` ordering.

POIs are fictional and their coverage is marked incomplete. Their 500 m coverage
margin is a spatial fixture, not evidence of real-world coverage. Category settings
are editable demo assumptions and automatic merging is disabled.

The migrations enforce foreign keys, lifecycle constraints, immutable audit/event
rows, one active report link and canonical area ownership. Distance queries use
PostGIS geography in metres and may cross area borders. Backup/restore verification
and operational workflows are not yet built.

Integration tests need permission to create a disposable local test database. The
tests explicitly guard their target and drop only their uniquely generated database.
Use a dedicated test server/account if the local demo account lacks this permission.

`../Checkpoints/checkpoint-NN.zip` contains the cumulative source at each completed
checkpoint; the adjacent JSON records file and ZIP SHA-256 hashes. The archive script
checks ZIP integrity and refuses to overwrite an existing checkpoint.

The worker now processes leased validation jobs. Run `python -m worker --once` for
one job, `--check` for readiness only, or no flag for the polling worker. Accepted
located reports enqueue admission work; that handler arrives in checkpoint 5.
The synthetic photo catalog is `fixtures/photo-validation.json`; it intentionally
contains no automatic acceptance hashes. `config/label-mapping.yaml` declares known
provider-version aliases. Ordinary photos go to human review. There is no model/GPU
dependency or externally exposed validation callback.
Checkpoint 2 adds authentication, uploads and persistent report APIs. Rerun migrations
and the demo seed to provision the five public demo identities. Seeding does not
rewrite existing users or restore revoked roles. Reviewer/operator demo grants are
scoped to Southwest. Operators currently receive no private citizen report access;
their repair-task permissions arrive with the staff/work lifecycle.

Original photos and metadata-free display JPEGs are stored privately under server
UUID directories. Do not expose `.local/media` as a static web directory. Access the
display copy through the authenticated media endpoint. Completion rechecks hashes
and decoding; submission rechecks stored hashes and attaches evidence transactionally.
Unattached uploads expire after one hour by default. Expiry prevents attachment;
it does not erase retained report evidence or imply a privacy retention policy.
Expired-file cleanup, crash-orphan reconciliation, distributed rate limiting and
backup/restore testing remain checkpoint 9 work.

OIDC configuration requires HTTPS issuer/JWKS URLs and an audience. The verifier
allows RS256/ES256, requires signature, issuer, audience, subject, issue time and
expiry, and checks database account activity/roles on every request. It fails closed
when keys cannot be obtained. Identities must be provisioned in `users.auth_subject`
with database role grants; no token/client role claim grants permission. No hosted
identity account has been connected. Production startup still blocks until validation
and rollout gates are implemented and reviewed.
