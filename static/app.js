/* Human Counter v2 — papan kendali. Semua data dari server /api/v1.
 * Escape semua teks dinamis (tidak ada innerHTML dengan data tak tepercaya).
 */
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));

const state = {
  cameras: [],
  editors: {}, // cameraId -> hls instance
  overlayScale: {}, // cameraId -> {sx, sy} fraksi video→tampil
  editor: null, // {cameraId, points: [], video}
  lastImgFetch: {}, // cameraId -> ts ms (jeda gambar teranotasi)
  liveMode: new Set(), // kamera yang di-set ke video langsung
};

/* ---------------- util ---------------- */
async function api(path, options) {
  const resp = await fetch(path, options);
  const payload = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(payload.detail || payload.error || `HTTP ${resp.status}`);
  return payload;
}

function todayStr(offsetDays = 0) {
  const d = new Date(Date.now() + offsetDays * 86400000);
  return d.toISOString().slice(0, 10);
}

/* ---------------- putar semua (gestur pengguna) ---------------- */
$("play-all").addEventListener("click", async () => {
  let n = 0;
  for (const v of document.querySelectorAll(".cam-video")) {
    try { await v.play(); n += 1; } catch { /* lanjut */ }
  }
  $("sse-status").textContent = `▶ ${n} video diputar`;
});

/* ---------------- boot ---------------- */
window.addEventListener("load", async () => {
  $("date-picker").value = todayStr();
  $("date-picker").addEventListener("change", refreshAll);
  $("export-btn").href = `/api/v1/export.csv?from=${todayStr()}`;
  await boot();
  connectSSE();
  setInterval(refreshCameras, 1500);
  setInterval(refreshStats, 5000);
});

async function boot() {
  try {
    const payload = await api("/api/v1/cameras");
    state.cameras = payload.cameras;
    buildGrid();
    await refreshStats();
    refreshCameras();
  } catch (err) {
    $("camera-grid").innerHTML =
      `<div class="boot-error">Backend belum siap: ${esc(err.message)} — coba muat ulang.</div>`;
  }
}

/* ---------------- grid kamera ---------------- */
function buildGrid() {
  const grid = $("camera-grid");
  grid.innerHTML = "";
  for (const cam of state.cameras) {
    const card = document.createElement("div");
    card.className = "cam-card";
    card.innerHTML = `
      <div class="cam-head">
        <span class="cam-name" title="${esc(cam.name)}">${esc(cam.name)}</span>
        <span class="cam-badge" id="badge-${esc(cam.id)}">…</span>
      </div>
      <div class="cam-stage" id="stage-${esc(cam.id)}">
        <video id="video-${esc(cam.id)}" class="cam-video" muted autoplay playsinline></video>
        <canvas id="overlay-${esc(cam.id)}" class="cam-overlay"></canvas>
        <img id="annot-${esc(cam.id)}" class="cam-annotated" alt="deteksi teranotasi" />
        <button class="btn btn-live" data-live="${esc(cam.id)}">LIVE VIDEO</button>
      </div>
      <div class="cam-foot">
        <span class="inout">▲<b id="in-${esc(cam.id)}">0</b> ▼<b id="out-${esc(cam.id)}">0</b></span>
        <span id="fps-${esc(cam.id)}">– fps</span>
        <button class="btn btn-line" data-cam="${esc(cam.id)}">atur garis</button>
      </div>`;
    grid.appendChild(card);
    attachHls(card.querySelector(`#video-${CSS.escape(cam.id)}`), cam.streamUrl);
  }
  grid.addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-cam]");
    if (btn) openEditor(btn.dataset.cam);
    const live = event.target.closest("button[data-live]");
    if (live) {
      const camId = live.dataset.live;
      const img = $(`annot-${CSS.escape(camId)}`);
      if (state.liveMode.has(camId)) {
        state.liveMode.delete(camId);
        live.textContent = "LIVE VIDEO";
        if (img) img.hidden = false;
      } else {
        state.liveMode.add(camId);
        live.textContent = "TAMPILAN DETEKSI";
        if (img) img.hidden = true;
      }
    }
  });
}

