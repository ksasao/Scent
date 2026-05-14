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

// ===== COM Port Management =====

const COM_PORT_STORAGE_KEY = "scent.selected.com.port.v1";
let preferredComPort = null;

async function getAvailableComPorts() {
    try {
        if (!navigator.serial) {
            console.warn("Web Serial API not supported");
            return [];
        }
        const ports = await navigator.serial.getPorts();
        return ports || [];
    } catch (err) {
        console.warn("Failed to get available COM ports:", err);
        return [];
    }
}

function getPortDisplayName(port) {
    try {
        const info = port.getInfo ? port.getInfo() : {};
        const usbProductId = info.usbProductId;
        const usbVendorId = info.usbVendorId;

        if (usbVendorId === 0x1a86 && usbProductId === 0x7523) {
            return "CH340";
        } else if (usbVendorId === 0x10c4 && usbProductId === 0xea60) {
            return "CP2102";
        } else if (usbVendorId === 0x0403) {
            return "FTDI";
        } else if (usbVendorId === 0x2e8a && usbProductId === 0x000a) {
            return "Pico";
        }
        return "Unknown";
    } catch (err) {
        return "Unknown";
    }
}

function saveSelectedComPort(port) {
    try {
        if (!port) {
            localStorage.removeItem(COM_PORT_STORAGE_KEY);
            return;
        }
        // ポートオブジェクトは JSON化できないため、識別情報を保存
        const info = port.getInfo ? port.getInfo() : {};
        const portData = JSON.stringify({
            usbVendorId: info.usbVendorId,
            usbProductId: info.usbProductId
        });
        localStorage.setItem(COM_PORT_STORAGE_KEY, portData);
    } catch (err) {
        console.warn("Failed to save selected COM port:", err);
    }
}

function findSavedComPort(ports) {
    try {
        const savedData = localStorage.getItem(COM_PORT_STORAGE_KEY);
        if (!savedData) {
            return null;
        }
        const saved = JSON.parse(savedData);
        return ports.find((port) => {
            const info = port.getInfo ? port.getInfo() : {};
            return info.usbVendorId === saved.usbVendorId && 
                   info.usbProductId === saved.usbProductId;
        });
    } catch (err) {
        console.warn("Failed to find saved COM port:", err);
        return null;
    }
}

function setPreferredComPort(port) {
    preferredComPort = port || null;
    if (port) {
        saveSelectedComPort(port);
    }
}

async function pickComPortForConnection() {
    const grantedPorts = await getAvailableComPorts();
    if (preferredComPort) {
        return preferredComPort;
    }
    const savedPort = findSavedComPort(grantedPorts);
    if (savedPort) {
        return savedPort;
    }
    if (grantedPorts.length === 1) {
        return grantedPorts[0];
    }
    // 許可済みポートが複数ある場合はユーザーに選択してもらう。
    // requestPort は許可済みポートを選び直す用途にも使える。
    const picked = await navigator.serial.requestPort();
    setPreferredComPort(picked);
    return picked;
}

async function queryDeviceIdFromDevice(timeoutMs = 6000) {
    if (!state.isConnected || !state.writer || !state.reader) {
        throw new Error("device is not connected");
    }

    const startMs = Date.now();
    let lastRequestMs = 0;
    const REQUEST_INTERVAL_MS = 1000; // ID要求を1秒ごとに再送信
    const POLL_INTERVAL_MS = 50;      // ポーリング間隔を短縮（100ms → 50ms）

    // ID要求を複数回送信（リトライあり）
    while (Date.now() - startMs < timeoutMs) {
        // 定期的にID要求を送信（再試行）
        if (Date.now() - lastRequestMs > REQUEST_INTERVAL_MS) {
            try {
                await sendCommand("id\n");
                lastRequestMs = Date.now();
                console.debug("ID query sent to device");
            } catch (err) {
                console.warn("Failed to send ID query command", err);
            }
        }

        // ID が取得できたか確認（"-" 以外の値が存在すればOK）
        if (state.sensorId && state.sensorId !== "-") {
            console.log(`Device ID obtained: ${state.sensorId} (${Date.now() - startMs}ms)`);
            return state.sensorId;
        }

        // ポーリング間隔を短縮して高速化
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    }

    // タイムアウト後も最後の値をチェック
    if (state.sensorId && state.sensorId !== "-") {
        console.warn(`Device ID obtained after timeout: ${state.sensorId} (${Date.now() - startMs}ms)`);
        return state.sensorId;
    }

    throw new Error(`device id query timed out after ${Date.now() - startMs}ms (timeout=${timeoutMs}ms)`);
}

