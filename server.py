"""
DeepVision AI - Enterprise Cloud & Web Server (FastAPI)
Includes:
- Phase 17: College Location-Based Attendance (Geofencing with Haversine Formula)
- Phase 18: Strict Email Validation (Lowercase alphanumeric local part, valid domain, uniqueness)
- Phase 19: Student Name Validation (Title Case / UPPERCASE, no digits, no arbitrary mixed case)
- Phase 20: Numeric Roll Number Validation (Digits 0-9 only, preserves leading zeros)
- Phase 21: Lecture-Wise Attendance & Anti-Bunking (50m default, windows, mid-lecture checks, audit trail)
- Phase 22: Configuration & Administrator Controls (Role-based access, audit logging)
"""
import base64
import hmac
import io
import json
import os
import sys
import time
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

import cv2
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request, Response, status, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Ensure base directory is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import (
    DB_PATH,
    YUNET_MODEL_PATH,
    SFACE_MODEL_PATH,
    HOST,
    PORT,
    CONFIDENCE_THRESHOLD,
    COSINE_SIMILARITY_THRESHOLD,
    COOLDOWN_MINUTES,
    LATE_CUTOFF_TIME,
    DEFAULT_ADMIN_USER,
    DEFAULT_ADMIN_PASS,
    SECRET_KEY,
    EXPORTS_DIR,
    DEFAULT_GEOFENCE_RADIUS_METERS,
    DEFAULT_CAMPUS_NAME,
    DEFAULT_CAMPUS_LAT,
    DEFAULT_CAMPUS_LON,
    DEFAULT_LOCATION_ACCURACY_THRESHOLD_METERS,
    GEOFENCE_ENABLED,
    DEFAULT_LECTURE_DURATION_MINUTES,
    DEFAULT_ATTENDANCE_WINDOW_BEFORE_MINS,
    DEFAULT_ATTENDANCE_WINDOW_AFTER_MINS,
    INSTITUTION_TIMEZONE,
    ALLOWED_ORIGINS,
    MAX_IMAGE_BYTES,
    RATE_LIMIT_LOGIN_MAX,
    RATE_LIMIT_LOGIN_WINDOW,
    RATE_LIMIT_RECOGNIZE_MAX,
    RATE_LIMIT_RECOGNIZE_WINDOW
)
from core.model_loader import ensure_models_exist
from core.face_engine import FaceEngine
from core.liveness import LivenessDetector
from core.validators import validate_email, validate_student_name, validate_roll_number
from core.geofence import verify_student_location, validate_coordinates, haversine_distance
from core.security import (
    Role, create_auth_token, verify_auth_token,
    validate_password_strength, rate_limiter, sanitize_csv_field
)
from core.anti_proxy import (
    MultiLayerVerificationEngine, VerificationPolicy,
    VerificationStatus, RejectionReason
)
from core.qr_engine import generate_qr_token, verify_qr_token, get_token_time_remaining
from core.ml_analytics import AttendanceAnalyticsEngine
from core.notification_service import NotificationService
from core.reports_engine import ReportsEngine
from core.offline_sync import OfflineSyncEngine, create_offline_attendance_packet, verify_offline_packet
from database.db_manager import DatabaseManager

# Global singletons
db: Optional[DatabaseManager] = None
engine: Optional[FaceEngine] = None
liveness: Optional[LivenessDetector] = None
cached_students: List[Dict] = []
analytics_engine: Optional[AttendanceAnalyticsEngine] = None
notification_service: Optional[NotificationService] = None
reports_engine: Optional[ReportsEngine] = None
offline_sync_engine: Optional[OfflineSyncEngine] = None
anti_proxy_engine: Optional[MultiLayerVerificationEngine] = None

def reload_student_cache():
    global cached_students, db
    if db:
        cached_students = db.get_all_students()
        print(f"[CACHE] Loaded {len(cached_students)} registered students into memory.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, engine, liveness, analytics_engine, notification_service, reports_engine, offline_sync_engine, anti_proxy_engine
    print("=" * 60)
    print(" Starting SmartAttend AI Server with Multi-Layer Verification")
    print(f" Environment: Host={HOST}, Port={PORT}, DB={DB_PATH}")
    print("=" * 60)

    # 1. Ensure models
    if not ensure_models_exist():
        print("WARNING: Could not automatically verify ONNX models!")

    # 2. Connect DB
    db = DatabaseManager(DB_PATH)
    db.ensure_default_admin(DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASS)

    # 3. Vision Engine
    engine = FaceEngine(
        yunet_path=YUNET_MODEL_PATH,
        sface_path=SFACE_MODEL_PATH,
        conf_threshold=CONFIDENCE_THRESHOLD,
        cosine_threshold=COSINE_SIMILARITY_THRESHOLD
    )
    liveness = LivenessDetector()

    # 4. SmartAttend Core Engines
    analytics_engine = AttendanceAnalyticsEngine(db)
    notification_service = NotificationService(db)
    reports_engine = ReportsEngine(db)
    offline_sync_engine = OfflineSyncEngine(db)
    anti_proxy_engine = MultiLayerVerificationEngine()

    # 5. Cache students
    reload_student_cache()
    print("SmartAttend AI API ready to accept connections.")
    yield
    print("Shutting down SmartAttend AI Web Server...")

app = FastAPI(
    title="SmartAttend AI - Intelligent Location Verified Attendance & College Management Platform",
    description="Multi-factor Contactless Facial Recognition, Geofencing, Dynamic QR, and Campus Management",
    version="4.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS if ALLOWED_ORIGINS else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helper: Decode Base64 Image with size validation
def decode_image_base64(image_data: str) -> np.ndarray:
    if "," in image_data:
        image_data = image_data.split(",", 1)[1]
    try:
        raw_bytes = base64.b64decode(image_data)
        if len(raw_bytes) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Image size ({len(raw_bytes)} bytes) exceeds maximum allowed size ({MAX_IMAGE_BYTES} bytes)."
            )
        np_arr = np.frombuffer(raw_bytes, dtype=np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("cv2.imdecode returned None")
        return frame
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 image data: {str(e)}")

# --- Security & Token Utilities ---
def create_admin_token(username: str) -> str:
    timestamp = int(time.time())
    payload = f"{username}:{timestamp}"
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), "sha256").hexdigest()
    token = base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()
    return token

def verify_admin_token(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    try:
        if token.startswith("Bearer "):
            token = token[7:].strip()
        
        # Check standard HMAC auth token first
        is_ok, payload, _ = verify_auth_token(token, required_roles=[Role.ADMIN])
        if is_ok and payload:
            return payload.get("sub") or str(payload.get("uid"))

        # Fallback to legacy 3-part token
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        parts = decoded.split(":")
        if len(parts) == 3:
            username, ts_str, sig = parts
            payload_str = f"{username}:{ts_str}"
            expected_sig = hmac.new(SECRET_KEY.encode(), payload_str.encode(), "sha256").hexdigest()
            if hmac.compare_digest(sig, expected_sig) and (time.time() - int(ts_str) <= 86400):
                return username
        return None
    except Exception:
        return None

def require_admin(authorization: Optional[str] = Header(None), x_admin_token: Optional[str] = Header(None)) -> str:
    token = authorization or x_admin_token
    username = verify_admin_token(token)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Valid administrator session required to access this endpoint."
        )
    return username