function attachHls(video, url) {
  if (window.Hls && window.Hls.isSupported()) {
    const hls = new window.Hls({ liveDurationInfinity: true });
    hls.loadSource(url);
    hls.attachMedia(video);
    hls.on(window.Hls.Events.ERROR, (_e, data) => {
      if (data.fatal) setTimeout(() => {
        hls.destroy();
        attachHls(video, url);
      }, 3000);
    });
  } else {
    video.src = url; // Safari
  }
}

/* refresh ringan tiap 1.5s: status, kotak, garis, penghitung sesi */
async function refreshCameras() {
  let payload;
  try {
    payload = await api("/api/v1/cameras");
  } catch { return; }
  for (const cam of payload.cameras) {
    const badge = $(`badge-${CSS.escape(cam.id)}`);
    if (badge) {
      badge.textContent = cam.status.toUpperCase();
      badge.className = `cam-badge ${cam.status.toLowerCase()}`;
    }
    const inEl = $(`in-${CSS.escape(cam.id)}`);
    const outEl = $(`out-${CSS.escape(cam.id)}`);
    if (inEl) inEl.textContent = cam.inCount;
    if (outEl) outEl.textContent = cam.outCount;
    const fpsEl = $(`fps-${CSS.escape(cam.id)}`);
    if (fpsEl) fpsEl.textContent = `${cam.fps.toFixed(1)} fps · conf ${cam.avgConf.toFixed(2)}`;
    const canvas = $(`overlay-${CSS.escape(cam.id)}`);
    const video = $(`video-${CSS.escape(cam.id)}`);
    const annot = $(`annot-${CSS.escape(cam.id)}`);
    const nowMs = Date.now();
    if (annot && nowMs - (state.lastImgFetch?.[cam.id] || 0) > 4000
        && !state.liveMode.has(cam.id)) {
      state.lastImgFetch = state.lastImgFetch || {};
      state.lastImgFetch[cam.id] = nowMs;
      annot.src = `/api/v1/annotated/${encodeURIComponent(cam.id)}?t=${nowMs}`;
    }
    if (video && video.paused && video.readyState >= 2) video.play().catch(() => {});
    if (canvas && video && video.videoWidth) drawOverlay(canvas, video, cam);
  }
}

function drawOverlay(canvas, video, cam) {
  const w = video.clientWidth, h = video.clientHeight;
  if (!w || !h) return;
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w; canvas.height = h;
  }
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, w, h);
  const sx = w / (video.videoWidth || w);
  const sy = h / (video.videoHeight || h);
  // garis hitung
  ctx.strokeStyle = "#ffd166";
  ctx.lineWidth = 2;
  for (const line of cam.lines || []) {
    ctx.beginPath();
    ctx.moveTo(line.p1x * w, line.p1y * h);
    ctx.lineTo(line.p2x * w, line.p2y * h);
    ctx.stroke();
  }
  // kotak jejak
  ctx.font = "10px monospace";
  for (const [tid, box, conf] of cam.boxes || []) {
    const [x, y, bw, bh] = box;
    ctx.strokeStyle = "rgba(0, 229, 255, 0.9)";
    ctx.strokeRect(x * sx, y * sy, bw * sx, bh * sy);
    const label = `#${tid} ${Math.round(conf * 100)}%`;
    ctx.fillStyle = "rgba(0, 229, 255, 0.9)";
    ctx.fillRect(x * sx, Math.max(0, y * sy - 13), ctx.measureText(label).width + 6, 13);
    ctx.fillStyle = "#04070b";
    ctx.fillText(label, x * sx + 3, Math.max(10, y * sy - 3));
  }
}

