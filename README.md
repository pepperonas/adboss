# ADBOSS

**Android Debug Bridge Desktop Manager** — A PySide6/Qt6 desktop application for controlling Android devices via ADB.

ADBOSS provides a unified control panel for device monitoring, system settings, app management, file transfer, shell access, and live logcat viewing — all from a single dark-themed GUI.

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![Qt](https://img.shields.io/badge/GUI-PySide6%20(Qt6)-green)
![License](https://img.shields.io/badge/License-MIT-yellow)
![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)

---

## Features

### Dashboard
Real-time device overview with auto-refresh (configurable, default 5s):
- **Device Info** — Model, Manufacturer, Android Version, Build ID, SDK, Serial, Uptime
- **Battery Gauge** — Circular arc visualization with color coding (green >50%, yellow >20%, red ≤20%), plus temperature, voltage, health, charging status
- **RAM & Storage Bars** — Horizontal progress bars with used/total display and color-coded thresholds
- **Network Info** — WiFi SSID, IP address, signal strength (dBm)
- **Display Info** — Resolution and DPI

### Device Control
- **Battery Simulation** — Slider (0–100) to fake battery level for testing, with reset to real values
- **Brightness** — Slider (0–255), applies on release, auto-disables adaptive brightness
- **Volume** — Three independent sliders for Media, Ringtone, and Alarm streams (0–15)
- **Toggles** — WiFi, Bluetooth, Airplane Mode, Do Not Disturb (on/off buttons with state display)
- **Screen** — Wake, Sleep, Lock buttons + screen timeout dropdown (15s to 30min)
- **Developer Options** — Layout Bounds and GPU Overdraw toggles

### App Manager
- **Searchable Package Table** — Package name, version, install date; filterable by name
- **System App Filter** — Toggle visibility of system packages
- **App Actions** — Launch, Force Stop, Uninstall (with confirmation), Clear Data
- **Enable/Disable** — Disable bloatware without uninstalling (via context menu)
- **Permissions Dialog** — View all app permissions, grant/revoke with checkboxes
- **APK Install** — File picker dialog or drag & drop `.apk` files onto the tab
- **Background Loading** — Package list loads in a background thread

### File Transfer
- **Dual-Pane Browser** — Device (remote) on the left, Desktop (local) on the right, resizable splitter
- **Navigation** — Editable path bar, Up button, double-click to enter directories
- **Push & Pull** — Buttons for explicit transfer, or drag & drop files between panels
- **Progress Bar** — Real-time transfer progress parsed from ADB stderr
- **Screenshot** — Capture device screen, save as PNG, preview in popup dialog
- **Screen Recording** — Start/Stop recording to `/sdcard/record.mp4` with elapsed time display
- **Path Memory** — Last used local and remote paths are persisted across sessions

### ADB Shell
- **Terminal Emulator** — Dark background, monospace font, color-coded output
- **Command History** — Up/Down arrow navigation, stores last 100 commands
- **Timestamps** — Every command and output block is timestamped
- **Quick Actions** — One-click buttons for Reboot, Bootloader, Recovery, getprop, ps, df
- **Non-blocking** — Commands execute in a background thread

### Logcat Viewer
- **Live Streaming** — Real-time logcat output via background thread
- **Color Coding** — Verbose (gray), Debug (blue), Info (green), Warning (yellow), Error (red), Fatal (purple)
- **Filters** — Log level dropdown, tag filter, PID filter, free-text search — all combinable
- **Pause/Resume** — Pause display while buffering continues
- **Auto-Scroll** — Toggleable, enabled by default
- **Export** — Save buffered logcat to `.txt` file
- **Buffer Limit** — Configurable max 5000 lines (oldest lines trimmed)

### General
- **Dark Theme** — Full QSS stylesheet with cyan (#00BCD4) accent color
- **Multi-Device** — Device selector dropdown with auto-detection (polls every 3s)
- **Status Bar** — Connection status, last action result, copyright
- **Responsive** — Freely resizable, minimum 900×600, window size persisted
- **Graceful Shutdown** — All threads, timers, and subprocesses cleaned up on exit

---

## Prerequisites

- **Python 3.11+**
- **ADB** installed and in your PATH (or configured manually in `~/.adboss/config.json`)
- **USB Debugging** enabled on your Android device

### Installing ADB

```bash
# macOS
brew install android-platform-tools

# Ubuntu/Debian
sudo apt install android-tools-adb

# Windows (via scoop)
scoop install adb
```

Verify: `adb version`

---

## Installation

```bash
git clone https://github.com/pepperonas/adboss.git
cd adboss
python3 -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

```bash
source venv/bin/activate
python main.py
```

Connect your Android device via USB (with USB Debugging enabled) or via `adb connect <ip>:<port>` for wireless debugging. ADBOSS will detect the device automatically within 3 seconds.

---

## Project Structure

```
adboss/
├── main.py                         # Entry point
├── requirements.txt                # PySide6
├── assets/
│   ├── icon.png                    # App icon (generated)
│   └── styles.qss                  # Dark theme stylesheet (430+ lines)
├── core/
│   ├── adb_client.py               # ADB wrapper (48 methods, all subprocess calls)
│   ├── device_monitor.py           # QThread for periodic device stats
│   └── file_transfer.py            # QThread for push/pull with progress
├── ui/
│   ├── main_window.py              # Main window, tab container, menu, status bar
│   ├── dashboard_tab.py            # Device info, battery gauge, storage bars
│   ├── control_tab.py              # Brightness, volume, toggles, screen
│   ├── apps_tab.py                 # Package list, install, permissions
│   ├── files_tab.py                # Dual-pane file browser, drag & drop
│   ├── shell_tab.py                # ADB shell terminal
│   ├── logcat_tab.py               # Live logcat with filters
│   └── widgets/
│       ├── battery_widget.py       # Circular gauge (custom QPainter)
│       ├── storage_widget.py       # Labeled progress bar
│       └── device_selector.py      # Auto-refreshing device dropdown
└── utils/
    ├── config.py                   # JSON config (~/.adboss/config.json)
    └── helpers.py                  # ADB output parsers (10 parse functions)
```

---

## Architecture

### ADB Wrapper

All ADB interaction goes through `core/adb_client.py`. No raw `subprocess` calls exist elsewhere. The `ADBClient` class:

- Automatically prefixes `adb -s <serial>` for multi-device support
- Enforces per-command timeouts (10s default, up to 600s for backups)
- Returns empty strings on failure instead of raising exceptions
- Delegates all output parsing to pure functions in `utils/helpers.py`

### Threading

The GUI thread never blocks. Five worker types handle ADB I/O:

| Worker | Type | Purpose |
|--------|------|---------|
| `DeviceMonitor` | One-shot QThread | Collects all dashboard stats per refresh cycle |
| `FileTransferWorker` | Long-running QThread | Push/Pull with real-time progress |
| `PackageLoader` | One-shot QThread | Loads package list with version info |
| `ShellWorker` | One-shot QThread | Executes single shell commands |
| `LogcatReader` | Long-running QThread | Streams logcat lines continuously |

All thread→UI communication uses Qt signals/slots.

### Configuration

Stored at `~/.adboss/config.json`, auto-created on first run:

| Key | Default | Description |
|-----|---------|-------------|
| `adb_path` | auto-detected | Path to ADB binary |
| `refresh_interval_ms` | 5000 | Dashboard refresh interval |
| `device_poll_interval_ms` | 3000 | Device detection polling |
| `window_width` / `window_height` | 1100 / 750 | Window size (persisted) |
| `logcat_max_lines` | 5000 | Logcat buffer limit |
| `shell_history_max` | 100 | Shell command history size |
| `last_local_path` | `$HOME` | File browser local path |
| `last_remote_path` | `/sdcard/` | File browser remote path |

---

## ADB Command Coverage

ADBOSS wraps **48 ADB commands** across 10 categories:

| Category | Commands | Examples |
|----------|----------|---------|
| Device Info | 9 | `getprop`, `dumpsys battery`, `/proc/meminfo`, `df`, `top`, `wm size/density`, `dumpsys wifi` |
| Device Control | 10 | `settings put system screen_brightness`, `media volume`, `svc wifi`, `input keyevent` |
| App Management | 12 | `pm list packages`, `pm install/uninstall`, `am force-stop`, `pm grant/revoke`, `pm clear` |
| File Transfer | 6 | `adb push/pull`, `screencap`, `screenrecord`, `ls -la` |
| Shell & Logcat | 2 | `adb shell`, `adb logcat` |
| Input Simulation | 4 | `input tap/swipe/text/keyevent` |
| Backup | 1 | `adb backup` |
| Developer | 2 | `setprop debug.layout`, `setprop debug.hwui.overdraw` |
| Reboot | 1 | `adb reboot [bootloader\|recovery]` |
| Detection | 1 | `adb devices -l` |

---

## Theming

The dark theme is defined in `assets/styles.qss` with these design tokens:

| Role | Color |
|------|-------|
| Background | `#1e1e1e` |
| Surface | `#252526` |
| Widget BG | `#2d2d2d` |
| Text | `#d4d4d4` |
| Muted | `#888888` |
| Accent | `#00BCD4` (Cyan) |
| Accent Dark | `#00838F` (Teal) |
| Success | `#4CAF50` (Green) |
| Warning | `#FFC107` (Amber) |
| Error | `#F44336` (Red) |
| Fatal | `#E040FB` (Purple) |

The stylesheet covers all Qt widgets (buttons, sliders, tabs, tables, trees, scrollbars, dialogs, menus, tooltips) for a consistent appearance.

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| PySide6 | ≥ 6.6.0 | Qt6 GUI framework |

No external ADB libraries — all device communication uses Python's `subprocess` module for maximum control and transparency.

---

## License

MIT

---

**© 2026 Martin Pfeffer | [celox.io](https://celox.io)**
