# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

ADBOSS is a PySide6 (Qt6) desktop app that controls Android devices via ADB. All ADB interaction goes through `subprocess` — no external ADB libraries.

## Development Commands

```bash
# Setup
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt

# Run
source venv/bin/activate && python main.py

# Verify imports (no device needed)
python -c "from ui.main_window import MainWindow; print('OK')"
```

No test framework is configured yet. Parsing functions in `utils/helpers.py` are pure and can be unit-tested without a device.

## Architecture

### Layered Design

```
main.py → MainWindow → 6 Tabs (each with own QThread workers)
                ↓
           ADBClient (single shared instance, all ADB goes through here)
                ↓
           subprocess.run / Popen → adb binary
```

### ADBClient Is the Only ADB Gateway

Every ADB command flows through `core/adb_client.py`. Never call `subprocess` for ADB elsewhere. The client:
- Prefixes `adb -s <serial>` automatically for multi-device
- Enforces timeouts (default 10s, up to 600s for backups)
- Returns empty string on failure (never raises for ADB errors)
- Logs all commands at DEBUG level

### Threading Model

The GUI thread must never block. Three threading patterns are used:

1. **One-shot QThread** (DeviceMonitor, PackageLoader, ShellWorker) — created per operation, collects data, emits signals, finishes
2. **Long-running QThread** (LogcatReader, FileTransferWorker) — streams data continuously via signals until stopped
3. **QTimer polling** — DeviceSelector polls `adb devices` every 3s, dashboard refreshes every 5s

All thread→UI communication uses Qt signals/slots (thread-safe).

### Device Context Flow

`MainWindow` owns one `ADBClient` instance. On device switch:
1. `ADBClient.device_serial` is updated
2. All 6 tabs receive it via `tab.set_adb(self._adb)`
3. Dashboard refresh cycle restarts

`DeviceSelector` has its own separate `ADBClient` (no serial) just for polling `adb devices -l`.

### Config

Singleton at `utils/config.py` → persists to `~/.adboss/config.json`. Smart ADB path detection: checks configured path → `shutil.which("adb")` → falls back to `"adb"`.

### Parsing

All ADB output parsing lives in `utils/helpers.py` as pure functions. ADBClient methods call the parser and return dicts. This keeps parsing testable without devices.

## Adding Features

1. New ADB command → add method to `ADBClient`, add parser to `helpers.py` if needed
2. New UI control → add to the appropriate tab, use `self._run(label, self._adb.method, args)` pattern for error handling + status bar feedback
3. New config key → add default to `DEFAULT_CONFIG` in `utils/config.py`
4. Long-running operation → must use QThread with signal emission, never block GUI thread

## Key Conventions

- `status_message = Signal(str)` on every tab — connected to MainWindow status bar
- Tabs are independent; they share state only through the injected ADBClient
- QSS theming in `assets/styles.qss`, accent color `#00BCD4`
- Copyright: `© 2026 Martin Pfeffer | celox.io`
