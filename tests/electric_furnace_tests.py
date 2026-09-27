"""The electric furnace: a box with a real inside.

A processor makes one thing of another on a deck. A furnace has to make its
INSIDE hot, and the inside is the point -- a steel shell, a refractory
lining, and the space the lining encloses, which is a real volume of real air
in the thermal network. These check the three things that makes true:

* what the lining decides. Heat leaves at U = k*A/t and an element of P watts
  holds the chamber at ambient + P/U, so the lining is what says whether a
  furnace can smelt iron or cannot burn lime. The bench answers that before
  anything is built.
* that a recipe's temperature, and nothing else, decides which machine works
  it -- so a recipe that gains or loses its heat moves between them on its
  own, and the Workshop's recipes cannot drift from the generator's chain.
* that the chamber is real in the engine: it heats, it holds, and it goes
  cold when the element stops.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tests/electric_furnace_tests.py

Without BANJO_LIVE_ENGINE the checks that need no engine still run.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground")]
import mcp  # noqa: E402,F401
from mcp import workshop as w, workshop_products  # noqa: E402
import fracture_lab, live_session, world_room, world_seed  # noqa: E402

ENGINE = Path(os.environ["BANJO_LIVE_ENGINE"]).resolve() if os.environ.get("BANJO_LIVE_ENGINE") else None
DT = 1 / 240


def defaults() -> dict:
    workshop_products.install()
    return {p.name: p.default for p in workshop_products.ELECTRIC_FURNACE_PARAMETERS}


class TheWorkshopsRecipesAreTheGamesChain(unittest.TestCase):
    """The Workshop's table and the generator's chain say the same thing.

    They are written out twice because mcp/ does not sit on playground's path
    -- a lazy import would work in the server and fail on the bench, which is
    the worst of both. So this is the join: every number, checked, and a drift
    names which one moved rather than showing up as a furnace that will not
    heat or a world nobody can finish.
    """

    def test_every_recipe_agrees_number_for_number(self):
        workshop_products.install()
        self.assertEqual({s.name for s in world_seed.CHAIN},
                         set(workshop_products.CATALOGUE_RECIPES),
                         "the same recipes, neither more nor fewer")
        for step in world_seed.CHAIN:
            row = workshop_products.CATALOGUE_RECIPES[step.name]
            with self.subTest(recipe=step.name):
                self.assertEqual(step.takes, row["in"])
                self.assertEqual(step.makes, row["out"])
                self.assertAlmostEqual(step.real_mj_per_kg * 1e6 * world_seed.WORK_SCALE,
                                       row["work_j_per_kg"], places=6,
                                       msg="the chain's real energy, taken down by WORK_SCALE")
                self.assertAlmostEqual(step.s_per_kg, row["s_per_kg"], places=9)
                self.assertAlmostEqual(step.needs_c, row["needs_c"], places=9)

    def test_the_temperature_alone_says_which_machine_works_it(self):
        workshop_products.install()
        hot, cold = workshop_products.FURNACE_RECIPES, workshop_products.PROCESSOR_RECIPES
        self.assertEqual(set(), set(hot) & set(cold), "a recipe belongs to one or the other")
        self.assertEqual(set(workshop_products.CATALOGUE_RECIPES), set(hot) | set(cold))
        self.assertTrue(all(r["needs_c"] > 0 for r in hot.values()))
        self.assertTrue(all(r["needs_c"] == 0 for r in cold.values()))
        # And the bench offers exactly those, so no build can be made that
        # cannot work: a processor told to smelt would stand at its bin.
        kinds = {a.name: a for a in w.ASSEMBLIES}
        self.assertEqual(tuple(sorted(hot)),
                         next(p for p in kinds["electric-furnace"].parameters if p.name == "recipe").choices)
        self.assertEqual(set(cold),
                         set(next(p for p in kinds["processor"].parameters if p.name == "recipe").choices))

    def test_a_processor_asked_to_smelt_says_why_it_cannot(self):
        """Refused twice, and the second one matters.

        The bench refuses first, on the parameter's own choices, which is
        what a person building one meets. Behind that the overrides refuse
        again with the reason -- and that is the one worth having, because
        the recipe list used to be looked up with a fallback to nothing: a
        processor built for a recipe it did not know came out perfectly
        formed, installed, powered up, and made nothing for ever.
        """
        workshop_products.install()
        with self.assertRaisesRegex(ValueError, "recipe must be one of"):
            w.assemble("processor", design_id="p", parameters={"recipe": "smelt copper"})
        with self.assertRaisesRegex(ValueError, "recipe must be one of"):
            w.assemble("electric-furnace", design_id="f", parameters={"recipe": "draw wire"})
        values = {p.name: p.default for p in
                  next(a for a in w.ASSEMBLIES if a.name == "processor").parameters}
        with self.assertRaisesRegex(ValueError, "no chamber to make hot"):
            workshop_products._processor_overrides(dict(values, recipe="smelt copper"), [])
        with self.assertRaisesRegex(ValueError, "the recipes it knows are"):
            workshop_products._processor_overrides(dict(values, recipe="brew tea"), [])
        with self.assertRaisesRegex(ValueError, "cold work"):
            workshop_products._electric_furnace_overrides(dict(defaults(), recipe="draw wire"), [])


class WhatTheLiningDecides(unittest.TestCase):
    """U = k*A/t, and the element holds the chamber at ambient + P/U."""

    def test_the_chamber_and_its_losses_come_out_of_the_geometry(self):
        values = defaults()
        volume, area, conductance = workshop_products._furnace_chamber(values)
        self.assertAlmostEqual(0.4 * 0.4 * 0.3, volume, places=9)
        self.assertAlmostEqual(2 * (0.16 + 0.12 + 0.12), area, places=9, msg="the inside's six faces")
        self.assertAlmostEqual(0.3 * 0.8 / 0.08, conductance, places=9, msg="k*A/t")
        self.assertAlmostEqual(20.0 + 5000.0 / 3.0, workshop_products.furnace_reaches_c(values), places=6)

    def test_a_thin_lining_cannot_smelt_and_the_bench_says_so_before_it_is_built(self):
        # 40 mm reaches 853 C, which will not burn lime at 900; 80 mm reaches
        # 1687 and smelts iron at 1538 with about 150 C in hand.
        reaches = {t: workshop_products.furnace_reaches_c(dict(defaults(), lining_m=t))
                   for t in (0.02, 0.04, 0.08, 0.12)}
        self.assertLess(reaches[0.02], 900.0)
        self.assertLess(reaches[0.04], 900.0)
        self.assertGreater(reaches[0.08], 1538.0)
        self.assertGreater(reaches[0.12], reaches[0.08], "more lining reaches further")
        for thin in (0.02, 0.04):
            with self.subTest(lining_m=thin), self.assertRaisesRegex(ValueError, "tops out at"):
                w.assemble("electric-furnace", design_id="f",
                           parameters={"recipe": "smelt iron", "lining_m": thin})
        # And it is refused for the recipe it was asked for, not in general:
        # 60 mm cannot smelt iron but burns lime perfectly well.
        w.assemble("electric-furnace", design_id="f",
                   parameters={"recipe": "burn lime", "lining_m": 0.06})
        with self.assertRaisesRegex(ValueError, "tops out at"):
            w.assemble("electric-furnace", design_id="f",
                       parameters={"recipe": "smelt iron", "lining_m": 0.06})

    def test_a_chamber_too_big_for_its_element_is_refused_too(self):
        # Losses go with the chamber's surface, so a big box on a small
        # element reaches nothing: four times the volume on the same 5 kW
        # tops out below even lime.
        big = dict(defaults(), chamber_w_m=0.8, chamber_d_m=0.8, chamber_h_m=0.6)
        self.assertLess(workshop_products.furnace_reaches_c(big), 900.0)
        with self.assertRaisesRegex(ValueError, "Thicken the lining, shrink the chamber, or fit a bigger element"):
            w.assemble("electric-furnace", design_id="f",
                       parameters={"recipe": "smelt copper", "chamber_w_m": 0.8,
                                   "chamber_d_m": 0.8, "chamber_h_m": 0.6})
        # The same box with an element to match is fine.
        w.assemble("electric-furnace", design_id="f",
                   parameters={"recipe": "smelt copper", "chamber_w_m": 0.8, "chamber_d_m": 0.8,
                               "chamber_h_m": 0.6, "element_w": 20000.0})

    def test_it_is_a_shell_round_a_lining_round_the_chamber(self):
        design = w.assemble("electric-furnace", design_id="f")
        by_name = {p.name: p for p in design.parts}
        self.assertEqual(17, len(design.parts))
        self.assertEqual({"concrete"}, {by_name[n].material for n in by_name if n.startswith("lining-")})
        self.assertEqual({"iron"}, {by_name[n].material for n in by_name if n.startswith("shell-")},
                         "a furnace shell is steel, and not the caller's choice")
        # The chamber is the gap: the lining's floor ends where the chamber
        # begins and its roof starts where the chamber ends.
        floor = by_name["lining-floor"]
        roof = by_name["lining-roof"]
        top_of_floor = floor.center_m[1] + floor.size_m[1] / 2.0
        under_roof = roof.center_m[1] - roof.size_m[1] / 2.0
        self.assertAlmostEqual(0.3, under_roof - top_of_floor, places=9, msg="the chamber's height, as declared")
        self.assertGreater(by_name["intake bin"].center_m[2], by_name["output bin"].center_m[2],
                           "intake ahead, output behind, as a processor's are")


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "needs BANJO_LIVE_ENGINE")
class TheChamberIsRealInTheEngine(unittest.TestCase):
    def test_it_heats_holds_and_goes_cold(self):
        """The whole of the furnace's physics, in one room of exact bodies.

        Exact bodies have no thermal model, which is why this could not be
        done at all until a gas region was allowed to stand among them. The
        chamber is not a body: it is the space the lining encloses.
        """
        spec = world_room.yard()
        spec["thermo"] = {"gas_regions": [{"name": "chamber", "volume_m3": 0.048,
                                           "wall_conductance_w_k": 3.0, "pressure_pa": 101325.0}]}
        spec = fracture_lab.validate(spec)
        with tempfile.TemporaryDirectory() as tmp:
            session = live_session.Session(ENGINE, spec, Path(tmp))
            try:
                def chamber():
                    said = session.send(op="thermo")
                    block = said.get("thermo") if isinstance(said.get("thermo"), dict) else said
                    return next(r for r in block["regions"] if r["name"] == "chamber")

                session.send(op="step", dt=DT, n=10)
                self.assertAlmostEqual(20.0, chamber()["temperature_k"] - 273.15, places=1,
                                       msg="it starts at the room's own temperature")

                # HEATED, it climbs toward ambient + P/U and stops there. 5 kW
                # on 3 W/K is 1687 C, so iron's 1538 is reachable and there is
                # no waiting for a temperature that will never come.
                session.send(op="heat", target="chamber", power_w=5000.0, seconds=600.0)
                session.send(op="step", dt=DT, n=int(40 / DT))
                hot = chamber()["temperature_k"] - 273.15
                self.assertGreater(hot, 1538.0, "it reaches iron inside 40 s")
                session.send(op="step", dt=DT, n=int(200 / DT))
                settled = chamber()["temperature_k"] - 273.15
                self.assertAlmostEqual(20.0 + 5000.0 / 3.0, settled, delta=2.0,
                                       msg="ambient + P/U, and it does not run away past it")
                self.assertAlmostEqual(5000.0, chamber()["wall_loss_w"], delta=5.0,
                                       msg="at a hold, what leaks out is what goes in")
            finally:
                session.close()

    def test_a_furnace_left_alone_goes_cold(self):
        spec = world_room.yard()
        spec["thermo"] = {"gas_regions": [{"name": "chamber", "volume_m3": 0.048,
                                           "wall_conductance_w_k": 3.0, "pressure_pa": 101325.0}]}
        spec = fracture_lab.validate(spec)
        with tempfile.TemporaryDirectory() as tmp:
            session = live_session.Session(ENGINE, spec, Path(tmp))
            try:
                def now_c():
                    said = session.send(op="thermo")
                    block = said.get("thermo") if isinstance(said.get("thermo"), dict) else said
                    return next(r for r in block["regions"] if r["name"] == "chamber")["temperature_k"] - 273.15

                session.send(op="heat", target="chamber", power_w=5000.0, seconds=15.0)
                session.send(op="step", dt=DT, n=int(15 / DT))
                was = now_c()
                self.assertGreater(was, 900.0)
                session.send(op="step", dt=DT, n=int(60 / DT))
                self.assertLess(now_c(), 60.0, "a minute later it is nearly cold again")
            finally:
                session.close()


if __name__ == "__main__":
    unittest.main()
