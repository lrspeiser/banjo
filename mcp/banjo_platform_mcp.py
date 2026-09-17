#!/usr/bin/env python3
"""Banjo platform MCP: world physics plus the complete Workshop/Product surface.

This wrapper extends the mature ``banjo_mcp.py`` server rather than forking it.
All existing world tools stay owned by that module; Workshop tools are adapters
over ``mcp.workshop_platform`` and therefore reach the same Workshop API
functions as the browser.

Install this server when you want the whole Banjo platform::

    claude mcp add banjo -- python /path/to/banjo/mcp/banjo_platform_mcp.py

``BANJO_LIBRARY`` points at the C library as before. Engine-backed Workshop tests
(cart roll, kettle heat, machine control and declared static load) additionally
use ``BANJO_LIVE_ENGINE`` pointing at ``banjo_live_world_run``. Pure Workshop
design, ProductGraph, PhysicsContract, force-probe and library tools work without
that executable.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "mcp") not in sys.path:
    sys.path.insert(0, str(ROOT / "mcp"))

import banjo_mcp as core  # noqa: E402
from mcp import workshop_mcp_tools  # noqa: E402


def _model_error(handler: Callable[[dict[str, Any]], dict[str, Any]]):
    """Turn correctable Workshop validation errors into normal MCP refusals."""
    def wrapped(arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            return handler(arguments)
        except core.Refused:
            raise
        except (ValueError, KeyError, TypeError) as problem:
            raise core.Refused(str(problem)) from None
    return wrapped


# banjo_mcp.handle reads these globals from the imported core module, so
# extending them in place makes tools/list and tools/call one protocol surface.
existing = {tool["name"] for tool in core.TOOLS}
core.TOOLS = list(core.TOOLS) + [tool for tool in workshop_mcp_tools.TOOLS
                                 if tool["name"] not in existing]
for name, handler in workshop_mcp_tools.HANDLERS.items():
    core.HANDLERS[name] = _model_error(handler)

core.SERVER = {"name": "banjo-platform", "version": "1.1.0"}

TOOLS = core.TOOLS
HANDLERS = core.HANDLERS
handle = core.handle
serve = core.serve


def main() -> int:
    return core.main()


if __name__ == "__main__":
    raise SystemExit(main())
