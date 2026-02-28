"""Parsing utilities for ADB output."""

import logging
import re

logger = logging.getLogger(__name__)


def parse_devices_output(output: str) -> list[dict]:
    """Parse `adb devices -l` output into a list of device dicts."""
    devices = []
    for line in output.strip().splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial = parts[0]
        state = parts[1]
        info = {}
        for part in parts[2:]:
            if ":" in part:
                k, v = part.split(":", 1)
                info[k] = v
        devices.append({
            "serial": serial,
            "state": state,
            "model": info.get("model", "unknown"),
            "device": info.get("device", ""),
            "transport_id": info.get("transport_id", ""),
        })
    return devices


def parse_battery_output(output: str) -> dict:
    """Parse `dumpsys battery` output."""
    info: dict = {}
    for line in output.splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower().replace(" ", "_")
        value = value.strip()
        if key == "level":
            info["level"] = int(value)
        elif key == "status":
            status_map = {"1": "Unknown", "2": "Charging", "3": "Discharging",
                          "4": "Not charging", "5": "Full"}
            info["status"] = status_map.get(value, value)
        elif key == "health":
            health_map = {"1": "Unknown", "2": "Good", "3": "Overheat",
                          "4": "Dead", "5": "Over voltage", "6": "Unspecified failure"}
            info["health"] = health_map.get(value, value)
        elif key == "temperature":
            try:
                info["temperature"] = float(value) / 10.0
            except ValueError:
                info["temperature"] = 0.0
        elif key == "voltage":
            try:
                info["voltage"] = int(value)
            except ValueError:
                info["voltage"] = 0
        elif key == "technology":
            info["technology"] = value
        elif key == "ac_powered":
            info["ac_powered"] = value.lower() == "true"
        elif key == "usb_powered":
            info["usb_powered"] = value.lower() == "true"
    return info


def parse_meminfo(output: str) -> dict:
    """Parse /proc/meminfo output."""
    info: dict = {}
    for line in output.splitlines():
        if line.startswith("MemTotal:"):
            info["total_kb"] = _extract_kb(line)
        elif line.startswith("MemAvailable:"):
            info["available_kb"] = _extract_kb(line)
        elif line.startswith("MemFree:"):
            info["free_kb"] = _extract_kb(line)
    total = info.get("total_kb", 0)
    available = info.get("available_kb", info.get("free_kb", 0))
    info["used_kb"] = total - available
    return info


def _extract_kb(line: str) -> int:
    m = re.search(r"(\d+)", line)
    return int(m.group(1)) if m else 0


def parse_df_output(output: str) -> dict:
    """Parse `df` output for storage info."""
    info: dict = {}
    lines = output.strip().splitlines()
    if len(lines) < 2:
        return info
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 4 and ("/data" in parts[-1] or parts[0] == "/data"):
            try:
                info["total_kb"] = int(parts[1])
                info["used_kb"] = int(parts[2])
                info["free_kb"] = int(parts[3])
            except (ValueError, IndexError):
                pass
            break
    return info


def parse_cpu_output(output: str) -> dict:
    """Parse `top -n 1 -b` output for CPU info."""
    info: dict = {"usage_percent": 0.0, "top_processes": []}
    for line in output.splitlines():
        if "cpu" in line.lower() and "%" in line:
            numbers = re.findall(r"(\d+)%", line)
            if numbers:
                idle = 0
                m = re.search(r"(\d+)%idle", line.replace(" ", ""))
                if m:
                    idle = int(m.group(1))
                    info["usage_percent"] = 100 - idle
                else:
                    user = int(numbers[0]) if len(numbers) > 0 else 0
                    sys_ = int(numbers[1]) if len(numbers) > 1 else 0
                    info["usage_percent"] = user + sys_
                break
    proc_count = 0
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 9 and parts[0].isdigit() and proc_count < 5:
            try:
                cpu_str = parts[8].replace("%", "")
                cpu_val = float(cpu_str)
                name = parts[-1] if len(parts) > 9 else parts[8]
                info["top_processes"].append({"pid": parts[0], "cpu": cpu_val, "name": name})
                proc_count += 1
            except (ValueError, IndexError):
                continue
    return info


