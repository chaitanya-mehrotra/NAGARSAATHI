"""Failure recovery, authentication, automated decisions and repair propagation."""
import time
import io
import os
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from backend import database
from backend.pc_worker import PCWorker
from backend.policy import priority
from backend.test_support import PipelineCase, photo


class WorkerQueueTests(PipelineCase):
    def test_atomic_claim_and_stale_lease_replay_protection(self):
        report = self.submit().json()
        with ThreadPoolExecutor(max_workers=2) as pool:
            claimed = list(pool.map(self.claim, ['first','second']))
        self.assertEqual(sum(j is not None for j in claimed),1)
        old = next(j for j in claimed if j)
        with database.connect() as db:
            db.execute('UPDATE analysis_jobs SET lease_until=0 WHERE id=?',(old['id'],))
        current = self.claim('replacement')
        stale = self.client.post(f"/worker/jobs/{old['id']}/result",headers=self.worker_headers,json=self.payload(old))
        self.assertEqual(stale.status_code,409)
        self.complete(current)
        replay = self.client.post(f"/worker/jobs/{current['id']}/result",headers=self.worker_headers,json=self.payload(current))
        self.assertTrue(replay.json()['replayed'])
        changed = self.payload(current)
        changed['detections'][0]['confidence'] = .8
        self.assertEqual(self.client.post(f"/worker/jobs/{current['id']}/result",headers=self.worker_headers,json=changed).status_code,409)
        self.assertEqual(self.issue(self.detail(report['id'])['issue_id'])['report_count'],1)
        self.assertEqual(self.client.get(current['input_path'],headers={**self.worker_headers,'X-Lease-Token':current['lease_token']}).status_code,409)

    def test_bounded_failures_become_reviewable_and_admin_retry_is_safe(self):
        report = self.submit().json()
        for attempt in range(3):
            job = self.claim()
            failure = self.client.post(f"/worker/jobs/{job['id']}/failure",headers=self.worker_headers,
                                       json={'lease_token':job['lease_token'],'error_code':'inference_error'})
            self.assertEqual(failure.json()['status'],'failed' if attempt == 2 else 'queued')
            with database.connect() as db:
                db.execute('UPDATE analysis_jobs SET available_at=0')
        self.assertEqual(self.detail(report['id'])['verification_status'],'needs_review')
        self.assertEqual(self.detail(report['id'])['status'],'open')
        self.assertEqual(self.client.get('/processing/exceptions',headers=self.admin).json()['total'],1)
        self.assertIsNone(self.claim())
        retry = self.client.post(f"/processing/reports/{report['id']}/retry",headers=self.admin)
        self.assertEqual(retry.status_code,200)
        self.complete()
        self.assertEqual(self.detail(report['id'])['verification_status'],'supported')
        self.assertEqual(self.client.get('/reports',headers=self.admin).json().__len__(),1)

    def test_repeated_crashes_also_exhaust_attempts(self):
        report = self.submit().json()
        for attempt in range(3):
            self.assertIsNotNone(self.claim())
            with database.connect() as db:
                db.execute("UPDATE analysis_jobs SET lease_until=0 WHERE state='processing'")
        self.assertIsNone(self.claim())
        self.assertEqual(self.detail(report['id'])['verification_status'],'needs_review')

    def test_model_photo_and_box_binding(self):
        self.submit()
        job = self.claim()
        for field,value in [('model_sha256','0'*64),('image_sha256','0'*64),('image_width',63)]:
            result = self.payload(job)
            result[field] = value
            self.assertEqual(self.client.post(f"/worker/jobs/{job['id']}/result",headers=self.worker_headers,json=result).status_code,400)
        result = self.payload(job)
        result['detections'][0]['bbox_xyxy'] = [20,20,10,10]
        self.assertEqual(self.client.post(f"/worker/jobs/{job['id']}/result",headers=self.worker_headers,json=result).status_code,400)
        result = self.payload(job)
        result['detections'][0]['confidence'] = 'NaN'
        self.assertEqual(self.client.post(f"/worker/jobs/{job['id']}/result",headers=self.worker_headers,json=result).status_code,400)
        self.complete(job)

    def test_worker_is_scoped_to_leased_photos_not_citizen_or_admin_routes(self):
        report = self.submit().json()
        self.assertEqual(self.client.post('/worker/jobs/claim',headers=self.citizen,json={'worker_id':'rogue'}).status_code,401)
        self.assertEqual(self.client.get('/reports',headers=self.worker_headers).status_code,401)
        job = self.claim()
        headers = {**self.worker_headers,'X-Lease-Token':job['lease_token']}
        self.assertEqual(self.client.get(job['input_path'],headers=headers).status_code,200)
        self.assertEqual(self.client.get(f"/worker/jobs/{job['id']}/candidates/{report['id']}",headers=headers).status_code,403)
        self.assertEqual(self.client.get(job['input_path'],headers={**self.worker_headers,'X-Lease-Token':'x'*48}).status_code,409)

    def test_no_detection_is_saved_for_review_not_rejected_or_published(self):
        report = self.submit().json()
        self.complete(detections=[])
        saved = self.detail(report['id'])
        self.assertEqual(saved['verification_status'],'needs_review')
        self.assertEqual(saved['status'],'open')
        self.assertFalse(self.issue(saved['issue_id'])['published'])
        self.assertEqual(self.client.get('/issues',headers=self.nigam).json()['total'],0)
        review = self.client.patch(f"/processing/reports/{report['id']}/review",headers=self.admin,
                                  json={'verification_status':'supported','reason':'Human inspected the photo'})
        self.assertEqual(review.status_code,200)
        self.assertTrue(self.issue(saved['issue_id'])['published'])

    def test_status_updates_reach_every_linked_citizen(self):
        first = self.processed()
        other = self.account('second-citizen')
        second = self.processed(headers=other)
        issue_id = first['issue_id']
        self.assertEqual(second['issue_id'],issue_id)
        self.assertEqual(self.client.patch(f'/issues/{issue_id}/status',headers=self.citizen,
                         json={'status':'resolved','note':'not authorized'}).status_code,403)
        changed = self.client.patch(f'/issues/{issue_id}/status',headers=self.nigam,
                                    json={'status':'resolved','note':'Repair completed'})
        self.assertEqual(changed.status_code,200,changed.text)
        self.assertEqual(changed.json()['priority_score'],0)
        for report,headers in [(first,self.citizen),(second,other)]:
            self.assertEqual(self.client.get(f"/reports/{report['id']}",headers=headers).json()['status'],'resolved')
        self.assertEqual(self.client.get(f'/issues/{issue_id}/history',headers=self.nigam).json()[0]['event'],'repair_status')

    def test_priority_uses_distinct_supported_accounts_not_submissions_or_confidence(self):
        first = self.processed()
        self.processed()
        self.assertEqual(self.issue(first['issue_id'])['priority_score'],7)
        person = self.account('another')
        self.processed(headers=person)
        issue = self.issue(first['issue_id'])
        self.assertEqual(issue['reporter_count'],2)
        self.assertEqual(issue['priority_score'],14)
        self.assertEqual(priority(100,0,now=86400*100)[0],100)
        self.assertEqual(priority(1,100,now=0)[0],7)

    def test_late_worker_result_cannot_overwrite_admin_review(self):
        report = self.submit().json()
        job = self.claim()
        review = self.client.patch(f"/processing/reports/{report['id']}/review",headers=self.admin,
                                  json={'verification_status':'not_supported','reason':'Human found unrelated content'})
        self.assertEqual(review.status_code,200)
        response = self.client.post(f"/worker/jobs/{job['id']}/result",headers=self.worker_headers,json=self.payload(job))
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.detail(report['id'])['verification_status'],'not_supported')

    def test_actual_worker_transport_with_stub_detector(self):
        self.submit()
        detector = Mock(return_value={'model_version':'nagarsaathi-yolo11n-v3',
                                     'detections':[{'label':'pothole','confidence':.9,'bbox_xyxy':[2,2,60,60]}]})
        worker = PCWorker('http://testserver',self.key,'pc-client',client=self.client,detector=detector)
        self.assertTrue(worker.run_once())
        self.assertEqual(detector.call_count,1)
        self.assertFalse(worker.run_once())
        self.assertEqual(self.client.get('/issues',headers=self.nigam).json()['total'],1)

    def test_one_hundred_reports_form_twenty_actual_fixture_groups(self):
        people = [self.citizen] + [self.account(f'contributor-{i}') for i in range(4)]
        for group in range(20):
            for headers in people:
                self.processed(headers=headers,image=photo((group*10,20,30)),lat=12+group*.01)
        admin = self.client.get('/complaints?limit=100',headers=self.admin).json()
        municipal = self.client.get('/issues?limit=100',headers=self.nigam).json()
        self.assertEqual(admin['total'],100)
        self.assertEqual(municipal['total'],20)
        self.assertTrue(all((r['report_count'],r['reporter_count']) == (5,5) for r in municipal['items']))

    def test_opt_in_geometric_matching_uses_actual_defect_comparison(self):
        from backend.evaluate_matching import controlled_pairs
        first,second,da,db,_ = next(iter(controlled_pairs()))
        detector = Mock(return_value={'model_version':'nagarsaathi-yolo11n-v3','detections':da})
        worker = PCWorker('http://testserver',self.key,'geometry-pc',client=self.client,detector=detector)
        with patch.dict(os.environ,{'NAGARSAATHI_VISUAL_AUTO_MERGE':'1'}):
            issue_ids = []
            for image in (first,second):
                stream = io.BytesIO()
                image.save(stream,format='PNG')
                report = self.submit(image=stream.getvalue()).json()
                worker.run_once()
                issue_ids.append(self.detail(report['id'])['issue_id'])
            self.assertEqual(issue_ids[0],issue_ids[1])
            self.assertEqual(self.issue(issue_ids[0])['unique_photo_count'],2)

    def test_weak_mismatched_and_incomplete_both_evidence_stay_private(self):
        cases = [('pothole',[{'label':'waterlogging','confidence':.9,'bbox_xyxy':[2,2,60,60]}]),
                 ('pothole',[{'label':'pothole','confidence':.3,'bbox_xyxy':[2,2,60,60]}]),
                 ('both',[{'label':'pothole','confidence':.9,'bbox_xyxy':[2,2,60,60]}])]
        for category,detections in cases:
            report = self.submit(category=category).json()
            self.complete(detections=detections)
            self.assertEqual(self.detail(report['id'])['verification_status'],'needs_review')
        self.assertEqual(self.client.get('/issues',headers=self.nigam).json()['total'],0)

    def test_explicit_withholding_survives_new_supported_reports(self):
        first = self.processed()
        response = self.client.patch(f"/issues/{first['issue_id']}/publication",headers=self.admin,json={'published':False})
        self.assertEqual(response.status_code,200)
        self.processed()
        self.assertFalse(self.issue(first['issue_id'])['published'])
        self.assertEqual(self.client.get('/issues',headers=self.nigam).json()['total'],0)
