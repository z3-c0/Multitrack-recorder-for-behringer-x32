const socket = io();

// ---------- STATE ----------
let recording = false;
let playing = false;
let paused = false;
let duration = 0;
let position = 0;
let currentPlayFile = null;
let recordTime = 0;
let filesData = [];       // last "files" payload from server
let expandedFile = null;  // which recording row is expanded
let searchQuery = "";
let renameTarget = null;
let deleteTarget = null;

// ---------- DOM ----------
const viewRecord = document.getElementById("view-record");
const viewRecordings = document.getElementById("view-recordings");

const micBtn = document.getElementById("micBtn");
const timerText = document.getElementById("timerText");
const recordHint = document.getElementById("recordHint");
const recordControls = document.getElementById("recordControls");
const discardBtn = document.getElementById("discardBtn");
const finishBtn = document.getElementById("finishBtn");
const recordWaveform = document.getElementById("recordWaveform");
const statusDot = document.getElementById("statusDot");
const statusDotRecordings = document.getElementById("statusDotRecordings");

const settingsBtn = document.getElementById("settingsBtn");
const recordingsBtn = document.getElementById("recordingsBtn");
const backBtn = document.getElementById("backBtn");
const searchInput = document.getElementById("searchInput");
const recordingsList = document.getElementById("recordingsList");

const settingsModalEl = document.getElementById("settingsModal");
const settingsModal = new bootstrap.Modal(settingsModalEl);
const storageSelect = document.getElementById("storageSelect");
const settingsConnected = document.getElementById("settingsConnected");
const settingsDeviceModel = document.getElementById("settingsDeviceModel");
const settingsFree = document.getElementById("settingsFree");
const settingsTotal = document.getElementById("settingsTotal");
const settingsPath = document.getElementById("settingsPath");

const renameModal = new bootstrap.Modal(document.getElementById("renameModal"));
const renameInput = document.getElementById("renameInput");

const deleteModal = new bootstrap.Modal(document.getElementById("deleteModal"));

const errorModal = new bootstrap.Modal(document.getElementById("errorModal"));
const errorMessage = document.getElementById("errorMessage");

// ---------- VIEW SWITCHING ----------
function showView(name) {
    viewRecord.classList.toggle("active", name === "record");
    viewRecordings.classList.toggle("active", name === "recordings");
}

settingsBtn.addEventListener("click", () => settingsModal.show());
recordingsBtn.addEventListener("click", () => showView("recordings"));
backBtn.addEventListener("click", () => showView("record"));

// ---------- WAVEFORM HELPERS ----------
// Deterministic pseudo-random bar heights, seeded by a string (filename).
function seededHeights(seed, count) {
    let h = 0;
    for (let i = 0; i < seed.length; i++) {
        h = (h * 31 + seed.charCodeAt(i)) & 0xffffffff;
    }
    const heights = [];
    for (let i = 0; i < count; i++) {
        h = (h * 1103515245 + 12345) & 0x7fffffff;
        const pct = (h % 1000) / 1000;
        heights.push(6 + pct * 28); // 6px - 34px
    }
    return heights;
}

function renderWaveform(container, seed, barCount, progressRatio) {
    container.innerHTML = "";
    const heights = seededHeights(seed || "seed", barCount);
    const playedCount = Math.round((progressRatio || 0) * barCount);
    heights.forEach((h, i) => {
        const bar = document.createElement("div");
        bar.className = "bar" + (i < playedCount ? " played" : "");
        bar.style.height = h + "px";
        container.appendChild(bar);
    });
}

// Idle record-view waveform (static, low bars) vs recording (animated)
let recordWaveformTimer = null;
function startRecordWaveformAnim() {
    stopRecordWaveformAnim();
    let tick = 0;
    recordWaveformTimer = setInterval(() => {
        tick++;
        renderWaveform(recordWaveform, "rec" + tick, 32, 1);
    }, 220);
}
function stopRecordWaveformAnim() {
    if (recordWaveformTimer) {
        clearInterval(recordWaveformTimer);
        recordWaveformTimer = null;
    }
    renderWaveform(recordWaveform, "idle", 32, 0);
}

// ---------- SOCKET LISTENERS ----------
socket.on("status", (data) => {
    paused = !!data.paused;
    recording = !!data.recording;
    playing = !!data.playing;
    duration = data.duration || 0;
    position = data.position || 0;
    currentPlayFile = data.file || null;
    recordTime = data.record_time || 0;

    const connected = !!data.connected;
    statusDot.classList.toggle("on", connected);
    statusDotRecordings.classList.toggle("on", connected);

    settingsConnected.textContent = connected ? "Connected" : "Not found";
    settingsDeviceModel.textContent = data.device_model || "-";
    settingsFree.textContent = formatBytes(data.storage_free_bytes || 0);
    settingsTotal.textContent = formatBytes(data.storage_total_bytes || 0);
    settingsPath.textContent = data.storage_path || "-";

    // ---- mic / record UI ----
    if (recording) {
        micBtn.classList.add("recording");
        micBtn.disabled = true;
        recordHint.textContent = "Recording...";
        recordControls.classList.remove("hidden");
        if (!recordWaveformTimer) startRecordWaveformAnim();
    } else {
        micBtn.classList.remove("recording");
        micBtn.disabled = false;
        recordHint.textContent = "Tap to record";
        recordControls.classList.add("hidden");
        stopRecordWaveformAnim();
    }
    timerText.textContent = formatDuration(recordTime);

    // ---- files / recordings list ----
    filesData = data.files || filesData;
    renderRecordingsList();
});

