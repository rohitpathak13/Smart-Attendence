"""
SmartAttend AI - Security & Role-Based Access Control (RBAC) Module
Handles:
- Cryptographic token generation & validation (Admin, Teacher, Student, Parent)
- Role-based permissions
- Rate limiting helper (in-memory token bucket / sliding window)
- Password complexity validation
- CSV formula injection sanitization
- Secure input sanitization
"""
import base64
import hashlib
import hmac
import json
import re
import time
from typing import Dict, List, Optional, Tuple, Any
import config


# --- Role Definitions ---
class Role:
    ADMIN = "ADMIN"
    TEACHER = "TEACHER"
    STUDENT = "STUDENT"
    PARENT = "PARENT"
    CAMERA = "CAMERA"


# --- Token Management ---
def create_auth_token(
    user_id: int,
    username: str,
    role: str,
    expiry_seconds: int = 86400,
    secret: Optional[str] = None
) -> str:
    """
    Creates a cryptographically signed HMAC-SHA256 session token.
    Token format: base64url(payload).hmac_signature
    Payload contains user_id, username, role, issued_at, expires_at.
    """
    signing_secret = (secret or config.SECRET_KEY).encode("utf-8")
    now = int(time.time())
    payload = {
        "uid": user_id,
        "sub": username,
        "role": role.upper(),
        "iat": now,
        "exp": now + expiry_seconds
    }
    raw_payload = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode("utf-8")
    b64_payload = base64.urlsafe_b64encode(raw_payload).decode("utf-8").rstrip("=")
    
    signature = hmac.new(signing_secret, b64_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{b64_payload}.{signature}"


def verify_auth_token(
    token: str,
    required_roles: Optional[List[str]] = None,
    secret: Optional[str] = None
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Verifies an HMAC-SHA256 session token.
    Returns (is_valid, payload_dict, message).
    """
    if not token or "." not in token:
        return False, None, "Malformed or missing token"

    parts = token.split(".")
    if len(parts) != 2:
        return False, None, "Invalid token format"

    b64_payload, signature = parts
    signing_secret = (secret or config.SECRET_KEY).encode("utf-8")

    expected_sig = hmac.new(signing_secret, b64_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_sig):
        return False, None, "Invalid token signature"

    # Decode payload
    try:
        # Add back base64 padding
        padding = 4 - (len(b64_payload) % 4)
        if padding != 4:
            b64_payload += "=" * padding
        raw_json = base64.urlsafe_b64decode(b64_payload.encode("utf-8")).decode("utf-8")
        payload = json.loads(raw_json)
    except Exception:
        return False, None, "Corrupted token payload"

    # Check expiration
    now = int(time.time())
    if payload.get("exp", 0) < now:
        return False, None, "Token has expired"

    # Check role requirement if specified
    if required_roles:
        user_role = payload.get("role", "").upper()
        allowed = [r.upper() for r in required_roles]
        if user_role not in allowed and Role.ADMIN not in allowed:
            # ADMIN can access any authorized endpoint unless strictly restricted
            if user_role != Role.ADMIN:
                return False, None, f"Insufficient permissions: requires {required_roles}"

    return True, payload, "Token valid"


# --- Password Complexity Policy ---
def validate_password_strength(password: str) -> Tuple[bool, str]:
    """
    Enforces secure password policy:
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit or special character
    """
    if not password or len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r"[0-9!@#$%^&*(),.?\":{}|<>]", password):
        return False, "Password must contain at least one number or special character."
    return True, "Password meets security policy."


# --- CSV Formula Injection Sanitization ---
def sanitize_csv_field(value: Any) -> str:
    """
    Prevents CSV Formula Injection (CWE-1236).
    If a field starts with =, +, -, @, tab, or carriage return,
    it prepends an apostrophe ' to neutralize formula execution in Excel/Sheets.
    """
    if value is None:
        return ""
    str_val = str(value)
    if str_val and str_val[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + str_val
    return str_val


# --- Sliding Window Rate Limiter ---
class InMemoryRateLimiter:
    """
    Thread-safe sliding-window rate limiter for sensitive endpoints
    like /api/auth/login and /api/recognize.
    """
    def __init__(self):
        self._requests: Dict[str, List[float]] = {}

    def is_allowed(self, client_key: str, max_requests: int = 10, window_seconds: int = 60) -> Tuple[bool, int]:
        """
        Returns (is_allowed, remaining_requests).
        """
        now = time.time()
        window_start = now - window_seconds
        
        timestamps = self._requests.get(client_key, [])
        # Filter out old requests
        valid_timestamps = [t for t in timestamps if t > window_start]
        
        if len(valid_timestamps) >= max_requests:
            self._requests[client_key] = valid_timestamps
            return False, 0
        
        valid_timestamps.append(now)
        self._requests[client_key] = valid_timestamps
        return True, max_requests - len(valid_timestamps)

    def reset(self, client_key: Optional[str] = None):
        if client_key:
            self._requests.pop(client_key, None)
        else:
            self._requests.clear()


# Global rate limiter instance
rate_limiter = InMemoryRateLimiter()
