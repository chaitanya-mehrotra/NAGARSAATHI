"""Isolated HTTP fixtures; no production records or real model inference."""
import hashlib
import io
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from backend import database, reports
from backend.accounts import create_user
from backend.main import app
from backend.worker_api import MODEL_SHA256


def photo(color='grey'):
    output = io.BytesIO()
    Image.new('RGB', (64,64), color).save(output,format='PNG')
    return output.getvalue()


class PipelineCase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(database,'DATA_DIR',self.directory))
        self.stack.enter_context(patch.object(reports,'DATA_DIR',self.directory))
        self.key = 'fictional-test-worker-key-' + 'x'*32
        self.stack.enter_context(patch.dict(os.environ, {'NAGARSAATHI_WORKER_TOKEN_SHA256':hashlib.sha256(self.key.encode()).hexdigest(),
                                                         'NAGARSAATHI_VISUAL_AUTO_MERGE':'0'}))
        self.client = self.stack.enter_context(TestClient(app))
        self.admin = self.account('admin','admin')
        self.nigam = self.account('officer','nigam')
        self.citizen = self.account('citizen')
        self.worker_headers = {'X-Worker-Key':self.key}

    def account(self, name, role='citizen'):
        create_user(name,f'{name}@example.com','test-password-123',role=role)
        response = self.client.post('/auth/login',json={'email':f'{name}@example.com','password':'test-password-123'})
        self.assertEqual(response.json()['user']['role'],role)
        return {'Authorization':'Bearer '+response.json()['access_token']}

    def submit(self, headers=None, image=None, category='pothole', lat=12.9716,lon=77.5946,key=None):
        headers = dict(headers or self.citizen)
        if key:
            headers['Idempotency-Key'] = key
        return self.client.post('/reports',headers=headers,data={'description':'Road defect','latitude':lat,'longitude':lon,'issue_type':category},
                                files={'image':('road.png', image or photo(),'image/png')})

    def claim(self, worker='test-pc'):
        response = self.client.post('/worker/jobs/claim',headers=self.worker_headers,json={'worker_id':worker})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['job']

    def payload(self, job, label='pothole', detections=None):
        return {'lease_token':job['lease_token'],'image_sha256':job['image_sha256'],'model_sha256':MODEL_SHA256,
                'model_version':'nagarsaathi-yolo11n-v3','image_width':job['image_width'],'image_height':job['image_height'],
                'detections':detections if detections is not None else [{'label':label,'confidence':.9,'bbox_xyxy':[2,2,60,60]}], 'matches':[]}

    def complete(self, job=None, label='pothole', detections=None):
        job = job or self.claim()
        response = self.client.post(f"/worker/jobs/{job['id']}/result",headers=self.worker_headers,json=self.payload(job,label,detections))
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def processed(self, **kwargs):
        response = self.submit(**kwargs)
        self.assertEqual(response.status_code,201,response.text)
        self.complete(label=kwargs.get('category','pothole'))
        return self.detail(response.json()['id'])

    def detail(self, report_id):
        return self.client.get(f'/reports/{report_id}',headers=self.admin).json()

    def issue(self, issue_id):
        return self.client.get(f'/issues/{issue_id}',headers=self.admin).json()

    def group(self, report_id, issue_id):
        return self.client.patch(f'/issues/report/{report_id}/group',headers=self.admin,
                                 json={'issue_id':issue_id,'reason':'Reviewed physical issue'})
