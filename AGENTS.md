# Repository guidance

This is the UNI-T **UT61E+** CP2110/CH9329 USB toolkit, not the older UT61E serial model.
Use `.agents/skills/ut61e-dmm/SKILL.md` for measurement tasks. CLI stdout is a
machine-readable contract; keep diagnostics off MCP stdout. Replay must remain
explicit and visibly labeled, and checks must never pass unusable readings.

Protocol changes need meaningful framing/scaling/flags regression tests. Run
`python -m pytest` and `python -m ruff check .` in the project's environment.
Update the generated tool definitions after changing MCP signatures with
`python scripts/export_tool_definitions.py`. No real hardware is needed for tests.
Document hardware verification separately from tests or simulation.

