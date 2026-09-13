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
    def test_the_library_speaks_abi_16(self):
        # 14 added heat, chemistry and gas; 15 added terrain and water on top;
        # 16 made heat change what things can carry.
        self.assertEqual(banjo.library().banjo_abi_version(), 16)
        self.assertEqual(banjo.ABI_VERSION, 16)

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


# ---- heat and strength (ABI 16, docs/thermal-mechanics.md) ------------------

def peg_assembly(tag: str = "", x: float = 0.0, gate: bool = True) -> list[dict]:
    """An anchored oak gatepost, a 40 mm oak peg standing 5 mm off its face, and
    a 32 kg iron gate hanging 5 mm under the peg -- tests/thermal_mechanics_tests.cpp's."""
    bodies = [box(f"{tag}post", "oak", (0.16, 1.6, 0.16), (x, 0.8, 0.0), True),
              box(f"{tag}peg", "oak", (0.04, 0.04, 0.16), (x, 1.4, 0.165))]
    if gate:
        bodies.append(box(f"{tag}gate", "iron", (0.32, 0.32, 0.04), (x, 1.215, 0.205)))
    return bodies


def hang(world, tag: str = "", x: float = 0.0) -> int:
    peg = world.fix(f"{tag}post", f"{tag}peg", (x, 1.4, 0.08), (0, 0, 1), 0.0, 800.0,
                    member=f"{tag}peg")
    world.fix(f"{tag}peg", f"{tag}gate", (x, 1.375, 0.205), (0, 1, 0))
    return peg


def joint(world, joint_id: int):
    return next(j for j in world.joints() if j.id == joint_id)


class StrengthThroughTheLibrary(unittest.TestCase):
    def test_a_heated_peg_gives_way_under_its_gate_and_says_why(self):
        scene = {"plasticity": True, "bodies": peg_assembly() + peg_assembly("cold ", 3.0)}
        with banjo.World(scene, cell_size_m=0.04) as world:
            hot, cold = hang(world), hang(world, "cold ", 3.0)
            run(world, 3.0)
            pin = joint(world, hot)
            self.assertEqual(pin.member, "peg")
            self.assertEqual(pin.rated_shear_n, 800.0)
            self.assertEqual(pin.capacity_fraction, 1.0)
            # The weld: nothing named, so exactly what was declared.
            weld = next(j for j in world.joints() if j.b == "gate")
            self.assertEqual(weld.member, "")
            world.heat("peg", 2000.0, 300.0)
            parted = None
            for step in range(int(round(120.0 / DT))):
                world.advance(DT)
                if step % 24 == 0 and not joint(world, hot).attached:
                    parted = joint(world, hot)
                    break
            self.assertIsNotNone(parted, "the heated peg gave way within 120 s of 2 kW")
            self.assertGreater(parted.parted_load_n, parted.parted_capacity_n,
                               "it let go because the load passed what was left")
            self.assertIn("sheared", parted.parted_because)
            self.assertIn("peg", parted.parted_because)
            twin = joint(world, cold)
            self.assertTrue(twin.attached)
            self.assertGreater(twin.capacity_fraction, 0.99)
            state = {m.name: m for m in world.body_mechanics()}
            peg = state["peg"]
            self.assertTrue(peg.tracked)
            self.assertIn("EN 1995-1-2", peg.law)
            self.assertEqual(peg.provenance, "reference-derived")
            self.assertGreater(peg.char_m, 0.0, "its surface layer has charred")
            self.assertLess(peg.shear, 0.5)
            self.assertLessEqual(peg.shear_if_cooled, 1.0 - 0.9 * (1 - (0.034 * 0.034) / (0.04 * 0.04)),
                                 "cooled, the char would stay")
            self.assertEqual(peg.section_m, (0.04, 0.04))
            report = world.mechanics_report(with_laws=True)
            self.assertEqual({law["material"] for law in report["laws"]}, {"oak", "iron", "concrete"})
            self.assertTrue(report["limitations"])
            self.assertTrue(any(a["member"] == "peg" and not a["attached"] and a["parted_because"]
                                for a in report["attachments"]))
            # No spring was made of anything: nothing was handed over as heat.
            self.assertEqual(world.energy().mechanical_in_j, 0.0)

    def test_only_what_has_a_strength_can_be_made_of_something(self):
        with banjo.World({"bodies": peg_assembly()}, cell_size_m=0.04) as world:
            pin = world.hinge("post", "peg", (0, 1.4, 0.08), (0, 0, 1))
            with self.assertRaises(banjo.BanjoError):
                world.joint_member(pin, "peg")
            fixing = world.fix("post", "peg", (0, 1.4, 0.08), (0, 0, 1), 0.0, 800.0)
            with self.assertRaises(banjo.BanjoError):
                world.joint_member(fixing, "gate")   # not one of its two ends
            world.joint_member(fixing, "peg")
            self.assertEqual(joint(world, fixing).member, "peg")
            world.joint_member(fixing, "")           # back to the declared numbers
            self.assertEqual(joint(world, fixing).member, "")
            self.assertEqual(joint(world, fixing).holds_shear_n, 800.0)

    def test_a_member_with_no_declared_strength_holds_its_own_section(self):
        with banjo.World({"bodies": peg_assembly(gate=False)}, cell_size_m=0.04) as world:
            fixing = world.fix("post", "peg", (0, 1.4, 0.08), (0, 0, 1), member="peg")
            pin = joint(world, fixing)
            # Oak's catalogue shear strength, 11 MPa, across 40 x 40 mm.
            self.assertAlmostEqual(pin.rated_shear_n, 11.0e6 * 0.04 * 0.04, delta=1.0)
            self.assertAlmostEqual(pin.rated_tension_n, 90.0e6 * 0.04 * 0.04, delta=1.0)

    def test_the_laws_are_readable_without_a_world(self):
        laws = banjo.thermo_model()["model"]["mechanical_laws"]
        oak = next(law for law in laws if law["material"] == "oak")
        self.assertAlmostEqual(oak["char_k"], 573.15)
        self.assertIn("EN 1995-1-2", oak["source"])
        self.assertEqual(oak["provenance"], "reference-derived")
        iron = next(law for law in laws if law["material"] == "iron")
        self.assertTrue(iron["recovers_on_cooling"])
        concrete = next(law for law in laws if law["material"] == "concrete")
        self.assertFalse(concrete["recovers_on_cooling"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
