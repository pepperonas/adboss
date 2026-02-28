"""Logcat tab — live logcat viewer with filters and color coding."""

import logging
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QFont, QColor, QTextCursor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QLineEdit,
    QPushButton,
    QComboBox,
    QCheckBox,
    QLabel,
    QFileDialog,
)

from core.adb_client import ADBClient
from utils.helpers import parse_logcat_line

logger = logging.getLogger(__name__)

LEVEL_COLORS = {
    "V": "#888888",
    "D": "#2196F3",
    "I": "#4CAF50",
    "W": "#FFC107",
    "E": "#F44336",
    "F": "#E040FB",
    "A": "#E040FB",
}

LEVEL_NAMES = {
    "V": "Verbose",
    "D": "Debug",
    "I": "Info",
    "W": "Warning",
    "E": "Error",
    "F": "Fatal",
}


class LogcatReader(QThread):
    """Read logcat output line by line and emit signals."""

    line_received = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, adb: ADBClient, parent=None) -> None:
        super().__init__(parent)
        self._adb = adb
        self._process: subprocess.Popen | None = None
        self._running = False

    def run(self) -> None:
        self._running = True
        try:
            self._process = self._adb.stream_logcat()
            if self._process.stdout:
                for line in self._process.stdout:
                    if not self._running:
                        break
                    self.line_received.emit(line.rstrip("\n"))
        except Exception as e:
            self.error_occurred.emit(str(e))

    def stop(self) -> None:
        self._running = False
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except (subprocess.TimeoutExpired, OSError):
                if self._process:
                    self._process.kill()
            self._process = None
        self.quit()
        self.wait(2000)


