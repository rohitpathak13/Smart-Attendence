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
    INSTITUTION_TIMEZONE
)
from core.model_loader import ensure_models_exist
from core.face_engine import FaceEngine
from core.liveness import LivenessDetector
from core.validators import validate_email, validate_student_name, validate_roll_number
from core.geofence import verify_student_location, validate_coordinates, haversine_distance
from database.db_manager import DatabaseManager

# Global singletons
db: Optional[DatabaseManager] = None
engine: Optional[FaceEngine] = None
liveness: Optional[LivenessDetector] = None
cached_students: List[Dict] = []

def reload_student_cache():
    global cached_students, db
    if db:
        cached_students = db.get_all_students()
        print(f"[CACHE] Loaded {len(cached_students)} registered students into memory.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, engine, liveness
    print("=" * 60)
    print(" Starting DeepVision Web Server with Geofencing & Lecture Attendance")
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

    # 4. Cache students
    reload_student_cache()
    print("DeepVision API ready to accept connections.")
    yield
    print("Shutting down DeepVision Web Server...")

app = FastAPI(
    title="DeepVision AI Attendance API",
    description="Contactless Facial Recognition, Geofenced Attendance & Lecture Anti-Bunking System",
    version="3.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helper: Decode Base64 Image
def decode_image_base64(image_data: str) -> np.ndarray:
    if "," in image_data:
        image_data = image_data.split(",", 1)[1]
    try:
        raw_bytes = base64.b64decode(image_data)
        np_arr = np.frombuffer(raw_bytes, dtype=np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("cv2.imdecode returned None")
        return frame
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 image data: {str(e)}")

# --- Security & Admin Token Utilities ---
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
        # Strip Bearer prefix if present
        if token.startswith("Bearer "):
            token = token[7:].strip()
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        parts = decoded.split(":")
        if len(parts) != 3:
            return None
        username, ts_str, sig = parts
        payload = f"{username}:{ts_str}"
        expected_sig = hmac.new(SECRET_KEY.encode(), payload.encode(), "sha256").hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        # Token valid for 24 hours
        if time.time() - int(ts_str) > 86400:
            return None
        return username
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
        allow_admin_override=bool(payload.allow_admin_override)
    )

    if not success:
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
    uvicorn.run("server:app", host=HOST, port=PORT, reload=False)
