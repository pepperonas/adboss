"""File transfer tab — dual-pane browser with push/pull and screenshot."""

import logging
import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QMimeData, QUrl
from PySide6.QtGui import QPixmap, QDrag
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QGroupBox,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QPushButton,
    QLineEdit,
    QProgressBar,
    QFileDialog,
    QLabel,
    QDialog,
)

from core.adb_client import ADBClient
from core.file_transfer import FileTransferWorker
from utils.config import config

logger = logging.getLogger(__name__)


class DragTreeWidget(QTreeWidget):
    """QTreeWidget that supports starting drags with file path info."""

    file_dragged = Signal(str)  # full path of dragged file

    def __init__(self, is_remote: bool, parent=None) -> None:
        super().__init__(parent)
        self._is_remote = is_remote
        self._current_path = ""
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.DragDrop)

    def set_current_path(self, path: str) -> None:
        self._current_path = path

    def startDrag(self, supportedActions) -> None:
        item = self.currentItem()
        if not item:
            return
        name = item.text(0)
        if self._is_remote:
            full_path = self._current_path.rstrip("/") + "/" + name
        else:
            full_path = str(Path(self._current_path) / name)
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData("application/x-adboss-transfer", full_path.encode("utf-8"))
        mime.setText(full_path)
        if self._is_remote:
            mime.setData("application/x-adboss-remote", b"1")
        else:
            mime.setData("application/x-adboss-local", b"1")
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat("application/x-adboss-transfer"):
            # Accept drops from the opposite panel only
            is_from_remote = event.mimeData().hasFormat("application/x-adboss-remote")
            if is_from_remote != self._is_remote:
                event.acceptProposedAction()
                return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat("application/x-adboss-transfer"):
            is_from_remote = event.mimeData().hasFormat("application/x-adboss-remote")
            if is_from_remote != self._is_remote:
                event.acceptProposedAction()
                return
        event.ignore()


