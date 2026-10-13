/**
 * DeepVision AI - Web Client Controller (Version 3.0)
 * Includes:
 * - Phase 17: College Location-Based Attendance (GPS Geofencing with accuracy checks)
 * - Phase 18: Student Email Validation (lowercase alphanumeric local part & uniqueness)
 * - Phase 19: Student Name Validation (Title Case / UPPERCASE, no digits, no mixed case)
 * - Phase 20: Numeric Roll Number Validation (digits 0-9 only, preserves leading zeros)
 * - Phase 21: Lecture-Wise Attendance & Anti-Bunking (50m default, window checks, mid-checks)
 * - Phase 22: Configuration & Administrator Controls (Role-based tokens & audit trail)
 */

// --- Global App State ---
const state = {
  isStreaming: false,
  stream: null,
  facingMode: "user",
  captureInterval: null,
  fpsCounter: 0,
  lastFpsTimestamp: performance.now(),
  enrollingStream: null,
  capturedEnrollBase64: null,
  audioCtx: null,
  // Geolocation State (Phase 17)
  userCoords: {
    latitude: null,
    longitude: null,
    accuracy: null,
    status: "idle", // 'idle', 'acquiring', 'locked', 'denied', 'unavailable', 'unsupported'
    errorMsg: ""
  },
  // Active Lecture Session (Phase 21)
  activeLecture: null,
  // Admin Session Token (Phase 22)
  adminToken: localStorage.getItem("dv_admin_token") || "",
  adminUser: localStorage.getItem("dv_admin_user") || "admin"
};

// --- DOM Elements ---
const el = {
  // Navigation
  navTabs: document.querySelectorAll(".nav-tab"),
  tabContents: document.querySelectorAll(".tab-content"),
  liveClock: document.getElementById("live-clock"),
  systemStatusPill: document.getElementById("system-status-pill"),
  systemStatusText: document.getElementById("system-status-text"),
  geofenceStatusPill: document.getElementById("geofence-status-pill"),
  geofenceStatusText: document.getElementById("geofence-status-text"),

  // KPIs
  kpiTotal: document.getElementById("kpi-total"),
  kpiPresent: document.getElementById("kpi-present"),
  kpiLate: document.getElementById("kpi-late"),
  kpiAbsent: document.getElementById("kpi-absent"),
  kpiMonthPct: document.getElementById("kpi-month-pct"),
  kpiMonthDays: document.getElementById("kpi-month-days"),

  // Active Lecture Banner
  activeLectureBanner: document.getElementById("active-lecture-banner"),
  bannerLectureTag: document.getElementById("banner-lecture-tag"),
  bannerLectureTitle: document.getElementById("banner-lecture-title"),
  bannerLectureMeta: document.getElementById("banner-lecture-meta"),
  btnBannerMidCheck: document.getElementById("btn-banner-mid-check"),

  // Live Camera & HUD
  webcam: document.getElementById("webcam"),
  hudCanvas: document.getElementById("hud-canvas"),
  cameraOverlay: document.getElementById("camera-overlay"),
  btnCameraToggle: document.getElementById("btn-camera-toggle"),
  btnCameraFlip: document.getElementById("btn-camera-flip"),
  btnCameraStartOverlay: document.getElementById("btn-camera-start-overlay"),
  streamFps: document.getElementById("stream-fps"),
  streamGpsStatus: document.getElementById("stream-gps-status"),
  livenessStatus: document.getElementById("liveness-status"),
  todayTableBody: document.getElementById("today-table-body"),
  btnRefreshFeed: document.getElementById("btn-refresh-feed"),

  // Enrollment (Phases 18, 19, 20)
  enrollForm: document.getElementById("enroll-form"),
  enrollRoll: document.getElementById("enroll-roll"),
  enrollName: document.getElementById("enroll-name"),
  enrollDept: document.getElementById("enroll-dept"),
  enrollEmail: document.getElementById("enroll-email"),
  errEnrollRoll: document.getElementById("err-enroll-roll"),
  errEnrollName: document.getElementById("err-enroll-name"),
  errEnrollEmail: document.getElementById("err-enroll-email"),
  enrollVideo: document.getElementById("enroll-video"),
  enrollCanvas: document.getElementById("enroll-canvas"),
  enrollPreviewImg: document.getElementById("enroll-preview-img"),
  enrollPlaceholder: document.getElementById("enroll-placeholder"),
  btnEnrollCamToggle: document.getElementById("btn-enroll-cam-toggle"),
  btnEnrollSnap: document.getElementById("btn-enroll-snap"),
  enrollFileInput: document.getElementById("enroll-file-input"),
  btnSubmitEnroll: document.getElementById("btn-submit-enroll"),

  // Lectures Tab (Phase 21)
  lectureForm: document.getElementById("lecture-form"),
  lecCourseCode: document.getElementById("lec-course-code"),
  lecSubjectName: document.getElementById("lec-subject-name"),
  lecInstructor: document.getElementById("lec-instructor"),
  lecDate: document.getElementById("lec-date"),
  lecStartTime: document.getElementById("lec-start-time"),
  lecDuration: document.getElementById("lec-duration"),
  lecRoom: document.getElementById("lec-room"),
  lecturesContainer: document.getElementById("lectures-container"),
  btnRefreshLectures: document.getElementById("btn-refresh-lectures"),
  analyticsTableBody: document.getElementById("analytics-table-body"),

  // Modal (Lecture Report & Corrections)
  lectureModal: document.getElementById("lecture-modal"),
  modalLectureTitle: document.getElementById("modal-lecture-title"),
  modalLectureSub: document.getElementById("modal-lecture-sub"),
  modalKpiPresent: document.getElementById("modal-kpi-present"),
  modalKpiLate: document.getElementById("modal-kpi-late"),
  modalKpiAbsent: document.getElementById("modal-kpi-absent"),
  modalKpiMid: document.getElementById("modal-kpi-mid"),
  modalStudentTbody: document.getElementById("modal-student-tbody"),
  btnCloseModal: document.getElementById("btn-close-modal"),

  // Reports
  reportDatePicker: document.getElementById("report-date-picker"),
  btnLoadReport: document.getElementById("btn-load-report"),
  btnExportCsv: document.getElementById("btn-export-csv"),
  reportTableBody: document.getElementById("report-table-body"),

  // Directory
  directorySearch: document.getElementById("directory-search"),
  directoryTableBody: document.getElementById("directory-table-body"),

  // Settings & Admin Controls (Phases 17, 22)
  adminAuthStatus: document.getElementById("admin-auth-status"),
  btnAdminRelogin: document.getElementById("btn-admin-relogin"),
  geofenceForm: document.getElementById("geofence-form"),
  cfgCampusName: document.getElementById("cfg-campus-name"),
  cfgCampusLat: document.getElementById("cfg-campus-lat"),
  cfgCampusLon: document.getElementById("cfg-campus-lon"),
  cfgCampusRadius: document.getElementById("cfg-campus-radius"),
  cfgCampusAccuracy: document.getElementById("cfg-campus-accuracy"),
  cfgGeofenceEnabled: document.getElementById("cfg-geofence-enabled"),
  radiusBtns: document.querySelectorAll(".radius-btn"),
  policiesForm: document.getElementById("policies-form"),
  cfgLectureDuration: document.getElementById("cfg-lecture-duration"),
  cfgWindowBefore: document.getElementById("cfg-window-before"),
  cfgWindowAfter: document.getElementById("cfg-window-after"),
  cfgLateCutoff: document.getElementById("cfg-late-cutoff"),
  cfgTimezone: document.getElementById("cfg-timezone"),
  cfgNumericRoll: document.getElementById("cfg-numeric-roll"),
  adminPasswordForm: document.getElementById("admin-password-form"),
  adminUser: document.getElementById("admin-user"),
  adminOldPass: document.getElementById("admin-old-pass"),
  adminNewPass: document.getElementById("admin-new-pass"),
  diagRadius: document.getElementById("diag-radius"),
  btnRefreshAudit: document.getElementById("btn-refresh-audit"),
  auditTableBody: document.getElementById("audit-table-body"),

  // Toast Container
  toastContainer: document.getElementById("toast-container")
};

