// Bridge URL candidates to probe (in order of preference)
const BRIDGE_URL_CANDIDATES = [
    "http://127.0.0.1:8001",
    "http://localhost:8001",
];

const BRIDGE_BATCH_SIZE = 10;
const BRIDGE_FLUSH_INTERVAL_MS = 1000;
const BRIDGE_SAMPLE_INTERVAL_MS = 1000;
const BRIDGE_COMMAND_POLL_INTERVAL_MS = 2000;
const BRIDGE_PROBE_TIMEOUT_MS = 3000;

const bridgeState = {
    httpUrl: null,
    wsUrl: null,
    socket: null,
    connected: false,
    enabled: false,
    status: "disabled",
    reconnectTimer: null,
    flushTimer: null,
    commandPollTimer: null,
    queue: [],
    lastDataRecordSentAt: 0,
    lastHandledCommandId: null,
    sequence: 0
};

function nextBridgeSequence() {
    bridgeState.sequence += 1;
    return bridgeState.sequence;
}

function updateBridgeUi(status) {
    bridgeState.status = status;
    if (!dom.bridgeStatusText || !dom.bridgeStatusDot) {
        return;
    }

    const classNames = [
        "bridge-status-disabled",
        "bridge-status-connecting",
        "bridge-status-connected",
        "bridge-status-disconnected"
    ];
    dom.bridgeStatusText.classList.remove(...classNames);
    dom.bridgeStatusDot.classList.remove("ok");

    if (status === "connected") {
        dom.bridgeStatusText.classList.add("bridge-status-connected");
        dom.bridgeStatusDot.classList.add("ok");
        dom.bridgeStatusText.lastChild.textContent = "connected";
        return;
    }
    if (status === "connecting") {
        dom.bridgeStatusText.classList.add("bridge-status-connecting");
        dom.bridgeStatusText.lastChild.textContent = "connecting";
        return;
    }
    if (status === "disconnected") {
        dom.bridgeStatusText.classList.add("bridge-status-disconnected");
        dom.bridgeStatusText.lastChild.textContent = "disconnected";
        return;
    }

    dom.bridgeStatusText.classList.add("bridge-status-disabled");
    dom.bridgeStatusText.lastChild.textContent = "disabled";
}

function loadBridgeEnabledPreference() {
    try {
        return localStorage.getItem(BRIDGE_ENABLED_STORAGE_KEY) === "true";
    } catch (err) {
        console.warn("Failed to load bridge preference", err);
        return false;
    }
}

function saveBridgeEnabledPreference(enabled) {
    try {
        localStorage.setItem(BRIDGE_ENABLED_STORAGE_KEY, enabled ? "true" : "false");
    } catch (err) {
        console.warn("Failed to save bridge preference", err);
    }
}

function loadBridgeUrlPreference() {
    try {
        return localStorage.getItem(BRIDGE_URL_STORAGE_KEY) || null;
    } catch (err) {
        console.warn("Failed to load bridge URL preference", err);
        return null;
    }
}

function saveBridgeUrlPreference(url) {
    try {
        localStorage.setItem(BRIDGE_URL_STORAGE_KEY, url || "");
    } catch (err) {
        console.warn("Failed to save bridge URL preference", err);
    }
}

function clearViewerSessionsOnBridgeUrlChange(newUrl) {
    // Bridge URL が変わった場合、Viewer側のセッション履歴をクリアして、新接続先から再取得する
    try {
        const previousUrl = localStorage.getItem(BRIDGE_URL_PREVIOUS_STORAGE_KEY) || "";
        const normalizedNew = (newUrl || "").trim();
        const normalizedPrev = (previousUrl || "").trim();

        if (normalizedPrev && normalizedNew !== normalizedPrev) {
            console.log(`Bridge URL changed from ${normalizedPrev} to ${normalizedNew}, clearing session cache`);
            localStorage.removeItem(STORAGE_KEY);
            localStorage.removeItem(BRIDGE_SESSION_SYNC_KEY);
        }

        localStorage.setItem(BRIDGE_URL_PREVIOUS_STORAGE_KEY, normalizedNew);
    } catch (err) {
        console.warn("Failed to handle bridge URL change", err);
    }
}


