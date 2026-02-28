"""Logcat tab — high-performance live logcat viewer with filters and color coding."""

import logging
import re
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QThread, QTimer, QRegularExpression
from PySide6.QtGui import (
    QFont,
    QColor,
    QTextCharFormat,
    QSyntaxHighlighter,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPlainTextEdit,
    QLineEdit,
    QPushButton,
    QComboBox,
    QCheckBox,
    QLabel,
    QFileDialog,
    QSpinBox,
)

from core.adb_client import ADBClient
from utils.helpers import parse_logcat_line

logger = logging.getLogger(__name__)

LEVEL_COLORS = {
    "V": QColor("#888888"),
    "D": QColor("#2196F3"),
    "I": QColor("#4CAF50"),
    "W": QColor("#FFC107"),
    "E": QColor("#F44336"),
    "F": QColor("#E040FB"),
    "A": QColor("#E040FB"),
}

TAG_COLOR = QColor("#00BCD4")
TIMESTAMP_COLOR = QColor("#666666")
DEFAULT_COLOR = QColor("#CCCCCC")

# Regex matching logcat threadtime format
LOGCAT_RE = re.compile(
    r"^(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)"  # timestamp
    r"\s+(\d+)\s+(\d+)"                            # pid tid
    r"\s+([VDIWEFA])"                               # level
    r"\s+(.+?):\s"                                  # tag
)


