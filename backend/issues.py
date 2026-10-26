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
except ImportError:
    from accounts import current_user, admin_user
    from database import connect
    from grouping import new_issue, summary, sync_representative
    from reports import resolve_photo_user
    import reports

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
                search: str = "", issue: str = "", status: str = "", sort: str = "newest",
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
    if search:
        # Search only the representative description visible in the consolidated view.
        clauses.append("EXISTS(SELECT 1 FROM reports r WHERE r.id=i.representative_report_id AND r.description LIKE ?)")
        params.append(f"%{search}%")
    where = " AND ".join(clauses)
    with connect() as db:
        total = db.execute(f"SELECT COUNT(*) FROM issues i WHERE {where}", params).fetchone()[0]
        ids = db.execute(f"SELECT i.id FROM issues i WHERE {where} ORDER BY i.id {'ASC' if sort == 'oldest' else 'DESC'} LIMIT ? OFFSET ?",
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
        accessible_issue(db, issue_id, user)
        db.execute("UPDATE issues SET published=? WHERE id=?", (int(body.published), issue_id))
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
        db.execute("UPDATE reports SET issue_id=?, duplicate_of=NULL, grouping_reason='admin_review', status=(SELECT status FROM issues WHERE id=?) WHERE id=?",
                   (target_id, target_id, report_id))
        # The former advisory root links are no longer authoritative.
        db.execute("UPDATE reports SET duplicate_of=NULL WHERE duplicate_of=?", (report_id,))
        db.execute("DELETE FROM duplicate_candidates WHERE report_id=?", (report_id,))
        db.execute("INSERT INTO grouping_history(report_id,from_issue,to_issue,actor_id,reason,created_at) VALUES(?,?,?,?,?,?)",
                   (report_id, old_id, target_id, user["id"], body.reason.strip(), int(time.time())))
        sync_representative(db, old_id)
        sync_representative(db, target_id)
        db.execute("DELETE FROM duplicate_candidates WHERE issue_id=(SELECT issue_id FROM reports WHERE id=report_id)")
        return summary(db, target_id)
