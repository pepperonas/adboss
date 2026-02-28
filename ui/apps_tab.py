"""App Manager tab — list, install, uninstall, permissions."""

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QPushButton,
    QLineEdit,
    QCheckBox,
    QMenu,
    QFileDialog,
    QMessageBox,
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QLabel,
)

from core.adb_client import ADBClient

logger = logging.getLogger(__name__)


class PackageLoader(QThread):
    """Load packages in a background thread."""

    finished = Signal(list)

    def __init__(self, adb: ADBClient, include_system: bool, parent=None) -> None:
        super().__init__(parent)
        self.adb = adb
        self.include_system = include_system

    def run(self) -> None:
        try:
            packages = self.adb.list_packages(self.include_system)
            result = []
            for pkg in packages:
                info = self.adb.get_package_info(pkg)
                result.append(info)
            self.finished.emit(result)
        except Exception as e:
            logger.exception("Failed to load packages")
            self.finished.emit([])


class PermissionsDialog(QDialog):
    """Dialog showing app permissions with grant/revoke toggles."""

    def __init__(self, adb: ADBClient, package: str, parent=None) -> None:
        super().__init__(parent)
        self._adb = adb
        self._package = package
        self.setWindowTitle(f"Permissions — {package}")
        self.setMinimumSize(500, 400)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Permissions for {package}:"))

        self._list = QListWidget()
        layout.addWidget(self._list)

        perms = adb.get_app_permissions(package)
        for p in perms:
            item = QListWidgetItem(p["name"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if p["granted"] else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, p["name"])
            self._list.addItem(item)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Close
        )
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply(self) -> None:
        for i in range(self._list.count()):
            item = self._list.item(i)
            perm = item.data(Qt.ItemDataRole.UserRole)
            if item.checkState() == Qt.CheckState.Checked:
                self._adb.grant_permission(self._package, perm)
            else:
                self._adb.revoke_permission(self._package, perm)
        QMessageBox.information(self, "Permissions", "Permissions updated.")


class AppsTab(QWidget):
    """App manager — browse, install, uninstall, manage permissions."""

    status_message = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._adb: ADBClient | None = None
        self._loader: PackageLoader | None = None
        self._packages: list[dict] = []
        self.setAcceptDrops(True)
        self._build_ui()

    def set_adb(self, adb: ADBClient) -> None:
        self._adb = adb

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".apk"):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event) -> None:
        if not self._adb:
            self.status_message.emit("No device connected")
            return
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".apk"):
                self.status_message.emit(f"Installing {Path(path).name}...")
                result = self._adb.install_apk(path)
                self.status_message.emit(f"Install: {result}")
                self.refresh()
                return

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Toolbar
        toolbar = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search packages...")
        self._search.textChanged.connect(self._filter_table)
        toolbar.addWidget(self._search)

        self._system_check = QCheckBox("Show system apps")
        self._system_check.stateChanged.connect(lambda: self.refresh())
        toolbar.addWidget(self._system_check)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)

        install_btn = QPushButton("Install APK...")
        install_btn.clicked.connect(self._install_apk)
        toolbar.addWidget(install_btn)

        layout.addLayout(toolbar)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["Package", "Version", "Installed"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._context_menu)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._table)

        # Action buttons
        actions = QHBoxLayout()
        for label, handler in [
            ("Launch", self._launch), ("Force Stop", self._force_stop),
            ("Uninstall", self._uninstall), ("Clear Data", self._clear_data),
            ("Permissions", self._show_permissions),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(handler)
            actions.addWidget(btn)
        layout.addLayout(actions)

    def refresh(self) -> None:
        """Reload the package list."""
        if not self._adb:
            return
        self.status_message.emit("Loading packages...")
        include_system = self._system_check.isChecked()
        self._loader = PackageLoader(self._adb, include_system)
        self._loader.finished.connect(self._on_packages_loaded)
        self._loader.start()

    def _on_packages_loaded(self, packages: list[dict]) -> None:
        self._packages = sorted(packages, key=lambda p: p.get("package", ""))
        self._populate_table(self._packages)
        self.status_message.emit(f"Loaded {len(packages)} packages")

    def _populate_table(self, packages: list[dict]) -> None:
        self._table.setRowCount(len(packages))
        for row, pkg in enumerate(packages):
            self._table.setItem(row, 0, QTableWidgetItem(pkg.get("package", "")))
            self._table.setItem(row, 1, QTableWidgetItem(pkg.get("version", "")))
            self._table.setItem(row, 2, QTableWidgetItem(pkg.get("installed", "")))

    def _filter_table(self, text: str) -> None:
        filtered = [p for p in self._packages if text.lower() in p.get("package", "").lower()]
        self._populate_table(filtered)

    def _selected_package(self) -> str | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        return item.text() if item else None

    def _context_menu(self, pos) -> None:
        pkg = self._selected_package()
        if not pkg:
            return
        menu = QMenu(self)
        menu.addAction("Launch", self._launch)
        menu.addAction("Force Stop", self._force_stop)
        menu.addAction("Uninstall", self._uninstall)
        menu.addAction("Clear Data", self._clear_data)
        menu.addAction("Disable", self._disable)
        menu.addAction("Enable", self._enable)
        menu.addAction("Permissions", self._show_permissions)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _launch(self) -> None:
        pkg = self._selected_package()
        if pkg and self._adb:
            self._adb.launch_app(pkg)
            self.status_message.emit(f"Launched {pkg}")

    def _force_stop(self) -> None:
        pkg = self._selected_package()
        if pkg and self._adb:
            self._adb.force_stop(pkg)
            self.status_message.emit(f"Force stopped {pkg}")

    def _uninstall(self) -> None:
        pkg = self._selected_package()
        if not pkg or not self._adb:
            return
        reply = QMessageBox.question(
            self, "Uninstall", f"Uninstall {pkg}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            result = self._adb.uninstall_app(pkg)
            self.status_message.emit(f"Uninstall {pkg}: {result}")
            self.refresh()

    def _clear_data(self) -> None:
        pkg = self._selected_package()
        if pkg and self._adb:
            result = self._adb.clear_app_data(pkg)
            self.status_message.emit(f"Clear data {pkg}: {result}")

    def _disable(self) -> None:
        pkg = self._selected_package()
        if pkg and self._adb:
            self._adb.disable_app(pkg)
            self.status_message.emit(f"Disabled {pkg}")

    def _enable(self) -> None:
        pkg = self._selected_package()
        if pkg and self._adb:
            self._adb.enable_app(pkg)
            self.status_message.emit(f"Enabled {pkg}")

    def _show_permissions(self) -> None:
        pkg = self._selected_package()
        if pkg and self._adb:
            dlg = PermissionsDialog(self._adb, pkg, self)
            dlg.exec()

    def _install_apk(self) -> None:
        if not self._adb:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Select APK", "", "APK Files (*.apk)")
        if path:
            self.status_message.emit(f"Installing {Path(path).name}...")
            result = self._adb.install_apk(path)
            self.status_message.emit(f"Install: {result}")
            self.refresh()
