"""Collection integration: retained counts, permissions, archives and verified repair work."""
import os
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import database
from backend.main import app
from backend.test_support import PipelineCase, photo


class CollectionTests(PipelineCase):
    def moderate(self, report_id, action='archive', headers=None):
        return self.client.post(f'/moderation/reports/{report_id}/{action}',headers=headers or self.admin,json={'reason':'Reviewed test moderation'})

    def assign(self, issue_id, headers=None, version=0, assignee=None):
        user_id = self.client.get('/auth/me',headers=assignee or self.nigam).json()['id']
        return self.client.put(f'/issues/{issue_id}/assignment',headers=headers or self.admin,
            json={'assigned_to':user_id,'team':'Road maintenance crew','note':'Inspect and repair road defect','expected_version':version})

    def repair(self, issue_id, version=1, headers=None, key='repair-request', image=None):
        return self.client.post(f'/issues/{issue_id}/repairs',headers={**(headers or self.nigam),'Idempotency-Key':key},
            data={'note':'Repair completed and checked on site','expected_version':version}, files={'image':('repair.png',image or photo('blue'),'image/png')})

    def review(self, issue_id, repair_id, version=2, headers=None, decision='verified'):
        return self.client.post(f'/issues/{issue_id}/repairs/{repair_id}/review',headers=headers or self.admin,
            json={'decision':decision,'note':'Independent on-site inspection','expected_version':version})

    def test_archive_restores_without_losing_counts_or_photos(self):
        first = self.processed()
        second = self.processed(headers=self.account('another-citizen'))
        iid = first['issue_id']
        self.assertEqual(second['issue_id'],iid)
        for auth in (self.citizen,self.nigam):
            self.assertEqual(self.moderate(first['id'],headers=auth).status_code,403)
            self.assertEqual(self.client.get('/moderation/reports',headers=auth).status_code,403)
        self.assertEqual(self.moderate(first['id']).status_code,200)
        self.assertEqual(self.moderate(first['id']).status_code,200)
        summary = self.issue(iid)
        self.assertEqual((summary['report_count'],summary['reporter_count'],summary['active_report_count'],summary['archived_report_count']),(2,2,1,1))
        self.assertIn('1 distinct accounts',summary['priority_reason'])
        self.assertEqual(self.client.get('/complaints',headers=self.admin).json()['total'],1)
        self.assertEqual(self.client.get(f"/reports/{first['id']}/photo",headers=self.citizen).status_code,404)
        self.assertEqual(self.client.get(f"/reports/{first['id']}/photo",headers=self.admin).status_code,200)
        self.assertEqual(self.client.get('/moderation/reports',headers=self.admin).json()['total'],1)
        self.moderate(second['id'])
        self.assertEqual(self.client.get('/issues',headers=self.nigam).json()['total'],0)
        self.assertEqual(self.client.get(f'/issues/{iid}',headers=self.nigam).status_code,404)
        self.assertEqual(self.issue(iid)['report_count'],2)
        self.moderate(first['id'],'restore'); self.moderate(first['id'],'restore')
        self.assertEqual(self.client.get('/issues',headers=self.nigam).json()['total'],1)
        history = self.client.get(f"/moderation/reports/{first['id']}/history",headers=self.admin).json()
        self.assertEqual([event['action'] for event in history],['archive','restore'])
        self.assertEqual(len(list((self.directory/'photos').glob('*.png'))),2)

    def test_archive_revokes_inflight_worker_and_restore_queues_new_job(self):
        rid = self.submit().json()['id']; job = self.claim()
        self.moderate(rid)
        self.assertEqual(self.client.post(f"/worker/jobs/{job['id']}/result",headers=self.worker_headers,json=self.payload(job)).status_code,409)
        self.assertIsNone(self.claim())
        self.assertEqual(self.client.post(f'/reports/{rid}/retry',headers=self.admin).status_code,409)
        self.assertEqual(self.client.patch(f'/reports/{rid}/review',headers=self.admin,json={'verification_status':'supported','reason':'review'}).status_code,409)
        self.moderate(rid,'restore')
        replacement = self.claim()
        self.assertNotEqual(replacement['id'],job['id'])
        self.complete(replacement)
        self.assertEqual(self.detail(rid)['verification_status'],'supported')
        with database.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reports').fetchone()[0],1)

    def test_repair_assignment_evidence_independent_verification_and_retries(self):
        report = self.processed(); iid = report['issue_id']
        other = self.account('another-citizen')
        second = self.processed(headers=other)
        self.assertEqual(self.assign(iid,headers=self.citizen).status_code,403)
        self.assertEqual(self.assign(iid).status_code,200)
        self.assertEqual(self.assign(iid).status_code,409)
        self.assertEqual(self.client.patch(f'/issues/{iid}/status',headers=self.nigam,json={'status':'resolved','note':'Shortcut attempt'}).status_code,409)
        self.assertEqual(self.repair(iid,headers=self.citizen).status_code,403)
        self.assertEqual(self.repair(iid,headers=self.admin).status_code,403)
        self.assertEqual(self.repair(iid,image=b'bad image').status_code,400)
        response = self.repair(iid)
        self.assertEqual(response.status_code,201,response.text)
        rid = response.json()['repairs'][0]['id']
        self.assertEqual(self.repair(iid).status_code,201)
        self.assertEqual(len(list((self.directory/'repairs').glob('*.png'))),1)
        self.assertEqual(self.issue(iid)['status'],'in_progress')
        self.assertEqual(self.repair(iid,key='another-key',version=2).status_code,409)
        url = response.json()['repairs'][0]['photo_url']
        self.assertEqual(self.client.get(url,headers=self.citizen).status_code,403)
        self.assertEqual(self.client.get(url,headers=self.nigam).status_code,200)
        self.assertEqual(self.review(iid,rid,headers=self.nigam).status_code,403)
        self.assertEqual(self.review(iid,rid,version=1).status_code,409)
        self.assertEqual(self.review(iid,rid).status_code,200)
        self.assertEqual(self.review(iid,rid).status_code,200)
        for report_id, auth in ((report['id'],self.citizen),(second['id'],other)):
            detail = self.client.get(f'/reports/{report_id}',headers=auth).json()
            self.assertEqual(detail['status'],'resolved')
            self.assertNotIn('repairs',detail)
        self.assertEqual(self.client.get('/issues?queue=resolved',headers=self.nigam).json()['total'],1)
        self.assertEqual(self.issue(iid)['priority_score'],0)

    def test_repair_cannot_self_verify_or_verify_after_membership_changes(self):
        report = self.processed(); iid = report['issue_id']
        self.assign(iid,assignee=self.admin)
        result = self.repair(iid,headers=self.admin).json()
        rid = result['repairs'][0]['id']
        self.assertEqual(self.review(iid,rid).status_code,403)
        reviewer = self.account('independent-admin','admin')
        self.processed(headers=self.account('new-reporter'))
        self.assertEqual(self.review(iid,rid,headers=reviewer).status_code,409)
        self.assertEqual(self.review(iid,rid,headers=reviewer,decision='rejected').status_code,200)
        result = self.repair(iid,headers=self.admin,version=3,key='new-repair').json()
        repair_id = result['repairs'][0]['id']
        # Tamper the new evidence specifically and require verification to fail closed.
        with database.connect() as db:
            filename = db.execute('SELECT photo_name FROM repair_evidence WHERE id=?',(repair_id,)).fetchone()[0]
        (self.directory/'repairs'/filename).write_bytes(b'tampered')
        self.assertEqual(self.review(iid,repair_id,version=4,headers=reviewer).status_code,409)

    def test_ui_contract_aliases_exceptions_and_restart_preservation(self):
        supported = self.processed()
        pending = self.submit().json()['id']
        self.complete(detections=[])
        inbox = self.client.get('/complaints?needs_attention=true',headers=self.admin).json()
        self.assertEqual([row['id'] for row in inbox['items']],[pending])
        self.assertEqual(inbox['items'][0]['processing_status'],'completed')
        self.assertIn('issue',inbox['items'][0])
        result = self.client.patch(f'/reports/{pending}/review',headers=self.admin,json={'verification_status':'supported','reason':'Reviewed original photo'})
        self.assertEqual(result.status_code,200)
        self.moderate(supported['id'])
        with database.connect() as db:
            before = {table:[tuple(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY 1')] for table in ('users','sessions','reports','issues','moderation_events')}
        with TestClient(app):
            pass
        with database.connect() as db:
            after = {table:[tuple(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY 1')] for table in before}
            self.assertEqual(before,after)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_regrouping_preserves_existing_work_and_repair_history(self):
        report = self.processed(); iid = report['issue_id']
        self.assign(iid)
        repair_id = self.repair(iid).json()['repairs'][0]['id']
        separate = self.processed(image=photo('red'),lat=13.5)
        moved = self.group(report['id'],separate['issue_id'])
        self.assertEqual(moved.status_code,200,moved.text)
        self.assertEqual(self.issue(iid)['report_count'],0)
        self.assertEqual(self.review(iid,repair_id).status_code,409)
        self.assertEqual(self.review(iid,repair_id,decision='rejected').status_code,200)
        with database.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM repair_evidence WHERE issue_id=?',(iid,)).fetchone()[0],1)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])


class GoogleTests(PipelineCase):
    def test_google_library_is_called_with_audience_and_rejects_invalid_token(self):
        with patch.dict(os.environ,{'GOOGLE_CLIENT_ID':'test-client-id'}):
            with patch('google.oauth2.id_token.verify_oauth2_token',side_effect=ValueError('bad signature')) as verifier:
                result = self.client.post('/auth/google',json={'credential':'a-tampered-or-unsigned-token'})
                self.assertEqual(result.status_code,401)
                self.assertEqual(verifier.call_args.args[2],'test-client-id')
                with database.connect() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM google_identities').fetchone()[0],0)

    def google(self, claims):
        with patch('backend.google_auth.verify_google',return_value=claims):
            return self.client.post('/auth/google',json={'credential':'fictional-signed-token-value'})

    def claims(self):
        nonce = self.client.post('/auth/google/challenge').json()['nonce']
        return {'sub':'google-subject-123','email':'new-google@example.com','name':'Google Citizen','email_verified':True,
                'iss':'https://accounts.google.com','aud':'test-client-id','nonce':nonce}

    def test_google_is_optional_verified_citizen_only_and_nonce_is_single_use(self):
        with patch.dict(os.environ,{'GOOGLE_CLIENT_ID':''}):
            self.assertIsNone(self.client.get('/auth/options').json()['google_client_id'])
            self.assertEqual(self.client.post('/auth/google',json={'credential':'fictional-token-value'}).status_code,503)
        with patch.dict(os.environ,{'GOOGLE_CLIENT_ID':'test-client-id'}):
            claims = self.claims()
            for field,value in (('aud','wrong-app'),('iss','untrusted'),('email_verified',False)):
                self.assertEqual(self.google({**claims,field:value}).status_code,401)
            result = self.google(claims)
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['user']['role'],'citizen')
            self.assertEqual(self.google(claims).status_code,401)
            self.assertEqual(self.client.post('/auth/google',json={'email':'admin@example.com','credential':'fictional-token-value'}).status_code,400)
            collision = self.claims() | {'email':'admin@example.com','sub':'different-subject'}
            self.assertEqual(self.google(collision).status_code,409)
            self.assertEqual(self.client.get('/auth/me',headers=self.admin).json()['role'],'admin')
            # A later sign-in is keyed by Google's stable subject, not a caller-supplied email match.
            again = self.google(self.claims())
            self.assertEqual(again.json()['user']['id'],result.json()['user']['id'])
