"""Durable queue and scoped worker transport; no machine-learning imports."""
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.accounts import admin_user
from backend.database import connect
from backend import reports
from backend.grouping import nearby_reports, apply_automatic_grouping
from backend.policy import verification, refresh_issue, record_event

router = APIRouter(tags=['PC processing'])
LEASE_SECONDS = 180
MAX_ATTEMPTS = 3
MODEL_SHA256 = '748e47702e7fa7068ab64a9005cbefb02873e0190eff67496dbd2ef2a8f6a676'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def worker_access(key: str = Header(default='', alias='X-Worker-Key')):
    expected = os.getenv('NAGARSAATHI_WORKER_TOKEN_SHA256', '')
    if len(expected) != 64 or len(key) < 32 or not hmac.compare_digest(digest(key), expected):
        raise HTTPException(401, 'Worker credential required')


class Claim(BaseModel):
    worker_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')


class Lease(BaseModel):
    lease_token: str = Field(min_length=32, max_length=128)


def leased(db, job_id, token, allow_completed=False):
    job = db.execute('SELECT * FROM analysis_jobs WHERE id=?', (job_id,)).fetchone()
    if job is None or not hmac.compare_digest(job['lease_hash'] or '', digest(token)):
        raise HTTPException(409, 'Job lease is not owned by this worker')
    if allow_completed and job['state'] == 'completed':
        return job
    if job['state'] != 'processing' or job['lease_until'] <= int(time.time()):
        raise HTTPException(409, 'Job lease expired or no longer processing')
    return job


def enqueue(db, report_id):
    now = int(time.time())
    db.execute('INSERT INTO analysis_jobs(report_id,available_at,updated_at) VALUES(?,?,?)', (report_id, now, now))


@router.post('/worker/jobs/claim', dependencies=[Depends(worker_access)])
def claim_job(body: Claim):
    now = int(time.time())
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT INTO worker_heartbeats VALUES(?,?) ON CONFLICT(worker_id) DO UPDATE SET last_seen=excluded.last_seen', (body.worker_id, now))
        expired = db.execute("SELECT * FROM analysis_jobs WHERE state='processing' AND lease_until<=?", (now,)).fetchall()
        for old in expired:
            state = 'failed' if old['attempts'] >= MAX_ATTEMPTS else 'queued'
            db.execute('UPDATE analysis_jobs SET state=?,available_at=?,error_code=?,updated_at=? WHERE id=?',
                       (state, now, 'lease_expired', now, old['id']))
            if state == 'failed':
                db.execute("UPDATE reports SET analysis_status='failed',verification_status='needs_review',verification_reason='Processing needs administrator attention; your report is retained' WHERE id=?", (old['report_id'],))
        job = db.execute("SELECT * FROM analysis_jobs WHERE state='queued' AND available_at<=? ORDER BY id LIMIT 1", (now,)).fetchone()
        if job is None:
            return {'job': None}
        report = db.execute('SELECT * FROM reports WHERE id=?', (job['report_id'],)).fetchone()
        # Legacy records may not yet have dimensions; read using Pillow, never YOLO.
        if not report['image_width']:
            try:
                with reports._PIL_OPEN(reports.DATA_DIR / 'photos' / report['photo_name']) as image:
                    db.execute('UPDATE reports SET image_width=?,image_height=? WHERE id=?', (*image.size, report['id']))
            except OSError:
                db.execute("UPDATE analysis_jobs SET state='failed',error_code='input_missing',updated_at=? WHERE id=?", (now, job['id']))
                db.execute("UPDATE reports SET analysis_status='failed',verification_status='needs_review',verification_reason='Saved evidence needs administrator attention' WHERE id=?", (report['id'],))
                return {'job': None}
            report = db.execute('SELECT * FROM reports WHERE id=?', (report['id'],)).fetchone()
        candidates = nearby_reports(db, report)[:20]
        token = secrets.token_urlsafe(32)
        db.execute("""UPDATE analysis_jobs SET state='processing',attempts=attempts+1,lease_hash=?,lease_until=?,
            worker_id=?,candidate_ids=?,report_revision=?,updated_at=? WHERE id=?""",
            (digest(token), now + LEASE_SECONDS, body.worker_id, json.dumps([r['id'] for r in candidates]), report['processing_revision'], now, job['id']))
        db.execute("UPDATE reports SET analysis_status='processing' WHERE id=?", (report['id'],))
        return {'job': {'id': job['id'], 'report_id': report['id'], 'lease_token': token,
            'lease_seconds': LEASE_SECONDS, 'image_sha256': report['image_sha256'],
            'image_width': report['image_width'], 'image_height': report['image_height'], 'issue_type': report['issue_type'],
            'input_path': f"/worker/jobs/{job['id']}/input",
            'candidates': [{'report_id': r['id'], 'image_sha256': r['image_sha256'],
                            'input_path': f"/worker/jobs/{job['id']}/candidates/{r['id']}",
                            'analysis': json.loads(r['result_json'] or '{}')} for r in candidates]}}


