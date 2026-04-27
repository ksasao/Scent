#!/usr/bin/env python3
"""Web realtime plotter for M5Atom/BME688 CSV stream.

Expected line format (5 data columns + 1 checksum):
index,temp,humidity,pressure,current,checksum

The checksum is CRC-8 (AUTOSAR polynomial 0x31) of all data characters (characters before the final comma).
This script:
- Reads serial CSV on Windows COM port and validates checksums
- Logs received lines to Python/logs/yyyyMMdd_HHmmss.csv
- Writes aggregated rows to Python/data/yyyyMMdd_HHmmss.csv on D9 timing
- Prepends current timestamp as first column in the log
- Serves browser UI with realtime chart
- Graph x-axis uses relative time (seconds from first sample)
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, List, Tuple

from flask import Flask, jsonify, render_template
import serial
from serial.tools import list_ports


Point = Tuple[float, float]


# CRC-8 lookup table (AUTOSAR polynomial 0x31)
CRC8_TABLE = [
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
]

def crc8(data: str) -> int:
    """Calculate CRC-8 (AUTOSAR polynomial 0x31) for given data string."""
    crc = 0
    for byte in data.encode('utf-8'):
        crc = CRC8_TABLE[crc ^ byte]
    return crc


def create_log_file() -> Path:
    return create_output_files()[0]


def create_output_files() -> Tuple[Path, Path]:
    base_dir = Path(__file__).resolve().parent
    log_dir = base_dir / "logs"
    data_dir = base_dir / "data"
    log_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    filename = datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
    data_file = data_dir / filename
    with data_file.open("w", encoding="utf-8", newline="") as f:
        f.write("date,temperature,humidity,pressure,d0,d1,d2,d3,d4,d5,d6,d7,d8,d9\n")
    return log_dir / filename, data_file


def now_text() -> str:
    return datetime.now().strftime("%Y/%m/%d %H:%M:%S.%f")[:-3]


def last_good_port_file() -> Path:
    return Path(__file__).resolve().parent / "last_good_port.txt"


def load_last_good_port() -> str | None:
    path = last_good_port_file()
    try:
        if not path.exists():
            return None
        port = path.read_text(encoding="utf-8").strip()
        return port or None
    except Exception:
        return None


def save_last_good_port(port: str) -> None:
    path = last_good_port_file()
    try:
        path.write_text(port, encoding="utf-8")
    except Exception:
        # Persistence failure should not interrupt acquisition.
        pass


class SharedState:
    def __init__(self, max_points: int) -> None:
        self.data: Dict[int, Deque[Point]] = defaultdict(lambda: deque(maxlen=max_points))
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.running = False
        self.error_message = ""
        self.log_file = ""
        self.data_file = ""
        self.baseline: Dict[int, float] | None = None
        self.reset_at: float | None = None
        self.reset_at_text: str | None = None
        self.ser_ref: serial.Serial | None = None
        self.id_event = threading.Event()
        self.id_response: str | None = None
        self.start_time: datetime | None = None  # First data reception time for relative time calculation
        self.requested_port: str | None = None  # Requested port to connect to
        self.port_change_event = threading.Event()  # Signal port change request
        self.last_rx_monotonic: float | None = None  # Last valid data reception time (monotonic)
        self.connected_monotonic: float | None = None  # Serial open time (monotonic)


def available_ports() -> List[str]:
    return [p.device for p in list_ports.comports()]


def parse_line(line: str) -> Tuple[int, float, float, float, float] | None:
    parts = line.strip().split(",")
    if len(parts) < 6:  # 5 data columns + 1 checksum
        return None

    try:
        channel = int(parts[0])
        temp = float(parts[1])
        humidity = float(parts[2])
        pressure = float(parts[3])
        current = float(parts[4])
        received_checksum = parts[5].upper()
    except (ValueError, IndexError):
        return None

    if not (0 <= channel <= 9):
        return None

    # Verify CRC-8 (AUTOSAR polynomial 0x31)
    data_str = ",".join(parts[:5])
    calculated_crc = crc8(data_str)
    
    # CRC should match (case-insensitive hex)
    if f"{calculated_crc:X}" != received_checksum:
        return None

    return channel, temp, humidity, pressure, current


def serial_reader(port: str | None, baudrate: int, state: SharedState) -> None:
    log_file, data_file = create_output_files()
    state.log_file = str(log_file)
    state.data_file = str(data_file)
    
    # Set initial port if provided
    if port:
        state.requested_port = port

    last_values: Dict[int, float] = {}
    d0_datetime = ""
    d0_temp: float | None = None
    d0_humidity: float | None = None
    d0_pressure: float | None = None
    
    retry_count = 0
    max_retries = 10
    base_retry_delay = 1.0  # seconds

    # Outer loop: reconnection loop
    while not state.stop_event.is_set():
        # Wait for requested port if not set
        current_port = state.requested_port
        if not current_port:
            time.sleep(0.5)
            continue
        
        try:
            state.running = True
            state.error_message = ""
            
            with serial.Serial(port=current_port, baudrate=baudrate, timeout=1) as ser:
                state.ser_ref = ser
                state.connected_monotonic = time.monotonic()
                state.last_rx_monotonic = None
                port_marked_good = False
                retry_count = 0  # Reset retry count on successful connection
                print(f"[{now_text()}] Connected to {current_port}")
                
                with log_file.open("a", encoding="utf-8", newline="") as log_fp, data_file.open("a", encoding="utf-8", newline="") as data_fp:
                    # Inner loop: data reading loop
                    while not state.stop_event.is_set():
                        try:
                            # Stop reading immediately when disconnect or port switch is requested.
                            if state.requested_port != current_port:
                                next_port = state.requested_port
                                if next_port is None:
                                    print(f"[{now_text()}] Disconnected from {current_port}")
                                else:
                                    print(f"[{now_text()}] Port switch requested: {current_port} -> {next_port}")
                                break

                            raw = ser.readline()
                            if not raw:
                                continue
                            line = raw.decode("utf-8", errors="ignore")
                            line_clean = line.strip()

                            # Handle ID response from Arduino
                            if line_clean.startswith("ID,"):
                                state.id_response = line_clean
                                state.id_event.set()
                                continue

                            parsed = parse_line(line)
                            if parsed is None:
                                continue

                            if line_clean:
                                log_fp.write(f"{now_text()},{line_clean}\n")
                                log_fp.flush()

                            channel, temp, humidity, pressure, value = parsed
                            state.last_rx_monotonic = time.monotonic()
                            if not port_marked_good:
                                save_last_good_port(current_port)
                                port_marked_good = True
                            
                            # Calculate relative time (seconds) from first data reception
                            now = datetime.now()
                            if state.start_time is None:
                                state.start_time = now
                            t_sec = (now - state.start_time).total_seconds()

                            last_values[channel] = value

                            if channel == 0:
                                d0_datetime = now_text()
                                d0_temp = temp
                                d0_humidity = humidity
                                d0_pressure = pressure

                            if (
                                channel == 9
                                and len(last_values) == 10
                                and d0_datetime
                                and d0_temp is not None
                                and d0_humidity is not None
                                and d0_pressure is not None
                            ):
                                # Emit one aggregated row when D9 arrives; missing channels
                                # in the current cycle are naturally filled by retained values.
                                row = [
                                    d0_datetime,
                                    f"{d0_temp:.2f}",
                                    f"{d0_humidity:.2f}",
                                    f"{d0_pressure:.2f}",
                                ] + [f"{last_values[d]:.3f}" for d in range(10)]
                                data_fp.write(",".join(row) + "\n")
                                data_fp.flush()

                            with state.lock:
                                state.data[channel].append((t_sec, value))
                        except Exception as read_exc:
                            print(f"[{now_text()}] Serial read error: {read_exc}")
                            state.error_message = f"Serial read error: {read_exc}"
                            raise  # Trigger reconnection
        except Exception as exc:
            state.ser_ref = None
            state.running = False
            
            # Handle reconnection logic
            if state.stop_event.is_set():
                break
                
            retry_count += 1
            if retry_count > max_retries:
                error_msg = f"Failed to connect after {max_retries} retries: {exc}"
                print(f"[{now_text()}] {error_msg}")
                state.error_message = error_msg
                state.running = False
                # Reset port and wait for user to select a new one
                state.requested_port = None
                retry_count = 0
                print(f"[{now_text()}] Waiting for new port selection...")
                time.sleep(1.0)
                continue
            
            # Exponential backoff with cap
            wait_time = min(base_retry_delay * (2 ** (retry_count - 1)), 30.0)
            print(f"[{now_text()}] Connection lost ({exc}). Retrying in {wait_time:.1f}s (attempt {retry_count}/{max_retries})...")
            state.error_message = f"Reconnecting... (attempt {retry_count}/{max_retries})"
            
            time.sleep(wait_time)
        finally:
            state.ser_ref = None
            state.running = False
            state.connected_monotonic = None


def create_app(state: SharedState, update_ms: int) -> Flask:
    template_dir = Path(__file__).resolve().parent / "templates"
    app = Flask(__name__, template_folder=str(template_dir))

    @app.get("/")
    def index():
        return render_template("index.html", update_ms=update_ms)

    @app.get("/data")
    def data_api():
        now_mono = time.monotonic()
        comm_timeout_s = 6.0
        connect_grace_s = 6.0
        with state.lock:
            if state.baseline is None or state.reset_at is None:
                channels = {
                    str(ch): [{"x": x, "y": y} for (x, y) in state.data[ch]]
                    for ch in range(10)
                }
                mode = "raw"
            else:
                channels = {}
                for ch in range(10):
                    base = state.baseline.get(ch)
                    if base is None:
                        channels[str(ch)] = []
                        continue
                    channels[str(ch)] = [
                        {"x": x - state.reset_at, "y": y - base}
                        for (x, y) in state.data[ch]
                        if x >= state.reset_at
                    ]
                mode = "delta"
            reset_at_text = state.reset_at_text
            running = state.running
            last_rx = state.last_rx_monotonic
            connected_at = state.connected_monotonic
        if state.error_message:
            status = f"error: {state.error_message}"
        elif state.running:
            status = "running"
        else:
            status = "stopped"

        # Communication is healthy when serial is running and data is recent.
        # During connection warm-up, keep it healthy for a short grace period.
        if not running:
            comm_ok = False
        elif last_rx is not None:
            comm_ok = (now_mono - last_rx) <= comm_timeout_s
        elif connected_at is not None:
            comm_ok = (now_mono - connected_at) <= connect_grace_s
        else:
            comm_ok = False

        return jsonify(
            {
                "serial_port": state.requested_port or "-",
                "log_file": state.log_file,
                "status": status,
                "running": running,
                "comm_ok": comm_ok,
                "mode": mode,
                "reset_at": reset_at_text,
                "channels": channels,
            }
        )

    @app.get("/id")
    def id_api():
        ser = state.ser_ref
        if ser is None or not state.running:
            return jsonify({"ok": False, "message": "Serial not connected"}), 503
        state.id_response = None
        state.id_event.clear()
        try:
            ser.write(b"id\n")
        except Exception as exc:
            return jsonify({"ok": False, "message": str(exc)}), 500
        if state.id_event.wait(timeout=3.0):
            parts = (state.id_response or "").split(",", 1)
            uid = parts[1] if len(parts) == 2 else ""
            return jsonify({"ok": True, "id": uid})
        return jsonify({"ok": False, "message": "Timeout waiting for response"}), 504

    @app.post("/reset")
    def reset_api():
        with state.lock:
            baseline: Dict[int, float] = {}
            latest_x = 0.0
            has_any = False

            for ch in range(10):
                if not state.data[ch]:
                    continue
                x, y = state.data[ch][-1]
                baseline[ch] = y
                latest_x = max(latest_x, x)
                has_any = True

            if not has_any:
                state.baseline = None
                state.reset_at = None
                state.reset_at_text = None
                return jsonify({"ok": False, "message": "No data yet"}), 400

            state.baseline = baseline
            state.reset_at = latest_x
            state.reset_at_text = now_text()

        return jsonify({"ok": True, "reset_at": state.reset_at_text})

    @app.get("/api/ports")
    def api_ports():
        """Return list of available COM ports"""
        try:
            ports = available_ports()
            return jsonify({"ok": True, "ports": ports, "current": state.requested_port})
        except Exception as exc:
            return jsonify({"ok": False, "message": str(exc)}), 500

    @app.post("/api/connect/<port>")
    def api_connect(port: str):
        """Connect to specified COM port"""
        # Validate port is in available ports
        available = available_ports()
        if port not in available:
            return jsonify({"ok": False, "message": f"Port {port} not available"}), 400
        
        state.requested_port = port
        print(f"[{now_text()}] Connection requested to {port}")
        return jsonify({"ok": True, "message": f"Connecting to {port}"})

    @app.post("/api/disconnect")
    def api_disconnect():
        """Disconnect from current COM port"""
        state.requested_port = None
        ser = state.ser_ref
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
        print(f"[{now_text()}] Disconnection requested")
        return jsonify({"ok": True, "message": "Disconnecting"})

    return app


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Web realtime plotter for M5Atom/BME688 CSV serial data")
    parser.add_argument("--port", type=str, help="COM port name, e.g. COM3")
    parser.add_argument("--baudrate", type=int, default=115200, help="Serial baudrate (default: 115200)")
    parser.add_argument("--max-points", type=int, default=2000, help="Max points to keep per channel")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Web server host (default: 127.0.0.1)")
    parser.add_argument("--web-port", type=int, default=5000, help="Web server port (default: 5000)")
    parser.add_argument("--update-ms", type=int, default=500, help="Browser update interval in ms")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    serial_port = args.port
    if serial_port is None:
        remembered = load_last_good_port()
        if remembered and remembered in available_ports():
            serial_port = remembered
            print(f"[{now_text()}] Auto-selected last good port: {serial_port}")
        else:
            print(f"[{now_text()}] No startup port selected. Please choose a COM port from the Web UI.")

    state = SharedState(max_points=args.max_points)
    reader = threading.Thread(
        target=serial_reader,
        args=(serial_port, args.baudrate, state),
        daemon=True,
    )
    reader.start()

    app = create_app(state=state, update_ms=args.update_ms)
    serial_text = serial_port if serial_port else "(not selected)"
    print(f"Serial: {serial_text} @ {args.baudrate} bps")
    print(f"Web UI: http://{args.host}:{args.web_port}")
    print("Press Ctrl+C to stop.")

    try:
        app.run(host=args.host, port=args.web_port, debug=False, use_reloader=False)
    finally:
        state.stop_event.set()
        reader.join(timeout=2)


if __name__ == "__main__":
    main()
