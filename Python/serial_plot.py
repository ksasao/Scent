#!/usr/bin/env python3
"""Entry point for the Scent web serial plotter."""

from __future__ import annotations

import argparse
import threading

from scent_web.serial_worker import serial_reader
from scent_web.state import SharedState
from scent_web.utils import available_ports, load_last_good_port, now_text
from scent_web.web_app import create_app


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
