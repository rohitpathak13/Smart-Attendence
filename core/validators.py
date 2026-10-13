"""
Validation module for student registration and identity verification.
Enforces institutional standards for:
- Email addresses (lowercase alphanumeric local part, valid domain structure)
- Student names (Title Case or UPPERCASE, no digits, no arbitrary mixed case)
- Roll numbers / Student IDs (digits 0-9 only, preserves leading zeros)
"""
import re
from typing import Tuple, Optional

# --- Email Validation ---
# Local part: ONLY lowercase letters a-z and digits 0-9. No uppercase, no spaces, no symbols.
LOCAL_PART_PATTERN = re.compile(r"^[a-z0-9]+$")

# Domain label: letters, digits, hyphens (cannot start or end with hyphen)
DOMAIN_LABEL_PATTERN = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")

# Top Level Domain: at least 2 alphabetic characters
TLD_PATTERN = re.compile(r"^[a-zA-Z]{2,63}$")

def validate_email(
    email: Optional[str],
    institutional_domain: Optional[str] = None
) -> Tuple[bool, str, str]:
    """
    Validates a student email address according to institutional policy:
    1. Normalizes by trimming whitespace.
    2. Local part MUST be lowercase alphanumeric (a-z, 0-9 only).
       Uppercase letters are rejected.
       Special characters (+, ., _, -) are rejected unless explicitly allowed.
    3. Requires a valid domain structure with proper TLD (e.g. domain.tld).
       Rejects inputs like 'abcd@123' (missing valid domain suffix).
    4. If institutional_domain is provided, checks domain matches policy.

    Returns:
        (is_valid, normalized_email, error_message)
    """
    if email is None:
        return False, "", "Email address is required."

    normalized = email.strip()
    if not normalized:
        return False, "", "Email address cannot be empty."

    if " " in normalized:
        return False, normalized, "Email address cannot contain spaces."

    if "@" not in normalized:
        return False, normalized, "Email address must contain an '@' symbol."

    parts = normalized.split("@")
    if len(parts) != 2:
        return False, normalized, "Email address must contain exactly one '@' symbol."

    local_part, domain_part = parts

    if not local_part:
        return False, normalized, "Email local part (before '@') cannot be empty."

    if not domain_part:
        return False, normalized, "Email domain part (after '@') cannot be empty."

    # Validate local part strictly
    if not LOCAL_PART_PATTERN.match(local_part):
        if any(c.isupper() for c in local_part):
            return False, normalized, (
                "Email local part must be strictly lowercase. "
                "Uppercase characters are not permitted."
            )
        return False, normalized, (
            "Email local part must contain only lowercase letters (a-z) and digits (0-9). "
            "Special characters and symbols are not permitted."
        )

    # Validate domain part
    domain_labels = domain_part.split(".")
    if len(domain_labels) < 2:
        return False, normalized, (
            f"Invalid domain '{domain_part}'. Domain must include a valid name and suffix (e.g. 'example.com')."
        )

    for label in domain_labels[:-1]:
        if not label or not DOMAIN_LABEL_PATTERN.match(label):
            return False, normalized, f"Invalid domain label '{label}' in email domain."

    tld = domain_labels[-1]
    if not TLD_PATTERN.match(tld):
        return False, normalized, (
            f"Invalid top-level domain '.{tld}'. Top-level domain must contain at least 2 letters."
        )

    # Optional institutional domain check
    if institutional_domain:
        req_domain = institutional_domain.strip().lower().lstrip("@")
        if req_domain:
            actual_domain = domain_part.lower()
            if actual_domain != req_domain and not actual_domain.endswith("." + req_domain):
                return False, normalized, (
                    f"Email must belong to the authorized institutional domain (@{req_domain})."
                )

    # Return normalized email (local part lowercase + domain lowercase)
    final_email = f"{local_part}@{domain_part.lower()}"
    return True, final_email, "Email is valid."


# --- Student Name Validation ---
# Supports Title Case (e.g., "Rohit", "Rohit Pathak") and ALL UPPERCASE (e.g., "ROHIT", "ROHIT PATHAK")
# Also supports legitimate hyphenated and apostrophe name parts (e.g. "O'Connor", "Smith-Jones")

