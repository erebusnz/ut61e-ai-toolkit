import asyncio
import json
import sys
from pathlib import Path

import pytest

mcp = pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from ut61e_toolkit.mcp_server import create_server  # noqa: E402


def test_stdio_tools_and_check(replay_file):
    async def exercise():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "ut61e_toolkit.mcp_server", "--replay", str(replay_file)],
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                listing = await session.list_tools()
                assert {t.name for t in listing.tools} == {
                    "dmm_list_devices",
                    "dmm_identify",
                    "dmm_read",
                    "dmm_check",
                }
                result = await session.call_tool(
                    "dmm_check",
                    {
                        "mode": "DCV",
                        "unit": "V",
                        "minimum": 3.2,
                        "maximum": 3.4,
                        "count": 5,
                        "interval": 0,
                        "max_span": 0.01,
                    },
                )
                assert not result.isError
                data = result.structuredContent
                assert data["verdict"] == "pass"
                assert data["sources"] == ["replay"]
                bad = await session.call_tool("dmm_read", {"count": 0})
                assert bad.isError
                exhausted = await session.call_tool("dmm_read", {"count": 6, "interval": 0})
                assert exhausted.structuredContent["ok"] is False
                assert exhausted.structuredContent["error"]["code"] == "replay_error"

    async def bounded():
        await asyncio.wait_for(exercise(), timeout=20)

    asyncio.run(bounded())


def test_published_tool_definitions_match_runtime():
    actual = asyncio.run(create_server().list_tools())
    path = Path(__file__).resolve().parents[1] / "tools" / "ut61e.tools.json"
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert [tool.model_dump(exclude_none=True) for tool in actual] == expected
