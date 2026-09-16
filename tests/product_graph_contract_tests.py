"""ProductGraph/PhysicsContract are generic physical abstractions, not archetype switches."""
from __future__ import annotations

from pathlib import Path
import inspect
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp.product_graph import ProductGraph, component, interface, relationship  # noqa: E402
from mcp.product_contract import compile_contract  # noqa: E402
from mcp.workshop import assemble  # noqa: E402
from mcp import workshop_graph, product_contract  # noqa: E402


def box(component_id: str, role: str, mass: float, center, size, *tags: str):
    return component(component_id, role, material="iron",
                     geometry={"shape": "box", "mass_kg": mass,
                               "center_m": list(center), "size_m": list(size),
                               "rotation_deg": [0, 0, 0]},
                     physics_tags=tags)


class GenericProductGraph(unittest.TestCase):
    def test_workshop_table_becomes_product_graph_with_physics_tags(self):
        product = workshop_graph.product(assemble("table", design_id="table-a"))
        doc = product.described()
        self.assertEqual(doc["schema"], "banjo.product-graph.v1")
        self.assertIn("beam", doc["physics_tags"]["physics"])
        self.assertIn("plate", doc["physics_tags"]["physics"])
        self.assertTrue(any(r["kind"] == "physical-contact" for r in doc["relationships"]))

    def test_contact_does_not_fuse_runtime_bodies(self):
        product = ProductGraph("touching", components=[
            box("a", "surface", 5, (0, 0, 0), (1, .1, 1), "plate", "collision_surface"),
            box("b", "leg", 2, (0, -.55, 0), (.1, 1, .1), "beam", "structural_member"),
        ], relationships=[relationship("r", "physical-contact", "a", "b", derived=True)])
        contract = compile_contract(product)
        self.assertEqual(len(contract["runtime_bodies"]), 2)
        self.assertTrue(contract["reduction_candidates"][0]["requires_validation"])

    def test_declared_fixed_parts_can_collapse_and_mass_is_conserved(self):
        product = ProductGraph("welded", components=[
            box("a", "frame", 5, (0, 0, 0), (1, .1, 1), "structural_member"),
            box("b", "brace", 2, (1, 0, 0), (1, .1, .1), "structural_member"),
        ], relationships=[relationship("weld", "fixed", "a", "b")])
        contract = compile_contract(product)
        self.assertEqual(len(contract["runtime_bodies"]), 1)
        self.assertAlmostEqual(contract["conserved"]["mass_kg"], 7.0)
        self.assertEqual(set(contract["runtime_bodies"][0]["components"]), {"a", "b"})

    def test_synthetic_guillotine_uses_only_generic_slider_and_blade_semantics(self):
        graph = ProductGraph("cutting-rig", components=[
            box("frame", "frame", 60, (0, 1, 0), (1, 2, .5), "structural_member", "collision_member"),
            box("blade", "blade", 12, (0, 1.2, 0), (.7, .5, .03), "blade", "cutter", "collision_surface"),
        ], relationships=[relationship("guide", "slider", "frame", "blade",
                                       properties={"axis": [0, 1, 0], "lower_m": 0, "upper_m": .9})])
        contract = compile_contract(graph)
        self.assertEqual([j["kind"] for j in contract["mechanisms"]], ["slider"])
        self.assertIn("blade", {z["kind"] for z in contract["collision_zones"]})
        self.assertEqual(len(contract["runtime_bodies"]), 2)

    def test_synthetic_merry_go_round_preserves_bearing_energy_and_control(self):
        graph = ProductGraph("rotating-platform", components=[
            box("foundation", "foundation", 800, (0, .1, 0), (2, .2, 2), "structural_base", "collision_surface"),
            box("shaft", "axle", 50, (0, 1, 0), (.2, 2, .2), "shaft", "structural_member"),
            box("platform", "platform", 180, (0, 1.2, 0), (3, .15, 3), "rotor", "collision_surface"),
        ], relationships=[
            relationship("base-shaft", "fixed", "foundation", "shaft"),
            relationship("main-bearing", "bearing", "shaft", "platform",
                         properties={"axis": [0, 1, 0]}),
        ], energy=[{"id": "motor", "kind": "motor", "drives": "main-bearing"}],
           controls=[{"id": "speed", "kind": "drive_setting", "actuator": "motor"}])
        contract = compile_contract(graph)
        self.assertEqual(len(contract["runtime_bodies"]), 2)
        self.assertEqual(contract["mechanisms"][0]["kind"], "bearing")
        self.assertEqual(contract["energy"][0]["kind"], "motor")
        self.assertEqual(contract["controls"][0]["kind"], "drive_setting")
        self.assertGreater(contract["conserved"]["inertia_principal_kg_m2"][1], 0)

    def test_compiler_has_no_named_product_special_cases(self):
        source = inspect.getsource(product_contract).lower()
        for product_name in ("guillotine", "merry-go-round", "merry go round", "kettle", "cart"):
            self.assertNotIn(product_name, source)


if __name__ == "__main__":
    unittest.main()
