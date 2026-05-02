#!/usr/bin/env python3
"""Desktop entry point for the Scent embedded WebView app."""

from __future__ import annotations

import argparse
import socket
import threading
import time

import webview
from waitress.server import create_server

from scent_web.runtime import RuntimeOptions, create_runtime, stop_runtime


class WaitressThread:
    def __init__(self, app, host: str, port: int) -> None:
        self._server = create_server(app, host=host, port=port, threads=4)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.close()
        self._thread.join(timeout=2)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Desktop realtime plotter for M5Atom/BME688 CSV serial data")
    parser.add_argument("--port", type=str, help="COM port name, e.g. COM3")
    parser.add_argument("--baudrate", type=int, default=115200, help="Serial baudrate (default: 115200)")
    parser.add_argument("--max-points", type=int, default=2000, help="Max points to keep per channel")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Embedded web server host (default: 127.0.0.1)")
    parser.add_argument("--web-port", type=int, default=0, help="Embedded web server port (default: auto)")
    parser.add_argument("--update-ms", type=int, default=500, help="UI update interval in ms")
    parser.add_argument("--window-title", type=str, default="Scent", help="Desktop window title")
    parser.add_argument("--window-width", type=int, default=1360, help="Initial window width")
    parser.add_argument("--window-height", type=int, default=920, help="Initial window height")
    return parser


def reserve_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def wait_for_server(host: str, port: int, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.25)
            if sock.connect_ex((host, port)) == 0:
                return
        time.sleep(0.1)
    raise RuntimeError(f"Embedded server did not start within {timeout_s:.1f}s")


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

    server_port = args.web_port or reserve_port(args.host)
    server = WaitressThread(runtime.app, args.host, server_port)
    url = f"http://{args.host}:{server_port}"

    serial_text = runtime.serial_port if runtime.serial_port else "(not selected)"
    print(f"Serial: {serial_text} @ {runtime.baudrate} bps")
    print(f"Embedded UI: {url}")

    try:
        server.start()
        wait_for_server(args.host, server_port)
        webview.create_window(
            args.window_title,
            url,
            width=args.window_width,
            height=args.window_height,
            min_size=(980, 700),
        )
        webview.start()
    finally:
        server.stop()
        stop_runtime(runtime)


if __name__ == "__main__":
    main()