"""
SmartAttend AI — Central Configuration
Loads all settings from environment variables.
NEVER hardcode secrets in this file — use a .env file for local development.
"""
import os
import sys

# Load environment variables from .env file if available (local dev only)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============================================================
# BASE DIRECTORIES
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.environ.get("MODELS_DIR", os.path.join(BASE_DIR, "models"))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
EXPORTS_DIR = os.environ.get("EXPORTS_DIR", os.path.join(BASE_DIR, "exports"))

# Ensure required directories exist
for folder in [MODELS_DIR, DATA_DIR, EXPORTS_DIR]:
    os.makedirs(folder, exist_ok=True)

# ============================================================
# DATABASE
# ============================================================
DB_PATH = os.environ.get("DB_PATH", os.path.join(DATA_DIR, "attendance_system.db"))

# ============================================================
# SERVER
# ============================================================
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", 8000))

# CORS — Restrict to configured origins in production
# Format: comma-separated list, e.g., "https://myapp.railway.app,http://localhost:3000"
# Default "*" is only acceptable in local development. Set ALLOWED_ORIGINS in production.
_raw_origins = os.environ.get("ALLOWED_ORIGINS", "*")
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]

# ============================================================
# SECURITY
# ============================================================
# REQUIRED: Set SECRET_KEY in environment. No hardcoded fallback in production.
_IS_PRODUCTION = os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("PRODUCTION", "")
_DEFAULT_SECRET = "smartattend-dev-only-secret-key-change-in-production"

SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    if _IS_PRODUCTION:
        print("FATAL: SECRET_KEY environment variable is not set in production. Exiting.", file=sys.stderr)
        sys.exit(1)
    else:
        SECRET_KEY = _DEFAULT_SECRET
        print("WARNING: SECRET_KEY not set. Using insecure development default. Set SECRET_KEY env var for production.")

