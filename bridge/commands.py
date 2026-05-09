import json
import logging
from typing import Any, Dict, Optional
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)

class CommandType(str, Enum):
    """ブリッジから Viewer へ送るコマンド型"""
    DOWNLOAD_SESSION = "download_session"
    EXPORT_SESSION = "export_session"
    QUERY_STATE = "query_state"
    QUERY_DEVICE_ID = "query_device_id"
    NOTIFY_USER = "notify_user"
    CONNECT_DEVICE = "connect_device"
    DISCONNECT_DEVICE = "disconnect_device"
    START_SESSION = "start_session"
    STOP_SESSION = "stop_session"

class Command:
    """コマンドの標準形式"""
    def __init__(self, cmd_type: CommandType, payload: Dict[str, Any]):
        self.id = f"cmd-{datetime.now().timestamp()}"
        self.type = cmd_type
        self.payload = payload
        self.created_at = datetime.utcnow().isoformat()
        self.executed = False
        self.result = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "payload": self.payload,
            "created_at": self.created_at,
            "executed": self.executed,
            "result": self.result,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

class CommandQueue:
    """コマンドキュー管理"""
    def __init__(self):
        self.pending: list[Command] = []
        self.history: list[Command] = []

    def enqueue(self, cmd: Command):
        """コマンドをキューに追加"""
        self.pending.append(cmd)
        logger.info(f"Command queued: {cmd.id} ({cmd.type.value})")

    def dequeue(self) -> Optional[Command]:
        """キューからコマンドを取り出す"""
        return self.pending.pop(0) if self.pending else None

    def peek(self) -> Optional[Command]:
        """キューの先頭を確認"""
        return self.pending[0] if self.pending else None

    def mark_executed(self, cmd: Command, result: Any = None):
        """コマンド実行済みにマーク"""
        if cmd in self.pending:
            self.pending.remove(cmd)
        cmd.executed = True
        cmd.result = result
        self.history.append(cmd)
        logger.info(f"Command executed: {cmd.id}")

    def get_pending_count(self) -> int:
        return len(self.pending)

    def get_history(self, limit: int = 100) -> list[Command]:
        """実行済みコマンド履歴を取得"""
        return self.history[-limit:]

class CommandFactory:
    """コマンド生成ファクトリ"""

    @staticmethod
    def create_download_session(session_id: str, format: str = "zip") -> Command:
        """セッションダウンロードコマンドを生成"""
        return Command(
            CommandType.DOWNLOAD_SESSION,
            {
                "session_id": session_id,
                "format": format,  # zip, csv_raw, csv_data
            }
        )

    @staticmethod
    def create_export_session(session_id: str, target: str = "local") -> Command:
        """セッションエクスポートコマンドを生成"""
        return Command(
            CommandType.EXPORT_SESSION,
            {
                "session_id": session_id,
                "target": target,  # local, cloud, etc.
            }
        )

    @staticmethod
    def create_query_state() -> Command:
        """Viewer の状態クエリコマンド"""
        return Command(CommandType.QUERY_STATE, {})

    @staticmethod
    def create_query_device_id() -> Command:
        """Viewer にデバイス ID を問い合わせるコマンド"""
        return Command(CommandType.QUERY_DEVICE_ID, {})

    @staticmethod
    def create_notify_user(message: str, level: str = "info") -> Command:
        """ユーザー通知コマンド"""
        return Command(
            CommandType.NOTIFY_USER,
            {
                "message": message,
                "level": level,  # info, warning, error
            }
        )

    @staticmethod
    def create_connect_device() -> Command:
        """デバイス接続コマンド"""
        return Command(CommandType.CONNECT_DEVICE, {})

    @staticmethod
    def create_disconnect_device() -> Command:
        """デバイス切断コマンド"""
        return Command(CommandType.DISCONNECT_DEVICE, {})

    @staticmethod
    def create_start_session(name: str | None = None) -> Command:
        """セッション開始コマンド"""
        payload: Dict[str, Any] = {}
        if name:
            payload["name"] = name
        return Command(CommandType.START_SESSION, payload)

    @staticmethod
    def create_stop_session() -> Command:
        """セッション終了コマンド"""
        return Command(CommandType.STOP_SESSION, {})
