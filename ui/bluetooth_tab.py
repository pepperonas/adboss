"""Bluetooth tab — HCI snoop capture, device discovery, and packet analysis."""

import logging
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QGroupBox,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QPlainTextEdit,
    QComboBox,
    QLineEdit,
    QHeaderView,
    QFileDialog,
    QAbstractItemView,
)

from core.adb_client import ADBClient
from core.bluetooth_parser import (
    HCIPacket,
    HCIPacketType,
    HCIDirection,
    CaptureStats,
    parse_btsnoop,
    compute_stats,
    export_pcap,
    export_btsnoop,
    format_hex_dump,
)

logger = logging.getLogger(__name__)

# Colors for packet types
PKT_TYPE_COLORS = {
    "CMD": QColor("#2196F3"),   # Blue
    "EVT": QColor("#4CAF50"),   # Green
    "ACL": QColor("#FFC107"),   # Amber
    "SCO": QColor("#9C27B0"),   # Purple
}

PROTOCOL_COLORS = {
    "HCI": QColor("#d4d4d4"),
    "L2CAP": QColor("#26C6DA"),
    "ATT": QColor("#FF9800"),
    "SMP": QColor("#E040FB"),
    "GATT": QColor("#8BC34A"),
}


class BluetoothInfoWorker(QThread):
    """Fetch Bluetooth adapter info and paired devices."""

    info_ready = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, adb: ADBClient, parent=None) -> None:
        super().__init__(parent)
        self._adb = adb

    def run(self) -> None:
        try:
            info = self._adb.get_bluetooth_info()
            self.info_ready.emit(info)
        except Exception as e:
            self.error_occurred.emit(str(e))


class BtSnoopCaptureWorker(QThread):
    """Pull and parse btsnoop log from device."""

    capture_ready = Signal(list)  # list[HCIPacket]
    progress = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, adb: ADBClient, parent=None) -> None:
        super().__init__(parent)
        self._adb = adb
        self._running = False

    def run(self) -> None:
        self._running = True
        self.progress.emit("Pulling btsnoop_hci.log from device...")
        try:
            data = self._adb.get_bt_snoop_log_data()
            if not data:
                self.error_occurred.emit(
                    "No btsnoop log found. Enable HCI snoop logging in "
                    "Developer Options or use the Enable button, then "
                    "toggle Bluetooth off/on."
                )
                return
            self.progress.emit(f"Parsing {len(data)} bytes...")
            packets = parse_btsnoop(data)
            if not packets:
                self.error_occurred.emit(
                    "btsnoop log found but contained no valid packets."
                )
                return
            self.progress.emit(f"Decoded {len(packets)} packets")
            self.capture_ready.emit(packets)
        except Exception as e:
            if self._running:
                self.error_occurred.emit(f"Capture error: {e}")

    def stop(self) -> None:
        self._running = False
        self.quit()
        self.wait(3000)


class LiveCaptureWorker(QThread):
    """Periodically pull btsnoop log for live-ish monitoring."""

    new_packets = Signal(list)  # list[HCIPacket]
    progress = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, adb: ADBClient, interval_ms: int = 2000, parent=None) -> None:
        super().__init__(parent)
        self._adb = adb
        self._interval = interval_ms / 1000.0
        self._running = False
        self._last_count = 0

    def run(self) -> None:
        self._running = True
        self._last_count = 0
        while self._running:
            try:
                data = self._adb.get_bt_snoop_log_data()
                if data:
                    packets = parse_btsnoop(data)
                    if len(packets) > self._last_count:
                        new_pkts = packets[self._last_count:]
                        self._last_count = len(packets)
                        self.new_packets.emit(new_pkts)
                        self.progress.emit(
                            f"Live: {len(packets)} total packets "
                            f"(+{len(new_pkts)} new)"
                        )
            except Exception as e:
                if self._running:
                    self.error_occurred.emit(str(e))
            # Sleep in small increments so stop() is responsive
            end = time.monotonic() + self._interval
            while self._running and time.monotonic() < end:
                time.sleep(0.1)

    def stop(self) -> None:
        self._running = False
        self.quit()
        self.wait(5000)


