#!/usr/bin/env python3
"""Web realtime plotter for M5Atom/BME688 CSV stream.

Expected line format (6 columns):
index,time,temp,humidity,pressure,current

This script:
- Reads serial CSV on Windows COM port
- Logs received lines to Python/logs/yyyyMMdd_HHmmss.csv
- Writes aggregated rows to Python/data/yyyyMMdd_HHmmss.csv on D9 timing
- Prepends current timestamp as first column in the log
- Serves browser UI with realtime chart
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import threading
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


def parse_line(line: str) -> Tuple[int, float, float, float, float, float] | None:
    parts = line.strip().split(",")
    if len(parts) < 6:
        return None

    try:
        channel = int(parts[0])
        t_ms = float(parts[1])
        temp = float(parts[2])
        humidity = float(parts[3])
        pressure = float(parts[4])
        current = float(parts[5])
    except ValueError:
        return None

    if not (0 <= channel <= 9):
        return None

    return channel, t_ms, temp, humidity, pressure, current


def serial_reader(port: str, baudrate: int, state: SharedState) -> None:
    base_ms: float | None = None
    log_file, data_file = create_output_files()
    state.log_file = str(log_file)
    state.data_file = str(data_file)

    last_values: Dict[int, float] = {}
    d0_datetime = ""
    d0_temp: float | None = None
    d0_humidity: float | None = None
    d0_pressure: float | None = None

    try:
        with serial.Serial(port=port, baudrate=baudrate, timeout=1) as ser:
            state.running = True
            with log_file.open("a", encoding="utf-8", newline="") as log_fp, data_file.open("a", encoding="utf-8", newline="") as data_fp:
                while not state.stop_event.is_set():
                    raw = ser.readline()
                    if not raw:
                        continue
                    line = raw.decode("utf-8", errors="ignore")
                    parsed = parse_line(line)
                    if parsed is None:
                        continue

                    line_clean = line.strip()
                    if line_clean:
                        log_fp.write(f"{now_text()},{line_clean}\n")
                        log_fp.flush()

                    channel, t_ms, temp, humidity, pressure, value = parsed
                    if base_ms is None:
                        base_ms = t_ms
                    t_sec = (t_ms - base_ms) / 1000.0

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
    except Exception as exc:
        state.error_message = str(exc)
    finally:
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
