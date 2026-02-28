"""Shell tab — ADB shell terminal emulator."""

import logging
from datetime import datetime

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QLineEdit,
    QPushButton,
    QLabel,
)

from core.adb_client import ADBClient

logger = logging.getLogger(__name__)

SHELL_HISTORY_MAX = 100


class ShellWorker(QThread):
    """Run a shell command in a background thread."""

    output_ready = Signal(str, str)  # command, output

    def __init__(self, adb: ADBClient, command: str, parent=None) -> None:
        super().__init__(parent)
        self.adb = adb
        self.command = command

    def run(self) -> None:
        try:
            output = self.adb.execute_shell(self.command)
            self.output_ready.emit(self.command, output)
        except Exception as e:
            self.output_ready.emit(self.command, f"Error: {e}")


class ShellTab(QWidget):
    """Interactive ADB shell console."""

    status_message = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._adb: ADBClient | None = None
        self._history: list[str] = []
        self._history_idx = -1
        self._worker: ShellWorker | None = None
        self._build_ui()

    def set_adb(self, adb: ADBClient) -> None:
        self._adb = adb

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Quick action buttons
        quick = QHBoxLayout()
        for label, cmd in [
            ("Reboot", "__reboot__"),
            ("Bootloader", "__reboot_bootloader__"),
            ("Recovery", "__reboot_recovery__"),
            ("Get Props", "getprop"),
            ("Processes", "ps -A"),
            ("Disk Usage", "df -h"),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _, c=cmd: self._run_command(c))
            quick.addWidget(btn)
        layout.addLayout(quick)

        # Output area
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(QFont("Menlo, Consolas, monospace", 11))
        self._output.setObjectName("shellOutput")
        layout.addWidget(self._output)

        # Input
        input_row = QHBoxLayout()
        prompt = QLabel("adb shell>")
        prompt.setObjectName("shellPrompt")
        prompt.setFont(QFont("Menlo, Consolas, monospace", 11))
        input_row.addWidget(prompt)

        self._input = QLineEdit()
        self._input.setFont(QFont("Menlo, Consolas, monospace", 11))
        self._input.setObjectName("shellInput")
        self._input.returnPressed.connect(self._on_enter)
        self._input.installEventFilter(self)
        input_row.addWidget(self._input)

        send_btn = QPushButton("Run")
        send_btn.clicked.connect(self._on_enter)
        input_row.addWidget(send_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._output.clear)
        input_row.addWidget(clear_btn)

        layout.addLayout(input_row)

    def eventFilter(self, obj, event) -> bool:
        """Handle up/down arrows for command history."""
        if obj is self._input and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Up:
                self._navigate_history(-1)
                return True
            elif event.key() == Qt.Key.Key_Down:
                self._navigate_history(1)
                return True
        return super().eventFilter(obj, event)

    def _navigate_history(self, direction: int) -> None:
        if not self._history:
            return
        self._history_idx = max(0, min(len(self._history) - 1, self._history_idx + direction))
        self._input.setText(self._history[self._history_idx])

    def _on_enter(self) -> None:
        cmd = self._input.text().strip()
        if not cmd:
            return
        self._input.clear()

        # History management
        if not self._history or self._history[-1] != cmd:
            self._history.append(cmd)
            if len(self._history) > SHELL_HISTORY_MAX:
                self._history.pop(0)
        self._history_idx = len(self._history)

        self._run_command(cmd)

    def _run_command(self, cmd: str) -> None:
        if not self._adb:
            self._append_output("", "No device connected")
            return

        # Special reboot commands
        if cmd == "__reboot__":
            self._adb.reboot()
            self._append_output("reboot", "Rebooting device...")
            return
        elif cmd == "__reboot_bootloader__":
            self._adb.reboot("bootloader")
            self._append_output("reboot bootloader", "Rebooting to bootloader...")
            return
        elif cmd == "__reboot_recovery__":
            self._adb.reboot("recovery")
            self._append_output("reboot recovery", "Rebooting to recovery...")
            return

        self._worker = ShellWorker(self._adb, cmd)
        self._worker.output_ready.connect(self._on_output)
        self._worker.start()
        self.status_message.emit(f"Running: {cmd}")

    def _on_output(self, command: str, output: str) -> None:
        self._append_output(command, output)
        self.status_message.emit("Ready")

    def _append_output(self, command: str, output: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._output.append(f'<span style="color:#00BCD4;">[{timestamp}]</span> '
                            f'<span style="color:#FFC107;">$ {command}</span>')
        if output.strip():
            escaped = output.replace("<", "&lt;").replace(">", "&gt;")
            self._output.append(f'<span style="color:#CCCCCC;">{escaped}</span>')
        self._output.append("")
        self._output.moveCursor(QTextCursor.MoveOperation.End)
