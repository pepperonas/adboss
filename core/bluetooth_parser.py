"""Bluetooth HCI snoop log parser and packet decoder.

Parses btsnoop_hci.log files (RFC 1761 variant used by Android)
and decodes HCI commands, events, ACL data, L2CAP, ATT/GATT, and SMP.
"""

import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum


# ── btsnoop constants ──────────────────────────────────────────────────────

BTSNOOP_MAGIC = b"btsnoop\x00"
BTSNOOP_HEADER_SIZE = 16
BTSNOOP_RECORD_HEADER_SIZE = 24

# Timestamp epoch: midnight Jan 1, 0000 AD → convert to Unix epoch
_BTSNOOP_EPOCH_DELTA = 0x00DCDDB30F2F8000  # microseconds between 0 AD and 1970


class HCIPacketType(IntEnum):
    COMMAND = 0x01
    ACL_DATA = 0x02
    SCO_DATA = 0x03
    EVENT = 0x04


class HCIDirection(IntEnum):
    SENT = 0  # Host → Controller
    RECEIVED = 1  # Controller → Host


# ── HCI Command OGF definitions ───────────────────────────────────────────

OGF_NAMES = {
    0x01: "Link Control",
    0x02: "Link Policy",
    0x03: "Controller & Baseband",
    0x04: "Informational",
    0x05: "Status",
    0x06: "Testing",
    0x08: "LE Controller",
    0x3F: "Vendor Specific",
}

# Common HCI command opcodes (OGF << 10 | OCF)
HCI_COMMAND_NAMES = {
    0x0401: "Inquiry",
    0x0402: "Inquiry Cancel",
    0x0403: "Periodic Inquiry Mode",
    0x0405: "Create Connection",
    0x0406: "Disconnect",
    0x0408: "Create Connection Cancel",
    0x0409: "Accept Connection Request",
    0x040A: "Reject Connection Request",
    0x040B: "Link Key Request Reply",
    0x040C: "Link Key Request Negative Reply",
    0x040D: "PIN Code Request Reply",
    0x0413: "Change Connection Packet Type",
    0x0415: "Authentication Requested",
    0x0417: "Set Connection Encryption",
    0x0419: "Change Connection Link Key",
    0x041A: "Central Link Key",
    0x041B: "Remote Name Request",
    0x041C: "Remote Name Request Cancel",
    0x041D: "Read Remote Supported Features",
    0x041F: "Read Remote Version Information",
    0x0C01: "Set Event Mask",
    0x0C03: "Reset",
    0x0C05: "Set Event Filter",
    0x0C0D: "Read Stored Link Key",
    0x0C11: "Write Stored Link Key",
    0x0C12: "Delete Stored Link Key",
    0x0C13: "Write Local Name",
    0x0C14: "Read Local Name",
    0x0C19: "Read Scan Enable",
    0x0C1A: "Write Scan Enable",
    0x0C1E: "Write Page Scan Activity",
    0x0C23: "Read Class of Device",
    0x0C24: "Write Class of Device",
    0x0C25: "Read Voice Setting",
    0x0C26: "Write Voice Setting",
    0x0C33: "Host Buffer Size",
    0x0C35: "Read Current IAC LAP",
    0x0C38: "Write Inquiry Scan Type",
    0x0C3A: "Write Inquiry Mode",
    0x0C3F: "Write Extended Inquiry Response",
    0x0C45: "Read Inquiry Response TX Power",
    0x0C52: "Write Simple Pairing Mode",
    0x0C56: "Write LE Host Supported",
    0x0C63: "Set Event Mask Page 2",
    0x0C6C: "Read LE Host Supported",
    0x0C6D: "Write Secure Connections Host Support",
    0x1001: "Read Local Version Information",
    0x1002: "Read Local Supported Commands",
    0x1003: "Read Local Supported Features",
    0x1004: "Read Local Extended Features",
    0x1005: "Read Buffer Size",
    0x1009: "Read BD_ADDR",
    0x1405: "Read RSSI",
    0x2001: "LE Set Event Mask",
    0x2002: "LE Read Buffer Size",
    0x2003: "LE Read Local Supported Features",
    0x2005: "LE Set Random Address",
    0x2006: "LE Set Advertising Parameters",
    0x2007: "LE Read Advertising Channel TX Power",
    0x2008: "LE Set Advertising Data",
    0x2009: "LE Set Scan Response Data",
    0x200A: "LE Set Advertising Enable",
    0x200B: "LE Set Scan Parameters",
    0x200C: "LE Set Scan Enable",
    0x200D: "LE Create Connection",
    0x200E: "LE Create Connection Cancel",
    0x200F: "LE Read Filter Accept List Size",
    0x2010: "LE Clear Filter Accept List",
    0x2011: "LE Add Device To Filter Accept List",
    0x2013: "LE Connection Update",
    0x2016: "LE Read Remote Features",
    0x2017: "LE Encrypt",
    0x2018: "LE Rand",
    0x2019: "LE Enable Encryption",
    0x201A: "LE Long Term Key Request Reply",
    0x2025: "LE Read Resolving List Size",
    0x202B: "LE Read Maximum Data Length",
    0x2036: "LE Set Extended Advertising Parameters",
    0x2039: "LE Set Extended Advertising Enable",
    0x2041: "LE Set Extended Scan Parameters",
    0x2042: "LE Set Extended Scan Enable",
    0x2043: "LE Extended Create Connection",
}

# ── HCI Event codes ───────────────────────────────────────────────────────

HCI_EVENT_NAMES = {
    0x01: "Inquiry Complete",
    0x02: "Inquiry Result",
    0x03: "Connection Complete",
    0x04: "Connection Request",
    0x05: "Disconnection Complete",
    0x06: "Authentication Complete",
    0x07: "Remote Name Request Complete",
    0x08: "Encryption Change",
    0x09: "Change Connection Link Key Complete",
    0x0B: "Read Remote Supported Features Complete",
    0x0C: "Read Remote Version Information Complete",
    0x0E: "Command Complete",
    0x0F: "Command Status",
    0x10: "Hardware Error",
    0x12: "Role Change",
    0x13: "Number Of Completed Packets",
    0x17: "Link Key Notification",
    0x1B: "Max Slots Change",
    0x1D: "Read Clock Offset Complete",
    0x1E: "Connection Packet Type Changed",
    0x20: "Page Scan Repetition Mode Change",
    0x22: "Inquiry Result with RSSI",
    0x23: "Read Remote Extended Features Complete",
    0x2F: "Extended Inquiry Result",
    0x30: "Encryption Key Refresh Complete",
    0x31: "IO Capability Request",
    0x32: "IO Capability Response",
    0x33: "User Confirmation Request",
    0x34: "User Passkey Request",
    0x36: "Simple Pairing Complete",
    0x38: "User Passkey Notification",
    0x3B: "Enhanced Flush Complete",
    0x3E: "LE Meta Event",
    0xFF: "Vendor Specific",
}

