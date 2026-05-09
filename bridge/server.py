import logging
import json
import re
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio

from config import BRIDGE_HOST, BRIDGE_PORT, ALLOWED_ORIGINS, BRIDGE_LOG_DIR
from events import Event, EventType, EventQueue
from ai import AIRouter
from commands import CommandQueue, CommandFactory, CommandType

import os

# ログディレクトリ作成
os.makedirs(BRIDGE_LOG_DIR, exist_ok=True)

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(BRIDGE_LOG_DIR, "bridge.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# グローバル状態
event_queue = EventQueue()
command_queue = CommandQueue()
ai_router = AIRouter()
connected_viewers: set[WebSocket] = set()
device_state = {
    "last_data_record_at": None,
    "last_device_connected_at": None,
    "last_device_disconnected_at": None,
    "last_session_started_at": None,
    "last_session_ended_at": None,
    "last_sensor_id": None,
}

viewer_state_snapshot = {
    "origin": None,
    "page_url": None,
    "sessions": [],
    "updated_at": None,
}

RECEIVING_WINDOW_SECONDS = 15


def extract_field(data: dict, *keys: str):
    """複数のキー候補から先に見つかった値を返す"""
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def update_device_state(event_type: EventType, data: dict):
    """受信中判定のための最新状態を更新する"""
    now = time.time()
    sensor_id = extract_field(data, "sensor_id", "sensorId")
    if event_type == EventType.DATA_RECORD:
        device_state["last_data_record_at"] = now
        if sensor_id:
            device_state["last_sensor_id"] = sensor_id
    elif event_type == EventType.DEVICE_CONNECTED:
        device_state["last_device_connected_at"] = now
        if sensor_id:
            device_state["last_sensor_id"] = sensor_id
    elif event_type == EventType.DEVICE_DISCONNECTED:
        device_state["last_device_disconnected_at"] = now
    elif event_type == EventType.SESSION_STARTED:
        device_state["last_session_started_at"] = now
        if sensor_id:
            device_state["last_sensor_id"] = sensor_id
    elif event_type == EventType.SESSION_ENDED:
        device_state["last_session_ended_at"] = now


def current_device_id() -> str | None:
    """現在のデバイスIDを返す"""
    return device_state["last_sensor_id"]


def get_event_session_id(data: dict):
    """イベントから session ID を取り出す"""
    return extract_field(data, "session_id", "sessionId")


def get_session_name(data: dict) -> str:
    name = extract_field(data, "name", "session_name")
    return str(name) if name is not None else ""


def get_session_sensor_id(data: dict):
    return extract_field(data, "sensor_id", "sensorId")


def get_session_start_iso(data: dict, fallback: str) -> str:
    return str(extract_field(data, "startIso", "start_iso") or fallback)


def get_session_end_iso(data: dict, fallback: str) -> str:
    return str(extract_field(data, "endIso", "end_iso") or fallback)


def normalize_viewer_session(session: dict) -> dict | None:
    if not isinstance(session, dict):
        return None

    session_id = str(session.get("id") or session.get("session_id") or "").strip()
    if not session_id:
        return None

    records = session.get("records")
    if not isinstance(records, list):
        records = []

    normalized_records = [record for record in records if isinstance(record, dict)]
    start_iso = str(session.get("startIso") or session.get("start_iso") or "").strip()
    end_iso_raw = session.get("endIso") if "endIso" in session else session.get("end_iso")
    end_iso = str(end_iso_raw).strip() if end_iso_raw else None

    return {
        "index": 0,
        "session_id": session_id,
        "name": str(session.get("name") or ""),
        "sensor_id": str(session.get("sensorId") or session.get("sensor_id") or current_device_id() or ""),
        "start_iso": start_iso,
        "end_iso": end_iso,
        "records": normalized_records,
        "records_count": len(normalized_records),
        "running": not bool(end_iso),
    }


def set_viewer_state_snapshot(payload: dict) -> int:
    if not isinstance(payload, dict):
        return 0

    sessions_payload = payload.get("sessions")
    normalized_sessions: list[dict] = []
    if isinstance(sessions_payload, list):
        for item in sessions_payload:
            normalized = normalize_viewer_session(item)
            if normalized:
                normalized_sessions.append(normalized)

    normalized_sessions.sort(key=lambda item: item.get("start_iso") or "", reverse=True)
    for index, session in enumerate(normalized_sessions, start=1):
        session["index"] = index

    viewer_state_snapshot["origin"] = str(payload.get("origin") or "").strip() or None
    viewer_state_snapshot["page_url"] = str(payload.get("page_url") or "").strip() or None
    viewer_state_snapshot["sessions"] = normalized_sessions
    viewer_state_snapshot["updated_at"] = time.time()
    return len(normalized_sessions)


def get_active_sessions() -> list[dict]:
    sessions = viewer_state_snapshot.get("sessions")
    if isinstance(sessions, list) and sessions:
        compact_sessions: list[dict] = []
        for index, session in enumerate(sessions, start=1):
            records = session.get("records")
            records_count = session.get("records_count")
            if records_count is None and isinstance(records, list):
                records_count = len(records)

            compact_sessions.append({
                "index": index,
                "session_id": session.get("session_id", ""),
                "name": session.get("name", ""),
                "sensor_id": session.get("sensor_id", ""),
                "start_iso": session.get("start_iso", ""),
                "end_iso": session.get("end_iso"),
                "records_count": records_count or 0,
                "running": bool(session.get("running", session.get("end_iso") is None)),
            })
        return compact_sessions
    return build_session_summaries()


def get_active_session_details(session_id: str) -> dict | None:
    sessions = viewer_state_snapshot.get("sessions")
    if isinstance(sessions, list) and sessions:
        for session in sessions:
            if session.get("session_id") == session_id:
                return dict(session)
    return get_session_details(session_id)


def build_session_summaries() -> list[dict]:
    """受信イベントからセッション一覧を再構成する"""
    sessions: dict[str, dict] = {}
    ordered_session_ids: list[str] = []

    for event in event_queue.queue:
        data = event.data if isinstance(event.data, dict) else {}
        session_id = get_event_session_id(data)

        if event.type == EventType.SESSION_STARTED and session_id:
            if session_id not in sessions:
                sessions[session_id] = {
                    "session_id": session_id,
                    "name": get_session_name(data),
                    "sensor_id": get_session_sensor_id(data) or current_device_id(),
                    "start_iso": get_session_start_iso(data, event.timestamp),
                    "end_iso": None,
                    "records": [],
                }
                ordered_session_ids.append(session_id)
            else:
                sessions[session_id]["name"] = get_session_name(data) or sessions[session_id]["name"]
                sessions[session_id]["sensor_id"] = get_session_sensor_id(data) or sessions[session_id]["sensor_id"]
                sessions[session_id]["start_iso"] = get_session_start_iso(data, sessions[session_id]["start_iso"])
            continue

        if event.type == EventType.DATA_RECORD and session_id:
            session = sessions.get(session_id)
            if not session:
                session = {
                    "session_id": session_id,
                    "name": "",
                    "sensor_id": get_session_sensor_id(data) or current_device_id(),
                    "start_iso": get_session_start_iso(data, event.timestamp),
                    "end_iso": None,
                    "records": [],
                }
                sessions[session_id] = session
                ordered_session_ids.append(session_id)
            record = extract_field(data, "record") or data
            if isinstance(record, dict):
                session["records"].append(record)
                session["sensor_id"] = get_session_sensor_id(data) or session["sensor_id"]
            continue

        if event.type == EventType.SESSION_ENDED and session_id:
            session = sessions.get(session_id)
            if not session:
                session = {
                    "session_id": session_id,
                    "name": get_session_name(data),
                    "sensor_id": get_session_sensor_id(data) or current_device_id(),
                    "start_iso": get_session_start_iso(data, event.timestamp),
                    "end_iso": get_session_end_iso(data, event.timestamp),
                    "records": [],
                }
                sessions[session_id] = session
                ordered_session_ids.append(session_id)
            session["end_iso"] = get_session_end_iso(data, event.timestamp)
            session["name"] = get_session_name(data) or session["name"]
            session["sensor_id"] = get_session_sensor_id(data) or session["sensor_id"]

    result = []
    for index, session_id in enumerate(ordered_session_ids, start=1):
        session = sessions[session_id]
        result.append({
            "index": index,
            "session_id": session["session_id"],
            "name": session["name"],
            "sensor_id": session["sensor_id"],
            "start_iso": session["start_iso"],
            "end_iso": session["end_iso"],
            "records_count": len(session["records"]),
            "running": session["end_iso"] is None,
        })
    return result


def get_session_details(session_id: str) -> dict | None:
    """指定セッションの詳細を構築する"""
    session = None
    for summary in build_session_summaries():
        if summary["session_id"] == session_id:
            session = summary
            break
    if not session:
        return None

    records: list[dict] = []
    collecting = False
    for event in event_queue.queue:
        data = event.data if isinstance(event.data, dict) else {}
        current_session_id = get_event_session_id(data)
        if event.type == EventType.SESSION_STARTED and current_session_id == session_id:
            collecting = True
            continue
        if event.type == EventType.SESSION_ENDED and current_session_id == session_id:
            collecting = False
            continue
        if collecting and event.type == EventType.DATA_RECORD and current_session_id == session_id:
            record = extract_field(data, "record") or data
            if isinstance(record, dict):
                records.append(record)

    session["records"] = records
    return session


def get_running_session_summaries() -> list[dict]:
    """現在実行中のセッション一覧を返す"""
    return [summary for summary in build_session_summaries() if summary.get("running")]


def close_running_sessions_before_start() -> list[str]:
    """新しいセッション開始前に、既存の running セッションを自動終了する"""
    running_sessions = get_running_session_summaries()
    if not running_sessions:
        return []

    ended_session_ids: list[str] = []
    end_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

    for summary in running_sessions:
        session_id = str(summary.get("session_id") or "").strip()
        if not session_id:
            continue

        ended_event = Event(
            EventType.SESSION_ENDED,
            {
                "sessionId": session_id,
                "name": str(summary.get("name") or ""),
                "sensorId": str(summary.get("sensor_id") or current_device_id() or ""),
                "endIso": end_iso,
            },
            source="bridge",
        )
        event_queue.enqueue(ended_event)
        update_device_state(ended_event.type, ended_event.data)
        ended_session_ids.append(session_id)

    if ended_session_ids:
        logger.info("Auto-closed running sessions before start: %s", ", ".join(ended_session_ids))

    return ended_session_ids


def make_session_stem(session: dict) -> str:
    raw_name = (session.get("name") or "").strip()
    start = str(session.get("start_iso") or "").replace(":", "-").replace(".", "-")
    safe_name = re.sub(r"[<>:\"/\\|?*\x00-\x1F]", "_", raw_name).strip().replace(" ", "_")
    if safe_name:
        return f"scent_session_{safe_name}_{start}"
    return f"scent_session_{start}"


def build_session_zip_bytes(session: dict) -> tuple[bytes, str]:
    """セッションの ZIP を生成する"""
    import csv
    import io
    import zipfile

    stem = make_session_stem(session)
    raw_buffer = io.StringIO()
    raw_writer = csv.writer(raw_buffer, lineterminator="\n")
    raw_writer.writerow(["session_id", "start_iso", "end_iso", "sensor_id", "record_index", "t", "ch", "temp", "humidity", "pressure", "current"])

    for record_index, record in enumerate(session.get("records", []), start=1):
        raw_writer.writerow([
            session.get("session_id", ""),
            session.get("start_iso", ""),
            session.get("end_iso", "") or "",
            session.get("sensor_id", "") or "",
            record_index,
            record.get("t", ""),
            record.get("ch", ""),
            record.get("temp", ""),
            record.get("humidity", ""),
            record.get("pressure", ""),
            record.get("current", ""),
        ])

    data_buffer = io.StringIO()
    data_writer = csv.writer(data_buffer, lineterminator="\n")
    data_writer.writerow(["record_index", "t", "ch", "temp", "humidity", "pressure", "current"])
    for record_index, record in enumerate(session.get("records", []), start=1):
        data_writer.writerow([
            record_index,
            record.get("t", ""),
            record.get("ch", ""),
            record.get("temp", ""),
            record.get("humidity", ""),
            record.get("pressure", ""),
            record.get("current", ""),
        ])

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{stem}_raw.csv", raw_buffer.getvalue())
        archive.writestr(f"{stem}_data.csv", data_buffer.getvalue())
        archive.writestr(f"{stem}_meta.json", json.dumps(session, ensure_ascii=False, indent=2))

    return zip_buffer.getvalue(), f"{stem}.zip"


def get_device_receiving_snapshot() -> dict:
    """現在データ受信中かのスナップショットを返す"""
    now = time.time()
    last_data_record_at = device_state["last_data_record_at"]
    last_device_connected_at = device_state["last_device_connected_at"]
    last_device_disconnected_at = device_state["last_device_disconnected_at"]

    seconds_since_last_data = None if last_data_record_at is None else round(now - last_data_record_at, 3)
    seconds_since_connected = None if last_device_connected_at is None else round(now - last_device_connected_at, 3)
    seconds_since_disconnected = None if last_device_disconnected_at is None else round(now - last_device_disconnected_at, 3)

    receiving = False
    reason = "no data yet"
    if last_data_record_at is not None:
        if seconds_since_last_data is not None and seconds_since_last_data <= RECEIVING_WINDOW_SECONDS:
            receiving = True
            reason = f"data received within last {RECEIVING_WINDOW_SECONDS} seconds"
        else:
            reason = "no recent data received"

    if last_device_disconnected_at is not None and last_data_record_at is not None:
        if last_device_disconnected_at >= last_data_record_at:
            receiving = False
            reason = "device was disconnected after the last data event"

    return {
        "receiving": receiving,
        "reason": reason,
        "last_sensor_id": device_state["last_sensor_id"],
        "last_data_record_at": last_data_record_at,
        "seconds_since_last_data": seconds_since_last_data,
        "seconds_since_connected": seconds_since_connected,
        "seconds_since_disconnected": seconds_since_disconnected,
        "window_seconds": RECEIVING_WINDOW_SECONDS,
    }


def prompt_requests_receiving_status(prompt: str) -> bool:
    """問い合わせが受信中判定を求めているかを判定する"""
    text = (prompt or "").strip()
    if not text:
        return False
    return bool(re.search(r"受信中|データ.*受信|data.*receiv|currently receiving|receiving data", text, re.IGNORECASE))


def format_receiving_answer(snapshot: dict) -> dict:
    """AI 向けの回答を組み立てる"""
    if snapshot["receiving"]:
        answer = "はい。現在デバイスからデータを受信中です。"
    else:
        answer = "いいえ。現在デバイスからデータは受信されていません。"

    detail_parts = [snapshot["reason"]]
    if snapshot["last_sensor_id"]:
        detail_parts.append(f"sensor_id={snapshot['last_sensor_id']}")
    if snapshot["seconds_since_last_data"] is not None:
        detail_parts.append(f"last_data_age={snapshot['seconds_since_last_data']}s")

    return {
        "answer": answer,
        "details": "; ".join(detail_parts),
        "snapshot": snapshot,
    }


def apply_command_result_side_effects(command, result: dict | None):
    """コマンド実行結果から bridge 状態へ反映すべき副作用を適用する"""
    if not command or command.type != CommandType.STOP_SESSION:
        return
    if not isinstance(result, dict) or not result.get("success"):
        return

    session_id = extract_field(result, "sessionId", "session_id")
    if not session_id:
        return

    ended_event = Event(
        EventType.SESSION_ENDED,
        {
            "sessionId": session_id,
            "name": extract_field(result, "name", "session_name") or "",
            "sensorId": extract_field(result, "sensorId", "sensor_id") or current_device_id(),
            "endIso": extract_field(result, "endIso", "end_iso") or time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        },
        source="bridge",
    )
    event_queue.enqueue(ended_event)
    update_device_state(ended_event.type, ended_event.data)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """サーバーの起動・終了処理"""
    logger.info("Bridge server starting...")
    await ai_router.ollama.check_health()
    if ai_router.ollama.is_available:
        logger.info(f"Ollama available at {ai_router.ollama.base_url}")
    else:
        logger.warning("Ollama not available, will run in degraded mode")
    yield
    logger.info("Bridge server shutting down...")

app = FastAPI(title="Scent Bridge", lifespan=lifespan)

# CORS 設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def allow_private_network_access(request: Request, call_next):
    """HTTPS origin から localhost へのアクセス時に必要な PNA ヘッダーを付与する。"""
    is_pna_preflight = (
        request.method == "OPTIONS"
        and request.headers.get("access-control-request-private-network", "").lower() == "true"
    )

    if is_pna_preflight:
        response = Response(status_code=204)
    else:
        response = await call_next(request)

    if request.headers.get("origin"):
        response.headers["Access-Control-Allow-Private-Network"] = "true"

    return response

# ============================================================================
# HTTP Endpoints
# ============================================================================

@app.get("/health")
async def health_check():
    """ヘルスチェック"""
    snapshot = get_device_receiving_snapshot()
    return {
        "status": "ok",
        "ollama_available": ai_router.ollama.is_available,
        "event_queue_size": event_queue.size(),
        "pending_commands": command_queue.get_pending_count(),
        "connected_viewers": len(connected_viewers),
        "current_device_id": current_device_id(),
        "device_receiving": snapshot,
        "viewer_state_origin": viewer_state_snapshot.get("origin"),
        "viewer_state_updated_at": viewer_state_snapshot.get("updated_at"),
    }


@app.post("/viewer-state")
async def update_viewer_state(payload: dict):
    """Viewer localStorage ベースの状態スナップショットを受け取る"""
    count = set_viewer_state_snapshot(payload)
    return {
        "received": True,
        "sessions": count,
        "origin": viewer_state_snapshot.get("origin"),
        "page_url": viewer_state_snapshot.get("page_url"),
    }

@app.post("/event")
async def receive_event(payload: dict):
    """Viewer からのイベント受信 (HTTP)"""
    try:
        event_type = EventType(payload.get("type", "unknown"))
    except ValueError:
        event_type = EventType.UNKNOWN

    event = Event(event_type, payload.get("data", {}))
    event_queue.enqueue(event)
    logger.info(f"Event received: {event.type.value}")
    update_device_state(event.type, event.data)

    # AI 処理を非同期で開始
    result = await ai_router.route_event(event)
    event.result = result

    # 接続中の Viewer に通知
    await broadcast_to_viewers({
        "type": "event_processed",
        "event": event.to_dict(),
        "ai_result": result,
    })

    return {
        "event_id": event.id,
        "received": True,
        "ai_result": result,
    }

@app.get("/events")
async def get_events(skip: int = 0, limit: int = 100):
    """イベント履歴を取得"""
    events_list = event_queue.queue[skip : skip + limit]
    return {
        "total": event_queue.size(),
        "events": [e.to_dict() for e in events_list],
    }

@app.get("/sessions")
async def get_sessions():
    """セッション一覧を取得"""
    sessions = get_active_sessions()
    return {
        "total": len(sessions),
        "sessions": sessions,
        "source_origin": viewer_state_snapshot.get("origin"),
    }

@app.get("/sessions/{session_id}/download")
async def download_session(session_id: str):
    """セッションのZIPをダウンロードする"""
    session = get_active_session_details(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    zip_bytes, filename = build_session_zip_bytes(session)
    # ファイル名をASCII-safeに変換（日本語など多バイト文字への対応）
    safe_filename = filename.encode("ascii", errors="ignore").decode("ascii") or "session.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


@app.get("/sessions/{session_id}/download-full")
async def download_session_full(session_id: str):
    """セッションのZIPをダウンロードする（別名）"""
    return await download_session(session_id)

@app.get("/commands/pending")
async def get_pending_commands():
    """保留中のコマンドを取得"""
    cmd = command_queue.peek()
    if cmd:
        return cmd.to_dict()
    return {"message": "No pending commands"}

@app.get("/commands/history")
async def get_command_history(limit: int = 100):
    """コマンド実行履歴を取得"""
    history = command_queue.get_history(limit)
    return {
        "total": len(command_queue.history),
        "history": [c.to_dict() for c in history],
    }

@app.post("/commands")
async def enqueue_command(payload: dict):
    """Viewer 向けコマンドをキューに追加"""
    command_type_text = str(payload.get("type", "")).strip()
    command_payload = payload.get("payload", {})

    if not command_type_text:
        raise HTTPException(status_code=400, detail="type is required")
    if not isinstance(command_payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")

    try:
        command_type = CommandType(command_type_text)
    except ValueError:
        allowed = [c.value for c in CommandType]
        raise HTTPException(status_code=400, detail=f"unsupported command type: {command_type_text}; allowed={allowed}")

    if command_type == CommandType.DOWNLOAD_SESSION:
        session_id = str(command_payload.get("session_id", "")).strip()
        if not session_id:
            raise HTTPException(status_code=400, detail="payload.session_id is required")
        cmd = CommandFactory.create_download_session(session_id, str(command_payload.get("format", "zip") or "zip"))
    elif command_type == CommandType.EXPORT_SESSION:
        session_id = str(command_payload.get("session_id", "")).strip()
        if not session_id:
            raise HTTPException(status_code=400, detail="payload.session_id is required")
        cmd = CommandFactory.create_export_session(session_id, str(command_payload.get("target", "local") or "local"))
    elif command_type == CommandType.QUERY_STATE:
        cmd = CommandFactory.create_query_state()
    elif command_type == CommandType.QUERY_DEVICE_ID:
        cmd = CommandFactory.create_query_device_id()
    elif command_type == CommandType.NOTIFY_USER:
        message = str(command_payload.get("message", "")).strip()
        if not message:
            raise HTTPException(status_code=400, detail="payload.message is required")
        cmd = CommandFactory.create_notify_user(message, str(command_payload.get("level", "info") or "info"))
    elif command_type == CommandType.CONNECT_DEVICE:
        cmd = CommandFactory.create_connect_device()
    elif command_type == CommandType.DISCONNECT_DEVICE:
        cmd = CommandFactory.create_disconnect_device()
    elif command_type == CommandType.START_SESSION:
        close_running_sessions_before_start()
        name = command_payload.get("name")
        cmd = CommandFactory.create_start_session(str(name).strip() if name is not None else None)
    elif command_type == CommandType.STOP_SESSION:
        cmd = CommandFactory.create_stop_session()
    else:
        raise HTTPException(status_code=400, detail=f"unsupported command type: {command_type_text}")

    command_queue.enqueue(cmd)

    if connected_viewers:
        await broadcast_to_viewers(cmd.to_dict())

    return {
        "queued": True,
        "command": cmd.to_dict(),
        "connected_viewers": len(connected_viewers),
    }

@app.post("/commands/execute/{command_id}")
async def mark_command_executed(command_id: str, result: dict = None):
    """コマンド実行完了を報告"""
    pending_cmd = next((cmd for cmd in command_queue.pending if cmd.id == command_id), None)
    if pending_cmd:
        command_queue.mark_executed(pending_cmd, result)
        apply_command_result_side_effects(pending_cmd, result)
        return {"success": True, "command_id": command_id}
    raise HTTPException(status_code=404, detail="Command not found")


@app.post("/agent/query")
async def agent_query(payload: dict):
    """AI エージェントからの自然文問い合わせを処理する"""
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    snapshot = get_device_receiving_snapshot()
    if prompt_requests_receiving_status(prompt):
        result = format_receiving_answer(snapshot)
        logger.info(f"Agent query handled locally: {prompt}")
        return {
            "prompt": prompt,
            "handled_locally": True,
            "result": result,
        }

    event = Event(EventType.UNKNOWN, {"prompt": prompt, "source": "agent"}, source="agent")
    ai_result = await ai_router.ollama.analyze_event(event) if ai_router.ollama.is_available else "Ollama is not available"
    logger.info(f"Agent query forwarded to AI: {prompt}")
    return {
        "prompt": prompt,
        "handled_locally": False,
        "result": {
            "answer": ai_result,
            "snapshot": snapshot,
        },
    }

# ============================================================================
# WebSocket
# ============================================================================

@app.websocket("/ws/viewer")
async def websocket_viewer(websocket: WebSocket):
    """Viewer との WebSocket 接続"""
    await websocket.accept()
    connected_viewers.add(websocket)
    logger.info(f"Viewer connected. Total viewers: {len(connected_viewers)}")

    try:
        while True:
            # Viewer からメッセージ受信
            msg = await websocket.receive_text()
            data = json.loads(msg)

            if data.get("type") == "event":
                # イベント受信
                try:
                    event_type = EventType(data.get("event_type", "unknown"))
                except ValueError:
                    event_type = EventType.UNKNOWN

                event = Event(event_type, data.get("data", {}))
                event_queue.enqueue(event)
                logger.info(f"Event from WebSocket: {event.type.value}")
                update_device_state(event.type, event.data)

                # AI 処理
                result = await ai_router.route_event(event)
                event.result = result

                # 応答
                await websocket.send_text(json.dumps({
                    "type": "event_ack",
                    "event_id": event.id,
                    "ai_result": result,
                }))

                # 他の Viewer に通知
                await broadcast_to_viewers({
                    "type": "event_broadcast",
                    "event": event.to_dict(),
                }, exclude=websocket)

            elif data.get("type") == "command_result":
                # コマンド実行結果
                cmd_id = data.get("command_id")
                result = data.get("result")
                pending_cmd = next((cmd for cmd in command_queue.pending if cmd.id == cmd_id), None)
                if pending_cmd:
                    command_queue.mark_executed(pending_cmd, result)
                    apply_command_result_side_effects(pending_cmd, result)
                    logger.info(f"Command completed: {cmd_id}")

            elif data.get("type") == "query_state":
                # 状態クエリ
                await websocket.send_text(json.dumps({
                    "type": "state_response",
                    "event_queue_size": event_queue.size(),
                    "pending_commands": command_queue.get_pending_count(),
                    "device_receiving": get_device_receiving_snapshot(),
                    "viewer_state_origin": viewer_state_snapshot.get("origin"),
                    "sessions": get_active_sessions(),
                }))

    except WebSocketDisconnect:
        connected_viewers.discard(websocket)
        logger.info(f"Viewer disconnected. Total viewers: {len(connected_viewers)}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        connected_viewers.discard(websocket)

# ============================================================================
# Utility Functions
# ============================================================================

async def broadcast_to_viewers(message: dict, exclude: WebSocket = None):
    """すべての接続中 Viewer にメッセージをブロードキャスト"""
    dead_viewers = set()
    for viewer in connected_viewers:
        if exclude and viewer == exclude:
            continue
        try:
            await viewer.send_text(json.dumps(message))
        except Exception as e:
            logger.warning(f"Failed to send to viewer: {e}")
            dead_viewers.add(viewer)

    connected_viewers.difference_update(dead_viewers)

def create_app() -> FastAPI:
    """FastAPI アプリケーション生成"""
    return app