async function probeBridgeUrlCandidate(url) {
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), BRIDGE_PROBE_TIMEOUT_MS);
        
        const response = await fetch(`${url}/health`, {
            signal: controller.signal
        });
        
        clearTimeout(timeoutId);
        
        if (response.ok) {
            console.log(`Bridge URL probe succeeded: ${url}`);
            return url;
        }
    } catch (err) {
        console.debug(`Bridge URL probe failed for ${url}:`, err.message);
    }
    return null;
}

async function autoProbeBridgeUrl() {
    // First try saved preference
    const savedUrl = loadBridgeUrlPreference();
    if (savedUrl) {
        const result = await probeBridgeUrlCandidate(savedUrl);
        if (result) {
            return result;
        }
        console.warn(`Saved bridge URL ${savedUrl} is no longer available, reprobing...`);
    }

    // Try all candidates
    for (const url of BRIDGE_URL_CANDIDATES) {
        const result = await probeBridgeUrlCandidate(url);
        if (result) {
            saveBridgeUrlPreference(url);
            return url;
        }
    }

    console.error("No bridge URL candidates responded to probe");
    return null;
}

async function initBridgeUrl() {
    const httpUrl = await autoProbeBridgeUrl();
    if (!httpUrl) {
        bridgeState.httpUrl = null;
        bridgeState.wsUrl = null;
        return;
    }

    // URL 変更検知: 前回と異なれば セッション履歴をクリア
    clearViewerSessionsOnBridgeUrlChange(httpUrl);

    bridgeState.httpUrl = httpUrl;
    
    if (window.location.protocol === "https:") {
        bridgeState.wsUrl = null;
    } else {
        bridgeState.wsUrl = httpUrl.replace(/^http:/, "ws:") + "/ws/viewer";
    }

    console.log(`Bridge configured: HTTP=${bridgeState.httpUrl}, WS=${bridgeState.wsUrl}`);
}


function buildSessionSyncSignature(sessions) {
    if (!Array.isArray(sessions) || sessions.length === 0) {
        return "empty";
    }

    return sessions.map((session) => [
        session?.id || "",
        session?.name || "",
        session?.startIso || "",
        session?.endIso || "",
        Array.isArray(session?.records) ? session.records.length : 0
    ].join("|")).join(";");
}

function loadLastBridgeSessionSyncSignature() {
    try {
        return localStorage.getItem(BRIDGE_SESSION_SYNC_KEY) || "";
    } catch (err) {
        console.warn("Failed to load bridge session sync marker", err);
        return "";
    }
}

function saveLastBridgeSessionSyncSignature(signature) {
    try {
        localStorage.setItem(BRIDGE_SESSION_SYNC_KEY, signature || "");
    } catch (err) {
        console.warn("Failed to save bridge session sync marker", err);
    }
}

async function getBridgeSessionCount() {
    try {
        if (!bridgeState.httpUrl) {
            return null;
        }
        const response = await fetch(`${bridgeState.httpUrl}/sessions`);
        if (!response.ok) {
            return null;
        }
        const payload = await response.json();
        return Number.isFinite(payload?.total) ? payload.total : null;
    } catch (err) {
        console.warn("Failed to inspect bridge session count", err);
        return null;
    }
}

function setBridgeEnabled(enabled) {
    bridgeState.enabled = !!enabled;
    saveBridgeEnabledPreference(bridgeState.enabled);
    if (dom.bridgeEnabledInput) {
        dom.bridgeEnabledInput.checked = bridgeState.enabled;
    }
    if (bridgeState.enabled) {
        updateBridgeUi("connecting");
        // Initialize bridge URL first (async), then connect
        initBridgeUrl().then(() => {
            startBridgeCommandPolling();
            ensureBridgeConnection();
            flushBridgeQueueSoon();
        }).catch((err) => {
            console.error("Failed to initialize bridge URL", err);
            updateBridgeUi("disconnected");
        });
        return;
    }
    disconnectBridge();
    updateBridgeUi("disabled");
}

