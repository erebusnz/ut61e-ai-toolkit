from pathlib import Path

import pytest

from ut61e_toolkit.protocol import encode_frame


@pytest.fixture
def sample_frame():
    def make(display="3.3000", mode=2, range_index=1, flags=(0, 0, 0)):
        text = display.rjust(7).encode("ascii")
        assert len(text) == 7
        payload = bytes([mode, 0x30 + range_index]) + text + b"\x00\x00"
        payload += bytes(0x30 | f for f in flags)
        return encode_frame(payload)

    return make


@pytest.fixture
def replay_file():
    return Path(__file__).resolve().parents[1] / "examples" / "dc_3v3.jsonl"
