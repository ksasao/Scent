function crc8FromFirmwareTable(text) {
    let crc = 0;
    for (let i = 0; i < text.length; i += 1) {
        crc = CRC8_TABLE[(crc ^ (text.charCodeAt(i) & 0xff)) & 0xff];
    }
    return crc;
}

function parseSensorLine(line) {
    const parts = line.trim().split(",");
    if (parts.length < 6) return null;

    const rawCh = parts[0].trim();
    const rawTemp = parts[1].trim();
    const rawHumidity = parts[2].trim();
    const rawPressure = parts[3].trim();
    const rawCurrent = parts[4].trim();
    const received = (parts[5] || "").trim().toUpperCase();

    const ch = Number(rawCh);
    const temp = Number(rawTemp);
    const humidity = Number(rawHumidity);
    const pressure = Number(rawPressure);
    const current = Number(rawCurrent);

    if (!Number.isInteger(ch) || ch < 0 || ch > 9) return null;
    if ([temp, humidity, pressure, current].some((v) => Number.isNaN(v))) return null;

    // Firmware calculates CRC from the raw CSV text fields (before numeric parsing).
    const dataStr = [rawCh, rawTemp, rawHumidity, rawPressure, rawCurrent].join(",");
    const calcValue = crc8FromFirmwareTable(dataStr) & 0xff;
    const receivedValue = Number.parseInt(received, 16);
    if (!Number.isFinite(receivedValue)) {
        return null;
    }
    const crcOk = calcValue === (receivedValue & 0xff);

    return { ch, temp, humidity, pressure, current, crcOk };
}

function onCrcError(line) {
    console.warn("CRC mismatch", { line });
    if (typeof enqueueBridgeEvent === "function") {
        enqueueBridgeEvent("crc_error", { line });
    }
}

async function queryDeviceIdFromDevice(timeoutMs = 6000) {
    if (!state.isConnected || !state.writer || !state.reader) {
        throw new Error("device is not connected");
    }

    const previousSensorId = state.sensorId;
    await sendCommand("id\n");

    const startMs = Date.now();
    while (Date.now() - startMs < timeoutMs) {
        if (state.sensorId && state.sensorId !== "-" && state.sensorId !== previousSensorId) {
            return state.sensorId;
        }
        if (state.sensorId && state.sensorId !== "-") {
            return state.sensorId;
        }
        await new Promise((resolve) => setTimeout(resolve, 100));
    }

    if (state.sensorId && state.sensorId !== "-") {
        return state.sensorId;
    }

    throw new Error("device id query timed out");
}

async function connectDevice() {
    try {
        if (!navigator.serial) {
            throw new Error("Web Serial API is not supported on this browser");
        }

        // Agent 経由でも接続できるよう、許可済みポートがあれば優先して使用する
        const grantedPorts = await navigator.serial.getPorts();
        if (grantedPorts && grantedPorts.length > 0) {
            state.port = grantedPorts[0];
        } else {
            state.port = await navigator.serial.requestPort();
        }
        await state.port.open({ baudRate: BAUD_RATE });

        state.writer = state.port.writable ? state.port.writable.getWriter() : null;
        state.reader = state.port.readable ? state.port.readable.getReader() : null;
        if (!state.reader) {
            throw new Error("Serial readable stream is unavailable");
        }

        state.readLoopActive = true;
        state.readBuffer = "";
        state.isConnected = true;
        state.sensorId = "-";
        dom.sensorId.textContent = "-";
        dom.latestRxLine.textContent = "-";
        state.liveStartMs = Date.now();
        state.lastRxMs = Date.now();
        setStatus("connected");
        updateCommUi(true);
        updateButtons();
        if (typeof enqueueBridgeEvent === "function") {
            enqueueBridgeEvent("device_connected", {
                sensorId: state.sensorId,
                connectedAt: nowIso()
            });
        }

        try {
            // Multi-cycle polling-based ID read (3 cycles x 2 seconds = up to 6 seconds)
            const deviceId = await queryDeviceIdFromDevice();
            console.log(`ID read successful: ${deviceId}`);
        } catch (idErr) {
            console.warn("ID read failed:", idErr);
        }

        readLoop();
    } catch (err) {
        console.error(err);
        await disconnectDevice(true);
        setStatus(`connect error: ${err.message || err}`);
    }
}

