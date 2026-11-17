from dataclasses import replace

import pytest

from ut61e_toolkit.checks import evaluate, validate_limits
from ut61e_toolkit.protocol import decode_reading


def check(readings, **kwargs):
    defaults = {"mode": "DCV", "unit": "V", "minimum": "3.2", "maximum": "3.4"}
    defaults.update(kwargs)
    return evaluate(readings, **defaults)


def test_inclusive_limits_and_decimal_stability(sample_frame):
    readings = [decode_reading(sample_frame(v)) for v in ("3.2000", "3.4000")]
    result = check(readings, max_span="0.2")
    assert result["verdict"] == "pass"
    assert result["statistics"] == {"min": 3.2, "max": 3.4, "mean": 3.3, "span": 0.2, "unit": "V"}
    assert check(readings, max_span="0.1999")["verdict"] == "fail"


def test_every_sample_must_pass_not_just_average(sample_frame):
    readings = [decode_reading(sample_frame(v)) for v in ("3.1000", "3.5000")]
    result = check(readings)
    assert result["statistics"]["mean"] == 3.3
    assert result["verdict"] == "fail"
    assert result["out_of_limits_samples"] == [0, 1]


@pytest.mark.parametrize(
    "flags", [(1, 0, 0), (2, 0, 0), (4, 0, 0), (8, 0, 0), (0, 0, 2), (0, 0, 4), (0, 2, 0)]
)
def test_unusable_flags_never_pass(sample_frame, flags):
    result = check([decode_reading(sample_frame(flags=flags))])
    assert result["verdict"] == "invalid"
    assert result["passed"] is False
    assert result["statistics"] is None


@pytest.mark.parametrize(
    "frame_args",
    [
        {"display": "OL"},
        {"mode": 0},
        {"mode": 6},
        {"range_index": 9},
    ],
)
def test_invalid_context(sample_frame, frame_args):
    assert check([decode_reading(sample_frame(**frame_args))])["verdict"] == "invalid"


def test_hv_is_exposed_and_replay_remains_replay(sample_frame):
    reading = decode_reading(sample_frame(flags=(0, 1, 0)), source="replay")
    result = check([reading])
    assert result["verdict"] == "pass"
    assert result["hv_warning"] is True
    assert result["sources"] == ["replay"]
    assert check([reading, replace(reading, source="usb")])["verdict"] == "invalid"


@pytest.mark.parametrize(
    "changes",
    [
        {"minimum": "NaN"},
        {"maximum": "Infinity"},
        {"minimum": 4},
        {"max_span": -1},
        {"mode": "AC+DCV"},
        {"unit": "mV"},
        {"unit": "A"},
        {"minimum": "-1e9999"},
        {"max_span": "1e-9999"},
    ],
)
def test_invalid_criteria(changes):
    args = {"mode": "DCV", "unit": "V", "minimum": 3.2, "maximum": 3.4, **changes}
    with pytest.raises(ValueError):
        validate_limits(**args)


def test_zero_or_one_sample_stability_is_invalid(sample_frame):
    with pytest.raises(ValueError):
        check([])
    with pytest.raises(ValueError):
        check([decode_reading(sample_frame())], max_span=1)
