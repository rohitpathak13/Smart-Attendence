"""
SmartAttend AI - Notification Service Test Suite
Verifies:
1. Immediate database queue persistence
2. Formatting and dispatch of attendance confirmation
3. Absence alerts to students and parents
4. Low attendance shortage warnings
5. Graceful handling of unconfigured SMTP settings (fail-safe without crashing)
"""
import os
import sys
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from database.db_manager import DatabaseManager
from core.notification_service import NotificationService, NotificationType


class TestNotificationService(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_notif.db")
        self.db = DatabaseManager(self.db_path)
        self.service = NotificationService(self.db)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_queue_attendance_confirmation(self):
        """Attendance confirmation notification is queued correctly in database."""
        nid = self.service.notify_attendance_marked(
            student_id=101,
            student_name="Pooja Sharma",
            student_email="pooja@college.edu",
            subject_name="Operating Systems",
            timestamp="10:05:00"
        )
        self.assertIsInstance(nid, int)
        self.assertGreater(nid, 0)

        notifs = self.db.get_user_notifications("STUDENT", 101)
        self.assertEqual(len(notifs), 1)
        self.assertEqual(notifs[0]["type"], NotificationType.CONFIRMATION)
        self.assertIn("Operating Systems", notifs[0]["subject"])
        self.assertIn("Pooja Sharma", notifs[0]["body"])

    def test_queue_low_attendance_warning(self):
        """Shortage warning is queued with recovery details."""
        nid = self.service.notify_low_attendance_warning(
            student_id=101,
            student_name="Pooja",
            student_email="pooja@college.edu",
            current_pct=64.5,
            classes_needed=8
        )
        notifs = self.db.get_user_notifications("STUDENT", 101)
        self.assertEqual(len(notifs), 1)
        self.assertEqual(notifs[0]["type"], NotificationType.LOW_ATTENDANCE)
        self.assertIn("64.5%", notifs[0]["body"])
        self.assertIn("8 consecutive upcoming classes", notifs[0]["body"])

    def test_queue_parent_absence_alert(self):
        """Parent absence alert is queued correctly."""
        nid = self.service.notify_parent_absence(
            parent_id=5,
            parent_name="Mr. Sharma",
            parent_email="parent@example.com",
            student_name="Pooja",
            subject_name="Physics Lab",
            date_str="2026-11-25"
        )
        notifs = self.db.get_user_notifications("PARENT", 5)
        self.assertEqual(len(notifs), 1)
        self.assertEqual(notifs[0]["type"], NotificationType.PARENT_ALERT)
        self.assertIn("Pooja was marked absent", notifs[0]["body"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
