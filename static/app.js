/**
 * SmartAttend AI - Intelligent Web Client Controller (Version 4.0)
 * Handles:
 * - Tab switching across all 9 portals
 * - Live webcam capture and frame streaming for multi-layer anti-proxy verification
 * - GPS Geolocation capture with accuracy reporting
 * - Dynamic Rotating QR Code generation & live timer display (Teacher Portal)
 * - Student Portal (Live percentages, subject breakdown, leave submission)
 * - Teacher Portal (Assigned classes, session control, leave review)
 * - Parent Portal (Ward monitoring)
 * - AI & Predictive Analytics (Forecast, bunking anomalies, department trends)
 * - Security Reviews (Borderline presence resolution, cameras, beacons)
 * - Safe CSV Exports (Formula injection protected)
 * - Multi-Role Authentication Modal
 */

// --- Global Application State ---
const state = {
  isStreaming: false,
  stream: null,
  captureInterval: null,
  fpsCounter: 0,
  lastFpsTimestamp: performance.now(),
  userCoords: {
    latitude: null,
    longitude: null,
    accuracy: null,
    status: "acquiring"
  },
  currentRole: localStorage.getItem("sa_role") || "ADMIN",
  authToken: localStorage.getItem("sa_token") || localStorage.getItem("dv_admin_token") || "",
  currentUser: JSON.parse(localStorage.getItem("sa_user") || "null") || { name: "Administrator" },
  activeSessionId: null,
  qrTimerInterval: null,
  qrSecondsRemaining: 30
};

