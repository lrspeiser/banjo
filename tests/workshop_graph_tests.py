"""Explicit component graph derived from Workshop's authoritative geometry."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp.workshop import assemble  # noqa: E402
from mcp import workshop_graph  # noqa: E402


class ComponentRelationships(unittest.TestCase):
    def test_table_nodes_have_interfaces_and_legs_contact_the_top(self):
        design = assemble("table", design_id="t")
        graph = workshop_graph.graph(design)
        self.assertEqual(len(design.parts), len(graph["nodes"]))
        leg = next(n for n in graph["nodes"] if n["id"] == "leg-1")
        self.assertIn("end-a", {i["name"] for i in leg["interfaces"]})
        self.assertIn("top", workshop_graph.contacts_of(graph, "leg-1"))

    def test_cart_graph_finds_wheel_axle_contact_without_an_llm_coordinate_guess(self):
        design = assemble("cart", design_id="c")
        graph = workshop_graph.graph(design)
        wheel = next(n for n in graph["nodes"] if n["role"] == "wheel")
        self.assertIn("hub", {i["name"] for i in wheel["interfaces"]})
        touching = workshop_graph.contacts_of(graph, wheel["id"])
        self.assertTrue(any(name.startswith("axle-") for name in touching), (wheel, touching))

    def test_relationships_are_symmetric_to_query(self):
        graph = workshop_graph.graph(assemble("chair", design_id="chair"))
        for relation in graph["relationships"]:
            a, b = relation["a"], relation["b"]
            self.assertIn(b, workshop_graph.contacts_of(graph, a))
            self.assertIn(a, workshop_graph.contacts_of(graph, b))


if __name__ == "__main__":
    unittest.main()
