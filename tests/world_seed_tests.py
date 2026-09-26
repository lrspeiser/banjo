"""A new game's world is generated, and then proved.

    python tests/world_seed_tests.py -v

The proof is the point, so most of these are about it rather than about the
map: that a start with no machines strands everything, that the start we give
reaches everything, that taking one piece out of the start breaks it again,
and that a map which loses a substance says so instead of quietly passing.

They run on a valley built here in twenty lines, so no engine is needed. One
of them opens the real valley instead, and is skipped without BANJO_LIVE_ENGINE.
"""
from __future__ import annotations

import math
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))
sys.path.insert(0, str(ROOT))

import world_seed as ws  # noqa: E402


def a_valley(nx: int = 120, nz: int = 120, cell: float = 0.5, river: bool = True) -> dict:
    """A valley with a river running west to east and hills either side.

    Not the engine's valley: enough of one to place things on, so that what is
    being tested is the generator and not the terrain generator.
    """
    h, wet = [], set()
    x0 = z0 = -0.5 * nx * cell
    for j in range(nz):
        for i in range(nx):
            x, z = x0 + i * cell, z0 + j * cell
            floor = 0.8 + 0.06 * abs(z) + 0.4 * math.sin(x / 9.0)
            hill = 3.0 * math.exp(-((x + 14) ** 2 + (z + 16) ** 2) / 70.0)
            hill += 2.6 * math.exp(-((x - 16) ** 2 + (z - 15) ** 2) / 90.0)
            h.append(floor + hill - (1.2 if river and abs(z) < 1.6 else 0.0))
            if river and abs(z) < 1.4:
                wet.add((i, j))
    return {"nx": nx, "nz": nz, "cell": cell, "x0": x0, "z0": z0, "h": h, "wet": wet}


START = (0.0, 6.0)


class WhatANewGameNeeds(unittest.TestCase):
    """The circle this module exists to break."""

    def setUp(self):
        self.ground = a_valley()
        self.goods = ws.place(self.ground, 7, start_xz=START)

    def test_with_no_machines_at_all_the_world_is_unwinnable(self):
        """The bug, written as a test so it cannot come back quietly.

        A person on foot cannot gather: `Goods.dug` is reached only from the
        scoop, and a stockpile is taken from only by a machine. So a new game
        that hands over an empty rack and no machines can reach NOTHING, on
        any map, however rich -- which is what a new game did before this.
        """
        proof = ws.prove_you_can_make_it(self.goods, can=())
        self.assertEqual({}, proof["reached"])
        self.assertFalse(proof["ok"])
        # And it says why in terms somebody can act on, chased down past the
        # recipe to the ore lying in the ground that nobody can lift.
        self.assertEqual("smelt copper would make it and nothing can process",
                         proof["stranded"]["copper"])
        self.assertIn("nothing can haul", proof["stranded"]["oak"])

    def test_the_start_we_give_reaches_everything_the_workshop_spends(self):
        proof = ws.prove_you_can_make_it(self.goods, can=ws.start()["can"])
        self.assertEqual({}, proof["stranded"], proof["stranded"])
        self.assertTrue(proof["ok"])
        for substance in ws.wants()["materials"] + ws.wants()["goods"]:
            with self.subTest(substance):
                self.assertTrue(substance in proof["reached"] or
                                substance in proof["not in the world"])

    def test_the_start_is_only_just_enough(self):
        """Take one piece out and something strands.

        A bootstrap that still works with a piece missing was never a
        bootstrap, it was the finished game handed over at the door. This is
        the check that stops the start quietly growing.
        """
        only = ws.prove_it_is_only_just_enough(self.goods, can=ws.start()["can"])
        self.assertEqual({}, only["spare"], only["spare"])
        self.assertEqual({"dig", "haul", "process"}, set(only["needed"]))

    def test_the_two_the_start_stands_are_a_digger_and_a_processor(self):
        began = ws.start()
        self.assertEqual(["rover", "smelter"], began["standing"])
        self.assertIn("dig", began["can"])
        self.assertIn("process", began["can"])

    def test_what_the_start_stands_is_priced_off_the_real_designs(self):
        """Not a second copy of the numbers: the rover's own bill.

        If the rover grows a part, the bootstrap grows with it, and nobody has
        to remember to update a table here.
        """
        rover = ws.costs("rover")
        self.assertGreater(rover["goods"]["copper wire"], 0.0)
        self.assertIn("oak", rover["materials"])
        # It is more oak than a new player's rack holds, which is the other
        # half of why a new game cannot start: even the matter is short.
        from workshop_library import DEFAULT_RACK
        self.assertGreater(rover["materials"]["oak"], DEFAULT_RACK["oak"])