/* ---------------- editor garis ---------------- */
function openEditor(cameraId) {
  const cam = state.cameras.find((c) => c.id === cameraId) ||
    (state.cameras = state.cameras, null);
  const video = $(`video-${CSS.escape(cameraId)}`);
  if (!video) return;
  const modal = $("editor-modal");
  const canvas = $("editor-canvas");
  $("editor-title").textContent = `Editor garis — ${cam?.name || cameraId}`;
  $("editor-status").textContent = "";
  $("line-name").value = "";
  modal.hidden = false;
  state.editor = { cameraId, points: [], video, canvas };
  const draw = () => {
    const w = video.clientWidth, h = video.clientHeight;
    canvas.width = Math.min(w || 640, 820);
    canvas.height = Math.round(canvas.width * (video.videoHeight || 360) / (video.videoWidth || 640));
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    // garis lama
    ctx.strokeStyle = "#ffd166";
    ctx.lineWidth = 2;
    for (const line of cam?.lines || []) {
      ctx.beginPath();
      ctx.moveTo(line.p1x * canvas.width, line.p1y * canvas.height);
      ctx.lineTo(line.p2x * canvas.width, line.p2y * canvas.height);
      ctx.stroke();
    }
    // titik yang sudah diklik
    ctx.fillStyle = "#8dff87";
    for (const p of state.editor.points) {
      ctx.beginPath();
      ctx.arc(p.x * canvas.width, p.y * canvas.height, 5, 0, Math.PI * 2);
      ctx.fill();
    }
    if (state.editor.points.length === 2) {
      const [a, b] = state.editor.points;
      ctx.strokeStyle = "#8dff87";
      ctx.beginPath();
      ctx.moveTo(a.x * canvas.width, a.y * canvas.height);
      ctx.lineTo(b.x * canvas.width, b.y * canvas.height);
      ctx.stroke();
    }
  };
  state.editor.draw = draw;
  draw();
  const loop = setInterval(() => {
    if (!modal.hidden && state.editor && state.editor.cameraId === cameraId) draw();
    else clearInterval(loop);
  }, 500);
}

$("editor-canvas").addEventListener("click", (event) => {
  if (!state.editor || state.editor.points.length >= 2) return;
  const rect = event.target.getBoundingClientRect();
  state.editor.points.push({
    x: (event.clientX - rect.left) / rect.width,
    y: (event.clientY - rect.top) / rect.height,
  });
  state.editor.draw();
});

$("editor-close").addEventListener("click", () => {
  $("editor-modal").hidden = true;
  state.editor = null;
});

$("editor-save").addEventListener("click", async () => {
  if (!state.editor) return;
  const { cameraId, points } = state.editor;
  if (points.length !== 2) {
    $("editor-status").textContent = "Klik dua titik dulu.";
    return;
  }
  const name = ($("line-name").value || "garis").slice(0, 40);
  try {
    await api(`/api/v1/cameras/${encodeURIComponent(cameraId)}/lines`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        lines: [{ name, p1: [points[0].x, points[0].y], p2: [points[1].x, points[1].y] }],
      }),
    });
    $("editor-status").textContent = "Garis tersimpan ✓";
    await refreshCameras();
  } catch (err) {
    $("editor-status").textContent = `Gagal: ${err.message}`;
  }
});

/* ---------------- statistik & grafik ---------------- */
async function refreshStats() {
  const date = $("date-picker").value || todayStr();
  try {
    const stats = await api(`/api/v1/summary?date=${date}`);
    $("kpi-total").textContent = stats.total;
    $("kpi-in").textContent = stats.in;
    $("kpi-out").textContent = stats.out;
    $("kpi-peak").textContent = stats.peakHour ? `${stats.peakHour}:00` : "–";
    $("kpi-online").textContent = `${stats.camerasOnline}/${stats.camerasTotal}`;
    $("kpi-cov").textContent = stats.coveragePct != null ? `${stats.coveragePct}%` : "–";
    $("export-btn").href = `/api/v1/export.csv?from=${date}`;
    const hourly = await api(`/api/v1/hourly?date=${date}`);
    drawHourly(hourly.hours || []);
    refreshRank();
  } catch { /* siklus berikutnya */ }
}

