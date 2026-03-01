"""Tests for utils/helpers.py — pure parsing functions."""

from utils.helpers import (
    parse_devices_output,
    parse_battery_output,
    parse_meminfo,
    parse_df_output,
    parse_cpu_output,
    parse_display_info,
    parse_network_info,
    parse_packages,
    parse_permissions,
    format_bytes,
    parse_logcat_line,
)
from tests.conftest import (
    DEVICES_OUTPUT_MULTI,
    DEVICES_OUTPUT_SINGLE,
    DEVICES_OUTPUT_EMPTY,
    BATTERY_OUTPUT_CHARGING,
    BATTERY_OUTPUT_DISCHARGING,
    MEMINFO_OUTPUT,
    DF_OUTPUT,
    CPU_OUTPUT,
    WIFI_OUTPUT,
    IP_OUTPUT,
    PACKAGES_OUTPUT,
    PERMISSIONS_OUTPUT,
    LOGCAT_LINE_DEBUG,
    LOGCAT_LINE_ERROR,
    LOGCAT_LINE_INFO,
    LOGCAT_LINE_MALFORMED,
)


# --- parse_devices_output ---

class TestParseDevicesOutput:
    def test_multi_device(self):
        devices = parse_devices_output(DEVICES_OUTPUT_MULTI)
        assert len(devices) == 2
        assert devices[0]["serial"] == "ABC123"
        assert devices[0]["state"] == "device"
        assert devices[0]["model"] == "Pixel_6"
        assert devices[1]["serial"] == "XYZ789"
        assert devices[1]["model"] == "Pixel_6_Pro"
        assert devices[1]["transport_id"] == "2"

    def test_single_device(self):
        devices = parse_devices_output(DEVICES_OUTPUT_SINGLE)
        assert len(devices) == 1
        assert devices[0]["serial"] == "emulator-5554"
        assert devices[0]["model"] == "sdk_gphone64_arm64"

    def test_empty(self):
        devices = parse_devices_output(DEVICES_OUTPUT_EMPTY)
        assert devices == []

    def test_malformed_lines(self):
        output = "List of devices attached\n* daemon started\nshort\n"
        devices = parse_devices_output(output)
        assert devices == []

    def test_offline_device(self):
        output = "List of devices attached\nABC123  offline\n"
        devices = parse_devices_output(output)
        assert len(devices) == 1
        assert devices[0]["state"] == "offline"
        assert devices[0]["model"] == "unknown"


# --- parse_battery_output ---

class TestParseBatteryOutput:
    def test_charging(self):
        info = parse_battery_output(BATTERY_OUTPUT_CHARGING)
        assert info["level"] == 85
        assert info["status"] == "Charging"
        assert info["health"] == "Good"
        assert info["temperature"] == 31.0
        assert info["voltage"] == 4200
        assert info["technology"] == "Li-ion"
        assert info["ac_powered"] is True
        assert info["usb_powered"] is False

    def test_discharging(self):
        info = parse_battery_output(BATTERY_OUTPUT_DISCHARGING)
        assert info["level"] == 42
        assert info["status"] == "Discharging"
        assert info["temperature"] == 27.5

    def test_missing_fields(self):
        info = parse_battery_output("Some random output\nno battery here\n")
        assert info == {}

    def test_empty(self):
        info = parse_battery_output("")
        assert info == {}


# --- parse_meminfo ---

class TestParseMeminfo:
    def test_normal(self):
        info = parse_meminfo(MEMINFO_OUTPUT)
        assert info["total_kb"] == 7890124
        assert info["available_kb"] == 3456789
        assert info["free_kb"] == 512340
        assert info["used_kb"] == 7890124 - 3456789

    def test_missing_available(self):
        output = "MemTotal:  4096000 kB\nMemFree:   1024000 kB\n"
        info = parse_meminfo(output)
        assert info["total_kb"] == 4096000
        assert info["free_kb"] == 1024000
        # Falls back to free_kb when available is missing
        assert info["used_kb"] == 4096000 - 1024000

    def test_empty(self):
        info = parse_meminfo("")
        assert info["used_kb"] == 0


# --- parse_df_output ---

class TestParseDfOutput:
    def test_normal(self):
        info = parse_df_output(DF_OUTPUT)
        assert info["total_kb"] == 62914560
        assert info["used_kb"] == 34567890
        assert info["free_kb"] == 28346670

    def test_empty(self):
        info = parse_df_output("")
        assert info == {}

    def test_no_data_partition(self):
        output = "Filesystem  1K-blocks  Used Available Use% Mounted on\n/dev/sda  1000 500 500 50% /boot\n"
        info = parse_df_output(output)
        assert info == {}


# --- parse_cpu_output ---

