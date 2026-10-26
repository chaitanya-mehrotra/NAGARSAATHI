"""Conservative issue grouping. Visual resemblance suggests; exact local reuse links."""
import hashlib
import math

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
    row = db.execute("SELECT MIN(id) AS id FROM reports WHERE issue_id=?", (issue_id,)).fetchone()
    if row["id"] is None:
        db.execute("DELETE FROM duplicate_candidates WHERE issue_id=?", (issue_id,))
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
    row = db.execute(
        """SELECT i.*, COUNT(r.id) AS report_count, COUNT(DISTINCT r.user_id) AS reporter_count,
        COUNT(DISTINCT COALESCE(r.image_sha256, 'legacy:' || r.id)) AS unique_photo_count,
        MAX(r.created_at) AS last_report_at
        FROM issues i JOIN reports r ON r.issue_id=i.id WHERE i.id=? GROUP BY i.id""", (issue_id,),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["published"] = bool(result["published"])
    result["photo_url"] = f"/issues/{issue_id}/photo"
    result["description"] = db.execute("SELECT description FROM reports WHERE id=?", (row["representative_report_id"],)).fetchone()["description"]
    # Representative identity is an internal relationship, not municipal report access.
    result.pop("representative_report_id")
    return result