function initializeBridgeControls() {
    bridgeState.enabled = loadBridgeEnabledPreference();
    if (dom.bridgeEnabledInput) {
        dom.bridgeEnabledInput.checked = bridgeState.enabled;
        dom.bridgeEnabledInput.addEventListener("change", (event) => {
            setBridgeEnabled(event.target.checked);
        });
    }
    updateBridgeUi(bridgeState.enabled ? "disconnected" : "disabled");
    if (bridgeState.enabled) {
        // Initialize bridge URL first (async), then connect
        initBridgeUrl().then(() => {
            startBridgeCommandPolling();
            ensureBridgeConnection();
        }).catch((err) => {
            console.error("Failed to initialize bridge URL", err);
            updateBridgeUi("disconnected");
        });
    }
}

async function probeBridgeConnection() {
    try {
        if (!bridgeState.httpUrl) {
            bridgeState.connected = false;
            updateBridgeUi(bridgeState.enabled ? "disconnected" : "disabled");
            return;
        }
        const response = await fetch(`${bridgeState.httpUrl}/health`);
        if (response.ok) {
            bridgeState.connected = true;
            updateBridgeUi("connected");
            return;
        }
    } catch (err) {
        console.warn("Bridge HTTP probe failed", err);
    }
    bridgeState.connected = false;
    updateBridgeUi(bridgeState.enabled ? "disconnected" : "disabled");
}

function buildBridgeEnvelope(eventType, data) {
    return {
        id: `viewer-${Date.now()}-${nextBridgeSequence()}`,
        type: eventType,
        ts: nowIso(),
        data
    };
}

function enqueueBridgeEvent(eventType, data) {
    if (eventType === "data_record") {
        const now = Date.now();
        if (now - bridgeState.lastDataRecordSentAt < BRIDGE_SAMPLE_INTERVAL_MS) {
            return;
        }
        bridgeState.lastDataRecordSentAt = now;
    }

    bridgeState.queue.push(buildBridgeEnvelope(eventType, data));
    if (bridgeState.queue.length > 500) {
        bridgeState.queue.shift();
    }
    flushBridgeQueueSoon();
}

function flushBridgeQueueSoon() {
    if (bridgeState.flushTimer) {
        return;
    }
    bridgeState.flushTimer = setTimeout(async () => {
        bridgeState.flushTimer = null;
        await flushBridgeQueue();
    }, BRIDGE_FLUSH_INTERVAL_MS);
}

async function flushBridgeQueue() {
    if (!bridgeState.enabled || bridgeState.queue.length === 0) {
        return;
    }

    const batch = bridgeState.queue.slice(0, BRIDGE_BATCH_SIZE);
    if (bridgeState.connected && bridgeState.socket && bridgeState.socket.readyState === WebSocket.OPEN) {
        for (const event of batch) {
            bridgeState.socket.send(JSON.stringify({
                type: "event",
                event_type: event.type,
                data: event.data
            }));
        }
        bridgeState.queue.splice(0, batch.length);
        if (bridgeState.queue.length > 0) {
            flushBridgeQueueSoon();
        }
        return;
    }

    if (!bridgeState.httpUrl) {
        ensureBridgeConnection();
        return;
    }

    try {
        for (const event of batch) {
            const response = await fetch(`${bridgeState.httpUrl}/event`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    type: event.type,
                    data: event.data
                })
            });
            if (!response.ok) {
                throw new Error(`bridge http ${response.status}`);
            }
            bridgeState.queue.shift();
        }
    } catch (err) {
        console.warn("Bridge flush failed", err);
        ensureBridgeConnection();
    }
}

