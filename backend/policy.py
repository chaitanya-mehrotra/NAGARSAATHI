"""Versioned, explainable demand policy. This is not a physical-danger estimator."""
import json
import time

PRIORITY_POLICY = "demand-age-v1"
VERIFICATION_POLICY = "visual-evidence-v1"
SUPPORT_THRESHOLD = 0.55  # Provisional operating point; not a calibrated probability.


def verification(claimed, detections):
    labels = {d['label'] for d in detections if d['confidence'] >= SUPPORT_THRESHOLD}
    required = {'pothole', 'waterlogging'} if claimed == 'both' else {claimed}
    if required <= labels:
        return 'supported', 'Photo contains supporting visual evidence; authenticity is not established'
    if not detections:
        return 'needs_review', 'The photo could not be confirmed automatically; your report is retained for review'
    return 'needs_review', 'The photo needs review because the evidence is uncertain or differs from the selected category'


def priority(reporter_count, first_seen, now=None):
    now = int(time.time()) if now is None else now
    days = max(0, now - first_seen) / 86400
    demand = 70 * min(reporter_count / 10, 1)
    waiting = 30 * min(days / 7, 1)
    score = round(demand + waiting, 2)
    return score, f'{reporter_count} distinct accounts: {demand:.1f}/70; waiting {days:.1f} days: {waiting:.1f}/30. Demand and age only, not physical severity.'


def refresh_issue(db, issue_id, now=None):
    row = db.execute("""SELECT i.*, MIN(r.created_at) AS first_seen,
        COUNT(DISTINCT CASE WHEN r.verification_status='supported' THEN r.user_id END) AS eligible_reporters,
        SUM(r.verification_status='supported') AS supported_reports
        FROM issues i JOIN reports r ON r.issue_id=i.id WHERE i.id=? GROUP BY i.id""", (issue_id,)).fetchone()
    if not row:
        return
    score, reason = priority(row['eligible_reporters'], row['first_seen'], now)
    if row['status'] in ('resolved', 'rejected'):
        score, reason = 0, 'Closed issue; excluded from active priority queue'
    mode = row['publication_mode']
    if mode == 'automatic':
        published = int(row['supported_reports'] > 0)
    else:
        published = row['published']
    db.execute('UPDATE issues SET priority_score=?, priority_reason=?, priority_policy_version=?, published=? WHERE id=?',
               (score, reason, PRIORITY_POLICY, published, issue_id))


def record_event(db, issue_id, event, details, actor_id=None):
    db.execute('INSERT INTO issue_history(issue_id,actor_id,event,details,created_at) VALUES(?,?,?,?,?)',
               (issue_id, actor_id, event, json.dumps(details), int(time.time())))