def get_current_user(
    authorization: Optional[str] = Header(None),
    x_token: Optional[str] = Header(None),
    x_admin_token: Optional[str] = Header(None)
) -> Dict[str, Any]:
    token = authorization or x_token or x_admin_token
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication token required.")
    if token.startswith("Bearer "):
        token = token[7:].strip()
    
    is_valid, payload, msg = verify_auth_token(token)
    if is_valid and payload:
        return payload
    
    admin_user = verify_admin_token(token)
    if admin_user:
        return {"uid": 1, "sub": admin_user, "role": Role.ADMIN}

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Unauthorized: {msg}")

def require_auth(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    return user

def require_teacher(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") not in (Role.TEACHER, Role.ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teacher or Admin role required")
    return user

def require_student(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") not in (Role.STUDENT, Role.ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Student or Admin role required")
    return user

def require_parent(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") not in (Role.PARENT, Role.ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Parent or Admin role required")
    return user

# --- Request / Response Models ---
class FrameRecognitionRequest(BaseModel):
    image: str
    mark_attendance: bool = True
    session_id: Optional[str] = "web_client"
    # Geolocation fields (Phase 17)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy: Optional[float] = None
    # Lecture session fields (Phase 21)
    lecture_id: Optional[int] = None
    verification_event_id: Optional[int] = None

class EnrollStudentRequest(BaseModel):
    roll_no: str
    name: str
    department: Optional[str] = "General"
    email: Optional[str] = ""
    image: str
    allow_admin_override: Optional[bool] = False
    allow_update: Optional[bool] = False

class AdminLoginRequest(BaseModel):
    username: str
    password: str

class AdminPasswordChangeRequest(BaseModel):
    username: str
    old_password: str
    new_password: str

class CampusCreateRequest(BaseModel):
    name: str
    latitude: float
    longitude: float
    radius_meters: float = Field(default=30.0, description="Allowed radius in meters. Default is 30m.")
    accuracy_threshold_meters: float = Field(default=50.0, description="GPS accuracy threshold.")

class CampusUpdateRequest(BaseModel):
    name: str
    latitude: float
    longitude: float
    radius_meters: float
    accuracy_threshold_meters: float = 50.0
    is_active: bool = True

class SettingsUpdateRequest(BaseModel):
    settings: Dict[str, str]

class LectureCreateRequest(BaseModel):
    course_code: str
    subject_name: str
    instructor_name: str
    date: str
    start_time: str
    duration_minutes: int = Field(default=50, description="Lecture duration in minutes. Default is 50m.")
    section: Optional[str] = "A"
    room: Optional[str] = "Room 101"
    campus_id: Optional[int] = None
    window_before_mins: Optional[int] = 5
    window_after_mins: Optional[int] = 15

class LectureStatusUpdateRequest(BaseModel):
    status: str

class MidCheckCreateRequest(BaseModel):
    duration_minutes: int = 5
    event_type: str = "MID_LECTURE"

class AttendanceCorrectionRequest(BaseModel):
    lecture_id: int
    student_id: int
    new_status: str
    reason: str
    authorized_by: str

# --- SmartAttend AI Extended Models ---
class UnifiedLoginRequest(BaseModel):
    username: str
    password: str
    role: Optional[str] = "ADMIN"

class MultiLayerVerificationRequest(BaseModel):
    image: str
    session_id: Optional[int] = None
    lecture_id: Optional[int] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy: Optional[float] = None
    qr_token: Optional[str] = None
    beacon_uuid: Optional[str] = None
    camera_id: Optional[str] = None
    camera_api_key: Optional[str] = None

class TeacherSessionStartRequest(BaseModel):
    subject_id: Optional[int] = None
    classroom_id: Optional[int] = None
    lecture_id: Optional[int] = None
    qr_expiry_seconds: int = 30
    require_face: bool = True
    require_location: bool = True
    require_qr: bool = True

class LeaveSubmitRequest(BaseModel):
    leave_type: str = "MEDICAL"
    from_date: str
    to_date: str
    reason: str

class LeaveReviewRequest(BaseModel):
    decision: str
    comment: Optional[str] = None

class DepartmentCreateRequest(BaseModel):
    name: str
    code: str
    head_teacher_id: Optional[int] = None

class CourseCreateRequest(BaseModel):
    department_id: int
    name: str
    code: str
    semester: int = 1
    credits: int = 4

class SubjectCreateRequest(BaseModel):
    course_id: int
    name: str
    code: str
    type: str = "Theory"

class ClassroomCreateRequest(BaseModel):
    name: str
    building: str = "Main Building"
    floor: int = 1
    capacity: int = 60
    campus_id: Optional[int] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class TeacherCreateRequest(BaseModel):
    employee_id: str
    name: str
    email: str
    password: str
    department_id: Optional[int] = None

class TeacherAssignRequest(BaseModel):
    teacher_id: int
    subject_id: int
    classroom_id: Optional[int] = None

class CameraCreateRequest(BaseModel):
    camera_uid: str
    name: str
    api_key: str
    classroom_id: Optional[int] = None

class BeaconCreateRequest(BaseModel):
    beacon_uuid: str
    name: str
    classroom_id: Optional[int] = None
    major: Optional[int] = None
    minor: Optional[int] = None

class TimetableCreateRequest(BaseModel):
    subject_id: int
    teacher_id: int
    day_of_week: int
    start_time: str
    end_time: str
    classroom_id: Optional[int] = None

class HolidayCreateRequest(BaseModel):
    date: str
    name: str
    type: str = "NATIONAL"

class OfflineSyncRequest(BaseModel):
    packets: List[Dict[str, Any]]

# --- General System & Health Endpoints ---

@app.get("/health")
def health_check():
    """Railway Healthcheck Probe Endpoint"""
    return {
        "status": "healthy",
        "service": "DeepVision AI Contactless Attendance & Anti-Bunking System",
        "models_loaded": engine is not None,
        "students_count": len(cached_students),
        "cooldown_minutes": COOLDOWN_MINUTES,
        "late_cutoff": LATE_CUTOFF_TIME,
        "default_geofence_radius": DEFAULT_GEOFENCE_RADIUS_METERS,
        "default_lecture_duration": DEFAULT_LECTURE_DURATION_MINUTES,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/config/public")
def get_public_config():
    """
    Returns public institutional settings for frontend UI:
    Exposes only non-sensitive flags without leaking administrative coordinates.
    """
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    settings = db.get_all_settings()
    campuses = db.get_active_campuses()
    
    return {
        "geofence_enabled": settings.get("geofence_enabled", "true").lower() == "true",
        "default_radius_meters": float(settings.get("default_radius_meters", DEFAULT_GEOFENCE_RADIUS_METERS)),
        "accuracy_threshold_meters": float(settings.get("accuracy_threshold_meters", DEFAULT_LOCATION_ACCURACY_THRESHOLD_METERS)),
        "default_lecture_duration_minutes": int(settings.get("default_lecture_duration_minutes", DEFAULT_LECTURE_DURATION_MINUTES)),
        "attendance_window_before_mins": int(settings.get("attendance_window_before_mins", DEFAULT_ATTENDANCE_WINDOW_BEFORE_MINS)),
        "attendance_window_after_mins": int(settings.get("attendance_window_after_mins", DEFAULT_ATTENDANCE_WINDOW_AFTER_MINS)),
        "active_campuses_count": len(campuses),
        "institution_timezone": settings.get("institution_timezone", INSTITUTION_TIMEZONE),
        "require_numeric_roll_no": settings.get("require_numeric_roll_no", "true").lower() == "true",
        "email_local_part_policy": "lowercase_alphanumeric"
    }

# --- Recognition & Geofenced Attendance (Phases 17, 21) ---

@app.post("/api/recognize")
def recognize_frame(payload: FrameRecognitionRequest):
    """
    Processes webcam frame and records attendance if student is recognized, live, and inside geofence.
    Server strictly validates:
    1. yuNet face detection
    2. SFace ArcFace 128-D embedding matching
    3. Anti-spoofing texture & temporal micro-motion liveness
    4. Haversine distance to college campus (Phase 17)
    5. Lecture attendance session & window verification (Phase 21)
    """
    if engine is None or db is None:
        raise HTTPException(status_code=503, detail="Face engine not ready")

    frame = decode_image_base64(payload.image)
    detected_faces = engine.detect_faces(frame)

    # 1. Server-side Geofence Pre-Verification
    settings = db.get_all_settings()
    geofence_enabled = settings.get("geofence_enabled", "true").lower() == "true"
    accuracy_threshold = float(settings.get("accuracy_threshold_meters", DEFAULT_LOCATION_ACCURACY_THRESHOLD_METERS))
    active_campuses = db.get_active_campuses()

    is_loc_verified, loc_message, loc_details = verify_student_location(
        student_lat=payload.latitude,
        student_lon=payload.longitude,
        accuracy_meters=payload.accuracy,
        campuses=active_campuses,
        accuracy_threshold_meters=accuracy_threshold,
        geofence_enabled=geofence_enabled
    )

    results = []
    for face in detected_faces:
        x, y, w, h = face["bbox"]
        landmarks = face["landmarks"]
        conf = face["confidence"]

        # Anti-spoofing Texture & Micro-Motion
        face_crop = frame[y:y+h, x:x+w]
        is_texture_plausible, tex_score = liveness.analyze_texture(face_crop)
        is_motion_live, liveness_msg, motion_score = liveness.check_temporal_liveness(
            payload.session_id, landmarks
        )

        is_spoof = (not is_texture_plausible) or (not is_motion_live and "Spoof" in liveness_msg)

        # Extract ArcFace 128-D embedding
        emb = engine.extract_embedding(frame, face["raw"])
        matched_student, match_score = engine.identify_face(emb, cached_students)

        attendance_event = None
        if matched_student and not is_spoof and payload.mark_attendance:
            # Check Geofence first
            if not is_loc_verified:
                attendance_event = {
                    "recorded": False,
                    "message": loc_message,
                    "reason": loc_details.get("error_type", "GEOFENCE_VIOLATION"),
                    "geofence": loc_details
                }
                # Log audit event for geofence rejection
                db.log_audit(
                    "GEOFENCE_REJECTION",
                    f"Student {matched_student['name']} ({matched_student['roll_no']}) attendance rejected: {loc_message}",
                    actor=matched_student["roll_no"]
                )
            else:
                # Location is verified! Check Lecture session or Daily Attendance
                distance_m = loc_details.get("distance_meters")

                if payload.verification_event_id:
                    # Mid-Lecture Verification check
                    rec_ok, rec_msg, rec_info = db.record_mid_lecture_verification(
                        event_id=payload.verification_event_id,
                        student_id=matched_student["id"],
                        confidence=match_score,
                        distance_meters=distance_m
                    )
                    attendance_event = {
                        "recorded": rec_ok,
                        "message": rec_msg,
                        "type": "MID_LECTURE_VERIFICATION",
                        "record": rec_info
                    }
                elif payload.lecture_id:
                    # Specific lecture attendance marking
                    rec_ok, rec_msg, rec_info = db.mark_lecture_attendance(
                        lecture_id=payload.lecture_id,
                        student_id=matched_student["id"],
                        confidence=match_score,
                        distance_meters=distance_m
                    )
                    attendance_event = {
                        "recorded": rec_ok,
                        "message": rec_msg,
                        "type": "LECTURE_ATTENDANCE",
                        "record": rec_info
                    }
                else:
                    # Check if there is an active lecture session open right now
                    active_lecture = db.get_current_or_open_lecture()
                    if active_lecture:
                        rec_ok, rec_msg, rec_info = db.mark_lecture_attendance(
                            lecture_id=active_lecture["id"],
                            student_id=matched_student["id"],
                            confidence=match_score,
                            distance_meters=distance_m
                        )
                        attendance_event = {
                            "recorded": rec_ok,
                            "message": rec_msg,
                            "type": "LECTURE_ATTENDANCE",
                            "record": rec_info
                        }
                    else:
                        # Fallback to standard daily attendance
                        rec_ok, rec_msg, rec_info = db.mark_attendance(
                            student_id=matched_student["id"],
                            confidence=match_score,
                            cooldown_minutes=COOLDOWN_MINUTES,
                            late_cutoff=LATE_CUTOFF_TIME
                        )
                        attendance_event = {
                            "recorded": rec_ok,
                            "message": rec_msg,
                            "type": "DAILY_ATTENDANCE",
                            "record": rec_info
                        }

        results.append({
            "bbox": [x, y, w, h],
            "landmarks": landmarks,
            "detection_confidence": round(conf, 3),
            "match_confidence": round(match_score, 3),
            "is_recognized": matched_student is not None,
            "student": {
                "id": matched_student["id"],
                "roll_no": matched_student["roll_no"],
                "name": matched_student["name"],
                "department": matched_student["department"]
            } if matched_student else None,
            "liveness": {
                "is_live": not is_spoof,
                "status": liveness_msg,
                "texture_score": round(tex_score, 1)
            },
            "location_verified": is_loc_verified,
            "attendance": attendance_event
        })

    return {
        "faces_detected": len(results),
        "results": results,
        "geofence_status": {
            "verified": is_loc_verified,
            "message": loc_message,
            "details": loc_details
        },
        "timestamp": datetime.now().isoformat()
    }

# --- Student Enrollment & Directory (Phases 18, 19, 20) ---

@app.post("/api/students/enroll")
def enroll_student(payload: EnrollStudentRequest):
    """
    Enrolls a new student with strict multi-phase validations:
    - Phase 18: Lowercase alphanumeric local part email validation & uniqueness
    - Phase 19: Student name validation (Title Case or UPPERCASE, no digits, no mixed case)
    - Phase 20: Numeric roll number validation (Digits 0-9 only, preserves leading zeros)
    - ArcFace 128-D facial feature embedding extraction
    """
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    settings = db.get_all_settings()
    require_numeric = settings.get("require_numeric_roll_no", "true").lower() == "true"
    inst_domain = settings.get("institution_email_domain", "")

    # 1. Roll Number Validation (Phase 20)
    is_roll_ok, norm_roll, roll_err = validate_roll_number(payload.roll_no, require_numeric=require_numeric)
    if not is_roll_ok:
        raise HTTPException(status_code=400, detail=roll_err)

    # 2. Student Name Validation (Phase 19)
    is_name_ok, norm_name, name_err = validate_student_name(payload.name, allow_admin_override=bool(payload.allow_admin_override))
    if not is_name_ok:
        raise HTTPException(status_code=400, detail=name_err)

    # 3. Email Validation (Phase 18)
    norm_email = ""
    if payload.email and payload.email.strip():
        is_email_ok, norm_email, email_err = validate_email(payload.email, institutional_domain=inst_domain)
        if not is_email_ok:
            raise HTTPException(status_code=400, detail=email_err)

    if engine is None:
        raise HTTPException(status_code=503, detail="Face engine not ready")

    frame = decode_image_base64(payload.image)
    faces = engine.detect_faces(frame)

    if len(faces) == 0:
        raise HTTPException(status_code=400, detail="No face detected in the image. Please position your face clearly in good lighting.")
    if len(faces) > 1:
        raise HTTPException(status_code=400, detail=f"{len(faces)} faces detected. Only one person must be present during enrollment.")

    face = faces[0]
    emb = engine.extract_embedding(frame, face["raw"])

    success, msg = db.register_student(
        roll_no=norm_roll,
        name=norm_name,
        department=payload.department or "General",
        email=norm_email,
        embedding=emb,
        allow_admin_override=bool(payload.allow_admin_override),
        allow_update=bool(payload.allow_update)
    )

    if not success:
        if "duplicate" in msg.lower():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
        raise HTTPException(status_code=400, detail=msg)

    # Reload memory cache
    reload_student_cache()

    return {
        "success": True,
        "message": msg,
        "student": {
            "roll_no": norm_roll,
            "name": norm_name,
            "department": payload.department or "General",
            "email": norm_email
        }
    }

@app.get("/api/students")
def get_students():
    """Returns all enrolled students with monthly active days attendance statistics"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    students = db.get_students_directory()
    return {"students": students, "count": len(students)}

@app.delete("/api/students/{roll_no}")
def delete_student(roll_no: str, admin_user: str = Depends(require_admin)):
    """Deletes an enrolled student by roll number (Admin Only)"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    ok, msg = db.delete_student(roll_no)
    if not ok:
        raise HTTPException(status_code=404, detail=msg)
    reload_student_cache()
    return {"success": True, "message": msg}

@app.get("/api/admin/students/audit")
def audit_students(admin_user: str = Depends(require_admin)):
    """
    Returns an institutional audit report of student records, identifying valid
    records preserved and legacy/rejected records flagged for administrative review.
    """
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    return db.audit_student_records()

# --- Lecture Scheduling & Attendance Operations (Phase 21) ---

@app.get("/api/lectures")
def list_lectures(date: Optional[str] = None, status: Optional[str] = None):
    """Lists scheduled lectures, filterable by date and status"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    lectures = db.get_lectures(date_str=date, status=status)
    return {"lectures": lectures, "count": len(lectures)}

@app.get("/api/lectures/active")
def get_active_lecture():
    """Returns the currently active or open lecture session"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    lecture = db.get_current_or_open_lecture()
    return {"active_lecture": lecture}

@app.get("/api/lectures/{lecture_id}")
def get_lecture_details(lecture_id: int):
    """Returns details and attendance statistics for a single lecture"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    lecture = db.get_lecture_by_id(lecture_id)
    if not lecture:
        raise HTTPException(status_code=404, detail=f"Lecture {lecture_id} not found")
    report = db.get_lecture_attendance_report(lecture_id)
    return {"lecture": lecture, "report": report}

@app.post("/api/lectures")
def create_lecture(payload: LectureCreateRequest, admin_user: str = Depends(require_admin)):
    """
    Schedules a new lecture session (Admin / Instructor only):
    - Default duration: 50 minutes (Phase 21-A)
    - Attendance window automatically configured around start time
    """
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    ok, msg, lecture_id = db.create_lecture(
        course_code=payload.course_code,
        subject_name=payload.subject_name,
        instructor_name=payload.instructor_name,
        date_str=payload.date,
        start_time_str=payload.start_time,
        duration_minutes=payload.duration_minutes,
        section=payload.section or "A",
        room=payload.room or "Room 101",
        campus_id=payload.campus_id,
        window_before_mins=payload.window_before_mins or 5,
        window_after_mins=payload.window_after_mins or 15,
        actor=admin_user
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "lecture_id": lecture_id}

@app.post("/api/lectures/{lecture_id}/status")
def update_lecture_status(lecture_id: int, payload: LectureStatusUpdateRequest, admin_user: str = Depends(require_admin)):
    """Updates lecture status: Scheduled, Open, Closed, Cancelled (Admin / Instructor only)"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    ok, msg = db.update_lecture_status(lecture_id, payload.status, actor=admin_user)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

@app.post("/api/lectures/{lecture_id}/mid-check")
def trigger_mid_lecture_check(lecture_id: int, payload: MidCheckCreateRequest, admin_user: str = Depends(require_admin)):
    """
    Triggers an anti-bunking mid-lecture verification event with a bounded valid window (Phase 21-D, E)
    """
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    ok, msg, event_id = db.create_mid_lecture_verification_event(
        lecture_id=lecture_id,
        duration_minutes=payload.duration_minutes,
        event_type=payload.event_type,
        actor=admin_user
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "event_id": event_id}

@app.get("/api/lectures/{lecture_id}/attendance")
def get_lecture_attendance_report(lecture_id: int):
    """Returns detailed attendance report with anti-bunking mid-check records for a lecture"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    report = db.get_lecture_attendance_report(lecture_id)
    if not report:
        raise HTTPException(status_code=404, detail="Lecture not found")
    return report

@app.post("/api/admin/attendance/correct")
def correct_attendance(payload: AttendanceCorrectionRequest, admin_user: str = Depends(require_admin)):
    """
    Authorized instructor / administrator manual attendance correction with mandatory audit trail (Phase 21-D)
    """
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    ok, msg = db.correct_lecture_attendance(
        lecture_id=payload.lecture_id,
        student_id=payload.student_id,
        new_status=payload.new_status,
        reason=payload.reason,
        authorized_by=admin_user
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

@app.get("/api/reports/lecture-stats")
def get_anti_bunking_analytics():
    """Returns aggregated anti-bunking analytics: student attendance %, subject %, missed lectures"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    analytics = db.get_anti_bunking_analytics()
    return analytics

# --- Campus & Administrator Geofence Management (Phases 17, 22) ---

@app.get("/api/admin/campuses")
def list_campuses_admin(admin_user: str = Depends(require_admin)):
    """Returns all configured campuses with exact coordinates and radii (Admin Only)"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    campuses = db.get_all_campuses()
    return {"campuses": campuses}

@app.post("/api/admin/campuses")
def add_campus(payload: CampusCreateRequest, admin_user: str = Depends(require_admin)):
    """
    Registers a new authorized college campus location (Admin Only):
    - Default radius is 30 meters (Phase 17)
    - Validates latitude [-90, 90] and longitude [-180, 180]
    """
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    ok, msg, campus_id = db.add_campus(
        name=payload.name,
        latitude=payload.latitude,
        longitude=payload.longitude,
        radius_meters=payload.radius_meters,
        accuracy_threshold_meters=payload.accuracy_threshold_meters,
        actor=admin_user
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "campus_id": campus_id}

@app.put("/api/admin/campuses/{campus_id}")
def update_campus(campus_id: int, payload: CampusUpdateRequest, admin_user: str = Depends(require_admin)):
    """Updates campus coordinates, radius, or active status (Admin Only)"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    ok, msg = db.update_campus(
        campus_id=campus_id,
        name=payload.name,
        latitude=payload.latitude,
        longitude=payload.longitude,
        radius_meters=payload.radius_meters,
        accuracy_threshold_meters=payload.accuracy_threshold_meters,
        is_active=payload.is_active,
        actor=admin_user
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

@app.delete("/api/admin/campuses/{campus_id}")
def delete_campus(campus_id: int, admin_user: str = Depends(require_admin)):
    """Deletes an authorized campus location (Admin Only)"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    ok, msg = db.delete_campus(campus_id, actor=admin_user)
    if not ok:
        raise HTTPException(status_code=404, detail=msg)
    return {"success": True, "message": msg}

# --- System Settings & Audit Logs (Phase 22) ---

@app.get("/api/admin/settings")
def get_system_settings_admin(admin_user: str = Depends(require_admin)):
    """Returns all system settings and institutional policies (Admin Only)"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    settings = db.get_all_settings()
    return {"settings": settings}

@app.post("/api/admin/settings")
def update_system_settings_admin(payload: SettingsUpdateRequest, admin_user: str = Depends(require_admin)):
    """Updates system settings and institutional policies with audit logging (Admin Only)"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    ok, msg = db.update_settings(payload.settings, actor=admin_user)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

@app.get("/api/admin/audit-logs")
def get_audit_logs_admin(limit: int = 100, admin_user: str = Depends(require_admin)):
    """Fetches administrative and security audit trail (Admin Only)"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    logs = db.get_audit_logs(limit=limit)
    return {"logs": logs}

# --- Daily Attendance & Reporting Endpoints (Preserved) ---

@app.get("/api/attendance/today")
def get_today_attendance():
    """Returns today's live KPI summary and attendance records"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    stats = db.get_today_stats()
    records = db.get_today_attendance()
    return {
        "stats": stats,
        "records": records,
        "date": datetime.now().strftime("%Y-%m-%d")
    }

@app.get("/api/attendance")
def get_attendance_by_date(date: Optional[str] = None):
    """Returns attendance records for a specific date (YYYY-MM-DD)"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    date_str = date or datetime.now().strftime("%Y-%m-%d")
    records = db.get_attendance_by_date(date_str)
    return {
        "date": date_str,
        "count": len(records),
        "records": records
    }

@app.get("/api/attendance/export")
def export_attendance_csv(date: Optional[str] = None):
    """Generates and downloads a clean CSV report for the specified date"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    date_str = date or datetime.now().strftime("%Y-%m-%d")
    records = db.get_attendance_by_date(date_str)
    if not records:
        raise HTTPException(status_code=404, detail=f"No attendance records found for date {date_str}.")

    df = pd.DataFrame(records)
    df = df[["roll_no", "name", "department", "date", "time", "status", "confidence"]]
    df.columns = ["Roll No", "Name", "Department", "Date", "Time", "Status", "Confidence"]

    stream = io.StringIO()
    df.to_csv(stream, index=False)
    csv_bytes = stream.getvalue().encode("utf-8")

    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=attendance_{date_str}.csv"
        }
    )

# --- Admin Authentication Endpoints ---

@app.post("/api/admin/login")
def admin_login(payload: AdminLoginRequest):
    """Verifies admin credentials and returns a secure session token"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    if db.verify_admin(payload.username, payload.password):
        token = create_admin_token(payload.username)
        db.log_audit("ADMIN_LOGIN_SUCCESS", f"User '{payload.username}' logged in successfully", actor=payload.username)
        return {
            "success": True,
            "message": "Authentication successful",
            "username": payload.username,
            "token": token
        }
    db.log_audit("ADMIN_LOGIN_FAILED", f"Failed login attempt for username '{payload.username}'", actor=payload.username)
    raise HTTPException(status_code=401, detail="Invalid username or password")

@app.post("/api/admin/change-password")
def admin_change_password(payload: AdminPasswordChangeRequest, admin_user: str = Depends(require_admin)):
    """Changes admin password (Admin Only)"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    ok, msg = db.change_admin_password(payload.username, payload.old_password, payload.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

# =========================================================================
# --- PHASE 2-14: SMARTATTEND AI CORE API ENDPOINTS ---
# =========================================================================

# --- 1. Unified Authentication (Admin, Teacher, Student, Parent) ---
@app.post("/api/auth/login")
def unified_login(payload: UnifiedLoginRequest, request: Request):
    """
    Unified multi-role login with sliding-window rate limiting.
    Supports ADMIN, TEACHER, STUDENT, PARENT roles.
    """
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    # Rate limiting by client IP
    client_ip = request.client.host if request.client else "unknown"
    is_allowed, remaining = rate_limiter.is_allowed(f"login_{client_ip}", max_requests=RATE_LIMIT_LOGIN_MAX, window_seconds=RATE_LIMIT_LOGIN_WINDOW)
    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Please wait {RATE_LIMIT_LOGIN_WINDOW // 60} minutes."
        )

    role = (payload.role or "ADMIN").upper()
    user_record = None

    if role == Role.ADMIN:
        if db.verify_admin(payload.username, payload.password):
            token = create_auth_token(user_id=1, username=payload.username, role=Role.ADMIN)
            db.log_audit("AUTH_LOGIN_SUCCESS", f"Admin '{payload.username}' logged in", actor=payload.username)
            return {
                "success": True,
                "role": Role.ADMIN,
                "username": payload.username,
                "user": {"name": payload.username, "role": Role.ADMIN},
                "token": token
            }
    elif role == Role.TEACHER:
        teacher = db.verify_teacher_login(payload.username, payload.password)
        if teacher:
            token = create_auth_token(user_id=teacher["id"], username=teacher["email"], role=Role.TEACHER)
            db.log_audit("AUTH_LOGIN_SUCCESS", f"Teacher '{teacher['name']}' logged in", actor=teacher["email"])
            return {
                "success": True,
                "role": Role.TEACHER,
                "username": teacher["email"],
                "user": teacher,
                "token": token
            }
    elif role == Role.STUDENT:
        student = db.verify_student_login(payload.username, payload.password)
        if student:
            token = create_auth_token(user_id=student["id"], username=student["roll_number"], role=Role.STUDENT)
            db.log_audit("AUTH_LOGIN_SUCCESS", f"Student '{student['name']}' logged in", actor=student["roll_number"])
            return {
                "success": True,
                "role": Role.STUDENT,
                "username": student["roll_number"],
                "user": student,
                "token": token
            }
    elif role == Role.PARENT:
        parent = db.verify_parent_login(payload.username, payload.password)
        if parent:
            token = create_auth_token(user_id=parent["id"], username=parent["email"], role=Role.PARENT)
            db.log_audit("AUTH_LOGIN_SUCCESS", f"Parent '{parent['name']}' logged in", actor=parent["email"])
            return {
                "success": True,
                "role": Role.PARENT,
                "username": parent["email"],
                "user": parent,
                "token": token
            }

    db.log_audit("AUTH_LOGIN_FAILED", f"Failed {role} login for '{payload.username}'", actor=payload.username)
    raise HTTPException(status_code=401, detail="Invalid username, role, or password.")

@app.get("/api/auth/me")
def get_current_user_profile(user: Dict[str, Any] = Depends(require_auth)):
    """Returns profile and role permissions for the currently authenticated session"""
    return {"user": user}

# --- 2. Multi-Layer Anti-Proxy Attendance Verification ---
@app.post("/api/attendance/verify-multi-layer")
def verify_attendance_multi_layer(payload: MultiLayerVerificationRequest, request: Request):
    """
    Phase 2 & 3: Multi-Layer Anti-Proxy Attendance Verification Engine.
    Combines:
    1. Face Recognition (Cosine similarity matching)
    2. Liveness Detection (Laplacian texture variance + temporal motion)
    3. GPS Geofencing (Distance to classroom/campus, accuracy check)
    4. Dynamic QR verification (One-time nonce consumption, expiry)
    5. Bluetooth Beacon proximity (optional)
    6. Fixed Camera Authentication
    7. Duplicate Attendance Prevention
    Returns VERIFIED, REJECTED, or PENDING_REVIEW.
    """
    if db is None or engine is None:
        raise HTTPException(status_code=503, detail="System services not ready")

    # Rate limiting
    client_ip = request.client.host if request.client else "unknown"
    is_allowed, _ = rate_limiter.is_allowed(f"recog_{client_ip}", max_requests=RATE_LIMIT_RECOGNIZE_MAX, window_seconds=RATE_LIMIT_RECOGNIZE_WINDOW)
    if not is_allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many recognition requests. Please slow down.")

    frame = decode_image_base64(payload.image)

    # 1. Face Recognition
    faces = engine.detect_faces(frame)
    if len(faces) == 0:
        return {
            "overall_status": "REJECTED",
            "primary_reason": "FACE_NOT_DETECTED",
            "detail_message": "No face detected in the camera frame.",
            "layers": {"face": {"status": "NO_FACE"}}
        }

    face = faces[0]
    emb = engine.extract_embedding(frame, face["raw"])
    matched_student, sim_score = engine.identify_face(emb, cached_students)

    face_match_data = None
    if matched_student:
        face_match_data = {
            "matched": True,
            "student_id": matched_student["id"],
            "name": matched_student["name"],
            "roll_number": matched_student["roll_no"],
            "similarity": float(sim_score)
        }
    else:
        face_match_data = {"matched": False, "similarity": float(sim_score)}

    # 2. Liveness Detection
    liveness_tex = liveness.analyze_texture(frame, face["bbox"]) if liveness else 50.0
    is_live_temporal = True
    if liveness:
        tracking_id = matched_student["roll_no"] if matched_student else "unknown"
        is_live_temporal = liveness.check_temporal_liveness(tracking_id, face["landmarks"])

    liveness_data = {
        "is_live": bool(is_live_temporal and (liveness_tex >= 20.0)),
        "texture_score": float(liveness_tex),
        "reason": "STATIC_IMAGE" if not is_live_temporal else "LIVE"
    }

    # 3. Retrieve Session Details (if session_id provided)
    session_info = None
    target_coords = (DEFAULT_CAMPUS_LAT, DEFAULT_CAMPUS_LON)
    target_radius = DEFAULT_GEOFENCE_RADIUS_METERS
    is_session_active = True
    req_qr = False

    if payload.session_id:
        session_info = db.get_session_by_id(payload.session_id)
        if not session_info:
            is_session_active = False
        else:
            is_session_active = (session_info.get("status") == "ACTIVE")
            req_qr = bool(session_info.get("require_qr", 1))
            if session_info.get("latitude") and session_info.get("longitude"):
                target_coords = (session_info["latitude"], session_info["longitude"])

    # 4. Duplicate Check
    is_already_marked = False
    if matched_student:
        is_already_marked = db.is_attendance_already_recorded(
            student_id=matched_student["id"],
            lecture_id=payload.lecture_id or (session_info.get("lecture_id") if session_info else None)
        )

    # 5. Nonce consumption callback for Dynamic QR
    def check_and_consume_nonce(nonce_str: str) -> bool:
        if db.is_qr_nonce_consumed(nonce_str):
            return True  # Replay detected
        if matched_student:
            db.mark_qr_nonce_consumed(nonce_str, matched_student["id"])
        return False

    # 6. Evaluate via MultiLayerVerificationEngine
    policy = VerificationPolicy(
        require_face=True,
        require_liveness=True,
        require_location=GEOFENCE_ENABLED,
        require_qr=req_qr
    )
    evaluator = MultiLayerVerificationEngine(policy=policy)

    student_coords = (payload.latitude, payload.longitude) if (payload.latitude is not None and payload.longitude is not None) else None

    eval_result = evaluator.evaluate(
        face_match=face_match_data,
        liveness_data=liveness_data,
        student_coords=student_coords,
        location_accuracy=payload.accuracy,
        target_coords=target_coords,
        target_radius_m=target_radius,
        qr_token_str=payload.qr_token,
        qr_nonce_consumed_fn=check_and_consume_nonce if payload.qr_token else None,
        is_already_marked=is_already_marked,
        is_session_active=is_session_active
    )

    # 7. Record Verification Event to Database
    student_id = matched_student["id"] if matched_student else 0
    if student_id:
        db.record_verification_result(
            student_id=student_id,
            overall_status=eval_result.overall_status.value,
            session_id=payload.session_id,
            lecture_id=payload.lecture_id,
            face_match_score=eval_result.face_score,
            face_status=eval_result.face_status,
            liveness_status=eval_result.liveness_status,
            liveness_texture_score=eval_result.liveness_score,
            location_status=eval_result.location_status,
            location_distance_m=eval_result.location_distance_m,
            qr_status=eval_result.qr_status,
            rejection_reason=eval_result.primary_reason.value
        )

    # 8. If VERIFIED, record official attendance
    if eval_result.overall_status == VerificationStatus.VERIFIED and matched_student:
        now_dt = datetime.now()
        date_str = now_dt.strftime("%Y-%m-%d")
        time_str = now_dt.strftime("%H:%M:%S")

        db.record_offline_attendance(
            student_id=matched_student["id"],
            lecture_id=payload.lecture_id or 1,
            date_str=date_str,
            time_str=time_str,
            verification_method="SMARTATTEND_MULTI_LAYER"
        )

        # Send instant notification
        if notification_service and matched_student.get("email"):
            sub_name = session_info.get("subject_name", "Scheduled Class") if session_info else "Class"
            notification_service.notify_attendance_marked(
                student_id=matched_student["id"],
                student_name=matched_student["name"],
                student_email=matched_student["email"],
                subject_name=sub_name,
                timestamp=time_str
            )

    return eval_result.to_dict()

# --- 3. Teacher Portal Endpoints ---
@app.get("/api/teacher/classes")
def get_teacher_classes(auth_user: Dict[str, Any] = Depends(require_teacher)):
    """Returns assigned subjects, classrooms, and timetables for the teacher"""
    teacher_id = auth_user.get("uid")
    assigned = db.get_teacher_assigned_subjects(teacher_id)
    timetables = db.get_timetables_by_teacher(teacher_id)
    return {"assigned_subjects": assigned, "timetables": timetables}

@app.post("/api/teacher/sessions/start")
def start_attendance_session(payload: TeacherSessionStartRequest, auth_user: Dict[str, Any] = Depends(require_teacher)):
    """Teacher initiates an active attendance session for a class"""
    teacher_id = auth_user.get("uid")
    ok, msg, sess_id = db.create_attendance_session(
        teacher_id=teacher_id,
        subject_id=payload.subject_id,
        classroom_id=payload.classroom_id,
        lecture_id=payload.lecture_id,
        qr_expiry_seconds=payload.qr_expiry_seconds,
        require_face=payload.require_face,
        require_location=payload.require_location,
        require_qr=payload.require_qr
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "session_id": sess_id}

@app.post("/api/teacher/sessions/{session_id}/end")
def end_attendance_session_endpoint(session_id: int, auth_user: Dict[str, Any] = Depends(require_teacher)):
    """Closes an active attendance session"""
    teacher_id = auth_user.get("uid")
    ok, msg = db.end_attendance_session(session_id, teacher_id=teacher_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

@app.get("/api/teacher/sessions/{session_id}/qr")
def get_dynamic_session_qr(session_id: int, auth_user: Dict[str, Any] = Depends(require_teacher)):
    """
    Generates a cryptographically signed, rotating one-time QR token for the classroom.
    Default expiry: 30 seconds.
    """
    sess = db.get_session_by_id(session_id)
    if not sess or sess.get("status") != "ACTIVE":
        raise HTTPException(status_code=400, detail="Session is not active or does not exist.")

    expiry_secs = sess.get("qr_expiry_seconds", 30)
    token_str, payload = generate_qr_token(
        session_id=session_id,
        classroom_id=sess.get("classroom_id") or 0,
        teacher_id=sess.get("teacher_id") or auth_user.get("uid"),
        expiry_seconds=expiry_secs
    )

    # Store nonce in DB
    db.store_qr_token(
        nonce=payload["nonce"],
        session_id=session_id,
        teacher_id=sess.get("teacher_id") or auth_user.get("uid"),
        classroom_id=sess.get("classroom_id"),
        expiry_seconds=expiry_secs
    )

    return {
        "session_id": session_id,
        "qr_token": token_str,
        "expires_in_seconds": expiry_secs,
        "issued_at": payload["iat"],
        "expires_at": payload["exp"]
    }

@app.get("/api/teacher/leaves")
def get_teacher_leave_requests(auth_user: Dict[str, Any] = Depends(require_teacher)):
    """Returns student leave requests pending review"""
    pending = db.get_pending_leave_requests()
    return {"leave_requests": pending, "count": len(pending)}

@app.post("/api/teacher/leaves/{request_id}/review")
def review_leave_endpoint(request_id: int, payload: LeaveReviewRequest, auth_user: Dict[str, Any] = Depends(require_teacher)):
    """Teacher approves or rejects a student's leave request"""
    reviewer = auth_user.get("sub") or "Teacher"
    ok, msg = db.review_leave_request(request_id, payload.decision, reviewer, payload.comment)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

# --- 4. Student Portal Endpoints ---
@app.get("/api/student/dashboard")
def get_student_dashboard(auth_user: Dict[str, Any] = Depends(require_student)):
    """Returns attendance percentage, subject-wise statistics, and shortage alerts for the student"""
    student_id = auth_user.get("uid")
    stats = db.get_student_attendance_stats(student_id)
    subjects = db.get_student_subject_breakdown(student_id)
    history = db.get_student_lecture_history(student_id, limit=10)

    # Compute prediction and risk
    prediction = analytics_engine.predict_student_attendance(student_id) if analytics_engine else {}

    return {
        "stats": stats,
        "subjects": subjects,
        "recent_history": history,
        "prediction": prediction,
        "is_shortage": stats.get("percentage", 0.0) < 75.0
    }

@app.get("/api/student/attendance")
def get_student_attendance_history(auth_user: Dict[str, Any] = Depends(require_student), limit: int = 50):
    """Returns daily attendance ledger for the authenticated student"""
    student_id = auth_user.get("uid")
    history = db.get_student_lecture_history(student_id, limit=limit)
    return {"history": history, "count": len(history)}

@app.post("/api/student/leaves")
def submit_student_leave(payload: LeaveSubmitRequest, auth_user: Dict[str, Any] = Depends(require_student)):
    """Student submits an official or medical leave application"""
    student_id = auth_user.get("uid")
    ok, msg, req_id = db.submit_leave_request(
        student_id=student_id,
        leave_type=payload.leave_type,
        from_date=payload.from_date,
        to_date=payload.to_date,
        reason=payload.reason
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "request_id": req_id}

@app.get("/api/student/leaves")
def get_student_leaves(auth_user: Dict[str, Any] = Depends(require_student)):
    """Returns leave history and approval status for the authenticated student"""
    student_id = auth_user.get("uid")
    leaves = db.get_student_leave_requests(student_id)
    return {"leave_requests": leaves, "count": len(leaves)}

# --- 5. Parent Portal Endpoints ---
@app.get("/api/parent/wards")
def get_parent_wards_summary(auth_user: Dict[str, Any] = Depends(require_parent)):
    """Returns linked wards with attendance summaries for parents"""
    parent_id = auth_user.get("uid")
    wards = db.get_parent_wards(parent_id)
    ward_summaries = []
    for w in wards:
        stats = db.get_student_attendance_stats(w["id"])
        ward_summaries.append({**w, **stats})
    return {"wards": ward_summaries}

# --- 6. Admin Portal Extended Management Endpoints ---
@app.get("/api/admin/departments")
def list_departments(admin: str = Depends(require_admin)):
    return {"departments": db.get_departments()}

@app.post("/api/admin/departments")
def create_dept(payload: DepartmentCreateRequest, admin: str = Depends(require_admin)):
    ok, msg, dept_id = db.create_department(payload.name, payload.code, payload.head_teacher_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "id": dept_id}

@app.get("/api/admin/courses")
def list_courses(department_id: Optional[int] = None, admin: str = Depends(require_admin)):
    return {"courses": db.get_courses(department_id)}

@app.post("/api/admin/courses")
def create_course_endpoint(payload: CourseCreateRequest, admin: str = Depends(require_admin)):
    ok, msg, cid = db.create_course(payload.department_id, payload.name, payload.code, payload.semester, payload.credits)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "id": cid}

@app.get("/api/admin/subjects")
def list_subjects(course_id: Optional[int] = None, admin: str = Depends(require_admin)):
    return {"subjects": db.get_subjects(course_id)}

@app.post("/api/admin/subjects")
def create_sub(payload: SubjectCreateRequest, admin: str = Depends(require_admin)):
    ok, msg, sid = db.create_subject(payload.course_id, payload.name, payload.code, payload.type)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "id": sid}

