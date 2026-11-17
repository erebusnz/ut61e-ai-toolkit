# Agent integration

Use either the shell interface or the stdio MCP server. Both return the same
measurement fields and use the same check implementation. No API keys or
network service are required.

## Skills

The canonical repository skill is `.agents/skills/ut61e-dmm/SKILL.md`.
The `.claude/skills/ut61e-dmm/SKILL.md` entrypoint routes to it for Claude.
Both are repository-scoped. The skill assumes the toolkit has been installed
in the interpreter used by the agent, or that `scripts/dmm.py` is invoked from
this repository. It does not install dependencies or change global agent settings.

## MCP setup

Install `.[usb,mcp]`. Configure the client to launch the **absolute path to
this environment's Python**, passing `-m ut61e_toolkit.mcp_server`. An editable
installation makes this independent of the client's working directory.

For a client using the `mcpServers` JSON format (for example Claude Desktop):

```json
{
  "mcpServers": {
    "ut61e": {
      "command": "C:/absolute/path/ut61e-ai-toolkit/.venv/Scripts/python.exe",
      "args": ["-m", "ut61e_toolkit.mcp_server"]
    }
  }
}
```

See the [MCP local server guide](https://modelcontextprotocol.io/docs/develop/connect-local-servers)
for client configuration details.

For a Codex MCP configuration using TOML:

```toml
[mcp_servers.ut61e]
command = "C:/absolute/path/ut61e-ai-toolkit/.venv/Scripts/python.exe"
args = ["-m", "ut61e_toolkit.mcp_server"]
tool_timeout_sec = 75
```

See the [Codex MCP configuration reference](https://developers.openai.com/codex/mcp/)
for the configuration location and supported settings.

These are examples to merge into the client's configuration, not files that
overwrite existing settings. Adjust paths for the machine. On Linux/macOS the
interpreter is `.venv/bin/python`. For offline development, append `--replay`
and an absolute JSONL path to the args. The server will explicitly identify
that source as replay and will not enumerate USB.

| Tool | Purpose |
| --- | --- |
| `dmm_list_devices` | Enumerate bridge candidates without configuring a meter |
| `dmm_identify` | Query and validate model identity |
| `dmm_read` | Acquire 1..100 readings with mode, flags, base units, and raw data |
| `dmm_check` | Acquire samples and evaluate explicit mode, unit, bounds and optional span |

MCP calls have a maximum acquisition budget of 60 seconds. For longer captures,
use the CLI with an explicit `--total-timeout` (maximum 3600 seconds). The
`dmm_read` response can be saved by the host; logging directly to disk is a CLI
operation. The server only uses stdout for MCP messages.

The generated `tools/ut61e.tools.json` describes the runtime tools in MCP
format. For a custom model host, its `inputSchema` is the function's argument
schema. Dispatch validated arguments to the MCP tool of the same name, rather
than interpolating model-generated arguments into shell strings.

## Example request and result interpretation

> Use the UT61E+ to check whether this 3.3 V rail stays between 3.2 and 3.4 V
> for five readings. The probes are already connected and the dial is on DC V.

After identifying the device, call `dmm_check` with `mode="DCV"`, `unit="V"`,
`minimum=3.2`, `maximum=3.4`, `count=5`. Include `max_span` only if the user has
specified a stability limit or agreed to one. Check `ok`, then `verdict`, then
`sources`. Report the observed range and sample count; do not call a replay
result a live measurement. An error or invalid sample is not a failed circuit
and is never a pass.