function syncStoredSessionsToBridge() {
    // localStorage のセッション一覧を bridge に同期
    const storedSessions = loadSessions();
    if (!storedSessions || storedSessions.length === 0) {
        console.debug("No stored sessions to sync to bridge");
        return;
    }

    const signature = buildSessionSyncSignature(storedSessions);
    const lastSignature = loadLastBridgeSessionSyncSignature();
    if (signature === lastSignature) {
        // bridge 再起動後で event_queue が消えている場合は再同期する
        void getBridgeSessionCount().then((count) => {
            if (count && count > 0) {
                console.debug("Stored sessions already synced to bridge; skipping replay");
            } else {
                console.debug("Bridge has no sessions; forcing stored session replay");
                saveLastBridgeSessionSyncSignature("");
                syncStoredSessionsToBridge();
            }
        });
        return;
    }

    console.log(`Syncing ${storedSessions.length} stored sessions to bridge`);
    for (const session of storedSessions) {
        // session_started イベントを送信
        if (typeof enqueueBridgeEvent === "function") {
            enqueueBridgeEvent("session_started", {
                sessionId: session.id,
                name: session.name,
                sensorId: session.sensorId,
                startIso: session.startIso
            });
        }

        // records を DATA_RECORD イベントとして送信
        if (session.records && Array.isArray(session.records) && typeof enqueueBridgeEvent === "function") {
            for (const record of session.records) {
                enqueueBridgeEvent("data_record", {
                    sessionId: session.id,
                    sensorId: session.sensorId,
                    channels: record
                });
            }
        }

        // もし session が終了していれば、session_ended イベントも送信
        if (session.endIso && typeof enqueueBridgeEvent === "function") {
            enqueueBridgeEvent("session_ended", {
                sessionId: session.id,
                name: session.name,
                sensorId: session.sensorId,
                startIso: session.startIso,
                endIso: session.endIso,
                records: session.records ? session.records.length : 0
            });
        }
    }

    saveLastBridgeSessionSyncSignature(signature);
}

function ensureBridgeConnection() {
    if (!bridgeState.enabled) {
        return;
    }
    if (!bridgeState.wsUrl) {
        void probeBridgeConnection();
        return;
    }
    if (bridgeState.socket && (bridgeState.socket.readyState === WebSocket.OPEN || bridgeState.socket.readyState === WebSocket.CONNECTING)) {
        return;
    }
    connectBridge();
}

function connectBridge() {
    if (!bridgeState.enabled) {
        return;
    }
    if (!bridgeState.wsUrl) {
        void probeBridgeConnection();
        return;
    }
    updateBridgeUi("connecting");
    try {
        const socket = new WebSocket(bridgeState.wsUrl);
        bridgeState.socket = socket;

        socket.addEventListener("open", () => {
            bridgeState.connected = true;
            updateBridgeUi("connected");
            if (bridgeState.reconnectTimer) {
                clearTimeout(bridgeState.reconnectTimer);
                bridgeState.reconnectTimer = null;
            }
            syncStoredSessionsToBridge();
            flushBridgeQueueSoon();
            startBridgeCommandPolling();
            socket.send(JSON.stringify({ type: "query_state" }));
        });

        socket.addEventListener("message", async (event) => {
            try {
                const message = JSON.parse(event.data);
                await handleBridgeMessage(message);
            } catch (err) {
                console.warn("Bridge message parse failed", err);
            }
        });

        socket.addEventListener("close", () => {
            bridgeState.connected = false;
            updateBridgeUi(bridgeState.enabled ? "disconnected" : "disabled");
            if (bridgeState.socket === socket) {
                bridgeState.socket = null;
            }
            scheduleBridgeReconnect();
        });

        socket.addEventListener("error", (err) => {
            bridgeState.connected = false;
            updateBridgeUi(bridgeState.enabled ? "disconnected" : "disabled");
            console.warn("Bridge socket error", err);
        });
    } catch (err) {
        updateBridgeUi("disconnected");
        console.warn("Bridge connection failed", err);
        scheduleBridgeReconnect();
    }
}

function scheduleBridgeReconnect() {
    if (!bridgeState.enabled) {
        return;
    }
    if (!bridgeState.wsUrl) {
        bridgeState.reconnectTimer = setTimeout(() => {
            bridgeState.reconnectTimer = null;
            void probeBridgeConnection();
        }, 3000);
        return;
    }
    if (bridgeState.reconnectTimer) {
        return;
    }
    bridgeState.reconnectTimer = setTimeout(() => {
        bridgeState.reconnectTimer = null;
        connectBridge();
    }, 3000);
}

