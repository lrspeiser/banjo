"""The public APIs name everything they expose, and this keeps them so.

The engine C ABI/Python binding, legacy world MCP, unified platform MCP and
Workshop HTTP client all have different adapters but one rule: a capability not
in the public docs is not a public capability. These checks also exercise the
pure Workshop platform path so a documented adapter cannot silently rot.
"""
from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mcp"))
sys.path.insert(0, str(ROOT / "playground"))

import room_world   # noqa: E402,F401  (puts mcp/ on the path for legacy callers)
import banjo_mcp    # noqa: E402

# Capture the legacy world's public surface before importing the platform wrapper,
# which intentionally extends this module's TOOLS/HANDLERS in place.
WORLD_TOOLS = {tool["name"] for tool in banjo_mcp.TOOLS}

from mcp import workshop_mcp_tools, workshop_platform  # noqa: E402
import banjo_platform_mcp  # noqa: E402

DOCS = ROOT / "docs" / "api"


def declared() -> list[str]:
    """Every function banjo.h declares."""
    header = (ROOT / "include" / "banjo" / "banjo.h").read_text(encoding="utf-8")
    return sorted(set(re.findall(r"\b(banjo_[a-z0-9_]+)\s*\(", header)))


def tabled_tools(path: Path, heading: str) -> set[str]:
    """Every backticked tool in the first column of one Markdown tool table."""
    text = path.read_text(encoding="utf-8")
    if heading not in text:
        raise AssertionError(f"{path} has no {heading!r} heading")
    table = text.split(heading, 1)[1].split("\n## ", 1)[0]
    names: set[str] = set()
    for first in re.findall(r"^\|([^|\n]+)\|", table, re.M):
        names.update(re.findall(r"`([a-z_]+)`", first))
    return names


def named_in(text: str, name: str) -> bool:
    return re.search(rf"\b{re.escape(name)}\b", text) is not None


class TheDocsNameEverything(unittest.TestCase):
    def test_machine_versions_and_schema_fields_are_documented(self):
        import banjo
        from circuit_api import CIRCUIT_SCHEMA
        header = (ROOT / "include" / "banjo" / "banjo.h").read_text(encoding="utf-8")
        version = int(re.search(r"#define BANJO_ABI_VERSION (\d+)", header).group(1))
        self.assertEqual(version, banjo.ABI_VERSION)
        doc = (DOCS / "c-api.md").read_text(encoding="utf-8")
        self.assertIn(f"Current ABI: **{version}**", doc)
        reference = (DOCS / "machine-networks.md").read_text(encoding="utf-8")
        self.assertIn(f"**{banjo_platform_mcp.core.SERVER['version']}**", reference)
        def fields(schema):
            for name, child in schema.get("properties", {}).items():
                yield name
                yield from fields(child)
            if "items" in schema:
                yield from fields(schema["items"])
        missing = sorted({field for field in fields(CIRCUIT_SCHEMA) if not named_in(reference, field)})
        self.assertFalse(missing, f"circuit schema fields missing from reference: {missing}")
        names = set(re.findall(r"`(banjo_[a-z0-9_]+)`", reference))
        self.assertFalse(names - set(declared()), f"unknown C API functions: {names-set(declared())}")

    def test_every_world_mcp_tool_has_exactly_one_documented_surface(self):
        documented = tabled_tools(DOCS / "mcp.md", "## The tools")
        self.assertEqual(WORLD_TOOLS, documented,
                         f"world MCP/docs drift: missing={sorted(WORLD_TOOLS-documented)}, "
                         f"extra={sorted(documented-WORLD_TOOLS)}")

    def test_every_workshop_mcp_tool_is_documented(self):
        offered = {tool["name"] for tool in workshop_mcp_tools.TOOLS}
        documented = tabled_tools(DOCS / "workshop.md", "## MCP tools")
        self.assertEqual(offered, documented,
                         f"Workshop MCP/docs drift: missing={sorted(offered-documented)}, "
                         f"extra={sorted(documented-offered)}")

    def test_platform_mcp_is_world_plus_workshop_without_name_collisions(self):
        workshop = {tool["name"] for tool in workshop_mcp_tools.TOOLS}
        self.assertFalse(WORLD_TOOLS & workshop)
        unified = {tool["name"] for tool in banjo_platform_mcp.TOOLS}
        self.assertEqual(WORLD_TOOLS | workshop, unified)
        self.assertEqual(unified, set(banjo_platform_mcp.HANDLERS))

    def test_every_c_function_is_in_the_c_api_doc(self):
        doc = (DOCS / "c-api.md").read_text(encoding="utf-8")
        missing = [name for name in declared() if not named_in(doc, name)]
        self.assertFalse(missing, f"declared in banjo.h and named nowhere in "
                                  f"docs/api/c-api.md: {missing}")

    def test_every_c_function_is_reached_by_the_python_binding(self):
        binding = (ROOT / "bindings" / "python" / "banjo.py").read_text(encoding="utf-8")
        missing = [name for name in declared() if not named_in(binding, name)]
        self.assertFalse(missing, f"declared in banjo.h and not reached by "
                                  f"bindings/python/banjo.py: {missing}")

    def test_workshop_sim_uses_only_documented_platform_routes(self):
        source = (ROOT / "playground" / "workshop.js").read_text(encoding="utf-8")
        called = set(re.findall(r'api\("(/api/workshop/[a-z-]+)"', source))
        public = set(workshop_platform.HTTP.values())
        self.assertTrue(called, "Workshop browser no longer appears to use its HTTP API")
        self.assertFalse(called - public,
                         f"Workshop browser calls routes outside the platform contract: {sorted(called-public)}")
        doc = (DOCS / "workshop.md").read_text(encoding="utf-8")
        missing = sorted(route for route in public if route not in doc)
        self.assertFalse(missing, f"Workshop platform routes missing from docs: {missing}")

    def test_product_platform_compiles_workshop_design_through_public_facade(self):
        answer = workshop_platform.engineer(
            "inspect_product", {"kind": "table", "design_id": "api-doc-parity", "parameters": {}})
        self.assertEqual("banjo.product-graph.v1", answer["product_graph"]["schema"])
        self.assertEqual("banjo.physics-contract.v1", answer["physics_contract"]["schema"])
        self.assertEqual("banjo.workshop-platform.v1", answer["schema"])

    def test_workshop_mcp_uses_same_open_inspect_and_library_surface(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            original = workshop_mcp_tools.APP
            workshop_mcp_tools.APP = SimpleNamespace(
                runs_path=root / "runs", workshop_store=root / "store", workshop_db=root / "banjo.db",
                workshop_owner_id="api-test", engine_path=None, api_key="", model="gpt-5-mini", live=None)
            workshop_mcp_tools.APP.runs_path.mkdir()
            workshop_mcp_tools.APP.workshop_store.mkdir()
            try:
                opened = workshop_mcp_tools.tool_open({"kind": "table"})
                self.assertTrue(opened["candidates"])
                self.assertEqual("banjo.workshop-platform.v1", opened["platform"]["schema"])
                inspected = workshop_mcp_tools.tool_inspect(
                    {"kind": "table", "design_id": "mcp-table", "parameters": {}})
                self.assertEqual("banjo.product-graph.v1", inspected["product_graph"]["schema"])
                empty = workshop_mcp_tools.tool_library(
                    {"action": "search", "tags": {"physics": ["rotor"]}})
                self.assertEqual([], empty["personal_library"])
            finally:
                workshop_mcp_tools.APP = original


if __name__ == "__main__":
    unittest.main()
