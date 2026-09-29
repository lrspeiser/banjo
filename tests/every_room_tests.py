"""Every room the server serves opens, runs, and says nothing is wrong.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tests/every_room_tests.py

A room is a JSON document or a builder, and either can rot: a scene that names
a body that is no longer there, a machine wired to a battery that was renamed,
a sun a newer engine will not put up, a cell size that now exceeds the lane's
cap. None of that shows up until somebody opens the room and looks, and by then
it is the person testing who finds it.

So this opens every scene in `world_room.SCENES` the way the playground opens
it, steps a second of its world, and asks:

- it opened, with no joint, machine or sun problem said out loud;
- it has bodies, and they are where the room put them (nothing at the origin
  that should not be);
- a step moves its clock;
- and what that second of world cost in wall time, which is the owner's gate:
  a room has to run at realtime to be worth walking around in.

Without BANJO_LIVE_ENGINE only the shape of each room is checked, unless
BANJO_ROOMS_LIVE_TESTS=required, which ctest sets.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground")]
import fracture_lab, live_session, room_store, world_room   # noqa: E402

ENGINE = Path(os.environ["BANJO_LIVE_ENGINE"]).resolve() if os.environ.get("BANJO_LIVE_ENGINE") else None
#: What the ground calls a tunnel somebody has dug, in its run of beds.
WORKING = "a working"
DT = 1 / 240
# A second of world in each room, in twelve-step batches as the page asks for
# them. Long enough for a machine to be reported and for anything unstable to
# start moving; short enough to do every room in a test.
WORLD_S = 1.0
# The rooms that are meant to be empty of bodies: the Explorer's own scenes
# build themselves from the gameplay layer once a person arrives.
NO_BODIES = {"expedition"}


class EveryRoomIsWellFormed(unittest.TestCase):
    """What can be checked without opening a world at all."""

    def test_every_scene_validates(self):
        bad = {}
        for name in sorted(world_room.SCENES):
            try:
                spec = fracture_lab.validate(world_room.SCENES[name]())
                if name not in NO_BODIES:
                    self.assertTrue(spec.get("bodies") or spec.get("precise_rigid_bodies"),
                                    f"{name} has no bodies")
            except Exception as error:   # noqa: BLE001 -- the room is the thing under test
                bad[name] = f"{type(error).__name__}: {error}"
        self.assertEqual({}, bad, "rooms that will not validate")


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE is required")
class EveryRoomOpensAndRuns(unittest.TestCase):
    """Each scene opened as the playground opens it, and stepped."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def open_and_step(self, name: str) -> dict:
        live = live_session.Live()
        try:
            room = world_room.Room(name)
            app = SimpleNamespace(live=live, live_holder="world", room=room, engine_path=ENGINE,
                                  runs_path=self.root / "runs",
                                  store=room_store.RoomStore(self.root / "rooms" / name))
            began = time.monotonic()
            opened = live.open(app, {"spec": room.spec})
            opening_s = time.monotonic() - began
            problems = {key: opened[key] for key in
                        ("joint_problems", "machine_problems", "sun_problem", "blade_problems",
                         "tool_point_problems", "construction_problems")
                        if opened.get(key)}
            began = time.monotonic()
            was = float(opened.get("t", 0.0) or 0.0)
            state = {}
            for _ in range(int(WORLD_S / (DT * 12))):
                state = live.session.send(op="step", dt=DT, n=12)
            ran_s = time.monotonic() - began
            return {"problems": problems, "bodies": len(state.get("bodies") or opened.get("bodies") or []),
                    "clock": float(state.get("t", 0.0) or 0.0) - was,
                    "opening_s": opening_s, "realtime": WORLD_S / ran_s if ran_s > 0 else 0.0}
        finally:
            live.shutdown()

    def test_every_room_opens_steps_and_keeps_up(self):
        trouble, slow = {}, {}
        for name in sorted(world_room.SCENES):
            with self.subTest(room=name):
                try:
                    got = self.open_and_step(name)
                except Exception as error:   # noqa: BLE001 -- the room is the thing under test
                    trouble[name] = f"{type(error).__name__}: {str(error)[:200]}"
                    continue
                print(f"    {name}: {got['bodies']} bodies, opened in {got['opening_s']:.1f} s, "
                      f"ran at {got['realtime']:.1f}x realtime"
                      + (f", SAID: {got['problems']}" if got["problems"] else ""), flush=True)
                if got["problems"]:
                    trouble[name] = got["problems"]
                elif got["clock"] <= 0.0:
                    trouble[name] = "its clock did not move"
                elif name not in NO_BODIES and got["bodies"] == 0:
                    trouble[name] = "it opened with no bodies"
                elif got["realtime"] < 1.0:
                    slow[name] = round(got["realtime"], 2)
        self.assertEqual({}, trouble, "rooms that did not open and run")
        # The owner's gate: a room has to run at realtime. Said separately so a
        # room that is merely slow is not confused with one that is broken.
        self.assertEqual({}, slow, "rooms that ran slower than realtime")

    def test_nothing_starts_under_the_ground(self):
        """A thing buried when its room opens is the worst kind of broken.

        It is present, meshed, reported visible -- and invisible, and the
        crosshair goes straight through it to the terrain. Nothing else in
        this suite catches it: the room opens, its clock runs and its bodies
        are counted, and every one of those is true of a room whose furniture
        is under the field.

        It happens because `standing_on_the_ground` seats a room only when the
        ground is `flat`; on a generated valley the heights are whatever the
        tool that laid the room out fitted to the surface IT generated, and
        generated ground is build-dependent -- the valley's cache name mixes
        in `fp::profileHash()` exactly so that "a valley another build made is
        left in the cache and not used". So a room like that fits the machine
        that built it and no other.

        Anchored scenery is left out: a footing or a tunnel wall belongs under
        the surface. What is asked of everything else is only that its CENTRE
        is not below the ground under it, which is the point at which it stops
        being findable.
        """
        buried = {}
        for name in sorted(world_room.SCENES):
            with self.subTest(room=name):
                live = live_session.Live()
                try:
                    room = world_room.Room(name)
                    app = SimpleNamespace(live=live, live_holder="world", room=room, engine_path=ENGINE,
                                          runs_path=self.root / "runs",
                                          store=room_store.RoomStore(self.root / "rooms" / name))
                    live.open(app, {"spec": room.spec})
                    under = []
                    for pose in live.session.send(op="poses")["bodies"]:
                        if pose.get("anchored"):
                            continue
                        x, y, z = pose["position_m"]
                        survey = live.session.send(op="survey", at=[x, z])["survey"]
                        runs = survey.get("runs")
                        if runs:
                            # Which bed the body's centre is in. A run called
                            # "a working" is a tunnel somebody dug, so a lamp
                            # or a breaker down there is exactly where it
                            # belongs; anything else is solid matter.
                            bed = next((r for r in runs
                                        if float(r["from_m"]) <= y < float(r["to_m"])), None)
                            if bed is not None and str(bed.get("material")) != WORKING:
                                under.append(f"{pose['name']} {round((float(bed['to_m'])-y)*1000)} mm "
                                             f"inside {bed.get('material')}")
                            continue
                        ground = survey.get("ground_m")
                        if ground is not None and y < float(ground):
                            under.append(f"{pose['name']} {round((float(ground)-y)*1000)} mm under")
                    if under:
                        buried[name] = under[:6]
                        print(f"    {name}: BURIED {under[:6]}", flush=True)
                finally:
                    live.shutdown()
        self.assertEqual({}, buried, "things that start under the ground of their own room")


if __name__ == "__main__":
    if os.environ.get("BANJO_ROOMS_LIVE_TESTS") == "required" and not (ENGINE and ENGINE.is_file()):
        raise RuntimeError("BANJO_LIVE_ENGINE must be built for the required live room tests")
    unittest.main()