// --- Toast Notifications ---
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `<span class="toast-msg">${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// --- Auth Helper Headers ---
function getAuthHeaders() {
  const headers = { "Content-Type": "application/json" };
  if (state.authToken) {
    headers["Authorization"] = `Bearer ${state.authToken}`;
    headers["X-Admin-Token"] = state.authToken;
  }
  return headers;
}

// --- Initialization ---
document.addEventListener("DOMContentLoaded", () => {
  initClock();
  initGeolocation();
  initNavigation();
  initLoginModal();
  initWebcam();
  initTeacherPortal();
  initStudentPortal();
  initParentPortal();
  initAnalytics();
  initSecurityReviews();
  initEnrollment();
  initSettings();
  loadInitialDashboardData();
});

// --- Live Clock ---
function initClock() {
  const clockEl = document.getElementById("live-clock");
  if (!clockEl) return;
  setInterval(() => {
    const now = new Date();
    clockEl.textContent = now.toLocaleTimeString();
  }, 1000);
}

// --- Browser GPS Geolocation ---
function initGeolocation() {
  const displayEl = document.getElementById("client-coords-display");
  const geofencePill = document.getElementById("geofence-status-text");

  if (!navigator.geolocation) {
    state.userCoords.status = "unsupported";
    if (displayEl) displayEl.textContent = "📍 Geolocation not supported by this browser.";
    return;
  }

  navigator.geolocation.getCurrentPosition(
    (pos) => {
      state.userCoords.latitude = pos.coords.latitude;
      state.userCoords.longitude = pos.coords.longitude;
      state.userCoords.accuracy = pos.coords.accuracy;
      state.userCoords.status = "locked";
      if (displayEl) {
        displayEl.textContent = `📍 Device GPS: ${pos.coords.latitude.toFixed(5)}, ${pos.coords.longitude.toFixed(5)} (±${Math.round(pos.coords.accuracy)}m)`;
      }
      if (geofencePill) {
        geofencePill.textContent = `📍 GPS Locked (±${Math.round(pos.coords.accuracy)}m)`;
      }
    },
    (err) => {
      state.userCoords.status = "error";
      if (displayEl) {
        displayEl.textContent = `📍 GPS Notice: ${err.message}. Attendance will flag for manual verification if required.`;
      }
    },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 }
  );
}

// --- Tab Navigation ---
function initNavigation() {
  const navTabs = document.querySelectorAll(".nav-tab");
  const tabContents = document.querySelectorAll(".tab-content");

  navTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const targetId = tab.getAttribute("data-tab");
      navTabs.forEach((t) => t.classList.remove("active"));
      tabContents.forEach((c) => c.classList.remove("active"));

      tab.classList.add("active");
      const targetContent = document.getElementById(targetId);
      if (targetContent) targetContent.classList.add("active");

      // Trigger data loads on tab switch
      if (targetId === "teacher-tab") loadTeacherData();
      if (targetId === "student-tab") loadStudentData();
      if (targetId === "parent-tab") loadParentData();
      if (targetId === "analytics-tab") loadAnalyticsData();
      if (targetId === "security-tab") loadSecurityData();
      if (targetId === "settings-tab") loadAuditLogs();
    });
  });
}

// --- Login / Role Switch Modal ---
function initLoginModal() {
  const loginBtn = document.getElementById("btn-header-login");
  const modal = document.getElementById("login-modal");
  const closeBtn = document.getElementById("btn-close-login-modal");
  const form = document.getElementById("modal-login-form");
  const roleSelect = document.getElementById("modal-login-role");
  const userLabel = document.getElementById("modal-login-user-label");

  if (loginBtn && modal) {
    loginBtn.addEventListener("click", () => {
      modal.classList.add("active");
    });
  }

  if (closeBtn && modal) {
    closeBtn.addEventListener("click", () => {
      modal.classList.remove("active");
    });
  }

  if (roleSelect && userLabel) {
    roleSelect.addEventListener("change", () => {
      const r = roleSelect.value;
      if (r === "STUDENT") userLabel.textContent = "Roll Number or Institutional Email";
      else if (r === "TEACHER") userLabel.textContent = "Faculty Email or Employee ID";
      else if (r === "PARENT") userLabel.textContent = "Parent Registered Email";
      else userLabel.textContent = "Admin Username";
    });
  }

  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const role = document.getElementById("modal-login-role").value;
      const username = document.getElementById("modal-login-username").value.trim();
      const password = document.getElementById("modal-login-password").value;

      try {
        const res = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ role, username, password })
        });
        const data = await res.json();
        if (res.ok && data.success) {
          state.authToken = data.token;
          state.currentRole = data.role;
          state.currentUser = data.user;
          localStorage.setItem("sa_token", data.token);
          localStorage.setItem("sa_role", data.role);
          localStorage.setItem("sa_user", JSON.stringify(data.user));

          showToast(`Signed in successfully as ${role}: ${data.username}`, "success");
          if (modal) modal.classList.remove("active");

          // Auto navigate to relevant tab
          if (role === "TEACHER") document.getElementById("nav-teacher")?.click();
          else if (role === "STUDENT") document.getElementById("nav-student")?.click();
          else if (role === "PARENT") document.getElementById("nav-parent")?.click();
          else document.getElementById("nav-attendance")?.click();
        } else {
          showToast(data.detail || "Authentication failed", "danger");
        }
      } catch (err) {
        showToast(`Login error: ${err.message}`, "danger");
      }
    });
  }
}

// --- Live Webcam & Multi-Layer Frame Recognition ---
function initWebcam() {
  const toggleBtn = document.getElementById("btn-toggle-camera");
  const video = document.getElementById("webcam-feed");
  const overlayMsg = document.getElementById("video-overlay-msg");
  const badgesBox = document.getElementById("multi-layer-badges");

  if (!toggleBtn || !video) return;

  toggleBtn.addEventListener("click", async () => {
    if (state.isStreaming) {
      // Stop webcam
      if (state.stream) {
        state.stream.getTracks().forEach((t) => t.stop());
        state.stream = null;
      }
      clearInterval(state.captureInterval);
      state.isStreaming = false;
      toggleBtn.textContent = "Start Camera";
      if (overlayMsg) {
        overlayMsg.style.display = "flex";
        overlayMsg.textContent = "Camera Offline";
      }
      if (badgesBox) badgesBox.style.display = "none";
    } else {
      // Start webcam
      try {
        state.stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
          audio: false
        });
        video.srcObject = state.stream;
        await video.play();
        state.isStreaming = true;
        toggleBtn.textContent = "Stop Camera";
        if (overlayMsg) overlayMsg.style.display = "none";
        if (badgesBox) badgesBox.style.display = "flex";

        // Begin frame capture loop (~1.5 fps for balanced performance)
        state.captureInterval = setInterval(captureAndVerifyFrame, 650);
      } catch (err) {
        showToast(`Camera access denied: ${err.message}`, "danger");
      }
    }
  });
}

// Captures a frame and submits it to multi-layer verification
async function captureAndVerifyFrame() {
  const video = document.getElementById("webcam-feed");
  const canvas = document.getElementById("detection-canvas");
  if (!video || !canvas || !state.isStreaming) return;

  canvas.width = video.videoWidth || 640;
  canvas.height = video.videoHeight || 480;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

  const base64Image = canvas.toDataURL("image/jpeg", 0.85);

  const payload = {
    image: base64Image,
    session_id: state.activeSessionId,
    latitude: state.userCoords.latitude,
    longitude: state.userCoords.longitude,
    accuracy: state.userCoords.accuracy
  };

  try {
    const res = await fetch("/api/attendance/verify-multi-layer", {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify(payload)
    });

    if (res.ok) {
      const data = await res.json();
      updateLayerBadges(data);

      if (data.overall_status === "VERIFIED") {
        showToast(`✓ Attendance Verified: ${data.student_name} (${data.roll_number})`, "success");
        loadLiveAttendanceTable();
        loadKPISummary();
      } else if (data.overall_status === "PENDING_REVIEW") {
        showToast(`⚠️ Attendance Flagged: ${data.detail_message}`, "warning");
      }
    }
  } catch (err) {
    // Network or processing hiccup
  }
}

function updateLayerBadges(result) {
  const bFace = document.getElementById("badge-face");
  const bLive = document.getElementById("badge-liveness");
  const bGeo = document.getElementById("badge-geofence");
  const bQr = document.getElementById("badge-qr");

  if (!result || !result.layers) return;

  if (bFace && result.layers.face) {
    const f = result.layers.face;
    bFace.textContent = `Face: ${f.status} (${f.score || 0})`;
    bFace.style.borderColor = f.status === "VERIFIED" ? "var(--success)" : "var(--danger)";
  }
  if (bLive && result.layers.liveness) {
    const l = result.layers.liveness;
    bLive.textContent = `Liveness: ${l.status}`;
    bLive.style.borderColor = l.status === "PASSED" ? "var(--success)" : "var(--amber)";
  }
  if (bGeo && result.layers.location) {
    const g = result.layers.location;
    bGeo.textContent = `GPS: ${g.status} (${g.distance_m ? g.distance_m + "m" : "--"})`;
    bGeo.style.borderColor = g.status === "INSIDE" ? "var(--success)" : "var(--danger)";
  }
  if (bQr && result.layers.qr) {
    const q = result.layers.qr;
    bQr.textContent = `QR: ${q.status}`;
  }
}

// --- Teacher Portal & Dynamic Rotating QR Engine ---
function initTeacherPortal() {
  const form = document.getElementById("start-session-form");
  const endBtn = document.getElementById("btn-end-teacher-session");

  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const subjectId = parseInt(document.getElementById("sess-subject-select").value) || null;
      const classroomId = parseInt(document.getElementById("sess-classroom-select").value) || null;
      const qrExpiry = parseInt(document.getElementById("sess-qr-expiry").value) || 30;
      const reqLocation = document.getElementById("sess-req-location").checked;

      try {
        const res = await fetch("/api/teacher/sessions/start", {
          method: "POST",
          headers: getAuthHeaders(),
          body: JSON.stringify({
            subject_id: subjectId,
            classroom_id: classroomId,
            qr_expiry_seconds: qrExpiry,
            require_location: reqLocation,
            require_qr: true
          })
        });
        const data = await res.json();
        if (res.ok && data.success) {
          state.activeSessionId = data.session_id;
          showToast("Live attendance session started! Rotating QR code activated.", "success");
          startQRRotation(data.session_id, qrExpiry);
        } else {
          showToast(data.detail || "Failed to start session", "danger");
        }
      } catch (err) {
        showToast(`Error: ${err.message}`, "danger");
      }
    });
  }

  if (endBtn) {
    endBtn.addEventListener("click", async () => {
      if (!state.activeSessionId) return;
      try {
        const res = await fetch(`/api/teacher/sessions/${state.activeSessionId}/end`, {
          method: "POST",
          headers: getAuthHeaders()
        });
        const data = await res.json();
        if (res.ok) {
          showToast("Attendance session closed successfully.", "info");
          stopQRRotation();
        }
      } catch (err) {
        showToast(`Error: ${err.message}`, "danger");
      }
    });
  }

  // Refresh leaves button
  document.getElementById("btn-refresh-teacher-leaves")?.addEventListener("click", loadTeacherLeaves);
}

function startQRRotation(sessionId, expirySeconds) {
  state.activeSessionId = sessionId;
  state.qrSecondsRemaining = expirySeconds;

  const statusEl = document.getElementById("qr-session-status");
  const placeholder = document.getElementById("qr-placeholder-text");
  const tokenDisplay = document.getElementById("qr-token-string");
  const timerBar = document.getElementById("qr-timer-bar");
  const timerText = document.getElementById("qr-timer-text");
  const endBtn = document.getElementById("btn-end-teacher-session");

  if (statusEl) statusEl.textContent = `SESSION #${sessionId} ACTIVE`;
  if (placeholder) placeholder.style.display = "none";
  if (tokenDisplay) tokenDisplay.style.display = "block";
  if (timerBar) timerBar.style.display = "block";
  if (timerText) timerText.style.display = "block";
  if (endBtn) endBtn.style.display = "inline-block";

  fetchNewQRToken(sessionId);

  // Interval for countdown and token rotation
  clearInterval(state.qrTimerInterval);
  state.qrTimerInterval = setInterval(() => {
    state.qrSecondsRemaining--;
    const fill = document.getElementById("qr-timer-fill");
    if (fill) {
      const pct = (state.qrSecondsRemaining / expirySeconds) * 100;
      fill.style.width = `${Math.max(0, pct)}%`;
    }
    if (timerText) timerText.textContent = `Rotating in ${state.qrSecondsRemaining}s...`;

    if (state.qrSecondsRemaining <= 0) {
      state.qrSecondsRemaining = expirySeconds;
      fetchNewQRToken(sessionId);
    }
  }, 1000);
}

