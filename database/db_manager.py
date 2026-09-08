import sqlite3
import hashlib
import os
import secrets
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Students table
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

            # Attendance table
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

            # Admin users table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
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
        if len(new_pass) < 4:
            return False, "Password must be at least 4 characters."
        pw_hash, salt = self._hash_password(new_pass)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE admins SET password_hash = ?, salt = ? WHERE username = ?",
                (pw_hash, salt, username)
            )
            conn.commit()
        return True, "Password updated successfully."

    # --- Student Operations ---
    def register_student(self, roll_no: str, name: str, department: str, email: str, embedding: np.ndarray) -> Tuple[bool, str]:
        roll_no = roll_no.strip()
        name = name.strip()
        if not roll_no or not name:
            return False, "Roll number and name cannot be empty."

        embedding_blob = embedding.astype(np.float32).tobytes()
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO students (roll_no, name, department, email, embedding)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(roll_no) DO UPDATE SET
                        name = excluded.name,
                        department = excluded.department,
                        email = excluded.email,
                        embedding = excluded.embedding
                    """,
                    (roll_no, name, department.strip() or 'General', email.strip(), embedding_blob)
                )
                conn.commit()
            return True, f"Student {name} ({roll_no}) registered successfully."
        except Exception as e:
            return False, f"Failed to register student: {str(e)}"

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
                return True, f"Student {roll_no} deleted."
            return False, f"Student {roll_no} not found."

    # --- Attendance Operations ---
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
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT a.id, s.roll_no, s.name, s.department, a.date, a.time, a.status, a.confidence
                FROM attendance a
                JOIN students s ON a.student_id = s.id
                WHERE a.date = ?
                ORDER BY a.id DESC
                """,
                (date_str,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_today_attendance(self) -> List[Dict]:
        today_str = datetime.now().strftime("%Y-%m-%d")
        return self.get_attendance_by_date(today_str)

    def get_today_stats(self) -> Dict[str, int]:
        today_str = datetime.now().strftime("%Y-%m-%d")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(DISTINCT student_id) FROM attendance WHERE date = ?", (today_str,))
            present_today = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT student_id) FROM attendance WHERE date = ? AND status = 'LATE'", (today_str,))
            late_today = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM students")
            total_students = cursor.fetchone()[0]

            return {
                "total_students": total_students,
                "present_today": present_today,
                "late_today": late_today,
                "absent_today": max(0, total_students - present_today)
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

