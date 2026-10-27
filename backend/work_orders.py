"""Assignments and independent repair verification adapted from main's work lifecycle."""
import hashlib
import io
import json
import os
import secrets
import time

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from backend.accounts import admin_user, current_user
from backend.database import connect
from backend.issues import accessible_issue
from backend.policy import record_event, refresh_issue
from backend import reports

router = APIRouter(tags=['Assignments and repair evidence'])


def membership_digest(db, issue_id):
    rows = [list(r) for r in db.execute('SELECT id,processing_revision,archived_at FROM reports WHERE issue_id=? ORDER BY id', (issue_id,))]
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def work_detail(db, issue_id):
    order = db.execute('SELECT * FROM work_orders WHERE issue_id=?', (issue_id,)).fetchone()
    if order is None:
        return {'assignment': None, 'repairs': []}
    assignment = {key: order[key] for key in ('assigned_to', 'team', 'note', 'version', 'updated_at')}
    evidence = db.execute('SELECT * FROM repair_evidence WHERE issue_id=? ORDER BY id DESC', (issue_id,)).fetchall()
    # Citizen identities/session credentials are never part of work responses.
    return {'assignment': assignment, 'repairs': [
        {key: r[key] for key in ('id','note','state','submitted_at','reviewed_at','review_note')}
        | {'photo_url': f"/issues/{issue_id}/repairs/{r['id']}/photo"} for r in evidence]}


def order_for_update(db, issue_id, user, version):
    issue = accessible_issue(db, issue_id, user)
    order = db.execute('SELECT * FROM work_orders WHERE issue_id=?', (issue_id,)).fetchone()
    if not order:
        raise HTTPException(409, 'Assign the issue before recording repair work')
    if order['version'] != version:
        raise HTTPException(409, 'Work order changed. Refresh before continuing')
    return issue, order


def progress(db, issue_id, status, event, details, actor):
    db.execute('UPDATE issues SET status=? WHERE id=?', (status, issue_id))
    db.execute('UPDATE reports SET status=?,processing_revision=processing_revision+1 WHERE issue_id=?', (status, issue_id))
    db.execute('UPDATE work_orders SET version=version+1,updated_at=? WHERE issue_id=?', (int(time.time()), issue_id))
    record_event(db, issue_id, event, details, actor['id'])
    refresh_issue(db, issue_id)


@router.get('/work/accounts')
def staff_accounts(user=Depends(admin_user)):
    with connect() as db:
        return [dict(r) for r in db.execute("""SELECT u.id,u.name,
            CASE WHEN u.role='admin' THEN 'admin' ELSE 'nigam' END AS role
            FROM users u LEFT JOIN municipal_accounts m ON m.user_id=u.id
            WHERE u.role='admin' OR m.user_id IS NOT NULL ORDER BY u.name,u.id""")]


@router.get('/issues/{issue_id}/work')
def get_work(issue_id: int, user=Depends(current_user)):
    with connect() as db:
        accessible_issue(db, issue_id, user)
        detail = work_detail(db, issue_id)
        detail['can_submit'] = bool(detail['assignment'] and detail['assignment']['assigned_to'] == user['id'])
        authors = {r['id']: r['submitted_by'] for r in db.execute('SELECT id,submitted_by FROM repair_evidence WHERE issue_id=?',(issue_id,))}
        for repair in detail['repairs']:
            repair['can_review'] = user['role'] == 'admin' and authors[repair['id']] != user['id']
        return detail


class Assignment(BaseModel):
    assigned_to: int = Field(gt=0)
    team: str = Field(min_length=1, max_length=100)
    note: str = Field(min_length=3, max_length=1000)
    expected_version: int = Field(ge=0)