@app.get("/api/admin/classrooms")
def list_classrooms(admin: str = Depends(require_admin)):
    return {"classrooms": db.get_classrooms()}

@app.post("/api/admin/classrooms")
def create_cls(payload: ClassroomCreateRequest, admin: str = Depends(require_admin)):
    ok, msg, cid = db.create_classroom(
        name=payload.name,
        building=payload.building,
        floor=payload.floor,
        capacity=payload.capacity,
        campus_id=payload.campus_id,
        latitude=payload.latitude,
        longitude=payload.longitude
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "id": cid}

@app.get("/api/admin/teachers")
def list_teachers(department_id: Optional[int] = None, admin: str = Depends(require_admin)):
    return {"teachers": db.get_teachers(department_id)}

@app.post("/api/admin/teachers")
def create_teacher_endpoint(payload: TeacherCreateRequest, admin: str = Depends(require_admin)):
    ok_pw, pw_msg = validate_password_strength(payload.password)
    if not ok_pw:
        raise HTTPException(status_code=400, detail=pw_msg)
    ok, msg, tid = db.create_teacher(
        employee_id=payload.employee_id,
        name=payload.name,
        email=payload.email,
        password=payload.password,
        department_id=payload.department_id
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "id": tid}

@app.post("/api/admin/teachers/assign")
def assign_teacher_subject_endpoint(payload: TeacherAssignRequest, admin: str = Depends(require_admin)):
    ok, msg = db.assign_teacher_subject(payload.teacher_id, payload.subject_id, payload.classroom_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

@app.get("/api/admin/cameras")
def list_cameras(admin: str = Depends(require_admin)):
    return {"cameras": db.get_cameras()}

@app.post("/api/admin/cameras")
def create_cam(payload: CameraCreateRequest, admin: str = Depends(require_admin)):
    ok, msg, cid = db.create_camera(payload.camera_uid, payload.name, payload.api_key, payload.classroom_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "id": cid}

@app.get("/api/admin/beacons")
def list_beacons(admin: str = Depends(require_admin)):
    return {"beacons": db.get_beacons()}

@app.post("/api/admin/beacons")
def create_bcn(payload: BeaconCreateRequest, admin: str = Depends(require_admin)):
    ok, msg, bid = db.create_beacon(payload.beacon_uuid, payload.name, payload.classroom_id, payload.major, payload.minor)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "id": bid}

