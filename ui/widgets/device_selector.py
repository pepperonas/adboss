"""Device selector dropdown with auto-refresh."""

import logging

from PySide6.QtCore import Signal, QTimer
from PySide6.QtWidgets import QWidget, QHBoxLayout, QComboBox, QLabel, QPushButton

from core.adb_client import ADBClient

logger = logging.getLogger(__name__)


class DeviceSelector(QWidget):
    """Dropdown that lists connected ADB devices and auto-refreshes."""

    device_changed = Signal(str)  # Emits the serial of the selected device

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._adb = ADBClient()
        self._devices: list[dict] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._status_indicator = QLabel("\u26aa")
        self._status_indicator.setFixedWidth(20)
        layout.addWidget(self._status_indicator)

        self._combo = QComboBox()
        self._combo.setMinimumWidth(200)
        self._combo.currentIndexChanged.connect(self._on_selection_changed)
        layout.addWidget(self._combo)

        self._refresh_btn = QPushButton("\u21bb")
        self._refresh_btn.setFixedWidth(30)
        self._refresh_btn.setToolTip("Refresh devices")
        self._refresh_btn.clicked.connect(self.refresh_devices)
        layout.addWidget(self._refresh_btn)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self.refresh_devices)
        self._poll_timer.start(3000)

        self.refresh_devices()

    def refresh_devices(self) -> None:
        """Poll for connected devices and update the dropdown."""
        devices = self._adb.get_connected_devices()
        device_serials = [d["serial"] for d in devices if d["state"] == "device"]
        current_serials = [
            self._combo.itemData(i) for i in range(self._combo.count())
        ]

        if device_serials == current_serials:
            return

        current = self._combo.currentData()
        self._combo.blockSignals(True)
        self._combo.clear()
        self._devices = devices

        for d in devices:
            if d["state"] == "device":
                label = f"{d.get('model', d['serial'])} ({d['serial']})"
                self._combo.addItem(label, d["serial"])

        if not device_serials:
            self._combo.addItem("No device connected", "")
            self._status_indicator.setText("\ud83d\udd34")
        else:
            self._status_indicator.setText("\ud83d\udfe2")
            if current in device_serials:
                idx = device_serials.index(current)
                self._combo.setCurrentIndex(idx)

        self._combo.blockSignals(False)
        self._on_selection_changed()

    def _on_selection_changed(self) -> None:
        serial = self._combo.currentData() or ""
        self.device_changed.emit(serial)

    def current_serial(self) -> str:
        return self._combo.currentData() or ""

    def stop_polling(self) -> None:
        self._poll_timer.stop()
