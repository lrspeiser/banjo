#!/usr/bin/env python3
"""Building a design part by part: placement, contact and declared joints."""
from __future__ import annotations

from math import cos, pi, radians
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mcp  # noqa: E402,F401  (registers the functional products)
from mcp import product_contract, workshop_components, workshop_construction as con, workshop_graph  # noqa: E402
from mcp.workshop import WirePart, _rotate, strut  # noqa: E402

KEY = con.CONSTRUCTION_KEY


def box(name, size, centre, rotation=(0, 0, 0), *, role="beam", shape="box", material="oak"):
    return WirePart(name=name, role=role, size_m=tuple(size), center_m=tuple(centre),
                    rotation_deg=tuple(rotation), shape=shape, material=material)


def cart(overrides=None):
    return workshop_components.design_from_spec(
        {"kind": "cart", "design_id": "cart-t", "parameters": {}, "component_overrides": overrides or {}})


class Rotations(unittest.TestCase):
    def test_the_matrix_is_the_models_own_rotation(self):
        for angles in [(0, 0, 0), (10, 20, 30), (-75, 40, 170), (0, 90, 0), (33, -90, 12), (90, 0, 0)]:
            matrix = con.rotation_matrix(angles)
            for v in [(1, 0, 0), (0, 1, 0), (0, 0, 1), (0.3, -0.7, 0.2)]:
                for got, want in zip(con._apply(matrix, v), _rotate(angles, v)):
                    self.assertAlmostEqual(want, got, places=12)

    def test_euler_angles_come_back_as_the_same_rotation(self):
        for angles in [(10, 20, 30), (-75, 40, 170), (0, 90, 0), (33, -90, 12), (180, 0, 0)]:
            matrix = con.rotation_matrix(angles)
            again = con.rotation_matrix(con.euler_from_matrix(matrix))
            for row, back in zip(matrix, again):
                for want, got in zip(row, back):
                    self.assertAlmostEqual(want, got, places=10)


class Placement(unittest.TestCase):
    def setUp(self):
        self.slab = box("slab", (0.8, 0.04, 0.5), (0.0, 0.4, 0.0), role="top")
        self.post = box("post", (0.04, 0.3, 0.04), (0, 0, 0), role="post")

    def test_a_part_set_on_top_stands_on_the_face_and_keeps_the_slabs_axes(self):
        placed = con.place(self.post, by="face-y-", onto=self.slab, at_m=(0.2, 0.42, 0.1), snap=False)
        self.assertAlmostEqual(0.42, placed.lowest_m(), places=9)
        self.assertEqual((0.2, 0.1), (round(placed.center_m[0], 9), round(placed.center_m[2], 9)))
        for angle in placed.rotation_deg:
            self.assertAlmostEqual(0.0, angle, places=6)

    def test_a_part_hung_underneath_grows_downwards(self):
        placed = con.place(self.post, by="face-y-", onto=self.slab, at_m=(0.0, 0.38, 0.0), snap=False)
        self.assertAlmostEqual(0.38 - 0.15, placed.center_m[1], places=9)
        high = max(c[1] for c in placed.corners_m())
        self.assertAlmostEqual(0.38, high, places=9)

    def test_a_part_put_on_a_side_face_grows_out_sideways(self):
        placed = con.place(self.post, by="face-y-", onto=self.slab, at_m=(0.4, 0.4, 0.0), snap=False)
        self.assertAlmostEqual(0.4 + 0.15, placed.center_m[0], places=9)
        start, end = placed.ends_m()
        self.assertAlmostEqual(0.3, abs(end[0] - start[0]), places=9)

    def test_a_click_near_the_edge_settles_flush_and_near_the_middle_on_the_middle(self):
        flush = con.place(self.post, by="face-y-", onto=self.slab, at_m=(0.385, 0.42, 0.235))
        self.assertAlmostEqual(0.4 - 0.02, flush.center_m[0], places=9)
        self.assertAlmostEqual(0.25 - 0.02, flush.center_m[2], places=9)
        middle = con.place(self.post, by="face-y-", onto=self.slab, at_m=(0.02, 0.42, -0.01))
        self.assertAlmostEqual(0.0, middle.center_m[0], places=9)
        self.assertAlmostEqual(0.0, middle.center_m[2], places=9)

    def test_twist_turns_it_about_the_face_and_depth_sinks_it_in(self):
        plank = box("plank", (0.2, 0.02, 0.06), (0, 0, 0))
        flat = con.place(plank, by="face-y-", onto=self.slab, at_m=(0, 0.42, 0), snap=False)
        turned = con.place(plank, by="face-y-", onto=self.slab, at_m=(0, 0.42, 0), twist_deg=90, snap=False)
        span = lambda p: max(c[0] for c in p.corners_m()) - min(c[0] for c in p.corners_m())  # noqa: E731
        self.assertAlmostEqual(0.2, span(flat), places=9)
        self.assertAlmostEqual(0.06, span(turned), places=9)
        sunk = con.place(self.post, by="face-y-", onto=self.slab, at_m=(0, 0.42, 0), depth_m=0.01, snap=False)
        self.assertAlmostEqual(0.41, sunk.lowest_m(), places=9)

    def test_it_lands_square_on_a_tilted_part_too(self):
        ramp = box("ramp", (1.0, 0.04, 0.4), (0, 0.5, 0), rotation=(0, 0, 20))
        top = con.to_product(ramp, (0.1, 0.02, 0.0))
        placed = con.place(self.post, by="face-y-", onto=ramp, at_m=top, snap=False)
        patch = con.contact_patch(ramp, placed)
        self.assertIsNotNone(patch)
        self.assertFalse(patch["mitred"])
        self.assertAlmostEqual(0.04 * 0.04, patch["area_m2"], places=9)


