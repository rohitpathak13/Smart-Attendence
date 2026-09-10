# DeepVision: AI-Powered Smart Attendance Monitoring System

An enterprise-grade, contactless attendance monitoring system powered by Deep Learning, OpenCV, SQLite, and a modern Tkinter desktop GUI. 

---

## 🚀 Key Improvements Over Legacy LBPH Systems

| Feature | Legacy System (Haar + LBPH) | DeepVision (Modern Architecture) |
| :--- | :--- | :--- |
| **Face Detection** | Haar Cascade Classifier (sensitive to angles & light) | **YuNet (ONNX Deep Neural Network)** |
| **Face Recognition** | LBPH Recognizer (requires retraining every time) | **SFace (ArcFace 128-D Deep Feature Embeddings)** |
| **Student Enrollment** | 100 raw images to disk + manual retraining | **Instant 1-click snapshot $\rightarrow$ 128-D vector saved to DB** |
| **Anti-Spoofing** | None (vulnerable to printed photos & phone screens) | **Temporal Landmark Micro-Motion & Texture Analysis** |
| **Data Storage** | Fragile CSV files & plaintext passwords | **ACID SQLite Database + Salted PBKDF2 Password Hashing** |
| **Attendance Rules** | Buggy (only recorded last detected person) | **Automatic status (`PRESENT` / `LATE`), 30m duplicate cooldown** |
| **User Interface** | Comic Sans, blocking external OpenCV popups | **Modern Dark UI with embedded 30 FPS camera feed** |
| **Reporting** | Manual CSV checks | **Real-time KPI cards, date filtering, and 1-click CSV export** |

---

## 📂 Project Architecture

```
Andanced feature Attendance/
├── config.py                 # Central configurations (thresholds, timings, paths)
├── main.py                   # Clean application bootstrap entry point
├── main_legacy.py            # Backup of original legacy script
├── test_core.py              # Automated unit tests for DB, Vision & Liveness
├── requirements.txt          # Minimal required dependencies
│
├── core/                     # Computer Vision & AI Pipeline
│   ├── model_loader.py       # Auto-downloads official YuNet & SFace ONNX models
│   ├── face_engine.py        # YuNet detection & SFace cosine similarity matching
│   ├── liveness.py           # Anti-spoofing micro-motion & texture check
│   └── video_capture.py      # Threaded non-blocking camera capture
│
├── database/                 # Persistent Storage & Security
│   └── db_manager.py         # SQLite CRUD, PBKDF2 password hashing & CSV export
│
├── ui/                       # Modern Desktop Interface
│   └── app_window.py         # Embedded video, KPI cards, Enrollment & Reports
│
├── models/                   # Auto-managed deep learning ONNX models
├── data/                     # SQLite database (attendance_system.db)
└── exports/                  # Exported attendance CSV files
```

---

## 🛠️ Installation & Setup

### 1. Install Dependencies
Make sure you have Python 3.8+ installed. Install the required libraries:
```bash
pip install -r requirements.txt
```
*(Dependencies: `opencv-contrib-python`, `numpy`, `pandas`, `pillow`)*

### 2. Run the Application

#### Option A: Cloud Web Server & Browser Dashboard (Railway Ready)
Launch the FastAPI cloud web server:
```bash
python server.py
```
Open [http://localhost:8000](http://localhost:8000) in your browser.

#### Option B: Desktop Tkinter GUI
Launch the desktop native interface:
```bash
python main.py
```
> **Note:** On the first run, the application will automatically download the official OpenCV YuNet detector and SFace recognizer into the `models/` directory.

### 3. Deploy to Railway (Cloud)
To deploy this project to [Railway](https://railway.app/) in 1-click with zero-setup Docker & Persistent Volume, read the complete guide in [RAILWAY.md](RAILWAY.md).

### 4. Run Automated Tests

You can verify the database, face matching algorithms, and liveness detector at any time:
```bash
python test_core.py
```

---

## 📖 How to Use

### 1. Instant Student Enrollment
1. Open the application and switch to the **"Enroll Student"** tab on the right.
2. Enter the **Roll ID** (e.g., `CS101`), **Name**, and optional Department / Email.
3. Position the student in front of the camera.
4. Click **"📸 Capture & Enroll Face"**.
5. The system extracts the 128-dimensional ArcFace vector and stores it in the database immediately. **No retraining needed!**

### 2. Automatic Real-Time Attendance
1. Switch to the **"Live Attendance"** tab.
2. When an enrolled student approaches the camera:
   - A **green bounding box** with the student's name and confidence percentage appears.
   - The anti-spoofing engine verifies liveness.
   - Attendance is instantly recorded in the database and displayed in the live table.
   - If attendance is recorded after `09:15:00`, it is automatically tagged as **`LATE`**.
   - A **30-minute cooldown** prevents duplicate marks.

### 3. Reports & CSV Export
1. Switch to the **"Reports & Export"** tab.
2. Pick any date (defaults to today) and click **"Load Records"**.
3. Click **"📥 Export CSV"** to save a clean attendance sheet to the `exports/` folder or your preferred location.

### 4. Settings & Security
- Default Administrator Credentials:
  - **Username:** `admin`
  - **Password:** `admin123`
- Change admin passwords and manage student records from the **"Settings"** tab.