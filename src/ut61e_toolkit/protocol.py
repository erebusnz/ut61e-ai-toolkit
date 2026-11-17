"""UT61E+ wire framing and decoding. Protocol references: docs/protocol.md."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from .errors import ProtocolError

HEADER = b"\xab\xcd"
GET_READING = 0x5E
GET_NAME = 0x5F

# Mode names deliberately follow the E+ references where practical. Range indices
# are ASCII '0' onwards on the wire, not a generic exponent or decimal position.
MODES = {
    0x00: "ACV",
    0x01: "ACmV",
    0x02: "DCV",
    0x03: "DCmV",
    0x04: "Hz",
    0x05: "%",
    0x06: "OHM",
    0x07: "CONT",
    0x08: "DIODE",
    0x09: "CAP",
    0x0C: "DCuA",
    0x0D: "ACuA",
    0x0E: "DCmA",
    0x0F: "ACmA",
    0x10: "DCA",
    0x11: "ACA",
    0x12: "HFE",
    0x14: "NCV",
    0x18: "LPF",
    0x19: "AC+DCV",
}
RANGE_UNITS = {
    "ACV": ("V",) * 4,
    "DCV": ("V",) * 4,
    "ACmV": ("mV",),
    "DCmV": ("mV",),
    "Hz": ("Hz", "Hz", "kHz", "kHz", "kHz", "MHz", "MHz", "MHz"),
    "%": ("%",),
    "OHM": ("ohm", "kohm", "kohm", "kohm", "Mohm", "Mohm", "Mohm"),
    "CONT": ("ohm",),
    "DIODE": ("V",),
    "CAP": ("nF", "nF", "uF", "uF", "uF", "mF", "mF", "mF"),
    "DCuA": ("uA",) * 2,
    "ACuA": ("uA",) * 2,
    "DCmA": ("mA",) * 2,
    "ACmA": ("mA",) * 2,
    # Range zero is not established for the UT61E+ A dial.
    "DCA": (None, "A"),
    "ACA": (None, "A"),
    "LPF": ("V",) * 4,
    "AC+DCV": ("V",) * 4,
}
BASE_UNITS = {"V", "A", "ohm", "F", "Hz", "%"}
PREFIX_EXPONENTS = {"n": -9, "u": -6, "m": -3, "k": 3, "M": 6}
CHECK_MODES = tuple(mode for mode in RANGE_UNITS if mode != "AC+DCV")


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def encode_frame(payload: bytes) -> bytes:
    if not 1 <= len(payload) <= 253:
        raise ValueError("Frame payload must contain 1..253 bytes")
    body = HEADER + bytes([len(payload) + 2]) + payload
    return body + (sum(body) & 0xFFFF).to_bytes(2, "big")


def frame_payload(frame: bytes) -> bytes:
    if len(frame) < 6 or frame[:2] != HEADER or len(frame) != frame[2] + 3:
        raise ProtocolError("Invalid frame header or length")
    if sum(frame[:-2]) & 0xFFFF != int.from_bytes(frame[-2:], "big"):
        raise ProtocolError("Frame checksum mismatch")
    return frame[3:-2]


class FrameDecoder:
    """Reassemble fragmented reports, recover after noise, verify every checksum."""

    def __init__(self):
        self.buffer = bytearray()
        self.rejected = 0

    def feed(self, data: bytes) -> list[bytes]:
        self.buffer.extend(data)
        frames = []
        while self.buffer:
            start = self.buffer.find(HEADER)
            if start < 0:
                self.buffer[:] = self.buffer[-1:] if self.buffer[-1] == 0xAB else b""
                break
            del self.buffer[:start]
            if len(self.buffer) < 3:
                break
            size = self.buffer[2] + 3
            if size < 6:
                self.rejected += 1
                del self.buffer[0]
                continue
            if len(self.buffer) < size:
                # A corrupted length must not hide a later complete, valid frame.
                later = self.buffer.find(HEADER, 2)
                recovered = False
                while later >= 0 and len(self.buffer) >= later + 3:
                    end = later + self.buffer[later + 2] + 3
                    if end <= len(self.buffer):
                        try:
                            frame_payload(bytes(self.buffer[later:end]))
                        except ProtocolError:
                            pass
                        else:
                            del self.buffer[:later]
                            self.rejected += 1
                            recovered = True
                            break
                    later = self.buffer.find(HEADER, later + 2)
                if recovered:
                    continue
                break
            candidate = bytes(self.buffer[:size])
            try:
                frame_payload(candidate)
            except ProtocolError:
                self.rejected += 1
                del self.buffer[0]
            else:
                frames.append(candidate)
                del self.buffer[:size]
        return frames


def split_unit(unit: str) -> tuple[str, int]:
    if unit in BASE_UNITS:
        return unit, 0
    return unit[1:], PREFIX_EXPONENTS[unit[0]]


@dataclass(frozen=True)
class Reading:
    timestamp: str
    source: str
    mode: str
    range_index: int
    display: str
    display_unit: str | None
    value: Decimal | None
    unit: str | None
    status: str
    flags: dict[str, bool]
    raw_hex: str
    recorded_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "source": self.source,
            "recorded_at": self.recorded_at,
            "mode": self.mode,
            "range_index": self.range_index,
            "display": self.display,
            "display_unit": self.display_unit,
            "value": float(self.value) if self.value is not None else None,
            "unit": self.unit,
            "status": self.status,
            "flags": self.flags,
            "raw_hex": self.raw_hex,
        }


def decode_reading(
    frame: bytes,
    *,
    source: str = "usb",
    recorded_at: str | None = None,
) -> Reading:
    payload = frame_payload(frame)
    if len(payload) != 14:
        raise ProtocolError("Expected a 19-byte measurement frame")
    if not 0x30 <= payload[1] <= 0x39:
        raise ProtocolError("Range byte is not an ASCII digit")
    if any(b & 0xF0 != 0x30 for b in payload[11:14]):
        raise ProtocolError("Invalid status flag encoding")
    try:
        display = payload[2:9].decode("ascii").replace(" ", "")
    except UnicodeDecodeError as exc:
        raise ProtocolError("Display is not ASCII") from exc
    f1, f2, f3 = payload[11:14]
    flags = {
        "rel": bool(f1 & 1),
        "hold": bool(f1 & 2),
        "min": bool(f1 & 4),
        "max": bool(f1 & 8),
        "hv_warning": bool(f2 & 1),
        "low_battery": bool(f2 & 2),
        "auto_range": not bool(f2 & 4),
        "apo": bool(f2 & 8),
        "bar_negative": bool(f3 & 1),
        "peak_min": bool(f3 & 2),
        "peak_max": bool(f3 & 4),
        "ac_component": bool(f3 & 8),
    }
    mode = MODES.get(payload[0], f"UNKNOWN_0x{payload[0]:02X}")
    index = payload[1] - 0x30
    units = RANGE_UNITS.get(mode, ())
    display_unit = units[index] if index < len(units) else None
    unit, exponent = split_unit(display_unit) if display_unit else (None, 0)
    value = None
    if re.fullmatch(r"-?(?:\.OL|O\.L|OL\.?|OL)", display):
        status = "overload"
    elif display_unit is None:
        status = "unsupported" if mode != "NCV" else "non_numeric"
    elif not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", display):
        raise ProtocolError(f"Unrecognized numeric display: {display!r}")
    else:
        value = Decimal(display).scaleb(exponent)
        status = "ok"
    return Reading(
        timestamp=utc_now(),
        source=source,
        mode=mode,
        range_index=index,
        display=display,
        display_unit=display_unit,
        value=value,
        unit=unit,
        status=status,
        flags=flags,
        raw_hex=frame.hex(" "),
        recorded_at=recorded_at,
    )
