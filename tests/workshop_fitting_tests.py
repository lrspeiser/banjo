#!/usr/bin/env python3
"""Check Validity: the concepts it insists on, and the redraws it makes.

The cart is what the rules were written against. The door is the test that
matters: it is built from components here, nothing about it was tuned for, and
it has to come out as a frame and a leaf on one hinge without anybody saying so.
"""
from __future__ import annotations
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "playground"))

from mcp.workshop import WorkshopDesign, WirePart, assemble  # noqa: E402
from mcp import workshop_components  # noqa: E402
from mcp import workshop_construction as construction  # noqa: E402
import workshop_articulation  # noqa: E402
import workshop_fitting  # noqa: E402

CELL = 0.04


def block(name, role, size, at, material="oak"):
    return WirePart(name=name, role=role, size_m=tuple(size), center_m=tuple(at),
                    material=material, rotation_deg=(0.0, 0.0, 0.0), shape="box", family=role)


def door_and_frame():
    """Two posts, a lintel across them, and a leaf hung on the left post."""
    base = WorkshopDesign(design_id="door", purpose="a door that swings in its frame",
                          parts=[block("post-left", "post", (0.09, 2.03, 0.09), (-0.52, 1.015, 0.0))],
                          kind="custom")
    overrides = construction.add_part(
        base, {}, part=block("post-right", "post", (0.09, 2.03, 0.09), (0.52, 1.015, 0.0)))
    built = workshop_components.apply_overrides(base, overrides)
    overrides = construction.add_part(
        built, overrides, part=block("lintel", "beam", (1.13, 0.09, 0.09), (0.0, 2.075, 0.0)),
        joint={"to": "post-left", "kind": "fixed"})
    built = workshop_components.apply_overrides(base, overrides)
    overrides = construction.set_joint(built, overrides, a="lintel", b="post-right", kind="fixed")
    built = workshop_components.apply_overrides(base, overrides)
    overrides = construction.add_part(
        built, overrides, part=block("door", "panel", (0.90, 1.97, 0.045), (-0.025, 1.0, 0.0)),
        joint={"to": "post-left", "kind": "bearing"})
    return base, overrides


def compiled(base, answer, root):
    fitted = workshop_components.apply_overrides(base, answer["overrides"])
    return workshop_articulation.compile_design(fitted, answer["overrides"], cell_m=CELL, root=root)


class TheCart(unittest.TestCase):
    def setUp(self):
        self.design = assemble("cart", design_id="c")

    def test_it_will_not_compile_as_the_template_draws_it(self):
        overrides = workshop_fitting._readopt(self.design, {})
        built = workshop_components.apply_overrides(self.design, overrides)
        with self.assertRaises(ValueError):
            workshop_articulation.compile_design(built, overrides, cell_m=CELL, root="cart")

    def test_check_validity_redraws_it_until_it_does(self):
        answer = workshop_fitting.check_validity(self.design, {}, cell_m=CELL, root="cart")
        self.assertTrue(answer["ok"], answer.get("why"))
        self.assertEqual("ready", answer["stage"])
        self.assertTrue(answer["changes"])

    def test_it_comes_out_as_four_wheels_turning_on_a_frame(self):
        answer = workshop_fitting.check_validity(self.design, {}, cell_m=CELL, root="cart")
        made = compiled(self.design, answer, "cart")
        self.assertEqual(5, len(made["groups"]))
        self.assertEqual(4, len(made["joints"]))
        self.assertEqual({"hinge"}, {j["kind"] for j in made["joints"]})
        masses = sorted(round(g["mass_kg"], 1) for g in made["groups"])
        self.assertEqual(1, len(set(masses[:4])), "the four wheels should weigh the same")
        self.assertGreater(masses[-1], masses[0], "the frame is heavier than a wheel")

    def test_the_through_axle_is_drawn_as_stubs(self):
        answer = workshop_fitting.check_validity(self.design, {}, cell_m=CELL, root="cart")
        rules = {c["rule"] for c in answer["changes"]}
        self.assertIn("a shaft through its mounts becomes stubs", rules)
        fitted = workshop_components.apply_overrides(self.design, answer["overrides"])
        names = {p.name for p in fitted.parts}
        self.assertNotIn("axle-1", names, "the through-axle is gone")
        self.assertTrue([n for n in names if n.startswith("axle-1-stub")])

    def test_every_change_says_what_it_did_and_why(self):
        answer = workshop_fitting.check_validity(self.design, {}, cell_m=CELL, root="cart")
        for change in answer["changes"]:
            self.assertTrue(change["says"].strip())
            self.assertIn(change["part"].split(",")[0].strip(), change["says"])
            self.assertTrue(change["rule"].strip())


