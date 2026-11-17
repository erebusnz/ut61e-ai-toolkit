"""Machine-readable command line interface; stdout is JSON except --help and CSV files."""

import argparse
import csv
import json
import sys

from . import __version__
from .errors import DMMError
from .protocol import CHECK_MODES
from .service import (
    check_measurements,
    collect,
    open_meter,
    read_measurements,
    validate_acquisition,
)
from .transport import list_devices


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def emit(value):
    print(json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")))


def build_parser():
    parser = Parser(description="UT61E+ USB measurements and limits checks (JSON output)")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("devices", help="List supported USB bridge candidates without opening them")
    for name in ("info", "read", "check", "log"):
        sub = commands.add_parser(name)
        sub.add_argument("--serial", help="Exact USB serial number")
        sub.add_argument("--path-hex", help="Exact hexadecimal HID path returned by devices")
        sub.add_argument(
            "--replay", help="Read capture JSONL instead of USB; always labeled replay"
        )
        sub.add_argument(
            "--timeout", type=float, default=3.0, help="Per-request seconds (default 3)"
        )
        if name == "info":
            continue
        sub.add_argument("--count", type=int, default=5 if name == "check" else 1)
        sub.add_argument("--interval", type=float, default=0.5, help="Seconds between responses")
        sub.add_argument(
            "--total-timeout", type=float, default=60.0, help="Whole acquisition seconds"
        )
        if name == "check":
            sub.add_argument("--mode", required=True, choices=CHECK_MODES)
            sub.add_argument("--unit", required=True, choices=("V", "A", "ohm", "F", "Hz", "%"))
            sub.add_argument(
                "--min", dest="minimum", required=True, help="Inclusive base-unit limit"
            )
            sub.add_argument(
                "--max", dest="maximum", required=True, help="Inclusive base-unit limit"
            )
            sub.add_argument(
                "--max-span", help="Optional maximum sample max-minus-min in base units"
            )
        if name == "log":
            sub.add_argument(
                "--output", required=True, help="New output file (existing files refused)"
            )
            sub.add_argument("--format", choices=("jsonl", "csv"), default="jsonl")
    return parser


def log_measurements(*, output, format, **kwargs):
    validate_acquisition(
        kwargs["count"], kwargs["interval"], kwargs["timeout"], kwargs["total_timeout"]
    )
    # Exclusive creation avoids overwriting an earlier capture, including the input replay.
    with open(output, "x", encoding="utf-8", newline="") as handle:
        writer = None
        if format == "csv":
            fields = [
                "timestamp",
                "source",
                "recorded_at",
                "mode",
                "range_index",
                "display",
                "display_unit",
                "value",
                "unit",
                "status",
                "flags",
                "raw_hex",
            ]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()

        def save(reading):
            record = reading.to_dict()
            if writer:
                record["flags"] = json.dumps(record["flags"], sort_keys=True)
                writer.writerow(record)
            else:
                handle.write(json.dumps(record, allow_nan=False) + "\n")
            handle.flush()  # A failed run still leaves its successfully acquired samples.

        identity, readings = collect(**kwargs, on_reading=save)
    return {
        "ok": True,
        "identity": identity,
        "samples_written": len(readings),
        "output": str(output),
        "format": format,
    }


def main(argv=None):
    try:
        args = vars(build_parser().parse_args(argv))
        command = args.pop("command")
        if command == "devices":
            result = {"ok": True, "devices": list_devices()}
        elif command == "info":
            validate_acquisition(timeout=args["timeout"])
            with open_meter(**args) as meter:
                result = {"ok": True, "identity": meter.identity}
        elif command == "read":
            result = read_measurements(**args)
        elif command == "check":
            result = check_measurements(**args)
        else:
            result = log_measurements(**args)
        emit(result)
        return {"pass": 0, "fail": 1, "invalid": 2}.get(result.get("verdict"), 0)
    except (DMMError, ValueError, OSError) as exc:
        emit(
            {
                "ok": False,
                "error": {"code": getattr(exc, "code", "invalid_input"), "message": str(exc)},
            }
        )
        return 2
    except KeyboardInterrupt:
        emit({"ok": False, "error": {"code": "interrupted", "message": "Acquisition interrupted"}})
        return 130


if __name__ == "__main__":
    sys.exit(main())