# LE Sub-Event codes
LE_SUBEVENT_NAMES = {
    0x01: "LE Connection Complete",
    0x02: "LE Advertising Report",
    0x03: "LE Connection Update Complete",
    0x04: "LE Read Remote Features Complete",
    0x05: "LE Long Term Key Request",
    0x06: "LE Remote Connection Parameter Request",
    0x07: "LE Data Length Change",
    0x08: "LE Read Local P-256 Public Key Complete",
    0x09: "LE Generate DHKey Complete",
    0x0A: "LE Enhanced Connection Complete",
    0x0B: "LE Directed Advertising Report",
    0x0C: "LE PHY Update Complete",
    0x0D: "LE Extended Advertising Report",
    0x12: "LE Channel Selection Algorithm",
}

# ── ATT opcodes ────────────────────────────────────────────────────────────

ATT_OPCODE_NAMES = {
    0x01: "Error Response",
    0x02: "Exchange MTU Request",
    0x03: "Exchange MTU Response",
    0x04: "Find Information Request",
    0x05: "Find Information Response",
    0x06: "Find By Type Value Request",
    0x07: "Find By Type Value Response",
    0x08: "Read By Type Request",
    0x09: "Read By Type Response",
    0x0A: "Read Request",
    0x0B: "Read Response",
    0x0C: "Read Blob Request",
    0x0D: "Read Blob Response",
    0x0E: "Read Multiple Request",
    0x0F: "Read Multiple Response",
    0x10: "Read By Group Type Request",
    0x11: "Read By Group Type Response",
    0x12: "Write Request",
    0x13: "Write Response",
    0x16: "Prepare Write Request",
    0x17: "Prepare Write Response",
    0x18: "Execute Write Request",
    0x19: "Execute Write Response",
    0x1B: "Handle Value Notification",
    0x1D: "Handle Value Indication",
    0x1E: "Handle Value Confirmation",
    0x52: "Write Command",
    0xD2: "Signed Write Command",
}

# ── SMP opcodes ────────────────────────────────────────────────────────────

SMP_OPCODE_NAMES = {
    0x01: "Pairing Request",
    0x02: "Pairing Response",
    0x03: "Pairing Confirm",
    0x04: "Pairing Random",
    0x05: "Pairing Failed",
    0x06: "Encryption Information",
    0x07: "Central Identification",
    0x08: "Identity Information",
    0x09: "Identity Address Information",
    0x0A: "Signing Information",
    0x0B: "Security Request",
    0x0C: "Pairing Public Key",
    0x0D: "Pairing DHKey Check",
}

# ── Common GATT UUIDs ─────────────────────────────────────────────────────

GATT_SERVICE_UUIDS = {
    0x1800: "Generic Access",
    0x1801: "Generic Attribute",
    0x1802: "Immediate Alert",
    0x1803: "Link Loss",
    0x1804: "Tx Power",
    0x1805: "Current Time",
    0x180A: "Device Information",
    0x180D: "Heart Rate",
    0x180F: "Battery Service",
    0x1810: "Blood Pressure",
    0x1812: "Human Interface Device",
    0x1816: "Cycling Speed and Cadence",
    0x1818: "Cycling Power",
    0x1819: "Location and Navigation",
    0x181C: "User Data",
    0x181D: "Weight Scale",
    0xFE95: "Xiaomi",
    0xFEA0: "Google",
    0xFEB9: "Apple Continuity",
    0xFD6F: "COVID-19 Exposure Notification",
}

GATT_CHARACTERISTIC_UUIDS = {
    0x2A00: "Device Name",
    0x2A01: "Appearance",
    0x2A02: "Peripheral Privacy Flag",
    0x2A04: "Peripheral Preferred Connection Parameters",
    0x2A05: "Service Changed",
    0x2A19: "Battery Level",
    0x2A24: "Model Number String",
    0x2A25: "Serial Number String",
    0x2A26: "Firmware Revision String",
    0x2A27: "Hardware Revision String",
    0x2A28: "Software Revision String",
    0x2A29: "Manufacturer Name String",
    0x2A37: "Heart Rate Measurement",
    0x2A38: "Body Sensor Location",
}

# ── Bluetooth Company IDs (top entries) ────────────────────────────────────

COMPANY_IDS = {
    0x0000: "Ericsson Technology Licensing",
    0x0001: "Nokia Mobile Phones",
    0x0002: "Intel Corp.",
    0x0003: "IBM Corp.",
    0x0004: "Toshiba Corp.",
    0x0006: "Microsoft",
    0x000A: "Qualcomm",
    0x000D: "Texas Instruments",
    0x000F: "Broadcom",
    0x0010: "Mitel Semiconductor",
    0x001D: "Qualcomm Technologies",
    0x004C: "Apple, Inc.",
    0x0059: "Nordic Semiconductor ASA",
    0x0075: "Samsung Electronics",
    0x0087: "Garmin International",
    0x00E0: "Google",
    0x010F: "Xiaomi",
    0x0157: "Huawei Technologies",
    0x02FF: "Bose Corporation",
    0x038F: "Tile, Inc.",
}

# ── Error codes ────────────────────────────────────────────────────────────