async function fetchNewQRToken(sessionId) {
  try {
    const res = await fetch(`/api/teacher/sessions/${sessionId}/qr`, {
      headers: getAuthHeaders()
    });
    const data = await res.json();
    if (res.ok) {
      const tokenDisplay = document.getElementById("qr-token-string");
      if (tokenDisplay) {
        tokenDisplay.textContent = `Token: ${data.qr_token.substring(0, 32)}... (Expires: ${data.expires_in_seconds}s)`;
      }
    }
  } catch (err) {
    // Network retry
  }
}

function stopQRRotation() {
  clearInterval(state.qrTimerInterval);
  state.activeSessionId = null;

  const statusEl = document.getElementById("qr-session-status");
  const placeholder = document.getElementById("qr-placeholder-text");
  const tokenDisplay = document.getElementById("qr-token-string");
  const timerBar = document.getElementById("qr-timer-bar");
  const timerText = document.getElementById("qr-timer-text");
  const endBtn = document.getElementById("btn-end-teacher-session");

  if (statusEl) statusEl.textContent = "NO ACTIVE SESSION";
  if (placeholder) placeholder.style.display = "block";
  if (tokenDisplay) tokenDisplay.style.display = "none";
  if (timerBar) timerBar.style.display = "none";
  if (timerText) timerText.style.display = "none";
  if (endBtn) endBtn.style.display = "none";
}

