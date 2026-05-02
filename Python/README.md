# Web Serial Plotter (M5Atom + BME688)

This app reads CSV lines from a serial COM port, validates CRC-8, and serves a realtime graph in a browser or an embedded desktop window.

## Setup (Windows PowerShell)

```powershell
cd Python
py -m pip install -r requirements.txt
```

## Run

Browser version:

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

Desktop window version:

```powershell
python desktop_main.py --port COM3
```

Or without `--port`:

```powershell
python desktop_main.py
```

The desktop version opens the same UI inside a native window using WebView2 on Windows 11.

## Build EXE for Windows 11

Run in Windows PowerShell:

```powershell
cd Python
```

Install dependencies (first time only):

```powershell
py -m pip install -r requirements.txt
```

Generate the application icon from the current icon design:

```powershell
py make_icon.py
```

Optional: update `WebFlasher/` with the latest Arduino build outputs (run after rebuilding in Arduino IDE):

```powershell
py sync_firmware_assets.py build
```

This generates `WebFlasher/flash_config.json` and copies the firmware binaries into `WebFlasher/firmware/`. You can open `WebFlasher/` with a local server to verify flashing before publishing.

Optional: deploy `WebFlasher/` contents to `docs/firmware/` for publishing:

```powershell
py sync_firmware_assets.py deploy
```

This copies `index.html`, `style.css`, `flasher.js`, `flash_config.json`, and `firmware/*.bin` from `WebFlasher/` into `docs/firmware/`, and regenerates `manifest.json`.

To run both steps at once:

```powershell
py sync_firmware_assets.py
```

Optional: stop a running desktop app before rebuild:

```powershell
Get-Process Scent -ErrorAction SilentlyContinue | Stop-Process -Force
```

Create the distributable app:

```powershell
py -m PyInstaller --noconfirm --clean --windowed --onedir --name Scent --icon Scent.ico --add-data "templates;templates" --add-data "static;static" --collect-all webview desktop_main.py
```

Output folder:

```text
Python/dist/Scent/
```

Quick check:

```powershell
Test-Path .\dist\Scent\Scent.exe
```

Notes:

- `requirements.txt` includes both runtime and Windows build dependencies.
- `templates` and `static` are bundled automatically.
- `make_icon.py` regenerates `Scent.ico` from the current icon design before building.
- `WebView2 Runtime` must be present on the target Windows 11 machine.

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
- Desktop mode uses the same HTML UI inside an embedded window.

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

## Code Structure

- `serial_plot.py`: thin entrypoint (argument parsing, startup, thread launch)
- `desktop_main.py`: Windows desktop launcher using embedded WebView
- `make_icon.py`: generates `Scent.ico` used by PyInstaller
- `scent_web/config.py`: runtime constants (timeouts, retry limits, flush interval)
- `scent_web/crc.py`: CRC-8 table and calculation
- `scent_web/state.py`: shared runtime state object
- `scent_web/runtime.py`: shared bootstrap for CLI and desktop launchers
- `scent_web/utils.py`: timestamps, file/port helpers, persistence
- `scent_web/serial_worker.py`: serial parsing and acquisition loop
- `scent_web/web_app.py`: Flask app factory and API routes
