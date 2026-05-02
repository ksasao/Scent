"""Filesystem, timestamp, and COM-port helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from serial.tools import list_ports


def now_text() -> str:
    return datetime.now().strftime("%Y/%m/%d %H:%M:%S.%f")[:-3]


def create_output_files() -> Tuple[Path, Path]:
    base_dir = Path(__file__).resolve().parent.parent
    log_dir = base_dir / "logs"
    data_dir = base_dir / "data"
    log_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    filename = datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
    data_file = data_dir / filename
    with data_file.open("w", encoding="utf-8", newline="") as f:
        f.write("date,temperature,humidity,pressure,d0,d1,d2,d3,d4,d5,d6,d7,d8,d9\n")
    return log_dir / filename, data_file


def last_good_port_file() -> Path:
    return Path(__file__).resolve().parent.parent / "last_good_port.txt"


def load_last_good_port() -> str | None:
    path = last_good_port_file()
    try:
        if not path.exists():
            return None
        port = path.read_text(encoding="utf-8").strip()
        return port or None
    except Exception:
        return None


def save_last_good_port(port: str) -> None:
    path = last_good_port_file()
    try:
        path.write_text(port, encoding="utf-8")
    except Exception:
        # Persistence failure should not interrupt acquisition.
        pass


def available_ports() -> List[str]:
    return [p.device for p in list_ports.comports()]
