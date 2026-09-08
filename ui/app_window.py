import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import cv2
from PIL import Image, ImageTk
import numpy as np
import os
import sys
from datetime import datetime
from typing import Optional, List, Dict

# Ensure base directory is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import (
    CAMERA_INDEX,
    COOLDOWN_MINUTES,
    LATE_CUTOFF_TIME,
    EXPORTS_DIR
)
from database.db_manager import DatabaseManager
from core.face_engine import FaceEngine
from core.liveness import LivenessDetector
from core.video_capture import ThreadedCamera

# Design Palette
THEME = {
    "bg": "#0f172a",          # Slate 900
    "panel": "#1e293b",       # Slate 800
    "card": "#334155",        # Slate 700
    "primary": "#6366f1",     # Indigo 500
    "primary_hover": "#4f46e5",
    "success": "#10b981",     # Emerald 500
    "warning": "#f59e0b",     # Amber 500
    "danger": "#ef4444",      # Rose 500
    "text_main": "#f8fafc",   # Slate 50
    "text_muted": "#94a3b8",  # Slate 400
    "border": "#475569"
}

class AttendanceApp:
    def __init__(self, root: tk.Tk, db: DatabaseManager, engine: FaceEngine):
        self.root = root
        self.db = db
        self.engine = engine
        self.liveness = LivenessDetector()

        self.root.title("DeepVision - AI Face Attendance System")
        self.root.geometry("1360x780")
        self.root.minsize(1200, 700)
        self.root.configure(bg=THEME["bg"])

        # Cache of registered students
        self.cached_students: List[Dict] = []
        self.reload_students()

        # Camera & State
        self.camera: Optional[ThreadedCamera] = None
        self.is_camera_running = False
        self.latest_frame: Optional[np.ndarray] = None
        self.enable_liveness = True

        # Notification banner timer
        self.banner_clear_after = None

        self._setup_styles()
        self._build_header()
        self._build_layout()

        # Start Camera automatically
        self.start_camera()

        # Schedule UI Loops
        self.update_clock()
        self.update_video_feed()

    def reload_students(self):
        self.cached_students = self.db.get_all_students()

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        # Configure Notebook (Tabs)
        style.configure("TNotebook", background=THEME["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", 
                        background=THEME["panel"], 
                        foreground=THEME["text_muted"], 
                        padding=[16, 8],
                        font=("Segoe UI", 11, "bold"))
        style.map("TNotebook.Tab",
                  background=[("selected", THEME["primary"])],
                  foreground=[("selected", THEME["text_main"])])

        # Configure Treeview (Tables)
        style.configure("Treeview",
                        background=THEME["panel"],
                        foreground=THEME["text_main"],
                        fieldbackground=THEME["panel"],
                        rowheight=32,
                        font=("Segoe UI", 10))
        style.configure("Treeview.Heading",
                        background=THEME["card"],
                        foreground=THEME["text_main"],
                        font=("Segoe UI", 10, "bold"),
                        padding=[8, 8])
        style.map("Treeview",
                  background=[("selected", THEME["primary"])],
                  foreground=[("selected", THEME["text_main"])])

    def _build_header(self):
        header_frame = tk.Frame(self.root, bg=THEME["panel"], height=70)
        header_frame.pack(side="top", fill="x", padx=16, pady=(12, 8))
        header_frame.pack_propagate(False)

        # Title & Subtitle
        title_box = tk.Frame(header_frame, bg=THEME["panel"])
        title_box.pack(side="left", padx=16, pady=10)

        title_lbl = tk.Label(title_box, text="DeepVision Attendance", font=("Segoe UI", 18, "bold"),
                             fg=THEME["text_main"], bg=THEME["panel"])
        title_lbl.pack(anchor="w")

        sub_lbl = tk.Label(title_box, text="YuNet Detector • SFace ArcFace Embeddings • Anti-Spoof Liveness",
                           font=("Segoe UI", 9), fg=THEME["text_muted"], bg=THEME["panel"])
        sub_lbl.pack(anchor="w")

        # Clock & Date in Header
        self.clock_lbl = tk.Label(header_frame, text="", font=("Consolas", 15, "bold"),
                                  fg=THEME["primary"], bg=THEME["panel"])
        self.clock_lbl.pack(side="right", padx=20)

    def _build_layout(self):
        main_container = tk.Frame(self.root, bg=THEME["bg"])
        main_container.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        # --- Left Column: Video & Camera Controls ---
        left_col = tk.Frame(main_container, bg=THEME["panel"], width=620)
        left_col.pack(side="left", fill="both", padx=(0, 10), pady=0)
        left_col.pack_propagate(False)

        # Camera Display Header
        cam_header = tk.Frame(left_col, bg=THEME["panel"])
        cam_header.pack(fill="x", padx=12, pady=(10, 6))

        tk.Label(cam_header, text="Live Camera Feed", font=("Segoe UI", 12, "bold"),
                 fg=THEME["text_main"], bg=THEME["panel"]).pack(side="left")

        self.cam_status_lbl = tk.Label(cam_header, text="● Active", font=("Segoe UI", 10, "bold"),
                                       fg=THEME["success"], bg=THEME["panel"])
        self.cam_status_lbl.pack(side="right")

        # Video Canvas
        self.video_canvas = tk.Label(left_col, bg="#000000", width=580, height=435)
        self.video_canvas.pack(fill="both", expand=True, padx=12, pady=6)

        # In-App Notification Banner
        self.banner = tk.Label(left_col, text="Ready for attendance", font=("Segoe UI", 11, "bold"),
                               fg=THEME["text_main"], bg=THEME["card"], height=2)
        self.banner.pack(fill="x", padx=12, pady=(0, 8))

        # Camera Action Controls
        btn_bar = tk.Frame(left_col, bg=THEME["panel"])
        btn_bar.pack(fill="x", padx=12, pady=(0, 12))

        self.btn_toggle_cam = tk.Button(btn_bar, text="Pause Camera", command=self.toggle_camera,
                                        bg=THEME["card"], fg=THEME["text_main"],
                                        activebackground=THEME["primary"], font=("Segoe UI", 10, "bold"),
                                        relief="flat", padx=12, pady=6)
        self.btn_toggle_cam.pack(side="left", padx=(0, 8))

        self.chk_liveness_var = tk.BooleanVar(value=True)
        chk_liveness = tk.Checkbutton(btn_bar, text="Anti-Spoof Liveness", variable=self.chk_liveness_var,
                                      bg=THEME["panel"], fg=THEME["text_main"], selectcolor=THEME["card"],
                                      activebackground=THEME["panel"], activeforeground=THEME["text_main"],
                                      font=("Segoe UI", 10))
        chk_liveness.pack(side="left")

        # --- Right Column: Tabs (Live Attendance, Enrollment, Reports, Settings) ---
        right_col = tk.Frame(main_container, bg=THEME["panel"])
        right_col.pack(side="right", fill="both", expand=True, padx=(10, 0), pady=0)

        self.notebook = ttk.Notebook(right_col)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        # Tabs
        self.tab_attendance = tk.Frame(self.notebook, bg=THEME["panel"])
        self.tab_enrollment = tk.Frame(self.notebook, bg=THEME["panel"])
        self.tab_reports = tk.Frame(self.notebook, bg=THEME["panel"])
        self.tab_settings = tk.Frame(self.notebook, bg=THEME["panel"])

        self.notebook.add(self.tab_attendance, text=" Live Attendance ")
        self.notebook.add(self.tab_enrollment, text=" Enroll Student ")
        self.notebook.add(self.tab_reports, text=" Reports & Export ")
        self.notebook.add(self.tab_settings, text=" Settings ")

        self._build_attendance_tab()
        self._build_enrollment_tab()
        self._build_reports_tab()
        self._build_settings_tab()

    # --- TAB 1: Live Attendance ---
    def _build_attendance_tab(self):
        # Stats KPI Cards
        stats_frame = tk.Frame(self.tab_attendance, bg=THEME["panel"])
        stats_frame.pack(fill="x", padx=12, pady=10)

        self.stat_total_val = self._create_stat_card(stats_frame, "Total Enrolled", "0", THEME["primary"], 0)
        self.stat_present_val = self._create_stat_card(stats_frame, "Present Today", "0", THEME["success"], 1)
        self.stat_late_val = self._create_stat_card(stats_frame, "Late Today", "0", THEME["warning"], 2)

        # Attendance Table
        table_frame = tk.Frame(self.tab_attendance, bg=THEME["panel"])
        table_frame.pack(fill="both", expand=True, padx=12, pady=(5, 12))

        cols = ("roll_no", "name", "dept", "time", "status", "conf")
        self.tree_attendance = ttk.Treeview(table_frame, columns=cols, show="headings", height=12)
        self.tree_attendance.heading("roll_no", text="Roll No")
        self.tree_attendance.heading("name", text="Name")
        self.tree_attendance.heading("dept", text="Department")
        self.tree_attendance.heading("time", text="Time")
        self.tree_attendance.heading("status", text="Status")
        self.tree_attendance.heading("conf", text="Confidence")

        self.tree_attendance.column("roll_no", width=100, anchor="center")
        self.tree_attendance.column("name", width=140, anchor="w")
        self.tree_attendance.column("dept", width=110, anchor="center")
        self.tree_attendance.column("time", width=80, anchor="center")
        self.tree_attendance.column("status", width=90, anchor="center")
        self.tree_attendance.column("conf", width=90, anchor="center")

        scroll_y = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree_attendance.yview)
        self.tree_attendance.configure(yscrollcommand=scroll_y.set)

        self.tree_attendance.pack(side="left", fill="both", expand=True)
        scroll_y.pack(side="right", fill="y")

        self.refresh_today_attendance()

    def _create_stat_card(self, parent, title, initial_val, color, col_idx):
        card = tk.Frame(parent, bg=THEME["card"], padx=14, pady=10)
        card.grid(row=0, column=col_idx, padx=6, sticky="nsew")
        parent.grid_columnconfigure(col_idx, weight=1)

        tk.Label(card, text=title, font=("Segoe UI", 10), fg=THEME["text_muted"], bg=THEME["card"]).pack(anchor="w")
        val_lbl = tk.Label(card, text=initial_val, font=("Segoe UI", 18, "bold"), fg=color, bg=THEME["card"])
        val_lbl.pack(anchor="w", pady=(2, 0))
        return val_lbl

    def refresh_today_attendance(self):
        for item in self.tree_attendance.get_children():
            self.tree_attendance.delete(item)

        records = self.db.get_today_attendance()
        for r in records:
            conf_str = f"{int(r['confidence'] * 100)}%" if r['confidence'] <= 1.0 else f"{r['confidence']:.2f}"
            self.tree_attendance.insert("", "end", values=(
                r["roll_no"], r["name"], r.get("department", "General"),
                r["time"], r["status"], conf_str
            ))

        stats = self.db.get_today_stats()
        self.stat_total_val.config(text=str(stats["total_students"]))
        self.stat_present_val.config(text=str(stats["present_today"]))
        self.stat_late_val.config(text=str(stats["late_today"]))

    # --- TAB 2: Student Enrollment ---
    def _build_enrollment_tab(self):
        container = tk.Frame(self.tab_enrollment, bg=THEME["panel"], padx=20, pady=20)
        container.pack(fill="both", expand=True)

        tk.Label(container, text="Instant Face Enrollment", font=("Segoe UI", 14, "bold"),
                 fg=THEME["text_main"], bg=THEME["panel"]).pack(anchor="w", pady=(0, 4))
        tk.Label(container, text="Fill details, position face in camera, and click 'Capture & Enroll Face'.",
                 font=("Segoe UI", 9), fg=THEME["text_muted"], bg=THEME["panel"]).pack(anchor="w", pady=(0, 16))

        # Form Fields
        form_frame = tk.Frame(container, bg=THEME["panel"])
        form_frame.pack(fill="x", pady=6)

        self.reg_roll = self._create_input_field(form_frame, "Roll / Student ID *", 0)
        self.reg_name = self._create_input_field(form_frame, "Full Name *", 1)
        self.reg_dept = self._create_input_field(form_frame, "Department", 2, default="Computer Science")
        self.reg_email = self._create_input_field(form_frame, "Email Address", 3)

        # Action Buttons
        btn_box = tk.Frame(container, bg=THEME["panel"])
        btn_box.pack(fill="x", pady=20)

        btn_enroll = tk.Button(btn_box, text="📸 Capture & Enroll Face", command=self.enroll_student_from_camera,
                               bg=THEME["primary"], fg=THEME["text_main"], activebackground=THEME["primary_hover"],
                               font=("Segoe UI", 11, "bold"), relief="flat", padx=16, pady=8, cursor="hand2")
        btn_enroll.pack(side="left", padx=(0, 10))

        btn_clear = tk.Button(btn_box, text="Clear Form", command=self._clear_enroll_form,
                              bg=THEME["card"], fg=THEME["text_main"], font=("Segoe UI", 10),
                              relief="flat", padx=12, pady=8)
        btn_clear.pack(side="left")

        # Enrollment Feedback Box
        self.enroll_msg = tk.Label(container, text="", font=("Segoe UI", 10),
                                   fg=THEME["success"], bg=THEME["panel"])
        self.enroll_msg.pack(anchor="w", pady=10)

    def _create_input_field(self, parent, label, row_idx, default=""):
        tk.Label(parent, text=label, font=("Segoe UI", 10, "bold"),
                 fg=THEME["text_main"], bg=THEME["panel"]).grid(row=row_idx, column=0, sticky="w", pady=6)
        entry = tk.Entry(parent, font=("Segoe UI", 11), bg=THEME["card"], fg=THEME["text_main"],
                         insertbackground=THEME["text_main"], relief="flat", highlightthickness=1,
                         highlightbackground=THEME["border"], width=35)
        entry.grid(row=row_idx, column=1, sticky="ew", padx=12, pady=6)
        if default:
            entry.insert(0, default)
        return entry

    def _clear_enroll_form(self):
        self.reg_roll.delete(0, "end")
        self.reg_name.delete(0, "end")
        self.reg_email.delete(0, "end")
        self.enroll_msg.config(text="")

    def enroll_student_from_camera(self):
        roll = self.reg_roll.get().strip()
        name = self.reg_name.get().strip()
        dept = self.reg_dept.get().strip()
        email = self.reg_email.get().strip()

        if not roll or not name:
            messagebox.showwarning("Validation Error", "Please enter both Roll ID and Name.")
            return

        if self.latest_frame is None:
            messagebox.showerror("Camera Error", "Camera feed is not available. Ensure camera is started.")
            return

        # Detect face on current frame
        frame = self.latest_frame.copy()
        faces = self.engine.detect_faces(frame)

        if len(faces) == 0:
            messagebox.showwarning("No Face Detected", "No face was detected. Please face the camera with good lighting.")
            return
        elif len(faces) > 1:
            messagebox.showwarning("Multiple Faces", "Multiple faces detected. Please make sure only 1 person is in frame.")
            return

        # Extract 128-d ArcFace embedding
        raw_face = faces[0]["raw"]
        embedding = self.engine.extract_embedding(frame, raw_face)

        # Register in SQLite database
        ok, msg = self.db.register_student(roll, name, dept, email, embedding)
        if ok:
            self.reload_students()
            self.refresh_today_attendance()
            self._show_banner(f"Enrolled: {name} ({roll})", THEME["success"])
            self.enroll_msg.config(text=f"✓ Successfully enrolled {name} ({roll})!", fg=THEME["success"])
            messagebox.showinfo("Success", f"Student {name} ({roll}) has been enrolled successfully!")
            self._clear_enroll_form()
        else:
            messagebox.showerror("Error", msg)

    # --- TAB 3: Reports & Export ---
    def _build_reports_tab(self):
        container = tk.Frame(self.tab_reports, bg=THEME["panel"], padx=16, pady=16)
        container.pack(fill="both", expand=True)

        top_bar = tk.Frame(container, bg=THEME["panel"])
        top_bar.pack(fill="x", pady=(0, 10))

        tk.Label(top_bar, text="Date (YYYY-MM-DD):", font=("Segoe UI", 10, "bold"),
                 fg=THEME["text_main"], bg=THEME["panel"]).pack(side="left", padx=(0, 6))

        today_str = datetime.now().strftime("%Y-%m-%d")
        self.report_date_entry = tk.Entry(top_bar, font=("Segoe UI", 10), width=12,
                                          bg=THEME["card"], fg=THEME["text_main"], relief="flat")
        self.report_date_entry.insert(0, today_str)
        self.report_date_entry.pack(side="left", padx=(0, 12))

        btn_search = tk.Button(top_bar, text="Load Records", command=self.load_report_records,
                               bg=THEME["card"], fg=THEME["text_main"], font=("Segoe UI", 9, "bold"),
                               relief="flat", padx=10, pady=4)
        btn_search.pack(side="left", padx=(0, 8))

        btn_export = tk.Button(top_bar, text="📥 Export CSV", command=self.export_report_csv,
                               bg=THEME["success"], fg=THEME["text_main"], font=("Segoe UI", 9, "bold"),
                               relief="flat", padx=12, pady=4)
        btn_export.pack(side="right")

        # Report Treeview
        r_cols = ("roll_no", "name", "dept", "date", "time", "status", "conf")
        self.tree_reports = ttk.Treeview(container, columns=r_cols, show="headings")
        self.tree_reports.heading("roll_no", text="Roll No")
        self.tree_reports.heading("name", text="Name")
        self.tree_reports.heading("dept", text="Department")
        self.tree_reports.heading("date", text="Date")
        self.tree_reports.heading("time", text="Time")
        self.tree_reports.heading("status", text="Status")
        self.tree_reports.heading("conf", text="Confidence")

        self.tree_reports.column("roll_no", width=100, anchor="center")
        self.tree_reports.column("name", width=140, anchor="w")
        self.tree_reports.column("dept", width=110, anchor="center")
        self.tree_reports.column("date", width=100, anchor="center")
        self.tree_reports.column("time", width=80, anchor="center")
        self.tree_reports.column("status", width=90, anchor="center")
        self.tree_reports.column("conf", width=90, anchor="center")

        scroll_r = ttk.Scrollbar(container, orient="vertical", command=self.tree_reports.yview)
        self.tree_reports.configure(yscrollcommand=scroll_r.set)

        self.tree_reports.pack(side="left", fill="both", expand=True)
        scroll_r.pack(side="right", fill="y")

        self.load_report_records()

    def load_report_records(self):
        query_date = self.report_date_entry.get().strip()
        for item in self.tree_reports.get_children():
            self.tree_reports.delete(item)

        records = self.db.get_attendance_by_date(query_date)
        for r in records:
            conf_str = f"{int(r['confidence'] * 100)}%" if r['confidence'] <= 1.0 else f"{r['confidence']:.2f}"
            self.tree_reports.insert("", "end", values=(
                r["roll_no"], r["name"], r.get("department", "General"),
                r["date"], r["time"], r["status"], conf_str
            ))

    def export_report_csv(self):
        query_date = self.report_date_entry.get().strip()
        default_filename = f"Attendance_{query_date}.csv"
        default_path = os.path.join(EXPORTS_DIR, default_filename)

        save_path = filedialog.asksaveasfilename(
            initialdir=EXPORTS_DIR,
            initialfile=default_filename,
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )

        if not save_path:
            return

        ok, msg = self.db.export_attendance_csv(query_date, save_path)
        if ok:
            messagebox.showinfo("Export Successful", msg)
        else:
            messagebox.showwarning("Export", msg)

    # --- TAB 4: Settings ---
    def _build_settings_tab(self):
        container = tk.Frame(self.tab_settings, bg=THEME["panel"], padx=20, pady=20)
        container.pack(fill="both", expand=True)

        tk.Label(container, text="Security & System Settings", font=("Segoe UI", 14, "bold"),
                 fg=THEME["text_main"], bg=THEME["panel"]).pack(anchor="w", pady=(0, 16))

        # Change Password Box
        pw_box = tk.LabelFrame(container, text="Change Admin Password", font=("Segoe UI", 10, "bold"),
                               bg=THEME["panel"], fg=THEME["text_main"], padx=14, pady=12)
        pw_box.pack(fill="x", pady=(0, 16))

        self.set_old_pass = self._create_input_field(pw_box, "Old Password", 0)
        self.set_old_pass.config(show="*")
        self.set_new_pass = self._create_input_field(pw_box, "New Password", 1)
        self.set_new_pass.config(show="*")

        btn_save_pass = tk.Button(pw_box, text="Update Password", command=self._update_password,
                                  bg=THEME["primary"], fg=THEME["text_main"], font=("Segoe UI", 9, "bold"),
                                  relief="flat", padx=12, pady=6)
        btn_save_pass.grid(row=2, column=1, sticky="w", padx=12, pady=10)

        # Delete Student Box
        del_box = tk.LabelFrame(container, text="Manage Students", font=("Segoe UI", 10, "bold"),
                                bg=THEME["panel"], fg=THEME["text_main"], padx=14, pady=12)
        del_box.pack(fill="x")

        self.del_roll_entry = self._create_input_field(del_box, "Student Roll No to Delete", 0)
        btn_del = tk.Button(del_box, text="Delete Student", command=self._delete_student,
                            bg=THEME["danger"], fg=THEME["text_main"], font=("Segoe UI", 9, "bold"),
                            relief="flat", padx=12, pady=6)
        btn_del.grid(row=1, column=1, sticky="w", padx=12, pady=10)

    def _update_password(self):
        old_p = self.set_old_pass.get()
        new_p = self.set_new_pass.get()
        ok, msg = self.db.change_admin_password("admin", old_p, new_p)
        if ok:
            messagebox.showinfo("Success", msg)
            self.set_old_pass.delete(0, "end")
            self.set_new_pass.delete(0, "end")
        else:
            messagebox.showerror("Error", msg)

    def _delete_student(self):
        roll = self.del_roll_entry.get().strip()
        if not roll:
            return
        if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete student {roll}?"):
            ok, msg = self.db.delete_student(roll)
            if ok:
                self.reload_students()
                self.refresh_today_attendance()
                messagebox.showinfo("Deleted", msg)
                self.del_roll_entry.delete(0, "end")
            else:
                messagebox.showerror("Error", msg)

    # --- Video & Camera Logic ---
    def start_camera(self):
        try:
            self.camera = ThreadedCamera(src=CAMERA_INDEX, width=640, height=480).start()
            self.is_camera_running = True
            self.cam_status_lbl.config(text="● Active", fg=THEME["success"])
            self.btn_toggle_cam.config(text="Pause Camera")
        except Exception as e:
            self.cam_status_lbl.config(text="● Offline", fg=THEME["danger"])
            self._show_banner(f"Camera start failed: {e}", THEME["danger"])

    def stop_camera(self):
        self.is_camera_running = False
        if self.camera:
            self.camera.release()
            self.camera = None
        self.cam_status_lbl.config(text="● Paused", fg=THEME["warning"])
        self.btn_toggle_cam.config(text="Resume Camera")

    def toggle_camera(self):
        if self.is_camera_running:
            self.stop_camera()
        else:
            self.start_camera()

    def update_video_feed(self):
        if self.is_camera_running and self.camera:
            ret, frame = self.camera.read()
            if ret and frame is not None:
                self.latest_frame = frame
                display_frame = frame.copy()

                # Process faces
                faces = self.engine.detect_faces(frame)
                for face in faces:
                    x, y, w, h = face["bbox"]
                    landmarks = face["landmarks"]
                    raw_face = face["raw"]

                    # Extract feature & identify
                    feature = self.engine.extract_embedding(frame, raw_face)
                    matched_student, sim_score = self.engine.identify_face(feature, self.cached_students)

                    # Liveness Check
                    is_live = True
                    liveness_label = "Live"
                    if self.chk_liveness_var.get():
                        tracking_id = matched_student["roll_no"] if matched_student else f"{x}_{y}"
                        is_live, reason, _ = self.liveness.check_temporal_liveness(tracking_id, landmarks)
                        liveness_label = "Live" if is_live else "Spoof"

                    if matched_student:
                        student_name = matched_student["name"]
                        roll_no = matched_student["roll_no"]
                        pct = int(sim_score * 100)

                        if is_live:
                            box_color = (16, 185, 129) # Emerald Green (BGR)
                            label_text = f"{student_name} ({pct}%)"

                            # Attempt attendance mark
                            marked, reason, info = self.db.mark_attendance(
                                matched_student["id"],
                                confidence=sim_score,
                                cooldown_minutes=COOLDOWN_MINUTES,
                                late_cutoff=LATE_CUTOFF_TIME
                            )
                            if marked and info:
                                self.refresh_today_attendance()
                                self._show_banner(f"Attendance Marked: {student_name} ({info['status']})", THEME["success"])
                        else:
                            box_color = (68, 68, 239) # Red (Spoof)
                            label_text = f"{student_name} [SPOOF REJECT]"
                            self._show_banner(f"Warning: Spoof detected for {student_name}", THEME["danger"])
                    else:
                        box_color = (200, 200, 200) # Gray (Unknown)
                        label_text = "Unknown"

                    # Draw Bounding Box & Labels
                    cv2.rectangle(display_frame, (x, y), (x + w, y + h), box_color, 2)
                    
                    # Tag background
                    tag_h = 24
                    cv2.rectangle(display_frame, (x, max(0, y - tag_h)), (x + w, y), box_color, -1)
                    cv2.putText(display_frame, label_text, (x + 4, y - 6),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

                # Render frame on Canvas
                display_frame = cv2.resize(display_frame, (580, 435))
                rgb_frame = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(rgb_frame)
                imgtk = ImageTk.PhotoImage(image=img)
                self.video_canvas.imgtk = imgtk
                self.video_canvas.configure(image=imgtk)

        # Schedule next frame (30ms ~ 33 FPS)
        self.root.after(30, self.update_video_feed)

    def _show_banner(self, text: str, color: str):
        self.banner.config(text=text, fg=color)
        if self.banner_clear_after:
            self.root.after_cancel(self.banner_clear_after)
        self.banner_clear_after = self.root.after(4000, lambda: self.banner.config(text="Ready for attendance", fg=THEME["text_main"]))

    def update_clock(self):
        now_str = datetime.now().strftime("%A, %b %d %Y  |  %H:%M:%S")
        self.clock_lbl.config(text=now_str)
        self.root.after(500, self.update_clock)

    def on_closing(self):
        self.stop_camera()
        self.root.destroy()

