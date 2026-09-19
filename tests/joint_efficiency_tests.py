#!/usr/bin/env python3
"""What a joint keeps of the material it joins, and how it reaches the engine.

The numbers themselves are declared (mcp/joint_efficiency.py) and are the
owner's to change; what is pinned here is that each case gets the law it should,
that every number says where it comes from, and that the law arrives at the
scene intact.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "playground"))

import fracture_lab  # noqa: E402
import mcp  # noqa: E402,F401
from mcp import joint_efficiency as je  # noqa: E402
from mcp import workshop_components, workshop_construction as con  # noqa: E402
from mcp.workshop import WirePart  # noqa: E402

KEY = con.CONSTRUCTION_KEY


def part(name, size, centre, *, material="oak", role="beam", shape="box"):
    return {"name": name, "role": role, "shape": shape, "size_m": list(size),
            "center_m": list(centre), "rotation_deg": [0, 0, 0], "material": material}


def built(parts, joints):
    rows = [{"id": f"j{i + 1}", "kind": kind, "a": a, "b": b,
             **({"method": method} if method else {})}
            for i, (a, b, kind, method) in enumerate(joints)]
    return workshop_components.design_from_spec(
        {"kind": "custom", "design_id": "case", "parameters": {},
         "component_overrides": {KEY: {"added": parts, "joints": rows, "joints_authored": True}}})[0]


def only(design):
    row = con.joints(design)[0]
    parts = {p.name: p for p in design.parts}
    return je.efficiency(row, parts[row["a"]], parts[row["b"]])


class WhichWayTheGrainRuns(unittest.TestCase):
    def test_the_grain_runs_along_a_parts_longest_side(self):
        for size, axis in ((( .05, .70, .05), 1),      # a leg
                           (( .70, .04, 1.0), 2),      # a table top: along the board, not its thickness
                           ((1.2, .04, .70), 0),
                           (( .10, .10, .10), None),   # a cube says nothing
                           (( .32, .06, .32), None)):  # a disc says nothing
            self.assertEqual(axis, je.grain_axis(WirePart(
                name="p", role="beam", size_m=size, center_m=(0, 0, 0))), size)

    def test_a_face_is_end_grain_when_it_looks_along_the_grain(self):
        leg = WirePart(name="leg", role="leg", size_m=(.05, .70, .05), center_m=(0, 0, 0))
        self.assertTrue(je._is_end("face-y-", leg))
        self.assertTrue(je._is_end("face-y+", leg))
        self.assertFalse(je._is_end("face-x+", leg))
        # A part with no longest side is taken to show end grain: for a strength
        # answer that is the safe way to be wrong.
        cube = WirePart(name="c", role="beam", size_m=(.1, .1, .1), center_m=(0, 0, 0))
        self.assertTrue(je._is_end("face-x+", cube))


class WhichLawEachJointGets(unittest.TestCase):
    def test_a_leg_glued_into_a_top_is_an_end_grain_butt_joint(self):
        design = built([part("top", (.8, .04, .5), (0, .72, 0), role="top"),
                        part("leg", (.05, .70, .05), (.3, .35, .2), role="leg")],
                       [("top", "leg", "fixed", "bonded")])
        keeps = only(design)
        self.assertEqual("bonded, end grain butted to another part", keeps["id"])
        self.assertEqual((.25, .25, 1.0), (keeps["tension"], keeps["shear"], keeps["compression"]))
        self.assertIn("leg's end grain", keeps["basis"])
        self.assertEqual("reference-derived", keeps["provenance"])
        self.assertIn("Wood Handbook", keeps["source"])

    def test_two_boards_glued_face_to_face_are_as_strong_as_the_wood(self):
        design = built([part("a", (.8, .04, .5), (0, .02, 0), role="panel"),
                        part("b", (.8, .04, .5), (0, .06, 0), role="panel")],
                       [("a", "b", "fixed", "bonded")])
        keeps = only(design)
        self.assertEqual("bonded, side grain or isotropic", keeps["id"])
        self.assertEqual((1.0, 1.0, 1.0), (keeps["tension"], keeps["shear"], keeps["compression"]))
        self.assertIn("side grain to side grain", keeps["basis"])

    def test_iron_has_no_grain_so_a_weld_is_the_plate(self):
        design = built([part("a", (.2, .02, .2), (0, .01, 0), material="iron", role="panel"),
                        part("b", (.05, .30, .05), (0, .17, 0), material="iron", role="post")],
                       [("a", "b", "fixed", "bonded")])
        keeps = only(design)
        self.assertEqual("bonded, side grain or isotropic", keeps["id"])
        self.assertEqual(1.0, keeps["tension"])
        # The same shapes in oak are an end-grain butt: the material decides.
        oak = built([part("a", (.2, .02, .2), (0, .01, 0), role="panel"),
                     part("b", (.05, .30, .05), (0, .17, 0), role="post")],
                    [("a", "b", "fixed", "bonded")])
        self.assertEqual(.25, only(oak)["tension"])

    def test_a_press_fit_is_a_demonstration_number_and_says_so(self):
        design = built([part("block", (.0345, .18, .0345), (.19, .25, 0)),
                        part("axle", (.03, .76, .03), (0, .16, 0), shape="cylinder", role="axle")],
                       [("block", "axle", "fixed", "pressed")])
        keeps = only(design)
        self.assertEqual("pressed fit", keeps["id"])
        self.assertEqual("demonstration", keeps["provenance"])
        self.assertEqual(.15, keeps["tension"])
        self.assertIn("DEMONSTRATION", keeps["source"])

    def test_a_bearing_is_not_a_bond_and_is_left_alone_out_loud(self):
        design = built([part("block", (.0345, .18, .0345), (.19, .25, 0)),
                        part("axle", (.03, .76, .03), (0, .16, 0), shape="cylinder", role="axle")],
                       [("block", "axle", "bearing", "bearing")])
        keeps = only(design)
        self.assertFalse(keeps["rated"])
        self.assertEqual((1.0, 1.0, 1.0), (keeps["tension"], keeps["shear"], keeps["compression"]))
        self.assertIn("not declared in the design", keeps["basis"])

    def test_every_declared_law_carries_its_source_and_what_it_misses(self):
        laws = je.described()
        self.assertEqual(3, len(laws))
        for row in laws:
            self.assertIn(row["provenance"], {"reference-derived", "demonstration"})
            self.assertGreater(len(row["source"]), 120, row["id"])
            self.assertTrue(row["not_modelled"], row["id"])
            self.assertEqual(1.0, row["compression"], row["id"])
            for key in ("tension", "shear"):
                self.assertTrue(0.0 < row[key] <= 1.0, row)


class ReachingTheScene(unittest.TestCase):
    def table(self):
        design = workshop_components.design_from_spec(
            {"kind": "table", "design_id": "t", "parameters": {"material": "oak"}})[0]
        return workshop_components.design_from_spec(
            {"kind": "table", "design_id": "t", "parameters": {"material": "oak"},
             "component_overrides": {KEY: con.adopted(design)}})[0]

    def test_a_template_declares_nothing_until_its_joints_are_its_own(self):
        plain = workshop_components.design_from_spec(
            {"kind": "table", "design_id": "t", "parameters": {"material": "oak"}})[0]
        self.assertEqual([], je.scene_interfaces(plain))

    def test_every_leg_reaches_the_scene_as_its_own_joint(self):
        declared = je.scene_interfaces(self.table())
        self.assertEqual(4, len(declared))
        self.assertEqual({"top"}, {face["a"] for face in declared})
        self.assertEqual({f"leg-{i}" for i in range(1, 5)}, {face["b"] for face in declared})
        for face in declared:
            self.assertEqual({"a": face["a"], "b": face["b"], "tension": .25,
                              "shear": .25, "compression": 1.0}, face)

    def test_an_open_joint_crosses_nothing_so_it_is_left_out(self):
        design = self.table()
        overrides = dict(design.lineage["component_overrides"])
        overrides["leg-1"] = {"center_m": [3.0, 3.0, 3.0]}
        moved = workshop_components.design_from_spec(
            {"kind": "table", "design_id": "t", "parameters": {"material": "oak"},
             "component_overrides": overrides})[0]
        self.assertEqual(3, len(je.scene_interfaces(moved)))

    def test_the_scene_carries_the_parts_and_their_joints_to_the_engine(self):
        bodies = [{"name": "top", "shape": "box", "material": "oak", "size_mm": [400, 40, 200],
                   "center_mm": [0, 420, 0], "join": "t", "part": "top"},
                  {"name": "leg", "shape": "box", "material": "oak", "size_mm": [40, 400, 40],
                   "center_mm": [0, 200, 0], "join": "t", "part": "leg"}]
        spec = fracture_lab.validate({"algorithm": "lattice", "cell_m": .02, "bodies": bodies,
                                      "interfaces": [{"a": "top", "b": "leg", "tension": .25}]})
        document = fracture_lab.scene_document(spec)
        self.assertEqual(["top", "leg"], [b["part"] for b in document["bodies"]])
        self.assertEqual([{"a": "top", "b": "leg", "tension": .25}], document["interfaces"])
        # A scene that declares none carries none, so its document is the word
        # every saved world is already checked against.
        plain = fracture_lab.scene_document(
            fracture_lab.validate({"algorithm": "lattice", "cell_m": .02, "bodies": bodies}))
        self.assertNotIn("interfaces", plain)

    def test_what_the_scene_refuses(self):
        bodies = [{"name": "top", "shape": "box", "material": "oak", "size_mm": [400, 40, 200],
                   "center_mm": [0, 420, 0], "join": "t", "part": "top"},
                  {"name": "leg", "shape": "box", "material": "oak", "size_mm": [40, 400, 40],
                   "center_mm": [0, 200, 0], "join": "t", "part": "leg"}]
        for interfaces, why in (
            ([{"a": "top", "b": "ghost", "tension": .5}], "which no body in this scene is"),
            ([{"a": "top", "b": "leg", "tension": 2.0}], "between 0 and 1"),
            ([{"a": "top", "b": "leg", "tension": 0, "shear": 0, "compression": 0}], "two objects"),
            ([{"a": "top", "b": "leg", "glue": .5}], "unknown field"),
            ([{"a": "top", "b": "top", "tension": .5}], "two different named parts"),
            ([{"a": "top", "b": "leg"}, {"a": "leg", "b": "top"}], "more than one interface"),
            ({"a": "top"}, "must be a list"),
        ):
            with self.assertRaisesRegex(ValueError, why, msg=str(interfaces)):
                fracture_lab.validate({"algorithm": "lattice", "cell_m": .02,
                                       "bodies": bodies, "interfaces": interfaces})
        # A part label only means something inside a join group.
        with self.assertRaisesRegex(ValueError, "only a body in a join group"):
            fracture_lab.validate({"algorithm": "lattice", "cell_m": .02, "bodies": [
                {"name": "lone", "shape": "box", "material": "oak", "size_mm": [40, 40, 40],
                 "center_mm": [0, 20, 0], "part": "top"}]})

    def test_the_products_cells_are_decomposed_part_by_part(self):
        import workshop_motion
        import workshop_sparse_trial as sparse
        design = self.table()
        setup = workshop_motion.scene(design, "drop_product", {"height_m": 1.0, "cell_size_m": .02})
        labelled = [b for b in setup["spec"]["bodies"] if b.get("part")]
        self.assertEqual({"top", "leg-1", "leg-2", "leg-3", "leg-4"}, {b["part"] for b in labelled})
        self.assertEqual(4, len(setup["spec"]["interfaces"]))
        # Every cell is still there, and each belongs to exactly one part.
        matter = setup["matter"]
        part_of = sparse._grid_parts(matter)
        self.assertEqual(matter["total_cells"], len(part_of))
        self.assertEqual(set(part_of), sparse._grid_set(matter))


if __name__ == "__main__":
    unittest.main()
