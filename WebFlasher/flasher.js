import { ESPLoader, Transport } from "https://unpkg.com/esptool-js@0.6.0/bundle.js";

const statusEl = document.getElementById("status");
const logEl = document.getElementById("log");
const connectBtn = document.getElementById("connectBtn");
const flashBtn = document.getElementById("flashBtn");
const disconnectBtn = document.getElementById("disconnectBtn");
const eraseAllEl = document.getElementById("eraseAll");

let port = null;
let transport = null;
let esploader = null;
let firmwareManifest = null;

function appendLog(message) {
  const ts = new Date().toLocaleTimeString("ja-JP", { hour12: false });
  logEl.textContent += `\n[${ts}] ${message}`;
  logEl.scrollTop = logEl.scrollHeight;
}

function setButtons(state) {
  connectBtn.disabled = !!state.connectDisabled;
  flashBtn.disabled = !!state.flashDisabled;
  disconnectBtn.disabled = !!state.disconnectDisabled;
  eraseAllEl.disabled = !!state.eraseDisabled;
}

function setStatus(type, message) {
  statusEl.className = "status";
  if (type) statusEl.classList.add(type);
  statusEl.textContent = message;
}

async function loadManifest() {
  if (firmwareManifest) return firmwareManifest;
  const res = await fetch("./manifest.json", { cache: "no-store" });
  if (!res.ok) throw new Error(`manifest.json の取得に失敗 (${res.status})`);
  firmwareManifest = await res.json();
  return firmwareManifest;
}

async function fetchFirmwareParts(manifest) {
  const build = manifest?.builds?.[0];
  if (!build?.parts?.length) throw new Error("manifest.json に builds[0].parts が見つかりません。");

  const fileArray = [];
  for (const part of build.parts) {
    const res = await fetch(part.path, { cache: "no-store" });
    if (!res.ok) throw new Error(`${part.path} の取得に失敗 (${res.status})`);
    const data = new Uint8Array(await res.arrayBuffer());
    fileArray.push({ data, address: part.offset });
    appendLog(`part 読み込み: ${part.path} (${data.length} bytes @ 0x${part.offset.toString(16)})`);
  }
  return fileArray;
}

async function connectDevice() {
  setButtons({ connectDisabled: true, flashDisabled: true, disconnectDisabled: true, eraseDisabled: true });
  try {
    appendLog("シリアルポート選択ダイアログを表示します。");
    port = await navigator.serial.requestPort();
    transport = new Transport(port, true);
    esploader = new ESPLoader({
      transport,
      baudrate: 115200,
      terminal: {
        clean() {},
        writeLine(data) { appendLog(data); },
        write(data) { appendLog(data); }
      }
    });

    const chip = await esploader.main("default_reset");
    appendLog(`接続成功: ${chip}`);
    setStatus("ok", `接続済み: ${chip}。書き込み開始を押してください。`);
    setButtons({ connectDisabled: true, flashDisabled: false, disconnectDisabled: false, eraseDisabled: false });
  } catch (err) {
    appendLog(`接続エラー: ${err?.message || err}`);
    setStatus("error", `接続に失敗しました: ${err?.message || err}`);
    await disconnectDevice(true);
  }
}

async function flashDevice() {
  if (!esploader) {
    setStatus("warn", "先に接続を実行してください。");
    return;
  }

  setButtons({ connectDisabled: true, flashDisabled: true, disconnectDisabled: true, eraseDisabled: true });
  try {
    const manifest = await loadManifest();
    appendLog(`manifest 読み込み: ${manifest.name || "(nameなし)"} v${manifest.version || "?"}`);
    const fileArray = await fetchFirmwareParts(manifest);

    await esploader.writeFlash({
      fileArray,
      flashMode: "dio",
      flashFreq: "40m",
      flashSize: "4MB",
      eraseAll: eraseAllEl.checked,
      compress: true,
      reportProgress: (fileIndex, written, total) => {
        const pct = Math.floor((written / total) * 100);
        setStatus("", `書き込み中: file ${fileIndex + 1}/${fileArray.length} ${pct}%`);
      }
    });

    appendLog("書き込み完了。ハードリセットします。");
    await esploader.after("hard_reset");
    appendLog("リセット後にシリアルポートを解放します。");
    try { await transport.disconnect(); } catch (_) {}
    port = null;
    transport = null;
    esploader = null;
    setStatus("ok", "書き込みが完了しました。デバイスを再起動しました。");
  } catch (err) {
    appendLog(`書き込みエラー: ${err?.message || err}`);
    setStatus("error", `書き込みに失敗しました: ${err?.message || err}`);
  } finally {
    setButtons({ connectDisabled: false, flashDisabled: true, disconnectDisabled: true, eraseDisabled: true });
  }
}

async function disconnectDevice(silent = false) {
  try {
    if (transport) await transport.disconnect();
  } catch (err) {
    if (!silent) appendLog(`切断時に警告: ${err?.message || err}`);
  }

  port = null;
  transport = null;
  esploader = null;

  setButtons({ connectDisabled: false, flashDisabled: true, disconnectDisabled: true, eraseDisabled: true });
  if (!silent) {
    appendLog("切断しました。");
    setStatus("warn", "デバイスを切断しました。再度接続してください。");
  }
}

if (!("serial" in navigator)) {
  setStatus("error", "このブラウザは WebSerial 非対応です。Chrome または Edge を使用してください。");
  setButtons({ connectDisabled: true, flashDisabled: true, disconnectDisabled: true, eraseDisabled: true });
} else if (location.protocol !== "https:" && location.hostname !== "localhost") {
  setStatus("warn", "WebSerialは HTTPS または localhost でのみ有効です。公開時はHTTPSを使用してください。");
  setButtons({ connectDisabled: true, flashDisabled: true, disconnectDisabled: true, eraseDisabled: true });
} else {
  setStatus("ok", "WebSerial 対応ブラウザです。接続して書き込みできます。");
  setButtons({ connectDisabled: false, flashDisabled: true, disconnectDisabled: true, eraseDisabled: true });
}

connectBtn.addEventListener("click", connectDevice);
flashBtn.addEventListener("click", flashDevice);
disconnectBtn.addEventListener("click", () => {
  disconnectDevice(false);
});

window.addEventListener("beforeunload", () => {
  if (transport) {
    transport.disconnect().catch(() => {});
  }
});

try {
  loadManifest().then((m) => {
    appendLog(`manifest 事前確認: ${m.name || "(nameなし)"}`);
  }).catch((err) => {
    appendLog(`manifest 事前確認エラー: ${err?.message || err}`);
  });
} catch (err) {
  appendLog(`初期化エラー: ${err?.message || err}`);
}