@router.post('/worker/jobs/{job_id}/heartbeat', dependencies=[Depends(worker_access)])
def heartbeat(job_id: int, body: Lease):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        job = leased(db, job_id, body.lease_token)
        until = int(time.time()) + LEASE_SECONDS
        db.execute('UPDATE analysis_jobs SET lease_until=?,updated_at=? WHERE id=?', (until, int(time.time()), job_id))
        db.execute('UPDATE worker_heartbeats SET last_seen=? WHERE worker_id=?', (int(time.time()), job['worker_id']))
        return {'lease_until': until}


def input_response(job_id, lease_token, report_id=None):
    with connect() as db:
        job = leased(db, job_id, lease_token)
        if report_id is not None and report_id not in json.loads(job['candidate_ids']):
            raise HTTPException(403, 'Photo is outside the claimed job')
        row = db.execute('SELECT photo_name FROM reports WHERE id=?', (report_id or job['report_id'],)).fetchone()
    path = reports.DATA_DIR / 'photos' / row['photo_name']
    if not path.is_file():
        raise HTTPException(404, 'Input unavailable')
    return FileResponse(path, media_type='image/png')


@router.get('/worker/jobs/{job_id}/input', dependencies=[Depends(worker_access)])
def job_input(job_id: int, lease_token: str = Header(alias='X-Lease-Token')):
    return input_response(job_id, lease_token)


@router.get('/worker/jobs/{job_id}/candidates/{report_id}', dependencies=[Depends(worker_access)])
def candidate_input(job_id: int, report_id: int, lease_token: str = Header(alias='X-Lease-Token')):
    return input_response(job_id, lease_token, report_id)


