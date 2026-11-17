"""CP2110/CH9329 USB access and an explicit offline replay source."""

import hashlib
import json
import math
import os
import tempfile
import time
from collections import deque
from pathlib import Path

from .errors import ConnectionError, ProtocolError, ReadTimeout, ReplayError
from .protocol import (
    GET_NAME,
    GET_READING,
    FrameDecoder,
    decode_reading,
    encode_frame,
    frame_payload,
)

VID, PID = 0x10C4, 0xEA80
USB_BRIDGES = {(VID, PID): "CP2110", (0x1A86, 0xE429): "CH9329"}


def _hid():
    try:
        import hid
    except ImportError as exc:
        raise ConnectionError('USB support is missing; install "ut61e-ai-toolkit[usb]"') from exc
    if not hasattr(hid, "device"):
        raise ConnectionError("Install the 'hidapi' package, not the different 'hid' package")
    return hid


def list_devices() -> list[dict]:
    """List bridge candidates; the VID/PID alone does not establish meter identity."""
    try:
        hid = _hid()
        devices = [
            (device, vid, pid, bridge)
            for (vid, pid), bridge in USB_BRIDGES.items()
            for device in hid.enumerate(vid, pid)
        ]
    except OSError as exc:
        raise ConnectionError(f"Cannot enumerate HID devices: {exc}") from exc
    return [
        {
            "path_hex": d["path"].hex(),
            "serial": d.get("serial_number"),
            "manufacturer": d.get("manufacturer_string"),
            "product": d.get("product_string"),
            "vendor_id": vid,
            "product_id": pid,
            "bridge": bridge,
        }
        for d, vid, pid, bridge in devices
    ]


class _DeviceLock:
    """An OS-held lease, shared by separate CLI and MCP processes for this user."""

    def __init__(self, path: bytes):
        key = hashlib.sha256(path).hexdigest()[:24]
        self.path = Path(tempfile.gettempdir()) / f"ut61e-{key}.lock"
        self.file = None

    def acquire(self):
        self.file = self.path.open("a+b")
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b"\0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            raise ConnectionError(
                "This meter is already in use by another toolkit process"
            ) from exc

    def close(self):
        if self.file:
            self.file.close()  # Closing releases the OS lock, including on process exit.
            self.file = None


