# Local release candidate — checkpoint 9

The baseline citizen, reviewer and operator lifecycle is verified locally. This is synthetic
acceptance; real boundaries, matching quality, priority usefulness and municipal commitments
are not validated by these tests. Optional model integration remains checkpoint 10.

Run `.venv/Scripts/python.exe scripts/release_validation.py` with development dependencies,
Docker/PostGIS running and free port 8002. It creates uniquely named disposable databases,
migrates/seeds them and removes only its own databases. The load identity verifier requires
test mode, a local connection and the exact disposable database name pattern. Normal API
authentication does not accept load tokens. Backups/media/logs stay in an ignored unique
`.local/release-*` directory; demo complaints are not reset.

Fixture `release-v1` uses fixed UUIDs and evidence timestamps anchored to 2026-10-01:
1,000 reports, 300 issues, six areas, four main categories and 20 reporter accounts.
There are 970 admitted reports and 10 each rejected, out-of-scope and awaiting review.
Seeded human decisions are labelled synthetic; database constraints remain enabled and
snapshots use the real scoring implementation. An additional failed repair/photo verifies
retained work-history restoration. Load submissions are additional to the initial fixture.

Reference environment: Windows build 26200, AMD Ryzen 9 270 (8 cores/16 logical processors),
16,422,010,880 bytes reported RAM, Python 3.11.9, Docker PostgreSQL 17/PostGIS 3.5, one
Uvicorn process and default SQLAlchemy pool. Photos were 12×8 synthetic PNGs; production
network, large-photo and external-provider latency are not inferred. JSON records the run
timestamp, exact measurements, hardware and backup SHA-256.

At 20 concurrent distinct synthetic identities, 100 filtered queue reads measured p95
**238.68 ms** against 500 ms. Forty metadata submissions measured p95 **171.86 ms** against
1 second, excluding upload/completion. Processing them to required human review measured
p95 **1.194 seconds**; this excludes reviewer wait and does not measure automatic admission.
All 300 aged snapshots refreshed in **7.141 seconds**, with zero remaining stale snapshots.
Database restoration and hash checks passed for **1,001 originals and 1,001 derivatives**,
including the retained repair record/linkage. The optional 10,000-report test was not run.

The first queue measurement was about 3.47 seconds. Issue/snapshot reads are now batched.
Using explicit `127.0.0.1` in default/example database URLs removes the IPv6 fallback timeout
against Docker's IPv4-only port. Custom environment URLs are not rewritten. These are local
measurements for this dataset, not a general throughput guarantee.

Recovery tests kill a leased worker after an uncommitted SQL write, verify rollback, advance
lease expiry and recover without duplicate issue links. Duplicate/old revision delivery and
storage/location-resolver failure are covered. Repair verification rechecks stored hashes,
leaving resolution pending if evidence is unavailable. Maintenance dry-run/apply tests remove
only expired unattached/orphan data and retain admitted evidence; live maintenance was run
in dry-run mode only. Database/photo restoration was performed in isolated databases.

Final checks: 169 full Python tests, 18 desktop/mobile Playwright journeys, two Vitest tests,
generated contracts, TypeScript/build, strict mypy, Ruff and formatting pass. Enhanced recovery
checks pass in a three-test run; a final four-test staff run verifies photo integrity checks
with real uploads. Exact-reference lookup fixes the earlier first-50 merge-picker limit.
Browser fixtures choose an unused neighbourhood without resetting previous demo data.
Live API/worker and HTTP/PostGIS/private-storage/web/proxy smoke pass. Existing TestClient
deprecation and MapLibre bundle-size warnings remain.

Real pilot launch still needs reviewed boundaries/priority policy, human usefulness review,
real identity/providers, backup operating procedures and disabling demo sources. Production
startup stays blocked. Operator overview is limited to 50 assignments; larger operator
workloads need paging. General abandoned-account retention, distributed rate limiting,
multi-host load and real-size photo/provider measurements remain deployment work.
