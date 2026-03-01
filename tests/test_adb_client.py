"""Tests for core/adb_client.py — ADBClient with mocked subprocess."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import (
    DEVICES_OUTPUT_MULTI,
    BATTERY_OUTPUT_CHARGING,
    MEMINFO_OUTPUT,
    DF_OUTPUT,
    PACKAGES_OUTPUT,
)


class TestADBClientRun:
    def test_run_returns_stdout(self, mock_adb):
        client, mock_sub, mock_result = mock_adb
        mock_result.stdout = "test output"
        result = client._run(["version"])
        assert result == "test output"

    def test_run_includes_device_serial(self, mock_adb):
        client, mock_sub, mock_result = mock_adb
        client._run(["devices"])
        call_args = mock_sub.run.call_args[0][0]
        assert "-s" in call_args
        assert "TEST123" in call_args

    def test_run_timeout(self, mock_adb):
        client, mock_sub, _ = mock_adb
        mock_sub.run.side_effect = subprocess.TimeoutExpired(cmd="adb", timeout=10)
        result = client._run(["shell", "sleep 100"])
        assert result == ""

    def test_run_file_not_found(self, mock_adb):
        client, mock_sub, _ = mock_adb
        mock_sub.run.side_effect = FileNotFoundError("adb not found")
        mock_sub.TimeoutExpired = subprocess.TimeoutExpired
        result = client._run(["version"])
        assert result == ""

    def test_run_os_error(self, mock_adb):
        client, mock_sub, _ = mock_adb
        mock_sub.run.side_effect = OSError("permission denied")
        mock_sub.TimeoutExpired = subprocess.TimeoutExpired
        result = client._run(["version"])
        assert result == ""


class TestADBClientShell:
    def test_shell_wraps_run(self, mock_adb):
        client, mock_sub, mock_result = mock_adb
        mock_result.stdout = "shell output"
        result = client._shell("getprop ro.product.model")
        assert result == "shell output"
        call_args = mock_sub.run.call_args[0][0]
        assert "shell" in call_args


class TestGetConnectedDevices:
    def test_returns_parsed_devices(self, mock_adb):
        client, mock_sub, mock_result = mock_adb
        mock_result.stdout = DEVICES_OUTPUT_MULTI
        devices = client.get_connected_devices()
        assert len(devices) == 2
        assert devices[0]["serial"] == "ABC123"
        assert devices[0]["model"] == "Pixel_6"

    def test_empty_output(self, mock_adb):
        client, mock_sub, mock_result = mock_adb
        mock_result.stdout = "List of devices attached\n\n"
        devices = client.get_connected_devices()
        assert devices == []


class TestGetBatteryInfo:
    def test_returns_parsed_battery(self, mock_adb):
        client, mock_sub, mock_result = mock_adb
        mock_result.stdout = BATTERY_OUTPUT_CHARGING
        info = client.get_battery_info()
        assert info["level"] == 85
        assert info["status"] == "Charging"


class TestGetMemoryInfo:
    def test_returns_parsed_memory_with_formatted(self, mock_adb):
        client, mock_sub, mock_result = mock_adb
        mock_result.stdout = MEMINFO_OUTPUT
        info = client.get_memory_info()
        assert info["total_kb"] == 7890124
        assert "total_str" in info
        assert "used_str" in info
        assert "available_str" in info


class TestGetStorageInfo:
    def test_returns_parsed_storage_with_formatted(self, mock_adb):
        client, mock_sub, mock_result = mock_adb
        mock_result.stdout = DF_OUTPUT
        info = client.get_storage_info()
        assert info["total_kb"] == 62914560
        assert "total_str" in info
        assert "used_str" in info
        assert "free_str" in info


class TestListPackages:
    def test_returns_parsed_packages(self, mock_adb):
        client, mock_sub, mock_result = mock_adb
        mock_result.stdout = PACKAGES_OUTPUT
        packages = client.list_packages()
        assert "com.android.chrome" in packages
        assert "com.spotify.music" in packages
        assert len(packages) == 3

    def test_empty_output(self, mock_adb):
        client, mock_sub, mock_result = mock_adb
        mock_result.stdout = ""
        packages = client.list_packages()
        assert packages == []
