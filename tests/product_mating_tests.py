from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp.product_graph import ProductGraph, component, interface  # noqa: E402
from mcp.product_mating import mate_component, solve_mate, transform_point  # noqa: E402
from mcp.product_contract import compile_contract  # noqa: E402


class InterfaceMating(unittest.TestCase):
    def test_two_faces_meet_at_one_point_with_opposed_normals(self):
        source = interface("mount", "surface", point_m=(0, -0.5, 0), normal=(0, -1, 0))
        target = interface("top", "surface", point_m=(2, 1, 3), normal=(0, 1, 0))
        transform = solve_mate(source, target)
        self.assertEqual((2.0, 1.0, 3.0), transform_point(transform, (0, -0.5, 0)))
        self.assertEqual("opposed-surface-normals", transform["alignment"])

    def test_shafts_align_without_an_llm_coordinate_guess(self):
        source = interface("hub", "shaft", point_m=(0, 0, 0), axis=(1, 0, 0))
        target = interface("shaft", "shaft", point_m=(1, 2, 3), axis=(0, 0, 1))
        transform = solve_mate(source, target)
        self.assertEqual((1.0, 2.0, 3.0), transform_point(transform, (0, 0, 0)))
        self.assertEqual("aligned-axes", transform["alignment"])

    def test_saved_wheel_can_be_mated_to_an_axle_and_contract_keeps_bearing(self):
        axle = component("axle", "axle", material="iron",
            geometry={"shape": "cylinder", "mass_kg": 3, "center_m": [0, 0.5, 0], "size_m": [.04, 1, .04]},
            interfaces=(interface("shaft", "shaft", point_m=(0, .5, 0), axis=(1, 0, 0)),),
            physics_tags=("shaft", "structural_member"))
        wheel = component("wheel", "wheel", material="rubber",
            geometry={"shape": "cylinder", "mass_kg": 2, "center_m": [0, 0, 0], "size_m": [.4, .06, .4]},
            interfaces=(interface("hub", "shaft", point_m=(0, 0, 0), axis=(0, 1, 0)),),
            physics_tags=("rotor", "rolling_contact", "collision_surface"))
        graph = ProductGraph("wheel-on-axle", components=[axle, wheel])
        mated, transform = mate_component(
            graph, moving_component="wheel", moving_interface="hub",
            target_component="axle", target_interface="shaft", relationship_kind="bearing")
        moved = mated.component("wheel")
        hub = next(p for p in moved.interfaces if p.interface_id == "hub")
        self.assertEqual((0.0, 0.5, 0.0), tuple(round(v, 6) for v in hub.point_m))
        contract = compile_contract(mated)
        self.assertEqual(["bearing"], [j["kind"] for j in contract["mechanisms"]])
        self.assertEqual(2, len(contract["runtime_bodies"]))
        self.assertEqual("aligned-axes", transform["alignment"])

    def test_moving_one_member_of_an_existing_subassembly_is_refused(self):
        a = component("a", "frame", geometry={"mass_kg": 1})
        b = component("b", "frame", geometry={"mass_kg": 1},
                      interfaces=(interface("m", "surface", point_m=(0,0,0), normal=(0,1,0)),))
        c = component("c", "frame", geometry={"mass_kg": 1},
                      interfaces=(interface("m", "surface", point_m=(0,0,0), normal=(0,-1,0)),))
        from mcp.product_graph import relationship
        graph = ProductGraph("g", components=[a,b,c], relationships=[relationship("ab", "fixed", "a", "b")])
        with self.assertRaisesRegex(ValueError, "subassembly"):
            mate_component(graph, moving_component="b", moving_interface="m",
                           target_component="c", target_interface="m")


if __name__ == "__main__": unittest.main()
