# SmartAttend AI — Production Deployment & Operations Guide

**Platform:** SmartAttend AI — Intelligent Location Verified Attendance and College Management Platform  
**Supported Deployments:** Local Workstation, On-Premises Server, Railway Cloud, Docker Container  

---

## 1. Quickstart — Local Development

### Prerequisites
- Python 3.10, 3.11, 3.12, or 3.13
- OpenCV compatible environment
- Webcam (built-in or USB)

### Installation Steps
```bash
# 1. Clone repository & navigate to directory
cd "Advanced attendance monitoring system"

# 2. Create and activate virtual environment
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Verify AI models exist (will auto-download if missing)
python -c "from core.model_loader import ensure_models_exist; ensure_models_exist()"

# 5. Run the full automated test suite (100/100 tests)
python -m pytest test_core.py test_validators.py test_geofence.py test_student_registration.py test_lecture_attendance.py test_acceptance.py test_smartattend.py test_anti_proxy.py test_ml_analytics.py test_notifications.py test_reports.py test_offline_sync.py test_api_v2.py -v

# 6. Launch the SmartAttend AI Server
python server.py
```
Open your browser at `http://localhost:8000`.

---

## 2. Docker Deployment

The application includes an optimized production `Dockerfile`.

```bash
# Build the container image
docker build -t smartattend-ai:latest .

# Run container with persistent data volume
docker run -d \
  -p 8000:8000 \
  -e SECRET_KEY="generate-a-strong-32-byte-hex-secret-key" \
  -e DEFAULT_ADMIN_PASS="ChangeThisAdminPass2026!" \
  -e ALLOWED_ORIGINS="https://college.edu,http://localhost:8000" \
  -v smartattend_data:/app/data \
  --name smartattend-server \
  smartattend-ai:latest
```

---

## 3. Railway Cloud Deployment

The repository includes `railway.json` configured for Docker builds with automatic healthcheck probes at `/health`.

### Steps on Railway:
1. Connect your GitHub repository to Railway.
2. Under **Service Settings > Variables**, configure:
   - `SECRET_KEY`: Long random cryptographic string.
   - `DEFAULT_ADMIN_PASS`: Strong administrator password.
   - `ALLOWED_ORIGINS`: Comma-separated domain names of your frontend/app.
   - `PRODUCTION`: `true`
3. Add a persistent volume mounted at `/app/data` to ensure SQLite database records persist across deployments.
4. Deploy the service. Railway will verify the `/health` endpoint before directing traffic.

---

## 4. Environment Variables Reference

| Variable | Required in Prod | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | **YES** | None (Fails fast) | Cryptographic key for HMAC tokens & QR signatures |
| `DEFAULT_ADMIN_PASS` | **YES** | None (Fails fast) | Initial password for the administrator account |
| `DEFAULT_ADMIN_USER` | No | `admin` | Administrator username |
| `ALLOWED_ORIGINS` | No | `*` (dev only) | Comma-separated list of allowed CORS origins |
| `PORT` | No | `8000` | Server listening port |
| `HOST` | No | `0.0.0.0` | Server listening interface |
| `PRODUCTION` | No | `""` | Enforces fail-fast validation when set to `true` |
| `GEOFENCE_RADIUS_METERS`| No | `30.0` | Default permitted classroom geofence radius |
| `CAMPUS_LATITUDE` | No | `28.5355` | Default institutional latitude |
| `CAMPUS_LONGITUDE` | No | `77.3910` | Default institutional longitude |
| `QR_TOKEN_EXPIRY_SECONDS`| No | `30` | Rotating dynamic QR token lifetime |
| `SMTP_HOST` | No | `""` | SMTP mail server hostname |
| `SMTP_PORT` | No | `587` | SMTP port (587 for STARTTLS) |
| `SMTP_USER` | No | `""` | SMTP authentication user |
| `SMTP_PASSWORD` | No | `""` | SMTP password |
| `SMTP_FROM` | No | `""` | From email address |
| `SMTP_USE_TLS` | No | `true` | Use STARTTLS for email delivery |

---

## 5. Security Fail-Fast Behavior

In production environments (indicated by `PRODUCTION=true` or `RAILWAY_ENVIRONMENT`), `config.py` enforces immediate shutdown if:
- `SECRET_KEY` is missing or empty.
- `DEFAULT_ADMIN_PASS` is missing or empty.

This prevents the server from ever booting in production with vulnerable default credentials.

---

## 6. Backup & Recovery

The entire database is self-contained in `data/attendance_system.db`.
To perform a hot backup:
```bash
sqlite3 data/attendance_system.db ".backup data/backup_$(date +%Y%m%d).db"
```
To restore:
```bash
cp data/backup_20261125.db data/attendance_system.db
```