function initializeSerialPortEventListeners() {
    /**
     * デバイスが接続/切断された時にポート一覧を自動更新
     * これにより、新しいデバイス接続時に自動的にドロップダウンが更新される
     */
    if (navigator.serial) {
        navigator.serial.addEventListener("connect", (event) => {
            console.log("Serial device connected");
            void getAvailableComPorts().then((ports) => {
                setStatus(`${ports.length} serial port(s) available`);
            });
        });

        navigator.serial.addEventListener("disconnect", (event) => {
            console.log("Serial device disconnected");
            void getAvailableComPorts().then((ports) => {
                setStatus(`${ports.length} serial port(s) available`);
            });
        });
    }
}

async function connectDevice() {
    try {
        if (!navigator.serial) {
            throw new Error("Web Serial API is not supported on this browser");
        }

        const selectedPort = await pickComPortForConnection();

        if (!selectedPort) {
            throw new Error("No COM port selected");
        }

        state.port = selectedPort;
        setStatus("opening port...");
        await state.port.open({ baudRate: BAUD_RATE });
        
        // ポート選択を保存
        saveSelectedComPort(selectedPort);

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
        
        // 接続中はRefreshボタンを無効化
        if (dom.refreshPortsBtn) {
            dom.refreshPortsBtn.disabled = true;
        }
        
        if (typeof enqueueBridgeEvent === "function") {
            enqueueBridgeEvent("device_connected", {
                sensorId: state.sensorId,
                connectedAt: nowIso()
            });
        }

        // Start read loop immediately (important: do this before ID query)
        // readLoop is async infinite loop, so we don't await it
        readLoop().catch((err) => {
            console.error("readLoop terminated unexpectedly:", err);
        });

        // Device ID 取得を段階的に試行（ネットワーク遅延対策）
        setStatus("querying device id...");
        let deviceId = null;
        const idQueryAttempts = [
            { timeout: 3000, attempt: 1 },
            { timeout: 5000, attempt: 2 },
            { timeout: 8000, attempt: 3 }
        ];

        for (const { timeout, attempt } of idQueryAttempts) {
            try {
                setStatus(`querying device id (attempt ${attempt}/${idQueryAttempts.length})...`);
                deviceId = await queryDeviceIdFromDevice(timeout);
                console.log(`ID read successful on attempt ${attempt}: ${deviceId}`);
                setStatus("device id obtained");
                break;
            } catch (idErr) {
                const elapsedMs = Date.now() - state.liveStartMs;
                console.warn(`ID read attempt ${attempt} failed after ${elapsedMs}ms:`, idErr.message);
                if (attempt === idQueryAttempts.length) {
                    // 最終試行が失敗した場合も接続は続ける
                    console.warn("All ID query attempts exhausted; continuing with unknown ID");
                    setStatus("connected (device id: unknown)");
                } else {
                    // 次の試行前に少し待機
                    await new Promise((resolve) => setTimeout(resolve, 500));
                }
            }
        }
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
    preferredComPort = null;
    dom.latestRxLine.textContent = "-";
    updateButtons();
    
    // 接続解除後はRefreshボタンを有効化
    if (dom.refreshPortsBtn) {
        dom.refreshPortsBtn.disabled = false;
    }
    
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
