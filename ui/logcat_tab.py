"""Logcat tab — high-performance live logcat viewer with filters and color coding."""

import logging
import re
import subprocess
import time
from collections import deque
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QThread, QTimer
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

LEVEL_ORDER = "VDIWEFA"

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


class LogcatView(QPlainTextEdit):
    """QPlainTextEdit subclass with controllable auto-scroll.

    When follow is off, preserves the user's viewport position even as
    new lines are appended and old lines are trimmed by maxBlockCount.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._follow = True

    def set_follow(self, on: bool) -> None:
        self._follow = on

    def append_lines(self, text: str) -> None:
        """Append text. Scroll behavior controlled by _follow flag."""
        bar = self.verticalScrollBar()

        if self._follow:
            cursor = QTextCursor(self.document())
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(text)
            bar.setValue(bar.maximum())
        else:
            # Track which block is at the top of the viewport
            target_block = self.firstVisibleBlock().blockNumber()

            cursor = QTextCursor(self.document())
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(text)

            # After insert (and possible trimming), scroll back to
            # show the same block. The block number stays valid because
            # trimming removes from the top, shifting all numbers down,
            # but firstVisibleBlock already accounts for that.
            block = self.document().findBlockByNumber(target_block)
            if block.isValid():
                cursor = QTextCursor(block)
                # Use setTextCursor + centerOnScroll to position viewport
                self.setTextCursor(cursor)
                # Now ensure it's at the TOP of viewport, not centered
                bar.setValue(target_block)


class LogcatReader(QThread):
    """Read logcat in background, filter there, emit pre-filtered batches."""

    batch_ready = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, adb: ADBClient, parent=None) -> None:
        super().__init__(parent)
        self._adb = adb
        self._process: subprocess.Popen | None = None
        self._running = False

        # Filter state (set from GUI thread, read from worker thread)
        self.min_level_idx = 0
        self.tag_filter = ""
        self.pid_filter = ""
        self.search_filter = ""

    def run(self) -> None:
        self._running = True
        batch: list[str] = []
        last_emit = time.monotonic()
        try:
            self._process = self._adb.stream_logcat()
            if not self._process.stdout:
                return
            for raw_line in self._process.stdout:
                if not self._running:
                    break
                line = raw_line.rstrip("\n")
                if self._passes_filter(line):
                    batch.append(line)
                # Emit when batch is large enough OR enough time has passed
                now = time.monotonic()
                if len(batch) >= 200 or (batch and now - last_emit >= 0.1):
                    self.batch_ready.emit(batch)
                    batch = []
                    last_emit = now
            # Emit remaining
            if batch and self._running:
                self.batch_ready.emit(batch)
        except Exception as e:
            if self._running:
                self.error_occurred.emit(str(e))

    def _passes_filter(self, line: str) -> bool:
        """Filter on the worker thread to avoid GUI overhead."""
        m = LOGCAT_RE.match(line)
        if m:
            level = m.group(4)
            if LEVEL_ORDER.index(level) < self.min_level_idx:
                return False
            tf = self.tag_filter
            if tf and tf not in m.group(5).lower():
                return False
            pf = self.pid_filter
            if pf and m.group(2) != pf:
                return False

        sf = self.search_filter
        if sf and sf not in line.lower():
            return False
        return True

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

    # Max lines to insert per flush to keep UI responsive
    _FLUSH_BATCH_LIMIT = 500

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._adb: ADBClient | None = None
        self._reader: LogcatReader | None = None
        self._paused = False
        self._auto_scroll = True
        self._line_count = 0
        self._max_lines = 10000
        self._pending: deque[str] = deque()
        self._font_size = 11
        self._build_ui()

        # Batch flush timer — collects lines and flushes every 60ms
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(60)
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
        self._level_combo.currentIndexChanged.connect(self._sync_filters)
        filter_row.addWidget(self._level_combo)

        filter_row.addWidget(QLabel("Tag:"))
        self._tag_filter = QLineEdit()
        self._tag_filter.setPlaceholderText("Filter by tag...")
        self._tag_filter.setMaximumWidth(150)
        self._tag_filter.textChanged.connect(self._sync_filters)
        filter_row.addWidget(self._tag_filter)

        filter_row.addWidget(QLabel("PID:"))
        self._pid_filter = QLineEdit()
        self._pid_filter.setPlaceholderText("PID...")
        self._pid_filter.setMaximumWidth(80)
        self._pid_filter.textChanged.connect(self._sync_filters)
        filter_row.addWidget(self._pid_filter)

        filter_row.addWidget(QLabel("Search:"))
        self._search_filter = QLineEdit()
        self._search_filter.setPlaceholderText("Search text...")
        self._search_filter.setMaximumWidth(200)
        self._search_filter.textChanged.connect(self._sync_filters)
        filter_row.addWidget(self._search_filter)

        filter_row.addStretch()

        self._auto_scroll_check = QCheckBox("Auto-scroll")
        self._auto_scroll_check.setChecked(True)
        self._auto_scroll_check.toggled.connect(self._on_auto_scroll_toggled)
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

        # --- Log output (LogcatView + highlighter) ---
        self._output = LogcatView()
        self._output.setReadOnly(True)
        self._output.setFont(QFont("JetBrains Mono", self._font_size))
        # Fallback chain if JetBrains Mono not installed
        font = self._output.font()
        if not font.exactMatch():
            for fallback in ("Fira Code", "Source Code Pro", "Menlo", "Consolas", "monospace"):
                font.setFamily(fallback)
                self._output.setFont(font)
                if self._output.font().exactMatch():
                    break
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

    def _on_auto_scroll_toggled(self, on: bool) -> None:
        self._auto_scroll = on
        self._output.set_follow(on)
        if on:
            self._output.moveCursor(QTextCursor.MoveOperation.End)

    # --- Filter sync (push filters to worker thread) ---

    def _sync_filters(self) -> None:
        """Push current filter values to the reader thread."""
        if not self._reader:
            return
        level_data = self._level_combo.currentData()
        self._reader.min_level_idx = LEVEL_ORDER.index(level_data)
        self._reader.tag_filter = self._tag_filter.text().strip().lower()
        self._reader.pid_filter = self._pid_filter.text().strip()
        self._reader.search_filter = self._search_filter.text().strip().lower()

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
        self._sync_filters()
        self._reader.batch_ready.connect(self._on_batch)
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

    def _on_batch(self, lines: list[str]) -> None:
        """Receive a pre-filtered batch from the worker thread."""
        self._line_count += len(lines)
        # Always buffer — pause only prevents flushing to display
        self._pending.extend(lines)

    def _flush_pending(self) -> None:
        """Flush buffered lines to the display — capped per tick for responsiveness."""
        if not self._pending or self._paused:
            self._count_label.setText(f"{self._line_count} lines")
            return

        # Take at most _FLUSH_BATCH_LIMIT lines per tick
        count = min(len(self._pending), self._FLUSH_BATCH_LIMIT)
        batch = [self._pending.popleft() for _ in range(count)]

        self._output.append_lines("\n".join(batch) + "\n")

        self._count_label.setText(f"{self._line_count} lines")
        self._rate_label.setText(f"+{count}")

    # --- Actions ---

    def _clear(self) -> None:
        self._output.clear()
        self._line_count = 0
        self._pending.clear()
        self._count_label.setText("0 lines")
        self._rate_label.setText("")

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Logcat", str(Path.home() / "logcat.txt"), "Text Files (*.txt)"
        )
        if path:
            text = self._output.toPlainText()
            Path(path).write_text(text, encoding="utf-8")
            line_count = text.count("\n")
            self.status_message.emit(f"Exported {line_count} lines to {path}")

    def cleanup(self) -> None:
        """Stop logcat reader on shutdown."""
        self.stop_logcat()
