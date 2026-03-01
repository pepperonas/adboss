"""Input tab — remote control with navigation keys, text input, tap/swipe."""

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QGroupBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QSizePolicy,
)

from core.adb_client import ADBClient

logger = logging.getLogger(__name__)

# Keycode constants
KEYCODES = {
    "Home": 3,
    "Back": 4,
    "Recent": 187,
    "Vol+": 24,
    "Vol-": 25,
    "Mute": 164,
    "Power": 26,
    "Menu": 82,
    "Tab": 61,
    "Up": 19,
    "Down": 20,
    "Left": 21,
    "Right": 22,
    "Enter": 66,
}


class InputTab(QWidget):
    """Remote control for navigation keys, text input, tap and swipe."""

    status_message = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._adb: ADBClient | None = None
        self._build_ui()

    def set_adb(self, adb: ADBClient) -> None:
        self._adb = adb

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)

        # --- Navigation Keys ---
        nav_group = QGroupBox("Navigation Keys")
        nav_layout = QGridLayout(nav_group)

        # Row 0: Home, Back, Recent Apps
        for col, (label, key) in enumerate([
            ("Home", "Home"), ("Back", "Back"), ("Recent", "Recent"),
        ]):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _, k=key: self._press_key(k))
            nav_layout.addWidget(btn, 0, col)

        # Row 1: Vol+, Vol-, Mute
        for col, (label, key) in enumerate([
            ("Vol+", "Vol+"), ("Vol-", "Vol-"), ("Mute", "Mute"),
        ]):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _, k=key: self._press_key(k))
            nav_layout.addWidget(btn, 1, col)

        # Row 2: Power, Menu, Tab
        for col, (label, key) in enumerate([
            ("Power", "Power"), ("Menu", "Menu"), ("Tab", "Tab"),
        ]):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _, k=key: self._press_key(k))
            nav_layout.addWidget(btn, 2, col)

        # Row 3-5: Arrow keys + Enter (d-pad style)
        nav_layout.addWidget(QLabel(), 3, 0)  # spacer row
        up_btn = QPushButton("\u25b2 Up")
        up_btn.clicked.connect(lambda: self._press_key("Up"))
        nav_layout.addWidget(up_btn, 3, 1)

        left_btn = QPushButton("\u25c0 Left")
        left_btn.clicked.connect(lambda: self._press_key("Left"))
        nav_layout.addWidget(left_btn, 4, 0)

        enter_btn = QPushButton("OK")
        enter_btn.setStyleSheet("font-weight: bold;")
        enter_btn.clicked.connect(lambda: self._press_key("Enter"))
        nav_layout.addWidget(enter_btn, 4, 1)

        right_btn = QPushButton("Right \u25b6")
        right_btn.clicked.connect(lambda: self._press_key("Right"))
        nav_layout.addWidget(right_btn, 4, 2)

        down_btn = QPushButton("\u25bc Down")
        down_btn.clicked.connect(lambda: self._press_key("Down"))
        nav_layout.addWidget(down_btn, 5, 1)

        nav_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        splitter.addWidget(nav_group)

        # --- Text Input ---
        text_group = QGroupBox("Text Input")
        text_layout = QVBoxLayout(text_group)

        input_row = QHBoxLayout()
        self._text_input = QLineEdit()
        self._text_input.setPlaceholderText("Type text to send...")
        self._text_input.returnPressed.connect(self._send_text)
        input_row.addWidget(self._text_input)

        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self._send_text)
        input_row.addWidget(send_btn)

        text_layout.addLayout(input_row)

        enter_row = QHBoxLayout()
        enter_key_btn = QPushButton("Press Enter")
        enter_key_btn.clicked.connect(lambda: self._press_key("Enter"))
        enter_row.addWidget(enter_key_btn)
        enter_row.addStretch()
        text_layout.addLayout(enter_row)

        text_layout.addStretch()
        text_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        splitter.addWidget(text_group)

        # --- Tap / Swipe ---
        touch_group = QGroupBox("Tap / Swipe")
        touch_layout = QVBoxLayout(touch_group)

        # Tap section
        tap_label = QLabel("Tap at coordinates:")
        touch_layout.addWidget(tap_label)

        tap_row = QHBoxLayout()
        tap_row.addWidget(QLabel("X:"))
        self._tap_x = QSpinBox()
        self._tap_x.setRange(0, 9999)
        tap_row.addWidget(self._tap_x)
        tap_row.addWidget(QLabel("Y:"))
        self._tap_y = QSpinBox()
        self._tap_y.setRange(0, 9999)
        tap_row.addWidget(self._tap_y)
        tap_btn = QPushButton("Tap")
        tap_btn.clicked.connect(self._do_tap)
        tap_row.addWidget(tap_btn)
        touch_layout.addLayout(tap_row)

        # Swipe section
        swipe_label = QLabel("Swipe:")
        touch_layout.addWidget(swipe_label)

        swipe_from = QHBoxLayout()
        swipe_from.addWidget(QLabel("From X:"))
        self._swipe_x1 = QSpinBox()
        self._swipe_x1.setRange(0, 9999)
        swipe_from.addWidget(self._swipe_x1)
        swipe_from.addWidget(QLabel("Y:"))
        self._swipe_y1 = QSpinBox()
        self._swipe_y1.setRange(0, 9999)
        swipe_from.addWidget(self._swipe_y1)
        touch_layout.addLayout(swipe_from)

        swipe_to = QHBoxLayout()
        swipe_to.addWidget(QLabel("To X:"))
        self._swipe_x2 = QSpinBox()
        self._swipe_x2.setRange(0, 9999)
        swipe_to.addWidget(self._swipe_x2)
        swipe_to.addWidget(QLabel("Y:"))
        self._swipe_y2 = QSpinBox()
        self._swipe_y2.setRange(0, 9999)
        swipe_to.addWidget(self._swipe_y2)
        touch_layout.addLayout(swipe_to)

        dur_row = QHBoxLayout()
        dur_row.addWidget(QLabel("Duration (ms):"))
        self._swipe_duration = QSpinBox()
        self._swipe_duration.setRange(50, 5000)
        self._swipe_duration.setValue(300)
        self._swipe_duration.setSingleStep(50)
        dur_row.addWidget(self._swipe_duration)
        swipe_btn = QPushButton("Swipe")
        swipe_btn.clicked.connect(self._do_swipe)
        dur_row.addWidget(swipe_btn)
        touch_layout.addLayout(dur_row)

        touch_layout.addStretch()
        touch_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        splitter.addWidget(touch_group)

        layout.addWidget(splitter)

    def _run(self, label: str, func, *args) -> None:
        """Execute an ADB action with status feedback."""
        if not self._adb or not self._adb.device_serial:
            self.status_message.emit("No device connected")
            return
        try:
            func(*args)
            self.status_message.emit(label)
        except Exception as e:
            self.status_message.emit(f"Error: {e}")

    def _press_key(self, key_name: str) -> None:
        code = KEYCODES.get(key_name, 0)
        self._run(f"Key: {key_name}", self._adb.press_key, str(code))

    def _send_text(self) -> None:
        text = self._text_input.text()
        if not text:
            return
        self._run(f"Text sent: {text[:30]}", self._adb.input_text, text)
        self._text_input.clear()

    def _do_tap(self) -> None:
        x, y = self._tap_x.value(), self._tap_y.value()
        self._run(f"Tap: ({x}, {y})", self._adb.tap, x, y)

    def _do_swipe(self) -> None:
        x1 = self._swipe_x1.value()
        y1 = self._swipe_y1.value()
        x2 = self._swipe_x2.value()
        y2 = self._swipe_y2.value()
        dur = self._swipe_duration.value()
        self._run(f"Swipe: ({x1},{y1})->({x2},{y2})", self._adb.swipe, x1, y1, x2, y2, dur)