HCI_ERROR_CODES = {
    0x00: "Success",
    0x01: "Unknown HCI Command",
    0x02: "Unknown Connection Identifier",
    0x03: "Hardware Failure",
    0x04: "Page Timeout",
    0x05: "Authentication Failure",
    0x06: "PIN or Key Missing",
    0x07: "Memory Capacity Exceeded",
    0x08: "Connection Timeout",
    0x09: "Connection Limit Exceeded",
    0x0A: "Synchronous Connection Limit Exceeded",
    0x0B: "Connection Already Exists",
    0x0C: "Command Disallowed",
    0x0D: "Connection Rejected (Limited Resources)",
    0x0E: "Connection Rejected (Security)",
    0x0F: "Connection Rejected (Unacceptable BD_ADDR)",
    0x10: "Connection Accept Timeout Exceeded",
    0x11: "Unsupported Feature or Parameter Value",
    0x12: "Invalid HCI Command Parameters",
    0x13: "Remote User Terminated Connection",
    0x14: "Remote Device Terminated (Low Resources)",
    0x15: "Remote Device Terminated (Power Off)",
    0x16: "Connection Terminated By Local Host",
    0x1A: "Unsupported Remote Feature",
    0x1E: "Invalid LMP Parameters",
    0x1F: "Unspecified Error",
    0x22: "LMP Response Timeout",
    0x28: "Instant Passed",
    0x29: "Pairing With Unit Key Not Supported",
    0x2A: "Different Transaction Collision",
    0x3A: "Controller Busy",
    0x3B: "Unacceptable Connection Parameters",
    0x3C: "Advertising Timeout",
    0x3D: "Connection Terminated due to MIC Failure",
    0x3E: "Connection Failed to be Established",
}


# ── Data classes ───────────────────────────────────────────────────────────

@dataclass
class HCIPacket:
    """A decoded HCI packet from a btsnoop capture."""

    index: int = 0
    timestamp: datetime | None = None
    timestamp_us: int = 0
    direction: HCIDirection = HCIDirection.SENT
    packet_type: HCIPacketType = HCIPacketType.EVENT
    raw_data: bytes = b""

    # Decoded fields
    type_name: str = ""
    summary: str = ""
    detail_lines: list[str] = field(default_factory=list)

    # For ACL packets: L2CAP/ATT decoded info
    l2cap_cid: int = 0
    protocol: str = ""  # "HCI", "L2CAP", "ATT", "SMP", "GATT"

    @property
    def direction_str(self) -> str:
        return "\u2192" if self.direction == HCIDirection.SENT else "\u2190"

    @property
    def direction_label(self) -> str:
        return "Sent" if self.direction == HCIDirection.SENT else "Recv"

    @property
    def hex_dump(self) -> str:
        return format_hex_dump(self.raw_data)

    @property
    def relative_time(self) -> float:
        """Relative time in seconds (set externally by parser)."""
        return self.timestamp_us / 1_000_000.0 if self.timestamp_us else 0.0


def format_hex_dump(data: bytes, bytes_per_line: int = 16) -> str:
    """Format bytes as a hex dump with ASCII sidebar."""
    lines = []
    for offset in range(0, len(data), bytes_per_line):
        chunk = data[offset:offset + bytes_per_line]
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset:04X}  {hex_part:<{bytes_per_line * 3 - 1}}  {ascii_part}")
    return "\n".join(lines)


def format_bd_addr(data: bytes) -> str:
    """Format 6 bytes as a Bluetooth address (reversed byte order)."""
    if len(data) < 6:
        return "??:??:??:??:??:??"
    return ":".join(f"{b:02X}" for b in reversed(data[:6]))


def lookup_uuid16(uuid16: int) -> str:
    """Look up a 16-bit UUID in known GATT services/characteristics."""
    if uuid16 in GATT_SERVICE_UUIDS:
        return GATT_SERVICE_UUIDS[uuid16]
    if uuid16 in GATT_CHARACTERISTIC_UUIDS:
        return GATT_CHARACTERISTIC_UUIDS[uuid16]
    return f"0x{uuid16:04X}"


# ── Packet decoding ───────────────────────────────────────────────────────

def decode_hci_command(pkt: HCIPacket) -> None:
    """Decode an HCI Command packet."""
    data = pkt.raw_data
    if len(data) < 3:
        pkt.summary = "Malformed HCI Command"
        return

    opcode = struct.unpack_from("<H", data, 0)[0]
    param_len = data[2]
    params = data[3:3 + param_len]

    ogf = (opcode >> 10) & 0x3F
    ocf = opcode & 0x03FF
    ogf_name = OGF_NAMES.get(ogf, f"OGF 0x{ogf:02X}")
    cmd_name = HCI_COMMAND_NAMES.get(opcode, f"Unknown (0x{opcode:04X})")

    pkt.type_name = "CMD"
    pkt.protocol = "HCI"
    pkt.summary = cmd_name
    pkt.detail_lines = [
        f"HCI Command: {cmd_name}",
        f"Opcode: 0x{opcode:04X} (OGF: {ogf_name}, OCF: 0x{ocf:03X})",
        f"Parameter Length: {param_len}",
    ]

    # Decode specific commands
    if opcode == 0x0406 and len(params) >= 3:  # Disconnect
        handle = struct.unpack_from("<H", params, 0)[0] & 0x0FFF
        reason = params[2]
        reason_str = HCI_ERROR_CODES.get(reason, f"0x{reason:02X}")
        pkt.detail_lines.append(f"Connection Handle: 0x{handle:04X}")
        pkt.detail_lines.append(f"Reason: {reason_str}")
    elif opcode == 0x200C and len(params) >= 1:  # LE Set Scan Enable
        enabled = "Enable" if params[0] else "Disable"
        dup_filter = "On" if len(params) > 1 and params[1] else "Off"
        pkt.summary = f"LE Set Scan {enabled}"
        pkt.detail_lines.append(f"Scan: {enabled}")
        pkt.detail_lines.append(f"Filter Duplicates: {dup_filter}")
    elif opcode == 0x200B and len(params) >= 7:  # LE Set Scan Parameters
        scan_type = "Active" if params[0] else "Passive"
        interval = struct.unpack_from("<H", params, 1)[0]
        window = struct.unpack_from("<H", params, 3)[0]
        pkt.detail_lines.append(f"Scan Type: {scan_type}")
        pkt.detail_lines.append(f"Scan Interval: {interval * 0.625:.2f} ms")
        pkt.detail_lines.append(f"Scan Window: {window * 0.625:.2f} ms")
    elif opcode == 0x200A and len(params) >= 1:  # LE Set Advertising Enable
        enabled = "Enable" if params[0] else "Disable"
        pkt.summary = f"LE Advertising {enabled}"
        pkt.detail_lines.append(f"Advertising: {enabled}")
    elif opcode == 0x2005 and len(params) >= 6:  # LE Set Random Address
        addr = format_bd_addr(params[:6])
        pkt.detail_lines.append(f"Random Address: {addr}")

    if params:
        pkt.detail_lines.append(f"Parameters: {params.hex(' ').upper()}")


