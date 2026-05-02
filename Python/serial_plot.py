#!/usr/bin/env python3
"""Entry point for the Scent web serial plotter."""

from __future__ import annotations

import argparse

from scent_web.runtime import RuntimeOptions, create_runtime, stop_runtime


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

    runtime = create_runtime(
        RuntimeOptions(
            port=args.port,
            baudrate=args.baudrate,
            max_points=args.max_points,
            update_ms=args.update_ms,
        )
    )

    serial_text = runtime.serial_port if runtime.serial_port else "(not selected)"
    print(f"Serial: {serial_text} @ {runtime.baudrate} bps")
    print(f"Web UI: http://{args.host}:{args.web_port}")
    print("Press Ctrl+C to stop.")

    try:
        runtime.app.run(host=args.host, port=args.web_port, debug=False, use_reloader=False)
    finally:
        stop_runtime(runtime)


if __name__ == "__main__":
    main()
