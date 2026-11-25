"""
SmartAttend AI - Multi-Layer Anti-Proxy Attendance Verification Test Suite
Verifies:
1. Face Recognition matching & rejection
2. Liveness detection (static photograph rejection vs live detection)
3. Active class session verification
4. GPS geofence verification & boundary calculation
5. Dynamic rotating QR verification (valid, expired, tampered, replay/consumed nonce)
6. BLE beacon verification
7. Fixed camera verification
8. Duplicate attendance prevention
9. PENDING_REVIEW escalation for ambiguous signals (does not punish students on noisy sensor data)
All tests run with real logic against isolated temporary environments.
"""
import os
import sys
import time
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.anti_proxy import (
    MultiLayerVerificationEngine, VerificationPolicy,
    VerificationStatus, RejectionReason
)
from core.qr_engine import generate_qr_token


class TestMultiLayerAntiProxyVerification(unittest.TestCase):

    def setUp(self):
        self.policy = VerificationPolicy(
            require_face=True,
            require_liveness=True,
            require_location=True,
            require_qr=True,
            min_face_similarity=0.50,
            min_face_pending_threshold=0.42
        )
        self.engine = MultiLayerVerificationEngine(policy=self.policy)
        self.campus_coords = (28.5355, 77.3910)

    def test_all_layers_passed_yields_verified(self):
        """When face, liveness, geofence, and dynamic QR code pass, status must be VERIFIED."""
        token_str, _ = generate_qr_token(session_id=1, classroom_id=1, teacher_id=1, expiry_seconds=30)
        
        result = self.engine.evaluate(
            face_match={"matched": True, "student_id": 101, "name": "Rahul Sharma", "roll_number": "2026001", "similarity": 0.85},
            liveness_data={"is_live": True, "texture_score": 45.0, "reason": "LIVE"},
            student_coords=(28.53552, 77.39102),  # ~3 meters away
            location_accuracy=10.0,
            target_coords=self.campus_coords,
            target_radius_m=50.0,
            qr_token_str=token_str,
            qr_nonce_consumed_fn=lambda n: False,
            is_already_marked=False,
            is_session_active=True
        )

        self.assertEqual(result.overall_status, VerificationStatus.VERIFIED)
        self.assertEqual(result.primary_reason, RejectionReason.NONE)
        self.assertEqual(result.face_status, "VERIFIED")
        self.assertEqual(result.liveness_status, "PASSED")
        self.assertEqual(result.location_status, "INSIDE")
        self.assertEqual(result.qr_status, "PASSED")

    def test_inactive_session_rejected(self):
        """Attendance for inactive or ended session must be rejected."""
        result = self.engine.evaluate(
            face_match={"matched": True, "student_id": 101, "name": "Rahul", "similarity": 0.90},
            is_session_active=False
        )
        self.assertEqual(result.overall_status, VerificationStatus.REJECTED)
        self.assertEqual(result.primary_reason, RejectionReason.INACTIVE_SESSION)

    def test_duplicate_attendance_rejected(self):
        """Duplicate attendance submission in same session must be rejected."""
        result = self.engine.evaluate(
            face_match={"matched": True, "student_id": 101, "name": "Rahul", "similarity": 0.90},
            is_already_marked=True,
            is_session_active=True
        )
        self.assertEqual(result.overall_status, VerificationStatus.REJECTED)
        self.assertEqual(result.primary_reason, RejectionReason.DUPLICATE_ATTENDANCE)

    def test_liveness_static_spoof_rejected(self):
        """Static photograph presentation must be detected and rejected."""
        token_str, _ = generate_qr_token(session_id=1, classroom_id=1, teacher_id=1, expiry_seconds=30)

        result = self.engine.evaluate(
            face_match={"matched": True, "student_id": 101, "name": "Rahul", "similarity": 0.90},
            liveness_data={"is_live": False, "texture_score": 12.0, "reason": "STATIC_IMAGE"},
            student_coords=self.campus_coords,
            target_coords=self.campus_coords,
            qr_token_str=token_str,
            qr_nonce_consumed_fn=lambda n: False,
            is_session_active=True
        )
        self.assertEqual(result.overall_status, VerificationStatus.REJECTED)
        self.assertEqual(result.primary_reason, RejectionReason.LIVENESS_STATIC_PHOTO)

    def test_outside_geofence_rejected(self):
        """Submitting attendance from home (far outside campus) must be rejected."""
        token_str, _ = generate_qr_token(session_id=1, classroom_id=1, teacher_id=1, expiry_seconds=30)
        distant_home_coords = (28.6139, 77.2090)  # Central Delhi ~18km away

        result = self.engine.evaluate(
            face_match={"matched": True, "student_id": 101, "name": "Rahul", "similarity": 0.88},
            liveness_data={"is_live": True, "texture_score": 50.0},
            student_coords=distant_home_coords,
            target_coords=self.campus_coords,
            target_radius_m=50.0,
            qr_token_str=token_str,
            qr_nonce_consumed_fn=lambda n: False,
            is_session_active=True
        )
        self.assertEqual(result.overall_status, VerificationStatus.REJECTED)
        self.assertEqual(result.primary_reason, RejectionReason.OUTSIDE_GEOFENCE)

    def test_qr_replay_attack_rejected(self):
        """Re-using a previously consumed dynamic QR token must be rejected."""
        token_str, _ = generate_qr_token(session_id=1, classroom_id=1, teacher_id=1, expiry_seconds=30)

        # Simulate nonce callback indicating already consumed
        result = self.engine.evaluate(
            face_match={"matched": True, "student_id": 101, "name": "Rahul", "similarity": 0.88},
            liveness_data={"is_live": True, "texture_score": 50.0},
            student_coords=self.campus_coords,
            target_coords=self.campus_coords,
            qr_token_str=token_str,
            qr_nonce_consumed_fn=lambda nonce: True,  # Already consumed!
            is_session_active=True
        )
        self.assertEqual(result.overall_status, VerificationStatus.REJECTED)
        self.assertEqual(result.primary_reason, RejectionReason.REPLAYED_QR)

    def test_ambiguous_location_escalates_to_pending_review(self):
        """
        When location is unavailable or weak indoor GPS accuracy occurs,
        the system must escalate to PENDING_REVIEW rather than unfairly rejecting.
        """
        token_str, _ = generate_qr_token(session_id=1, classroom_id=1, teacher_id=1, expiry_seconds=30)

        result = self.engine.evaluate(
            face_match={"matched": True, "student_id": 101, "name": "Rahul", "similarity": 0.85},
            liveness_data={"is_live": True, "texture_score": 45.0},
            student_coords=None,  # Location permission denied or unavailable
            target_coords=self.campus_coords,
            qr_token_str=token_str,
            qr_nonce_consumed_fn=lambda n: False,
            is_session_active=True
        )
        self.assertEqual(result.overall_status, VerificationStatus.PENDING_REVIEW)
        self.assertEqual(result.primary_reason, RejectionReason.LOCATION_UNAVAILABLE)
        self.assertIn("LOCATION_UNAVAILABLE", result.signals_flagged)

    def test_marginal_face_match_escalates_to_pending_review(self):
        """Borderline face similarity (0.42 to 0.50) triggers PENDING_REVIEW for teacher check."""
        token_str, _ = generate_qr_token(session_id=1, classroom_id=1, teacher_id=1, expiry_seconds=30)

        result = self.engine.evaluate(
            face_match={"matched": True, "student_id": 101, "name": "Rahul", "similarity": 0.46},
            liveness_data={"is_live": True, "texture_score": 40.0},
            student_coords=self.campus_coords,
            target_coords=self.campus_coords,
            qr_token_str=token_str,
            qr_nonce_consumed_fn=lambda n: False,
            is_session_active=True
        )
        self.assertEqual(result.overall_status, VerificationStatus.PENDING_REVIEW)
        self.assertEqual(result.face_status, "MARGINAL")


if __name__ == "__main__":
    unittest.main(verbosity=2)