def _is_valid_part(part: str, mode: str) -> bool:
    """Checks if a name component conforms to Title Case or UPPERCASE."""
    if not part:
        return False
    # Check for digits
    if any(c.isdigit() for c in part):
        return False

    # Handle hyphenated parts (e.g. Mary-Jane)
    subparts = part.split("-")
    for sp in subparts:
        # Handle apostrophes (e.g. O'Connor)
        apostrophe_subparts = sp.split("'")
        for asp in apostrophe_subparts:
            if not asp.isalpha():
                return False
            if mode == "UPPER":
                if not asp.isupper():
                    return False
            elif mode == "TITLE":
                if not (asp[0].isupper() and (len(asp) == 1 or asp[1:].islower())):
                    return False
    return True

def validate_student_name(
    name: Optional[str],
    allow_admin_override: bool = False
) -> Tuple[bool, str, str]:
    """
    Validates student name format according to institutional policy:
    1. Trims leading and trailing whitespace.
    2. Rejects empty names.
    3. Rejects names containing digits or numbers only.
    4. Supports two standard institutional formats:
       - Title Case: First letter uppercase, remaining letters lowercase for every name part.
         (e.g., 'Rohit', 'Rohit Pathak')
       - All Uppercase: Entire name in capital letters.
         (e.g., 'ROHIT', 'ROHIT PATHAK')
    5. Rejects arbitrary mixed-case formatting (e.g. 'rohit PATHAK', 'rohit123', '12345').
    6. Preserves legitimate multi-part names, hyphens, and apostrophes.
    7. Supports allow_admin_override for exceptional legitimate legal naming conventions.

    Returns:
        (is_valid, normalized_name, error_message)
    """
    if name is None:
        return False, "", "Student name is required."

    # Trim leading and trailing whitespace; collapse internal multiple spaces
    normalized = " ".join(name.strip().split())
    if not normalized:
        return False, "", "Student name cannot be empty."

    # Reject any digits
    if any(c.isdigit() for c in normalized):
        return False, normalized, "Student name cannot contain digits or numbers."

    if allow_admin_override:
        return True, normalized, "Student name accepted under administrator override."

    parts = normalized.split(" ")

    # Check if ALL parts are ALL UPPERCASE
    all_upper = all(_is_valid_part(p, "UPPER") for p in parts)
    if all_upper:
        return True, normalized, "Student name is valid (UPPERCASE format)."

    # Check if ALL parts are Title Case
    all_title = all(_is_valid_part(p, "TITLE") for p in parts)
    if all_title:
        return True, normalized, "Student name is valid (Title Case format)."

    # If mixed case across parts (e.g. "rohit PATHAK" or "rohit")
    has_lowercase_start = any(p[0].islower() for p in parts if p)
    if has_lowercase_start:
        return False, normalized, (
            "Invalid name capitalization: Each word must start with a capital letter "
            "(e.g., 'Rohit Pathak') or the entire name must be in UPPERCASE (e.g., 'ROHIT PATHAK')."
        )

    return False, normalized, (
        "Invalid name formatting: Name must follow Title Case (e.g., 'Rohit Pathak') "
        "or UPPERCASE (e.g., 'ROHIT PATHAK'). Inconsistent mixed-case is not allowed."
    )


# --- Numeric Roll Number / Student ID Validation ---
NUMERIC_ROLL_PATTERN = re.compile(r"^\d+$")

def validate_roll_number(
    roll_no: Optional[str],
    require_numeric: bool = True
) -> Tuple[bool, str, str]:
    """
    Validates student roll number / ID:
    1. Preserves leading zeros (stored as string, NEVER converted to int).
    2. Allows digits 0-9 only when require_numeric is True.
    3. Rejects alphabetic characters ('AB123', '12A45').
    4. Rejects spaces and punctuation ('12-345', '12 345').
    5. Rejects empty values.

    Returns:
        (is_valid, normalized_roll_no, error_message)
    """
    if roll_no is None:
        return False, "", "Roll number / Student ID is required."

    normalized = str(roll_no).strip()
    if not normalized:
        return False, "", "Roll number / Student ID cannot be empty."

    if require_numeric:
        if not NUMERIC_ROLL_PATTERN.match(normalized):
            if any(c.isalpha() for c in normalized):
                return False, normalized, (
                    "Roll number must contain digits only (0-9). "
                    "Alphabetic characters are not permitted."
                )
            if " " in normalized:
                return False, normalized, "Roll number cannot contain spaces."
            return False, normalized, (
                "Roll number must contain digits only (0-9). "
                "Special characters, hyphens, and symbols are not permitted."
            )

    return True, normalized, "Roll number is valid."
