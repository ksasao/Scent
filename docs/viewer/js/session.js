function startSession() {
    if (!state.isConnected) {
        setStatus("connect first");
        return;
    }
    if (state.currentSession && !state.currentSession.endIso) {
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
    setStatus("session started");
}

function stopSession() {
    if (!state.currentSession || state.currentSession.endIso) {
        return;
    }
    state.currentSession.endIso = nowIso();
    saveSessions();
    refreshSessionSelect();
    updateSessionInfo();
    updateButtons();
    setStatus("session ended");
}

function getSelectedSession() {
    const id = dom.sessionSelect.value;
    return state.sessions.find((s) => s.id === id) || null;
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
    const rawCsv = buildRawSessionCsvText(session);
    const pythonDataCsv = buildPythonDataCsvText(session);

    const zip = new JSZip();
    zip.file(`${stem}_raw.csv`, rawCsv);
    zip.file(`${stem}_data.csv`, pythonDataCsv);

    const zipBlob = await zip.generateAsync({ type: "blob" });
    const url = URL.createObjectURL(zipBlob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${stem}.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
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