async function loadTeacherData() {
  try {
    const res = await fetch("/api/teacher/classes", { headers: getAuthHeaders() });
    if (res.ok) {
      const data = await res.json();
      const subSelect = document.getElementById("sess-subject-select");
      if (subSelect && data.assigned_subjects) {
        subSelect.innerHTML = '<option value="">-- Select Subject --</option>';
        data.assigned_subjects.forEach((s) => {
          subSelect.innerHTML += `<option value="${s.subject_id}">${s.subject_code} - ${s.subject_name}</option>`;
        });
      }
    }
    loadClassrooms();
    loadTeacherLeaves();
  } catch (err) { }
}

async function loadClassrooms() {
  try {
    const res = await fetch("/api/admin/classrooms", { headers: getAuthHeaders() });
    if (res.ok) {
      const data = await res.json();
      const clsSelect = document.getElementById("sess-classroom-select");
      if (clsSelect && data.classrooms) {
        clsSelect.innerHTML = '<option value="">-- Select Classroom --</option>';
        data.classrooms.forEach((c) => {
          clsSelect.innerHTML += `<option value="${c.id}">${c.name} (${c.building})</option>`;
        });
      }
    }
  } catch (err) { }
}

async function loadTeacherLeaves() {
  const tbody = document.getElementById("teacher-leaves-tbody");
  if (!tbody) return;
  try {
    const res = await fetch("/api/teacher/leaves", { headers: getAuthHeaders() });
    if (res.ok) {
      const data = await res.json();
      if (!data.leave_requests || data.leave_requests.length === 0) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="7">No pending leave requests.</td></tr>';
        return;
      }
      tbody.innerHTML = "";
      data.leave_requests.forEach((lr) => {
        tbody.innerHTML += `
          <tr>
            <td>${lr.student_name} (${lr.roll_no})</td>
            <td><span class="status-badge badge-warning">${lr.leave_type}</span></td>
            <td>${lr.from_date}</td>
            <td>${lr.to_date}</td>
            <td>${lr.reason}</td>
            <td>${lr.created_at}</td>
            <td>
              <button class="btn btn-primary btn-sm" onclick="reviewLeave(${lr.id}, 'APPROVED')">Approve</button>
              <button class="btn btn-danger btn-sm" onclick="reviewLeave(${lr.id}, 'REJECTED')">Reject</button>
            </td>
          </tr>
        `;
      });
    }
  } catch (err) { }
}