function disconnectBridge() {
    bridgeState.connected = false;
    if (bridgeState.reconnectTimer) {
        clearTimeout(bridgeState.reconnectTimer);
        bridgeState.reconnectTimer = null;
    }
    if (bridgeState.commandPollTimer) {
        clearInterval(bridgeState.commandPollTimer);
        bridgeState.commandPollTimer = null;
    }
    if (bridgeState.socket) {
        const socket = bridgeState.socket;
        bridgeState.socket = null;
        if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
            socket.close();
        }
    }
    updateBridgeUi(bridgeState.enabled ? "disconnected" : "disabled");
}

async function handleBridgeMessage(message) {
    if (!message || typeof message !== "object") {
        return;
    }

    if (message.type === "state_response" || message.type === "event_ack" || message.type === "event_processed" || message.type === "event_broadcast") {
        return;
    }

    const commandType = message.type;
    if (commandType === "download_session") {
        await executeDownloadSessionCommand(message);
        return;
    }

    if (commandType === "query_device_id") {
        await executeQueryDeviceIdCommand(message);
        return;
    }

    if (commandType === "connect_device") {
        await executeConnectDeviceCommand(message);
        return;
    }

    if (commandType === "disconnect_device") {
        await executeDisconnectDeviceCommand(message);
        return;
    }

    if (commandType === "start_session") {
        await executeStartSessionCommand(message);
        return;
    }

    if (commandType === "stop_session") {
        await executeStopSessionCommand(message);
        return;
    }

    if (commandType === "notify_user") {
        const payload = message.payload || {};
        setStatus(payload.message || "bridge notification");
    }
}

function startBridgeCommandPolling() {
    if (!bridgeState.enabled) {
        return;
    }
    if (bridgeState.commandPollTimer) {
        return;
    }
    bridgeState.commandPollTimer = setInterval(() => {
        void pollPendingBridgeCommand();
    }, BRIDGE_COMMAND_POLL_INTERVAL_MS);
}

async function pollPendingBridgeCommand() {
    if (!bridgeState.enabled || !bridgeState.httpUrl) {
        return;
    }
    try {
        const response = await fetch(`${bridgeState.httpUrl}/commands/pending`);
        if (!response.ok) {
            return;
        }
        const command = await response.json();
        if (!command || !command.id || !command.type) {
            return;
        }
        if (command.id === bridgeState.lastHandledCommandId) {
            return;
        }
        bridgeState.lastHandledCommandId = command.id;
        await handleBridgeMessage(command);
    } catch (err) {
        console.warn("Bridge command poll failed", err);
    }
}

async function executeDownloadSessionCommand(message) {
    const payload = message.payload || {};
    const sessionId = payload.session_id;
    const session = typeof getSessionById === "function" ? getSessionById(sessionId) : null;

    if (!session) {
        await sendBridgeCommandResult(message.id, {
            success: false,
            error: "session not found",
            sessionId
        });
        return;
    }

    try {
        await downloadSessionZip(session);
        await sendBridgeCommandResult(message.id, {
            success: true,
            action: "browser_download_started",
            sessionId,
            fileName: `${getSessionFileStem(session)}.zip`
        });
    } catch (err) {
        await sendBridgeCommandResult(message.id, {
            success: false,
            error: err.message || String(err),
            sessionId
        });
    }
}

async function executeConnectDeviceCommand(message) {
    if (state.isConnected) {
        await sendBridgeCommandResult(message.id, {
            success: true,
            action: "connect_device",
            alreadyConnected: true
        });
        return;
    }

    try {
        await connectDevice();
        await sendBridgeCommandResult(message.id, {
            success: state.isConnected,
            action: "connect_device",
            connected: state.isConnected,
            sensorId: state.sensorId
        });
    } catch (err) {
        await sendBridgeCommandResult(message.id, {
            success: false,
            action: "connect_device",
            error: err.message || String(err)
        });
    }
}

