/**
 * DeepVision AI - Web Client Controller
 * Real-time WebRTC Camera Stream, Face HUD Overlay, Attendance & Enrollment
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
  audioCtx: null
};

// --- DOM Elements ---
const el = {
  // Navigation
  navTabs: document.querySelectorAll(".nav-tab"),
  tabContents: document.querySelectorAll(".tab-content"),
  liveClock: document.getElementById("live-clock"),
  systemStatusPill: document.getElementById("system-status-pill"),
  systemStatusText: document.getElementById("system-status-text"),

  // KPIs
  kpiTotal: document.getElementById("kpi-total"),
  kpiPresent: document.getElementById("kpi-present"),
  kpiLate: document.getElementById("kpi-late"),
  kpiAbsent: document.getElementById("kpi-absent"),
  kpiMonthPct: document.getElementById("kpi-month-pct"),
  kpiMonthDays: document.getElementById("kpi-month-days"),

  // Live Camera & HUD
  webcam: document.getElementById("webcam"),
  hudCanvas: document.getElementById("hud-canvas"),
  cameraOverlay: document.getElementById("camera-overlay"),
  btnCameraToggle: document.getElementById("btn-camera-toggle"),
  btnCameraFlip: document.getElementById("btn-camera-flip"),
  btnCameraStartOverlay: document.getElementById("btn-camera-start-overlay"),
  streamFps: document.getElementById("stream-fps"),
  livenessStatus: document.getElementById("liveness-status"),
  todayTableBody: document.getElementById("today-table-body"),
  btnRefreshFeed: document.getElementById("btn-refresh-feed"),

  // Enrollment
  enrollForm: document.getElementById("enroll-form"),
  enrollRoll: document.getElementById("enroll-roll"),
  enrollName: document.getElementById("enroll-name"),
  enrollDept: document.getElementById("enroll-dept"),
  enrollEmail: document.getElementById("enroll-email"),
  enrollVideo: document.getElementById("enroll-video"),
  enrollCanvas: document.getElementById("enroll-canvas"),
  enrollPreviewImg: document.getElementById("enroll-preview-img"),
  enrollPlaceholder: document.getElementById("enroll-placeholder"),
  btnEnrollCamToggle: document.getElementById("btn-enroll-cam-toggle"),
  btnEnrollSnap: document.getElementById("btn-enroll-snap"),
  enrollFileInput: document.getElementById("enroll-file-input"),
  btnSubmitEnroll: document.getElementById("btn-submit-enroll"),

  // Reports
  reportDatePicker: document.getElementById("report-date-picker"),
  btnLoadReport: document.getElementById("btn-load-report"),
  btnExportCsv: document.getElementById("btn-export-csv"),
  reportTableBody: document.getElementById("report-table-body"),

  // Directory
  directorySearch: document.getElementById("directory-search"),
  directoryTableBody: document.getElementById("directory-table-body"),

  // Settings
  diagCooldown: document.getElementById("diag-cooldown"),
  diagLateCutoff: document.getElementById("diag-late-cutoff"),
  adminPasswordForm: document.getElementById("admin-password-form"),
  adminUser: document.getElementById("admin-user"),
  adminOldPass: document.getElementById("admin-old-pass"),
  adminNewPass: document.getElementById("admin-new-pass"),

  // Toast Container
  toastContainer: document.getElementById("toast-container")
};

// --- Web Audio Synthesizer (Attendance Chime) ---
function playAttendanceChime() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    if (!state.audioCtx) {
      state.audioCtx = new AudioCtx();
    }
    if (state.audioCtx.state === "suspended") {
      state.audioCtx.resume();
    }

    const now = state.audioCtx.currentTime;
    // Pleasant futuristic ascending two-tone chord
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
  }, 4000);
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

      // Auto-load tab data
      if (targetId === "attendance-tab") {
        fetchTodayAttendance();
      } else if (targetId === "directory-tab") {
        fetchDirectory();
      } else if (targetId === "reports-tab") {
        loadReport();
      }
    });
  });
}

// ==========================================================================
// Camera & Vision Stream
// ==========================================================================

async function startCamera() {
  try {
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
    el.webcam.onloadedmetadata = () => {
      el.hudCanvas.width = el.webcam.videoWidth || 640;
      el.hudCanvas.height = el.webcam.videoHeight || 480;
    };

    // Begin real-time recognition frame capture loop (~5-6 FPS for optimal cloud responsiveness)
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

// Flip Camera (Mobile User vs Environment)
async function flipCamera() {
  state.facingMode = state.facingMode === "user" ? "environment" : "user";
  el.webcam.style.transform = state.facingMode === "user" ? "scaleX(-1)" : "none";
  if (state.isStreaming) {
    stopCamera();
    await startCamera();
  }
}

// Capture frame from webcam and send to /api/recognize
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

    // Convert to JPEG base64
    const base64Data = tempCanvas.toDataURL("image/jpeg", 0.75);

    const res = await fetch("/api/recognize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image: base64Data,
        mark_attendance: true,
        session_id: "client_" + (state.facingMode || "user")
      })
    });

    if (res.ok) {
      const data = await res.json();
      drawHUD(data.results);
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

// Draw Cyberpunk HUD bounding box overlay on Canvas
function drawHUD(faces) {
  const canvas = el.hudCanvas;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  if (!faces || faces.length === 0) return;

  // Mirror X coordinates when front selfie camera preview is mirrored
  const isMirrored = state.facingMode === "user";

  faces.forEach((face) => {
    const [x, y, w, h] = face.bbox;
    const isRecognized = face.is_recognized;
    const isLive = face.liveness.is_live;

    // Calculate screen coordinates to precisely match the video preview
    const bx = isMirrored ? (canvas.width - (x + w)) : x;
    const by = y;
    const bw = w;
    const bh = h;

    let primaryColor = "#06b6d4"; // Cyan: Scanning / Unknown
    if (isRecognized && isLive) primaryColor = "#10b981"; // Emerald: Verified Student
    if (!isLive) primaryColor = "#f43f5e"; // Rose: Anti-Spoof Alert

    ctx.strokeStyle = primaryColor;
    ctx.lineWidth = 2.5;

    // Corner bracket styles
    const cornerLen = Math.min(bw, bh) * 0.25;

    // Top-Left
    ctx.beginPath();
    ctx.moveTo(bx, by + cornerLen);
    ctx.lineTo(bx, by);
    ctx.lineTo(bx + cornerLen, by);
    ctx.stroke();

    // Top-Right
    ctx.beginPath();
    ctx.moveTo(bx + bw - cornerLen, by);
    ctx.lineTo(bx + bw, by);
    ctx.lineTo(bx + bw, by + cornerLen);
    ctx.stroke();

    // Bottom-Left
    ctx.beginPath();
    ctx.moveTo(bx, by + bh - cornerLen);
    ctx.lineTo(bx, by + bh);
    ctx.lineTo(bx + cornerLen, by + bh);
    ctx.stroke();

    // Bottom-Right
    ctx.beginPath();
    ctx.moveTo(bx + bw - cornerLen, by + bh);
    ctx.lineTo(bx + bw, by + bh);
    ctx.lineTo(bx + bw, by + bh - cornerLen);
    ctx.stroke();

    // Subtle face box fill
    ctx.fillStyle = `${primaryColor}15`;
    ctx.fillRect(bx, by, bw, bh);

    // Draw facial landmark dots
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

    // Clearly format student details: Roll No + Name + Match %
    let label;
    if (isRecognized && face.student) {
      const roll = face.student.roll_no ? `${face.student.roll_no} • ` : "";
      const conf = Math.round(face.match_confidence * 100);
      label = `${roll}${face.student.name} (${conf}%)`;
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

// Process Attendance notifications from recognizer response
function handleAttendanceEvents(faces) {
  if (!faces) return;

  faces.forEach((face) => {
    if (face.attendance && face.attendance.recorded) {
      const rec = face.attendance.record;
      playAttendanceChime();
      showToast(
        "Attendance Recorded! ✓",
        `${rec.name} (${rec.roll_no}) marked as ${rec.status}`,
        "success"
      );
      fetchTodayAttendance();
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

    // Update KPIs
    el.kpiTotal.textContent = data.stats.total_students || 0;
    el.kpiPresent.textContent = data.stats.present_today || 0;
    el.kpiLate.textContent = data.stats.late_today || 0;
    el.kpiAbsent.textContent = data.stats.absent_today || 0;
    if (el.kpiMonthPct) {
      el.kpiMonthPct.textContent = (data.stats.monthly_percentage || 0) + "%";
    }
    if (el.kpiMonthDays) {
      const days = data.stats.active_days_month || 0;
      el.kpiMonthDays.textContent = `${days} Active Day${days === 1 ? "" : "s"}`;
    }

    // Populate Table
    if (!data.records || data.records.length === 0) {
      el.todayTableBody.innerHTML = `
        <tr class="empty-row">
          <td colspan="6">No attendance marked yet today.</td>
        </tr>
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
// Enrollment Workflow
// ==========================================================================

async function toggleEnrollCamera() {
  if (state.enrollingStream) {
    // Turn off
    state.enrollingStream.getTracks().forEach((t) => t.stop());
    state.enrollingStream = null;
    el.enrollVideo.srcObject = null;
    el.btnEnrollCamToggle.textContent = "Turn On Camera";
    el.btnEnrollSnap.disabled = true;
    el.enrollPlaceholder.style.display = "flex";
    el.enrollVideo.style.display = "none";
  } else {
    // Turn on
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
      showToast("Camera Error", "Could not activate enroll camera: " + err.message, "danger");
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

  // Show captured photo preview
  el.enrollPreviewImg.src = state.capturedEnrollBase64;
  el.enrollPreviewImg.style.display = "block";
  el.enrollVideo.style.display = "none";

  // Stop enroll webcam
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

    if (!res.ok) {
      throw new Error(data.detail || "Enrollment failed.");
    }

    showToast("Enrollment Successful! 🎉", data.message, "success");

    // Reset Form
    el.enrollForm.reset();
    state.capturedEnrollBase64 = null;
    el.enrollPreviewImg.style.display = "none";
    el.enrollPlaceholder.style.display = "flex";

    // Refresh KPI and Directory
    fetchTodayAttendance();
  } catch (err) {
    showToast("Enrollment Failed", err.message, "danger");
  } finally {
    el.btnSubmitEnroll.disabled = false;
    el.btnSubmitEnroll.textContent = "💾 Register Student & Face";
  }
}

// ==========================================================================
// Reports & Export
// ==========================================================================

async function loadReport() {
  const dateStr = el.reportDatePicker.value || new Date().toISOString().split("T")[0];

  try {
    el.reportTableBody.innerHTML = `
      <tr class="empty-row"><td colspan="8">Loading records...</td></tr>
    `;

    const res = await fetch(`/api/attendance?date=${encodeURIComponent(dateStr)}`);
    if (!res.ok) throw new Error("Could not fetch reports");
    const data = await res.json();

    if (!data.records || data.records.length === 0) {
      el.reportTableBody.innerHTML = `
        <tr class="empty-row"><td colspan="8">No attendance records found for ${dateStr}.</td></tr>
      `;
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
          <td>
            <span class="badge ${r.status === 'LATE' ? 'badge-late' : 'badge-present'}">
              ${r.status}
            </span>
          </td>
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

// ==========================================================================
// Student Directory
// ==========================================================================

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
    el.directoryTableBody.innerHTML = `
      <tr class="empty-row"><td colspan="7">No registered students found.</td></tr>
    `;
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
          <button class="btn-delete" onclick="deleteStudent('${s.roll_no}', '${s.name}')">
            🗑 Delete
          </button>
        </td>
      </tr>
    `)
    .join("");
}

window.deleteStudent = async function (rollNo, name) {
  if (!confirm(`Are you sure you want to delete student ${name} (${rollNo})?`)) return;

  try {
    const res = await fetch(`/api/students/${encodeURIComponent(rollNo)}`, {
      method: "DELETE"
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
// Settings & System Health
// ==========================================================================

async function checkSystemHealth() {
  try {
    const res = await fetch("/health");
    if (res.ok) {
      const data = await res.json();
      el.systemStatusPill.classList.add("online");
      el.systemStatusText.textContent = "Online • Cloud Live";
      if (el.diagCooldown) el.diagCooldown.textContent = `${data.cooldown_minutes} Minutes`;
      if (el.diagLateCutoff) el.diagLateCutoff.textContent = data.late_cutoff;
    } else {
      el.systemStatusPill.classList.remove("online");
      el.systemStatusText.textContent = "Degraded";
    }
  } catch (err) {
    el.systemStatusPill.classList.remove("online");
    el.systemStatusText.textContent = "Offline";
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
      headers: { "Content-Type": "application/json" },
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

  // Set default report date to today
  const today = new Date().toISOString().split("T")[0];
  el.reportDatePicker.value = today;

  // Initial Data Fetch
  checkSystemHealth();
  fetchTodayAttendance();

  // Event Listeners: Live Camera
  el.btnCameraToggle.addEventListener("click", () => {
    if (state.isStreaming) stopCamera();
    else startCamera();
  });
  el.btnCameraStartOverlay.addEventListener("click", startCamera);
  el.btnCameraFlip.addEventListener("click", flipCamera);
  el.btnRefreshFeed.addEventListener("click", fetchTodayAttendance);

  // Event Listeners: Enrollment
  el.btnEnrollCamToggle.addEventListener("click", toggleEnrollCamera);
  el.btnEnrollSnap.addEventListener("click", snapEnrollPhoto);
  el.enrollFileInput.addEventListener("change", handleEnrollFileUpload);
  el.enrollForm.addEventListener("submit", submitEnrollment);

  // Event Listeners: Reports & Directory
  el.btnLoadReport.addEventListener("click", loadReport);
  el.btnExportCsv.addEventListener("click", exportReportCsv);
  el.directorySearch.addEventListener("input", filterDirectory);

  // Event Listeners: Settings
  el.adminPasswordForm.addEventListener("submit", handleAdminPasswordChange);

  // Periodic health check every 30 seconds
  setInterval(checkSystemHealth, 30000);
});