class FileBrowser(QWidget):
    """A file browser panel for either local or remote files."""

    path_changed = Signal(str)
    file_dropped = Signal(str, str)  # source_path, target_dir

    def __init__(self, title: str, is_remote: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._is_remote = is_remote
        self._current_path = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox(title)
        group_layout = QVBoxLayout(group)

        # Path bar
        path_row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.returnPressed.connect(self._navigate_to_path)
        path_row.addWidget(self._path_edit)

        up_btn = QPushButton("\u2b06 Up")
        up_btn.setFixedWidth(60)
        up_btn.clicked.connect(self._go_up)
        path_row.addWidget(up_btn)

        group_layout.addLayout(path_row)

        # Tree with drag support
        self._tree = DragTreeWidget(is_remote)
        self._tree.setHeaderLabels(["Name", "Size", "Permissions"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.setRootIsDecorated(False)
        self._tree.doubleClicked.connect(self._on_double_click)
        self._tree.viewport().installEventFilter(self)
        group_layout.addWidget(self._tree)

        layout.addWidget(group)

    def eventFilter(self, obj, event) -> bool:
        """Handle drops on the tree viewport."""
        if obj is self._tree.viewport() and event.type() == event.Type.Drop:
            mime = event.mimeData()
            if mime.hasFormat("application/x-adboss-transfer"):
                source_path = bytes(mime.data("application/x-adboss-transfer")).decode("utf-8")
                self.file_dropped.emit(source_path, self._current_path)
                event.acceptProposedAction()
                return True
        return super().eventFilter(obj, event)

    def set_path(self, path: str) -> None:
        self._current_path = path
        self._path_edit.setText(path)
        self._tree.set_current_path(path)

    def current_path(self) -> str:
        return self._current_path

    def selected_item(self) -> str | None:
        item = self._tree.currentItem()
        if item:
            return item.text(0)
        return None

    def selected_full_path(self) -> str | None:
        name = self.selected_item()
        if name:
            if self._is_remote:
                return self._current_path.rstrip("/") + "/" + name
            else:
                return str(Path(self._current_path) / name)
        return None

    def populate_local(self, path: str) -> None:
        """List local directory contents."""
        self._tree.clear()
        self._current_path = path
        self._path_edit.setText(path)
        self._tree.set_current_path(path)
        try:
            entries = sorted(Path(path).iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
            for entry in entries:
                item = QTreeWidgetItem()
                item.setText(0, entry.name)
                if entry.is_dir():
                    item.setText(1, "<DIR>")
                    item.setData(0, Qt.ItemDataRole.UserRole, "dir")
                else:
                    size = entry.stat().st_size
                    item.setText(1, self._format_size(size))
                    item.setData(0, Qt.ItemDataRole.UserRole, "file")
                self._tree.addTopLevelItem(item)
        except PermissionError:
            logger.warning("Permission denied: %s", path)

    def populate_remote(self, files: list[dict]) -> None:
        """Populate with remote file listing."""
        self._tree.clear()
        self._path_edit.setText(self._current_path)
        self._tree.set_current_path(self._current_path)
        dirs = sorted([f for f in files if f["is_dir"]], key=lambda f: f["name"].lower())
        regular = sorted([f for f in files if not f["is_dir"]], key=lambda f: f["name"].lower())
        for f in dirs + regular:
            item = QTreeWidgetItem()
            item.setText(0, f["name"])
            if f["is_dir"]:
                item.setText(1, "<DIR>")
                item.setData(0, Qt.ItemDataRole.UserRole, "dir")
            else:
                item.setText(1, self._format_size(f["size"]))
                item.setData(0, Qt.ItemDataRole.UserRole, "file")
            item.setText(2, f.get("permissions", ""))
            self._tree.addTopLevelItem(item)

    def _format_size(self, size: int) -> str:
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        return f"{size / (1024 * 1024 * 1024):.2f} GB"

    def _navigate_to_path(self) -> None:
        path = self._path_edit.text().strip()
        if path:
            self.path_changed.emit(path)

    def _go_up(self) -> None:
        if self._is_remote:
            parts = self._current_path.rstrip("/").rsplit("/", 1)
            parent = parts[0] if parts[0] else "/"
        else:
            parent = str(Path(self._current_path).parent)
        self.path_changed.emit(parent)

    def _on_double_click(self, index) -> None:
        item = self._tree.itemFromIndex(index)
        if item and item.data(0, Qt.ItemDataRole.UserRole) == "dir":
            name = item.text(0)
            if self._is_remote:
                new_path = self._current_path.rstrip("/") + "/" + name
            else:
                new_path = str(Path(self._current_path) / name)
            self.path_changed.emit(new_path)


class FilesTab(QWidget):
    """Dual-pane file transfer with screenshot/screenrecord support."""

    status_message = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._adb: ADBClient | None = None
        self._transfer_worker: FileTransferWorker | None = None
        self._recording = False
        self._record_start_time = 0.0
        self._build_ui()

    def set_adb(self, adb: ADBClient) -> None:
        self._adb = adb

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # File browsers
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._remote_browser = FileBrowser("Device (Remote)", is_remote=True)
        self._remote_browser.path_changed.connect(self._navigate_remote)
        self._remote_browser.file_dropped.connect(self._on_drop_to_remote)
        splitter.addWidget(self._remote_browser)

        self._local_browser = FileBrowser("Desktop (Local)", is_remote=False)
        self._local_browser.path_changed.connect(self._navigate_local)
        self._local_browser.file_dropped.connect(self._on_drop_to_local)
        splitter.addWidget(self._local_browser)

        layout.addWidget(splitter)

        # Transfer controls
        transfer_row = QHBoxLayout()
        pull_btn = QPushButton("\u2b05 Pull (Device \u2192 Desktop)")
        pull_btn.clicked.connect(self._pull_file)
        transfer_row.addWidget(pull_btn)

        push_btn = QPushButton("\u27a1 Push (Desktop \u2192 Device)")
        push_btn.clicked.connect(self._push_file)
        transfer_row.addWidget(push_btn)

        self._progress = QProgressBar()
        self._progress.setFixedHeight(18)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        transfer_row.addWidget(self._progress)
        layout.addLayout(transfer_row)

        # Screenshot / Record
        media_row = QHBoxLayout()
        screenshot_btn = QPushButton("Screenshot")
        screenshot_btn.clicked.connect(self._take_screenshot)
        media_row.addWidget(screenshot_btn)

        self._record_btn = QPushButton("Start Recording")
        self._record_btn.clicked.connect(self._toggle_recording)
        media_row.addWidget(self._record_btn)

        self._record_label = QLabel("")
        media_row.addWidget(self._record_label)
        media_row.addStretch()
        layout.addLayout(media_row)

    def init_paths(self) -> None:
        """Initialize file browsers with default paths."""
        local_path = config.get("last_local_path", str(Path.home()))
        remote_path = config.get("last_remote_path", "/sdcard/")
        self._navigate_local(local_path)
        self._navigate_remote(remote_path)

    def _navigate_local(self, path: str) -> None:
        self._local_browser.populate_local(path)
        config.set("last_local_path", path)

    def _navigate_remote(self, path: str) -> None:
        if not self._adb:
            return
        self._remote_browser.set_path(path)
        files = self._adb.list_remote_files(path)
        self._remote_browser.populate_remote(files)
        config.set("last_remote_path", path)

    def _on_drop_to_remote(self, source_path: str, target_dir: str) -> None:
        """Handle file dropped from local panel onto remote panel (push)."""
        if not self._adb:
            return
        self._start_transfer(source_path, target_dir, "push")

    def _on_drop_to_local(self, source_path: str, target_dir: str) -> None:
        """Handle file dropped from remote panel onto local panel (pull)."""
        if not self._adb:
            return
        self._start_transfer(source_path, target_dir, "pull")

    def _pull_file(self) -> None:
        remote = self._remote_browser.selected_full_path()
        if not remote or not self._adb:
            self.status_message.emit("Select a remote file to pull")
            return
        local_dir = self._local_browser.current_path()
        self._start_transfer(remote, local_dir, "pull")

    def _push_file(self) -> None:
        local = self._local_browser.selected_full_path()
        if not local or not self._adb:
            self.status_message.emit("Select a local file to push")
            return
        remote_dir = self._remote_browser.current_path()
        self._start_transfer(local, remote_dir, "push")

    def _start_transfer(self, source: str, dest: str, direction: str) -> None:
        serial = self._adb.device_serial if self._adb else None
        self._progress.setValue(0)
        self._transfer_worker = FileTransferWorker(source, dest, direction, serial)
        self._transfer_worker.progress.connect(self._progress.setValue)
        self._transfer_worker.finished_transfer.connect(self._on_transfer_done)
        self._transfer_worker.start()
        self.status_message.emit(f"{direction.capitalize()}ing {source}...")

    def _on_transfer_done(self, success: bool, message: str) -> None:
        if success:
            self.status_message.emit(f"Transfer complete: {message}")
            self._navigate_local(self._local_browser.current_path())
            if self._adb:
                self._navigate_remote(self._remote_browser.current_path())
        else:
            self.status_message.emit(f"Transfer failed: {message}")

    def _take_screenshot(self) -> None:
        if not self._adb:
            return
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save Screenshot", str(Path.home() / "screenshot.png"), "PNG (*.png)"
        )
        if not save_path:
            return
        self.status_message.emit("Taking screenshot...")
        if self._adb.take_screenshot(save_path):
            self.status_message.emit(f"Screenshot saved: {save_path}")
            self._show_screenshot_preview(save_path)
        else:
            self.status_message.emit("Screenshot failed")

    def _show_screenshot_preview(self, path: str) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Screenshot Preview")
        layout = QVBoxLayout(dlg)
        label = QLabel()
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                400, 700,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            label.setPixmap(scaled)
        layout.addWidget(label)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn)
        dlg.exec()

    def _toggle_recording(self) -> None:
        if not self._adb:
            return
        if not self._recording:
            if self._adb.start_screenrecord():
                self._recording = True
                self._record_start_time = time.time()
                self._record_btn.setText("Stop Recording")
                self._record_label.setText("Recording...")
                self.status_message.emit("Screen recording started")
            else:
                self.status_message.emit("Failed to start recording")
        else:
            self._adb.stop_screenrecord()
            self._recording = False
            self._record_btn.setText("Start Recording")
            elapsed = int(time.time() - self._record_start_time)
            self._record_label.setText(f"Recorded {elapsed}s")
            self.status_message.emit(
                "Recording stopped — file on device at /sdcard/record.mp4"
            )