class LogcatTab(QWidget):
    """Live logcat viewer with filtering and export."""

    status_message = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._adb: ADBClient | None = None
        self._reader: LogcatReader | None = None
        self._paused = False
        self._auto_scroll = True
        self._lines: list[str] = []
        self._max_lines = 5000
        self._build_ui()

    def set_adb(self, adb: ADBClient) -> None:
        self._adb = adb

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Filter bar
        filter_row = QHBoxLayout()

        filter_row.addWidget(QLabel("Level:"))
        self._level_combo = QComboBox()
        self._level_combo.addItem("Verbose", "V")
        self._level_combo.addItem("Debug", "D")
        self._level_combo.addItem("Info", "I")
        self._level_combo.addItem("Warning", "W")
        self._level_combo.addItem("Error", "E")
        self._level_combo.addItem("Fatal", "F")
        self._level_combo.setCurrentIndex(0)
        filter_row.addWidget(self._level_combo)

        filter_row.addWidget(QLabel("Tag:"))
        self._tag_filter = QLineEdit()
        self._tag_filter.setPlaceholderText("Filter by tag...")
        self._tag_filter.setMaximumWidth(150)
        filter_row.addWidget(self._tag_filter)

        filter_row.addWidget(QLabel("PID:"))
        self._pid_filter = QLineEdit()
        self._pid_filter.setPlaceholderText("Filter by PID...")
        self._pid_filter.setMaximumWidth(100)
        filter_row.addWidget(self._pid_filter)

        filter_row.addWidget(QLabel("Search:"))
        self._search_filter = QLineEdit()
        self._search_filter.setPlaceholderText("Search text...")
        self._search_filter.setMaximumWidth(200)
        filter_row.addWidget(self._search_filter)

        filter_row.addStretch()

        self._auto_scroll_check = QCheckBox("Auto-scroll")
        self._auto_scroll_check.setChecked(True)
        self._auto_scroll_check.toggled.connect(lambda on: setattr(self, "_auto_scroll", on))
        filter_row.addWidget(self._auto_scroll_check)

        layout.addLayout(filter_row)

        # Log output
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(QFont("Menlo, Consolas, monospace", 10))
        self._output.setObjectName("logcatOutput")
        self._output.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self._output)

        # Control bar
        ctrl_row = QHBoxLayout()

        self._start_btn = QPushButton("Start")
        self._start_btn.clicked.connect(self.start_logcat)
        ctrl_row.addWidget(self._start_btn)

        self._pause_btn = QPushButton("Pause")
        self._pause_btn.clicked.connect(self._toggle_pause)
        self._pause_btn.setEnabled(False)
        ctrl_row.addWidget(self._pause_btn)

        stop_btn = QPushButton("Stop")
        stop_btn.clicked.connect(self.stop_logcat)
        ctrl_row.addWidget(stop_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear)
        ctrl_row.addWidget(clear_btn)

        export_btn = QPushButton("Export...")
        export_btn.clicked.connect(self._export)
        ctrl_row.addWidget(export_btn)

        self._count_label = QLabel("0 lines")
        ctrl_row.addStretch()
        ctrl_row.addWidget(self._count_label)

        layout.addLayout(ctrl_row)

    def start_logcat(self) -> None:
        """Start streaming logcat."""
        if not self._adb or self._reader:
            return
        self._reader = LogcatReader(self._adb)
        self._reader.line_received.connect(self._on_line)
        self._reader.error_occurred.connect(lambda e: self.status_message.emit(f"Logcat error: {e}"))
        self._reader.start()
        self._start_btn.setEnabled(False)
        self._pause_btn.setEnabled(True)
        self.status_message.emit("Logcat started")

    def stop_logcat(self) -> None:
        """Stop streaming logcat."""
        if self._reader:
            self._reader.stop()
            self._reader = None
        self._start_btn.setEnabled(True)
        self._pause_btn.setEnabled(False)
        self._paused = False
        self._pause_btn.setText("Pause")
        self.status_message.emit("Logcat stopped")

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self._pause_btn.setText("Resume" if self._paused else "Pause")

    def _on_line(self, line: str) -> None:
        if self._paused:
            return

        self._lines.append(line)
        if len(self._lines) > self._max_lines:
            self._lines = self._lines[-self._max_lines:]

        if not self._should_show(line):
            return

        parsed = parse_logcat_line(line)
        if parsed:
            color = LEVEL_COLORS.get(parsed["level"], "#CCCCCC")
            escaped_msg = parsed["message"].replace("<", "&lt;").replace(">", "&gt;")
            escaped_tag = parsed["tag"].replace("<", "&lt;").replace(">", "&gt;")
            html = (
                f'<span style="color:#666;">{parsed["timestamp"]}</span> '
                f'<span style="color:{color}; font-weight:bold;">{parsed["level"]}</span> '
                f'<span style="color:#00BCD4;">{escaped_tag}</span>: '
                f'<span style="color:{color};">{escaped_msg}</span>'
            )
        else:
            escaped = line.replace("<", "&lt;").replace(">", "&gt;")
            html = f'<span style="color:#CCCCCC;">{escaped}</span>'

        self._output.append(html)
        self._count_label.setText(f"{len(self._lines)} lines")

        if self._auto_scroll:
            self._output.moveCursor(QTextCursor.MoveOperation.End)

    def _should_show(self, line: str) -> bool:
        """Check if a line passes the current filters."""
        min_level = self._level_combo.currentData()
        level_order = "VDIWEF"
        parsed = parse_logcat_line(line)

        if parsed:
            if level_order.index(parsed["level"]) < level_order.index(min_level):
                return False
            tag_filter = self._tag_filter.text().strip().lower()
            if tag_filter and tag_filter not in parsed["tag"].lower():
                return False
            pid_filter = self._pid_filter.text().strip()
            if pid_filter and parsed["pid"] != pid_filter:
                return False

        search = self._search_filter.text().strip().lower()
        if search and search not in line.lower():
            return False

        return True

    def _clear(self) -> None:
        self._output.clear()
        self._lines.clear()
        self._count_label.setText("0 lines")

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Logcat", str(Path.home() / "logcat.txt"), "Text Files (*.txt)"
        )
        if path:
            Path(path).write_text("\n".join(self._lines), encoding="utf-8")
            self.status_message.emit(f"Exported {len(self._lines)} lines to {path}")

    def cleanup(self) -> None:
        """Stop logcat reader on shutdown."""
        self.stop_logcat()
