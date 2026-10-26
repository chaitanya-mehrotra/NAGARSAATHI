"""Shared repair issues: individual reports stay private to platform administrators."""
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

try:
    from backend.accounts import current_user, admin_user
    from backend.database import connect
    from backend.grouping import new_issue, summary, sync_representative
    from backend.reports import resolve_photo_user
    from backend import reports
    from backend.policy import refresh_issue, record_event
except ImportError:
    from accounts import current_user, admin_user
    from database import connect
    from grouping import new_issue, summary, sync_representative
    from reports import resolve_photo_user
    import reports
    from policy import refresh_issue, record_event

router = APIRouter(prefix="/issues", tags=["Consolidated issues"])


def require_staff(user):
    if user["role"] not in ("admin", "nigam"):
        raise HTTPException(403, "Staff account required")


def accessible_issue(db, issue_id, user):
    require_staff(user)
    issue = summary(db, issue_id)
    if issue is None or (user["role"] == "nigam" and not issue["published"]):
        raise HTTPException(404, "Issue not found")
    return issue


@router.get("")
def list_issues(limit: int = Query(40, ge=1, le=100), offset: int = Query(0, ge=0),
                search: str = "", issue: str = "", status: str = "", sort: str = "priority",
                user: dict = Depends(current_user)):
    require_staff(user)
    clauses, params = ["EXISTS(SELECT 1 FROM reports r WHERE r.issue_id=i.id)"], []
    if user["role"] == "nigam":
        clauses.append("i.published=1")
    if issue:
        clauses.append("i.issue_type IN (?, 'both')")
        params.append(issue)
    if status:
        clauses.append("i.status=?")
        params.append(status)
    else:
        clauses.append("i.status IN ('open','in_progress')")
    if search:
        # Search only the representative description visible in the consolidated view.
        clauses.append("EXISTS(SELECT 1 FROM reports r WHERE r.id=i.representative_report_id AND r.description LIKE ?)")
        params.append(f"%{search}%")
    where = " AND ".join(clauses)
    with connect() as db:
        for row in db.execute('SELECT id FROM issues').fetchall():
            refresh_issue(db, row['id'])
        total = db.execute(f"SELECT COUNT(*) FROM issues i WHERE {where}", params).fetchone()[0]
        ordering = "CASE WHEN i.status IN ('resolved','rejected') THEN 1 ELSE 0 END, i.priority_score DESC, i.created_at ASC, i.id ASC" if sort == 'priority' else f"i.id {'ASC' if sort == 'oldest' else 'DESC'}"
        ids = db.execute(f"SELECT i.id FROM issues i WHERE {where} ORDER BY {ordering} LIMIT ? OFFSET ?",
                         [*params, limit, offset]).fetchall()
        return {"items": [summary(db, row["id"]) for row in ids], "total": total}


@router.get("/{issue_id}")
def get_issue(issue_id: int, user: dict = Depends(current_user)):
    with connect() as db:
        return accessible_issue(db, issue_id, user)


@router.get("/{issue_id}/photo")
def issue_photo(issue_id: int, user: dict = Depends(resolve_photo_user)):
    with connect() as db:
        accessible_issue(db, issue_id, user)
        row = db.execute("SELECT r.photo_name FROM reports r JOIN issues i ON r.id=i.representative_report_id WHERE i.id=?", (issue_id,)).fetchone()
    path = reports.DATA_DIR / "photos" / row["photo_name"]
    if not path.is_file():
        raise HTTPException(404, "Photo not found")
    return FileResponse(path, media_type="image/png")


class Publication(BaseModel):
    published: bool


