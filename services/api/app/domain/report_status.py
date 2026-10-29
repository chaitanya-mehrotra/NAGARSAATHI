"""The one status a citizen sees for a report.

Accepted reports follow their issue's lifecycle; everything else shows the report's own
state. The complaints list, its status filter, the metrics counters and the detail view
all use this so their numbers agree.
"""

# Expects the report as `r` and its active issue (if any) as `i`; see REPORT_WITH_ISSUE_SQL.
DISPLAY_STATUS_SQL = """
    CASE
        WHEN r.state = 'admitted' AND i.status = 'resolved' THEN 'resolved'
        WHEN r.state = 'admitted' AND i.status IN ('assigned', 'in_progress', 'resolution_pending')
            THEN 'in_progress'
        WHEN r.state = 'admitted' THEN 'open'
        WHEN r.state IN ('submitted', 'processing', 'awaiting_review', 'processing_failed')
            THEN 'awaiting_review'
        ELSE r.state
    END
"""

REPORT_WITH_ISSUE_SQL = """
    reports r
    LEFT JOIN issue_report_links irl ON irl.report_id = r.id AND irl.active
    LEFT JOIN issues i ON i.id = irl.issue_id
"""

DISPLAY_STATUSES = ("awaiting_review", "open", "in_progress", "resolved", "out_of_scope", "rejected")

# Reviewers move a report between these report states before it is accepted...
REPORT_REVIEW_STATUSES = {"awaiting_review", "out_of_scope", "rejected"}
# ...and an accepted report's issue between these.
ISSUE_REVIEW_STATUSES = {"open", "in_progress", "resolved"}