class USBMeter:
    source = "usb"

    def __init__(self, *, serial: str | None = None, path_hex: str | None = None, timeout=3.0):
        self.serial = serial
        self.path_hex = path_hex
        self.timeout = timeout
        self.device = None
        self.lease = None
        self.decoder = FrameDecoder()
        self.pending = deque()
        self.identity = None
        self.bridge = None

    def __enter__(self):
        candidates = list_devices()
        if self.serial is not None:
            candidates = [d for d in candidates if d["serial"] == self.serial]
        if self.path_hex is not None:
            try:
                selector = bytes.fromhex(self.path_hex).hex()
            except ValueError as exc:
                raise ValueError("path_hex must be a hexadecimal HID path from 'devices'") from exc
            candidates = [d for d in candidates if d["path_hex"] == selector]
        if not candidates:
            raise ConnectionError(
                "No matching USB bridge found. Connect the UT61E+ USB cable and run 'devices'."
            )
        if len(candidates) != 1:
            raise ConnectionError("Multiple bridges match; select a unique --serial or --path-hex")
        selected = candidates[0]
        self.bridge = selected["bridge"]
        path = bytes.fromhex(selected["path_hex"])
        self.lease = _DeviceLock(path)
        try:
            self.lease.acquire()
            self.device = _hid().device()
            self.device.open_path(path)
            if self.bridge == "CP2110":
                # Enable UART; set 9600/8N1/no flow control; purge the RX FIFO.
                for report in (
                    b"\x41\x01",
                    bytes.fromhex("50 00 00 25 80 00 00 03 00"),
                    b"\x43\x02",
                ):
                    if self.device.send_feature_report(report) != len(report):
                        raise ConnectionError("CP2110 rejected a UART configuration report")
            # The UNI-T CH9329 cable is already configured. It uses unnumbered
            # 65-byte writes, not CP2110 feature reports or variable report IDs.
            name_frame = self._request(GET_NAME, self.timeout)
            try:
                name = frame_payload(name_frame).decode("ascii").strip("\0 \r\n")
            except UnicodeDecodeError as exc:
                raise ProtocolError("Meter returned a non-ASCII model name") from exc
            if name.upper() != "UT61E+":
                raise ConnectionError(f"Unsupported meter identity {name!r}; expected UT61E+")
            self.identity = {"model": name, "source": self.source, "device": selected}
            return self
        except BaseException as exc:
            self.close()
            if isinstance(exc, OSError):
                raise ConnectionError(
                    f"Cannot open/configure USB bridge: {exc}. Close other DMM applications."
                ) from exc
            raise

    def _request(self, command: int, timeout: float) -> bytes:
        # Requests are strictly serial. A timed-out session is closed by the caller;
        # it is never retried with an ambiguous delayed response still in flight.
        if self.pending or self.decoder.buffer:
            raise ProtocolError(
                "Unexpected buffered response before a new request; reopen the meter"
            )
        frame = encode_frame(bytes([command]))
        report = bytes([len(frame)]) + frame
        if self.bridge == "CH9329":
            report = (b"\x00" + report).ljust(65, b"\x00")
        read_size = 65 if self.bridge == "CH9329" else 64
        deadline = time.monotonic() + timeout
        try:
            # Windows HIDAPI pads to the device's longest report and returns that
            # byte count. Other backends return the submitted short report length.
            if self.device.write(report) not in (len(report), read_size):
                raise ConnectionError("Incomplete HID write")
            while True:
                while self.pending:
                    response = self.pending.popleft()
                    payload = frame_payload(response)
                    if payload == b"\xff\x00":
                        continue  # GetName may deliver an ACK before the model string.
                    if payload[:1] == b"\xff":
                        raise ProtocolError(f"Meter rejected request: {payload.hex(' ')}")
                    return response
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ReadTimeout(
                        "No valid meter response before the deadline. Check power, USB mode, "
                        f"and cable alignment. Rejected frames: {self.decoder.rejected}."
                    )
                report = bytes(
                    self.device.read(read_size, max(1, min(100, math.ceil(remaining * 1000))))
                )
                if not report:
                    continue
                offset = 0
                if self.bridge == "CH9329" and report[0] == 0:
                    # Some HID backends retain the zero report ID; Windows strips
                    # it. In either case, the next byte is the UART byte count.
                    if len(report) == 1:
                        continue
                    offset = 1
                length = report[offset]
                if length > 63 or len(report) < offset + length + 1:
                    raise ProtocolError(f"Invalid {self.bridge} data report length")
                if length == 0:
                    if self.bridge == "CH9329":
                        continue
                    raise ProtocolError("Invalid CP2110 data report length")
                # Trailing bytes can contain stale, nonzero padding on CH9329.
                start = offset + 1
                self.pending.extend(self.decoder.feed(report[start : start + length]))
        except OSError as exc:
            raise ConnectionError(f"USB I/O failed: {exc}") from exc

    def read(self, timeout: float):
        return decode_reading(self._request(GET_READING, timeout), source=self.source)

    def close(self):
        try:
            if self.device is not None:
                self.device.close()
                self.device = None
        finally:
            if self.lease:
                self.lease.close()

    def __exit__(self, *_):
        self.close()


class ReplayMeter:
    source = "replay"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.file = None
        self.line = 0
        self.identity = {"model": "UT61E+", "source": self.source, "file": str(self.path)}

    def __enter__(self):
        try:
            self.file = self.path.open(encoding="utf-8-sig")
        except OSError as exc:
            raise ReplayError(f"Cannot open replay: {exc}") from exc
        return self

    def read(self, timeout: float):
        for line in self.file:
            self.line += 1
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                frame = bytes.fromhex(record["raw_hex"])
                recorded_at = record.get("timestamp")
                if recorded_at is not None and not isinstance(recorded_at, str):
                    raise ValueError("timestamp must be a string")
                # Re-decode the wire bytes; never trust cached values or a prior verdict.
                return decode_reading(frame, source=self.source, recorded_at=recorded_at)
            except (ValueError, TypeError, KeyError, ProtocolError) as exc:
                raise ReplayError(f"Invalid replay record at line {self.line}: {exc}") from exc
        raise ReplayError("Replay exhausted; request fewer samples or provide a longer capture")

    def __exit__(self, *_):
        if self.file:
            self.file.close()
