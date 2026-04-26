#!/usr/bin/env python3
"""Web realtime plotter for M5Atom/BME688 CSV stream.

Expected line format (5 data columns + 1 checksum):
index,temp,humidity,pressure,current,checksum

The checksum is an XOR of all data characters (characters before the final comma).
This script:
- Reads serial CSV on Windows COM port and validates checksums
- Logs received lines to Python/logs/yyyyMMdd_HHmmss.csv
- Writes aggregated rows to Python/data/yyyyMMdd_HHmmss.csv on D9 timing
- Prepends current timestamp as first column in the log
- Serves browser UI with realtime chart
- Graph x-axis uses sequential counter (sample index)
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


def available_ports() -> List[str]:
    return [p.device for p in list_ports.comports()]


def select_port_interactive() -> str:
    ports = available_ports()
    if not ports:
        raise RuntimeError("No serial ports found.")

    print("Available COM ports:")
    for i, p in enumerate(ports, start=1):
        print(f"  {i}: {p}")

    while True:
        choice = input("Select port number: ").strip()
        if not choice.isdigit():
            print("Please enter a number.")
            continue
        idx = int(choice)
        if 1 <= idx <= len(ports):
            return ports[idx - 1]
        print("Out of range.")


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

    # Verify checksum: XOR of all data characters
    data_str = ",".join(parts[:5])
    calculated_checksum = 0
    for c in data_str:
        calculated_checksum ^= ord(c)
    
    # Checksum should match (case-insensitive hex)
    if f"{calculated_checksum:X}" != received_checksum:
        return None

    return channel, temp, humidity, pressure, current


def serial_reader(port: str, baudrate: int, state: SharedState) -> None:
    log_file, data_file = create_output_files()
    state.log_file = str(log_file)
    state.data_file = str(data_file)

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
        try:
            state.running = True
            state.error_message = ""
            
            with serial.Serial(port=port, baudrate=baudrate, timeout=1) as ser:
                state.ser_ref = ser
                retry_count = 0  # Reset retry count on successful connection
                print(f"[{now_text()}] Connected to {port}")
                
                with log_file.open("a", encoding="utf-8", newline="") as log_fp, data_file.open("a", encoding="utf-8", newline="") as data_fp:
                    # Inner loop: data reading loop
                    while not state.stop_event.is_set():
                        try:
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
                break
            
            # Exponential backoff with cap
            wait_time = min(base_retry_delay * (2 ** (retry_count - 1)), 30.0)
            print(f"[{now_text()}] Connection lost ({exc}). Retrying in {wait_time:.1f}s (attempt {retry_count}/{max_retries})...")
            state.error_message = f"Reconnecting... (attempt {retry_count}/{max_retries})"
            
            time.sleep(wait_time)
        finally:
            state.ser_ref = None
            state.running = False


def create_app(state: SharedState, serial_port: str, update_ms: int) -> Flask:
    template_dir = Path(__file__).resolve().parent / "templates"
    app = Flask(__name__, template_folder=str(template_dir))

    @app.get("/")
    def index():
        return render_template("index.html", update_ms=update_ms)

    @app.get("/data")
    def data_api():
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
        if state.error_message:
            status = f"error: {state.error_message}"
        elif state.running:
            status = "running"
        else:
            status = "stopped"

        return jsonify(
            {
                "serial_port": serial_port,
                "log_file": state.log_file,
                "status": status,
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

    serial_port = args.port or select_port_interactive()

    state = SharedState(max_points=args.max_points)
    reader = threading.Thread(
        target=serial_reader,
        args=(serial_port, args.baudrate, state),
        daemon=True,
    )
    reader.start()

    app = create_app(state=state, serial_port=serial_port, update_ms=args.update_ms)
    print(f"Serial: {serial_port} @ {args.baudrate} bps")
    print(f"Web UI: http://{args.host}:{args.web_port}")
    print("Press Ctrl+C to stop.")

    try:
        app.run(host=args.host, port=args.web_port, debug=False, use_reloader=False)
    finally:
        state.stop_event.set()
        reader.join(timeout=2)


if __name__ == "__main__":
    main()
