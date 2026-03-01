"""Tests for utils/config.py — configuration management."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def config_dir(tmp_path):
    """Provide a temporary config directory and patch Config to use it."""
    config_file = tmp_path / "config.json"
    with patch("utils.config.CONFIG_DIR", tmp_path), \
         patch("utils.config.CONFIG_FILE", config_file):
        yield tmp_path, config_file


class TestConfig:
    def test_default_creation(self, config_dir):
        """Config should start with defaults when no file exists."""
        from utils.config import Config
        cfg = Config()
        assert cfg.get("refresh_interval_ms") == 5000
        assert cfg.get("device_poll_interval_ms") == 3000
        assert cfg.get("logcat_max_lines") == 5000

    def test_save_and_load(self, config_dir):
        """Config should persist to disk and reload."""
        tmp_path, config_file = config_dir
        from utils.config import Config

        cfg1 = Config()
        cfg1.set("window_width", 1400)

        assert config_file.exists()
        stored = json.loads(config_file.read_text())
        assert stored["window_width"] == 1400

        cfg2 = Config()
        assert cfg2.get("window_width") == 1400

    def test_get_set(self, config_dir):
        """get/set should work for arbitrary keys."""
        from utils.config import Config
        cfg = Config()
        cfg.set("custom_key", "custom_value")
        assert cfg.get("custom_key") == "custom_value"

    def test_get_default(self, config_dir):
        """get should return default for missing keys."""
        from utils.config import Config
        cfg = Config()
        assert cfg.get("nonexistent") is None
        assert cfg.get("nonexistent", 42) == 42

    def test_adb_path_from_which(self, config_dir):
        """adb_path should fall back to shutil.which."""
        from utils.config import Config
        cfg = Config()
        with patch("utils.config.shutil.which", return_value="/usr/local/bin/adb"):
            assert cfg.adb_path == "/usr/local/bin/adb"

    def test_adb_path_fallback(self, config_dir):
        """adb_path should return 'adb' when nothing is found."""
        from utils.config import Config
        cfg = Config()
        with patch("utils.config.shutil.which", return_value=None):
            assert cfg.adb_path == "adb"

    def test_adb_path_configured(self, config_dir, tmp_path):
        """adb_path should use configured path when it exists."""
        fake_adb = tmp_path / "adb"
        fake_adb.touch()
        from utils.config import Config
        cfg = Config()
        cfg._data["adb_path"] = str(fake_adb)
        assert cfg.adb_path == str(fake_adb)

    def test_corrupt_config_file(self, config_dir):
        """Config should handle corrupt JSON gracefully."""
        _, config_file = config_dir
        config_file.write_text("{invalid json")
        from utils.config import Config
        cfg = Config()
        # Should fall back to defaults
        assert cfg.get("refresh_interval_ms") == 5000
