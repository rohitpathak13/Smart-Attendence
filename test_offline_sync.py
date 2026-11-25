"""
SmartAttend AI - Offline Attendance Synchronization Test Suite
Verifies:
1. Construction of HMAC-signed offline attendance packets
2. Packet signature verification and tamper detection
3. Server-side batch processing
4. Nonce deduplication & duplicate attendance rejection
5. Unknown student rejection
"""
import os
import sys
import tempfile
import time
import unittest
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from database.db_manager import DatabaseManager
from core.offline_sync import (
    OfflineSyncEngine, create_offline_attendance_packet, verify_offline_packet
)


class TestOfflineSync(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_sync.db")
        self.db = DatabaseManager(self.db_path)
        self.sync_engine = OfflineSyncEngine(self.db)

        # Register a valid student
        dummy_emb = np.random.randn(128).astype(np.float32)
        self.db.register_student("2026001", "Rohan Gupta", "CS", "rohan@college.edu", dummy_emb)
        students = self.db.get_all_students()
        self.student_id = students[0]["id"]

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_offline_packet_signing_and_verification(self):
        """Offline packet signs cleanly and verifies with valid signature."""
        now = int(time.time())
        packet = create_offline_attendance_packet(
            student_id=self.student_id,
            session_id=1,
            device_id="KIOSK-ROOM-101",
            timestamp_epoch=now,
            latitude=28.5355,
            longitude=77.3910
        )
        is_valid, payload, msg = verify_offline_packet(packet)
        self.assertTrue(is_valid)
        self.assertEqual(payload["sid"], self.student_id)
        self.assertEqual(payload["did"], "KIOSK-ROOM-101")

    def test_tampered_offline_packet_rejected(self):
        """Tampered payload must fail cryptographic signature check."""
        now = int(time.time())
        packet = create_offline_attendance_packet(
            student_id=self.student_id,
            session_id=1,
            device_id="KIOSK-101",
            timestamp_epoch=now
        )
        # Maliciously change student_id in payload
        packet["payload"]["sid"] = 9999
        is_valid, _, msg = verify_offline_packet(packet)
        self.assertFalse(is_valid)
        self.assertIn("Invalid packet signature", msg)

    def test_batch_sync_processing(self):
        """Sync engine ingests valid packets, skips duplicates, and rejects bad packets."""
        now = int(time.time())
        valid_packet = create_offline_attendance_packet(
            student_id=self.student_id,
            session_id=10,
            device_id="KIOSK-101",
            timestamp_epoch=now
        )
        invalid_student_packet = create_offline_attendance_packet(
            student_id=99999,  # Non-existent student
            session_id=10,
            device_id="KIOSK-101",
            timestamp_epoch=now
        )

        batch = [valid_packet, invalid_student_packet]
        results = self.sync_engine.process_sync_batch(batch, submitted_by="OFFLINE_TEST")

        self.assertEqual(results["total_submitted"], 2)
        self.assertEqual(results["synced_count"], 1)
        self.assertEqual(results["rejected_count"], 1)

        # Re-submitting the same batch should identify the first packet as a duplicate
        results2 = self.sync_engine.process_sync_batch([valid_packet], submitted_by="OFFLINE_TEST")
        self.assertEqual(results2["duplicate_count"], 1)
        self.assertEqual(results2["synced_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
