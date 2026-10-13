"""
Unit Tests for Phase 18 (Email), Phase 19 (Student Name), and Phase 20 (Roll Number / Student ID).
"""
import unittest
from core.validators import validate_email, validate_student_name, validate_roll_number

class TestValidators(unittest.TestCase):
    # =========================================================================
    # PHASE 18: EMAIL VALIDATION TESTS
    # =========================================================================
    def test_valid_emails(self):
        # Lowercase alphanumeric local part with valid domain
        valid_cases = [
            "abcd123@example.com",
            "student2026@university.edu",
            "rohit13@college.ac.in",
            "john01@sub.domain.org",
            "12345@domain.com"
        ]
        for email in valid_cases:
            is_valid, norm, msg = validate_email(email)
            self.assertTrue(is_valid, f"Expected '{email}' to be valid. Got error: {msg}")
            self.assertEqual(norm, email.strip().lower())

    def test_rejected_uppercase_in_local_part(self):
        # Requirement: "Abcd123@example.com should be rejected under the requested lowercase-only local-part policy"
        invalid_cases = [
            "Abcd123@example.com",
            "ROHIT@example.com",
            "johnDoe@example.com"
        ]
        for email in invalid_cases:
            is_valid, _, msg = validate_email(email)
            self.assertFalse(is_valid, f"Expected '{email}' with uppercase local part to be rejected.")
            self.assertIn("lowercase", msg.lower())

    def test_rejected_special_chars_in_local_part(self):
        # Requirement: "Special characters in the local part are not allowed"
        invalid_cases = [
            "abcd.123@example.com",
            "abcd_123@example.com",
            "abcd-123@example.com",
            "abcd+test@example.com",
            "abcd#123@example.com"
        ]
        for email in invalid_cases:
            is_valid, _, msg = validate_email(email)
            self.assertFalse(is_valid, f"Expected '{email}' with special chars to be rejected.")

    def test_rejected_invalid_domains_and_suffixes(self):
        # Requirement: "The sample 'abcd@123' is not a conventional valid email address because it does not contain a proper domain name with a suffix."
        invalid_cases = [
            "abcd@123",            # Missing TLD
            "abcd123@",            # Missing domain
            "@example.com",        # Missing local part
            "abcd 123@example.com",# Space in local part
            "abcd123@example .com",# Space in domain
            "abcd123@example",     # Missing TLD suffix
            "abcd123@.com",        # Missing domain label
            "abcd123@example.c",   # TLD too short (single char)
            "",                    # Empty
            None                   # None
        ]
        for email in invalid_cases:
            is_valid, _, msg = validate_email(email)
            self.assertFalse(is_valid, f"Expected '{email}' to be rejected as invalid email structure.")

    def test_institutional_domain_policy(self):
        # Configurable institutional domain check
        inst_domain = "university.edu"
        ok_valid, _, _ = validate_email("student123@university.edu", institutional_domain=inst_domain)
        self.assertTrue(ok_valid)

        ok_sub, _, _ = validate_email("student123@cs.university.edu", institutional_domain=inst_domain)
        self.assertTrue(ok_sub)

        ok_foreign, _, msg = validate_email("student123@other.com", institutional_domain=inst_domain)
        self.assertFalse(ok_foreign)
        self.assertIn("institutional domain", msg)

    # =========================================================================
    # PHASE 19: STUDENT NAME VALIDATION TESTS
    # =========================================================================
    def test_valid_student_names(self):
        # Title Case and ALL UPPERCASE
        valid_cases = [
            ("Rohit", "Rohit"),
            ("Rohit Pathak", "Rohit Pathak"),
            ("ROHIT", "ROHIT"),
            ("ROHIT PATHAK", "ROHIT PATHAK"),
            ("Mary Jane Watson", "Mary Jane Watson"),
            ("ALICE SMITH", "ALICE SMITH"),
            ("O'Connor", "O'Connor"),
            ("Smith-Jones", "Smith-Jones")
        ]
        for name_in, expected_norm in valid_cases:
            is_valid, norm, msg = validate_student_name(name_in)
            self.assertTrue(is_valid, f"Expected '{name_in}' to be valid. Got error: {msg}")
            self.assertEqual(norm, expected_norm)

    def test_rejected_student_names_with_digits(self):
        # Reject digits in names and pure numbers
        invalid_cases = [
            "rohit123",
            "12345",
            "Rohit 2nd",
            "Agent 007",
            "123"
        ]
        for name in invalid_cases:
            is_valid, _, msg = validate_student_name(name)
            self.assertFalse(is_valid, f"Expected '{name}' with digits to be rejected.")
            self.assertIn("digits", msg.lower())

    def test_rejected_mixed_case_student_names(self):
        # Reject arbitrary mixed case (e.g. "rohit PATHAK")
        invalid_cases = [
            "rohit PATHAK",
            "rohit pathak",
            "rohit",
            "RoHiT",
            "ROHIT pathak"
        ]
        for name in invalid_cases:
            is_valid, _, msg = validate_student_name(name)
            self.assertFalse(is_valid, f"Expected '{name}' with improper capitalization to be rejected.")

    def test_rejected_empty_names(self):
        for name in ["", "   ", None]:
            is_valid, _, msg = validate_student_name(name)
            self.assertFalse(is_valid)
            self.assertTrue("empty" in msg.lower() or "required" in msg.lower())

    def test_student_name_admin_override(self):
        # Administrator-approved exception mechanism for legitimate edge-case names
        is_valid, norm, _ = validate_student_name("de la Cruz", allow_admin_override=True)
        self.assertTrue(is_valid)
        self.assertEqual(norm, "de la Cruz")

    # =========================================================================
    # PHASE 20: NUMERIC ROLL NUMBER AND STUDENT ID TESTS
    # =========================================================================
    def test_valid_numeric_roll_numbers(self):
        # Digits 0-9 only, preserve leading zeros
        valid_cases = [
            "12345",
            "20261001",
            "001234",
            "0001",
            "7"
        ]
        for roll in valid_cases:
            is_valid, norm, msg = validate_roll_number(roll, require_numeric=True)
            self.assertTrue(is_valid, f"Expected '{roll}' to be valid numeric roll number. Got error: {msg}")
            # Ensure leading zero is preserved as string
            self.assertEqual(norm, roll)

    def test_rejected_alphabetic_roll_numbers(self):
        # Reject alphabetic characters
        invalid_cases = [
            "AB123",
            "12A45",
            "CS101",
            "RollNo1"
        ]
        for roll in invalid_cases:
            is_valid, _, msg = validate_roll_number(roll, require_numeric=True)
            self.assertFalse(is_valid, f"Expected '{roll}' with alphabetic chars to be rejected.")
            self.assertIn("digits only", msg.lower())

    def test_rejected_punctuation_and_spaces_in_roll_numbers(self):
        # Reject spaces and punctuation
        invalid_cases = [
            "12-345",
            "12 345",
            "12.345",
            "12_345",
            "#123"
        ]
        for roll in invalid_cases:
            is_valid, _, msg = validate_roll_number(roll, require_numeric=True)
            self.assertFalse(is_valid, f"Expected '{roll}' with punctuation/spaces to be rejected.")

    def test_rejected_empty_roll_numbers(self):
        for roll in ["", "   ", None]:
            is_valid, _, msg = validate_roll_number(roll, require_numeric=True)
            self.assertFalse(is_valid)

if __name__ == "__main__":
    unittest.main()
