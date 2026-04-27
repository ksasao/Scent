# Web Serial Plotter (M5Atom + BME688)

This app reads CSV lines from a serial COM port, validates CRC-8, and serves a realtime graph in your browser.

## Setup (Windows PowerShell)

```powershell
cd Python
python -m pip install -r requirements.txt
```

## Run

Specify COM port directly:

```powershell
python serial_plot.py --port COM3 --baudrate 115200 --host 127.0.0.1 --web-port 5000
```

Or run without `--port`:

```powershell
python serial_plot.py
```

When `--port` is omitted:

- If the last successfully communicating COM port exists, it is auto-selected at startup.
- Otherwise, the app starts disconnected and you select/connect from the browser UI.
- Interactive COM selection in the command line is not used.

Open this URL in your browser:

```text
http://127.0.0.1:5000
```

## Serial Input Format

Expected line format:

```text
index,temp,humidity,pressure,current,crc
```

Example:

```text
3,24.71,42.51,100842.89,10.337,A4
```

Field notes:

- `index`: channel `0-9`
- `temp`: temperature
- `humidity`: relative humidity
- `pressure`: pressure
- `current`: `log(gas_resistance)` value
- `crc`: CRC-8 (AUTOSAR polynomial `0x31`) of text before the final comma

## Plot Behavior

- 10 lines are plotted (`D0` to `D9`) based on `index`
- X axis uses relative seconds from Python receive time (not Arduino timestamp)
- Y axis uses `current`
- `Reset` stores baseline and switches to delta mode

## Web UI

- COM port dropdown + single `Connect/Disconnect` toggle button
- Dropdown is disabled while connected
- Communication indicator:
	- green dot: normal
	- red dot: abnormal

## Logging

- Raw log files: `Python/logs/YYYYMMDD_HHMMSS.csv`
	- each line: `python_timestamp,raw_serial_line`
- Aggregated files: `Python/data/YYYYMMDD_HHMMSS.csv`
	- header: `date,temperature,humidity,pressure,d0,d1,...,d9`
	- one row is emitted when channel `9` is received

## API Endpoints

- `GET /`: dashboard
- `GET /data`: latest graph payload and status
- `POST /reset`: set baseline
- `GET /id`: request sensor unique ID (`id` command)
- `GET /api/ports`: list available COM ports
- `POST /api/connect/<port>`: request connection to COM port
- `POST /api/disconnect`: disconnect current COM port
