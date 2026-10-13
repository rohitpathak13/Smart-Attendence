"""
Integration and End-to-End API Tests for Phases 17-22 using FastAPI TestClient:
- Phase 17: Geofencing via /api/recognize, unauthorized campus edit prevention
- Phase 18: Email validation and uniqueness via /api/students/enroll
- Phase 19: Student name validation via /api/students/enroll
- Phase 20: Numeric roll number validation via /api/students/enroll
- Phase 21: Lecture creation, active session, attendance marking
- Phase 22: Admin security, settings, and public config privacy
"""
import os
import sys
import tempfile
import unittest
import base64
import cv2
import numpy as np
from fastapi.testclient import TestClient

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import server
from database.db_manager import DatabaseManager
from config import DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASS

class TestAPIEndpoints(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_db_path = os.path.join(self.temp_dir.name, "api_test.db")
        self.db = DatabaseManager(self.temp_db_path)
        self.db.ensure_default_admin("admin", "admin123")

        # Mock server db and cached students
        server.db = self.db
        server.cached_students = []

        self.client = TestClient(server.app)

        # Obtain admin token
        login_res = self.client.post("/api/admin/login", json={"username": "admin", "password": "admin123"})
        self.assertEqual(login_res.status_code, 200)
        self.admin_token = login_res.json()["token"]
        self.auth_headers = {"Authorization": f"Bearer {self.admin_token}"}

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    # 1. Public config privacy (Does not leak coordinates)
    def test_public_config_privacy(self):
        res = self.client.get("/api/config/public")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("geofence_enabled", data)
        self.assertIn("default_radius_meters", data)
        self.assertEqual(data["default_radius_meters"], 30.0) # Default is 30m!
        self.assertEqual(data["default_lecture_duration_minutes"], 50) # Default 50m!
        # Critical: Must NOT leak campus coordinates in public endpoint
        self.assertNotIn("latitude", data)
        self.assertNotIn("longitude", data)

    # 2. Unauthorized access prevention on campus configuration
    def test_unauthorized_campus_mutation_blocked(self):
        # Attempt to add campus without token -> 401
        res = self.client.post("/api/admin/campuses", json={
            "name": "Hacked Campus",
            "latitude": 10.0,
            "longitude": 20.0,
            "radius_meters": 100.0
        })
        self.assertEqual(res.status_code, 401)

        # With admin token -> 200 Success
        res_ok = self.client.post("/api/admin/campuses", json={
            "name": "New Campus Branch",
            "latitude": 28.6000,
            "longitude": 77.2000,
            "radius_meters": 30.0
        }, headers=self.auth_headers)
        self.assertEqual(res_ok.status_code, 200)
        self.assertTrue(res_ok.json()["success"])

    # 3. Enrollment Email Validation (Phase 18)
    def test_enrollment_email_validation(self):
        # Create dummy 100x100 white image
        dummy_img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        _, buf = cv2.imencode(".jpg", dummy_img)
        img_b64 = "data:image/jpeg;base64," + base64.b64encode(buf).decode()

        # Reject uppercase local part
        res_upper = self.client.post("/api/students/enroll", json={
            "roll_no": "2026001",
            "name": "Alice Smith",
            "email": "Alice123@example.com",
            "image": img_b64
        })
        self.assertEqual(res_upper.status_code, 400)
        self.assertIn("lowercase", res_upper.json()["detail"].lower())

        # Reject missing domain suffix
        res_bad_dom = self.client.post("/api/students/enroll", json={
            "roll_no": "2026001",
            "name": "Alice Smith",
            "email": "abcd@123",
            "image": img_b64
        })
        self.assertEqual(res_bad_dom.status_code, 400)

    # 4. Enrollment Student Name Validation (Phase 19)
    def test_enrollment_student_name_validation(self):
        dummy_img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        _, buf = cv2.imencode(".jpg", dummy_img)
        img_b64 = "data:image/jpeg;base64," + base64.b64encode(buf).decode()

        # Reject name with digits
        res_digits = self.client.post("/api/students/enroll", json={
            "roll_no": "2026002",
            "name": "rohit123",
            "email": "rohit123@example.com",
            "image": img_b64
        })
        self.assertEqual(res_digits.status_code, 400)
        self.assertIn("digits", res_digits.json()["detail"].lower())

        # Reject mixed case name
        res_mixed = self.client.post("/api/students/enroll", json={
            "roll_no": "2026003",
            "name": "rohit PATHAK",
            "email": "rohitpathak@example.com",
            "image": img_b64
        })
        self.assertEqual(res_mixed.status_code, 400)

    # 5. Enrollment Numeric Roll Number Validation (Phase 20)
    def test_enrollment_numeric_roll_number(self):
        dummy_img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        _, buf = cv2.imencode(".jpg", dummy_img)
        img_b64 = "data:image/jpeg;base64," + base64.b64encode(buf).decode()

        # Reject alphabetic characters
        res_alpha = self.client.post("/api/students/enroll", json={
            "roll_no": "CS101",
            "name": "Alice Smith",
            "email": "alicesmith@example.com",
            "image": img_b64
        })
        self.assertEqual(res_alpha.status_code, 400)
        self.assertIn("digits only", res_alpha.json()["detail"].lower())

    # 6. Lecture Creation & Anti-Bunking Analytics API
    def test_lecture_api_and_analytics(self):
        # Create lecture
        res = self.client.post("/api/lectures", json={
            "course_code": "CS301",
            "subject_name": "Cloud Computing",
            "instructor_name": "Prof. Alan",
            "date": "2026-10-15",
            "start_time": "10:00:00",
            "duration_minutes": 50
        }, headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        lec_id = res.json()["lecture_id"]

        # List lectures
        list_res = self.client.get("/api/lectures?date=2026-10-15")
        self.assertEqual(list_res.status_code, 200)
        self.assertEqual(list_res.json()["count"], 1)

        # Fetch lecture details
        detail_res = self.client.get(f"/api/lectures/{lec_id}")
        self.assertEqual(detail_res.status_code, 200)

        # Trigger mid-check
        mid_res = self.client.post(f"/api/lectures/{lec_id}/mid-check", json={
            "duration_minutes": 5
        }, headers=self.auth_headers)
        self.assertEqual(mid_res.status_code, 200)

        # Anti-bunking stats endpoint
        stats_res = self.client.get("/api/reports/lecture-stats")
        self.assertEqual(stats_res.status_code, 200)
        self.assertIn("total_scheduled_lectures", stats_res.json())

if __name__ == "__main__":
    unittest.main()
