"""The world page as a person uses it, in a real browser on the real engine.

The owner's rule is that nothing is done until it can be seen working in 3D,
and the checks that saw it were scripts in a scratchpad: nothing ran them again
when the code moved on. These are kept here, and CI runs them.

A reload rejoins the running room (server._rejoin):
- a thing picked up with E is still in the hand after a reload, and the person
  stands where they stood;
- a thing put down somewhere is where it was put after the next reload, not
  where the room was authored with it;
- "Start the room again" opens the room again from what it is held as.

A restart gives back the room as it stood: the server keeps the running world
with the room (room_store), and one that starts again opens it whole.
- Killed outright and started again, it gives back the thing in the hand, and
  the reload puts the person where they stood. The page has given the room up
  as stopped by then, as it has for anyone who reloads after a restart.
- Asked to stop and started again, it gives back a thing where it was put.

Each starts a playground server of its own on a free port, with the engine the
build made (BANJO_BUILD_DIR, or build/integration/Release) and rooms in a
folder of its own, and drives headless Chrome over the DevTools protocol
(tests/qa_browser.py: BANJO_CHROME says where Chrome is, BANJO_CHROME_ARGS what
else it needs). They skip without the engine or Chrome -- unless
BANJO_BROWSER_TESTS=required, which CI sets, so a browser that went missing
fails rather than passing unseen.

    python tests/world_page_journey_tests.py -v
"""
from __future__ import annotations

import http.client
import json
import math
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import qa_browser  # noqa: E402

BUILD = Path(os.environ["BANJO_BUILD_DIR"]).resolve() if os.environ.get("BANJO_BUILD_DIR") else \
    ROOT / "build" / "integration" / "Release"
SUFFIX = ".exe" if os.name == "nt" else ""
ENGINE = BUILD / f"banjo_platform_cli{SUFFIX}"
RUNNER = BUILD / f"banjo_live_world_run{SUFFIX}"
STUDIO = BUILD / f"banjo_network_lab{SUFFIX}"
LIBRARY = BUILD / ("banjo.dll" if os.name == "nt" else "libbanjo.so")
REQUIRED = os.environ.get("BANJO_BROWSER_TESTS") == "required"
THINGS = ("[...banjoRoom.world.bodies].map(([n, e]) => ({name: n, anchored: !!e.anchored, "
          "mass: e.mass || 0, p: e.mesh.position.toArray()}))")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def start_server(port: int, folder: Path, log) -> subprocess.Popen | None:
    """A playground server of the test's own on `port`, keeping its rooms in
    `folder`; None if it did not come up within a minute."""
    env = dict(os.environ, OPENAI_API_KEY="", BANJO_LIVE_ENGINE=str(RUNNER))
    if LIBRARY.is_file():
        env["BANJO_LIBRARY"] = str(LIBRARY)
    command = [sys.executable, "-u", str(ROOT / "playground" / "server.py"), "--port", str(port),
               "--engine", str(ENGINE), "--rooms", str(folder / "rooms"), "--runs", str(folder / "runs")]
    if STUDIO.is_file():
        command += ["--studio", str(STUDIO)]
    # A process group of its own: it can be asked to stop (on Windows, Ctrl+Break
    # reaches a group), and stopped with the live runner it started and nothing
    # else.
    group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    server = subprocess.Popen(command, cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT, **group)
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline and server.poll() is None:
        try:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            connection.request("GET", "/world")
            up = connection.getresponse().status == 200
            connection.close()
            if up:
                return server
        except OSError:
            pass
        time.sleep(0.3)
    stop_server(server)
    return None


