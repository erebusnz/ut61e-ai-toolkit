"""Local stdio MCP server. Never print diagnostics to protocol stdout."""

import argparse
import threading
from typing import Annotated, Any, Literal

from .errors import DMMError
from .protocol import CHECK_MODES
from .service import check_measurements, open_meter, read_measurements
from .transport import list_devices


def create_server(replay: str | None = None):
    try:
        from anyio import to_thread
        from mcp.server.fastmcp import FastMCP
        from mcp.types import ToolAnnotations
        from pydantic import Field
    except ImportError as exc:
        raise RuntimeError('Install the MCP extra: pip install -e ".[usb,mcp]"') from exc

    server = FastMCP(
        "ut61e",
        instructions=(
            "Read a UNI-T UT61E+ through its CP2110 or CH9329 USB bridge. The user sets the dial, "
            "leads, and circuit. Values and limits use base units V, A, ohm, F, Hz, %. "
            "Check ok indicates execution, passed/verdict indicate the measurement result. "
            "Replay results are offline evidence and never establish a live circuit's state."
        ),
    )
    lock = threading.Lock()
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False)

    async def invoke(action):
        if not lock.acquire(blocking=False):
            return {
                "ok": False,
                "error": {"code": "busy", "message": "Another DMM call is running"},
            }
        try:
            # Keep stdio/pings responsive during HID reads. Retain the lock until
            # the worker exits, even if the client cancels a bounded acquisition.
            return await to_thread.run_sync(action)
        except (DMMError, ValueError, OSError) as exc:
            return {
                "ok": False,
                "error": {"code": getattr(exc, "code", "invalid_input"), "message": str(exc)},
            }
        finally:
            lock.release()

    @server.tool(annotations=annotations, structured_output=True)
    async def dmm_list_devices() -> dict[str, Any]:
        """List USB bridge candidates. Multiple candidates require a serial or path_hex selector."""
        if replay is not None:
            return {"ok": True, "source": "replay", "devices": [], "replay_file": replay}
        return await invoke(lambda: {"ok": True, "devices": list_devices()})

    @server.tool(annotations=annotations, structured_output=True)
    async def dmm_identify(
        serial: str | None = None,
        path_hex: str | None = None,
        timeout: Annotated[float, Field(ge=0.05, le=30)] = 3.0,
    ) -> dict[str, Any]:
        """Read model identity; refuse devices other than UT61E+. Does not change meter mode."""

        def identify():
            with open_meter(
                serial=serial, path_hex=path_hex, replay=replay, timeout=timeout
            ) as meter:
                return {"ok": True, "identity": meter.identity}

        return await invoke(identify)

    @server.tool(annotations=annotations, structured_output=True)
    async def dmm_read(
        count: Annotated[int, Field(ge=1, le=100)] = 1,
        interval: Annotated[float, Field(ge=0, le=10)] = 0.5,
        timeout: Annotated[float, Field(ge=0.05, le=30)] = 3.0,
        total_timeout: Annotated[float, Field(ge=0.05, le=60)] = 60.0,
        serial: str | None = None,
        path_hex: str | None = None,
    ) -> dict[str, Any]:
        """Read bounded samples with base units, mode, flags and raw frames. Never simulates USB."""
        return await invoke(
            lambda: read_measurements(
                count=count,
                interval=interval,
                timeout=timeout,
                total_timeout=total_timeout,
                serial=serial,
                path_hex=path_hex,
                replay=replay,
            )
        )

    @server.tool(annotations=annotations, structured_output=True)
    async def dmm_check(
        mode: Annotated[str, Field(json_schema_extra={"enum": list(CHECK_MODES)})],
        unit: Literal["V", "A", "ohm", "F", "Hz", "%"],
        minimum: Annotated[float, Field(allow_inf_nan=False)],
        maximum: Annotated[float, Field(allow_inf_nan=False)],
        max_span: float | None = None,
        count: Annotated[int, Field(ge=1, le=100)] = 5,
        interval: Annotated[float, Field(ge=0, le=10)] = 0.5,
        timeout: Annotated[float, Field(ge=0.05, le=30)] = 3.0,
        total_timeout: Annotated[float, Field(ge=0.05, le=60)] = 60.0,
        serial: str | None = None,
        path_hex: str | None = None,
    ) -> dict[str, Any]:
        """Check every sample against inclusive base-unit limits and an exact mode (e.g. DCV/V,
        DCmV/V, OHM/ohm, CONT/ohm, DIODE/V, CAP/F, Hz/Hz, DCmA/A). Optional max_span
        bounds sample max-minus-min. HOLD, REL, MIN/MAX, peak, low battery, overload,
        unknown modes or mismatches make the verdict invalid. Inspect verdict and sources.
        """
        return await invoke(
            lambda: check_measurements(
                mode=mode,
                unit=unit,
                minimum=minimum,
                maximum=maximum,
                max_span=max_span,
                count=count,
                interval=interval,
                timeout=timeout,
                total_timeout=total_timeout,
                serial=serial,
                path_hex=path_hex,
                replay=replay,
            )
        )

    return server


def main():
    parser = argparse.ArgumentParser(description="UT61E+ stdio MCP server")
    parser.add_argument("--replay", help="Explicit offline replay file; never touches USB")
    args = parser.parse_args()
    create_server(replay=args.replay).run(transport="stdio")


if __name__ == "__main__":
    main()
