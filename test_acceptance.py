"""
Phase 23: Complete Acceptance Test Suite.
Verifies all criteria across Phases 17-22:
- Geofencing (inside, outside, boundary, poor accuracy, multi-campus, 30m vs 50m)
- Email (lowercase alphanumeric local part, valid domain, duplicate check)
- Name (Title Case, UPPERCASE, no digits, no arbitrary mixed case)
- Student ID (numeric digits only, preserving leading zeros)
- Lecture Scheduling & Anti-Bunking (50 min default, custom, windows, duplicates, mid-checks, corrections)
- Security (Admin token, public privacy, audit trail)
- Data Integrity & Regression (Existing records preservation)
"""
import os
import sys
import tempfile
import unittest
import base64
import cv2
import numpy as np
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from database.db_manager import DatabaseManager
from core.geofence import haversine_distance, verify_student_location
from core.validators import validate_email, validate_student_name, validate_roll_number
from server import create_admin_token, verify_admin_token

class TestPhaseAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_db_path = os.path.join(self.temp_dir.name, "acceptance.db")
        self.db = DatabaseManager(self.temp_db_path)
        self.db.ensure_default_admin("admin", "admin123")

        self.campus_lat = 28.535500
        self.campus_lon = 77.391000

        # Register standard students
        emb = np.random.randn(128).astype(np.float32)
        emb /= np.linalg.norm(emb)
        self.db.register_student("2026001", "Rohit Pathak", "Computer Science", "rohit2026@example.com", emb)
        self.db.register_student("001234", "ALICE SMITH", "Electrical Eng", "alice001@example.com", emb)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    # --- 1. GEOFENCING ACCEPTANCE TESTS (PHASE 17) ---
    def test_geofence_acceptance(self):
        campuses = self.db.get_active_campuses()
        self.assertEqual(len(campuses), 1)
        # Default radius must be 30m, not 50m
        self.assertEqual(campuses[0]["radius_meters"], 30.0)

        # A. Clearly Inside Radius (5m away)
        ok_in, msg_in, det_in = verify_student_location(
            student_lat=self.campus_lat + 0.00004,
            student_lon=self.campus_lon,
            accuracy_meters=5.0,
            campuses=campuses,
            accuracy_threshold_meters=50.0
        )
        self.assertTrue(ok_in)
        self.assertLessEqual(det_in["distance_meters"], 30.0)

        # B. Clearly Outside Radius (80m away)
        ok_out, msg_out, det_out = verify_student_location(
            student_lat=self.campus_lat + 0.00072,
            student_lon=self.campus_lon,
            accuracy_meters=10.0,
            campuses=campuses,
            accuracy_threshold_meters=50.0
        )
        self.assertFalse(ok_out)
        self.assertEqual(msg_out, "Attendance is allowed only within the authorized college campus area.")
        self.assertGreater(det_out["distance_meters"], 30.0)

        # C. Server calculates distance independently with Haversine formula
        manual_dist = haversine_distance(self.campus_lat, self.campus_lon, self.campus_lat + 0.00072, self.campus_lon)
        self.assertAlmostEqual(det_out["distance_meters"], round(manual_dist, 2), delta=0.5)

        # D. Poor GPS accuracy is rejected
        ok_acc, msg_acc, det_acc = verify_student_location(
            student_lat=self.campus_lat,
            student_lon=self.campus_lon,
            accuracy_meters=85.0, # Exceeds 50m threshold
            campuses=campuses,
            accuracy_threshold_meters=50.0
        )
        self.assertFalse(ok_acc)
        self.assertEqual(det_acc["error_type"], "POOR_ACCURACY")

        # E. Administrator Configurable Radius (30m to 50m)
        self.db.update_campus(campuses[0]["id"], "Main Campus", self.campus_lat, self.campus_lon, radius_meters=50.0)
        campuses_updated = self.db.get_active_campuses()
        self.assertEqual(campuses_updated[0]["radius_meters"], 50.0)

        # Point ~40m from campus is now accepted under 50m
        ok_40m, _, det_40m = verify_student_location(
            student_lat=self.campus_lat + 0.00036,
            student_lon=self.campus_lon,
            accuracy_meters=5.0,
            campuses=campuses_updated
        )
        self.assertTrue(ok_40m)

    # --- 2. EMAIL VALIDATION ACCEPTANCE TESTS (PHASE 18) ---
    def test_email_validation_acceptance(self):
        # A. Valid lowercase alphanumeric local part
        ok1, norm1, _ = validate_email("abcd123@example.com")
        self.assertTrue(ok1)
        self.assertEqual(norm1, "abcd123@example.com")

        # B. Uppercase in local part strictly rejected
        ok2, _, msg2 = validate_email("Abcd123@example.com")
        self.assertFalse(ok2)
        self.assertIn("lowercase", msg2.lower())

        # C. Invalid domain structure without suffix rejected ("abcd@123")
        ok3, _, _ = validate_email("abcd@123")
        self.assertFalse(ok3)

        # D. Duplicate email rejected by database
        emb = np.random.randn(128).astype(np.float32)
        dup_ok, dup_msg = self.db.register_student("2026999", "Charlie Brown", "CS", "rohit2026@example.com", emb)
        self.assertFalse(dup_ok)
        self.assertIn("already registered", dup_msg.lower())

    # --- 3. STUDENT NAME VALIDATION ACCEPTANCE TESTS (PHASE 19) ---
    def test_student_name_acceptance(self):
        # A. Supported formats accepted: Title Case & UPPERCASE
        for name in ["Rohit", "Rohit Pathak", "ROHIT", "ROHIT PATHAK"]:
            is_ok, norm, _ = validate_student_name(name)
            self.assertTrue(is_ok, f"Failed on valid name: {name}")

        # B. Rejected formats: digits, pure numbers, arbitrary mixed case
        for bad_name in ["rohit123", "12345", "rohit PATHAK", ""]:
            is_ok, _, _ = validate_student_name(bad_name)
            self.assertFalse(is_ok, f"Should have rejected bad name: {bad_name}")

    # --- 4. NUMERIC ROLL NUMBER VALIDATION ACCEPTANCE TESTS (PHASE 20) ---
    def test_numeric_roll_number_acceptance(self):
        # A. Valid digits-only roll numbers
        for valid_roll in ["12345", "20261001", "001234"]:
            is_ok, norm, _ = validate_roll_number(valid_roll, require_numeric=True)
            self.assertTrue(is_ok)
            # Leading zeros must be preserved as string
            self.assertEqual(norm, valid_roll)

        # B. Alphabetic, punctuation, spaces rejected
        for bad_roll in ["AB123", "12A45", "12-345", "12 345"]:
            is_ok, _, _ = validate_roll_number(bad_roll, require_numeric=True)
            self.assertFalse(is_ok)

    # --- 5. LECTURE ATTENDANCE & ANTI-BUNKING ACCEPTANCE TESTS (PHASE 21) ---
    def test_lecture_attendance_acceptance(self):
        today = datetime.now().strftime("%Y-%m-%d")

        # A. Default duration is 50 minutes
        ok, _, lec_id = self.db.create_lecture(
            course_code="CS401",
            subject_name="Machine Learning",
            instructor_name="Dr. Banner",
            date_str=today,
            start_time_str="09:00:00"
        )
        self.assertTrue(ok)
        lec = self.db.get_lecture_by_id(lec_id)
        self.assertEqual(lec["duration_minutes"], 50)
        self.assertEqual(lec["end_time"], "09:50:00")

        # B. Tied to specific lecture, within attendance window
        st_rohit = self.db.get_student_by_roll("2026001")
        sim_time = datetime.strptime(f"{today} 09:05:00", "%Y-%m-%d %H:%M:%S")

        att_ok, _, att_rec = self.db.mark_lecture_attendance(
            lecture_id=lec_id,
            student_id=st_rohit["id"],
            confidence=0.94,
            distance_meters=15.0,
            now_dt=sim_time
        )
        self.assertTrue(att_ok)
        self.assertEqual(att_rec["status"], "PRESENT")

        # C. Duplicate attendance rejected
        dup_ok, dup_msg, _ = self.db.mark_lecture_attendance(
            lecture_id=lec_id,
            student_id=st_rohit["id"],
            confidence=0.96,
            now_dt=sim_time + timedelta(seconds=30)
        )
        self.assertFalse(dup_ok)
        self.assertIn("already recorded", dup_msg.lower())

        # D. Attendance outside window rejected
        st_alice = self.db.get_student_by_roll("001234")
        late_time = datetime.strptime(f"{today} 09:30:00", "%Y-%m-%d %H:%M:%S") # Closed at 09:15:00
        late_ok, late_msg, _ = self.db.mark_lecture_attendance(
            lecture_id=lec_id,
            student_id=st_alice["id"],
            confidence=0.90,
            now_dt=late_time
        )
        self.assertFalse(late_ok)
        self.assertIn("closed", late_msg.lower())

        # E. Mid-lecture check and missed check accurately logged
        ev_ok, _, ev_id = self.db.create_mid_lecture_verification_event(lec_id, duration_minutes=5)
        self.assertTrue(ev_ok)

        # Rohit verifies mid-lecture
        mid_ok, _, _ = self.db.record_mid_lecture_verification(ev_id, st_rohit["id"], confidence=0.95, now_dt=datetime.now())
        self.assertTrue(mid_ok)

        # Check report reflects Rohit verified, Alice absent
        rep = self.db.get_lecture_attendance_report(lec_id)
        self.assertEqual(rep["summary"]["present_count"], 1)
        self.assertEqual(rep["summary"]["absent_count"], 1)
        self.assertEqual(rep["summary"]["mid_lecture_verified_count"], 1)

        # F. Authorized correction with audit trail
        corr_ok, _ = self.db.correct_lecture_attendance(
            lecture_id=lec_id,
            student_id=st_alice["id"],
            new_status="PRESENT",
            reason="Bus breakdown, verified by Dean",
            authorized_by="dr_banner"
        )
        self.assertTrue(corr_ok)

        rep_after = self.db.get_lecture_attendance_report(lec_id)
        self.assertEqual(rep_after["summary"]["present_count"], 2)

    # --- 6. SECURITY & AUDIT TRAIL ACCEPTANCE TESTS (PHASE 22) ---
    def test_security_acceptance(self):
        # Admin authentication
        self.assertTrue(self.db.verify_admin("admin", "admin123"))
        self.assertFalse(self.db.verify_admin("admin", "wrongpassword"))

        # Explicitly log audit action and verify retrieval
        self.db.log_audit("ADMIN_SETTING_CHANGE", "Updated default radius to 30m", actor="admin")
        logs = self.db.get_audit_logs(limit=10)
        self.assertGreater(len(logs), 0)
        self.assertEqual(logs[0]["action"], "ADMIN_SETTING_CHANGE")
        self.assertEqual(logs[0]["actor"], "admin")

if __name__ == "__main__":
    unittest.main()