class Contact(unittest.TestCase):
    def test_two_square_faces_meet_over_their_overlap(self):
        a = box("a", (0.4, 0.1, 0.4), (0, 0.05, 0))
        b = box("b", (0.2, 0.3, 0.1), (0.15, 0.25, 0))       # overhangs a's +x edge by 0.05
        patch = con.contact_patch(a, b)
        self.assertEqual(("a", "face-y+", "b", "face-y-"),
                         (patch["on"], patch["on_face"], patch["against"], patch["against_face"]))
        self.assertAlmostEqual(0.15 * 0.1, patch["area_m2"], places=12)
        self.assertAlmostEqual(0.125, patch["centre_m"][0], places=12)
        # A 0.15 x 0.10 rectangle: I = b h^3 / 12 about each of its own axes.
        for want, got in zip(sorted([0.15 * 0.1 ** 3 / 12, 0.1 * 0.15 ** 3 / 12]),
                             sorted([patch["i_uu_m4"], patch["i_vv_m4"]])):
            self.assertAlmostEqual(want, got, places=12)

    def test_parts_apart_or_side_by_side_do_not_meet(self):
        a = box("a", (0.4, 0.1, 0.4), (0, 0.05, 0))
        self.assertIsNone(con.contact_patch(a, box("b", (0.2, 0.3, 0.1), (0, 0.26, 0))))     # 10 mm above
        self.assertIsNone(con.contact_patch(a, box("c", (0.2, 0.1, 0.1), (0.31, 0.05, 0))))  # 10 mm beside

    def test_a_round_end_bears_over_its_disc(self):
        slab = box("slab", (0.4, 0.04, 0.4), (0, 0.02, 0))
        peg = box("peg", (0.06, 0.2, 0.06), (0, 0.14, 0), shape="cylinder")
        patch = con.contact_patch(slab, peg)
        # The disc is drawn as a 32-gon, which encloses 0.6% less than the circle.
        self.assertAlmostEqual(pi * 0.03 ** 2, patch["area_m2"], delta=0.007 * pi * 0.03 ** 2)

    def test_a_raked_member_bears_over_its_section_divided_by_the_cosine(self):
        slab = box("slab", (1.0, 0.04, 1.0), (0, 0.5, 0), role="top")
        rake = 15.0
        leg = strut(name="leg", role="leg", from_m=(0.0, 0.48, 0.0),
                    to_m=(0.3 * cos(radians(90 - rake)), 0.48 - 0.3 * cos(radians(rake)), 0.0),
                    section_m=(0.05, 0.05))
        patch = con.contact_patch(slab, leg)
        self.assertTrue(patch["mitred"])
        self.assertEqual("slab", patch["on"])
        self.assertAlmostEqual(0.05 * 0.05 / cos(radians(rake)), patch["area_m2"], places=9)

    def test_a_shaft_through_a_block_is_measured_by_what_lies_inside(self):
        block = box("block", (0.0345, 0.18, 0.0345), (0.19, 0.25, 0.0))
        axle = strut(name="axle", role="axle", from_m=(-0.38, 0.16, 0), to_m=(0.38, 0.16, 0),
                     section_m=(0.03, 0.03), shape="cylinder")
        how = con.interface(block, axle)
        self.assertEqual(("cylindrical", "axle", "block"), (how["form"], how["shaft"], how["housing"]))
        self.assertAlmostEqual(0.0345, how["engaged_m"], places=9)
        self.assertAlmostEqual(0.03, how["diameter_m"], places=12)
        self.assertTrue(how["through"])
        for got, want in zip(how["axis"], (1.0, 0.0, 0.0)):
            self.assertAlmostEqual(want, abs(got), places=9)


