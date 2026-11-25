"""
Migration and Student Data Audit Script for DeepVision Attendance System.

This script:
1. Applies required unique constraints and case-insensitive indexes to the database.
2. Audits all existing student records against institutional validation rules:
   - Preserves leading zeros on numeric roll numbers.
   - Enforces name formatting policies (Title Case / UPPERCASE, rejects digits).
   - Validates email structure and lowercase alphanumeric local part.
3. Preserves existing valid student records without rewriting data automatically.
4. Generates a standalone JSON audit report for manual administrative review.
"""
import os
import sys
import json
import sqlite3
from datetime import datetime

# Add root directory to sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import DB_PATH, DATA_DIR
from database.db_manager import DatabaseManager


def run_migration_and_audit(db_path: str = DB_PATH) -> dict:
    print("=" * 70)
    print(" Running Student Registration Migration & Data Audit")
    print(f" Database Path: {db_path}")
    print("=" * 70)

    # 1. Initialize DatabaseManager (ensures table schemas and indexes exist)
    db = DatabaseManager(db_path)

    # 2. Explicitly verify/ensure unique constraints and case-insensitive indexes
    print("[1/3] Ensuring database integrity constraints and indexes...")
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_students_roll_no_unique
        ON students(roll_no);
        """)
        cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_students_email_nocase
        ON students(LOWER(email))
        WHERE email IS NOT NULL AND email != '';
        """)
        conn.commit()
    print("      [OK] Unique indexes on roll_no and LOWER(email) verified.")

    # 3. Perform audit of existing records
    print("[2/3] Auditing existing student records against institutional policies...")
    report_file = os.path.join(DATA_DIR, "legacy_records_audit_report.json")
    results = db.audit_student_records(report_path=report_file)

    # 4. Display findings
    print("[3/3] Audit Results Summary:")
    print(f"      Total Students Audited: {results['total_students']}")
    print(f"      Valid Records Preserved: {results['valid_count']}")
    print(f"      Legacy Records for Review: {results['legacy_rejected_count']}")
    print(f"      Detailed Report Saved to: {report_file}")

    if results["valid_records"]:
        print("\n   [+] Valid Student Records Preserved:")
        for s in results["valid_records"]:
            print(f"       - ID {s['id']}: Roll='{s['roll_no']}', Name='{s['name']}', Email='{s['email']}'")

    if results["rejected_legacy_records"]:
        print("\n   [!] Legacy Records Flagged for Manual Review (NOT Automatically Rewritten):")
        for s in results["rejected_legacy_records"]:
            print(f"       - ID {s['id']}: Roll='{s['roll_no']}', Name='{s['name']}', Email='{s['email']}'")
            for reason in s.get("review_reasons", []):
                print(f"         * {reason}")

    print("\n" + "=" * 70)
    print(" Migration & Audit Complete. All existing records preserved safely.")
    print("=" * 70)
    return results


if __name__ == "__main__":
    run_migration_and_audit()
