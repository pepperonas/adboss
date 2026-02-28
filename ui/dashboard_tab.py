"""Dashboard tab — device overview with battery, memory, storage, network info."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QGroupBox,
    QGridLayout,
    QScrollArea,
)

from ui.widgets.battery_widget import BatteryWidget
from ui.widgets.storage_widget import StorageBar


class DashboardTab(QWidget):
    """Main dashboard showing device info at a glance."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        content = QWidget()
        main_layout = QVBoxLayout(content)
        main_layout.setSpacing(12)

        # --- Device Info Header ---
        self._device_group = QGroupBox("Device")
        device_grid = QGridLayout(self._device_group)
        self._info_labels: dict[str, QLabel] = {}
        fields = [
            ("Model", "model"), ("Manufacturer", "manufacturer"),
            ("Android", "android_version"), ("Build", "build_id"),
            ("SDK", "sdk_version"), ("Serial", "serial"),
            ("Uptime", "uptime"),
        ]
        for i, (label, key) in enumerate(fields):
            row, col = divmod(i, 3)
            lbl = QLabel(f"{label}:")
            lbl.setObjectName("infoKey")
            val = QLabel("--")
            val.setObjectName("infoValue")
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            device_grid.addWidget(lbl, row, col * 2)
            device_grid.addWidget(val, row, col * 2 + 1)
            self._info_labels[key] = val
        main_layout.addWidget(self._device_group)

        # --- Middle row: Battery + Storage ---
        mid_layout = QHBoxLayout()

        self._battery = BatteryWidget()
        mid_layout.addWidget(self._battery)

        storage_col = QVBoxLayout()
        self._ram_bar = StorageBar("RAM")
        self._storage_bar = StorageBar("Internal Storage")
        storage_col.addWidget(self._ram_bar)
        storage_col.addWidget(self._storage_bar)
        storage_col.addStretch()
        mid_layout.addLayout(storage_col, 1)
        main_layout.addLayout(mid_layout)

        # --- Network & Display ---
        bottom_layout = QHBoxLayout()

        self._net_group = QGroupBox("Network")
        net_grid = QGridLayout(self._net_group)
        self._net_labels: dict[str, QLabel] = {}
        for i, (label, key) in enumerate([("SSID", "ssid"), ("IP", "ip"), ("Signal", "signal")]):
            lbl = QLabel(f"{label}:")
            lbl.setObjectName("infoKey")
            val = QLabel("--")
            val.setObjectName("infoValue")
            net_grid.addWidget(lbl, i, 0)
            net_grid.addWidget(val, i, 1)
            self._net_labels[key] = val
        bottom_layout.addWidget(self._net_group)

        self._display_group = QGroupBox("Display")
        disp_grid = QGridLayout(self._display_group)
        self._disp_labels: dict[str, QLabel] = {}
        for i, (label, key) in enumerate([("Resolution", "resolution"), ("DPI", "dpi")]):
            lbl = QLabel(f"{label}:")
            lbl.setObjectName("infoKey")
            val = QLabel("--")
            val.setObjectName("infoValue")
            disp_grid.addWidget(lbl, i, 0)
            disp_grid.addWidget(val, i, 1)
            self._disp_labels[key] = val
        bottom_layout.addWidget(self._display_group)

        main_layout.addLayout(bottom_layout)
        main_layout.addStretch()

        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # --- Data update slots ---

    def update_device_info(self, info: dict) -> None:
        for key, label in self._info_labels.items():
            label.setText(info.get(key, "--"))

    def update_battery(self, data: dict) -> None:
        self._battery.update_data(data)

    def update_memory(self, data: dict) -> None:
        self._ram_bar.update_data(
            data.get("used_kb", 0), data.get("total_kb", 0),
            data.get("used_str", ""), data.get("total_str", ""),
        )

    def update_storage(self, data: dict) -> None:
        self._storage_bar.update_data(
            data.get("used_kb", 0), data.get("total_kb", 0),
            data.get("used_str", ""), data.get("total_str", ""),
        )

    def update_network(self, data: dict) -> None:
        for key, label in self._net_labels.items():
            label.setText(str(data.get(key, "--")))

    def update_display(self, data: dict) -> None:
        for key, label in self._disp_labels.items():
            label.setText(str(data.get(key, "--")))

    def clear(self) -> None:
        """Clear all fields when device disconnects."""
        for lbl in self._info_labels.values():
            lbl.setText("--")
        for lbl in self._net_labels.values():
            lbl.setText("--")
        for lbl in self._disp_labels.values():
            lbl.setText("--")
        self._battery.update_data({})
        self._ram_bar.update_data(0, 0, "", "")
        self._storage_bar.update_data(0, 0, "", "")
