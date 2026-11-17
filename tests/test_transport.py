import json
from collections import deque
from types import SimpleNamespace

import pytest

from ut61e_toolkit import transport
from ut61e_toolkit.errors import ConnectionError, ProtocolError, ReadTimeout, ReplayError
from ut61e_toolkit.protocol import encode_frame


class FakeHID:
    def __init__(self, frame, *, name=b"UT61E+", silent=False, padded=False):
        self.frame = frame
        self.name = name
        self.silent = silent
        self.padded = padded
        self.queue = deque()
        self.features = []
        self.writes = []
        self.closed = False

    def open_path(self, path):
        self.path = path

    def send_feature_report(self, report):
        self.features.append(report)
        return len(report)

    def write(self, report):
        self.writes.append(report)
        if not self.silent:
            if report[4] == 0x5F:
                frames = encode_frame(b"\xff\x00") + encode_frame(self.name)
            else:
                frames = self.frame
            if self.padded:
                self.queue.append(bytes([len(frames)]) + frames + b"\0" * (63 - len(frames)))
            else:
                self.queue.extend(bytes([1, b]) for b in frames)
        return 64 if self.padded else len(report)

    def read(self, size, timeout_ms):
        assert size == 64
        assert 1 <= timeout_ms <= 100
        return self.queue.popleft() if self.queue else []

    def close(self):
        self.closed = True


def install_fake(monkeypatch, fake, candidates=None, *, bridge="CP2110"):
    if candidates is None:
        candidates = [{"path": b"fake-ut61e-test", "serial_number": "test"}]
    identifiers = next(pair for pair, name in transport.USB_BRIDGES.items() if name == bridge)
    module = SimpleNamespace(
        device=lambda: fake,
        enumerate=lambda vid, pid: candidates if (vid, pid) == identifiers else [],
    )
    monkeypatch.setattr(transport, "_hid", lambda: module)


@pytest.mark.parametrize("padded", [True, False])
def test_usb_identity_fragments_and_close(monkeypatch, sample_frame, padded):
    fake = FakeHID(sample_frame(), padded=padded)
    install_fake(monkeypatch, fake)
    with transport.USBMeter() as meter:
        assert meter.identity["model"] == "UT61E+"
        assert meter.read(0.1).to_dict()["value"] == 3.3
    assert fake.closed
    assert fake.features == [b"\x41\x01", bytes.fromhex("50 00 00 25 80 00 00 03 00"), b"\x43\x02"]
    assert fake.writes == [
        bytes.fromhex("06 ab cd 03 5f 01 da"),
        bytes.fromhex("06 ab cd 03 5e 01 d9"),
    ]


def test_identity_mismatch_and_timeout_close_device(monkeypatch, sample_frame):
    for kwargs, error in (({"name": b"UT61D+"}, ConnectionError), ({"silent": True}, ReadTimeout)):
        fake = FakeHID(sample_frame(), **kwargs)
        install_fake(monkeypatch, fake)
        with pytest.raises(error), transport.USBMeter(timeout=0.01):
            pytest.fail("Must fail while opening")
        assert fake.closed


def test_selection_is_unambiguous(monkeypatch, sample_frame):
    fake = FakeHID(sample_frame())
    candidates = [
        {"path": b"fake-a", "serial_number": "same"},
        {"path": b"fake-b", "serial_number": "same"},
    ]
    install_fake(monkeypatch, fake, candidates)
    with pytest.raises(ConnectionError, match="Multiple"), transport.USBMeter(serial="same"):
        pass
    with transport.USBMeter(path_hex=b"fake-b".hex()) as meter:
        assert meter.identity["device"]["path_hex"] == b"fake-b".hex()
    with pytest.raises(ConnectionError, match="No matching"), transport.USBMeter(serial="absent"):
        pass


def test_toolkit_lock_releases_on_close():
    first = transport._DeviceLock(b"test-lock-key")
    second = transport._DeviceLock(b"test-lock-key")
    try:
        first.acquire()
        with pytest.raises(ConnectionError, match="already in use"):
            second.acquire()
        first.close()
        second.acquire()
    finally:
        first.close()
        second.close()


def test_short_write_and_invalid_hid_report(monkeypatch, sample_frame):
    fake = FakeHID(sample_frame())
    install_fake(monkeypatch, fake)
    with transport.USBMeter() as meter:
        monkeypatch.setattr(fake, "write", lambda data: 0)
        with pytest.raises(ConnectionError, match="Incomplete"):
            meter.read(0.1)
    fake = FakeHID(sample_frame())
    install_fake(monkeypatch, fake)
    with transport.USBMeter() as meter:
        monkeypatch.setattr(fake, "read", lambda *_: [63, 1])
        with pytest.raises(ProtocolError, match="length"):
            meter.read(0.1)


