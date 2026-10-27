"""Audited, reversible archives. Duplicate reports are grouped, never bulk deleted."""
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.accounts import admin_user
from backend.database import connect
from backend.grouping import summary, sync_representative
from backend import reports

router = APIRouter(prefix='/moderation', tags=['Complaint archive'])


class Reason(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


def clean_reason(body):
    value = body.reason.strip()
    if len(value) < 3:
        raise HTTPException(400, 'Explain the moderation decision')
    return value


@router.get('/reports')
def archived(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), user=Depends(admin_user)):
    with connect() as db:
        rows = db.execute('SELECT * FROM reports WHERE archived_at IS NOT NULL ORDER BY archived_at DESC,id DESC LIMIT ? OFFSET ?', (limit, offset)).fetchall()
        return {'items': [reports.serialize(row, db, True) for row in rows],
                'total': db.execute('SELECT COUNT(*) FROM reports WHERE archived_at IS NOT NULL').fetchone()[0]}


@router.post('/reports/{report_id}/archive')
def archive(report_id: int, body: Reason, user=Depends(admin_user)):
    reason = clean_reason(body)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = reports.accessible_report(db, report_id, user)
        if row['archived_at'] is None:
            now = int(time.time())
            db.execute('UPDATE reports SET archived_at=?,archived_by=?,archive_reason=?,processing_revision=processing_revision+1 WHERE id=?', (now, user['id'], reason, report_id))
            # Revoke any in-flight lease: a late worker cannot republish an archived report.
            db.execute("UPDATE analysis_jobs SET state='failed',lease_hash=NULL,lease_until=NULL,error_code='report_archived',updated_at=? WHERE report_id=? AND state IN ('queued','processing')", (now, report_id))
            db.execute("INSERT INTO moderation_events(report_id,actor_id,action,reason,created_at) VALUES(?,?,'archive',?,?)", (report_id, user['id'], reason, now))
            if row['issue_id']:
                sync_representative(db, row['issue_id'])
                summary(db, row['issue_id'])
        return {'id': report_id, 'archived': True}


@router.post('/reports/{report_id}/restore')
def restore(report_id: int, body: Reason, user=Depends(admin_user)):
    reason = clean_reason(body)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = reports.accessible_report(db, report_id, user)
        if row['archived_at'] is not None:
            now = int(time.time())
            db.execute('UPDATE reports SET archived_at=NULL,archived_by=NULL,archive_reason=NULL,processing_revision=processing_revision+1 WHERE id=?', (report_id,))
            job = db.execute('SELECT * FROM analysis_jobs WHERE report_id=?', (report_id,)).fetchone()
            if job and job['error_code'] == 'report_archived':
                from backend.worker_api import enqueue
                db.execute('DELETE FROM analysis_jobs WHERE id=?', (job['id'],))
                db.execute("UPDATE reports SET analysis_status='queued',verification_status='pending',verification_reason='Restored report awaiting processing' WHERE id=?", (report_id,))
                enqueue(db, report_id)
            db.execute("INSERT INTO moderation_events(report_id,actor_id,action,reason,created_at) VALUES(?,?,'restore',?,?)", (report_id, user['id'], reason, now))
            if row['issue_id']:
                sync_representative(db, row['issue_id'])
                summary(db, row['issue_id'])
        return {'id': report_id, 'archived': False}


@router.get('/reports/{report_id}/history')
def history(report_id: int, user=Depends(admin_user)):
    with connect() as db:
        reports.accessible_report(db, report_id, user)
        return [dict(r) for r in db.execute('SELECT action,reason,created_at FROM moderation_events WHERE report_id=? ORDER BY id', (report_id,))]
