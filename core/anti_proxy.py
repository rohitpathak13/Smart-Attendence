"""
SmartAttend AI - Multi-Layer Anti-Proxy Attendance Verification Engine
Coordinates multi-factor physical and biometric presence verification:
1. Face Recognition (YuNet + SFace 128-D cosine similarity)
2. Anti-Spoof Liveness Detection (Laplacian texture variance + temporal motion)
3. Active Session / Lecture Time-window verification
4. Device Geolocation / GPS Geofencing (Haversine formula against campus/classroom)
5. Dynamic Rotating QR Verification (Cryptographic HMAC tokens, one-time nonce)
6. Bluetooth Low Energy (BLE) Beacon Proximity (Optional / classroom specific)
7. Fixed Classroom Camera Authentication
8. Duplicate Attendance Prevention

Verification Outcomes:
- VERIFIED: All required primary factors passed convincingly.
- REJECTED: Definitive spoofing, invalid credentials, or severe rule violation detected.
- PENDING_REVIEW: Borderline signals (e.g. weak GPS accuracy or marginal face score)
  flagged for human instructor review rather than unfair automated punishment.
"""
from dataclasses import dataclass, field
from enum import Enum
import logging
from typing import Dict, List, Optional, Tuple, Any

from core.geofence import haversine_distance
from core.qr_engine import verify_qr_token

logger = logging.getLogger(__name__)


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    PENDING_REVIEW = "PENDING_REVIEW"


class RejectionReason(str, Enum):
    NONE = "NONE"
    FACE_NOT_MATCHED = "FACE_NOT_MATCHED"
    FACE_NOT_DETECTED = "FACE_NOT_DETECTED"
    LIVENESS_FAILED = "LIVENESS_FAILED"
    LIVENESS_STATIC_PHOTO = "LIVENESS_STATIC_PHOTO"
    OUTSIDE_GEOFENCE = "OUTSIDE_GEOFENCE"
    LOCATION_UNAVAILABLE = "LOCATION_UNAVAILABLE"
    LOCATION_ACCURACY_POOR = "LOCATION_ACCURACY_POOR"
    INVALID_QR = "INVALID_QR"
    EXPIRED_QR = "EXPIRED_QR"
    REPLAYED_QR = "REPLAYED_QR"
    INACTIVE_SESSION = "INACTIVE_SESSION"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    DUPLICATE_ATTENDANCE = "DUPLICATE_ATTENDANCE"
    BEACON_MISMATCH = "BEACON_MISMATCH"
    UNAUTHORIZED_CAMERA = "UNAUTHORIZED_CAMERA"
    MULTIPLE_SUSPICIOUS_SIGNALS = "MULTIPLE_SUSPICIOUS_SIGNALS"


@dataclass
class VerificationPolicy:
    """Configurable security policy for attendance sessions."""
    require_face: bool = True
    require_liveness: bool = True
    require_location: bool = True
    require_qr: bool = False
    require_beacon: bool = False
    require_fixed_camera: bool = False
    
    # Thresholds
    min_face_similarity: float = 0.50
    min_face_pending_threshold: float = 0.42  # 0.42 to 0.50 triggers review
    min_liveness_texture_score: float = 25.0
    max_location_accuracy_meters: float = 100.0
    allowed_geofence_buffer_meters: float = 20.0  # Tolerance for GPS jitter