@router.put('/issues/{issue_id}/assignment')
def assign(issue_id: int, body: Assignment, user=Depends(admin_user)):
    if not body.team.strip() or len(body.note.strip()) < 3:
        raise HTTPException(400, 'Enter a team and assignment note')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        issue = accessible_issue(db, issue_id, user)
        if not issue['published'] or not issue['active_report_count']:
            raise HTTPException(409, 'Review and publish an active supported issue before assigning work')
        if issue['status'] in ('resolved','rejected'):
            raise HTTPException(409, 'Reopen the issue before assigning work')
        eligible = db.execute("SELECT 1 FROM users u LEFT JOIN municipal_accounts m ON m.user_id=u.id WHERE u.id=? AND (u.role='admin' OR m.user_id IS NOT NULL)", (body.assigned_to,)).fetchone()
        if not eligible:
            raise HTTPException(400, 'Assign an existing Nagar Nigam or administrator account')
        previous = db.execute('SELECT * FROM work_orders WHERE issue_id=?', (issue_id,)).fetchone()
        version = previous['version'] if previous else 0
        if body.expected_version != version:
            raise HTTPException(409, 'Assignment changed. Refresh before continuing')
        if db.execute("SELECT 1 FROM repair_evidence WHERE issue_id=? AND state='pending'", (issue_id,)).fetchone():
            raise HTTPException(409, 'Review pending repair evidence before reassigning')
        db.execute('''INSERT INTO work_orders(issue_id,assigned_to,assigned_by,team,note,version,updated_at)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(issue_id) DO UPDATE SET assigned_to=excluded.assigned_to,
            assigned_by=excluded.assigned_by,team=excluded.team,note=excluded.note,version=excluded.version,updated_at=excluded.updated_at''',
            (issue_id,body.assigned_to,user['id'],body.team.strip(),body.note.strip(),version+1,int(time.time())))
        record_event(db,issue_id,'work_assignment',{'team':body.team.strip(),'note':body.note.strip()},user['id'])
        return work_detail(db, issue_id)


@router.post('/issues/{issue_id}/repairs', status_code=201)
def submit_repair(issue_id: int, note: str = Form(min_length=3,max_length=1000),
                  expected_version: int = Form(ge=1), image: UploadFile = File(),
                  request_key: str = Header(alias='Idempotency-Key',min_length=1,max_length=128), user=Depends(current_user)):
    if user['role'] not in ('admin','nigam'):
        raise HTTPException(403, 'Staff account required')
    if len(note.strip()) < 3:
        raise HTTPException(400, 'Describe the completed repair')
    content = image.file.read(reports.MAX_UPLOAD_BYTES + 1)
    if len(content) > reports.MAX_UPLOAD_BYTES:
        raise HTTPException(413, 'Photo must be 10 MB or smaller')
    try:
        with reports._PIL_OPEN(io.BytesIO(content),formats=['JPEG','PNG','WEBP']) as source:
            if source.width*source.height > reports.MAX_MEGAPIXELS or getattr(source,'n_frames',1) != 1:
                raise ValueError('Invalid dimensions or animation')
            corrected = ImageOps.exif_transpose(source).convert('RGB')
            canonical = Image.new('RGB',corrected.size)
            canonical.paste(corrected)
    except (OSError,ValueError,UnidentifiedImageError,Image.DecompressionBombError):
        raise HTTPException(400, 'Upload a valid JPEG, PNG or WebP repair photo')
    sha = hashlib.sha256(f'{canonical.width}x{canonical.height}:'.encode()+canonical.tobytes()).hexdigest()
    folder = reports.DATA_DIR / 'repairs'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (secrets.token_hex(16)+'.png')
    try:
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            accessible_issue(db,issue_id,user)
            replay = db.execute('SELECT * FROM repair_evidence WHERE submitted_by=? AND request_key=?',(user['id'],request_key)).fetchone()
            if replay:
                if replay['issue_id'] != issue_id or replay['image_sha256'] != sha or replay['note'] != note.strip():
                    raise HTTPException(409,'Submission key was used for different repair evidence')
                return work_detail(db,issue_id)
            issue, order = order_for_update(db,issue_id,user,expected_version)
            if order['assigned_to'] != user['id']:
                raise HTTPException(403,'Only the assigned staff account can submit repair evidence')
            if issue['status'] not in ('open','in_progress'):
                raise HTTPException(409,'Issue is not in the active repair stage')
            if db.execute("SELECT 1 FROM repair_evidence WHERE issue_id=? AND state='pending'",(issue_id,)).fetchone():
                raise HTTPException(409,'Repair evidence already awaits independent review')
            with path.open('wb') as saved:
                canonical.save(saved,format='PNG'); saved.flush(); os.fsync(saved.fileno())
            # Repair remains in progress until a different administrator verifies it.
            progress(db,issue_id,'in_progress','repair_submitted',{'note':note.strip()},user)
            db.execute('''INSERT INTO repair_evidence(issue_id,submitted_by,note,photo_name,image_sha256,membership_digest,submitted_at,request_key)
                VALUES(?,?,?,?,?,?,?,?)''',(issue_id,user['id'],note.strip(),path.name,sha,membership_digest(db,issue_id),int(time.time()),request_key))
            return work_detail(db,issue_id)
    except Exception:
        path.unlink(missing_ok=True)
        raise


