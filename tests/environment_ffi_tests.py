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
    def test_the_library_speaks_an_abi_with_ground_and_water_in_it(self):
        # 15 added terrain and water, and every ABI after it keeps them.
        self.assertGreaterEqual(banjo.library().banjo_abi_version(), 15)
        self.assertEqual(banjo.ABI_VERSION, banjo.library().banjo_abi_version())

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

    def test_what_is_dug_is_carried_and_a_heap_is_made_of_it(self):
        """The ground keeps its own account of what came out of it: dug, less
        heaped. Whoever dug it carries it -- the playground's Carried list, and
        all the MCP's fill may heap -- and the ground plus what is carried is
        the ground there was. A world opened again from the same edits carries
        the same; a heap a scene declares is declared ground, owed by nobody."""
        def carried(world):
            return world.environment_report()["ground"]["carried"]

        dig = {"from_m": [-3.0, 0.0], "to_m": [-1.0, 0.0], "width_m": 1.0, "depth_m": 0.4}
        with banjo.World(scene(FLAT), cell_size_m=CELL) as world:
            self.assertEqual((carried(world)["sand_m3"], carried(world)["soil_m3"]), (0.0, 0.0))
            dug = world.dig(dig["from_m"], dig["to_m"], width_m=dig["width_m"], depth_m=dig["depth_m"])
            have = carried(world)
            self.assertEqual(have["sand_m3"], dug.sand_m3)
            self.assertEqual(have["soil_m3"], dug.soil_m3)
            self.assertAlmostEqual(have["sand_kg"] + have["soil_kg"], dug.mass_kg, delta=1e-9)
            heap = {"at_m": [3.0, 2.0], "radius_m": 1.0,
                    "sand_m3": dug.sand_m3 / 2, "soil_m3": dug.soil_m3 / 4}
            world.deposit(heap["at_m"], radius_m=heap["radius_m"], sand_m3=heap["sand_m3"],
                          soil_m3=heap["soil_m3"])
            have = carried(world)
            self.assertAlmostEqual(have["sand_m3"], dug.sand_m3 / 2, delta=1e-12)
            self.assertAlmostEqual(have["soil_m3"], dug.soil_m3 * 3 / 4, delta=1e-12)
            run(world, 2.0)   # the trench's sides slump and the heap settles: neither is carried
            ground = world.environment_report()["ground"]
            left = ground["carried"]
            for kind in ("sand", "soil"):
                # Rounding over the 48 m3 of this ground, and nothing else.
                self.assertAlmostEqual(
                    ground["volumes"][f"{kind}_m3"] + left[f"{kind}_m3"],
                    ground["ledger"]["initial"][f"{kind}_m3"], delta=1e-9,
                    msg=f"{kind}: the ground plus what is carried is not the ground there was")
        # The same edits, replayed as a world opens: the same account.
        edited = scene(FLAT)
        edited["terrain"]["edits"] = [{"dig": dig}, {"deposit": heap}]
        with banjo.World(edited, cell_size_m=CELL) as again:
            self.assertAlmostEqual(carried(again)["sand_m3"], left["sand_m3"], delta=1e-12)
            self.assertAlmostEqual(carried(again)["soil_m3"], left["soil_m3"], delta=1e-12)
        # A heap declared with nothing dug is declared ground: nothing is owed,
        # and what is dug afterwards is carried whole.
        declared = scene(FLAT)
        declared["terrain"]["edits"] = [{"deposit": {"at_m": [3.0, 2.0], "radius_m": 1.0, "soil_m3": 1.0}}]
        with banjo.World(declared, cell_size_m=CELL) as heaped:
            self.assertEqual(carried(heaped)["soil_m3"], 0.0)
            more = heaped.dig((-3.0, -2.0), width_m=0.8, depth_m=0.3)
            self.assertEqual(carried(heaped)["sand_m3"], more.sand_m3)
            self.assertEqual(carried(heaped)["soil_m3"], more.soil_m3)

    def test_a_world_opened_again_from_its_edits_is_the_ground_they_were_made_in(self):
        """A world is opened again from its edits -- after the chat changes the
        room, or on a reload -- each replayed and let come to rest before the
        next, in the strides the running world settles in. So when each edit
        had come to rest before the next was made, the world opened again is
        the same ground to the bit: a second pit dug into the first one's
        slumped sides takes what the slump left there. Replayed back to back
        and settled once, the page's reload carried 7.8 litres more soil."""
        first = {"from_m": [0.0, 0.0], "to_m": [0.0, 0.0], "width_m": 1.0, "depth_m": 0.5}
        second = {"from_m": [0.4, 0.2], "to_m": [0.4, 0.2], "width_m": 1.0, "depth_m": 0.5}
        heap = {"at_m": [2.5, -1.0], "radius_m": 0.8, "sand_m3": 0.05, "soil_m3": 0.05}
        with banjo.World(scene(FLAT), cell_size_m=CELL) as world:
            run(world, 1.0)
            for edit, made in (("first dig", first), ("second dig", second), ("heap", heap)):
                if edit != "heap":
                    world.dig(made["from_m"], made["to_m"], width_m=made["width_m"],
                              depth_m=made["depth_m"])
                else:
                    world.deposit(made["at_m"], radius_m=made["radius_m"],
                                  sand_m3=made["sand_m3"], soil_m3=made["soil_m3"])
                # Measured: the first pit's sides are at rest by 3.5 s (0.111
                # of their 0.130 m3 in the first half second), the second pit,
                # dug into the first, by 6.25 s; this heap holds at once.
                run(world, 10.0)
                self.assertEqual(world.environment_report()["ground"]["unsettled_columns"], 0,
                                 f"the ground had not come to rest after the {edit}")
            ground = world.environment_report()["ground"]
            self.assertGreater(ground["ledger"]["slumped_m3"], 0.0,
                               "nothing slumped between the digs, so this proves nothing")
            heights, carried = world.terrain_heights(), ground["carried"]
        edited = scene(FLAT)
        edited["terrain"]["edits"] = [{"dig": first}, {"dig": second}, {"deposit": heap}]
        with banjo.World(edited, cell_size_m=CELL) as again:
            self.assertEqual(again.terrain_heights(), heights,
                             "the ground opened again is not the ground the edits left")
            self.assertEqual(again.environment_report()["ground"]["carried"], carried)

    def channel_ends(self):
        """Where the channel's stream comes in and where it leaves: the ground at
        the middle of its west and east edges."""
        with banjo.World(scene(CHANNEL), cell_size_m=CELL) as probe:
            t = probe.terrain()
            x_west, x_east = t.origin_m[0], t.origin_m[0] + (t.nx - 1) * t.cell_m
            z_mid = t.origin_m[1] + (t.nz // 2) * t.cell_m
            return (probe.survey(x_west, z_mid)["ground_m"], probe.survey(x_east, z_mid)["ground_m"],
                    (x_west + x_east) / 2, z_mid)

    def watershed(self, west, east):
        """A reservoir beyond the stream's source, fed at the stream's own
        discharge, and a basin beyond its mouth that lets water go over a weir
        (docs/watershed.md)."""
        return {"basins": [
                    {"name": "the reservoir", "bed_m": west - 0.5, "area_m2": 50.0, "level_m": west + 0.25},
                    {"name": "the basin", "bed_m": east - 1.0, "area_m2": 200.0, "level_m": east - 0.6,
                     "outlet": {"crest_m": east - 0.45, "width_m": 1.0}}],
                "connections": [{"basin": "the reservoir", "instead_of": "the stream"},
                                {"basin": "the basin", "instead_of": "the stream's end"}]}

    def test_a_reservoir_feeds_the_channel_across_a_connection_on_one_account(self):
        """The channel's source and mouth are now connections to the water of the
        regions beyond them: what crosses is the water on both sides, every cubic
        metre is on one account, and a world opened again from the state keeps
        the basins where they were, to the bit."""
        west, east, _, _ = self.channel_ends()
        shed = self.watershed(west, east)
        with banjo.World(scene(CHANNEL, water={"watershed": shed}), cell_size_m=CELL) as world:
            before = {b["name"]: b for b in world.environment_report()["watershed"]["basins"]}
            run(world, 120.0)
            report = world.environment_report()["watershed"]
            basins = {b["name"]: b for b in report["basins"]}
            links = {link["name"]: link for link in report["connections"]}
            self.assertGreater(links["the stream"]["into_this_region_m3_s"], 0.0,
                               "the reservoir feeds the channel")
            self.assertLess(links["the stream's end"]["into_this_region_m3_s"], 0.0,
                            "the channel pours into the basin")
            self.assertGreater(basins["the basin"]["volume_m3"], before["the basin"]["volume_m3"],
                               "the basin downstream holds what the channel sent it")
            self.assertLessEqual(abs(report["unaccounted_m3"]), 1e-9 * report["water_held_m3"],
                                 "one account for the reservoir, the channel and the basin")
            state, held = world.environment_state(), world.water().volume_m3
        again_scene = scene(CHANNEL, water={"watershed": shed, "state": state})
        with banjo.World(again_scene, cell_size_m=CELL) as again:
            report = again.environment_report()["watershed"]
            for basin in report["basins"]:
                self.assertEqual(basin["volume_m3"], basins[basin["name"]]["volume_m3"],
                                 f"{basin['name']} is not where it was left")
            self.assertEqual(again.water().volume_m3, held, "nor is the channel's water")

    def test_a_bank_across_the_channel_backs_up_into_the_reservoir(self):
        """Two channels the same but for an earth bank heaped across one of them:
        the reservoir beyond the banked-up one stands higher and less crosses
        from it -- the connection passes what the water on both sides says,
        not the discharge written down for the stream."""
        west, east, x_mid, z_mid = self.channel_ends()
        shed = self.watershed(west, east)
        bank = {"deposit": {"at_m": [x_mid, z_mid], "radius_m": 2.5, "soil_m3": 4.0}}
        results = {}
        for label, edits in (("open", []), ("banked", [bank])):
            document = scene(CHANNEL, water={"watershed": shed})
            if edits:
                document["terrain"]["edits"] = edits
            with banjo.World(document, cell_size_m=CELL) as world:
                run(world, 180.0)
                report = world.environment_report()["watershed"]
                results[label] = ({b["name"]: b for b in report["basins"]}["the reservoir"]["level_m"],
                                  {c["name"]: c for c in report["connections"]}["the stream"]["into_this_region_m3_s"],
                                  report["unaccounted_m3"], report["water_held_m3"])
        (open_level, open_in, _, _), (banked_level, banked_in, unaccounted, held) = \
            results["open"], results["banked"]
        self.assertGreater(banked_level, open_level + 0.005,
                           f"the reservoir behind the bank stands at {banked_level:.4f} m against "
                           f"{open_level:.4f} m without it")
        self.assertLess(banked_in, open_in, "and less crosses from it")
        self.assertLessEqual(abs(unaccounted), 1e-9 * held, "every cubic metre accounted")

    def test_a_river_network_brings_the_stream_down_and_takes_it_on_to_a_lake(self):
        """The channel between two reaches (docs/watershed.md, W3): one comes down
        from a reservoir onto the stream's source, another takes the stream from
        its end to a lake with a weir. What crosses each edge is the water on
        both sides, the reaches carry it on, every cubic metre of the channel and
        the network is on one account, and a world opened again from the state
        has the reaches and basins where they were, to the bit."""
        with banjo.World(scene(CHANNEL), cell_size_m=CELL) as probe:
            plain = probe.environment_report()
        cell = plain["grid"]["cell_m"]
        river, mouth = plain["water"]["rivers"][0], plain["water"]["mouths"][0]
        path = [p for p in plain["water"]["river_path"] if p.get("level_m") is not None]
        top, bottom = path[0]["bed_m"], path[-1]["bed_m"]
        q = river["discharge_m3_s"]
        shed = {"basins": [
                    {"name": "the reservoir", "bed_m": top - 0.3, "area_m2": 60.0, "level_m": top + 0.35},
                    {"name": "the lake", "bed_m": bottom - 1.0, "area_m2": 200.0, "level_m": bottom - 0.15,
                     "outlet": {"crest_m": bottom - 0.05, "width_m": 1.0}}],
                "reaches": [
                    {"name": "the reach above", "from": "the reservoir", "to": {"connection": river["name"]},
                     "length_m": 12.0, "width_m": (river["cells"][1] - river["cells"][0] + 1) * cell,
                     "bed_from_m": top + 0.06, "bed_to_m": top, "cells": 3, "depth_m": 0.1,
                     "discharge_m3_s": q},
                    {"name": "the reach below", "from": {"connection": mouth["name"]}, "to": "the lake",
                     "length_m": 12.0, "width_m": (mouth["cells"][1] - mouth["cells"][0] + 1) * cell,
                     "bed_from_m": bottom, "bed_to_m": bottom - 0.06, "cells": 3, "depth_m": 0.05,
                     "discharge_m3_s": q}]}
        with banjo.World(scene(CHANNEL, water={"watershed": shed}), cell_size_m=CELL) as world:
            run(world, 120.0)
            report = world.environment_report()["watershed"]
            reaches = {r["name"]: r for r in report["reaches"]}
            links = {c["name"]: c for c in report["connections"]}
            self.assertEqual(links[river["name"]]["to"], "the reach above")
            self.assertGreater(links[river["name"]]["into_this_region_m3_s"], 0.0, "the reach feeds the channel")
            self.assertLess(links[mouth["name"]]["into_this_region_m3_s"], 0.0,
                            "the channel pours into the reach below")
            self.assertGreater(reaches["the reach above"]["middle_m3_s"], 0.0, "the reach above carries it down")
            self.assertGreater(reaches["the reach below"]["middle_m3_s"], 0.0, "the reach below carries it on")
            self.assertLessEqual(abs(report["unaccounted_m3"]), 1e-9 * report["water_held_m3"],
                                 "one account for the reservoir, the reaches, the channel and the lake")
            state = world.environment_state()
        again_scene = scene(CHANNEL, water={"watershed": shed, "state": state})
        with banjo.World(again_scene, cell_size_m=CELL) as again:
            opened = again.environment_report()["watershed"]
            for reach in opened["reaches"]:
                self.assertEqual(reach["level_m"], reaches[reach["name"]]["level_m"],
                                 f"{reach['name']} is not where it was left")
                self.assertEqual(reach["q_m3_s"][1:-1], reaches[reach["name"]]["q_m3_s"][1:-1],
                                 f"{reach['name']}'s water is not moving as it was")
            before = {b["name"]: b for b in report["basins"]}
            for basin in opened["basins"]:
                self.assertEqual((basin["volume_m3"], basin["level_m"]),
                                 (before[basin["name"]]["volume_m3"], before[basin["name"]]["level_m"]),
                                 f"{basin['name']} is not where it was left")

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