def stop_server(server: subprocess.Popen | None, ask: bool = False) -> bool:
    """Stops a server of the test's own, with the live runner it started and
    nothing else: outright, as a crash or a hard stop does -- or, with `ask`,
    the way a host asks a service to stop (SIGTERM; Ctrl+Break on Windows),
    when the server saves the running world on its way out. True when it
    stopped when asked."""
    if server is None or server.poll() is not None:
        return False
    if ask:
        try:
            os.kill(server.pid, signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
            server.wait(timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            pass   # stopped outright below, and the caller says it did not stop when asked
        else:
            if os.name != "nt":
                try:
                    os.killpg(server.pid, signal.SIGKILL)   # anything it left behind
                except ProcessLookupError:
                    pass
            return True
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"], capture_output=True)
    else:
        os.killpg(server.pid, signal.SIGKILL)
    server.wait(timeout=15)
    return False


class PageJourney(unittest.TestCase):
    """What the journeys share: a server of their own, headless Chrome, and
    the page read the way a person reads it."""

    @classmethod
    def setUpClass(cls):
        missing = [what for what, there in (("the engine", ENGINE.is_file()),
                                            ("the live runner", RUNNER.is_file()),
                                            ("Chrome", qa_browser.CHROME.is_file())) if not there]
        if missing:
            why = f"{' and '.join(missing)} not found (build {BUILD}, Chrome {qa_browser.CHROME})"
            if REQUIRED:
                raise RuntimeError(why)
            raise unittest.SkipTest(why)
        cls._temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls._temp.name)
        cls.port = free_port()
        cls.log_path = cls.folder / "server.log"
        cls.log = open(cls.log_path, "w", encoding="utf-8")
        cls.server = None
        try:
            cls.server = cls.start()
        except RuntimeError:
            cls.tearDownClass()
            raise

    @classmethod
    def start(cls) -> subprocess.Popen:
        server = start_server(cls.port, cls.folder, cls.log)
        if server is None:
            raise RuntimeError(f"the playground did not come up on {cls.port}:\n"
                               + cls.log_path.read_text(encoding="utf-8", errors="replace")[-2000:])
        return server

    @classmethod
    def tearDownClass(cls):
        stop_server(getattr(cls, "server", None))
        if getattr(cls, "log", None) is not None:
            cls.log.close()
            cls.log = None
        try:
            cls._temp.cleanup()
        except OSError:
            pass

    # -- in the page --------------------------------------------------------
    def setUp(self):
        # Small, because CI draws it in software.
        self.chrome = qa_browser.Chrome(960, 600)
        self.addCleanup(self.chrome.close)
        self.page = self.chrome.page
        self.page.send("Page.enable")

    def js(self, expression):
        return json.loads(self.page.evaluate(f"JSON.stringify({expression})", timeout=30))

    def wait_for(self, expression, timeout_s=30.0):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                if self.page.evaluate(expression, timeout=10):
                    return True
            except (RuntimeError, TimeoutError):
                pass   # between documents
            time.sleep(0.2)
        return False

    def press_e(self):
        for kind in ("keyDown", "keyUp"):
            self.page.send("Input.dispatchKeyEvent", {
                "type": kind, "key": "e", "code": "KeyE", "windowsVirtualKeyCode": 69,
                "nativeVirtualKeyCode": 69, **({"text": "e", "unmodifiedText": "e"} if kind == "keyDown" else {})})
            time.sleep(0.05)

    def position(self, name):
        q = json.dumps(name)
        return self.js(f"banjoRoom.world.bodies.get({q}) ? "
                       f"banjoRoom.world.bodies.get({q}).mesh.position.toArray() : null")

    def at_rest(self, name, timeout_s=30.0):
        """Where it lies once it has stopped moving."""
        last = self.position(name)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            time.sleep(0.5)
            now = self.position(name)
            if now is not None and last is not None and math.dist(now, last) < 0.002:
                return now
            last = now
        return last

    def no_page_errors(self, when):
        errors = self.js("banjoRoom.status().errors")
        self.assertFalse(errors, f"page errors {when}: {errors}")

    def offering(self, what):
        """Whether the side view marks `what` as the thing E does now -- what a
        person reads before pressing it. The page works that out in the frame
        after the crosshair lands on something, and in CI's software drawing a
        frame can be a second away: E pressed the moment the crosshair was on
        the ball did nothing there."""
        return self.wait_for("banjoRoom.details().rows.some((r) => r[2] === 'chosen' && "
                             f"r[1] === {json.dumps(what)})", 30)

    def situation(self):
        """What the page says of itself and the server's last lines, for a
        failure to explain itself."""
        try:
            page = json.dumps(self.js("""(() => {
              const r = banjoRoom, d = r.details ? r.details() : {};
              const placing = r.world.placing;
              return {aim: r.world.aim && r.world.aim.name, held: r.world.held && r.world.held.name,
                      placing: placing ? {why: placing.answer && placing.answer.why,
                                          at: placing.answer && placing.answer.at_m} : null,
                      mode: r.world.use && r.world.use.mode, last: d.last, facts: d.facts,
                      rows: d.rows, errors: r.status().errors};
            })()"""))[:1500]
        except Exception as error:   # the page itself is what went wrong
            page = f"(the page could not say: {error})"
        tail = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-12:]
        return page + "\n  server: " + "\n  server: ".join(tail)

    def open_the_world(self):
        self.page.send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/world"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.status().scene === 'world' && "
                                      "banjoRoom.ready()", 300), "the world room did not open")
        # How fast this machine draws the room, for reading a failure by: CI
        # draws it in software.
        frames = self.page.evaluate(
            "new Promise((done) => { let n = 0; const t0 = performance.now(); const tick = () => {"
            " n++; if (performance.now() - t0 < 1000) requestAnimationFrame(tick); else done(n); };"
            " requestAnimationFrame(tick); })", await_promise=True, timeout=30)
        print(f"\n   the page draws {frames} frames a second here", flush=True)

    def carry_a_ball(self):
        """E: a loose ball into the right hand. Then two metres to the side with
        it, so that where it ends up is nowhere the room was authored with it,
        looking down at the ground 1.5 m ahead: within the 3 m a hand places
        things at. Its name, where the room had it at rest, and where the
        person stands."""
        things = self.js(THINGS)
        ball = next((b for b in things if not b["anchored"] and 0 < b["mass"] < 20 and "ball" in b["name"]),
                    None)
        self.assertIsNotNone(ball, f"no loose ball in the world room: {sorted(b['name'] for b in things)}")
        name, q = ball["name"], json.dumps(ball["name"])
        authored = self.at_rest(name)
        x, y, z = authored
        ground = self.js(f"banjoRoom.groundAt({x}, {z + 1.0})") or 0.0
        self.page.evaluate(f"banjoRoom.standAt({x}, {ground + 1.62}, {z + 1.0}); "
                           f"banjoRoom.lookAt({x}, {y}, {z}); true")
        self.assertTrue(self.wait_for(f"banjoRoom.world.aim && banjoRoom.world.aim.name === {q}", 10),
                        f"the crosshair is not on {name}")
        self.assertTrue(self.offering("Pick it up"), f"E is not offering to pick {name} up: {self.situation()}")
        self.press_e()
        self.assertTrue(self.wait_for(f"banjoRoom.world.held && banjoRoom.world.held.name === {q} && "
                                      f"banjoRoom.world.inventory.hands.right && "
                                      f"banjoRoom.world.inventory.hands.right.name === {q}", 30),
                        f"E did not pick {name} up into the right hand: {self.situation()}")
        eye = self.js("banjoRoom.camera.position.toArray()")
        gx, gz = eye[0] + 2.0, eye[2]
        ground = self.js(f"banjoRoom.groundAt({gx}, {gz})") or 0.0
        ahead = self.js(f"banjoRoom.groundAt({gx}, {gz - 1.5})") or ground
        self.page.evaluate(f"banjoRoom.standAt({gx}, {ground + 1.62}, {gz}); "
                           f"banjoRoom.lookAt({gx}, {ahead}, {gz - 1.5}); true")
        time.sleep(1.5)
        return name, authored, self.js("banjoRoom.camera.position.toArray()")

    def put_it_down(self, name):
        """E shows where it will go (the owner: "E shows, E places"): a
        see-through copy on the ground ahead, which the engine says fits. E
        again carries it there and lets go. Where it comes to rest."""
        self.assertTrue(self.offering("Place it…"), f"E is not offering to place it: {self.situation()}")
        self.press_e()
        self.assertTrue(self.wait_for("banjoRoom.world.placing && banjoRoom.world.placing.answer && "
                                      "banjoRoom.world.placing.answer.fits", 30),
                        f"the copy never said it fits: {self.situation()}")
        self.assertTrue(self.offering("Put it here"), f"E is not offering to put it there: {self.situation()}")
        self.press_e()
        self.assertTrue(self.wait_for("!banjoRoom.world.held", 30), f"E did not put it there: {self.situation()}")
        return self.at_rest(name)


