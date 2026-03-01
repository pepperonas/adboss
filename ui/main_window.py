"""Main application window with tab navigation."""

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow,
    QTabWidget,
    QStatusBar,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QMenuBar,
)

from core.adb_client import ADBClient
from core.device_monitor import DeviceMonitor
from ui.dashboard_tab import DashboardTab
from ui.control_tab import ControlTab
from ui.apps_tab import AppsTab
from ui.files_tab import FilesTab
from ui.shell_tab import ShellTab
from ui.logcat_tab import LogcatTab
from ui.input_tab import InputTab
from ui.settings_tab import SettingsTab
from ui.widgets.device_selector import DeviceSelector
from utils.config import config
from version import __version__

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """ADBOSS main window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"ADBOSS v{__version__}")
        self.setMinimumSize(900, 600)
        self.resize(
            config.get("window_width", 1100),
            config.get("window_height", 750),
        )

        self._adb = ADBClient()
        self._monitor: DeviceMonitor | None = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_dashboard)

        self._build_ui()
        self._build_menu()
        self._connect_signals()

        # Start monitoring after a short delay
        QTimer.singleShot(500, self._on_device_changed)

    def _build_ui(self) -> None:
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # Header
        header = QHBoxLayout()
        title = QLabel("ADBOSS")
        title.setObjectName("appTitle")
        header.addWidget(title)
        header.addStretch()

        self._device_selector = DeviceSelector()
        self._device_selector.set_shared_adb(self._adb)
        header.addWidget(self._device_selector)
        main_layout.addLayout(header)

        # Tabs
        self._tabs = QTabWidget()
        self._tabs.setTabPosition(QTabWidget.TabPosition.North)

        self._dashboard = DashboardTab()
        self._control = ControlTab()
        self._apps = AppsTab()
        self._files = FilesTab()
        self._shell = ShellTab()
        self._logcat = LogcatTab()
        self._input = InputTab()
        self._settings = SettingsTab()

        self._tabs.addTab(self._dashboard, "Dashboard")
        self._tabs.addTab(self._control, "Control")
        self._tabs.addTab(self._apps, "Apps")
        self._tabs.addTab(self._files, "Files")
        self._tabs.addTab(self._shell, "Shell")
        self._tabs.addTab(self._logcat, "Logcat")
        self._tabs.addTab(self._input, "Input")
        self._tabs.addTab(self._settings, "Settings")

        main_layout.addWidget(self._tabs)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_label = QLabel("Disconnected")
        self._status_bar.addWidget(self._status_label, 1)
        self._copyright = QLabel("\u00a9 2026 Martin Pfeffer | celox.io")
        self._copyright.setObjectName("copyright")
        self._status_bar.addPermanentWidget(self._copyright)

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("File")
        quit_action = QAction("Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # View menu — tab shortcuts
        view_menu = menu_bar.addMenu("View")
        tab_names = [
            "Dashboard", "Control", "Apps", "Files",
            "Shell", "Logcat", "Input", "Settings",
        ]
        for i, name in enumerate(tab_names):
            action = QAction(f"{name}", self)
            action.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            idx = i
            action.triggered.connect(lambda _, x=idx: self._tabs.setCurrentIndex(x))
            view_menu.addAction(action)

        # Tools menu — context shortcuts
        tools_menu = menu_bar.addMenu("Tools")

        refresh_action = QAction("Refresh", self)
        refresh_action.setShortcut(QKeySequence("Ctrl+R"))
        refresh_action.triggered.connect(self._shortcut_refresh)
        tools_menu.addAction(refresh_action)

        logcat_toggle_action = QAction("Logcat Start/Stop", self)
        logcat_toggle_action.setShortcut(QKeySequence("Ctrl+L"))
        logcat_toggle_action.triggered.connect(self._shortcut_logcat_toggle)
        tools_menu.addAction(logcat_toggle_action)

        logcat_clear_action = QAction("Logcat Clear", self)
        logcat_clear_action.setShortcut(QKeySequence("Ctrl+K"))
        logcat_clear_action.triggered.connect(self._logcat._clear)
        tools_menu.addAction(logcat_clear_action)

        screenshot_action = QAction("Screenshot", self)
        screenshot_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        screenshot_action.triggered.connect(self._files._take_screenshot)
        tools_menu.addAction(screenshot_action)

        # Help menu
        help_menu = menu_bar.addMenu("Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _shortcut_refresh(self) -> None:
        """Context-dependent refresh: Dashboard, Apps, Files, or Settings."""
        current = self._tabs.currentWidget()
        if current is self._dashboard:
            self._refresh_dashboard()
        elif current is self._apps:
            self._apps.refresh()
        elif current is self._files:
            self._files.init_paths()
        elif current is self._settings:
            self._settings.refresh()

    def _shortcut_logcat_toggle(self) -> None:
        """Toggle logcat start/stop."""
        if self._logcat._reader and self._logcat._reader.isRunning():
            self._logcat.stop_logcat()
        else:
            self._logcat.start_logcat()

    def _connect_signals(self) -> None:
        self._device_selector.device_changed.connect(self._on_device_changed)
        self._tabs.currentChanged.connect(self._on_tab_changed)

        # Status messages from tabs
        self._control.status_message.connect(self._show_status)
        self._apps.status_message.connect(self._show_status)
        self._files.status_message.connect(self._show_status)
        self._shell.status_message.connect(self._show_status)
        self._logcat.status_message.connect(self._show_status)
        self._input.status_message.connect(self._show_status)
        self._settings.status_message.connect(self._show_status)

    def _on_tab_changed(self, index: int) -> None:
        """Auto-refresh apps when switching to the Apps tab."""
        widget = self._tabs.widget(index)
        if widget is self._apps and self._adb.device_serial and not self._apps._packages:
            self._apps.refresh()

    def _on_device_changed(self, serial: str = "") -> None:
        """Handle device selection change."""
        if not serial:
            serial = self._device_selector.current_serial()

        # Stop existing monitoring
        self._refresh_timer.stop()
        if self._monitor:
            self._monitor.stop()
            self._monitor = None

        if not serial:
            self._adb.device_serial = None
            self._status_label.setText("Disconnected")
            self._dashboard.clear()
            return

        self._adb.device_serial = serial
        self._control.set_adb(self._adb)
        self._apps.set_adb(self._adb)
        self._files.set_adb(self._adb)
        self._shell.set_adb(self._adb)
        self._logcat.set_adb(self._adb)
        self._input.set_adb(self._adb)
        self._settings.set_adb(self._adb)

        self._status_label.setText(f"Connected: {serial}")
        self._refresh_dashboard()

        interval = config.get("refresh_interval_ms", 5000)
        self._refresh_timer.start(interval)

        self._files.init_paths()

        # Clear cached packages so Apps tab reloads for the new device
        self._apps._packages.clear()
        self._apps._table.setRowCount(0)

        # If already on Apps tab, load immediately
        if self._tabs.currentWidget() is self._apps:
            self._apps.refresh()

    def _refresh_dashboard(self) -> None:
        """Start a monitoring cycle."""
        if not self._adb.device_serial:
            return
        if self._monitor and self._monitor.isRunning():
            return

        self._monitor = DeviceMonitor(self._adb)
        self._monitor.device_info_updated.connect(self._dashboard.update_device_info)
        self._monitor.battery_updated.connect(self._dashboard.update_battery)
        self._monitor.memory_updated.connect(self._dashboard.update_memory)
        self._monitor.storage_updated.connect(self._dashboard.update_storage)
        self._monitor.network_updated.connect(self._dashboard.update_network)
        self._monitor.display_info_updated.connect(self._dashboard.update_display)
        self._monitor.error_occurred.connect(self._on_monitor_error)
        self._monitor.start()

    def _on_monitor_error(self, message: str) -> None:
        self._show_status(f"Monitor: {message}")

    def _show_status(self, message: str) -> None:
        self._status_label.setText(message)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About ADBOSS",
            "<h2>ADBOSS</h2>"
            "<p>Android Debug Bridge Desktop Manager</p>"
            f"<p>Version {__version__}</p>"
            "<hr>"
            "<p>\u00a9 2026 Martin Pfeffer | celox.io</p>",
        )

    def closeEvent(self, event) -> None:
        """Clean up on exit."""
        config.set("window_width", self.width())
        config.set("window_height", self.height())

        # Stop timers first to prevent new work being scheduled
        self._refresh_timer.stop()
        self._device_selector.stop_polling()

        # Disconnect monitor signals before stopping to avoid emitting to destroyed widgets
        if self._monitor:
            try:
                self._monitor.device_info_updated.disconnect()
                self._monitor.battery_updated.disconnect()
                self._monitor.memory_updated.disconnect()
                self._monitor.storage_updated.disconnect()
                self._monitor.network_updated.disconnect()
                self._monitor.display_info_updated.disconnect()
                self._monitor.error_occurred.disconnect()
            except RuntimeError:
                pass
            self._monitor.stop()

        self._apps.cleanup()
        self._logcat.cleanup()
        self._adb.cleanup()

        event.accept()