def test_buffered_unsolicited_frame_is_not_a_fresh_reading(monkeypatch, sample_frame):
    fake = FakeHID(sample_frame() + sample_frame(), padded=True)
    install_fake(monkeypatch, fake)
    with transport.USBMeter() as meter:
        meter.read(0.1)
        with pytest.raises(ProtocolError, match="buffered"):
            meter.read(0.1)


def test_failed_usb_setup_releases_handle_and_lock(monkeypatch, sample_frame):
    fake = FakeHID(sample_frame())
    install_fake(monkeypatch, fake)
    monkeypatch.setattr(fake, "send_feature_report", lambda _: -1)
    with pytest.raises(ConnectionError, match="configuration"), transport.USBMeter():
        pass
    assert fake.closed
    replacement = FakeHID(sample_frame())
    install_fake(monkeypatch, replacement)
    with transport.USBMeter():
        pass


def test_replay_redecodes_and_rejects_bad_frame(tmp_path, sample_frame):
    path = tmp_path / "record.jsonl"
    path.write_text(
        json.dumps(
            {
                "raw_hex": sample_frame().hex(),
                "value": 999,
                "source": "usb",
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        + "\n"
    )
    with transport.ReplayMeter(path) as meter:
        reading = meter.read(1)
        assert reading.to_dict()["value"] == 3.3
        assert reading.source == "replay"
        assert reading.recorded_at == "2026-01-01T00:00:00Z"
        with pytest.raises(ReplayError, match="exhausted"):
            meter.read(1)
    path.write_text('{"raw_hex":"ab cd 03 5e 00 00"}\n')
    with transport.ReplayMeter(path) as meter, pytest.raises(ReplayError, match="checksum"):
        meter.read(1)


class FakeWCH(FakeHID):
    def __init__(self, frame, *, report_id_present):
        super().__init__(frame)
        self.report_id_present = report_id_present

    def send_feature_report(self, report):
        pytest.fail("CH9329 must not receive CP2110 configuration reports")

    def write(self, report):
        self.writes.append(report)
        assert len(report) == 65
        assert report[:2] == b"\x00\x06"
        assert report[8:] == bytes(57)
        if report[5] == 0x5F:
            frames = [encode_frame(b"\xff\x00"), encode_frame(self.name)]
        else:
            # Fragment a measurement over several reports, with stale nonzero
            # bytes after the declared length as observed on the physical cable.
            frames = [self.frame[:3], self.frame[3:10], self.frame[10:]]
        self.queue.append(bytes(65 if self.report_id_present else 64))
        for frame in frames:
            raw = (bytes([len(frame)]) + frame).ljust(64, b"\xdd")
            self.queue.append(b"\x00" + raw if self.report_id_present else raw)
        return 65

    def read(self, size, timeout_ms):
        assert size == 65
        assert 1 <= timeout_ms <= 100
        return self.queue.popleft() if self.queue else []


@pytest.mark.parametrize("report_id_present", [False, True])
def test_ch9329_identity_and_reading(monkeypatch, sample_frame, report_id_present):
    fake = FakeWCH(sample_frame(), report_id_present=report_id_present)
    install_fake(monkeypatch, fake, bridge="CH9329")
    with transport.USBMeter() as meter:
        assert meter.identity["model"] == "UT61E+"
        assert meter.identity["device"]["bridge"] == "CH9329"
        assert meter.identity["device"]["vendor_id"] == 0x1A86
        assert meter.read(0.1).to_dict()["value"] == 3.3
        assert meter.read(0.1).to_dict()["value"] == 3.3
    assert fake.closed
    assert fake.writes[0][:8].hex(" ") == "00 06 ab cd 03 5f 01 da"
    assert fake.writes[1][:8].hex(" ") == "00 06 ab cd 03 5e 01 d9"


@pytest.mark.parametrize("raw", [b"\x00\x40", b"\x40", b"\x03\xab\xcd"])
def test_ch9329_rejects_malformed_report(monkeypatch, sample_frame, raw):
    fake = FakeWCH(sample_frame(), report_id_present=False)
    install_fake(monkeypatch, fake, bridge="CH9329")
    with transport.USBMeter() as meter:
        monkeypatch.setattr(fake, "read", lambda *_: raw)
        with pytest.raises(ProtocolError, match="CH9329.*length"):
            meter.read(0.1)


def test_mixed_bridge_types_require_selection(monkeypatch, sample_frame):
    fake = FakeHID(sample_frame())
    module = SimpleNamespace(
        device=lambda: fake,
        enumerate=lambda vid, pid: [{"path": str(vid).encode(), "serial_number": str(vid)}],
    )
    monkeypatch.setattr(transport, "_hid", lambda: module)
    devices = transport.list_devices()
    assert {d["bridge"] for d in devices} == {"CP2110", "CH9329"}
    with pytest.raises(ConnectionError, match="Multiple"), transport.USBMeter():
        pass
