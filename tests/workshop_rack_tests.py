#!/usr/bin/env python3
"""The rack: what a design takes, what you hold, and what making it spends.

The rule these tests hold to is that designing is free and making is not. A
design is drawn, measured and offered as a candidate whatever the rack holds;
only ``take_from_rack`` -- which ``workshop_install.commit`` is the one caller
of -- refuses, and it refuses all of it or none.
"""
from __future__ import annotations
from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "playground"))

from mcp.workshop import assemble  # noqa: E402
import workshop_api_core  # noqa: E402
import workshop_library  # noqa: E402


def _design(**parameters):
    return assemble("table", design_id="t", parameters=parameters or None)


class Rack(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.app = types.SimpleNamespace(runs_path=root / "runs", workshop_owner_id="owner")
        self.app.runs_path.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def held(self, material):
        rows = {r["material"]: r["mass_kg"] for r in workshop_library.rack(self.app)["materials"]}
        return rows[material]

    def test_the_rack_starts_with_what_the_default_says(self):
        self.assertEqual(workshop_library.DEFAULT_RACK["oak"], self.held("oak"))
        self.assertEqual(workshop_library.DEFAULT_RACK["iron"], self.held("iron"))

    def test_a_design_the_rack_covers_says_so_and_names_no_shortfall(self):
        workshop_library.set_rack(self.app, "oak", 500.0)
        needs = workshop_library.what_it_needs(self.app, _design())
        self.assertTrue(needs["enough"])
        self.assertEqual([], needs["missing"])
        self.assertIn("the rack has all of it", needs["says"])
        for row in needs["materials"]:
            self.assertTrue(row["enough"])
            self.assertEqual(0.0, row["short_kg"])

    def test_a_design_the_rack_cannot_cover_names_the_material_and_the_kilograms(self):
        workshop_library.set_rack(self.app, "oak", 1.0)
        needs = workshop_library.what_it_needs(self.app, _design())
        self.assertFalse(needs["enough"])
        missing = {row["material"]: row["short_kg"] for row in needs["missing"]}
        self.assertIn("oak", missing)
        row = next(r for r in needs["materials"] if r["material"] == "oak")
        self.assertAlmostEqual(row["needed_kg"] - 1.0, missing["oak"], places=3)
        self.assertIn("short", needs["says"])
        self.assertIn("oak", needs["says"])

    def test_an_empty_rack_never_stops_a_design_being_drawn_or_measured(self):
        for material in list(workshop_library.DEFAULT_RACK):
            workshop_library.set_rack(self.app, material, 0.0)
        answer = workshop_api_core.candidates(self.app, {"kind": "table"})
        candidate = answer["candidates"][0]
        self.assertTrue(candidate["parts"])
        self.assertGreater(candidate["measured"]["mass_kg"], 0.0)
        self.assertFalse(candidate["needs"]["enough"])
        plan = workshop_api_core.plan(self.app, {"kind": "table"})
        self.assertTrue(plan["objects"] or plan.get("wireframe_objects"))
        self.assertFalse(plan["needs"]["enough"])

    def test_making_it_takes_the_stock_out_of_the_rack(self):
        workshop_library.set_rack(self.app, "oak", 500.0)
        needs = workshop_library.what_it_needs(self.app, _design())
        oak = next(r for r in needs["materials"] if r["material"] == "oak")["needed_kg"]
        answer = workshop_library.take_from_rack(self.app, needs)
        self.assertAlmostEqual(500.0 - oak, self.held("oak"), places=3)
        took = {r["material"]: r["took_kg"] for r in answer["took"]}
        self.assertAlmostEqual(oak, took["oak"], places=3)

    def test_a_short_rack_refuses_and_spends_nothing(self):
        workshop_library.set_rack(self.app, "oak", 1.0)
        needs = workshop_library.what_it_needs(self.app, _design())
        with self.assertRaises(ValueError) as caught:
            workshop_library.take_from_rack(self.app, needs)
        self.assertIn("short", str(caught.exception))
        self.assertIn("oak", str(caught.exception))
        self.assertEqual(1.0, self.held("oak"))

    def test_the_rack_is_read_again_when_it_is_spent_not_when_it_was_asked(self):
        workshop_library.set_rack(self.app, "oak", 500.0)
        needs = workshop_library.what_it_needs(self.app, _design())
        self.assertTrue(needs["enough"])
        workshop_library.set_rack(self.app, "oak", 0.5)   # somebody else spent it
        with self.assertRaises(ValueError):
            workshop_library.take_from_rack(self.app, needs)
        self.assertEqual(0.5, self.held("oak"))

    def test_taking_the_same_design_twice_runs_the_rack_down_and_then_refuses(self):
        needs = workshop_library.what_it_needs(self.app, _design())
        oak = next(r for r in needs["materials"] if r["material"] == "oak")["needed_kg"]
        workshop_library.set_rack(self.app, "oak", oak * 1.5)
        workshop_library.take_from_rack(self.app, workshop_library.what_it_needs(self.app, _design()))
        with self.assertRaises(ValueError):
            workshop_library.take_from_rack(self.app, workshop_library.what_it_needs(self.app, _design()))
        self.assertAlmostEqual(oak * 0.5, self.held("oak"), places=3)

    def test_the_bench_answers_what_it_needs_without_a_design_change(self):
        answer = workshop_api_core.library(self.app, {"action": "needs", "kind": "table"})
        self.assertIn("needs", answer)
        self.assertIn("materials", answer["rack"])
        self.assertEqual(answer["needs"]["says"],
                         workshop_library.what_it_needs(self.app, _design())["says"])

    def test_the_rack_can_be_stocked_and_the_shortfall_goes_away(self):
        workshop_library.set_rack(self.app, "oak", 0.0)
        self.assertFalse(workshop_library.what_it_needs(self.app, _design())["enough"])
        workshop_library.set_rack(self.app, "oak", 999.0)
        self.assertTrue(workshop_library.what_it_needs(self.app, _design())["enough"])


class ChatSaysWhatIsMissing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.app = types.SimpleNamespace(runs_path=root / "runs", workshop_owner_id="owner")
        self.app.runs_path.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _state(self):
        import workshop_chat
        candidate = workshop_api_core.candidates(self.app, {"kind": "table"})["candidates"][0]
        return workshop_chat._State(self.app, candidate, None, ["oak"], [])

    def test_the_tool_is_offered_to_the_model(self):
        import workshop_chat
        names = {tool["name"] for tool in workshop_chat._tool_definitions(["oak"])}
        self.assertIn("what_it_needs", names)

    def test_the_tool_answers_with_the_shortfall_in_words(self):
        workshop_library.set_rack(self.app, "oak", 0.2)
        result = self._state().execute("what_it_needs", {})
        self.assertFalse(result["enough"])
        self.assertIn("oak", result["summary"])
        self.assertIn("short", result["summary"])
        self.assertIn("cannot be made", result["note"])

    def test_the_tool_says_so_when_the_rack_covers_it(self):
        workshop_library.set_rack(self.app, "oak", 500.0)
        result = self._state().execute("what_it_needs", {})
        self.assertTrue(result["enough"])
        self.assertEqual([], result["missing"])


if __name__ == "__main__":
    unittest.main()