class AReloadKeepsTheRoom(PageJourney):

    def reload(self, why):
        self.no_page_errors(f"before {why}")
        origin = self.js("performance.timeOrigin")
        session = self.js("banjoRoom.world.session")
        self.page.send("Page.reload", {})
        self.assertTrue(self.wait_for(f"performance.timeOrigin !== {origin} && window.banjoRoom && "
                                      f"banjoRoom.ready()", 180), f"{why}: the page did not come back")
        time.sleep(1.5)
        self.assertNotEqual(self.js("banjoRoom.world.session"), session,
                            f"{why}: the page did not take the room over under a new id")
        said = self.js("banjoRoom.status().said") or []
        self.assertTrue(any("as you left it" in line for line in said),
                        f"{why}: the room was opened again rather than rejoined: {said[-3:]}")

    def test_what_the_hand_holds_and_where_things_were_put_survive_a_reload(self):
        self.open_the_world()
        name, authored, stood = self.carry_a_ball()
        q = json.dumps(name)

        self.reload("a reload with it in the hand")
        self.assertTrue(self.wait_for(f"banjoRoom.world.held && banjoRoom.world.held.name === {q}", 20),
                        f"after a reload the hand no longer holds {name}")
        self.assertTrue(self.js(f"!!(banjoRoom.world.inventory.hands.right && "
                                f"banjoRoom.world.inventory.hands.right.name === {q})"),
                        "after a reload the record's right hand is empty")
        now = self.js("banjoRoom.camera.position.toArray()")
        self.assertLess(math.dist(now, stood), 0.3,
                        f"after a reload the person is not where they stood: {stood} -> {now}")

        # Put down where the copy showed -- and after the next reload it is
        # still there.
        put = self.put_it_down(name)
        self.assertGreater(math.dist(put, authored), 1.0,
                           f"it was put down only {math.dist(put, authored):.2f} m from where the room had it")
        self.reload("a reload after putting it down")
        after = self.at_rest(name)
        self.assertIsNotNone(after, f"{name} is gone after a reload")
        self.assertLess(math.dist(after, put), 0.05,
                        f"after a reload it is not where it was put: {put} -> {after}")

        # "Start the room again": the room as it is held, the ball back where it
        # was authored -- the way out of a room that has stopped.
        self.no_page_errors("before starting the room again")
        session = self.js("banjoRoom.world.session")
        self.page.evaluate("document.getElementById('reset').click(); true")
        self.assertTrue(self.wait_for(f"banjoRoom.world.session !== {json.dumps(session)} && "
                                      f"banjoRoom.ready()", 180), "the room did not start again")
        again = self.at_rest(name)
        self.assertLess(math.dist(again, authored), 0.3,
                        f"'Start the room again' did not put {name} back where the room had it: "
                        f"{again} against {authored}")
        self.no_page_errors("after starting the room again")