@dataclass
class VerificationResult:
    """Comprehensive result of multi-layer verification."""
    overall_status: VerificationStatus
    primary_reason: RejectionReason
    detail_message: str
    student_id: Optional[int] = None
    student_name: Optional[str] = None
    roll_number: Optional[str] = None
    
    # Layer Breakdown
    face_score: float = 0.0
    face_status: str = "SKIPPED"
    liveness_score: float = 0.0
    liveness_status: str = "SKIPPED"
    location_distance_m: Optional[float] = None
    location_status: str = "SKIPPED"
    qr_status: str = "SKIPPED"
    beacon_status: str = "SKIPPED"
    camera_status: str = "SKIPPED"
    duplicate_status: str = "PASSED"
    
    signals_flagged: List[str] = field(default_factory=list)
    signals_passed: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_status": self.overall_status.value,
            "primary_reason": self.primary_reason.value,
            "detail_message": self.detail_message,
            "student_id": self.student_id,
            "student_name": self.student_name,
            "roll_number": self.roll_number,
            "layers": {
                "face": {"status": self.face_status, "score": round(self.face_score, 4)},
                "liveness": {"status": self.liveness_status, "score": round(self.liveness_score, 2)},
                "location": {"status": self.location_status, "distance_m": round(self.location_distance_m, 2) if self.location_distance_m is not None else None},
                "qr": {"status": self.qr_status},
                "beacon": {"status": self.beacon_status},
                "camera": {"status": self.camera_status},
                "duplicate_check": {"status": self.duplicate_status}
            },
            "signals_flagged": self.signals_flagged,
            "signals_passed": self.signals_passed
        }


