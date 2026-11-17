# UT61E+ AI toolkit

Python commands and local MCP tools for reading a **UNI-T UT61E+** and checking
measurements against explicit limits. Includes a Codex/Claude skill, raw-frame
replay, JSONL/CSV logging, and tests that run without a meter.

This implementation supports **CP2110 (10c4:ea80)** and **WCH CH9329
(1a86:e429)** USB cables, detected automatically. The older UT61E serial
protocol, Bluetooth adapters, and other meter models are not supported.
The user selects the dial, connects the leads, and prepares the
circuit. Software reads the display; it does not establish that the probes are
on the intended nodes.

## Install

Python 3.11 or newer. From this repository on Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[usb,mcp,dev]"
.\.venv\Scripts\python.exe -m ut61e_toolkit devices
```

On Linux/macOS use `.venv/bin/python` in place of `.venv\Scripts\python.exe`.
Use `pip install -e .` for dependency-free replay/CLI use; `.[usb]` adds USB;
`.[usb,mcp]` adds the MCP server. The console command `ut61e` is available when
the environment is activated. `python scripts/dmm.py` also works without an
editable install (USB still requires `hidapi`).

Windows uses the standard HID driver: this bridge is not a COM port. Linux may
need a HID library and permission to access its hidraw device; see
[troubleshooting](docs/troubleshooting.md). Install the package named **hidapi**,
which imports as `hid`, rather than the unrelated package named `hid`.

## Read and check

Examples below assume the environment is activated. Turn on the meter and
enable its USB communication mode as described in its manual. Close other
software using the meter.

```powershell
ut61e devices
ut61e info
ut61e read --count 3 --interval 0.5
ut61e check --mode DCV --unit V --min 3.135 --max 3.465 --count 5 --max-span 0.02
ut61e check --mode OHM --unit ohm --min 950 --max 1050 --count 5
ut61e check --mode CONT --unit ohm --min 0 --max 2 --count 3
ut61e log --count 60 --interval 0.5 --output bench.jsonl
ut61e log --count 60 --interval 0.5 --output bench.csv --format csv
```

The examples describe different physical setups; set the meter and probes for
each one. Resistance, continuity, diode, and capacitance checks require a
de-energized circuit and discharged capacitors. Current measurements require
the correct fused input and a series connection. Never infer a safe circuit or
absence of voltage from an overload, timeout, or NCV indication.

Every normal command writes one JSON object to stdout. `--help` and `--version`
are human-readable. The limits are **inclusive, in base units**: V, A, ohm, F,
Hz, or %. For example, a displayed `53.54 mV` has `value: 0.05354, unit: "V"`;
220 nF is `0.00000022 F`. The display value and unit are retained separately.
Mode names are exact: `DCV` and `DCmV` both use V limits, but different mode
criteria. Run `ut61e check --help` for supported modes.

| Result | Meaning | Exit code |
| --- | --- | --- |
| `verdict: "pass"` | Every usable sample meets the limits and optional span | 0 |
| `verdict: "fail"` | A valid sample exceeds a limit, or the span is too large | 1 |
| `verdict: "invalid"` | Wrong mode/unit, overload, stored/relative reading, low battery, or unsupported data | 2 |
| `ok: false` | Input, connection, protocol, file, or timeout error | 2 |
| Interrupted | User cancelled acquisition | 130 |

`ok: true` means the command completed, **not** that a check passed. Inspect
`verdict`/`passed`. HOLD, REL, MIN/MAX, peak, and low-battery readings cannot pass
a check. HV warnings are reported, not hidden. Unknown modes/ranges have no
numeric value. NCV and hFE quantitative checks and combined AC+DC checks are
intentionally unsupported. A limits check is not an accuracy calibration;
criteria should account for the meter specification and the test setup.

Each request has `--timeout` (default 3 s); acquisition has `--total-timeout`
(default 60 s). `--interval` is an additional delay after a response. There are
no automatic request retries or simulated fallbacks. Multiple detected bridges
require `--serial` or the exact `--path-hex` returned by `devices`. Identity is
queried before measurements; a shared USB bridge ID alone does not identify a
UT61E+. Toolkit processes use an OS lock to prevent concurrent access.

## Try it without hardware

```powershell
python -m ut61e_toolkit read --replay examples/dc_3v3.jsonl --count 3 --interval 0
python -m ut61e_toolkit check --replay examples/dc_3v3.jsonl --mode DCV --unit V --min 3.2 --max 3.4 --count 5 --interval 0 --max-span 0.01
```

The example is **synthetic test data**. Replay is always marked `source: "replay"`
and cannot establish the state of a live circuit. Each invocation starts at the
beginning of the file; EOF is an error, not a loop. JSONL captures contain
`raw_hex` and timestamps and can be replayed with the same option. Replay
revalidates checksums and decodes raw bytes instead of trusting saved numeric
values. `timestamp` is when the replay record was decoded; `recorded_at` retains
the capture timestamp. This is sequential replay, not a timing simulation.

Log files are created exclusively: existing files are never overwritten.
Samples are flushed as they arrive, so a failed log may contain partial data.
Only JSONL is replayable; CSV is intended for analysis.

## Codex and Claude

The repository includes the [UT61E+ skill](.agents/skills/ut61e-dmm/SKILL.md),
a Claude skill entrypoint, and [MCP setup examples](docs/agents.md). The MCP
server exposes `dmm_list_devices`, `dmm_identify`, `dmm_read`, and `dmm_check`.
It runs locally over stdio and shares the same implementation as the CLI.

```powershell
python -m ut61e_toolkit.mcp_server
# Offline integration development:
python -m ut61e_toolkit.mcp_server --replay examples/dc_3v3.jsonl
```

[tools/ut61e.tools.json](tools/ut61e.tools.json) contains generated MCP tool
definitions for custom hosts. Regenerate with `python scripts/export_tool_definitions.py`.
The server's runtime schemas are authoritative.

## Python API and development

```python
from ut61e_toolkit.service import check_measurements, read_measurements

reading = read_measurements(count=1)
result = check_measurements(
    mode="DCV",
    unit="V",
    minimum="3.2",
    maximum="3.4",
    count=5,
    interval=0.5,
    max_span="0.01",
)
print(result["verdict"])
```

```powershell
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

Tests cover wire framing, unit scaling, flags, invalid checks, mock USB traffic,
CLI capture/replay, and an actual stdio MCP client/server exchange. Hardware
validation is separate: [hardware checklist](docs/troubleshooting.md#hardware-validation).
Read [protocol notes and references](docs/protocol.md) before changing the
decoder. The two user-supplied references are
[prickle/UT61E-Multimeter](https://github.com/prickle/UT61E-Multimeter) (older UT61E)
and [ljakob/unit_ut61eplus](https://github.com/ljakob/unit_ut61eplus) (UT61E+).