class TestParseCpuOutput:
    def test_with_processes(self):
        info = parse_cpu_output(CPU_OUTPUT)
        assert info["usage_percent"] == 17  # 100 - 83% idle
        assert len(info["top_processes"]) == 2
        assert info["top_processes"][0]["pid"] == "1234"
        assert info["top_processes"][0]["cpu"] == 8.3
        assert info["top_processes"][0]["name"] == "system_server"

    def test_empty(self):
        info = parse_cpu_output("")
        assert info["usage_percent"] == 0.0
        assert info["top_processes"] == []

    def test_no_idle_format(self):
        output = "%Cpu(s):  25%user,  10%sys,   0%nice\n"
        info = parse_cpu_output(output)
        assert info["usage_percent"] == 35  # user + sys


# --- parse_display_info ---

class TestParseDisplayInfo:
    def test_normal(self):
        info = parse_display_info(
            "Physical size: 1080x2400",
            "Physical density: 420"
        )
        assert info["width"] == 1080
        assert info["height"] == 2400
        assert info["resolution"] == "1080x2400"
        assert info["dpi"] == 420

    def test_missing_size(self):
        info = parse_display_info("", "Physical density: 420")
        assert "width" not in info
        assert info["dpi"] == 420

    def test_missing_density(self):
        info = parse_display_info("Physical size: 1080x2400", "")
        assert info["width"] == 1080
        assert "dpi" not in info

    def test_both_empty(self):
        info = parse_display_info("", "")
        assert info == {}


# --- parse_network_info ---

class TestParseNetworkInfo:
    def test_wifi_connected(self):
        info = parse_network_info(WIFI_OUTPUT, IP_OUTPUT)
        assert info["ssid"] == "HomeNetwork"
        assert info["ip"] == "192.168.1.42"
        assert info["signal"] == "-45 dBm"

    def test_no_wifi(self):
        info = parse_network_info("Wi-Fi is disabled", "wlan0: DOWN")
        assert info["ssid"] == "N/A"
        assert info["ip"] == "N/A"
        assert info["signal"] == "N/A"

    def test_empty(self):
        info = parse_network_info("", "")
        assert info["ssid"] == "N/A"


# --- parse_packages ---

class TestParsePackages:
    def test_multiple(self):
        packages = parse_packages(PACKAGES_OUTPUT)
        assert len(packages) == 3
        assert "com.android.chrome" in packages
        assert "com.spotify.music" in packages
        assert "com.whatsapp" in packages

    def test_empty(self):
        assert parse_packages("") == []

    def test_no_package_prefix(self):
        assert parse_packages("random line\nanother line\n") == []


# --- parse_permissions ---

class TestParsePermissions:
    def test_granted_denied_mix(self):
        perms = parse_permissions(PERMISSIONS_OUTPUT)
        names = {p["name"]: p["granted"] for p in perms}
        assert names["android.permission.CAMERA"] is True
        assert names["android.permission.READ_CONTACTS"] is False
        assert names["android.permission.INTERNET"] is True

    def test_empty(self):
        assert parse_permissions("") == []


# --- format_bytes ---

class TestFormatBytes:
    def test_kb(self):
        assert format_bytes(512) == "512 KB"

    def test_mb(self):
        assert format_bytes(1536) == "1.5 MB"

    def test_gb(self):
        assert format_bytes(2 * 1024 * 1024) == "2.00 GB"

    def test_zero(self):
        assert format_bytes(0) == "0 KB"

    def test_boundary_kb_mb(self):
        assert format_bytes(1023) == "1023 KB"
        assert format_bytes(1024) == "1.0 MB"

    def test_boundary_mb_gb(self):
        assert format_bytes(1024 * 1024 - 1) == "1024.0 MB"
        assert format_bytes(1024 * 1024) == "1.00 GB"


# --- parse_logcat_line ---

class TestParseLogcatLine:
    def test_debug(self):
        result = parse_logcat_line(LOGCAT_LINE_DEBUG)
        assert result is not None
        assert result["level"] == "D"
        assert result["tag"] == "MyTag"
        assert result["message"] == "Debug message here"
        assert result["pid"] == "1234"
        assert result["tid"] == "5678"

    def test_error(self):
        result = parse_logcat_line(LOGCAT_LINE_ERROR)
        assert result["level"] == "E"
        assert result["tag"] == "CrashTag"

    def test_info(self):
        result = parse_logcat_line(LOGCAT_LINE_INFO)
        assert result["level"] == "I"
        assert result["tag"] == "SystemTag"

    def test_all_levels(self):
        for level in "VDIWEFA":
            line = f"01-15 12:34:56.789  1000  2000 {level} Tag: msg"
            result = parse_logcat_line(line)
            assert result is not None
            assert result["level"] == level

    def test_malformed(self):
        assert parse_logcat_line(LOGCAT_LINE_MALFORMED) is None

    def test_empty(self):
        assert parse_logcat_line("") is None