@router.patch("/{issue_id}/publication")
def publication(issue_id: int, body: Publication, user: dict = Depends(admin_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        accessible_issue(db, issue_id, user)
        if body.published and not db.execute("SELECT 1 FROM reports WHERE issue_id=? AND verification_status='supported'", (issue_id,)).fetchone():
            raise HTTPException(409, 'Review supporting evidence before publishing this issue')
        db.execute("UPDATE issues SET published=?,publication_mode=? WHERE id=?", (int(body.published), 'manual' if body.published else 'withheld', issue_id))
        record_event(db, issue_id, 'publication', {'published':body.published}, user['id'])
        return summary(db, issue_id)


class Grouping(BaseModel):
    issue_id: int | None = Field(default=None, gt=0)
    reason: str = Field(min_length=1, max_length=1000)


@router.patch("/report/{report_id}/group")
def move_report(report_id: int, body: Grouping, user: dict = Depends(admin_user)):
    if not body.reason.strip():
        raise HTTPException(400, "Explain the grouping decision")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        report = reports.accessible_report(db, report_id, user)
        if report['analysis_status'] in ('pending', 'queued', 'processing'):
            raise HTTPException(409, 'Wait for processing or review the exception before grouping')
        old_id = report["issue_id"]
        if body.issue_id == old_id:
            return summary(db, old_id)  # Repeated decisions do not increment counters.
        if body.issue_id is None:
            target_id = new_issue(db, report)
        else:
            target = accessible_issue(db, body.issue_id, user)
            if target["issue_type"] != report["issue_type"]:
                raise HTTPException(400, "Only matching categories can be grouped")
            if target["status"] not in ("open", "in_progress"):
                raise HTTPException(400, "Cannot attach a report to a closed issue")
            target_id = body.issue_id
        db.execute("UPDATE reports SET issue_id=?, duplicate_of=NULL, grouping_reason='admin_review',processing_revision=processing_revision+1, status=(SELECT status FROM issues WHERE id=?) WHERE id=?",
                   (target_id, target_id, report_id))
        # The former advisory root links are no longer authoritative.
        db.execute("UPDATE reports SET duplicate_of=NULL WHERE duplicate_of=?", (report_id,))
        db.execute("DELETE FROM duplicate_candidates WHERE report_id=?", (report_id,))
        db.execute("INSERT INTO grouping_history(report_id,from_issue,to_issue,actor_id,reason,created_at) VALUES(?,?,?,?,?,?)",
                   (report_id, old_id, target_id, user["id"], body.reason.strip(), int(time.time())))
        sync_representative(db, old_id)
        sync_representative(db, target_id)
        refresh_issue(db, old_id)
        refresh_issue(db, target_id)
        db.execute("DELETE FROM duplicate_candidates WHERE issue_id=(SELECT issue_id FROM reports WHERE id=report_id)")
        return summary(db, target_id)


class StatusUpdate(BaseModel):
    status: str = Field(pattern=r'^(open|in_progress|resolved|rejected)$')
    note: str = Field(min_length=1, max_length=1000)


@router.patch('/{issue_id}/status')
def change_status(issue_id: int, body: StatusUpdate, user: dict = Depends(current_user)):
    if not body.note.strip():
        raise HTTPException(400, 'Explain the status change')
    if user['role'] == 'nigam' and body.status == 'rejected':
        raise HTTPException(403, 'Evidence rejection is a platform review decision')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        old = accessible_issue(db, issue_id, user)
        db.execute('UPDATE issues SET status=? WHERE id=?', (body.status, issue_id))
        db.execute('UPDATE reports SET status=?,processing_revision=processing_revision+1 WHERE issue_id=?', (body.status, issue_id))
        record_event(db, issue_id, 'repair_status', {'from':old['status'],'status':body.status,'note':body.note.strip()}, user['id'])
        refresh_issue(db, issue_id)
        return summary(db, issue_id)


@router.get('/{issue_id}/history')
def history(issue_id: int, user: dict = Depends(current_user)):
    with connect() as db:
        accessible_issue(db, issue_id, user)
        events = db.execute('SELECT event,details,created_at FROM issue_history WHERE issue_id=? ORDER BY id', (issue_id,)).fetchall()
        return [dict(row) for row in events if user['role'] == 'admin' or row['event'] == 'repair_status']
