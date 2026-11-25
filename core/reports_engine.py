"""
SmartAttend AI - Reports and Export Engine
Generates structured attendance reports and exports:
- Daily institutional attendance ledger
- Monthly student and subject aggregations
- Subject-wise performance metrics
- Department-wise compliance reports
- CSV export with CSV Formula Injection Protection (CWE-1236)
- JSON export for frontend charts and heatmaps
"""
import csv
import io
from typing import Dict, List, Optional, Tuple, Any
from core.security import sanitize_csv_field


class ReportsEngine:
    """
    Produces clean, compliant reports with formula injection protection
    and standardized aggregation structures.
    """

    def __init__(self, db_manager: Any):
        self.db = db_manager

    # --- CSV Export with Formula Injection Protection ---
    def export_attendance_csv(
        self,
        lecture_id: Optional[int] = None,
        date_filter: Optional[str] = None
    ) -> str:
        """
        Exports attendance records to CSV string safely.
        Sanitizes all string fields to neutralize CSV formula injection attacks
        (fields starting with =, +, -, @, \\t, \\r are prepended with an apostrophe).
        """
        records = self.db.get_filtered_attendance_records(lecture_id=lecture_id, date_filter=date_filter)

        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

        # Header
        headers = [
            "Attendance ID",
            "Student ID",
            "Roll Number",
            "Student Name",
            "Subject",
            "Lecture ID",
            "Date",
            "Timestamp",
            "Status",
            "Verification Method",
            "Location Status"
        ]
        writer.writerow(headers)

        for rec in records:
            row = [
                sanitize_csv_field(rec.get("id")),
                sanitize_csv_field(rec.get("student_id")),
                sanitize_csv_field(rec.get("roll_no") or rec.get("roll_number")),
                sanitize_csv_field(rec.get("name") or rec.get("student_name")),
                sanitize_csv_field(rec.get("subject")),
                sanitize_csv_field(rec.get("lecture_id")),
                sanitize_csv_field(rec.get("date")),
                sanitize_csv_field(rec.get("timestamp")),
                sanitize_csv_field(rec.get("status")),
                sanitize_csv_field(rec.get("verification_method") or "FACE_GEOFENCE"),
                sanitize_csv_field(rec.get("location_status") or "VERIFIED")
            ]
            writer.writerow(row)

        return output.getvalue()

    def export_student_summary_csv(self, department_id: Optional[int] = None) -> str:
        """
        Exports institution-wide or department-specific student attendance summary to CSV.
        Safely neutralizes formula injection.
        """
        students = self.db.get_students_summary_for_reports(department_id=department_id)

        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

        headers = [
            "Student ID",
            "Roll Number",
            "Name",
            "Department",
            "Email",
            "Total Classes",
            "Attended Classes",
            "Attendance Percentage",
            "Compliance Status"
        ]
        writer.writerow(headers)

        for s in students:
            pct = s.get("percentage", 0.0)
            status = "Compliant" if pct >= 75.0 else ("Critical Shortage" if pct < 65.0 else "Warning")
            row = [
                sanitize_csv_field(s.get("id")),
                sanitize_csv_field(s.get("roll_number")),
                sanitize_csv_field(s.get("name")),
                sanitize_csv_field(s.get("department")),
                sanitize_csv_field(s.get("email")),
                sanitize_csv_field(s.get("total_classes")),
                sanitize_csv_field(s.get("attended_classes")),
                f"{pct:.1f}%",
                sanitize_csv_field(status)
            ]
            writer.writerow(row)

        return output.getvalue()

    # --- Structured Analytics & Heatmap Aggregations ---
    def get_attendance_heatmap_data(self, student_id: Optional[int] = None, days_back: int = 90) -> List[Dict[str, Any]]:
        """
        Aggregates daily attendance counts for calendar heatmap visualization.
        """
        raw_counts = self.db.get_daily_attendance_counts(student_id=student_id, days_back=days_back)
        return raw_counts

    def get_subject_wise_summary(self, student_id: int) -> List[Dict[str, Any]]:
        """
        Returns subject-wise breakdown with total lectures, attended count,
        and current percentage for the student dashboard.
        """
        return self.db.get_student_subject_breakdown(student_id)
