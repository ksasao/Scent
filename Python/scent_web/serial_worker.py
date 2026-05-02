"""Serial parsing and reader thread implementation."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, Tuple

import serial

from .config import BASE_RETRY_DELAY, LOG_FLUSH_INTERVAL_S, MAX_RETRIES
from .crc import crc8
from .state import SharedState
from .utils import create_output_files, now_text, save_last_good_port


def parse_line(line: str) -> Tuple[int, float, float, float, float] | None:
    parts = line.strip().split(",")
    if len(parts) < 6:
        return None

    try:
        channel = int(parts[0])
        temp = float(parts[1])
        humidity = float(parts[2])
        pressure = float(parts[3])
        current = float(parts[4])
        received_checksum = parts[5].upper()
    except (ValueError, IndexError):
        return None

    if not (0 <= channel <= 9):
        return None

    data_str = ",".join(parts[:5])
    calculated_crc = crc8(data_str)
    if f"{calculated_crc:X}" != received_checksum:
        return None

    return channel, temp, humidity, pressure, current


def serial_reader(port: str | None, baudrate: int, state: SharedState) -> None:
    log_file, data_file = create_output_files()
    state.log_file = str(log_file)
    state.data_file = str(data_file)

    if port:
        state.requested_port = port

    last_values: Dict[int, float] = {}
    d0_datetime = ""
    d0_temp: float | None = None
    d0_humidity: float | None = None
    d0_pressure: float | None = None

    retry_count = 0
    max_retries = MAX_RETRIES
    base_retry_delay = BASE_RETRY_DELAY

    while not state.stop_event.is_set():
        current_port = state.requested_port
        if not current_port:
            time.sleep(0.5)
            continue

        try:
            state.running = True
            state.error_message = ""

            with serial.Serial(port=current_port, baudrate=baudrate, timeout=1) as ser:
                state.ser_ref = ser
                state.connected_monotonic = time.monotonic()
                state.last_rx_monotonic = None
                port_marked_good = False
                retry_count = 0
                print(f"[{now_text()}] Connected to {current_port}")

                with log_file.open("a", encoding="utf-8", newline="") as log_fp, data_file.open("a", encoding="utf-8", newline="") as data_fp:
                    log_flush_interval_s = LOG_FLUSH_INTERVAL_S
                    last_log_flush_mono = time.monotonic()
                    log_dirty = False
                    try:
                        while not state.stop_event.is_set():
                            try:
                                if state.requested_port != current_port:
                                    next_port = state.requested_port
                                    if next_port is None:
                                        print(f"[{now_text()}] Disconnected from {current_port}")
                                    else:
                                        print(f"[{now_text()}] Port switch requested: {current_port} -> {next_port}")
                                    break

                                raw = ser.readline()
                                if not raw:
                                    continue
                                line = raw.decode("utf-8", errors="ignore")
                                line_clean = line.strip()

                                if line_clean.startswith("ID,"):
                                    state.id_response = line_clean
                                    state.id_event.set()
                                    continue

                                parsed = parse_line(line)
                                if parsed is None:
                                    continue

                                if line_clean:
                                    log_fp.write(f"{now_text()},{line_clean}\n")
                                    log_dirty = True

                                channel, temp, humidity, pressure, value = parsed
                                now_mono = time.monotonic()
                                state.last_rx_monotonic = now_mono
                                if not port_marked_good:
                                    save_last_good_port(current_port)
                                    port_marked_good = True
                                if log_dirty and (now_mono - last_log_flush_mono) >= log_flush_interval_s:
                                    log_fp.flush()
                                    last_log_flush_mono = now_mono
                                    log_dirty = False

                                now = datetime.now()
                                if state.start_time is None:
                                    state.start_time = now
                                t_sec = (now - state.start_time).total_seconds()

                                last_values[channel] = value

                                if channel == 0:
                                    d0_datetime = now_text()
                                    d0_temp = temp
                                    d0_humidity = humidity
                                    d0_pressure = pressure

                                if (
                                    channel == 9
                                    and len(last_values) == 10
                                    and d0_datetime
                                    and d0_temp is not None
                                    and d0_humidity is not None
                                    and d0_pressure is not None
                                ):
                                    row = [
                                        d0_datetime,
                                        f"{d0_temp:.2f}",
                                        f"{d0_humidity:.2f}",
                                        f"{d0_pressure:.2f}",
                                    ] + [f"{last_values[d]:.3f}" for d in range(10)]
                                    data_fp.write(",".join(row) + "\n")
                                    data_fp.flush()

                                with state.lock:
                                    state.data[channel].append((t_sec, value))
                            except Exception as read_exc:
                                print(f"[{now_text()}] Serial read error: {read_exc}")
                                state.error_message = f"Serial read error: {read_exc}"
                                raise
                    finally:
                        if log_dirty:
                            log_fp.flush()
        except Exception as exc:
            state.ser_ref = None
            state.running = False

            if state.stop_event.is_set():
                break

            retry_count += 1
            if retry_count > max_retries:
                error_msg = f"Failed to connect after {max_retries} retries: {exc}"
                print(f"[{now_text()}] {error_msg}")
                state.error_message = error_msg
                state.running = False
                state.requested_port = None
                retry_count = 0
                print(f"[{now_text()}] Waiting for new port selection...")
                time.sleep(1.0)
                continue

            wait_time = min(base_retry_delay * (2 ** (retry_count - 1)), 30.0)
            print(
                f"[{now_text()}] Connection lost ({exc}). Retrying in {wait_time:.1f}s "
                f"(attempt {retry_count}/{max_retries})..."
            )
            state.error_message = f"Reconnecting... (attempt {retry_count}/{max_retries})"

            time.sleep(wait_time)
        finally:
            state.ser_ref = None
            state.running = False
            state.connected_monotonic = None
