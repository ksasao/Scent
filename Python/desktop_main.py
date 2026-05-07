#!/usr/bin/env python3
"""Desktop entry point for the Scent embedded WebView app."""

from __future__ import annotations

import argparse
import ctypes
import platform
import socket
import subprocess
import sys
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


def show_dependency_message(title: str, message: str) -> None:
    """Show dependency guidance in a native dialog on Windows."""
    if platform.system() == "Windows":
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x00000010)
    else:
        print(f"{title}\n{message}", file=sys.stderr)


def has_webview2_runtime() -> bool:
    """Return True when Microsoft Edge WebView2 Runtime appears installed."""
    if platform.system() != "Windows":
        return True

    client_guid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    keys = (
        fr"HKLM\SOFTWARE\Microsoft\EdgeUpdate\Clients\{client_guid}",
        fr"HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{client_guid}",
        fr"HKCU\SOFTWARE\Microsoft\EdgeUpdate\Clients\{client_guid}",
    )
    for key in keys:
        result = subprocess.run(
            ["reg", "query", key, "/v", "pv"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and "pv" in result.stdout:
            return True
    return False


def get_pythonnet_error() -> str | None:
    """Return an error message when pythonnet/.NET runtime cannot initialize."""
    try:
        import clr  # type: ignore # noqa: F401
    except Exception as exc:  # pragma: no cover - depends on local runtime state
        return f"{type(exc).__name__}: {exc}"
    return None


def require_desktop_dependencies() -> None:
    """Ensure required desktop runtime dependencies are present."""
    missing_runtime_messages: list[str] = []

    if not has_webview2_runtime():
        missing_runtime_messages.append("- Microsoft Edge WebView2 Runtime")

    pythonnet_error = get_pythonnet_error()
    if pythonnet_error is not None:
        missing_runtime_messages.append("- .NET Desktop Runtime 8 (x64)")

    if not missing_runtime_messages:
        return

    show_dependency_message(
        "Missing Runtime Dependencies",
        "This app cannot initialize desktop dependencies.\n\n"
        "Please install/update the following and start the app again:\n"
        + "\n".join(missing_runtime_messages)
        + "\n\nDownload:\n"
        "WebView2: https://developer.microsoft.com/microsoft-edge/webview2/\n"
        ".NET 8 Desktop Runtime: https://dotnet.microsoft.com/download/dotnet/8.0/runtime"
        + (f"\n\nTechnical detail:\n{pythonnet_error}" if pythonnet_error else ""),
    )
    raise SystemExit(1)


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    require_desktop_dependencies()

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
    except Exception as exc:
        show_dependency_message(
            "Failed To Start Desktop UI",
            "Failed to initialize desktop WebView.\n\n"
            "Please verify these runtimes are installed:\n"
            "- Microsoft Edge WebView2 Runtime\n"
            "- .NET Desktop Runtime 8 (x64)\n\n"
            "WebView2: https://developer.microsoft.com/microsoft-edge/webview2/\n"
            ".NET 8 Desktop Runtime: https://dotnet.microsoft.com/download/dotnet/8.0/runtime\n\n"
            f"Error: {exc}",
        )
        raise
    finally:
        server.stop()
        stop_runtime(runtime)


if __name__ == "__main__":
    main()