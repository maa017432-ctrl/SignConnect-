(function () {
  "use strict";

  /* ── Element refs ─────────────────────────────────────────── */
  const themeToggle     = document.getElementById("theme-toggle");
  const video           = document.getElementById("video-stream");
  const videoOverlay    = document.getElementById("video-overlay");
  const recognizedText  = document.getElementById("recognized-text");
  const confidenceBadge = document.getElementById("confidence-badge");
  const sentenceDisplay = document.getElementById("sentence-display");
  const commitProgress  = document.getElementById("commit-progress");
  const progressHint    = document.getElementById("progress-hint");
  const historyList     = document.getElementById("history-list");
  const cameraStatus    = document.getElementById("camera-status");
  const cameraDot       = document.getElementById("camera-dot");
  const modelStatus     = document.getElementById("model-status");
  const modelDot        = document.getElementById("model-dot");
  const fpsStatus       = document.getElementById("fps-status");
  const startBtn        = document.getElementById("start-btn");
  const pauseBtn        = document.getElementById("pause-btn");
  const clearBtn        = document.getElementById("clear-btn");
  const deleteWordBtn   = document.getElementById("delete-word-btn");
  const speakBtn        = document.getElementById("speak-btn");
  const refreshHistBtn  = document.getElementById("refresh-history-btn");
  const clearHistBtn    = document.getElementById("clear-history-btn");
  const langSelect      = document.getElementById("lang-select");
  const thresholdSlider = document.getElementById("threshold-slider");
  const thresholdVal    = document.getElementById("threshold-val");
  const trainingModeToggle = document.getElementById("training-mode-toggle");
  const topkPanel = document.getElementById("topk-panel");
  const topkList = document.getElementById("topk-list");

  /* ── Stream state ─────────────────────────────────────────── */
  const FRAME_MS      = 80;    // ~12.5 fps camera polling target
  const STATUS_MS     = 4000;
  const PREDICT_MS    = 300;   // HTTP fallback prediction poll interval

  let streamTimer      = null;
  let predictionTimer  = null; // set only when socket.io unavailable
  let paused           = true;
  let frameInFlight    = false;
  let blobUrl          = null;
  let prevFrameAt      = 0;
  let fpsWindow        = [];   // sliding window of frame intervals (ms)

  /* ── WebSocket (socket.io) — push-based predictions ─────────── */
  let socketConnected = false;

  function initSocket() {
    if (typeof io === "undefined") {
      startPredictionPoll();
      return;
    }
    const socket = io({
      reconnectionAttempts: 5,
      timeout: 4000,
      transports: ["websocket", "polling"],
    });

    socket.on("connect", () => {
      socketConnected = true;
      // Stop HTTP polling if it was running as a fallback
      if (predictionTimer) { clearInterval(predictionTimer); predictionTimer = null; }
      LOGGER("WebSocket connected — switching from HTTP poll to push");
    });

    socket.on("disconnect", () => {
      socketConnected = false;
      // Restart HTTP polling as fallback while disconnected
      if (!predictionTimer) startPredictionPoll();
    });

    socket.on("connect_error", () => {
      if (!socketConnected && !predictionTimer) startPredictionPoll();
    });

    socket.on("prediction", (data) => {
      updatePredictionUI(data);
    });
  }

  function startPredictionPoll() {
    if (predictionTimer) return;
    predictionTimer = setInterval(pollPrediction, PREDICT_MS);
    pollPrediction();
  }

  function LOGGER(msg) {
    if (typeof console !== "undefined") console.debug("[SignConnect]", msg);
  }

  /* ── Frame URLs ────────────────────────────────────────────── */
  function mjpegUrl() {
    return (video && video.dataset.mjpegUrl) || "/video_feed";
  }

  function frameUrl() {
    return (video && video.dataset.frameUrl) || "/api/camera_frame";
  }

  /* ── Loading overlay ──────────────────────────────────────── */
  function showOverlay(text) {
    if (!videoOverlay) return;
    const msg = videoOverlay.querySelector(".overlay-msg");
    if (msg) msg.textContent = text || "Connecting to camera…";
    videoOverlay.classList.remove("hidden");
  }

  function hideOverlay() {
    if (videoOverlay) videoOverlay.classList.add("hidden");
  }

  /* ── Theme toggle ─────────────────────────────────────────── */
  function initTheme() {
    const saved = localStorage.getItem("sc_theme") || "dark";
    document.body.setAttribute("data-theme", saved);
    if (themeToggle) {
      themeToggle.textContent = saved === "dark" ? "☀ Light" : "🌙 Dark";
      themeToggle.addEventListener("click", () => {
        const next =
          document.body.getAttribute("data-theme") === "dark" ? "light" : "dark";
        document.body.setAttribute("data-theme", next);
        themeToggle.textContent = next === "dark" ? "☀ Light" : "🌙 Dark";
        localStorage.setItem("sc_theme", next);
      });
    }
  }

  /* ── Status dot helpers ───────────────────────────────────── */
  function setDot(dot, state) {
    if (!dot) return;
    dot.className = "status-dot " + (state || "");
  }

  /* ── Poll /api/status (slow — health chips only) ──────────── */
  async function pollStatus() {
    try {
      const res  = await fetch("/api/status", { cache: "no-store" });
      const data = await res.json();

      if (cameraStatus) {
        const ok = data.camera && data.camera_frame_route !== false;
        cameraStatus.textContent = ok ? "Camera: OK" : "Camera: DOWN";
        setDot(cameraDot, ok ? "ok" : "err");
      }
      if (modelStatus) {
        const label = !data.model ? "DOWN" : data.model_demo_mode ? "DEMO" : "OK";
        modelStatus.textContent = `Model: ${label}`;
        setDot(modelDot, data.model ? (data.model_demo_mode ? "warn" : "ok") : "err");
      }
      updateFpsDisplay();
    } catch {
      if (cameraStatus) cameraStatus.textContent = "Camera: ERR";
      setDot(cameraDot, "err");
    }
  }

  function updateFpsDisplay() {
    if (!fpsStatus) return;
    if (paused || fpsWindow.length === 0) {
      fpsStatus.textContent = "FPS: —";
      return;
    }
    const avg = fpsWindow.reduce((a, b) => a + b, 0) / fpsWindow.length;
    fpsStatus.textContent = `FPS: ${Math.min(60, Math.max(1, Math.round(1000 / Math.max(16, avg))))}`;
  }

  /* ── Shared prediction UI updater (called by socket OR poll) ── */
  function updatePredictionUI(data) {
    const display = data.smoothed_label || data.label;
    if (recognizedText) recognizedText.textContent = display || "—";
    updateConfidence(display ? data.confidence : 0);
    updateSentenceDisplay(data.sentence || "");
    updateProgressBar(data.current_run, data.stable_frames, data.is_cooling_down);
    updateTopCandidates(data.top_candidates || []);
  }

  function updateTopCandidates(candidates) {
    if (!topkList) return;
    topkList.innerHTML = "";
    if (!Array.isArray(candidates) || candidates.length === 0) {
      const li = document.createElement("li");
      li.textContent = "No candidate predictions yet.";
      topkList.appendChild(li);
      return;
    }
    candidates.slice(0, 3).forEach((item, idx) => {
      const label = item && item.label ? String(item.label) : "Unknown";
      const score = Math.round((Number(item?.confidence) || 0) * 100);
      const li = document.createElement("li");
      li.innerHTML = `
        <span class="topk-label">${idx + 1}. ${escHtml(label)}</span>
        <span class="topk-score">${score}%</span>
      `;
      topkList.appendChild(li);
    });
  }

  /* ── HTTP fallback poll for /api/prediction ───────────────── */
  async function pollPrediction() {
    if (socketConnected) return; // socket push takes over — skip
    try {
      const res  = await fetch("/api/prediction", { cache: "no-store" });
      const data = await res.json();
      updatePredictionUI(data);
    } catch { /* ignore */ }
  }

  /* ── Sentence display ─────────────────────────────────────── */
  function updateSentenceDisplay(sentence) {
    if (!sentenceDisplay) return;
    if (sentence) {
      sentenceDisplay.textContent = sentence;
      sentenceDisplay.classList.add("has-content");
    } else {
      sentenceDisplay.textContent = "…";
      sentenceDisplay.classList.remove("has-content");
    }
  }

  /* ── Progress bar ─────────────────────────────────────────── */
  function updateProgressBar(currentRun, stableFrames, coolingDown) {
    if (!commitProgress) return;

    if (coolingDown) {
      commitProgress.style.width = "100%";
      commitProgress.classList.add("cooling");
      if (progressHint) progressHint.textContent = "Word committed! Lower hand to continue.";
      return;
    }

    commitProgress.classList.remove("cooling");

    const fraction = stableFrames > 0
      ? Math.min(1, (currentRun || 0) / stableFrames)
      : 0;
    commitProgress.style.width = `${Math.round(fraction * 100)}%`;

    if (progressHint) {
      if (fraction === 0) {
        progressHint.textContent = "Hold a gesture steadily to build a word";
      } else if (fraction < 1) {
        const remaining = stableFrames - (currentRun || 0);
        progressHint.textContent = `Hold… ${remaining} frame${remaining === 1 ? "" : "s"} to commit`;
      } else {
        progressHint.textContent = "Committing…";
      }
    }
  }

  /* ── Confidence badge ─────────────────────────────────────── */
  function updateConfidence(raw) {
    if (!confidenceBadge) return;
    const pct = Math.round((raw || 0) * 100);
    confidenceBadge.textContent = `${pct}%`;
    confidenceBadge.className =
      "badge " + (pct > 85 ? "high" : pct > 70 ? "mid" : "low");
  }

  /* ── Language selector ────────────────────────────────────── */
  function getSelectedLang() {
    if (langSelect) return langSelect.value;
    return localStorage.getItem("sc_lang") || "en";
  }

  function initLanguageSelector() {
    if (!langSelect) return;
    const saved = localStorage.getItem("sc_lang") || "en";
    langSelect.value = saved;
    langSelect.addEventListener("change", () => {
      localStorage.setItem("sc_lang", langSelect.value);
    });
  }

  /* ── Confidence threshold slider ──────────────────────────── */
  function initThresholdSlider() {
    if (!thresholdSlider) return;

    // Load current server value
    fetch("/api/config", { cache: "no-store" })
      .then((r) => r.json())
      .then((data) => {
        const pct = Math.round((data.confidence_threshold || 0.75) * 100);
        thresholdSlider.value = pct;
        if (thresholdVal) thresholdVal.textContent = `${pct}%`;
      })
      .catch(() => {});

    let debounce = null;
    thresholdSlider.addEventListener("input", () => {
      const pct = parseInt(thresholdSlider.value, 10);
      if (thresholdVal) thresholdVal.textContent = `${pct}%`;
      clearTimeout(debounce);
      debounce = setTimeout(() => {
        fetch("/api/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confidence_threshold: pct / 100 }),
        }).catch(() => {});
      }, 350);
    });
  }

  function setTrainingMode(enabled) {
    if (topkPanel) topkPanel.classList.toggle("hidden", !enabled);
    if (trainingModeToggle) trainingModeToggle.checked = !!enabled;
    localStorage.setItem("sc_training_mode", enabled ? "1" : "0");
  }

  function initTrainingMode() {
    if (!trainingModeToggle && !topkPanel) return;
    const saved = localStorage.getItem("sc_training_mode");
    const enabled = saved === null ? true : saved === "1";
    setTrainingMode(enabled);
    if (trainingModeToggle) {
      trainingModeToggle.addEventListener("change", () => {
        setTrainingMode(trainingModeToggle.checked);
      });
    }
  }

  /* ── Speak ────────────────────────────────────────────────── */
  async function speakText() {
    /* Prefer the full sentence; fall back to current gesture label */
    const sentence =
      sentenceDisplay && sentenceDisplay.classList.contains("has-content")
        ? sentenceDisplay.textContent.trim()
        : null;
    const text =
      sentence || (recognizedText ? recognizedText.textContent.trim() : "");

    if (!text || text === "—" || text === "…") return;

    try {
      const res = await fetch("/api/translate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, lang: getSelectedLang() }),
      });
      if (!res.ok) return;
      const data = await res.json();
      if (data.audio_url) new Audio(data.audio_url).play().catch(() => {});
      refreshHistorySidebar();
    } catch { /* ignore */ }
  }

  /* ── Delete last word ─────────────────────────────────────── */
  async function deleteLastWord() {
    try {
      const res  = await fetch("/api/sentence/delete", { method: "POST" });
      const data = await res.json();
      updateSentenceDisplay(data.sentence || "");
    } catch { /* ignore */ }
  }

  /* ── Clear sentence ───────────────────────────────────────── */
  async function clearSentence() {
    try {
      await fetch("/api/sentence/clear", { method: "POST" });
    } catch { /* ignore */ }
    updateSentenceDisplay("");
    updateProgressBar(0, 15, false);
  }

  /* ── Clear history (history page) ────────────────────────── */
  async function clearHistory() {
    try {
      await fetch("/api/history", { method: "DELETE" });
    } catch { /* network error */ }
    refreshHistoryPage();
  }

  /* ── History (translator sidebar) ────────────────────────── */
  async function refreshHistorySidebar() {
    if (!historyList) return;
    try {
      const res  = await fetch("/api/history", { cache: "no-store" });
      const data = await res.json();
      historyList.innerHTML = "";
      if (data.length === 0) {
        const li = document.createElement("li");
        li.textContent = "No translations yet.";
        historyList.appendChild(li);
        return;
      }
      data.slice(0, 10).forEach((item) => {
        const li = document.createElement("li");
        li.textContent = `${item.gesture_label} · ${
          item.created_at ? item.created_at.slice(0, 16) : ""
        }`;
        historyList.appendChild(li);
      });
      historyList.scrollTop = historyList.scrollHeight;
    } catch { /* ignore */ }
  }

  /* ── History page (full table) ───────────────────────────── */
  async function refreshHistoryPage() {
    const tbody = document.getElementById("history-tbody");
    if (!tbody) return;
    try {
      const res  = await fetch("/api/history", { cache: "no-store" });
      const data = await res.json();
      tbody.innerHTML = "";
      if (data.length === 0) {
        tbody.innerHTML =
          '<tr><td colspan="4" class="history-empty">No history yet.</td></tr>';
        return;
      }
      data.forEach((item) => {
        const tr    = document.createElement("tr");
        const audio = item.audio_file
          ? `<audio src="/static/audio/${item.audio_file}" controls preload="none"></audio>`
          : "—";
        tr.innerHTML = `
          <td>${escHtml(item.gesture_label)}</td>
          <td>${
            item.confidence != null
              ? (item.confidence * 100).toFixed(1) + "%"
              : "—"
          }</td>
          <td>${audio}</td>
          <td>${item.created_at ? item.created_at.slice(0, 16) : "—"}</td>
        `;
        tbody.appendChild(tr);
      });
    } catch { /* ignore */ }
  }

  function escHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /* ── Camera frame polling ─────────────────────────────────── */
  async function tickFrame() {
    if (paused || frameInFlight || !video) return;
    frameInFlight = true;
    try {
      const res = await fetch(`${frameUrl()}?_=${Date.now()}`, {
        cache: "no-store",
      });
      if (!res.ok) {
        showOverlay(
          res.status === 404
            ? "Route not found — restart app.py"
            : "Camera error"
        );
        return;
      }
      const blob = await res.blob();
      if (!blob.type || !blob.type.startsWith("image/")) return;

      const url = URL.createObjectURL(blob);
      if (blobUrl) URL.revokeObjectURL(blobUrl);
      blobUrl = url;
      video.src = url;

      /* Per-frame FPS */
      const now = Date.now();
      if (prevFrameAt > 0) {
        fpsWindow.push(now - prevFrameAt);
        if (fpsWindow.length > 10) fpsWindow.shift();
      }
      prevFrameAt = now;
      hideOverlay();
    } catch { /* network hiccup */ } finally {
      frameInFlight = false;
    }
  }

  function startStream() {
    paused = false;
    if (streamTimer) clearInterval(streamTimer);
    streamTimer = null;

    if (video) {
      video.src = mjpegUrl();
      video.onload = () => hideOverlay();
      video.onerror = () => {
        showOverlay("Camera error — retrying…");
        setTimeout(() => { if (!paused && video) video.src = mjpegUrl(); }, 3000);
      };
    }

    showOverlay("Connecting to camera…");
    if (startBtn) startBtn.disabled = true;
    if (pauseBtn) pauseBtn.disabled = false;
    setDot(cameraDot, "pulsing");
  }

  function pauseStream() {
    paused = true;
    if (streamTimer) { clearInterval(streamTimer); streamTimer = null; }
    if (video) video.removeAttribute("src");
    if (blobUrl) { URL.revokeObjectURL(blobUrl); blobUrl = null; }
    prevFrameAt = 0;
    fpsWindow   = [];
    showOverlay("Stream paused");
    if (startBtn) startBtn.disabled = false;
    if (pauseBtn) pauseBtn.disabled = true;
    updateFpsDisplay();
  }

  /* ── Bind buttons ─────────────────────────────────────────── */
  function bindButtons() {
    if (startBtn)      startBtn.addEventListener("click", startStream);
    if (pauseBtn) {
      pauseBtn.addEventListener("click", pauseStream);
      pauseBtn.disabled = true;
    }
    if (speakBtn)      speakBtn.addEventListener("click", speakText);
    if (deleteWordBtn) deleteWordBtn.addEventListener("click", deleteLastWord);
    if (clearBtn)      clearBtn.addEventListener("click", clearSentence);
    if (refreshHistBtn) refreshHistBtn.addEventListener("click", refreshHistoryPage);
    if (clearHistBtn)   clearHistBtn.addEventListener("click", clearHistory);
  }

  /* ── Mark active nav link ─────────────────────────────────── */
  function markActiveNav() {
    document.querySelectorAll(".site-header nav a").forEach((a) => {
      if (a.href === location.href) a.classList.add("active");
    });
  }

  /* ── Boot ─────────────────────────────────────────────────── */
  initTheme();
  initLanguageSelector();
  initThresholdSlider();
  initTrainingMode();
  bindButtons();
  markActiveNav();

  /* Translator page */
  if (video) {
    startStream();
    initSocket();           // WebSocket push; HTTP poll used only as fallback
    refreshHistorySidebar().catch(() => {});
    updateConfidence(0);
    updateProgressBar(0, 15, false);
  }

  /* History page */
  if (document.getElementById("history-tbody")) {
    refreshHistoryPage().catch(() => {});
  }

  /* All pages */
  setInterval(pollStatus, STATUS_MS);
  pollStatus();
  setInterval(updateFpsDisplay, 1000);
})();
