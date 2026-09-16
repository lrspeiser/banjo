"""The Workshop's server side: one model behind /api/workshop/*.

These run the module directly, with no socket and no engine, because every
workshop answer is pure computation over mcp/workshop.py.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "playground"))

import workshop_api  # noqa: E402


class Bench:
    """Just enough of the server's app object for the workshop to answer."""

    def __init__(self, where: Path) -> None:
        self.workshop_store = where


class Opening(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Bench(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_opening_a_bench_offers_a_library_and_a_first_set(self):
        answer = workshop_api.open_workshop(self.app, {"kind": "table"})
        self.assertTrue(answer["session"]["outside_paused"])
        self.assertEqual(6, len(answer["candidates"]))
        self.assertGreaterEqual(len(answer["families"]), 10)
        self.assertEqual(6, len(answer["assemblies"]))

    def test_every_candidate_arrives_measured_and_ready_to_draw(self):
        answer = workshop_api.open_workshop(self.app, {"kind": "table"})
        for candidate in answer["candidates"]:
            self.assertTrue(candidate["label"])
            self.assertTrue(candidate["parts"])
            for part in candidate["parts"]:
                self.assertEqual(3, len(part["size_m"]))
                self.assertEqual(3, len(part["center_m"]))
                self.assertEqual(3, len(part["rotation_deg"]))
                self.assertIn(part["shape"], {"box", "tapered", "cylinder"})
            measured = candidate["measured"]
            self.assertGreater(measured["mass_kg"], 0)
            self.assertTrue(measured["stands_up"])
            self.assertIn("tip_angle_deg", measured)

    def test_every_assembly_the_bench_offers_can_be_opened(self):
        for described in workshop_api.library()["assemblies"]:
            with self.subTest(described["assembly"]):
                answer = workshop_api.candidates(self.app, {"kind": described["assembly"]})
                self.assertTrue(answer["candidates"])
                self.assertTrue(all(c["measured"]["stands_up"] for c in answer["candidates"]))

    def test_an_assembly_the_bench_does_not_know_is_refused(self):
        with self.assertRaises(KeyError):
            workshop_api.open_workshop(self.app, {"kind": "spaceship"})

    def test_a_parameter_the_assembly_does_not_have_is_refused(self):
        with self.assertRaises(KeyError):
            workshop_api.candidates(self.app, {"kind": "table",
                                               "parameters": {"leg_colour": "red"}})

    def test_a_parameter_outside_its_bounds_is_refused(self):
        with self.assertRaises(ValueError):
            workshop_api.candidates(self.app, {"kind": "table",
                                               "parameters": {"splay_deg": 80}})


class MoreLikeThis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Bench(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_it_returns_a_new_generation_around_the_chosen_one(self):
        opened = workshop_api.open_workshop(self.app, {"kind": "table"})
        chosen = opened["candidates"][2]
        more = workshop_api.more_like_this(
            self.app, {"kind": "table", "generation": opened["generation"],
                       "parameters": chosen["parameters"]})
        self.assertEqual(opened["generation"] + 1, more["generation"])
        self.assertEqual(6, len(more["candidates"]))
        sections = {c["parameters"]["leg_section_m"] for c in more["candidates"]}
        self.assertGreater(len(sections), 1)

    def test_nudging_never_leaves_the_parameter_bounds(self):
        more = workshop_api.more_like_this(
            self.app, {"kind": "table", "parameters": {"leg_section_m": 0.3,
                                                       "splay_deg": 25}})
        for candidate in more["candidates"]:
            self.assertLessEqual(candidate["parameters"]["leg_section_m"], 0.3)
            self.assertLessEqual(candidate["parameters"]["splay_deg"], 25)


class Plans(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Bench(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_plan_is_never_a_commit(self):
        plan = workshop_api.plan(self.app, {"kind": "chair", "design_id": "c1"})
        self.assertEqual("not-committed", plan["commit"]["status"])
        self.assertIn("fingerprint", plan)
        self.assertIn("measured", plan)

    def test_an_absurd_cell_size_is_refused(self):
        for cell in (0, 1.0, "wide"):
            with self.assertRaises(ValueError):
                workshop_api.plan(self.app, {"kind": "table", "cell_size_m": cell})


class Remembering(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Bench(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_feedback_outlives_the_browser_that_gave_it(self):
        # localStorage made a preference a note on one machine.
        self.assertEqual(0, workshop_api.remembered(self.app)["kept"])
        saved = workshop_api.remember(self.app, {
            "kind": "table", "design_id": "table-g0-v3", "rating": 5,
            "note": "widest base of the six"})
        self.assertEqual(1, saved["kept"])
        self.assertEqual(5, saved["saved"]["rating"])
        self.assertIn("fingerprint", saved["saved"])
        again = workshop_api.remembered(self.app)
        self.assertEqual(1, again["kept"])
        self.assertEqual("widest base of the six", again["feedback"][0]["note"])

    def test_a_rating_outside_one_to_five_is_refused(self):
        with self.assertRaises(ValueError):
            workshop_api.remember(self.app, {"kind": "table", "rating": 9})

    def test_a_design_id_that_could_escape_the_store_is_refused(self):
        for bad in ("../escape", "a/b", ".", "x" * 200):
            with self.assertRaises(ValueError):
                workshop_api.remember(self.app, {"kind": "table", "design_id": bad})

    def test_a_note_cannot_grow_without_bound(self):
        saved = workshop_api.remember(self.app, {"kind": "table", "note": "n" * 9000})
        self.assertEqual(2000, len(saved["saved"]["note"]))


class NothingTouchesTheWorld(unittest.TestCase):
    def test_the_workshop_module_never_reaches_for_the_engine(self):
        source = (ROOT / "playground" / "workshop_api.py").read_text(encoding="utf-8")
        for forbidden in ("live_session", "run_action", "subprocess", "banjo.dll",
                          "BANJO_LIBRARY", "app.room", "world_chat"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
