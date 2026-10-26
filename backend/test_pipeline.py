"""Intake accepts reports with no model or worker; privacy is enforced server-side."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import database, inference
from backend.main import app
from backend.test_support import PipelineCase, photo


class IntakeTests(PipelineCase):
    def test_offline_intake_never_calls_model_and_pending_survives_restart(self):
        with patch.object(inference,'load_model',side_effect=AssertionError('API loaded model')), \
             patch.object(inference,'detect_potholes',side_effect=AssertionError('API ran inference')):
            response = self.submit()
            self.assertEqual(response.status_code,201)
            result = response.json()
            self.assertEqual(result['verification_status'],'pending')
            self.assertNotIn('analysis',result)
            with TestClient(app) as restarted:
                saved = restarted.get(f"/reports/{result['id']}",headers=self.citizen).json()
                self.assertEqual(saved['verification_status'],'pending')
                with database.connect() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM analysis_jobs').fetchone()[0],1)
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM issues').fetchone()[0],0)
            self.assertEqual(self.client.get('/ready').status_code,200)

    def test_retries_create_one_report_one_job_one_photo(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            responses = list(pool.map(lambda _:self.submit(key='same-request'),range(3)))
        self.assertEqual({r.status_code for r in responses},{201})
        self.assertEqual(len({r.json()['id'] for r in responses}),1)
        self.assertEqual(self.submit(key='same-request',image=photo('red')).status_code,409)
        with database.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reports').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM analysis_jobs').fetchone()[0],1)
        self.assertEqual(len(list((self.directory/'photos').glob('*.png'))),1)

    def test_roles_privacy_expiry_and_no_citizen_model_preview(self):
        for role in ('admin','nigam'):
            reg = self.client.post('/auth/register',json={'name':'Public','email':f'{role}-attempt@example.com','password':'password-123','role':role})
            self.assertEqual(reg.json()['role'],'citizen')
        report = self.processed()
        other = self.account('other')
        for path in (f"/reports/{report['id']}",f"/reports/{report['id']}/photo",f"/complaints/{report['id']}"):
            self.assertEqual(self.client.get(path,headers=other).status_code,404)
        own = self.client.get(f"/reports/{report['id']}",headers=self.citizen).json()
        for secret in ('analysis','result_json','priority','processing','image_sha256','issue_summary','duplicate_candidates'):
            self.assertNotIn(secret,own)
        self.assertEqual(self.client.post('/dev/detect',headers=self.citizen).status_code,403)
        self.assertEqual(self.client.post('/dev/detect',headers=self.admin).status_code,410)
        self.assertEqual(self.client.get('/processing/health',headers=self.citizen).status_code,403)
        self.assertEqual(self.client.post('/auth/logout',headers=other).status_code,204)
        self.assertEqual(self.client.get('/auth/me',headers=other).status_code,401)

    def test_invalid_upload_is_not_saved(self):
        self.assertEqual(self.submit(image=b'not an image').status_code,400)
        with database.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reports').fetchone()[0],0)