socket.on("position", (data) => {
    position = data.position || 0;
    duration = data.duration || 0;
    updateExpandedPlaybackUI();
});

socket.on("files", (files) => {
    filesData = files || [];
    renderRecordingsList();
});

socket.on("storage_options", (data) => {
    const currentPath = data.current_path || "";
    const previous = storageSelect.value;
    storageSelect.innerHTML = "";

    (data.options || []).forEach((optData) => {
        const opt = document.createElement("option");
        opt.value = optData.path;
        opt.text = `${optData.label} — ${formatBytes(optData.free_bytes)} free`;
        storageSelect.appendChild(opt);
    });

    storageSelect.value = previous || currentPath;
});

socket.on("app_error", (data) => {
    showErrorModal(data.msg);
});

// ---------- RECORD VIEW ACTIONS ----------
micBtn.addEventListener("click", () => {
    if (recording) return;
    socket.emit("start_record");
});

discardBtn.addEventListener("click", () => {
    socket.emit("discard_record");
});

finishBtn.addEventListener("click", () => {
    socket.emit("stop_record");
    showView("recordings");
});

// ---------- RECORDINGS VIEW ----------
searchInput.addEventListener("input", () => {
    searchQuery = searchInput.value.trim().toLowerCase();
    renderRecordingsList();
});

function parseFileMeta(name) {
    // rec_YYYY-MM-DD_HH-MM-SS.wav
    const m = name.match(/^rec_(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})/);
    if (!m) {
        return { group: "Recordings", label: name, dateStr: "" };
    }
    const [, y, mo, d, h, mi] = m;
    const monthNames = ["January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"];
    const monthIdx = parseInt(mo, 10) - 1;
    const group = `${monthNames[monthIdx] || mo} ${y}`;
    const dateStr = `${d} ${(monthNames[monthIdx] || mo).slice(0, 3)} ${y} | ${h}:${mi}`;
    return { group, label: name, dateStr };
}

function renderRecordingsList() {
    recordingsList.innerHTML = "";

    let files = filesData.slice();
    if (searchQuery) {
        files = files.filter((f) => {
            const name = typeof f === "string" ? f : f.name;
            return name.toLowerCase().includes(searchQuery);
        });
    }

    if (files.length === 0) {
        const empty = document.createElement("div");
        empty.className = "empty-hint";
        empty.textContent = "No recordings yet";
        recordingsList.appendChild(empty);
        return;
    }

    // group by parsed month/year, most recent files first
    const groups = new Map();
    files.slice().reverse().forEach((f) => {
        const name = typeof f === "string" ? f : f.name;
        const size = typeof f === "string" ? 0 : (f.size_bytes || 0);
        const meta = parseFileMeta(name);
        if (!groups.has(meta.group)) groups.set(meta.group, []);
        groups.get(meta.group).push({ name, size, meta });
    });

    groups.forEach((rows, groupName) => {
        const header = document.createElement("div");
        header.className = "group-header";
        header.textContent = groupName;
        recordingsList.appendChild(header);

        rows.forEach((row) => recordingsList.appendChild(buildRecordingRow(row)));
    });
}

