function startSession() {
    if (!state.isConnected) {
        setStatus("connect first");
        return;
    }
    const runningSession = getRunningSession();
    if (runningSession) {
        state.currentSession = runningSession;
        drawCurrentSession();
        updateSessionInfo();
        updateButtons();
        setStatus("session already running");
        return;
    }

    clearChartData();
    const sid = (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function")
        ? globalThis.crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

    state.currentSession = {
        id: sid,
        name: (dom.sessionNameInput.value || "").trim(),
        startIso: nowIso(),
        endIso: null,
        sensorId: state.sensorId,
        baselineCurrents: Array(10).fill(null),
        baselineReady: false,
        records: []
    };

    state.sessions.push(state.currentSession);
    saveSessions();
    refreshSessionSelect();
    dom.sessionSelect.value = state.currentSession.id;
    updateSessionInfo();
    updateButtons();
    if (typeof enqueueBridgeEvent === "function") {
        enqueueBridgeEvent("session_started", {
            sessionId: state.currentSession.id,
            name: state.currentSession.name,
            sensorId: state.currentSession.sensorId,
            startIso: state.currentSession.startIso
        });
    }
    setStatus("session started");
}

function getRunningSession() {
    for (let i = state.sessions.length - 1; i >= 0; i -= 1) {
        const session = state.sessions[i];
        if (session && !session.endIso) {
            return session;
        }
    }
    return null;
}

function stopSession(sessionId = null) {
    let target = null;
    if (sessionId) {
        target = getSessionById(sessionId);
        if (target && target.endIso) {
            target = null;
        }
    }
    if (!target && state.currentSession && !state.currentSession.endIso) {
        target = state.currentSession;
    }
    if (!target) {
        target = getRunningSession();
    }
    if (!target) {
        return;
    }

    state.currentSession = target;
    target.endIso = nowIso();
    saveSessions();
    refreshSessionSelect();
    dom.sessionSelect.value = target.id;
    updateSessionInfo();
    updateButtons();
    if (typeof enqueueBridgeEvent === "function") {
        enqueueBridgeEvent("session_ended", {
            sessionId: target.id,
            name: target.name,
            sensorId: target.sensorId,
            startIso: target.startIso,
            endIso: target.endIso,
            records: target.records.length
        });
    }
    setStatus("session ended");
}

function getSelectedSession() {
    const id = dom.sessionSelect.value;
    return state.sessions.find((s) => s.id === id) || null;
}

function getSessionById(sessionId) {
    return state.sessions.find((s) => s.id === sessionId) || null;
}

function escapeCsv(value) {
    const text = String(value ?? "");
    if (/[",\n]/.test(text)) {
        return `"${text.replace(/"/g, '""')}"`;
    }
    return text;
}

function pad2(value) {
    return String(value).padStart(2, "0");
}

function pad3(value) {
    return String(value).padStart(3, "0");
}

function formatPythonDataTimestamp(date) {
    return `${date.getFullYear()}/${pad2(date.getMonth() + 1)}/${pad2(date.getDate())} `
        + `${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}.${pad3(date.getMilliseconds())}`;
}

function formatFixed(value, digits) {
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(digits) : "";
}

function buildRawSessionCsvText(session) {
    const lines = [
        "session_id,start_iso,end_iso,sensor_id,t,ch,temp,humidity,pressure,current"
    ];
    for (const r of session.records) {
        lines.push([
            session.id,
            session.startIso,
            session.endIso || "",
            session.sensorId || "",
            r.t.toFixed(3),
            r.ch,
            r.temp,
            r.humidity,
            r.pressure,
            r.current
        ].map(escapeCsv).join(","));
    }
    return lines.join("\n");
}

function buildPythonDataCsvText(session) {
    const rows = [
        "timestamp,temp,humidity,pressure,d0,d1,d2,d3,d4,d5,d6,d7,d8,d9,rel_d0,rel_d1,rel_d2,rel_d3,rel_d4,rel_d5,rel_d6,rel_d7,rel_d8,rel_d9"
    ];
    const currents = Array(10).fill(null);
    const seen = new Set();
    const sessionStartMs = Date.parse(session.startIso);
    let baselineCurrents = null;

    for (const r of session.records) {
        if (!Number.isInteger(r.ch) || r.ch < 0 || r.ch > 9) {
            continue;
        }
        currents[r.ch] = r.current;
        seen.add(r.ch);

        if (seen.size < 10) {
            continue;
        }

        const ts = new Date(sessionStartMs + Math.round(r.t * 1000));
        if (!baselineCurrents) {
            baselineCurrents = currents.map((v) => Number(v));
        }
        const relativeCurrents = currents.map((v, idx) => Number(v) - baselineCurrents[idx]);
        const line = [
            formatPythonDataTimestamp(ts),
            formatFixed(r.temp, 2),
            formatFixed(r.humidity, 2),
            formatFixed(r.pressure, 2),
            ...currents.map((v) => formatFixed(v, 3)),
            ...relativeCurrents.map((v) => formatFixed(v, 3))
        ].join(",");
        rows.push(line);
        seen.clear();
    }
    return rows.join("\n");
}

function getSessionFileStem(session) {
    const start = session.startIso.replace(/[:.]/g, "-");
    const rawName = (session.name || "").trim();
    const safeName = rawName
        .replace(/[<>:"/\\|?*\x00-\x1F]/g, "_")
        .replace(/\s+/g, "_")
        .replace(/[. ]+$/g, "")
        .slice(0, 60);
    return safeName ? `scent_session_${safeName}_${start}` : `scent_session_${start}`;
}

async function downloadSessionZip(session) {
    if (!session) {
        alert("No session selected");
        return;
    }

    if (typeof JSZip === "undefined") {
        alert("ZIP library is not loaded.");
        return;
    }

    const stem = getSessionFileStem(session);
    const zipBlob = await buildSessionZipBlob(session);
    const url = URL.createObjectURL(zipBlob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${stem}.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
}

async function buildSessionZipBlob(session) {
    const stem = getSessionFileStem(session);
    const rawCsv = buildRawSessionCsvText(session);
    const pythonDataCsv = buildPythonDataCsvText(session);

    const zip = new JSZip();
    zip.file(`${stem}_raw.csv`, rawCsv);
    zip.file(`${stem}_data.csv`, pythonDataCsv);
    return zip.generateAsync({ type: "blob" });
}

function openUploadSessionZipDialog() {
    if (!dom.uploadZipInput) {
        return;
    }
    dom.uploadZipInput.click();
}

function decodeImportedSessionName(fileName) {
    const base = String(fileName || "").replace(/\.zip$/i, "");
    if (!base.startsWith("scent_session_")) {
        return "";
    }
    const withoutPrefix = base.slice("scent_session_".length);
    const parts = withoutPrefix.split("_");
    if (parts.length < 2) {
        return "";
    }
    parts.pop();
    return parts.join(" ").trim();
}

function parseSimpleCsvLine(line) {
    const values = [];
    let current = "";
    let inQuotes = false;

    for (let i = 0; i < line.length; i += 1) {
        const ch = line[i];
        if (ch === '"') {
            if (inQuotes && line[i + 1] === '"') {
                current += '"';
                i += 1;
                continue;
            }
            inQuotes = !inQuotes;
            continue;
        }
        if (ch === "," && !inQuotes) {
            values.push(current);
            current = "";
            continue;
        }
        current += ch;
    }
    values.push(current);
    return values;
}

function parseRawSessionCsvText(csvText) {
    const lines = String(csvText || "")
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter((line) => line.length > 0);

    if (lines.length < 2) {
        throw new Error("raw CSV has no records");
    }

    const header = parseSimpleCsvLine(lines[0]);
    const requiredColumns = ["session_id", "start_iso", "end_iso", "sensor_id", "t", "ch", "temp", "humidity", "pressure", "current"];
    const indices = {};
    for (const column of requiredColumns) {
        const index = header.indexOf(column);
        if (index < 0) {
            throw new Error(`raw CSV missing column: ${column}`);
        }
        indices[column] = index;
    }

    const records = [];
    let sourceSessionId = "";
    let startIso = "";
    let endIso = "";
    let sensorId = "";

    for (let i = 1; i < lines.length; i += 1) {
        const cols = parseSimpleCsvLine(lines[i]);
        const get = (key) => cols[indices[key]] ?? "";
        if (!sourceSessionId) sourceSessionId = get("session_id").trim();
        if (!startIso) startIso = get("start_iso").trim();
        if (!endIso) endIso = get("end_iso").trim();
        if (!sensorId) sensorId = get("sensor_id").trim();

        const t = Number(get("t"));
        const ch = Number(get("ch"));
        const temp = Number(get("temp"));
        const humidity = Number(get("humidity"));
        const pressure = Number(get("pressure"));
        const current = Number(get("current"));

        if (!Number.isFinite(t) || !Number.isFinite(ch) || !Number.isFinite(current)) {
            continue;
        }

        records.push({
            t,
            ch,
            temp: Number.isFinite(temp) ? temp : 0,
            humidity: Number.isFinite(humidity) ? humidity : 0,
            pressure: Number.isFinite(pressure) ? pressure : 0,
            current
        });
    }

    if (records.length === 0) {
        throw new Error("raw CSV has no valid records");
    }

    return {
        sourceSessionId,
        startIso: startIso || nowIso(),
        endIso: endIso || null,
        sensorId: sensorId || "-",
        records
    };
}

function ensureUniqueSessionId(candidateId) {
    const fallbackId = (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function")
        ? globalThis.crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const baseId = (candidateId || "").trim() || fallbackId;
    if (!state.sessions.some((s) => s.id === baseId)) {
        return baseId;
    }

    let suffix = 1;
    while (state.sessions.some((s) => s.id === `${baseId}-imported-${suffix}`)) {
        suffix += 1;
    }
    return `${baseId}-imported-${suffix}`;
}

async function importSessionZip(file) {
    if (!file) {
        return;
    }
    if (typeof JSZip === "undefined") {
        throw new Error("ZIP library is not loaded");
    }

    const zip = await JSZip.loadAsync(file);
    const rawCsvEntry = Object.values(zip.files).find((entry) => !entry.dir && /_raw\.csv$/i.test(entry.name));
    if (!rawCsvEntry) {
        throw new Error("ZIP does not contain *_raw.csv");
    }

    const rawCsvText = await rawCsvEntry.async("text");
    const parsed = parseRawSessionCsvText(rawCsvText);
    const importedName = decodeImportedSessionName(file.name);

    const session = {
        id: ensureUniqueSessionId(parsed.sourceSessionId),
        name: importedName,
        startIso: parsed.startIso,
        endIso: parsed.endIso,
        sensorId: parsed.sensorId,
        baselineCurrents: Array(10).fill(null),
        baselineReady: false,
        records: parsed.records
    };

    state.sessions.push(session);
    state.currentSession = session;
    saveSessions();
    refreshSessionSelect();
    dom.sessionSelect.value = session.id;
    drawCurrentSession();
    updateSessionInfo();
    updateButtons();
    setStatus(`session imported (${session.records.length} rows)`);
}

function deleteSelectedSession() {
    const session = getSelectedSession();
    if (!session) {
        return;
    }
    const yes = window.confirm("Delete selected session from local storage?");
    if (!yes) return;

    state.sessions = state.sessions.filter((s) => s.id !== session.id);
    saveSessions();
    refreshSessionSelect();

    if (state.currentSession && state.currentSession.id === session.id) {
        state.currentSession = null;
        clearChartData();
        updateSessionInfo();
        updateButtons();
    }
}

function deleteAllSessions() {
    if (state.sessions.length === 0) {
        setStatus("no sessions to delete");
        return;
    }

    const yes = window.confirm(`Delete ALL ${state.sessions.length} sessions from local storage?`);
    if (!yes) return;

    const token = window.prompt("Type DELETE to confirm deleting all sessions", "");
    if (token !== "DELETE") {
        setStatus("delete all canceled");
        return;
    }

    state.sessions = [];
    state.currentSession = null;
    clearChartData();
    saveSessions();
    refreshSessionSelect();
    updateSessionInfo();
    updateButtons();
    setStatus("all sessions deleted");
}