class LogcatHighlighter(QSyntaxHighlighter):
    """Fast syntax highlighter for logcat output — no HTML needed."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._fmt_cache: dict[str, QTextCharFormat] = {}
        self._build_formats()

    def _build_formats(self) -> None:
        for level, color in LEVEL_COLORS.items():
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            self._fmt_cache[f"line_{level}"] = fmt

            bold = QTextCharFormat()
            bold.setForeground(color)
            bold.setFontWeight(QFont.Weight.Bold)
            self._fmt_cache[f"level_{level}"] = bold

        ts_fmt = QTextCharFormat()
        ts_fmt.setForeground(TIMESTAMP_COLOR)
        self._fmt_cache["timestamp"] = ts_fmt

        tag_fmt = QTextCharFormat()
        tag_fmt.setForeground(TAG_COLOR)
        tag_fmt.setFontWeight(QFont.Weight.Bold)
        self._fmt_cache["tag"] = tag_fmt

        default_fmt = QTextCharFormat()
        default_fmt.setForeground(DEFAULT_COLOR)
        self._fmt_cache["default"] = default_fmt

    def highlightBlock(self, text: str) -> None:
        """Color a single line of logcat output."""
        if not text:
            return

        m = LOGCAT_RE.match(text)
        if not m:
            self.setFormat(0, len(text), self._fmt_cache["default"])
            return

        ts_end = m.end(1)
        level = m.group(4)
        level_start = m.start(4)
        level_end = m.end(4)
        tag_start = m.start(5)
        tag_end = m.end(5)

        # Timestamp
        self.setFormat(0, ts_end, self._fmt_cache["timestamp"])

        # PID/TID region (between timestamp and level)
        self.setFormat(ts_end, level_start - ts_end, self._fmt_cache["timestamp"])

        # Level character
        level_fmt_key = f"level_{level}"
        if level_fmt_key in self._fmt_cache:
            self.setFormat(level_start, level_end - level_start, self._fmt_cache[level_fmt_key])

        # Tag
        self.setFormat(tag_start, tag_end - tag_start, self._fmt_cache["tag"])

        # Message (rest of line)
        msg_start = m.end(0)
        line_fmt_key = f"line_{level}"
        if line_fmt_key in self._fmt_cache:
            self.setFormat(msg_start, len(text) - msg_start, self._fmt_cache[line_fmt_key])


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
    """High-performance live logcat viewer with filtering, font controls, and export."""

    status_message = Signal(str)

    LEVEL_ORDER = "VDIWEFA"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._adb: ADBClient | None = None
        self._reader: LogcatReader | None = None
        self._paused = False
        self._auto_scroll = True
        self._lines: list[str] = []
        self._max_lines = 10000
        self._pending: list[str] = []
        self._font_size = 11
        self._build_ui()

        # Batch flush timer — collects lines and flushes every 50ms
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(50)
        self._flush_timer.timeout.connect(self._flush_pending)

    def set_adb(self, adb: ADBClient) -> None:
        self._adb = adb

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        # --- Filter bar ---
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
        self._pid_filter.setPlaceholderText("PID...")
        self._pid_filter.setMaximumWidth(80)
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

        # --- Display settings bar ---
        display_row = QHBoxLayout()

        display_row.addWidget(QLabel("Font:"))
        self._font_spin = QSpinBox()
        self._font_spin.setRange(7, 24)
        self._font_spin.setValue(self._font_size)
        self._font_spin.setSuffix(" px")
        self._font_spin.setFixedWidth(80)
        self._font_spin.valueChanged.connect(self._on_font_size_changed)
        display_row.addWidget(self._font_spin)

        self._wrap_check = QCheckBox("Line Wrap")
        self._wrap_check.setChecked(False)
        self._wrap_check.toggled.connect(self._on_wrap_toggled)
        display_row.addWidget(self._wrap_check)

        display_row.addWidget(QLabel("Max Lines:"))
        self._max_lines_spin = QSpinBox()
        self._max_lines_spin.setRange(1000, 100000)
        self._max_lines_spin.setSingleStep(1000)
        self._max_lines_spin.setValue(self._max_lines)
        self._max_lines_spin.setFixedWidth(100)
        self._max_lines_spin.valueChanged.connect(self._on_max_lines_changed)
        display_row.addWidget(self._max_lines_spin)

        display_row.addStretch()
        layout.addLayout(display_row)

        # --- Log output (QPlainTextEdit + highlighter) ---
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(QFont("Menlo", self._font_size))
        self._output.setObjectName("logcatOutput")
        self._output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._output.setMaximumBlockCount(self._max_lines)
        self._output.setUndoRedoEnabled(False)

        self._highlighter = LogcatHighlighter(self._output.document())

        layout.addWidget(self._output)

        # --- Control bar ---
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
        self._rate_label = QLabel("")
        ctrl_row.addStretch()
        ctrl_row.addWidget(self._rate_label)
        ctrl_row.addWidget(self._count_label)

        layout.addLayout(ctrl_row)

    # --- Font / display controls ---

    def _on_font_size_changed(self, size: int) -> None:
        self._font_size = size
        font = self._output.font()
        font.setPointSize(size)
        self._output.setFont(font)

    def _on_wrap_toggled(self, on: bool) -> None:
        if on:
            self._output.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        else:
            self._output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

    def _on_max_lines_changed(self, value: int) -> None:
        self._max_lines = value
        self._output.setMaximumBlockCount(value)

    # --- Logcat control ---

    def start_logcat(self) -> None:
        """Start streaming logcat."""
        if not self._adb or self._reader:
            return
        self._reader = LogcatReader(self._adb)
        self._reader.line_received.connect(self._on_line)
        self._reader.error_occurred.connect(
            lambda e: self.status_message.emit(f"Logcat error: {e}")
        )
        self._reader.start()
        self._flush_timer.start()
        self._start_btn.setEnabled(False)
        self._pause_btn.setEnabled(True)
        self.status_message.emit("Logcat started")

    def stop_logcat(self) -> None:
        """Stop streaming logcat."""
        self._flush_timer.stop()
        self._flush_pending()
        if self._reader:
            self._reader.stop()
            self._reader = None
        self._start_btn.setEnabled(True)
        self._pause_btn.setEnabled(False)
        self._paused = False
        self._pause_btn.setText("Pause")
        self._rate_label.setText("")
        self.status_message.emit("Logcat stopped")

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self._pause_btn.setText("Resume" if self._paused else "Pause")

    # --- Line processing (batched) ---

    def _on_line(self, line: str) -> None:
        """Buffer incoming lines. Actual display happens in _flush_pending."""
        self._lines.append(line)
        if len(self._lines) > self._max_lines:
            self._lines = self._lines[-self._max_lines:]

        if self._paused:
            return

        if self._should_show(line):
            self._pending.append(line)

    def _flush_pending(self) -> None:
        """Flush buffered lines to the display in one batch — called by timer."""
        if not self._pending:
            return

        batch = self._pending
        self._pending = []

        # Block signals on highlighter during bulk insert for speed
        self._highlighter.blockSignals(True)
        self._output.setUpdatesEnabled(False)

        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # Join all lines and insert as single block
        text = "\n".join(batch)
        cursor.insertText(text + "\n")

        self._output.setUpdatesEnabled(True)
        self._highlighter.blockSignals(False)

        # Re-highlight the newly inserted blocks
        self._highlighter.rehighlight()

        self._count_label.setText(f"{len(self._lines)} lines")
        self._rate_label.setText(f"+{len(batch)}")

        if self._auto_scroll:
            self._output.moveCursor(QTextCursor.MoveOperation.End)

    def _should_show(self, line: str) -> bool:
        """Check if a line passes the current filters."""
        min_level = self._level_combo.currentData()
        m = LOGCAT_RE.match(line)

        if m:
            level = m.group(4)
            if self.LEVEL_ORDER.index(level) < self.LEVEL_ORDER.index(min_level):
                return False
            tag_filter = self._tag_filter.text().strip().lower()
            if tag_filter and tag_filter not in m.group(5).lower():
                return False
            pid_filter = self._pid_filter.text().strip()
            if pid_filter and m.group(2) != pid_filter:
                return False

        search = self._search_filter.text().strip().lower()
        if search and search not in line.lower():
            return False

        return True

    # --- Actions ---

    def _clear(self) -> None:
        self._output.clear()
        self._lines.clear()
        self._pending.clear()
        self._count_label.setText("0 lines")
        self._rate_label.setText("")

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
