"""File transfer with progress tracking."""

import logging
import re
import subprocess

from PySide6.QtCore import QThread, Signal

from utils.config import config

logger = logging.getLogger(__name__)


class FileTransferWorker(QThread):
    """Runs adb push/pull in a thread and reports progress."""

    progress = Signal(int)  # 0-100
    finished_transfer = Signal(bool, str)  # success, message

    def __init__(
        self,
        source: str,
        destination: str,
        direction: str,
        device_serial: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.source = source
        self.destination = destination
        self.direction = direction  # "push" or "pull"
        self.device_serial = device_serial

    def run(self) -> None:
        cmd = [config.adb_path]
        if self.device_serial:
            cmd.extend(["-s", self.device_serial])

        if self.direction == "push":
            cmd.extend(["push", self.source, self.destination])
        else:
            cmd.extend(["pull", self.source, self.destination])

        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            output_lines: list[str] = []
            if proc.stderr:
                for line in proc.stderr:
                    output_lines.append(line)
                    m = re.search(r"\[\s*(\d+)%\]", line)
                    if m:
                        self.progress.emit(int(m.group(1)))

            proc.wait()
            stdout = proc.stdout.read() if proc.stdout else ""
            all_output = stdout + "\n".join(output_lines)

            if proc.returncode == 0:
                self.progress.emit(100)
                self.finished_transfer.emit(True, all_output.strip())
            else:
                self.finished_transfer.emit(False, all_output.strip())

        except Exception as e:
            logger.exception("Transfer failed")
            self.finished_transfer.emit(False, str(e))
