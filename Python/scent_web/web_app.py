"""Flask app factory and API routes."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Dict

from flask import Flask, jsonify, render_template

from .config import COMM_TIMEOUT_S, CONNECT_GRACE_S
from .state import SharedState
from .utils import available_ports, now_text


def create_app(state: SharedState, update_ms: int) -> Flask:
    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    template_dir = base_dir / "templates"
    static_dir = base_dir / "static"
    app = Flask(
        __name__,
        template_folder=str(template_dir),
        static_folder=str(static_dir),
        static_url_path="/static",
    )

    @app.get("/")
    def index():
        return render_template("index.html", update_ms=update_ms)

    @app.get("/data")
    def data_api():
        now_mono = time.monotonic()
        comm_timeout_s = COMM_TIMEOUT_S
        connect_grace_s = CONNECT_GRACE_S
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
        try:
            ports = available_ports()
            return jsonify({"ok": True, "ports": ports, "current": state.requested_port})
        except Exception as exc:
            return jsonify({"ok": False, "message": str(exc)}), 500

    @app.post("/api/connect/<port>")
    def api_connect(port: str):
        available = available_ports()
        if port not in available:
            return jsonify({"ok": False, "message": f"Port {port} not available"}), 400

        state.requested_port = port
        print(f"[{now_text()}] Connection requested to {port}")
        return jsonify({"ok": True, "message": f"Connecting to {port}"})

    @app.post("/api/disconnect")
    def api_disconnect():
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