def decode_hci_event(pkt: HCIPacket) -> None:
    """Decode an HCI Event packet."""
    data = pkt.raw_data
    if len(data) < 2:
        pkt.summary = "Malformed HCI Event"
        return

    event_code = data[0]
    param_len = data[1]
    params = data[2:2 + param_len]

    event_name = HCI_EVENT_NAMES.get(event_code, f"Unknown Event (0x{event_code:02X})")

    pkt.type_name = "EVT"
    pkt.protocol = "HCI"
    pkt.summary = event_name
    pkt.detail_lines = [
        f"HCI Event: {event_name}",
        f"Event Code: 0x{event_code:02X}",
        f"Parameter Length: {param_len}",
    ]

    # Decode specific events
    if event_code == 0x0E and len(params) >= 3:  # Command Complete
        num_pkts = params[0]
        opcode = struct.unpack_from("<H", params, 1)[0]
        cmd_name = HCI_COMMAND_NAMES.get(opcode, f"0x{opcode:04X}")
        status = params[3] if len(params) > 3 else None
        pkt.summary = f"Command Complete: {cmd_name}"
        pkt.detail_lines.append(f"Num HCI Packets: {num_pkts}")
        pkt.detail_lines.append(f"Command Opcode: 0x{opcode:04X} ({cmd_name})")
        if status is not None:
            status_str = HCI_ERROR_CODES.get(status, f"0x{status:02X}")
            pkt.detail_lines.append(f"Status: {status_str}")
        if opcode == 0x1009 and len(params) >= 10:  # Read BD_ADDR
            addr = format_bd_addr(params[4:10])
            pkt.detail_lines.append(f"BD_ADDR: {addr}")
        elif opcode == 0x1405 and len(params) >= 7:  # Read RSSI
            handle = struct.unpack_from("<H", params, 4)[0] & 0x0FFF
            rssi = struct.unpack_from("<b", params, 6)[0]
            pkt.detail_lines.append(f"Handle: 0x{handle:04X}")
            pkt.detail_lines.append(f"RSSI: {rssi} dBm")

    elif event_code == 0x0F and len(params) >= 4:  # Command Status
        status = params[0]
        opcode = struct.unpack_from("<H", params, 2)[0]
        cmd_name = HCI_COMMAND_NAMES.get(opcode, f"0x{opcode:04X}")
        status_str = HCI_ERROR_CODES.get(status, f"0x{status:02X}")
        pkt.summary = f"Command Status: {cmd_name} ({status_str})"
        pkt.detail_lines.append(f"Status: {status_str}")
        pkt.detail_lines.append(f"Command: {cmd_name} (0x{opcode:04X})")

    elif event_code == 0x03 and len(params) >= 11:  # Connection Complete
        status = params[0]
        handle = struct.unpack_from("<H", params, 1)[0] & 0x0FFF
        addr = format_bd_addr(params[3:9])
        link_type = params[9]
        enc = params[10]
        status_str = HCI_ERROR_CODES.get(status, f"0x{status:02X}")
        link_str = {0x00: "SCO", 0x01: "ACL", 0x02: "eSCO"}.get(link_type, f"0x{link_type:02X}")
        pkt.summary = f"Connection Complete: {addr} ({status_str})"
        pkt.detail_lines.append(f"Status: {status_str}")
        pkt.detail_lines.append(f"Handle: 0x{handle:04X}")
        pkt.detail_lines.append(f"BD_ADDR: {addr}")
        pkt.detail_lines.append(f"Link Type: {link_str}")
        pkt.detail_lines.append(f"Encryption: {'Enabled' if enc else 'Disabled'}")

    elif event_code == 0x05 and len(params) >= 4:  # Disconnection Complete
        status = params[0]
        handle = struct.unpack_from("<H", params, 1)[0] & 0x0FFF
        reason = params[3]
        status_str = HCI_ERROR_CODES.get(status, f"0x{status:02X}")
        reason_str = HCI_ERROR_CODES.get(reason, f"0x{reason:02X}")
        pkt.summary = f"Disconnection: Handle 0x{handle:04X} ({reason_str})"
        pkt.detail_lines.append(f"Status: {status_str}")
        pkt.detail_lines.append(f"Handle: 0x{handle:04X}")
        pkt.detail_lines.append(f"Reason: {reason_str}")

    elif event_code == 0x22 and len(params) >= 1:  # Inquiry Result with RSSI
        num_responses = params[0]
        pkt.summary = f"Inquiry Result with RSSI ({num_responses} device(s))"
        offset = 1
        for i in range(num_responses):
            if offset + 14 > len(params):
                break
            addr = format_bd_addr(params[offset:offset + 6])
            rssi = struct.unpack_from("<b", params, offset + 13)[0]
            pkt.detail_lines.append(f"Device {i + 1}: {addr} (RSSI: {rssi} dBm)")
            offset += 14

    elif event_code == 0x3E:  # LE Meta Event
        _decode_le_meta_event(pkt, params)

    if params:
        pkt.detail_lines.append(f"Parameters: {params.hex(' ').upper()}")


def _decode_le_meta_event(pkt: HCIPacket, params: bytes) -> None:
    """Decode LE Meta Event sub-events."""
    if not params:
        return
    subevent = params[0]
    subevent_name = LE_SUBEVENT_NAMES.get(subevent, f"Unknown LE Sub-Event (0x{subevent:02X})")
    pkt.summary = subevent_name
    pkt.detail_lines.append(f"LE Sub-Event: {subevent_name} (0x{subevent:02X})")

    if subevent == 0x01 and len(params) >= 19:  # LE Connection Complete
        status = params[1]
        handle = struct.unpack_from("<H", params, 2)[0] & 0x0FFF
        role = "Central" if params[4] == 0 else "Peripheral"
        addr_type = "Public" if params[5] == 0 else "Random"
        addr = format_bd_addr(params[6:12])
        interval = struct.unpack_from("<H", params, 12)[0]
        latency = struct.unpack_from("<H", params, 14)[0]
        timeout = struct.unpack_from("<H", params, 16)[0]
        status_str = HCI_ERROR_CODES.get(status, f"0x{status:02X}")
        pkt.summary = f"LE Connection: {addr} ({status_str})"
        pkt.detail_lines.append(f"Status: {status_str}")
        pkt.detail_lines.append(f"Handle: 0x{handle:04X}")
        pkt.detail_lines.append(f"Role: {role}")
        pkt.detail_lines.append(f"Peer Address: {addr} ({addr_type})")
        pkt.detail_lines.append(f"Conn Interval: {interval * 1.25:.2f} ms")
        pkt.detail_lines.append(f"Conn Latency: {latency}")
        pkt.detail_lines.append(f"Supervision Timeout: {timeout * 10} ms")

    elif subevent == 0x02:  # LE Advertising Report
        _decode_le_adv_report(pkt, params)

    elif subevent == 0x0D:  # LE Extended Advertising Report
        _decode_le_ext_adv_report(pkt, params)