def parse_display_info(size_output: str, density_output: str) -> dict:
    """Parse wm size and wm density output."""
    info: dict = {}
    m = re.search(r"(\d+)x(\d+)", size_output)
    if m:
        info["width"] = int(m.group(1))
        info["height"] = int(m.group(2))
        info["resolution"] = f"{m.group(1)}x{m.group(2)}"
    m = re.search(r"(\d+)", density_output)
    if m:
        info["dpi"] = int(m.group(1))
    return info


def parse_network_info(wifi_output: str, ip_output: str) -> dict:
    """Parse network information from dumpsys wifi and ip addr."""
    info: dict = {"ssid": "N/A", "ip": "N/A", "signal": "N/A"}
    m = re.search(r'SSID:\s*"?([^",\n]+)"?', wifi_output)
    if not m:
        m = re.search(r'mWifiInfo.*?SSID:\s*"?([^",\n]+)"?', wifi_output)
    if m:
        info["ssid"] = m.group(1).strip().strip('"')
    m = re.search(r'inet\s+([\d.]+).*wlan0', ip_output, re.DOTALL)
    if not m:
        m = re.search(r'wlan0.*?inet\s+([\d.]+)', ip_output, re.DOTALL)
    if m:
        info["ip"] = m.group(1)
    m = re.search(r'rssi[=:]\s*(-?\d+)', wifi_output, re.IGNORECASE)
    if not m:
        m = re.search(r'mRssi[=:]\s*(-?\d+)', wifi_output, re.IGNORECASE)
    if m:
        info["signal"] = f"{m.group(1)} dBm"
    return info


def parse_packages(output: str) -> list[str]:
    """Parse `pm list packages` output into package names."""
    packages = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            packages.append(line[8:])
    return packages


def parse_permissions(output: str) -> list[dict]:
    """Parse package permissions from dumpsys package output."""
    permissions: list[dict] = []
    in_requested = False
    in_install = False
    granted_map: dict[str, bool] = {}

    for line in output.splitlines():
        stripped = line.strip()
        if "install permissions:" in stripped or "runtime permissions:" in stripped:
            in_install = True
            continue
        if "requested permissions:" in stripped:
            in_requested = True
            in_install = False
            continue
        if stripped.startswith("User ") or (stripped and not stripped.startswith("android.") and "." not in stripped and in_requested):
            if not stripped.startswith("android.permission") and not stripped.startswith("com.") and not stripped.startswith("org."):
                in_requested = False
                continue

        if in_install and ": granted=" in stripped:
            perm_name = stripped.split(":")[0].strip()
            granted = "granted=true" in stripped
            granted_map[perm_name] = granted

        if in_requested and ("android." in stripped or "com." in stripped or "org." in stripped):
            perm = stripped.rstrip(",").strip()
            if perm:
                permissions.append({"name": perm, "granted": granted_map.get(perm, False)})

    return permissions


def format_bytes(kb: int) -> str:
    """Format kilobytes into a human-readable string."""
    if kb < 1024:
        return f"{kb} KB"
    elif kb < 1024 * 1024:
        return f"{kb / 1024:.1f} MB"
    else:
        return f"{kb / (1024 * 1024):.2f} GB"


def parse_logcat_line(line: str) -> dict | None:
    """Parse a single logcat line into components."""
    m = re.match(
        r"(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+"
        r"(\d+)\s+(\d+)\s+([VDIWEFA])\s+"
        r"(.+?):\s*(.*)",
        line,
    )
    if m:
        return {
            "timestamp": m.group(1),
            "pid": m.group(2),
            "tid": m.group(3),
            "level": m.group(4),
            "tag": m.group(5).strip(),
            "message": m.group(6),
        }
    return None