// --- Web Audio Synthesizer (Chime) ---
function playAttendanceChime() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    if (!state.audioCtx) state.audioCtx = new AudioCtx();
    if (state.audioCtx.state === "suspended") state.audioCtx.resume();

    const now = state.audioCtx.currentTime;
    const osc1 = state.audioCtx.createOscillator();
    const osc2 = state.audioCtx.createOscillator();
    const gain = state.audioCtx.createGain();

    osc1.type = "sine";
    osc2.type = "sine";
    osc1.frequency.setValueAtTime(587.33, now); // D5
    osc1.frequency.exponentialRampToValueAtTime(880, now + 0.15); // A5

    osc2.frequency.setValueAtTime(440, now); // A4
    osc2.frequency.exponentialRampToValueAtTime(1174.66, now + 0.2); // D6

    gain.gain.setValueAtTime(0.2, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.45);

    osc1.connect(gain);
    osc2.connect(gain);
    gain.connect(state.audioCtx.destination);

    osc1.start(now);
    osc2.start(now);
    osc1.stop(now + 0.45);
    osc2.stop(now + 0.45);
  } catch (err) {
    console.debug("Audio play skipped:", err);
  }
}

// --- Toast Notifications ---
function showToast(title, message, type = "success") {
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  const icon = type === "success" ? "✓" : type === "warning" ? "⚠️" : "✕";

  toast.innerHTML = `
    <span class="toast-icon">${icon}</span>
    <div class="toast-body">
      <div class="toast-title">${title}</div>
      <div class="toast-msg">${message}</div>
    </div>
  `;

  el.toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(100%)";
    setTimeout(() => toast.remove(), 300);
  }, 4500);
}

// --- Live Clock ---
function startLiveClock() {
  const update = () => {
    const now = new Date();
    el.liveClock.textContent = now.toTimeString().split(" ")[0];
  };
  update();
  setInterval(update, 1000);
}

// --- Tab Switching ---
function initTabs() {
  el.navTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const targetId = tab.getAttribute("data-tab");
      el.navTabs.forEach((t) => t.classList.remove("active"));
      el.tabContents.forEach((c) => c.classList.remove("active"));

      tab.classList.add("active");
      const targetContent = document.getElementById(targetId);
      if (targetContent) targetContent.classList.add("active");

      // Tab specific refreshes
      if (targetId === "attendance-tab") {
        fetchTodayAttendance();
        fetchActiveLecture();
      } else if (targetId === "lectures-tab") {
        fetchLecturesList();
        fetchAntiBunkingAnalytics();
      } else if (targetId === "directory-tab") {
        fetchDirectory();
      } else if (targetId === "reports-tab") {
        loadReport();
      } else if (targetId === "settings-tab") {
        loadSettingsTab();
      }
    });
  });
}

// ==========================================================================
// Phase 17: Geolocation & Geofence Client Logic
// ==========================================================================

function initGeolocation() {
  if (!navigator.geolocation) {
    state.userCoords.status = "unsupported";
    state.userCoords.errorMsg = "Your browser does not support the Geolocation API required for attendance verification.";
    updateGpsUI();
    return;
  }

  state.userCoords.status = "acquiring";
  updateGpsUI();

  // Watch position with high accuracy
  navigator.geolocation.watchPosition(
    (pos) => {
      state.userCoords.latitude = pos.coords.latitude;
      state.userCoords.longitude = pos.coords.longitude;
      state.userCoords.accuracy = pos.coords.accuracy;
      state.userCoords.status = "locked";
      state.userCoords.errorMsg = "";
      updateGpsUI();
    },
    (err) => {
      if (err.code === err.PERMISSION_DENIED) {
        state.userCoords.status = "denied";
        state.userCoords.errorMsg = "Location access was denied. Please allow location access in your browser address bar settings to mark attendance.";
      } else if (err.code === err.POSITION_UNAVAILABLE) {
        state.userCoords.status = "unavailable";
        state.userCoords.errorMsg = "Location unavailable. Please ensure GPS/Location Services are enabled.";
      } else {
        state.userCoords.status = "unavailable";
        state.userCoords.errorMsg = "Location request timed out. Retrying GPS lock...";
      }
      updateGpsUI();
    },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
  );
}

function updateGpsUI() {
  const status = state.userCoords.status;
  if (!el.streamGpsStatus) return;

  if (status === "locked") {
    const acc = Math.round(state.userCoords.accuracy || 0);
    el.streamGpsStatus.className = "metric-val text-emerald";
    el.streamGpsStatus.textContent = `📍 GPS Locked (±${acc}m)`;
    if (el.geofenceStatusPill) {
      el.geofenceStatusPill.classList.remove("geofence-denied");
      el.geofenceStatusText.textContent = `📍 Location Active (±${acc}m)`;
    }
  } else if (status === "denied") {
    el.streamGpsStatus.className = "metric-val text-rose";
    el.streamGpsStatus.textContent = "🚫 GPS Permission Denied";
    if (el.geofenceStatusPill) {
      el.geofenceStatusPill.classList.add("geofence-denied");
      el.geofenceStatusText.textContent = "🚫 Location Denied";
    }
  } else if (status === "acquiring") {
    el.streamGpsStatus.className = "metric-val text-cyan";
    el.streamGpsStatus.textContent = "📍 Acquiring GPS...";
  } else {
    el.streamGpsStatus.className = "metric-val text-amber";
    el.streamGpsStatus.textContent = "⚠️ GPS Unavailable";
  }
}

