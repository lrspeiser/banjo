"""The room on /world, and the tools that change it.

The model's side is not tested here -- that needs a key and a paid round trip.
What is tested is everything underneath it: that the room opens, that the tools
do what they say, and above all that a change the engine would refuse is refused
HERE, where the thing that made it can be told about it.
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))

import fracture_lab      # noqa: E402
import live_session      # noqa: E402
import world_room        # noqa: E402

ENGINE = next((p for p in [
    ROOT / "build/integration/Release/banjo_live_world_run.exe",
    ROOT / "build/integration/banjo_live_world_run",
] if p.is_file()), None)


class TheRoomAsAuthored(unittest.TestCase):
    def test_every_material_in_the_catalogue_is_in_it(self):
        """The room is there to be experimented on, so it has to carry the whole
        catalogue: a room of three materials cannot show that what a thing is
        made of is what decides how it behaves."""
        used = {b["material"] for b in world_room.room()["bodies"]}
        self.assertEqual(used, set(world_room.MATERIALS),
                         f"missing from the room: {set(world_room.MATERIALS) - used}")

    def test_every_side_is_a_whole_number_of_cells(self):
        spec = world_room.room()
        cell_mm = spec["cell_m"] * 1000.0
        for body in spec["bodies"]:
            for axis, side in zip("xyz", body["size_mm"]):
                self.assertAlmostEqual(
                    side / cell_mm, round(side / cell_mm), places=6,
                    msg=f"{body['name']} is {side} mm on {axis}, which is not a whole "
                        f"number of {cell_mm:g} mm cells")

    def test_nothing_loose_is_buried_in_the_floor(self):
        """A body's centre is its middle, so an object on the floor sits at half
        its own height. Authoring one at y = 0 buries half of it, and the engine
        will push it out on the first step -- which looks like the room
        exploding for no reason."""
        for body in world_room.room()["bodies"]:
            if body.get("anchored"):
                continue
            bottom = body["center_mm"][1] - body["size_mm"][1] / 2.0
            self.assertGreaterEqual(bottom, -1e-6,
                                    f"{body['name']} starts {-bottom:.0f} mm into the floor")

    def test_it_fits_in_the_lane(self):
        spec = fracture_lab.validate(world_room.room())
        cells = sum(fracture_lab.body_cells(b, spec["cell_m"]) for b in spec["bodies"])
        self.assertLess(cells, 16000,
                        f"the room is {cells} cells and the lane holds about 16,000")

    def test_the_scene_the_engine_gets_asks_for_plasticity(self):
        """Without it nothing can hold a shape it was pushed into, so nothing
        can dent. It was set on the room, validated, and then dropped on the way
        to the engine, because the scene document only ever carried bodies."""
        document = fracture_lab.scene_document(fracture_lab.validate(world_room.room()))
        self.assertTrue(document["plasticity"],
                        "the engine is not being told to allow a permanent set")


    def test_there_is_something_of_every_material_to_drop_things_on(self):
        """Targets, not just things to throw.

        A room where the only thing that breaks is one glass pane teaches one
        fact. Every material has its own threshold and its own way of failing,
        and the only way to see that is to have one of each to aim at."""
        plates = [b for b in world_room.room()["bodies"] if "plate" in b["name"]]
        self.assertEqual({b["material"] for b in plates}, set(world_room.MATERIALS),
                         "not every material has something to drop things on")
        for material in world_room.MATERIALS:
            thicknesses = {b["size_mm"][1] for b in plates if b["material"] == material}
            self.assertGreater(len(thicknesses), 1,
                               f"{material} comes in only one thickness, so nothing "
                               f"there can show that thickness matters")

    def test_every_plate_is_bridged_rather_than_lying_on_the_floor(self):
        """What breaks a plate is a span under it.

        The same plate flat on the ground is held everywhere and will not break
        however hard it is hit, so a room of plates lying on the floor would
        have nothing to show."""
        room = world_room.room()["bodies"]
        for plate in [b for b in room if "plate" in b["name"]]:
            bottom = plate["center_mm"][1] - plate["size_mm"][1] / 2.0
            self.assertGreater(bottom, 50.0,
                               f"{plate['name']} sits {bottom:.0f} mm up, which is on "
                               f"the floor rather than on piers")


class TheToolsThatChangeIt(unittest.TestCase):
    def setUp(self):
        self.room = world_room.Room()

    def test_adding_something_puts_it_there(self):
        note = self.room.add_object(
            {"name": "test ball", "shape": "sphere", "material": "glass",
             "size_mm": [100, 100, 100], "position_mm": [0, 3000, -2500],
             "velocity_m_s": [0, 0, 0], "anchored": False})
        self.assertIn("glass", note)
        self.assertIsNotNone(self.room.find("test ball"))

    def test_a_change_the_engine_would_refuse_is_refused_here(self):
        """And the room is left exactly as it was.

        This is the whole point of checking inside the tool. A complaint raised
        when the room is rebuilt arrives after the model's turn has ended: the
        person reads a validator message about overlapping cells and the model,
        which is the only thing that can move the object, never hears about it.
        """
        before = [dict(b) for b in self.room.bodies()]
        with self.assertRaises(ValueError) as caught:
            # Right on top of a plate that is already there. Found rather than
            # written down, so the test does not quietly stop testing anything
            # when the room is laid out differently.
            plate = next(b for b in self.room.bodies() if "plate" in b["name"])
            self.room.add_object(
                {"name": "overlapping tile", "shape": "box", "material": "ceramic",
                 "size_mm": list(plate["size_mm"]),
                 "position_mm": list(plate["center_mm"]),
                 "velocity_m_s": [0, 0, 0], "anchored": False})
        self.assertIn("same cells", str(caught.exception))
        self.assertEqual(self.room.bodies(), before, "the refused change was left behind")

    def test_a_bad_material_or_shape_is_refused_by_name(self):
        for bad in ({"material": "cheese"}, {"shape": "dodecahedron"}):
            args = {"name": "x", "shape": "box", "material": "glass",
                    "size_mm": [100, 100, 100], "position_mm": [0, 2000, -3000],
                    "velocity_m_s": [0, 0, 0], "anchored": False}
            args.update(bad)
            with self.assertRaises(ValueError):
                self.room.add_object(args)

    def test_clearing_and_rebuilding_works(self):
        self.assertIn("emptied", self.room.clear_room({}))
        self.assertEqual(self.room.bodies(), [])
        # An empty room is not a broken one: emptying is the first half of
        # "clear this and build me ...", and checking an empty scene asks the
        # validator about a single-tile lane nobody mentioned.
        self.room.add_object(
            {"name": "lone plate", "shape": "box", "material": "glass",
             "size_mm": [600, 20, 200], "position_mm": [0, 410, 900],
             "velocity_m_s": [0, 0, 0], "anchored": False})
        self.assertEqual(len(self.room.bodies()), 1)

    def test_moving_and_removing_name_what_they_touched(self):
        self.assertIn("iron ball", self.room.move_object(
            {"name": "iron ball", "position_mm": [0, 2000, -3000]}))
        self.assertIn("iron ball", self.room.remove_object({"name": "iron ball"}))
        self.assertIsNone(self.room.find("iron ball"))
        with self.assertRaises(ValueError):
            self.room.remove_object({"name": "iron ball"})


@unittest.skipUnless(ENGINE, "the live engine is not built")
class TheRoomActuallyOpens(unittest.TestCase):
    def test_it_opens_and_every_body_says_what_it_is_made_of(self):
        runs = ROOT / "build" / "playground-runs"
        runs.mkdir(parents=True, exist_ok=True)
        spec = fracture_lab.validate(world_room.room())
        session = live_session.Session(ENGINE, spec, runs)
        try:
            bodies = session.state["bodies"]
            self.assertEqual(len(bodies), len(spec["bodies"]))
            for body in bodies:
                self.assertTrue(body.get("material"),
                                f"{body['name']} came back with no material, so nothing "
                                f"can label it")
            # The label needs the material, and the pointer needs the ray.
            found = session.send(op="pick", **{"from": [-0.9, 3.0, 0.0], "dir": [0, -1, 0]})
            self.assertTrue(found["hit"])
            self.assertEqual(found["name"], "iron ball")
            # And it runs far faster than real time, which is the rule this
            # whole engine is built to.
            import time
            began = time.perf_counter()
            for _ in range(60):
                state = session.send(op="step", dt=1 / 120.0, n=4)
                while state.get("breakable"):
                    state = session.send(op="fracture", name=state["breakable"][0])
            wall = time.perf_counter() - began
            self.assertLess(wall, 2.0 * 1.1,
                            f"2 s of room took {wall:.2f} s, which is past the rule")
        finally:
            session.close()


class TheCourtyard(unittest.TestCase):
    """The room with things that swing.

    A gate is not a prop here: it is a body on a pin, and it opens because
    something is pushed into it. What these check is that the ROOM says so --
    that a scene document can carry its own pins, that a pin naming something
    which is not there is refused where the thing that wrote it can be told, and
    that opening the room actually hangs them.
    """

    def test_the_courtyard_carries_its_own_joints(self):
        # By KIND and by what each one holds, never by a total. Every increment
        # adds mechanisms to this room, and an assertion that counts them is an
        # assertion that fails on the next one for no reason -- which is what
        # "2 != 12" was, twice.
        spec = fracture_lab.validate(world_room.courtyard())
        by_kind: dict[str, list] = {}
        for joint in spec["joints"]:
            by_kind.setdefault(joint["kind"], []).append(joint)
        self.assertLessEqual({"hinge", "slider", "link", "pulley"}, set(by_kind),
                             "the courtyard is missing a kind of mechanism")

        pin = by_kind["hinge"][0]
        self.assertEqual((pin["a"], pin["b"]), ("gate jamb left", "oak gate"))
        # It opens outward only. A gate that swings both ways is a saloon door.
        self.assertEqual(pin["lower_deg"], 0.0)
        self.assertGreater(pin["upper_deg"], 45.0)
        # And it is stiff enough to stay where it is pushed.
        self.assertGreater(pin["friction_n_m"], 0.0)

        groove = by_kind["slider"][0]
        self.assertEqual((groove["a"], groove["b"]),
                         ("portcullis jamb left", "iron portcullis"))
        # It rests on the ground and can only go up.
        self.assertEqual(groove["lower_mm"], 0.0)
        self.assertGreater(groove["upper_mm"], 500.0)
        # 1.28 x 1.2 x 0.12 m of iron is 1,450 kg: 14.2 kN of weight. The
        # grooves grip at far less than that ON PURPOSE, because a portcullis
        # that holds itself up needs no winch and demonstrates nothing.
        weight_n = 1.28 * 1.2 * 0.12 * 7870.0 * 9.81
        self.assertLess(groove["friction_n"], 0.5 * weight_n,
                        "the portcullis holds itself up, so letting go of it "
                        "shows nothing")

        # The chain: every link tied to the one above it, not all of them to the
        # beam. That was an off-by-one once, and eight things nailed to the same
        # spot looks like a chain until you pull on it.
        chain = [j for j in by_kind["link"] if "chain" in j["a"] or "chain" in j["b"]]
        self.assertGreaterEqual(len(chain), 4, "the chain is too short to hang")
        hangs_from = {j["a"] for j in chain}
        self.assertEqual(len(hangs_from), len(chain),
                         "two links hang from the same thing, so it is not a chain")
        for joint in chain:
            # Each link is tied above where it hangs to.
            self.assertGreater(joint["at_mm"][1], joint["to_mm"][1],
                               f"{joint['b']} is tied to something below it")

    def test_the_winch_cannot_lift_the_portcullis_on_its_own(self):
        """A hoist nobody has to operate is not a hoist.

        The counterweight is deliberately lighter than the grate: haul on it and
        the grate rises, let go and it settles back. If the weights were the
        other way round the gateway would simply stand open and there would be
        nothing to do.
        """
        spec = fracture_lab.validate(world_room.courtyard())
        bodies = {body["name"]: body for body in spec["bodies"]}
        DENSITY = {"iron": 7870.0, "concrete": 2400.0, "oak": 700.0}

        def weight_n(name):
            body = bodies[name]
            volume = 1.0
            for side in body["size_mm"]:
                volume *= side / 1000.0
            return volume * DENSITY[body["material"]] * 9.81

        grate = weight_n("iron portcullis")
        counter = weight_n("winch counterweight")
        self.assertLess(counter, grate,
                        f"the counterweight ({counter:.0f} N) outweighs the grate "
                        f"({grate:.0f} N), so the gateway stands open by itself")
        # And not so light that hauling is pointless either.
        self.assertGreater(counter, 0.1 * grate,
                           "the counterweight is so light that the rope might as "
                           "well not be there")

    def test_the_shelf_can_be_overloaded_by_what_is_in_the_room(self):
        """A shelf nobody can overload demonstrates nothing.

        Bending stress goes as one over the depth squared, so the slab's
        thickness is what decides whether the things lying around this courtyard
        are enough to break it. Checked here in newtons rather than discovered
        by carrying blocks about: a 120 mm slab wants 3.7 kN, which is more than
        everything loose in the room put together.
        """
        spec = fracture_lab.validate(world_room.courtyard())
        bodies = {body["name"]: body for body in spec["bodies"]}
        DENSITY = {"iron": 7870.0, "concrete": 2400.0, "oak": 700.0}

        def weight_n(name):
            body = bodies[name]
            volume = 1.0
            for side in body["size_mm"]:
                volume *= side / 1000.0
            # A sphere is not a box.
            if body["shape"] == "sphere":
                volume *= math.pi / 6.0
            return volume * DENSITY[body["material"]] * 9.81

        shelf = bodies["stone shelf"]
        left = bodies["shelf pier left"]
        right = bodies["shelf pier right"]
        # The clear span: between the piers' inner faces.
        span = ((right["center_mm"][0] - right["size_mm"][0] / 2)
                - (left["center_mm"][0] + left["size_mm"][0] / 2)) / 1000.0
        breadth = shelf["size_mm"][2] / 1000.0
        depth = shelf["size_mm"][1] / 1000.0
        # Simply supported, load in the middle: stress = 3 W L / (2 b d^2).
        per_newton = 3.0 * span / (2.0 * breadth * depth * depth)
        # Concrete's tensile strength, which is what a beam fails on.
        breaks_at_n = 3.0e6 / per_newton

        loose = sum(weight_n(name) for name in
                    ("stone block", "iron ball", "oak barrel"))
        self.assertLess(breaks_at_n, loose,
                        f"the shelf needs {breaks_at_n:.0f} N to break and there "
                        f"is only {loose:.0f} N loose in the whole courtyard, so "
                        f"nobody can overload it")
        # And not so weak that it fails under its own weight standing empty.
        own = weight_n("stone shelf")
        self.assertGreater(breaks_at_n, 2.0 * own,
                           f"the shelf breaks at {breaks_at_n:.0f} N and weighs "
                           f"{own:.0f} N itself, so it is barely standing up")

    def test_the_portcullis_cannot_rise_through_its_own_arch(self):
        """Travel measured against the room, not guessed.

        A grate whose lift puts its top above the lintel is a grate that was
        never measured against the gateway it is in.
        """
        spec = fracture_lab.validate(world_room.courtyard())
        bodies = {body["name"]: body for body in spec["bodies"]}
        grate = bodies["iron portcullis"]
        lintel = bodies["portcullis lintel"]
        groove = next(j for j in spec["joints"] if j["kind"] == "slider")
        top_when_up = (grate["center_mm"][1] + grate["size_mm"][1] / 2
                       + groove["upper_mm"])
        arch = lintel["center_mm"][1] - lintel["size_mm"][1] / 2
        self.assertLessEqual(top_when_up, arch + 1.0,
                             f"raised fully, the grate's top is at {top_when_up} mm "
                             f"and the arch starts at {arch} mm")

    def test_the_bench_room_still_has_none(self):
        self.assertEqual(fracture_lab.validate(world_room.room())["joints"], [])

    def test_a_pin_naming_nothing_is_refused_where_it_can_be_fixed(self):
        """Refused HERE, not at the engine.

        A pin the engine will not hang produces a gate that simply does not
        swing, and from the outside that reads as the physics being broken
        rather than as the room being wrong about where its own hinge is.
        """
        for why, wrong in (
            ("a body that is not in the room",
             {"kind": "hinge", "a": "gate jamb left", "b": "a gate nobody built",
              "at_mm": [0, 1000, 120]}),
            ("a body hung on itself",
             {"kind": "hinge", "a": "oak gate", "b": "oak gate",
              "at_mm": [0, 1000, 120]}),
            ("an axis with no direction",
             {"kind": "hinge", "a": "gate jamb left", "b": "oak gate",
              "at_mm": [0, 1000, 120], "axis": [0, 0, 0]}),
            ("a kind of joint that does not exist",
             {"kind": "ball socket", "a": "gate jamb left", "b": "oak gate",
              "at_mm": [0, 1000, 120]}),
            ("limits the wrong way round",
             {"kind": "hinge", "a": "gate jamb left", "b": "oak gate",
              "at_mm": [0, 1000, 120], "lower_deg": 90, "upper_deg": -90}),
            ("a pin with no place",
             {"kind": "hinge", "a": "gate jamb left", "b": "oak gate"}),
        ):
            spec = world_room.courtyard()
            spec["joints"] = [wrong]
            with self.assertRaises(ValueError, msg=f"it accepted {why}"):
                fracture_lab.validate(spec)

    @unittest.skipIf(ENGINE is None, "no live engine built")
    def test_opening_the_courtyard_hangs_the_gate(self):
        live = live_session.Live()
        try:
            class App:
                engine_path = ENGINE
                runs_path = ROOT / "build/playground-runs"
                live_inprocess = False
            opened = live.open(App(), {"spec": world_room.courtyard()})
            self.assertNotIn("joint_problems", opened,
                             f"the room could not hang its own gate: "
                             f"{opened.get('joint_problems')}")
            pins = opened.get("joints") or []
            asked = fracture_lab.validate(world_room.courtyard())["joints"]
            self.assertEqual(len(pins), len(asked),
                             "the room did not make every joint it asked for")
            self.assertTrue(all(pin["attached"] for pin in pins),
                            "something opened already detached")
            by_kind: dict[str, list] = {}
            for pin in pins:
                by_kind.setdefault(pin["kind"], []).append(pin)
            self.assertAlmostEqual(by_kind["hinge"][0]["degrees"], 0.0, places=3,
                                   msg="the gate did not open shut")
            self.assertAlmostEqual(by_kind["slider"][0]["metres"], 0.0, places=3,
                                   msg="the portcullis did not open down")

            # And it swings when something is pushed into it -- which is the
            # whole claim. Nothing here asks for the gate to move.
            session = live.session
            session.send(op="grab", name="iron ball")
            for i in range(141):
                session.send(op="step", dt=1 / 240.0, n=4, moved=True,
                             hand=[0.9, 1.0, 1.0 - i * 0.01])
            session.send(op="release")
            turned = next(j for j in session.send(op="joints")["joints"]
                          if j["kind"] == "hinge")["degrees"]
            self.assertGreater(abs(turned), 10.0,
                               f"the ball was walked through where the gate is and "
                               f"the gate turned {turned} degrees")
            self.assertLessEqual(abs(turned), 100.0,
                                 "the gate went past the stop the room gave it")

            # And the portcullis: hauled up and let go, it comes back down. The
            # grooves grip at a fifth of its weight, so nothing holds it.
            session.send(op="grab", name="iron portcullis")
            for i in range(1, 101):
                session.send(op="step", dt=1 / 240.0, n=4, moved=True,
                             hand=[-2.6, 0.6 + i * 0.01, 0.14])
            lifted = next(j for j in session.send(op="joints")["joints"]
                          if j["kind"] == "slider")["metres"]
            session.send(op="release")
            for _ in range(180):
                session.send(op="step", dt=1 / 240.0, n=4, moved=True)
            fell = next(j for j in session.send(op="joints")["joints"]
                        if j["kind"] == "slider")["metres"]
            self.assertGreater(lifted, 0.7, "hauling did not lift the portcullis")
            self.assertLess(fell, 0.2,
                            f"the portcullis was let go {lifted} m up and is still "
                            f"at {fell} m")

            # The winch: haul the counterweight down and the grate comes up,
            # because the rope's length cannot change. Nothing tells the grate
            # to move.
            def groove_at():
                return next(j for j in session.send(op="joints")["joints"]
                            if j["kind"] == "slider")["metres"]

            session.send(op="grab", name="winch counterweight")
            for i in range(1, 101):
                session.send(op="step", dt=1 / 240.0, n=4, moved=True,
                             hand=[-1.0, 1.6 - i * 0.01, 0.14])
            hauled = groove_at()
            session.send(op="release")
            for _ in range(240):
                session.send(op="step", dt=1 / 240.0, n=8, moved=True)
            settled = groove_at()
            self.assertGreater(hauled, 0.7,
                               f"hauling the counterweight down a metre raised the "
                               f"grate only {hauled} m")
            self.assertLess(settled, 0.3,
                            f"the grate stayed at {settled} m when the winch was "
                            f"let go, so the counterweight is holding it up on "
                            f"its own")

            # And the chain hangs: every link carries what is below it, so the
            # tensions step DOWN the chain. That is the whole difference between
            # a chain of bodies and a chain-shaped decoration.
            for _ in range(240):
                session.send(op="step", dt=1 / 240.0, n=4, moved=True)
            links = [j for j in session.send(op="joints")["joints"]
                     if j["kind"] == "link" and "chain" in j["a"] + j["b"]]
            links.sort(key=lambda j: -j["at"][1])
            carried = [j["tension_n"] for j in links]
            self.assertTrue(carried, "the chain reported no links at all")
            for upper, lower in zip(carried, carried[1:]):
                self.assertGreater(
                    upper, lower,
                    f"a link lower down carries more than the one above it: "
                    f"{carried}")
        finally:
            live.shutdown()


if __name__ == "__main__":
    unittest.main(verbosity=2)
