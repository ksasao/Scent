from enum import Enum
from typing import Any, Dict
from datetime import datetime
import json

class EventType(str, Enum):
    """Viewer から送られるイベント型"""
    DEVICE_CONNECTED = "device_connected"
    DEVICE_DISCONNECTED = "device_disconnected"
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"
    CRC_ERROR = "crc_error"
    DATA_RECORD = "data_record"
    SENSOR_ANOMALY = "sensor_anomaly"
    UNKNOWN = "unknown"

class Event:
    """イベントの標準形式"""
    def __init__(self, event_type: EventType, data: Dict[str, Any], source: str = "viewer"):
        self.id = f"{datetime.now().timestamp()}-{hash(str(data))}"
        self.type = event_type
        self.timestamp = datetime.utcnow().isoformat()
        self.data = data
        self.source = source
        self.processed = False
        self.result = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "timestamp": self.timestamp,
            "data": self.data,
            "source": self.source,
            "processed": self.processed,
            "result": self.result,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

class EventQueue:
    """イベントキュー管理"""
    def __init__(self, max_size: int = 10000):
        self.queue: list[Event] = []
        self.max_size = max_size
        self.processed_count = 0

    def enqueue(self, event: Event):
        """イベントをキューに追加"""
        if len(self.queue) >= self.max_size:
            self.queue.pop(0)  # 古いイベントを削除
        self.queue.append(event)

    def dequeue(self) -> Event | None:
        """キューからイベントを取り出す"""
        return self.queue.pop(0) if self.queue else None

    def peek(self) -> Event | None:
        """キューの先頭を確認（取り出さない）"""
        return self.queue[0] if self.queue else None

    def size(self) -> int:
        return len(self.queue)

    def clear(self):
        self.queue.clear()
