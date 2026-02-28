"""ADB wrapper class — all ADB commands go through here."""

import logging
import subprocess
import threading
from pathlib import Path
from typing import Generator

from utils.config import config
from utils.helpers import (
    format_bytes,
    parse_battery_output,
    parse_cpu_output,
    parse_devices_output,
    parse_df_output,
    parse_display_info,
    parse_meminfo,
    parse_network_info,
    parse_packages,
    parse_permissions,
)

logger = logging.getLogger(__name__)


class ADBClient:
    """Central ADB wrapper. Every ADB interaction flows through this class."""

    def __init__(self, device_serial: str | None = None) -> None:
        self.device_serial = device_serial
        self._screenrecord_proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def _base_cmd(self) -> list[str]:
        cmd = [config.adb_path]
        if self.device_serial:
            cmd.extend(["-s", self.device_serial])
        return cmd

    def _run(self, args: list[str], timeout: int = 10) -> str:
        """Run an ADB command and return stdout."""
        cmd = self._base_cmd() + args
        logger.debug("ADB: %s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
            if result.returncode != 0 and result.stderr.strip():
                logger.warning("ADB stderr: %s", result.stderr.strip())
            return result.stdout
        except subprocess.TimeoutExpired:
            logger.error("ADB command timed out: %s", " ".join(cmd))
            return ""
        except FileNotFoundError:
            logger.error("ADB binary not found at: %s", config.adb_path)
            return ""
        except OSError as e:
            logger.error("ADB command failed: %s", e)
            return ""

    def _shell(self, command: str, timeout: int = 10) -> str:
        """Run `adb shell <command>`."""
        return self._run(["shell", command], timeout=timeout)

    # --- Device Detection ---

    def get_connected_devices(self) -> list[dict]:
        """Return list of connected devices with serial, model, state."""
        output = self._run(["devices", "-l"])
        return parse_devices_output(output)

    # --- Device Info ---

    def get_device_info(self) -> dict:
        """Collect model, manufacturer, Android version, build, serial, uptime."""
        props = {
            "model": "ro.product.model",
            "manufacturer": "ro.product.manufacturer",
            "android_version": "ro.build.version.release",
            "build_id": "ro.build.display.id",
            "sdk_version": "ro.build.version.sdk",
            "serial": "ro.serialno",
        }
        info: dict = {}
        for key, prop in props.items():
            info[key] = self._shell(f"getprop {prop}").strip()
        uptime = self._shell("cat /proc/uptime").strip().split()
        if uptime:
            try:
                secs = int(float(uptime[0]))
                hours, remainder = divmod(secs, 3600)
                minutes, seconds = divmod(remainder, 60)
                info["uptime"] = f"{hours}h {minutes}m {seconds}s"
            except ValueError:
                info["uptime"] = "N/A"
        return info

    def get_battery_info(self) -> dict:
        """Parse dumpsys battery for level, status, health, temperature, etc."""
        output = self._shell("dumpsys battery")
        return parse_battery_output(output)

    def set_battery_level(self, level: int) -> None:
        """Simulate battery level (for testing)."""
        self._shell(f"dumpsys battery set level {level}")

    def reset_battery(self) -> None:
        """Reset battery simulation."""
        self._shell("dumpsys battery reset")

    def get_memory_info(self) -> dict:
        """Parse /proc/meminfo for RAM stats."""
        output = self._shell("cat /proc/meminfo")
        info = parse_meminfo(output)
        info["total_str"] = format_bytes(info.get("total_kb", 0))
        info["used_str"] = format_bytes(info.get("used_kb", 0))
        info["available_str"] = format_bytes(info.get("available_kb", 0))
        return info

    def get_storage_info(self) -> dict:
        """Parse df for /data partition storage."""
        output = self._shell("df /data")
        info = parse_df_output(output)
        info["total_str"] = format_bytes(info.get("total_kb", 0))
        info["used_str"] = format_bytes(info.get("used_kb", 0))
        info["free_str"] = format_bytes(info.get("free_kb", 0))
        return info

    def get_cpu_info(self) -> dict:
        """Get CPU usage from top."""
        output = self._shell("top -n 1 -b", timeout=15)
        return parse_cpu_output(output)

    def get_display_info(self) -> dict:
        """Get screen resolution and DPI."""
        size_out = self._shell("wm size")
        density_out = self._shell("wm density")
        return parse_display_info(size_out, density_out)

    def get_network_info(self) -> dict:
        """Get WiFi SSID, IP, signal strength."""
        wifi_out = self._shell("dumpsys wifi")
        ip_out = self._shell("ip addr show wlan0")
        return parse_network_info(wifi_out, ip_out)

    # --- Controls ---

    def set_brightness(self, value: int) -> None:
        """Set screen brightness (0-255)."""
        self._shell("settings put system screen_brightness_mode 0")
        self._shell(f"settings put system screen_brightness {value}")

    def set_volume(self, stream: int, value: int) -> None:
        """Set volume for a stream (3=media, 2=ring, 4=alarm)."""
        self._shell(f"media volume --stream {stream} --set {value} --show")

    def toggle_wifi(self, enable: bool) -> None:
        """Enable or disable WiFi."""
        action = "enable" if enable else "disable"
        self._shell(f"svc wifi {action}")

    def toggle_bluetooth(self, enable: bool) -> None:
        """Enable or disable Bluetooth."""
        action = "enable" if enable else "disable"
        self._shell(f"svc bluetooth {action}")

    def toggle_airplane_mode(self, enable: bool) -> None:
        """Toggle airplane mode."""
        val = "1" if enable else "0"
        self._shell(f"settings put global airplane_mode_on {val}")
        self._shell(
            "am broadcast -a android.intent.action.AIRPLANE_MODE "
            "--ez state " + ("true" if enable else "false")
        )

    def toggle_dnd(self, enable: bool) -> None:
        """Toggle Do Not Disturb."""
        val = "2" if enable else "0"
        self._shell(f"settings put global zen_mode {val}")

    def screen_on(self) -> None:
        """Wake screen."""
        self._shell("input keyevent KEYCODE_WAKEUP")

    def screen_off(self) -> None:
        """Turn off screen."""
        self._shell("input keyevent KEYCODE_SLEEP")

    def lock_screen(self) -> None:
        """Lock the screen."""
        self._shell("input keyevent KEYCODE_POWER")

    def set_screen_timeout(self, ms: int) -> None:
        """Set screen off timeout in milliseconds."""
        self._shell(f"settings put system screen_off_timeout {ms}")

    # --- App Management ---

    def list_packages(self, include_system: bool = False) -> list[str]:
        """List installed packages."""
        flag = "" if include_system else "-3"
        output = self._shell(f"pm list packages {flag}")
        return parse_packages(output)

    def get_package_info(self, package: str) -> dict:
        """Get version and other info for a package."""
        output = self._shell(f"dumpsys package {package}")
        info: dict = {"package": package}
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("versionName="):
                info["version"] = stripped.split("=", 1)[1]
            elif stripped.startswith("versionCode="):
                info["version_code"] = stripped.split("=", 1)[1].split()[0]
            elif stripped.startswith("firstInstallTime="):
                info["installed"] = stripped.split("=", 1)[1]
        return info

    def install_apk(self, apk_path: str) -> str:
        """Install an APK file."""
        output = self._run(["install", "-r", apk_path], timeout=120)
        return output.strip()

    def uninstall_app(self, package: str, keep_data: bool = False) -> str:
        """Uninstall an app."""
        args = ["uninstall"]
        if keep_data:
            args.append("-k")
        args.append(package)
        return self._run(args, timeout=30).strip()

    def force_stop(self, package: str) -> None:
        """Force stop an app."""
        self._shell(f"am force-stop {package}")

    def clear_app_data(self, package: str) -> str:
        """Clear app data and cache."""
        return self._shell(f"pm clear {package}").strip()

    def disable_app(self, package: str) -> None:
        """Disable an app for the current user."""
        self._shell(f"pm disable-user --user 0 {package}")

    def enable_app(self, package: str) -> None:
        """Enable a disabled app."""
        self._shell(f"pm enable {package}")

    def get_app_permissions(self, package: str) -> list[dict]:
        """Get requested permissions for an app."""
        output = self._shell(f"dumpsys package {package}")
        return parse_permissions(output)

    def grant_permission(self, package: str, permission: str) -> None:
        """Grant a runtime permission."""
        self._shell(f"pm grant {package} {permission}")

    def revoke_permission(self, package: str, permission: str) -> None:
        """Revoke a runtime permission."""
        self._shell(f"pm revoke {package} {permission}")

    def launch_app(self, package: str) -> None:
        """Launch an app."""
        self._shell(
            f"monkey -p {package} -c android.intent.category.LAUNCHER 1"
        )

    # --- File Transfer ---

    def pull_file(self, remote: str, local: str) -> str:
        """Pull a file from device."""
        return self._run(["pull", remote, local], timeout=300).strip()

    def push_file(self, local: str, remote: str) -> str:
        """Push a file to device."""
        return self._run(["push", local, remote], timeout=300).strip()

    def list_remote_files(self, remote_path: str) -> list[dict]:
        """List files in a remote directory."""
        output = self._shell(f"ls -la {remote_path}")
        files: list[dict] = []
        for line in output.splitlines():
            parts = line.split()
            if len(parts) < 7:
                continue
            perms = parts[0]
            is_dir = perms.startswith("d")
            name = " ".join(parts[7:]) if len(parts) > 7 else parts[-1]
            if name in (".", ".."):
                continue
            size_str = parts[4] if len(parts) > 4 else "0"
            try:
                size = int(size_str)
            except ValueError:
                size = 0
            files.append({
                "name": name,
                "is_dir": is_dir,
                "size": size,
                "permissions": perms,
            })
        return files

    def take_screenshot(self, save_path: str) -> bool:
        """Take a screenshot and save locally."""
        cmd = self._base_cmd() + ["exec-out", "screencap", "-p"]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            if result.returncode == 0 and result.stdout:
                Path(save_path).write_bytes(result.stdout)
                return True
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.error("Screenshot failed: %s", e)
        return False

    def start_screenrecord(self, remote_path: str = "/sdcard/record.mp4") -> bool:
        """Start screen recording (non-blocking)."""
        with self._lock:
            if self._screenrecord_proc is not None:
                return False
            cmd = self._base_cmd() + ["shell", "screenrecord", remote_path]
            try:
                self._screenrecord_proc = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                return True
            except OSError as e:
                logger.error("Screenrecord start failed: %s", e)
                return False

    def stop_screenrecord(self) -> bool:
        """Stop screen recording."""
        with self._lock:
            if self._screenrecord_proc is None:
                self._shell("pkill -2 screenrecord")
                return True
            self._screenrecord_proc.terminate()
            try:
                self._screenrecord_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._screenrecord_proc.kill()
            self._screenrecord_proc = None
            return True

    # --- Shell & Logcat ---

    def execute_shell(self, command: str, timeout: int = 30) -> str:
        """Execute an arbitrary shell command."""
        return self._shell(command, timeout=timeout)

    def stream_logcat(
        self, filters: list[str] | None = None
    ) -> subprocess.Popen:
        """Start logcat streaming. Returns a Popen process."""
        cmd = self._base_cmd() + ["logcat", "-v", "threadtime"]
        if filters:
            cmd.extend(filters)
        return subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )

    # --- Input Simulation ---

    def tap(self, x: int, y: int) -> None:
        """Simulate screen tap."""
        self._shell(f"input tap {x} {y}")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        """Simulate swipe gesture."""
        self._shell(f"input swipe {x1} {y1} {x2} {y2} {duration_ms}")

    def input_text(self, text: str) -> None:
        """Input text on device."""
        escaped = text.replace(" ", "%s").replace("'", "\\'")
        self._shell(f"input text '{escaped}'")

    def press_key(self, keycode: str) -> None:
        """Press a key by keycode."""
        self._shell(f"input keyevent {keycode}")

    # --- Backup ---

    def create_backup(self, output_path: str, include_apks: bool = True) -> str:
        """Create a full device backup."""
        args = ["backup", "-all"]
        if include_apks:
            args.append("-apk")
        args.extend(["-f", output_path])
        return self._run(args, timeout=600)

    # --- Developer Options ---

    def toggle_layout_bounds(self, enable: bool) -> None:
        """Toggle layout bounds display."""
        val = "true" if enable else "false"
        self._shell(f"setprop debug.layout {val}")
        self._shell("service call activity 1599295570")

    def toggle_gpu_overdraw(self, enable: bool) -> None:
        """Toggle GPU overdraw display."""
        val = "show" if enable else "false"
        self._shell(f"setprop debug.hwui.overdraw {val}")

    # --- Reboot ---

    def reboot(self, mode: str = "") -> None:
        """Reboot device. mode can be '', 'bootloader', 'recovery'."""
        if mode:
            self._run(["reboot", mode], timeout=5)
        else:
            self._run(["reboot"], timeout=5)

    def cleanup(self) -> None:
        """Clean up resources on shutdown."""
        self.stop_screenrecord()