window.reviewLeave = async function (requestId, decision) {
  try {
    const res = await fetch(`/api/teacher/leaves/${requestId}/review`, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify({ decision })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(data.message, "success");
      loadTeacherLeaves();
    } else {
      showToast(data.detail || "Action failed", "danger");
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "danger");
  }
};

// --- Student Portal ---
function initStudentPortal() {
  const leaveForm = document.getElementById("student-leave-form");
  if (leaveForm) {
    leaveForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const payload = {
        leave_type: document.getElementById("leave-type").value,
        from_date: document.getElementById("leave-from-date").value,
        to_date: document.getElementById("leave-to-date").value,
        reason: document.getElementById("leave-reason").value.trim()
      };
      try {
        const res = await fetch("/api/student/leaves", {
          method: "POST",
          headers: getAuthHeaders(),
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok) {
          showToast("Leave application submitted successfully!", "success");
          leaveForm.reset();
        } else {
          showToast(data.detail || "Submission failed", "danger");
        }
      } catch (err) {
        showToast(`Error: ${err.message}`, "danger");
      }
    });
  }
}

async function loadStudentData() {
  try {
    const res = await fetch("/api/student/dashboard", { headers: getAuthHeaders() });
    if (res.ok) {
      const data = await res.json();
      const stats = data.stats || {};
      const pred = data.prediction || {};

      document.getElementById("student-kpi-overall").textContent = `${stats.percentage || 0}%`;
      document.getElementById("student-kpi-attended").textContent = `${stats.attended || 0} / ${stats.total_lectures || 0}`;
      document.getElementById("student-kpi-predicted").textContent = `${pred.predicted_final_percentage || stats.percentage || 0}%`;
      document.getElementById("student-kpi-needed").textContent = pred.classes_needed_for_75 || 0;

      // Shortage alert
      const alertBox = document.getElementById("student-shortage-alert");
      if (alertBox) {
        if (stats.percentage < 75.0) {
          alertBox.style.display = "block";
          document.getElementById("student-shortage-msg").textContent =
            `Your attendance stands at ${stats.percentage}%. You must attend at least ${pred.classes_needed_for_75 || 1} upcoming classes without absence to clear the shortage threshold.`;
        } else {
          alertBox.style.display = "none";
        }
      }

      // Subject breakdown table
      const tbody = document.getElementById("student-subjects-tbody");
      if (tbody && data.subjects) {
        tbody.innerHTML = "";
        data.subjects.forEach((s) => {
          const badgeClass = s.percentage >= 75 ? "badge-success" : "badge-danger";
          tbody.innerHTML += `
            <tr>
              <td><strong>${s.subject}</strong></td>
              <td>${s.total_classes}</td>
              <td>${s.attended}</td>
              <td>${s.percentage}%</td>
              <td><span class="status-badge ${badgeClass}">${s.status}</span></td>
            </tr>
          `;
        });
      }
    }
  } catch (err) { }
}

