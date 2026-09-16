#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp import workshop_graph  # noqa: E402
from mcp.product_contract import compile_contract  # noqa: E402
from mcp.workshop import assemble, assemblies  # noqa: E402


class ProductCatalogue(unittest.TestCase):
    def test_functional_products_are_real_workshop_assemblies(self):
        names = {item["assembly"] for item in assemblies()}
        self.assertIn("cart", names)
        self.assertIn("kettle", names)


class FunctionalCart(unittest.TestCase):
    def setUp(self):
        self.design = assemble("cart", design_id="rolling-cart")
        self.graph = workshop_graph.product(self.design)

    def test_cart_has_real_wheels_axles_and_bearing_supports(self):
        roles = [component.role for component in self.graph.components]
        self.assertEqual(4, roles.count("wheel"))
        self.assertEqual(2, roles.count("axle"))
        self.assertEqual(4, roles.count("bearing_mount"))
        bearings = [r for r in self.graph.relationships if r.kind == "bearing"]
        self.assertGreaterEqual(len(bearings), 2)
        self.assertTrue(all("axis" in r.properties for r in bearings))

    def test_wheels_are_coupled_to_the_rotating_axles(self):
        wheel_ids = {c.component_id for c in self.graph.components if c.role == "wheel"}
        axle_ids = {c.component_id for c in self.graph.components if c.role == "axle"}
        coupled = [r for r in self.graph.relationships
                   if r.kind == "fixed" and {r.a, r.b} & wheel_ids and {r.a, r.b} & axle_ids]
        self.assertEqual(4, len(coupled))

    def test_runtime_contract_preserves_axle_rotation_but_collapses_fixed_detail(self):
        contract = compile_contract(self.graph)
        self.assertGreaterEqual(len(contract["mechanisms"]), 2)
        self.assertTrue(all(m["kind"] == "bearing" for m in contract["mechanisms"]))
        self.assertLess(len(contract["runtime_bodies"]), len(self.graph.components))
        for wheel in (c.component_id for c in self.graph.components if c.role == "wheel"):
            body = contract["component_to_body"][wheel]
            axle = next(r.a if r.b == wheel else r.b for r in self.graph.relationships
                        if r.kind == "fixed" and wheel in {r.a, r.b}
                        and (r.a.startswith("axle-") or r.b.startswith("axle-")))
            self.assertEqual(body, contract["component_to_body"][axle])

    def test_cart_declares_a_roll_trial(self):
        self.assertTrue(any(test.get("kind") == "cart_roll" for test in self.design.tests))


class FunctionalKettle(unittest.TestCase):
    def setUp(self):
        self.design = assemble("kettle", design_id="water-kettle")
        self.graph = workshop_graph.product(self.design)

    def test_kettle_is_an_open_container_derived_from_its_parts(self):
        roles = [component.role for component in self.graph.components]
        self.assertEqual(1, roles.count("container_bottom"))
        self.assertEqual(4, roles.count("container_wall"))
        self.assertEqual(1, len(self.graph.contents))
        contents = self.graph.contents[0]
        self.assertEqual("liquid-volume", contents["kind"])
        self.assertGreater(contents["capacity_l"], 1.0)
        self.assertIn("water", contents["accepted_substances"])
        self.assertEqual("empty-until-filled-by-test-or-world", contents["fill_state"])

    def test_capacity_changes_when_the_actual_kettle_geometry_changes(self):
        small = workshop_graph.product(assemble(
            "kettle", parameters={"width_m": 0.20, "depth_m": 0.18,
                                  "vessel_height_m": 0.12, "wall_thickness_m": 0.006}))
        large = workshop_graph.product(assemble(
            "kettle", parameters={"width_m": 0.32, "depth_m": 0.28,
                                  "vessel_height_m": 0.24, "wall_thickness_m": 0.006}))
        self.assertLess(small.contents[0]["capacity_l"], large.contents[0]["capacity_l"])

    def test_heat_path_runs_through_the_actual_bottom_into_contents(self):
        self.assertEqual(1, len(self.graph.energy))
        path = self.graph.energy[0]
        self.assertEqual("thermal_path", path["kind"])
        self.assertEqual("kettle-bottom", path["through_component"])
        self.assertEqual("primary-contents", path["to_contents"])
        self.assertEqual("conduction", path["mode"])

    def test_kettle_shell_and_handle_are_physically_connected(self):
        fixed = {(r.a, r.b) for r in self.graph.relationships if r.kind == "fixed"}
        connected = {name for pair in fixed for name in pair}
        self.assertIn("kettle-bottom", connected)
        self.assertIn("handle-mount-1", connected)
        self.assertIn("handle", connected)

    def test_kettle_declares_fill_and_heat_trials(self):
        kinds = {test.get("kind") for test in self.design.tests}
        self.assertTrue({"container_fill", "kettle_heat"} <= kinds)


if __name__ == "__main__":
    unittest.main()
