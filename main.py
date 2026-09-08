"""
DeepVision - AI-Powered Face Attendance Monitoring System
Main Application Bootstrap
"""
import tkinter as tk
import os
import sys

from config import DB_PATH, YUNET_MODEL_PATH, SFACE_MODEL_PATH, DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASS
from database.db_manager import DatabaseManager
from core.model_loader import ensure_models_exist
from core.face_engine import FaceEngine
from ui.app_window import AttendanceApp

def main():
    print("=" * 60)
    print(" Initializing DeepVision Face Attendance System")
    print("=" * 60)

    # 1. Ensure Deep Learning Models are present
    print("[1/4] Verifying YuNet & SFace ONNX models...")
    if not ensure_models_exist():
        print("ERROR: Failed to load models. Please check your internet connection.")
        sys.exit(1)

    # 2. Initialize Database & Security
    print("[2/4] Connecting to SQLite Database...")
    db = DatabaseManager(DB_PATH)
    db.ensure_default_admin(DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASS)

    # 3. Initialize AI Vision Engine
    print("[3/4] Initializing Face Detection & ArcFace Recognition Engine...")
    engine = FaceEngine(YUNET_MODEL_PATH, SFACE_MODEL_PATH)

    # 4. Launch Modern User Interface
    print("[4/4] Launching GUI Dashboard...")
    root = tk.Tk()
    app = AttendanceApp(root, db, engine)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    
    print("System ready. Running application...")
    root.mainloop()

if __name__ == "__main__":
    main()