"""The world keeps running when nobody is looking at it.

    python tests/world_clock_tests.py -v

Until now the page was the only thing that ever stepped a room, so going to
the Workshop -- or to another tab -- stopped time. These hold the three things
that must be true of the server's own clock: it takes the room only when the
page has really gone, it runs at realtime and never faster, and it asks no
model while it runs.

The last of those is the owner's constraint, 2026-09-26: "we can't have every
bot constantly asking llms for what to do, it will need to have routines that
it can run without constant calls to the llm."

The end-to-end one starts a real server and is skipped without
BANJO_LIVE_ENGINE.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))

import world_clock  # noqa: E402


class WhoHasTheRoom(unittest.TestCase):
    """Only one of the page and the clock ever steps it."""

    def test_the_page_has_it_while_it_is_stepping(self):
        clock = world_clock.WorldClock(SimpleNamespace())
        clock.page_stepped()
        self.assertFalse(clock.has_it(), "the clock must not step a room a page is stepping")

    def test_the_clock_takes_it_once_the_page_has_gone_quiet(self):
        clock = world_clock.WorldClock(SimpleNamespace())
        clock.page_stepped()
        # Reach into the one thing time depends on rather than sleeping for
        # two seconds in a unit test.
        clock._page_at -= world_clock.PAGE_HAS_IT_S + 0.01
        self.assertTrue(clock.has_it())

    def test_nothing_is_stepped_when_no_room_is_open(self):
        clock = world_clock.WorldClock(SimpleNamespace(live=SimpleNamespace(session=None)))
        self.assertFalse(clock._tick())

    def test_a_room_the_lab_holds_is_not_stepped(self):
        """`live_holder` says whose the one live world is. The Workshop's own
        world is not the room, and the clock must not run it."""
        app = SimpleNamespace(live=SimpleNamespace(session=SimpleNamespace(id="s")),
                              live_holder="lab")
        self.assertFalse(world_clock.WorldClock(app)._tick())


class NoModelIsAskedWhileNobodyIsWatching(unittest.TestCase):
    """The owner's constraint, as a test."""

    def _a_brain(self, mode="jev"):
        import rover_brain

        class Decider:
            kind = label = "jev"

            def ask(self, *a, **k):
                raise AssertionError("a model was asked while nobody was watching")

        brain = rover_brain.Brain("rover", {"jev": Decider()}, mode, None)
        brain.before = self.DRY
        return brain

    #: A program that is running, with a water sensor. `situations` gives no
    #: event at all for a program without `power`, so a bare dict would have
    #: made every one of these pass for the wrong reason.
    #: `side` is the sensor's offset across the machine, not a word: positive
    #: is its left (machine_senses._side).
    DRY = {"name": "rover", "power": True, "doing": "going forward", "parts": ["rover"],
           "sensors": [{"side": 0.2, "sees": False}]}
    WET = {"name": "rover", "power": True, "doing": "going forward", "parts": ["rover"],
           "sensors": [{"side": 0.2, "sees": True}]}

    def test_a_brain_marked_unattended_asks_nothing(self):
        brain = self._a_brain()
        brain.unattended = True
        brain.observe(self.WET, {"programs": [], "controls": []}, [], 1.0)
        self.assertIsNone(brain.thinking, "nothing should have been asked")

    def test_the_same_brain_does_ask_when_somebody_is_watching(self):
        """So the test above is about `unattended` and not about the event
        never being worth asking in the first place.

        `thinking` is what is checked and not the decider being called,
        because the question goes on its own thread (rover_brain, so the
        page's frame rate never waits on the network): an exception raised in
        there would never reach this one.
        """
        brain = self._a_brain()
        brain.unattended = False
        brain.observe(self.WET, {"programs": [], "controls": []}, [], 1.0)
        self.assertEqual("water ahead on its left", brain.thinking,
                         "with somebody watching, this event is one a decider is asked about")

    def test_reflexes_alone_never_ask_whoever_is_watching(self):
        brain = self._a_brain(mode="reflex")
        brain.observe(self.WET, {"programs": [], "controls": []}, [], 1.0)
        self.assertIsNone(brain.thinking)


PORT = 8875
WAIT_S = 12.0