@app.get("/api/admin/timetables")
def list_timetables(teacher_id: int, admin: str = Depends(require_admin)):
    return {"timetables": db.get_timetables_by_teacher(teacher_id)}

@app.post("/api/admin/timetables")
def create_tt(payload: TimetableCreateRequest, admin: str = Depends(require_admin)):
    ok, msg, tid = db.create_timetable_entry(
        subject_id=payload.subject_id,
        teacher_id=payload.teacher_id,
        day_of_week=payload.day_of_week,
        start_time=payload.start_time,
        end_time=payload.end_time,
        classroom_id=payload.classroom_id
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "id": tid}

@app.get("/api/admin/holidays")
def list_holidays(admin: str = Depends(require_admin)):
    return {"holidays": db.get_holidays()}

@app.post("/api/admin/holidays")
def add_hol(payload: HolidayCreateRequest, admin: str = Depends(require_admin)):
    ok, msg = db.add_holiday(payload.date, payload.name, payload.type)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

@app.get("/api/admin/verification-reviews")
def list_pending_verification_reviews(admin: str = Depends(require_admin)):
    """Returns borderline attendance events flagged for manual administrative review"""
    reviews = db.get_pending_verification_reviews()
    return {"reviews": reviews, "count": len(reviews)}

@app.post("/api/admin/verification-reviews/{result_id}")
def resolve_verification_review(result_id: int, decision: str, admin: str = Depends(require_admin)):
    """Approves or rejects a borderline attendance flag"""
    if decision not in ("VERIFIED", "REJECTED"):
        raise HTTPException(status_code=400, detail="Decision must be VERIFIED or REJECTED")
    ok = db.review_verification_result(result_id, decision, reviewed_by=admin)
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to update verification review.")
    return {"success": True, "message": f"Review marked as {decision}."}

