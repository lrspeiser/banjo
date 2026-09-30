"""The Workshop Test cards against the native engine, not a mocked runner.

BANJO_LIVE_ENGINE=.../banjo_live_world_run python tests/workshop_screen_sim_tests.py
Every run owns a scratch room and leaves the person's open world alone.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground"), str(ROOT / "mcp")]

from mcp import workshop as w  # noqa: E402
import workshop_bench  # noqa: E402

ENGINE = Path(os.environ["BANJO_LIVE_ENGINE"]).resolve() if os.environ.get("BANJO_LIVE_ENGINE") else None


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE is required")
class ScreenSimulationContract(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.app = SimpleNamespace(engine_path=ENGINE, runs_path=Path(scratch.name),
                                   workshop_owner_id="screen-sim-test")

    @staticmethod
    def visible(kind: str) -> set[str]:
        return {t["test"] for t in workshop_bench.catalog(kind)
                if t.get("category") == "simulation"
                and t.get("subject") == "selected-product"
                and t.get("required_model") in ("any", "lattice")}

    def test_every_default_little_world_card_matches_native_installation(self):
        """A card must run; a newly working default should acquire a card."""
        for assembly in w.ASSEMBLIES:
            kind = assembly.name
            with self.subTest(kind=kind):
                design = w.assemble(kind)
                candidate = {"kind": kind, "design_id": "screen-" + kind,
                             "parameters": dict(design.parameters)}
                advertised = "try_in_a_room" in self.visible(kind)
                try:
                    result = workshop_bench.run(
                        self.app, design, {"test": "try_in_a_room",
                                           "config": {"seconds": 0.5, "turn_on": False}},
                        candidate=candidate)
                except ValueError as refused:
                    self.assertFalse(advertised, f"{kind} offers a card that refuses: {refused}")
                else:
                    self.assertTrue(advertised, f"{kind} installs but has no little-world card")
                    self.assertTrue(result["engine_backed"])
                    self.assertGreater(result["measured"]["cells"], 0)
                    self.assertGreaterEqual(len(result["playback"]["frames"]), 2)
                    self.assertEqual("not-declared", result["acceptance"]["status"])

    def test_specialized_cart_and_kettle_cards_run_their_native_sims(self):
        cart = workshop_bench.run(self.app, w.assemble("cart"),
                                  {"test": "cart_roll", "config": {"duration_s": 0.5}})
        self.assertIn("cart_roll", self.visible("cart"))
        self.assertGreater(cart["measured"]["chassis_delta_m"][2], 0.1)
        self.assertTrue(all(axle["degrees"] > 0 for axle in cart["measured"]["axle_turns"]))
        self.assertGreaterEqual(len(cart["playback"]["frames"]), 2)

        kettle = workshop_bench.run(self.app, w.assemble("kettle"),
                                    {"test": "kettle_heat", "config": {"duration_s": 5}})
        self.assertIn("kettle_heat", self.visible("kettle"))
        measured = kettle["measured"]
        self.assertGreater(measured["water_end_k"], measured["water_start_k"])
        self.assertGreater(measured["ledger"]["heater_in_j"], 0)
        self.assertLess(abs(measured["ledger"]["residual_j"]), 1e-4)
        self.assertGreaterEqual(len(kettle["playback"]["frames"]), 2)


if __name__ == "__main__":
    unittest.main()