@unittest.skipUnless(os.environ.get("BANJO_LIVE_ENGINE"), "needs BANJO_LIVE_ENGINE")
class TheWorldRunsWithNobodyOnIt(unittest.TestCase):
    """A real server, a real room, and a page that walks away."""

    token = ""

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=30) as r:
            return r.read().decode("utf-8", "replace")

    def post(self, path, body):
        request = urllib.request.Request(
            f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Banjo-Token": self.token})
        with urllib.request.urlopen(request, timeout=60) as r:
            return json.loads(r.read())

    def setUp(self):
        rooms = ROOT / "build" / "playground-rooms-clock-test"
        shutil.rmtree(rooms, ignore_errors=True)
        engine = ROOT / "build/integration/Release/banjo_platform_cli.exe"
        if not engine.is_file():
            engine = ROOT / "build/ci/banjo_platform_cli"
        # No keys: a decider that cannot be reached cannot be asked, which
        # keeps this test about the clock and not about the network.
        env = dict(os.environ, OPENAI_API_KEY="", TYPESAFE_API_KEY="")
        self.server = subprocess.Popen(
            [sys.executable, "-u", str(ROOT / "playground/server.py"), "--port", str(PORT),
             "--engine", str(engine), "--rooms", str(rooms),
             "--runs", str(ROOT / "build" / "playground-runs-clock-test")],
            cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for _ in range(80):
            try:
                self.token = json.loads(self.get("/api/status"))["csrf_token"]
                return
            except Exception:
                time.sleep(0.5)
        self.fail("the server never came up")

    def tearDown(self):
        self.server.terminate()
        try:
            self.server.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            self.server.kill()
            self.server.communicate()

    def test_the_room_runs_on_at_realtime_when_the_page_stops_asking(self):
        opened = self.post("/api/world/open", {"scene": "new-game"})
        session = opened["session"]
        running = [(p["name"], p["doing"]) for p in (opened.get("machines") or {}).get("programs") or []]
        self.assertTrue(running, "the new-game room should open with its machines in it")
        self.assertNotIn("stopped", [d for _, d in running],
                         f"a new game's machines should be running at open, not {running}")

        def step():
            got = self.post("/api/live/act", {"session": session, "op": "step", "dt": 1 / 240, "n": 1})
            return float(got.get("t", 0.0)), got

        for _ in range(10):
            was, reply = step()
        where = next(b["position_m"] for b in reply["bodies"] if b["name"] == "rover")

        # And now the page is gone. Nothing is sent at all.
        gone = time.monotonic()
        time.sleep(WAIT_S)
        waited = time.monotonic() - gone
        now, reply = step()
        moved = next(b["position_m"] for b in reply["bodies"] if b["name"] == "rover")

        ran = now - was
        # The first PAGE_HAS_IT_S is still the page's, by design.
        had = waited - world_clock.PAGE_HAS_IT_S
        print(f"\n    {ran:.2f} s of world in the {had:.1f} s the clock had "
              f"({100.0 * ran / had:.0f}% of realtime); the rover moved "
              f"{((moved[0] - where[0]) ** 2 + (moved[2] - where[2]) ** 2) ** 0.5:.2f} m")
        self.assertGreater(ran, 0.5 * had, "the world should have kept running with no page on it")
        self.assertLess(ran, 1.25 * waited, "and it must never run faster than the wall")

    def test_the_machines_carry_on_while_nobody_is_there(self):
        """Not just the clock ticking: the rover's routine takes its steps."""
        opened = self.post("/api/world/open", {"scene": "new-game"})
        session = opened["session"]
        self.post("/api/live/act", {"session": session, "op": "step", "dt": 1 / 240, "n": 1})
        where = next(b["position_m"] for b in
                     self.post("/api/live/act", {"session": session, "op": "step",
                                                 "dt": 1 / 240, "n": 1})["bodies"]
                     if b["name"] == "rover")
        time.sleep(WAIT_S)
        reply = self.post("/api/live/act", {"session": session, "op": "step", "dt": 1 / 240, "n": 1})
        moved = next(b["position_m"] for b in reply["bodies"] if b["name"] == "rover")
        gone = ((moved[0] - where[0]) ** 2 + (moved[2] - where[2]) ** 2) ** 0.5
        self.assertGreater(gone, 0.3, f"the rover should have driven while nobody watched; it moved {gone:.2f} m")


if __name__ == "__main__":
    unittest.main(verbosity=2)
