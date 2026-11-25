"""
SmartAttend AI — Dynamic QR Token Engine
Implements cryptographically secure, time-bound, one-time-use QR tokens for attendance.

Security Design:
- Tokens signed with HMAC-SHA256 using server SECRET_KEY.
- Token payload includes: session_id, classroom_id, issued_at, expiry, nonce (UUID4).
- Tokens consumed server-side on first use (one-time use).
- Expired tokens are ALWAYS rejected, regardless of signature validity.
- Replay attacks prevented by nonce tracking in database.
- Screenshots cannot be reused — token expires in configurable seconds (default 30s).
- Tokens bound to a specific attendance_session — cross-session use rejected.

Limitations:
- QR codes CAN be photographed and used within the expiry window.
- For highest security, combine QR with face recognition + GPS.
- Never treat QR as the sole proof of presence.
"""
import hmac
import hashlib
import json
import os
import sys
import time
import uuid
import base64
from typing import Tuple, Optional, Dict, Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    from config import SECRET_KEY, QR_TOKEN_EXPIRY_SECONDS
except ImportError:
    SECRET_KEY = "dev-fallback-key"
    QR_TOKEN_EXPIRY_SECONDS = 30


def _sign_payload(payload_str: str, secret: str) -> str:
    """HMAC-SHA256 signature of a string payload."""
    return hmac.new(
        secret.encode("utf-8"),
        payload_str.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def generate_qr_token(
    session_id: int,
    classroom_id: Optional[int],
    teacher_id: int,
    expiry_seconds: Optional[int] = None,
    secret: Optional[str] = None
) -> Tuple[str, Dict[str, Any]]:
    """
    Generates a cryptographically signed QR token.

    Returns:
        (token_string, payload_dict)

    Token format: base64url(json_payload).signature

    The token_string is what gets encoded into the QR image.
    Store the payload['nonce'] in the database to prevent replay.
    """
    _secret = secret or SECRET_KEY
    _expiry = expiry_seconds if expiry_seconds is not None else QR_TOKEN_EXPIRY_SECONDS

    issued_at = int(time.time())
    expires_at = issued_at + _expiry
    nonce = str(uuid.uuid4())

    payload = {
        "sid": session_id,            # attendance session ID
        "cid": classroom_id,          # classroom ID (None = no room restriction)
        "tid": teacher_id,            # teacher ID who generated it
        "iat": issued_at,             # issued-at timestamp
        "exp": expires_at,            # expiry timestamp
        "nonce": nonce,               # one-time nonce (stored server-side after use)
        "v": 1                        # token version
    }

    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("utf-8")
    signature = _sign_payload(payload_b64, _secret)

    token_string = f"{payload_b64}.{signature}"
    return token_string, payload


def verify_qr_token(
    token_string: str,
    secret: Optional[str] = None
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Verifies a QR token string:
    1. Checks format validity.
    2. Verifies HMAC-SHA256 signature (constant-time comparison).
    3. Checks expiry.

    Does NOT check one-time use — that must be done by the caller (database nonce check).

    Returns:
        (is_valid, payload_dict_or_None, error_message)
    """
    _secret = secret or SECRET_KEY

    if not token_string or "." not in token_string:
        return False, None, "INVALID_QR: Malformed token format."

    parts = token_string.rsplit(".", 1)
    if len(parts) != 2:
        return False, None, "INVALID_QR: Malformed token (missing signature)."

    payload_b64, received_sig = parts

    # Verify signature (constant-time to prevent timing attacks)
    expected_sig = _sign_payload(payload_b64, _secret)
    if not hmac.compare_digest(expected_sig, received_sig):
        return False, None, "INVALID_QR: Token signature verification failed."

    # Decode payload
    try:
        payload_json = base64.urlsafe_b64decode(payload_b64.encode("utf-8") + b"==").decode("utf-8")
        payload = json.loads(payload_json)
    except Exception:
        return False, None, "INVALID_QR: Failed to decode token payload."

    # Check required fields
    required_fields = ["sid", "tid", "iat", "exp", "nonce", "v"]
    for field in required_fields:
        if field not in payload:
            return False, None, f"INVALID_QR: Missing required field '{field}'."

    # Check expiry
    now = int(time.time())
    if now > payload["exp"]:
        seconds_expired = now - payload["exp"]
        return False, payload, f"EXPIRED_QR: Token expired {seconds_expired}s ago. QR codes are single-use and expire after {QR_TOKEN_EXPIRY_SECONDS}s."

    # Check issued-at is not in the future (clock skew tolerance: 10s)
    if payload["iat"] > now + 10:
        return False, payload, "INVALID_QR: Token issued in the future (clock skew detected)."

    return True, payload, "QR token is valid."


def get_token_time_remaining(token_string: str, secret: Optional[str] = None) -> Optional[int]:
    """Returns seconds remaining until token expiry, or None if already expired/invalid."""
    is_valid, payload, _ = verify_qr_token(token_string, secret)
    if not is_valid or payload is None:
        return None
    remaining = payload.get("exp", 0) - int(time.time())
    return max(0, remaining)
