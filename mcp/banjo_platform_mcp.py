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
from mcp import workshop_mcp_tools, material_qa_tools, physics_trial_tools  # noqa: E402


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
for module in (workshop_mcp_tools, material_qa_tools, physics_trial_tools):
    existing = {tool["name"] for tool in core.TOOLS}
    core.TOOLS = list(core.TOOLS) + [tool for tool in module.TOOLS
                                   if tool["name"] not in existing]
    for name, handler in module.HANDLERS.items():
        core.HANDLERS[name] = _model_error(handler)

core.SERVER = {"name": "banjo-platform", "version": "1.7.0"}
_CORE_HANDLE = core.handle


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    """Core protocol plus product-design guidance in the initialize handshake."""
    reply = _CORE_HANDLE(message)
    if message.get("method") == "initialize" and isinstance(reply, dict):
        result = reply.get("result")
        if isinstance(result, dict):
            result["instructions"] = (
                str(result.get("instructions") or "")
                + " For product or component design, do not build trial geometry directly in the live "
                  "world first: call workshop_catalog, open or compose the product with workshop_open, "
                  "inspect ProductGraph/PhysicsContract with workshop_inspect, and use workshop_test "
                  "for isolated evidence. Workshop materialization is a preview and does not mutate a "
                  "live world. Use the ordinary world tools only when the intent is to change or run "
                  "persistent physical reality. For editable mechanics experiments use physics_trial_catalog, "
                  "physics_trial_validate and physics_trial_run: bounded native operations, isolated from the live room. "
                  "Never replace a physical outcome with scripted motion or silently relax a regression check."
            )
    return reply


# core.serve/main look up core.handle at runtime; point that name at the extended
# handshake while keeping every other bit of the mature protocol implementation.
core.handle = handle
TOOLS = core.TOOLS
HANDLERS = core.HANDLERS
serve = core.serve


def main() -> int:
    return core.main()


if __name__ == "__main__":
    raise SystemExit(main())
