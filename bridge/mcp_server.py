#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
import uvicorn


BRIDGE_URL = os.getenv("SCENT_BRIDGE_URL", "http://127.0.0.1:8001").rstrip("/")
DEFAULT_WAIT_SECONDS = float(os.getenv("SCENT_COMMAND_WAIT_SECONDS", "12"))
DEFAULT_DOWNLOAD_DIR = Path(os.getenv("SCENT_MCP_DOWNLOAD_DIR", str(Path(__file__).resolve().parent / "downloads")))
MCP_HOST = os.getenv("SCENT_MCP_HOST", "127.0.0.1")
try:
    MCP_PORT = int(os.getenv("SCENT_MCP_PORT", "8002"))
except ValueError:
    MCP_PORT = 8002
MCP_TRANSPORT = os.getenv("SCENT_MCP_TRANSPORT", "streamable-http")


class BridgeClient:
    def __init__(self, bridge_url: str):
        self.bridge_url = bridge_url.rstrip("/")

    def request_json(
        self,
        path: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        data = None
        headers: dict[str, str] = {}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        url = f"{self.bridge_url}{path}"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)

    def request_binary(self, path: str, timeout: float = 60.0) -> tuple[bytes, dict[str, str]]:
        url = f"{self.bridge_url}{path}"
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(), dict(response.headers.items())

    def health(self) -> dict[str, Any]:
        return self.request_json("/health")

    def sessions(self) -> dict[str, Any]:
        return self.request_json("/sessions")

    def command_history(self, limit: int = 100) -> dict[str, Any]:
        return self.request_json(f"/commands/history?limit={max(limit, 1)}")

    def enqueue_command(self, command_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request_json(
            "/commands",
            method="POST",
            payload={"type": command_type, "payload": payload or {}},
        )

    def wait_for_command_result(self, command_id: str, timeout_seconds: float = DEFAULT_WAIT_SECONDS) -> dict[str, Any] | None:
        deadline = time.time() + max(timeout_seconds, 0.5)
        while time.time() < deadline:
            history = self.command_history(limit=200).get("history", [])
            if isinstance(history, list):
                for command in history:
                    if not isinstance(command, dict):
                        continue
                    if command.get("id") != command_id:
                        continue
                    if command.get("executed"):
                        result = command.get("result")
                        return result if isinstance(result, dict) else {"result": result}
            time.sleep(0.25)
        return None

    def download_session_zip(self, session_id: str, output_dir: Path | None = None) -> Path:
        target_dir = output_dir or DEFAULT_DOWNLOAD_DIR
        target_dir.mkdir(parents=True, exist_ok=True)

        encoded = urllib.parse.quote(session_id)
        body, headers = self.request_binary(f"/sessions/{encoded}/download")
        disposition = headers.get("Content-Disposition", "")
        match = __import__("re").search(r'filename="([^"]+)"', disposition)
        filename = match.group(1) if match else f"{session_id}.zip"
        path = target_dir / filename
        path.write_bytes(body)
        return path


def _extract_device_id(result: dict[str, Any]) -> str | None:
    for key in ("sensorId", "deviceId", "sensor_id", "device_id"):
        value = result.get(key)
        if isinstance(value, str) and value.strip() and value.strip() != "-":
            return value.strip()
    return None


client = BridgeClient(BRIDGE_URL)
mcp = FastMCP("scent-bridge-local")


@mcp.tool()
def bridge_health() -> dict[str, Any]:
    """Bridgeのヘルス状態を返します。"""
    try:
        return client.health()
    except Exception as exc:
        return {"success": False, "error": f"bridge_health failed: {exc}"}


@mcp.tool()
def sessions_list() -> dict[str, Any]:
    """Bridgeが保持しているセッション一覧を返します。"""
    try:
        return client.sessions()
    except Exception as exc:
        return {"success": False, "error": f"sessions_list failed: {exc}", "total": 0, "sessions": []}


@mcp.tool()
def device_connect(wait_result: bool = True, timeout_seconds: float = DEFAULT_WAIT_SECONDS) -> dict[str, Any]:
    """Viewerへデバイス接続コマンドを送ります。"""
    try:
        queued = client.enqueue_command("connect_device")
        command_id = queued.get("command", {}).get("id")
        if not wait_result or not command_id:
            return {"success": True, "queued": queued}
        result = client.wait_for_command_result(command_id, timeout_seconds)
        return {"success": bool(result and result.get("success", False)), "command_id": command_id, "result": result}
    except Exception as exc:
        return {"success": False, "error": f"device_connect failed: {exc}"}


@mcp.tool()
def device_disconnect(wait_result: bool = True, timeout_seconds: float = DEFAULT_WAIT_SECONDS) -> dict[str, Any]:
    """Viewerへデバイス切断コマンドを送ります。"""
    try:
        queued = client.enqueue_command("disconnect_device")
        command_id = queued.get("command", {}).get("id")
        if not wait_result or not command_id:
            return {"success": True, "queued": queued}
        result = client.wait_for_command_result(command_id, timeout_seconds)
        return {"success": bool(result and result.get("success", False)), "command_id": command_id, "result": result}
    except Exception as exc:
        return {"success": False, "error": f"device_disconnect failed: {exc}"}


@mcp.tool()
def session_start(name: str = "", wait_result: bool = True, timeout_seconds: float = DEFAULT_WAIT_SECONDS) -> dict[str, Any]:
    """Viewerへセッション開始コマンドを送ります。nameは任意です。"""
    try:
        normalized_name = name.strip() if isinstance(name, str) else ""
        payload = {"name": normalized_name} if normalized_name else {}
        queued = client.enqueue_command("start_session", payload)
        command_id = queued.get("command", {}).get("id")
        if not wait_result or not command_id:
            return {"success": True, "queued": queued}
        result = client.wait_for_command_result(command_id, timeout_seconds)
        return {"success": bool(result and result.get("success", False)), "command_id": command_id, "result": result}
    except Exception as exc:
        return {"success": False, "error": f"session_start failed: {exc}"}


@mcp.tool()
def session_stop(wait_result: bool = True, timeout_seconds: float = DEFAULT_WAIT_SECONDS) -> dict[str, Any]:
    """Viewerへセッション終了コマンドを送ります。"""
    try:
        queued = client.enqueue_command("stop_session")
        command_id = queued.get("command", {}).get("id")
        if not wait_result or not command_id:
            return {"success": True, "queued": queued}
        result = client.wait_for_command_result(command_id, timeout_seconds)
        return {"success": bool(result and result.get("success", False)), "command_id": command_id, "result": result}
    except Exception as exc:
        return {"success": False, "error": f"session_stop failed: {exc}"}


@mcp.tool()
def device_id_get_live(timeout_seconds: float = DEFAULT_WAIT_SECONDS) -> dict[str, Any]:
    """都度ブラウザ経由でデバイスIDを問い合わせて返します。"""
    try:
        queued = client.enqueue_command("query_device_id")
        command_id = queued.get("command", {}).get("id")
        if not command_id:
            return {"success": False, "error": "command_id was not returned"}

        result = client.wait_for_command_result(command_id, timeout_seconds)
        if not isinstance(result, dict):
            return {"success": False, "command_id": command_id, "error": "timeout waiting for command result"}

        device_id = _extract_device_id(result)
        if not device_id:
            return {
                "success": False,
                "command_id": command_id,
                "error": result.get("error") or "device id not available",
                "result": result,
            }

        return {"success": True, "command_id": command_id, "device_id": device_id, "result": result}
    except Exception as exc:
        return {"success": False, "error": f"device_id_get_live failed: {exc}"}


@mcp.tool()
def session_download(session_id: str, output_dir: str = "") -> dict[str, Any]:
    """指定session_idのZIPをローカル保存します。"""
    if not session_id or not session_id.strip():
        return {"success": False, "error": "session_id is required"}
    try:
        normalized_output_dir = output_dir.strip() if isinstance(output_dir, str) else ""
        target = Path(normalized_output_dir).expanduser() if normalized_output_dir else DEFAULT_DOWNLOAD_DIR
        file_path = client.download_session_zip(session_id.strip(), target)
        return {"success": True, "session_id": session_id.strip(), "file_path": str(file_path)}
    except urllib.error.HTTPError as exc:
        return {"success": False, "error": f"session_download failed: HTTP {exc.code}", "session_id": session_id.strip()}
    except Exception as exc:
        return {"success": False, "error": f"session_download failed: {exc}", "session_id": session_id.strip()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Scent MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default=MCP_TRANSPORT,
        help="MCP transport (default: env SCENT_MCP_TRANSPORT or streamable-http)",
    )
    parser.add_argument("--host", default=MCP_HOST, help="Bind host for HTTP transports")
    parser.add_argument("--port", type=int, default=MCP_PORT, help="Bind port for HTTP transports")
    parser.add_argument(
        "--force-kill-port-owner",
        action="store_true",
        help="On Windows, kill process(es) listening on --host:--port before startup",
    )
    return parser.parse_args()


def _find_windows_listening_pids(host: str, port: int) -> list[int]:
    try:
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception:
        return []

    pids: list[int] = []
    pattern = re.compile(r"\s*TCP\s+(\S+)\s+(\S+)\s+LISTENING\s+(\d+)\s*$", re.IGNORECASE)
    host_lower = host.lower()
    target_suffix = f":{port}"

    for line in completed.stdout.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        local_addr = match.group(1).lower()
        pid_text = match.group(3)
        if not local_addr.endswith(target_suffix):
            continue
        if host_lower not in ("0.0.0.0", "::"):
            local_host = local_addr.rsplit(":", 1)[0]
            if local_host not in (host_lower, "0.0.0.0", "::", "[::]"):
                continue
        try:
            pids.append(int(pid_text))
        except ValueError:
            continue

    return sorted(set(pids))


def _kill_windows_pids(pids: list[int]) -> None:
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False)


def main() -> None:
    args = parse_args()
    if args.transport != "stdio" and args.force_kill_port_owner and os.name == "nt":
        pids = _find_windows_listening_pids(args.host, args.port)
        if pids:
            print(f"[mcp_server] Port {args.host}:{args.port} is in use by PID(s): {pids}. Killing them...")
            _kill_windows_pids(pids)
            time.sleep(0.5)

    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return

    try:
        if args.transport == "streamable-http":
            app = mcp.streamable_http_app()
        else:
            app = mcp.sse_app()
        uvicorn.run(app, host=args.host, port=args.port)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 10048 and os.name == "nt":
            pids = _find_windows_listening_pids(args.host, args.port)
            if pids:
                print(f"[mcp_server] Bind failed on {args.host}:{args.port}. Listening PID(s): {pids}")
                print("[mcp_server] Retry with --force-kill-port-owner or stop those PID(s) manually.")
        raise


if __name__ == "__main__":
    main()