def _decode_le_adv_report(pkt: HCIPacket, params: bytes) -> None:
    """Decode LE Advertising Report sub-event."""
    if len(params) < 2:
        return
    num_reports = params[1]
    pkt.summary = f"LE Advertising Report ({num_reports} device(s))"
    offset = 2
    for i in range(num_reports):
        if offset + 9 > len(params):
            break
        event_type = params[offset]
        addr_type = "Public" if params[offset + 1] == 0 else "Random"
        addr = format_bd_addr(params[offset + 2:offset + 8])
        data_len = params[offset + 8]
        ad_data = params[offset + 9:offset + 9 + data_len]
        rssi_offset = offset + 9 + data_len
        rssi = struct.unpack_from("<b", params, rssi_offset)[0] if rssi_offset < len(params) else 0

        evt_types = {0: "ADV_IND", 1: "ADV_DIRECT_IND", 2: "ADV_SCAN_IND",
                     3: "ADV_NONCONN_IND", 4: "SCAN_RSP"}
        evt_str = evt_types.get(event_type, f"0x{event_type:02X}")

        pkt.detail_lines.append(f"--- Device {i + 1} ---")
        pkt.detail_lines.append(f"Address: {addr} ({addr_type})")
        pkt.detail_lines.append(f"Event Type: {evt_str}")
        pkt.detail_lines.append(f"RSSI: {rssi} dBm")

        # Decode AD structures
        _decode_ad_structures(pkt, ad_data)

        offset = rssi_offset + 1


def _decode_le_ext_adv_report(pkt: HCIPacket, params: bytes) -> None:
    """Decode LE Extended Advertising Report."""
    if len(params) < 2:
        return
    num_reports = params[1]
    pkt.summary = f"LE Extended Advertising Report ({num_reports} device(s))"
    offset = 2
    for i in range(num_reports):
        if offset + 24 > len(params):
            break
        addr_type = "Public" if params[offset + 3] == 0 else "Random"
        addr = format_bd_addr(params[offset + 4:offset + 10])
        rssi = struct.unpack_from("<b", params, offset + 20)[0]
        data_len = struct.unpack_from("<H", params, offset + 22)[0]
        ad_data = params[offset + 24:offset + 24 + data_len]

        pkt.detail_lines.append(f"--- Device {i + 1} ---")
        pkt.detail_lines.append(f"Address: {addr} ({addr_type})")
        pkt.detail_lines.append(f"RSSI: {rssi} dBm")
        _decode_ad_structures(pkt, ad_data)

        offset = offset + 24 + data_len


def _decode_ad_structures(pkt: HCIPacket, data: bytes) -> None:
    """Decode Advertising Data (AD) structures."""
    offset = 0
    while offset < len(data):
        if offset + 1 > len(data):
            break
        length = data[offset]
        if length == 0:
            break
        if offset + 1 + length > len(data):
            break
        ad_type = data[offset + 1]
        ad_value = data[offset + 2:offset + 1 + length]

        if ad_type == 0x01:  # Flags
            flags = ad_value[0] if ad_value else 0
            flag_strs = []
            if flags & 0x01:
                flag_strs.append("LE Limited Discoverable")
            if flags & 0x02:
                flag_strs.append("LE General Discoverable")
            if flags & 0x04:
                flag_strs.append("BR/EDR Not Supported")
            pkt.detail_lines.append(f"  Flags: {', '.join(flag_strs) if flag_strs else f'0x{flags:02X}'}")
        elif ad_type in (0x02, 0x03):  # Incomplete/Complete 16-bit UUIDs
            uuids = []
            for j in range(0, len(ad_value), 2):
                if j + 2 <= len(ad_value):
                    uuid16 = struct.unpack_from("<H", ad_value, j)[0]
                    uuids.append(lookup_uuid16(uuid16))
            pkt.detail_lines.append(f"  16-bit UUIDs: {', '.join(uuids)}")
        elif ad_type in (0x08, 0x09):  # Shortened/Complete Local Name
            try:
                name = ad_value.decode("utf-8", errors="replace")
                label = "Complete" if ad_type == 0x09 else "Short"
                pkt.detail_lines.append(f"  {label} Name: {name}")
            except Exception:
                pass
        elif ad_type == 0x0A:  # TX Power Level
            if ad_value:
                tx_power = struct.unpack_from("<b", ad_value, 0)[0]
                pkt.detail_lines.append(f"  TX Power: {tx_power} dBm")
        elif ad_type == 0xFF:  # Manufacturer Specific Data
            if len(ad_value) >= 2:
                company_id = struct.unpack_from("<H", ad_value, 0)[0]
                company = COMPANY_IDS.get(company_id, f"0x{company_id:04X}")
                mfr_data = ad_value[2:]
                pkt.detail_lines.append(f"  Manufacturer: {company}")
                if mfr_data:
                    pkt.detail_lines.append(f"  Manufacturer Data: {mfr_data.hex(' ').upper()}")
        else:
            ad_type_names = {
                0x06: "128-bit UUIDs", 0x07: "128-bit UUIDs",
                0x14: "16-bit Service Solicitation",
                0x16: "Service Data (16-bit UUID)",
                0x19: "Appearance", 0x1B: "LE Bluetooth Device Address",
            }
            name = ad_type_names.get(ad_type, f"AD Type 0x{ad_type:02X}")
            pkt.detail_lines.append(f"  {name}: {ad_value.hex(' ').upper()}")

        offset += 1 + length


