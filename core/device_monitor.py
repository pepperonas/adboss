"""Background thread for live device monitoring."""

import logging

from PySide6.QtCore import QThread, Signal

from core.adb_client import ADBClient

logger = logging.getLogger(__name__)


class DeviceMonitor(QThread):
    """Periodically polls device stats and emits signals with the data."""

    battery_updated = Signal(dict)
    memory_updated = Signal(dict)
    storage_updated = Signal(dict)
    cpu_updated = Signal(dict)
    network_updated = Signal(dict)
    device_info_updated = Signal(dict)
    display_info_updated = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, adb: ADBClient, parent=None) -> None:
        super().__init__(parent)
        self.adb = adb
        self._running = False

    def run(self) -> None:
        """Main monitoring loop — runs once per invocation."""
        self._running = True
        try:
            info = self.adb.get_device_info()
            if not self._running:
                return
            if info.get("model"):
                self.device_info_updated.emit(info)
            else:
                self.error_occurred.emit("Device not responding")
                return

            battery = self.adb.get_battery_info()
            if not self._running:
                return
            self.battery_updated.emit(battery)

            memory = self.adb.get_memory_info()
            if not self._running:
                return
            self.memory_updated.emit(memory)

            storage = self.adb.get_storage_info()
            if not self._running:
                return
            self.storage_updated.emit(storage)

            cpu = self.adb.get_cpu_info()
            if not self._running:
                return
            self.cpu_updated.emit(cpu)

            network = self.adb.get_network_info()
            if not self._running:
                return
            self.network_updated.emit(network)

            display = self.adb.get_display_info()
            if not self._running:
                return
            self.display_info_updated.emit(display)

        except Exception as e:
            if self._running:
                logger.exception("Monitor error")
                self.error_occurred.emit(str(e))

    def stop(self) -> None:
        self._running = False
        self.quit()
        self.wait(3000)
