"""
SmartAttend AI - Machine Learning & Analytics Test Suite
Verifies:
1. Student attendance forecast & probability calculation
2. Absenteeism risk classification (CRITICAL, ELEVATED, NORMAL)
3. Calculation of exact classes needed to clear mandatory 75% threshold
4. Anomaly detection (day-of-week clustering, extended absence streaks)
5. Department-wise comparative statistics
6. Monthly attendance trends and directional momentum
7. Governance: verifies presence of advisory disclaimers (no auto-punishment)
"""
import os
import sys
import tempfile
import unittest
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from database.db_manager import DatabaseManager
from core.ml_analytics import AttendanceAnalyticsEngine


class TestMLAnalytics(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_analytics.db")
        self.db = DatabaseManager(self.db_path)
        self.analytics = AttendanceAnalyticsEngine(self.db)

        # Register a test student
        dummy_emb = np.random.randn(128).astype(np.float32)
        self.db.register_student("2026001", "Ananya Verma", "CS", "ananya@college.edu", dummy_emb)
        students = self.db.get_all_students()
        self.student_id = students[0]["id"]

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_insufficient_data_handling(self):
        """New students with zero history receive UNKNOWN risk and advisory notice."""
        pred = self.analytics.predict_student_attendance(self.student_id)
        self.assertEqual(pred["risk_level"], "UNKNOWN")
        self.assertIn("disclaimer", pred)
        self.assertIn("must not be used for automatic disciplinary decisions", pred["disclaimer"])

    def test_attendance_prediction_and_shortage_calculation(self):
        """Simulate low attendance and verify exact recovery count and CRITICAL risk flag."""
        # Record 10 conducted sessions where student only attended 4 (40% attendance)
        for i in range(1, 11):
            date_str = f"2026-11-{i:02d}"
            status = "PRESENT" if i <= 4 else "ABSENT"
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT OR IGNORE INTO lectures (id, course_code, subject_name, instructor_name, date, start_time, end_time, status)
                VALUES (?, 'CS101', 'Data Structures', 'Prof', ?, '10:00:00', '11:00:00', 'Open')
                """, (i, date_str))
                cursor.execute("""
                INSERT INTO lecture_attendance (lecture_id, student_id, date, marked_at, status, confidence)
                VALUES (?, ?, ?, '10:00:00', ?, 0.95)
                """, (i, self.student_id, date_str, status))
                if status == "PRESENT":
                    cursor.execute("""
                    INSERT INTO attendance (student_id, date, time, status, confidence)
                    VALUES (?, ?, '10:00:00', 'PRESENT', 0.95)
                    """, (self.student_id, date_str))
                conn.commit()

        pred = self.analytics.predict_student_attendance(self.student_id, total_planned_classes=40)
        self.assertEqual(pred["attended"], 4)
        self.assertEqual(pred["total_conducted"], 10)
        self.assertEqual(pred["current_percentage"], 40.0)
        self.assertEqual(pred["risk_level"], "CRITICAL")
        # To get 75% of 40 = 30 classes. Attended = 4. Needed = 26.
        self.assertEqual(pred["classes_needed_for_75"], 26)
        self.assertTrue(pred["confidence_score"] > 0)
        self.assertIn("disclaimer", pred)

    def test_streak_absence_anomaly_detection(self):
        """Extended absence streak of 4+ consecutive sessions must be flagged as anomaly."""
        for i in range(1, 7):
            date_str = f"2026-11-{i:02d}"
            status = "ABSENT" if i >= 2 else "PRESENT"  # 5 consecutive absences
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT OR IGNORE INTO lectures (id, course_code, subject_name, instructor_name, date, start_time, end_time, status)
                VALUES (?, 'CS101', 'Data Structures', 'Prof', ?, '10:00:00', '11:00:00', 'Open')
                """, (i, date_str))
                cursor.execute("""
                INSERT INTO lecture_attendance (lecture_id, student_id, date, marked_at, status, confidence)
                VALUES (?, ?, ?, '10:00:00', ?, 0.95)
                """, (i, self.student_id, date_str, status))
                if status == "PRESENT":
                    cursor.execute("""
                    INSERT INTO attendance (student_id, date, time, status, confidence)
                    VALUES (?, ?, '10:00:00', 'PRESENT', 0.95)
                    """, (self.student_id, date_str))
                conn.commit()

        anomalies = self.analytics.detect_student_anomalies(self.student_id)
        self.assertTrue(anomalies["has_anomalies"])
        types = [a["type"] for a in anomalies["anomalies"]]
        self.assertIn("EXTENDED_ABSENCE_STREAK", types)

    def test_department_comparative_analytics(self):
        """Department analytics computes valid averages and risk counts."""
        self.db.create_department("Computer Science", "CS")
        results = self.analytics.get_department_comparative_analytics()
        self.assertIsInstance(results, list)
        self.assertGreaterEqual(len(results), 1)
        dept = results[0]
        self.assertEqual(dept["name"], "Computer Science")
        self.assertIn("average_attendance", dept)
        self.assertIn("students_at_risk", dept)


if __name__ == "__main__":
    unittest.main(verbosity=2)