def decode_acl_data(pkt: HCIPacket) -> None:
    """Decode an ACL Data packet including L2CAP, ATT, and SMP."""
    data = pkt.raw_data
    if len(data) < 4:
        pkt.type_name = "ACL"
        pkt.protocol = "HCI"
        pkt.summary = "Malformed ACL Data"
        return

    handle_flags = struct.unpack_from("<H", data, 0)[0]
    handle = handle_flags & 0x0FFF
    pb_flag = (handle_flags >> 12) & 0x03
    bc_flag = (handle_flags >> 14) & 0x03
    acl_len = struct.unpack_from("<H", data, 2)[0]

    pkt.type_name = "ACL"
    pkt.detail_lines = [
        f"ACL Data Packet",
        f"Connection Handle: 0x{handle:04X}",
        f"PB Flag: {pb_flag} ({'First' if pb_flag in (0, 2) else 'Continuation'})",
        f"BC Flag: {bc_flag}",
        f"Data Length: {acl_len}",
    ]

    l2cap_data = data[4:]
    if len(l2cap_data) < 4:
        pkt.protocol = "HCI"
        pkt.summary = f"ACL Handle 0x{handle:04X} ({acl_len} bytes)"
        return

    # L2CAP header
    l2cap_len = struct.unpack_from("<H", l2cap_data, 0)[0]
    l2cap_cid = struct.unpack_from("<H", l2cap_data, 2)[0]
    l2cap_payload = l2cap_data[4:4 + l2cap_len]
    pkt.l2cap_cid = l2cap_cid

    pkt.detail_lines.append(f"--- L2CAP ---")
    pkt.detail_lines.append(f"Length: {l2cap_len}")
    pkt.detail_lines.append(f"CID: 0x{l2cap_cid:04X}")

    if l2cap_cid == 0x0004:  # ATT
        pkt.protocol = "ATT"
        _decode_att(pkt, l2cap_payload, handle)
    elif l2cap_cid == 0x0006:  # SMP
        pkt.protocol = "SMP"
        _decode_smp(pkt, l2cap_payload)
    elif l2cap_cid == 0x0001:  # L2CAP Signaling
        pkt.protocol = "L2CAP"
        pkt.summary = f"L2CAP Signaling Handle 0x{handle:04X}"
        if l2cap_payload:
            sig_code = l2cap_payload[0]
            sig_names = {
                0x01: "Command Reject", 0x02: "Connection Request",
                0x03: "Connection Response", 0x04: "Configure Request",
                0x05: "Configure Response", 0x06: "Disconnection Request",
                0x07: "Disconnection Response", 0x0A: "Information Request",
                0x0B: "Information Response", 0x12: "Connection Parameter Update Request",
                0x13: "Connection Parameter Update Response",
            }
            pkt.summary = sig_names.get(sig_code, f"L2CAP Signal 0x{sig_code:02X}")
            pkt.detail_lines.append(f"Signal Code: {pkt.summary}")
    elif l2cap_cid == 0x0005:  # LE L2CAP Signaling
        pkt.protocol = "L2CAP"
        pkt.summary = f"LE L2CAP Signaling Handle 0x{handle:04X}"
    else:
        pkt.protocol = "L2CAP"
        pkt.summary = f"L2CAP CID 0x{l2cap_cid:04X} Handle 0x{handle:04X}"


def _decode_att(pkt: HCIPacket, payload: bytes, handle: int) -> None:
    """Decode ATT (Attribute Protocol) payload."""
    if not payload:
        pkt.summary = f"ATT Empty Handle 0x{handle:04X}"
        return

    opcode = payload[0]
    att_name = ATT_OPCODE_NAMES.get(opcode, f"ATT Opcode 0x{opcode:02X}")
    pkt.summary = att_name
    pkt.detail_lines.append(f"--- ATT ---")
    pkt.detail_lines.append(f"Opcode: 0x{opcode:02X} ({att_name})")

    if opcode == 0x01 and len(payload) >= 5:  # Error Response
        req_opcode = payload[1]
        attr_handle = struct.unpack_from("<H", payload, 2)[0]
        error_code = payload[4]
        error_names = {
            0x01: "Invalid Handle", 0x02: "Read Not Permitted",
            0x03: "Write Not Permitted", 0x05: "Authentication",
            0x06: "Request Not Supported", 0x07: "Invalid Offset",
            0x0A: "Attribute Not Found", 0x0D: "Insufficient Encryption",
            0x0E: "Insufficient Authentication",
        }
        pkt.detail_lines.append(f"Request Opcode: 0x{req_opcode:02X}")
        pkt.detail_lines.append(f"Attribute Handle: 0x{attr_handle:04X}")
        pkt.detail_lines.append(f"Error: {error_names.get(error_code, f'0x{error_code:02X}')}")

    elif opcode in (0x02, 0x03) and len(payload) >= 3:  # Exchange MTU
        mtu = struct.unpack_from("<H", payload, 1)[0]
        pkt.summary = f"{'Exchange MTU Request' if opcode == 0x02 else 'Exchange MTU Response'}: {mtu}"
        pkt.detail_lines.append(f"MTU: {mtu}")

    elif opcode in (0x08, 0x09):  # Read By Type Request/Response
        if opcode == 0x08 and len(payload) >= 7:
            start = struct.unpack_from("<H", payload, 1)[0]
            end = struct.unpack_from("<H", payload, 3)[0]
            if len(payload) == 7:
                uuid16 = struct.unpack_from("<H", payload, 5)[0]
                uuid_str = lookup_uuid16(uuid16)
            else:
                uuid_str = payload[5:].hex()
            pkt.summary = f"Read By Type: {uuid_str}"
            pkt.detail_lines.append(f"Start Handle: 0x{start:04X}")
            pkt.detail_lines.append(f"End Handle: 0x{end:04X}")
            pkt.detail_lines.append(f"UUID: {uuid_str}")

    elif opcode in (0x10, 0x11):  # Read By Group Type Request/Response
        if opcode == 0x10 and len(payload) >= 7:
            start = struct.unpack_from("<H", payload, 1)[0]
            end = struct.unpack_from("<H", payload, 3)[0]
            if len(payload) == 7:
                uuid16 = struct.unpack_from("<H", payload, 5)[0]
                uuid_str = lookup_uuid16(uuid16)
            else:
                uuid_str = payload[5:].hex()
            pkt.summary = f"Read By Group Type: {uuid_str}"
            pkt.detail_lines.append(f"Start Handle: 0x{start:04X}")
            pkt.detail_lines.append(f"End Handle: 0x{end:04X}")
            pkt.detail_lines.append(f"UUID: {uuid_str}")

    elif opcode in (0x0A, 0x0B):  # Read Request/Response
        if opcode == 0x0A and len(payload) >= 3:
            attr_handle = struct.unpack_from("<H", payload, 1)[0]
            pkt.summary = f"Read Request: Handle 0x{attr_handle:04X}"
            pkt.detail_lines.append(f"Attribute Handle: 0x{attr_handle:04X}")
        elif opcode == 0x0B:
            pkt.detail_lines.append(f"Value: {payload[1:].hex(' ').upper()}")

    elif opcode in (0x12, 0x52) and len(payload) >= 3:  # Write Request/Command
        attr_handle = struct.unpack_from("<H", payload, 1)[0]
        value = payload[3:]
        label = "Write Request" if opcode == 0x12 else "Write Command"
        pkt.summary = f"{label}: Handle 0x{attr_handle:04X}"
        pkt.detail_lines.append(f"Attribute Handle: 0x{attr_handle:04X}")
        pkt.detail_lines.append(f"Value: {value.hex(' ').upper()}")

    elif opcode == 0x1B and len(payload) >= 3:  # Handle Value Notification
        attr_handle = struct.unpack_from("<H", payload, 1)[0]
        value = payload[3:]
        pkt.summary = f"Notification: Handle 0x{attr_handle:04X}"
        pkt.detail_lines.append(f"Attribute Handle: 0x{attr_handle:04X}")
        pkt.detail_lines.append(f"Value: {value.hex(' ').upper()}")

    elif opcode == 0x1D and len(payload) >= 3:  # Handle Value Indication
        attr_handle = struct.unpack_from("<H", payload, 1)[0]
        value = payload[3:]
        pkt.summary = f"Indication: Handle 0x{attr_handle:04X}"
        pkt.detail_lines.append(f"Attribute Handle: 0x{attr_handle:04X}")
        pkt.detail_lines.append(f"Value: {value.hex(' ').upper()}")

    if len(payload) > 1:
        pkt.detail_lines.append(f"ATT Payload: {payload.hex(' ').upper()}")


