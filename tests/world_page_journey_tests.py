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

A change to a room keeps what it did not touch (server.world_to_carry): the
hoist wound up and braked, the room's chat -- a scripted model in place of the
paid one (tests/scripted_chat_server.py) -- adds a crate through the page's own
chat box, and the hoist is still up with its battery as it was, at realtime.

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


def start_server(port: int, folder: Path, log, program: Path | None = None,
                 env_added: dict | None = None) -> subprocess.Popen | None:
    """A playground server of the test's own on `port`, keeping its rooms in
    `folder`; None if it did not come up within a minute. `program` runs in
    server.py's place, with its arguments (tests/scripted_chat_server.py), and
    `env_added` goes into its environment."""
    env = dict(os.environ, OPENAI_API_KEY="", BANJO_LIVE_ENGINE=str(RUNNER), **(env_added or {}))
    if LIBRARY.is_file():
        env["BANJO_LIBRARY"] = str(LIBRARY)
    command = [sys.executable, "-u", str(program or ROOT / "playground" / "server.py"), "--port", str(port),
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
        again carries it there and lets go. Where it comes to rest.

        Since 365f43a the copy shows by itself as soon as a thing is held
        ("Preview is visible before the key is pressed; E commits that
        destination"), so E may be offering to put it there already -- after
        a reload it always is. Only when it is not does E first show it."""
        either = ("banjoRoom.details().rows.some((r) => r[2] === 'chosen' && "
                  "(r[1] === 'Place it…' || r[1] === 'Put it here'))")
        self.assertTrue(self.wait_for(either, 30), f"E is not offering to place it: {self.situation()}")
        if self.js("banjoRoom.details().rows.some((r) => r[2] === 'chosen' && r[1] === 'Place it…')"):
            self.press_e()
        self.assertTrue(self.wait_for("banjoRoom.world.placing && banjoRoom.world.placing.answer && "
                                      "banjoRoom.world.placing.answer.fits", 30),
                        f"the copy never said it fits: {self.situation()}")
        self.assertTrue(self.offering("Put it here"), f"E is not offering to put it there: {self.situation()}")
        self.press_e()
        self.assertTrue(self.wait_for("!banjoRoom.world.held", 30), f"E did not put it there: {self.situation()}")
        return self.at_rest(name)

    def press_tab(self):
        for kind in ("keyDown", "keyUp"):
            self.page.send("Input.dispatchKeyEvent", {"type": kind, "key": "Tab", "code": "Tab",
                                                      "windowsVirtualKeyCode": 9, "nativeVirtualKeyCode": 9})
            time.sleep(0.05)

    def middle_of(self, element_id):
        return self.js(f"(() => {{ const r = document.getElementById({json.dumps(element_id)})"
                       f".getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()")

    def click(self, element_id):
        """A button pressed with the mouse, as a person presses it: moved over
        its middle, down and up (Input.dispatchMouseEvent)."""
        x, y = self.middle_of(element_id)
        self.page.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        for kind in ("mousePressed", "mouseReleased"):
            self.page.send("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left",
                                                        "clickCount": 1})
            time.sleep(0.05)

    def touch_and_cancel(self, element_id):
        """A finger put on a button and taken away by the browser -- a scroll,
        a gesture -- rather than lifted: pointerdown, then pointercancel, and
        no click (Input.dispatchTouchEvent)."""
        x, y = self.middle_of(element_id)
        self.page.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        time.sleep(0.1)
        self.page.send("Input.dispatchTouchEvent", {"type": "touchCancel", "touchPoints": []})
        time.sleep(0.05)

    def choose(self, what):
        """Tab through the choices of what the crosshair is on until `what` is
        the one E does. The side view works out what is chosen in the frame
        after a key, and in CI's software drawing a frame can be a second away."""
        for _ in range(10):
            if self.wait_for("banjoRoom.details().rows.some((r) => r[2] === 'chosen' && r[1] === "
                             f"{json.dumps(what)})", 2):
                return True
            self.press_tab()
        return False

    def machines(self):
        return self.js("banjoRoom.world.machines")

    def open_the_hoist(self):
        """The tests-machines room, looking at the hoist's drum from in front."""
        self.page.send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/world?scene=tests-machines"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.status().scene === 'tests-machines' && "
                                      "banjoRoom.ready()", 300), "the hoist room did not open")
        self.assertTrue(self.wait_for("banjoRoom.world.machines && banjoRoom.world.machines.motors && "
                                      "banjoRoom.world.machines.motors.length === 1", 60),
                        f"the room's steps do not carry its machines: {self.situation()}")
        self.page.evaluate("banjoRoom.standAt(0.1, 1.62, 2.2); banjoRoom.lookAt(0.0, 2.0, 0.0); true")
        self.assertTrue(self.wait_for("banjoRoom.world.aim && banjoRoom.world.aim.name === 'hoist: drum'", 10),
                        "the crosshair is not on the drum")


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


