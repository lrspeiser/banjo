"""The tests-engines room, in the real engine: does a person see three machines
work?

tests/gas_pressure_tests.cpp pins the thermochemical network's promises with a
one-dimensional stand-in for the mechanics. This is the other half: the same
three machines built as a ROOM, run by the real engine with Jolt underneath,
because a piston that lifts in a spreadsheet and a piston that lifts in the
playground are not the same claim.

What it does not do is pin numbers tightly. A room has ground contact, lattice
bodies and a settling step in it, and the owner's line on this is that tests
need to produce results rather than repeat exactly. So each machine is asked
only for the thing that makes it that machine: the piston goes UP and keeps
going, the ball goes DOWN THE BARREL and stays gone, the rocket LEAVES THE
BENCH by a distance no bounce would explain.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))

import fracture_lab      # noqa: E402
import live_session      # noqa: E402
import world_room        # noqa: E402

ENGINE = next((p for p in [
    *([Path(os.environ["BANJO_LIVE_ENGINE"])] if os.environ.get("BANJO_LIVE_ENGINE") else []),
    ROOT / "build/integration/Release/banjo_live_world_run.exe",
    ROOT / "build/integration/banjo_live_world_run",
] if p.is_file()), None)

DT = 1.0 / 240.0


@unittest.skipIf(ENGINE is None, "no live engine built")
class ThreeMachinesRunInOneRoom(unittest.TestCase):
    """One mechanism, three shapes of it, all in /world?scene=tests-engines."""

    @classmethod
    def setUpClass(cls):
        spec = fracture_lab.validate(world_room.SCENES["tests-engines"]())
        cls._tmp = tempfile.TemporaryDirectory()
        cls.session = live_session.Session(ENGINE, spec, Path(cls._tmp.name))
        cls.start = cls._poses()
        # Ten seconds, sampled every second, so the rocket's flight -- which is
        # over in under two -- is caught as well as the steam engine's climb.
        cls.track = []
        for _ in range(10):
            cls.session.send(op="step", dt=DT, n=240)
            cls.track.append((cls._poses(), cls._thermo()))

    @classmethod
    def tearDownClass(cls):
        close = getattr(cls.session, "close", None)
        if close:
            close()
        cls._tmp.cleanup()

    @classmethod
    def _poses(cls):
        said = cls.session.send(op="poses")
        return {b["name"]: (b.get("position_m") or b.get("center_m"))
                for b in said.get("bodies") or [] if b.get("name")}

    @classmethod
    def _thermo(cls):
        said = cls.session.send(op="thermo")
        block = said.get("thermo") if isinstance(said.get("thermo"), dict) else said
        return ({r["name"]: r for r in block.get("regions") or []},
                {b.get("name", b.get("body")): b for b in block.get("bodies") or []})

    def test_the_steam_engine_boils_water_and_lifts_its_piston(self):
        """Boiling is what drives it: the water holds at 100 C and the steam it
        makes is the volume the piston has to make room for."""
        heights = [p["piston"][1] for p, _ in self.track]
        rise = heights[-1] - self.start["piston"][1]
        _, bodies = self.track[-1][1]
        water = bodies["boiler water"]
        self.assertAlmostEqual(100.0, water["temperature_k"] - 273.15, places=1,
                               msg="the boiler should hold at its boiling point")
        self.assertGreater(water.get("boiled_kg", 0.0), 0.01, "it should have boiled some water")
        self.assertGreater(rise, 0.25, f"the piston should have climbed; it went {rise:.3f} m")
        # And kept climbing, rather than being thrown up once and falling back.
        self.assertEqual(heights, sorted(heights),
                         "the piston should rise steadily, not bounce")

    def test_the_cannon_throws_its_ball_down_the_barrel(self):
        """The charge carries its own oxidiser, so a sealed breech burns it just
        as well -- and the gas it makes has one way out."""
        moved = self.track[-1][0]["ball"][0] - self.start["ball"][0]
        self.assertGreater(moved, 1.0, f"the ball should have been thrown; it went {moved:.3f} m")
        _, bodies = self.track[-1][1]
        self.assertLess(bodies["cannon charge"].get("fuel_kg", 1.0), 1.0e-4,
                        "the charge should be spent")

    def test_the_rocket_leaves_the_bench_on_its_own_exhaust(self):
        """Nothing is pushed against: the gas goes down the throat and the
        momentum of it carries the rocket up."""
        peak = max(p["rocket"][1] for p, _ in self.track)
        climb = peak - self.start["rocket"][1]
        self.assertGreater(climb, 2.0, f"the rocket should have flown; it reached {climb:.3f} m")
        # It is a rocket and not a firework on a stick: the push came from the
        # nozzle, so the motor must have done thrust work.
        thrusted = max(r["motor"].get("thrust_work_j", 0.0) for _, (r, _) in self.track)
        self.assertGreater(thrusted, 0.0, "the nozzle should have done work on the rocket")

    def test_a_sealed_region_never_pushes_its_vessel(self):
        """The breech is sealed and enormous while it fires, and it pushes the
        ball, not the room. Thrust is the momentum of what LEAVES -- a region
        with no vent has none, however hard it is pressed."""
        for _, (regions, _) in self.track:
            self.assertEqual(0.0, regions["breech"].get("thrust_n", 0.0),
                             "a sealed breech should report no thrust")
            self.assertEqual(0.0, regions["cylinder gas"].get("thrust_n", 0.0),
                             "a cylinder with a piston and no vent should report no thrust")


if __name__ == "__main__":
    unittest.main(verbosity=2)
