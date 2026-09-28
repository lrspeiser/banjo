"""What every ground column is made of, all the way down, over the wire.

The page used to be told a height and one byte for what is on TOP of each
column, so a pit's wall could only ever be drawn in the colour of the grass
above it (docs/earth-and-mining-plan.md, why you cannot read the ground). It is
now told the column's RUNS -- a material and the height it reaches -- which is
what a cut face has to be drawn from, and what the ground will go on being said
in when it holds strata and veins.

These checks are against the real engine through the line protocol: the block
parses exactly, agrees with the heights and the survey it is sent beside, and a
dig changes it where the dig was and nowhere else.

    python tests/terrain_runs_tests.py
"""
from __future__ import annotations

import base64
import json
import struct
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

# Flat ground: soil over rock with a sandy layer on top, so every column has all
# three runs and the check can tell them apart.
FLAT = {"bodies": [{"name": "marker", "material": "oak", "shape": "box",
                    "size_mm": [100, 100, 100], "center_mm": [0, 2000, 0]}],
        "terrain": {"generate": {"kind": "flat", "nx": 48, "nz": 48, "cell_m": 0.25,
                                 "soil_m": 0.6, "sand_m": 0.2}}}

KINDS = {0: "rock", 1: "soil", 2: "sand", 3: "loose soil"}


def unpack_runs(block: dict) -> list[list[tuple[str, float]]]:
    """Every column's runs from a terrain block: (material, top in metres).

    Raises if the bytes do not account for exactly the columns claimed, which is
    the point: a packing whose lengths do not add up is not a format.
    """
    raw = base64.b64decode(block["runs_b64"])
    floor = float(block["floor_m"])
    columns = []
    at = 0
    while at < len(raw):
        count = raw[at]
        at += 1
        if count < 1:
            raise AssertionError(f"column {len(columns)} claims {count} runs")
        runs = []
        for _ in range(count):
            kind = raw[at]
            (mm,) = struct.unpack_from("<H", raw, at + 1)
            at += 3
            if kind not in KINDS:
                raise AssertionError(f"column {len(columns)}: unknown run kind {kind}")
            runs.append((KINDS[kind], floor + mm / 1000.0))
        columns.append(runs)
    if at != len(raw):
        raise AssertionError(f"{len(raw) - at} bytes left over after {len(columns)} columns")
    return columns


def heights_of(block: dict) -> list[float]:
    raw = base64.b64decode(block["heights_b64"])
    return list(struct.unpack(f"<{len(raw) // 4}f", raw))


class GroundRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not ENGINE.exists():
            raise unittest.SkipTest(f"no live engine at {ENGINE}")

    def setUp(self) -> None:
        self.live = live_session.Session(ENGINE, fracture_lab.validate(FLAT),
                                        (ROOT / "playground" / "runs").resolve())
        self.addCleanup(self.live.close)
        self.ground = self.live.state["terrain"]

    def test_the_block_parses_and_covers_every_column(self):
        grid = self.ground["grid"]
        columns = unpack_runs(self.ground)
        self.assertEqual(len(columns), grid["nx"] * grid["nz"])

    def test_every_column_is_rock_upwards_and_its_top_run_is_the_ground(self):
        columns = unpack_runs(self.ground)
        heights = heights_of(self.ground)
        self.assertEqual(len(heights), len(columns))
        for c, runs in enumerate(columns):
            self.assertEqual(runs[0][0], "rock", f"column {c} does not start in rock")
            tops = [top for _, top in runs]
            self.assertEqual(tops, sorted(tops), f"column {c}'s runs are not bottom-up")
            # The top of the last run is the ground itself, to the millimetre the
            # wire carries.
            self.assertAlmostEqual(tops[-1], heights[c], delta=0.001,
                                   msg=f"column {c}: top run {tops[-1]} against height {heights[c]}")

    def test_flat_ground_declared_as_soil_and_sand_is_rock_soil_sand(self):
        columns = unpack_runs(self.ground)
        kinds = {tuple(kind for kind, _ in runs) for runs in columns}
        self.assertEqual(kinds, {("rock", "soil", "sand")},
                         f"a flat 0.6 m of soil under 0.2 m of sand gave {kinds}")
        runs = columns[len(columns) // 2]
        self.assertAlmostEqual(runs[1][1] - runs[0][1], 0.6, delta=1e-3)   # the soil
        self.assertAlmostEqual(runs[2][1] - runs[1][1], 0.2, delta=1e-3)   # the sand

    def test_the_runs_agree_with_the_survey_at_the_same_place(self):
        grid = self.ground["grid"]
        x = grid["x0_m"] + grid["cell_m"] * (grid["nx"] // 2)
        z = grid["z0_m"] + grid["cell_m"] * (grid["nz"] // 2)
        said = self.live.send(op="survey", at=[x, z])
        survey = said.get("survey") or said
        self.assertIn("runs", survey, f"the survey says no runs: {sorted(survey)}")
        from_survey = [(r["material"], round(r["to_m"], 3)) for r in survey["runs"]]
        c = (grid["nx"] // 2) + (grid["nz"] // 2) * grid["nx"]
        from_wire = [(kind, round(top, 3)) for kind, top in unpack_runs(self.ground)[c]]
        self.assertEqual(from_survey, from_wire)

    def test_a_dig_changes_the_runs_where_it_dug_and_nowhere_else(self):
        grid = self.ground["grid"]
        before = unpack_runs(self.ground)
        x = grid["x0_m"] + grid["cell_m"] * 20
        z = grid["z0_m"] + grid["cell_m"] * 20
        answer = self.live.send(op="dig", **{"from": [x, z], "to": [x, z]},
                                width_m=1.0, depth_m=0.5)
        changed = answer.get("terrain_changed")
        self.assertIsNotNone(changed, "a dig sent no changed ground")
        self.assertIn("runs_b64", changed, "the changed rectangle carries no runs")
        i0, j0, ni, nj = changed["box"]
        # The rectangle's own runs parse, and cover exactly the rectangle.
        rect = unpack_runs({"runs_b64": changed["runs_b64"], "floor_m": self.ground["floor_m"]})
        self.assertEqual(len(rect), ni * nj)

        whole = unpack_runs(self.live.send(op="terrain")["terrain"])
        moved = [c for c in range(len(before)) if before[c] != whole[c]]
        self.assertTrue(moved, "the dig changed no column's runs")
        for c in moved:
            i, j = c % grid["nx"], c // grid["nx"]
            self.assertTrue(i0 <= i < i0 + ni and j0 <= j < j0 + nj,
                            f"column ({i}, {j}) changed outside the rectangle it reported")
        # 0.5 m down through 0.2 m of sand and into the soil: the sand is gone
        # and what is left is rock under soil.
        dug = [whole[c] for c in moved if len(whole[c]) == 2]
        self.assertTrue(dug, f"nothing was dug down to bare soil: {set(len(whole[c]) for c in moved)}")
        for runs in dug:
            self.assertEqual([kind for kind, _ in runs], ["rock", "soil"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
