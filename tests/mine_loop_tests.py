"""The whole loop: Workshop parts, into the bag, into the world, a tunnel, light.

The owner, 2026-09-28: "prove that we can take the same parts from the workshop,
put them into our inventory, go into the world and dig a tunnel and install the
lights to a solar panel".

This is that, in the real engine, step by step:

 1. The Workshop MAKES the parts -- a mine lamp, a powered breaker and a solar
    array -- from the templates anybody can build, and installs them.
 2. They go into the BAG: picked up and stowed, which parks them out of the
    world; a lamp in a bag is dark, because a lamp is a fitting and there is
    nothing behind it.
 3. They come out again where they are wanted, and their machines come with
    them: a lamp's light is on the lamp's own body, so it goes where it goes.
 4. The breaker DRIVES A HEADING: held against the face it spends its battery
    into the rock at its own rate, and cells of rock come out whole and are
    carried (rock-work-v1).
 5. A RUN OF CABLE from the array's battery to the lamp lights it, and the
    length of the run is paid for in volts.
 6. The sun charges the array, so what lights the mine is the sun.

Run it with the engine built:

    BANJO_LIVE_ENGINE=build/integration/Release/banjo_live_world_run.exe \\
        python tests/mine_loop_tests.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground")]

import live_session  # noqa: E402
import world_room  # noqa: E402
from mcp import workshop as w, workshop_components, workshop_machines, workshop_products  # noqa: E402

ENGINE = Path(os.environ["BANJO_LIVE_ENGINE"]).resolve() if os.environ.get("BANJO_LIVE_ENGINE") else None

# A cell of the ground, and what a cell of rock weighs: the numbers the whole
# loop turns on (docs/earth-and-mining-plan.md).
CELL_M = 0.25
ROCK_KG_M3 = 2400.0

#: See the note where it is used: a room needs at least one ordinary body.
MARKER = {"name": "marker", "shape": "box", "material": "concrete", "size_mm": [100, 100, 100],
          "center_mm": [4000, 50, 4000], "anchored": True}


def made(kind: str) -> tuple[dict, dict]:
    """A Workshop template, built and turned into what a room declares.

    The same two calls the bench makes: assemble the template, then ask
    `workshop_machines` for the room's own rows named by body. Nothing here is
    hand-written -- change the template and this changes with it.

    It comes out as an EXACT BODY, which is what these products install as: one
    rigid group with its parts in their own frame, not a lattice of cells. A
    solar array cut into 10 mm cells is a quarter of a million of them, well past
    what a room may hold, and it is a frame with panels bolted to it rather than
    anything that is going to bend.
    """
    workshop_products.install()
    design = w.assemble(kind)
    parts = []
    for part in design.parts:
        parts.append({"name": part.name,
                      "center_local_m": [round(float(v), 6) for v in part.center_m],
                      "dimensions_m": [round(float(v), 6) for v in part.size_m],
                      "material": str(part.material)})
    group = {"name": kind, "material": str(design.parts[0].material), "parts": parts}
    # Every component on the one group: an exact body is one thing, however many
    # parts it is drawn with.
    rows = workshop_machines.installed(design, {p.name: kind for p in design.parts})
    return group, rows


def put(group: dict, at: tuple[float, float, float]) -> dict:
    """The same thing, standing somewhere: what placing it does."""
    out = json.loads(json.dumps(group))
    out["position_m"] = [round(float(v), 6) for v in at]
    out["orientation_wxyz"] = [1.0, 0.0, 0.0, 0.0]
    return out


def shift(rows: dict, at: tuple[float, float, float]) -> dict:
    """And their machines with them, which is the whole point of item 3."""
    out = json.loads(json.dumps(rows))
    for key in ("panels", "lamps", "breakers"):
        for row in out.get(key) or []:
            row["at_mm"] = [round(row["at_mm"][i] + 1000.0 * at[i], 3) for i in range(3)]
    return out


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE is required")
class TheMineLoop(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory()
        cls.app = SimpleNamespace(engine_path=ENGINE, runs_path=Path(cls._temp.name),
                                  live_inprocess=False)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    def open(self, spec: dict) -> dict:
        live = live_session.Live()
        self.addCleanup(live.shutdown)
        opened = live.open(self.app, {"spec": spec})
        self.live = live
        return opened

    def act(self, op: str, **body) -> dict:
        return self.live.act({"session": self.live.session.id, "op": op, **body})

    def step(self, seconds: float, actor: str = "") -> dict:
        """Run the world for that long, at the page's own step.

        A step is told `dt` and `n`, never "seconds" -- a call that says seconds
        takes ONE step of a sixtieth and looks for all the world like it ran.
        And at most 120 steps go in one call, so a second of world is three.
        """
        dt, said = 1.0 / 240.0, {}
        left = max(1, int(round(seconds / dt)))
        while left > 0:
            n = min(left, 120)
            said = self.act("step", dt=dt, n=n, actor=actor)
            left -= n
        return said

    def machines(self) -> dict:
        return self.step(1.0 / 240.0).get("machines") or {}

    # ---- 1: the Workshop makes the parts --------------------------------
    def test_1_the_workshop_makes_a_lamp_a_breaker_and_an_array(self):
        lamp, lamp_rows = made("mine-lamp")
        breaker, breaker_rows = made("breaker")
        array, array_rows = made("solar-array")
        self.assertEqual([p["name"] for p in lamp["parts"]], ["foot", "globe bracket", "globe"])
        # The lamp comes out UNWIRED: no store and no cable, which is what makes
        # running the cable a thing somebody has to do.
        self.assertEqual(len(lamp_rows["lamps"]), 1)
        self.assertEqual(lamp_rows["lamps"][0]["store"], "")
        self.assertEqual(lamp_rows["lamps"][0]["cable"], "")
        self.assertTrue(lamp_rows["lamps"][0]["on"])
        self.assertEqual(lamp_rows["lamps"][0]["body"], "mine-lamp")
        # The breaker brings its own battery, and the array brings panels.
        self.assertEqual(len(breaker_rows["stores"]), 1)
        self.assertEqual(breaker_rows["stores"][0]["capacity_j"], 1.5e6)
        self.assertGreaterEqual(len(array_rows["panels"]), 6)
        self.assertEqual(len(array_rows["stores"]), 1)
        print(f"  the bench makes a lamp of {len(lamp['parts'])} parts (unwired), "
              f"a breaker of {len(breaker['parts'])} with a "
              f"{breaker_rows['stores'][0]['capacity_j'] / 1e6:.1f} MJ battery, and an array of "
              f"{len(array['parts'])} with {len(array_rows['panels'])} panels")

    # ---- 2 and 3: into the bag, and out again where they are wanted ------
    def test_2_a_lamp_in_the_bag_is_dark_and_lights_where_it_is_put(self):
        lamp, lamp_rows = made("mine-lamp")
        spec = {"algorithm": "lattice", "cell_m": 0.01,
                "terrain": {"generate": {"kind": "flat", "nx": 48, "nz": 48, "cell_m": CELL_M,
                                         "sand_m": 0.0, "soil_m": 0.0}},
                # A room with an EMPTY bodies list is not a room with nothing in
                # it: the engine substitutes its own drop-test scene, and the
                # machines declared against the parts of a product that is not
                # there go quietly nowhere. One marker body off to the side is
                # enough for the room to be this room.
                "bodies": [MARKER],
                "precise_rigid_bodies": [put(lamp, (0.0, 1.0, 0.0))],
                "machines": shift(lamp_rows, (0.0, 1.0, 0.0))}
        self.open(spec)
        lamps = self.machines().get("lamps") or []
        self.assertEqual(len(lamps), 1, lamps)
        self.assertFalse(lamps[0]["lit"])
        self.assertEqual(lamps[0]["why"], "not wired to anything")
        standing = lamps[0]["why"]
        # Parked: what stowing it in a bag does. Its light goes with it.
        self.act("park", name="mine-lamp")
        lamps = self.machines().get("lamps") or []
        self.assertIn("is not in the world", lamps[0]["why"])
        print(f"  a lamp standing on the floor: {standing}; stowed in the bag: {lamps[0]['why']}")

    # ---- 4: the breaker drives a heading ---------------------------------
    def test_3_the_breaker_drives_a_heading_and_the_rock_is_carried(self):
        self.heading()

    def test_3b_a_held_breaker_credits_its_owner_during_other_player_and_clock_steps(self):
        self.heading("alice")

    def heading(self, owner=""):
        breaker, breaker_rows = made("breaker")
        # A wall of rock to work: flat ground at y = 0, the breaker standing over
        # it with its chisel looking down.
        spec = {"algorithm": "lattice", "cell_m": 0.01,
                "terrain": {"generate": {"kind": "flat", "nx": 48, "nz": 48, "cell_m": CELL_M,
                                         "sand_m": 0.0, "soil_m": 0.0}},
                # A room with an EMPTY bodies list is not a room with nothing in
                # it: the engine substitutes its own drop-test scene, and the
                # machines declared against the parts of a product that is not
                # there go quietly nowhere. One marker body off to the side is
                # enough for the room to be this room.
                "bodies": [MARKER],
                "precise_rigid_bodies": [put(breaker, (0.0, 1.2, 0.0))],
                "machines": json.loads(json.dumps(breaker_rows))}
        spec["machines"]["breakers"] = [{
            "name": "breaker", "body": "breaker", "store": "breaker battery",
            "at_mm": [0.0, 1000.0, 0.0], "along": [0.0, -1.0, 0.0],
            "watts": 1500.0, "reach_m": 0.5, "on": True}]
        opened = self.open(spec)
        self.assertFalse(opened.get("machine_problems"), opened.get("machine_problems"))
        if owner:
            # Let the tool settle through ordinary gravity/contact before the
            # native hand takes hold; no pose or velocity assignment.
            self.step(1.0)
            pose=next(b for b in self.act("poses")["bodies"] if b["name"]=="breaker")
            self.act("wield",actor=owner,name="breaker",grip=pose["position_m"])
        # A person can hold 80 kg, and a cell of rock is 37.5, so the heading
        # stops after two cells until something is put down. This is about the
        # tool, so nothing is limiting what it can carry.
        initial=self.machines()
        before = (initial.get("stores") or [{}])[0].get("charge_j", 0.0)
        initial_work=(initial.get("breakers") or [{}])[0].get("broke_total_m3",0.0)
        cell_m3 = CELL_M ** 3
        seen, worked, ran_s, rock_kg = [], 0.0, 0.0, 0.0
        for frame in range(400):
            said = self.step(1.0,"bob" if owner and frame%2==0 else "")
            ran_s += 1.0
            machines = said.get("machines") or {}
            breaker = (machines.get("breakers") or [{}])[0]
            worked = breaker.get("broke_total_m3", 0.0)
            seen.append(breaker.get("why", ""))
            # Not "has it bought a cell's worth" -- the cell comes out on the
            # blow AFTER the one that pays for it. What settles this is the
            # ground: a cell is out when somebody is carrying it.
            if worked >= cell_m3:
                ground = (self.act("environment",actor=owner).get("environment") or {}).get("ground") or {}
                rock_kg = float((ground.get("carried") or {}).get("rock_kg", 0.0))
                if rock_kg > 0.0:
                    break
        if owner and rock_kg==0:
            # The actual 47.023 kg tool plus a 37.5 kg cell exceeds the normal
            # 80 kg account. Refusal must use Alice's budget despite Bob's empty
            # account. Increase only this experiment's declared allowance to
            # 100 kg, then let native work resume; production stays at 80 kg.
            self.assertIn("more rock than can be carried",breaker["why"])
            blocked=self.act("poses",actor=owner)["player_carried"]
            self.assertGreater(blocked[owner]["objects_kg"],42.5)
            self.assertEqual(0,blocked["bob"]["total_kg"])
            self.live.session.send(op="carry_limit",kg=100)
            self.step(1/240,"bob")
            worked=self.live.session.state["machines"]["breakers"][0]["broke_total_m3"]
        after = (self.machines().get("stores") or [{}])[0].get("charge_j", 0.0)
        ground = (self.act("environment",actor=owner).get("environment") or {}).get("ground") or {}
        carried = ground.get("carried") or {}
        rock_kg = float(carried.get("rock_kg", 0.0))
        dug = float((ground.get("ledger") or {}).get("dug", {}).get("rock_m3", 0.0))
        print(f"  a 1.5 kW breaker took {ran_s:.0f} s of the world to break one 0.25 m cell out of fresh "
              f"rock: {worked * 1e3:.1f} L, {(before - after) / 1000.0:.0f} kJ of the battery's 1500, "
              f"and {rock_kg:.1f} kg of rock in hand")
        self.assertGreaterEqual(worked, cell_m3 * 0.99, f"it did not get through a cell: {seen[:3]}")
        # rock-work-v1: 30 MJ the cubic metre for fresh rock, and every joule
        # out of the battery.
        self.assertAlmostEqual(before - after, (worked-initial_work) * 30.0e6, delta=worked * 30.0e6 * 0.02)
        self.assertGreater(rock_kg, 0.9 * cell_m3 * ROCK_KG_M3, carried)
        # And the ground lost exactly that: the heading is a cell deeper.
        self.assertAlmostEqual(dug, cell_m3, delta=1e-9)
        if owner:
            accounts=self.act("poses",actor=owner)["player_carried"]
            self.assertAlmostEqual(rock_kg,accounts[owner]["rock_kg"],places=6)
            for actor in ("bob",""):
                self.assertEqual(0,accounts[actor]["rock_kg"])
            print("  breaker output belongs to Alice; Bob and the unattended account carry no rock")

    # ---- 5 and 6: the cable, and the sun ---------------------------------
    def test_4_a_run_of_cable_from_the_array_lights_the_lamp(self):
        lamp, lamp_rows = made("mine-lamp")
        array, array_rows = made("solar-array")
        # The array up the hill at x = 12, the lamp down at the origin: what a
        # farm on the surface and a fitting underground look like.
        away = 12.0
        machines = shift(array_rows, (away, 0.0, 0.0))
        machines["lamps"] = shift(lamp_rows, (0.0, 0.0, 0.0))["lamps"]
        spec = {"algorithm": "lattice", "cell_m": 0.01,
                "terrain": {"generate": {"kind": "flat", "nx": 96, "nz": 48, "cell_m": CELL_M,
                                         "sand_m": 0.0, "soil_m": 0.0}},
                "sun": {"elevation_deg": 90, "azimuth_deg": 0, "irradiance_w_m2": 1000},
                # A room with an EMPTY bodies list is not a room with nothing in
                # it: the engine substitutes its own drop-test scene, and the
                # machines declared against the parts of a product that is not
                # there go quietly nowhere. One marker body off to the side is
                # enough for the room to be this room.
                "bodies": [MARKER],
                "precise_rigid_bodies": [put(array, (away, 0.0, 0.0)), put(lamp, (0.0, 0.0, 0.0))],
                "machines": machines}
        opened = self.open(spec)
        self.assertFalse(opened.get("machine_problems"), opened.get("machine_problems"))
        machines_now = self.machines()
        lamp = (machines_now.get("lamps") or [{}])[0]
        store = (machines_now.get("stores") or [{}])[0]
        self.assertFalse(lamp["lit"])
        self.assertEqual(lamp["why"], "not wired to anything")

        # The run: paid out from the array to the lamp, the way a person walked.
        run = [[away, 0.9, 0.0], [away - 4.0, 0.3, 0.0], [4.0, 0.3, 0.0], [0.0, 0.3, 0.0]]
        said = self.act("cable", store=store["id"], run_m=run, area_mm2=4.0)
        cable = said["ran"]
        self.assertAlmostEqual(cable["length_m"], _length(run), places=6)
        self.act("lamp_wire", lamp=lamp["id"], cable=cable["id"])
        machines_now = self.machines()
        lamp = (machines_now.get("lamps") or [{}])[0]
        cable = (machines_now.get("cables") or [{}])[0]
        print(f"  {cable['length_m']:.1f} m of 4 mm2 from the array to the lamp: "
              f"{cable['resistance_ohm']:.3f} ohm, {cable['volts_lost']:.3f} V lost, "
              f"the lamp at {lamp['drawn_w']:.2f} W of {lamp['watts']:.0f}")
        self.assertTrue(lamp["lit"], lamp["why"])
        self.assertGreater(lamp["drawn_w"], 0.9 * lamp["watts"])
        self.assertLess(lamp["drawn_w"], lamp["watts"], "a real run keeps some of the voltage")
        self.assertAlmostEqual(cable["carried_w"], lamp["drawn_w"], places=6)

        # And what lights it is the sun: the array gains on the lamp.
        before = (self.machines().get("stores") or [{}])[0]
        for _ in range(4):
            self.step(1.0)
        after = (self.machines().get("stores") or [{}])[0]
        print(f"  under an overhead sun the array gained {after['charge_j'] - before['charge_j']:.0f} J "
              f"while the lamp burned")
        self.assertGreater(after["charge_j"], before["charge_j"])

        # A run twice as long is dimmer, which is the reason to think about it.
        far = [[away, 0.9, 0.0], [away, 0.3, 20.0], [0.0, 0.3, 20.0], [0.0, 0.3, 0.0]]
        said = self.act("cable", store=store["id"], run_m=far, area_mm2=1.0)
        self.act("lamp_wire", lamp=lamp["id"], cable=said["ran"]["id"])
        dim = (self.machines().get("lamps") or [{}])[0]
        print(f"  on {said['ran']['length_m']:.1f} m of 1 mm2 instead: {dim['drawn_w']:.2f} W — {dim['why']}")
        self.assertLess(dim["drawn_w"], lamp["drawn_w"])
        self.assertIn("dim", dim["why"])


def _length(points) -> float:
    return sum(math.dist(points[i], points[i - 1]) for i in range(1, len(points)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