// ==========================================================================
// Camera & Vision Stream
// ==========================================================================

async function startCamera() {
  try {
    // Check geolocation permission prompt immediately
    if (state.userCoords.status === "idle") {
      initGeolocation();
    }

    const constraints = {
      video: {
        facingMode: state.facingMode,
        width: { ideal: 640 },
        height: { ideal: 480 }
      },
      audio: false
    };

    state.stream = await navigator.mediaDevices.getUserMedia(constraints);
    el.webcam.srcObject = state.stream;
    el.webcam.style.transform = state.facingMode === "user" ? "scaleX(-1)" : "none";
    await el.webcam.play();

    state.isStreaming = true;
    el.cameraOverlay.classList.add("hidden");
    el.btnCameraToggle.innerHTML = `<span class="btn-icon">⏹</span> Stop Camera`;
    el.btnCameraToggle.classList.replace("btn-primary", "btn-ghost");

    // Adjust Canvas HUD resolution to match video
    const syncCanvasSize = () => {
      if (el.webcam.videoWidth && el.webcam.videoHeight) {
        el.hudCanvas.width = el.webcam.videoWidth;
        el.hudCanvas.height = el.webcam.videoHeight;
      }
    };
    syncCanvasSize();
    el.webcam.addEventListener("loadedmetadata", syncCanvasSize);

    // Refresh active lecture
    fetchActiveLecture();

    // Frame capture loop (~5 FPS for optimal cloud responsiveness)
    clearInterval(state.captureInterval);
    state.captureInterval = setInterval(captureAndRecognize, 200);

    showToast("Camera Active", "Live facial recognition scanning initiated", "success");
  } catch (err) {
    console.error("Camera access error:", err);
    showToast("Camera Error", "Could not access webcam: " + err.message, "danger");
  }
}

function stopCamera() {
  if (state.stream) {
    state.stream.getTracks().forEach((track) => track.stop());
    state.stream = null;
  }
  clearInterval(state.captureInterval);
  state.isStreaming = false;

  el.webcam.srcObject = null;
  el.cameraOverlay.classList.remove("hidden");
  el.btnCameraToggle.innerHTML = `<span class="btn-icon">▶</span> Start Camera`;
  el.btnCameraToggle.classList.replace("btn-ghost", "btn-primary");

  // Clear HUD
  const ctx = el.hudCanvas.getContext("2d");
  ctx.clearRect(0, 0, el.hudCanvas.width, el.hudCanvas.height);
  el.streamFps.textContent = "0";
}

async function flipCamera() {
  state.facingMode = state.facingMode === "user" ? "environment" : "user";
  el.webcam.style.transform = state.facingMode === "user" ? "scaleX(-1)" : "none";
  if (state.isStreaming) {
    stopCamera();
    await startCamera();
  }
}

// Capture frame and send to server with Geofence coordinates (Phase 17) & Lecture ID (Phase 21)
let isRecognizeBusy = false;

async function captureAndRecognize() {
  if (!state.isStreaming || isRecognizeBusy || !el.webcam.videoWidth) return;
  isRecognizeBusy = true;

  try {
    const tempCanvas = document.createElement("canvas");
    tempCanvas.width = el.webcam.videoWidth;
    tempCanvas.height = el.webcam.videoHeight;
    const ctx = tempCanvas.getContext("2d");
    ctx.drawImage(el.webcam, 0, 0, tempCanvas.width, tempCanvas.height);

    const base64Data = tempCanvas.toDataURL("image/jpeg", 0.75);

    const payload = {
      image: base64Data,
      mark_attendance: true,
      session_id: "client_" + (state.facingMode || "user"),
      latitude: state.userCoords.latitude,
      longitude: state.userCoords.longitude,
      accuracy: state.userCoords.accuracy,
      lecture_id: state.activeLecture ? state.activeLecture.id : null
    };

    const res = await fetch("/api/recognize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (res.ok) {
      const data = await res.json();
      drawHUD(data.results, data.geofence_status);
      handleAttendanceEvents(data.results);

      // Calculate FPS
      state.fpsCounter++;
      const now = performance.now();
      if (now - state.lastFpsTimestamp >= 1000) {
        el.streamFps.textContent = state.fpsCounter;
        state.fpsCounter = 0;
        state.lastFpsTimestamp = now;
      }
    }
  } catch (err) {
    console.debug("Recognize frame skipped:", err);
  } finally {
    isRecognizeBusy = false;
  }
}

// Draw Cyberpunk HUD bounding box overlay
function drawHUD(faces, geofenceStatus) {
  const canvas = el.hudCanvas;
  if (el.webcam.videoWidth && el.webcam.videoHeight) {
    if (canvas.width !== el.webcam.videoWidth || canvas.height !== el.webcam.videoHeight) {
      canvas.width = el.webcam.videoWidth;
      canvas.height = el.webcam.videoHeight;
    }
  }

  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  if (!faces || faces.length === 0) return;
  const isMirrored = state.facingMode === "user";

  faces.forEach((face) => {
    const [x, y, w, h] = face.bbox;
    const isRecognized = face.is_recognized;
    const isLive = face.liveness.is_live;
    const isLocOk = face.location_verified !== false;

    const bx = isMirrored ? (canvas.width - (x + w)) : x;
    const by = y;
    const bw = w;
    const bh = h;

    let primaryColor = "#06b6d4"; // Cyan: Scanning
    if (isRecognized && isLive && isLocOk) primaryColor = "#10b981"; // Emerald: Verified
    if (isRecognized && !isLocOk) primaryColor = "#f59e0b"; // Amber: Location Warning
    if (!isLive) primaryColor = "#f43f5e"; // Rose: Anti-Spoof Alert

    ctx.strokeStyle = primaryColor;
    ctx.lineWidth = 2.5;
    const cornerLen = Math.min(bw, bh) * 0.25;

    // Corners
    ctx.beginPath();
    ctx.moveTo(bx, by + cornerLen); ctx.lineTo(bx, by); ctx.lineTo(bx + cornerLen, by);
    ctx.moveTo(bx + bw - cornerLen, by); ctx.lineTo(bx + bw, by); ctx.lineTo(bx + bw, by + cornerLen);
    ctx.moveTo(bx, by + bh - cornerLen); ctx.lineTo(bx, by + bh); ctx.lineTo(bx + cornerLen, by + bh);
    ctx.moveTo(bx + bw - cornerLen, by + bh); ctx.lineTo(bx + bw, by + bh); ctx.lineTo(bx + bw, by + bh - cornerLen);
    ctx.stroke();

    ctx.fillStyle = `${primaryColor}15`;
    ctx.fillRect(bx, by, bw, bh);

    // Landmarks
    if (face.landmarks) {
      ctx.fillStyle = primaryColor;
      for (const ptName in face.landmarks) {
        const [rawLx, ly] = face.landmarks[ptName];
        const lx = isMirrored ? (canvas.width - rawLx) : rawLx;
        ctx.beginPath();
        ctx.arc(lx, ly, 3, 0, 2 * Math.PI);
        ctx.fill();
      }
    }

    // Label
    let label;
    if (isRecognized && face.student) {
      const roll = face.student.roll_no ? `${face.student.roll_no} • ` : "";
      const conf = Math.round(face.match_confidence * 100);
      if (!isLocOk) {
        label = `⚠️ ${face.student.name} (Outside Campus)`;
      } else {
        label = `${roll}${face.student.name} (${conf}%)`;
      }
    } else {
      label = isLive ? "Scanning..." : "⚠️ Spoof Detected";
    }

    ctx.font = "bold 13px 'JetBrains Mono', monospace";
    const textMetrics = ctx.measureText(label);
    const textWidth = textMetrics.width;
    const bannerH = 22;
    const bannerW = textWidth + 14;
    const bannerY = by > 26 ? by - bannerH - 2 : by + bh + 4;
    let bannerX = bx;
    if (bannerX + bannerW > canvas.width) bannerX = canvas.width - bannerW - 2;
    if (bannerX < 2) bannerX = 2;

    ctx.fillStyle = `${primaryColor}e6`;
    if (ctx.roundRect) {
      ctx.beginPath();
      ctx.roundRect(bannerX, bannerY, bannerW, bannerH, 4);
      ctx.fill();
    } else {
      ctx.fillRect(bannerX, bannerY, bannerW, bannerH);
    }

    ctx.fillStyle = "#ffffff";
    ctx.textBaseline = "middle";
    ctx.fillText(label, bannerX + 7, bannerY + (bannerH / 2));
  });
}

