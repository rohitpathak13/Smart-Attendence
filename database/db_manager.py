import json
import sqlite3
import hashlib
import hmac
import os
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, time
import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple, Any

from config import (
    DEFAULT_GEOFENCE_RADIUS_METERS,
    DEFAULT_CAMPUS_NAME,
    DEFAULT_CAMPUS_LAT,
    DEFAULT_CAMPUS_LON,
    DEFAULT_LOCATION_ACCURACY_THRESHOLD_METERS,
    DEFAULT_LECTURE_DURATION_MINUTES,
    DEFAULT_ATTENDANCE_WINDOW_BEFORE_MINS,
    DEFAULT_ATTENDANCE_WINDOW_AFTER_MINS,
    INSTITUTION_TIMEZONE,
    REQUIRE_NUMERIC_ROLL_NO,
    INSTITUTION_EMAIL_DOMAIN
)
from core.validators import validate_email, validate_student_name, validate_roll_number

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.init_db()
        self.init_extended_db()

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Students table (preserved from previous schema)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                roll_no TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                department TEXT DEFAULT 'General',
                email TEXT DEFAULT '',
                embedding BLOB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # 2. Daily Attendance table (preserved for backwards compatibility)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('PRESENT', 'LATE')),
                confidence REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
            )
            """)

            # 3. Admin users table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # 4. Normalized constraints and indexes on students
            cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_students_roll_no_unique
            ON students(roll_no)
            """)

            cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_students_email_unique
            ON students(email)
            WHERE email IS NOT NULL AND email != ''
            """)

            cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_students_email_nocase
            ON students(LOWER(email))
            WHERE email IS NOT NULL AND email != ''
            """)

            # 5. Campus Geofence Configuration (Phase 17)
            # Default radius: 30.0 meters (NOT 50 meters, configurable by admin)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS campuses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                radius_meters REAL NOT NULL DEFAULT 30.0,
                accuracy_threshold_meters REAL NOT NULL DEFAULT 50.0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # 6. Institutional System Settings (Phase 22)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                description TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # 7. Lecture Scheduling (Phase 21-A)
            # Default duration: 50 minutes (configurable per lecture)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS lectures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_code TEXT NOT NULL,
                subject_name TEXT NOT NULL,
                section TEXT NOT NULL DEFAULT 'A',
                instructor_name TEXT NOT NULL,
                date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL DEFAULT 50,
                room TEXT DEFAULT 'Room 101',
                attendance_window_start TEXT,
                attendance_window_end TEXT,
                status TEXT NOT NULL DEFAULT 'Scheduled' CHECK(status IN ('Scheduled', 'Open', 'Closed', 'Cancelled')),
                campus_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (campus_id) REFERENCES campuses(id) ON DELETE SET NULL
            )
            """)

            # 8. Lecture-Wise Attendance (Phase 21-B, C)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS lecture_attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lecture_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                marked_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('PRESENT', 'LATE', 'ABSENT')),
                confidence REAL NOT NULL,
                initial_verified INTEGER NOT NULL DEFAULT 1,
                mid_lecture_verified INTEGER DEFAULT NULL,
                distance_meters REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (lecture_id) REFERENCES lectures(id) ON DELETE CASCADE,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
                UNIQUE(lecture_id, student_id)
            )
            """)

            # 9. Anti-Bunking Verification Events (Phase 21-D, E)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS verification_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lecture_id INTEGER NOT NULL,
                event_type TEXT NOT NULL DEFAULT 'MID_LECTURE',
                window_start TEXT NOT NULL,
                window_end TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'COMPLETED', 'EXPIRED')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (lecture_id) REFERENCES lectures(id) ON DELETE CASCADE
            )
            """)

            # 10. Student Mid-Lecture Verification Records
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS lecture_verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                verification_event_id INTEGER NOT NULL,
                lecture_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                verified_at TEXT NOT NULL,
                confidence REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'VERIFIED' CHECK(status IN ('VERIFIED', 'MISSED', 'EXCUSED')),
                distance_meters REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (verification_event_id) REFERENCES verification_events(id) ON DELETE CASCADE,
                FOREIGN KEY (lecture_id) REFERENCES lectures(id) ON DELETE CASCADE,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
                UNIQUE(verification_event_id, student_id)
            )
            """)

            # 11. Attendance Corrections with Audit Trail (Phase 21-D)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance_corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lecture_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                old_status TEXT NOT NULL,
                new_status TEXT NOT NULL,
                reason TEXT NOT NULL,
                authorized_by TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (lecture_id) REFERENCES lectures(id) ON DELETE CASCADE,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
            )
            """)

            # 12. Security & Administrative Audit Logs (Phase 17, 22)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                details TEXT NOT NULL,
                actor TEXT NOT NULL,
                ip_address TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            conn.commit()

            # Seed default campus if none exists
            cursor.execute("SELECT COUNT(*) FROM campuses")
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                INSERT INTO campuses (name, latitude, longitude, radius_meters, accuracy_threshold_meters, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
                """, (
                    DEFAULT_CAMPUS_NAME,
                    DEFAULT_CAMPUS_LAT,
                    DEFAULT_CAMPUS_LON,
                    DEFAULT_GEOFENCE_RADIUS_METERS,
                    DEFAULT_LOCATION_ACCURACY_THRESHOLD_METERS
                ))
                conn.commit()

            # Seed default system settings if missing
            default_settings = [
                ("geofence_enabled", "true", "Whether location verification is strictly required for attendance"),
                ("default_radius_meters", str(DEFAULT_GEOFENCE_RADIUS_METERS), "Default authorized attendance radius in meters (30m)"),
                ("accuracy_threshold_meters", str(DEFAULT_LOCATION_ACCURACY_THRESHOLD_METERS), "Maximum allowable GPS inaccuracy in meters"),
                ("default_lecture_duration_minutes", str(DEFAULT_LECTURE_DURATION_MINUTES), "Default duration of scheduled lectures in minutes (50m)"),
                ("attendance_window_before_mins", str(DEFAULT_ATTENDANCE_WINDOW_BEFORE_MINS), "Minutes before lecture start when attendance opens"),
                ("attendance_window_after_mins", str(DEFAULT_ATTENDANCE_WINDOW_AFTER_MINS), "Minutes after lecture start when initial attendance closes"),
                ("late_cutoff_minutes", "10", "Minutes after lecture start after which attendance is marked LATE"),
                ("institution_timezone", INSTITUTION_TIMEZONE, "Official institution timezone for lecture schedules"),
                ("institution_email_domain", INSTITUTION_EMAIL_DOMAIN, "Allowed institutional domain suffix, or empty for all valid domains"),
                ("require_numeric_roll_no", "true" if REQUIRE_NUMERIC_ROLL_NO else "false", "Enforce digits-only student IDs and preserve leading zeros")
            ]

            for key, val, desc in default_settings:
                cursor.execute("""
                INSERT INTO system_settings (key, value, description)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO NOTHING
                """, (key, val, desc))

            conn.commit()

    def init_extended_db(self):
        """
        Phase 2 (SmartAttend AI) schema extension.
        Adds new tables without touching existing tables.
        Safe to call multiple times (idempotent via CREATE TABLE IF NOT EXISTS).
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 13. Departments
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS departments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                code TEXT UNIQUE NOT NULL,
                head_teacher_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # 14. Courses
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS courses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                department_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                code TEXT UNIQUE NOT NULL,
                semester INTEGER NOT NULL DEFAULT 1,
                academic_year TEXT NOT NULL DEFAULT '2026-27',
                credits INTEGER DEFAULT 4,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE
            )
            """)

            # 15. Subjects (linked to courses)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                code TEXT UNIQUE NOT NULL,
                type TEXT NOT NULL DEFAULT 'Theory' CHECK(type IN ('Theory', 'Practical', 'Tutorial')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
            )
            """)

            # 16. Classrooms
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS classrooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                building TEXT,
                floor INTEGER DEFAULT 0,
                capacity INTEGER DEFAULT 60,
                campus_id INTEGER,
                latitude REAL,
                longitude REAL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (campus_id) REFERENCES campuses(id) ON DELETE SET NULL
            )
            """)

            # 17. Teachers
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS teachers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                department_id INTEGER,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE SET NULL
            )
            """)

            # 18. Teacher-Subject Assignments
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS teacher_subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher_id INTEGER NOT NULL,
                subject_id INTEGER NOT NULL,
                classroom_id INTEGER,
                academic_year TEXT NOT NULL DEFAULT '2026-27',
                FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE,
                FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
                FOREIGN KEY (classroom_id) REFERENCES classrooms(id) ON DELETE SET NULL,
                UNIQUE(teacher_id, subject_id, academic_year)
            )
            """)

            # 19. Parents
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS parents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                phone TEXT,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # 20. Student-Parent Links
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS student_parents (
                student_id INTEGER NOT NULL,
                parent_id INTEGER NOT NULL,
                relation TEXT DEFAULT 'Parent',
                PRIMARY KEY (student_id, parent_id),
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
                FOREIGN KEY (parent_id) REFERENCES parents(id) ON DELETE CASCADE
            )
            """)

            # 21. Student Login Credentials (separate from biometrics)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS student_logins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                last_login TIMESTAMP,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
            )
            """)

            # 22. QR Tokens (one-time, time-bound attendance tokens)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS qr_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nonce TEXT UNIQUE NOT NULL,
                session_id INTEGER NOT NULL,
                classroom_id INTEGER,
                teacher_id INTEGER NOT NULL,
                issued_at TIMESTAMP NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                consumed INTEGER NOT NULL DEFAULT 0,
                consumed_by_student_id INTEGER,
                consumed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (classroom_id) REFERENCES classrooms(id) ON DELETE SET NULL
            )
            """)

            # 23. Attendance Sessions (teacher-started sessions for QR/live marking)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lecture_id INTEGER,
                subject_id INTEGER,
                classroom_id INTEGER,
                teacher_id INTEGER NOT NULL,
                session_date TEXT NOT NULL,
                started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                ended_at TIMESTAMP,
                status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'ENDED', 'CANCELLED')),
                qr_expiry_seconds INTEGER NOT NULL DEFAULT 30,
                require_face INTEGER NOT NULL DEFAULT 1,
                require_location INTEGER NOT NULL DEFAULT 1,
                require_qr INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (lecture_id) REFERENCES lectures(id) ON DELETE SET NULL,
                FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE SET NULL,
                FOREIGN KEY (classroom_id) REFERENCES classrooms(id) ON DELETE SET NULL
            )
            """)

            # 24. Attendance Verification Results (multi-layer anti-proxy results)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance_verification_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                lecture_id INTEGER,
                student_id INTEGER NOT NULL,
                overall_status TEXT NOT NULL CHECK(overall_status IN ('VERIFIED', 'REJECTED', 'PENDING_REVIEW')),
                face_match_score REAL,
                face_status TEXT,
                liveness_status TEXT,
                liveness_texture_score REAL,
                location_status TEXT,
                location_distance_m REAL,
                qr_status TEXT,
                rejection_reason TEXT,
                submitted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_by TEXT,
                reviewed_at TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES attendance_sessions(id) ON DELETE SET NULL,
                FOREIGN KEY (lecture_id) REFERENCES lectures(id) ON DELETE SET NULL,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
            )
            """)

            # 25. Registered Fixed Cameras
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS cameras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_uid TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                classroom_id INTEGER,
                campus_id INTEGER,
                api_key_hash TEXT NOT NULL,
                api_key_salt TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                last_seen TIMESTAMP,
                health_status TEXT DEFAULT 'UNKNOWN',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (classroom_id) REFERENCES classrooms(id) ON DELETE SET NULL,
                FOREIGN KEY (campus_id) REFERENCES campuses(id) ON DELETE SET NULL
            )
            """)

            # 26. BLE Beacons (optional classroom proximity)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS beacons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                beacon_uuid TEXT UNIQUE NOT NULL,
                major INTEGER,
                minor INTEGER,
                name TEXT NOT NULL,
                classroom_id INTEGER,
                is_active INTEGER NOT NULL DEFAULT 1,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (classroom_id) REFERENCES classrooms(id) ON DELETE SET NULL
            )
            """)

            # 27. Timetables
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS timetables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_id INTEGER NOT NULL,
                teacher_id INTEGER NOT NULL,
                classroom_id INTEGER,
                day_of_week INTEGER NOT NULL CHECK(day_of_week BETWEEN 0 AND 6),
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                academic_year TEXT NOT NULL DEFAULT '2026-27',
                semester INTEGER NOT NULL DEFAULT 1,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
                FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE,
                FOREIGN KEY (classroom_id) REFERENCES classrooms(id) ON DELETE SET NULL
            )
            """)

            # 28. Leave Requests
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS leave_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                leave_type TEXT NOT NULL DEFAULT 'MEDICAL' CHECK(leave_type IN ('MEDICAL', 'PERSONAL', 'OFFICIAL', 'BEREAVEMENT', 'OTHER')),
                from_date TEXT NOT NULL,
                to_date TEXT NOT NULL,
                reason TEXT NOT NULL,
                supporting_document_path TEXT,
                status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED')),
                reviewed_by TEXT,
                reviewed_at TIMESTAMP,
                review_comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
            )
            """)

            # 29. Notifications
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient_type TEXT NOT NULL CHECK(recipient_type IN ('STUDENT', 'TEACHER', 'PARENT', 'ADMIN')),
                recipient_id INTEGER NOT NULL,
                recipient_email TEXT,
                type TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                is_sent INTEGER NOT NULL DEFAULT 0,
                sent_at TIMESTAMP,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # 30. Holidays
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS holidays (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'NATIONAL' CHECK(type IN ('NATIONAL', 'REGIONAL', 'INSTITUTIONAL')),
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # Indexes for performance on new tables
            cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_qr_tokens_nonce ON qr_tokens(nonce)
            """)
            cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_qr_tokens_session ON qr_tokens(session_id)
            """)
            cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_att_sessions_status ON attendance_sessions(status)
            """)
            cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_att_verification_student ON attendance_verification_results(student_id)
            """)
            cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_leave_requests_student ON leave_requests(student_id, status)
            """)
            cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_notifications_recipient ON notifications(recipient_type, recipient_id, is_sent)
            """)

            conn.commit()

    # --- Security & Auth Methods ---

    @staticmethod
    def _hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
        if not salt:
            salt = secrets.token_hex(16)
        key = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        )
        return key.hex(), salt

    def ensure_default_admin(self, default_user: str = "admin", default_pass: str = "admin123"):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM admins WHERE username = ?", (default_user,))
            if not cursor.fetchone():
                pw_hash, salt = self._hash_password(default_pass)
                cursor.execute(
                    "INSERT INTO admins (username, password_hash, salt) VALUES (?, ?, ?)",
                    (default_user, pw_hash, salt)
                )
                conn.commit()

    def verify_admin(self, username: str, password: str) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT password_hash, salt FROM admins WHERE username = ?", (username,))
            row = cursor.fetchone()
            if not row:
                return False
            expected_hash, salt = row["password_hash"], row["salt"]
            computed_hash, _ = self._hash_password(password, salt)
            return secrets.compare_digest(expected_hash, computed_hash)

    def change_admin_password(self, username: str, old_pass: str, new_pass: str) -> Tuple[bool, str]:
        if not self.verify_admin(username, old_pass):
            return False, "Old password is incorrect."
        if len(new_pass) < 8:
            return False, "Password must be at least 8 characters."
        pw_hash, salt = self._hash_password(new_pass)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE admins SET password_hash = ?, salt = ? WHERE username = ?",
                (pw_hash, salt, username)
            )
            conn.commit()
            self.log_audit("ADMIN_PASSWORD_CHANGE", f"Password changed for user '{username}'", actor=username)
        return True, "Password updated successfully."

    # --- Student Operations (Phases 18, 19, 20) ---
    def register_student(
        self,
        roll_no: str,
        name: str,
        department: str,
        email: str,
        embedding: np.ndarray,
        allow_admin_override: bool = False,
        allow_update: bool = False
    ) -> Tuple[bool, str]:
        """
        Registers a new student profile or updates an existing one with strict validation:
        - Roll No: digits 0-9 only, preserving leading zeros (Phase 20)
        - Name: Title Case or UPPERCASE, no digits, no mixed case (Phase 19)
        - Email: lowercase alphanumeric local part, valid domain, duplicate check (Phase 18)
        - Safe Duplicate Handling: Rejects duplicate roll numbers and duplicate emails unless allow_update=True
        """
        # Retrieve settings
        settings = self.get_all_settings()
        require_numeric = settings.get("require_numeric_roll_no", "true").lower() == "true"
        inst_domain = settings.get("institution_email_domain", "")

        # 1. Roll Number Validation
        is_roll_ok, norm_roll, roll_err = validate_roll_number(roll_no, require_numeric=require_numeric)
        if not is_roll_ok:
            return False, roll_err

        # 2. Student Name Validation
        is_name_ok, norm_name, name_err = validate_student_name(name, allow_admin_override=allow_admin_override)
        if not is_name_ok:
            return False, name_err

        # 3. Email Validation (if provided)
        norm_email = ""
        if email and email.strip():
            is_email_ok, norm_email, email_err = validate_email(email, institutional_domain=inst_domain)
            if not is_email_ok:
                return False, email_err

        embedding_blob = embedding.astype(np.float32).tobytes()
        norm_dept = department.strip() if department else "General"

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Check duplicate roll number
                cursor.execute(
                    "SELECT id, roll_no, name, email FROM students WHERE roll_no = ?",
                    (norm_roll,)
                )
                existing_roll_student = cursor.fetchone()
                if existing_roll_student and not allow_update:
                    return False, f"Duplicate registration: Student with roll number '{norm_roll}' is already registered as '{existing_roll_student['name']}'."

                # Check duplicate email against other registered students
                if norm_email:
                    cursor.execute(
                        "SELECT roll_no, name FROM students WHERE LOWER(email) = LOWER(?) AND roll_no != ?",
                        (norm_email, norm_roll)
                    )
                    existing_email_student = cursor.fetchone()
                    if existing_email_student:
                        return False, f"Duplicate registration: An account with email '{norm_email}' is already registered (Roll No: {existing_email_student['roll_no']})."

                if existing_roll_student and allow_update:
                    cursor.execute(
                        """
                        UPDATE students SET
                            name = ?,
                            department = ?,
                            email = ?,
                            embedding = ?
                        WHERE roll_no = ?
                        """,
                        (norm_name, norm_dept, norm_email, embedding_blob, norm_roll)
                    )
                    conn.commit()
                    return True, f"Student {norm_name} ({norm_roll}) updated successfully."
                else:
                    cursor.execute(
                        """
                        INSERT INTO students (roll_no, name, department, email, embedding)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (norm_roll, norm_name, norm_dept, norm_email, embedding_blob)
                    )
                    conn.commit()
                    return True, f"Student {norm_name} ({norm_roll}) registered successfully."
        except sqlite3.IntegrityError as e:
            err_msg = str(e)
            if "students.roll_no" in err_msg or "UNIQUE constraint failed: students.roll_no" in err_msg:
                return False, f"Duplicate registration: Student with roll number '{norm_roll}' already exists."
            if "students.email" in err_msg or "UNIQUE constraint failed: students.email" in err_msg or "idx_students_email_nocase" in err_msg:
                return False, f"Duplicate registration: An account with email '{norm_email}' is already registered."
            return False, f"Database integrity error: {err_msg}"
        except Exception as e:
            return False, f"Failed to register student: {str(e)}"

    def audit_student_records(self, report_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Audits all existing student records against current institutional policies:
        - Roll number numeric validation and leading zero preservation
        - Name formatting (Title Case / UPPERCASE, no digits)
        - Email structure and lowercase policy
        
        Preserves existing valid records and identifies legacy / rejected records
        separately for manual administrative review. Does NOT automatically alter or rewrite data.
        """
        settings = self.get_all_settings()
        require_numeric = settings.get("require_numeric_roll_no", "true").lower() == "true"
        inst_domain = settings.get("institution_email_domain", "")

        audit_results = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_students": 0,
            "valid_count": 0,
            "legacy_rejected_count": 0,
            "valid_records": [],
            "rejected_legacy_records": []
        }

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, roll_no, name, department, email, created_at FROM students ORDER BY id")
            rows = cursor.fetchall()
            audit_results["total_students"] = len(rows)

            for row in rows:
                student_info = {
                    "id": row["id"],
                    "roll_no": row["roll_no"],
                    "name": row["name"],
                    "department": row["department"],
                    "email": row["email"],
                    "created_at": str(row["created_at"])
                }
                issues = []

                # Check roll number
                is_roll_ok, norm_roll, roll_err = validate_roll_number(row["roll_no"], require_numeric=require_numeric)
                if not is_roll_ok:
                    issues.append(f"Roll Number Issue: {roll_err}")

                # Check name
                is_name_ok, norm_name, name_err = validate_student_name(row["name"], allow_admin_override=False)
                if not is_name_ok:
                    issues.append(f"Name Formatting Issue: {name_err}")

                # Check email if provided
                if row["email"] and str(row["email"]).strip():
                    is_email_ok, norm_email, email_err = validate_email(str(row["email"]).strip(), institutional_domain=inst_domain)
                    if not is_email_ok:
                        issues.append(f"Email Issue: {email_err}")
                elif not row["email"]:
                    issues.append("Email Missing: Student record has no email address configured.")

                if issues:
                    student_info["review_reasons"] = issues
                    audit_results["rejected_legacy_records"].append(student_info)
                    audit_results["legacy_rejected_count"] += 1
                else:
                    audit_results["valid_records"].append(student_info)
                    audit_results["valid_count"] += 1

        if report_path:
            os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(audit_results, f, indent=2)

        return audit_results

    def get_all_students(self) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, roll_no, name, department, email, embedding, created_at FROM students ORDER BY roll_no")
            rows = cursor.fetchall()
            students = []
            for row in rows:
                emb_array = np.frombuffer(row["embedding"], dtype=np.float32)
                students.append({
                    "id": row["id"],
                    "roll_no": row["roll_no"],
                    "name": row["name"],
                    "department": row["department"],
                    "email": row["email"],
                    "embedding": emb_array,
                    "created_at": row["created_at"]
                })
            return students

    def get_student_by_id(self, student_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, roll_no, name, department, email, embedding, created_at FROM students WHERE id = ?", (student_id,))
            row = cursor.fetchone()
            if not row:
                return None
            emb_array = np.frombuffer(row["embedding"], dtype=np.float32)
            return {
                "id": row["id"],
                "roll_no": row["roll_no"],
                "name": row["name"],
                "department": row["department"],
                "email": row["email"],
                "embedding": emb_array,
                "created_at": row["created_at"]
            }

    def get_student_by_roll(self, roll_no: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, roll_no, name, department, email, embedding, created_at FROM students WHERE roll_no = ?", (roll_no.strip(),))
            row = cursor.fetchone()
            if not row:
                return None
            emb_array = np.frombuffer(row["embedding"], dtype=np.float32)
            return {
                "id": row["id"],
                "roll_no": row["roll_no"],
                "name": row["name"],
                "department": row["department"],
                "email": row["email"],
                "embedding": emb_array,
                "created_at": row["created_at"]
            }

    def get_students_directory(self) -> List[Dict]:
        month_str = datetime.now().strftime("%Y-%m")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(DISTINCT date) FROM attendance WHERE date LIKE ?", (f"{month_str}%",))
            active_days_month = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT s.id, s.roll_no, s.name, s.department, s.email, s.created_at,
                       COUNT(DISTINCT a.date) as active_days_present
                FROM students s
                LEFT JOIN attendance a ON s.id = a.student_id AND a.date LIKE ?
                GROUP BY s.id
                ORDER BY s.roll_no
                """,
                (f"{month_str}%",)
            )
            rows = cursor.fetchall()
            students = []
            for row in rows:
                present_days = row["active_days_present"] or 0
                pct = round((present_days / active_days_month) * 100, 1) if active_days_month > 0 else 0.0
                students.append({
                    "id": row["id"],
                    "roll_no": row["roll_no"],
                    "name": row["name"],
                    "department": row["department"],
                    "email": row["email"],
                    "created_at": row["created_at"],
                    "active_days_present": present_days,
                    "total_active_days": active_days_month,
                    "monthly_percentage": pct
                })
            return students

    def get_student_count(self) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM students")
            return cursor.fetchone()[0]

    def delete_student(self, roll_no: str) -> Tuple[bool, str]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM students WHERE roll_no = ?", (roll_no.strip(),))
            if cursor.rowcount > 0:
                conn.commit()
                self.log_audit("STUDENT_DELETE", f"Deleted student with roll_no {roll_no}")
                return True, f"Student {roll_no} deleted."
            return False, f"Student {roll_no} not found."

    # --- Campus & Geofence Operations (Phase 17, 22) ---
    def get_all_campuses(self) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, latitude, longitude, radius_meters, accuracy_threshold_meters, is_active, created_at, updated_at FROM campuses ORDER BY id")
            return [dict(row) for row in cursor.fetchall()]

    def get_active_campuses(self) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, latitude, longitude, radius_meters, accuracy_threshold_meters, is_active, created_at, updated_at FROM campuses WHERE is_active = 1 ORDER BY id")
            return [dict(row) for row in cursor.fetchall()]

    def get_campus_by_id(self, campus_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, latitude, longitude, radius_meters, accuracy_threshold_meters, is_active, created_at, updated_at FROM campuses WHERE id = ?", (campus_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def add_campus(
        self,
        name: str,
        latitude: float,
        longitude: float,
        radius_meters: float = 30.0,
        accuracy_threshold_meters: float = 50.0,
        actor: str = "admin"
    ) -> Tuple[bool, str, Optional[int]]:
        name = name.strip()
        if not name:
            return False, "Campus name cannot be empty.", None
        if not (-90.0 <= latitude <= 90.0):
            return False, "Invalid latitude value (must be -90 to 90).", None
        if not (-180.0 <= longitude <= 180.0):
            return False, "Invalid longitude value (must be -180 to 180).", None
        if radius_meters <= 0:
            return False, "Allowed radius must be positive.", None

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO campuses (name, latitude, longitude, radius_meters, accuracy_threshold_meters, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
            """, (name, float(latitude), float(longitude), float(radius_meters), float(accuracy_threshold_meters)))
            campus_id = cursor.lastrowid
            conn.commit()
            self.log_audit("CAMPUS_ADD", f"Added campus '{name}' at ({latitude}, {longitude}) with radius {radius_meters}m", actor=actor)
            return True, f"Campus '{name}' added successfully.", campus_id

    def update_campus(
        self,
        campus_id: int,
        name: str,
        latitude: float,
        longitude: float,
        radius_meters: float,
        accuracy_threshold_meters: float = 50.0,
        is_active: bool = True,
        actor: str = "admin"
    ) -> Tuple[bool, str]:
        name = name.strip()
        if not name:
            return False, "Campus name cannot be empty."
        if not (-90.0 <= latitude <= 90.0):
            return False, "Invalid latitude value."
        if not (-180.0 <= longitude <= 180.0):
            return False, "Invalid longitude value."
        if radius_meters <= 0:
            return False, "Allowed radius must be greater than zero."

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE campuses
            SET name = ?, latitude = ?, longitude = ?, radius_meters = ?, accuracy_threshold_meters = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """, (name, float(latitude), float(longitude), float(radius_meters), float(accuracy_threshold_meters), 1 if is_active else 0, campus_id))
            if cursor.rowcount == 0:
                return False, f"Campus ID {campus_id} not found."
            conn.commit()
            self.log_audit("CAMPUS_UPDATE", f"Updated campus {campus_id} ('{name}'): lat={latitude}, lon={longitude}, radius={radius_meters}m", actor=actor)
            return True, f"Campus '{name}' updated successfully."

    def delete_campus(self, campus_id: int, actor: str = "admin") -> Tuple[bool, str]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM campuses WHERE id = ?", (campus_id,))
            if cursor.rowcount == 0:
                return False, f"Campus ID {campus_id} not found."
            conn.commit()
            self.log_audit("CAMPUS_DELETE", f"Deleted campus ID {campus_id}", actor=actor)
            return True, f"Campus {campus_id} deleted successfully."

    # --- System Settings Operations (Phase 22) ---
    def get_all_settings(self) -> Dict[str, str]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM system_settings")
            return {row["key"]: row["value"] for row in cursor.fetchall()}

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str, actor: str = "admin") -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO system_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
            """, (key, str(value)))
            conn.commit()
            self.log_audit("SETTING_UPDATE", f"Updated setting '{key}' = '{value}'", actor=actor)
            return True

    def update_settings(self, settings_dict: Dict[str, str], actor: str = "admin") -> Tuple[bool, str]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for key, val in settings_dict.items():
                cursor.execute("""
                INSERT INTO system_settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                """, (key, str(val)))
            conn.commit()
            self.log_audit("SETTINGS_BATCH_UPDATE", f"Updated {len(settings_dict)} settings", actor=actor)
            return True, "Settings updated successfully."

    # --- Audit Logging (Phase 17, 21, 22) ---
    def log_audit(self, action: str, details: str, actor: str = "system", ip_address: Optional[str] = None):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO audit_logs (action, details, actor, ip_address)
                VALUES (?, ?, ?, ?)
                """, (action, details, actor, ip_address))
                conn.commit()
        except Exception:
            pass  # Ensure audit failure never halts main business logic

    def get_audit_logs(self, limit: int = 100) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, action, details, actor, ip_address, created_at FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    # --- Lecture Scheduling & Attendance Operations (Phase 21) ---
    def create_lecture(
        self,
        course_code: str,
        subject_name: str,
        instructor_name: str,
        date_str: str,
        start_time_str: str,
        duration_minutes: int = 50,
        section: str = "A",
        room: str = "Room 101",
        campus_id: Optional[int] = None,
        window_before_mins: int = 5,
        window_after_mins: int = 15,
        actor: str = "admin"
    ) -> Tuple[bool, str, Optional[int]]:
        """
        Creates a scheduled lecture session:
        - Default duration: 50 minutes (configurable).
        - Computes end_time = start_time + duration_minutes.
        - Computes attendance window: start_time - window_before_mins to start_time + window_after_mins.
        """
        course_code = course_code.strip()
        subject_name = subject_name.strip()
        instructor_name = instructor_name.strip()

        if not course_code or not subject_name or not instructor_name:
            return False, "Course code, subject name, and instructor name are required.", None

        if duration_minutes <= 0:
            return False, "Lecture duration must be positive.", None

        # Validate date format (YYYY-MM-DD)
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return False, "Invalid date format. Expected YYYY-MM-DD.", None

        # Validate start_time format (HH:MM or HH:MM:SS)
        start_dt = None
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                start_dt = datetime.strptime(start_time_str, fmt)
                break
            except ValueError:
                continue

        if not start_dt:
            return False, "Invalid start time format. Expected HH:MM or HH:MM:SS.", None

        # Compute end time
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        end_time_str = end_dt.strftime("%H:%M:%S")
        start_time_norm = start_dt.strftime("%H:%M:%S")

        # Compute attendance window
        window_start_dt = start_dt - timedelta(minutes=window_before_mins)
        window_end_dt = start_dt + timedelta(minutes=window_after_mins)
        window_start_str = window_start_dt.strftime("%H:%M:%S")
        window_end_str = window_end_dt.strftime("%H:%M:%S")

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO lectures (
                course_code, subject_name, section, instructor_name,
                date, start_time, end_time, duration_minutes, room,
                attendance_window_start, attendance_window_end, status, campus_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Scheduled', ?)
            """, (
                course_code, subject_name, section, instructor_name,
                date_str, start_time_norm, end_time_str, duration_minutes, room,
                window_start_str, window_end_str, campus_id
            ))
            lecture_id = cursor.lastrowid
            conn.commit()

            self.log_audit("LECTURE_CREATE", f"Created lecture {lecture_id} '{subject_name}' ({course_code}) duration {duration_minutes}m", actor=actor)
            return True, f"Lecture '{subject_name}' ({course_code}) scheduled successfully.", lecture_id

    def get_lectures(self, date_str: Optional[str] = None, status: Optional[str] = None) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = """
            SELECT l.id, l.course_code, l.subject_name, l.section, l.instructor_name,
                   l.date, l.start_time, l.end_time, l.duration_minutes, l.room,
                   l.attendance_window_start, l.attendance_window_end, l.status,
                   l.campus_id, c.name as campus_name, l.created_at,
                   (SELECT COUNT(*) FROM lecture_attendance la WHERE la.lecture_id = l.id) as total_marked,
                   (SELECT COUNT(*) FROM lecture_attendance la WHERE la.lecture_id = l.id AND la.status = 'PRESENT') as present_count,
                   (SELECT COUNT(*) FROM lecture_attendance la WHERE la.lecture_id = l.id AND la.status = 'LATE') as late_count
            FROM lectures l
            LEFT JOIN campuses c ON l.campus_id = c.id
            WHERE 1=1
            """
            params = []
            if date_str:
                query += " AND l.date = ?"
                params.append(date_str)
            if status:
                query += " AND l.status = ?"
                params.append(status)

            query += " ORDER BY l.date DESC, l.start_time ASC"
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_lecture_by_id(self, lecture_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT l.id, l.course_code, l.subject_name, l.section, l.instructor_name,
                   l.date, l.start_time, l.end_time, l.duration_minutes, l.room,
                   l.attendance_window_start, l.attendance_window_end, l.status,
                   l.campus_id, c.name as campus_name, l.created_at
            FROM lectures l
            LEFT JOIN campuses c ON l.campus_id = c.id
            WHERE l.id = ?
            """, (lecture_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_lecture_status(self, lecture_id: int, new_status: str, actor: str = "admin") -> Tuple[bool, str]:
        if new_status not in ("Scheduled", "Open", "Closed", "Cancelled"):
            return False, f"Invalid status '{new_status}'. Allowed: Scheduled, Open, Closed, Cancelled."

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE lectures SET status = ? WHERE id = ?", (new_status, lecture_id))
            if cursor.rowcount == 0:
                return False, f"Lecture ID {lecture_id} not found."
            conn.commit()
            self.log_audit("LECTURE_STATUS_UPDATE", f"Lecture {lecture_id} status changed to '{new_status}'", actor=actor)
            return True, f"Lecture status updated to {new_status}."

    def get_current_or_open_lecture(
        self,
        course_code: Optional[str] = None,
        now_dt: Optional[datetime] = None
    ) -> Optional[Dict]:
        """
        Finds the active or scheduled lecture matching the current date and time.
        First checks lectures explicitly marked 'Open'.
        If none, checks lectures whose attendance window is currently active.
        """
        now = now_dt or datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. First look for explicitly Open lecture today
            query1 = "SELECT * FROM lectures WHERE date = ? AND status = 'Open'"
            params1 = [date_str]
            if course_code:
                query1 += " AND course_code = ?"
                params1.append(course_code)
            query1 += " ORDER BY start_time ASC LIMIT 1"

            cursor.execute(query1, params1)
            row = cursor.fetchone()
            if row:
                return dict(row)

            # 2. Look for Scheduled lecture whose attendance window is active
            query2 = """
            SELECT * FROM lectures 
            WHERE date = ? AND status = 'Scheduled'
              AND attendance_window_start <= ? AND attendance_window_end >= ?
            """
            params2 = [date_str, time_str, time_str]
            if course_code:
                query2 += " AND course_code = ?"
                params2.append(course_code)
            query2 += " ORDER BY start_time ASC LIMIT 1"

            cursor.execute(query2, params2)
            row = cursor.fetchone()
            return dict(row) if row else None

    # --- Lecture Attendance Verification & Anti-Bunking Marking ---
    def mark_lecture_attendance(
        self,
        lecture_id: int,
        student_id: int,
        confidence: float,
        distance_meters: Optional[float] = None,
        now_dt: Optional[datetime] = None
    ) -> Tuple[bool, str, Optional[Dict]]:
        """
        Records attendance for a specific lecture session with full checks:
        1. Lecture must exist and NOT be cancelled or closed.
        2. Attendance window must be open (checked against server time).
        3. Prevents duplicate submissions: student can only have ONE record per lecture.
        4. Distinguishes PRESENT from LATE based on late cutoff.
        """
        now = now_dt or datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Fetch lecture details
            cursor.execute("SELECT * FROM lectures WHERE id = ?", (lecture_id,))
            lecture = cursor.fetchone()
            if not lecture:
                return False, f"Lecture session {lecture_id} not found.", None

            # Check lecture status
            if lecture["status"] == "Cancelled":
                return False, "Attendance rejected: This lecture has been cancelled.", None
            if lecture["status"] == "Closed":
                return False, "Attendance rejected: Attendance for this lecture is closed.", None

            # Check date
            if lecture["date"] != date_str:
                return False, f"Attendance rejected: Lecture date is {lecture['date']}, not today ({date_str}).", None

            # Check attendance window (unless lecture is explicitly forced 'Open')
            if lecture["status"] != "Open":
                win_start = lecture["attendance_window_start"]
                win_end = lecture["attendance_window_end"]

                if time_str < win_start:
                    return False, f"Attendance has not opened yet for this lecture (opens at {win_start}).", None
                if time_str > win_end:
                    return False, "Attendance rejected: The attendance window for this lecture is closed.", None

            # Check for existing record (DUPLICATE SUBMISSION CHECK)
            cursor.execute(
                "SELECT id, status, marked_at FROM lecture_attendance WHERE lecture_id = ? AND student_id = ?",
                (lecture_id, student_id)
            )
            existing = cursor.fetchone()
            if existing:
                return False, f"Attendance already recorded for this lecture ({existing['status']} at {existing['marked_at']}).", None

            # Fetch student details
            cursor.execute("SELECT roll_no, name FROM students WHERE id = ?", (student_id,))
            student = cursor.fetchone()
            if not student:
                return False, f"Student ID {student_id} not found.", None

            # Determine PRESENT vs LATE
            # Read late cutoff setting or default to 10 mins after lecture start
            settings = self.get_all_settings()
            late_cutoff_mins = int(settings.get("late_cutoff_minutes", 10))
            
            start_dt = datetime.strptime(f"{date_str} {lecture['start_time']}", "%Y-%m-%d %H:%M:%S")
            cutoff_dt = start_dt + timedelta(minutes=late_cutoff_mins)
            
            is_late = now > cutoff_dt
            status = "LATE" if is_late else "PRESENT"

            # Insert into lecture_attendance with duplicate protection
            try:
                cursor.execute("""
                INSERT INTO lecture_attendance (
                    lecture_id, student_id, date, marked_at, status, confidence, initial_verified, distance_meters
                )
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """, (
                    lecture_id, student_id, date_str, time_str, status, float(confidence),
                    float(distance_meters) if distance_meters is not None else None
                ))

                # Also mirror in daily attendance table for backwards compatibility
                cursor.execute("""
                INSERT INTO attendance (student_id, date, time, status, confidence)
                VALUES (?, ?, ?, ?, ?)
                """, (student_id, date_str, time_str, status, float(confidence)))

                conn.commit()
            except sqlite3.IntegrityError:
                return False, "Attendance already recorded for this lecture session.", None

            record = {
                "lecture_id": lecture_id,
                "course_code": lecture["course_code"],
                "subject_name": lecture["subject_name"],
                "student_id": student_id,
                "roll_no": student["roll_no"],
                "name": student["name"],
                "date": date_str,
                "time": time_str,
                "status": status,
                "confidence": round(confidence, 2),
                "distance_meters": round(distance_meters, 1) if distance_meters is not None else None
            }

            return True, f"Recorded as {status}", record

    # --- Anti-Bunking Verification Events (Phase 21-D, E) ---
    def create_mid_lecture_verification_event(
        self,
        lecture_id: int,
        duration_minutes: int = 5,
        event_type: str = "MID_LECTURE",
        actor: str = "instructor"
    ) -> Tuple[bool, str, Optional[int]]:
        """
        Creates an anti-bunking verification event during an active lecture.
        Students must confirm attendance during this valid window.
        """
        now = datetime.now()
        start_str = now.strftime("%H:%M:%S")
        end_str = (now + timedelta(minutes=duration_minutes)).strftime("%H:%M:%S")

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, subject_name, status FROM lectures WHERE id = ?", (lecture_id,))
            lecture = cursor.fetchone()
            if not lecture:
                return False, "Lecture not found.", None
            if lecture["status"] == "Cancelled":
                return False, "Cannot trigger verification on a cancelled lecture.", None

            cursor.execute("""
            INSERT INTO verification_events (lecture_id, event_type, window_start, window_end, status)
            VALUES (?, ?, ?, ?, 'ACTIVE')
            """, (lecture_id, event_type, start_str, end_str))
            event_id = cursor.lastrowid
            conn.commit()

            self.log_audit("VERIFICATION_EVENT_CREATE", f"Created {event_type} verification for lecture {lecture_id} (Window: {start_str} - {end_str})", actor=actor)
            return True, f"Verification event {event_id} created (Active until {end_str}).", event_id

    def record_mid_lecture_verification(
        self,
        event_id: int,
        student_id: int,
        confidence: float,
        distance_meters: Optional[float] = None,
        now_dt: Optional[datetime] = None
    ) -> Tuple[bool, str, Optional[Dict]]:
        """
        Records a student's anti-bunking mid-lecture verification.
        Validates event window and prevents duplicate verification entries.
        """
        now = now_dt or datetime.now()
        time_str = now.strftime("%H:%M:%S")

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Check verification event
            cursor.execute("SELECT * FROM verification_events WHERE id = ?", (event_id,))
            event = cursor.fetchone()
            if not event:
                return False, "Verification event not found.", None

            if event["status"] != "ACTIVE":
                return False, f"Verification event is not active ({event['status']}).", None

            if time_str < event["window_start"]:
                return False, "Verification window has not opened yet.", None
            if time_str > event["window_end"]:
                return False, "Verification window for this event has expired.", None

            lecture_id = event["lecture_id"]

            # Check for duplicate verification submission
            cursor.execute(
                "SELECT id FROM lecture_verifications WHERE verification_event_id = ? AND student_id = ?",
                (event_id, student_id)
            )
            if cursor.fetchone():
                return False, "Mid-lecture verification already completed for this event.", None

            # Record verification
            cursor.execute("""
            INSERT INTO lecture_verifications (
                verification_event_id, lecture_id, student_id, verified_at, confidence, status, distance_meters
            )
            VALUES (?, ?, ?, ?, ?, 'VERIFIED', ?)
            """, (
                event_id, lecture_id, student_id, time_str, float(confidence),
                float(distance_meters) if distance_meters is not None else None
            ))

            # Update lecture_attendance record for this student
            cursor.execute("""
            UPDATE lecture_attendance
            SET mid_lecture_verified = 1
            WHERE lecture_id = ? AND student_id = ?
            """, (lecture_id, student_id))

            conn.commit()

            cursor.execute("SELECT roll_no, name FROM students WHERE id = ?", (student_id,))
            student = cursor.fetchone()

            return True, "Mid-lecture verification confirmed.", {
                "event_id": event_id,
                "lecture_id": lecture_id,
                "student_id": student_id,
                "roll_no": student["roll_no"] if student else "",
                "name": student["name"] if student else "",
                "verified_at": time_str,
                "confidence": round(confidence, 2)
            }

    # --- Instructor Attendance Correction (Phase 21-D, E) ---
    def correct_lecture_attendance(
        self,
        lecture_id: int,
        student_id: int,
        new_status: str,
        reason: str,
        authorized_by: str
    ) -> Tuple[bool, str]:
        """
        Allows an authorized instructor or administrator to manually correct an attendance record
        with a mandatory audit log entry.
        """
        new_status = new_status.upper()
        if new_status not in ("PRESENT", "LATE", "ABSENT"):
            return False, "Invalid attendance status. Must be PRESENT, LATE, or ABSENT."

        reason = reason.strip()
        if not reason:
            return False, "A reason must be provided for manual attendance corrections."

        authorized_by = authorized_by.strip()
        if not authorized_by:
            return False, "Authorizing instructor / admin username is required."

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Find existing record
            cursor.execute(
                "SELECT id, status FROM lecture_attendance WHERE lecture_id = ? AND student_id = ?",
                (lecture_id, student_id)
            )
            existing = cursor.fetchone()

            if existing:
                old_status = existing["status"]
                cursor.execute(
                    "UPDATE lecture_attendance SET status = ? WHERE id = ?",
                    (new_status, existing["id"])
                )
            else:
                old_status = "ABSENT"
                now = datetime.now()
                cursor.execute("""
                INSERT INTO lecture_attendance (lecture_id, student_id, date, marked_at, status, confidence, initial_verified)
                VALUES (?, ?, ?, ?, ?, 1.0, 1)
                """, (lecture_id, student_id, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), new_status))

            # Insert into corrections audit trail
            cursor.execute("""
            INSERT INTO attendance_corrections (lecture_id, student_id, old_status, new_status, reason, authorized_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (lecture_id, student_id, old_status, new_status, reason, authorized_by))

            conn.commit()

            self.log_audit(
                "ATTENDANCE_CORRECTION",
                f"Corrected lecture {lecture_id} student {student_id} from {old_status} to {new_status}. Reason: {reason}",
                actor=authorized_by
            )

            return True, f"Attendance corrected from {old_status} to {new_status}."

    # --- Lecture Reports & Anti-Bunking Analytics (Phase 21-D, E) ---
    def get_lecture_attendance_report(self, lecture_id: int) -> Dict[str, Any]:
        """
        Generates detailed report for a lecture session:
        - Total students
        - Present, Late, Absent counts
        - Mid-lecture check status (verified vs missed)
        - Individual student audit records
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            lecture = self.get_lecture_by_id(lecture_id)
            if not lecture:
                return {}

            # All students
            cursor.execute("SELECT id, roll_no, name, department, email FROM students ORDER BY roll_no")
            all_students = [dict(r) for r in cursor.fetchall()]

            # Attendance records for this lecture
            cursor.execute("""
            SELECT la.id, la.student_id, la.date, la.marked_at, la.status, la.confidence,
                   la.initial_verified, la.mid_lecture_verified, la.distance_meters,
                   s.roll_no, s.name, s.department
            FROM lecture_attendance la
            JOIN students s ON la.student_id = s.id
            WHERE la.lecture_id = ?
            ORDER BY s.roll_no
            """, (lecture_id,))
            attended_rows = {r["student_id"]: dict(r) for r in cursor.fetchall()}

            # Verification events count for this lecture
            cursor.execute("SELECT COUNT(*) FROM verification_events WHERE lecture_id = ?", (lecture_id,))
            has_mid_checks = cursor.fetchone()[0] > 0

            records = []
            present_count = 0
            late_count = 0
            absent_count = 0
            mid_verified_count = 0
            mid_missed_count = 0

            for st in all_students:
                st_id = st["id"]
                if st_id in attended_rows:
                    att = attended_rows[st_id]
                    status = att["status"]
                    if status == "PRESENT":
                        present_count += 1
                    elif status == "LATE":
                        late_count += 1

                    mid_ver = att.get("mid_lecture_verified")
                    if mid_ver == 1:
                        mid_verified_count += 1
                    elif has_mid_checks and mid_ver != 1:
                        mid_missed_count += 1

                    records.append({
                        "student_id": st_id,
                        "roll_no": st["roll_no"],
                        "name": st["name"],
                        "department": st["department"],
                        "status": status,
                        "marked_at": att["marked_at"],
                        "confidence": att["confidence"],
                        "distance_meters": att.get("distance_meters"),
                        "mid_lecture_verified": mid_ver
                    })
                else:
                    absent_count += 1
                    records.append({
                        "student_id": st_id,
                        "roll_no": st["roll_no"],
                        "name": st["name"],
                        "department": st["department"],
                        "status": "ABSENT",
                        "marked_at": "-",
                        "confidence": 0.0,
                        "distance_meters": None,
                        "mid_lecture_verified": 0 if has_mid_checks else None
                    })

            total = len(all_students)
            pct = round(((present_count + late_count) / total) * 100, 1) if total > 0 else 0.0

            return {
                "lecture": lecture,
                "summary": {
                    "total_students": total,
                    "present_count": present_count,
                    "late_count": late_count,
                    "absent_count": absent_count,
                    "attendance_percentage": pct,
                    "mid_lecture_verified_count": mid_verified_count,
                    "mid_lecture_missed_count": mid_missed_count
                },
                "records": records
            }

    def get_anti_bunking_analytics(self) -> Dict[str, Any]:
        """
        Computes aggregate institutional anti-bunking analytics:
        - Student-wise attendance percentage across all scheduled lectures
        - Subject-wise attendance percentage
        - Missed lecture frequency
        - Late arrival counts
        - Mid-lecture check completion rate
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Total lectures
            cursor.execute("SELECT COUNT(*) FROM lectures WHERE status != 'Cancelled'")
            total_lectures = cursor.fetchone()[0]

            # Student-wise breakdown
            cursor.execute("""
            SELECT s.id, s.roll_no, s.name, s.department,
                   COUNT(la.id) as lectures_attended,
                   SUM(CASE WHEN la.status = 'PRESENT' THEN 1 ELSE 0 END) as on_time_count,
                   SUM(CASE WHEN la.status = 'LATE' THEN 1 ELSE 0 END) as late_count,
                   SUM(CASE WHEN la.mid_lecture_verified = 1 THEN 1 ELSE 0 END) as mid_checks_passed
            FROM students s
            LEFT JOIN lecture_attendance la ON s.id = la.student_id
            GROUP BY s.id
            ORDER BY s.roll_no
            """)
            student_stats = []
            for row in cursor.fetchall():
                r = dict(row)
                attended = r["lectures_attended"] or 0
                pct = round((attended / total_lectures) * 100, 1) if total_lectures > 0 else 0.0
                r["missed_lectures"] = max(0, total_lectures - attended)
                r["attendance_percentage"] = pct
                student_stats.append(r)

            # Subject-wise breakdown
            cursor.execute("""
            SELECT l.course_code, l.subject_name,
                   COUNT(DISTINCT l.id) as total_sessions,
                   COUNT(la.id) as total_attendances
            FROM lectures l
            LEFT JOIN lecture_attendance la ON l.id = la.lecture_id
            WHERE l.status != 'Cancelled'
            GROUP BY l.course_code, l.subject_name
            """)
            subject_stats = []
            for row in cursor.fetchall():
                r = dict(row)
                sessions = r["total_sessions"] or 0
                cursor.execute("SELECT COUNT(*) FROM students")
                enrolled = cursor.fetchone()[0]
                possible = sessions * enrolled
                pct = round((r["total_attendances"] / possible) * 100, 1) if possible > 0 else 0.0
                r["attendance_percentage"] = pct
                subject_stats.append(r)

            return {
                "total_scheduled_lectures": total_lectures,
                "student_analytics": student_stats,
                "subject_analytics": subject_stats
            }

    # --- Traditional Attendance Operations (Preserved) ---
    def mark_attendance(
        self, 
        student_id: int, 
        confidence: float, 
        cooldown_minutes: int = 30,
        late_cutoff: str = "09:15:00"
    ) -> Tuple[bool, str, Optional[Dict]]:
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Check cooldown against previous attendance today
            cursor.execute(
                """
                SELECT time FROM attendance 
                WHERE student_id = ? AND date = ? 
                ORDER BY id DESC LIMIT 1
                """,
                (student_id, date_str)
            )
            last_record = cursor.fetchone()

            if last_record:
                last_time_str = last_record["time"]
                last_dt = datetime.strptime(f"{date_str} {last_time_str}", "%Y-%m-%d %H:%M:%S")
                if now - last_dt < timedelta(minutes=cooldown_minutes):
                    remaining = int((timedelta(minutes=cooldown_minutes) - (now - last_dt)).total_seconds() // 60)
                    return False, f"Cooldown active ({remaining}m left)", None

            # Determine attendance status (PRESENT or LATE)
            status = "LATE" if time_str > late_cutoff else "PRESENT"

            cursor.execute(
                """
                INSERT INTO attendance (student_id, date, time, status, confidence)
                VALUES (?, ?, ?, ?, ?)
                """,
                (student_id, date_str, time_str, status, float(confidence))
            )
            conn.commit()

            cursor.execute("SELECT roll_no, name FROM students WHERE id = ?", (student_id,))
            st_info = cursor.fetchone()

            return True, "Recorded", {
                "roll_no": st_info["roll_no"],
                "name": st_info["name"],
                "date": date_str,
                "time": time_str,
                "status": status,
                "confidence": round(confidence, 2)
            }

    def get_attendance_by_date(self, date_str: str) -> List[Dict]:
        month_str = date_str[:7]
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(DISTINCT date) FROM attendance WHERE date LIKE ?", (f"{month_str}%",))
            active_days_month = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT a.id, s.roll_no, s.name, s.department, a.date, a.time, a.status, a.confidence,
                       (SELECT COUNT(DISTINCT a2.date) FROM attendance a2 WHERE a2.student_id = s.id AND a2.date LIKE ?) as month_present_days
                FROM attendance a
                JOIN students s ON a.student_id = s.id
                WHERE a.date = ?
                ORDER BY a.id DESC
                """,
                (f"{month_str}%", date_str)
            )
            records = []
            for row in cursor.fetchall():
                r = dict(row)
                present_days = r.get("month_present_days", 0) or 0
                r["active_days_month"] = active_days_month
                r["month_present_days"] = present_days
                r["monthly_percentage"] = round((present_days / active_days_month) * 100, 1) if active_days_month > 0 else 0.0
                records.append(r)
            return records

    def get_today_attendance(self) -> List[Dict]:
        today_str = datetime.now().strftime("%Y-%m-%d")
        return self.get_attendance_by_date(today_str)

    def get_today_stats(self) -> Dict[str, Any]:
        today_str = datetime.now().strftime("%Y-%m-%d")
        month_str = datetime.now().strftime("%Y-%m")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(DISTINCT student_id) FROM attendance WHERE date = ?", (today_str,))
            present_today = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT student_id) FROM attendance WHERE date = ? AND status = 'LATE'", (today_str,))
            late_today = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM students")
            total_students = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT date) FROM attendance WHERE date LIKE ?", (f"{month_str}%",))
            active_days_month = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT student_id || '_' || date) FROM attendance WHERE date LIKE ?", (f"{month_str}%",))
            month_attendances = cursor.fetchone()[0]

            if active_days_month > 0 and total_students > 0:
                possible_attendances = total_students * active_days_month
                monthly_percentage = round((month_attendances / possible_attendances) * 100, 1)
            else:
                monthly_percentage = 0.0

            return {
                "total_students": total_students,
                "present_today": present_today,
                "late_today": late_today,
                "absent_today": max(0, total_students - present_today),
                "active_days_month": active_days_month,
                "monthly_percentage": monthly_percentage
            }

    def clear_today_attendance(self) -> int:
        today_str = datetime.now().strftime("%Y-%m-%d")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM attendance WHERE date = ?", (today_str,))
            count = cursor.rowcount
            conn.commit()
            return count

    # --- Export Utilities ---
    def export_attendance_csv(self, date_str: str, file_path: str) -> Tuple[bool, str]:
        records = self.get_attendance_by_date(date_str)
        if not records:
            return False, f"No attendance records found for date {date_str}."

        df = pd.DataFrame(records)
        df = df[["roll_no", "name", "department", "date", "time", "status", "confidence"]]
        df.columns = ["Roll No", "Name", "Department", "Date", "Time", "Status", "Confidence"]
        df.to_csv(file_path, index=False)
        return True, f"Exported {len(df)} records to {file_path}"

    # =========================================================================
    # --- PHASE 2 - 14: SMARTATTEND AI EXTENDED METHODS ---
    # =========================================================================

    # --- 1. Departments ---
    def create_department(self, name: str, code: str, head_teacher_id: Optional[int] = None) -> Tuple[bool, str, Optional[int]]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO departments (name, code, head_teacher_id) VALUES (?, ?, ?)",
                    (name.strip(), code.strip().upper(), head_teacher_id)
                )
                dept_id = cursor.lastrowid
                conn.commit()
                return True, f"Department '{name}' created successfully.", dept_id
        except sqlite3.IntegrityError:
            return False, f"Department with name '{name}' or code '{code}' already exists.", None
        except Exception as e:
            return False, str(e), None

    def get_departments(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM departments ORDER BY name ASC")
            return [dict(row) for row in cursor.fetchall()]

    def get_department_by_id(self, dept_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM departments WHERE id = ?", (dept_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # --- 2. Courses ---
    def create_course(self, department_id: int, name: str, code: str, semester: int = 1, credits: int = 4) -> Tuple[bool, str, Optional[int]]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO courses (department_id, name, code, semester, credits) VALUES (?, ?, ?, ?, ?)",
                    (department_id, name.strip(), code.strip().upper(), semester, credits)
                )
                course_id = cursor.lastrowid
                conn.commit()
                return True, f"Course '{name}' created successfully.", course_id
        except sqlite3.IntegrityError:
            return False, f"Course with code '{code}' already exists.", None
        except Exception as e:
            return False, str(e), None

    def get_courses(self, department_id: Optional[int] = None) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if department_id:
                cursor.execute("SELECT * FROM courses WHERE department_id = ? ORDER BY code ASC", (department_id,))
            else:
                cursor.execute("SELECT * FROM courses ORDER BY code ASC")
            return [dict(row) for row in cursor.fetchall()]

    # --- 3. Subjects ---
    def create_subject(self, course_id: int, name: str, code: str, sub_type: str = "Theory") -> Tuple[bool, str, Optional[int]]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO subjects (course_id, name, code, type) VALUES (?, ?, ?, ?)",
                    (course_id, name.strip(), code.strip().upper(), sub_type)
                )
                sub_id = cursor.lastrowid
                conn.commit()
                return True, f"Subject '{name}' created successfully.", sub_id
        except sqlite3.IntegrityError:
            return False, f"Subject with code '{code}' already exists.", None
        except Exception as e:
            return False, str(e), None

    def get_subjects(self, course_id: Optional[int] = None) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if course_id:
                cursor.execute("SELECT * FROM subjects WHERE course_id = ? ORDER BY name ASC", (course_id,))
            else:
                cursor.execute("SELECT * FROM subjects ORDER BY name ASC")
            return [dict(row) for row in cursor.fetchall()]

    # --- 4. Classrooms ---
    def create_classroom(
        self,
        name: str,
        building: str = "Main Building",
        floor: int = 1,
        capacity: int = 60,
        campus_id: Optional[int] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None
    ) -> Tuple[bool, str, Optional[int]]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO classrooms (name, building, floor, capacity, campus_id, latitude, longitude)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (name.strip(), building.strip(), floor, capacity, campus_id, latitude, longitude))
                c_id = cursor.lastrowid
                conn.commit()
                return True, f"Classroom '{name}' created successfully.", c_id
        except Exception as e:
            return False, str(e), None

    def get_classrooms(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM classrooms WHERE is_active = 1 ORDER BY name ASC")
            return [dict(row) for row in cursor.fetchall()]

    def get_classroom_by_id(self, classroom_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM classrooms WHERE id = ?", (classroom_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # --- 5. Teachers & Assignments ---
    def create_teacher(
        self,
        employee_id: str,
        name: str,
        email: str,
        password: str,
        department_id: Optional[int] = None
    ) -> Tuple[bool, str, Optional[int]]:
        pw_hash, salt = self._hash_password(password)
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO teachers (employee_id, name, email, department_id, password_hash, salt)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (employee_id.strip().upper(), name.strip(), email.strip().lower(), department_id, pw_hash, salt))
                t_id = cursor.lastrowid
                conn.commit()
                return True, f"Teacher '{name}' registered successfully.", t_id
        except sqlite3.IntegrityError:
            return False, "Teacher with this Employee ID or Email already exists.", None
        except Exception as e:
            return False, str(e), None

    def get_teachers(self, department_id: Optional[int] = None) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if department_id:
                cursor.execute("SELECT id, employee_id, name, email, department_id, is_active, created_at FROM teachers WHERE department_id = ?", (department_id,))
            else:
                cursor.execute("SELECT id, employee_id, name, email, department_id, is_active, created_at FROM teachers ORDER BY name ASC")
            return [dict(row) for row in cursor.fetchall()]

    def get_teacher_by_id(self, teacher_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, employee_id, name, email, department_id, is_active, created_at FROM teachers WHERE id = ?", (teacher_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def verify_teacher_login(self, email_or_empid: str, password: str) -> Optional[Dict[str, Any]]:
        clean_id = email_or_empid.strip().lower()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM teachers WHERE (LOWER(email) = ? OR LOWER(employee_id) = ?) AND is_active = 1",
                (clean_id, clean_id.upper())
            )
            row = cursor.fetchone()
            if not row:
                return None
            stored_hash = row["password_hash"]
            salt = row["salt"]
            calculated_hash, _ = self._hash_password(password, salt)
            if hmac.compare_digest(stored_hash, calculated_hash):
                return {
                    "id": row["id"],
                    "employee_id": row["employee_id"],
                    "name": row["name"],
                    "email": row["email"],
                    "department_id": row["department_id"],
                    "role": "TEACHER"
                }
            return None

    def assign_teacher_subject(self, teacher_id: int, subject_id: int, classroom_id: Optional[int] = None) -> Tuple[bool, str]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT OR REPLACE INTO teacher_subjects (teacher_id, subject_id, classroom_id)
                VALUES (?, ?, ?)
                """, (teacher_id, subject_id, classroom_id))
                conn.commit()
                return True, "Subject assigned to teacher successfully."
        except Exception as e:
            return False, str(e)

    def get_teacher_assigned_subjects(self, teacher_id: int) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT ts.id, ts.teacher_id, ts.subject_id, ts.classroom_id,
                   s.name as subject_name, s.code as subject_code, s.type as subject_type,
                   c.name as classroom_name, c.building, c.floor
            FROM teacher_subjects ts
            JOIN subjects s ON ts.subject_id = s.id
            LEFT JOIN classrooms c ON ts.classroom_id = c.id
            WHERE ts.teacher_id = ?
            """, (teacher_id,))
            return [dict(row) for row in cursor.fetchall()]

    # --- 6. Student Portal & Credentials ---
    def create_student_login(self, student_id: int, password: str) -> Tuple[bool, str]:
        pw_hash, salt = self._hash_password(password)
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT OR REPLACE INTO student_logins (student_id, password_hash, salt, is_active)
                VALUES (?, ?, ?, 1)
                """, (student_id, pw_hash, salt))
                conn.commit()
                return True, "Student login credentials configured successfully."
        except Exception as e:
            return False, str(e)

    def verify_student_login(self, roll_or_email: str, password: str) -> Optional[Dict[str, Any]]:
        clean_id = roll_or_email.strip().lower()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT s.id, s.roll_no, s.name, s.department, s.email, sl.password_hash, sl.salt
            FROM students s
            JOIN student_logins sl ON s.id = sl.student_id
            WHERE (LOWER(s.roll_no) = ? OR LOWER(s.email) = ?) AND sl.is_active = 1
            """, (clean_id, clean_id))
            row = cursor.fetchone()
            if not row:
                return None
            stored_hash = row["password_hash"]
            salt = row["salt"]
            calculated_hash, _ = self._hash_password(password, salt)
            if hmac.compare_digest(stored_hash, calculated_hash):
                # Update last login
                cursor.execute("UPDATE student_logins SET last_login = CURRENT_TIMESTAMP WHERE student_id = ?", (row["id"],))
                conn.commit()
                return {
                    "id": row["id"],
                    "roll_number": row["roll_no"],
                    "name": row["name"],
                    "department": row["department"],
                    "email": row["email"],
                    "role": "STUDENT"
                }
            return None

    def get_student_by_id(self, student_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, roll_no, name, department, email, created_at FROM students WHERE id = ?", (student_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_student_by_roll(self, roll_no: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, roll_no, name, department, email, created_at FROM students WHERE roll_no = ?", (roll_no.strip(),))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_student_attendance_stats(self, student_id: int) -> Dict[str, Any]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT roll_no, name, department FROM students WHERE id = ?", (student_id,))
            s_row = cursor.fetchone()
            if not s_row:
                return {"total_lectures": 0, "attended": 0, "percentage": 0.0}

            # Count distinct lectures or attendance marks
            cursor.execute("SELECT COUNT(*) FROM attendance WHERE student_id = ? AND status IN ('PRESENT', 'LATE')", (student_id,))
            attended_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT lecture_id) FROM lecture_attendance WHERE student_id = ?", (student_id,))
            total_lectures = cursor.fetchone()[0]
            if total_lectures == 0:
                # Fallback to total system lectures
                cursor.execute("SELECT COUNT(*) FROM lectures WHERE status != 'CANCELLED'")
                total_lectures = cursor.fetchone()[0]

            total_lectures = max(total_lectures, attended_count)
            pct = round((attended_count / total_lectures) * 100.0, 1) if total_lectures > 0 else 0.0

            return {
                "student_id": student_id,
                "roll_number": s_row["roll_no"],
                "name": s_row["name"],
                "department": s_row["department"],
                "total_lectures": total_lectures,
                "attended": attended_count,
                "percentage": pct
            }

    def is_attendance_already_recorded(self, student_id: int, lecture_id: Optional[int] = None, date_str: Optional[str] = None) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if lecture_id is not None:
                cursor.execute(
                    "SELECT id FROM lecture_attendance WHERE lecture_id = ? AND student_id = ?",
                    (lecture_id, student_id)
                )
                return cursor.fetchone() is not None
            elif date_str is not None:
                cursor.execute(
                    "SELECT id FROM attendance WHERE student_id = ? AND date = ?",
                    (student_id, date_str)
                )
                return cursor.fetchone() is not None
            else:
                today = datetime.now().strftime("%Y-%m-%d")
                cursor.execute(
                    "SELECT id FROM attendance WHERE student_id = ? AND date = ?",
                    (student_id, today)
                )
                return cursor.fetchone() is not None

    def get_student_lecture_history(self, student_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT la.id, la.date, la.marked_at as time, la.status, la.confidence,
                   COALESCE(l.subject_name, 'General') as subject,
                   COALESCE(l.start_time, '09:00') as start_time,
                   COALESCE(l.end_time, '17:00') as end_time,
                   COALESCE(l.status, 'COMPLETED') as lecture_status
            FROM lecture_attendance la
            LEFT JOIN lectures l ON la.lecture_id = l.id
            WHERE la.student_id = ?
            ORDER BY la.date DESC, la.marked_at DESC
            LIMIT ?
            """, (student_id, limit))
            records = [dict(row) for row in cursor.fetchall()]
            if not records:
                cursor.execute("""
                SELECT a.id, a.date, a.time, a.status, a.confidence,
                       'General' as subject, '09:00' as start_time, '17:00' as end_time, 'COMPLETED' as lecture_status
                FROM attendance a
                WHERE a.student_id = ?
                ORDER BY a.date DESC, a.time DESC
                LIMIT ?
                """, (student_id, limit))
                records = [dict(row) for row in cursor.fetchall()]
            return records

    def get_student_subject_breakdown(self, student_id: int) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT COALESCE(l.subject_name, 'General Attendance') as subject_name,
                   COUNT(*) as total_conducted,
                   SUM(CASE WHEN la.status IN ('PRESENT', 'LATE') THEN 1 ELSE 0 END) as attended
            FROM lecture_attendance la
            LEFT JOIN lectures l ON la.lecture_id = l.id
            WHERE la.student_id = ?
            GROUP BY subject_name
            """, (student_id,))
            rows = cursor.fetchall()
            results = []
            for r in rows:
                total = r["total_conducted"]
                att = r["attended"] or 0
                pct = round((att / total) * 100.0, 1) if total > 0 else 0.0
                results.append({
                    "subject": r["subject_name"],
                    "total_classes": total,
                    "attended": att,
                    "percentage": pct,
                    "status": "Safe" if pct >= 75.0 else "Shortage"
                })
            return results

    # --- 7. Parent Management & Auth ---
    def create_parent(self, name: str, email: str, password: str, phone: Optional[str] = None) -> Tuple[bool, str, Optional[int]]:
        pw_hash, salt = self._hash_password(password)
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO parents (name, email, phone, password_hash, salt)
                VALUES (?, ?, ?, ?, ?)
                """, (name.strip(), email.strip().lower(), phone, pw_hash, salt))
                p_id = cursor.lastrowid
                conn.commit()
                return True, f"Parent '{name}' registered successfully.", p_id
        except sqlite3.IntegrityError:
            return False, "Parent with this email already exists.", None
        except Exception as e:
            return False, str(e), None

    def link_student_parent(self, student_id: int, parent_id: int, relation: str = "Parent") -> Tuple[bool, str]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT OR REPLACE INTO student_parents (student_id, parent_id, relation)
                VALUES (?, ?, ?)
                """, (student_id, parent_id, relation))
                conn.commit()
                return True, "Parent linked to student successfully."
        except Exception as e:
            return False, str(e)

    def verify_parent_login(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        clean_email = email.strip().lower()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM parents WHERE LOWER(email) = ?", (clean_email,))
            row = cursor.fetchone()
            if not row:
                return None
            stored_hash = row["password_hash"]
            salt = row["salt"]
            calc_hash, _ = self._hash_password(password, salt)
            if hmac.compare_digest(stored_hash, calc_hash):
                return {
                    "id": row["id"],
                    "name": row["name"],
                    "email": row["email"],
                    "role": "PARENT"
                }
            return None

    def get_parent_wards(self, parent_id: int) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT s.id, s.roll_no, s.name, s.department, s.email, sp.relation
            FROM student_parents sp
            JOIN students s ON sp.student_id = s.id
            WHERE sp.parent_id = ?
            """, (parent_id,))
            return [dict(row) for row in cursor.fetchall()]

    # --- 8. Dynamic Attendance Sessions (QR & Live Verification) ---
    def create_attendance_session(
        self,
        teacher_id: int,
        subject_id: Optional[int] = None,
        classroom_id: Optional[int] = None,
        lecture_id: Optional[int] = None,
        qr_expiry_seconds: int = 30,
        require_face: bool = True,
        require_location: bool = True,
        require_qr: bool = True
    ) -> Tuple[bool, str, Optional[int]]:
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO attendance_sessions (
                    teacher_id, subject_id, classroom_id, lecture_id, session_date,
                    qr_expiry_seconds, require_face, require_location, require_qr, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE')
                """, (
                    teacher_id, subject_id, classroom_id, lecture_id, today,
                    qr_expiry_seconds, 1 if require_face else 0,
                    1 if require_location else 0, 1 if require_qr else 0
                ))
                sess_id = cursor.lastrowid
                conn.commit()
                return True, "Attendance session started successfully.", sess_id
        except Exception as e:
            return False, str(e), None

    def end_attendance_session(self, session_id: int, teacher_id: Optional[int] = None) -> Tuple[bool, str]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if teacher_id:
                cursor.execute(
                    "UPDATE attendance_sessions SET status = 'ENDED', ended_at = CURRENT_TIMESTAMP WHERE id = ? AND teacher_id = ?",
                    (session_id, teacher_id)
                )
            else:
                cursor.execute(
                    "UPDATE attendance_sessions SET status = 'ENDED', ended_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (session_id,)
                )
            if cursor.rowcount > 0:
                conn.commit()
                return True, "Session closed successfully."
            return False, "Session not found or unauthorized."

    def get_session_by_id(self, session_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT sess.*, s.name as subject_name, s.code as subject_code,
                   c.name as classroom_name, c.latitude, c.longitude,
                   t.name as teacher_name
            FROM attendance_sessions sess
            LEFT JOIN subjects s ON sess.subject_id = s.id
            LEFT JOIN classrooms c ON sess.classroom_id = c.id
            LEFT JOIN teachers t ON sess.teacher_id = t.id
            WHERE sess.id = ?
            """, (session_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # --- 9. QR Token Nonce Tracking ---
    def store_qr_token(self, nonce: str, session_id: int, teacher_id: int, classroom_id: Optional[int], expiry_seconds: int = 30) -> bool:
        now = datetime.now()
        exp = now + timedelta(seconds=expiry_seconds)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        exp_str = exp.strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO qr_tokens (nonce, session_id, teacher_id, classroom_id, issued_at, expires_at, consumed)
                VALUES (?, ?, ?, ?, ?, ?, 0)
                """, (nonce, session_id, teacher_id, classroom_id, now_str, exp_str))
                conn.commit()
                return True
        except Exception:
            return False

    def is_qr_nonce_consumed(self, nonce: str) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT consumed FROM qr_tokens WHERE nonce = ?", (nonce,))
            row = cursor.fetchone()
            if not row:
                return False
            return bool(row["consumed"])

    def mark_qr_nonce_consumed(self, nonce: str, student_id: int) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE qr_tokens
            SET consumed = 1, consumed_by_student_id = ?, consumed_at = CURRENT_TIMESTAMP
            WHERE nonce = ? AND consumed = 0
            """, (student_id, nonce))
            updated = cursor.rowcount > 0
            conn.commit()
            return updated

    # --- 10. Multi-Layer Verification Results & Reviews ---
    def record_verification_result(
        self,
        student_id: int,
        overall_status: str,
        session_id: Optional[int] = None,
        lecture_id: Optional[int] = None,
        face_match_score: Optional[float] = None,
        face_status: Optional[str] = None,
        liveness_status: Optional[str] = None,
        liveness_texture_score: Optional[float] = None,
        location_status: Optional[str] = None,
        location_distance_m: Optional[float] = None,
        qr_status: Optional[str] = None,
        rejection_reason: Optional[str] = None
    ) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO attendance_verification_results (
                student_id, overall_status, session_id, lecture_id, face_match_score,
                face_status, liveness_status, liveness_texture_score, location_status,
                location_distance_m, qr_status, rejection_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                student_id, overall_status, session_id, lecture_id, face_match_score,
                face_status, liveness_status, liveness_texture_score, location_status,
                location_distance_m, qr_status, rejection_reason
            ))
            res_id = cursor.lastrowid
            conn.commit()
            return res_id

    def get_pending_verification_reviews(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT vr.*, s.roll_no, s.name as student_name, s.department
            FROM attendance_verification_results vr
            JOIN students s ON vr.student_id = s.id
            WHERE vr.overall_status = 'PENDING_REVIEW'
            ORDER BY vr.submitted_at DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def review_verification_result(self, result_id: int, new_status: str, reviewed_by: str) -> bool:
        if new_status not in ("VERIFIED", "REJECTED"):
            return False
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE attendance_verification_results
            SET overall_status = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """, (new_status, reviewed_by, result_id))
            updated = cursor.rowcount > 0
            conn.commit()
            return updated

    # --- 11. Leave Requests ---
    def submit_leave_request(
        self,
        student_id: int,
        leave_type: str,
        from_date: str,
        to_date: str,
        reason: str,
        document_path: Optional[str] = None
    ) -> Tuple[bool, str, Optional[int]]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO leave_requests (student_id, leave_type, from_date, to_date, reason, supporting_document_path, status)
                VALUES (?, ?, ?, ?, ?, ?, 'PENDING')
                """, (student_id, leave_type.upper(), from_date, to_date, reason.strip(), document_path))
                req_id = cursor.lastrowid
                conn.commit()
                return True, "Leave request submitted successfully.", req_id
        except Exception as e:
            return False, str(e), None

    def get_student_leave_requests(self, student_id: int) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT * FROM leave_requests WHERE student_id = ? ORDER BY created_at DESC
            """, (student_id,))
            return [dict(row) for row in cursor.fetchall()]

    def get_pending_leave_requests(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT lr.*, s.roll_no, s.name as student_name, s.department
            FROM leave_requests lr
            JOIN students s ON lr.student_id = s.id
            WHERE lr.status = 'PENDING'
            ORDER BY lr.created_at ASC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def review_leave_request(self, request_id: int, decision: str, reviewer_name: str, comment: Optional[str] = None) -> Tuple[bool, str]:
        if decision not in ("APPROVED", "REJECTED"):
            return False, "Invalid decision: must be APPROVED or REJECTED"
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE leave_requests
            SET status = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP, review_comment = ?
            WHERE id = ? AND status = 'PENDING'
            """, (decision, reviewer_name, comment, request_id))
            if cursor.rowcount > 0:
                conn.commit()
                return True, f"Leave request marked {decision}."
            return False, "Request not found or already processed."

    # --- 12. Notifications ---
    def create_notification_record(
        self,
        recipient_type: str,
        recipient_id: int,
        recipient_email: Optional[str],
        notification_type: str,
        subject: str,
        body: str
    ) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO notifications (recipient_type, recipient_id, recipient_email, type, subject, body, is_sent)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            """, (recipient_type.upper(), recipient_id, recipient_email, notification_type, subject, body))
            nid = cursor.lastrowid
            conn.commit()
            return nid

    def mark_notification_sent(self, notif_id: int, is_sent: int = 1, error_message: Optional[str] = None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE notifications
            SET is_sent = ?, sent_at = CURRENT_TIMESTAMP, error_message = ?
            WHERE id = ?
            """, (is_sent, error_message, notif_id))
            conn.commit()

    def get_user_notifications(self, recipient_type: str, recipient_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT * FROM notifications
            WHERE recipient_type = ? AND recipient_id = ?
            ORDER BY created_at DESC LIMIT ?
            """, (recipient_type.upper(), recipient_id, limit))
            return [dict(row) for row in cursor.fetchall()]

    # --- 13. Reports & Analytics Helper Queries ---
    def get_filtered_attendance_records(
        self,
        lecture_id: Optional[int] = None,
        date_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if lecture_id:
                query = """
                SELECT la.id, la.student_id, s.roll_no, s.name, s.department,
                       COALESCE(l.subject_name, 'General') as subject, la.lecture_id,
                       la.date, la.marked_at as timestamp, la.status,
                       'SMARTATTEND_MULTI_LAYER' as verification_method,
                       'VERIFIED' as location_status
                FROM lecture_attendance la
                JOIN students s ON la.student_id = s.id
                LEFT JOIN lectures l ON la.lecture_id = l.id
                WHERE la.lecture_id = ?
                """
                params = [lecture_id]
                if date_filter:
                    query += " AND la.date = ?"
                    params.append(date_filter)
                query += " ORDER BY la.date DESC, la.marked_at DESC"
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
            else:
                query = """
                SELECT a.id, a.student_id, s.roll_no, s.name, s.department,
                       'General' as subject, 0 as lecture_id,
                       a.date, a.time as timestamp, a.status,
                       'FACE_GEOFENCE' as verification_method,
                       'VERIFIED' as location_status
                FROM attendance a
                JOIN students s ON a.student_id = s.id
                WHERE 1=1
                """
                params = []
                if date_filter:
                    query += " AND a.date = ?"
                    params.append(date_filter)
                query += " ORDER BY a.date DESC, a.time DESC"
                cursor.execute(query, params)
                records = [dict(row) for row in cursor.fetchall()]
                if not records:
                    query2 = """
                    SELECT la.id, la.student_id, s.roll_no, s.name, s.department,
                           COALESCE(l.subject_name, 'General') as subject, la.lecture_id,
                           la.date, la.marked_at as timestamp, la.status,
                           'SMARTATTEND_MULTI_LAYER' as verification_method,
                           'VERIFIED' as location_status
                    FROM lecture_attendance la
                    JOIN students s ON la.student_id = s.id
                    LEFT JOIN lectures l ON la.lecture_id = l.id
                    WHERE 1=1
                    """
                    params2 = []
                    if date_filter:
                        query2 += " AND la.date = ?"
                        params2.append(date_filter)
                    query2 += " ORDER BY la.date DESC, la.marked_at DESC"
                    cursor.execute(query2, params2)
                    records = [dict(row) for row in cursor.fetchall()]
                return records

    def get_students_summary_for_reports(self, department_id: Optional[int] = None) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT s.id, s.roll_no, s.name, s.department, s.email FROM students s WHERE 1=1"
            params = []
            if department_id:
                # Resolve department name
                cursor.execute("SELECT name FROM departments WHERE id = ?", (department_id,))
                drow = cursor.fetchone()
                if drow:
                    query += " AND s.department = ?"
                    params.append(drow["name"])
            cursor.execute(query, params)
            students = cursor.fetchall()
            summaries = []
            for s in students:
                stats = self.get_student_attendance_stats(s["id"])
                summaries.append({
                    "id": s["id"],
                    "roll_number": s["roll_no"],
                    "name": s["name"],
                    "department": s["department"],
                    "email": s["email"],
                    "total_classes": stats["total_lectures"],
                    "attended_classes": stats["attended"],
                    "percentage": stats["percentage"]
                })
            return summaries

    def get_daily_attendance_counts(self, student_id: Optional[int] = None, days_back: int = 90) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
            if student_id:
                cursor.execute("""
                SELECT date, COUNT(*) as count
                FROM attendance
                WHERE student_id = ? AND date >= ? AND status IN ('PRESENT', 'LATE')
                GROUP BY date ORDER BY date ASC
                """, (student_id, cutoff))
            else:
                cursor.execute("""
                SELECT date, COUNT(DISTINCT student_id) as count
                FROM attendance
                WHERE date >= ? AND status IN ('PRESENT', 'LATE')
                GROUP BY date ORDER BY date ASC
                """, (cutoff,))
            return [{"date": row["date"], "count": row["count"]} for row in cursor.fetchall()]

    def get_students_by_department(self, department_id: int) -> List[Dict[str, Any]]:
        dept = self.get_department_by_id(department_id)
        if not dept:
            return []
        dept_name = dept["name"]
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, roll_no, name, department, email FROM students WHERE department = ?", (dept_name,))
            return [dict(row) for row in cursor.fetchall()]

    def get_monthly_system_attendance(self, months_back: int = 6) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT SUBSTR(date, 1, 7) as month,
                   COUNT(*) as total_marked,
                   SUM(CASE WHEN status IN ('PRESENT', 'LATE') THEN 1 ELSE 0 END) as present_count
            FROM attendance
            GROUP BY month
            ORDER BY month DESC
            LIMIT ?
            """, (months_back,))
            rows = cursor.fetchall()
            return [dict(row) for row in reversed(rows)]

    def record_offline_attendance(
        self,
        student_id: int,
        lecture_id: int,
        date_str: str,
        time_str: str,
        verification_method: str = "OFFLINE_SYNC",
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        submitted_by: str = "OFFLINE_CLIENT"
    ) -> bool:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # Ensure lecture exists or create a default record to satisfy FK
                cursor.execute("SELECT id FROM lectures WHERE id = ?", (lecture_id,))
                if not cursor.fetchone():
                    cursor.execute("""
                    INSERT OR IGNORE INTO lectures (id, course_code, subject_name, instructor_name, date, start_time, end_time, status)
                    VALUES (?, 'GEN101', 'General', 'System', ?, ?, '17:00:00', 'Open')
                    """, (lecture_id, date_str, time_str))

                cursor.execute("""
                INSERT OR REPLACE INTO lecture_attendance (lecture_id, student_id, date, marked_at, status, confidence, initial_verified)
                VALUES (?, ?, ?, ?, 'PRESENT', 0.99, 1)
                """, (lecture_id, student_id, date_str, time_str))

                cursor.execute("SELECT id FROM attendance WHERE student_id = ? AND date = ?", (student_id, date_str))
                if not cursor.fetchone():
                    cursor.execute("""
                    INSERT INTO attendance (student_id, date, time, status, confidence)
                    VALUES (?, ?, ?, 'PRESENT', 0.99)
                    """, (student_id, date_str, time_str))
                conn.commit()
                return True
        except Exception:
            return False

    # --- 14. Camera & Beacon Management ---
    def create_camera(self, camera_uid: str, name: str, api_key: str, classroom_id: Optional[int] = None) -> Tuple[bool, str, Optional[int]]:
        key_hash, salt = self._hash_password(api_key)
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO cameras (camera_uid, name, classroom_id, api_key_hash, api_key_salt, is_active, health_status)
                VALUES (?, ?, ?, ?, ?, 1, 'ONLINE')
                """, (camera_uid.strip(), name.strip(), classroom_id, key_hash, salt))
                cam_id = cursor.lastrowid
                conn.commit()
                return True, f"Camera '{name}' registered.", cam_id
        except sqlite3.IntegrityError:
            return False, "Camera with this UID already exists.", None
        except Exception as e:
            return False, str(e), None

    def get_cameras(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT c.id, c.camera_uid, c.name, c.classroom_id, c.is_active, c.last_seen, c.health_status,
                   cr.name as classroom_name
            FROM cameras c
            LEFT JOIN classrooms cr ON c.classroom_id = cr.id
            ORDER BY c.name ASC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def verify_camera_key(self, camera_uid: str, api_key: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM cameras WHERE camera_uid = ? AND is_active = 1", (camera_uid.strip(),))
            row = cursor.fetchone()
            if not row:
                return None
            stored_hash = row["api_key_hash"]
            salt = row["api_key_salt"]
            calc_hash, _ = self._hash_password(api_key, salt)
            if hmac.compare_digest(stored_hash, calc_hash):
                # Update last seen
                cursor.execute("UPDATE cameras SET last_seen = CURRENT_TIMESTAMP, health_status = 'ONLINE' WHERE id = ?", (row["id"],))
                conn.commit()
                return dict(row)
            return None

    def create_beacon(self, beacon_uuid: str, name: str, classroom_id: Optional[int] = None, major: Optional[int] = None, minor: Optional[int] = None) -> Tuple[bool, str, Optional[int]]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO beacons (beacon_uuid, name, classroom_id, major, minor, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
                """, (beacon_uuid.strip(), name.strip(), classroom_id, major, minor))
                b_id = cursor.lastrowid
                conn.commit()
                return True, f"Beacon '{name}' registered.", b_id
        except sqlite3.IntegrityError:
            return False, "Beacon with this UUID already exists.", None
        except Exception as e:
            return False, str(e), None

    def get_beacons(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT b.*, cr.name as classroom_name
            FROM beacons b
            LEFT JOIN classrooms cr ON b.classroom_id = cr.id
            ORDER BY b.name ASC
            """)
            return [dict(row) for row in cursor.fetchall()]

    # --- 15. Timetables ---
    def create_timetable_entry(
        self,
        subject_id: int,
        teacher_id: int,
        day_of_week: int,
        start_time: str,
        end_time: str,
        classroom_id: Optional[int] = None
    ) -> Tuple[bool, str, Optional[int]]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO timetables (subject_id, teacher_id, day_of_week, start_time, end_time, classroom_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (subject_id, teacher_id, day_of_week, start_time, end_time, classroom_id))
                tt_id = cursor.lastrowid
                conn.commit()
                return True, "Timetable entry created.", tt_id
        except Exception as e:
            return False, str(e), None

    def get_timetables_by_teacher(self, teacher_id: int) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT tt.*, s.name as subject_name, s.code as subject_code, cr.name as classroom_name
            FROM timetables tt
            JOIN subjects s ON tt.subject_id = s.id
            LEFT JOIN classrooms cr ON tt.classroom_id = cr.id
            WHERE tt.teacher_id = ? AND tt.is_active = 1
            ORDER BY tt.day_of_week, tt.start_time
            """, (teacher_id,))
            return [dict(row) for row in cursor.fetchall()]

    # --- 16. Holidays ---
    def add_holiday(self, date_str: str, name: str, h_type: str = "NATIONAL") -> Tuple[bool, str]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO holidays (date, name, type) VALUES (?, ?, ?)", (date_str, name.strip(), h_type.upper()))
                conn.commit()
                return True, f"Holiday '{name}' added for {date_str}."
        except sqlite3.IntegrityError:
            return False, f"Holiday already exists for date {date_str}."
        except Exception as e:
            return False, str(e)

    def get_holidays(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM holidays WHERE is_active = 1 ORDER BY date ASC")
            return [dict(row) for row in cursor.fetchall()]

    def is_holiday(self, date_str: str) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM holidays WHERE date = ? AND is_active = 1", (date_str,))
            return cursor.fetchone()[0] > 0

