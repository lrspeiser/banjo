"""Heat, chemistry and gas through the C library, from Python.

The point of the C face is that anything able to call a C function can drive a
world, so everything the thermochemical network does has to be reachable
through it: declaring what things contain, lighting them, reading how hot they
are and what the gas is doing, and the ledger that says where the energy went.

Needs the library: BANJO_LIBRARY=<build>/Release/banjo.dll.
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bindings" / "python"))

import banjo  # noqa: E402

DT = 1.0 / 240.0


def box(name, material, size, at, anchored=False, **extra):
    body = {"name": name, "shape": "box", "material": material, "dimensions_m": list(size),
            "center_m": list(at), "anchored": anchored}
    body.update(extra)
    return body


def cylinder(heater_w=800.0, heater_s=30.0):
    """Anchored walls with a glass front, an iron piston over 0.4 m of argon,
    and an iron block resting on the piston."""
    return {"plasticity": True, "bodies": [
        box("cylinder base", "concrete", (0.48, 0.08, 0.48), (0, 0.04, 0), True),
        box("cylinder wall left", "concrete", (0.08, 1.2, 0.48), (-0.2, 0.68, 0), True),
        box("cylinder wall right", "concrete", (0.08, 1.2, 0.48), (0.2, 0.68, 0), True),
        box("cylinder wall back", "concrete", (0.32, 1.2, 0.08), (0, 0.68, -0.2), True),
        box("cylinder window", "glass", (0.32, 1.2, 0.08), (0, 0.68, 0.2), True),
        box("piston", "iron", (0.24, 0.08, 0.24), (0, 0.52, 0)),
        box("load", "iron", (0.16, 0.16, 0.16), (0, 0.64, 0))],
        "thermo": {"gas_regions": [{"name": "cylinder gas", "contents": {"argon": 1},
                                    "piston": "piston", "height_m": 0.4, "balance": True}],
                   "heaters": [{"target": "cylinder gas", "power_w": heater_w,
                                "seconds": heater_s}]}}


def run(world, seconds):
    for _ in range(int(round(seconds / DT))):
        world.advance(DT)


class HeatThroughTheLibrary(unittest.TestCase):
    def test_the_library_speaks_an_abi_with_heat_in_it(self):
        # 14 added heat, chemistry and gas, and every ABI after it keeps them.
        # Pinned to exactly 15, this failed the day the hand's strokes made 16
        # -- which says nothing about heat.
        self.assertGreaterEqual(banjo.library().banjo_abi_version(), 14)
        self.assertEqual(banjo.ABI_VERSION, banjo.library().banjo_abi_version())

    def test_the_model_is_readable_without_a_world(self):
        model = banjo.thermo_model()["model"]
        reactions = {r["id"]: r for r in model["reactions"]}
        self.assertIn("wood combustion", reactions)
        self.assertEqual(reactions["wood combustion"]["provenance"], "demonstration")
        self.assertAlmostEqual(reactions["wood combustion"]["heat_released_j_per_kg_at_298k"],
                               16.0e6, delta=1.0)
        self.assertIn("oak", model["compositions"])
        self.assertIn("dry wood", model["compositions"]["oak"])

    def test_a_hot_log_declared_in_the_scene_burns(self):
        scene = {"bodies": [box("log", "oak", (0.12, 0.12, 0.48), (0, 0.06, 0),
                                temperature_k=1000.0)]}
        with banjo.World(scene, cell_size_m=0.04) as world:
            run(world, 2.0)
            log = {h.name: h for h in world.heat_states()}["log"]
            self.assertTrue(log.reacting)
            self.assertGreater(log.heat_release_w, 1000.0)
            self.assertTrue(math.isfinite(log.remaining_s) and log.remaining_s > 600.0,
                            "an estimated remaining burn time, under current conditions")
            energy = world.energy()
            self.assertLess(abs(energy.residual_j), 1e-9 * abs(energy.stored_j))
            self.assertGreater(energy.matter_out_kg, energy.matter_in_kg)
            self.assertAlmostEqual(energy.stored_j, energy.chemical_j + energy.thermal_j,
                                   delta=1e-6 * abs(energy.stored_j))

    def test_heat_from_the_library_lights_a_log(self):
        scene = {"bodies": [box("log", "oak", (0.12, 0.12, 0.48), (0, 0.06, 0))]}
        with banjo.World(scene, cell_size_m=0.04) as world:
            self.assertEqual(world.heat_states(), [], "a cold log is not yet in the network")
            heater = world.heat("log", 10000.0, 60.0)
            self.assertGreater(heater, 0)
            run(world, 90.0)
            log = {h.name: h for h in world.heat_states()}["log"]
            self.assertTrue(log.reacting, f"lit: {log}")
            self.assertAlmostEqual(world.energy().heater_in_j, 600000.0, delta=1e-3)

    def test_a_heated_gas_lifts_a_load(self):
        with banjo.World(cylinder(), cell_size_m=0.04) as world:
            world.slide("cylinder base", "piston", (0, 0.52, 0), (0, 1, 0), -0.2, 0.6, 0.0)
            before = world.body("piston").position_m[1]
            mechanical0 = world.energy().mechanical_j
            run(world, 30.0)
            gas = world.gas_regions()[0]
            rose = world.body("piston").position_m[1] - before
            self.assertEqual(gas.piston, "piston")
            self.assertGreater(rose, 0.1)
            self.assertAlmostEqual(gas.stroke_m, rose, delta=0.002)
            self.assertAlmostEqual(gas.height_m, 0.4 + gas.stroke_m, delta=0.002)
            energy = world.energy()
            self.assertGreater(energy.work_to_bodies_j, 0.0)
            self.assertAlmostEqual(energy.mechanical_j - mechanical0, energy.work_to_bodies_j,
                                   delta=0.03 * energy.work_to_bodies_j)

    def test_a_declaration_it_does_not_understand_is_refused_by_name(self):
        scene = {"bodies": [box("log", "oak", (0.12, 0.12, 0.48), (0, 0.06, 0))]}
        with banjo.World(scene, cell_size_m=0.04) as world:
            with self.assertRaises(banjo.BanjoError) as caught:
                world.declare({"heaters": [{"target": "log", "tempreature": 3}]})
            self.assertIn("tempreature", str(caught.exception))
            with self.assertRaises(banjo.BanjoError):
                world.heat("nothing called this", 1000.0, 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
