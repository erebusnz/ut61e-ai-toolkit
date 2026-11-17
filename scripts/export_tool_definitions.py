"""Export the actual MCP schemas for custom hosts. Requires the mcp extra."""

import asyncio
import json
from pathlib import Path

from ut61e_toolkit.mcp_server import create_server


async def main():
    definitions = await create_server().list_tools()
    target = Path(__file__).resolve().parents[1] / "tools" / "ut61e.tools.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(
        json.dumps([tool.model_dump(exclude_none=True) for tool in definitions], indent=2) + "\n",
        encoding="utf-8",
    )
    print(target)


if __name__ == "__main__":
    asyncio.run(main())