// Attendance events handler
function handleAttendanceEvents(faces) {
  if (!faces) return;

  faces.forEach((face) => {
    if (face.attendance) {
      if (face.attendance.recorded) {
        const rec = face.attendance.record;
        playAttendanceChime();
        showToast(
          "Attendance Recorded! ✓",
          `${rec.name} (${rec.roll_no}) marked as ${rec.status}`,
          "success"
        );
        fetchTodayAttendance();
      } else if (face.attendance.reason === "OUTSIDE_GEOFENCE" || face.attendance.reason === "POOR_ACCURACY") {
        showToast(
          "Location Verification Failed 📍",
          face.attendance.message,
          "warning"
        );
      }
    }
  });
}

// ==========================================================================
// Live Attendance Table & KPIs
// ==========================================================================

async function fetchTodayAttendance() {
  try {
    const res = await fetch("/api/attendance/today");
    if (!res.ok) return;
    const data = await res.json();

    el.kpiTotal.textContent = data.stats.total_students || 0;
    el.kpiPresent.textContent = data.stats.present_today || 0;
    el.kpiLate.textContent = data.stats.late_today || 0;
    el.kpiAbsent.textContent = data.stats.absent_today || 0;
    if (el.kpiMonthPct) el.kpiMonthPct.textContent = (data.stats.monthly_percentage || 0) + "%";
    if (el.kpiMonthDays) {
      const days = data.stats.active_days_month || 0;
      el.kpiMonthDays.textContent = `${days} Active Day${days === 1 ? "" : "s"}`;
    }

    if (!data.records || data.records.length === 0) {
      el.todayTableBody.innerHTML = `
        <tr class="empty-row"><td colspan="6">No attendance marked yet today.</td></tr>
      `;
      return;
    }

    el.todayTableBody.innerHTML = data.records
      .map((r) => `
        <tr>
          <td><strong class="text-cyan">${r.roll_no}</strong></td>
          <td>${r.name}</td>
          <td>${r.time}</td>
          <td>
            <span class="badge ${r.status === 'LATE' ? 'badge-late' : 'badge-present'}">
              ${r.status}
            </span>
          </td>
          <td>
            <span class="badge-month">${r.monthly_percentage || 0}%</span>
            <small class="text-muted" style="font-size:0.72rem;margin-left:3px;">(${r.month_present_days || 0}/${r.active_days_month || 0}d)</small>
          </td>
          <td><span class="badge-confidence">${Math.round(r.confidence * 100)}%</span></td>
        </tr>
      `)
      .join("");
  } catch (err) {
    console.error("Failed to load today's attendance:", err);
  }
}

// ==========================================================================
// Phase 21: Lectures & Anti-Bunking UI Logic
// ==========================================================================

async function fetchActiveLecture() {
  try {
    const res = await fetch("/api/lectures/active");
    if (!res.ok) return;
    const data = await res.json();
    state.activeLecture = data.active_lecture;

    if (state.activeLecture) {
      el.activeLectureBanner.style.display = "flex";
      el.bannerLectureTitle.textContent = `${state.activeLecture.course_code} — ${state.activeLecture.subject_name}`;
      el.bannerLectureMeta.textContent = `Room ${state.activeLecture.room || "101"} • ${state.activeLecture.instructor_name} • Window: ${state.activeLecture.attendance_window_start} - ${state.activeLecture.attendance_window_end}`;
    } else {
      el.activeLectureBanner.style.display = "none";
    }
  } catch (err) {
    console.debug("Active lecture fetch error:", err);
  }
}

async function fetchLecturesList() {
  try {
    const today = new Date().toISOString().split("T")[0];
    const res = await fetch(`/api/lectures?date=${today}`);
    if (!res.ok) return;
    const data = await res.json();
    renderLecturesList(data.lectures);
  } catch (err) {
    console.error("Failed to fetch lectures:", err);
  }
}

