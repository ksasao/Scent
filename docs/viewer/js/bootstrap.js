function maybeUpdateCommHealth() {
    if (!state.isConnected) {
        updateCommUi(false);
        return;
    }
    const ok = Date.now() - state.lastRxMs <= 10000;
    updateCommUi(ok);
}

function onSessionSelectChanged() {
    const selected = getSelectedSession();
    if (!selected) {
        return;
    }
    state.currentSession = selected;
    drawCurrentSession();
    updateSessionInfo();
    updateButtons();
    setStatus(selected.endIso ? "session loaded" : "running session loaded");
}

async function toggleConnection() {
    if (state.isConnected) {
        await disconnectDevice(false);
    } else {
        await connectDevice();
    }
    updateButtons();
}

function toggleSession() {
    const running = !!state.currentSession && !state.currentSession.endIso;
    if (running) {
        stopSession();
    } else {
        startSession();
    }
    updateButtons();
}

dom.connectionToggleBtn.addEventListener("click", toggleConnection);
dom.sessionToggleBtn.addEventListener("click", toggleSession);
dom.downloadBtn.addEventListener("click", async () => {
    try {
        await downloadSessionZip(getSelectedSession());
    } catch (err) {
        console.error(err);
        setStatus(`download error: ${err.message || err}`);
    }
});
dom.deleteBtn.addEventListener("click", deleteSelectedSession);
dom.deleteAllBtn.addEventListener("click", deleteAllSessions);
dom.sessionSelect.addEventListener("change", onSessionSelectChanged);

dom.chartCanvas.addEventListener("wheel", onWheelZoom, { passive: false });
dom.chartCanvas.addEventListener("mousedown", onPanStart);
dom.chartCanvas.addEventListener("mousemove", onPanMove);
dom.chartCanvas.addEventListener("mouseleave", onPanEnd);
window.addEventListener("mouseup", onPanEnd);

if (window.ResizeObserver) {
    const resizeObserver = new ResizeObserver(() => chart.resize());
    resizeObserver.observe(dom.chartCanvas.parentElement);
}

if (typeof initializeBridgeControls === "function") {
    initializeBridgeControls();
}

refreshSessionSelect();
if (state.sessions.length > 0) {
    dom.sessionSelect.value = state.sessions[state.sessions.length - 1].id;
    onSessionSelectChanged();
} else {
    updateSessionInfo();
}
updateButtons();
maybeUpdateCommHealth();

// Initialize serial port event listeners
if (typeof initializeSerialPortEventListeners === "function") {
    initializeSerialPortEventListeners();
}

void getAvailableComPorts().then((ports) => {
    setStatus(`${ports.length} serial port(s) available`);
});

if (dom.refreshPortsBtn) {
    dom.refreshPortsBtn.addEventListener("click", async () => {
        setStatus("refreshing COM ports...");
        // Web Serial は許可済みポートのみ getPorts() で列挙されるため、
        // 追加デバイスを出すにはユーザー操作で requestPort() が必要。
        let shouldAutoConnect = false;
        if (navigator.serial) {
            try {
                const selectedPort = await navigator.serial.requestPort();
                if (typeof setPreferredComPort === "function") {
                    setPreferredComPort(selectedPort);
                }
                if (typeof getPortDisplayName === "function") {
                    setStatus(`selected: ${getPortDisplayName(selectedPort)}`);
                }
                shouldAutoConnect = !state.isConnected;
            } catch (err) {
                // ユーザーがダイアログを閉じた場合は通常動作として扱う
                if (!err || err.name !== "NotFoundError") {
                    console.warn("Failed to request additional serial port permission", err);
                }
            }
        }
        const ports = await getAvailableComPorts();
        setStatus(`${ports.length} serial port(s) available`);

        // ポート選択ダイアログで「接続」が押された直後に、そのまま接続処理を開始する
        if (shouldAutoConnect) {
            setStatus("connecting...");
            await connectDevice();
            updateButtons();
        }
    });
}

setInterval(maybeUpdateCommHealth, 1000);

window.addEventListener("beforeunload", () => {
    if (state.currentSession && !state.currentSession.endIso) {
        state.currentSession.endIso = nowIso();
    }
    saveSessions();
});
