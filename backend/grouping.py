"""Conservative issue grouping. Visual resemblance suggests; exact local reuse links."""
import hashlib
import math

from backend.policy import refresh_issue, record_event

from PIL import Image


def fingerprints(image):
    image = image.convert("RGB")
    digest = hashlib.sha256(f"{image.width}x{image.height}:".encode() + image.tobytes()).hexdigest()
    small = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = [small.getpixel((x, y)) for y in range(8) for x in range(9)]
    bits = sum((pixels[y * 9 + x] > pixels[y * 9 + x + 1]) << (y * 8 + x)
               for y in range(8) for x in range(8))
    return digest, f"{bits:016x}"


def distance_metres(lat1, lon1, lat2, lon2):
    a, b = math.radians(lat1), math.radians(lat2)
    h = math.sin((b - a) / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def new_issue(db, report):
    cursor = db.execute(
        """INSERT INTO issues(representative_report_id, issue_type, latitude, longitude, created_at, status)
        VALUES(?,?,?,?,?,?)""",
        (report["id"], report["issue_type"], report["latitude"], report["longitude"], report["created_at"], report["status"]),
    )
    return cursor.lastrowid


def sync_representative(db, issue_id):
    row = db.execute("SELECT COALESCE(MIN(CASE WHEN archived_at IS NULL THEN id END), MIN(id)) AS id FROM reports WHERE issue_id=?", (issue_id,)).fetchone()
    if row["id"] is None:
        db.execute("DELETE FROM duplicate_candidates WHERE issue_id=?", (issue_id,))
        if db.execute('SELECT 1 FROM work_orders WHERE issue_id=?',(issue_id,)).fetchone():
            # Preserve assignments/repair evidence when the last member is regrouped.
            db.execute("UPDATE issues SET published=0,publication_mode='withheld',priority_score=0,priority_reason='No linked reports; retained work history' WHERE id=?",(issue_id,))
        else:
            db.execute("DELETE FROM issues WHERE id=?", (issue_id,))
    else:
        db.execute("UPDATE issues SET representative_report_id=? WHERE id=?", (row["id"], issue_id))


def assign_report(db, report_id):
    """Called in the report-write transaction, preventing concurrent double grouping."""
    report = db.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    candidates = db.execute(
        """SELECT r.*, i.status AS issue_status FROM reports r JOIN issues i ON i.id=r.issue_id
        WHERE i.status IN ('open','in_progress') AND r.issue_type=? AND r.created_at>=?
        ORDER BY r.id""", (report["issue_type"], report["created_at"] - 30 * 86400),
    ).fetchall()
    suggestions = {}
    exact = None
    for other in candidates:
        distance = distance_metres(report["latitude"], report["longitude"], other["latitude"], other["longitude"])
        # Require agreement with the issue anchor too; do not grow a chain down a road.
        anchor = db.execute("SELECT latitude, longitude FROM issues WHERE id=?", (other["issue_id"],)).fetchone()
        if distance > 30 or distance_metres(report["latitude"], report["longitude"], anchor["latitude"], anchor["longitude"]) > 30:
            if report["image_sha256"] and report["image_sha256"] == other["image_sha256"]:
                suggestions[other["issue_id"]] = "reused_photo_different_location"
            continue
        if report["image_sha256"] and report["image_sha256"] == other["image_sha256"]:
            exact = other
            break
        similar = bool(report["image_dhash"] and other["image_dhash"] and
                       (int(report["image_dhash"], 16) ^ int(other["image_dhash"], 16)).bit_count() <= 6)
        suggestions[other["issue_id"]] = "nearby_similar_photo" if similar else "nearby_same_category"

    issue_id = exact["issue_id"] if exact else new_issue(db, report)
    db.execute("UPDATE reports SET issue_id=?, duplicate_of=?, grouping_reason=? WHERE id=?",
               (issue_id, exact["id"] if exact else None, "exact_photo_nearby" if exact else "new_issue", report_id))
    db.execute("UPDATE reports SET status=(SELECT status FROM issues WHERE id=?) WHERE id=?", (issue_id, report_id))
    if not exact:
        for target_id, reason in suggestions.items():
            db.execute("INSERT OR IGNORE INTO duplicate_candidates VALUES(?,?,?)", (report_id, target_id, reason))
    return issue_id


def summary(db, issue_id):
    refresh_issue(db, issue_id)
    row = db.execute(
        """SELECT i.*, COUNT(r.id) AS report_count, COUNT(DISTINCT r.user_id) AS reporter_count,
        COUNT(DISTINCT COALESCE(r.image_sha256, 'legacy:' || r.id)) AS unique_photo_count,
        SUM(r.id IS NOT NULL AND r.archived_at IS NULL) AS active_report_count,
        COUNT(DISTINCT CASE WHEN r.archived_at IS NULL THEN r.user_id END) AS active_reporter_count,
        SUM(r.id IS NOT NULL AND r.archived_at IS NOT NULL) AS archived_report_count,
        MAX(r.created_at) AS last_report_at
        FROM issues i LEFT JOIN reports r ON r.issue_id=i.id WHERE i.id=? GROUP BY i.id""", (issue_id,),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["published"] = bool(result["published"])
    result["photo_url"] = f"/issues/{issue_id}/photo"
    result["description"] = db.execute("SELECT description FROM reports WHERE id=?", (row["representative_report_id"],)).fetchone()["description"]
    # Representative identity is an internal relationship, not municipal report access.
    result.pop("representative_report_id")
    order = db.execute('SELECT team,version FROM work_orders WHERE issue_id=?',(issue_id,)).fetchone()
    result['work_order'] = dict(order) if order else None
    result['pending_repair'] = bool(db.execute("SELECT 1 FROM repair_evidence WHERE issue_id=? AND state='pending'",(issue_id,)).fetchone())
    return result


def nearby_reports(db, report):
    rows = db.execute("""SELECT r.* FROM reports r JOIN issues i ON i.id=r.issue_id
        WHERE r.id<>? AND r.archived_at IS NULL AND r.issue_type=? AND r.verification_status='supported'
        AND i.status IN ('open','in_progress') AND r.created_at>=? ORDER BY r.id DESC""",
        (report['id'], report['issue_type'], report['created_at'] - 30 * 86400)).fetchall()
    return [r for r in rows if distance_metres(report['latitude'], report['longitude'], r['latitude'], r['longitude']) <= 30]


def apply_automatic_grouping(db, report_id, visual_matches, visual_enabled=False):
    """Server decides membership using trusted stored category, time, location and evidence."""
    report = db.execute('SELECT * FROM reports WHERE id=?', (report_id,)).fetchone()
    old_id = report['issue_id']
    nearby = nearby_reports(db, report)
    valid = []
    copies = db.execute('SELECT latitude,longitude FROM reports WHERE id<>? AND archived_at IS NULL AND image_sha256=?',
                        (report_id, report['image_sha256'])).fetchall()
    far_copy = any(distance_metres(report['latitude'], report['longitude'], r['latitude'], r['longitude']) > 30 for r in copies)
    for other in nearby:
        anchor = db.execute('SELECT latitude,longitude FROM issues WHERE id=?', (other['issue_id'],)).fetchone()
        if distance_metres(report['latitude'], report['longitude'], anchor['latitude'], anchor['longitude']) > 30:
            continue
        if report['image_sha256'] == other['image_sha256']:
            valid.append((other, 'exact_photo_nearby'))
        elif visual_enabled:
            evidence = next((m for m in visual_matches if m['report_id'] == other['id']), None)
            if evidence and evidence['inliers'] >= 20 and evidence['inlier_ratio'] >= .8 and evidence['coverage'] >= .25:
                valid.append((other, 'orb-defect-v1'))
    issue_ids = {r['issue_id'] for r, _ in valid}
    supported = report['verification_status'] == 'supported'
    ambiguous = bool(far_copy or len(issue_ids) > 1 or (nearby and not valid))
    if supported and not ambiguous and len(issue_ids) == 1:
        target, reason = valid[0]
        issue_id = target['issue_id']
    else:
        issue_id = old_id or new_issue(db, report)
        reason = 'ambiguous_duplicate' if supported and ambiguous else ('new_supported_issue' if supported else 'unconfirmed_evidence')
    if reason == 'ambiguous_duplicate':
        db.execute("UPDATE reports SET verification_status='needs_review', verification_reason=? WHERE id=?",
                   ('Photo evidence exists but location or duplicate matching needs review; your report is retained', report_id))
    db.execute('UPDATE reports SET issue_id=?,duplicate_of=NULL,grouping_reason=?,status=(SELECT status FROM issues WHERE id=?) WHERE id=?',
               (issue_id, reason, issue_id, report_id))
    if old_id and old_id != issue_id:
        sync_representative(db, old_id)
    db.execute('DELETE FROM duplicate_candidates WHERE report_id=?', (report_id,))
    for candidate in nearby:
        if candidate['issue_id'] != issue_id:
            db.execute('INSERT OR IGNORE INTO duplicate_candidates VALUES(?,?,?)', (report_id, candidate['issue_id'], 'requires_visual_review'))
    # Previously forwarded historical/manual decisions are never silently overturned.
    db.execute("UPDATE issues SET publication_mode='automatic' WHERE id=? AND publication_mode='legacy' AND published=0", (issue_id,))
    refresh_issue(db, issue_id)
    record_event(db, issue_id, 'automatic_processing', {'report_id': report_id, 'grouping_reason': reason, 'policy': 'grouping-v1'})
    return issue_id
