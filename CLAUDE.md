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

# Run all tests
pytest tests/ -v --tb=short

# Run single test file / class / method
pytest tests/test_helpers.py -v
pytest tests/test_helpers.py::TestParseDevicesOutput -v
pytest tests/test_helpers.py::TestParseDevicesOutput::test_multi_device -v

# Coverage
pytest --cov=. --cov-report=term-missing

# Build macOS app (also: pyinstaller ADBOSS.spec --noconfirm)
pyinstaller --name "ADBOSS" --windowed --icon assets/icon.icns --add-data "assets:assets" --noconfirm main.py
```

## Architecture

### Layered Design

```
main.py → MainWindow → 9 Tabs (each with own QThread workers)
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

1. **One-shot QThread** (DeviceMonitor, PackageLoader, ShellWorker, SettingsLoaderThread) — created per operation, collects data, emits signals, finishes
2. **Long-running QThread** (LogcatReader, FileTransferWorker) — streams data continuously via signals until stopped
3. **QTimer polling** — DeviceSelector polls `adb devices` every 3s, dashboard refreshes every 5s

All thread-to-UI communication uses Qt signals/slots (thread-safe).

### Device Context Flow

`MainWindow` owns one `ADBClient` instance. On device switch:
1. `ADBClient.device_serial` is updated
2. All 9 tabs receive it via `tab.set_adb(self._adb)`
3. Dashboard refresh cycle restarts

`DeviceSelector` has its own separate `ADBClient` (no serial) for polling `adb devices -l`, plus a reference to the shared ADBClient via `set_shared_adb()` for WiFi ADB features (TCP/IP switching, IP auto-detection).

### Config

Singleton at `utils/config.py` → persists to `~/.adboss/config.json`. Smart ADB path detection: checks configured path → `shutil.which("adb")` → falls back to `"adb"`.

### Parsing

All ADB text output parsing lives in `utils/helpers.py` as pure functions. ADBClient methods call the parser and return dicts. This keeps parsing testable without devices.

Binary protocol parsing (Bluetooth HCI/btsnoop) lives in `core/bluetooth_parser.py` as a separate module since it operates on `bytes` not `str`, uses `struct` for decoding, and has its own dataclasses (`HCIPacket`, `CaptureStats`). The Bluetooth tab pulls raw binary data via `adb exec-out cat` rather than the usual `adb shell` text pipeline.

### Tests

Tests live in `tests/` using pytest. `conftest.py` provides a `mock_adb` fixture that patches subprocess and config. All tests are pure — no real ADB device needed. CI runs on Python 3.11/3.12/3.13 via `.github/workflows/tests.yml`.

## Adding Features

1. New ADB command → add method to `ADBClient`, add parser to `helpers.py` if needed
2. New UI control → add to the appropriate tab, use `self._run(label, self._adb.method, args)` pattern for error handling + status bar feedback
3. New tab → create `ui/new_tab.py` with `status_message = Signal(str)` and `set_adb()`, register in `main_window.py` (_build_ui, _connect_signals, _on_device_changed), add keyboard shortcut in `_build_menu`
4. New config key → add default to `DEFAULT_CONFIG` in `utils/config.py`
5. Long-running operation → must use QThread with signal emission, never block GUI thread

## Keyboard Shortcuts

All defined in `MainWindow._build_menu()`:
- `Ctrl+1`..`Ctrl+9` — Switch to tab (Dashboard, Control, Apps, Files, Shell, Logcat, Input, Settings, Bluetooth)
- `Ctrl+R` — Context-dependent refresh (Dashboard/Apps/Files/Settings/Bluetooth)
- `Ctrl+L` — Logcat Start/Stop toggle
- `Ctrl+K` — Logcat Clear
- `Ctrl+Shift+S` — Screenshot (Files tab)
- `Ctrl+Q` — Quit

## LogcatView Scroll Architecture

`LogcatView` (QPlainTextEdit subclass in `ui/logcat_tab.py`) has critical scroll-management logic:

- **Follow mode** (`_follow=True`): inserts text at document end, scrolls to bottom
- **Frozen mode** (`_follow=False`): inserts text but preserves scroll position via `bar.setValue(old_val)` + deferred `QTimer.singleShot(0)` restore (counters async Qt `_q_adjustScrollbars`)
- **Trimming suspended** while frozen: `maxBlockCount` is set to 0 to prevent content at the viewport from being replaced. Restored when follow re-enables.
- **Auto-follow detection** uses `verticalScrollBar().actionTriggered` (not `valueChanged`) — only fires on real user actions (wheel, click, drag), never on programmatic `setValue()`
- **Cursor anchoring**: `set_follow(False)` moves widget cursor into viewport to prevent `ensureCursorVisible()` from fighting scroll position

Do NOT simplify this logic — each piece solves a specific Qt behavior that caused viewport drift during extensive testing.

## Key Conventions

- `status_message = Signal(str)` on every tab — connected to MainWindow status bar
- Tabs are independent; they share state only through the injected ADBClient
- Version single source of truth: `version.py`
- QSS theming in `assets/styles.qss`, accent color `#00BCD4`
- Copyright: `(c) 2026 Martin Pfeffer | celox.io`
- Release workflow (`.github/workflows/release.yml`) triggers on `v*` tags, builds for macOS/Linux/Windows
