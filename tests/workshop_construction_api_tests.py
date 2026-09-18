#!/usr/bin/env python3
"""Building part by part through the Workshop API: preview, add, save, reopen."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "playground"))

import workshop_api  # noqa: E402
import workshop_store  # noqa: E402
from mcp import workshop_construction as con  # noqa: E402

KEY = con.CONSTRUCTION_KEY
POST = {"family": "post", "length_m": 0.3, "material": "oak", "parameters": {"width_m": 0.04, "depth_m": 0.04}}


def spec_of(candidate, kind):
    return {"kind": kind, "design_id": candidate["design_id"], "parameters": candidate["parameters"],
            "component_overrides": candidate["component_overrides"]}


class Building(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        self.app = types.SimpleNamespace(workshop_store=root / "workshop")
        self.app.workshop_store.mkdir(parents=True)
        # The default cart, not the first seeded variant: deck top at 0.38 m, 0.32 m wheels.
        self.cart = workshop_api.candidates(self.app, {"kind": "cart", "sweeps": {}})["candidates"][0]

    def tearDown(self):
        self.tmp.cleanup()

    def add_post(self, candidate, at=(0.1, 0.38, 0.1), **more):
        return workshop_api.candidates(self.app, {
            **spec_of(candidate, "cart"),
            "construct": {"action": "add", "part": dict(POST), "by": "face-y-", "onto": "deck",
                          "at_m": list(at), "joint": {"kind": "fixed"}, **more}})

    def test_a_template_says_it_has_no_joints_of_its_own_yet(self):
        self.assertFalse(self.cart["construction"]["joints_authored"])
        self.assertEqual([], self.cart["construction"]["joints"])

    def test_a_preview_shows_where_the_part_would_go_and_changes_nothing(self):
        answer = workshop_api.candidates(self.app, {
            **spec_of(self.cart, "cart"),
            "construct": {"action": "preview", "part": dict(POST), "by": "face-y-", "onto": "deck",
                          "at_m": [0.1, 0.38, 0.1], "snap": False}})
        self.assertNotIn("candidates", answer)
        self.assertEqual(0, answer["generation"])
        ghost = answer["construct"]["part"]
        self.assertEqual("post-1", ghost["name"])
        self.assertAlmostEqual(0.38 + 0.15, ghost["center_m"][1], places=9)
        self.assertEqual({"form": "planar", "area_m2": 0.0016, "mitred": False}, answer["construct"]["touching"])

    def test_adding_a_part_returns_the_built_design_with_its_joints_measured(self):
        answer = self.add_post(self.cart)
        built = answer["candidates"][0]
        self.assertEqual(1, answer["generation"])
        self.assertEqual("post-1", answer["construct"]["select"])
        self.assertEqual(15, len(built["parts"]))
        self.assertIn(KEY, built["component_overrides"])
        self.assertEqual("15 parts · built part by part", built["label"])
        construction = built["construction"]
        self.assertTrue(construction["joints_authored"])
        self.assertEqual(17, len(construction["joints"]))
        self.assertEqual([], construction["unfastened"])
        self.assertEqual([], [j["id"] for j in construction["joints"] if j["open"]])
        # The rest of the bench still reads it: skin, buildability and the bill.
        self.assertEqual(15, len(built["skin"]["components"]))
        self.assertIn("buildability", built)
        mass = lambda c: sum(row["mass_kg"] for row in c["bom"]["materials"])  # noqa: E731
        self.assertAlmostEqual(0.04 * 0.04 * 0.3 * 700.0, mass(built) - mass(self.cart), places=3)

    def test_a_second_part_gets_its_own_name_and_a_part_can_stand_on_an_added_part(self):
        first = self.add_post(self.cart)["candidates"][0]
        post = next(p for p in first["parts"] if p["name"] == "post-1")
        top = post["center_m"][1] + 0.15
        answer = workshop_api.candidates(self.app, {
            **spec_of(first, "cart"),
            "construct": {"action": "add", "part": {"family": "surface", "material": "oak",
                                                    "parameters": {"width_m": 0.2, "thickness_m": 0.02, "depth_m": 0.2}},
                          "by": "face-y-", "onto": "post-1", "at_m": [post["center_m"][0], top, post["center_m"][2]],
                          "joint": {"kind": "fixed"}}})
        built = answer["candidates"][0]
        self.assertEqual("surface-1", answer["construct"]["select"])
        self.assertEqual(16, len(built["parts"]))
        second = self.add_post(built, at=(-0.2, 0.38, -0.2))["candidates"][0]
        self.assertIn("post-2", [p["name"] for p in second["parts"]])

    def test_it_is_saved_reopened_from_the_library_and_from_saved_designs_as_built(self):
        built = self.add_post(self.cart)["candidates"][0]
        saved = workshop_api.remember(self.app, {**spec_of(built, "cart"), "save_design": True,
                                                 "label": "Cart with a post"})
        reopened = workshop_api.open_workshop(self.app, {"library_item_id": saved["library_item"]["item_id"]})
        again = reopened["candidates"][0]
        self.assertEqual(15, len(again["parts"]))
        self.assertEqual(17, len(again["construction"]["joints"]))
        record, design = workshop_store.load(Path(self.app.workshop_store), saved["design"]["design_id"])
        self.assertEqual(15, len(design.parts))
        self.assertIn(KEY, record["component_overrides"])
        from_store = workshop_api.open_workshop(self.app, {"saved_design_id": saved["design"]["design_id"]})
        self.assertEqual(15, len(from_store["candidates"][0]["parts"]))

    def test_an_ordinary_edit_afterwards_keeps_what_was_built(self):
        built = self.add_post(self.cart)["candidates"][0]
        edited = workshop_api.candidates(self.app, {
            **spec_of(built, "cart"),
            "component_edit": {"part_name": "post-1", "action": "material", "material": "iron"}})["candidates"][0]
        self.assertEqual("iron", next(p for p in edited["parts"] if p["name"] == "post-1")["material"])
        self.assertEqual(17, len(edited["construction"]["joints"]))
        skinned = workshop_api.candidates(self.app, {
            **spec_of(edited, "cart"),
            "skin_edit": {"part_name": "post-1", "skin": {"profile": "round"}}})["candidates"][0]
        self.assertEqual(15, len(skinned["parts"]))
        self.assertIn(KEY, skinned["component_overrides"])

    def test_taking_a_part_off_and_unfastening_and_fastening_again(self):
        built = self.add_post(self.cart)["candidates"][0]
        without = workshop_api.candidates(self.app, {
            **spec_of(built, "cart"), "construct": {"action": "remove", "part_name": "handle"}})["candidates"][0]
        self.assertEqual(14, len(without["parts"]))
        self.assertEqual(15, len(without["construction"]["joints"]))
        loose = workshop_api.candidates(self.app, {
            **spec_of(without, "cart"),
            "construct": {"action": "unfasten", "a": "deck", "b": "post-1"}})["candidates"][0]
        self.assertEqual(["post-1"], loose["construction"]["unfastened"])
        held = workshop_api.candidates(self.app, {
            **spec_of(loose, "cart"),
            "construct": {"action": "fasten", "a": "deck", "b": "post-1", "kind": "fixed"}})["candidates"][0]
        self.assertEqual([], held["construction"]["unfastened"])

    def test_variants_are_not_offered_for_a_built_design(self):
        built = self.add_post(self.cart)["candidates"][0]
        with self.assertRaisesRegex(ValueError, "parts you put in or took off"):
            workshop_api.more_like_this(self.app, spec_of(built, "cart"))
        swept = workshop_api.candidates(self.app, {**spec_of(built, "cart"),
                                                   "sweeps": {"wheel_diameter_m": [0.2, 0.3, 0.4]}})
        self.assertEqual(1, len(swept["candidates"]))

    def test_a_saved_component_can_be_added_as_a_part(self):
        saved = workshop_api.library(self.app, {"action": "save_component", **spec_of(self.cart, "cart"),
                                                "part_name": "wheel-11", "name": "Cart wheel"})["library_item"]
        answer = workshop_api.candidates(self.app, {
            **spec_of(self.cart, "cart"),
            "construct": {"action": "add", "part": {"library_item_id": saved["item_id"]}, "by": "face-y-",
                          "onto": "deck", "at_m": [0.0, 0.38, 0.0], "joint": {"kind": "fixed"}}})
        wheel = next(p for p in answer["candidates"][0]["parts"] if p["name"] == answer["construct"]["select"])
        self.assertEqual(("wheel", "cylinder", [0.32, 0.06, 0.32]), (wheel["role"], wheel["shape"], wheel["size_m"]))

    def test_a_design_is_started_from_one_part_and_built_up(self):
        slab = {"name": "slab-1", "role": "top", "family": "surface", "shape": "box",
                "size_m": [0.8, 0.04, 0.5], "center_m": [0, 0.4, 0], "rotation_deg": [0, 0, 0], "material": "oak"}
        opened = workshop_api.open_workshop(self.app, {
            "kind": "custom", "component_overrides": {KEY: {"added": [slab], "joints_authored": True}}})
        self.assertEqual("custom", opened["kind"])
        self.assertNotIn("custom", [a["assembly"] for a in opened["assemblies"]])
        current = opened["candidates"][0]
        for x, z in [(0.37, 0.22), (-0.37, 0.22), (0.37, -0.22), (-0.37, -0.22)]:
            current = workshop_api.candidates(self.app, {
                **spec_of(current, "custom"),
                "construct": {"action": "add", "by": "face-y-", "onto": "slab-1", "at_m": [x, 0.38, z],
                              "part": {"family": "post", "length_m": 0.38,
                                       "parameters": {"width_m": 0.05, "depth_m": 0.05}},
                              "joint": {"kind": "fixed"}}})["candidates"][0]
        self.assertEqual(5, len(current["parts"]))
        self.assertEqual(4, len(current["construction"]["joints"]))
        self.assertAlmostEqual(0.0, current["measured"]["lowest_m"], places=9)
        self.assertEqual(4, len(current["measured"]["standing_on"]))
        matter = workshop_api.plan(self.app, {**spec_of(current, "custom"), "cell_size_m": 0.02,
                                              "visual": {"cell_size_m": 0.02}})
        self.assertGreater(matter["matter"]["total_cells"], 0)
        self.assertEqual([], matter["matter"]["missing_components"])

    def test_a_new_build_starts_from_one_part_standing_on_the_floor(self):
        opened = workshop_api.open_workshop(self.app, {"kind": "custom", "first_part": {
            "family": "surface", "material": "oak",
            "parameters": {"width_m": 0.8, "thickness_m": 0.04, "depth_m": 0.5}}})
        first = opened["candidates"][0]
        self.assertEqual("1 part · built part by part", first["label"])
        self.assertEqual(["surface-1"], [p["name"] for p in first["parts"]])
        self.assertAlmostEqual(0.0, first["measured"]["lowest_m"], places=9)
        self.assertTrue(first["construction"]["joints_authored"])
        with self.assertRaisesRegex(ValueError, "already has its parts"):
            workshop_api.open_workshop(self.app, {"kind": "cart", "first_part": {"family": "post"}})

    def push(self, candidate, **config):
        return workshop_api.plan(self.app, {**spec_of(candidate, "cart"), "bench_test": {
            "test": "force_probe", "config": {"component": "handle", "force_n": 3000.0, **config}}})["bench"]


    def test_a_push_says_which_joint_goes_first_once_the_design_has_joints_of_its_own(self):
        template = self.push(self.cart)["joint_screen"]
        self.assertFalse(template["available"])
        self.assertIn("no joints of its own", template["why"])

        shown = workshop_api.candidates(self.app, {**spec_of(self.cart, "cart"),
                                                   "construct": {"action": "adopt"}})["candidates"][0]
        answer = self.push(shown)
        screen = answer["joint_screen"]
        self.assertEqual("analytical-screen", screen["evidence"])
        # 3 kN down on a handle that overhangs the back axle tips the cart onto its back wheels.
        self.assertIn("tipping, on wheel-", screen["standing"])
        tips = screen["stops_standing_square"]
        self.assertEqual("tips", tips["does"])
        self.assertTrue(100.0 < tips["force_n"] < 300.0, tips)
        self.assertEqual(16, len(screen["joints"]))
        self.assertEqual(sorted(j["utilisation"] for j in screen["joints"])[::-1],
                         [j["utilisation"] for j in screen["joints"]])          # worst first
        first = screen["first_to_give"]
        self.assertIn("handle-arm", first["a"] + first["b"])
        self.assertLess(first["force_n"], 3000.0)
        self.assertEqual(2, len(screen["comes_apart_into"]))
        self.assertEqual(["handle", "handle-arm-1", "handle-arm-2"], sorted(screen["comes_apart_into"][1]))
        # The first layer is still there, and says what it always said.
        self.assertEqual("analytical-estimate", answer["evidence"])
        self.assertTrue(answer["load_paths"])

    def test_the_same_push_in_mid_air_and_in_another_direction_is_a_different_answer(self):
        shown = workshop_api.candidates(self.app, {**spec_of(self.cart, "cart"),
                                                   "construct": {"action": "adopt"}})["candidates"][0]
        # Pushed straight down through the centre of mass, so that it does not turn.
        parts = shown["parts"]
        whole = sum(p["mass_kg"] for p in parts)
        through_com = [sum(p["mass_kg"] * p["center_m"][k] for p in parts) / whole for k in (0, 2)]
        spot = [through_com[0], 0.38, through_com[1]]
        resting = self.push(shown, component="deck", point_m=spot)["joint_screen"]
        free = self.push(shown, component="deck", point_m=spot, standing="free")["joint_screen"]
        sideways = self.push(shown, push="+x")["joint_screen"]
        self.assertEqual("resting on the floor", resting["standing"])
        self.assertEqual("free", free["standing"])
        # Standing, the chassis's weight and the whole push go out through the four
        # bearings to the floor. In mid-air the cart falls freely, so its weight
        # loads nothing, and the bearings carry only the share of the push that
        # accelerates the two wheelsets beyond them.
        through = lambda s: sum(j["load"]["shear_n"] for j in s["joints"] if j["kind"] == "bearing")  # noqa: E731
        mass = {p["name"]: p["mass_kg"] for p in shown["parts"]}
        wheelsets = sum(m for name, m in mass.items() if name.startswith(("axle", "wheel")))
        total = sum(mass.values())
        self.assertAlmostEqual((total - wheelsets) * 9.80665 + 3000.0, through(resting), delta=0.5)
        self.assertAlmostEqual(3000.0 * wheelsets / total, through(free), delta=0.5)
        self.assertEqual([1.0, 0.0, 0.0], sideways["blow"]["direction"])
        with self.assertRaisesRegex(ValueError, "push must be one of"):
            self.push(shown, push="sideways")

    def test_what_cannot_be_done_is_said(self):
        for construct, why in [
            ({"action": "add", "part": dict(POST), "by": "face-y-", "onto": "nothing", "at_m": [0, 0, 0]}, "click the part"),
            ({"action": "add", "by": "face-y-", "onto": "deck", "at_m": [0, 0.38, 0]}, "which part to add"),
            ({"action": "add", "part": dict(POST), "by": "lid", "onto": "deck", "at_m": [0, 0.38, 0]}, "not a face"),
            ({"action": "remove", "part_name": "ghost"}, "no part"),
            ({"action": "fasten", "a": "deck", "b": "wheel-11", "kind": "fixed"}, "does not touch"),
            ({"action": "paint"}, "action must be"),
        ]:
            with self.assertRaisesRegex(ValueError, why, msg=str(construct)):
                workshop_api.candidates(self.app, {**spec_of(self.cart, "cart"), "construct": construct})


if __name__ == "__main__":
    unittest.main()
