from decimal import Decimal

import pytest

from ut61e_toolkit.errors import ProtocolError
from ut61e_toolkit.protocol import FrameDecoder, decode_reading, encode_frame, frame_payload


def test_documented_wire_vectors():
    assert encode_frame(b"\x5e").hex(" ") == "ab cd 03 5e 01 d9"
    assert encode_frame(b"\x5f").hex(" ") == "ab cd 03 5f 01 da"
    # ACmV example documented by ljakob/unit_ut61eplus (not encoder-generated).
    reading = decode_reading(
        bytes.fromhex("ab cd 10 01 30 20 20 35 33 2e 35 34 01 00 30 34 30 03 8d")
    )
    assert reading.display == "53.54"
    assert reading.display_unit == "mV"
    assert reading.value == Decimal("0.05354")
    assert reading.unit == "V"
    assert reading.mode == "ACmV"
    assert reading.flags["auto_range"] is False


def test_live_ut61eplus_dcv_frame():
    # Captured via WCH 1a86:e429 on 2026-11-18; see the hardware validation report.
    reading = decode_reading(
        bytes.fromhex("ab cd 10 02 30 2d 30 2e 30 30 30 31 00 04 30 30 30 03 9a")
    )
    assert reading.mode == "DCV"
    assert reading.unit == "V"
    assert reading.value == Decimal("-0.0001")
    assert reading.status == "ok"


def test_fragmentation_noise_and_multiple_frames(sample_frame):
    expected = sample_frame()
    stream = b"noise\xab\xab" + expected + expected
    for width in range(1, len(stream) + 1):
        decoder = FrameDecoder()
        actual = []
        for start in range(0, len(stream), width):
            actual.extend(decoder.feed(stream[start : start + width]))
        assert actual == [expected, expected]


def test_corrupt_checksum_and_length_resynchronize(sample_frame):
    frame = sample_frame()
    bad_checksum = frame[:-1] + bytes([frame[-1] ^ 1])
    bad_length = b"\xab\xcd\xffgarbage"
    for prefix in (bad_checksum, bad_length, b"\xab\xcd\x00"):
        decoder = FrameDecoder()
        assert decoder.feed(prefix + frame) == [frame]
        assert decoder.rejected > 0
    with pytest.raises(ProtocolError, match="checksum"):
        decode_reading(bad_checksum)


@pytest.mark.parametrize(
    "mode,index,display,unit,value",
    [
        (2, 0, "1.2345", "V", "1.2345"),
        (2, 3, "999.99", "V", "999.99"),
        (3, 0, "-12.345", "V", "-0.012345"),
        (6, 1, "1.0000", "ohm", "1000"),
        (6, 6, "12.345", "ohm", "12345000"),
        (9, 0, "2.2000", "F", "0.0000000022"),
        (9, 2, "2.2000", "F", "0.0000022"),
        (9, 5, "2.2000", "F", "0.0022"),
        (12, 1, "100.00", "A", "0.0001"),
        (14, 0, "10.000", "A", "0.01"),
        (16, 1, "1.0000", "A", "1"),
        (4, 2, "1.0000", "Hz", "1000"),
        (4, 5, "1.0000", "Hz", "1000000"),
        (5, 0, "50.000", "%", "50"),
        (7, 0, "1.2345", "ohm", "1.2345"),
        (8, 0, "0.6543", "V", "0.6543"),
    ],
)
def test_unit_scaling(sample_frame, mode, index, display, unit, value):
    reading = decode_reading(sample_frame(display, mode, index))
    assert reading.unit == unit
    assert reading.value == Decimal(value)


@pytest.mark.parametrize("display", ["OL", "OL.", ".OL", "O.L", "-OL", "-O.L"])
def test_overload_is_not_a_number(sample_frame, display):
    reading = decode_reading(sample_frame(display))
    assert reading.status == "overload"
    assert reading.value is None
    assert reading.to_dict()["value"] is None


@pytest.mark.parametrize("mode,index", [(2, 9), (16, 0), (0x7F, 0), (18, 0)])
def test_unknown_data_is_not_guessed(sample_frame, mode, index):
    reading = decode_reading(sample_frame(mode=mode, range_index=index))
    assert reading.status == "unsupported"
    assert reading.value is None


def test_ncv_remains_non_numeric(sample_frame):
    reading = decode_reading(sample_frame("EF", mode=20, range_index=0))
    assert reading.status == "non_numeric"
    assert reading.value is None


@pytest.mark.parametrize("display", ["NaN", "inf", "1e3", "", "abc"])
def test_invalid_numeric_display(sample_frame, display):
    with pytest.raises(ProtocolError):
        decode_reading(sample_frame(display))


def test_flag_semantics(sample_frame):
    reading = decode_reading(sample_frame(flags=(15, 15, 15)))
    assert all(v for k, v in reading.flags.items() if k != "auto_range")
    assert reading.flags["auto_range"] is False
    zero = decode_reading(sample_frame())
    assert zero.flags["auto_range"] is True
    assert zero.flags["ac_component"] is False


def test_bad_range_and_status_bytes(sample_frame):
    payload = bytearray(frame_payload(sample_frame()))
    for index, value in ((1, 0), (11, 0xFF)):
        modified = payload.copy()
        modified[index] = value
        with pytest.raises(ProtocolError):
            decode_reading(encode_frame(modified))