class ARestartGivesBackTheRoom(PageJourney):

    def kept(self):
        """The room's file as the server last wrote it: when, and its world."""
        try:
            record = json.loads((self.folder / "rooms" / "world.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, None
        return record.get("saved_unix_s"), record.get("world")

    @staticmethod
    def kept_pose(world, name):
        for body in (world or {}).get("bodies") or []:
            if body.get("name") == name and body.get("pose"):
                return body["pose"]["com_m"]
        return None

    def restart(self, why, ask):
        """The server stopped -- outright, or asked to -- and started again once
        the page has given the room up as stopped, which is what a person who
        reloads after a restart has; then the page reloaded."""
        stopped_when_asked = stop_server(type(self).server, ask=ask)
        if ask:
            self.assertTrue(stopped_when_asked, f"{why}: the server did not stop when asked")
        self.assertTrue(self.wait_for("banjoRoom.world.session === null", 60),
                        f"{why}: the page did not give the room up once its server had gone: {self.situation()}")
        type(self).server = self.start()
        origin = self.js("performance.timeOrigin")
        self.page.send("Page.reload", {})
        self.assertTrue(self.wait_for(f"performance.timeOrigin !== {origin} && window.banjoRoom && "
                                      f"banjoRoom.ready()", 300), f"{why}: the page did not come back")
        time.sleep(1.5)
        said = self.js("banjoRoom.status().said") or []
        self.assertTrue(any("as you left it" in line for line in said),
                        f"{why}: the room was opened from its spec, not as it stood: {said[-3:]}")
        self.assertTrue(any(line.startswith("Not kept yet") for line in said),
                        f"{why}: the page did not say what a restart does not give back: {said[-3:]}")
        self.no_page_errors(f"after {why}")

    def test_the_hand_and_where_things_were_put_come_back_after_a_restart(self):
        self.open_the_world()
        name, authored, stood = self.carry_a_ball()
        q = json.dumps(name)
        held_at = self.position(name)
        walked = time.time()
        # The server keeps the running world every 5 s of its time while the
        # page steps it: wait for one kept after the walk, with the ball in the
        # hand where it is now.
        saved = None
        deadline = time.monotonic() + 90
        while saved is None and time.monotonic() < deadline:
            when, world = self.kept()
            at = self.kept_pose(world, name)
            if (when and when > walked and ((world or {}).get("hand") or {}).get("holding") == name
                    and at and math.dist(at, held_at) < 0.2):
                saved = at
            time.sleep(0.5)
        self.assertIsNotNone(saved, f"the server did not keep the world with {name} in the hand: "
                                    f"{self.situation()}")
        self.no_page_errors("before the server was killed")

        self.restart("a restart with it in the hand (the server killed outright)", ask=False)
        self.assertTrue(self.wait_for(f"banjoRoom.world.held && banjoRoom.world.held.name === {q}", 30),
                        f"after a restart the hand no longer holds {name}: {self.situation()}")
        self.assertTrue(self.js(f"!!(banjoRoom.world.inventory.hands.right && "
                                f"banjoRoom.world.inventory.hands.right.name === {q})"),
                        "after a restart the record's right hand is empty")
        now = self.js("banjoRoom.camera.position.toArray()")
        self.assertLess(math.dist(now, stood), 0.3,
                        f"after a restart the person is not where they stood: {stood} -> {now}")
        back = self.position(name)
        self.assertIsNotNone(back, f"{name} is gone after a restart")
        self.assertLess(math.dist(back, saved), 0.25,
                        f"after a restart {name} is not in the hand where it was kept: {saved} -> {back}")

        put = self.put_it_down(name)
        self.assertGreater(math.dist(put, authored), 1.0,
                           f"it was put down only {math.dist(put, authored):.2f} m from where the room had it")
        self.restart("a restart after putting it down (the server asked to stop)", ask=True)
        self.assertTrue(self.wait_for("!banjoRoom.world.held", 10),
                        f"after a restart the hand holds something: {self.situation()}")
        self.assertFalse(self.js("banjoRoom.world.inventory.hands.right"),
                         "after a restart the record's right hand is not empty")
        after = self.at_rest(name)
        self.assertIsNotNone(after, f"{name} is gone after a restart")
        self.assertLess(math.dist(after, put), 0.05,
                        f"after a restart it is not where it was put: {put} -> {after}")


class AHoistWindsInThePage(PageJourney):
    """A battery hoist (docs/machine-world.md), in the tests-machines room.

    The room opens with its battery full and its motor braked, and the
    Machines panel says so. Looking at the drum, E runs "Wind it up": the
    crate rises by the rope the drum takes on, and the battery gives what the
    motor draws. Tab on to "Stop" and E again, and the crate stays up with the
    motor drawing nothing."""

    def press_tab(self):
        for kind in ("keyDown", "keyUp"):
            self.page.send("Input.dispatchKeyEvent", {"type": kind, "key": "Tab", "code": "Tab",
                                                      "windowsVirtualKeyCode": 9, "nativeVirtualKeyCode": 9})
            time.sleep(0.05)

    def choose(self, what):
        """Tab through the drum's choices until `what` is the one E does. The
        side view works out what is chosen in the frame after a key, and in
        CI's software drawing a frame can be a second away."""
        for _ in range(10):
            if self.wait_for("banjoRoom.details().rows.some((r) => r[2] === 'chosen' && r[1] === "
                             f"{json.dumps(what)})", 2):
                return True
            self.press_tab()
        return False

    def machines(self):
        return self.js("banjoRoom.world.machines")

    def test_e_winds_the_crate_up_and_stop_holds_it(self):
        self.page.send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/world?scene=tests-machines"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.status().scene === 'tests-machines' && "
                                      "banjoRoom.ready()", 300), "the hoist room did not open")
        self.assertTrue(self.wait_for("banjoRoom.world.machines && banjoRoom.world.machines.motors && "
                                      "banjoRoom.world.machines.motors.length === 1", 60),
                        f"the room's steps do not carry its machines: {self.situation()}")
        m = self.machines()
        self.assertEqual(m["motors"][0]["state"], "braking", "the motor did not start with its brake on")
        self.assertEqual(m["stores"][0]["charge_j"], m["stores"][0]["capacity_j"], "the battery is not full")
        panel = self.js("document.getElementById('machines').hidden ? null : "
                        "document.getElementById('machine-list').innerText")
        self.assertTrue(panel and "hoist battery" in panel and "hoist: drum" in panel,
                        f"the Machines panel does not show the battery and the motor: {panel!r}")
        # In front of the drum, looking at it.
        self.page.evaluate("banjoRoom.standAt(0.1, 1.62, 2.2); banjoRoom.lookAt(0.0, 2.0, 0.0); true")
        self.assertTrue(self.wait_for("banjoRoom.world.aim && banjoRoom.world.aim.name === 'hoist: drum'", 10),
                        "the crosshair is not on the drum")
        self.assertTrue(self.offering("Wind it up"), f"E is not offering to wind it up: {self.situation()}")
        crate_y = "banjoRoom.world.bodies.get('hoist: crate').mesh.position.y"
        drawn0, rope0 = self.js(crate_y), m["ropes"][0]
        self.press_e()
        self.assertTrue(self.wait_for("banjoRoom.world.machines.motors[0].state === 'driving'", 30),
                        f"E did not set the motor winding: {self.situation()}")
        time.sleep(1.5)
        m = self.machines()
        rope1 = m["ropes"][0]
        # The rope's end on the crate and what is off the drum come from the
        # same step: the crate rises by what the drum takes on.
        rise = rope1["meets"][1] - rope0["meets"][1]
        taken = rope0["out_m"] - rope1["out_m"]
        print(f"\n   winding for 1.5 s: the crate rose {rise:.3f} m and {taken:.3f} m of rope went onto the"
              f" drum; the battery gave {m['stores'][0]['given_j']:.0f} J", flush=True)
        self.assertGreater(taken, 0.1, "the drum did not take the rope on")
        self.assertLess(abs(rise - taken), 0.002, f"the crate rose {rise:.4f} m for {taken:.4f} m of rope")
        self.assertGreater(self.js(crate_y) - drawn0, 0.1, "the crate the page draws did not go up")
        self.assertGreater(m["stores"][0]["given_j"], 0.0, "the battery gave nothing")
        self.assertTrue(self.choose("Stop"), f"Tab did not move on to Stop: {self.situation()}")
        self.press_e()
        self.assertTrue(self.wait_for("banjoRoom.world.machines.motors[0].state === 'braking'", 30),
                        f"Stop did not put the brake on: {self.situation()}")
        time.sleep(1.0)
        held = self.machines()
        time.sleep(1.5)
        now = self.machines()
        self.assertLess(abs(now["ropes"][0]["meets"][1] - held["ropes"][0]["meets"][1]), 0.005,
                        "braked, the crate did not stay up")
        self.assertEqual(now["motors"][0]["drawn_j"], held["motors"][0]["drawn_j"],
                         "braked, the motor went on drawing")
        self.no_page_errors("after winding the hoist")


if __name__ == "__main__":
    unittest.main()
