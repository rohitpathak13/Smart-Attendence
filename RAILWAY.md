# 🚀 Railway Deployment Guide: DeepVision AI

Deploy the **DeepVision AI Smart Face Attendance System** to [Railway](https://railway.app/) in less than 5 minutes.

---

## 🌟 Why Railway?
- **Zero Config Docker Support**: Railway automatically detects the included [`Dockerfile`](Dockerfile) and [`railway.json`](railway.json).
- **Free Automatic HTTPS**: Browsers require HTTPS to grant camera permissions (`navigator.mediaDevices.getUserMedia`). Railway provisions SSL certificates automatically on your custom or `.up.railway.app` domain.
- **Persistent Storage**: Attach a persistent volume so student biometric embeddings and SQLite attendance logs are never lost across redeployments.

---

## 📋 Step-by-Step Deployment

### Step 1: Push Project to GitHub
Ensure all your files are committed and pushed to your GitHub repository:
```bash
git add .
git commit -m "feat: make project ready for Railway deployment"
git push origin main
```

---

### Step 2: Create a New Project on Railway
1. Go to [railway.app](https://railway.app/) and sign in.
2. Click **"+ New Project"**.
3. Select **"Deploy from GitHub repo"**.
4. Choose your repository: `Smart-Attendence` (or your repository name).
5. Click **"Deploy Now"**.

---

### Step 3: Add a Persistent Volume (Crucial for Data Persistence)
By default, cloud containers have an ephemeral filesystem. To ensure your student database (`attendance_system.db`) persists across deployments and restarts:

1. In your Railway project dashboard, click on your service.
2. Go to the **"Volumes"** tab.
3. Click **"+ Add Volume"**.
4. Set the **Mount Path** to:
   ```
   /app/data
   ```
5. Click **Add**.

---

### Step 4: Configure Environment Variables (Optional)
Navigate to the **"Variables"** tab in your Railway service to customize any settings:

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `PORT` | *(Provided by Railway)* | The HTTP port dynamically assigned by Railway |
| `DATA_DIR` | `/app/data` | Path to persistent storage volume |
| `DEFAULT_ADMIN_USER` | `admin` | Initial administrator username |
| `DEFAULT_ADMIN_PASS` | `admin123` | Initial administrator password |
| `COOLDOWN_MINUTES` | `5` | Minutes before the same student can record attendance again |
| `LATE_CUTOFF_TIME` | `09:15:00` | Cutoff time after which attendance is marked `LATE` |
| `CONFIDENCE_THRESHOLD` | `0.60` | YuNet face detector confidence threshold |
| `COSINE_SIMILARITY_THRESHOLD` | `0.363` | SFace ArcFace cosine similarity match threshold |

---

### Step 5: Generate Public Domain (HTTPS)
1. Go to the **"Settings"** tab of your service on Railway.
2. Scroll down to the **"Networking"** section.
3. Click **"Generate Domain"** (e.g. `deepvision-production.up.railway.app`).
4. Railway will generate an SSL-secured HTTPS link.

---

## 📱 Using the System

### 1. Contactless Live Attendance
- Open your Railway domain in any browser (Chrome, Safari, Firefox, Edge on desktop or mobile).
- Click **"Start Camera"** and allow camera access.
- Position your face in front of the camera:
  - Real-time **YuNet face detection** locates faces with corner brackets.
  - **SFace ArcFace engine** compares the 128-D vector with registered students.
  - **Anti-spoofing engine** checks liveness.
  - An **audio chime** plays and a notification toast confirms attendance marked as `PRESENT` or `LATE`.
  - The live attendance table and KPI counters update instantaneously!

### 2. Enrolling New Students
1. Switch to the **"Enroll Student"** tab.
2. Fill in **Roll ID**, **Full Name**, **Department**, and **Email**.
3. Turn on the camera and click **"📸 Snap Photo"** (or upload an image file).
4. Click **"💾 Register Student & Face"**. The system extracts the 128-D embedding into SQLite immediately—**no retraining required**!

### 3. Reports & CSV Export
1. Switch to the **"Reports & Export"** tab.
2. Pick any date from the date picker and click **"Load Records"**.
3. Click **"📥 Export CSV"** to download an audit-ready attendance sheet.

### 4. Interactive API Documentation
You can also access the automated Swagger/OpenAPI documentation directly at:
```
https://<your-project>.up.railway.app/docs
```

---

## 💻 Local Testing Before Deployment

You can also run the web server locally anytime:
```bash
pip install -r requirements.txt
python server.py
```
Or with Uvicorn:
```bash
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```
Then visit [http://localhost:8000](http://localhost:8000).
