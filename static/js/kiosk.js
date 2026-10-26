const socket = io();

const connDot = document.getElementById("connDot");
const connText = document.getElementById("connText");
const deviceLabel = document.getElementById("deviceLabel");
const recPillValue = document.getElementById("recPillValue");
const playPillValue = document.getElementById("playPillValue");
const storagePillValue = document.getElementById("storagePillValue");
const fileList = document.getElementById("fileList");

function formatBytes(bytes) {
    if (!bytes || bytes < 1) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    let value = bytes;
    while (value >= 1024 && i < units.length - 1) {
        value /= 1024;
        i++;
    }
    return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

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

function setOffline() {
    connDot.classList.remove("on");
    connText.textContent = "Server offline";
    deviceLabel.textContent = "Console: —";
    recPillValue.textContent = "—";
    recPillValue.classList.remove("recording");
    playPillValue.textContent = "—";
    playPillValue.classList.remove("playing");
    storagePillValue.textContent = "—";
}

socket.on("connect", () => {
    connDot.classList.add("on");
    connText.textContent = "Server online";
});

socket.on("disconnect", setOffline);

socket.on("status", (data) => {
    const model = data.device_model || "Unknown";
    const consoleState = data.connected ? "connected" : "not detected";
    deviceLabel.textContent = `Console: ${model} (${consoleState})`;

    if (data.recording) {
        const name = data.recording_file || "";
        const t = formatDuration(data.record_time);
        recPillValue.textContent = `● REC ${t}\n${name}`;
        recPillValue.classList.add("recording");
    } else {
        recPillValue.textContent = "Idle";
        recPillValue.classList.remove("recording");
    }

    if (data.playing) {
        const name = data.file || "";
        const pos = formatDuration(data.position);
        const dur = formatDuration(data.duration);
        const state = data.paused ? "Paused" : "Playing";
        playPillValue.textContent = `${state} ${pos}/${dur}\n${name}`;
        playPillValue.classList.add("playing");
    } else {
        playPillValue.textContent = "Idle";
        playPillValue.classList.remove("playing");
    }

    const free = data.storage_free_bytes;
    const total = data.storage_total_bytes;
    if (free !== undefined && total !== undefined) {
        storagePillValue.textContent = `${formatBytes(free)} free\nof ${formatBytes(total)}`;
    } else {
        storagePillValue.textContent = "—";
    }

    renderFiles(data.files || []);
});

socket.on("files", (files) => {
    renderFiles(files || []);
});

function renderFiles(files) {
    fileList.innerHTML = "";

    if (!files.length) {
        const empty = document.createElement("div");
        empty.className = "kiosk-empty-hint";
        empty.textContent = "No recordings yet";
        fileList.appendChild(empty);
        return;
    }

    files
        .slice()
        .sort((a, b) => (a.name || "").localeCompare(b.name || ""))
        .forEach((f) => {
            const row = document.createElement("div");
            row.className = "kiosk-file-row";
            row.textContent = `${f.name} — ${formatBytes(f.size_bytes || 0)} (${f.label || "Local Storage"})`;
            fileList.appendChild(row);
        });
}

setOffline();
