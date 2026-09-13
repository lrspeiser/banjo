"""Terrain and water through the C library, from Python.

The C face is how anything outside this repository drives a world, so what the
ground and the water do has to be reachable through it: opening a world on
generated ground, reading the ground, the water and both their ledgers,
digging, heaping and cutting, turning a river up, and the arrays a renderer
draws the ground and the water from. Nothing here re-derives the physics: each
test asks the engine and checks what it says against what has to be true.

The ground is the generator's simple kinds, which cost nothing to make: a
bowl holding a lake at 1.0 m ("basin"), and level ground -- 0.6 m of soil and
0.2 m of sand over rock whose top is y = 0 ("flat"), or bare rock.

Needs the library: BANJO_LIBRARY=<build>/Release/banjo.dll.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bindings" / "python"))
# Generated ground is cached on disk; this suite's is kept out of anyone else's.
os.environ.setdefault("BANJO_TERRAIN_CACHE", str(Path(tempfile.gettempdir()) / "banjo-ffi-terrain"))

import banjo  # noqa: E402

DT = 1.0 / 60.0
CELL = 0.04
BASIN = {"kind": "basin"}
FLAT = {"kind": "flat"}
BARE_ROCK = {"kind": "flat", "soil_m": 0.0, "sand_m": 0.0}
CHANNEL = {"kind": "channel"}
# A world is opened from its bodies, so every scene has one: anchored, in the
# air over a corner, where nothing under test comes near it.
MARKER = {"name": "marker", "shape": "box", "material": "concrete",
          "dimensions_m": [0.08, 0.08, 0.08], "center_m": [-7.0, 10.0, -5.0], "anchored": True}


def box(name, material, size, at, anchored=False):
    return {"name": name, "shape": "box", "material": material, "dimensions_m": list(size),
            "center_m": list(at), "anchored": anchored}


def scene(generate, *bodies, water=None):
    document = {"plasticity": True, "bodies": [MARKER, *bodies], "terrain": {"generate": generate}}
    if water is not None:
        document["water"] = water
    return document


def run(world, seconds):
    for _ in range(int(round(seconds / DT))):
        world.advance(DT)


def body(world, name):
    return next(b for b in world.bodies() if b.name == name)


class TheGroundAndTheWaterThroughTheLibrary(unittest.TestCase):
    def test_the_library_speaks_abi_15(self):
        self.assertEqual(banjo.library().banjo_abi_version(), 15)
        self.assertEqual(banjo.ABI_VERSION, 15)

    def test_a_world_without_ground_says_so(self):
        flat_floor = {"bodies": [box("block", "concrete", (0.2, 0.2, 0.2), (0, 0.1, 0))]}
        with banjo.World(flat_floor, cell_size_m=CELL) as world:
            with self.assertRaises(banjo.BanjoError) as refused:
                world.terrain()
            self.assertIn("terrain", str(refused.exception))
            self.assertEqual(world.environment_report(), {})

    def test_a_lake_at_rest_stays_exactly_at_rest_and_its_ledger_closes(self):
        with banjo.World(scene(BASIN), cell_size_m=CELL) as world:
            ground = world.terrain()
            surface = world.water_surface()
            before = world.water()
            self.assertEqual(len(surface), ground.nx * ground.nz)
            self.assertGreater(before.wet_cells, 0)
            self.assertEqual(before.inflow_m3_s, 0.0, "a basin has no river")
            run(world, 2.0)
            after = world.water()
            now = world.water_surface()
            self.assertEqual([s is None for s in surface], [s is None for s in now],
                             "the lake's shore moved")
            moved = max(abs(a - b) for a, b in zip(surface, now) if a is not None)
            self.assertEqual(moved, 0.0, "a lake at rest moved")
            self.assertEqual(after.volume_m3, before.volume_m3)
            self.assertEqual(after.numerical_m3, 0.0)
            self.assertLessEqual(abs(after.residual_m3), 1e-12 * after.volume_m3)
            self.assertAlmostEqual(world.survey(0.0, 0.0)["water"]["surface_m"], 1.0, delta=1e-12)

    def test_water_carried_into_a_world_opened_again_is_the_same_water(self):
        with banjo.World(scene(BASIN), cell_size_m=CELL) as world:
            run(world, 0.5)
            state = world.environment_state()
            volume = world.water().volume_m3
            wet = world.water().wet_cells
        with banjo.World(scene(BASIN, water={"state": state}), cell_size_m=CELL) as again:
            self.assertAlmostEqual(again.water().volume_m3, volume, delta=1e-12 * volume)
            self.assertEqual(again.water().wet_cells, wet)

    def test_oak_floats_by_what_it_displaces_and_iron_sinks(self):
        """Oak is 700 kg/m3: afloat, the water it displaces weighs what it weighs,
        and that is 70% of its volume. Iron is 7870 and goes to the bottom.

        Dropped in, the log bobs about that line, and the bobbing dies away
        slowly -- ±5 cm after 2 s, ±1 cm after 10 s -- because a floating body
        pushes no water aside in the solver and so radiates no waves: drag is
        all that damps it (docs/terrain-and-water.md, not modelled). So the
        line it floats at is read as the mean over three seconds, not at an
        instant it happens to be passing through."""
        oak = box("oak log", "oak", (0.48, 0.24, 0.24), (0.0, 1.2, 0.0))
        iron = box("iron block", "iron", (0.16, 0.16, 0.16), (1.0, 1.2, 0.5))
        volume = 0.48 * 0.24 * 0.24
        with banjo.World(scene(BASIN, oak, iron), cell_size_m=CELL) as world:
            run(world, 7.0)
            under, lift, weight = [], [], []
            for _ in range(int(round(3.0 / DT))):
                world.advance(DT)
                held = {b["name"]: b for b in world.environment_report()["water"]["bodies_in_water"]}
                under.append(held["oak log"]["submerged_m3"] / volume)
                lift.append(held["oak log"]["buoyancy_n"])
                weight.append(held["oak log"]["weight_n"])
            self.assertAlmostEqual(sum(under) / len(under), 0.7, delta=0.02)
            self.assertAlmostEqual(sum(lift) / len(lift), weight[-1], delta=0.02 * weight[-1])
            self.assertTrue(held["oak log"]["floats"] or min(under) < 0.7 < max(under), held["oak log"])
            self.assertFalse(held["iron block"]["floats"], held["iron block"])
            bed = world.survey(*body(world, "iron block").position_m[0::2])["ground_m"]
            self.assertAlmostEqual(body(world, "iron block").position_m[1], bed + 0.08, delta=0.03)
            self.assertLessEqual(abs(world.water().residual_m3), 1e-12 * world.water().volume_m3)

    def test_a_dig_is_accounted_for_and_rebuilds_only_its_own_colliders(self):
        with banjo.World(scene(FLAT), cell_size_m=CELL) as world:
            ground = world.terrain()
            self.assertAlmostEqual(world.survey(-2.0, 0.0)["ground_m"], 0.8, delta=1e-9)
            dug = world.dig((-3.0, 0.0), (-1.0, 0.0), width_m=1.0, depth_m=0.4)
            self.assertGreater(dug.sand_m3, 0.0)
            self.assertGreater(dug.soil_m3, 0.0, "0.4 m through 0.2 m of sand reaches the soil")
            self.assertGreater(dug.columns, 0)
            self.assertLessEqual(dug.chunks_rebuilt, 2)
            self.assertLess(dug.chunks_rebuilt, ground.chunks_x * ground.chunks_z)
            after = world.terrain()
            self.assertAlmostEqual(after.dug_m3, dug.sand_m3 + dug.soil_m3, delta=1e-12)
            self.assertLessEqual(abs(after.residual_m3), 1e-9)
            heaped = world.deposit((3.0, 2.0), radius_m=1.0, sand_m3=dug.sand_m3, soil_m3=dug.soil_m3)
            self.assertGreater(heaped.columns, 0)
            run(world, 2.0)   # let the heap and the trench's sides settle
            settled = world.terrain()
            self.assertAlmostEqual(settled.deposited_m3, dug.sand_m3 + dug.soil_m3, delta=1e-12)
            self.assertLessEqual(abs(settled.residual_m3), 1e-9)

    def test_dug_from_under_a_block_it_falls_and_nothing_else_wakes(self):
        block = box("block", "concrete", (0.4, 0.4, 0.4), (2.0, 1.0, 1.0))
        with banjo.World(scene(FLAT, block), cell_size_m=CELL) as world:
            run(world, 3.0)
            self.assertEqual(world.awake_bodies(), 0, "a block at rest is asleep")
            far = world.dig((-5.0, -3.0), width_m=0.8, depth_m=0.3)
            self.assertEqual(far.bodies_woken, 0, "a pit 7 m away woke something")
            self.assertEqual(world.awake_bodies(), 0)
            top = body(world, "block").position_m[1]
            under = world.dig((2.0, 1.0), width_m=1.0, depth_m=0.5)
            self.assertEqual(under.bodies_woken, 1)
            run(world, 2.0)
            self.assertGreater(top - body(world, "block").position_m[1], 0.2,
                               "dug from under, the block did not fall")

    def test_a_block_cut_from_bare_rock_is_the_rock_that_left(self):
        with banjo.World(scene(BARE_ROCK), cell_size_m=CELL) as world:
            before = world.terrain().rock_m3
            with self.assertRaises(banjo.BanjoError) as refused:
                world.cut_block((0.0, 0.0), cells=(2, 2), height_m=0.4)   # 0.5 m: not whole cells
            self.assertIn("columns", str(refused.exception))
            block = world.cut_block((0.0, 0.0), cells=(4, 4), height_m=0.4)
            self.assertAlmostEqual(block.volume_m3, 0.4, delta=1e-9)
            self.assertAlmostEqual(block.mass_kg, 960.0, delta=1e-6)
            self.assertEqual(tuple(round(v, 9) for v in block.size_m), (1.0, 0.4, 1.0))
            after = world.terrain()
            self.assertAlmostEqual(after.cut_m3, 0.4, delta=1e-9)
            self.assertAlmostEqual(before - after.rock_m3, 0.4, delta=1e-9)
            self.assertLessEqual(abs(after.residual_m3), 1e-9)

    def test_a_river_is_turned_up_by_name_and_an_unknown_one_refused(self):
        with banjo.World(scene(CHANNEL), cell_size_m=CELL) as world:
            rivers = world.environment_report()["water"]["rivers"]
            self.assertTrue(rivers, "a channel has a stream")
            name = rivers[0]["name"]
            world.set_discharge(name, 0.3)
            run(world, 0.5)
            self.assertAlmostEqual(world.water().inflow_m3_s, 0.3, delta=1e-12)
            with self.assertRaises(banjo.BanjoError):
                world.set_discharge("no such river", 0.3)

    def test_the_arrays_a_renderer_draws_from(self):
        with banjo.World(scene(BASIN), cell_size_m=CELL) as world:
            ground = world.terrain()
            heights = world.terrain_heights()
            surface = world.water_surface()
            self.assertEqual(len(heights), ground.nx * ground.nz)
            self.assertAlmostEqual(min(heights), ground.lowest_m, delta=1e-6)
            self.assertAlmostEqual(max(heights), ground.highest_m, delta=1e-6)
            wet = [(h, s) for h, s in zip(heights, surface) if s is not None]
            self.assertEqual(len(wet), world.water().wet_cells)
            self.assertTrue(all(s > h for h, s in wet), "water drawn below its own bed")
            self.assertTrue(all(abs(s - 1.0) < 1e-12 for _, s in wet), "the lake is not level")


if __name__ == "__main__":
    unittest.main()