class MultiLayerVerificationEngine:
    """
    Evaluates multi-factor evidence against configured verification policy.
    Never relies on GPS alone (GPS can be spoofed).
    Never claims perfect spoof prevention.
    Applies defense-in-depth: combines biometrics + cryptography + proximity.
    """

    def __init__(self, policy: Optional[VerificationPolicy] = None):
        self.policy = policy or VerificationPolicy()

    def evaluate(
        self,
        # Biometric evidence
        face_match: Optional[Dict[str, Any]] = None,
        liveness_data: Optional[Dict[str, Any]] = None,
        # Environmental evidence
        student_coords: Optional[Tuple[float, float]] = None,
        location_accuracy: Optional[float] = None,
        target_coords: Optional[Tuple[float, float]] = None,
        target_radius_m: float = 150.0,
        # Cryptographic / Token evidence
        qr_token_str: Optional[str] = None,
        qr_nonce_consumed_fn: Optional[Any] = None,
        # Hardware / Beacon evidence
        scanned_beacon_uuid: Optional[str] = None,
        expected_beacon_uuid: Optional[str] = None,
        camera_id: Optional[str] = None,
        is_authenticated_camera: bool = False,
        # Duplicate check evidence
        is_already_marked: bool = False,
        # Session validity evidence
        is_session_active: bool = True
    ) -> VerificationResult:
        result = VerificationResult(
            overall_status=VerificationStatus.VERIFIED,
            primary_reason=RejectionReason.NONE,
            detail_message="All verification layers successfully verified."
        )

        # 1. Session Active Check
        if not is_session_active:
            result.overall_status = VerificationStatus.REJECTED
            result.primary_reason = RejectionReason.INACTIVE_SESSION
            result.detail_message = "The attendance session is inactive, ended, or outside class hours."
            result.signals_flagged.append("INACTIVE_SESSION")
            return result

        # 2. Duplicate Attendance Check
        if is_already_marked:
            result.overall_status = VerificationStatus.REJECTED
            result.primary_reason = RejectionReason.DUPLICATE_ATTENDANCE
            result.detail_message = "Attendance has already been recorded for this student in this session/lecture."
            result.duplicate_status = "FAILED"
            result.signals_flagged.append("DUPLICATE_ATTENDANCE")
            return result
        result.duplicate_status = "PASSED"

        suspicious_signals = []

        # 3. Dynamic QR Verification (if required)
        if self.policy.require_qr:
            if not qr_token_str:
                result.overall_status = VerificationStatus.REJECTED
                result.primary_reason = RejectionReason.INVALID_QR
                result.detail_message = "Dynamic classroom QR token is required but was not provided."
                result.qr_status = "MISSING"
                return result

            is_valid, payload, qr_msg = verify_qr_token(qr_token_str)
            if not is_valid:
                result.overall_status = VerificationStatus.REJECTED
                if "EXPIRED" in qr_msg:
                    result.primary_reason = RejectionReason.EXPIRED_QR
                    result.detail_message = "The QR code has expired. Please scan the current live QR code."
                else:
                    result.primary_reason = RejectionReason.INVALID_QR
                    result.detail_message = f"Invalid QR token: {qr_msg}"
                result.qr_status = "FAILED"
                return result

            # Check if nonce was already consumed (one-time replay prevention)
            if qr_nonce_consumed_fn and callable(qr_nonce_consumed_fn):
                nonce = payload.get("nonce")
                if qr_nonce_consumed_fn(nonce):
                    result.overall_status = VerificationStatus.REJECTED
                    result.primary_reason = RejectionReason.REPLAYED_QR
                    result.detail_message = "This QR token has already been consumed. Replay attack prevented."
                    result.qr_status = "REPLAYED"
                    return result

            result.qr_status = "PASSED"
            result.signals_passed.append("DYNAMIC_QR")

        # 4. GPS Geofencing Verification (if required)
        if self.policy.require_location:
            if not student_coords or None in student_coords:
                # Location unavailable / permission denied
                # Mark as PENDING_REVIEW rather than outright rejection to allow manual verification
                suspicious_signals.append("LOCATION_UNAVAILABLE")
                result.location_status = "UNAVAILABLE"
            elif not target_coords or None in target_coords:
                # Target classroom/campus not configured
                result.location_status = "UNCONFIGURED"
            else:
                s_lat, s_lon = student_coords
                t_lat, t_lon = target_coords
                dist = haversine_distance(s_lat, s_lon, t_lat, t_lon)
                result.location_distance_m = dist

                # Accuracy check
                if location_accuracy is not None and location_accuracy > self.policy.max_location_accuracy_meters:
                    suspicious_signals.append("LOCATION_ACCURACY_POOR")
                    result.location_status = "POOR_ACCURACY"
                elif dist > (target_radius_m + self.policy.allowed_geofence_buffer_meters):
                    # Definitively outside radius
                    suspicious_signals.append("OUTSIDE_GEOFENCE")
                    result.location_status = "OUTSIDE"
                else:
                    result.location_status = "INSIDE"
                    result.signals_passed.append("GEOFENCE")

        # 5. Fixed Camera Check (if required by policy)
        if self.policy.require_fixed_camera:
            if not camera_id or not is_authenticated_camera:
                result.overall_status = VerificationStatus.REJECTED
                result.primary_reason = RejectionReason.UNAUTHORIZED_CAMERA
                result.detail_message = "Attendance must originate from an authenticated classroom camera."
                result.camera_status = "UNAUTHORIZED"
                return result
            result.camera_status = "AUTHENTICATED"
            result.signals_passed.append("FIXED_CAMERA")

        # 6. BLE Beacon Check (if required by policy)
        if self.policy.require_beacon:
            if not scanned_beacon_uuid or scanned_beacon_uuid != expected_beacon_uuid:
                suspicious_signals.append("BEACON_MISMATCH")
                result.beacon_status = "MISMATCH"
            else:
                result.beacon_status = "VERIFIED"
                result.signals_passed.append("BLE_BEACON")

        # 7. Face Recognition Verification (if required)
        if self.policy.require_face:
            if not face_match or not face_match.get("matched"):
                result.overall_status = VerificationStatus.REJECTED
                result.primary_reason = RejectionReason.FACE_NOT_MATCHED
                result.detail_message = "Face not recognized. Biometric identity could not be verified."
                result.face_status = "NOT_MATCHED"
                return result

            score = face_match.get("similarity", 0.0)
            result.face_score = score
            result.student_id = face_match.get("student_id")
            result.student_name = face_match.get("name")
            result.roll_number = face_match.get("roll_number")

            if score < self.policy.min_face_pending_threshold:
                result.overall_status = VerificationStatus.REJECTED
                result.primary_reason = RejectionReason.FACE_NOT_MATCHED
                result.detail_message = f"Face similarity score {score:.2f} is below minimum threshold {self.policy.min_face_pending_threshold:.2f}."
                result.face_status = "REJECTED_LOW_SIMILARITY"
                return result
            elif score < self.policy.min_face_similarity:
                # Borderline match: queue for review
                suspicious_signals.append("MARGINAL_FACE_SIMILARITY")
                result.face_status = "MARGINAL"
            else:
                result.face_status = "VERIFIED"
                result.signals_passed.append("FACE_RECOGNITION")

        # 8. Liveness Detection Verification (if required)
        if self.policy.require_liveness:
            if not liveness_data:
                suspicious_signals.append("LIVENESS_MISSING")
                result.liveness_status = "MISSING"
            else:
                is_live = liveness_data.get("is_live", False)
                tex_score = liveness_data.get("texture_score", 0.0)
                result.liveness_score = tex_score

                if not is_live:
                    if liveness_data.get("reason") == "STATIC_IMAGE":
                        result.overall_status = VerificationStatus.REJECTED
                        result.primary_reason = RejectionReason.LIVENESS_STATIC_PHOTO
                        result.detail_message = "Spoof detected: Static image or replayed video detected."
                        result.liveness_status = "SPOOF_DETECTED"
                        return result
                    else:
                        suspicious_signals.append("LIVENESS_SUSPICIOUS")
                        result.liveness_status = "SUSPICIOUS"
                else:
                    result.liveness_status = "PASSED"
                    result.signals_passed.append("LIVENESS")

        # --- Multi-Signal Outcome Decision Matrix ---
        result.signals_flagged = suspicious_signals

        if not suspicious_signals:
            result.overall_status = VerificationStatus.VERIFIED
            result.primary_reason = RejectionReason.NONE
            result.detail_message = "All verification factors successfully confirmed."
            return result

        # Severe definitive failures:
        if "OUTSIDE_GEOFENCE" in suspicious_signals and ("MARGINAL_FACE_SIMILARITY" in suspicious_signals or "LIVENESS_SUSPICIOUS" in suspicious_signals):
            result.overall_status = VerificationStatus.REJECTED
            result.primary_reason = RejectionReason.MULTIPLE_SUSPICIOUS_SIGNALS
            result.detail_message = "Attendance rejected: Multiple conflicting presence and identity signals."
            return result

        if "OUTSIDE_GEOFENCE" in suspicious_signals:
            result.overall_status = VerificationStatus.REJECTED
            result.primary_reason = RejectionReason.OUTSIDE_GEOFENCE
            result.detail_message = f"Location verification failed: Device is outside classroom boundary ({result.location_distance_m:.1f}m away)."
            return result

        # If only a single ambiguous signal exists (e.g. GPS unavailable or weak accuracy in indoor room):
        # Escalate to PENDING_REVIEW rather than rejecting to prevent punishing legitimate students.
        result.overall_status = VerificationStatus.PENDING_REVIEW
        if "LOCATION_UNAVAILABLE" in suspicious_signals:
            result.primary_reason = RejectionReason.LOCATION_UNAVAILABLE
            result.detail_message = "Location could not be determined. Flagged for instructor manual verification."
        elif "LOCATION_ACCURACY_POOR" in suspicious_signals:
            result.primary_reason = RejectionReason.LOCATION_ACCURACY_POOR
            result.detail_message = f"Location accuracy ({location_accuracy:.1f}m) is poor. Flagged for instructor review."
        elif "MARGINAL_FACE_SIMILARITY" in suspicious_signals:
            result.primary_reason = RejectionReason.FACE_NOT_MATCHED
            result.detail_message = f"Face similarity ({result.face_score:.2f}) was borderline. Flagged for instructor review."
        else:
            result.primary_reason = RejectionReason.MULTIPLE_SUSPICIOUS_SIGNALS
            result.detail_message = f"Suspicious signals detected: {', '.join(suspicious_signals)}. Flagged for manual review."

        return result
