"""Shared acquisition entry points for the CLI, Python, and MCP tools."""

import math
import time

from .checks import evaluate, validate_limits
from .errors import ReadTimeout
from .transport import ReplayMeter, USBMeter


def validate_acquisition(count=1, interval=0.5, timeout=3.0, total_timeout=60.0):
    if type(count) is not int or not 1 <= count <= 1000:
        raise ValueError("count must be an integer from 1 to 1000")
    for value, name, low, high in (
        (interval, "interval", 0, 60),
        (timeout, "timeout", 0.05, 30),
        (total_timeout, "total_timeout", 0.05, 3600),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a number")
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{name} must be finite and between {low} and {high} seconds")
    if (count - 1) * interval >= total_timeout:
        raise ValueError("Sampling delays alone exceed total_timeout")


def open_meter(*, serial=None, path_hex=None, replay=None, timeout=3.0):
    if replay is not None:
        if serial is not None or path_hex is not None:
            raise ValueError("A replay cannot be combined with a USB selector")
        return ReplayMeter(replay)
    return USBMeter(serial=serial, path_hex=path_hex, timeout=timeout)


def collect(
    *,
    count=1,
    interval=0.5,
    timeout=3.0,
    total_timeout=60.0,
    serial=None,
    path_hex=None,
    replay=None,
    on_reading=None,
):
    validate_acquisition(count, interval, timeout, total_timeout)
    deadline = time.monotonic() + total_timeout
    readings = []
    with open_meter(
        serial=serial, path_hex=path_hex, replay=replay, timeout=min(timeout, total_timeout)
    ) as meter:
        for i in range(count):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ReadTimeout(
                    f"Total acquisition deadline exceeded after {len(readings)} samples"
                )
            if i and interval:
                if interval >= remaining:
                    raise ReadTimeout(
                        "Total acquisition deadline would be exceeded by sampling delay"
                    )
                time.sleep(interval)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ReadTimeout("Total acquisition deadline exceeded")
            reading = meter.read(min(timeout, remaining))
            if time.monotonic() > deadline:
                raise ReadTimeout("Response arrived after the total acquisition deadline")
            readings.append(reading)
            if on_reading:
                on_reading(reading)
        return meter.identity, readings


def read_measurements(**kwargs):
    identity, readings = collect(**kwargs)
    return {"ok": True, "identity": identity, "readings": [r.to_dict() for r in readings]}


def check_measurements(*, mode, unit, minimum, maximum, max_span=None, **kwargs):
    validate_limits(mode, unit, minimum, maximum, max_span)
    if max_span is not None and kwargs.get("count", 1) < 2:
        raise ValueError("A stability check needs at least two readings")
    identity, readings = collect(**kwargs)
    result = evaluate(
        readings, mode=mode, unit=unit, minimum=minimum, maximum=maximum, max_span=max_span
    )
    return {"ok": True, "identity": identity, **result, "readings": [r.to_dict() for r in readings]}