class WhatIsMissingFromTheGame(unittest.TestCase):
    """A bad roll and a missing feature are different things."""

    def test_rubber_and_ice_are_missing_from_the_world_not_stranded_in_it(self):
        """No map can supply them, so no amount of re-rolling would help.

        Keeping these apart is what lets the generator terminate: it re-seeds
        for a map that lost its clay and does not re-seed forever over a
        material nothing in the game can make.
        """
        goods = ws.place(a_valley(), 7, start_xz=START)
        proof = ws.prove_you_can_make_it(goods, can=ws.start()["can"])
        self.assertEqual({"rubber", "ice"}, set(proof["not in the world"]))
        self.assertTrue(proof["ok"])

    def test_a_map_that_lost_a_substance_is_stranded_and_says_which_recipe_wanted_it(self):
        goods = ws.place(a_valley(), 7, start_xz=START)
        goods["deposits"] = [d for d in goods["deposits"] if d["substance"] != "clay"]
        proof = ws.prove_you_can_make_it(goods, can=ws.start()["can"])
        self.assertFalse(proof["ok"])
        # Named to the root: the recipe, its missing input, and which half of
        # the generator is at fault for the input being missing.
        self.assertEqual("fire ceramic would make it but there is no clay -- and this "
                         "map could not fit it anywhere a machine can work",
                         proof["stranded"]["alumina ceramic"])

    def test_a_chain_broken_in_the_middle_names_the_link(self):
        goods = ws.place(a_valley(), 7, start_xz=START)
        goods["recipes"] = [r for r in goods["recipes"] if r["name"] != "burn lime"]
        proof = ws.prove_you_can_make_it(goods, can=ws.start()["can"])
        self.assertEqual("mix concrete would make it but there is no cement -- and "
                         "nothing in this map holds it and no recipe makes it",
                         proof["stranded"]["concrete"])


class WhereThingsArePut(unittest.TestCase):
    def setUp(self):
        self.ground = a_valley()

    def test_every_seed_gives_a_playable_world(self):
        """The regression that found the real bug.

        With the timber placed last, 25 of 60 seeds of the engine's valley had
        no room left for the only oak in the world. Everything now takes its
        first place before anything takes a second.
        """
        bad = []
        for seed in range(1, 31):
            goods = ws.place(self.ground, seed, start_xz=START)
            proof = ws.prove_you_can_make_it(goods, can=ws.start()["can"])
            if not proof["ok"]:
                bad.append((seed, proof["stranded"]))
        self.assertEqual([], bad, f"{len(bad)} of 30 seeds strand something")

    def test_every_substance_the_ground_holds_gets_at_least_one_seam(self):
        for seed in (1, 2, 3, 11, 29):
            with self.subTest(seed=seed):
                goods = ws.place(self.ground, seed, start_xz=START)
                got = {d["substance"] for d in goods["deposits"]}
                for seam in ws.GROUND_HOLDS:
                    self.assertIn(seam.substance, got)

    def test_the_same_seed_is_the_same_world(self):
        once = ws.place(self.ground, 12, start_xz=START)
        self.assertEqual(once, ws.place(self.ground, 12, start_xz=START))
        self.assertNotEqual(once, ws.place(self.ground, 13, start_xz=START))

    def test_nothing_is_placed_in_the_water_or_where_nothing_can_drive(self):
        goods = ws.place(self.ground, 5, start_xz=START)
        there = ws.drivable(self.ground, START)
        for thing in goods["deposits"] + goods["stockpiles"]:
            with self.subTest(thing["name"]):
                x, z = thing["at_m"]
                self.assertFalse(ws.wet_near(self.ground, x, z, thing["radius_m"]),
                                 f"{thing['name']} is in the water")
                self.assertIn(ws._cell_of(self.ground, x, z), there,
                              f"{thing['name']} cannot be driven to")

    def test_sand_and_clay_are_by_the_water_and_the_ores_are_not(self):
        """Where a thing is found is as much of the answer as that it is here.

        Rivers drop sand and clay; ore is in the high ground. The generator
        reads the kind of ground off the terrain, so this is a check that the
        reading works and not that a constant was typed in twice.
        """
        goods = ws.place(self.ground, 5, start_xz=START)
        wet = self.ground["wet"]
        cell = self.ground["cell"]

        def to_water(thing):
            x, z = thing["at_m"]
            return min(math.dist((x, z), (self.ground["x0"] + i * cell,
                                          self.ground["z0"] + j * cell))
                       for i, j in wet)

        banks = [to_water(d) for d in goods["deposits"] if d["substance"] in ("sand", "clay")]
        ores = [to_water(d) for d in goods["deposits"]
                if d["substance"] in ("copper ore", "iron ore", "bauxite", "limestone")]
        self.assertLess(max(banks), min(ores),
                        "every bank deposit should be nearer the water than every ore")

    def test_a_seam_is_shrunk_rather_than_left_out_when_the_ground_is_tight(self):
        """A smaller vein is a longer drive; a missing vein is an unwinnable
        game."""
        # 22 m across instead of 60: everything still fits, because three of
        # the seams are squeezed under the smallest radius any of them asks
        # for. Below about 18 m no amount of squeezing is enough and the map
        # loses its clay, which is a world the generator throws away rather
        # than one it lies about.
        goods = ws.place(a_valley(nx=44, nz=44, cell=0.5), 3, start_xz=(0.0, 6.0))
        got = {d["substance"] for d in goods["deposits"]}
        for seam in ws.GROUND_HOLDS:
            self.assertIn(seam.substance, got)
        least = min(s.radius_m[0] for s in ws.GROUND_HOLDS)
        self.assertTrue(any(d["radius_m"] < least for d in goods["deposits"]),
                        "a tight valley should have squeezed at least one seam")
        self.assertTrue(all(d["radius_m"] >= ws.LEAST_RADIUS_M for d in goods["deposits"]),
                        "and never below the floor, where a seam stops being one")


