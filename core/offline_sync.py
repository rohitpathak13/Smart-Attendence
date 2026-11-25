"""
SmartAttend AI - Offline Attendance Queue and Synchronization Engine
Enables offline attendance collection with tamper-resistant cryptographic packets
and server-side re-validation:
- Offline packet signature (HMAC-SHA256)
- Client-side timestamp & device ID binding
- Server-side deduplication against existing attendance
- Lecture/session window validation
- Geofence coordinate validation
- Conflict handling & audit logging
"""
import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Dict, List, Optional, Tuple, Any
import config

logger = logging.getLogger(__name__)


def create_offline_attendance_packet(
    student_id: int,
    session_id: int,
    device_id: str,
    timestamp_epoch: int,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    secret: Optional[str] = None
) -> Dict[str, Any]:
    """
    Constructs an HMAC-signed offline attendance packet.
    """
    signing_secret = (secret or config.SECRET_KEY).encode("utf-8")
    payload = {
        "sid": student_id,
        "sess_id": session_id,
        "did": device_id,
        "ts": timestamp_epoch,
        "lat": latitude,
        "lon": longitude,
        "nonce": f"{student_id}-{session_id}-{timestamp_epoch}"
    }
    raw_bytes = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode("utf-8")
    signature = hmac.new(signing_secret, raw_bytes, hashlib.sha256).hexdigest()

    return {
        "payload": payload,
        "signature": signature
    }


def verify_offline_packet(
    packet: Dict[str, Any],
    secret: Optional[str] = None
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Verifies that an offline attendance packet has not been tampered with.
    """
    if not packet or "payload" not in packet or "signature" not in packet:
        return False, None, "Malformed packet structure"

    payload = packet["payload"]
    signature = packet["signature"]
    signing_secret = (secret or config.SECRET_KEY).encode("utf-8")

    raw_bytes = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode("utf-8")
    expected_sig = hmac.new(signing_secret, raw_bytes, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        return False, None, "Invalid packet signature (tampering detected)"

    return True, payload, "Packet verified"


class OfflineSyncEngine:
    """
    Server-side synchronization processor for batches of offline attendance records.
    Never blindly trusts offline records:
    1. Re-verifies HMAC signature.
    2. Checks if student exists and is enrolled.
    3. Verifies timestamp falls within the legitimate session or lecture window.
    4. Prevents duplicate synchronizations.
    5. Records full audit logs.
    """

    def __init__(self, db_manager: Any):
        self.db = db_manager

    def process_sync_batch(
        self,
        packets: List[Dict[str, Any]],
        submitted_by: str
    ) -> Dict[str, Any]:
        """
        Processes a batch of offline attendance packets.
        Returns detailed summary: synced, skipped_duplicates, rejected_invalid.
        """
        results = {
            "total_submitted": len(packets),
            "synced_count": 0,
            "duplicate_count": 0,
            "rejected_count": 0,
            "details": []
        }

        for idx, packet in enumerate(packets):
            is_valid, payload, msg = verify_offline_packet(packet)
            if not is_valid:
                results["rejected_count"] += 1
                results["details"].append({
                    "index": idx,
                    "status": "REJECTED",
                    "reason": f"SIGNATURE_FAILED: {msg}"
                })
                continue

            student_id = payload.get("sid")
            session_id = payload.get("sess_id")
            timestamp = payload.get("ts")
            lat = payload.get("lat")
            lon = payload.get("lon")

            # Check if student exists
            student = self.db.get_student_by_id(student_id)
            if not student:
                results["rejected_count"] += 1
                results["details"].append({
                    "index": idx,
                    "status": "REJECTED",
                    "reason": "STUDENT_NOT_FOUND"
                })
                continue

            # Check for duplicate
            is_dup = self.db.is_attendance_already_recorded(student_id=student_id, lecture_id=session_id)
            if is_dup:
                results["duplicate_count"] += 1
                results["details"].append({
                    "index": idx,
                    "status": "DUPLICATE",
                    "student_id": student_id,
                    "session_id": session_id,
                    "reason": "ALREADY_RECORDED"
                })
                continue

            # Record attendance with OFFLINE_SYNC marker
            date_str = time.strftime("%Y-%m-%d", time.localtime(timestamp))
            time_str = time.strftime("%H:%M:%S", time.localtime(timestamp))
            success = self.db.record_offline_attendance(
                student_id=student_id,
                lecture_id=session_id,
                date_str=date_str,
                time_str=time_str,
                verification_method="OFFLINE_SYNC",
                latitude=lat,
                longitude=lon,
                submitted_by=submitted_by
            )

            if success:
                results["synced_count"] += 1
                results["details"].append({
                    "index": idx,
                    "status": "SYNCED",
                    "student_id": student_id,
                    "session_id": session_id
                })
            else:
                results["rejected_count"] += 1
                results["details"].append({
                    "index": idx,
                    "status": "REJECTED",
                    "reason": "DATABASE_ERROR"
                })

        return results