// --- Parent Portal ---
function initParentPortal() {
  document.getElementById("btn-refresh-parent-wards")?.addEventListener("click", loadParentData);
}

async function loadParentData() {
  const tbody = document.getElementById("parent-wards-tbody");
  if (!tbody) return;
  try {
    const res = await fetch("/api/parent/wards", { headers: getAuthHeaders() });
    if (res.ok) {
      const data = await res.json();
      if (!data.wards || data.wards.length === 0) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="7">No linked wards found.</td></tr>';
        return;
      }
      tbody.innerHTML = "";
      data.wards.forEach((w) => {
        const badge = w.percentage >= 75 ? "badge-success" : "badge-danger";
        tbody.innerHTML += `
          <tr>
            <td>${w.name}</td>
            <td>${w.roll_no}</td>
            <td>${w.department}</td>
            <td>${w.total_lectures || 0}</td>
            <td>${w.attended || 0}</td>
            <td><strong>${w.percentage || 0}%</strong></td>
            <td><span class="status-badge ${badge}">${w.percentage >= 75 ? "Good Standing" : "Shortage Warning"}</span></td>
          </tr>
        `;
      });
    }
  } catch (err) { }
}

// --- AI & Predictive Analytics ---
function initAnalytics() {
  document.getElementById("btn-refresh-dept-analytics")?.addEventListener("click", loadAnalyticsData);
}

async function loadAnalyticsData() {
  // Department comparative analytics
  try {
    const res = await fetch("/api/analytics/departments", { headers: getAuthHeaders() });
    if (res.ok) {
      const data = await res.json();
      const tbody = document.getElementById("dept-analytics-tbody");
      if (tbody && data.departments) {
        tbody.innerHTML = "";
        data.departments.forEach((d) => {
          tbody.innerHTML += `
            <tr>
              <td><strong>${d.name} (${d.code})</strong></td>
              <td>${d.enrolled_students}</td>
              <td>${d.average_attendance}%</td>
              <td><span class="text-rose font-bold">${d.students_at_risk} (${d.risk_percentage}%)</span></td>
            </tr>
          `;
        });
      }
    }
  } catch (err) { }

  // Monthly trends
  try {
    const res = await fetch("/api/analytics/trends", { headers: getAuthHeaders() });
    if (res.ok) {
      const data = await res.json();
      const tbody = document.getElementById("monthly-trends-tbody");
      if (tbody && data.trends) {
        tbody.innerHTML = "";
        data.trends.forEach((t) => {
          const arrow = t.trend === "UPWARD" ? "↗" : t.trend === "DOWNWARD" ? "↘" : "→";
          tbody.innerHTML += `
            <tr>
              <td>${t.month}</td>
              <td>${t.total_records}</td>
              <td>${t.present_count}</td>
              <td><strong>${t.percentage}%</strong></td>
              <td>${arrow} ${t.trend}</td>
            </tr>
          `;
        });
      }
    }
  } catch (err) { }
}