def _decode_smp(pkt: HCIPacket, payload: bytes) -> None:
    """Decode SMP (Security Manager Protocol) payload."""
    if not payload:
        pkt.summary = "SMP Empty"
        return

    opcode = payload[0]
    smp_name = SMP_OPCODE_NAMES.get(opcode, f"SMP Opcode 0x{opcode:02X}")
    pkt.summary = smp_name
    pkt.detail_lines.append(f"--- SMP ---")
    pkt.detail_lines.append(f"Code: 0x{opcode:02X} ({smp_name})")

    if opcode in (0x01, 0x02) and len(payload) >= 7:  # Pairing Request/Response
        io_cap = {0: "Display Only", 1: "Display YesNo", 2: "Keyboard Only",
                  3: "No IO", 4: "Keyboard Display"}.get(payload[1], f"0x{payload[1]:02X}")
        auth_req = payload[3]
        auth_flags = []
        if auth_req & 0x01:
            auth_flags.append("Bonding")
        if auth_req & 0x04:
            auth_flags.append("MITM")
        if auth_req & 0x08:
            auth_flags.append("Secure Connections")
        pkt.detail_lines.append(f"IO Capability: {io_cap}")
        pkt.detail_lines.append(f"Auth Requirements: {', '.join(auth_flags) if auth_flags else 'None'}")
        pkt.detail_lines.append(f"Max Encryption Key Size: {payload[4]}")

    elif opcode == 0x05 and len(payload) >= 2:  # Pairing Failed
        reason_names = {
            0x01: "Passkey Entry Failed", 0x02: "OOB Not Available",
            0x03: "Authentication Requirements", 0x04: "Confirm Value Failed",
            0x05: "Pairing Not Supported", 0x06: "Encryption Key Size",
            0x07: "Command Not Supported", 0x08: "Unspecified Reason",
            0x09: "Repeated Attempts", 0x0B: "DHKey Check Failed",
            0x0C: "Numeric Comparison Failed",
        }
        reason = reason_names.get(payload[1], f"0x{payload[1]:02X}")
        pkt.summary = f"Pairing Failed: {reason}"
        pkt.detail_lines.append(f"Reason: {reason}")


def decode_sco_data(pkt: HCIPacket) -> None:
    """Decode an SCO Data packet."""
    data = pkt.raw_data
    pkt.type_name = "SCO"
    pkt.protocol = "HCI"

    if len(data) < 3:
        pkt.summary = "Malformed SCO Data"
        return

    handle_flags = struct.unpack_from("<H", data, 0)[0]
    handle = handle_flags & 0x0FFF
    sco_len = data[2]

    pkt.summary = f"SCO Data Handle 0x{handle:04X} ({sco_len} bytes)"
    pkt.detail_lines = [
        f"SCO Data Packet",
        f"Connection Handle: 0x{handle:04X}",
        f"Data Length: {sco_len}",
    ]


# ── btsnoop file parser ───────────────────────────────────────────────────