class BluetoothTab(QWidget):
    """Bluetooth HCI snoop capture and analysis tab."""

    status_message = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._adb: ADBClient | None = None
        self._packets: list[HCIPacket] = []
        self._filtered_packets: list[HCIPacket] = []
        self._info_worker: BluetoothInfoWorker | None = None
        self._capture_worker: BtSnoopCaptureWorker | None = None
        self._live_worker: LiveCaptureWorker | None = None
        self._is_live = False
        self._build_ui()

    def set_adb(self, adb: ADBClient) -> None:
        self._adb = adb

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        # --- Toolbar ---
        toolbar = QHBoxLayout()

        self._scan_btn = QPushButton("Scan Devices")
        self._scan_btn.clicked.connect(self._scan_devices)
        toolbar.addWidget(self._scan_btn)

        self._enable_snoop_btn = QPushButton("Enable HCI Log")
        self._enable_snoop_btn.clicked.connect(self._enable_snoop)
        toolbar.addWidget(self._enable_snoop_btn)

        self._capture_btn = QPushButton("Pull Capture")
        self._capture_btn.clicked.connect(self._pull_capture)
        toolbar.addWidget(self._capture_btn)

        self._live_btn = QPushButton("Live Capture")
        self._live_btn.setCheckable(True)
        self._live_btn.clicked.connect(self._toggle_live_capture)
        toolbar.addWidget(self._live_btn)

        self._load_btn = QPushButton("Load File...")
        self._load_btn.clicked.connect(self._load_file)
        toolbar.addWidget(self._load_btn)

        self._export_btn = QPushButton("Export...")
        self._export_btn.clicked.connect(self._export)
        toolbar.addWidget(self._export_btn)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self._clear)
        toolbar.addWidget(self._clear_btn)

        toolbar.addStretch()

        self._snoop_status = QLabel("HCI Log: ?")
        self._snoop_status.setObjectName("infoValue")
        toolbar.addWidget(self._snoop_status)

        layout.addLayout(toolbar)

        # --- Filter bar ---
        filter_row = QHBoxLayout()

        filter_row.addWidget(QLabel("Type:"))
        self._type_filter = QComboBox()
        self._type_filter.addItems(["All", "CMD", "EVT", "ACL", "SCO"])
        self._type_filter.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self._type_filter)

        filter_row.addWidget(QLabel("Protocol:"))
        self._proto_filter = QComboBox()
        self._proto_filter.addItems(["All", "HCI", "L2CAP", "ATT", "SMP"])
        self._proto_filter.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self._proto_filter)

        filter_row.addWidget(QLabel("Direction:"))
        self._dir_filter = QComboBox()
        self._dir_filter.addItems(["All", "Sent", "Received"])
        self._dir_filter.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self._dir_filter)

        filter_row.addWidget(QLabel("Search:"))
        self._search_filter = QLineEdit()
        self._search_filter.setPlaceholderText("Filter packets...")
        self._search_filter.setMaximumWidth(200)
        self._search_filter.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self._search_filter)

        filter_row.addStretch()

        self._pkt_count_label = QLabel("0 packets")
        filter_row.addWidget(self._pkt_count_label)

        layout.addLayout(filter_row)

        # --- Main content (splitter) ---
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel: Devices + Stats
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        # Adapter info
        adapter_group = QGroupBox("Adapter")
        adapter_layout = QVBoxLayout(adapter_group)
        self._adapter_name = QLabel("Name: -")
        self._adapter_name.setObjectName("infoValue")
        self._adapter_addr = QLabel("Address: -")
        self._adapter_addr.setObjectName("infoValue")
        self._adapter_state = QLabel("State: -")
        self._adapter_state.setObjectName("infoValue")
        adapter_layout.addWidget(self._adapter_name)
        adapter_layout.addWidget(self._adapter_addr)
        adapter_layout.addWidget(self._adapter_state)
        left_layout.addWidget(adapter_group)

        # Paired devices
        devices_group = QGroupBox("Paired Devices")
        devices_layout = QVBoxLayout(devices_group)
        self._devices_tree = QTreeWidget()
        self._devices_tree.setHeaderLabels(["Device", "Address"])
        self._devices_tree.setAlternatingRowColors(True)
        self._devices_tree.setRootIsDecorated(False)
        self._devices_tree.header().setStretchLastSection(True)
        devices_layout.addWidget(self._devices_tree)
        left_layout.addWidget(devices_group)

        # Statistics
        stats_group = QGroupBox("Capture Statistics")
        stats_layout = QVBoxLayout(stats_group)
        self._stats_label = QLabel(
            "Packets: 0\n"
            "CMD: 0  EVT: 0\n"
            "ACL: 0  SCO: 0\n"
            "Sent: 0  Recv: 0\n"
            "Duration: 00:00:00\n"
            "Bytes: 0"
        )
        self._stats_label.setObjectName("infoValue")
        self._stats_label.setFont(QFont("JetBrains Mono", 11))
        stats_layout.addWidget(self._stats_label)

        # Protocol breakdown
        self._proto_label = QLabel("")
        self._proto_label.setObjectName("infoValue")
        stats_layout.addWidget(self._proto_label)

        # Devices seen
        self._seen_label = QLabel("")
        self._seen_label.setObjectName("infoValue")
        stats_layout.addWidget(self._seen_label)

        left_layout.addWidget(stats_group)
        left_layout.addStretch()

        main_splitter.addWidget(left_panel)

        # Right panel: Packet table + Detail
        right_splitter = QSplitter(Qt.Orientation.Vertical)

        # Packet table
        self._packet_table = QTableWidget()
        self._packet_table.setColumnCount(7)
        self._packet_table.setHorizontalHeaderLabels([
            "#", "Time", "Type", "Dir", "Protocol", "Summary", "Size",
        ])
        self._packet_table.setAlternatingRowColors(True)
        self._packet_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._packet_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._packet_table.verticalHeader().setVisible(False)
        self._packet_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )

        # Column widths
        hdr = self._packet_table.horizontalHeader()
        hdr.resizeSection(0, 55)   # #
        hdr.resizeSection(1, 90)   # Time
        hdr.resizeSection(2, 45)   # Type
        hdr.resizeSection(3, 35)   # Dir
        hdr.resizeSection(4, 60)   # Protocol
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        hdr.resizeSection(6, 50)   # Size

        self._packet_table.currentCellChanged.connect(self._on_packet_selected)
        right_splitter.addWidget(self._packet_table)

        # Detail panel (tabbed: detail + hex)
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(2)

        detail_header = QHBoxLayout()
        self._detail_title = QLabel("Packet Detail")
        self._detail_title.setObjectName("infoKey")
        detail_header.addWidget(self._detail_title)
        detail_header.addStretch()

        self._hex_toggle = QPushButton("Hex Dump")
        self._hex_toggle.setCheckable(True)
        self._hex_toggle.setMaximumWidth(100)
        self._hex_toggle.toggled.connect(self._toggle_hex_view)
        detail_header.addWidget(self._hex_toggle)
        detail_layout.addLayout(detail_header)

        self._detail_text = QPlainTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setFont(QFont("JetBrains Mono", 11))
        # Fallback fonts
        font = self._detail_text.font()
        if not font.exactMatch():
            for fallback in ("Fira Code", "Source Code Pro", "Menlo", "Consolas", "monospace"):
                font.setFamily(fallback)
                self._detail_text.setFont(font)
                if self._detail_text.font().exactMatch():
                    break
        self._detail_text.setObjectName("logcatOutput")
        self._detail_text.setMaximumBlockCount(0)
        detail_layout.addWidget(self._detail_text)

        right_splitter.addWidget(detail_widget)
        right_splitter.setSizes([400, 200])

        main_splitter.addWidget(right_splitter)
        main_splitter.setSizes([250, 650])

        layout.addWidget(main_splitter)

    # --- Device scan ---

    def _scan_devices(self) -> None:
        if not self._adb:
            self.status_message.emit("No device connected")
            return
        if self._info_worker and self._info_worker.isRunning():
            return
        self._info_worker = BluetoothInfoWorker(self._adb, self)
        self._info_worker.info_ready.connect(self._on_bt_info)
        self._info_worker.error_occurred.connect(
            lambda e: self.status_message.emit(f"BT scan error: {e}")
        )
        self._info_worker.finished.connect(
            lambda: setattr(self, "_info_worker", None)
        )
        self._info_worker.start()
        self.status_message.emit("Scanning Bluetooth devices...")

        # Also check snoop status
        self._check_snoop_status()

    def _check_snoop_status(self) -> None:
        if not self._adb:
            return
        try:
            enabled = self._adb.is_bt_snoop_enabled()
            self._snoop_status.setText(
                f"HCI Log: {'Enabled' if enabled else 'Disabled'}"
            )
            self._snoop_status.setStyleSheet(
                f"color: {'#4CAF50' if enabled else '#F44336'};"
            )
        except Exception:
            pass

    def _on_bt_info(self, info: dict) -> None:
        # Adapter info
        name = info.get("name", "-")
        addr = info.get("address", "-")
        enabled = info.get("enabled", False)
        self._adapter_name.setText(f"Name: {name}")
        self._adapter_addr.setText(f"Address: {addr}")
        state_text = "Enabled" if enabled else "Disabled"
        self._adapter_state.setText(f"State: {state_text}")
        self._adapter_state.setStyleSheet(
            f"color: {'#4CAF50' if enabled else '#F44336'};"
        )

        # Paired devices
        self._devices_tree.clear()
        paired = info.get("paired_devices", [])
        connected = set(info.get("connected_devices", []))

        for dev in paired:
            addr = dev.get("address", "")
            name = dev.get("name", "Unknown")
            item = QTreeWidgetItem([name, addr])
            if addr in connected:
                item.setForeground(0, QColor("#4CAF50"))
                item.setForeground(1, QColor("#4CAF50"))
                item.setText(0, f"{name} (connected)")
            self._devices_tree.addTopLevelItem(item)

        count = len(paired)
        conn_count = len(connected)
        self.status_message.emit(
            f"Found {count} paired device(s), {conn_count} connected"
        )

    # --- HCI snoop control ---

    def _enable_snoop(self) -> None:
        if not self._adb:
            return
        self.status_message.emit("Enabling HCI snoop logging...")
        success = self._adb.enable_bt_snoop()
        if success:
            self.status_message.emit(
                "HCI snoop logging enabled. Toggle Bluetooth off/on "
                "to start capturing."
            )
        else:
            self.status_message.emit(
                "Could not confirm HCI snoop enabled. May need root "
                "or Developer Options on some devices."
            )
        self._check_snoop_status()

    # --- Capture ---

    def _pull_capture(self) -> None:
        if not self._adb:
            self.status_message.emit("No device connected")
            return
        if self._capture_worker and self._capture_worker.isRunning():
            return
        self._capture_worker = BtSnoopCaptureWorker(self._adb, self)
        self._capture_worker.capture_ready.connect(self._on_capture_ready)
        self._capture_worker.progress.connect(
            lambda msg: self.status_message.emit(msg)
        )
        self._capture_worker.error_occurred.connect(
            lambda e: self.status_message.emit(e)
        )
        self._capture_worker.finished.connect(
            lambda: setattr(self, "_capture_worker", None)
        )
        self._capture_worker.start()

    def _on_capture_ready(self, packets: list[HCIPacket]) -> None:
        self._packets = packets
        self._apply_filters()
        stats = compute_stats(packets)
        self._update_stats(stats)
        self.status_message.emit(f"Captured {len(packets)} HCI packets")

    # --- Live capture ---

    def _toggle_live_capture(self, checked: bool) -> None:
        if checked:
            self._start_live_capture()
        else:
            self._stop_live_capture()

    def _start_live_capture(self) -> None:
        if not self._adb:
            self._live_btn.setChecked(False)
            self.status_message.emit("No device connected")
            return
        self._is_live = True
        self._live_worker = LiveCaptureWorker(self._adb, interval_ms=2000, parent=self)
        self._live_worker.new_packets.connect(self._on_live_packets)
        self._live_worker.progress.connect(
            lambda msg: self.status_message.emit(msg)
        )
        self._live_worker.error_occurred.connect(
            lambda e: self.status_message.emit(f"Live capture error: {e}")
        )
        self._live_worker.start()
        self._live_btn.setText("Stop Live")
        self.status_message.emit("Live capture started (polling every 2s)")

    def _stop_live_capture(self) -> None:
        self._is_live = False
        if self._live_worker:
            self._live_worker.stop()
            self._live_worker = None
        self._live_btn.setText("Live Capture")
        self._live_btn.setChecked(False)
        self.status_message.emit("Live capture stopped")

    def _on_live_packets(self, new_packets: list[HCIPacket]) -> None:
        # Re-index new packets
        start_idx = len(self._packets)
        for i, pkt in enumerate(new_packets):
            pkt.index = start_idx + i
        self._packets.extend(new_packets)
        self._apply_filters()
        stats = compute_stats(self._packets)
        self._update_stats(stats)

    # --- Load file ---

    def _load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load btsnoop Log",
            str(Path.home()),
            "btsnoop Files (*.log *.btsnoop);;All Files (*)"
        )
        if not path:
            return
        try:
            data = Path(path).read_bytes()
            packets = parse_btsnoop(data)
            if not packets:
                self.status_message.emit("No valid HCI packets found in file")
                return
            self._packets = packets
            self._apply_filters()
            stats = compute_stats(packets)
            self._update_stats(stats)
            self.status_message.emit(
                f"Loaded {len(packets)} packets from {Path(path).name}"
            )
        except Exception as e:
            self.status_message.emit(f"Error loading file: {e}")

    # --- Export ---

    def _export(self) -> None:
        if not self._packets:
            self.status_message.emit("No packets to export")
            return

        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Export Capture",
            str(Path.home() / "bt_capture"),
            "pcap (*.pcap);;btsnoop (*.btsnoop);;Text (*.txt)"
        )
        if not path:
            return

        try:
            pkts = self._filtered_packets or self._packets
            if "pcap" in selected_filter.lower() or path.endswith(".pcap"):
                export_pcap(pkts, path)
            elif "btsnoop" in selected_filter.lower() or path.endswith(".btsnoop"):
                export_btsnoop(pkts, path)
            else:
                # Text export
                lines = []
                for pkt in pkts:
                    lines.append(
                        f"[{pkt.index:5d}] {pkt.relative_time:10.6f}s "
                        f"{pkt.direction_str} {pkt.type_name:3s} "
                        f"{pkt.protocol:5s} {pkt.summary}"
                    )
                    for dl in pkt.detail_lines:
                        lines.append(f"        {dl}")
                    lines.append(f"        {pkt.hex_dump}")
                    lines.append("")
                Path(path).write_text("\n".join(lines), encoding="utf-8")

            self.status_message.emit(
                f"Exported {len(pkts)} packets to {Path(path).name}"
            )
        except Exception as e:
            self.status_message.emit(f"Export error: {e}")

    # --- Clear ---

    def _clear(self) -> None:
        self._packets.clear()
        self._filtered_packets.clear()
        self._packet_table.setRowCount(0)
        self._detail_text.clear()
        self._pkt_count_label.setText("0 packets")
        self._stats_label.setText(
            "Packets: 0\nCMD: 0  EVT: 0\nACL: 0  SCO: 0\n"
            "Sent: 0  Recv: 0\nDuration: 00:00:00\nBytes: 0"
        )
        self._proto_label.setText("")
        self._seen_label.setText("")
        self.status_message.emit("Capture cleared")

    # --- Filtering ---

    def _apply_filters(self) -> None:
        type_filter = self._type_filter.currentText()
        proto_filter = self._proto_filter.currentText()
        dir_filter = self._dir_filter.currentText()
        search = self._search_filter.text().strip().lower()

        filtered = []
        for pkt in self._packets:
            if type_filter != "All" and pkt.type_name != type_filter:
                continue
            if proto_filter != "All" and pkt.protocol != proto_filter:
                continue
            if dir_filter == "Sent" and pkt.direction != HCIDirection.SENT:
                continue
            if dir_filter == "Received" and pkt.direction != HCIDirection.RECEIVED:
                continue
            if search and search not in pkt.summary.lower():
                continue
            filtered.append(pkt)

        self._filtered_packets = filtered
        self._populate_table(filtered)
        self._pkt_count_label.setText(
            f"{len(filtered)}/{len(self._packets)} packets"
        )

    def _populate_table(self, packets: list[HCIPacket]) -> None:
        self._packet_table.setUpdatesEnabled(False)
        self._packet_table.setRowCount(len(packets))

        for row, pkt in enumerate(packets):
            # #
            idx_item = QTableWidgetItem(str(pkt.index))
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._packet_table.setItem(row, 0, idx_item)

            # Time
            time_str = f"{pkt.relative_time:.6f}"
            time_item = QTableWidgetItem(time_str)
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._packet_table.setItem(row, 1, time_item)

            # Type
            type_item = QTableWidgetItem(pkt.type_name)
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            color = PKT_TYPE_COLORS.get(pkt.type_name, QColor("#d4d4d4"))
            type_item.setForeground(color)
            self._packet_table.setItem(row, 2, type_item)

            # Direction
            dir_item = QTableWidgetItem(pkt.direction_str)
            dir_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._packet_table.setItem(row, 3, dir_item)

            # Protocol
            proto_item = QTableWidgetItem(pkt.protocol)
            proto_color = PROTOCOL_COLORS.get(pkt.protocol, QColor("#d4d4d4"))
            proto_item.setForeground(proto_color)
            self._packet_table.setItem(row, 4, proto_item)

            # Summary
            summary_item = QTableWidgetItem(pkt.summary)
            summary_item.setForeground(color)
            self._packet_table.setItem(row, 5, summary_item)

            # Size
            size_item = QTableWidgetItem(str(len(pkt.raw_data)))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._packet_table.setItem(row, 6, size_item)

        self._packet_table.setUpdatesEnabled(True)

    # --- Packet detail ---

    def _on_packet_selected(self, row: int, _col: int, _prev_row: int, _prev_col: int) -> None:
        if row < 0 or row >= len(self._filtered_packets):
            return
        pkt = self._filtered_packets[row]
        self._show_packet_detail(pkt)

    def _show_packet_detail(self, pkt: HCIPacket) -> None:
        if self._hex_toggle.isChecked():
            self._show_hex_view(pkt)
        else:
            self._show_detail_view(pkt)

    def _show_detail_view(self, pkt: HCIPacket) -> None:
        lines = []
        lines.append(f"Packet #{pkt.index}")
        if pkt.timestamp:
            lines.append(f"Timestamp: {pkt.timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')}")
        lines.append(f"Relative Time: {pkt.relative_time:.6f}s")
        lines.append(f"Direction: {pkt.direction_label} ({pkt.direction_str})")
        lines.append(f"Type: {pkt.type_name}")
        lines.append(f"Protocol: {pkt.protocol}")
        lines.append(f"Size: {len(pkt.raw_data)} bytes")
        lines.append("")

        for dl in pkt.detail_lines:
            lines.append(dl)

        lines.append("")
        lines.append("--- Raw Data ---")
        lines.append(pkt.hex_dump)

        self._detail_text.setPlainText("\n".join(lines))
        self._detail_title.setText(
            f"Packet #{pkt.index}: {pkt.summary}"
        )

    def _show_hex_view(self, pkt: HCIPacket) -> None:
        lines = [
            f"Packet #{pkt.index} - {pkt.summary}",
            f"Size: {len(pkt.raw_data)} bytes",
            "",
            pkt.hex_dump,
        ]
        self._detail_text.setPlainText("\n".join(lines))

    def _toggle_hex_view(self, checked: bool) -> None:
        row = self._packet_table.currentRow()
        if row >= 0 and row < len(self._filtered_packets):
            pkt = self._filtered_packets[row]
            if checked:
                self._show_hex_view(pkt)
            else:
                self._show_detail_view(pkt)

    # --- Statistics ---

    def _update_stats(self, stats: CaptureStats) -> None:
        self._stats_label.setText(
            f"Packets: {stats.total_packets}\n"
            f"CMD: {stats.commands}  EVT: {stats.events}\n"
            f"ACL: {stats.acl_packets}  SCO: {stats.sco_packets}\n"
            f"Sent: {stats.sent}  Recv: {stats.received}\n"
            f"Duration: {stats.duration_str}\n"
            f"Bytes: {stats.total_bytes:,}"
        )

        # Protocol breakdown
        if stats.protocols:
            proto_lines = [f"{k}: {v}" for k, v in sorted(stats.protocols.items())]
            self._proto_label.setText("Protocols:\n" + "\n".join(proto_lines))
        else:
            self._proto_label.setText("")

        # Devices seen
        if stats.devices_seen:
            self._seen_label.setText(
                f"Devices seen ({len(stats.devices_seen)}):\n"
                + "\n".join(sorted(stats.devices_seen))
            )
        else:
            self._seen_label.setText("")

    # --- Refresh (for Ctrl+R) ---

    def refresh(self) -> None:
        self._scan_devices()

    # --- Cleanup ---

    def cleanup(self) -> None:
        if self._live_worker:
            self._live_worker.stop()
            self._live_worker = None
        if self._capture_worker:
            self._capture_worker.stop()
            self._capture_worker = None