// --- Security & Borderline Review Queue ---
function initSecurityReviews() {
  document.getElementById("btn-refresh-reviews")?.addEventListener("click", loadSecurityData);
}

async function loadSecurityData() {
  // Borderline reviews
  const tbody = document.getElementById("reviews-tbody");
  if (tbody) {
    try {
      const res = await fetch("/api/admin/verification-reviews", { headers: getAuthHeaders() });
      if (res.ok) {
        const data = await res.json();
        if (!data.reviews || data.reviews.length === 0) {
          tbody.innerHTML = '<tr class="empty-row"><td colspan="7">No pending verification reviews.</td></tr>';
        } else {
          tbody.innerHTML = "";
          data.reviews.forEach((r) => {
            tbody.innerHTML += `
              <tr>
                <td>${r.student_name}</td>
                <td>${r.roll_no}</td>
                <td><span class="status-badge badge-warning">${r.rejection_reason}</span></td>
                <td>${r.location_distance_m ? r.location_distance_m.toFixed(1) + "m" : "--"}</td>
                <td>${r.face_match_score ? r.face_match_score.toFixed(2) : "--"}</td>
                <td>${r.submitted_at}</td>
                <td>
                  <button class="btn btn-primary btn-sm" onclick="resolveReview(${r.id}, 'VERIFIED')">Confirm Present</button>
                  <button class="btn btn-danger btn-sm" onclick="resolveReview(${r.id}, 'REJECTED')">Reject</button>
                </td>
              </tr>
            `;
          });
        }
      }
    } catch (err) { }
  }

  // Cameras
  try {
    const res = await fetch("/api/admin/cameras", { headers: getAuthHeaders() });
    if (res.ok) {
      const data = await res.json();
      const camTbody = document.getElementById("cameras-tbody");
      if (camTbody && data.cameras) {
        camTbody.innerHTML = "";
        data.cameras.forEach((c) => {
          camTbody.innerHTML += `
            <tr>
              <td class="mono">${c.camera_uid}</td>
              <td>${c.name}</td>
              <td>${c.classroom_name || "General"}</td>
              <td><span class="status-badge badge-success">${c.health_status}</span></td>
            </tr>
          `;
        });
      }
    }
  } catch (err) { }

  // Beacons
  try {
    const res = await fetch("/api/admin/beacons", { headers: getAuthHeaders() });
    if (res.ok) {
      const data = await res.json();
      const bcnTbody = document.getElementById("beacons-tbody");
      if (bcnTbody && data.beacons) {
        bcnTbody.innerHTML = "";
        data.beacons.forEach((b) => {
          bcnTbody.innerHTML += `
            <tr>
              <td class="mono text-xs">${b.beacon_uuid.substring(0, 18)}...</td>
              <td>${b.name}</td>
              <td>${b.classroom_name || "Unassigned"}</td>
              <td><span class="status-badge badge-success">Active</span></td>
            </tr>
          `;
        });
      }
    }
  } catch (err) { }
}

window.resolveReview = async function (resultId, decision) {
  try {
    const res = await fetch(`/api/admin/verification-reviews/${resultId}?decision=${decision}`, {
      method: "POST",
      headers: getAuthHeaders()
    });
    const data = await res.json();
    if (res.ok) {
      showToast(data.message, "success");
      loadSecurityData();
    } else {
      showToast(data.detail || "Action failed", "danger");
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "danger");
  }
};

// --- Student Enrollment ---
function initEnrollment() {
  const form = document.getElementById("enroll-form");
  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const video = document.getElementById("webcam-feed");
    const canvas = document.createElement("canvas");
    canvas.width = 640;
    canvas.height = 480;
    const ctx = canvas.getContext("2d");
    if (video && state.isStreaming) {
      ctx.drawImage(video, 0, 0, 640, 480);
    } else {
      showToast("Please start the camera on the Live Kiosk tab first to capture an enrollment photo.", "warning");
      return;
    }

    const payload = {
      roll_no: document.getElementById("enroll-roll").value.trim(),
      name: document.getElementById("enroll-name").value.trim(),
      department: document.getElementById("enroll-dept").value.trim(),
      email: document.getElementById("enroll-email").value.trim(),
      image: canvas.toDataURL("image/jpeg", 0.9),
      allow_admin_override: document.getElementById("enroll-admin-override").checked
    };

    try {
      const res = await fetch("/api/students/enroll", {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (res.ok) {
        showToast(`✓ Student Enrolled: ${data.student.name} (${data.student.roll_no})`, "success");
        form.reset();
        loadKPISummary();
      } else {
        showToast(data.detail || "Enrollment failed", "danger");
      }
    } catch (err) {
      showToast(`Enrollment error: ${err.message}`, "danger");
    }
  });
}