class TheCartAsATemplate(unittest.TestCase):
    def test_adopting_writes_down_the_joints_the_template_implied(self):
        design, _ = cart()
        self.assertEqual({}, con.of(design))
        adopted = con.adopted(design)
        counted: dict[tuple[str, str], int] = {}
        for joint in adopted["joints"]:
            counted[(joint["kind"], joint["method"])] = counted.get((joint["kind"], joint["method"]), 0) + 1
        self.assertEqual({("fixed", "bonded"): 6, ("fixed", "pressed"): 6, ("bearing", "bearing"): 4}, counted)

    def test_every_adopted_joint_is_closed_and_the_runtime_bodies_do_not_change(self):
        design, _ = cart()
        before = product_contract.compile_contract(workshop_graph.product(design))
        built, _ = cart({KEY: con.adopted(design)})
        self.assertEqual([], [j["id"] for j in con.joints(built) if j["open"]])
        after = product_contract.compile_contract(workshop_graph.product(built))
        bodies = lambda c: sorted((len(b["components"]), b["mass_kg"]) for b in c["runtime_bodies"])  # noqa: E731
        self.assertEqual(bodies(before), bodies(after))
        self.assertEqual(3, len(after["runtime_bodies"]))
        self.assertEqual(4, len(after["mechanisms"]))

    def test_authored_joints_replace_what_touching_used_to_imply(self):
        design, overrides = cart()
        adopted = con.adopted(design)
        overrides = con.set_joint(*cart({KEY: adopted}), a="deck", b="handle-arm-1", kind=None)
        overrides = con.set_joint(*cart(overrides), a="deck", b="handle-arm-2", kind=None)
        built, _ = cart(overrides)
        contract = product_contract.compile_contract(workshop_graph.product(built))
        # The handle and its two arms still touch the deck and are no longer part of it.
        self.assertEqual(4, len(contract["runtime_bodies"]))
        loose = next(b for b in contract["runtime_bodies"] if "handle" in b["components"])
        self.assertEqual(["handle", "handle-arm-1", "handle-arm-2"], loose["components"])


