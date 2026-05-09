#!/usr/bin/env python3
"""Scent Agent

A minimal local AI agent that queries the Scent Bridge for device state.
It can ask the bridge whether the device is currently receiving data and
prints the returned result in a human-friendly format.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_BRIDGE_URL = "http://127.0.0.1:8001"
DEFAULT_PROMPT = "現在デバイスからデータを受信中かどうかを確認して"
DOWNLOAD_DIR = Path.cwd() / "downloads"


@dataclass
class AgentResponse:
    prompt: str
    handled_locally: bool
    answer: str
    details: str | None
    raw: dict[str, Any]


@dataclass
class SessionSummary:
    index: int
    session_id: str
    name: str
    sensor_id: str | None
    start_iso: str
    end_iso: str | None
    records_count: int
    running: bool


def request_json(url: str, method: str = "GET", payload: dict[str, Any] | None = None, timeout: float = 60.0) -> dict[str, Any]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        return json.loads(body)


def request_binary(url: str, method: str = "GET", timeout: float = 60.0) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), dict(response.headers.items())


def query_bridge(bridge_url: str, prompt: str) -> AgentResponse:
    response = request_json(f"{bridge_url.rstrip('/')}/agent/query", method="POST", payload={"prompt": prompt})
    result = response.get("result", {})
    return AgentResponse(
        prompt=response.get("prompt", prompt),
        handled_locally=bool(response.get("handled_locally", False)),
        answer=str(result.get("answer", "")),
        details=result.get("details"),
        raw=response,
    )


def format_response(result: AgentResponse) -> str:
    lines = [
        f"Prompt: {result.prompt}",
        f"Handled locally: {'yes' if result.handled_locally else 'no'}",
        f"Answer: {result.answer}",
    ]
    if result.details:
        lines.append(f"Details: {result.details}")
    return "\n".join(lines)


def format_session_list(sessions: list[dict[str, Any]]) -> str:
    if not sessions:
        return "セッションはまだありません。"

    lines = ["セッション一覧:"]
    for session in sessions:
        index = session.get("index", "-")
        session_id = session.get("session_id", "")
        name = session.get("name") or "(nameなし)"
        start_iso = session.get("start_iso", "")
        end_iso = session.get("end_iso") or "running"
        records_count = session.get("records_count", 0)
        lines.append(f"{index}. {name} | session_id={session_id} | start={start_iso} | end={end_iso} | records={records_count}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query the Scent Bridge from a local AI agent.")
    parser.add_argument("prompt", nargs="*", help="Prompt to send to the bridge")
    parser.add_argument("--bridge-url", default=DEFAULT_BRIDGE_URL, help=f"Bridge base URL (default: {DEFAULT_BRIDGE_URL})")
    parser.add_argument("--json", action="store_true", help="Print the raw JSON response")
    parser.add_argument("--status", action="store_true", help="Ask whether the device is currently receiving data")
    parser.add_argument("--interactive", action="store_true", help="Run interactive prompt mode")
    return parser


def resolve_prompt(args: argparse.Namespace) -> str:
    if args.status:
        return DEFAULT_PROMPT
    if args.prompt:
        return " ".join(args.prompt).strip()
    return ""


def normalize_prompt(prompt: str) -> str:
    return (prompt or "").strip()


def is_session_list_prompt(prompt: str) -> bool:
    text = normalize_prompt(prompt)
    return bool(re.search(r"セッション.*一覧|一覧.*セッション|session.*list|list.*session", text, re.IGNORECASE))


def is_device_id_prompt(prompt: str) -> bool:
    text = normalize_prompt(prompt)
    return bool(re.search(r"デバイス\s*ID|device\s*id|現在のデバイスID|現在の\s*デバイス\s*ID", text, re.IGNORECASE))


def parse_nth_session(prompt: str) -> int | None:
    text = normalize_prompt(prompt)
    match = re.search(r"(\d+)\s*(?:番目|件目|th|st|nd|rd)?", text, re.IGNORECASE)
    if match:
        value = int(match.group(1))
        return value if value > 0 else None
    return None


def is_session_download_prompt(prompt: str) -> bool:
    text = normalize_prompt(prompt)
    return bool(re.search(r"ダウンロード|download|保存", text, re.IGNORECASE)) and bool(parse_nth_session(text))


def is_device_disconnect_prompt(prompt: str) -> bool:
    text = normalize_prompt(prompt)
    return bool(re.search(r"(接続|device|デバイス).*(オフ|OFF|切断|disconnect|切って)|disconnect.*device", text, re.IGNORECASE))


def is_device_connect_prompt(prompt: str) -> bool:
    text = normalize_prompt(prompt)
    return bool(re.search(r"(接続|device|デバイス).*(オン|ON|接続して|connect|つないで|繋いで|再接続)|connect.*device", text, re.IGNORECASE))


def is_session_stop_prompt(prompt: str) -> bool:
    text = normalize_prompt(prompt)
    return bool(re.search(r"セッション.*(終了|停止|ストップ|止め)|stop.*session|end.*session", text, re.IGNORECASE))


def is_session_start_prompt(prompt: str) -> bool:
    text = normalize_prompt(prompt)
    return bool(re.search(r"セッション.*(開始|スタート|start)|start.*session", text, re.IGNORECASE))


def normalize_session_name(name: str) -> str | None:
    text = (name or "").strip().strip('"“”「」\'')
    # 抽出末尾に混ざりやすい指示語を除去
    text = re.sub(
        r"\s*(?:で(?:セッション)?(?:開始|スタート|start)|を?(?:開始|スタート)|にして|でお願い|お願いします|してください|して)\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    return text[:64]


def parse_session_name(prompt: str) -> str | None:
    text = normalize_prompt(prompt)
    quoted = re.search(r'["“「](.+?)["”」]', text)
    if quoted:
        return normalize_session_name(quoted.group(1))

    patterns = [
        r"セッション名(?:は|を)?\s*[:：]?\s*(.+?)(?=\s*(?:で(?:セッション)?(?:開始|スタート|start)|を?(?:開始|スタート)|にして|でお願い|お願いします|してください|$))",
        r"名前(?:は|を)?\s*[:：]?\s*(.+?)(?=\s*(?:で(?:セッション)?(?:開始|スタート|start)|を?(?:開始|スタート)|にして|でお願い|お願いします|してください|$))",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            name = normalize_session_name(match.group(1))
            if name:
                return name
    return None


def fetch_session_list(bridge_url: str) -> list[dict[str, Any]]:
    response = request_json(f"{bridge_url.rstrip('/')}/sessions")
    return list(response.get("sessions", []))


def fetch_health(bridge_url: str) -> dict[str, Any]:
    return request_json(f"{bridge_url.rstrip('/')}/health")


def fetch_events(bridge_url: str, skip: int = 0, limit: int = 100) -> dict[str, Any]:
    return request_json(f"{bridge_url.rstrip('/')}/events?skip={max(skip, 0)}&limit={max(limit, 1)}")


def fetch_command_history(bridge_url: str, limit: int = 100) -> dict[str, Any]:
    return request_json(f"{bridge_url.rstrip('/')}/commands/history?limit={max(limit, 1)}")


def enqueue_command(bridge_url: str, command_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return request_json(
        f"{bridge_url.rstrip('/')}/commands",
        method="POST",
        payload={
            "type": command_type,
            "payload": payload or {},
        },
    )


def wait_for_command_result(bridge_url: str, command_id: str, timeout_seconds: float = 10.0) -> dict[str, Any] | None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        history = fetch_command_history(bridge_url, limit=100).get("history", [])
        if isinstance(history, list):
            for entry in history:
                if not isinstance(entry, dict) or entry.get("id") != command_id:
                    continue
                if entry.get("executed"):
                    result = entry.get("result")
                    return result if isinstance(result, dict) else {"result": result}
        time.sleep(0.25)
    return None


def download_session_zip(bridge_url: str, session_id: str, destination_dir: Path = DOWNLOAD_DIR) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    body, headers = request_binary(f"{bridge_url.rstrip('/')}/sessions/{urllib.parse.quote(session_id)}/download")
    filename = None
    disposition = headers.get("Content-Disposition", "")
    match = re.search(r'filename="([^"]+)"', disposition)
    if match:
        filename = match.group(1)
    if not filename:
        filename = f"{session_id}.zip"
    output_path = destination_dir / filename
    output_path.write_bytes(body)
    return output_path


def handle_intent(bridge_url: str, prompt: str) -> str:
    if is_session_list_prompt(prompt):
        sessions = fetch_session_list(bridge_url)
        return format_session_list(sessions)

    if is_device_id_prompt(prompt):
        response = enqueue_command(bridge_url, "query_device_id")
        command = response.get("command", {})
        command_id = command.get("id")
        if not command_id:
            return "デバイスID問い合わせコマンドを送信できませんでした。"

        result = wait_for_command_result(bridge_url, command_id, timeout_seconds=12.0)
        if isinstance(result, dict):
            device_id = result.get("sensorId") or result.get("deviceId") or result.get("sensor_id")
            if device_id:
                return f"現在のデバイスIDは {device_id} です。"
            if result.get("success") is False:
                error = result.get("error") or "unknown error"
                return f"現在のデバイスIDを取得できませんでした: {error}"

        health = fetch_health(bridge_url)
        device_id = health.get("current_device_id") or health.get("device_receiving", {}).get("last_sensor_id")
        if device_id and device_id != "-":
            return f"現在のデバイスIDは {device_id} です。"
        return "現在のデバイスIDはまだ取得できていません。"

    if is_session_download_prompt(prompt):
        target_index = parse_nth_session(prompt)
        if not target_index:
            return "ダウンロード対象のセッション番号を解釈できませんでした。"
        sessions = fetch_session_list(bridge_url)
        if target_index > len(sessions):
            return f"{target_index}番目のセッションは存在しません。現在の件数は {len(sessions)} 件です。"
        session = sessions[target_index - 1]
        session_id = session.get("session_id")
        if not session_id:
            return "セッション ID を取得できませんでした。"
        output_path = download_session_zip(bridge_url, session_id)
        return f"{target_index}番目のセッションをダウンロードしました: {output_path}"

    if is_device_disconnect_prompt(prompt):
        response = enqueue_command(bridge_url, "disconnect_device")
        command = response.get("command", {})
        return f"デバイス切断コマンドを送信しました。command_id={command.get('id', '-') }"

    if is_device_connect_prompt(prompt):
        response = enqueue_command(bridge_url, "connect_device")
        command = response.get("command", {})
        return f"デバイス接続コマンドを送信しました。command_id={command.get('id', '-') }"

    if is_session_stop_prompt(prompt):
        response = enqueue_command(bridge_url, "stop_session")
        command = response.get("command", {})
        return f"セッション終了コマンドを送信しました。command_id={command.get('id', '-') }"

    if is_session_start_prompt(prompt):
        name = parse_session_name(prompt)
        payload = {"name": name} if name else {}
        response = enqueue_command(bridge_url, "start_session", payload=payload)
        command = response.get("command", {})
        name_note = f" (name={name})" if name else ""
        return f"セッション開始コマンドを送信しました{name_note}。command_id={command.get('id', '-') }"

    result = query_bridge(bridge_url, prompt)
    return format_response(result)


def format_viewer_event_notice(event: dict[str, Any]) -> str | None:
    event_type = str(event.get("type", "")).strip()
    source = str(event.get("source", "")).strip()
    if source and source != "viewer":
        return None

    data = event.get("data")
    payload = data if isinstance(data, dict) else {}
    session_id = payload.get("sessionId") or payload.get("session_id")
    sensor_id = payload.get("sensorId") or payload.get("sensor_id")
    name = payload.get("name") or ""

    if event_type == "device_connected":
        sid = f" sensor={sensor_id}" if sensor_id else ""
        return f"[通知] ブラウザ: デバイス接続{sid}"
    if event_type == "device_disconnected":
        sid = f" sensor={sensor_id}" if sensor_id else ""
        return f"[通知] ブラウザ: デバイス切断{sid}"
    if event_type == "session_started":
        name_part = f" name={name}" if name else ""
        sid = f" session_id={session_id}" if session_id else ""
        return f"[通知] ブラウザ: セッション開始{name_part}{sid}"
    if event_type == "session_ended":
        sid = f" session_id={session_id}" if session_id else ""
        return f"[通知] ブラウザ: セッション終了{sid}"
    if event_type == "crc_error":
        return "[通知] ブラウザ: CRC エラーを検出"
    if event_type == "sensor_anomaly":
        return "[通知] ブラウザ: センサー異常イベント"
    return None


class ViewerEventNotifier:
    def __init__(self, bridge_url: str, poll_interval: float = 1.0):
        self.bridge_url = bridge_url
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._cursor = 0
        self._warned_unreachable = False

    def start(self):
        # 起動時点の total から購読し、過去イベントの大量表示を避ける
        try:
            snapshot = fetch_events(self.bridge_url, skip=0, limit=1)
            self._cursor = int(snapshot.get("total", 0))
            self._warned_unreachable = False
        except Exception:
            self._cursor = 0
            self._warned_unreachable = True
            print("[通知] bridge に接続できません。イベント通知は復旧後に再開します。", flush=True)

        self._thread = threading.Thread(target=self._run, name="viewer-event-notifier", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _run(self):
        while not self._stop_event.is_set():
            try:
                response = fetch_events(self.bridge_url, skip=self._cursor, limit=100)
                total = int(response.get("total", self._cursor))
                events = response.get("events", [])
                if isinstance(events, list):
                    for event in events:
                        if not isinstance(event, dict):
                            continue
                        notice = format_viewer_event_notice(event)
                        if notice:
                            print(f"\n{notice}", flush=True)
                self._cursor = max(self._cursor + (len(events) if isinstance(events, list) else 0), total)
                self._warned_unreachable = False
            except Exception:
                if not self._warned_unreachable:
                    print("\n[通知] bridge への接続が一時的に失われました。", flush=True)
                    self._warned_unreachable = True
            self._stop_event.wait(self.poll_interval)


def run_interactive_mode(args: argparse.Namespace) -> int:
    bridge_url = args.bridge_url
    notifier = ViewerEventNotifier(bridge_url=bridge_url, poll_interval=1.0)
    notifier.start()

    print("Scent Agent 対話モードを開始します。終了するには exit または quit を入力してください。")
    print("ブラウザ側の操作（接続/切断/セッション開始/終了など）は通知として割り込み表示されます。")

    try:
        while True:
            try:
                prompt = input("agent> ").strip()
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print("\n終了します。")
                break

            if not prompt:
                continue
            if prompt.lower() in {"exit", "quit"}:
                break

            try:
                output = handle_intent(bridge_url, prompt)
            except urllib.error.URLError as exc:
                print(f"Failed to reach bridge: {exc}", file=sys.stderr)
                continue
            except json.JSONDecodeError as exc:
                print(f"Bridge returned invalid JSON: {exc}", file=sys.stderr)
                continue
            except Exception as exc:  # pragma: no cover - defensive guard for CLI use
                print(f"Unexpected error: {exc}", file=sys.stderr)
                continue

            if args.json:
                print(json.dumps({"prompt": prompt, "output": output}, ensure_ascii=False, indent=2))
            else:
                print(output)
    finally:
        notifier.stop()

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    prompt = resolve_prompt(args)

    if args.interactive or (not args.prompt and not args.status):
        return run_interactive_mode(args)

    if not prompt:
        parser.error("prompt is required")

    try:
        output = handle_intent(args.bridge_url, prompt)
    except urllib.error.URLError as exc:
        print(f"Failed to reach bridge: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"Bridge returned invalid JSON: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - defensive guard for CLI use
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"prompt": prompt, "output": output}, ensure_ascii=False, indent=2))
    else:
        print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
