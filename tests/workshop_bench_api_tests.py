"""Workshop functional bench through the same API surface the browser uses."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "playground"))

import workshop_api  # noqa: E402


class App:
    def __init__(self, root: Path) -> None:
        self.workshop_store = root / "workshop"
        self.workshop_db = root / "banjo.db"
        self.runs_path = root / "runs"
        self.engine_path = root / "engine"
        self.api_key = ""


class BenchAPI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = App(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_opening_workshop_describes_product_tests_and_visual_load(self):
        opened = workshop_api.open_workshop(self.app, {"kind": "table"})
        offered = {test["test"]: test for test in opened["bench_tests"]}
        for general in ("machine_control", "runtime_contract"):
            self.assertIn(general, offered, "a test with no kinds suits anything")
        for elsewhere in ("kettle_heat", "cart_roll"):
            self.assertNotIn(elsewhere, offered, f"{elsewhere} is not for a table")
        self.assertIn("declared_static_load", offered)
        self.assertTrue(offered["declared_static_load"]["visual_playback"])
        self.assertIn("cart_roll",
                      {t["test"] for t in workshop_api.open_workshop(
                          self.app, {"kind": "cart"})["bench_tests"]})
        self.assertIn("kettle_heat",
                      {t["test"] for t in workshop_api.open_workshop(
                          self.app, {"kind": "kettle"})["bench_tests"]})
        for test in opened["bench_tests"]:
            self.assertTrue(test.get("name"), f"{test['test']} needs a readable name")
        self.assertEqual([], opened["bench_presets"])

        saved = workshop_api.library(self.app, {
            "action": "save_bench_preset", "name": "Gentle lift",
            "test": "machine_control", "config": {"setting": 35, "direction": 1},
        })
        self.assertEqual("Gentle lift", saved["bench_preset"]["name"])
        again = workshop_api.open_workshop(self.app, {"kind": "table"})
        self.assertEqual("Gentle lift", again["bench_presets"][0]["name"])

    def test_plan_runs_requested_bench_fixture_and_keeps_normal_materialization(self):
        evidence = {"schema": "banjo.workshop-bench.v1", "test": "machine_control",
                    "evidence": "engine-trial", "measured": {"load_delta_y_m": 0.2}}
        with mock.patch.object(workshop_api.workshop_bench, "run", return_value=evidence) as run:
            answer = workshop_api.plan(self.app, {
                "kind": "table", "design_id": "candidate",
                "bench_test": {"test": "machine_control", "config": {"setting": 50}},
            })
        self.assertEqual("not-committed", answer["commit"]["status"])
        self.assertEqual(evidence, answer["bench"])
        self.assertEqual("candidate", run.call_args.args[1].design_id)
        self.assertEqual("machine_control", run.call_args.args[2]["test"])

    def test_visual_plan_returns_canonical_engine_grid_cells_and_separate_skin(self):
        answer = workshop_api.plan(self.app, {
            "kind": "table", "design_id": "visual-table", "parameters": {},
            "visual": {"cell_size_m": 0.08, "exterior_only": True},
        })
        self.assertEqual("banjo.product-skin.v1", answer["skin"]["schema"])
        matter = answer["matter"]
        self.assertEqual("banjo.workshop-matter.v2", matter["schema"])
        self.assertEqual("center=(index+0.5)*cell_size_m", matter["grid_convention"])
        self.assertTrue(matter["engine_ready"])
        self.assertEqual(64, len(matter["physics_hash"]))
        self.assertEqual(64, len(matter["artifact_hash"]))
        self.assertGreater(matter["total_cells"], 0)
        self.assertGreater(matter["shown_cells"], 0)
        self.assertLessEqual(matter["shown_cells"], matter["total_cells"])
        self.assertAlmostEqual(0.08, matter["cell_size_m"])
        for item in matter["cells"][:20]:
            self.assertEqual(3, len(item["grid"]))
            self.assertEqual(3, len(item["center_m"]))
            self.assertTrue(item["exposed"])
            self.assertTrue(item["exposed_faces"])
            expected = [(item["grid"][axis] + 0.5) * matter["cell_size_m"] for axis in range(3)]
            for got, want in zip(item["center_m"], expected):
                self.assertAlmostEqual(want, got, places=8)

    def test_exterior_only_changes_display_not_the_physics_hash(self):
        base = {"kind": "table", "design_id": "visual-table", "parameters": {}}
        all_cells = workshop_api.plan(self.app, {
            **base, "visual": {"cell_size_m": 0.04, "exterior_only": False}})["matter"]
        exterior = workshop_api.plan(self.app, {
            **base, "visual": {"cell_size_m": 0.04, "exterior_only": True}})["matter"]
        self.assertEqual(all_cells["physics_hash"], exterior["physics_hash"])
        self.assertEqual(all_cells["artifact_hash"], exterior["artifact_hash"])
        self.assertEqual(all_cells["total_cells"], exterior["total_cells"])
        self.assertLessEqual(exterior["shown_cells"], all_cells["shown_cells"])

    def test_physical_curve_changes_canonical_matter_and_appearance_curve_does_not(self):
        opened = workshop_api.open_workshop(self.app, {"kind": "cart"})
        candidate = opened["candidates"][0]
        handle = next(part for part in candidate["parts"] if part["role"] == "handle")

        baseline = workshop_api.plan(self.app, {
            "kind": "cart", "design_id": candidate["design_id"],
            "parameters": candidate["parameters"],
            "component_overrides": candidate.get("component_overrides") or {},
            "visual": {"cell_size_m": 0.04},
        })["matter"]

        cosmetic = workshop_api.candidates(self.app, {
            "kind": "cart", "design_id": candidate["design_id"],
            "parameters": candidate["parameters"],
            "component_overrides": candidate.get("component_overrides") or {},
            "skin_edit": {"part_name": handle["name"], "scope": "this",
                          "skin": {"profile": "curve", "bend_m": 0.12,
                                   "physical": False, "roughness": 0.4}},
        })["candidates"][0]
        cosmetic_matter = workshop_api.plan(self.app, {
            "kind": "cart", "design_id": cosmetic["design_id"],
            "parameters": cosmetic["parameters"],
            "component_overrides": cosmetic["component_overrides"],
            "visual": {"cell_size_m": 0.04},
        })["matter"]
        self.assertEqual(baseline["physics_hash"], cosmetic_matter["physics_hash"])

        edited = workshop_api.candidates(self.app, {
            "kind": "cart", "design_id": candidate["design_id"],
            "parameters": candidate["parameters"],
            "component_overrides": candidate.get("component_overrides") or {},
            "skin_edit": {"part_name": handle["name"], "scope": "this",
                          "skin": {"profile": "curve", "bend_m": 0.12,
                                   "physical": True, "roughness": 0.4}},
        })
        changed = edited["candidates"][0]
        descriptor = next(item for item in changed["skin"]["components"]
                          if item["component"] == handle["name"])
        self.assertEqual("bezier_tube", descriptor["kind"])
        self.assertTrue(descriptor["physical"])
        physical = workshop_api.plan(self.app, {
            "kind": "cart", "design_id": changed["design_id"],
            "parameters": changed["parameters"],
            "component_overrides": changed["component_overrides"],
            "visual": {"cell_size_m": 0.04},
        })["matter"]
        self.assertIn(handle["name"], physical["physical_curve_components"])
        self.assertGreater(physical["component_cell_counts"][handle["name"]], 0)
        self.assertNotEqual(baseline["physics_hash"], physical["physics_hash"])


if __name__ == "__main__":
    unittest.main()