# --- 7. AI & Predictive Analytics Endpoints (Phase 7) ---
@app.get("/api/analytics/student/{student_id}/prediction")
def get_student_prediction(student_id: int, user: Dict[str, Any] = Depends(require_auth)):
    """Advisory attendance forecasting and early warning indicators"""
    if not analytics_engine:
        raise HTTPException(status_code=503, detail="Analytics service not available")
    return analytics_engine.predict_student_attendance(student_id)

@app.get("/api/analytics/student/{student_id}/anomalies")
def get_student_anomalies(student_id: int, user: Dict[str, Any] = Depends(require_auth)):
    """Detects irregular bunking patterns or sudden absenteeism streaks"""
    if not analytics_engine:
        raise HTTPException(status_code=503, detail="Analytics service not available")
    return analytics_engine.detect_student_anomalies(student_id)

@app.get("/api/analytics/departments")
def get_department_analytics(admin: str = Depends(require_admin)):
    """Comparative attendance and risk metrics by department"""
    if not analytics_engine:
        raise HTTPException(status_code=503, detail="Analytics service not available")
    return {"departments": analytics_engine.get_department_comparative_analytics()}

@app.get("/api/analytics/trends")
def get_attendance_trends(months_back: int = 6, user: Dict[str, Any] = Depends(require_auth)):
    """Institutional monthly attendance trends and directional momentum"""
    if not analytics_engine:
        raise HTTPException(status_code=503, detail="Analytics service not available")
    return {"trends": analytics_engine.get_monthly_attendance_trends(months_back)}

