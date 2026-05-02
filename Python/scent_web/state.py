"""Shared state for serial acquisition and web APIs."""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from datetime import datetime
from typing import Deque, Dict, Tuple

import serial


Point = Tuple[float, float]


class SharedState:
    def __init__(self, max_points: int) -> None:
        self.data: Dict[int, Deque[Point]] = defaultdict(lambda: deque(maxlen=max_points))
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.running = False
        self.error_message = ""
        self.log_file = ""
        self.data_file = ""
        self.baseline: Dict[int, float] | None = None
        self.reset_at: float | None = None
        self.reset_at_text: str | None = None
        self.ser_ref: serial.Serial | None = None
        self.id_event = threading.Event()
        self.id_response: str | None = None
        self.start_time: datetime | None = None
        self.requested_port: str | None = None
        self.port_change_event = threading.Event()
        self.last_rx_monotonic: float | None = None
        self.connected_monotonic: float | None = None
