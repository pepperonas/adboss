"""Settings tab — browse and modify Android system/secure/global settings."""

import logging

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
)

from core.adb_client import ADBClient

logger = logging.getLogger(__name__)

NAMESPACES = ["system", "secure", "global"]


class SettingsLoaderThread(QThread):
    """Load settings in background to avoid blocking the UI."""

    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, adb: ADBClient, namespace: str) -> None:
        super().__init__()
        self._adb = adb
        self._namespace = namespace

    def run(self) -> None:
        try:
            result = self._adb.list_settings(self._namespace)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class SettingsTab(QWidget):
    """Browse and edit Android settings (system/secure/global)."""

    status_message = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._adb: ADBClient | None = None
        self._all_settings: dict[str, str] = {}
        self._loader: SettingsLoaderThread | None = None
        self._build_ui()

    def set_adb(self, adb: ADBClient) -> None:
        self._adb = adb

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Top bar: namespace + search + refresh
        top_row = QHBoxLayout()

        top_row.addWidget(QLabel("Namespace:"))
        self._namespace_combo = QComboBox()
        self._namespace_combo.addItems(NAMESPACES)
        self._namespace_combo.currentTextChanged.connect(self._on_namespace_changed)
        top_row.addWidget(self._namespace_combo)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search key...")
        self._search.textChanged.connect(self._filter_table)
        top_row.addWidget(self._search, 1)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.refresh)
        top_row.addWidget(self._refresh_btn)

        layout.addLayout(top_row)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(2)
        self._table.setHorizontalHeaderLabels(["Key", "Value"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.cellDoubleClicked.connect(self._on_row_double_click)
        layout.addWidget(self._table)

        # Bottom bar: key/value edit + set
        edit_group = QGroupBox("Edit Setting")
        edit_layout = QHBoxLayout(edit_group)

        edit_layout.addWidget(QLabel("Key:"))
        self._key_input = QLineEdit()
        self._key_input.setPlaceholderText("setting_key")
        edit_layout.addWidget(self._key_input, 1)

        edit_layout.addWidget(QLabel("Value:"))
        self._value_input = QLineEdit()
        self._value_input.setPlaceholderText("value")
        edit_layout.addWidget(self._value_input, 1)

        self._set_btn = QPushButton("Set")
        self._set_btn.clicked.connect(self._set_setting)
        edit_layout.addWidget(self._set_btn)

        layout.addWidget(edit_group)

    def _on_namespace_changed(self, _text: str) -> None:
        self.refresh()

    def refresh(self) -> None:
        if not self._adb or not self._adb.device_serial:
            self.status_message.emit("No device connected")
            return

        namespace = self._namespace_combo.currentText()
        self._refresh_btn.setEnabled(False)
        self.status_message.emit(f"Loading {namespace} settings...")

        self._loader = SettingsLoaderThread(self._adb, namespace)
        self._loader.finished.connect(self._on_settings_loaded)
        self._loader.error.connect(self._on_load_error)
        self._loader.start()

    def _on_settings_loaded(self, settings: dict) -> None:
        self._all_settings = settings
        self._populate_table(settings)
        self._refresh_btn.setEnabled(True)
        ns = self._namespace_combo.currentText()
        self.status_message.emit(f"Loaded {len(settings)} {ns} settings")

    def _on_load_error(self, message: str) -> None:
        self._refresh_btn.setEnabled(True)
        self.status_message.emit(f"Error loading settings: {message}")

    def _populate_table(self, settings: dict[str, str]) -> None:
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        search = self._search.text().lower()

        for key, value in sorted(settings.items()):
            if search and search not in key.lower():
                continue
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(key))
            self._table.setItem(row, 1, QTableWidgetItem(value))

        self._table.setSortingEnabled(True)

    def _filter_table(self, _text: str) -> None:
        self._populate_table(self._all_settings)

    def _on_row_double_click(self, row: int, _col: int) -> None:
        key_item = self._table.item(row, 0)
        value_item = self._table.item(row, 1)
        if key_item:
            self._key_input.setText(key_item.text())
        if value_item:
            self._value_input.setText(value_item.text())

    def _set_setting(self) -> None:
        if not self._adb or not self._adb.device_serial:
            self.status_message.emit("No device connected")
            return

        key = self._key_input.text().strip()
        value = self._value_input.text().strip()
        if not key:
            self.status_message.emit("Key cannot be empty")
            return

        namespace = self._namespace_combo.currentText()
        result = self._adb.put_setting(namespace, key, value)
        self.status_message.emit(f"Set {namespace}/{key} = {value}")
        self.refresh()