# --- 8. Reports & Safe CSV Exports (Phase 10) ---
@app.get("/api/reports/attendance/csv")
def download_attendance_csv(lecture_id: Optional[int] = None, date: Optional[str] = None, admin: str = Depends(require_admin)):
    """
    Exports attendance to CSV sanitized against formula injection (CWE-1236).
    """
    if not reports_engine:
        raise HTTPException(status_code=503, detail="Reports service not available")
    csv_content = reports_engine.export_attendance_csv(lecture_id=lecture_id, date_filter=date)
    filename = f"attendance_export_{date or 'all'}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/api/reports/students/csv")
def download_students_csv(department_id: Optional[int] = None, admin: str = Depends(require_admin)):
    """
    Exports student compliance summary to CSV with formula injection sanitization.
    """
    if not reports_engine:
        raise HTTPException(status_code=503, detail="Reports service not available")
    csv_content = reports_engine.export_student_summary_csv(department_id=department_id)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=students_attendance_summary.csv"}
    )

@app.get("/api/reports/heatmap")
def get_heatmap_data(student_id: Optional[int] = None, days_back: int = 90, user: Dict[str, Any] = Depends(require_auth)):
    """Daily attendance distribution data for calendar heatmaps"""
    if not reports_engine:
        raise HTTPException(status_code=503, detail="Reports service not available")
    return {"heatmap": reports_engine.get_attendance_heatmap_data(student_id=student_id, days_back=days_back)}

