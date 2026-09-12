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
        self.assertLessEqual({"hinge", "slider", "link", "pulley", "fixing"},
                             set(by_kind),
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

    def test_the_courtyard_carries_a_bow_made_of_ordinary_joints(self):
        """A bow, and not one thing in it is a bow.

        Two hinges, two elastics, two links and a fixing -- every one of them a
        mechanism this room already had. What is checked here is the GEOMETRY,
        because three of the four ways this fell over were geometry and none of
        them looked like geometry from the outside.
        """
        spec = fracture_lab.validate(world_room.courtyard())
        bodies = {b["name"]: b for b in spec["bodies"]}
        for wanted in ("bow grip upper", "bow grip lower", "upper limb tip",
                       "lower limb tip", "bowstring", "arrow", "spare arrow"):
            self.assertIn(wanted, bodies, f"the bow has no {wanted}")

        def joints_between(kind, a_part, b_part):
            return [j for j in spec["joints"] if j["kind"] == kind
                    and a_part in j["a"] and b_part in j["b"]]

        roots = joints_between("hinge", "bow grip", "limb tip")
        limbs = joints_between("elastic", "bow grip", "limb tip")
        string = joints_between("link", "limb tip", "bowstring")
        nock = joints_between("fixing", "bowstring", "arrow")
        self.assertEqual(len(roots), 2, "a limb that is not pinned swings on a "
                                        "sphere and stores nothing")
        self.assertEqual(len(limbs), 2, "the bow has no limbs to store anything in")
        self.assertEqual(len(string), 2, "a string is two ropes, one to each tip")
        self.assertEqual(len(nock), 1, "nothing holds the arrow to the string")

        # THE TIPS ARE LEVEL WITH THE STRING. Set them forward and the braced
        # string is a V whose two rope tensions no longer cancel: their
        # resultant shoves the nocking point at the bow, the arrow's weight
        # turns the whole assembly over, and the bow has fallen down before
        # anybody touches it. On the line the two tensions are equal and
        # opposite, which is what braced means.
        string_x = bodies["bowstring"]["center_mm"][0]
        for tip in ("upper limb tip", "lower limb tip"):
            self.assertAlmostEqual(
                bodies[tip]["center_mm"][0], string_x, places=3,
                msg=f"{tip} is not level with the string, so brace is not an "
                    f"equilibrium and the bow falls over on its own")

        # The limb's spring is anchored FORWARD of its pin, or drawing the
        # string back shortens it instead of lengthening it and the bow pushes
        # the arrow the wrong way.
        for limb, root in zip(sorted(limbs, key=lambda j: j["a"]),
                              sorted(roots, key=lambda j: j["a"])):
            self.assertGreater(limb["at_mm"][0], root["at_mm"][0] + 100,
                               f"the spring on {limb['b']} is anchored at its own "
                               f"pin, which is a lever arm of nothing")
            # And not collinear with the pin and the nocking point, which is the
            # other lever arm of nothing: the string then pulls straight through
            # the pivot and puts no torque on the limb at all.
            pin = root["at_mm"]
            tip = limb["to_mm"]
            nocked = [string_x, bodies["bowstring"]["center_mm"][1], tip[2]]
            cross = ((tip[0] - pin[0]) * (nocked[1] - pin[1]) -
                     (tip[1] - pin[1]) * (nocked[0] - pin[0]))
            self.assertGreater(abs(cross), 1000.0,
                               f"the pin, {limb['b']} and the nocking point are in "
                               f"a line, so the string exerts no torque on the limb")

        # The shaft clears the grip it runs through, above and below. A shaft
        # rubbing the grip is a shaft being drawn against friction: measured
        # with 40 mm of window the bow reached 50 mm of draw before it jammed.
        shaft = bodies["arrow"]
        top = shaft["center_mm"][1] + shaft["size_mm"][1] / 2
        for block, side in (("bow grip upper", 1), ("bow grip lower", -1)):
            face = (bodies[block]["center_mm"][1]
                    - side * bodies[block]["size_mm"][1] / 2)
            self.assertGreaterEqual(
                side * (face - (top if side > 0 else top - shaft["size_mm"][1])),
                0.0, f"the shaft runs through {block} rather than past it")

    @unittest.skipIf(ENGINE is None, "no live engine built")
    def test_drawing_the_bow_stores_work_and_loosing_spends_it(self):
        """The claim, end to end, through the same pipe the browser uses.

        There is no arrow speed anywhere in this room. What the arrow leaves
        with is what the limbs were holding, less what the string and the tips
        keep -- so a longer draw has to be a faster arrow, and nothing else
        could make it one.
        """
        live = live_session.Live()

        class App:
            engine_path = ENGINE
            runs_path = ROOT / "build/playground-runs"
            live_inprocess = False

        def step(session, **rest):
            # ANSWERING the handshake. A step that would break something is
            # taken back and the clock stops until the host says what to do --
            # so a test that only steps freezes the world at the first contact
            # and reads as a bow that jams halfway through its draw.
            state = session.send(op="step", dt=1 / 240.0, n=1, moved=True, **rest)
            for coming in state.get("breakable") or []:
                session.send(op="fracture", name=coming, wait=False)
            return state

        def body(session, name):
            return next(b for b in session.state["bodies"] if b["name"] == name)

        def stored(session):
            return sum(j["stored_j"] for j in session.send(op="joints")["joints"]
                       if j["kind"] == "elastic")

        def shoot(draw_m):
            opened = live.open(App(), {"spec": world_room.courtyard()})
            self.assertNotIn("joint_problems", opened,
                             f"the bow would not build: {opened.get('joint_problems')}")
            session = live.session
            nock = next(j for j in session.send(op="joints")["joints"]
                        if j["kind"] == "fixing" and j["b"] == "arrow")
            for _ in range(240):
                step(session)
            braced = body(session, "bowstring")["position_m"]
            self.assertAlmostEqual(
                braced[0], -1.76, places=2,
                msg=f"the bow did not stay braced with nobody touching it: the "
                    f"string is at {braced}")
            self.assertLess(stored(session), 0.05,
                            "a bow at brace is already holding energy")

            session.send(op="grab", name="bowstring")
            steps = int(draw_m / 0.002)
            for i in range(1, steps + 1):
                step(session, hand=[braced[0] - draw_m * i / steps,
                                    braced[1], braced[2]])
            # And HOLD at full draw. The hand pulls with a bounded force, so
            # reaching full draw takes as long as it takes; without the hold a
            # short draw simply runs out of steps before the force has finished
            # working, and stores less for having been given fewer of them.
            for _ in range(300):
                step(session)
            held = stored(session)
            drawn = braced[0] - body(session, "bowstring")["position_m"][0]

            session.send(op="release")
            # The arrow leaves when the limbs STOP PUSHING, and that is read
            # off the string's own acceleration rather than off any distance.
            #
            # Not "when the string gets back to brace", and not "when it stops":
            # traced step by step, a 290 mm draw runs the string home to
            # +5.25 m/s and then the ropes go taut 55 mm SHORT of brace, because
            # the limb tips have not finished coming back. That stop takes ONE
            # step, and a rule that waits to see it has already missed: at the
            # step after, the nock -- which is a rigid weld until it is let go
            # -- has hauled the arrow backwards at 2.13 m/s. Its acceleration,
            # though, falls to nothing several steps before that, because the
            # limbs are spent. That is the moment, and it is the same moment on
            # a real bow.
            away, fastest, best = False, 0.0, -99.0
            went, gaining_best = 0.0, 0.0
            for _ in range(600):
                going = body(session, "bowstring")["velocity_m_s"][0]
                gaining = going - went
                gaining_best = max(gaining_best, gaining)
                went = going
                if not away and going > 0.5 and gaining < 0.15 * gaining_best:
                    session.send(op="unhinge", joint=nock["id"])
                    away = True
                step(session)
                if away:
                    fastest = max(fastest,
                                  body(session, "arrow")["velocity_m_s"][0])
                best = max(best, body(session, "arrow")["position_m"][0])
            self.assertTrue(away, "the string never came back to brace, so the "
                                  "arrow was never loosed at all")
            return drawn, held, fastest, best

        try:
            short = shoot(0.15)
            long = shoot(0.30)
        finally:
            live.shutdown()

        print(f"\n    drawn {short[0] * 1000:.0f} mm: {short[1]:.1f} J, away at "
              f"{short[2]:.2f} m/s, reached x={short[3]:.2f}")
        print(f"    drawn {long[0] * 1000:.0f} mm: {long[1]:.1f} J, away at "
              f"{long[2]:.2f} m/s, reached x={long[3]:.2f}")

        self.assertGreater(short[1], 0.2, "a 150 mm draw stored nothing at all")
        self.assertGreater(long[1], 2.5 * short[1],
                           "doubling the draw barely changed the energy, so the "
                           "limbs are not what is storing it")
        self.assertGreater(long[2], short[2],
                           "the longer draw did not throw the arrow faster, so "
                           "the shot is not coming from the limbs")
        self.assertGreater(long[3], -1.0,
                           "the arrow went nowhere: it starts at x = -1.4")

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
        # Through the winch's ratio, because that is what the grate actually
        # feels. The counterweight's own weight is not the number that decides
        # whether the gateway stands open.
        # DIVIDED by the ratio, because the constraint puts force `lambda` on
        # end a and `ratio * lambda` on end b -- so what a counterweight at b is
        # worth at the grate is its own weight over the ratio. Multiplying
        # instead said a 3.95 kN counterweight was worth 1.38 kN and passed,
        # while the real figure was 11.3 and the sums it was guarding were
        # nonsense.
        ratio = next(j["ratio"] for j in spec["joints"] if j["kind"] == "pulley")
        at_the_grate = counter / ratio
        self.assertLess(at_the_grate, grate,
                        f"the counterweight ({counter:.0f} N over a ratio of "
                        f"{ratio:g} is {at_the_grate:.0f} N at the grate) "
                        f"outweighs the grate ({grate:.0f} N), so the gateway "
                        f"stands open by itself")
        self.assertGreater(at_the_grate, 0.5 * grate,
                           "the counterweight is so light that nobody could "
                           "finish the lift by hand")
        # And not so light that hauling is pointless either.
        self.assertGreater(counter, 0.1 * grate,
                           "the counterweight is so light that the rope might as "
                           "well not be there")

    @unittest.skipIf(ENGINE is None, "no live engine built")
    def test_the_bar_is_what_keeps_the_gate_shut(self):
        """A latch changes what the assembly IS.

        The same gate, the same pin, the same shove. Barred, it does not move;
        with the bar lifted off, it swings. Nothing about the gate changed --
        which is the whole difference between a latch and a very stiff hinge.
        """
        def shoved(lift_the_bar: bool) -> float:
            live = live_session.Live()
            try:
                class App:
                    engine_path = ENGINE
                    runs_path = ROOT / "build/playground-runs"
                    live_inprocess = False
                opened = live.open(App(), {"spec": world_room.courtyard()})
                self.assertNotIn("joint_problems", opened,
                                 f"the room would not build itself: "
                                 f"{opened.get('joint_problems')}")
                session = live.session
                if lift_the_bar:
                    for pin in session.send(op="joints")["joints"]:
                        if pin["kind"] == "fixing":
                            session.send(op="unhinge", joint=pin["id"])
                    for _ in range(30):
                        session.send(op="step", dt=1 / 240.0, n=8, moved=True)
                # Walk the iron ball into the gate, square to its face.
                session.send(op="grab", name="iron ball")
                for i in range(1, 141):
                    session.send(op="step", dt=1 / 240.0, n=4, moved=True,
                                 hand=[0.9, 1.0, 1.0 - i * 0.01])
                session.send(op="release")
                for _ in range(60):
                    session.send(op="step", dt=1 / 240.0, n=8, moved=True)
                return abs(next(j for j in session.send(op="joints")["joints"]
                                if j["kind"] == "hinge")["degrees"])
            finally:
                live.shutdown()

        barred = shoved(False)
        unbarred = shoved(True)
        self.assertLess(barred, 5.0,
                        f"a barred gate swung {barred} degrees")
        self.assertGreater(unbarred, 10.0,
                           f"the unbarred gate only moved {unbarred} degrees, so "
                           f"the shove proves nothing either way")

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
            #
            # The bar comes off first. A barred gate does not swing, which is
            # the point of the bar and is exactly what this test measured when
            # the bar was added: 4.26 degrees, which reads as a broken hinge and
            # is a working latch.
            session = live.session
            for pin in session.send(op="joints")["joints"]:
                if pin["kind"] == "fixing":
                    session.send(op="unhinge", joint=pin["id"])
            for _ in range(30):
                session.send(op="step", dt=1 / 240.0, n=8, moved=True)
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
            # Heaving on the grate ITSELF is not a thing worth asserting any
            # more, and that is the winch's doing rather than a regression.
            # Lifting the grate a metre needs the counterweight to rise 2.86,
            # and it has 0.46 m of room under its sheave -- so the rope holds
            # the grate almost still however hard anybody pulls on it directly,
            # which is exactly what being roped to a counterweight means.
            # Raising the gateway is the winch's job, and the winch is hauled
            # and measured below.

            # The winch: haul the counterweight down and the grate comes up,
            # because the rope's length cannot change. Nothing tells the grate
            # to move.
            def groove_at():
                return next(j for j in session.send(op="joints")["joints"]
                            if j["kind"] == "slider")["metres"]

            session.send(op="grab", name="winch counterweight")
            for i in range(1, 121):
                session.send(op="step", dt=1 / 240.0, n=4, moved=True,
                             hand=[-1.0, 2.0 - i * 0.015, 0.14])
            hauled = groove_at()
            session.send(op="release")
            for _ in range(240):
                session.send(op="step", dt=1 / 240.0, n=8, moved=True)
            settled = groove_at()
            # 0.4 m, not 0.7. The winch trades force for distance: at a ratio
            # of 0.35 the grate rises 0.35 m for every metre hauled, so a 1.8 m
            # pull is 0.63 m of gate. Asking for 0.7 was asking the geometry for
            # something it does not have, which is a different complaint from
            # the winch not working.
            self.assertGreater(hauled, 0.4,
                               f"hauling the counterweight down 1.8 m raised the "
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


class TheArmoury(unittest.TestCase):
    """The sword, and three things it can change. docs/cutting-model.md."""

    DENSITY = {"iron": 7870.0, "oak": 700.0, "rubber": 1100.0}
    OAK_TENSILE_PA = 90.0e6

    def spec(self):
        return fracture_lab.validate(world_room.armoury())

    def kg(self, body):
        volume = 1.0
        for side in body["size_mm"]:
            volume *= side / 1000.0
        return volume * self.DENSITY[body["material"]]

    def test_the_sword_has_one_edge_and_it_is_on_its_own_steel(self):
        spec = self.spec()
        self.assertEqual([b["body"] for b in spec["blades"]], ["sword"])
        edge = spec["blades"][0]
        sword = next(b for b in spec["bodies"] if b["name"] == "sword")
        for end in ("heel_mm", "tip_mm", "grip_mm"):
            for axis in range(3):
                off = abs(edge[end][axis] - sword["center_mm"][axis])
                self.assertLessEqual(off, sword["size_mm"][axis] / 2 + 1e-6,
                                     f"the edge's {end} is off the bar it belongs to")

    def test_the_rope_can_keep_its_length(self):
        """A chain of light links under a load hundreds of times heavier does
        not keep its length in an iterative solver. The first rope here hung
        0.6 m long, with gaps between segments that a blade went straight
        through without touching anything."""
        bodies = {b["name"]: b for b in self.spec()["bodies"]}
        ratio = self.kg(bodies["weight"]) / self.kg(bodies["rope 1"])
        self.assertLess(ratio, 50.0,
                        f"the weight is {ratio:.0f} times a rope segment")

    def test_the_batten_holds_whole_and_not_notched_beside_its_load(self):
        """What a plank can support, and what a notch does to it: the survey's
        own statics, done here by hand before the room is ever opened."""
        spec = self.spec()
        bodies = {b["name"]: b for b in spec["bodies"]}
        batten = bodies["oak batten"]
        left, right = bodies["batten pier left"], bodies["batten pier right"]
        clear = ((right["center_mm"][0] - right["size_mm"][0] / 2)
                 - (left["center_mm"][0] + left["size_mm"][0] / 2)) / 1000.0
        breadth = batten["size_mm"][2] / 1000.0
        depth = batten["size_mm"][1] / 1000.0
        cell = spec["cell_m"]
        load_n = self.kg(bodies["iron load"]) * 9.81
        whole = 3.0 * load_n * clear / (2.0 * breadth * depth * depth)
        self.assertLess(whole, self.OAK_TENSILE_PA,
                        f"the batten is overloaded before anyone touches it: {whole / 1e6:.0f} MPa")

        def notched(x_m):
            # A notch through the upper row of cells: one row is left, and the
            # survey's ligament is one cell deep.
            a = x_m + clear / 2.0
            moment = 0.5 * load_n * min(a, clear - a)
            return 6.0 * moment / (breadth * cell * cell)

        self.assertGreater(notched(0.2), self.OAK_TENSILE_PA,
                           f"a notch beside the load leaves it at {notched(0.2) / 1e6:.0f} MPa, "
                           f"so cutting it changes nothing")
        self.assertLess(notched(0.4), self.OAK_TENSILE_PA,
                        "a notch far out by a pier overloads it too, so where it is cut "
                        "does not matter, and it should")

    @unittest.skipUnless(ENGINE, "the live engine is not built")
    def test_an_edge_parts_the_rope_and_its_flat_does_not(self):
        """Through the same pipe the browser uses: the sword taken up, brought
        round beside the rope, and swept through it -- edge leading, then the
        same sweep turned a quarter so the flat leads. Nothing here says
        "cut": the hand pulls, and what the edge meets is the engine's."""
        root2 = math.sqrt(0.5)

        def qmul(a, b):
            aw, ax, ay, az = a
            bw, bx, by, bz = b
            return [aw * bw - ax * bx - ay * by - az * bz,
                    aw * bx + ax * bw + ay * bz - az * by,
                    aw * by - ax * bz + ay * bw + az * bx,
                    aw * bz + ax * by - ay * bx + az * bw]

        # The bar lies along x with its edge facing -z. Turned so it points
        # away (-z) with the edge facing left (-x): a half turn about (x+z).
        edge_left = [0.0, root2, 0.0, root2]
        # A quarter turn about the way it points: the edge faces up, and a
        # sweep to the left leads with the flat.
        flat_left = qmul([root2, 0.0, 0.0, -root2], edge_left)

        class App:
            engine_path = ENGINE
            runs_path = ROOT / "build/playground-runs"
            live_inprocess = False

        def sweep(facing):
            live = live_session.Live()
            try:
                opened = live.open(App(), {"spec": world_room.armoury()})
                self.assertNotIn("blade_problems", opened,
                                 f"the sword would not take its edge: {opened.get('blade_problems')}")
                session = live.session
                bodies = {b["name"]: b for b in opened["bodies"]}
                cuts = []

                def step(**rest):
                    state = session.send(op="step", dt=1 / 240.0, n=1, moved=True, **rest)
                    for b in state.get("bodies") or []:
                        bodies[b["name"]] = b
                    for name in state.get("gone") or []:
                        bodies.pop(name, None)
                    for coming in state.get("breakable") or []:
                        session.send(op="fracture", name=coming, wait=False)
                    cuts.extend(c for c in state.get("cuts") or [] if not c["open"])

                hung = bodies["weight"]["position_m"][1]
                session.send(op="wield", name="sword")
                start, rest = [0.0, 1.55, 1.95], [0.35, 1.005, 1.9]
                for i in range(240):      # a second to bring it round, clear of the rope
                    t = min(1.0, i / 180.0)
                    turn = [(1 - t) * a + t * b for a, b in zip([1.0, 0.0, 0.0, 0.0], facing)]
                    size = math.sqrt(sum(v * v for v in turn))
                    step(hand=[r + (s - r) * t for r, s in zip(rest, start)],
                         hand_q=[v / size for v in turn])
                # The sweep: the hand's target at 12 m/s to x = -1, the speed a
                # swing of the view gives the sword in the room (13 to 17 m/s
                # measured). At 8 m/s a 26 g segment of free-hanging rope is
                # knocked away about as fast as it is cut, and whether it parts
                # is a close thing -- as it is.
                for i in range(1, 21):
                    step(hand=[start[0] - i / 20.0, start[1], start[2]], hand_q=facing)
                for _ in range(360):      # and held, while whatever falls lands
                    step(hand=[start[0] - 1.0, start[1], start[2]], hand_q=facing)
                return hung, bodies, cuts
            finally:
                live.shutdown()

        hung, bodies, cuts = sweep(edge_left)
        on_rope = [c for c in cuts if c["target"].startswith("rope")]
        bit = [c for c in on_rope if c["kind"] == "edge" and c["area_mm2"] > 0]
        self.assertTrue(bit, f"the edge did not bite the rope: {on_rope}")
        through = [c for c in bit if c["separated"]]
        self.assertTrue(through, f"the edge cut into the rope but not through it: {bit}")
        # Accounted work: what it cost is its area at the rubber's resistance.
        for c in through:
            self.assertAlmostEqual(c["work_j"] / (c["area_mm2"] * 1e-6),
                                   c["resistance_j_m2"], delta=0.01 * c["resistance_j_m2"])
        self.assertLess(bodies["weight"]["position_m"][1], 0.3,
                        f"the rope was cut and the weight is still at "
                        f"{bodies['weight']['position_m'][1]:.2f} m (it hung at {hung:.2f})")

        hung, bodies, cuts = sweep(flat_left)
        on_rope = [c for c in cuts if c["target"].startswith("rope")]
        self.assertFalse([c for c in on_rope if c["bonds"] > 0 or c["links"] > 0],
                         f"the flat cut the rope: {on_rope}")
        self.assertTrue(any(c["kind"] == "flat" for c in on_rope),
                        f"the flat met the rope and it was not called a flat: {on_rope}")
        self.assertGreater(bodies["weight"]["position_m"][1], hung - 0.3,
                           "the weight fell, so the flat took the rope apart")

    def test_the_batten_stands_its_load_without_balancing_it(self):
        """A 160 mm block on a 20 mm stick tips at 5.7 degrees of roll, and a
        press beside it rolled it off. Kept above 8."""
        bodies = {b["name"]: b for b in self.spec()["bodies"]}
        batten, load = bodies["oak batten"], bodies["iron load"]
        half_width = batten["size_mm"][2] / 2.0
        height = batten["size_mm"][1] + load["size_mm"][1] / 2.0
        self.assertGreater(math.degrees(math.atan2(half_width, height)), 8.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
