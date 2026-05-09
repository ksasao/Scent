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

refreshSessionSelect();
if (state.sessions.length > 0) {
    dom.sessionSelect.value = state.sessions[state.sessions.length - 1].id;
    onSessionSelectChanged();
} else {
    updateSessionInfo();
}
updateButtons();
maybeUpdateCommHealth();
setInterval(maybeUpdateCommHealth, 1000);

window.addEventListener("beforeunload", () => {
    if (state.currentSession && !state.currentSession.endIso) {
        state.currentSession.endIso = nowIso();
    }
    saveSessions();
});
