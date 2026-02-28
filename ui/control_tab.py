"""Control tab — brightness, volume, toggles, screen controls."""

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QGridLayout,
    QLabel,
    QSlider,
    QPushButton,
    QComboBox,
    QScrollArea,
)

from core.adb_client import ADBClient

logger = logging.getLogger(__name__)


class ToggleButton(QPushButton):
    """A styled toggle button."""

    toggled_state = Signal(bool)

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self._on = False
        self.setCheckable(True)
        self.setMinimumWidth(80)
        self.clicked.connect(self._handle_click)

    def _handle_click(self) -> None:
        self._on = self.isChecked()
        self.setText(f"{self.text().split(':')[0]}: {'ON' if self._on else 'OFF'}")
        self.toggled_state.emit(self._on)

    def set_state(self, on: bool) -> None:
        self._on = on
        self.setChecked(on)
        base = self.text().split(":")[0]
        self.setText(f"{base}: {'ON' if on else 'OFF'}")


class ControlTab(QWidget):
    """Device control panel — sliders, toggles, buttons."""

    status_message = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._adb: ADBClient | None = None
        self._build_ui()

    def set_adb(self, adb: ADBClient) -> None:
        self._adb = adb

    def _run(self, label: str, func, *args) -> None:
        if not self._adb:
            return
        try:
            func(*args)
            self.status_message.emit(f"{label}: OK")
        except Exception as e:
            logger.error("%s failed: %s", label, e)
            self.status_message.emit(f"{label}: Failed — {e}")

    def _build_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        main = QVBoxLayout(content)
        main.setSpacing(12)

        # --- Battery Simulation ---
        bat_group = QGroupBox("Battery Simulation")
        bat_layout = QHBoxLayout(bat_group)
        self._bat_slider = QSlider(Qt.Orientation.Horizontal)
        self._bat_slider.setRange(0, 100)
        self._bat_slider.setValue(50)
        self._bat_label = QLabel("50")
        self._bat_slider.valueChanged.connect(lambda v: self._bat_label.setText(str(v)))
        bat_set = QPushButton("Set")
        bat_set.clicked.connect(self._set_battery)
        bat_reset = QPushButton("Reset")
        bat_reset.clicked.connect(self._reset_battery)
        bat_layout.addWidget(QLabel("Level:"))
        bat_layout.addWidget(self._bat_slider, 1)
        bat_layout.addWidget(self._bat_label)
        bat_layout.addWidget(bat_set)
        bat_layout.addWidget(bat_reset)
        main.addWidget(bat_group)

        # --- Brightness ---
        bright_group = QGroupBox("Brightness")
        bright_layout = QHBoxLayout(bright_group)
        self._bright_slider = QSlider(Qt.Orientation.Horizontal)
        self._bright_slider.setRange(0, 255)
        self._bright_slider.setValue(128)
        self._bright_label = QLabel("128")
        self._bright_slider.valueChanged.connect(lambda v: self._bright_label.setText(str(v)))
        self._bright_slider.sliderReleased.connect(self._set_brightness)
        bright_layout.addWidget(QLabel("\u2600"))
        bright_layout.addWidget(self._bright_slider, 1)
        bright_layout.addWidget(self._bright_label)
        main.addWidget(bright_group)

        # --- Volume ---
        vol_group = QGroupBox("Volume")
        vol_grid = QGridLayout(vol_group)
        self._vol_sliders: dict[int, QSlider] = {}
        for i, (label, stream) in enumerate([("Media", 3), ("Ring", 2), ("Alarm", 4)]):
            vol_grid.addWidget(QLabel(label), i, 0)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 15)
            slider.setValue(7)
            val_lbl = QLabel("7")
            slider.valueChanged.connect(lambda v, l=val_lbl: l.setText(str(v)))
            slider.sliderReleased.connect(lambda s=stream, sl=slider: self._set_volume(s, sl.value()))
            vol_grid.addWidget(slider, i, 1)
            vol_grid.addWidget(val_lbl, i, 2)
            self._vol_sliders[stream] = slider
        main.addWidget(vol_group)

        # --- Toggles ---
        toggle_group = QGroupBox("Toggles")
        toggle_layout = QHBoxLayout(toggle_group)
        self._wifi_btn = ToggleButton("WiFi: OFF")
        self._wifi_btn.toggled_state.connect(lambda on: self._run("WiFi", self._adb.toggle_wifi, on) if self._adb else None)
        self._bt_btn = ToggleButton("Bluetooth: OFF")
        self._bt_btn.toggled_state.connect(lambda on: self._run("Bluetooth", self._adb.toggle_bluetooth, on) if self._adb else None)
        self._airplane_btn = ToggleButton("Airplane: OFF")
        self._airplane_btn.toggled_state.connect(lambda on: self._run("Airplane", self._adb.toggle_airplane_mode, on) if self._adb else None)
        self._dnd_btn = ToggleButton("DND: OFF")
        self._dnd_btn.toggled_state.connect(lambda on: self._run("DND", self._adb.toggle_dnd, on) if self._adb else None)
        for btn in (self._wifi_btn, self._bt_btn, self._airplane_btn, self._dnd_btn):
            toggle_layout.addWidget(btn)
        main.addWidget(toggle_group)

        # --- Screen ---
        screen_group = QGroupBox("Screen")
        screen_layout = QHBoxLayout(screen_group)
        for label, func_name in [("Wake", "screen_on"), ("Sleep", "screen_off"), ("Lock", "lock_screen")]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _, fn=func_name: self._run(fn, getattr(self._adb, fn)) if self._adb else None)
            screen_layout.addWidget(btn)

        screen_layout.addWidget(QLabel("Timeout:"))
        self._timeout_combo = QComboBox()
        timeouts = [("15s", 15000), ("30s", 30000), ("1 min", 60000), ("2 min", 120000),
                     ("5 min", 300000), ("10 min", 600000), ("30 min", 1800000)]
        for label, ms in timeouts:
            self._timeout_combo.addItem(label, ms)
        self._timeout_combo.setCurrentIndex(3)
        self._timeout_combo.currentIndexChanged.connect(self._set_timeout)
        screen_layout.addWidget(self._timeout_combo)
        main.addWidget(screen_group)

        # --- Developer Options ---
        dev_group = QGroupBox("Developer Options")
        dev_layout = QHBoxLayout(dev_group)
        self._layout_bounds_btn = ToggleButton("Layout Bounds: OFF")
        self._layout_bounds_btn.toggled_state.connect(
            lambda on: self._run("Layout Bounds", self._adb.toggle_layout_bounds, on) if self._adb else None
        )
        self._gpu_overdraw_btn = ToggleButton("GPU Overdraw: OFF")
        self._gpu_overdraw_btn.toggled_state.connect(
            lambda on: self._run("GPU Overdraw", self._adb.toggle_gpu_overdraw, on) if self._adb else None
        )
        dev_layout.addWidget(self._layout_bounds_btn)
        dev_layout.addWidget(self._gpu_overdraw_btn)
        main.addWidget(dev_group)

        main.addStretch()
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _set_battery(self) -> None:
        if self._adb:
            self._run("Set Battery", self._adb.set_battery_level, self._bat_slider.value())

    def _reset_battery(self) -> None:
        if self._adb:
            self._run("Reset Battery", self._adb.reset_battery)

    def _set_brightness(self) -> None:
        if self._adb:
            self._run("Brightness", self._adb.set_brightness, self._bright_slider.value())

    def _set_volume(self, stream: int, value: int) -> None:
        if self._adb:
            self._run("Volume", self._adb.set_volume, stream, value)

    def _set_timeout(self) -> None:
        ms = self._timeout_combo.currentData()
        if self._adb and ms:
            self._run("Screen Timeout", self._adb.set_screen_timeout, ms)
