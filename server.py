"""
DeepVision AI - Cloud & Web Server (FastAPI)
Optimized for Railway Cloud Deployment and Browser-Based Contactless Attendance
"""
import base64
import io
import os
import sys
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

import cv2
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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
    EXPORTS_DIR
)
from core.model_loader import ensure_models_exist
from core.face_engine import FaceEngine
from core.liveness import LivenessDetector
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
    print(" Starting DeepVision Web Server for Railway Deployment")
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
    description="Contactless Facial Recognition Attendance System powered by YuNet & SFace ArcFace Deep Learning",
    version="2.0.0",
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

# --- Request / Response Models ---
class FrameRecognitionRequest(BaseModel):
    image: str
    mark_attendance: bool = True
    session_id: Optional[str] = "web_client"

class EnrollStudentRequest(BaseModel):
    roll_no: str
    name: str
    department: Optional[str] = "General"
    email: Optional[str] = ""
    image: str

class AdminLoginRequest(BaseModel):
    username: str
    password: str

class AdminPasswordChangeRequest(BaseModel):
    username: str
    old_password: str
    new_password: str

# --- Endpoints ---

@app.get("/health")
def health_check():
    """Railway Healthcheck Probe Endpoint"""
    return {
        "status": "healthy",
        "service": "DeepVision AI Face Attendance System",
        "models_loaded": engine is not None,
        "students_count": len(cached_students),
        "cooldown_minutes": COOLDOWN_MINUTES,
        "late_cutoff": LATE_CUTOFF_TIME,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/api/recognize")
def recognize_frame(payload: FrameRecognitionRequest):
    """
    Processes a frame captured from the user's browser webcam.
    Performs:
    1. YuNet Face Detection
    2. SFace ArcFace 128-D Embedding
    3. Liveness / Anti-spoofing check
    4. Student Identification & Attendance Recording
    """
    if engine is None or db is None:
        raise HTTPException(status_code=503, detail="Face engine not ready")

    frame = decode_image_base64(payload.image)
    detected_faces = engine.detect_faces(frame)

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
            success, message, record_info = db.mark_attendance(
                student_id=matched_student["id"],
                confidence=match_score,
                cooldown_minutes=COOLDOWN_MINUTES,
                late_cutoff=LATE_CUTOFF_TIME
            )
            attendance_event = {
                "recorded": success,
                "message": message,
                "record": record_info
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
            "attendance": attendance_event
        })

    return {
        "faces_detected": len(results),
        "results": results,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/api/students/enroll")
def enroll_student(payload: EnrollStudentRequest):
    """
    Enrolls a new student using an image captured from webcam or uploaded.
    Extracts 128-D ArcFace embedding and persists to SQLite database.
    """
    if engine is None or db is None:
        raise HTTPException(status_code=503, detail="Face engine not ready")

    roll_no = payload.roll_no.strip()
    name = payload.name.strip()
    if not roll_no or not name:
        raise HTTPException(status_code=400, detail="Roll number and name are required.")

    frame = decode_image_base64(payload.image)
    faces = engine.detect_faces(frame)

    if len(faces) == 0:
        raise HTTPException(status_code=400, detail="No face detected in the image. Please position your face clearly in good lighting.")
    if len(faces) > 1:
        raise HTTPException(status_code=400, detail=f"{len(faces)} faces detected. Only one person must be present during enrollment.")

    face = faces[0]
    emb = engine.extract_embedding(frame, face["raw"])

    success, msg = db.register_student(
        roll_no=roll_no,
        name=name,
        department=payload.department or "General",
        email=payload.email or "",
        embedding=emb
    )

    if not success:
        raise HTTPException(status_code=400, detail=msg)

    # Reload memory cache
    reload_student_cache()

    return {
        "success": True,
        "message": msg,
        "student": {
            "roll_no": roll_no,
            "name": name,
            "department": payload.department or "General",
            "email": payload.email or ""
        }
    }

@app.get("/api/students")
def get_students():
    """Returns all enrolled students (metadata only, omitting binary vectors)"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    students = db.get_all_students()
    # Strip raw embedding from JSON response
    sanitized = [
        {
            "id": s["id"],
            "roll_no": s["roll_no"],
            "name": s["name"],
            "department": s["department"],
            "email": s["email"],
            "created_at": s["created_at"]
        }
        for s in students
    ]
    return {"students": sanitized, "count": len(sanitized)}

@app.delete("/api/students/{roll_no}")
def delete_student(roll_no: str):
    """Deletes an enrolled student by roll number"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    ok, msg = db.delete_student(roll_no)
    if not ok:
        raise HTTPException(status_code=404, detail=msg)
    reload_student_cache()
    return {"success": True, "message": msg}

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

@app.post("/api/admin/login")
def admin_login(payload: AdminLoginRequest):
    """Verifies admin credentials"""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    if db.verify_admin(payload.username, payload.password):
        return {"success": True, "message": "Authentication successful", "username": payload.username}
    raise HTTPException(status_code=401, detail="Invalid username or password")

@app.post("/api/admin/change-password")
def admin_change_password(payload: AdminPasswordChangeRequest):
    """Changes admin password"""
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