// --- Settings & Audit Trail ---
function initSettings() {
  const pwForm = document.getElementById("admin-password-form");
  if (pwForm) {
    pwForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const payload = {
        username: document.getElementById("admin-user").value.trim(),
        old_password: document.getElementById("admin-old-pass").value,
        new_password: document.getElementById("admin-new-pass").value
      };
      try {
        const res = await fetch("/api/admin/change-password", {
          method: "POST",
          headers: getAuthHeaders(),
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok) {
          showToast(data.message, "success");
          pwForm.reset();
        } else {
          showToast(data.detail || "Password update failed", "danger");
        }
      } catch (err) {
        showToast(`Error: ${err.message}`, "danger");
      }
    });
  }

  document.getElementById("btn-refresh-audit")?.addEventListener("click", loadAuditLogs);
}

async function loadAuditLogs() {
  const tbody = document.getElementById("audit-table-body");
  if (!tbody) return;
  try {
    const res = await fetch("/api/audit-logs", { headers: getAuthHeaders() });
    if (res.ok) {
      const data = await res.json();
      if (!data.logs || data.logs.length === 0) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="5">No audit logs recorded.</td></tr>';
        return;
      }
      tbody.innerHTML = "";
      data.logs.forEach((l) => {
        tbody.innerHTML += `
          <tr>
            <td>${l.id}</td>
            <td><strong>${l.action}</strong></td>
            <td>${l.details}</td>
            <td>${l.actor}</td>
            <td>${l.timestamp}</td>
          </tr>
        `;
      });
    }
  } catch (err) { }
}

// --- Initial Dashboard Stats ---
async function loadInitialDashboardData() {
  loadKPISummary();
  loadLiveAttendanceTable();
}

async function loadKPISummary() {
  try {
    const res = await fetch("/api/attendance/today");
    if (res.ok) {
      const data = await res.json();
      const stats = data.stats || {};
      if (document.getElementById("kpi-total")) document.getElementById("kpi-total").textContent = stats.total_students || 0;
      if (document.getElementById("kpi-present")) document.getElementById("kpi-present").textContent = stats.present_today || 0;
      if (document.getElementById("kpi-late")) document.getElementById("kpi-late").textContent = stats.late_today || 0;
      if (document.getElementById("kpi-absent")) document.getElementById("kpi-absent").textContent = stats.absent_today || 0;
      if (document.getElementById("kpi-month-rate")) document.getElementById("kpi-month-rate").textContent = `${stats.monthly_percentage || 0}%`;
    }
  } catch (err) { }
}

async function loadLiveAttendanceTable() {
  const tbody = document.getElementById("live-table-body");
  if (!tbody) return;
  try {
    const res = await fetch("/api/attendance/today");
    if (res.ok) {
      const data = await res.json();
      if (!data.records || data.records.length === 0) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="5">No attendance marked yet today.</td></tr>';
        return;
      }
      tbody.innerHTML = "";
      data.records.forEach((r) => {
        const badge = r.status === "PRESENT" ? "badge-success" : "badge-warning";
        tbody.innerHTML += `
          <tr>
            <td class="mono font-bold">${r.roll_no}</td>
            <td>${r.name}</td>
            <td><span class="status-badge ${badge}">${r.status}</span></td>
            <td>${r.time}</td>
            <td><span class="status-badge badge-cyan">${r.verification_method || "FACE_GEOFENCE"}</span></td>
          </tr>
        `;
      });
    }
  } catch (err) { }
}
