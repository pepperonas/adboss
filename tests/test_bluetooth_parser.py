"""Tests for Bluetooth HCI snoop parser and helpers."""

import struct

import pytest

from core.bluetooth_parser import (
    BTSNOOP_MAGIC,
    HCIPacket,
    HCIPacketType,
    HCIDirection,
    CaptureStats,
    parse_btsnoop,
    compute_stats,
    decode_hci_command,
    decode_hci_event,
    decode_acl_data,
    format_hex_dump,
    format_bd_addr,
    lookup_uuid16,
    export_pcap,
    export_btsnoop,
    _BTSNOOP_EPOCH_DELTA,
)
from utils.helpers import parse_bluetooth_manager
from tests.conftest import BLUETOOTH_MANAGER_OUTPUT


# --- Helper to build btsnoop files ---

def _build_btsnoop(packets: list[tuple[int, int, int, bytes]]) -> bytes:
    """Build a minimal btsnoop file.

    packets: list of (flags, timestamp_us, pkt_type, hci_data)
    """
    buf = bytearray()
    # Header: magic + version(1) + datalink_type(1002 = H4)
    buf.extend(BTSNOOP_MAGIC)
    buf.extend(struct.pack(">II", 1, 1002))

    for flags, ts_us, pkt_type, hci_data in packets:
        # H4: type byte + data
        record = struct.pack("B", pkt_type) + hci_data
        orig_len = len(record)
        incl_len = len(record)
        abs_ts = ts_us + _BTSNOOP_EPOCH_DELTA

        buf.extend(struct.pack(">IIIIQ",
                               orig_len, incl_len, flags, 0, abs_ts))
        buf.extend(record)

    return bytes(buf)


# --- format_hex_dump ---

class TestFormatHexDump:
    def test_empty(self):
        assert format_hex_dump(b"") == ""

    def test_short(self):
        result = format_hex_dump(b"\x01\x02\x03")
        assert "01 02 03" in result
        assert "0000" in result

    def test_multiline(self):
        data = bytes(range(32))
        result = format_hex_dump(data)
        lines = result.strip().split("\n")
        assert len(lines) == 2
        assert lines[0].startswith("0000")
        assert lines[1].startswith("0010")


# --- format_bd_addr ---

class TestFormatBdAddr:
    def test_normal(self):
        # BD_ADDR is stored in reverse byte order
        data = b"\x66\x55\x44\x33\x22\x11"
        assert format_bd_addr(data) == "11:22:33:44:55:66"

    def test_short(self):
        assert "??" in format_bd_addr(b"\x01\x02")


# --- lookup_uuid16 ---

class TestLookupUuid16:
    def test_known_service(self):
        assert lookup_uuid16(0x180F) == "Battery Service"

    def test_known_characteristic(self):
        assert lookup_uuid16(0x2A19) == "Battery Level"

    def test_unknown(self):
        assert lookup_uuid16(0xFFFF) == "0xFFFF"


# --- parse_btsnoop ---

class TestParseBtsnoop:
    def test_empty(self):
        assert parse_btsnoop(b"") == []

    def test_bad_magic(self):
        assert parse_btsnoop(b"not_btsnoop_data") == []

    def test_header_only(self):
        data = BTSNOOP_MAGIC + struct.pack(">II", 1, 1002)
        assert parse_btsnoop(data) == []

    def test_single_hci_command(self):
        # HCI Reset command: opcode 0x0C03, param_len 0
        hci_cmd = struct.pack("<HB", 0x0C03, 0)
        flags = 0x02  # sent + command
        btsnoop_data = _build_btsnoop([(flags, 1000000, 0x01, hci_cmd)])

        packets = parse_btsnoop(btsnoop_data)
        assert len(packets) == 1
        pkt = packets[0]
        assert pkt.packet_type == HCIPacketType.COMMAND
        assert pkt.type_name == "CMD"
        assert "Reset" in pkt.summary
        assert pkt.direction == HCIDirection.SENT

    def test_single_hci_event(self):
        # Command Complete event for Reset
        # event_code=0x0E, param_len=4, num_pkts=1, opcode=0x0C03, status=0
        params = struct.pack("<BHB", 1, 0x0C03, 0)
        hci_evt = struct.pack("BB", 0x0E, len(params)) + params
        flags = 0x03  # received + event
        btsnoop_data = _build_btsnoop([(flags, 2000000, 0x04, hci_evt)])

        packets = parse_btsnoop(btsnoop_data)
        assert len(packets) == 1
        pkt = packets[0]
        assert pkt.packet_type == HCIPacketType.EVENT
        assert pkt.type_name == "EVT"
        assert "Command Complete" in pkt.summary
        assert "Reset" in pkt.summary

    def test_multiple_packets(self):
        # Two commands
        cmd1 = struct.pack("<HB", 0x0C03, 0)  # Reset
        cmd2 = struct.pack("<HB", 0x0401, 0)  # Inquiry (simplified)
        btsnoop_data = _build_btsnoop([
            (0x02, 1000000, 0x01, cmd1),
            (0x02, 2000000, 0x01, cmd2),
        ])

        packets = parse_btsnoop(btsnoop_data)
        assert len(packets) == 2
        assert "Reset" in packets[0].summary
        assert "Inquiry" in packets[1].summary

    def test_relative_timestamps(self):
        cmd = struct.pack("<HB", 0x0C03, 0)
        btsnoop_data = _build_btsnoop([
            (0x02, 1000000, 0x01, cmd),
            (0x02, 2500000, 0x01, cmd),
        ])
        packets = parse_btsnoop(btsnoop_data)
        assert packets[0].timestamp_us == 0
        assert packets[1].timestamp_us == 1500000

    def test_le_scan_enable_command(self):
        # LE Set Scan Enable: opcode 0x200C, enable=1, filter_dup=1
        params = struct.pack("BB", 1, 1)
        hci_cmd = struct.pack("<HB", 0x200C, len(params)) + params
        btsnoop_data = _build_btsnoop([(0x02, 1000000, 0x01, hci_cmd)])

        packets = parse_btsnoop(btsnoop_data)
        assert len(packets) == 1
        assert "LE Set Scan Enable" in packets[0].summary

    def test_disconnect_event(self):
        # Disconnection Complete: status=0, handle=0x0040, reason=0x13
        params = struct.pack("<BHB", 0, 0x0040, 0x13)
        hci_evt = struct.pack("BB", 0x05, len(params)) + params
        btsnoop_data = _build_btsnoop([(0x03, 1000000, 0x04, hci_evt)])

        packets = parse_btsnoop(btsnoop_data)
        assert len(packets) == 1
        assert "Disconnection" in packets[0].summary
        assert "Remote User Terminated" in str(packets[0].detail_lines)

    def test_acl_att_packet(self):
        # ACL header: handle=0x0040 (PB=2, BC=0), length=7
        # L2CAP: length=3, CID=0x0004 (ATT)
        # ATT: Exchange MTU Request, MTU=512
        att_payload = struct.pack("<BH", 0x02, 512)  # opcode + MTU
        l2cap = struct.pack("<HH", len(att_payload), 0x0004) + att_payload
        acl = struct.pack("<HH", 0x2040, len(l2cap)) + l2cap
        btsnoop_data = _build_btsnoop([(0x00, 1000000, 0x02, acl)])

        packets = parse_btsnoop(btsnoop_data)
        assert len(packets) == 1
        pkt = packets[0]
        assert pkt.type_name == "ACL"
        assert pkt.protocol == "ATT"
        assert "Exchange MTU" in pkt.summary
        assert "512" in pkt.summary


