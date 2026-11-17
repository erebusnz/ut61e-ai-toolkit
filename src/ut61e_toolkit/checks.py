"""Deterministic limits checks; no verdict without valid measurement context."""

import math
from decimal import Decimal, InvalidOperation

from .protocol import BASE_UNITS, CHECK_MODES, RANGE_UNITS, Reading, split_unit

UNUSABLE_FLAGS = ("hold", "rel", "min", "max", "peak_min", "peak_max", "low_battery")


def finite_decimal(value, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not result.is_finite() or not math.isfinite(float(result)):
        raise ValueError(f"{name} must be a finite JSON number")
    if result != 0 and float(result) == 0:
        raise ValueError(f"{name} is too small to represent as a JSON number")
    return result


def validate_limits(mode: str, unit: str, minimum, maximum, max_span=None):
    if mode not in CHECK_MODES:
        raise ValueError(f"Check mode must be one of: {', '.join(CHECK_MODES)}")
    if unit not in BASE_UNITS:
        raise ValueError("Use a base unit: V, A, ohm, F, Hz, or %")
    allowed_units = {split_unit(u)[0] for u in RANGE_UNITS[mode] if u}
    if unit not in allowed_units:
        raise ValueError(f"Unit {unit!r} does not match mode {mode!r}")
    low = finite_decimal(minimum, "minimum")
    high = finite_decimal(maximum, "maximum")
    span = finite_decimal(max_span, "max_span") if max_span is not None else None
    if low > high:
        raise ValueError("minimum must be <= maximum")
    if span is not None and span < 0:
        raise ValueError("max_span must be nonnegative")
    return low, high, span


def evaluate(readings: list[Reading], *, mode: str, unit: str, minimum, maximum, max_span=None):
    low, high, span_limit = validate_limits(mode, unit, minimum, maximum, max_span)
    if not readings:
        raise ValueError("A check needs at least one reading")
    if span_limit is not None and len(readings) < 2:
        raise ValueError("A stability check needs at least two readings")
    issues = []
    failures = []
    for i, reading in enumerate(readings):
        reasons = []
        if reading.status != "ok" or reading.value is None:
            reasons.append(reading.status)
        if reading.mode != mode:
            reasons.append(f"mode mismatch: expected {mode}, got {reading.mode}")
        if reading.unit != unit:
            reasons.append(f"unit mismatch: expected {unit}, got {reading.unit}")
        reasons.extend(flag for flag in UNUSABLE_FLAGS if reading.flags.get(flag))
        if reasons:
            issues.append({"sample": i, "reasons": reasons})
        elif not low <= reading.value <= high:
            failures.append(i)
    sources = sorted({r.source for r in readings})
    if len(sources) != 1:
        issues.append({"sample": None, "reasons": ["mixed measurement sources"]})
    stats = None
    unstable = False
    if not issues:
        values = [r.value for r in readings]
        spread = max(values) - min(values)
        stats = {
            "min": float(min(values)),
            "max": float(max(values)),
            "mean": float(sum(values) / len(values)),
            "span": float(spread),
            "unit": unit,
        }
        unstable = span_limit is not None and spread > span_limit
    verdict = "invalid" if issues else "fail" if failures or unstable else "pass"
    return {
        "verdict": verdict,
        "passed": verdict == "pass",
        "sources": sources,
        "sample_count": len(readings),
        "criteria": {
            "mode": mode,
            "unit": unit,
            "minimum": float(low),
            "maximum": float(high),
            "max_span": float(span_limit) if span_limit is not None else None,
        },
        "statistics": stats,
        "invalid_samples": issues,
        "out_of_limits_samples": failures,
        "unstable": unstable,
        "hv_warning": any(r.flags["hv_warning"] for r in readings),
    }
