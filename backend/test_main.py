"""Comprehensive test suite for NAGARSAATHI Phase 2 backend."""
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from backend import accounts, database, inference, reports
from backend.accounts import create_user
from backend.main import app


class BackendComprehensiveTests(unittest.TestCase):
    def test_full_system_lifecycle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            with patch.object(database, "DATA_DIR", temp_path), \
                 patch.object(reports, "DATA_DIR", temp_path), \
                 patch.object(inference, "load_model", return_value=None):

                with TestClient(app) as client:
                    # 1. Registration tests
                    # Public registration with attempted role='admin' must still register as 'citizen'
                    reg_resp = client.post("/auth/register", json={
                        "name": "Citizen One",
                        "email": "citizen1@example.com",
                        "password": "securepassword123",
                        "role": "admin"
                    })
                    self.assertEqual(reg_resp.status_code, 201)
                    self.assertEqual(reg_resp.json()["role"], "citizen")

                    # Register second citizen
                    reg_resp2 = client.post("/auth/register", json={
                        "name": "Citizen Two",
                        "email": "citizen2@example.com",
                        "password": "securepassword123"
                    })
                    self.assertEqual(reg_resp2.status_code, 201)
                    self.assertEqual(reg_resp2.json()["role"], "citizen")

                    # Duplicate email rejection
                    dup_resp = client.post("/auth/register", json={
                        "name": "Duplicate",
                        "email": "citizen1@example.com",
                        "password": "securepassword123"
                    })
                    self.assertEqual(dup_resp.status_code, 409)

                    # 2. Login and Session tests
                    # Wrong password
                    bad_login = client.post("/auth/login", json={
                        "email": "citizen1@example.com",
                        "password": "wrongpassword"
                    })
                    self.assertEqual(bad_login.status_code, 401)

                    # Successful login
                    login1 = client.post("/auth/login", json={
                        "email": "citizen1@example.com",
                        "password": "securepassword123"
                    })
                    self.assertEqual(login1.status_code, 200)
                    token1 = login1.json()["access_token"]
                    headers1 = {"Authorization": f"Bearer {token1}"}

                    login2 = client.post("/auth/login", json={
                        "email": "citizen2@example.com",
                        "password": "securepassword123"
                    })
                    token2 = login2.json()["access_token"]
                    headers2 = {"Authorization": f"Bearer {token2}"}

                    # Current user endpoint /auth/me
                    me_resp = client.get("/auth/me", headers=headers1)
                    self.assertEqual(me_resp.status_code, 200)
                    self.assertEqual(me_resp.json()["email"], "citizen1@example.com")
                    self.assertEqual(me_resp.json()["role"], "citizen")

                    # Create admin account via internal/CLI helper
                    create_user("Admin Officer", "admin@nagarsaathi.org", "adminpassword123", role="admin")
                    admin_login = client.post("/auth/login", json={
                        "email": "admin@nagarsaathi.org",
                        "password": "adminpassword123"
                    })
                    self.assertEqual(admin_login.status_code, 200)
                    admin_token = admin_login.json()["access_token"]
                    admin_headers = {"Authorization": f"Bearer {admin_token}"}

                    # Prepare valid test image
                    img_stream = io.BytesIO()
                    Image.new("RGB", (64, 64), color="grey").save(img_stream, format="PNG")
                    img_bytes = img_stream.getvalue()

                    def submit(headers=headers1, desc="Pothole on Main Road", lat="12.9716", lon="77.5946", content=img_bytes):
                        return client.post(
                            "/reports",
                            headers=headers,
                            data={"description": desc, "latitude": lat, "longitude": lon, "issue_type": "pothole"},
                            files={"image": ("road.png", content, "image/png")}
                        )

                    # 3. Model detection: zero boxes
                    empty_detection = {
                        "image_width": 64,
                        "image_height": 64,
                        "model_version": "test-yolo11n",
                        "confidence_threshold": 0.35,
                        "detections": []
                    }
                    with patch.object(inference, "detect_potholes", return_value=empty_detection):
                        rep1_resp = submit(headers=headers1)
                        self.assertEqual(rep1_resp.status_code, 201)
                        rep1 = rep1_resp.json()
                        rep1_id = rep1["id"]
                        self.assertEqual(rep1["analysis_status"], "completed")
                        self.assertEqual(rep1["analysis"]["detections"], [])
                        self.assertEqual(rep1["status"], "open")
                        self.assertEqual(rep1["priority"], "normal")

                    # Nearby duplicate detection suggestion (within 30m)
                    with patch.object(inference, "detect_potholes", return_value=empty_detection):
                        # Same location from citizen2
                        rep2_resp = submit(headers=headers2, desc="Another complaint at junction")
                        self.assertEqual(rep2_resp.status_code, 201)
                        rep2 = rep2_resp.json()
                        self.assertEqual(rep2["duplicate_of"], rep1_id)

                    # 4. Model detection: exception / failure handling
                    with patch.object(inference, "detect_potholes", side_effect=RuntimeError("GPU OOM / Timeout")):
                        rep3_resp = submit(headers=headers1, desc="Complaint with model exception")
                        self.assertEqual(rep3_resp.status_code, 201)
                        rep3 = rep3_resp.json()
                        # Safe storage: complaint is still saved despite model failure
                        self.assertEqual(rep3["analysis_status"], "failed")
                        self.assertEqual(rep3["status"], "open")

                    # 5. Model unavailable handling
                    app.state.model_ready = False
                    rep4_resp = submit(headers=headers1, desc="Complaint when model unavailable")
                    self.assertEqual(rep4_resp.status_code, 201)
                    self.assertEqual(rep4_resp.json()["analysis_status"], "unavailable")
                    app.state.model_ready = True

                    # 6. Invalid image content rejection
                    bad_img_resp = submit(headers=headers1, content=b"not an image file")
                    self.assertEqual(bad_img_resp.status_code, 400)

                    # 7. Role-based Access Control (Citizens see only their own)
                    # Citizen 2 cannot access Citizen 1's report
                    other_get = client.get(f"/reports/{rep1_id}", headers=headers2)
                    self.assertEqual(other_get.status_code, 404)

                    # Citizen 2 cannot access Citizen 1's photo
                    other_photo = client.get(f"/reports/{rep1_id}/photo", headers=headers2)
                    self.assertEqual(other_photo.status_code, 404)

                    # Citizen 1 can access their own report & photo
                    own_get = client.get(f"/reports/{rep1_id}", headers=headers1)
                    self.assertEqual(own_get.status_code, 200)
                    own_photo = client.get(f"/reports/{rep1_id}/photo", headers=headers1)
                    self.assertEqual(own_photo.status_code, 200)

                    # List reports: Citizen 2 only sees 1 report (theirs)
                    c2_list = client.get("/reports", headers=headers2)
                    self.assertEqual(len(c2_list.json()), 1)

                    # Citizen cannot update/review reports (PATCH forbidden)
                    citizen_patch = client.patch(
                        f"/reports/{rep1_id}",
                        headers=headers1,
                        json={"status": "in_progress", "priority": "high", "priority_reason": "urgent"}
                    )
                    self.assertEqual(citizen_patch.status_code, 403)

                    # 8. Admin privileges
                    # Admin can see all reports
                    admin_list = client.get("/reports", headers=admin_headers)
                    self.assertEqual(admin_list.status_code, 200)
                    self.assertGreaterEqual(len(admin_list.json()), 3)

                    # Admin can view photo of any citizen
                    admin_photo = client.get(f"/reports/{rep1_id}/photo", headers=admin_headers)
                    self.assertEqual(admin_photo.status_code, 200)

                    # Admin can review and update status
                    review_body = {
                        "status": "in_progress",
                        "priority": "urgent",
                        "priority_reason": "High traffic area near hospital",
                        "duplicate_of": None
                    }
                    admin_patch = client.patch(f"/reports/{rep1_id}", headers=admin_headers, json=review_body)
                    self.assertEqual(admin_patch.status_code, 200)
                    self.assertEqual(admin_patch.json()["priority"], "urgent")
                    self.assertEqual(admin_patch.json()["status"], "in_progress")

                    # 9. Logout
                    logout_resp = client.post("/auth/logout", headers=headers2)
                    self.assertEqual(logout_resp.status_code, 204)
                    revoked_me = client.get("/auth/me", headers=headers2)
                    self.assertEqual(revoked_me.status_code, 401)

                # 10. Persistence across application lifespan restart
                with TestClient(app) as restarted_client:
                    restarted_login = restarted_client.post("/auth/login", json={
                        "email": "citizen1@example.com",
                        "password": "securepassword123"
                    })
                    self.assertEqual(restarted_login.status_code, 200)
                    new_token = restarted_login.json()["access_token"]
                    persisted_report = restarted_client.get(
                        f"/reports/{rep1_id}",
                        headers={"Authorization": f"Bearer {new_token}"}
                    )
                    self.assertEqual(persisted_report.status_code, 200)
                    self.assertEqual(persisted_report.json()["priority"], "urgent")
                    self.assertEqual(persisted_report.json()["status"], "in_progress")

                    # Photo file persists as well
                    persisted_photo = restarted_client.get(
                        f"/reports/{rep1_id}/photo",
                        headers={"Authorization": f"Bearer {new_token}"}
                    )
                    self.assertEqual(persisted_photo.status_code, 200)


if __name__ == "__main__":
    unittest.main()