function renderLecturesList(lectures) {
  if (!lectures || lectures.length === 0) {
    el.lecturesContainer.innerHTML = `
      <p class="text-muted" style="padding: 1rem;">No lectures scheduled for today. Use the form on the left to schedule a lecture (50m default).</p>
    `;
    return;
  }

  el.lecturesContainer.innerHTML = lectures
    .map((lec) => {
      const statusClass = `badge-${lec.status.toLowerCase()}`;
      return `
        <div class="lecture-item-card">
          <div>
            <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.25rem;">
              <strong class="text-bright">${lec.course_code}: ${lec.subject_name}</strong>
              <span class="lecture-badge-status ${statusClass}">${lec.status}</span>
            </div>
            <div class="text-muted" style="font-size:0.8rem;">
              ⏱️ ${lec.start_time} - ${lec.end_time} (${lec.duration_minutes}m) • 📍 ${lec.room} • 👨‍🏫 ${lec.instructor_name}
            </div>
            <div style="font-size:0.75rem;color:var(--secondary);margin-top:0.25rem;">
              Window: ${lec.attendance_window_start} - ${lec.attendance_window_end} | Present: ${lec.present_count || 0} | Late: ${lec.late_count || 0}
            </div>
          </div>
          <div style="display:flex;gap:0.4rem;flex-wrap:wrap;">
            <button class="btn btn-ghost btn-sm" onclick="openLectureReport(${lec.id})">📊 Details</button>
            <button class="btn btn-secondary btn-sm" onclick="triggerMidCheck(${lec.id})">⚡ Mid-Check</button>
            ${lec.status === 'Scheduled' ? `<button class="btn btn-primary btn-sm" onclick="updateLectureStatus(${lec.id}, 'Open')">▶ Open</button>` : ''}
            ${lec.status === 'Open' ? `<button class="btn btn-ghost btn-sm" onclick="updateLectureStatus(${lec.id}, 'Closed')">⏹ Close</button>` : ''}
          </div>
        </div>
      `;
    })
    .join("");
}

async function handleScheduleLecture(e) {
  e.preventDefault();
  const payload = {
    course_code: el.lecCourseCode.value.trim(),
    subject_name: el.lecSubjectName.value.trim(),
    instructor_name: el.lecInstructor.value.trim(),
    date: el.lecDate.value,
    start_time: el.lecStartTime.value + ":00",
    duration_minutes: parseInt(el.lecDuration.value, 10) || 50,
    room: el.lecRoom.value.trim() || "Room 101"
  };

  try {
    const res = await fetch("/api/lectures", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.adminToken}`
      },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to schedule lecture");

    showToast("Lecture Scheduled", data.message, "success");
    el.lectureForm.reset();
    el.lecDuration.value = "50";
    el.lecRoom.value = "Room 101";
    fetchLecturesList();
    fetchActiveLecture();
  } catch (err) {
    showToast("Scheduling Failed", err.message, "danger");
  }
}

window.triggerMidCheck = async function (lecId) {
  try {
    const res = await fetch(`/api/lectures/${lecId}/mid-check`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.adminToken}`
      },
      body: JSON.stringify({ duration_minutes: 5, event_type: "MID_LECTURE" })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to trigger mid-check");

    showToast("Anti-Bunking Check Active", "5-minute verification window started for students", "success");
    fetchLecturesList();
  } catch (err) {
    showToast("Trigger Failed", err.message, "danger");
  }
};

