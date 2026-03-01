"""Shared fixtures and sample data for ADBOSS tests."""

import pytest
from unittest.mock import patch, MagicMock

# --- Sample ADB output strings ---

DEVICES_OUTPUT_MULTI = """\
List of devices attached
ABC123         device usb:1-1 product:oriole model:Pixel_6 device:oriole transport_id:1
XYZ789         device usb:1-2 product:raven model:Pixel_6_Pro device:raven transport_id:2

"""

DEVICES_OUTPUT_SINGLE = """\
List of devices attached
emulator-5554  device product:sdk_gphone64 model:sdk_gphone64_arm64 device:emu64a transport_id:3

"""

DEVICES_OUTPUT_EMPTY = """\
List of devices attached

"""

BATTERY_OUTPUT_CHARGING = """\
Current Battery Service state:
  AC powered: true
  USB powered: false
  Max charging current: 1500000
  status: 2
  health: 2
  level: 85
  temperature: 310
  voltage: 4200
  technology: Li-ion
"""

BATTERY_OUTPUT_DISCHARGING = """\
Current Battery Service state:
  AC powered: false
  USB powered: false
  status: 3
  health: 2
  level: 42
  temperature: 275
  voltage: 3850
  technology: Li-ion
"""

MEMINFO_OUTPUT = """\
MemTotal:        7890124 kB
MemFree:          512340 kB
MemAvailable:    3456789 kB
Buffers:          123456 kB
Cached:          2345678 kB
"""

DF_OUTPUT = """\
Filesystem     1K-blocks    Used Available Use% Mounted on
/dev/block/sda  62914560 34567890  28346670  55% /data
"""

CPU_OUTPUT = """\
Tasks: 324 total,   1 running, 323 sleeping,   0 stopped,   0 zombie
%Cpu(s):  12%user,   5%sys,   0%nice,  83%idle,   0%iowait
  PID USER      PR  NI    VIRT    RES    SHR S  %CPU %MEM     TIME+ COMMAND
 1234 system    20   0  1234567  56789  12345 S  8.3  0.7   1:23.45 system_server
 5678 u0_a123   20   0   987654  34567   8901 S  5.2  0.4   0:45.67 com.app.test
"""

WIFI_OUTPUT = """\
Wi-Fi is enabled
mWifiInfo SSID: "HomeNetwork", BSSID: aa:bb:cc:dd:ee:ff, RSSI: -45
"""

IP_OUTPUT = """\
3: wlan0: <BROADCAST,MULTICAST,UP> mtu 1500
    inet 192.168.1.42/24 brd 192.168.1.255 scope global wlan0
"""

PACKAGES_OUTPUT = """\
package:com.android.chrome
package:com.spotify.music
package:com.whatsapp
"""

PERMISSIONS_OUTPUT = """\
    install permissions:
      android.permission.INTERNET: granted=true
    runtime permissions:
      android.permission.CAMERA: granted=true
      android.permission.READ_CONTACTS: granted=false
    requested permissions:
      android.permission.CAMERA
      android.permission.READ_CONTACTS
      android.permission.INTERNET
"""

LOGCAT_LINE_DEBUG = "01-15 12:34:56.789  1234  5678 D MyTag: Debug message here"
LOGCAT_LINE_ERROR = "01-15 12:34:57.123  1234  5678 E CrashTag: Something went wrong"
LOGCAT_LINE_INFO = "01-15 12:34:58.456  9012  3456 I SystemTag: System started"
LOGCAT_LINE_MALFORMED = "This is not a valid logcat line"


@pytest.fixture
def mock_adb():
    """ADBClient with mocked subprocess and config."""
    import subprocess as real_subprocess
    with patch("core.adb_client.subprocess") as mock_sub, \
         patch("core.adb_client.config") as mock_config:
        mock_config.adb_path = "/usr/bin/adb"

        # Wire real exception classes so except clauses work
        mock_sub.TimeoutExpired = real_subprocess.TimeoutExpired
        mock_sub.Popen = real_subprocess.Popen

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_sub.run.return_value = mock_result

        from core.adb_client import ADBClient
        client = ADBClient(device_serial="TEST123")
        yield client, mock_sub, mock_result
