"""The C library, driven from Python.

Two things are being checked here. The first is the binding: ctypes gets no help
from the compiler, so a wrong argtype is a silent pointer truncation rather than
an error, and only running it finds that out.

The second is the claim the C face exists to make -- that a language which
cannot read a C++ header can still drive a world. Every physical result below is
one the C++ tests also check, so if the two ever disagree the boundary is what
broke, not the physics.
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bindings" / "python"))

import banjo  # noqa: E402


def pane_and_ball(drop_m: float) -> dict:
    """The same scene the C++ tests use: a glass pane with an iron ball above it."""
    return {"bodies": [
        {"name": "pane", "shape": "box", "material": "glass",
         "dimensions_m": [0.3, 0.04, 0.3], "center_m": [0.0, 0.02, 0.0]},
        {"name": "ball", "shape": "sphere", "material": "iron",
         "dimensions_m": [0.1, 0.1, 0.1], "center_m": [0.0, 0.04 + 0.05 + drop_m, 0.0]},
    ]}


# ---- machines (ABI 23): the rooms and checks of tests/motor_tests.cpp ----------

MOTOR_DT_S = 1.0 / 60.0      # the step tests/motor_tests.cpp takes
G_M_S2 = 9.81
# The flywheel's motor stalls at 10 N m and runs at 10 rad/s unloaded.
STALL_N_M = 10.0
UNLOADED_RAD_S = 10.0


def flywheel_room() -> dict:
    """An iron post fixed in place, and an iron flywheel 0.4 x 0.1 x 0.4 m clear
    above it, to be hung on a vertical pin through its middle."""
    return {"bodies": [
        {"name": "post", "shape": "box", "material": "iron",
         "dimensions_m": [0.1, 0.8, 0.1], "center_m": [0.5, 0.4, 0.0], "anchored": True},
        {"name": "flywheel", "shape": "box", "material": "iron",
         "dimensions_m": [0.4, 0.1, 0.4], "center_m": [0.5, 1.0, 0.0]},
    ]}


def hoist_room() -> dict:
    """An iron post; an oak drum 0.2 x 0.2 x 0.3 m on an axle along z at
    (0, 2, 0); and an iron crate 0.15 m across hanging 1.5 m below the drum's
    right-hand side, where a rope off the drum's 0.1 m radius comes straight
    down to it."""
    return {"bodies": [
        {"name": "post", "shape": "box", "material": "iron",
         "dimensions_m": [0.1, 2.0, 0.1], "center_m": [-0.4, 1.0, 0.0], "anchored": True},
        {"name": "drum", "shape": "box", "material": "oak",
         "dimensions_m": [0.2, 0.2, 0.3], "center_m": [0.0, 2.0, 0.0]},
        {"name": "crate", "shape": "box", "material": "iron",
         "dimensions_m": [0.15, 0.15, 0.15], "center_m": [0.1, 0.425, 0.0]},
    ]}


def run(world: banjo.World, seconds: float) -> float:
    """Step for about `seconds` at 1/60 s, as tests/motor_tests.cpp does, and
    say how long it stepped. `step` rather than `advance`: nothing in these
    rooms is struck, so a step taken back would be a surprise, and it is said
    rather than settled."""
    steps = round(seconds / MOTOR_DT_S)
    for _ in range(steps):
        if world.step(MOTOR_DT_S) == banjo.BREAK_PENDING:
            raise AssertionError(f"a step was taken back for {world.breakable()}, and nothing "
                                 f"in this room is struck")
    return steps * MOTOR_DT_S


class MachinesFromPython(unittest.TestCase):
    """A battery, a DC motor on a pin with a brake, and a rope that winds onto a
    drum (ABI 23, docs/machine-world.md), driven through the binding. The rooms,
    the checks and their tolerances are tests/motor_tests.cpp's, so if the two
    ever disagree the boundary is what broke, not the physics."""

    def test_a_flywheel_spun_up_by_a_motor_follows_its_line_and_its_work_is_the_spin(self):
        axle, up = (0.5, 1.0, 0.0), (0.0, 1.0, 0.0)
        with banjo.World(flywheel_room(), cell_size_m=0.05) as world:
            pin = world.hinge("post", "flywheel", at_m=axle, axis=up)
            battery = world.energy_store("battery", "post", 20000.0, 20000.0)
            drive = world.motor(pin, battery, STALL_N_M, UNLOADED_RAD_S)
            # What was made reads back as it was made, field by field: a struct
            # laid out differently on the two sides of the boundary shows here.
            self.assertEqual(world.energy_stores(), [banjo.EnergyStore(
                id=battery, name="battery", body="post", capacity_j=20000.0, charge_j=20000.0,
                voltage_v=24.0, max_power_w=0.0, given_j=0.0, short_j=0.0)])
            (told,) = world.motors()
            self.assertEqual((told.id, told.joint, told.store, told.stall_torque_n_m,
                              told.no_load_rad_s, told.brake_torque_n_m, told.command, told.brake,
                              told.state, told.turned_rad, told.drawn_j),
                             (drive, pin, battery, STALL_N_M, UNLOADED_RAD_S, 0.0, 0.0, False,
                              "coasting", 0.0, 0.0))

            # How hard it is to turn, from the solver, against the flywheel's
            # own mass and shape: a box turning about its middle is m (a^2 + b^2)
            # / 12 of the two sides across the axis -- 0.4 and 0.4 m about the
            # axle, 0.1 and 0.4 m about a line across it. Anchored scenery the
            # solver never turns.
            inertia = world.inertia_about("flywheel", up)
            across = world.inertia_about("flywheel", (1.0, 0.0, 0.0))
            mass = world.body("flywheel").mass_kg
            flat, edge = mass * (0.4 ** 2 + 0.4 ** 2) / 12.0, mass * (0.1 ** 2 + 0.4 ** 2) / 12.0
            print(f"\n  the flywheel ({mass:.2f} kg): {inertia:.5f} kg m^2 about its axle "
                  f"(a box: {flat:.5f}), {across:.5f} across it (a box: {edge:.5f})")
            self.assertLess(abs(inertia - flat), 0.01 * flat, "the inertia about the axle is not the box's")
            self.assertLess(abs(across - edge), 0.01 * edge, "the inertia across the wheel is not the box's")
            self.assertEqual(world.inertia_about("post", up), math.inf, "anchored scenery can be turned")

            # The line makes a first-order spin-up, w(t) = w0 (1 - exp(-t / T)),
            # with T = J w0 / stall.
            lag = inertia * UNLOADED_RAD_S / STALL_N_M
            world.drive_motor(drive, 1.0)
            t = 0.0
            for until in (lag, 2.0 * lag):
                t += run(world, until - t)
                m = world.motors()[0]
                line = UNLOADED_RAD_S * (1.0 - math.exp(-t / lag))
                print(f"  at {t:.3f} s it turns at {m.speed_rad_s:.4f} rad/s; the line says {line:.4f}")
                # Stepping the line at 1/60 s puts the curve about dt / 2T
                # behind the exponential: 0.25% here. A hundredth is four times.
                self.assertLess(abs(m.speed_rad_s - line), 0.01 * line,
                                "the flywheel is not on the motor's line")
                # The torque is the line's at the speed the step began with;
                # read at the speed it ended with, the line is one step's
                # change, dt / T of it, below that: 0.5%.
                self.assertLess(abs(m.torque_n_m - STALL_N_M * (1.0 - m.speed_rad_s / UNLOADED_RAD_S)),
                                0.01 * m.torque_n_m, "the motor's torque is not its line's")
                # A DC motor: what it asks of the store is its voltage times its
                # current (V I = I^2 R + k w I), less one step's change in speed
                # over w0 -- under 0.2% -- for the turn taken at the step's end.
                volts = world.energy_stores()[0].voltage_v
                self.assertLess(abs(m.power_w - volts * m.current_a), 0.005 * m.power_w,
                                "the power it asked is not its voltage times its current")
            m = world.motors()[0]
            self.assertEqual(m.state, "driving")
            # Turn after turn: the whole turn, not a reading wrapped at 180 degrees.
            turned = UNLOADED_RAD_S * (t - lag * (1.0 - math.exp(-t / lag)))
            print(f"  it has turned {m.turned_rad / (2.0 * math.pi):.4f} times; the line says "
                  f"{turned / (2.0 * math.pi):.4f}")
            self.assertLess(abs(m.turned_rad - turned), 0.01 * turned,
                            "the motor's count of its turns is not the line's")

            # The account: what the battery gave is what the motor asked for,
            # which is its work and its heat; and its work is the flywheel's spin
            # -- to within the half J dw^2 a step that torque times the turn at
            # the step's end speed runs ahead of it, about dt / 2T: 0.3%.
            store = world.energy_stores()[0]
            spin = 0.5 * inertia * m.speed_rad_s ** 2
            print(f"  the battery gave {store.given_j:.3f} J and the motor drew {m.drawn_j:.3f} J: "
                  f"{m.work_j:.3f} J of work and {m.heat_j:.3f} J of heat; the spin is {spin:.3f} J")
            self.assertEqual(store.short_j, 0.0)
            self.assertLessEqual(abs(store.given_j - m.drawn_j), 1e-9 * m.drawn_j,
                                 "the battery's account and the motor's differ")
            self.assertLessEqual(abs(store.capacity_j - store.charge_j - store.given_j),
                                 1e-9 * store.capacity_j, "the battery lost charge it did not give")
            self.assertLessEqual(abs(m.drawn_j - m.work_j - m.heat_j), 1e-9 * m.drawn_j,
                                 "what the motor drew is not its work and its heat")
            self.assertLessEqual(abs(m.work_j - spin), 0.01 * m.work_j,
                                 "the motor's work did not turn up as the flywheel's spin")

    def test_a_hoist_winds_its_rope_on_lifts_the_crate_and_holds_it_braked(self):
        centre, axle, radius = (0.0, 2.0, 0.0), (0.0, 0.0, 1.0), 0.1
        with banjo.World(hoist_room(), cell_size_m=0.05) as world:
            pin = world.hinge("post", "drum", at_m=centre, axis=axle)
            # Two metres of rope, 1.5 of it out: the drum turning the positive
            # way about z takes it on.
            rope = world.drum("drum", "crate", centre_m=centre, axis=axle, radius_m=radius,
                              load_at_m=(0.1, 0.5, 0.0), winds=1, length_m=2.0)
            battery = world.energy_store("battery", "post", 5000.0, 5000.0)
            # It stalls at 60 N m, over twice the crate's 26 N m on the drum; its
            # brake holds 200.
            drive = world.motor(pin, battery, 60.0, 10.0, brake_torque_n_m=200.0)
            inertia = world.inertia_about("drum", axle)

            # The brake holds the drum, and the rope carries the crate.
            world.drive_motor(drive, 0.0, brake=True)
            run(world, 1.0)
            crate = world.body("crate")
            weight = crate.mass_kg * G_M_S2
            (hanging,) = world.drum_ropes()
            listed = next(j for j in world.joints() if j.id == rope)
            print(f"\n  held by the brake: the rope carries {hanging.tension_n:.3f} N of the crate's "
                  f"{weight:.3f} N, with {hanging.out_m:.4f} m of it out and {hanging.wound_m:.4f} m "
                  f"on the drum")
            self.assertEqual(listed.kind, "drum")
            self.assertEqual((hanging.id, hanging.drum, hanging.load, hanging.radius_m,
                              hanging.length_m, hanging.attached),
                             (rope, "drum", "crate", radius, 2.0, True))
            # The joint and its rope say the same: what is off the drum, the
            # whole rope, what it carries, the drum's centre and its axle.
            self.assertEqual((listed.at, listed.upper, listed.tension_n, listed.at_m, listed.axis),
                             (hanging.out_m, hanging.length_m, hanging.tension_n, hanging.centre_m,
                              hanging.axis))
            self.assertLess(abs(hanging.wound_m + hanging.out_m - hanging.length_m), 1e-9)
            self.assertLess(abs(hanging.tension_n - weight), 0.01 * weight,
                            "the rope does not carry the crate's weight")
            self.assertEqual(world.motors()[0].state, "braking")
            self.assertEqual(world.motors()[0].drawn_j, 0.0, "holding the crate drew on the battery")
            # Where the rope is, for a host that draws it: it leaves the drum on
            # its rim, meets the crate where it was made off (the middle of its
            # top), and the taut run between the two is the rope that is out.
            self.assert_the_rope_is_where_it_says(hanging, crate, radius)

            # Lifting.
            before = world.motors()[0]
            world.drive_motor(drive, 1.0)
            run(world, 1.5)
            lifted = world.motors()[0]
            up = world.body("crate")
            (wound,) = world.drum_ropes()
            rise = up.position_m[1] - crate.position_m[1]
            turned = lifted.turned_rad - before.turned_rad
            taken = hanging.out_m - wound.out_m
            print(f"  lifting for 1.5 s: the drum turned {turned / (2.0 * math.pi):.4f} times, taking "
                  f"on {taken:.6f} m of rope (r x turn: {radius * turned:.6f} m), and the crate rose "
                  f"{rise:.6f} m")
            self.assertGreater(turned, 2.0 * math.pi, "the drum did not turn even once")
            self.assertLess(abs(taken - radius * turned), 0.002 * radius * turned,
                            "the rope taken on is not the drum's radius times its turn")
            self.assertLess(abs(rise - taken), 0.01 * taken, "the crate did not rise by the rope taken on")
            self.assert_the_rope_is_where_it_says(wound, up, radius)
            # The account: the motor's work is the crate's height and the
            # motion, and the battery gave what the motor drew.
            height = up.mass_kg * G_M_S2 * rise
            motion = (0.5 * up.mass_kg * sum(v * v for v in up.velocity_m_s)
                      + 0.5 * inertia * lifted.speed_rad_s ** 2)
            work = lifted.work_j - before.work_j
            heat = lifted.heat_j - before.heat_j
            drawn = lifted.drawn_j - before.drawn_j
            store = world.energy_stores()[0]
            print(f"  it drew {drawn:.3f} J: {work:.3f} J of work -- {height:.3f} J into the crate's "
                  f"height and {motion:.3f} J into motion -- and {heat:.3f} J of heat; the battery "
                  f"gave {store.given_j:.3f} J")
            self.assertLessEqual(abs(drawn - work - heat), 1e-9 * drawn,
                                 "what the motor drew is not its work and its heat")
            self.assertLessEqual(abs(work - height - motion), 0.01 * work,
                                 "the motor's work is not the crate's height and the motion")
            self.assertEqual(store.short_j, 0.0)
            self.assertLessEqual(abs(store.given_j - lifted.drawn_j), 1e-9 * lifted.drawn_j,
                                 "the battery did not give what the motor drew")

            # Braked at the top: it stays there, and holding it draws nothing.
            world.drive_motor(drive, 0.0, brake=True)
            run(world, 0.5)
            stopped = world.body("crate").position_m[1]
            drawn_stopped = world.motors()[0].drawn_j
            run(world, 1.0)
            still = world.body("crate").position_m[1]
            print(f"  braked: in a second the crate moved {still - stopped:.6f} m")
            self.assertLess(abs(still - stopped), 0.002, "braked, the crate did not stay up")
            self.assertEqual(world.motors()[0].drawn_j, drawn_stopped,
                             "holding the crate up drew on the battery")

            # The rope is a joint like any other: taken off, what hung on it falls.
            world.unhinge(rope)
            falling_s = run(world, 0.25)
            fell = still - world.body("crate").position_m[1]
            print(f"  its rope taken off, the crate fell {fell:.4f} m in {falling_s:.2f} s")
            self.assertEqual(world.drum_ropes(), [])
            # Stepped, a fall runs a little ahead of g t^2 / 2, never behind it.
            self.assertGreater(fell, 0.9 * 0.5 * G_M_S2 * falling_s ** 2,
                               "let off its rope, the crate did not fall")

    def assert_the_rope_is_where_it_says(self, rope: banjo.DrumRope, crate: banjo.Body,
                                         radius: float) -> None:
        top = (crate.position_m[0], crate.position_m[1] + 0.075, crate.position_m[2])
        rim = math.dist(rope.leaves_m, rope.centre_m)
        span = math.dist(rope.leaves_m, rope.meets_m)
        print(f"    it leaves the drum {rim * 1000:.4f} mm from its centre, meets the crate "
              f"{math.dist(rope.meets_m, top) * 1000:.4f} mm from the middle of its top, and runs "
              f"{span:.6f} m between with {rope.out_m:.6f} m out")
        self.assertLess(abs(rim - radius), 1e-5, "the rope does not leave the drum at its radius")
        self.assertLess(math.dist(rope.meets_m, top), 0.001, "the rope does not meet the crate "
                                                             "where it was made off")
        self.assertLess(abs(span - rope.out_m), 0.001, "the taut rope's run is not what is out")

    def test_what_is_not_a_machine_is_refused_and_says_why(self):
        centre, axle, made_off = (0.0, 2.0, 0.0), (0.0, 0.0, 1.0), (0.1, 0.5, 0.0)
        with banjo.World(hoist_room(), cell_size_m=0.05) as world:
            pin = world.hinge("post", "drum", at_m=centre, axis=axle)
            rope = world.drum("drum", "crate", centre, axle, 0.1, made_off, 1, 2.0)
            battery = world.energy_store("battery", "post", 5000.0, 5000.0)
            drive = world.motor(pin, battery, 60.0, 10.0, 200.0)
            for why, call, says in (
                ("a store in nothing called nowhere",
                 lambda: world.energy_store("b", "nowhere", 1.0, 1.0), "nowhere"),
                ("a store holding more than it can",
                 lambda: world.energy_store("b", "post", 1.0, 2.0), "charge"),
                ("a store with no voltage",
                 lambda: world.energy_store("b", "post", 1.0, 1.0, voltage_v=0.0), "voltage"),
                ("a motor on no joint", lambda: world.motor(99, battery, 60.0, 10.0), "no joint"),
                ("a motor on a drum's rope",
                 lambda: world.motor(rope, battery, 60.0, 10.0), "a drum's rope"),
                ("a motor wired to no store",
                 lambda: world.motor(pin, battery + 1, 60.0, 10.0), "no store"),
                ("a second motor on a pin",
                 lambda: world.motor(pin, battery, 60.0, 10.0), "motor already"),
                ("a motor that stalls at nothing",
                 lambda: world.motor(pin, battery, 0.0, 10.0), "stall"),
                ("a command past full", lambda: world.drive_motor(drive, 1.5), "-1 to 1"),
                ("a motor that is not there", lambda: world.drive_motor(drive + 1, 1.0), "no motor"),
                ("a drum that winds neither way",
                 lambda: world.drum("drum", "crate", centre, axle, 0.1, made_off, 0, 2.0), "winds"),
                ("a drum hung from itself",
                 lambda: world.drum("drum", "drum", centre, axle, 0.1, made_off, 1, 2.0), "same thing"),
                ("more rope out than there is",
                 lambda: world.drum("drum", "crate", centre, axle, 0.1, made_off, 1, 2.0, out_m=3.0),
                 "whole rope"),
                ("the inertia of nothing",
                 lambda: world.inertia_about("nothing at all", axle), "nothing called"),
                ("an inertia about no axis",
                 lambda: world.inertia_about("drum", (0.0, 0.0, 0.0)), "direction"),
            ):
                with self.assertRaises(banjo.BanjoError, msg=f"the engine accepted {why}") as caught:
                    call()
                self.assertIn(says, str(caught.exception), f"refusing {why}, it said: {caught.exception}")
            # A store may be in nothing, and one given no name is named for its id.
            spare = world.energy_store("", "", 10.0, 5.0)
            self.assertEqual([(s.id, s.name, s.body) for s in world.energy_stores()],
                             [(battery, "battery", "post"), (spare, f"store {spare}", "")])
            # Nothing refused was made.
            self.assertEqual([m.id for m in world.motors()], [drive])
            self.assertEqual([r.id for r in world.drum_ropes()], [rope])
            self.assertEqual(sorted(j.kind for j in world.joints()), ["drum", "hinge"])


class AWorldIsKeptFromPython(unittest.TestCase):
    """banjo_snapshot, banjo_open_snapshot and banjo_restored through the
    binding: the world saved, and the same scene opened again from it as it
    stood. The physics of it -- every body, cell, dent, joint and hand as it
    was -- is checked in tests/live_world_tests.cpp."""

    def test_a_world_saved_opens_again_as_it_stood(self):
        scene = pane_and_ball(10.0)
        with banjo.World(scene, cell_size_m=0.02) as world:
            pieces = 0
            for _ in range(900):
                if world.step(1 / 240) == banjo.BREAK_PENDING:
                    pieces = world.fracture("pane")
                    break
            self.assertGreater(pieces, 1, "the pane did not break, so this proves nothing")
            for _ in range(120):
                world.advance(1 / 240)
            saved = world.snapshot("the pane and the ball")
            self.assertIsNotNone(saved, world.last_refusal)
            self.assertEqual(saved["format"], "banjo.world.v1")
            self.assertEqual(saved["spec_digest"], "the pane and the ball")
            self.assertEqual(world.restored()["tier"], "", "a world opened from its scene says it was restored")
            was = {b.name: (b.position_m, b.orientation_wxyz) for b in world.bodies()}
            t = world.time_s
        with banjo.World(scene, cell_size_m=0.02, snapshot=saved) as again:
            said = again.restored()
            self.assertEqual(said["tier"], "whole", said.get("why"))
            self.assertTrue(said["not_kept"], "a restored world does not say what it does not keep")
            self.assertEqual(again.time_s, t)
            self.assertEqual({b.name: (b.position_m, b.orientation_wxyz) for b in again.bodies()}, was)
        with banjo.World(scene, cell_size_m=0.02, snapshot="{ half a world") as unread:
            self.assertEqual(unread.restored()["tier"], "none")
            self.assertEqual(sorted(b.name for b in unread.bodies()), ["ball", "pane"])


class TheLibraryLoads(unittest.TestCase):
    def test_the_abi_matches_the_binding(self):
        self.assertEqual(banjo.library().banjo_abi_version(), banjo.ABI_VERSION)

    def test_a_bad_scene_says_what_is_wrong_instead_of_crashing(self):
        with self.assertRaises(banjo.BanjoError) as caught:
            banjo.World("not json at all")
        self.assertTrue(str(caught.exception),
                        "the engine failed without saying why")

    def test_a_closed_world_refuses_rather_than_using_a_dead_handle(self):
        world = banjo.World(pane_and_ball(0.1))
        world.close()
        with self.assertRaises(banjo.BanjoError):
            world.advance(1 / 120)
        world.close()   # closing twice is not an error


class RollingResistanceFromPython(unittest.TestCase):
    """banjo_materials and banjo_rolling_report through the binding. The physics
    itself -- 5/7 c g on the level, rest below atan(c), the declared loss equal
    to the kinetic energy lost -- is measured in tests/rolling_resistance_tests.cpp."""

    def test_the_materials_say_their_rolling_resistance_and_where_it_came_from(self):
        said = banjo.materials()
        self.assertEqual({m["name"] for m in said["materials"]},
                         {"iron", "aluminum", "glass", "ceramic", "oak", "rubber", "ice", "concrete"})
        for material in said["materials"]:
            self.assertGreater(material["rolling_resistance"], 0.0, material["name"])
            self.assertIsInstance(material["rolling_resistance_sourced"], bool)
            self.assertTrue(material["rolling_resistance_basis"], material["name"])
        surfaces = {s["name"]: s for s in said["surfaces"]}
        self.assertEqual(surfaces["floor"]["made_of"], "concrete")
        self.assertGreater(surfaces["sand"]["rolling_resistance"], surfaces["soil"]["rolling_resistance"])

    def test_a_ball_rolled_across_the_floor_is_resisted_and_the_loss_is_declared(self):
        scene = {"bodies": [{"name": "ball", "shape": "sphere", "material": "rubber",
                             "dimensions_m": [0.12, 0.12, 0.12], "center_m": [0.0, 0.0605, 0.0],
                             "velocity_m_s": [1.0, 0.0, 0.0], "roll": True}]}
        with banjo.World(scene, cell_size_m=0.02) as world:
            for _ in range(240):
                world.step(1 / 240)
            report = world.rolling_report()
            contact = next(c for c in report["contacts"] if c["ball"] == "ball")
            self.assertEqual(contact["on"], "the floor")
            self.assertTrue(contact["from_solver"], "N was not the solver's own")
            rubber_on_concrete = (next(m for m in banjo.materials()["materials"] if m["name"] == "rubber")
                                  ["rolling_resistance"] + 0.001)
            self.assertAlmostEqual(contact["coefficient"], rubber_on_concrete, places=6)
            self.assertFalse(contact["held"], "a ball rolling at nearly 1 m/s is not held")
            self.assertLess(world.body("ball").velocity_m_s[0], 0.97, "a second on the floor took nothing off it")
            self.assertGreater(report["loss_j"], 0.0)
            self.assertEqual([b["name"] for b in report["balls"]], ["ball"])


class AWorldRunsFromPython(unittest.TestCase):
    def test_stepping_is_gravity(self):
        with banjo.World(pane_and_ball(1.0), cell_size_m=0.02) as world:
            start = world.body("ball").position_m[1]
            for _ in range(480):
                world.advance(1 / 240)
            end = world.body("ball").position_m[1]
            self.assertLess(end, start - 0.5, "the ball did not fall")
            self.assertGreater(end, 0.0, "the ball fell through the floor")

    def test_a_ray_names_what_it_meets(self):
        with banjo.World(pane_and_ball(1.0)) as world:
            down = world.pick([0, 6, 0], [0, -1, 0])
            self.assertTrue(down.hit)
            self.assertEqual(down.name, "ball")
            self.assertGreater(down.distance_m, 4.0)
            # On the ray, not somewhere near it.
            self.assertAlmostEqual(down.point_m[1], 6.0 - down.distance_m, places=6)

            beside = world.pick([3, 6, 0], [0, -1, 0])
            self.assertTrue(beside.hit, "a ray beside the scene met nothing at all")
            self.assertEqual(beside.name, "", "the ground should be a hit with no name")

            self.assertFalse(world.pick([0, 6, 0], [0, 1, 0]).hit,
                             "a ray fired at the sky hit something")

    def test_a_hard_enough_hit_breaks_it_and_says_how_many_pieces(self):
        with banjo.World(pane_and_ball(10.0)) as world:
            pieces = 0
            for _ in range(900):
                if world.step(1 / 240) != banjo.BREAK_PENDING:
                    continue
                waiting = world.breakable()
                self.assertIn("pane", waiting)
                pieces = world.fracture("pane")
                break
            self.assertGreater(pieces, 1, "a 13.9 m/s iron ball did not break a glass pane")
            # The count reported is the count in the world.
            present = sum(1 for b in world.bodies() if b.name.startswith("pane"))
            self.assertEqual(pieces, present,
                             "fracture reported a different number than the world holds")

    def test_a_break_can_be_worked_out_without_the_world_waiting_for_it(self):
        """The thing that makes a live host usable, reachable from the library.

        `fracture` blocks for the whole run -- a third of a second to a second --
        and because the caller drives time, everything stops with it. For two
        releases this was in the engine and not in the ABI, so anyone building on
        banjo.h got the stall and no way round it.
        """
        with banjo.World(pane_and_ball(10.0)) as world:
            started = False
            steps_while_working = 0
            pieces = 0
            for _ in range(900):
                if world.fracture_pending():
                    steps_while_working += 1
                    if world.fracture_ready():
                        pieces = world.finish_fracture()
                        break
                    world.step(1 / 240)      # the world carries on
                    continue
                if world.step(1 / 240) != banjo.BREAK_PENDING:
                    continue
                waiting = world.breakable()
                self.assertIn("pane", waiting)
                started = world.begin_fracture("pane")
                self.assertTrue(started, "the engine had nothing to work out for the pane")
                self.assertEqual(world.fracture_subject(), "pane")

            self.assertTrue(started, "the drop never produced a break to work out")
            self.assertGreater(pieces, 1, "a 13.9 m/s iron ball did not break a glass pane")
            self.assertFalse(world.fracture_pending(),
                             "the answer was collected and something is still pending")
            present = sum(1 for b in world.bodies() if b.name.startswith("pane"))
            self.assertEqual(pieces, present,
                             "the piece count reported is not the count in the world")

    def test_nothing_to_work_out_is_said_rather_than_raised(self):
        """Anchored scenery, and a name that is not there.

        Both are answered -- the world is not left wedged -- and both come back
        as False rather than an exception, because neither is the caller making
        a mistake.
        """
        with banjo.World(pane_and_ball(10.0)) as world:
            world.step(1 / 240)
            self.assertFalse(world.begin_fracture("no such thing"))
            self.assertFalse(world.fracture_pending())

    def test_the_floor_can_be_swept_and_says_what_it_picked_up(self):
        """Debris is what fills the body table, and a full body table is what
        stops the step being taken back -- which is what breaking needs. So
        sweeping is not a convenience, it is how a world that shatters keeps
        working."""
        with banjo.World(pane_and_ball(10.0)) as world:
            for _ in range(900):
                if world.step(1 / 240) != banjo.BREAK_PENDING:
                    continue
                if world.fracture("pane") > 1:
                    break
            shards = [b for b in world.bodies() if b.name.startswith("pane piece")]
            self.assertGreater(len(shards), 5, "nothing shattered, so there is nothing to sweep")
            before = len(world.bodies())

            middle = shards[0].position_m
            got = world.collect(middle, radius_m=5.0)
            self.assertTrue(got, "standing in the debris collected nothing")
            self.assertLess(len(world.bodies()), before,
                            "the sweep reported a haul but took no bodies out of the world")
            lot = got[0]
            self.assertGreater(lot.kilograms, 0.0, "it was collected but weighs nothing")
            self.assertGreater(lot.pieces, 0)
            self.assertTrue(lot.material, "collected matter with no material is no use to anyone")
            # The weight has to be the matter that was there, not a count of it.
            expected = lot.cells * (0.02 ** 3) * 2500.0
            self.assertLess(abs(lot.kilograms - expected) / expected, 0.3,
                            f"{lot.kilograms:.3f} kg from {lot.cells} cells of glass is "
                            f"not near the {expected:.3f} kg that much glass weighs")

    def test_a_sweep_leaves_what_is_not_debris(self):
        """The scene has to survive being walked through."""
        with banjo.World(pane_and_ball(10.0)) as world:
            for _ in range(900):
                if world.step(1 / 240) != banjo.BREAK_PENDING:
                    continue
                if world.fracture("pane") > 1:
                    break
            anchored = {b.name for b in world.bodies() if b.anchored}
            for body in list(world.bodies()):
                world.collect(body.position_m, radius_m=3.0)
            left = {b.name for b in world.bodies()}
            self.assertFalse(anchored - left,
                             f"sweeping took anchored scenery: {sorted(anchored - left)[:3]}")
            self.assertIn("ball", left, "sweeping pocketed the ball that did the breaking")

    def test_the_threshold_is_necessary_and_not_sufficient(self):
        """1.5 m clears the bar and still holds. Reading the bar as a promise
        reads the derivation backwards, so this pins the distinction."""
        with banjo.World(pane_and_ball(1.5)) as world:
            cleared = False
            for _ in range(900):
                if world.step(1 / 240) != banjo.BREAK_PENDING:
                    continue
                hit = [i for i in world.impacts() if i.struck == "pane"]
                self.assertTrue(hit, "the world stopped for a break it could not describe")
                self.assertGreater(hit[0].closing_speed_m_s, hit[0].threshold_speed_m_s)
                cleared = True
                self.assertLessEqual(world.fracture("pane"), 1,
                                     "the marginal drop broke it after all")
                break
            self.assertTrue(cleared, "the drop never cleared the threshold")

    def test_advance_never_leaves_the_world_wedged(self):
        """A step that would break something is taken back and time stops until
        the host answers. advance() answers, so the clock has to keep moving."""
        with banjo.World(pane_and_ball(10.0)) as world:
            for _ in range(900):
                world.advance(1 / 240)
            self.assertGreater(world.time_s, 3.0,
                               "the world stopped advancing: it is wedged on a break")
            self.assertGreater(len(world.bodies()), 2, "nothing broke, so this proves nothing")

    def test_declining_a_break_also_lets_time_move(self):
        with banjo.World(pane_and_ball(10.0)) as world:
            declined = False
            for _ in range(900):
                if world.step(1 / 240) != banjo.BREAK_PENDING:
                    continue
                for name in world.breakable():
                    world.decline_break(name)
                declined = True
                break
            self.assertTrue(declined, "nothing ever asked to break")
            stopped_at = world.time_s
            for _ in range(240):
                world.step(1 / 240)
            self.assertGreater(world.time_s, stopped_at,
                               "declining the break did not let time move again")
            self.assertEqual(len(world.bodies()), 2, "something broke after being declined")

    def test_lifting_something_and_letting_it_go(self):
        with banjo.World(pane_and_ball(0.06)) as world:
            for _ in range(1200):       # let it settle, and go to sleep
                world.advance(1 / 240)
            settled = world.body("ball").position_m[1]

            world.grab("ball")
            self.assertEqual(world.held, "ball")
            for i in range(1, 61):
                world.move_held([0.0, settled + i / 60.0, 0.0])
                world.advance(1 / 240)
            lifted = world.body("ball").position_m[1]
            self.assertAlmostEqual(lifted, settled + 1.0, places=2)

            world.release()
            self.assertEqual(world.held, "")
            for _ in range(480):
                world.advance(1 / 240)
            self.assertAlmostEqual(world.body("ball").position_m[1], settled, places=2,
                                   msg="it was let go a metre up and did not come back down")

    def test_anchored_scenery_and_missing_names_are_refused_clearly(self):
        scene = pane_and_ball(1.0)
        scene["bodies"][0]["anchored"] = True
        with banjo.World(scene) as world:
            with self.assertRaises(banjo.BanjoError):
                world.grab("pane")
            with self.assertRaises(banjo.BanjoError):
                world.grab("no such thing")
            self.assertEqual(world.held, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