class BuildingOn(unittest.TestCase):
    def test_adding_a_part_fastens_it_and_removing_it_takes_its_joints(self):
        design, overrides = cart()
        deck = next(p for p in design.parts if p.name == "deck")
        post = con.template_part({"name": con.fresh_name(design, "post"), "family": "post", "length_m": 0.3,
                                  "parameters": {"width_m": 0.04, "depth_m": 0.04}})
        placed = con.place(post, by="face-y-", onto=deck, at_m=(0.1, 0.38, 0.1), snap=False)
        overrides = con.add_part(design, overrides, part=placed, joint={"to": "deck", "kind": "fixed"})
        built, overrides = cart(overrides)
        self.assertEqual(15, len(built.parts))
        joint = con.joints(built)[-1]
        self.assertEqual(("deck", "post-1", "fixed", "bonded", False),
                         (joint["a"], joint["b"], joint["kind"], joint["method"], joint["open"]))
        self.assertAlmostEqual(0.0016, joint["interface"]["area_m2"], places=9)
        self.assertEqual([{"family": "post", "count": 1}],
                         [row for row in built.lineage["components"] if row["family"] == "post"])

        overrides = con.remove_part(built, overrides, "post-1")
        again, _ = cart(overrides)
        self.assertEqual(14, len(again.parts))
        self.assertEqual(16, len(con.of(again)["joints"]))

    def test_a_template_part_can_be_taken_off_and_its_edits_go_with_it(self):
        design, _ = cart({"handle": {"material": "iron"}})
        overrides = con.remove_part(design, design.lineage["component_overrides"], "handle")
        built, _ = cart(overrides)
        self.assertNotIn("handle", [p.name for p in built.parts])
        self.assertNotIn("handle", overrides)
        self.assertEqual(["handle"], con.of(built)["removed"])
        self.assertEqual([], [j for j in con.of(built)["joints"] if "handle" in (j["a"], j["b"])])

    def test_a_part_that_does_not_touch_cannot_be_fastened(self):
        design, overrides = cart()
        far = box("far", (0.1, 0.1, 0.1), (3, 3, 3))
        with self.assertRaisesRegex(ValueError, "does not touch"):
            con.add_part(design, overrides, part=far, joint={"to": "deck", "kind": "fixed"})
        loose = con.add_part(design, overrides, part=far, joint=None)      # loose is allowed, and said
        self.assertEqual(["far"], con.unfastened(cart(loose)[0]))

    def test_an_edit_that_pulls_a_part_away_leaves_its_joint_open_not_gone(self):
        design, overrides = cart()
        built, overrides = cart({KEY: con.adopted(design)})
        overrides["bearing-mount-11"] = {"center_m": [0.19, 0.9, -0.32]}
        moved, _ = cart(overrides)
        opened = [j for j in con.joints(moved) if j["open"]]
        self.assertEqual({"bearing-mount-11"}, {n for j in opened for n in (j["a"], j["b"])} & {"bearing-mount-11"})
        self.assertEqual(16, len(con.of(moved)["joints"]))
        # An open joint fastens nothing: the graph does not claim it.
        ids = {r.relationship_id for r in workshop_graph.product(moved).relationships if not r.derived}
        self.assertTrue({j["id"] for j in opened}.isdisjoint(ids))

    def test_a_design_can_be_built_from_nothing(self):
        slab = {"name": "slab-1", "role": "top", "family": "surface", "shape": "box",
                "size_m": [0.8, 0.04, 0.5], "center_m": [0, 0.4, 0], "rotation_deg": [0, 0, 0], "material": "oak"}
        spec = {"kind": "custom", "design_id": "mine", "parameters": {},
                "component_overrides": {KEY: {"added": [slab], "joints_authored": True}}}
        design, overrides = workshop_components.design_from_spec(spec)
        self.assertEqual(["slab-1"], [p.name for p in design.parts])
        leg = con.template_part({"name": "leg-1", "family": "post", "length_m": 0.38,
                                 "parameters": {"width_m": 0.05, "depth_m": 0.05}})
        placed = con.place(leg, by="face-y-", onto=design.parts[0], at_m=(0.37, 0.38, 0.22))
        overrides = con.add_part(design, overrides, part=placed, joint={"to": "slab-1", "kind": "fixed"})
        built, _ = workshop_components.design_from_spec({**spec, "component_overrides": overrides})
        self.assertAlmostEqual(0.0, built.measure()["lowest_m"], places=9)
        with self.assertRaisesRegex(ValueError, "at least one part"):
            workshop_components.design_from_spec({"kind": "custom", "design_id": "empty", "parameters": {}})


class Refusals(unittest.TestCase):
    def test_a_malformed_construction_is_refused_with_the_reason(self):
        part = {"name": "p", "role": "beam", "shape": "box", "size_m": [0.1, 0.1, 0.1],
                "center_m": [0, 0, 0], "material": "oak"}
        for block, why in [
            ({"added": [{**part, "size_m": [0.1, -1, 0.1]}]}, "positive"),
            ({"added": [{**part, "shape": "banana"}]}, "shape"),
            ({"added": [part, part]}, "different names"),
            ({"added": [{**part, "name": "@p"}]}, "begin with @"),
            ({"added": [part], "removed": ["p"]}, "both added and removed"),
            ({"joints": [{"id": "j", "kind": "welded", "a": "x", "b": "y"}]}, "kind"),
            ({"joints": [{"id": "j", "kind": "bearing", "method": "bonded", "a": "x", "b": "y"}]}, "bearing"),
            ({"joints": [{"id": "j", "kind": "fixed", "a": "x", "b": "x"}]}, "two different"),
            ({"joints": [{"id": "j", "kind": "fixed", "a": "x", "b": "y"},
                         {"id": "k", "kind": "fixed", "a": "y", "b": "x"}]}, "at most one joint"),
            ({"surprise": 1}, "unknown field"),
        ]:
            with self.assertRaisesRegex(ValueError, why, msg=str(block)):
                con.checked(block)

    def test_a_joint_or_a_removal_naming_a_part_that_is_not_there_is_refused(self):
        with self.assertRaisesRegex(ValueError, "does not have"):
            cart({KEY: {"removed": ["no-such-part"]}})
        with self.assertRaisesRegex(ValueError, "does not have"):
            cart({KEY: {"joints": [{"id": "j", "kind": "fixed", "a": "deck", "b": "ghost"}]}})
        with self.assertRaisesRegex(ValueError, "already here"):
            cart({KEY: {"added": [{"name": "deck", "role": "top", "shape": "box", "size_m": [1, 1, 1],
                                   "center_m": [0, 0, 0], "material": "oak"}]}})


if __name__ == "__main__":
    unittest.main()