window.updateLectureStatus = async function (lecId, status) {
  try {
    const res = await fetch(`/api/lectures/${lecId}/status`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.adminToken}`
      },
      body: JSON.stringify({ status })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to update status");

    showToast("Status Updated", data.message, "success");
    fetchLecturesList();
    fetchActiveLecture();
  } catch (err) {
    showToast("Update Failed", err.message, "danger");
  }
};

window.openLectureReport = async function (lecId) {
  try {
    const res = await fetch(`/api/lectures/${lecId}/attendance`);
    if (!res.ok) throw new Error("Could not load lecture report");
    const data = await res.json();

    el.modalLectureTitle.textContent = `${data.lecture.course_code}: ${data.lecture.subject_name}`;
    el.modalLectureSub.textContent = `Date: ${data.lecture.date} • ${data.lecture.start_time} - ${data.lecture.end_time} • Room ${data.lecture.room}`;

    el.modalKpiPresent.textContent = data.summary.present_count;
    el.modalKpiLate.textContent = data.summary.late_count;
    el.modalKpiAbsent.textContent = data.summary.absent_count;
    el.modalKpiMid.textContent = `${data.summary.mid_lecture_verified_count} / ${data.summary.present_count + data.summary.late_count}`;

    el.modalStudentTbody.innerHTML = data.records
      .map((r) => `
        <tr>
          <td><strong class="text-cyan">${r.roll_no}</strong></td>
          <td>${r.name}</td>
          <td>
            <span class="badge ${r.status === 'PRESENT' ? 'badge-present' : r.status === 'LATE' ? 'badge-late' : 'badge-danger'}">
              ${r.status}
            </span>
          </td>
          <td>${r.marked_at}</td>
          <td>${r.mid_lecture_verified === 1 ? '✓ Verified' : r.status === 'ABSENT' ? '—' : '⚠️ Missed'}</td>
          <td>${r.distance_meters !== null && r.distance_meters !== undefined ? `${r.distance_meters}m` : '—'}</td>
          <td>
            <button class="btn btn-ghost btn-sm" onclick="correctStudentAttendance(${lecId}, ${r.student_id}, '${r.name}', '${r.status}')">
              ✏️ Correct
            </button>
          </td>
        </tr>
      `)
      .join("");

    el.lectureModal.classList.add("active");
  } catch (err) {
    showToast("Report Error", err.message, "danger");
  }
};

window.correctStudentAttendance = async function (lecId, stId, stName, currentStatus) {
  const newStatus = prompt(`Correct attendance for ${stName} (Currently: ${currentStatus}). Enter PRESENT, LATE, or ABSENT:`, "PRESENT");
  if (!newStatus) return;
  const upperStatus = newStatus.toUpperCase().trim();
  if (!["PRESENT", "LATE", "ABSENT"].includes(upperStatus)) {
    alert("Invalid status. Must be PRESENT, LATE, or ABSENT.");
    return;
  }
  const reason = prompt("Enter mandatory audit reason for correction (e.g. Approved medical slip, instructor confirmation):");
  if (!reason || !reason.trim()) {
    alert("A reason is mandatory for auditing attendance corrections.");
    return;
  }

  try {
    const res = await fetch("/api/admin/attendance/correct", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.adminToken}`
      },
      body: JSON.stringify({
        lecture_id: lecId,
        student_id: stId,
        new_status: upperStatus,
        reason: reason.trim(),
        authorized_by: state.adminUser
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Correction failed");

    showToast("Correction Saved", data.message, "success");
    openLectureReport(lecId);
    fetchLecturesList();
  } catch (err) {
    showToast("Correction Failed", err.message, "danger");
  }
};

async function fetchAntiBunkingAnalytics() {
  try {
    const res = await fetch("/api/reports/lecture-stats");
    if (!res.ok) return;
    const data = await res.json();

    if (!data.student_analytics || data.student_analytics.length === 0) {
      el.analyticsTableBody.innerHTML = `
        <tr class="empty-row"><td colspan="8">No lecture analytics available yet.</td></tr>
      `;
      return;
    }

    el.analyticsTableBody.innerHTML = data.student_analytics
      .map((st) => `
        <tr>
          <td><strong class="text-cyan">${st.roll_no}</strong></td>
          <td>${st.name}</td>
          <td>${st.department || "General"}</td>
          <td>${st.lectures_attended || 0}</td>
          <td>${st.missed_lectures || 0}</td>
          <td>${st.late_count || 0}</td>
          <td>${st.mid_checks_passed || 0}</td>
          <td>
            <span class="badge ${st.attendance_percentage >= 75 ? 'badge-present' : 'badge-danger'}">
              ${st.attendance_percentage}%
            </span>
          </td>
        </tr>
      `)
      .join("");
  } catch (err) {
    console.error("Analytics fetch error:", err);
  }
}

// ==========================================================================
// Phase 18, 19, 20: Enrollment Client Validation
// ==========================================================================

function validateEnrollmentInputs() {
  let isValid = true;

  // 1. Roll Number Validation: Digits only (0-9)
  const rollVal = el.enrollRoll.value.trim();
  const isNumeric = /^\d+$/.test(rollVal);
  if (!isNumeric) {
    el.enrollRoll.classList.add("input-invalid");
    el.errEnrollRoll.textContent = "Roll ID must contain digits only (0-9). Alphabetic and special characters are rejected.";
    el.errEnrollRoll.style.display = "block";
    isValid = false;
  } else {
    el.enrollRoll.classList.remove("input-invalid");
    el.errEnrollRoll.style.display = "none";
  }

  // 2. Student Name Validation: Title Case or UPPERCASE, no digits
  const nameVal = el.enrollName.value.trim();
  const hasDigits = /\d/.test(nameVal);
  const parts = nameVal.split(/\s+/);
  const isAllUpper = parts.every((p) => /^[A-Z'-]+$/.test(p));
  const isTitle = parts.every((p) => /^[A-Z][a-z'-]*$/.test(p));

  if (hasDigits || (!isAllUpper && !isTitle)) {
    el.enrollName.classList.add("input-invalid");
    el.errEnrollName.textContent = "Name must be Title Case (e.g. 'Rohit Pathak') or UPPERCASE (e.g. 'ROHIT PATHAK') without numbers.";
    el.errEnrollName.style.display = "block";
    isValid = false;
  } else {
    el.enrollName.classList.remove("input-invalid");
    el.errEnrollName.style.display = "none";
  }

  // 3. Email Validation: Lowercase alphanumeric local part
  const emailVal = el.enrollEmail.value.trim();
  if (emailVal) {
    const emailParts = emailVal.split("@");
    const localPart = emailParts[0];
    const hasAt = emailParts.length === 2;
    const isLowerAlphanumeric = /^[a-z0-9]+$/.test(localPart);
    const hasValidDomain = hasAt && /^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(emailParts[1]);

    if (!isLowerAlphanumeric || !hasValidDomain) {
      el.enrollEmail.classList.add("input-invalid");
      el.errEnrollEmail.textContent = "Local part must be strictly lowercase alphanumeric (a-z, 0-9). Domain must have valid suffix.";
      el.errEnrollEmail.style.display = "block";
      isValid = false;
    } else {
      el.enrollEmail.classList.remove("input-invalid");
      el.errEnrollEmail.style.display = "none";
    }
  } else {
    el.enrollEmail.classList.remove("input-invalid");
    el.errEnrollEmail.style.display = "none";
  }

  return isValid;
}

async function toggleEnrollCamera() {
  if (state.enrollingStream) {
    state.enrollingStream.getTracks().forEach((t) => t.stop());
    state.enrollingStream = null;
    el.enrollVideo.srcObject = null;
    el.btnEnrollCamToggle.textContent = "Turn On Camera";
    el.btnEnrollSnap.disabled = true;
    el.enrollPlaceholder.style.display = "flex";
    el.enrollVideo.style.display = "none";
  } else {
    try {
      state.enrollingStream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" }
      });
      el.enrollVideo.srcObject = state.enrollingStream;
      el.enrollPlaceholder.style.display = "none";
      el.enrollPreviewImg.style.display = "none";
      el.enrollVideo.style.display = "block";
      el.btnEnrollCamToggle.textContent = "Turn Off Camera";
      el.btnEnrollSnap.disabled = false;
    } catch (err) {
      showToast("Camera Error", "Could not activate camera: " + err.message, "danger");
    }
  }
}

function snapEnrollPhoto() {
  if (!state.enrollingStream || !el.enrollVideo.videoWidth) return;

  const canvas = el.enrollCanvas;
  canvas.width = el.enrollVideo.videoWidth;
  canvas.height = el.enrollVideo.videoHeight;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(el.enrollVideo, 0, 0, canvas.width, canvas.height);

  state.capturedEnrollBase64 = canvas.toDataURL("image/jpeg", 0.9);
  el.enrollPreviewImg.src = state.capturedEnrollBase64;
  el.enrollPreviewImg.style.display = "block";
  el.enrollVideo.style.display = "none";

  toggleEnrollCamera();
  showToast("Photo Captured", "Face snapshot ready for enrollment", "success");
}

function handleEnrollFileUpload(e) {
  const file = e.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = (event) => {
    state.capturedEnrollBase64 = event.target.result;
    el.enrollPreviewImg.src = state.capturedEnrollBase64;
    el.enrollPreviewImg.style.display = "block";
    el.enrollPlaceholder.style.display = "none";
    el.enrollVideo.style.display = "none";
    showToast("File Loaded", `Selected ${file.name}`, "success");
  };
  reader.readAsDataURL(file);
}

async function submitEnrollment(e) {
  e.preventDefault();

  if (!validateEnrollmentInputs()) {
    showToast("Validation Error", "Please correct the highlighted form errors before submitting", "warning");
    return;
  }

  if (!state.capturedEnrollBase64) {
    showToast("Photo Missing", "Please snap a photo or upload an image first", "warning");
    return;
  }

  el.btnSubmitEnroll.disabled = true;
  el.btnSubmitEnroll.textContent = "⏳ Extracting 128-D ArcFace Embedding...";

  try {
    const payload = {
      roll_no: el.enrollRoll.value.trim(),
      name: el.enrollName.value.trim(),
      department: el.enrollDept.value.trim() || "General",
      email: el.enrollEmail.value.trim() || "",
      image: state.capturedEnrollBase64
    };

    const res = await fetch("/api/students/enroll", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Enrollment failed.");

    showToast("Enrollment Successful! 🎉", data.message, "success");
    el.enrollForm.reset();
    state.capturedEnrollBase64 = null;
    el.enrollPreviewImg.style.display = "none";
    el.enrollPlaceholder.style.display = "flex";
    fetchTodayAttendance();
  } catch (err) {
    showToast("Enrollment Failed", err.message, "danger");
  } finally {
    el.btnSubmitEnroll.disabled = false;
    el.btnSubmitEnroll.textContent = "💾 Register Student & Face";
  }
}

// ==========================================================================
// Reports & Directory
// ==========================================================================

async function loadReport() {
  const dateStr = el.reportDatePicker.value || new Date().toISOString().split("T")[0];
  try {
    el.reportTableBody.innerHTML = `<tr class="empty-row"><td colspan="8">Loading records...</td></tr>`;
    const res = await fetch(`/api/attendance?date=${encodeURIComponent(dateStr)}`);
    if (!res.ok) throw new Error("Could not fetch reports");
    const data = await res.json();

    if (!data.records || data.records.length === 0) {
      el.reportTableBody.innerHTML = `<tr class="empty-row"><td colspan="8">No attendance records found for ${dateStr}.</td></tr>`;
      return;
    }

    el.reportTableBody.innerHTML = data.records
      .map((r) => `
        <tr>
          <td>${r.id}</td>
          <td><strong class="text-cyan">${r.roll_no}</strong></td>
          <td>${r.name}</td>
          <td>${r.department || "General"}</td>
          <td>${r.date}</td>
          <td>${r.time}</td>
          <td><span class="badge ${r.status === 'LATE' ? 'badge-late' : 'badge-present'}">${r.status}</span></td>
          <td><span class="badge-confidence">${Math.round(r.confidence * 100)}%</span></td>
        </tr>
      `)
      .join("");
  } catch (err) {
    showToast("Report Error", err.message, "danger");
  }
}

function exportReportCsv() {
  const dateStr = el.reportDatePicker.value || new Date().toISOString().split("T")[0];
  window.location.href = `/api/attendance/export?date=${encodeURIComponent(dateStr)}`;
}

let directoryCache = [];
async function fetchDirectory() {
  try {
    const res = await fetch("/api/students");
    if (!res.ok) return;
    const data = await res.json();
    directoryCache = data.students || [];
    renderDirectory(directoryCache);
  } catch (err) {
    console.error("Failed to load directory:", err);
  }
}

function renderDirectory(students) {
  if (!students || students.length === 0) {
    el.directoryTableBody.innerHTML = `<tr class="empty-row"><td colspan="7">No registered students found.</td></tr>`;
    return;
  }
  el.directoryTableBody.innerHTML = students
    .map((s) => `
      <tr>
        <td><strong class="text-cyan">${s.roll_no}</strong></td>
        <td>${s.name}</td>
        <td>${s.department || "General"}</td>
        <td>
          <span class="badge-month">${s.monthly_percentage || 0}%</span>
          <small class="text-muted" style="font-size:0.75rem;margin-left:4px;">(${s.active_days_present || 0}/${s.total_active_days || 0} active days)</small>
        </td>
        <td>${s.email || "—"}</td>
        <td>${s.created_at || "—"}</td>
        <td>
          <button class="btn-delete" onclick="deleteStudent('${s.roll_no}', '${s.name}')">🗑 Delete</button>
        </td>
      </tr>
    `)
    .join("");
}

window.deleteStudent = async function (rollNo, name) {
  if (!confirm(`Are you sure you want to delete student ${name} (${rollNo})?`)) return;
  try {
    const res = await fetch(`/api/students/${encodeURIComponent(rollNo)}`, {
      method: "DELETE",
      headers: { "Authorization": `Bearer ${state.adminToken}` }
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Deletion failed");

    showToast("Student Deleted", data.message, "warning");
    fetchDirectory();
    fetchTodayAttendance();
  } catch (err) {
    showToast("Delete Failed", err.message, "danger");
  }
};

function filterDirectory() {
  const query = el.directorySearch.value.toLowerCase().trim();
  const filtered = directoryCache.filter(
    (s) =>
      s.name.toLowerCase().includes(query) ||
      s.roll_no.toLowerCase().includes(query) ||
      (s.department && s.department.toLowerCase().includes(query))
  );
  renderDirectory(filtered);
}

// ==========================================================================
// Phase 17 & 22: Settings, Geofence Config & Audit Logs
// ==========================================================================

async function ensureAdminAuth() {
  if (!state.adminToken) {
    const user = prompt("Administrator login required. Username:", "admin");
    if (!user) return false;
    const pass = prompt("Administrator password:", "admin123");
    if (!pass) return false;

    try {
      const res = await fetch("/api/admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: user, password: pass })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Authentication failed");

      state.adminToken = data.token;
      state.adminUser = user;
      localStorage.setItem("dv_admin_token", data.token);
      localStorage.setItem("dv_admin_user", user);
      el.adminAuthStatus.textContent = `🔒 Admin Session: Authenticated (${user})`;
      showToast("Admin Authenticated", "Full access granted", "success");
      return true;
    } catch (err) {
      showToast("Login Failed", err.message, "danger");
      return false;
    }
  }
  return true;
}

async function loadSettingsTab() {
  await ensureAdminAuth();

  // Load campus geofence config
  try {
    const res = await fetch("/api/admin/campuses", {
      headers: { "Authorization": `Bearer ${state.adminToken}` }
    });
    if (res.ok) {
      const data = await res.json();
      if (data.campuses && data.campuses.length > 0) {
        const c = data.campuses[0];
        el.cfgCampusName.value = c.name;
        el.cfgCampusLat.value = c.latitude;
        el.cfgCampusLon.value = c.longitude;
        el.cfgCampusRadius.value = c.radius_meters;
        el.cfgCampusAccuracy.value = c.accuracy_threshold_meters;
        el.cfgGeofenceEnabled.checked = c.is_active === 1;
        el.diagRadius.textContent = `${c.radius_meters} Meters`;

        // Update radius pill group active state
        el.radiusBtns.forEach((btn) => {
          btn.classList.toggle("active", parseFloat(btn.getAttribute("data-radius")) === c.radius_meters);
        });
      }
    }
  } catch (err) {
    console.debug("Campus settings fetch skipped:", err);
  }

  // Load institutional policies
  try {
    const res = await fetch("/api/admin/settings", {
      headers: { "Authorization": `Bearer ${state.adminToken}` }
    });
    if (res.ok) {
      const data = await res.json();
      const s = data.settings;
      if (s) {
        if (s.default_lecture_duration_minutes) el.cfgLectureDuration.value = s.default_lecture_duration_minutes;
        if (s.attendance_window_before_mins) el.cfgWindowBefore.value = s.attendance_window_before_mins;
        if (s.attendance_window_after_mins) el.cfgWindowAfter.value = s.attendance_window_after_mins;
        if (s.late_cutoff_minutes) el.cfgLateCutoff.value = s.late_cutoff_minutes;
        if (s.institution_timezone) el.cfgTimezone.value = s.institution_timezone;
        if (s.require_numeric_roll_no) el.cfgNumericRoll.checked = s.require_numeric_roll_no === "true";
      }
    }
  } catch (err) {
    console.debug("Policy settings fetch skipped:", err);
  }

  // Load audit logs
  fetchAuditLogs();
}

async function handleSaveGeofence(e) {
  e.preventDefault();
  if (!(await ensureAdminAuth())) return;

  const payload = {
    name: el.cfgCampusName.value.trim(),
    latitude: parseFloat(el.cfgCampusLat.value),
    longitude: parseFloat(el.cfgCampusLon.value),
    radius_meters: parseFloat(el.cfgCampusRadius.value),
    accuracy_threshold_meters: parseFloat(el.cfgCampusAccuracy.value),
    is_active: el.cfgGeofenceEnabled.checked
  };

  try {
    const res = await fetch("/api/admin/campuses/1", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.adminToken}`
      },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to update campus");

    showToast("Geofence Updated", `Campus radius set to ${payload.radius_meters}m`, "success");
    el.diagRadius.textContent = `${payload.radius_meters} Meters`;
    fetchAuditLogs();
  } catch (err) {
    showToast("Update Failed", err.message, "danger");
  }
}

async function handleSavePolicies(e) {
  e.preventDefault();
  if (!(await ensureAdminAuth())) return;

  const settings = {
    default_lecture_duration_minutes: el.cfgLectureDuration.value,
    attendance_window_before_mins: el.cfgWindowBefore.value,
    attendance_window_after_mins: el.cfgWindowAfter.value,
    late_cutoff_minutes: el.cfgLateCutoff.value,
    institution_timezone: el.cfgTimezone.value,
    require_numeric_roll_no: el.cfgNumericRoll.checked ? "true" : "false"
  };

  try {
    const res = await fetch("/api/admin/settings", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.adminToken}`
      },
      body: JSON.stringify({ settings })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to update policies");

    showToast("Policies Updated", data.message, "success");
    fetchAuditLogs();
  } catch (err) {
    showToast("Update Failed", err.message, "danger");
  }
}

async function fetchAuditLogs() {
  try {
    const res = await fetch("/api/admin/audit-logs", {
      headers: { "Authorization": `Bearer ${state.adminToken}` }
    });
    if (!res.ok) return;
    const data = await res.json();

    if (!data.logs || data.logs.length === 0) {
      el.auditTableBody.innerHTML = `<tr class="empty-row"><td colspan="5">No audit entries yet.</td></tr>`;
      return;
    }

    el.auditTableBody.innerHTML = data.logs
      .map((l) => `
        <tr>
          <td>${l.id}</td>
          <td><span class="badge badge-present">${l.action}</span></td>
          <td>${l.details}</td>
          <td><strong class="text-cyan">${l.actor}</strong></td>
          <td>${l.created_at}</td>
        </tr>
      `)
      .join("");
  } catch (err) {
    console.debug("Audit logs fetch skipped:", err);
  }
}

async function handleAdminPasswordChange(e) {
  e.preventDefault();
  const username = el.adminUser.value.trim();
  const oldPassword = el.adminOldPass.value;
  const newPassword = el.adminNewPass.value;

  try {
    const res = await fetch("/api/admin/change-password", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.adminToken}`
      },
      body: JSON.stringify({
        username,
        old_password: oldPassword,
        new_password: newPassword
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Update failed");

    showToast("Password Updated", "Admin password changed successfully", "success");
    el.adminOldPass.value = "";
    el.adminNewPass.value = "";
  } catch (err) {
    showToast("Update Failed", err.message, "danger");
  }
}

// ==========================================================================
// Initialization
// ==========================================================================

document.addEventListener("DOMContentLoaded", () => {
  startLiveClock();
  initTabs();

  // Set default dates
  const today = new Date().toISOString().split("T")[0];
  el.reportDatePicker.value = today;
  el.lecDate.value = today;
  el.lecStartTime.value = "10:00";

  // Geolocation Init
  initGeolocation();

  // Initial Fetches
  fetchTodayAttendance();
  fetchActiveLecture();

  // Radius buttons handler
  el.radiusBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      el.radiusBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const r = btn.getAttribute("data-radius");
      if (r !== "custom") {
        el.cfgCampusRadius.value = r;
      }
    });
  });

  // Modal Close
  el.btnCloseModal.addEventListener("click", () => {
    el.lectureModal.classList.remove("active");
  });

  // Event Listeners: Live Camera
  el.btnCameraToggle.addEventListener("click", () => {
    if (state.isStreaming) stopCamera();
    else startCamera();
  });
  el.btnCameraStartOverlay.addEventListener("click", startCamera);
  el.btnCameraFlip.addEventListener("click", flipCamera);
  el.btnRefreshFeed.addEventListener("click", fetchTodayAttendance);
  el.btnBannerMidCheck.addEventListener("click", () => {
    if (state.activeLecture) triggerMidCheck(state.activeLecture.id);
  });

  // Event Listeners: Enrollment Real-Time Validation
  el.enrollRoll.addEventListener("input", validateEnrollmentInputs);
  el.enrollName.addEventListener("input", validateEnrollmentInputs);
  el.enrollEmail.addEventListener("input", validateEnrollmentInputs);
  el.btnEnrollCamToggle.addEventListener("click", toggleEnrollCamera);
  el.btnEnrollSnap.addEventListener("click", snapEnrollPhoto);
  el.enrollFileInput.addEventListener("change", handleEnrollFileUpload);
  el.enrollForm.addEventListener("submit", submitEnrollment);

  // Event Listeners: Lectures Tab
  el.lectureForm.addEventListener("submit", handleScheduleLecture);
  el.btnRefreshLectures.addEventListener("click", () => {
    fetchLecturesList();
    fetchAntiBunkingAnalytics();
  });

  // Event Listeners: Reports & Directory
  el.btnLoadReport.addEventListener("click", loadReport);
  el.btnExportCsv.addEventListener("click", exportReportCsv);
  el.directorySearch.addEventListener("input", filterDirectory);

  // Event Listeners: Settings
  el.geofenceForm.addEventListener("submit", handleSaveGeofence);
  el.policiesForm.addEventListener("submit", handleSavePolicies);
  el.adminPasswordForm.addEventListener("submit", handleAdminPasswordChange);
  el.btnRefreshAudit.addEventListener("click", fetchAuditLogs);
  el.btnAdminRelogin.addEventListener("click", () => {
    localStorage.removeItem("dv_admin_token");
    state.adminToken = "";
    ensureAdminAuth();
  });

  // Periodic active lecture check every 60 seconds
  setInterval(fetchActiveLecture, 60000);
});
