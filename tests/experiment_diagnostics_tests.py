from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))
from experiment_diagnostics import build_diagnostics


def fixture(duration: float, ys: list[float], *, completed: int = 240):
    drop = {"target_dimensions_m": [.24, .36, .04], "projectile": "iron_ball",
            "projectile_dimensions_m": [.08, .08, .08], "support": "free_on_ground",
            "impact_offset_m": [0, 0], "heights_m": [1.391], "representation": "rigid",
            "resolution": [4, 4, 2]}
    plan = {"experiment": "drop_test", "duration_s": duration, "drop": drop}
    objects = []
    bodies = []
    for lane, material in enumerate(("glass", "oak", "iron")):
        x = (lane - 1) * .45
        objects += [{"id": lane*2+1, "name": material, "material": material, "shape": "box",
                     "dimensions_m": [.24, .36, .04], "position_m": [x, .02, 0],
                     "representation": "rigid"},
                    {"id": lane*2+2, "name": "ball", "material": "iron", "shape": "sphere",
                     "dimensions_m": [.08]*3, "position_m": [x, 1.471, 0],
                     "representation": "rigid"}]
        bodies += [{"id": f"{lane*2+1}:0", "object_id": lane*2+1, "material_id": material},
                   {"id": f"{lane*2+2}:0", "object_id": lane*2+2, "material_id": "iron"}]
    package = {"objects": objects, "materials": [{"id": x} for x in ("glass", "oak", "iron")]}
    frames = []
    for index, y in enumerate(ys):
        poses = []
        for lane in range(3):
            x = (lane - 1) * .45
            poses += [{"id": f"{lane*2+1}:0", "position_m": [x, .02, 0]},
                      {"id": f"{lane*2+2}:0", "position_m": [x, y, 0]}]
        frames.append({"time_s": duration * index / (len(ys)-1), "poses": poses})
    recording = {"status": "complete", "error": "", "requested_steps": 240,
                 "completed_steps": completed, "physical_response_validated": False,
                 "bodies": bodies, "frames": frames, "report": {"elapsed_s": duration}}
    return plan, package, recording


class DiagnosticsTests(unittest.TestCase):
    def test_half_second_is_too_short_for_high_drop(self):
        result = build_diagnostics(*fixture(.5, [1.491, 1.2, .8]))
        self.assertEqual(result["schema"], "banjo.experiment-diagnostics.v1")
        expected = result["expectations"][0]
        self.assertAlmostEqual(expected["estimated_flight_time_s"], math.sqrt(2*1.391/9.81))
        self.assertEqual(result["checks"][0]["observation"], "too_short")
        self.assertTrue(all(c["status"] == "fail" for c in result["checks"] if "clearance" in c["check"]))

    def test_longer_recording_reaches_gap_and_has_reversal_evidence(self):
        result = build_diagnostics(*fixture(1.04, [1.491, .5, .081, .06, .095]))
        lanes = [c for c in result["checks"] if "clearance" in c["check"]]
        self.assertTrue(all(c["status"] == "pass" for c in lanes))
        self.assertTrue(all(c["evidence"]["sampled_velocity_reversal"] for c in lanes))
        self.assertIn("no solver contact proof", lanes[0]["scope"])
        json.dumps(result, allow_nan=False)

    def test_short_execution_and_summary_bounds(self):
        plan, package, recording = fixture(1.04, [1.491, .8], completed=17)
        package["objects"] *= 20
        result = build_diagnostics(plan, package, recording)
        completion = next(c for c in result["checks"] if c["check"] == "execution_completion")
        self.assertEqual((completion["status"], completion["observation"]), ("fail", "execution_stopped"))
        self.assertEqual(len(result["package"]["scene"]["objects"]), 12)
        self.assertTrue(result["package"]["scene"]["objects_truncated"])

    def test_compiled_package_selects_the_sweep_case_height(self):
        plan, package, recording = fixture(1.04, [1.491, .5])
        plan["drop"]["heights_m"] = [.2, 1.391]
        result = build_diagnostics(plan, package, recording)
        self.assertAlmostEqual(result["expectations"][0]["height_m"], 1.391)
        self.assertEqual(result["expectations"][0]["height_source"],
                         "compiled_package_initial_clearance")

    def test_report_and_validity_are_bounded_native_facts(self):
        plan, package, recording = fixture(1.04, [1.491, .5])
        recording.pop("physical_response_validated")
        recording["report"] = {
            "state_valid": True,
            "physical_response_validated": False,
            "temporal_resolution": {"resolved": False, "material_validation": False},
            "samples": list(range(100)),
            "message": "x" * 5000,
        }
        result = build_diagnostics(plan, package, recording)
        self.assertEqual(result["validity"], {
            "temporal_resolution": {"resolved": False, "material_validation": False},
            "state_valid": True, "material_validation": False,
            "physical_response_validated": False,
        })
        self.assertEqual(len(result["native_facts"]["report"]["samples"]), 65)
        self.assertEqual(result["native_facts"]["report"]["samples"][-1],
                         {"truncated_items": 36})
        self.assertEqual(len(result["native_facts"]["report"]["message"]), 4096)

    def test_trajectory_analysis_includes_frames_after_sixty_four(self):
        # Closest approach and rebound occur only in the terminal samples. A
        # presentation/output bound must not truncate the analysis trajectory.
        ys = [1.5 - index * .005 for index in range(66)] + [.5, .081, .06, .095]
        result = build_diagnostics(*fixture(1.04, ys))
        lanes = [check for check in result["checks"] if "clearance" in check["check"]]
        self.assertTrue(all(check["status"] == "pass" for check in lanes))
        self.assertTrue(all(check["evidence"]["sampled_velocity_reversal"] for check in lanes))
        self.assertAlmostEqual(lanes[0]["evidence"]["minimum_vertical_gap_m"], -.02)


if __name__ == "__main__":
    unittest.main()
