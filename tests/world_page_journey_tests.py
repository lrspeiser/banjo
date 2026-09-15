"""The world page as a person uses it, in a real browser on the real engine.

The owner's rule is that nothing is done until it can be seen working in 3D,
and the checks that saw it were scripts in a scratchpad: nothing ran them again
when the code moved on. This is the first of them kept here, and CI runs it.

A reload rejoins the running room (server._rejoin):
- a thing picked up with E is still in the hand after a reload, and the person
  stands where they stood;
- a thing put down somewhere is where it was put after the next reload, not
  where the room was authored with it;
- "Start the room again" opens the room again from what it is held as.

It starts a playground server of its own on a free port, with the engine the
build made (BANJO_BUILD_DIR, or build/integration/Release) and rooms in a
folder of its own, and drives headless Chrome over the DevTools protocol
(tests/qa_browser.py: BANJO_CHROME says where Chrome is, BANJO_CHROME_ARGS what
else it needs). It skips without the engine or Chrome -- unless
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


class AReloadKeepsTheRoom(unittest.TestCase):

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
        folder = Path(cls._temp.name)
        cls.port = free_port()
        env = dict(os.environ, OPENAI_API_KEY="", BANJO_LIVE_ENGINE=str(RUNNER))
        if LIBRARY.is_file():
            env["BANJO_LIBRARY"] = str(LIBRARY)
        command = [sys.executable, "-u", str(ROOT / "playground" / "server.py"), "--port", str(cls.port),
                   "--engine", str(ENGINE), "--rooms", str(folder / "rooms"), "--runs", str(folder / "runs")]
        if STUDIO.is_file():
            command += ["--studio", str(STUDIO)]
        cls.log_path = folder / "server.log"
        cls.log = open(cls.log_path, "w", encoding="utf-8")
        cls.server = subprocess.Popen(command, cwd=str(ROOT), env=env, stdout=cls.log,
                                      stderr=subprocess.STDOUT,
                                      **({} if os.name == "nt" else {"start_new_session": True}))
        deadline = time.monotonic() + 60.0
        up = False
        while time.monotonic() < deadline and cls.server.poll() is None and not up:
            try:
                connection = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=2)
                connection.request("GET", "/world")
                up = connection.getresponse().status == 200
                connection.close()
            except OSError:
                time.sleep(0.3)
        if not up:
            cls.stop()
            raise RuntimeError(f"the playground did not come up on {cls.port}:\n"
                               + cls.log_path.read_text(encoding="utf-8", errors="replace")[-2000:])

    @classmethod
    def stop(cls):
        server = getattr(cls, "server", None)
        if server is not None and server.poll() is None:
            # The server and the live runner it started, and nothing else.
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"], capture_output=True)
            else:
                os.killpg(server.pid, signal.SIGTERM)
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    os.killpg(server.pid, signal.SIGKILL)
                server.wait(timeout=15)
        if getattr(cls, "log", None) is not None:
            cls.log.close()

    @classmethod
    def tearDownClass(cls):
        cls.stop()
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
              return {aim: r.world.aim && r.world.aim.name, held: r.world.held && r.world.held.name,
                      mode: r.world.use && r.world.use.mode, last: d.last, facts: d.facts,
                      rows: d.rows, errors: r.status().errors};
            })()"""))[:1500]
        except Exception as error:   # the page itself is what went wrong
            page = f"(the page could not say: {error})"
        tail = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-12:]
        return page + "\n  server: " + "\n  server: ".join(tail)

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
        things = self.js(THINGS)
        ball = next((b for b in things if not b["anchored"] and 0 < b["mass"] < 20 and "ball" in b["name"]),
                    None)
        self.assertIsNotNone(ball, f"no loose ball in the world room: {sorted(b['name'] for b in things)}")
        name, q = ball["name"], json.dumps(ball["name"])
        authored = self.at_rest(name)

        # E: into the hand. Then two metres to the side with it, so that where
        # it ends up is nowhere the room was authored with it.
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
        self.page.evaluate(f"banjoRoom.standAt({gx}, {ground + 1.62}, {gz}); "
                           f"banjoRoom.lookAt({gx}, {ground + 0.4}, {gz - 2.0}); true")
        time.sleep(1.5)
        stood = self.js("banjoRoom.camera.position.toArray()")

        self.reload("a reload with it in the hand")
        self.assertTrue(self.wait_for(f"banjoRoom.world.held && banjoRoom.world.held.name === {q}", 20),
                        f"after a reload the hand no longer holds {name}")
        self.assertTrue(self.js(f"!!(banjoRoom.world.inventory.hands.right && "
                                f"banjoRoom.world.inventory.hands.right.name === {q})"),
                        "after a reload the record's right hand is empty")
        now = self.js("banjoRoom.camera.position.toArray()")
        self.assertLess(math.dist(now, stood), 0.3,
                        f"after a reload the person is not where they stood: {stood} -> {now}")

        # E: put down there -- and after the next reload it is still there.
        self.assertTrue(self.offering("Put it down"), f"E is not offering to put it down: {self.situation()}")
        self.press_e()
        self.assertTrue(self.wait_for("!banjoRoom.world.held", 30), f"E did not put it down: {self.situation()}")
        put = self.at_rest(name)
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


if __name__ == "__main__":
    unittest.main()
