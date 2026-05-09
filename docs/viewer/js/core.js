const BAUD_RATE = 115200;
const STORAGE_KEY = "scent.sessions.v1";
const STRICT_CRC = true;
const CRC8_TABLE = [
    0x00, 0x31, 0x62, 0x53, 0xC4, 0xF5, 0xA6, 0x97, 0xB9, 0x88, 0xDB, 0xEA, 0x7D, 0x4C, 0x1F, 0x2E,
    0x43, 0x72, 0x21, 0x10, 0x87, 0xB6, 0xE5, 0xD4, 0xFA, 0xCB, 0x98, 0xA9, 0x3E, 0x0F, 0x5C, 0x6D,
    0x86, 0xB7, 0xE4, 0xD5, 0x42, 0x73, 0x20, 0x11, 0x3F, 0x0E, 0x5D, 0x6C, 0xFB, 0xCA, 0x99, 0xA8,
    0xC5, 0xF4, 0xA7, 0x96, 0x01, 0x30, 0x63, 0x52, 0x7C, 0x4D, 0x1E, 0x2F, 0xB8, 0x89, 0xDA, 0xEB,
    0x0C, 0x3D, 0x6E, 0x5F, 0xC8, 0xF9, 0xAA, 0x9B, 0xB5, 0x84, 0xD7, 0xE6, 0x71, 0x40, 0x13, 0x22,
    0x4F, 0x7E, 0x2D, 0x1C, 0x8B, 0xBA, 0xE9, 0xD8, 0xF6, 0xC7, 0x94, 0xA5, 0x32, 0x03, 0x50, 0x61,
    0x8A, 0xBB, 0xE8, 0xD9, 0x4E, 0x7F, 0x2C, 0x1D, 0x33, 0x02, 0x51, 0x60, 0xF7, 0xC6, 0x95, 0xA4,
    0xC9, 0xF8, 0xAB, 0x9A, 0x0D, 0x3C, 0x6F, 0x5E, 0x70, 0x41, 0x12, 0x23, 0xB4, 0x85, 0xD6, 0xE7,
    0x18, 0x29, 0x7A, 0x4B, 0xDC, 0xED, 0xBE, 0x8F, 0xA1, 0x90, 0xC3, 0xF2, 0x65, 0x54, 0x07, 0x36,
    0x5B, 0x6A, 0x39, 0x08, 0x9F, 0xAE, 0xFD, 0xCC, 0xE2, 0xD3, 0x80, 0xB1, 0x26, 0x17, 0x44, 0x75,
    0x9E, 0xAF, 0xFC, 0xCD, 0x5A, 0x6B, 0x38, 0x09, 0x27, 0x16, 0x45, 0x74, 0xE3, 0xD2, 0x81, 0xB0,
    0xDD, 0xEC, 0xBF, 0x8E, 0x19, 0x28, 0x7B, 0x4A, 0x64, 0x55, 0x06, 0x37, 0xA0, 0x91, 0xC2, 0xF3,
    0x14, 0x25, 0x76, 0x47, 0xD0, 0xE1, 0xB2, 0x83, 0xAD, 0x9C, 0xCF, 0xFE, 0x69, 0x58, 0x0B, 0x3A,
    0x57, 0x66, 0x35, 0x04, 0x93, 0xA2, 0xF1, 0xC0, 0xEE, 0xDF, 0x8C, 0xBD, 0x2A, 0x1B, 0x48, 0x79,
    0xB2, 0x83, 0xD0, 0xE1, 0x76, 0x47, 0x14, 0x25, 0x0B, 0x3A, 0x69, 0x58, 0xCF, 0xFE, 0xAD, 0x9C,
    0xF1, 0xC0, 0x93, 0xA2, 0x35, 0x04, 0x57, 0x66, 0x48, 0x79, 0x2A, 0x1B, 0x8C, 0xBD, 0xEE, 0xDF
];
const DATASET_COLORS = [
    "#e63946", "#f4a261", "#ffb703", "#2a9d8f", "#00a6fb",
    "#4361ee", "#7b2cbf", "#8338ec", "#ff006e", "#6c757d"
];

const state = {
    port: null,
    reader: null,
    writer: null,
    readLoopActive: false,
    readBuffer: "",
    isConnected: false,
    liveStartMs: 0,
    lastRxMs: 0,
    sensorId: "-",
    sessions: loadSessions(),
    currentSession: null,
    persistTimer: null,
    xAutoRange: true,
    isPanning: false,
    lastPanX: 0
};

const datasets = Array.from({ length: 10 }, (_, ch) => ({
    label: `D${ch}`,
    data: [],
    borderColor: DATASET_COLORS[ch],
    backgroundColor: DATASET_COLORS[ch],
    pointRadius: 0,
    tension: 0,
    borderWidth: 2
}));

