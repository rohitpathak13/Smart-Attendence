import os

# Load environment variables from .env file if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Base Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.environ.get("MODELS_DIR", os.path.join(BASE_DIR, "models"))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
EXPORTS_DIR = os.environ.get("EXPORTS_DIR", os.path.join(BASE_DIR, "exports"))

# Ensure required directories exist
for folder in [MODELS_DIR, DATA_DIR, EXPORTS_DIR]:
    os.makedirs(folder, exist_ok=True)

# Database Path (Persistent on Railway volume if DATA_DIR is mounted)
DB_PATH = os.environ.get("DB_PATH", os.path.join(DATA_DIR, "attendance_system.db"))

# Server Configuration
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", 8000))

# Deep Learning Models (YuNet Face Detector & SFace Face Recognizer)
YUNET_MODEL_PATH = os.path.join(MODELS_DIR, "face_detection_yunet_2023mar.onnx")
SFACE_MODEL_PATH = os.path.join(MODELS_DIR, "face_recognition_sface_2021dec.onnx")

YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
SFACE_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"

# Vision & Recognition Settings
CAMERA_INDEX = int(os.environ.get("CAMERA_INDEX", 0))
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", 0.60))         # YuNet detection score
NMS_THRESHOLD = float(os.environ.get("NMS_THRESHOLD", 0.3))                         # Non-Maximum Suppression threshold
COSINE_SIMILARITY_THRESHOLD = float(os.environ.get("COSINE_SIMILARITY_THRESHOLD", 0.363)) # SFace cosine similarity
L2_DISTANCE_THRESHOLD = float(os.environ.get("L2_DISTANCE_THRESHOLD", 1.128))               # Norm-L2 distance threshold

# Attendance Rules
COOLDOWN_MINUTES = int(os.environ.get("COOLDOWN_MINUTES", 5))                       # Prevent duplicate entries within N minutes
LATE_CUTOFF_TIME = os.environ.get("LATE_CUTOFF_TIME", "09:15:00")                   # Attendance recorded after this time is marked LATE
LIVENESS_TEXTURE_THRESHOLD = float(os.environ.get("LIVENESS_TEXTURE_THRESHOLD", 20.0)) # Anti-spoof Laplacian sharpness threshold

# Security & Default Admin
DEFAULT_ADMIN_USER = os.environ.get("DEFAULT_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASS = os.environ.get("DEFAULT_ADMIN_PASS", "admin123")
SECRET_KEY = os.environ.get("SECRET_KEY", "deepvision-secret-railway-key-2026")

# Campus Geofencing (Default radius is 30m, configurable to 50m or custom)
DEFAULT_GEOFENCE_RADIUS_METERS = float(os.environ.get("GEOFENCE_RADIUS_METERS", 30.0))
DEFAULT_CAMPUS_NAME = os.environ.get("CAMPUS_NAME", "Main Campus")
DEFAULT_CAMPUS_LAT = float(os.environ.get("CAMPUS_LATITUDE", 28.5355))
DEFAULT_CAMPUS_LON = float(os.environ.get("CAMPUS_LONGITUDE", 77.3910))
DEFAULT_LOCATION_ACCURACY_THRESHOLD_METERS = float(os.environ.get("LOCATION_ACCURACY_THRESHOLD", 50.0))
GEOFENCE_ENABLED = os.environ.get("GEOFENCE_ENABLED", "true").lower() == "true"

# Lecture Scheduling & Anti-Bunking Defaults
DEFAULT_LECTURE_DURATION_MINUTES = int(os.environ.get("LECTURE_DURATION_MINUTES", 50))
DEFAULT_ATTENDANCE_WINDOW_BEFORE_MINS = int(os.environ.get("ATTENDANCE_WINDOW_BEFORE_MINS", 5))
DEFAULT_ATTENDANCE_WINDOW_AFTER_MINS = int(os.environ.get("ATTENDANCE_WINDOW_AFTER_MINS", 15))
INSTITUTION_TIMEZONE = os.environ.get("INSTITUTION_TIMEZONE", "Asia/Kolkata")

# Validation Policies
REQUIRE_NUMERIC_ROLL_NO = os.environ.get("REQUIRE_NUMERIC_ROLL_NO", "true").lower() == "true"
INSTITUTION_EMAIL_DOMAIN = os.environ.get("INSTITUTION_EMAIL_DOMAIN", "")



