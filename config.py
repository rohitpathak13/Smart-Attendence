import os

# Base Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
DATA_DIR = os.path.join(BASE_DIR, "data")
EXPORTS_DIR = os.path.join(BASE_DIR, "exports")

# Ensure required directories exist
for folder in [MODELS_DIR, DATA_DIR, EXPORTS_DIR]:
    os.makedirs(folder, exist_ok=True)

# Database
DB_PATH = os.path.join(DATA_DIR, "attendance_system.db")

# Deep Learning Models (YuNet Face Detector & SFace Face Recognizer)
YUNET_MODEL_PATH = os.path.join(MODELS_DIR, "face_detection_yunet_2023mar.onnx")
SFACE_MODEL_PATH = os.path.join(MODELS_DIR, "face_recognition_sface_2021dec.onnx")

YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
SFACE_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"

# Vision & Recognition Settings
CAMERA_INDEX = 0
CONFIDENCE_THRESHOLD = 0.85      # YuNet detection confidence score
NMS_THRESHOLD = 0.3              # Non-Maximum Suppression threshold
COSINE_SIMILARITY_THRESHOLD = 0.60  # SFace cosine similarity match threshold (> 0.60 is strong match)
L2_DISTANCE_THRESHOLD = 1.15     # Norm-L2 distance threshold (< 1.15 is match)

# Attendance Rules
COOLDOWN_MINUTES = 30            # Prevent recording same student within 30 minutes
LATE_CUTOFF_TIME = "09:15:00"    # Attendance recorded after this time is marked LATE

# Security & Default Admin
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASS = "admin123"

