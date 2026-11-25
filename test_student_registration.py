"""
Comprehensive Unit and Integration Tests for Student Registration and Validation Module.

Covers:
1. Student Name Validation (Title Case, UPPERCASE, initials, no digits, no mixed case).
2. Roll Number Validation (Numeric only, preserves leading zeros, rejects letters/symbols).
3. Email Validation (Lowercase alphanumeric local part, valid domain with TLD, rejects abcd@123).
4. Unique Database Constraints (roll_no unique, case-insensitive email unique).
5. Safe Duplicate Handling (Rejects duplicate roll/email without silent overwrite).
6. Secure Password Hashing (Salted PBKDF2-HMAC-SHA256, no plaintext).
7. Preservation of Existing Valid Student Records.
8. Legacy Record Audit Reporting (Flags records for manual review, no automatic rewrites).
"""
import os
import sys
import unittest
import tempfile
import sqlite3
import numpy as np

# Ensure root directory is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.validators import validate_student_name, validate_roll_number, validate_email
from database.db_manager import DatabaseManager


class TestStudentRegistrationAndValidation(unittest.TestCase):
    def setUp(self):
        # Create a temporary isolated database for each test
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_attendance.db")
        self.db = DatabaseManager(self.db_path)
        # Dummy 128-D normalized embedding vector
        dummy = np.random.randn(128).astype(np.float32)
        self.dummy_emb = dummy / np.linalg.norm(dummy)

    def tearDown(self):
        self.temp_dir.cleanup()

    # =========================================================================
    # 1. STUDENT NAME VALIDATION
    # =========================================================================
    def test_student_name_documented_policy_valid(self):
        valid_names = [
            ("Rohit Pathak", "Rohit Pathak"),
            ("ROHIT PATHAK", "ROHIT PATHAK"),
            ("Mary Jane Watson", "Mary Jane Watson"),
            ("ALICE SMITH", "ALICE SMITH"),
            ("Smith-Jones", "Smith-Jones"),
            ("O'Connor", "O'Connor"),
            ("Rohit K. Pathak", "Rohit K. Pathak"),
            ("J.K. Rowling", "J.K. Rowling"),
            ("A. P. J. Abdul Kalam", "A. P. J. Abdul Kalam"),
            ("  Suraj Kumar  ", "Suraj Kumar")  # Leading/trailing whitespace trimmed
        ]
        for raw, expected in valid_names:
            ok, norm, err = validate_student_name(raw)
            self.assertTrue(ok, f"Name '{raw}' should be valid, got: {err}")
            self.assertEqual(norm, expected)

    def test_student_name_rejects_digits_and_numbers(self):
        invalid_digit_names = [
            "rohit123",
            "12345",
            "John2",
            "Rohit 2nd",
            "Agent 007",
            "123",
            "Student#1"
        ]
        for name in invalid_digit_names:
            ok, _, err = validate_student_name(name)
            self.assertFalse(ok, f"Name '{name}' containing digits should be rejected.")
            self.assertTrue("digit" in err.lower() or "number" in err.lower() or "invalid" in err.lower())

    def test_student_name_rejects_irregular_mixed_cases(self):
        invalid_cases = [
            "rohit PATHAK",
            "rohit pathak",
            "rohit",
            "rOhIt",
            "ROHIT pathak"
        ]
        for name in invalid_cases:
            ok, _, err = validate_student_name(name)
            self.assertFalse(ok, f"Name '{name}' with irregular capitalization should be rejected.")

    def test_student_name_admin_override(self):
        # Admin override allows legitimate exceptional conventions (e.g. noble particles)
        ok, norm, _ = validate_student_name("de la Cruz", allow_admin_override=True)
        self.assertTrue(ok)
        self.assertEqual(norm, "de la Cruz")

    # =========================================================================
    # 2. ROLL NUMBER / STUDENT IDENTIFIER VALIDATION
    # =========================================================================
    def test_roll_number_numeric_and_preserves_leading_zeros(self):
        valid_rolls = [
            "007",
            "0123",
            "00001",
            "20261001",
            "1"
        ]
        for roll in valid_rolls:
            ok, norm, err = validate_roll_number(roll, require_numeric=True)
            self.assertTrue(ok, f"Roll '{roll}' should be valid, got: {err}")
            # Ensure leading zeros are strictly preserved as string
            self.assertEqual(norm, roll)
            self.assertIsInstance(norm, str)

    def test_roll_number_rejects_alphabetic_characters(self):
        invalid_alpha_rolls = [
            "AB123",
            "12A45",
            "CS101",
            "RollNo1",
            "R007"
        ]
        for roll in invalid_alpha_rolls:
            ok, _, err = validate_roll_number(roll, require_numeric=True)
            self.assertFalse(ok, f"Roll '{roll}' with letters should be rejected.")
            self.assertIn("digits only", err.lower())

    def test_roll_number_rejects_punctuation_and_spaces(self):
        invalid_rolls = [
            "12-345",
            "12 345",
            "12.345",
            "12_345",
            "#123",
            "",
            None
        ]
        for roll in invalid_rolls:
            ok, _, _ = validate_roll_number(roll, require_numeric=True)
            self.assertFalse(ok, f"Roll '{roll}' should be rejected.")

    # =========================================================================
    # 3. EMAIL STRUCTURE AND POLICY VALIDATION
    # =========================================================================
    def test_email_lowercase_alphanumeric_local_part(self):
        valid_emails = [
            "abcd123@example.com",
            "student2026@university.edu",
            "rohit13@college.ac.in",
            "12345@domain.com"
        ]
        for email in valid_emails:
            ok, norm, err = validate_email(email)
            self.assertTrue(ok, f"Email '{email}' should be valid, got: {err}")
            self.assertEqual(norm, email.strip().lower())

    def test_email_rejects_uppercase_in_local_part(self):
        invalid_emails = [
            "Abcd123@example.com",
            "ROHIT@example.com",
            "johnDoe@example.com"
        ]
        for email in invalid_emails:
            ok, _, err = validate_email(email)
            self.assertFalse(ok, f"Email '{email}' with uppercase local part should be rejected.")
            self.assertIn("lowercase", err.lower())

    def test_email_rejects_invalid_domains_such_as_abcd_123(self):
        # Explicit requirement: Do not treat abcd@123 as a standard valid email address
        invalid_emails = [
            "abcd@123",
            "abcd123@",
            "@example.com",
            "abcd123@example",
            "abcd123@.com",
            "abcd123@123.456",  # Numeric TLD
            "abcd123@example.c"  # Single letter TLD
        ]
        for email in invalid_emails:
            ok, _, err = validate_email(email)
            self.assertFalse(ok, f"Email '{email}' should be rejected as invalid.")

    # =========================================================================
    # 4. DATABASE CONSTRAINTS & DUPLICATE REGISTRATION SAFETY
    # =========================================================================
    def test_database_preserves_leading_zeros(self):
        ok, msg = self.db.register_student(
            roll_no="007",
            name="James Bond",
            department="Security",
            email="james007@secret.gov",
            embedding=self.dummy_emb
        )
        self.assertTrue(ok, msg)

        # Retrieve student from DB and check roll_no is string '007', not integer 7
        student = self.db.get_student_by_roll("007")
        self.assertIsNotNone(student)
        self.assertEqual(student["roll_no"], "007")
        self.assertEqual(student["name"], "James Bond")

    def test_duplicate_roll_number_rejected_safely_without_overwrite(self):
        # Register student 1
        ok, msg = self.db.register_student(
            roll_no="101",
            name="Alice Smith",
            department="CSE",
            email="alice101@college.edu",
            embedding=self.dummy_emb
        )
        self.assertTrue(ok, msg)

        # Attempt to register duplicate roll number with different person
        ok2, msg2 = self.db.register_student(
            roll_no="101",
            name="Bob Jones",
            department="ECE",
            email="bob101@college.edu",
            embedding=self.dummy_emb,
            allow_update=False
        )
        self.assertFalse(ok2, "Duplicate roll number registration must be rejected.")
        self.assertIn("duplicate registration", msg2.lower())

        # Verify original student record was NOT overwritten
        student = self.db.get_student_by_roll("101")
        self.assertEqual(student["name"], "Alice Smith")
        self.assertEqual(student["email"], "alice101@college.edu")

    def test_duplicate_email_rejected_safely(self):
        # Register student 1
        ok, msg = self.db.register_student(
            roll_no="201",
            name="Charlie Brown",
            department="CSE",
            email="charlie@college.edu",
            embedding=self.dummy_emb
        )
        self.assertTrue(ok, msg)

        # Attempt to register different student with duplicate email (different domain casing)
        ok2, msg2 = self.db.register_student(
            roll_no="202",
            name="Dave Clark",
            department="MECH",
            email="charlie@COLLEGE.EDU",  # uppercase casing in domain, local part lowercase
            embedding=self.dummy_emb
        )
        self.assertFalse(ok2, "Duplicate email registration must be rejected.")
        self.assertIn("duplicate registration", msg2.lower())

    def test_allowed_update_succeeds(self):
        # Register student
        ok, msg = self.db.register_student(
            roll_no="301",
            name="Eve White",
            department="CSE",
            email="eve301@college.edu",
            embedding=self.dummy_emb
        )
        self.assertTrue(ok)

        # Update with allow_update=True
        ok2, msg2 = self.db.register_student(
            roll_no="301",
            name="Eve Black",
            department="AI",
            email="eve301@college.edu",
            embedding=self.dummy_emb,
            allow_update=True
        )
        self.assertTrue(ok2, f"Allowed update should succeed: {msg2}")

        student = self.db.get_student_by_roll("301")
        self.assertEqual(student["name"], "Eve Black")
        self.assertEqual(student["department"], "AI")

    # =========================================================================
    # 5. PASSWORD HASHING AND CREDENTIAL SECURITY
    # =========================================================================
    def test_secure_password_hashing(self):
        plain_pass = "SecureAdminPass2026!"
        hash1, salt1 = DatabaseManager._hash_password(plain_pass)

        # Salt must be 32 hex chars (16 bytes random)
        self.assertEqual(len(salt1), 32)
        # Hash must be 64 hex chars (SHA-256)
        self.assertEqual(len(hash1), 64)
        # Plaintext must not match hash
        self.assertNotEqual(plain_pass, hash1)

        # Same password with same salt reproduces identical hash
        hash2, _ = DatabaseManager._hash_password(plain_pass, salt=salt1)
        self.assertEqual(hash1, hash2)

        # Different salt produces different hash
        hash3, salt3 = DatabaseManager._hash_password(plain_pass)
        self.assertNotEqual(salt1, salt3)
        self.assertNotEqual(hash1, hash3)

    # =========================================================================
    # 6. STUDENT RECORD AUDIT AND LEGACY REPORTING
    # =========================================================================
    def test_audit_student_records_identifies_legacy_issues_without_modifying(self):
        # Seed 1 valid student
        self.db.register_student(
            roll_no="501",
            name="Rohit Pathak",
            department="CSE",
            email="rohit501@college.edu",
            embedding=self.dummy_emb
        )

        # Seed 1 legacy student directly in SQLite without email (like legacy records)
        with self.db.get_connection() as conn:
            conn.execute(
                "INSERT INTO students (roll_no, name, department, email, embedding) VALUES (?, ?, ?, ?, ?)",
                ("502", "Legacy Student", "General", "", self.dummy_emb.tobytes())
            )
            conn.commit()

        # Run audit
        audit = self.db.audit_student_records()
        self.assertEqual(audit["total_students"], 2)
        self.assertEqual(audit["valid_count"], 1)
        self.assertEqual(audit["legacy_rejected_count"], 1)

        # Check that legacy student is reported for manual review with reason
        rejected = audit["rejected_legacy_records"][0]
        self.assertEqual(rejected["roll_no"], "502")
        self.assertIn("Email Missing", rejected["review_reasons"][0])

        # Verify that original records are NOT modified or deleted by audit
        all_students = self.db.get_all_students()
        self.assertEqual(len(all_students), 2)
        self.assertEqual(all_students[0]["roll_no"], "501")
        self.assertEqual(all_students[1]["roll_no"], "502")


if __name__ == "__main__":
    unittest.main()