function drawHourly(hours) {
  const canvas = $("hourly-chart");
  const width = canvas.clientWidth || canvas.width;
  canvas.width = width;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const byHour = new Map(hours.map((h) => [h.jam, h.total]));
  const values = [];
  for (let i = 0; i < 24; i++) values.push(byHour.get(String(i).padStart(2, "0")) || 0);
  const max = Math.max(1, ...values);
  const barW = canvas.width / 24;
  const nowHour = new Date().getHours();
  values.forEach((value, index) => {
    const h = (value / max) * (canvas.height - 28);
    contextFill(ctx, index, barW, canvas.height, h, value === 0);
    if (value) {
      ctx.fillStyle = "#cfe9f5";
      ctx.font = "9px monospace";
      ctx.fillText(value, index * barW + barW / 2 - 6, canvas.height - h - 16);
    }
    ctx.fillStyle = index === nowHour ? "#ffd166" : "#6f8b9c";
    ctx.font = "8px monospace";
    ctx.fillText(String(index).padStart(2, "0"), index * barW + 4, canvas.height - 4);
  });
}

function contextFill(ctx, index, barW, height, h, empty) {
  ctx.fillStyle = empty ? "rgba(255,255,255,0.06)" : "rgba(0, 212, 255, 0.7)";
  ctx.fillRect(index * barW + 2, height - h - 14, barW - 4, h);
}

async function refreshRank() {
  const stats = await api("/api/v1/summary?date=" + $("date-picker").value).catch(() => null);
  if (!stats) return;
  const perCam = {};
  const hourly = await api(`/api/v1/hourly?date=${$("date-picker").value}`).catch(() => ({ hours: [] }));
  void hourly;
  // peringkat dari endpoint cameras (in+out sesi ini) + events
  const payload = await api("/api/v1/cameras").catch(() => ({ cameras: [] }));
  for (const cam of payload.cameras) perCam[cam.id] = cam.inCount + cam.outCount;
  const events = await api("/api/v1/events?limit=200").catch(() => ({ events: [] }));
  for (const e of events.events || []) perCam[e.camera_id] = (perCam[e.camera_id] || 0) + 1;
  const rows = Object.entries(perCam).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...rows.map(([, v]) => v));
  const nameOf = Object.fromEntries(state.cameras.map((c) => [c.id, c.name]));
  $("rank").innerHTML = rows.map(([id, count]) => {
    const width = Math.round(100 * count / max);
    return `<li><span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(nameOf[id] || id)}</span>
      <span class="bar"><i style="width:${width}%"></i></span><b>${count}</b></li>`;
  }).join("");
}

/* ---------------- SSE ---------------- */
function connectSSE() {
  const es = new EventSource("/api/v1/live");
  es.onopen = () => { $("sse-status").textContent = "SSE: tersambung ✓"; };
  es.onerror = () => { $("sse-status").textContent = "SSE: tersambung ulang…"; };
  es.onmessage = (event) => {
    let data;
    try { data = JSON.parse(event.data); } catch { return; }
    if (data.type === "crossing") {
      const li = document.createElement("li");
      li.className = "new";
      const time = new Date((data.ts || Date.now() / 1000) * 1000).toTimeString().slice(0, 8);
      li.innerHTML = `<span>#${esc(data.cameraName || data.cameraId)} —
        <b class="dir-${esc(data.direction)}">${esc(data.direction)}</b> (${esc(data.line)})</span>
        <span class="feed-time">${esc(time)}</span>`;
      const feed = $("feed");
      feed.prepend(li);
      while (feed.children.length > 14) feed.lastChild.remove();
    }
  };
}


/* auto-start dashboard: DOM sudah siap saat skrip dieksekusi di akhir body */
function startDashboard() {
  boot();
  refreshFeed();
}
startDashboard();