# --- compute_stats ---

class TestComputeStats:
    def test_empty(self):
        stats = compute_stats([])
        assert stats.total_packets == 0
        assert stats.duration_str == "00:00:00"

    def test_with_packets(self):
        cmd = struct.pack("<HB", 0x0C03, 0)
        evt_params = struct.pack("<BHB", 1, 0x0C03, 0)
        hci_evt = struct.pack("BB", 0x0E, len(evt_params)) + evt_params

        btsnoop_data = _build_btsnoop([
            (0x02, 1000000, 0x01, cmd),
            (0x03, 2000000, 0x04, hci_evt),
        ])
        packets = parse_btsnoop(btsnoop_data)
        stats = compute_stats(packets)

        assert stats.total_packets == 2
        assert stats.commands == 1
        assert stats.events == 1
        assert stats.sent == 1
        assert stats.received == 1
        assert stats.total_bytes > 0


# --- export ---

class TestExport:
    def test_pcap_export(self, tmp_path):
        cmd = struct.pack("<HB", 0x0C03, 0)
        btsnoop_data = _build_btsnoop([(0x02, 1000000, 0x01, cmd)])
        packets = parse_btsnoop(btsnoop_data)

        pcap_path = str(tmp_path / "test.pcap")
        export_pcap(packets, pcap_path)

        # Verify pcap magic
        with open(pcap_path, "rb") as f:
            magic = struct.unpack("<I", f.read(4))[0]
            assert magic == 0xA1B2C3D4

    def test_btsnoop_export(self, tmp_path):
        cmd = struct.pack("<HB", 0x0C03, 0)
        btsnoop_data = _build_btsnoop([(0x02, 1000000, 0x01, cmd)])
        packets = parse_btsnoop(btsnoop_data)

        out_path = str(tmp_path / "test.btsnoop")
        export_btsnoop(packets, out_path)

        # Re-parse exported file
        with open(out_path, "rb") as f:
            data = f.read()
        re_parsed = parse_btsnoop(data)
        assert len(re_parsed) == 1
        assert "Reset" in re_parsed[0].summary


# --- parse_bluetooth_manager ---

class TestParseBluetoothManager:
    def test_full_output(self):
        info = parse_bluetooth_manager(BLUETOOTH_MANAGER_OUTPUT)
        assert info["enabled"] is True
        assert info["address"] == "AA:BB:CC:DD:EE:FF"
        assert info["name"] == "Pixel_6"
        assert len(info["paired_devices"]) == 3
        assert info["paired_devices"][0]["address"] == "11:22:33:44:55:66"
        assert info["paired_devices"][0]["name"] == "JBL Flip 5"
        assert "11:22:33:44:55:66" in info["connected_devices"]

    def test_empty_output(self):
        info = parse_bluetooth_manager("")
        assert info["enabled"] is False
        assert info["paired_devices"] == []
        assert info["connected_devices"] == []

    def test_profiles(self):
        info = parse_bluetooth_manager(BLUETOOTH_MANAGER_OUTPUT)
        assert "A2dpService" in info["profiles"]
        assert "HeadsetService" in info["profiles"]