class WhatIsDugIsCarriedAndWeighs(PageJourney):
    """Carried ground had no weight and no end: six presses of Dig here put
    435 kg of sand and soil on the person in the owner's room, who crossed it at
    a run. What a person carries is what their 800 N hand can lift, the spade
    takes out only what still fits, and the load is in their legs."""

    def carried(self):
        c = self.js("banjoRoom.world.carriedGround") or {}
        return float(c.get("sand_kg") or 0) + float(c.get("soil_kg") or 0), c.get("limit_kg")

    # The page's own time. It moves the person by the time since its last frame,
    # and takes no frame for longer than a tenth of a second -- so where frames
    # are slower than that (CI draws in software, at 6 a second) a second on the
    # wall is less than a second of walking, and a pace read off the wall clock
    # read 1.47 m/s there for a person walking at 2.4. Frame by frame, this adds
    # up what the page adds up.
    FOLLOW = ("new Promise((done) => { const p = banjoRoom.camera.position, t0 = performance.now();"
              " let last = null, time = 0, far = 0, paced = 0, x = 0, z = 0, frames = 0, reach = 0, apart = 0;"
              " const told = [0, 0], from = [0, 0];"
              # By performance.now() when the frame runs, as the page's own frame() reads it: the
              # time a frame is given as its argument drifts from that under load.
              # Where they are is read from the first frame followed, not from when this was asked: the
              # page has moved them once by then, which at 7 frames a second is a tenth of a second's worth.
              " const tick = () => { const now = performance.now();"
              " if (last === null) { x = from[0] = p.x; z = from[1] = p.z; }"
              " else { const dt = Math.min(0.1, (now - last) / 1000), w = banjoRoom.world.inWater;"
              "   time += dt; frames++; far += Math.hypot(p.x - x, p.z - z); x = p.x; z = p.z;"
              # The page's time weighed by the pace the water leaves them, frame by frame.
              "   paced += (w ? w.pace : 1) * dt;"
              "   if (w) { told[0] += w.u * w.carried * dt; told[1] += w.w * w.carried * dt; }"
              # How far the water has asked them to be from where they began, at its most,
              # and the furthest they have ever been from where it asked.
              "   reach = Math.max(reach, Math.hypot(told[0], told[1]));"
              "   apart = Math.max(apart, Math.hypot(p.x - from[0] - told[0], p.z - from[1] - told[1])); }"
              "  last = now; const spent = performance.now() - t0;"
              "  if ((spent < %d || frames < 10) && spent < 15000) requestAnimationFrame(tick);"
              "  else done(JSON.stringify({ time, far, paced, frames, told, reach, apart, went: [p.x - from[0], p.z - from[1]] })); };"
              " requestAnimationFrame(tick); })")

    def follow(self, seconds):
        """The person followed for that long and for ten frames at least, frame by
        frame: how far they went, in how much of the page's time, that time weighed
        by the pace the water left them, and where the water that had hold of them said."""
        return json.loads(self.page.evaluate(self.FOLLOW % int(1000 * seconds), await_promise=True, timeout=120))

    def walk(self, run=False, seconds=1.2):
        """W held down, and the person followed (follow)."""
        def key(kind, key, code, vk):
            self.page.send("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": code,
                                                      "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk})
        if run:
            key("rawKeyDown", "Shift", "ShiftLeft", 16)
        key("rawKeyDown", "w", "KeyW", 87)
        try:
            seen = self.follow(seconds)
        finally:
            key("keyUp", "w", "KeyW", 87)
            if run:
                key("keyUp", "Shift", "ShiftLeft", 16)
        time.sleep(0.2)
        self.assertGreaterEqual(seen["frames"], 10, f"the page drew too few frames to pace anyone: {seen}")
        return seen

    def pace(self, run=False, seconds=1.2):
        """How fast W takes the person across the ground, in metres a second of the page's time."""
        seen = self.walk(run, seconds)
        return seen["far"] / seen["time"]

    def heap_it_all(self):
        for _ in range(8):
            if self.carried()[0] < 0.01:
                return
            before = self.carried()[0]
            self.page.evaluate("document.getElementById('heap-it').click(); true")
            self.wait_for(f"(() => {{ const c = banjoRoom.world.carriedGround || {{}}; "
                          f"return (c.sand_kg || 0) + (c.soil_kg || 0) < {before} - 0.01; }})()", 20)
        self.fail(f"heaping never emptied the hands: {self.carried()[0]:.1f} kg still carried")

    def test_the_spade_takes_what_can_be_carried_and_the_load_is_in_the_legs(self):
        self.open_the_world()
        self.assertTrue(self.wait_for("!!banjoRoom.world.groundAim", 30), "the crosshair is not on the ground")
        self.heap_it_all()
        kg, limit = self.carried()
        self.assertEqual(80, limit, "the room does not say what a person can carry before anything is dug")

        # One press of Dig here lifts about 100 kg out of this ground. It takes 80.
        self.page.evaluate("document.getElementById('dig-it').click(); true")
        self.assertTrue(self.wait_for("(() => { const c = banjoRoom.world.carriedGround || {}; "
                                      "return (c.sand_kg || 0) + (c.soil_kg || 0) > 1; })()", 30), "nothing was dug")
        kg, limit = self.carried()
        self.assertAlmostEqual(limit, kg, delta=0.01, msg="the spade did not take exactly what could be carried")
        self.assertTrue(self.wait_for("document.getElementById('inv-carrying').textContent.includes('all you can carry')", 10),
                        self.js("document.getElementById('inv-carrying').textContent"))
        self.assertIn("80 of 80 kg", self.js("document.getElementById('inv-carrying').textContent"))

        # Again: refused, in words, and the ground and the load are as they were.
        self.page.evaluate("document.getElementById('dig-it').click(); true")
        self.assertTrue(self.wait_for("banjoRoom.world.last && banjoRoom.world.last.tone === 'refused' && "
                                      "banjoRoom.world.last.text.includes('is all you can carry: heap some of it first')", 20),
                        f"a full load was not refused in words: {self.js('banjoRoom.world.last')}")
        self.assertAlmostEqual(kg, self.carried()[0], delta=1e-9)

        # It is in their legs: two fifths of the pace, and no running.
        loaded_walk, loaded_run = self.pace(), self.pace(run=True)
        self.assertLess(loaded_run, 1.2 * loaded_walk, "a person carrying all they can still ran")

        # A reload carries the same: the room keeps the dig as deep as it WENT.
        AReloadKeepsTheRoom.reload(self, "a reload carrying all that can be carried")
        self.assertAlmostEqual(kg, self.carried()[0], delta=1e-6,
                               msg="the room opened again dug the whole pit and carried the lot")

        # Heaped back, the hands are free and so are the legs.
        self.assertTrue(self.wait_for("!!banjoRoom.world.groundAim", 30), "the crosshair is not on the ground")
        self.heap_it_all()
        free_walk, free_run = self.pace(), self.pace(run=True)
        print(f"\n   carrying {kg:.1f} kg: {loaded_walk:.2f} m/s walking and {loaded_run:.2f} running; "
              f"with empty hands {free_walk:.2f} and {free_run:.2f}", flush=True)
        self.assertAlmostEqual(0.4, loaded_walk / free_walk, delta=0.08)
        self.assertGreater(free_run, 1.5 * free_walk, "with empty hands, running is no faster than walking")
        self.no_page_errors("after digging, carrying and heaping")


class ThePersonIsInTheWater(WhatIsDugIsCarriedAndWeighs):
    """Everything else in the water already was: the engine presses on every
    body's own surface, and a log goes downstream with the river. The person is
    a point of view, and stood in a flowing river as if on dry land, or on the
    bed of a pool with nothing to say their head was under."""

    # The river as the page knows it: a shallow reach to wade down, and the deepest pool.
    SPOTS = ("(() => { const R = banjoRoom; let shallow = null, deep = null;"
             " for (let x = -28; x <= 28; x += 0.25) for (let z = -28; z <= 28; z += 0.25) {"
             "   const w = R.waterAt(x, z); if (!w || !(w.depth > 0.02)) continue;"
             # As deep as it is where a person would stand, not at the nearest column's middle.
             "   const depth = w.level - R.groundAt(x, z); if (!(depth > 0.02)) continue;"
             "   const speed = Math.hypot(w.u, w.w), spot = { x, z, depth, level: w.level, u: w.u, w: w.w, speed };"
             "   if (depth > 0.25 && depth < 0.45 && speed > 0.15) { let run = 0;"
             "     for (let ahead = 0.5; ahead <= 2.5; ahead += 0.5) { const ax = x + ahead * w.u / speed, az = z + ahead * w.w / speed,"
             "       there = R.waterAt(ax, az), deep = there ? there.level - R.groundAt(ax, az) : 0; if (deep > 0.15 && deep < 0.5) run++; else break; }"
             "     if (!shallow || run > shallow.run) shallow = { ...spot, run }; }"
             "   if (!deep || depth > deep.depth) deep = spot;"
             " } return { shallow, deep }; })()")

    def test_a_person_wades_swims_is_carried_and_can_be_under(self):
        self.open_the_world()
        self.assertTrue(self.wait_for("!!banjoRoom.waterAt && !!banjoRoom.world", 30))
        self.heap_it_all() if self.js("!!banjoRoom.world.groundAim") else None
        spots = self.js(self.SPOTS)
        shallow, deep = spots["shallow"], spots["deep"]
        self.assertIsNotNone(shallow, "the world's river has no shallow reach")
        self.assertGreater(deep["depth"], 1.0, "the world has no water a person can be under")

        def stand(spot, above_bed):
            """Stood with their eye `above_bed` over the ground at that spot. What
            the page says of them in the water, with what is under of a body 1.6 m
            from eye to foot read off the same water at the same moment."""
            x, z = spot["x"], spot["z"]
            self.page.evaluate(f"banjoRoom.standAt({x}, banjoRoom.groundAt({x}, {z}) + {above_bed}, {z}); true")
            time.sleep(0.3)
            seen = self.js(f"(() => {{ const w = banjoRoom.waterAt({x}, {z}), bed = banjoRoom.groundAt({x}, {z}), "
                           f"eye = banjoRoom.camera.position.y; return {{ wet: banjoRoom.world.inWater || null, "
                           f"under: w ? Math.min(1.6, w.level - Math.max(bed, eye - 1.6)) : 0 }}; }})()")
            if seen["wet"] is not None:
                self.assertAlmostEqual(seen["under"], seen["wet"]["under"], delta=0.03)
            return seen["wet"]

        # Five metres over the river is over it, not in it.
        self.assertIsNone(stand(shallow, 5.0), "a person in the air over a river was in the water")
        free = self.pace(seconds=0.5)
        # About the 2.4 m/s they walk at; what follows is read against this, not against 2.4.
        self.assertAlmostEqual(2.4, free, delta=0.5)

        # Standing on its bed they wade, slower the deeper -- and a shallow
        # river, however fast, does not carry them.
        self.assertGreaterEqual(shallow["run"], 4, f"the world's river has no shallow reach to wade down: {shallow}")

        def legs(seen):
            """How far their own legs took them: where they went, less where the water took them."""
            return math.hypot(seen["went"][0] - seen["told"][0], seen["went"][1] - seen["told"][1])

        wet = stand(shallow, 1.6)
        self.assertIsNotNone(wet, "a person standing on the bed of a river was not in the water")
        self.assertLess(wet["under"], 0.5)
        self.assertEqual(0, wet["carried"])
        self.assertFalse(wet["head_under"])
        self.assertAlmostEqual(1 - 0.7 * wet["under"] / 1.2, wet["pace"], delta=1e-6)
        # Down the reach, the way the water runs, so that they stay in it. Their legs
        # do what the water says of them frame by frame: the ground they cover is
        # their dry-land pace times the time it left them, wherever that took them.
        self.page.evaluate(f"banjoRoom.lookAt(banjoRoom.camera.position.x + {10 * shallow['u']}, banjoRoom.camera.position.y, "
                           f"banjoRoom.camera.position.z + {10 * shallow['w']}); true")
        waded = self.walk(seconds=0.6)
        wading = waded["far"] / waded["time"]
        self.assertLess(waded["paced"] / waded["time"], 0.93,
                        f"walking down a shallow reach they were hardly in the water, so this proves nothing: {waded}")
        self.assertAlmostEqual(free, legs(waded) / waded["paced"], delta=0.06 * free,
                               msg=f"wading at {wading:.2f} m/s against {free:.2f} on dry land: {waded}")
        self.assertTrue(self.wait_for("document.getElementById('inv-carrying').textContent.includes('wading')", 10),
                        self.js("document.getElementById('inv-carrying').textContent"))

        # Crouched on the bed of the deepest pool their head is under, and it
        # looks it; they swim at three tenths of their pace.
        wet = stand(deep, 0.3)
        self.assertTrue(wet["head_under"], wet)
        self.assertTrue(self.js("document.body.classList.contains('head-under-water')"))
        self.assertTrue(self.wait_for("document.getElementById('inv-carrying').textContent.includes('under water')", 10))
        # Standing up in it, as much of them as there is water for is under.
        wet = stand(deep, 1.6)
        self.assertGreater(wet["under"], 1.0)
        swum = self.walk(seconds=0.3)
        swimming = swum["far"] / swum["time"]
        self.assertLess(swum["paced"] / swum["time"], 0.6, f"standing up in {wet['under']:.2f} m of water they were hardly in it: {swum}")
        # The pool has hold of them as well, so their legs are what is left of where
        # they went once where the water took them is taken off.
        self.assertAlmostEqual(free, legs(swum) / swum["paced"], delta=0.12 * free,
                               msg=f"swimming at {swimming:.2f} m/s against {free:.2f} on dry land: {swum}")
        stand(shallow, 5.0)
        self.assertFalse(self.js("document.body.classList.contains('head-under-water')"))

        # Where water deeper than their thighs is moving, it takes them with it: none
        # of its speed at 0.5 m, all of it by 1.2 m. Not asked of the room's river,
        # whose deeper reaches are gentle, do not run one way for long, and are not
        # moving at all yet where the page is drawn at 7 frames a second and the
        # world runs behind the clock. Asked of water the journey describes, over
        # level ground, hands off the keys: 0.85 m of it going [0.3, -0.4] m/s has
        # half its hold, and takes them [0.15, -0.2] m every second.
        stand(shallow, 5.0)
        here = self.js("banjoRoom.camera.position.toArray()")
        for depth, hold in ((0.4, 0.0), (0.85, 0.5), (1.4, 1.0)):
            self.page.evaluate(f"banjoRoom.standAt({here[0]}, {here[1]}, {here[2]}); "
                               f"banjoRoom.waterForThePerson(() => ({{ level: {here[1]} - 1.6 + {depth}, depth: {depth}, "
                               f"u: 0.3, w: -0.4 }})); true")
            time.sleep(0.3)
            wet = self.js("banjoRoom.world.inWater")
            self.assertAlmostEqual(depth, wet["under"], delta=1e-6)
            self.assertAlmostEqual(hold, wet["carried"], delta=1e-6)
            self.assertAlmostEqual(1 - 0.7 * min(1.0, depth / 1.2), wet["pace"], delta=1e-6)
            seen = self.follow(1.5)
            went, told = seen["went"], seen["told"]
            print(f"   in {depth} m of water going [0.3, -0.4] m/s, hands off the keys, they went [{went[0]:+.3f}, {went[1]:+.3f}] m "
                  f"in {seen['time']:.2f} s of the page's time: its hold is {hold:g}", flush=True)
            for axis, speed in enumerate((0.3, -0.4)):
                self.assertAlmostEqual(speed * hold * seen["time"], went[axis], delta=0.03 * seen["time"] + 0.005,
                                       msg=f"in {depth} m of water: {seen}")
            self.assertLess(seen["apart"], 0.02, f"they left where the water took them: {seen}")
        self.page.evaluate("banjoRoom.waterForThePerson(null); true")
        time.sleep(0.3)
        self.assertIsNone(self.js("banjoRoom.world.inWater || null"), "the journey's water outlived the journey")
        self.no_page_errors("after being in the water")

    test_the_spade_takes_what_can_be_carried_and_the_load_is_in_the_legs = None


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


class AHoistWorkedFromItsPanel(PageJourney):
    """A battery hoist (docs/machine-world.md), in the tests-machines room,
    worked as the owner's review of 2026-09-15 asks ("Operating a machine").

    The room opens with its battery full and its motor braked, and the Machines
    panel says so. Looking at the drum, E opens the hoist's panel. Its buttons,
    pressed with the mouse, go to the hoist's controller: Power On, then Raise,
    and the crate rises by the rope the drum takes on, the battery giving what
    the motor draws, until it stops by itself at the top of its travel, which
    the panel says. Stop & hold keeps it there drawing nothing, and a press the
    browser cancels -- a finger put on Lower and taken away by a gesture --
    does nothing."""

    def test_its_panel_raises_it_to_the_top_and_holds_it(self):
        self.open_the_hoist()
        m = self.machines()
        self.assertEqual(m["motors"][0]["state"], "braking", "the motor did not start with its brake on")
        self.assertEqual(m["stores"][0]["charge_j"], m["stores"][0]["capacity_j"], "the battery is not full")
        listed = self.js("document.getElementById('machines').hidden ? null : "
                         "document.getElementById('machine-list').innerText")
        self.assertTrue(listed and "hoist battery" in listed and "hoist: drum" in listed,
                        f"the Machines panel does not show the battery and the motor: {listed!r}")
        self.assertTrue(self.offering("Open the hoist's panel"), f"E does not open the panel: {self.situation()}")
        self.press_e()
        self.assertTrue(self.wait_for("!document.getElementById('machine-panel').hidden", 10),
                        f"E did not open the hoist's panel: {self.situation()}")
        text = lambda element_id: self.js(f"document.getElementById({json.dumps(element_id)}).textContent")
        self.assertEqual(text("mp-enabled"), "Off")
        self.assertTrue(self.js("document.getElementById('mp-ahead').disabled"),
                        "Raise can be pressed while the hoist is off")
        crate_y = "banjoRoom.world.bodies.get('hoist: crate').mesh.position.y"
        drawn0, rope0 = self.js(crate_y), m["ropes"][0]
        self.click("mp-on")
        self.assertTrue(self.wait_for("banjoRoom.world.machines.controls[0].power === true", 15),
                        f"Power On did not reach the hoist: {self.situation()}")
        self.click("mp-ahead")
        self.assertTrue(self.wait_for("banjoRoom.world.machines.motors[0].state === 'driving'", 30),
                        f"Raise did not set the motor winding: {self.situation()}")
        time.sleep(1.5)
        m = self.machines()
        rope1 = m["ropes"][0]
        # The rope's end on the crate and what is off the drum come from the
        # same step: the crate rises by what the drum takes on.
        rise = rope1["meets"][1] - rope0["meets"][1]
        taken = rope0["out_m"] - rope1["out_m"]
        print(f"\n   raised from its panel for 1.5 s: the crate rose {rise:.3f} m and {taken:.3f} m of rope went"
              f" onto the drum; the battery gave {m['stores'][0]['given_j']:.0f} J", flush=True)
        self.assertGreater(taken, 0.1, "the drum did not take the rope on")
        self.assertLess(abs(rise - taken), 0.002, f"the crate rose {rise:.4f} m for {taken:.4f} m of rope")
        self.assertGreater(self.js(crate_y) - drawn0, 0.1, "the crate the page draws did not go up")
        self.assertGreater(m["stores"][0]["given_j"], 0.0, "the battery gave nothing")
        # And on to the top of its travel, where it stops by itself.
        self.assertTrue(self.wait_for("banjoRoom.world.machines.controls[0].condition === 'at the top'", 40),
                        f"the hoist did not stop at the top of its travel: {self.situation()}")
        top = self.machines()["controls"][0]
        print(f"   it stopped by itself with {top['out_m']:.3f} m of rope out (its top is {top['top_out_m']:.3f});"
              f" the panel says {text('mp-condition')!r}", flush=True)
        self.assertAlmostEqual(top["out_m"], top["top_out_m"], delta=0.01)
        self.assertEqual(text("mp-condition"), "at the top")
        self.click("mp-stop")
        self.assertTrue(self.wait_for("banjoRoom.world.machines.controls[0].direction === 0", 15),
                        f"Stop & hold did not reach the hoist: {self.situation()}")
        time.sleep(1.0)
        held = self.machines()
        time.sleep(1.5)
        now = self.machines()
        self.assertLess(abs(now["ropes"][0]["meets"][1] - held["ropes"][0]["meets"][1]), 0.005,
                        "held, the crate did not stay up")
        self.assertEqual(now["motors"][0]["drawn_j"], held["motors"][0]["drawn_j"],
                         "held on its brake, the motor went on drawing")
        # A press the browser takes away does nothing.
        self.touch_and_cancel("mp-back")
        time.sleep(1.0)
        self.assertEqual(self.machines()["controls"][0]["direction"], 0, "a cancelled press set the hoist going")
        self.no_page_errors("after working the hoist from its panel")


class AChatChangeKeepsTheHoistUp(PageJourney):
    """The room's chat changes a room, and what it did not touch is as it stood
    (server.world_to_carry, live_session.Live.open with a carry). In the
    tests-machines room E winds the hoist up and Stop brakes it; then the chat,
    asked in the page's own chat box, adds a crate beside it -- a scripted model
    in place of the paid one (tests/scripted_chat_server.py), working the
    room's real tools. The crate is there, the hoist is still up with its
    battery as it was, and the room runs on at realtime. Before, the chat's
    change put the hoist's crate back on the ground and its battery back to
    full."""

    ANSWERS = [
        {"status": "completed", "usage": {}, "output": [{
            "type": "function_call", "call_id": "c1", "name": "add_object",
            "arguments": json.dumps({"object": {"name": "new crate", "shape": "box", "material": "oak",
                                                "size_m": [0.3, 0.3, 0.3], "position_m": [0.8, 0.6]}})}]},
        {"status": "completed", "usage": {}, "output": [{"type": "message", "content": [
            {"type": "output_text", "text": "An oak crate is beside the hoist."}]}]},
    ]

    @classmethod
    def start(cls) -> subprocess.Popen:
        answers = cls.folder / "scripted-chat.json"
        answers.write_text(json.dumps(cls.ANSWERS), encoding="utf-8")
        server = start_server(cls.port, cls.folder, cls.log, program=ROOT / "tests" / "scripted_chat_server.py",
                              env_added={"BANJO_SCRIPTED_CHAT": str(answers)})
        if server is None:
            raise RuntimeError(f"the playground did not come up on {cls.port}:\n"
                               + cls.log_path.read_text(encoding="utf-8", errors="replace")[-2000:])
        return server

    def test_the_chats_crate_comes_and_the_hoist_stays_up(self):
        self.open_the_hoist()
        # The drum's panel is E's first choice now; its own actions are Tab on.
        self.assertTrue(self.choose("Wind it up"), f"Tab did not move on to Wind it up: {self.situation()}")
        self.press_e()
        self.assertTrue(self.wait_for("banjoRoom.world.machines.motors[0].state === 'driving'", 30),
                        f"E did not set the motor winding: {self.situation()}")
        # Tab on to Stop straight away, rather than waiting to see whether it is
        # chosen: left winding for the four seconds that took, the crate went up
        # into the drum.
        time.sleep(0.8)
        self.press_tab()
        self.assertTrue(self.choose("Stop"), f"Tab did not move on to Stop: {self.situation()}")
        self.press_e()
        self.assertTrue(self.wait_for("banjoRoom.world.machines.motors[0].state === 'braking'", 30),
                        f"Stop did not put the brake on: {self.situation()}")
        time.sleep(1.0)
        crate_y = "banjoRoom.world.bodies.get('hoist: crate').mesh.position.y"
        before, y_before = self.machines(), self.js(crate_y)
        self.assertGreater(before["ropes"][0]["wound_m"], 0.1, "the hoist was not wound up")
        session = self.js("banjoRoom.world.session")

        # Asked as a person asks: typed into the room's chat and sent.
        self.page.evaluate("document.getElementById('ask-text').value = 'put an oak crate beside the hoist'; "
                           "document.getElementById('ask').requestSubmit(); true")
        self.assertTrue(self.wait_for(f"banjoRoom.world.session !== {json.dumps(session)} && "
                                      "banjoRoom.world.bodies.has('new crate') && "
                                      "banjoRoom.world.bodies.has('hoist: crate')", 120),
                        f"the chat's crate did not come: {self.situation()}")
        time.sleep(1.0)
        after, y_after = self.machines(), self.js(crate_y)
        rope0, rope1 = before["ropes"][0], after["ropes"][0]
        store0, store1 = before["stores"][0], after["stores"][0]
        print(f"\n   wound up and braked: {rope0['wound_m']:.4f} m of rope on the drum, the crate at {y_before:.4f} m,"
              f" the battery at {store0['charge_j']:.2f} J ({store0['given_j']:.2f} J given)"
              f"\n   after the chat's crate: {rope1['wound_m']:.4f} m on the drum, the crate at {y_after:.4f} m,"
              f" the battery at {store1['charge_j']:.2f} J ({store1['given_j']:.2f} J given), the motor"
              f" {after['motors'][0]['state']}", flush=True)
        self.assertEqual(after["motors"][0]["state"], "braking", "the hoist's motor is not braked as it was")
        self.assertLess(abs(rope1["out_m"] - rope0["out_m"]), 0.001, "the rope is not as far out as it was")
        self.assertEqual((store1["charge_j"], store1["given_j"]), (store0["charge_j"], store0["given_j"]),
                         "the battery is not as it was")
        self.assertEqual(after["motors"][0]["drawn_j"], before["motors"][0]["drawn_j"],
                         "the motor's account is not as it was")
        self.assertLess(abs(y_after - y_before), 0.005, "the crate the page draws is not where it hung")
        said = self.js("banjoRoom.status().said") or []
        self.assertFalse(any(line.startswith("As the room has it now") for line in said),
                         f"the page said something was not carried: {said[-3:]}")

        # And the room runs on at realtime, with no page errors.
        t0, w0 = self.js("banjoRoom.status().time_s"), time.monotonic()
        time.sleep(3.0)
        t1, w1 = self.js("banjoRoom.status().time_s"), time.monotonic()
        realtime = 100.0 * (t1 - t0) / (w1 - w0)
        print(f"   after the chat's change the room ran {t1 - t0:.2f} s of its time in {w1 - w0:.2f} s:"
              f" {realtime:.1f}% of realtime", flush=True)
        self.assertGreater(realtime, 90.0, "the room did not run at realtime after the chat's change")
        self.no_page_errors("after the chat's change")


# Workshop controls share the existing required Chrome/engine CI gate.
from workshop_browser_tests import WorkshopBrowserRegression  # noqa: E402,F401

if __name__ == "__main__":
    unittest.main()