class ADoorNobodyTunedFor(unittest.TestCase):
    def setUp(self):
        self.base, self.overrides = door_and_frame()

    def test_it_is_built_from_components_with_one_turning_joint(self):
        built = workshop_components.apply_overrides(self.base, self.overrides)
        self.assertEqual(4, len(built.parts))
        joints = construction.joints(built)
        self.assertEqual(3, len(joints))
        self.assertEqual(1, sum(1 for j in joints if j["kind"] == "bearing"))

    def test_it_will_not_compile_as_drawn(self):
        built = workshop_components.apply_overrides(self.base, self.overrides)
        with self.assertRaises(ValueError):
            workshop_articulation.compile_design(built, self.overrides, cell_m=CELL, root="door")

    def test_check_validity_makes_it_a_door_that_swings(self):
        answer = workshop_fitting.check_validity(self.base, self.overrides, cell_m=CELL, root="door")
        self.assertTrue(answer["ok"], answer.get("why"))
        made = compiled(self.base, answer, "door")
        self.assertEqual(2, len(made["groups"]), "a frame and a leaf")
        self.assertEqual(1, len(made["joints"]))
        self.assertEqual("hinge", made["joints"][0]["kind"])

    def test_the_leaf_is_lighter_than_the_frame_it_hangs_in(self):
        answer = workshop_fitting.check_validity(self.base, self.overrides, cell_m=CELL, root="door")
        made = compiled(self.base, answer, "door")
        masses = sorted(g["mass_kg"] for g in made["groups"])
        self.assertLess(masses[0], masses[1])

    def test_the_bearing_survives_the_redraw_as_a_bearing(self):
        answer = workshop_fitting.check_validity(self.base, self.overrides, cell_m=CELL, root="door")
        fitted = workshop_components.apply_overrides(self.base, answer["overrides"])
        kinds = {j["kind"] for j in construction.joints(fitted)}
        self.assertIn("bearing", kinds,
                      "re-adopting after a redraw must not turn the hinge back into a bond")


class WhatItRefusesToInvent(unittest.TestCase):
    def test_a_part_fastened_to_nothing_is_refused(self):
        base = WorkshopDesign(design_id="loose", purpose="two things near each other",
                              parts=[block("a", "post", (0.08, 0.8, 0.08), (0.0, 0.4, 0.0)),
                                     block("b", "post", (0.08, 0.8, 0.08), (2.0, 0.4, 0.0))],
                              kind="custom")
        answer = workshop_fitting.check_validity(base, {}, cell_m=CELL, root="loose")
        self.assertFalse(answer["ok"])
        self.assertEqual("concepts", answer["stage"])
        self.assertIn("nothing holds", answer["says"])

    def test_a_wheel_with_nothing_to_turn_on_is_said_not_guessed(self):
        base = WorkshopDesign(design_id="stuck", purpose="a wheel bonded to a post",
                              parts=[block("post", "post", (0.08, 0.8, 0.08), (0.0, 0.4, 0.0))],
                              kind="custom")
        overrides = construction.add_part(
            base, {}, part=block("wheel", "wheel", (0.32, 0.08, 0.32), (0.2, 0.4, 0.0)),
            joint={"to": "post", "kind": "fixed"})
        built = workshop_components.apply_overrides(base, overrides)
        said = {c["concept"]: c for c in workshop_fitting.concepts(built)}
        turning = said["every wheel has something to turn on"]
        self.assertFalse(turning["ok"])
        self.assertIn("turns on nothing", turning["says"])


if __name__ == "__main__":
    unittest.main()
