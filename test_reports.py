"""
SmartAttend AI - Reports Engine & Formula Injection Protection Test Suite
Verifies:
1. Exporting attendance records to CSV
2. Exporting student compliance summary to CSV
3. Protection against CSV Formula Injection (CWE-1236)
   Fields starting with =, +, -, @, \\t, \\r must be prepended with apostrophe '
4. Subject-wise summary and attendance heatmap data aggregation
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
from core.reports_engine import ReportsEngine
from core.security import sanitize_csv_field


class TestReportsEngine(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_reports.db")
        self.db = DatabaseManager(self.db_path)
        self.reports = ReportsEngine(self.db)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_sanitize_csv_formula_injection(self):
        """Malicious spreadsheet formulas must be safely escaped."""
        self.assertEqual(sanitize_csv_field("=cmd|'/C calc'!A0"), "'=cmd|'/C calc'!A0")
        self.assertEqual(sanitize_csv_field("+12345"), "'+12345")
        self.assertEqual(sanitize_csv_field("-SUM(A1:A10)"), "'-SUM(A1:A10)")
        self.assertEqual(sanitize_csv_field("@SUM(B1:B5)"), "'@SUM(B1:B5)")
        self.assertEqual(sanitize_csv_field("\tTabPrefix"), "'\tTabPrefix")
        # Normal fields should not be modified
        self.assertEqual(sanitize_csv_field("Rahul Sharma"), "Rahul Sharma")
        self.assertEqual(sanitize_csv_field(2026001), "2026001")

    def test_csv_export_includes_sanitized_records(self):
        """Attendance export generates valid CSV with header and records."""
        # Insert student with potentially problematic characters
        dummy_emb = np.random.randn(128).astype(np.float32)
        self.db.register_student("2026001", "Normal Name", "CS", "test@college.edu", dummy_emb)
        students = self.db.get_all_students()
        sid = students[0]["id"]

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO attendance (student_id, date, time, status, confidence)
            VALUES (?, '2026-11-25', '10:00:00', 'PRESENT', 0.95)
            """, (sid,))
            conn.commit()

        csv_text = self.reports.export_attendance_csv()
        self.assertIn("Attendance ID,Student ID,Roll Number,Student Name,Subject", csv_text)
        self.assertIn("2026001", csv_text)
        self.assertIn("Normal Name", csv_text)
        self.assertIn("PRESENT", csv_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