def parse_btsnoop(data: bytes) -> list[HCIPacket]:
    """Parse a btsnoop_hci.log file and return decoded HCI packets."""
    if len(data) < BTSNOOP_HEADER_SIZE:
        return []

    # Validate header
    magic = data[:8]
    if magic != BTSNOOP_MAGIC:
        return []

    version = struct.unpack_from(">I", data, 8)[0]
    datalink_type = struct.unpack_from(">I", data, 12)[0]

    if version != 1:
        return []

    # datalink_type: 1001 = H1 (unframed), 1002 = H4/UART (framed with type byte)
    is_h4 = (datalink_type == 1002)

    packets: list[HCIPacket] = []
    offset = BTSNOOP_HEADER_SIZE
    index = 0
    first_ts = 0

    while offset + BTSNOOP_RECORD_HEADER_SIZE <= len(data):
        orig_len = struct.unpack_from(">I", data, offset)[0]
        incl_len = struct.unpack_from(">I", data, offset + 4)[0]
        flags = struct.unpack_from(">I", data, offset + 8)[0]
        _drops = struct.unpack_from(">I", data, offset + 12)[0]
        ts_us = struct.unpack_from(">Q", data, offset + 16)[0]

        record_data_offset = offset + BTSNOOP_RECORD_HEADER_SIZE
        if record_data_offset + incl_len > len(data):
            break

        record_data = data[record_data_offset:record_data_offset + incl_len]
        offset = record_data_offset + incl_len

        # Determine direction and packet type
        direction = HCIDirection.RECEIVED if (flags & 0x01) else HCIDirection.SENT
        is_cmd_evt = bool(flags & 0x02)

        if is_h4:
            # H4: first byte is packet type indicator
            if not record_data:
                continue
            pkt_type_byte = record_data[0]
            pkt_data = record_data[1:]
            try:
                pkt_type = HCIPacketType(pkt_type_byte)
            except ValueError:
                continue
        else:
            # H1: type inferred from flags
            if direction == HCIDirection.SENT:
                pkt_type = HCIPacketType.COMMAND if is_cmd_evt else HCIPacketType.ACL_DATA
            else:
                pkt_type = HCIPacketType.EVENT if is_cmd_evt else HCIPacketType.ACL_DATA
            pkt_data = record_data

        # Convert timestamp
        unix_us = ts_us - _BTSNOOP_EPOCH_DELTA
        if index == 0:
            first_ts = unix_us

        pkt = HCIPacket(
            index=index,
            timestamp_us=unix_us - first_ts,
            direction=direction,
            packet_type=pkt_type,
            raw_data=pkt_data,
        )

        # Convert to datetime
        try:
            pkt.timestamp = datetime(1970, 1, 1) + timedelta(microseconds=unix_us)
        except (ValueError, OverflowError):
            pkt.timestamp = None

        # Decode packet
        if pkt_type == HCIPacketType.COMMAND:
            decode_hci_command(pkt)
        elif pkt_type == HCIPacketType.EVENT:
            decode_hci_event(pkt)
        elif pkt_type == HCIPacketType.ACL_DATA:
            decode_acl_data(pkt)
        elif pkt_type == HCIPacketType.SCO_DATA:
            decode_sco_data(pkt)

        packets.append(pkt)
        index += 1

    return packets


# ── Statistics ─────────────────────────────────────────────────────────────

@dataclass
class CaptureStats:
    """Statistics for a Bluetooth capture."""

    total_packets: int = 0
    commands: int = 0
    events: int = 0
    acl_packets: int = 0
    sco_packets: int = 0
    sent: int = 0
    received: int = 0
    total_bytes: int = 0
    duration_us: int = 0
    protocols: dict[str, int] = field(default_factory=dict)
    devices_seen: set[str] = field(default_factory=set)

    @property
    def duration_str(self) -> str:
        secs = self.duration_us / 1_000_000
        mins, secs = divmod(int(secs), 60)
        hours, mins = divmod(mins, 60)
        return f"{hours:02d}:{mins:02d}:{secs:02d}"


def compute_stats(packets: list[HCIPacket]) -> CaptureStats:
    """Compute capture statistics from a list of packets."""
    stats = CaptureStats()
    stats.total_packets = len(packets)

    for pkt in packets:
        stats.total_bytes += len(pkt.raw_data)

        if pkt.packet_type == HCIPacketType.COMMAND:
            stats.commands += 1
        elif pkt.packet_type == HCIPacketType.EVENT:
            stats.events += 1
        elif pkt.packet_type == HCIPacketType.ACL_DATA:
            stats.acl_packets += 1
        elif pkt.packet_type == HCIPacketType.SCO_DATA:
            stats.sco_packets += 1

        if pkt.direction == HCIDirection.SENT:
            stats.sent += 1
        else:
            stats.received += 1

        proto = pkt.protocol or "Unknown"
        stats.protocols[proto] = stats.protocols.get(proto, 0) + 1

        # Extract device addresses from detail lines
        for line in pkt.detail_lines:
            if "Address:" in line or "BD_ADDR:" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    addr = parts[1].strip().split(" ")[0].strip()
                    if len(addr) == 17 and addr.count(":") == 5:
                        stats.devices_seen.add(addr)

    if len(packets) >= 2:
        stats.duration_us = packets[-1].timestamp_us - packets[0].timestamp_us

    return stats


# ── pcap export ────────────────────────────────────────────────────────────

PCAP_MAGIC = 0xA1B2C3D4
PCAP_LINKTYPE_BLUETOOTH_HCI_H4_WITH_PHDR = 201


def export_pcap(packets: list[HCIPacket], filepath: str) -> None:
    """Export packets as a pcap file (Bluetooth HCI H4 with pseudo-header)."""
    with open(filepath, "wb") as f:
        # Global header
        f.write(struct.pack("<IHHiIII",
                            PCAP_MAGIC,  # magic
                            2, 4,  # version
                            0,  # thiszone
                            0,  # sigfigs
                            65535,  # snaplen
                            PCAP_LINKTYPE_BLUETOOTH_HCI_H4_WITH_PHDR))

        for pkt in packets:
            # Pseudo-header: 4-byte direction (0=sent, 1=received)
            phdr = struct.pack("<I", pkt.direction.value)
            # H4 type byte + raw data
            h4_type = struct.pack("B", pkt.packet_type.value)
            pkt_data = phdr + h4_type + pkt.raw_data

            # Timestamp
            ts_sec = pkt.timestamp_us // 1_000_000
            ts_usec = pkt.timestamp_us % 1_000_000

            # Packet header
            f.write(struct.pack("<IIII",
                                ts_sec, ts_usec,
                                len(pkt_data), len(pkt_data)))
            f.write(pkt_data)


def export_btsnoop(packets: list[HCIPacket], filepath: str) -> None:
    """Export packets as a btsnoop file."""
    with open(filepath, "wb") as f:
        # Header
        f.write(BTSNOOP_MAGIC)
        f.write(struct.pack(">II", 1, 1002))  # version 1, H4

        for pkt in packets:
            # H4 type byte + raw data
            pkt_data = struct.pack("B", pkt.packet_type.value) + pkt.raw_data
            data_len = len(pkt_data)

            # Flags
            flags = 0
            if pkt.direction == HCIDirection.RECEIVED:
                flags |= 0x01
            if pkt.packet_type in (HCIPacketType.COMMAND, HCIPacketType.EVENT):
                flags |= 0x02

            # Timestamp
            ts_us = pkt.timestamp_us + _BTSNOOP_EPOCH_DELTA

            f.write(struct.pack(">IIIIQ",
                                data_len, data_len,
                                flags, 0, ts_us))
            f.write(pkt_data)
