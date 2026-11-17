from types import SimpleNamespace

import pytest

from ut61e_toolkit import service
from ut61e_toolkit.errors import ReadTimeout
from ut61e_toolkit.protocol import decode_reading


def test_acquisition_budget_covers_setup_delays_and_last_response(monkeypatch, sample_frame):
    clock = SimpleNamespace(now=0.0)

    def sleep(seconds):
        clock.now += seconds

    monkeypatch.setattr(service, "time", SimpleNamespace(monotonic=lambda: clock.now, sleep=sleep))

    class SlowMeter:
        identity = {"source": "test"}
        closed = False
        setup_time = 0
        read_time = 0

        def __enter__(self):
            clock.now += self.setup_time
            return self

        def read(self, timeout):
            assert 0 < timeout <= 1
            clock.now += self.read_time
            return decode_reading(sample_frame(), source="replay")

        def __exit__(self, *_):
            self.closed = True

    for setup, read, interval in ((2, 0, 0), (0, 2, 0), (0, 0.3, 0.8)):
        meter = SlowMeter()
        meter.setup_time = setup
        meter.read_time = read
        monkeypatch.setattr(service, "open_meter", lambda selected=meter, **_: selected)
        with pytest.raises(ReadTimeout):
            service.collect(count=2, interval=interval, timeout=1, total_timeout=1)
        assert meter.closed


def test_replay_selector_conflict():
    with pytest.raises(ValueError, match="selector"):
        service.open_meter(replay="file.jsonl", serial="live-device")