class Detection(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    label: Literal['pothole', 'waterlogging']
    confidence: float = Field(ge=0, le=1)
    bbox_xyxy: tuple[float, float, float, float]


class Match(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    report_id: int = Field(gt=0)
    inliers: int = Field(ge=0, le=2000)
    inlier_ratio: float = Field(ge=0, le=1)
    coverage: float = Field(ge=0, le=1)


class Result(Lease):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    image_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    model_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    model_version: Literal['nagarsaathi-yolo11n-v3']
    image_width: int = Field(gt=0, le=24000000)
    image_height: int = Field(gt=0, le=24000000)
    detections: list[Detection] = Field(max_length=300)
    matches: list[Match] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def boxes_in_image(self):
        if self.image_width * self.image_height > 24_000_000:
            raise ValueError('Image is too large')
        for detection in self.detections:
            x1, y1, x2, y2 = detection.bbox_xyxy
            if not (0 <= x1 < x2 <= self.image_width and 0 <= y1 < y2 <= self.image_height):
                raise ValueError('Invalid bounding box')
        if len({m.report_id for m in self.matches}) != len(self.matches):
            raise ValueError('Duplicate candidate evidence')
        return self


@router.post('/worker/jobs/{job_id}/result', dependencies=[Depends(worker_access)])
def result(job_id: int, body: Result):
    payload = body.model_dump(mode='json', exclude={'lease_token'})
    result_digest = digest(json.dumps(payload, sort_keys=True, separators=(',', ':')))
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        job = leased(db, job_id, body.lease_token, allow_completed=True)
        if job['state'] == 'completed':
            if job['result_digest'] != result_digest:
                raise HTTPException(409, 'Job already completed with a different result')
            return {'status': 'completed', 'report_id': job['report_id'], 'replayed': True}
        report = db.execute('SELECT * FROM reports WHERE id=?', (job['report_id'],)).fetchone()
        if (body.model_sha256 != MODEL_SHA256 or body.image_sha256 != report['image_sha256'] or
            (body.image_width, body.image_height) != (report['image_width'], report['image_height'])):
            raise HTTPException(400, 'Result model or image does not match the claimed job')
        if any(m.report_id not in json.loads(job['candidate_ids']) for m in body.matches):
            raise HTTPException(400, 'Unexpected candidate evidence')
        if report['processing_revision'] != job['report_revision'] or report['status'] in ('resolved', 'rejected'):
            db.execute("UPDATE analysis_jobs SET state='completed',result_digest=?,updated_at=? WHERE id=?", (result_digest, int(time.time()), job_id))
            db.execute("""UPDATE reports SET analysis_status='completed',
                verification_status=CASE WHEN verification_status='pending' THEN 'needs_review' ELSE verification_status END,
                verification_reason=CASE WHEN verification_status='pending' THEN 'Issue changed during processing; administrator review required' ELSE verification_reason END
                WHERE id=?""", (report['id'],))
            return {'status': 'superseded', 'report_id': report['id']}
        state, reason = verification(report['issue_type'], payload['detections'])
        payload['verification_policy'] = 'visual-evidence-v1'
        payload['grouping_policy'] = 'grouping-v1'
        db.execute("UPDATE reports SET result_json=?,analysis_status='completed',verification_status=?,verification_reason=? WHERE id=?",
                   (json.dumps(payload), state, reason, report['id']))
        issue_id = apply_automatic_grouping(db, report['id'], payload['matches'],
                                          visual_enabled=os.getenv('NAGARSAATHI_VISUAL_AUTO_MERGE', '0') == '1')
        db.execute("UPDATE analysis_jobs SET state='completed',result_digest=?,updated_at=? WHERE id=?", (result_digest, int(time.time()), job_id))
        return {'status': 'completed', 'report_id': report['id'], 'issue_id': issue_id, 'replayed': False}


class Failure(Lease):
    # Worker exception strings may contain paths or credentials. Accept a fixed code only.
    error_code: Literal['inference_error', 'input_error', 'transport_error']


@router.post('/worker/jobs/{job_id}/failure', dependencies=[Depends(worker_access)])
def failure(job_id: int, body: Failure):
    now = int(time.time())
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        job = leased(db, job_id, body.lease_token)
        state = 'failed' if job['attempts'] >= MAX_ATTEMPTS else 'queued'
        db.execute('UPDATE analysis_jobs SET state=?,available_at=?,error_code=?,updated_at=? WHERE id=?',
                   (state, now + 10 * 2 ** (job['attempts'] - 1), body.error_code, now, job_id))
        db.execute('UPDATE reports SET analysis_status=?,verification_status=?,verification_reason=? WHERE id=?',
                   ('failed' if state == 'failed' else 'queued', 'needs_review' if state == 'failed' else 'pending',
                    'Processing needs review; your report is retained' if state == 'failed' else 'Awaiting processing retry', job['report_id']))
        return {'status': state}


@router.get('/processing/health')
def processing_health(user: dict = Depends(admin_user)):
    now = int(time.time())
    with connect() as db:
        counts = {s: db.execute('SELECT COUNT(*) FROM analysis_jobs WHERE state=?', (s,)).fetchone()[0]
                  for s in ('queued', 'processing', 'completed', 'failed')}
        oldest = db.execute("SELECT MIN(available_at) FROM analysis_jobs WHERE state='queued'").fetchone()[0]
        return {'queue': counts, 'oldest_wait_seconds': max(0, now - oldest) if oldest else 0,
                'expired_leases':db.execute("SELECT COUNT(*) FROM analysis_jobs WHERE state='processing' AND lease_until<=?", (now,)).fetchone()[0],
                'workers': [dict(r) for r in db.execute('SELECT * FROM worker_heartbeats')],
                'worker_online': bool(db.execute('SELECT 1 FROM worker_heartbeats WHERE last_seen>?', (now - LEASE_SECONDS,)).fetchone())}


@router.get('/processing/exceptions')
def exceptions(limit: int = Query(40, ge=1, le=100), offset: int = Query(0, ge=0), user: dict = Depends(admin_user)):
    with connect() as db:
        rows = db.execute("SELECT * FROM reports WHERE verification_status='needs_review' ORDER BY id LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return {'items': [reports.serialize(r, db, True) for r in rows],
                'total': db.execute("SELECT COUNT(*) FROM reports WHERE verification_status='needs_review'").fetchone()[0]}


@router.post('/processing/reports/{report_id}/retry')
def retry(report_id: int, user: dict = Depends(admin_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        report = reports.accessible_report(db, report_id, user)
        job = db.execute('SELECT * FROM analysis_jobs WHERE report_id=?', (report_id,)).fetchone()
        if report['status'] in ('resolved', 'rejected') or (job and job['state'] in ('queued', 'processing')):
            raise HTTPException(409, 'Report is closed or already awaiting processing')
        if job:
            db.execute('DELETE FROM analysis_jobs WHERE id=?', (job['id'],))
        db.execute("UPDATE reports SET processing_revision=processing_revision+1,analysis_status='queued',verification_status='pending',verification_reason='Awaiting processing retry' WHERE id=?", (report_id,))
        enqueue(db, report_id)
        if report['issue_id']:
            refresh_issue(db, report['issue_id'])
        return {'status': 'queued', 'report_id': report_id}


class EvidenceReview(BaseModel):
    verification_status: Literal['supported', 'not_supported', 'needs_review']
    reason: str = Field(min_length=1, max_length=1000)


@router.patch('/processing/reports/{report_id}/review')
def review_evidence(report_id: int, body: EvidenceReview, user: dict = Depends(admin_user)):
    if not body.reason.strip():
        raise HTTPException(400, 'Explain the review decision')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        report = reports.accessible_report(db, report_id, user)
        if not report['issue_id']:
            from backend.grouping import new_issue
            issue_id = new_issue(db, report)
            db.execute('UPDATE reports SET issue_id=? WHERE id=?', (issue_id, report_id))
        else:
            issue_id = report['issue_id']
        messages = {'supported': 'Your report has supporting evidence after review',
                    'not_supported': 'The supplied evidence was not confirmed after review; you may contact the platform for follow-up',
                    'needs_review': 'Your report requires further review and remains saved'}
        db.execute("UPDATE reports SET verification_status=?,verification_reason=?,analysis_status='completed',processing_revision=processing_revision+1 WHERE id=?",
                   (body.verification_status, messages[body.verification_status], report_id))
        db.execute("UPDATE analysis_jobs SET state='completed',result_digest=?,updated_at=? WHERE report_id=? AND state<>'completed'",
                   (digest(f'admin-review:{time.time_ns()}'), int(time.time()), report_id))
        record_event(db, issue_id, 'evidence_review', {'report_id':report_id, 'decision':body.verification_status, 'reason':body.reason.strip()}, user['id'])
        db.execute("UPDATE issues SET publication_mode='automatic' WHERE id=? AND publication_mode='legacy' AND published=0", (issue_id,))
        refresh_issue(db, issue_id)
        return reports.serialize(db.execute('SELECT * FROM reports WHERE id=?', (report_id,)).fetchone(), db, True)