# Admin credentials — MUST be changed in production via environment variables.
# No hardcoded fallback for password in production.
DEFAULT_ADMIN_USER = os.environ.get("DEFAULT_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASS = os.environ.get("DEFAULT_ADMIN_PASS", "")
if not DEFAULT_ADMIN_PASS:
    if _IS_PRODUCTION:
        print("FATAL: DEFAULT_ADMIN_PASS not set in production. Exiting.", file=sys.stderr)
        sys.exit(1)
    else:
        DEFAULT_ADMIN_PASS = "admin123"
        print("WARNING: DEFAULT_ADMIN_PASS not set. Using insecure 'admin123' for local dev only.")

# Password policy
MIN_PASSWORD_LENGTH = int(os.environ.get("MIN_PASSWORD_LENGTH", 8))
TOKEN_EXPIRY_HOURS = int(os.environ.get("TOKEN_EXPIRY_HOURS", 24))

# Rate limiting
RATE_LIMIT_LOGIN_MAX = int(os.environ.get("RATE_LIMIT_LOGIN_MAX", 5))       # max attempts
RATE_LIMIT_LOGIN_WINDOW = int(os.environ.get("RATE_LIMIT_LOGIN_WINDOW", 300))  # seconds (5 min)
RATE_LIMIT_RECOGNIZE_MAX = int(os.environ.get("RATE_LIMIT_RECOGNIZE_MAX", 30))
RATE_LIMIT_RECOGNIZE_WINDOW = int(os.environ.get("RATE_LIMIT_RECOGNIZE_WINDOW", 60))

# Max image upload size (bytes) for base64 frame
MAX_IMAGE_BYTES = int(os.environ.get("MAX_IMAGE_BYTES", 5 * 1024 * 1024))  # 5 MB

# ============================================================
# DEEP LEARNING MODELS
# ============================================================
YUNET_MODEL_PATH = os.path.join(MODELS_DIR, "face_detection_yunet_2023mar.onnx")
SFACE_MODEL_PATH = os.path.join(MODELS_DIR, "face_recognition_sface_2021dec.onnx")

YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
SFACE_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"

# ============================================================
# VISION & RECOGNITION SETTINGS
# ============================================================
CAMERA_INDEX = int(os.environ.get("CAMERA_INDEX", 0))
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", 0.60))
NMS_THRESHOLD = float(os.environ.get("NMS_THRESHOLD", 0.3))
COSINE_SIMILARITY_THRESHOLD = float(os.environ.get("COSINE_SIMILARITY_THRESHOLD", 0.363))
L2_DISTANCE_THRESHOLD = float(os.environ.get("L2_DISTANCE_THRESHOLD", 1.128))

# ============================================================
# ATTENDANCE RULES
# ============================================================
COOLDOWN_MINUTES = int(os.environ.get("COOLDOWN_MINUTES", 5))
LATE_CUTOFF_TIME = os.environ.get("LATE_CUTOFF_TIME", "09:15:00")
LIVENESS_TEXTURE_THRESHOLD = float(os.environ.get("LIVENESS_TEXTURE_THRESHOLD", 20.0))

# ============================================================
# CAMPUS GEOFENCING
# ============================================================
DEFAULT_GEOFENCE_RADIUS_METERS = float(os.environ.get("GEOFENCE_RADIUS_METERS", 30.0))
DEFAULT_CAMPUS_NAME = os.environ.get("CAMPUS_NAME", "Main Campus")
DEFAULT_CAMPUS_LAT = float(os.environ.get("CAMPUS_LATITUDE", 28.5355))
DEFAULT_CAMPUS_LON = float(os.environ.get("CAMPUS_LONGITUDE", 77.3910))
DEFAULT_LOCATION_ACCURACY_THRESHOLD_METERS = float(os.environ.get("LOCATION_ACCURACY_THRESHOLD", 50.0))
GEOFENCE_ENABLED = os.environ.get("GEOFENCE_ENABLED", "true").lower() == "true"

# ============================================================
# LECTURE SCHEDULING & ANTI-BUNKING
# ============================================================
DEFAULT_LECTURE_DURATION_MINUTES = int(os.environ.get("LECTURE_DURATION_MINUTES", 50))
DEFAULT_ATTENDANCE_WINDOW_BEFORE_MINS = int(os.environ.get("ATTENDANCE_WINDOW_BEFORE_MINS", 5))
DEFAULT_ATTENDANCE_WINDOW_AFTER_MINS = int(os.environ.get("ATTENDANCE_WINDOW_AFTER_MINS", 15))
INSTITUTION_TIMEZONE = os.environ.get("INSTITUTION_TIMEZONE", "Asia/Kolkata")

# ============================================================
# QR CODE SYSTEM
# ============================================================
QR_TOKEN_EXPIRY_SECONDS = int(os.environ.get("QR_TOKEN_EXPIRY_SECONDS", 30))
QR_MAX_PER_SESSION = int(os.environ.get("QR_MAX_PER_SESSION", 1000))

# ============================================================
# NOTIFICATION / EMAIL (SMTP)
# ============================================================
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "")
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
NOTIFICATIONS_ENABLED = bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)

# Minimum attendance percentage before warning
ATTENDANCE_WARNING_THRESHOLD = float(os.environ.get("ATTENDANCE_WARNING_THRESHOLD", 75.0))

# ============================================================
# VALIDATION POLICIES
# ============================================================
REQUIRE_NUMERIC_ROLL_NO = os.environ.get("REQUIRE_NUMERIC_ROLL_NO", "true").lower() == "true"
INSTITUTION_EMAIL_DOMAIN = os.environ.get("INSTITUTION_EMAIL_DOMAIN", "")

# ============================================================
# EXPORTS
# ============================================================
EXPORTS_DIR = os.environ.get("EXPORTS_DIR", os.path.join(BASE_DIR, "exports"))
os.makedirs(EXPORTS_DIR, exist_ok=True)
