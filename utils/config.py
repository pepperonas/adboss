"""Configuration management for ADBOSS."""

import json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "adb_path": "",
    "refresh_interval_ms": 5000,
    "device_poll_interval_ms": 3000,
    "window_width": 1100,
    "window_height": 750,
    "last_device_serial": "",
    "logcat_max_lines": 5000,
    "shell_history_max": 100,
    "last_local_path": str(Path.home()),
    "last_remote_path": "/sdcard/",
}

CONFIG_DIR = Path.home() / ".adboss"
CONFIG_FILE = CONFIG_DIR / "config.json"


class Config:
    """Application configuration backed by a JSON file."""

    def __init__(self) -> None:
        self._data: dict = dict(DEFAULT_CONFIG)
        self._load()

    def _load(self) -> None:
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r") as f:
                    stored = json.load(f)
                self._data.update(stored)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load config: %s", e)

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self._data, f, indent=2)
        except OSError as e:
            logger.error("Failed to save config: %s", e)

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self.save()

    @property
    def adb_path(self) -> str:
        path = self._data.get("adb_path", "")
        if path and Path(path).exists():
            return path
        found = shutil.which("adb")
        if found:
            self._data["adb_path"] = found
            self.save()
            return found
        return "adb"

    @adb_path.setter
    def adb_path(self, value: str) -> None:
        self._data["adb_path"] = value
        self.save()


config = Config()
