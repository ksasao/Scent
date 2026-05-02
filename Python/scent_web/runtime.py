"""Reusable runtime bootstrap for CLI and desktop launchers."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from flask import Flask

from .serial_worker import serial_reader
from .state import SharedState
from .utils import available_ports, load_last_good_port, now_text
from .web_app import create_app


@dataclass(slots=True)
class RuntimeOptions:
    port: str | None
    baudrate: int
    max_points: int
    update_ms: int


@dataclass(slots=True)
class RuntimeContext:
    app: Flask
    state: SharedState
    reader: threading.Thread
    serial_port: str | None
    baudrate: int


def resolve_startup_port(port: str | None) -> str | None:
    if port is not None:
        return port

    remembered = load_last_good_port()
    if remembered and remembered in available_ports():
        print(f"[{now_text()}] Auto-selected last good port: {remembered}")
        return remembered

    print(f"[{now_text()}] No startup port selected. Please choose a COM port from the UI.")
    return None


def create_runtime(options: RuntimeOptions) -> RuntimeContext:
    serial_port = resolve_startup_port(options.port)
    state = SharedState(max_points=options.max_points)
    reader = threading.Thread(
        target=serial_reader,
        args=(serial_port, options.baudrate, state),
        daemon=True,
    )
    reader.start()

    app = create_app(state=state, update_ms=options.update_ms)
    return RuntimeContext(
        app=app,
        state=state,
        reader=reader,
        serial_port=serial_port,
        baudrate=options.baudrate,
    )


def stop_runtime(runtime: RuntimeContext) -> None:
    runtime.state.stop_event.set()
    runtime.reader.join(timeout=2)