function buildRecordingRow(row) {
    const { name, size, meta } = row;
    const isCurrent = currentPlayFile === name;
    const isExpanded = expandedFile === name;

    const wrap = document.createElement("div");
    wrap.className = "rec-row" + (isCurrent && playing ? " playing" : "") + (isExpanded ? " expanded" : "");

    const main = document.createElement("div");
    main.className = "rec-row-main";

    const playBtn = document.createElement("button");
    playBtn.className = "rec-play-btn";
    playBtn.textContent = isCurrent && playing && !paused ? "⏸" : "▶";
    playBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        handleRowPlayClick(name);
    });

    const info = document.createElement("div");
    info.className = "rec-info";
    const nameEl = document.createElement("div");
    nameEl.className = "rec-name";
    nameEl.textContent = meta.label;
    const metaEl = document.createElement("div");
    metaEl.className = "rec-meta";
    metaEl.textContent = meta.dateStr ? `${meta.dateStr} | ${formatBytes(size)}` : formatBytes(size);
    info.appendChild(nameEl);
    info.appendChild(metaEl);

    const durEl = document.createElement("div");
    durEl.className = "rec-duration";
    durEl.textContent = isCurrent && duration ? formatDuration(duration) : "";

    main.appendChild(playBtn);
    main.appendChild(info);
    main.appendChild(durEl);

    main.addEventListener("click", () => {
        expandedFile = isExpanded ? null : name;
        renderRecordingsList();
    });

    wrap.appendChild(main);

    // expanded section
    const expanded = document.createElement("div");
    expanded.className = "rec-expanded";

    const wf = document.createElement("div");
    wf.className = "waveform small";
    wf.id = "wf-" + cssEscape(name);
    expanded.appendChild(wf);

    const timeRow = document.createElement("div");
    timeRow.className = "rec-time-row";
    const curSpan = document.createElement("span");
    curSpan.className = "rec-cur-time";
    curSpan.textContent = isCurrent ? formatDuration(position) : "0:00";
    const totalSpan = document.createElement("span");
    totalSpan.className = "rec-total-time";
    totalSpan.textContent = isCurrent ? formatDuration(duration) : "0:00";
    timeRow.appendChild(curSpan);
    timeRow.appendChild(totalSpan);
    expanded.appendChild(timeRow);

    const seek = document.createElement("input");
    seek.type = "range";
    seek.className = "rec-seekbar";
    seek.min = 0;
    seek.max = isCurrent && duration ? duration : 100;
    seek.value = isCurrent ? position : 0;
    seek.addEventListener("mousedown", () => (seek.dataset.seeking = "1"));
    seek.addEventListener("touchstart", () => (seek.dataset.seeking = "1"));
    seek.addEventListener("change", () => {
        if (isCurrent) {
            socket.emit("seek", { pos: seek.value });
        }
        seek.dataset.seeking = "";
    });
    expanded.appendChild(seek);

    const actions = document.createElement("div");
    actions.className = "rec-actions";

    const renameBtn = document.createElement("button");
    renameBtn.className = "rename-btn";
    renameBtn.title = "Rename";
    renameBtn.textContent = "✎";
    renameBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        renameTarget = name;
        renameInput.value = "";
        renameModal.show();
    });

    const deleteBtn = document.createElement("button");
    deleteBtn.className = "delete-btn";
    deleteBtn.title = "Delete";
    deleteBtn.textContent = "🗑";
    deleteBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        deleteTarget = name;
        deleteModal.show();
    });

    actions.appendChild(renameBtn);
    actions.appendChild(deleteBtn);
    expanded.appendChild(actions);

    wrap.appendChild(expanded);

    // render waveform now (after attaching, since element needs to exist)
    requestAnimationFrame(() => {
        const ratio = isCurrent && duration ? position / duration : 0;
        renderWaveform(wf, name, 40, ratio);
    });

    return wrap;
}

function cssEscape(s) {
    return s.replace(/[^a-zA-Z0-9_-]/g, "_");
}

function handleRowPlayClick(name) {
    const isCurrent = currentPlayFile === name;
    if (isCurrent && playing) {
        socket.emit("pause_play");
    } else {
        socket.emit("play", { file: name });
        expandedFile = name;
    }
}

function updateExpandedPlaybackUI() {
    if (!expandedFile || expandedFile !== currentPlayFile) return;

    const curEl = document.querySelector(".rec-row.expanded .rec-cur-time");
    const totalEl = document.querySelector(".rec-row.expanded .rec-total-time");
    const seekEl = document.querySelector(".rec-row.expanded .rec-seekbar");
    const wfEl = document.getElementById("wf-" + cssEscape(expandedFile));

    if (curEl) curEl.textContent = formatDuration(position);
    if (totalEl) totalEl.textContent = formatDuration(duration);
    if (seekEl && seekEl.dataset.seeking !== "1") {
        seekEl.max = duration || 100;
        seekEl.value = position || 0;
    }
    if (wfEl) {
        const ratio = duration ? position / duration : 0;
        renderWaveform(wfEl, expandedFile, 40, ratio);
    }
}

// ---------- MODALS: rename / delete / error ----------
document.getElementById("confirmRenameBtn").addEventListener("click", () => {
    const newName = renameInput.value.trim();
    if (!newName || !renameTarget) return;

    socket.emit("rename", { old: renameTarget, new: newName });
    renameTarget = null;
    renameModal.hide();
});

document.getElementById("confirmDeleteBtn").addEventListener("click", () => {
    if (!deleteTarget) return;
    socket.emit("delete", { file: deleteTarget });
    if (expandedFile === deleteTarget) expandedFile = null;
    deleteTarget = null;
    deleteModal.hide();
});

function showErrorModal(message) {
    errorMessage.textContent = message;
    errorModal.show();
}

// ---------- SETTINGS: storage picker ----------
storageSelect.addEventListener("change", () => {
    if (!storageSelect.value) return;
    socket.emit("set_storage", { path: storageSelect.value });
});

// ---------- FORMAT HELPERS ----------
function formatDuration(sec) {
    sec = Math.floor(sec || 0);
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    if (h > 0) {
        return `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
    }
    return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatBytes(bytes) {
    if (!bytes || bytes < 1) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    let value = bytes;
    while (value >= 1024 && i < units.length - 1) {
        value /= 1024;
        i++;
    }
    return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[i]}`;
}

// ---------- INIT ----------
stopRecordWaveformAnim(); // draw idle waveform on load
showView("record");
