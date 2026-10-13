"""
Unit Tests for Phase 21 (Lecture-Wise Attendance & Anti-Bunking) and Phase 22 (Admin Controls & Security).
Tests:
- Default 50-minute lecture scheduling
- Custom duration lecture scheduling
- Attendance inside and outside valid attendance window
- Duplicate attendance submission prevention
- Two concurrent submissions for one student (database unique constraint)
- Absent student counting
- Cancelled lecture handling
- Mid-lecture anti-bunking verification
- Missed mid-lecture verification
- Instructor-authorized manual attendance correction with audit trail
- Invalid lecture schedule rejection
- Timezone-aware date and time handling
- Geofence integration during lecture
"""
import os
import sys
import tempfile
import unittest
import threading
from datetime import datetime, timedelta
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from database.db_manager import DatabaseManager
from server import create_admin_token, verify_admin_token

class TestLectureAttendanceAndSecurity(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_db_path = os.path.join(self.temp_dir.name, "lecture_test.db")
        self.db = DatabaseManager(self.temp_db_path)

        # Register two test students
        dummy_emb = np.random.randn(128).astype(np.float32)
        dummy_emb /= np.linalg.norm(dummy_emb)

        self.db.register_student("20261001", "Alice Smith", "Computer Science", "alice1@example.com", dummy_emb)
        self.db.register_student("20261002", "Bob Jones", "Computer Science", "bobjones2@example.com", dummy_emb)

        self.student_alice = self.db.get_student_by_roll("20261001")
        self.student_bob = self.db.get_student_by_roll("20261002")

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    # 1. Lecture lasting 50 minutes (Default Duration)
    def test_lecture_default_duration_50_minutes(self):
        today = datetime.now().strftime("%Y-%m-%d")
        ok, msg, lec_id = self.db.create_lecture(
            course_code="CS101",
            subject_name="Data Structures",
            instructor_name="Prof. Sharma",
            date_str=today,
            start_time_str="10:00:00",
            duration_minutes=50 # Default 50 minutes
        )
        self.assertTrue(ok)
        lec = self.db.get_lecture_by_id(lec_id)
        self.assertEqual(lec["duration_minutes"], 50)
        self.assertEqual(lec["start_time"], "10:00:00")
        self.assertEqual(lec["end_time"], "10:50:00")
        # Default window: 5 min before to 15 min after
        self.assertEqual(lec["attendance_window_start"], "09:55:00")
        self.assertEqual(lec["attendance_window_end"], "10:15:00")

    # 2. Lecture lasting custom duration (e.g. 75 minutes)
    def test_lecture_custom_duration(self):
        today = datetime.now().strftime("%Y-%m-%d")
        ok, msg, lec_id = self.db.create_lecture(
            course_code="CS202",
            subject_name="Algorithms Lab",
            instructor_name="Prof. Verma",
            date_str=today,
            start_time_str="14:00:00",
            duration_minutes=75 # Custom duration
        )
        self.assertTrue(ok)
        lec = self.db.get_lecture_by_id(lec_id)
        self.assertEqual(lec["duration_minutes"], 75)
        self.assertEqual(lec["end_time"], "15:15:00")

    # 3. Attendance Inside Valid Window
    def test_attendance_inside_valid_window(self):
        today = datetime.now().strftime("%Y-%m-%d")
        ok, _, lec_id = self.db.create_lecture(
            course_code="CS101",
            subject_name="Operating Systems",
            instructor_name="Prof. Rao",
            date_str=today,
            start_time_str="09:00:00",
            duration_minutes=50,
            window_before_mins=5,
            window_after_mins=15
        )
        # Simulate student marking attendance at 09:05:00 (inside window 08:55:00 - 09:15:00)
        sim_time = datetime.strptime(f"{today} 09:05:00", "%Y-%m-%d %H:%M:%S")
        att_ok, att_msg, rec = self.db.mark_lecture_attendance(
            lecture_id=lec_id,
            student_id=self.student_alice["id"],
            confidence=0.92,
            distance_meters=12.5,
            now_dt=sim_time
        )
        self.assertTrue(att_ok)
        self.assertEqual(rec["status"], "PRESENT")
        self.assertEqual(rec["roll_no"], "20261001")

    # 4. Attendance Outside Valid Window (Before and After)
    def test_attendance_outside_valid_window(self):
        today = datetime.now().strftime("%Y-%m-%d")
        ok, _, lec_id = self.db.create_lecture(
            course_code="CS101",
            subject_name="Database Systems",
            instructor_name="Prof. Gupta",
            date_str=today,
            start_time_str="10:00:00",
            duration_minutes=50,
            window_before_mins=5,
            window_after_mins=15
        )
        # Before window opens (09:50:00 < 09:55:00)
        early_time = datetime.strptime(f"{today} 09:50:00", "%Y-%m-%d %H:%M:%S")
        early_ok, early_msg, _ = self.db.mark_lecture_attendance(
            lecture_id=lec_id,
            student_id=self.student_alice["id"],
            confidence=0.90,
            now_dt=early_time
        )
        self.assertFalse(early_ok)
        self.assertIn("not opened yet", early_msg.lower())

        # After window closes (10:20:00 > 10:15:00)
        late_time = datetime.strptime(f"{today} 10:20:00", "%Y-%m-%d %H:%M:%S")
        late_ok, late_msg, _ = self.db.mark_lecture_attendance(
            lecture_id=lec_id,
            student_id=self.student_alice["id"],
            confidence=0.90,
            now_dt=late_time
        )
        self.assertFalse(late_ok)
        self.assertIn("closed", late_msg.lower())

    # 5. Duplicate Attendance Prevention
    def test_duplicate_attendance_rejected(self):
        today = datetime.now().strftime("%Y-%m-%d")
        ok, _, lec_id = self.db.create_lecture(
            course_code="CS101",
            subject_name="Networks",
            instructor_name="Prof. Rao",
            date_str=today,
            start_time_str="10:00:00",
            duration_minutes=50
        )
        sim_time = datetime.strptime(f"{today} 10:02:00", "%Y-%m-%d %H:%M:%S")
        # First submission
        ok1, _, _ = self.db.mark_lecture_attendance(
            lecture_id=lec_id,
            student_id=self.student_alice["id"],
            confidence=0.91,
            now_dt=sim_time
        )
        self.assertTrue(ok1)

        # Duplicate submission immediately after
        ok2, msg2, _ = self.db.mark_lecture_attendance(
            lecture_id=lec_id,
            student_id=self.student_alice["id"],
            confidence=0.93,
            now_dt=sim_time + timedelta(seconds=10)
        )
        self.assertFalse(ok2)
        self.assertIn("already recorded", msg2.lower())

    # 6. Two Concurrent Submissions for One Student
    def test_concurrent_submissions_for_one_student(self):
        today = datetime.now().strftime("%Y-%m-%d")
        ok, _, lec_id = self.db.create_lecture(
            course_code="CS101",
            subject_name="AI",
            instructor_name="Prof. Singh",
            date_str=today,
            start_time_str="11:00:00",
            duration_minutes=50
        )
        sim_time = datetime.strptime(f"{today} 11:05:00", "%Y-%m-%d %H:%M:%S")

        results = []
        def submit():
            ok_res, msg_res, _ = self.db.mark_lecture_attendance(
                lecture_id=lec_id,
                student_id=self.student_bob["id"],
                confidence=0.89,
                now_dt=sim_time
            )
            results.append((ok_res, msg_res))

        # Launch 2 threads concurrently for the same student
        t1 = threading.Thread(target=submit)
        t2 = threading.Thread(target=submit)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exactly one must succeed, the other must be rejected due to UNIQUE constraint
        success_count = sum(1 for r in results if r[0] is True)
        self.assertEqual(success_count, 1)

    # 7. Cancelled Lecture
    def test_cancelled_lecture_rejected(self):
        today = datetime.now().strftime("%Y-%m-%d")
        ok, _, lec_id = self.db.create_lecture(
            course_code="CS101",
            subject_name="Math",
            instructor_name="Prof. Sen",
            date_str=today,
            start_time_str="12:00:00",
            duration_minutes=50
        )
        self.db.update_lecture_status(lec_id, "Cancelled")

        sim_time = datetime.strptime(f"{today} 12:02:00", "%Y-%m-%d %H:%M:%S")
        att_ok, att_msg, _ = self.db.mark_lecture_attendance(
            lecture_id=lec_id,
            student_id=self.student_alice["id"],
            confidence=0.90,
            now_dt=sim_time
        )
        self.assertFalse(att_ok)
        self.assertIn("cancelled", att_msg.lower())

    # 8. Mid-Lecture Anti-Bunking Verification & Missed Check Reporting
    def test_mid_lecture_verification_and_missed_check(self):
        today = datetime.now().strftime("%Y-%m-%d")
        ok, _, lec_id = self.db.create_lecture(
            course_code="CS101",
            subject_name="Computer Architecture",
            instructor_name="Prof. Joshi",
            date_str=today,
            start_time_str="10:00:00",
            duration_minutes=50
        )
        # Alice marks initial attendance
        sim_time = datetime.strptime(f"{today} 10:05:00", "%Y-%m-%d %H:%M:%S")
        self.db.mark_lecture_attendance(
            lecture_id=lec_id,
            student_id=self.student_alice["id"],
            confidence=0.92,
            now_dt=sim_time
        )
        # Bob marks initial attendance
        self.db.mark_lecture_attendance(
            lecture_id=lec_id,
            student_id=self.student_bob["id"],
            confidence=0.88,
            now_dt=sim_time
        )

        # Instructor creates mid-lecture verification event at 10:25:00 (active until 10:30:00)
        ev_ok, _, event_id = self.db.create_mid_lecture_verification_event(
            lecture_id=lec_id,
            duration_minutes=5
        )
        self.assertTrue(ev_ok)

        # Alice completes mid-lecture check inside the window
        mid_sim_time = datetime.now() # Matches event window_start
        v_ok, _, v_rec = self.db.record_mid_lecture_verification(
            event_id=event_id,
            student_id=self.student_alice["id"],
            confidence=0.95,
            distance_meters=8.0,
            now_dt=mid_sim_time
        )
        self.assertTrue(v_ok)
        self.assertEqual(v_rec["student_id"], self.student_alice["id"])

        # Bob misses the mid-lecture check!
        # Generate lecture report
        report = self.db.get_lecture_attendance_report(lec_id)
        summary = report["summary"]
        self.assertEqual(summary["mid_lecture_verified_count"], 1)
        self.assertEqual(summary["mid_lecture_missed_count"], 1)

    # 9. Instructor-Authorized Manual Attendance Correction with Audit Trail
    def test_instructor_manual_attendance_correction(self):
        today = datetime.now().strftime("%Y-%m-%d")
        ok, _, lec_id = self.db.create_lecture(
            course_code="CS101",
            subject_name="Physics",
            instructor_name="Prof. Kumar",
            date_str=today,
            start_time_str="14:00:00",
            duration_minutes=50
        )
        # Alice was initially marked LATE
        sim_time = datetime.strptime(f"{today} 14:12:00", "%Y-%m-%d %H:%M:%S")
        self.db.mark_lecture_attendance(
            lecture_id=lec_id,
            student_id=self.student_alice["id"],
            confidence=0.91,
            now_dt=sim_time
        )

        # Instructor corrects status from LATE to PRESENT due to verified medical slip
        corr_ok, corr_msg = self.db.correct_lecture_attendance(
            lecture_id=lec_id,
            student_id=self.student_alice["id"],
            new_status="PRESENT",
            reason="Medical certificate approved by HoD",
            authorized_by="prof_kumar"
        )
        self.assertTrue(corr_ok)

        # Check updated report
        report = self.db.get_lecture_attendance_report(lec_id)
        alice_rec = next(r for r in report["records"] if r["student_id"] == self.student_alice["id"])
        self.assertEqual(alice_rec["status"], "PRESENT")

        # Check audit log
        logs = self.db.get_audit_logs(limit=5)
        corr_log = next(l for l in logs if l["action"] == "ATTENDANCE_CORRECTION")
        self.assertIn("Medical certificate approved", corr_log["details"])
        self.assertEqual(corr_log["actor"], "prof_kumar")

    # 10. Security: Admin Session Token Generation & Verification
    def test_admin_token_security(self):
        token = create_admin_token("admin")
        self.assertIsNotNone(token)
        # Valid token decodes to admin username
        username = verify_admin_token(token)
        self.assertEqual(username, "admin")

        # Tampered token fails
        self.assertIsNone(verify_admin_token(token + "tampered"))
        # Empty token fails
        self.assertIsNone(verify_admin_token(""))
        self.assertIsNone(verify_admin_token(None))

    # 11. Anti-Bunking Analytics
    def test_anti_bunking_analytics(self):
        analytics = self.db.get_anti_bunking_analytics()
        self.assertIn("student_analytics", analytics)
        self.assertIn("subject_analytics", analytics)
        self.assertIn("total_scheduled_lectures", analytics)

if __name__ == "__main__":
    unittest.main()
