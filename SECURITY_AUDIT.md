# SmartAttend AI — Security Audit and Compliance Report

**System Name:** SmartAttend AI  
**Audit Scope:** Authentication, Authorization, Biometrics, Cryptography, API Security, Geofencing, Data Storage, and External Integrations  
**Compliance Standard:** Institutional Privacy & Cyber Hygiene Standards  
**Overall Security Posture:** **HARDENED & PRODUCTION-READY**  

---

## 1. Executive Summary

This security audit assesses the security posture of SmartAttend AI. The platform underwent comprehensive architectural hardening across identity management, biometric storage, cryptographic session signing, geofencing anti-proxy defenses, and spreadsheet export sanitization.

All default hardcoded credentials have been replaced with environment-based configuration. Production environments fail fast if critical secrets are omitted.

---

## 2. Threat Modeling & Defense Matrix

### A. Proxy Attendance Attacks (Buddy Punching)
- **Threat:** A student attempts to mark attendance for an absent friend using a photograph or by remote check-in from a dormitory/home.
- **Defenses Implemented:**
  1. **YuNet + SFace Biometric Pipeline:** Multi-angle landmark alignment and 128-D facial feature embeddings with cosine similarity thresholds.
  2. **Texture Anti-Spoofing:** Laplacian frequency variance analysis to differentiate between printed paper, digital screens, and 3D facial skin.
  3. **Temporal Landmark Motion:** Rejects static photos and non-responsive video replays.
  4. **GPS Geofencing:** Mathematical Haversine distance verification restricting attendance to configured classrooms/campuses.
  5. **Dynamic Rotating QR Codes:** 30-second cryptographic tokens with one-time server-side nonce consumption to prevent forwarded screenshots.

### B. CSV Formula Injection (CWE-1236)
- **Threat:** Malicious student names or roll numbers starting with `=`, `+`, `-`, `@`, `\t`, or `\r` executing remote commands when exported to Microsoft Excel or Google Sheets.
- **Defense Implemented:** `sanitize_csv_field()` automatically neutralizes any formula trigger characters by prefixing them with an apostrophe `'`.

### C. Replay Attacks on QR & Offline Attendance
- **Threat:** Intercepting a dynamic QR code token or offline attendance packet and re-submitting it repeatedly.
- **Defense Implemented:**
  - Dynamic QR tokens carry cryptographically signed unique nonces. Once consumed, the database marks them as consumed; subsequent attempts are rejected as `REPLAYED_QR`.
  - Offline packets require HMAC-SHA256 signatures over `(student_id, session_id, device_id, timestamp, nonce)`. Re-submissions are flagged as duplicates.

### D. GPS Spoofing Awareness & Noisy Sensor Escalation
- **Security Policy:** GPS coordinates can be spoofed by rooted devices or mock location applications.
- **Governance:** The platform **never relies on GPS as the sole proof of physical presence**. GPS is combined with live biometrics, liveness checks, and classroom-bound dynamic QR tokens.
- **Fairness Guarantee:** Weak indoor GPS accuracy does not trigger automated disciplinary action; borderline events are flagged as `PENDING_REVIEW` for human instructor evaluation.

---

## 3. Cryptographic and Authentication Security

1. **Password Hashing:**
   - PBKDF2-HMAC-SHA256 with cryptographically random 16-byte hex salts and 100,000 iterations.
   - Enforces minimum 8 characters, requiring uppercase, lowercase, and numerical or special characters.

2. **Session Token Architecture:**
   - Cryptographically signed HMAC-SHA256 tokens (`create_auth_token`):
     `base64url(payload).hmac_sha256_signature`
   - Incorporates user ID, username, assigned role, issuance timestamp, and expiration.
   - 24-hour expiration lifetime.

3. **Rate Limiting:**
   - In-memory sliding-window token bucket (`InMemoryRateLimiter`).
   - Protects `/api/auth/login` (maximum 5 failed attempts per 5 minutes per IP).
   - Protects `/api/recognize` and `/api/attendance/verify-multi-layer` against rapid denial-of-service or brute-force matching.

---

## 4. Biometric Data Privacy & Protection

1. **Storage Policy:**
   - Raw facial photographs are **never persisted to disk** during standard attendance operations.
   - Facial features are stored strictly as 128-dimensional floating-point mathematical vectors (`np.float32` BLOBs).
   - Biometric vectors cannot be reversed into original high-resolution human face photographs.

2. **Access Control:**
   - Facial feature embeddings are accessible only by the backend vision pipeline in RAM.
   - Public and student API responses strictly redact biometric vector BLOBs.

---

## 5. Configuration & Environment Security

1. **Secrets Management:**
   - `config.py` loads `SECRET_KEY`, `DEFAULT_ADMIN_PASS`, and SMTP credentials strictly from environment variables.
   - In production (`PRODUCTION=true` or `RAILWAY_ENVIRONMENT`), missing critical keys cause immediate process termination (`sys.exit(1)`).

2. **CORS Hardening:**
   - Wildcard `allow_origins=["*"]` is restricted to development. Production loads explicit domains from `ALLOWED_ORIGINS`.

3. **Exposed File Isolation:**
   - `.gitignore` and `.dockerignore` ensure that local databases (`*.db`), personal attendance CSV files, test artifacts, and sensitive keys are never committed or baked into container images.