async function executeDisconnectDeviceCommand(message) {
    if (!state.isConnected) {
        await sendBridgeCommandResult(message.id, {
            success: true,
            action: "disconnect_device",
            alreadyDisconnected: true
        });
        return;
    }

    try {
        await disconnectDevice(false);
        await sendBridgeCommandResult(message.id, {
            success: !state.isConnected,
            action: "disconnect_device",
            disconnected: !state.isConnected
        });
    } catch (err) {
        await sendBridgeCommandResult(message.id, {
            success: false,
            action: "disconnect_device",
            error: err.message || String(err)
        });
    }
}

async function executeStartSessionCommand(message) {
    const payload = message.payload || {};
    const requestedName = typeof payload.name === "string" ? payload.name.trim() : "";

    if (!state.isConnected) {
        await sendBridgeCommandResult(message.id, {
            success: false,
            action: "start_session",
            error: "device is not connected"
        });
        return;
    }

    if (state.currentSession && !state.currentSession.endIso) {
        await sendBridgeCommandResult(message.id, {
            success: true,
            action: "start_session",
            alreadyRunning: true,
            sessionId: state.currentSession.id
        });
        return;
    }

    const beforeId = state.currentSession ? state.currentSession.id : null;
    if (requestedName && dom.sessionNameInput) {
        dom.sessionNameInput.value = requestedName;
    }

    try {
        startSession();
        const startedSession = state.currentSession;
        const started = !!startedSession && startedSession.id !== beforeId && !startedSession.endIso;
        await sendBridgeCommandResult(message.id, {
            success: started,
            action: "start_session",
            sessionId: startedSession ? startedSession.id : null,
            name: startedSession ? startedSession.name : "",
            running: !!startedSession && !startedSession.endIso
        });
    } catch (err) {
        await sendBridgeCommandResult(message.id, {
            success: false,
            action: "start_session",
            error: err.message || String(err)
        });
    }
}

async function executeStopSessionCommand(message) {
    const runningSession = (typeof getRunningSession === "function" && getRunningSession())
        || (state.currentSession && !state.currentSession.endIso ? state.currentSession : null);

    if (!runningSession) {
        await sendBridgeCommandResult(message.id, {
            success: true,
            action: "stop_session",
            alreadyStopped: true
        });
        return;
    }

    const targetSessionId = runningSession.id;
    try {
        stopSession(targetSessionId);
        const stoppedSession = typeof getSessionById === "function" ? getSessionById(targetSessionId) : null;
        const stopped = !!stoppedSession && !!stoppedSession.endIso;
        await sendBridgeCommandResult(message.id, {
            success: stopped,
            action: "stop_session",
            sessionId: targetSessionId,
            endIso: stoppedSession ? stoppedSession.endIso : null
        });
    } catch (err) {
        await sendBridgeCommandResult(message.id, {
            success: false,
            action: "stop_session",
            error: err.message || String(err)
        });
    }
}

async function sendBridgeCommandResult(commandId, result) {
    if (!commandId) {
        return;
    }

    const payload = {
        type: "command_result",
        command_id: commandId,
        result
    };

    if (bridgeState.connected && bridgeState.socket && bridgeState.socket.readyState === WebSocket.OPEN) {
        bridgeState.socket.send(JSON.stringify(payload));
        return;
    }

    if (!bridgeState.httpUrl) {
        return;
    }
    await fetch(`${bridgeState.httpUrl}/commands/execute/${encodeURIComponent(commandId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(result)
    });
}

async function executeQueryDeviceIdCommand(message) {
    if (!state.isConnected) {
        await sendBridgeCommandResult(message.id, {
            success: false,
            action: "query_device_id",
            error: "device is not connected"
        });
        return;
    }

    try {
        const deviceId = await queryDeviceIdFromDevice();
        await sendBridgeCommandResult(message.id, {
            success: true,
            action: "query_device_id",
            sensorId: deviceId,
            deviceId,
            source: "live_query"
        });
    } catch (err) {
        await sendBridgeCommandResult(message.id, {
            success: false,
            action: "query_device_id",
            error: err.message || String(err)
        });
    }
}