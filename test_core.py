import os
import sys
import numpy as np
import tempfile
import unittest

# Ensure base directory is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from database.db_manager import DatabaseManager
from core.face_engine import FaceEngine
from core.liveness import LivenessDetector
from config import YUNET_MODEL_PATH, SFACE_MODEL_PATH

class TestAttendanceSystemCore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_db_path = os.path.join(self.temp_dir.name, "test.db")
        self.db = DatabaseManager(self.temp_db_path)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_database_and_security(self):
        # Test admin creation and verification
        self.db.ensure_default_admin("admin", "secret123")
        self.assertTrue(self.db.verify_admin("admin", "secret123"))
        self.assertFalse(self.db.verify_admin("admin", "wrongpass"))

        # Test student registration with 128-d embedding
        dummy_embedding = np.random.randn(128).astype(np.float32)
        dummy_embedding /= np.linalg.norm(dummy_embedding) # Normalize

        ok, msg = self.db.register_student("CS101", "Alice Smith", "Computer Science", "alice@example.com", dummy_embedding)
        self.assertTrue(ok)
        self.assertEqual(self.db.get_student_count(), 1)

        # Retrieve and verify embedding round-trip
        students = self.db.get_all_students()
        self.assertEqual(len(students), 1)
        self.assertEqual(students[0]["roll_no"], "CS101")
        self.assertTrue(np.allclose(students[0]["embedding"], dummy_embedding, atol=1e-5))

        # Test attendance marking
        st_id = students[0]["id"]
        ok, status_msg, info = self.db.mark_attendance(st_id, confidence=0.88, cooldown_minutes=30)
        self.assertTrue(ok)
        self.assertEqual(info["roll_no"], "CS101")

        # Test cooldown deduplication (marking immediately again should fail)
        ok_again, cooldown_msg, _ = self.db.mark_attendance(st_id, confidence=0.90, cooldown_minutes=30)
        self.assertFalse(ok_again)
        self.assertIn("Cooldown active", cooldown_msg)

        # Test stats
        stats = self.db.get_today_stats()
        self.assertEqual(stats["total_students"], 1)
        self.assertEqual(stats["present_today"], 1)
        self.assertEqual(stats["absent_today"], 0)


    def test_face_engine_matching(self):
        engine = FaceEngine(YUNET_MODEL_PATH, SFACE_MODEL_PATH)
        
        # Test feature matching math
        feat_a = np.random.randn(128).astype(np.float32)
        feat_a /= np.linalg.norm(feat_a)

        # Self match should give 1.0
        self_score = engine.compare_faces(feat_a, feat_a)
        self.assertAlmostEqual(self_score, 1.0, places=3)

        # Random vector match should be low
        feat_b = np.random.randn(128).astype(np.float32)
        feat_b /= np.linalg.norm(feat_b)
        rand_score = engine.compare_faces(feat_a, feat_b)
        self.assertLess(rand_score, 0.5)

        # Test identify_face
        students = [{"id": 1, "roll_no": "TEST1", "name": "Bob", "embedding": feat_a}]
        matched, score = engine.identify_face(feat_a, students, threshold=0.60)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["roll_no"], "TEST1")

    def test_liveness_detector(self):
        liveness = LivenessDetector(history_len=6)
        
        # Simulate static landmarks (spoof test)
        static_landmarks = {
            "right_eye": (100, 100), "left_eye": (150, 100),
            "nose": (125, 125), "right_mouth": (110, 150), "left_mouth": (140, 150)
        }
        for _ in range(6):
            is_live, reason, std = liveness.check_temporal_liveness("face_1", static_landmarks)

        self.assertFalse(is_live)
        self.assertIn("Static Spoof", reason)

if __name__ == "__main__":
    unittest.main()

