from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp.workshop import assemble  # noqa: E402
from mcp import workshop_graph  # noqa: E402
from mcp.product_mating import solve_mate, transform_point  # noqa: E402


class CanonicalComponentTemplates(unittest.TestCase):
    def test_table_leg_template_forgets_where_that_leg_stood(self):
        design = assemble("table", design_id="t", parameters={"leg_style":"splayed", "splay_deg":10})
        leg = next(p for p in design.parts if p.name == "leg-1")
        self.assertNotEqual((0.0,0.0,0.0), leg.center_m)
        template = workshop_graph.template_component(leg, component_id="saved-leg")
        self.assertEqual([0.0,0.0,0.0], template.geometry["center_m"])
        self.assertEqual([0.0,0.0,0.0], template.geometry["rotation_deg"])
        end_a = next(p for p in template.interfaces if p.interface_id == "end-a")
        end_b = next(p for p in template.interfaces if p.interface_id == "end-b")
        self.assertAlmostEqual(-leg.size_m[1]/2, end_a.point_m[1])
        self.assertAlmostEqual(leg.size_m[1]/2, end_b.point_m[1])
        self.assertEqual((0.0,1.0,0.0), end_a.axis)

    def test_wheel_template_hub_is_at_local_origin_even_if_source_wheel_is_not(self):
        cart = assemble("cart", design_id="c")
        wheel = next(p for p in cart.parts if p.role == "wheel")
        self.assertNotEqual((0.0,0.0,0.0), wheel.center_m)
        template = workshop_graph.template_component(wheel)
        hub = next(p for p in template.interfaces if p.interface_id == "hub")
        self.assertEqual((0.0,0.0,0.0), hub.point_m)
        self.assertEqual((0.0,1.0,0.0), hub.axis)

    def test_canonical_saved_port_can_be_mated_anywhere(self):
        leg = next(p for p in assemble("table", design_id="t").parts if p.role == "leg")
        template = workshop_graph.template_component(leg)
        source = next(p for p in template.interfaces if p.interface_id == "end-b")
        from mcp.product_graph import interface
        target = interface("mount", "end", point_m=(7,3,-2), axis=(0,1,0))
        move = solve_mate(source, target)
        self.assertEqual((7.0,3.0,-2.0), transform_point(move, source.point_m))


if __name__ == "__main__": unittest.main()
