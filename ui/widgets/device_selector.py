"""Device selector dropdown with auto-refresh and WiFi ADB connect."""

import logging

from PySide6.QtCore import Signal, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QComboBox,
    QLabel,
    QPushButton,
    QDialog,
    QLineEdit,
    QSpinBox,
)

from core.adb_client import ADBClient

logger = logging.getLogger(__name__)


class WiFiConnectDialog(QDialog):
    """Dialog for connecting to a device over WiFi ADB."""

    def __init__(self, shared_adb: ADBClient | None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("WiFi ADB Connect")
        self.setMinimumWidth(350)
        self._shared_adb = shared_adb
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # IP
        ip_row = QHBoxLayout()
        ip_row.addWidget(QLabel("IP Address:"))
        self._ip_input = QLineEdit()
        self._ip_input.setPlaceholderText("192.168.x.x")
        ip_row.addWidget(self._ip_input)
        layout.addLayout(ip_row)

        # Port
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Port:"))
        self._port_input = QSpinBox()
        self._port_input.setRange(1, 65535)
        self._port_input.setValue(5555)
        port_row.addWidget(self._port_input)
        layout.addLayout(port_row)

        # Prefill IP from connected USB device
        if self._shared_adb and self._shared_adb.device_serial:
            ip = self._shared_adb.execute_shell("ip route").strip()
            for line in ip.splitlines():
                parts = line.split()
                if "src" in parts:
                    idx = parts.index("src")
                    if idx + 1 < len(parts):
                        self._ip_input.setText(parts[idx + 1])
                        break

        # Enable TCP/IP button
        self._tcpip_btn = QPushButton("Enable TCP/IP on USB device")
        self._tcpip_btn.setEnabled(
            bool(self._shared_adb and self._shared_adb.device_serial
                 and ":" not in (self._shared_adb.device_serial or ""))
        )
        self._tcpip_btn.clicked.connect(self._enable_tcpip)
        layout.addWidget(self._tcpip_btn)

        # Connect / Disconnect
        btn_row = QHBoxLayout()
        connect_btn = QPushButton("Connect")
        connect_btn.clicked.connect(self._connect)
        btn_row.addWidget(connect_btn)

        disconnect_btn = QPushButton("Disconnect")
        disconnect_btn.clicked.connect(self._disconnect)
        btn_row.addWidget(disconnect_btn)
        layout.addLayout(btn_row)

        # Status
        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

    def _enable_tcpip(self) -> None:
        if not self._shared_adb:
            return
        port = self._port_input.value()
        result = self._shared_adb.enable_tcpip(port)
        self._status.setText(f"TCP/IP: {result}")

    def _connect(self) -> None:
        ip = self._ip_input.text().strip()
        if not ip:
            self._status.setText("Please enter an IP address")
            return
        port = self._port_input.value()
        # Use a bare ADBClient (no serial) for connect
        adb = ADBClient()
        result = adb.connect_wifi(ip, port)
        self._status.setText(result)

    def _disconnect(self) -> None:
        ip = self._ip_input.text().strip()
        if not ip:
            self._status.setText("Please enter an IP address")
            return
        port = self._port_input.value()
        adb = ADBClient()
        result = adb.disconnect_wifi(ip, port)
        self._status.setText(result)


class DeviceSelector(QWidget):
    """Dropdown that lists connected ADB devices and auto-refreshes."""

    device_changed = Signal(str)  # Emits the serial of the selected device

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._adb = ADBClient()
        self._shared_adb: ADBClient | None = None
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

        self._wifi_btn = QPushButton("WiFi")
        self._wifi_btn.setFixedWidth(50)
        self._wifi_btn.setToolTip("WiFi ADB Connect")
        self._wifi_btn.clicked.connect(self._open_wifi_dialog)
        layout.addWidget(self._wifi_btn)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self.refresh_devices)
        self._poll_timer.start(3000)

        self.refresh_devices()

    def set_shared_adb(self, adb: ADBClient) -> None:
        """Set the shared ADBClient from MainWindow for WiFi features."""
        self._shared_adb = adb

    def _open_wifi_dialog(self) -> None:
        dialog = WiFiConnectDialog(self._shared_adb, self)
        dialog.exec()
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
