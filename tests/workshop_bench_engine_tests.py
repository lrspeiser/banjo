"""Real-engine acceptance cases for Workshop's functional bench.

CI supplies BANJO_LIVE_ENGINE after building banjo_live_world_run. These are
small isolated worlds compiled from the selected Workshop products, never the
owner's live room.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "playground"))

import workshop_bench  # noqa: E402
from mcp.workshop import assemble  # noqa: E402

ENGINE = Path(os.environ["BANJO_LIVE_ENGINE"]).resolve() if os.environ.get("BANJO_LIVE_ENGINE") else None


@unittest.skipUnless(ENGINE is not None and ENGINE.is_file(), "the live world runner is not built")
class TheWorkshopRunsRealThings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.app = type("App", (), {"engine_path": ENGINE, "runs_path": root / "runs"})()

    def tearDown(self): self.tmp.cleanup()

    def test_selected_kettle_holds_water_and_heat_below_warms_it(self):
        design = assemble("kettle", design_id="bench-kettle",
                          parameters={"width_m": 0.28, "depth_m": 0.24,
                                      "vessel_height_m": 0.18,
                                      "wall_thickness_m": 0.01,
                                      "material": "iron"})
        result = workshop_bench.run(self.app, design, {
            "test": "kettle_heat",
            "config": {"water_kg": 1.0, "heater_power_w": 5000.0, "duration_s": 60.0},
        })
        measured = result["measured"]
        self.assertGreater(result["design"]["capacity_l"], 1.0, result)
        self.assertEqual("iron", result["design"]["material"], result)
        self.assertIsNotNone(measured["water_start_k"], result)
        self.assertIsNotNone(measured["water_end_k"], result)
        self.assertGreater(measured["water_end_k"], measured["water_start_k"] + 0.01, result)
        self.assertGreater((measured["ledger"] or {}).get("heater_in_j", 0), 0, result)

    def test_selected_cart_moves_and_both_axles_turn_in_real_joints(self):
        design = assemble("cart", design_id="bench-cart")
        result = workshop_bench.run(self.app, design, {
            "test": "cart_roll", "config": {"speed_m_s": 0.8, "duration_s": 0.4},
        })
        measured = result["measured"]
        # Four, not two: each axle is carried by TWO bearing mounts, which is
        # how an axle is actually borne. The trial simplifies each pair into one
        # hinge, so the design has four bearing relationships and the scratch
        # world has two rotating joints; this asserted the realised count
        # against the design's.
        self.assertEqual(4, result["design"]["bearing_relationships"], result)
        # The pins must actually be hung. Session() starts a world without
        # them, so this trial once reported joint_count 0 with no axle turns
        # and a chassis that slid instead of rolling.
        self.assertGreater(measured["joint_count"], 0, result)
        self.assertGreater(measured["chassis_delta_m"][2], 0.03, result)
        self.assertEqual(2, len(measured["axle_turns"]), result)
        self.assertTrue(all(abs(row["degrees"]) > 2.0 for row in measured["axle_turns"]), result)

    def test_an_edited_machine_control_moves_the_load_and_draws_energy(self):
        design = assemble("table", design_id="bench-source")
        result = workshop_bench.run(self.app, design, {
            "test": "machine_control",
            "config": {"power": True, "direction": 1, "setting": 60.0,
                       "duration_s": 0.8, "load_kg": 20.0},
        })
        measured = result["measured"]
        self.assertEqual("applied", measured["acknowledgement"], result)
        self.assertEqual(1, measured["control"].get("direction"), result)
        self.assertAlmostEqual(0.6, measured["control"].get("setting"), delta=0.01, msg=result)
        self.assertGreater(measured["load_delta_y_m"], 0.01, result)
        self.assertGreater(measured["battery"].get("given_j", 0), 0, result)
        self.assertGreater(abs(measured["motor"].get("speed_rad_s", 0)), 0.01, result)


if __name__ == "__main__": unittest.main()
