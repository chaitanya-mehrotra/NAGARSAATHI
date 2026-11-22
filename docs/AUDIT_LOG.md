# Audit trail

Every report has a permanent history. Nothing is written twice: the `audit_log` database view reads
the existing append-only tables (`reports`, `validation_results`, `moderation_events`, `issue_events`,
`audit_events`, `issue_report_links`) and presents them in one shape.

| Endpoint | Who | What |
|---|---|---|
| `GET /api/v1/reports/{id}/history` | owner or staff | Oldest-first timeline. Citizens get only the step and resulting state (no staff names, reasons or model labels). Someone else's report is a 404. |
| `GET /api/v1/audit` | admin | Newest-first, filters `action`, `source`, `actor_id`, `report_id`, `since`, `until` (whole days, pilot time), paged with `limit` and `before`. |
| `GET /api/v1/audit/export.csv` | admin | Same filters, up to 20,000 rows; cells that start with `= + - @` are neutralised for spreadsheets. |

In the web app: a **History** panel in every complaint drawer, and an **Audit Log** page for admins.

Migration `0014` also fixed `deduplication_delete` (rejected by the table's CHECK), made
`moderation_events` append-only, and stopped it being deleted along with its report.
Admin status changes on an accepted report now also appear in the issue's own timeline.
