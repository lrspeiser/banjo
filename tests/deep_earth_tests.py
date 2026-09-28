"""How far down the rock goes, and what that lets out of it.

The earth was 2 m deep: `floor_` was the lowest rock top less 2 m, a cut below it
was refused with "that is deeper than the rock goes", and there was nowhere for a
mine to go (docs/earth-and-mining-plan.md, why you cannot read the ground). It is
30 m now -- `TerrainField::kEarthDepthM` -- and these checks are what that means
through the real engine.

Nothing in the page can reach rock yet, so this is a measurement and not
something to look at: breaking rock under a point has no law until stage 4.

    python tests/deep_earth_tests.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "playground"))

import fracture_lab  # noqa: E402
import live_session  # noqa: E402

ENGINE = ROOT / "build" / "integration" / "Release" / "banjo_live_world_run.exe"
if not ENGINE.exists():
    ENGINE = ROOT / "build" / "integration" / "banjo_live_world_run"

# Bare rock, level, with nothing on it: the clearing's own slab is the one place
# a test can cut without digging first.
ROCK = {"bodies": [{"name": "marker", "material": "oak", "shape": "box",
                    "size_mm": [100, 100, 100], "center_mm": [0, 3000, 0]}],
        "terrain": {"generate": {"kind": "flat", "nx": 48, "nz": 48, "cell_m": 0.25,
                                 "soil_m": 0.0, "sand_m": 0.0}}}

EARTH_M = 30.0


class DeepEarth(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not ENGINE.exists():
            raise unittest.SkipTest(f"no live engine at {ENGINE}")

    def setUp(self) -> None:
        self.live = live_session.Session(ENGINE, fracture_lab.validate(ROCK),
                                         (ROOT / "playground" / "runs").resolve())
        self.addCleanup(self.live.close)

    def cut(self, height_m: float, at=(3.0, 3.0), cells=(4, 4)):
        return self.live.send(op="cut_block", at=list(at), cells=list(cells), height_m=height_m)

    def test_the_rock_goes_down_thirty_metres(self):
        # The survey's own floor: the ground block says where the rock stops.
        ground = self.live.state["terrain"]
        floor = float(ground["floor_m"])
        # Flat ground at 0, so the floor is the whole earth below it.
        self.assertAlmostEqual(floor, -EARTH_M, delta=0.001,
                               msg=f"the earth is {-floor:.2f} m deep, not {EARTH_M}")

    def test_a_block_too_tall_for_the_old_earth_comes_out(self):
        # 3 m was refused when the earth was 2 m deep. It is a block now.
        said = self.cut(3.0)
        block = said.get("block")
        self.assertIsNotNone(block, f"a 3 m block was refused: {said}")
        self.assertAlmostEqual(block["size_m"][1], 3.0, delta=1e-6)
        # Exactly its footprint times its height of rock left the ground.
        self.assertAlmostEqual(block["volume_m3"], 1.0 * 1.0 * 3.0, delta=1e-9)
        self.assertAlmostEqual(block["kg"], block["volume_m3"] * 2400.0, delta=1e-6)

    def test_a_block_deeper_than_the_earth_is_still_refused_and_says_so(self):
        with self.assertRaises(Exception) as refused:
            self.cut(EARTH_M + 1.0)
        self.assertIn("deeper than the rock goes", str(refused.exception))

    def test_what_is_cut_out_is_what_the_ground_lost(self):
        before = self.live.send(op="environment")["environment"]["ground"]["volumes"]
        block = self.cut(3.0)["block"]
        after = self.live.send(op="environment")["environment"]["ground"]
        gone = before["rock_m3"] - after["volumes"]["rock_m3"]
        self.assertAlmostEqual(gone, block["volume_m3"], delta=1e-9,
                               msg="the ground lost something other than the block")
        residual = after["residual"]
        for kind in ("rock_m3", "soil_m3", "sand_m3"):
            self.assertLess(abs(residual[kind]), 1e-9, f"the ledger does not close on {kind}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
