"""Real-engine acceptance cases for Workshop's functional bench.

CI supplies BANJO_LIVE_ENGINE after building banjo_live_world_run. These are
small isolated worlds, not the owner's live room.
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
        self.design = assemble("table", design_id="bench-source")

    def tearDown(self):
        self.tmp.cleanup()

    def test_heat_below_a_kettle_warms_its_contained_water(self):
        result = workshop_bench.run(self.app, self.design, {
            "test": "kettle_heat",
            "config": {"water_kg": 1.0, "heater_power_w": 5000.0,
                       "duration_s": 60.0, "kettle_material": "iron"},
        })
        measured = result["measured"]
        self.assertIsNotNone(measured["water_start_k"], result)
        self.assertIsNotNone(measured["water_end_k"], result)
        self.assertGreater(measured["water_end_k"], measured["water_start_k"] + 0.01, result)
        self.assertGreater((measured["ledger"] or {}).get("heater_in_j", 0), 0, result)

    def test_an_edited_machine_control_moves_the_load_and_draws_energy(self):
        result = workshop_bench.run(self.app, self.design, {
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


if __name__ == "__main__":
    unittest.main()
