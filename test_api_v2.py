"""
SmartAttend AI - End-to-End API Integration & RBAC Test Suite
Tests FastAPI endpoints using FastAPI TestClient:
- Health probe
- Unified Auth (/api/auth/login, /api/auth/me) with RBAC
- Teacher Portal endpoints (/api/teacher/classes, /api/teacher/sessions/start, qr)
- Student Portal endpoints (/api/student/dashboard, leaves)
- AI Analytics endpoints (/api/analytics/departments, /api/analytics/trends)
- Safe CSV Export endpoints (/api/reports/attendance/csv)
- Offline Sync endpoint (/api/attendance/sync-offline)
"""
import os
import sys
import tempfile
import unittest
from fastapi.testclient import TestClient

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import server
from database.db_manager import DatabaseManager
from core.offline_sync import create_offline_attendance_packet


class TestAPIV2Integration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.temp_dir.name, "test_api_v2.db")
        cls.db = DatabaseManager(cls.db_path)
        cls.db.ensure_default_admin("admin", "admin123")

        # Create sample department and teacher
        cls.db.create_department("Computer Science", "CSE")
        cls.db.create_teacher("EMP001", "Prof. Verma", "verma@college.edu", "FacultyPass123", department_id=1)

        # Wire global singletons into server
        server.db = cls.db
        from core.ml_analytics import AttendanceAnalyticsEngine
        from core.notification_service import NotificationService
        from core.reports_engine import ReportsEngine
        from core.offline_sync import OfflineSyncEngine
        from core.anti_proxy import MultiLayerVerificationEngine

        server.analytics_engine = AttendanceAnalyticsEngine(cls.db)
        server.notification_service = NotificationService(cls.db)
        server.reports_engine = ReportsEngine(cls.db)
        server.offline_sync_engine = OfflineSyncEngine(cls.db)
        server.anti_proxy_engine = MultiLayerVerificationEngine()

        cls.client = TestClient(server.app)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.temp_dir.cleanup()
        except Exception:
            pass

    def test_health_check_endpoint(self):
        """Health endpoint returns 200 and healthy status."""
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "healthy")

    def test_admin_login_and_auth_me(self):
        """Admin logs in via /api/auth/login and checks /api/auth/me."""
        res = self.client.post("/api/auth/login", json={
            "role": "ADMIN",
            "username": "admin",
            "password": "admin123"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        token = data["token"]
        self.assertIsNotNone(token)

        # Access /api/auth/me with Bearer token
        res_me = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res_me.status_code, 200)
        me_data = res_me.json()
        self.assertEqual(me_data["user"]["role"], "ADMIN")

    def test_teacher_login_and_assigned_classes(self):
        """Teacher logs in and accesses /api/teacher/classes."""
        res = self.client.post("/api/auth/login", json={
            "role": "TEACHER",
            "username": "verma@college.edu",
            "password": "FacultyPass123"
        })
        self.assertEqual(res.status_code, 200)
        token = res.json()["token"]

        res_classes = self.client.get("/api/teacher/classes", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res_classes.status_code, 200)
        data = res_classes.json()
        self.assertIn("assigned_subjects", data)

    def test_analytics_departments_endpoint(self):
        """Analytics departments returns department breakdown."""
        # Get admin token
        res_login = self.client.post("/api/auth/login", json={
            "role": "ADMIN", "username": "admin", "password": "admin123"
        })
        token = res_login.json()["token"]

        res = self.client.get("/api/analytics/departments", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("departments", data)
        self.assertGreaterEqual(len(data["departments"]), 1)

    def test_safe_csv_export_endpoint(self):
        """CSV export endpoint returns text/csv header and clean content."""
        res_login = self.client.post("/api/auth/login", json={
            "role": "ADMIN", "username": "admin", "password": "admin123"
        })
        token = res_login.json()["token"]

        res = self.client.get("/api/reports/attendance/csv", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/csv", res.headers.get("content-type", ""))
        self.assertIn("Attendance ID", res.text)

    def test_offline_sync_endpoint(self):
        """Submitting an offline batch via API returns sync summary."""
        res_login = self.client.post("/api/auth/login", json={
            "role": "ADMIN", "username": "admin", "password": "admin123"
        })
        token = res_login.json()["token"]

        packet = create_offline_attendance_packet(
            student_id=999,  # Unregistered student
            session_id=1,
            device_id="TEST-DEV",
            timestamp_epoch=1700000000
        )

        res = self.client.post(
            "/api/attendance/sync-offline",
            json={"packets": [packet]},
            headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total_submitted"], 1)
        self.assertEqual(data["rejected_count"], 1)  # Rejected because student 999 not found


if __name__ == "__main__":
    unittest.main(verbosity=2)
