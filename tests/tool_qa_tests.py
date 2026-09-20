"""Native use cases, truthful unsupported outcomes, artifact and HTTP boundaries."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/"playground"), str(ROOT/"tests")]
import tool_qa as qa
from workbench_tests import WorkbenchTestCase


class Contracts(unittest.TestCase):
    def test_matched_tools_and_commands_keep_all_three_reference_materials(self):
        self.assertEqual(len(qa.cases()),6)
        for ground in ("soil","rock"):
            cases = [c for c in qa.cases() if c["ground"] == ground]
            self.assertEqual({c["material"] for c in cases},{"glass","oak","iron"})
            recipes = [qa.recipe(c) for c in cases]
            self.assertTrue(all(r["commands"] == recipes[0]["commands"] for r in recipes))
            self.assertTrue(all(r["spec"]["cells"] == recipes[0]["spec"]["cells"] for r in recipes))

    def test_paths_custom_code_and_unknown_inputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            manager = qa.Manager(SimpleNamespace(runs_path=Path(raw),engine_path=None))
            self.addCleanup(manager.shutdown)
            for ids in ([],["../outside"],["pick-oak-soil"]*2,[True],"all"):
                with self.assertRaises(ValueError):qa.select(ids)
            with self.assertRaises(ValueError):manager.start({"script":"anything"})
            with self.assertRaises(ValueError):manager.case("../outside","pick-oak-soil")
            with self.assertRaises(ValueError):manager.case("a"*32,"pick-oak-soil","../outside")

    def test_rigid_cell_transform_preserves_native_rotation(self):
        self.assertEqual(qa.rotate([1,0,0,0],[1,2,3]),[1,2,3])
        for actual,expected in zip(qa.rotate([0,0,0,1],[1,2,3]),[-1,-2,3]):
            self.assertAlmostEqual(actual,expected)


class HTTP(WorkbenchTestCase):
    def test_tools_page_and_catalog_leave_world_untouched(self):
        app = self.start(); original = app.live
        self.assertEqual(len(self.get(app,"/api/tool-qa")["cases"]),6)
        status,content,raw = self.request(app,"GET","/tool-qa")
        self.assertEqual(status,200); self.assertIn("text/html",content)
        self.assertIn(b"tool-qa.js",raw)
        self.assertIs(original,app.live)


@unittest.skipUnless(os.environ.get("BANJO_TRIAL_ENGINE"),"Set BANJO_TRIAL_ENGINE for native tool QA")
class Native(unittest.TestCase):
    def test_six_real_trials_show_motion_contact_and_explicit_unsupported_rock(self):
        with tempfile.TemporaryDirectory() as raw:
            folder=Path(raw)/"run"
            report=qa.run_suite(Path(os.environ["BANJO_TRIAL_ENGINE"]),folder)
            self.assertEqual(report["completed"],6)
            self.assertEqual(report["status"],"unsupported")
            for r in report["results"]:
                expected="unsupported" if r["ground"]=="rock" and r["material"]!="oak" else "passed"
                self.assertEqual(r["status"],expected,r)
                self.assertEqual(r["measured"]["mass_residual_kg"],0)
                self.assertLessEqual(r["measured"]["max_hand_force_n"],800.001)
                playback=qa.artifacts.read_json(folder/r["id"]/"playback.json")
                self.assertEqual(len(playback["frames"]),541)
                self.assertEqual(len(playback["bodies"]),28)
                self.assertNotEqual(playback["frames"][0]["poses"][0]["position_m"],
                                    playback["frames"][60]["poses"][0]["position_m"])
                self.assertTrue(all(len(f["poses"])==28 for f in playback["frames"]))
                if r["ground"]=="soil":self.assertGreaterEqual(r["measured"]["depth_m"],.03)
                else:self.assertEqual(r["measured"]["depth_m"],0)

    def test_cancelled_trial_does_not_claim_success(self):
        with tempfile.TemporaryDirectory() as raw:
            event=threading.Event();event.set()
            r=qa.run_case(Path(os.environ["BANJO_TRIAL_ENGINE"]),qa.cases()[0],Path(raw)/"case",event)
            self.assertEqual(r["status"],"cancelled")


if __name__ == "__main__": unittest.main()
