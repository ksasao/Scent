# Python Utilities

Python-based viewer/runtime files were removed. This folder now contains only maintenance tools.

## Remaining tools

- `make_icon.py`: regenerate `Scent.ico` from the current icon design
- `sync_firmware_assets.py`: sync firmware/web flasher assets between Arduino build outputs, `WebFlasher/`, and `docs/firmware/`

## Setup (Windows PowerShell)

```powershell
cd Python
py -m pip install -r requirements.txt
```

## Regenerate icon

```powershell
py make_icon.py
```

Output:

```text
Python/Scent.ico
```

## Sync firmware assets

Build only (Arduino build outputs -> WebFlasher):

```powershell
py sync_firmware_assets.py build
```

Deploy only (WebFlasher -> docs/firmware):

```powershell
py sync_firmware_assets.py deploy
```

Run both:

```powershell
py sync_firmware_assets.py
```