async function disconnectDevice(silent) {
    if (state.currentSession && !state.currentSession.endIso) {
        stopSession();
    }

    state.readLoopActive = false;

    try {
        if (state.reader) {
            await state.reader.cancel();
            state.reader.releaseLock();
        }
    } catch (err) {
        console.warn(err);
    }

    try {
        if (state.writer) {
            state.writer.releaseLock();
        }
    } catch (err) {
        console.warn(err);
    }

    try {
        if (state.port) {
            await state.port.close();
        }
    } catch (err) {
        console.warn(err);
    }

    state.reader = null;
    state.writer = null;
    state.port = null;
    state.isConnected = false;
    dom.latestRxLine.textContent = "-";
    updateButtons();
    updateCommUi(false);
    if (typeof enqueueBridgeEvent === "function") {
        enqueueBridgeEvent("device_disconnected", {
            sensorId: state.sensorId,
            disconnectedAt: nowIso()
        });
    }

    if (!silent) {
        setStatus("disconnected");
    }
}

async function readLoop() {
    while (state.readLoopActive && state.reader) {
        try {
            const { value, done } = await state.reader.read();
            if (done) break;
            if (!value) continue;

            state.lastRxMs = Date.now();
            updateCommUi(true);

            state.readBuffer += new TextDecoder().decode(value, { stream: true });
            let idx;
            while ((idx = state.readBuffer.indexOf("\n")) >= 0) {
                const line = state.readBuffer.slice(0, idx).replace(/\r$/, "");
                state.readBuffer = state.readBuffer.slice(idx + 1);
                handleSerialLine(line);
            }
        } catch (err) {
            if (state.readLoopActive) {
                setStatus(`read error: ${err.message || err}`);
            }
            break;
        }
    }
}

function handleSerialLine(line) {
    if (!line) return;

    dom.latestRxLine.textContent = line;

    if (line.startsWith("ID,")) {
        const idText = line.split(",", 2)[1] || "";
        state.sensorId = idText;
        dom.sensorId.textContent = idText ? `0x${idText.toUpperCase().padStart(8, "0")}` : "-";
        updateButtons();
        return;
    }

    const row = parseSensorLine(line);
    if (!row) {
        return;
    }

    if (!row.crcOk) {
        onCrcError(line);
        if (STRICT_CRC) {
            return;
        }
    }

    const sessionRunning = !!state.currentSession && !state.currentSession.endIso;
    if (!sessionRunning) {
        return;
    }
    const baseMs = Date.parse(state.currentSession.startIso);
    const t = (Date.now() - baseMs) / 1000;

    if (state.currentSession.baselineCurrents[row.ch] === null) {
        state.currentSession.baselineCurrents[row.ch] = row.current;
    }
    if (!state.currentSession.baselineReady) {
        state.currentSession.baselineReady = state.currentSession.baselineCurrents.every((v) => v !== null);
    }

    if (state.currentSession.baselineReady) {
        const relativeCurrent = row.current - state.currentSession.baselineCurrents[row.ch];
        datasets[row.ch].data.push({ x: t, y: relativeCurrent });
        if (datasets[row.ch].data.length > 5000) {
            datasets[row.ch].data.shift();
        }
    }

    const record = {
        t,
        ch: row.ch,
        temp: row.temp,
        humidity: row.humidity,
        pressure: row.pressure,
        current: row.current
    };
    state.currentSession.records.push(record);
    updateSessionInfo();
    schedulePersist();

    if (typeof enqueueBridgeEvent === "function") {
        enqueueBridgeEvent("data_record", {
            sessionId: state.currentSession.id,
            sensorId: state.currentSession.sensorId,
            record
        });
    }

    if (state.xAutoRange) {
        chart.options.scales.x.min = undefined;
        chart.options.scales.x.max = undefined;
    }
    chart.update("none");
}

async function sendCommand(text) {
    if (!state.writer) {
        throw new Error("Serial writer is unavailable");
    }
    const bytes = new TextEncoder().encode(text);
    await state.writer.write(bytes);
}
