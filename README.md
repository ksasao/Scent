# Scent

Realtime gas sensing and visualization with **M5Atom Lite + ENV Pro (BME688)**.

This repository contains:
- Arduino firmware to read BME688 data (heater profile / gas index 0-9)
- A Python web app to read serial data, validate CRC, plot realtime graphs, and save CSV logs

## Repository Layout

```
Arduino/
	Scent/
		Scent.ino         # M5Atom + BME688 firmware
Python/
	serial_plot.py      # Flask + serial reader + logger
	templates/index.html
	requirements.txt
	logs/               # Runtime-generated raw logs
	data/               # Runtime-generated aggregated CSV
```

## Features

### Arduino (`Arduino/Scent/Scent.ino`)
- Reads BME688 in parallel mode with a 10-step heater profile
- Outputs channel data for gas index `0-9`
- Supports `id` command over serial and returns sensor unique ID (`ID,<8-hex>`) 
- Hot-plug recovery: retries BME688 reinitialization on communication errors
- Watchdog reset if no valid measurement is received for 10 seconds
- Appends **CRC-8** (AUTOSAR polynomial `0x31`) to each data line

### Python (`Python/serial_plot.py`)
- Reads serial data from COM port (`115200` by default)
- Validates incoming lines with the same **CRC-8** algorithm
- Realtime web graph (Chart.js) for channels `D0-D9`
- X-axis uses **relative time in seconds** based on Python receive time
- Reset button for baseline/delta mode
- Auto-reconnect for COM disconnects with exponential backoff
- Logs raw serial lines and writes aggregated rows on D9 timing

## Serial Data Format

Data lines sent from Arduino:

```
index,temp,humidity,pressure,current,crc
```

Example:

```
3,24.71,42.51,100842.89,10.337,A4
```

Notes:
- `index`: `0-9` (gas heater step / channel)
- `current`: `log(gas_resistance)` with 3 decimals
- `crc`: CRC-8 over the text before the final comma

## Python App Setup

### Requirements
- Python 3.10+ recommended
- Windows COM serial environment

Install dependencies:

```powershell
cd Python
python -m pip install -r requirements.txt
```

## Run

Start with explicit COM port:

```powershell
cd Python
python serial_plot.py --port COM3 --baudrate 115200 --host 127.0.0.1 --web-port 5000
```

Or run without `--port`:

```powershell
cd Python
python serial_plot.py
```

When `--port` is omitted:
- If the last successfully communicating COM port exists, it is auto-selected at startup.
- Otherwise, the app starts disconnected and COM selection/connection is done from the browser UI.
- Interactive COM selection in the command line is not used.

Open in browser:

```
http://127.0.0.1:5000
```

## Runtime Outputs

- Raw log files: `Python/logs/YYYYMMDD_HHMMSS.csv`
	- Format: `python_timestamp,raw_serial_line`
- Aggregated files: `Python/data/YYYYMMDD_HHMMSS.csv`
	- Header: `date,temperature,humidity,pressure,d0,d1,...,d9`
	- One row is emitted when channel `9` is received

## Web API (used by UI)

- `GET /` : dashboard
- `GET /data` : latest plot payload
- `POST /reset` : set current values as baseline
- `GET /id` : request sensor unique ID over serial
- `GET /api/ports` : list available COM ports
- `POST /api/connect/<port>` : connect to specified COM port
- `POST /api/disconnect` : disconnect current COM port

## Arduino Build Notes

Required libraries:
- `M5Atom`
- `Bosch BME68x` library (`bme68xLibrary.h`)

I2C pins used by firmware:
- `SDA = 26`
- `SCL = 32`
- BME688 I2C address: `0x77`

## License

See `LICENSE`.
