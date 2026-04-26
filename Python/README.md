# Web Serial Plotter (M5Atom + BME688)

This app reads CSV lines from a serial COM port and serves a realtime graph in your web browser:

- X axis: time (2nd column, relative seconds)
- Y axis: current value (6th column)
- Separate line for each value of the 1st column (0-9)

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

Or run without `--port` to select from detected ports interactively:

```powershell
python serial_plot.py
```

Then open this URL in your browser:

```text
http://127.0.0.1:5000
```

## Logging

- Log files are saved under `Python/logs/`
- File name format: `yyyyMMdd_HHmmss.csv` (application startup time)
- Each logged line prepends current timestamp as the first column:
	- `yyyy/MM/dd HH:mm:ss.fff`

Example logged line:

```text
2026/04/26 15:22:31.123,3,209547,36.67,21.78,101704.55,17.254
```

## Notes

- X axis: relative time from the 2nd column
- Y axis: 6th column value (current)
- Separate line for each 1st-column channel (0-9)
- Click `Reset` in the browser to save latest ch0-ch9 values as baseline
- After Reset, graph switches to delta mode: `updated value - baseline value`
- Logging always stores raw received data (no delta conversion)

## Expected Input Format

```text
3,209547,36.67,21.78,101704.55,17.254
```

Only these fields are used for plotting:

- 1st column: channel/index (0-9)
- 2nd column: timestamp (ms)
- 6th column: plotted current value