class RepairReview(BaseModel):
    decision: str = Field(pattern='^(verified|rejected)$')
    note: str = Field(min_length=3,max_length=1000)
    expected_version: int = Field(ge=1)


@router.post('/issues/{issue_id}/repairs/{repair_id}/review')
def review_repair(issue_id: int, repair_id: int, body: RepairReview, user=Depends(admin_user)):
    if len(body.note.strip()) < 3:
        raise HTTPException(400,'Explain the repair review')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        accessible_issue(db,issue_id,user)
        repair = db.execute('SELECT * FROM repair_evidence WHERE id=? AND issue_id=?',(repair_id,issue_id)).fetchone()
        if not repair:
            raise HTTPException(404,'Repair evidence not found')
        if repair['submitted_by'] == user['id']:
            raise HTTPException(403,'A different administrator must verify this repair')
        if repair['state'] != 'pending':
            if repair['state'] == body.decision and repair['reviewed_by'] == user['id'] and repair['review_note'] == body.note.strip():
                return work_detail(db,issue_id)
            raise HTTPException(409,'Repair evidence has already been reviewed')
        issue, order = order_for_update(db,issue_id,user,body.expected_version)
        if issue['status'] != 'in_progress':
            raise HTTPException(409,'Issue changed during repair review')
        if body.decision == 'verified':
            if membership_digest(db,issue_id) != repair['membership_digest']:
                raise HTTPException(409,'Linked reports changed after repair. Reject this evidence and inspect again')
            try:
                with reports._PIL_OPEN(reports.DATA_DIR/'repairs'/repair['photo_name']) as stored:
                    actual = hashlib.sha256(f'{stored.width}x{stored.height}:'.encode()+stored.convert('RGB').tobytes()).hexdigest()
                if actual != repair['image_sha256']:
                    raise ValueError('Evidence changed')
            except (OSError,ValueError):
                raise HTTPException(409,'Saved repair evidence is missing or changed')
        db.execute('UPDATE repair_evidence SET state=?,reviewed_by=?,review_note=?,reviewed_at=? WHERE id=?',
                   (body.decision,user['id'],body.note.strip(),int(time.time()),repair_id))
        progress(db,issue_id,'resolved' if body.decision == 'verified' else 'in_progress','repair_review',{'decision':body.decision,'note':body.note.strip()},user)
        return work_detail(db,issue_id)


@router.get('/issues/{issue_id}/repairs/{repair_id}/photo')
def repair_photo(issue_id: int,repair_id: int,user=Depends(reports.resolve_photo_user)):
    with connect() as db:
        accessible_issue(db,issue_id,user)
        row = db.execute('SELECT photo_name FROM repair_evidence WHERE id=? AND issue_id=?',(repair_id,issue_id)).fetchone()
        if row is None:
            raise HTTPException(404,'Repair evidence not found')
    path = reports.DATA_DIR/'repairs'/row['photo_name']
    if not path.is_file():
        raise HTTPException(404,'Repair evidence not found')
    return FileResponse(path,media_type='image/png')