const dom = {
    connectionToggleBtn: document.getElementById("connectionToggleBtn"),
    sessionToggleBtn: document.getElementById("sessionToggleBtn"),
    sessionNameInput: document.getElementById("sessionNameInput"),
    sessionSelect: document.getElementById("sessionSelect"),
    downloadBtn: document.getElementById("downloadBtn"),
    deleteBtn: document.getElementById("deleteBtn"),
    deleteAllBtn: document.getElementById("deleteAllBtn"),
    sensorId: document.getElementById("sensorId"),
    latestRxLine: document.getElementById("latestRxLine"),
    status: document.getElementById("status"),
    commDot: document.getElementById("commDot"),
    commText: document.getElementById("commText"),
    sessionInfo: document.getElementById("sessionInfo"),
    chartCanvas: document.getElementById("chart")
};

const chart = new Chart(dom.chartCanvas, {
    type: "line",
    data: { datasets },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        parsing: false,
        animation: false,
        scales: {
            x: { type: "linear", title: { display: true, text: "Time [s]" } },
            y: { title: { display: true, text: "Current" } }
        },
        plugins: { legend: { position: "bottom" } }
    }
});

function nowIso() {
    return new Date().toISOString();
}

function setStatus(text) {
    dom.status.textContent = text;
}

function updateCommUi(isOk) {
    if (isOk) {
        dom.commDot.classList.add("ok");
        dom.commText.lastChild.textContent = "connected";
    } else {
        dom.commDot.classList.remove("ok");
        dom.commText.lastChild.textContent = "disconnected";
    }
}

function updateButtons() {
    const running = !!state.currentSession && !state.currentSession.endIso;
    const hasSensorId = !!state.sensorId && state.sensorId !== "-";
    const hasSavedSessions = state.sessions.length > 0;

    dom.connectionToggleBtn.disabled = false;
    dom.connectionToggleBtn.textContent = state.isConnected ? "Disconnect" : "Connect";
    dom.connectionToggleBtn.classList.toggle("primary", !state.isConnected);
    dom.connectionToggleBtn.classList.toggle("warn", state.isConnected);

    dom.sessionToggleBtn.disabled = running ? false : (!state.isConnected || !hasSensorId);
    dom.sessionToggleBtn.textContent = running ? "Stop Session" : "Start Session";
    dom.sessionToggleBtn.classList.toggle("primary", !running);
    dom.sessionToggleBtn.classList.toggle("warn", running);

    dom.downloadBtn.disabled = !hasSavedSessions;
    dom.deleteBtn.disabled = !hasSavedSessions;
    dom.deleteAllBtn.disabled = !hasSavedSessions;
}

function loadSessions() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
    } catch (err) {
        console.error("Failed to parse localStorage sessions", err);
        return [];
    }
}

function saveSessions() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.sessions));
}

function schedulePersist() {
    if (state.persistTimer) {
        return;
    }
    state.persistTimer = setTimeout(() => {
        state.persistTimer = null;
        saveSessions();
        refreshSessionSelect();
    }, 400);
}

function refreshSessionSelect() {
    const prev = dom.sessionSelect.value;
    dom.sessionSelect.innerHTML = "";

    if (state.sessions.length === 0) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "No sessions";
        dom.sessionSelect.appendChild(opt);
        return;
    }

    state.sessions
        .slice()
        .sort((a, b) => (a.startIso < b.startIso ? 1 : -1))
        .forEach((s) => {
            const opt = document.createElement("option");
            opt.value = s.id;
            const nameText = (s.name || "").trim();
            const endText = s.endIso ? new Date(s.endIso).toLocaleTimeString("ja-JP", { hour12: false }) : "running";
            opt.textContent = `${nameText ? `${nameText} - ` : ""}${new Date(s.startIso).toLocaleString("ja-JP")} (${s.records.length} rows, end: ${endText})`;
            dom.sessionSelect.appendChild(opt);
        });

    dom.sessionSelect.value = state.sessions.some((s) => s.id === prev) ? prev : state.sessions[state.sessions.length - 1].id;
}

function getCurrentSessionRowCount() {
    if (!state.currentSession) return 0;
    return state.currentSession.records.length;
}

function updateSessionInfo() {
    if (!state.currentSession) {
        dom.sessionInfo.textContent = "none";
        return;
    }
    const endText = state.currentSession.endIso ? `, ended ${new Date(state.currentSession.endIso).toLocaleTimeString("ja-JP", { hour12: false })}` : ", running";
    const nameText = (state.currentSession.name || "").trim();
    dom.sessionInfo.textContent = `${nameText ? `${nameText}, ` : ""}${new Date(state.currentSession.startIso).toLocaleTimeString("ja-JP", { hour12: false })}${endText}, rows ${getCurrentSessionRowCount()}`;
}

