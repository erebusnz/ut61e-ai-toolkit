import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ut61e_toolkit.cli import main
from ut61e_toolkit.service import check_measurements, validate_acquisition


def invoke(capsys, *args):
    code = main(list(args))
    captured = capsys.readouterr()
    assert not captured.err
    return code, json.loads(captured.out)


def test_cli_pass_fail_invalid_and_errors(capsys, replay_file):
    args = [
        "check",
        "--replay",
        str(replay_file),
        "--interval",
        "0",
        "--mode",
        "DCV",
        "--unit",
        "V",
        "--min",
        "3.2",
        "--max",
    ]
    code, result = invoke(capsys, *args, "3.4")
    assert code == 0 and result["verdict"] == "pass"
    assert result["sources"] == ["replay"]
    code, result = invoke(capsys, *args, "3.25")
    assert code == 1 and result["verdict"] == "fail"
    code, result = invoke(capsys, *args, "3.4", "--mode", "ACV")
    assert code == 2 and result["verdict"] == "invalid"
    code, result = invoke(capsys, *args, "NaN")
    assert code == 2 and not result["ok"]
    code, result = invoke(capsys, "read", "--unknown")
    assert code == 2 and not result["ok"]


def test_log_round_trip_and_no_overwrite(capsys, replay_file, tmp_path):
    path = tmp_path / "capture.jsonl"
    code, result = invoke(
        capsys,
        "log",
        "--replay",
        str(replay_file),
        "--count",
        "5",
        "--interval",
        "0",
        "--output",
        str(path),
    )
    assert code == 0 and result["samples_written"] == 5
    original = path.read_bytes()
    code, result = invoke(capsys, "read", "--replay", str(path), "--count", "5", "--interval", "0")
    assert code == 0 and len(result["readings"]) == 5
    code, result = invoke(capsys, "log", "--replay", str(replay_file), "--output", str(path))
    assert code == 2 and not result["ok"]
    assert path.read_bytes() == original


def test_csv_and_partial_capture(capsys, replay_file, tmp_path):
    path = tmp_path / "capture.csv"
    code, _ = invoke(
        capsys, "log", "--replay", str(replay_file), "--output", str(path), "--format", "csv"
    )
    assert code == 0
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1 and rows[0]["source"] == "replay"
    assert rows[0]["unit"] == "V"
    partial = tmp_path / "partial.jsonl"
    code, result = invoke(
        capsys,
        "log",
        "--replay",
        str(replay_file),
        "--output",
        str(partial),
        "--count",
        "6",
        "--interval",
        "0",
    )
    assert code == 2 and result["error"]["code"] == "replay_error"
    assert len(partial.read_text().splitlines()) == 5


@pytest.mark.parametrize(
    "kwargs",
    [
        {"count": 0},
        {"count": True},
        {"count": 1.5},
        {"interval": float("nan")},
        {"timeout": 0},
        {"interval": -1},
        {"total_timeout": float("inf")},
        {"count": 100, "interval": 1, "total_timeout": 30},
    ],
)
def test_invalid_acquisition_parameters(kwargs):
    with pytest.raises(ValueError):
        validate_acquisition(**kwargs)


def test_bad_check_fails_before_connecting():
    with pytest.raises(ValueError):
        check_measurements(mode="DCV", unit="V", minimum=3, maximum=4, max_span=0.1, count=1)


def test_module_and_script_entrypoints(replay_file):
    root = Path(__file__).resolve().parents[1]
    for command in (
        [sys.executable, "-m", "ut61e_toolkit"],
        [sys.executable, str(root / "scripts" / "dmm.py")],
    ):
        result = subprocess.run(
            command + ["read", "--replay", str(replay_file)],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=root,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["readings"][0]["source"] == "replay"