class GettingThere(unittest.TestCase):
    """The half of reachability a substance graph cannot see."""

    def test_a_seam_across_the_river_is_cut_off(self):
        ground = a_valley()
        goods = {"deposits": [{"name": "far seam", "substance": "copper ore",
                               "at_m": [0.0, -20.0], "radius_m": 1.0,
                               "grade": 0.3, "reserve_kg": 100.0}],
                 "stockpiles": [], "recipes": []}
        proof = ws.prove_you_can_get_there(ground, goods, START)
        self.assertFalse(proof["ok"])
        self.assertIn("far seam", proof["cut off"])

    def test_a_valley_with_no_river_is_all_one_piece(self):
        dry = a_valley(river=False)
        there = ws.drivable(dry, START)
        self.assertGreater(len(there), 0.5 * dry["nx"] * dry["nz"])

    def test_a_machine_will_not_climb_a_wall(self):
        ground = a_valley(river=False)
        nx, cell = ground["nx"], ground["cell"]
        # A cliff straight across the valley: nothing steps over it.
        for j in range(ground["nz"]):
            for i in range(nx // 2, nx // 2 + 2):
                ground["h"][j * nx + i] += 6.0
        there = ws.drivable(ground, START)
        beyond = ws._cell_of(ground, ground["x0"] + (nx - 4) * cell, START[1])
        self.assertNotIn(beyond, there)
        self.assertGreater(6.0 / cell, ws.CLIMB, "the wall has to be steeper than the limit")


class TheChainItself(unittest.TestCase):
    def test_the_work_scale_lands_on_the_recipes_that_were_already_there(self):
        """The two recipes in the mine room were written before this file and
        are not touched by it: smelting copper at 2,000 J/kg and drawing wire
        at 500. Both are their real specific energies at WORK_SCALE, which is
        why the scale is that number and not a rounder one."""
        recipes = {step.name: step.as_recipe() for step in ws.CHAIN}
        self.assertEqual(2000.0, recipes["smelt copper"]["work_j_per_kg"])
        self.assertEqual(500.0, recipes["draw wire"]["work_j_per_kg"])
        self.assertEqual({"copper ore": 1.0}, recipes["smelt copper"]["in"])
        self.assertEqual({"copper": 0.30}, recipes["smelt copper"]["out"])

    def test_aluminium_is_the_dearest_thing_in_the_game(self):
        """Hall-Heroult, and the ordering is the point of keeping the real
        energies: a player who smelts aluminium should feel it."""
        by_name = {step.name: step for step in ws.CHAIN}
        self.assertGreater(by_name["smelt aluminium"].real_mj_per_kg,
                           8 * by_name["smelt copper"].real_mj_per_kg)
        self.assertEqual(max(step.real_mj_per_kg for step in ws.CHAIN),
                         by_name["smelt aluminium"].real_mj_per_kg)

    def test_no_recipe_makes_more_mass_than_it_is_given(self):
        for step in ws.CHAIN:
            with self.subTest(step.name):
                self.assertLessEqual(sum(step.makes.values()), sum(step.takes.values()) + 1e-9,
                                     f"{step.name} makes mass out of nothing")

    def test_the_block_is_the_room_s_own_and_a_room_can_read_it(self):
        """What comes out has to be the goods block machine_goods already
        knows, or the world is a document nobody can open."""
        import machine_goods
        spec = {"goods": ws.place(a_valley(), 4, start_xz=START)}
        goods = machine_goods.Goods(spec)
        self.assertEqual(len(spec["goods"]["deposits"]), len(goods.deposits))
        self.assertTrue(any(p.get("rack") for p in goods.stockpiles))
        for pile in goods.stockpiles:
            self.assertIsNotNone(goods.by_name(pile["name"]))


class TheRealValley(unittest.TestCase):
    """The engine's own ground, not one written here."""

    @unittest.skipUnless(os.environ.get("BANJO_LIVE_ENGINE"), "needs BANJO_LIVE_ENGINE")
    def test_a_new_game_in_the_valley_is_playable(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import build_explore_world as builder

        ground = builder.read_ground(Path(os.environ["BANJO_LIVE_ENGINE"]))
        made = ws.new_world(ground, seed=1, start_xz=(0.0, 0.0))
        self.assertTrue(made["proof"]["ok"])
        self.assertEqual({}, made["proof"]["can make it"]["stranded"])
        self.assertEqual({}, made["proof"]["can get there"]["cut off"])
        # Every seam in a valley 39 m across, and every one of them somewhere
        # a rover can actually drive.
        got = {d["substance"] for d in made["goods"]["deposits"]}
        self.assertEqual({s.substance for s in ws.GROUND_HOLDS}, got)


if __name__ == "__main__":
    unittest.main(verbosity=2)