# --- 9. Offline Attendance Synchronization (Phase 14) ---
@app.post("/api/attendance/sync-offline")
def sync_offline_attendance(payload: OfflineSyncRequest, request: Request, user: Dict[str, Any] = Depends(require_auth)):
    """
    Synchronizes a batch of cryptographically signed offline attendance packets.
    Verifies signatures, prevents duplicate submissions, and validates against session active window.
    """
    if not offline_sync_engine:
        raise HTTPException(status_code=503, detail="Offline sync engine not available")
    
    submitted_by = user.get("sub") or "OFFLINE_CLIENT"
    result = offline_sync_engine.process_sync_batch(payload.packets, submitted_by=submitted_by)
    return result

# --- 10. Notifications Endpoints (Phase 8) ---
@app.get("/api/notifications")
def get_my_notifications(user: Dict[str, Any] = Depends(require_auth), limit: int = 20):
    """Returns recent notification alerts for the current user"""
    role = user.get("role", "STUDENT")
    uid = user.get("uid", 1)
    notifs = db.get_user_notifications(recipient_type=role, recipient_id=uid, limit=limit)
    return {"notifications": notifs}

@app.post("/api/notifications/test")
def test_notification_delivery(email: str, admin: str = Depends(require_admin)):
    """Sends a test email to verify SMTP configuration"""
    if not notification_service:
        raise HTTPException(status_code=503, detail="Notification service not ready")
    notif_id = notification_service.queue_notification(
        recipient_type="ADMIN",
        recipient_id=1,
        recipient_email=email,
        notification_type="TEST",
        subject="SmartAttend AI Test Notification",
        body="This is a test notification from SmartAttend AI verifying SMTP delivery configuration."
    )
    return {"success": True, "notification_id": notif_id, "message": f"Test notification queued for {email}."}

# --- Static Frontend Mounting ---
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "DeepVision AI API is running. Place frontend in /static/index.html."}

if __name__ == "__main__":
    import uvicorn
    import webbrowser
    import threading

    def open_browser():
        time.sleep(1.5)
        try:
            webbrowser.open(f"http://localhost:{PORT}")
        except Exception:
            pass

    print("\n" + "=" * 65)
    print(" 🚀 SmartAttend AI Server Started Successfully!")
    print("=" * 65)
    print(f" 👉 Open in your browser:  http://localhost:{PORT}")
    print(f" 👉 Loopback address:      http://127.0.0.1:{PORT}")
    print(" ⚠️  WINDOWS NOTE: Do NOT type 0.0.0.0 in your browser.")
    print("    Always use http://localhost:8000 or http://127.0.0.1:8000")
    print("=" * 65 + "\n")

    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run("server:app", host=HOST, port=PORT, reload=False)
