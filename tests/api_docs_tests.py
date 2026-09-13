"""The API docs name everything the API has, and this keeps them so.

Every tool the MCP server offers has a row in the table in docs/api/mcp.md;
every function banjo.h declares is named in docs/api/c-api.md, and is reached by
the Python binding. The docs are how anything outside this repository learns
what the engine can do, and a call that is not in them is, to a reader, a call
that does not exist. Found this way: banjo_version_string and the three
banjo_delay* calls were in the header and in no doc.

No engine is run: this is about what is written down.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))

import room_world   # noqa: E402,F401  (puts mcp/ on the path)
import banjo_mcp    # noqa: E402

DOCS = ROOT / "docs" / "api"


def declared() -> list[str]:
    """Every function banjo.h declares."""
    header = (ROOT / "include" / "banjo" / "banjo.h").read_text(encoding="utf-8")
    return sorted(set(re.findall(r"\b(banjo_[a-z0-9_]+)\s*\(", header)))


def tabled_tools() -> set[str]:
    """Every tool named in the first column of the table under "The tools" -- a
    row may name two or three (`hinge` / `slide`)."""
    text = (DOCS / "mcp.md").read_text(encoding="utf-8")
    table = text.split("## The tools", 1)[1].split("\n## ", 1)[0]
    names: set[str] = set()
    for first in re.findall(r"^\|([^|\n]+)\|", table, re.M):
        names.update(re.findall(r"`([a-z_]+)`", first))
    return names


def named_in(text: str, name: str) -> bool:
    return re.search(rf"\b{re.escape(name)}\b", text) is not None


class TheDocsNameEverything(unittest.TestCase):
    def test_every_mcp_tool_has_a_row(self):
        offered = {tool["name"] for tool in banjo_mcp.TOOLS}
        missing = sorted(offered - tabled_tools())
        self.assertFalse(missing, f"the MCP offers these and the table in docs/api/mcp.md "
                                  f"does not name them: {missing}")

    def test_the_table_names_no_tool_the_mcp_lacks(self):
        offered = {tool["name"] for tool in banjo_mcp.TOOLS}
        extra = sorted(tabled_tools() - offered)
        self.assertFalse(extra, f"the table in docs/api/mcp.md names tools the MCP does not "
                                f"have: {extra}")

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


if __name__ == "__main__":
    unittest.main()
