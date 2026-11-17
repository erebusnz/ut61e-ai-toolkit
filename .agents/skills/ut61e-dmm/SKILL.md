---
name: ut61e-dmm
description: Read a UNI-T UT61E+ over a CP2110 or CH9329 USB cable, capture samples, and check electrical measurements against explicit limits using the UT61E+ Python toolkit or MCP tools. Use for UT61E+ bench measurements and capture replay; not the older UT61E serial protocol.
---

Use the installed `ut61e` command, `python -m ut61e_toolkit`, or the `dmm_*` MCP
tools. From the repository, `python scripts/dmm.py` is also available. Consult
`--help` for options; use the environment where the toolkit is installed.

1. Establish the intended measurement mode, physical test points, and limits.
   Use existing user context; ask only for missing setup details. The user
   handles probes, dial position, and circuit preparation. Resistance,
   continuity, capacitance, and diode checks require an unpowered circuit with
   capacitors discharged. Current measurement needs the correct fused input
   and series connection. Do not infer safe-to-touch or absence of voltage
   from this software's output.
2. Discover with `devices` / `dmm_list_devices`, then `info` / `dmm_identify`.
   If multiple bridges match, select the intended serial or exact path_hex.
   Both CP2110 and CH9329 cables are detected automatically. A USB bridge ID
   by itself does not establish meter identity.
3. Read using `read --count 1` / `dmm_read`. Inspect mode, unit, status, flags,
   and source before evaluating the circuit. The toolkit does not change the
   dial, range, HOLD, or REL. Resolve setup mismatches with the user.
4. For a limits check, supply an exact mode, base unit, inclusive min/max, and
   a bounded sample count. Use agreed tolerances; do not invent a pass criterion.
   Values are normalized to V, A, ohm, F, Hz, or %. For example DCmV still uses
   V limits, and 1 k-ohm is 1000 ohm. `max_span` bounds max-minus-min across at
   least two samples; it is not a measurement-accuracy specification.
5. Interpret `ok` as execution success. Report `verdict`/`passed`, source,
   observed min/max, unit, sample count, and any HV warning. `invalid` means
   insufficient trustworthy context, not a circuit failure. HOLD, REL,
   MIN/MAX, peak, low battery, overload, and unknown modes/ranges cannot pass.

Example for an already prepared 3.3 V DC rail:

```sh
python -m ut61e_toolkit check --mode DCV --unit V --min 3.2 --max 3.4 --count 5
```

Commands return JSON; exit codes are 0 for success/pass, 1 for a valid failed
check, 2 for error/invalid, and 130 for interruption. Stop after a connection
or protocol error and diagnose its cause; do not silently retry indefinitely.
Do not substitute replay after a live acquisition fails.

Capture with `log --count N --output capture.jsonl`; existing files are refused
and a failed capture can contain partial samples. Use `--replay capture.jsonl`
only when offline analysis is intended. Replay always reports `source=replay`,
starts at the first record on each call, and never establishes live circuit
state. `timestamp` is host receive/decode time; `recorded_at` preserves capture
time during replay. No reading proves that probes contact the intended node.

For setup, Python use, and MCP configuration read the repository README and
`docs/agents.md`. For USB failures read `docs/troubleshooting.md`; for changing
decoding read `docs/protocol.md`. Do not apply the older UT61E serial decoder.

