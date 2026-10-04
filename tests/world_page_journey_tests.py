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

A cart drives itself to a lake's edge (docs/machine-world.md): E on its front
wheels opens its panel, On and Forward send it down the shore, and its water
sensor stops it with its front wheels dry. A rover roams the shore by itself:
E on it opens its program's panel, On sets it roaming, turning away from the
water, and Off stops it. With its battery low it rests while the solar panel
on its deck charges it from the room's sun. Under a sun with a day, the sun
sets, the room's light goes with it, and the rover rests until morning.

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

    # A named key is not a character: it has its own virtual key code and it
    # types nothing. `ord(key.upper())` is fine for "a" and dies on "Escape",
    # which is why nothing could press Escape until now.
    NAMED_KEYS = {"Escape": 27, "Tab": 9, "Enter": 13, "Backspace": 8, "Delete": 46,
                  "ArrowLeft": 37, "ArrowUp": 38, "ArrowRight": 39, "ArrowDown": 40,
                  "Shift": 16, "Control": 17, "Alt": 18}

    def key_event(self, kind, code, key, **extra):
        named = key in self.NAMED_KEYS
        where = self.NAMED_KEYS.get(key, ord(key.upper()) if len(key) == 1 else 0)
        self.page.send("Input.dispatchKeyEvent", {
            "type": "rawKeyDown" if named and kind == "keyDown" else kind,
            "key": key, "code": code,
            "windowsVirtualKeyCode": where, "nativeVirtualKeyCode": where,
            # Only a key that types something carries text. Saying Escape
            # types the six letters of its name is how a room ends up with
            # "Escape" in its chat box.
            **({"text": key, "unmodifiedText": key} if kind == "keyDown" and not named else {}),
            **extra})

    def press_key(self, code, key, **extra):
        """One key, pressed as a person presses it. The page listens for real
        key events, so nothing here reaches into its handlers."""
        for kind in ("keyDown", "keyUp"):
            self.key_event(kind, code, key, **extra)
            time.sleep(0.05)

    def hold_key(self, code, key, seconds):
        """A key held down, as driving something needs. press_key taps it."""
        def send(kind):
            self.key_event(kind, code, key)
        send("keyDown")
        try:
            time.sleep(seconds)
        finally:
            send("keyUp")
            time.sleep(0.2)

    def press_e(self):
        self.press_key("KeyE", "e")

    def when_idle(self, timeout_s=15.0):
        """Wait until the page has no request in flight. A key pressed while
        one is answers "your hand is busy", which is the room being careful
        rather than the key being wrong."""
        return self.wait_for("!banjoRoom.world.acting && !banjoRoom.world.busy", timeout_s)

    def position(self, name):
        q = json.dumps(name)
        return self.js(f"banjoRoom.world.bodies.get({q}) ? "
                       f"banjoRoom.world.bodies.get({q}).mesh.position.toArray() : null")

    def wait_world(self, seconds, wall_s=240.0):
        """Wait until `seconds` of the room's own time have passed. CI draws a
        frame or seven a second and a step can be half a second in coming, so
        a pause in the wall clock is not a pause in the world: a machine judged
        at rest when its position had not changed for half a second of wall
        was still braking (the rover's journey, main 70859d5, 64 mm)."""
        began = self.js("banjoRoom.status().time_s")
        deadline = time.monotonic() + wall_s
        while time.monotonic() < deadline and self.js("banjoRoom.status().time_s") - began < seconds:
            time.sleep(0.2)

    def stood_still(self, program, still_m_s=0.01, over_s=2.0, tries=20):
        """Where a machine is once it has really stopped, by the ENGINE.

        Two things make this harder than it looks, and both bit this suite.

        `position` reads the drawn mesh, and CI draws a frame or seven a
        second, so two readings a moment apart can match because nothing has
        been DRAWN in between rather than because the machine has stopped. A
        program carries the engine's own `speed_m_s` and `at_m`, fresh every
        reply, and those are what this asks.

        And slow is not stopped. A machine braking to a halt passes through
        zero on the way, so one reading under the bar can be caught mid-slide
        -- which is how a rover was passed as resting and then moved 1.2 m.
        It has to be slow, and STILL slow `over_s` of room time later.
        """
        for _ in range(tries):
            if not self.wait_for(f"{program}.speed_m_s < {still_m_s}", 60):
                self.fail(f"it never came to a stop: {self.situation()}")
            self.wait_world(over_s)
            if self.js(f"{program}.speed_m_s") < still_m_s:
                return self.js(f"{program}.at_m")
        self.fail(f"it never stayed still for {over_s} s together: {self.situation()}")
        return None

    def at_rest(self, name, timeout_s=30.0):
        """Where it lies once it has stopped moving, by the wall clock.

        Prefer `settled` for anything that is coming to a halt: this one can
        answer "stopped" during a pause in the drawing. It is fine for
        something that is merely being waited on rather than decelerating.
        """
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
        self.page.send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/world?scene=world"})
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

    def aim_at(self, element_id):
        """Where to press for this control, and whether pressing there would
        reach it: the panel scrolls, so a control can be off screen, and
        anything drawn over it takes the press instead.

        Returns (x, y, why) with why empty when the point really lands on the
        control or something inside it."""
        return self.js(f"""(() => {{
          const el = document.getElementById({json.dumps(element_id)});
          if (!el) return [0, 0, "there is no such control"];
          el.scrollIntoView({{block: "center", inline: "nearest"}});
          const r = el.getBoundingClientRect();
          if (!r.width || !r.height) return [0, 0, "the control has no size"];
          const x = r.left + r.width / 2, y = r.top + r.height / 2;
          if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) {{
            return [x, y, `the control is off screen at ${{Math.round(x)}},${{Math.round(y)}}`];
          }}
          const on = document.elementFromPoint(x, y);
          if (!on) return [x, y, "nothing is at the middle of the control"];
          if (on !== el && !el.contains(on)) {{
            const what = on.id || on.className || on.tagName;
            return [x, y, `${{what}} is over it`];
          }}
          return [x, y, ""];
        }})()""")

    def when_still(self, selector):
        """Wait until what `selector` finds has stopped moving: two readings of
        where it is, a tenth of a second apart, the same."""
        where = f"(() => {{ const e = document.querySelector({json.dumps(selector)}); " \
                f"return e ? [...Object.values(e.getBoundingClientRect().toJSON())] : null; }})()"
        last = None
        for _ in range(30):
            now = self.js(where)
            if now is not None and now == last:
                return
            last = now
            time.sleep(0.1)

    def click(self, element_id):
        """A button pressed with the mouse, as a person presses it: moved over
        its middle, down and up (Input.dispatchMouseEvent).

        It checks the press will reach the control first. A click that lands
        on something else used to fail the check several assertions later,
        with nothing saying the button had moved. And it waits for the control
        to stop moving: the side panel slides in when a machine's panel opens
        it (it starts folded away), and a press mid-slide lands where the
        button was."""
        self.when_still(f"#{element_id}")
        x, y, why = self.aim_at(element_id)
        if why:
            # Once more: the panel may have been mid-layout.
            time.sleep(0.3)
            x, y, why = self.aim_at(element_id)
        self.assertFalse(why, f"cannot press {element_id}: {why}")
        self.page.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        for kind in ("mousePressed", "mouseReleased"):
            self.page.send("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left",
                                                        "clickCount": 1})
            time.sleep(0.05)

    def click_selector(self, selector):
        target = json.dumps(selector)
        self.assertTrue(self.wait_for(f"!!document.querySelector({target})"))
        xy = self.js(f"""(() => {{
          const el = document.querySelector({target}); el.scrollIntoView({{block:'center'}});
          const r=el.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
          const hit=document.elementFromPoint(x,y);
          return [x,y,el===hit || el.contains(hit)];
        }})()""")
        self.assertTrue(xy[2], f"{selector} is covered or off screen")
        for kind in ("mousePressed", "mouseReleased"):
            self.page.send("Input.dispatchMouseEvent", {"type":kind,"x":xy[0],"y":xy[1],
                "button":"left","clickCount":1})
            time.sleep(.05)

    def open_world_menu(self, section):
        if not self.js("document.querySelector('#game-menu').open"):
            # The bottom bar's Menu: the side panel's own starts folded away.
            self.click_selector(".game-bottom-tabs [data-game-menu]")
        target = f'[data-world-menu="{section}"]'
        if not self.js(f"document.querySelector({json.dumps(target)}).open"):
            self.click_selector(target + " > summary")

    def hover(self, selector):
        """The mouse moved over the middle of what `selector` finds, as a person
        moves it there to see what it offers."""
        self.assertTrue(self.wait_for(f"!!document.querySelector({json.dumps(selector)})"), f"there is no {selector}")
        x, y = self.js(f"(() => {{ const r = document.querySelector({json.dumps(selector)}).getBoundingClientRect();"
                       f" return [r.x + r.width / 2, r.y + r.height / 2]; }})()")
        self.page.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        time.sleep(0.1)

    def open_details(self):
        """The side panel, opened as a person opens it: it starts folded away
        (body.panel-away), and Details on the bottom bar slides it in. Waits
        until it is all on screen, so that a click does not land mid-slide."""
        if self.js("document.body.classList.contains('panel-away')"):
            self.click_selector("#panel-details")
        self.assertTrue(self.wait_for("!document.body.classList.contains('panel-away') && Math.abs("
                                      "document.getElementById('panel').getBoundingClientRect().right - innerWidth) < 1", 10),
                        "Details did not bring the panel out")

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

    # A way to face with a run of dry ground ahead, within the room: the world
    # has a river, and running is walking in water, so a run that went into it
    # was read as a person who cannot run (they walk 4.2 m/s since 3e2b508d and
    # run 6.8, so two paces are 13 m).
    DRY_AHEAD = ("(() => { const p = banjoRoom.camera.position;"
                 " for (let turn = 0; turn < 24; turn++) { const a = turn * Math.PI / 12, dx = Math.sin(a), dz = Math.cos(a);"
                 "   let dry = true; for (let d = 0; d <= 15 && dry; d += 0.25) { const x = p.x + d * dx, z = p.z + d * dz,"
                 "     w = banjoRoom.waterAt(x, z); dry = Math.abs(x) < 27 && Math.abs(z) < 27 &&"
                 "     !(w && w.level - banjoRoom.groundAt(x, z) > 0.01); }"
                 "   if (dry) { banjoRoom.lookAt(p.x + 6 * dx, banjoRoom.groundAt(p.x + 6 * dx, p.z + 6 * dz), p.z + 6 * dz); return true; } }"
                 " return false; })()")

    def face_dry_ground(self):
        self.assertTrue(self.js(self.DRY_AHEAD), "no way from here has fifteen metres of dry ground")

    def pace(self, run=False, seconds=1.2):
        """How fast W takes the person across the ground, in metres a second of the page's time."""
        seen = self.walk(run, seconds)
        return seen["far"] / seen["time"]

    METER = "#world-load-meter"
    MOVING = "#world-load-meter [data-movement]"

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
        # The load meter over the room says it is full, and how much (it took
        # over from the panel's Carrying line with the compact Inventory).
        self.assertTrue(self.wait_for(f"document.querySelector({self.METER!r}).textContent.includes('Full')", 10),
                        self.js(f"document.querySelector({self.METER!r}).textContent"))
        self.assertIn("80.0 / 80 kg", self.js(f"document.querySelector({self.METER!r}).textContent"))

        # Again: refused, in words, and the ground and the load are as they were.
        self.page.evaluate("document.getElementById('dig-it').click(); true")
        self.assertTrue(self.wait_for("banjoRoom.world.last && banjoRoom.world.last.tone === 'refused' && "
                                      "banjoRoom.world.last.text.includes('is all you can carry: heap some of it first')", 20),
                        f"a full load was not refused in words: {self.js('banjoRoom.world.last')}")
        self.assertAlmostEqual(kg, self.carried()[0], delta=1e-9)

        # It is in their legs: two fifths of the pace, and no running.
        self.face_dry_ground()
        loaded_walk, loaded_run = self.pace(), self.pace(run=True)
        self.assertLess(loaded_run, 1.2 * loaded_walk, "a person carrying all they can still ran")

        # A reload carries the same: the room keeps the dig as deep as it WENT.
        AReloadKeepsTheRoom.reload(self, "a reload carrying all that can be carried")
        self.assertAlmostEqual(kg, self.carried()[0], delta=1e-6,
                               msg="the room opened again dug the whole pit and carried the lot")

        # Heaped back, the hands are free and so are the legs.
        self.assertTrue(self.wait_for("!!banjoRoom.world.groundAim", 30), "the crosshair is not on the ground")
        self.heap_it_all()
        self.face_dry_ground()
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
        # About the 4.2 m/s they walk at (3e2b508d; it was 2.4); what follows is read against this.
        self.assertAlmostEqual(4.2, free, delta=0.5)

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
        self.assertTrue(self.wait_for(f"document.querySelector({self.MOVING!r}).textContent.startsWith('Wade')", 10),
                        self.js(f"document.querySelector({self.MOVING!r}).textContent"))

        # Crouched on the bed of the deepest pool their head is under, and it
        # looks it; they swim at three tenths of their pace.
        wet = stand(deep, 0.3)
        self.assertTrue(wet["head_under"], wet)
        self.assertTrue(self.js("document.body.classList.contains('head-under-water')"))
        self.assertTrue(self.wait_for(f"document.querySelector({self.MOVING!r}).textContent.startsWith('Swim')", 10),
                        self.js(f"document.querySelector({self.MOVING!r}).textContent"))
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


class ACartDrivesItselfToTheWater(PageJourney):
    """The first step of the machine world's autonomous creature
    (docs/machine-world.md, "One autonomous creature"), in the tests-cart room:
    a battery in the Workshop's cart, a motor on its back wheels, and a
    controller whose water sensor looks at the ground in front of it.

    Looking at the cart's front wheels -- which the motor does not turn -- E
    opens the cart's panel. Power On and Forward, pressed with the mouse, send
    it down the shore; its water sensor comes to see the water, and the cart
    stops on its brake with its front wheels on dry ground, the panel saying
    why. Forward again does not move it; Reverse
    backs it away."""

    def test_it_drives_down_the_shore_and_stops_at_the_waters_edge(self):
        self.page.send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/world?scene=tests-cart"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.status().scene === 'tests-cart' && "
                                      "banjoRoom.ready()", 300), "the cart room did not open")
        self.assertTrue(self.wait_for("banjoRoom.world.machines && "
                                      "(banjoRoom.world.machines.controls || []).length === 1", 60),
                        f"the room's steps do not carry the cart's machine: {self.situation()}")
        control = "banjoRoom.world.machines.controls[0]"
        # The SENSOR, not a bead drawn for it. The beads and the motor arcs
        # came off the view on the owner's word (2026-09-26: "what are the
        # blue dots on lines in front the rover, they are confusing"), and
        # what they showed is on the machine's own panel now. This line was
        # always the one that knew the truth; the bead check beside it was a
        # second look at the same fact through a picture of it.
        self.assertEqual(self.js(f"{control}.sensors.map((s) => [s.kind, s.sees])"), [["water", False]])
        # Beside the front wheels and far enough off that the crosshair is on a
        # wheel rather than the deck above it: a person stands on the ground
        # now (the gravity controller lifts an eye put lower back to 1.62 m),
        # and from 1.4 m away the deck hides the wheels.
        x, y, z = self.position("cart-2")
        ground = self.js(f"banjoRoom.groundAt({x + 4.0}, {z})")
        self.page.evaluate(f"banjoRoom.standAt({x + 4.0}, {ground + 1.62}, {z}); banjoRoom.lookAt({x}, {y}, {z}); true")
        self.assertTrue(self.wait_for("banjoRoom.world.aim && banjoRoom.world.aim.name === 'cart-2'", 10),
                        f"the crosshair is not on the front wheels: {self.situation()}")
        self.assertTrue(self.offering("Open the cart's panel"),
                        f"E on the front wheels does not open the cart's panel: {self.situation()}")
        self.press_e()
        self.assertTrue(self.wait_for("!document.getElementById('machine-panel').hidden", 10),
                        f"E did not open the cart's panel: {self.situation()}")
        start = self.position("cart")
        self.click("mp-on")
        self.assertTrue(self.wait_for(f"{control}.power === true", 15),
                        f"Power On did not reach the cart: {self.situation()}")
        self.click("mp-ahead")
        self.assertTrue(self.wait_for("banjoRoom.world.machines.motors[0].state === 'driving'", 30),
                        f"Forward did not set the motor driving: {self.situation()}")
        self.assertTrue(self.wait_for(f"({control}.condition || '').startsWith('water ahead')", 90),
                        f"the cart never stopped for the water: {self.situation()}")
        text = lambda element_id: self.js(f"document.getElementById({json.dumps(element_id)}).textContent")
        # The engine names what stopped it -- water, or a drop or step in the ground (ff1b252b).
        self.assertEqual(text("mp-condition"), "water ahead: it stopped at the edge")
        # Its water sensor's reading, named for where it sits (ff1b252b).
        self.assertIn("Front middle · water:", text("mp-measured"))
        self.assertTrue(self.wait_for(f"{control}.sensors.every((s) => s.sees)", 10),
                        "the cart's water sensor does not see the water that stopped it")
        self.wait_world(2.0)          # brought to rest on its brake
        rest = self.position("cart")
        c = self.js(control)
        wx, wy, wz = self.position("cart-2")
        wet = self.js(f"banjoRoom.waterAt({wx}, {wz})")
        print(f"\n   sent forward from its panel, it went {math.dist(start, rest):.2f} m down the shore and "
              f"stopped: the panel says {text('mp-measured')!a}", flush=True)   # ascii: a Windows console cannot print its warning sign
        self.assertGreater(math.dist(start, rest), 3.0, "it did not drive down the shore")
        self.assertTrue(c["brake"] and c["command"] == 0, f"it is not held on its brake: {c}")
        self.assertTrue(wet is None or wet["depth"] < 0.005, f"its front wheels stopped in the water: {wet}")
        # Forward again: the sensor still sees the water, so it will not go.
        self.click("mp-stop")
        self.assertTrue(self.wait_for(f"{control}.direction === 0", 15), f"Stop did not reach it: {self.situation()}")
        self.click("mp-ahead")
        self.assertTrue(self.wait_for(f"{control}.direction === 1", 15), f"Forward did not reach it: {self.situation()}")
        self.wait_world(1.5)
        self.assertLess(math.dist(self.position("cart"), rest), 0.03, "told forward at the edge, it went on")
        # Back: the sensor stops it only going forward.
        self.click("mp-back")
        self.assertTrue(self.wait_for(f"{control}.direction === -1", 15), f"Reverse did not reach it: {self.situation()}")
        self.assertTrue(self.wait_for(f"banjoRoom.world.bodies.get('cart').mesh.position.distanceTo("
                                      f"new banjoRoom.THREE.Vector3({rest[0]}, {rest[1]}, {rest[2]})) > 0.5", 30),
                        f"told back, it did not back away from the water: {self.situation()}")
        self.no_page_errors("after driving the cart to the water's edge")



class ClickingWithTheMouse(PageJourney):
    """The cursor picks, and one click does it.

    The owner, 2026-09-26: "it's hard to click on objects because I have to
    line up my + symbol, I'd like to be able to just click on it with my
    mouse." Before this the pick was cast along the camera's own forward --
    the middle of the view, always -- and the first click on a thing was
    swallowed asking for the pointer lock, so it took two.

    tests-mine has a rover, a smelter and a mill standing apart from each
    other, so there is always something to put the cursor on that the middle
    of the view is NOT on, which is the whole of what is being tested.
    """

    def mouse_to(self, x, y):
        self.page.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})

    def click_at(self, x, y):
        self.mouse_to(x, y)
        time.sleep(0.15)
        for kind in ("mousePressed", "mouseReleased"):
            self.page.send("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y,
                                                        "button": "left", "clickCount": 1})
            time.sleep(0.05)

    def on_screen(self, name):
        """Where a body is on the canvas, through the camera's own projection,
        or None when it is not in view."""
        return self.js(f"""(() => {{
            const b = window.banjoRoom, e = b.world.bodies.get({json.dumps(name)});
            if (!e) return null;
            b.camera.updateMatrixWorld();
            const p = e.mesh.position.clone().project(b.camera);
            const box = document.getElementById("stage").getBoundingClientRect();
            const x = box.left + (p.x + 1) / 2 * box.width, y = box.top + (1 - p.y) / 2 * box.height;
            if (p.z > 1 || x < box.left || y < box.top || x > box.right || y > box.bottom) return null;
            return [x, y, box.left + box.width / 2, box.top + box.height / 2];
        }})()""")

    def open_the_mine(self):
        self.page.send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/world?scene=tests-mine"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.status().scene === 'tests-mine' && "
                                      "banjoRoom.ready()", 300), "the mine room did not open")
        self.assertTrue(self.wait_for("banjoRoom.world.bodies.has('smelter')", 60),
                        f"the smelter never arrived: {self.situation()}")

    def test_the_cursor_picks_what_it_is_over_and_not_the_middle_of_the_view(self):
        self.open_the_mine()
        # Stand so that the smelter is in view but off to one side, and the
        # middle of the view is on something else or on nothing.
        x, y, z = self.position("smelter")
        self.page.evaluate(f"banjoRoom.standAt({x + 2.6}, {y + 1.4}, {z + 3.0}); "
                           f"banjoRoom.lookAt({x + 1.5}, {y + 0.2}, {z + 1.2}); true")
        time.sleep(1.0)
        where = self.on_screen("smelter")
        self.assertIsNotNone(where, f"the smelter is not in view to aim at: {self.situation()}")
        sx, sy, mx, my = where
        self.assertGreater(math.dist((sx, sy), (mx, my)), 60.0,
                           "the smelter is too near the middle for this to prove anything")
        middle_on = self.js("banjoRoom.world.aim && banjoRoom.world.aim.name")
        self.mouse_to(sx, sy)
        self.assertTrue(self.wait_for("banjoRoom.world.aim && banjoRoom.world.aim.name === 'smelter'", 15),
                        f"the cursor on the smelter did not aim at it: {self.situation()}")
        print(f"\n   the middle of the view was on {middle_on!r}; the cursor "
              f"{math.dist((sx, sy), (mx, my)):.0f} px away from it picked the smelter", flush=True)
        self.assertNotEqual("smelter", middle_on,
                            "the middle was on the smelter too, so this proved nothing")

    def test_one_click_does_what_the_side_view_marks(self):
        self.open_the_mine()
        x, y, z = self.at_rest("rover")
        self.page.evaluate(f"banjoRoom.standAt({x + 2.2}, {y + 1.3}, {z + 2.4}); "
                           f"banjoRoom.lookAt({x + 1.2}, {y + 0.1}, {z + 1.3}); true")
        time.sleep(1.0)
        where = self.on_screen("rover")
        self.assertIsNotNone(where, f"the rover is not in view: {self.situation()}")
        rx, ry, _, _ = where
        self.mouse_to(rx, ry)
        self.assertTrue(self.wait_for("banjoRoom.world.aim && banjoRoom.world.aim.name === 'rover'", 15),
                        f"the cursor is not on the rover: {self.situation()}")
        self.assertTrue(self.js("document.getElementById('machine-panel').hidden"),
                        "its panel was open before the click")
        self.click_at(rx, ry)
        self.assertTrue(self.wait_for("!document.getElementById('machine-panel').hidden", 15),
                        f"ONE click did not open the rover's panel: {self.situation()}")
        self.assertFalse(self.js("!!document.pointerLockElement"),
                         "a click took the pointer lock; nothing should ask for it now")
        print("\n   one click on the rover opened its panel, and the pointer was not taken", flush=True)

    def test_dragging_looks_around_and_does_not_act(self):
        self.open_the_mine()
        x, y, z = self.at_rest("rover")
        self.page.evaluate(f"banjoRoom.standAt({x + 2.2}, {y + 1.3}, {z + 2.4}); "
                           f"banjoRoom.lookAt({x + 1.2}, {y + 0.1}, {z + 1.3}); true")
        time.sleep(1.0)
        where = self.on_screen("rover")
        self.assertIsNotNone(where, f"the rover is not in view: {self.situation()}")
        rx, ry, _, _ = where
        facing = lambda: self.js("(() => { const v = new banjoRoom.THREE.Vector3(0, 0, -1)"
                                 ".applyQuaternion(banjoRoom.camera.quaternion); return [v.x, v.z]; })()")
        was = facing()
        # Down on the rover, drawn across it, up: a look, not a click.
        self.page.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": rx, "y": ry,
                                                    "button": "left", "clickCount": 1})
        for step in range(1, 9):
            self.page.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": rx + step * 22, "y": ry,
                                                        "button": "left", "buttons": 1})
            time.sleep(0.03)
        self.page.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": rx + 176, "y": ry,
                                                    "button": "left", "clickCount": 1})
        time.sleep(1.0)
        now = facing()
        turned = math.dist(was, now)
        print(f"\n   dragging 176 px turned the view by {turned:.3f} of a unit vector, "
              f"and opened nothing", flush=True)
        self.assertGreater(turned, 0.05, f"dragging did not look around: {was} -> {now}")
        self.assertTrue(self.js("document.getElementById('machine-panel').hidden"),
                        "a drag across the rover opened its panel; that was a look, not a click")


class LearningSomethingIsSaidWhereYouAreLooking(PageJourney):
    """A card over the world, and the next rung under the details.

    The owner asked for "achievement unlock messages when a robot or user does
    something new ... and goals that use those new skills". Both were built
    and neither could be felt: learning said itself into the room's
    conversation, where the next thing a smelter reported pushed it out of
    sight, and the ladder was drawn in the Notes tab, one of five.

    The journal starts empty here because this class keeps its own rooms
    folder, so the smelter working in front of the page TEACHES something and
    the card has to appear for it.
    """

    def machine_notes(self):
        """Each machine's brain as the server has it: its routine's notes say
        where a delivery stopped."""
        try:
            return self.page.evaluate("""(async () => {
                const w = window.banjoRoom.world, out = {};
                const token = (await fetch("/api/status").then((r) => r.json())).csrf_token;
                for (const p of (w.machines?.programs || []))
                    out[p.name] = await fetch("/api/world/rover/brain", {method: "POST",
                        headers: {"Content-Type": "application/json", "X-Banjo-Token": token},
                        body: JSON.stringify({session: w.session, program: p.name})}).then((r) => r.json());
                return JSON.stringify(out).slice(0, 6000);
            })()""", timeout=60, await_promise=True)
        except Exception as error:
            return f"(could not read the machines: {error})"

    def turn_the_machines_on(self):
        return self.page.evaluate("""(async () => {
            const w = window.banjoRoom.world;
            const token = (await fetch("/api/status").then((r) => r.json())).csrf_token;
            let seq = 500, on = [];
            for (const p of (w.machines?.programs || [])) {
                await fetch("/api/world/machine", {method: "POST",
                    headers: {"Content-Type": "application/json", "X-Banjo-Token": token},
                    body: JSON.stringify({session: w.session, program: p.id,
                                          sender: "test", seq: ++seq, power: true})});
                on.push(p.name);
            }
            return on.join(", ");
        })()""", timeout=60, await_promise=True)

    def test_a_technique_learned_shows_a_card_and_the_next_rung(self):
        self.page.send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/world?scene=tests-mine"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.status().scene === 'tests-mine' && "
                                      "banjoRoom.ready()", 300), "the mine room did not open")
        # Nothing known yet, and nothing announced on the way in: a card at
        # page load for something learned last week would be noise.
        # self.js cannot await; the notebook comes over the wire.
        known = json.loads(self.page.evaluate(
            "(async () => JSON.stringify((await fetch('/api/knowledge').then((r) => r.json()))"
            ".techniques.map((t) => t.name)))()", timeout=30, await_promise=True))
        self.assertEqual([], known, f"this journal should start empty, not {known}")
        self.assertTrue(self.js("document.getElementById('unlocked').hidden"),
                        "a card was shown before anything had been learned")

        self.turn_the_machines_on()
        # The smelter working in front of the page is what teaches it.
        self.assertTrue(self.wait_for("!document.getElementById('unlocked').hidden", 180),
                        f"nothing was said over the world when a technique was learned: {self.situation()}; "
                        f"the machines: {self.machine_notes()}")
        card = self.js("[document.getElementById('unlocked-what').textContent, "
                       "document.getElementById('unlocked-opens').textContent]")
        print(f"\n   the card said {card[0]!r} / {card[1]!r}", flush=True)
        self.assertIn("new achievement:", card[0].lower())   # the card's heading since a9ba0e3c
        # And it says what the technique opened. Read off the technique, not
        # off the ladder: a rung leaves the ladder the moment it is learned.
        self.assertTrue(card[1], "the card did not say what the new skill was for")

        # It names what the technique opened, rather than counting it: "It
        # lets you make 1 thing" is not a reason to want it. (The line under
        # the details was the next rung of the ladder until 0c18d185; it is the
        # world's one next action now, which a test room has none of, and the
        # ladder is the Workshop's Skills tree.)
        learned = json.loads(self.page.evaluate(
            "(async () => JSON.stringify((await fetch('/api/knowledge').then((r) => r.json()))"
            ".techniques))()", timeout=30, await_promise=True))
        said = next((t for t in learned if card[0].lower().endswith(t["name"].lower())), None)
        self.assertIsNotNone(said, f"the card names no technique the journal holds: {card[0]!r} against {learned}")
        opens = [o["name"] for o in said.get("opens_named") or []]
        self.assertEqual(f"Unlocked: {', '.join(opens)}" if opens else "Skill learned", card[1])

    def test_the_card_goes_away_by_itself(self):
        self.page.send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/world?scene=tests-mine"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.ready()", 300), "the room did not open")
        # Shown by hand rather than waiting for a second technique: what is
        # under test here is that it clears itself, not what raises it.
        self.page.evaluate("""(() => {
            const box = document.getElementById("unlocked");
            box.hidden = false;
            document.getElementById("unlocked-what").textContent = "You can now test things";
            return true; })()""")
        self.assertFalse(self.js("document.getElementById('unlocked').hidden"))
        # It does not cover the crosshair or the side panel: over the world,
        # near the top, clear of both.
        room = self.js("""(() => {
            const b = document.getElementById("unlocked").getBoundingClientRect();
            const p = document.getElementById("panel").getBoundingClientRect();
            const c = document.getElementById("crosshair").getBoundingClientRect();
            return [b.right <= p.left + 1, b.bottom < c.top, b.top >= 0]; })()""")
        self.assertEqual([True, True, True], room,
                         "the card is over the panel, over the crosshair, or off the top")

class YouAreAMachineInTheRoom(PageJourney):
    """There is no person: you are always looking out of something real.

    The owner, 2026-09-29, asked for the player to walk with gravity instead
    of flying, and then asked the better question -- "can we always inhabit
    the body of a robot and choose which one we want to inhabit?" So we do.
    A machine is already a body the engine simulates: it has mass, it collides
    with a crate, it falls off the lip of the adit, its wheels slip. A walking
    person would have needed every one of those written again, worse.

    God mode is the old free camera kept whole, for looking at a room rather
    than being in it.
    """

    def settings(self):
        self.open_world_menu("settings")
        return self.js("document.getElementById('settings-said').textContent")

    def get_into(self, name):
        """Choose a machine to be, from the Settings tab.

        You start as the camera: being a machine is something you do, not
        where you begin. See the note on `riding` in world.js for the six
        things that being one by default took away."""
        self.open_world_menu("settings")
        self.assertTrue(self.wait_for(
            f"!!document.querySelector('[data-rides=\"{name}\"]')", 30),
            f"{name} is not offered as something to be")
        self.js(f"(document.querySelector('[data-rides=\"{name}\"]')"
                f".scrollIntoView({{block: 'center'}}), true)")
        time.sleep(0.2)
        self.click_selector(f'[data-rides="{name}"]')
        self.assertTrue(self.wait_for(
            f"document.getElementById('settings-said').textContent.includes('You are {name}')", 15),
            f"choosing {name} did not make you it")

    def rover_at(self):
        return self.position("rover")

    def test_you_are_the_machine_and_the_eye_rides_it(self):
        self.page.send("Page.navigate",
                       {"url": f"http://127.0.0.1:{self.port}/world?scene=tests-rover"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.status().scene === 'tests-rover'"
                                      " && banjoRoom.ready()", 300), "the rover room did not open")
        self.assertTrue(self.wait_for("!!document.getElementById('pane-settings')", 30),
                        "there are no machine driving controls in Menu")
        self.assertIn("god", self.settings().lower() + " god",
                      "you should start as the camera")
        self.get_into("rover")
        # The eye is ON it, not beside it: the camera sits a fixed height over
        # the body wherever the body has got to.
        self.assertTrue(self.wait_for(
            "(() => { const r = banjoRoom.world.bodies.get('rover');"
            " return r && Math.abs(banjoRoom.camera.position.y - r.mesh.position.y - 1.1) < 0.35"
            " && Math.hypot(banjoRoom.camera.position.x - r.mesh.position.x,"
            " banjoRoom.camera.position.z - r.mesh.position.z) < 0.35; })()", 30),
            f"the eye is not on the rover: {self.js('banjoRoom.camera.position.toArray()')}")

        # AND WHAT IT SENSES, drawn rather than written. The owner: "be far
        # more visual about things, like show me what the rover can sense".
        # Five lamps laid out where the sensors sit, the ground under it and
        # ahead of it as swatches in the ground's own colours, and a battery
        # bar -- all off what the page already has, so none of it costs a
        # round trip.
        self.assertTrue(self.wait_for("!document.getElementById('settings-senses').hidden", 20),
                        "the senses are not shown")
        self.assertEqual(5, self.js("document.querySelectorAll('.sense-lamp').length"),
                         "a water sensor is missing a lamp")
        self.assertEqual(2, self.js("document.querySelectorAll('.sense-swatch').length"),
                         "the ground under it and ahead of it are two swatches")
        self.assertTrue(self.js("!!document.querySelector('.sense-swatch').title"),
                        "a swatch does not say what it is")
        self.assertTrue(self.js("!!document.querySelector('.sense-bar > i').style.width"),
                        "the battery bar has no fill")

    def test_getting_in_turns_it_on_and_it_holds_still_until_you_drive(self):
        """A machine you are sitting in does not wander off by itself.

        Both halves were wrong first time and both are worth a test. It opened
        with its power OFF, so the keys did nothing and nothing said why. And
        an ask lapses on purpose, so with the page only sending one when the
        keys CHANGED, the rover took itself back and went roaming with me
        aboard -- it turned away from the lake on its own.
        """
        self.page.send("Page.navigate",
                       {"url": f"http://127.0.0.1:{self.port}/world?scene=tests-rover"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.ready()", 300), "it did not open")
        self.get_into("rover")
        program = "banjoRoom.world.machines.programs[0]"
        self.assertTrue(self.wait_for(f"{program}.power === true", 60),
                        "getting into it did not turn it on")
        was = self.rover_at()
        time.sleep(5.0)
        now = self.rover_at()
        time.sleep(1.0)
        after = self.rover_at()
        # Two things, and they are different. It must not be UNDER WAY -- a
        # roaming program that took itself back drives at about a metre a
        # second -- and it must not have taken itself somewhere.
        crept = math.dist(now, after)
        self.assertLess(crept, 0.5,
                        f"it is driving itself with nobody at the keys: {crept:.2f} m/s, "
                        f"{now} -> {after}. Under power it does about 1 m/s; left alone "
                        f"on a slope it coasts at a few tenths, because its wheels brake "
                        f"and its caster does not.")
        self.assertLess(math.dist(was, after), 5.0,
                        f"it wandered off with nobody driving: {was} -> {after}. "
                        f"Under power it would do about 6 m in this time; rolling "
                        f"down the valley side on a braked pair of wheels and a free "
                        f"caster it does about 3.")

    def test_the_keys_drive_it_and_letting_go_stops_it(self):
        self.page.send("Page.navigate",
                       {"url": f"http://127.0.0.1:{self.port}/world?scene=tests-rover"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.ready()", 300), "it did not open")
        self.get_into("rover")
        self.assertTrue(self.wait_for("banjoRoom.world.machines.programs[0].power === true", 60))
        was = self.rover_at()
        self.hold_key("KeyW", "w", 6.0)
        drove = self.rover_at()
        self.assertGreater(math.dist(was, drove), 0.5,
                           f"W did not drive it: {was} -> {drove}")
        # It has to come to REST, which is not the same as not having gone
        # far: its wheels brake, its caster is free, and on a slope it
        # coasts. So let it settle and then measure the last second -- under
        # power that is about a metre, rolling to a stop it is a few tenths.
        time.sleep(3.0)
        settled = self.rover_at()
        time.sleep(1.0)
        rest = self.rover_at()
        crept = math.dist(settled, rest)
        self.assertLess(crept, 0.5,
                        f"it did not stop when the key came up: still moving {crept:.2f} m/s "
                        f"three seconds after, {settled} -> {rest}. Under power it does "
                        f"about 1 m/s.")

    def test_a_wheel_its_program_owns_says_so_instead_of_pretending(self):
        """The panel has to say who has the wheel.

        A machine with a program tells its wheels every step, on or off, so
        Forward on a wheel of the rover does nothing: the program puts it
        back before the next frame. That was deliberate and documented as a
        gap -- "it should be said in the panel rather than discovered" -- and
        the owner discovered it: "I don't understand all the commands for the
        rover in the side bar, they don't seem to do things they say."
        """
        self.page.send("Page.navigate",
                       {"url": f"http://127.0.0.1:{self.port}/world?scene=tests-rover"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.ready()", 300), "it did not open")
        self.assertTrue(self.wait_for("document.querySelectorAll('#machine-list button').length > 0", 60),
                        "the room listed no machines")
        self.js("(document.querySelectorAll('#machine-list button')[0].click(), true)")
        self.assertTrue(self.wait_for("!document.getElementById('machine-panel').hidden", 20),
                        "the wheel's panel did not open")
        # Not offered, because it would not happen.
        for button in ("mp-back", "mp-ahead", "mp-stop"):
            self.assertTrue(self.js(f"document.getElementById('{button}').disabled"),
                            f"{button} is still offered on a wheel its program owns")
        self.assertTrue(self.js("document.getElementById('mp-setting').disabled"),
                        "the drive setting is still offered")
        hint = self.js("document.querySelector('#machine-panel .mp-hint').textContent")
        self.assertIn("program has this wheel", hint, hint)
        # And it says where you CAN drive it from.
        self.assertIn("Menu → Drive a machine", hint, hint)

    def test_god_mode_lets_go_of_the_machine_and_flies(self):
        self.page.send("Page.navigate",
                       {"url": f"http://127.0.0.1:{self.port}/world?scene=tests-rover"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.ready()", 300), "it did not open")
        self.get_into("rover")
        self.open_world_menu("settings")
        self.assertEqual("machine",self.js("document.querySelector('#game-menu-movement select').value"))
        self.click_selector("#game-menu-movement select")
        self.press_key("KeyF", "f")
        self.press_key("Enter", "Enter")
        self.assertTrue(self.wait_for(
            "document.getElementById('settings-said').textContent.includes('Flying')", 15),
            "pressing Fly did not let go of the machine: "
            + self.js("document.getElementById('settings-said').textContent"))
        # Free of it: Space now takes the eye up, and the rover is left alone.
        above = self.js("banjoRoom.camera.position.y")
        self.hold_key("Space", " ", 2.0)
        self.assertGreater(self.js("banjoRoom.camera.position.y"), above + 0.3,
                           "Space did not take the eye up in god mode")
        # And back into it.
        self.get_into("rover")
        self.assertIn("You are rover", self.js("document.getElementById('settings-said').textContent"))


class ARoverRoamsTheShore(PageJourney):
    """The machine world's autonomous creature, its second step
    (docs/machine-world.md), in the tests-rover room: a rover with a motor on
    each back wheel, a caster in front, and a program that roams.

    E on the rover opens its program's panel -- not each wheel's -- whose only
    buttons are On and Off. On, and it roams by itself: forward, backing off and
    turning away wherever a front sensor sees water, turning back from ground
    too steep, and never with a wheel in the water. The panel says what it is
    doing and why. Off, and it stops on its brakes."""

    WHEELS = ("rover: left wheel", "rover: right wheel", "rover: caster wheel")

    def test_turned_on_it_roams_by_itself_and_turned_off_it_stops(self):
        self.page.send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/world?scene=tests-rover"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.status().scene === 'tests-rover' && "
                                      "banjoRoom.ready()", 300), "the rover room did not open")
        self.assertTrue(self.wait_for("banjoRoom.world.machines && "
                                      "(banjoRoom.world.machines.programs || []).length === 1", 60),
                        f"the room's steps do not carry the rover's program: {self.situation()}")
        program = "banjoRoom.world.machines.programs[0]"
        self.assertEqual(self.js(f"[{program}.power, {program}.doing]"), [False, "stopped"])
        # From behind and above its deck, once it has settled on its wheels.
        x, y, z = self.at_rest("rover")
        self.page.evaluate(f"banjoRoom.standAt({x + 0.3}, {y + 1.4}, {z - 1.9}); "
                           f"banjoRoom.lookAt({x}, {y + 0.05}, {z}); true")
        self.assertTrue(self.wait_for("banjoRoom.world.aim && banjoRoom.world.aim.name === 'rover'", 10),
                        f"the crosshair is not on the rover: {self.situation()}")
        self.assertTrue(self.offering("Open the rover's panel"),
                        f"E on the rover does not open its program's panel: {self.situation()}")
        self.press_e()
        self.assertTrue(self.wait_for("!document.getElementById('machine-panel').hidden", 10),
                        f"E did not open the rover's panel: {self.situation()}")
        text = lambda element_id: self.js(f"document.getElementById({json.dumps(element_id)}).textContent")
        self.assertEqual(text("mp-kind"), "Machine with a program")
        self.assertEqual(self.js("getComputedStyle(document.querySelector('#machine-panel .mp-drive')).display"),
                         "none", "a program's panel offers its wheels' directions")
        self.click("mp-on")
        self.assertTrue(self.wait_for(f"{program}.power === true", 15),
                        f"On did not reach the rover's program: {self.situation()}")
        # Forty seconds of its world, however long the page takes to draw them.
        began = self.js("banjoRoom.status().time_s")
        path, wet, seen, was = 0.0, 0.0, [], self.position("rover")
        wettest = ""      # what it was doing when a wheel was deepest
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline and self.js("banjoRoom.status().time_s") - began < 40.0:
            time.sleep(0.5)
            now = self.position("rover")
            path += math.dist(now, was)
            was = now
            for wheel in self.WHEELS:
                wx, _, wz = self.position(wheel)
                water = self.js(f"banjoRoom.waterAt({wx}, {wz})")
                if water and water.get("depth") is not None:
                    if water["depth"] > wet:
                        wet = water["depth"]
                        wettest = (f"{wheel} {wet * 1000:.0f} mm while "
                                   f"{self.js(f'{program}.doing')!r}, sensors seeing "
                                   f"{self.js(f'{program}.sensors.map(s => s.sees)')}")
            doing = self.js(f"{program}.doing")
            if not seen or seen[-1] != doing:
                seen.append(doing)
        said = self.js(program)
        print(f"\n   roamed by itself for {self.js('banjoRoom.status().time_s') - began:.0f} s: {path:.1f} m, "
              f"{said['turns']} turns away, at most {wet * 1000:.1f} mm of water under a wheel; it did {seen}",
              flush=True)
        self.assertGreater(path, 10.0, "it did not roam")
        self.assertGreaterEqual(said["turns"], 1, f"it never turned away from anything: {seen}")
        # WADING, NOT SWIMMING. The sensors trip at 80 mm, the axle of its
        # caster (the owner, 2026-10-04: a rover may wade the shallows of a
        # shore, never go into the lake), and they sit over a metre ahead of
        # the wheels; on a curved shore the front sweeps through the shallows
        # as the machine turns, and a wheel can go deeper than they read.
        # That sweep is the 47 mm this allowed over the old 3 mm sensors.
        #
        # What it must not do is get IN. Before the sensor work it put a wheel
        # 12 to 176 mm down on every single run. So: the shallows at most.
        self.assertLessEqual(wet, 0.08 + 0.047, f"a wheel went INTO the water: {wettest}")
        # The panel says why, and it is still roaming: the reason it gave a
        # moment ago is not the reason now. Ask the page to compare the two
        # itself, so both come from one instant instead of two round-trips apart.
        agrees = (f"document.getElementById('mp-condition').textContent === "
                  f"({program}.power ? ({program}.why || 'nothing in its way') : 'off')")
        self.assertTrue(self.wait_for(agrees, 10),
                        f"the panel does not say the program's own reason: it shows "
                        f"{text('mp-condition')!r} for a program that says {self.js(program + '.why')!r}")
        self.click("mp-off")
        self.assertTrue(self.wait_for(f"{program}.doing === 'stopped'", 15),
                        f"Off did not reach the rover's program: {self.situation()}")
        # Wait for it to really stop, by the engine's own reading rather than
        # by the drawing (stood_still): measured from a fixed two seconds and
        # the mesh, this saw anything from 0 to 155 mm of leftover slide.
        rest = self.stood_still(program)
        self.wait_world(1.0)
        self.assertLess(math.dist(self.js(f"{program}.at_m"), rest), 0.02,
                        "turned off, it did not stop")
        # waterAt answers null where the room has no water at all.
        ended = [self.js(f"(banjoRoom.waterAt({p[0]}, {p[2]}) || {{}}).depth || 0")
                 for p in (self.position(w) for w in self.WHEELS) if p]
        self.assertTrue(all((d or 0.0) <= 0.003 for d in ended),
                        f"it finished with a wheel in the water: {ended}")
        self.no_page_errors("after the rover roamed")


class ARoverRestsInTheSun(PageJourney):
    """Solar panels (docs/machine-world.md), in the tests-solar room: the rover's
    battery is nearly flat, and a solar panel on its deck charges it from the
    room's sun, which the page is lit from.

    Turned on from its panel, it roams until its battery is low, then rests
    where it is, on its brakes, while the sun charges it. The panel says why;
    the Machines list says what the solar panel gives and what the battery has
    taken in. Off, and it stops."""

    def test_it_rests_while_the_sun_charges_it(self):
        self.page.send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/world?scene=tests-solar"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.status().scene === 'tests-solar' && "
                                      "banjoRoom.ready()", 300), "the solar room did not open")
        self.assertTrue(self.wait_for("banjoRoom.world.machines && "
                                      "(banjoRoom.world.machines.programs || []).length === 1", 60),
                        f"the room's steps do not carry the rover's program: {self.situation()}")
        sun = self.js("banjoRoom.world.sun")
        self.assertTrue(sun and sun["elevation_deg"] == 50.0, f"the page does not have the room's sun: {sun}")
        program = "banjoRoom.world.machines.programs[0]"
        store = "banjoRoom.world.machines.stores[0]"
        x, y, z = self.at_rest("rover")
        self.page.evaluate(f"banjoRoom.standAt({x + 0.3}, {y + 1.4}, {z - 1.9}); "
                           f"banjoRoom.lookAt({x}, {y + 0.05}, {z}); true")
        self.assertTrue(self.wait_for("banjoRoom.world.aim && banjoRoom.world.aim.name === 'rover'", 10),
                        f"the crosshair is not on the rover: {self.situation()}")
        self.assertTrue(self.offering("Open the rover's panel"), f"E does not open its panel: {self.situation()}")
        self.press_e()
        self.assertTrue(self.wait_for("!document.getElementById('machine-panel').hidden", 10),
                        f"E did not open the rover's panel: {self.situation()}")
        self.click("mp-on")
        self.assertTrue(self.wait_for(f"{program}.power === true", 15),
                        f"On did not reach the rover's program: {self.situation()}")
        self.assertTrue(self.wait_for(f"{program}.doing === 'resting'", 240),
                        f"its battery never ran low enough to rest: {self.situation()}")
        text = lambda element_id: self.js(f"document.getElementById({json.dumps(element_id)}).textContent")
        self.assertEqual(text("mp-condition"), "its battery is low, so it rests while its panel charges it")
        # Wait for it to really stop, by the engine's own reading rather than
        # by the drawing (stood_still). Measured from a fixed wait and the
        # drawn mesh, this failed about a third of the time two ways at once:
        # the rover had 'moved' up to 1.2 m, which was the last of its slide,
        # and the battery had gained 48 J of the 100 wanted, because a rover
        # still rolling is a rover still drawing.
        rest = self.stood_still(program)
        charge = self.js(f"{store}.charge_j")
        doing_first, rests_first = self.js(f"{program}.doing"), self.js(f"{program}.rests")
        self.wait_world(8.0)
        doing_after, rests_after = self.js(f"{program}.doing"), self.js(f"{program}.rests")
        gained = self.js(f"{store}.charge_j") - charge
        panel = self.js("banjoRoom.world.machines.panels[0]")
        listed = self.js("document.getElementById('machine-list').innerText")
        print(f"\n   resting in the sun for 8 s: the battery gained {gained:.0f} J, the panel giving "
              f"{panel['power_w']:.1f} W of {panel['sunlight_w']:.0f} W of sun", flush=True)
        # It rests until it is charged (rest_until), so a window that straddles
        # the moment it sets off again is not a window on resting at all -- the
        # rover draws, and the battery can come out LOWER than it went in. Say
        # which it was rather than leaving a negative number to be puzzled over.
        self.assertEqual("resting", doing_first, "the window should start with it resting")
        self.assertEqual("resting", doing_after,
                         f"it set off again mid-measurement (it is {doing_after!r}), so this is "
                         f"not a reading of a resting rover charging")
        # And that it rested ONCE across the window. It rests until charged
        # and then sets off; a window that catches it going, draining and
        # coming back to rest reads both states as "resting" at its ends and
        # the battery comes out LOWER than it went in -- measured once at
        # -65 J while the panel was giving a steady 29 W.
        self.assertEqual(rests_first, rests_after,
                         f"it set off and came back to rest inside the window "
                         f"({rests_first} rests to {rests_after}), so this is not one rest")
        self.assertGreater(gained, 100.0, "resting in the sun, its battery did not charge")
        self.assertGreater(panel["power_w"], 0.0)
        self.assertIn("solar panel on rover", listed)
        self.assertIn("has taken in", listed)
        self.assertLess(math.dist(self.js(f"{program}.at_m"), rest), 0.02, "resting, it moved")
        self.click("mp-off")
        self.assertTrue(self.wait_for(f"{program}.doing === 'stopped'", 15),
                        f"Off did not reach the rover's program: {self.situation()}")
        self.no_page_errors("after the rover rested in the sun")


class ARoverRestsThroughTheNight(PageJourney):
    """A day for the sun (docs/machine-world.md), in the tests-day room: the
    room's sun goes round in four minutes, and the room begins at four in the
    afternoon. The page lights the room from where the sun is, and the Room
    tab's clock says the hour.

    Turned on, the rover roams on into the evening. The sun sets in the west,
    its light and the sky's go with it, and the solar panel says it is night;
    when the rover's battery is low it rests on its brakes and says it is
    waiting for the morning, and nothing charges it in the dark."""

    def test_the_sun_sets_and_it_rests_until_morning(self):
        self.page.send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/world?scene=tests-day"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.status().scene === 'tests-day' && "
                                      "banjoRoom.ready()", 300), "the day room did not open")
        self.assertTrue(self.wait_for("banjoRoom.world.machines && "
                                      "(banjoRoom.world.machines.programs || []).length === 1 && "
                                      "banjoRoom.world.sun && banjoRoom.world.sun.day_s > 0", 60),
                        f"the room's steps do not carry the rover's program and the sun: {self.situation()}")
        light = self.js("banjoRoom.light()")
        sun = light["sun"]
        self.assertTrue(sun["day_s"] == 240.0 and 16.0 <= sun["hour"] < 17.0,
                        f"the page does not have the room's afternoon sun: {sun}")
        clock = lambda: self.js("document.getElementById('room-clock').textContent")
        self.assertRegex(clock(), r"16:\d\d, the sun \d+° up \(a day is 240 s\)")
        self.assertGreater(light["key"], 0.5, "the afternoon sun's lamp is not lit")
        self.assertLess(light["from"][0], 0.0, "the afternoon sun does not light the room from the west")
        program = "banjoRoom.world.machines.programs[0]"
        store = "banjoRoom.world.machines.stores[0]"
        x, y, z = self.at_rest("rover")
        self.page.evaluate(f"banjoRoom.standAt({x + 0.3}, {y + 1.4}, {z - 1.9}); "
                           f"banjoRoom.lookAt({x}, {y + 0.05}, {z}); true")
        self.assertTrue(self.wait_for("banjoRoom.world.aim && banjoRoom.world.aim.name === 'rover'", 10),
                        f"the crosshair is not on the rover: {self.situation()}")
        self.assertTrue(self.offering("Open the rover's panel"), f"E does not open its panel: {self.situation()}")
        self.press_e()
        self.assertTrue(self.wait_for("!document.getElementById('machine-panel').hidden", 10),
                        f"E did not open the rover's panel: {self.situation()}")
        self.click("mp-on")
        self.assertTrue(self.wait_for(f"{program}.power === true", 15),
                        f"On did not reach the rover's program: {self.situation()}")
        # The sun sets at six, twenty seconds of the room's time in.
        self.assertTrue(self.wait_for("banjoRoom.world.sun.elevation_deg < 0", 240),
                        f"the sun never set: {self.situation()}")
        self.assertTrue(self.wait_for("banjoRoom.light().key === 0", 10), "the sun set and its lamp stayed lit")
        # The clock and the Machines list are drawn from the sun the page had
        # at the start of the step, so they are one frame behind it. At CI's
        # seven frames a second that frame is 150 ms, and demanding the words
        # on the first read failed there while passing at 60 fps here.
        self.assertTrue(self.wait_for("/\\d\\d:\\d\\d, night/.test("
                                      "document.getElementById('room-clock').textContent)", 20),
                        f"the clock does not say it is night: {clock()}")
        self.assertTrue(self.wait_for("document.getElementById('machine-list').innerText"
                                      ".includes('nothing: it is night')", 20),
                        "the panel does not say it is getting nothing: "
                        + self.js("document.getElementById('machine-list').innerText")[:200])
        self.assertTrue(self.wait_for(f"{program}.doing === 'resting'", 240),
                        f"its battery never ran low enough to rest: {self.situation()}")
        text = lambda element_id: self.js(f"document.getElementById({json.dumps(element_id)}).textContent")
        self.assertEqual(text("mp-condition"), "its battery is low and the sun is down, so it rests until morning")
        self.wait_world(2.0)          # brought to rest on its brakes
        rest = self.position("rover")
        taken = self.js(f"{store}.taken_j")
        self.wait_world(4.0)
        light = self.js("banjoRoom.light()")
        print(f"\n   resting at {clock()}: the sun {light['sun']['elevation_deg']:.0f} degrees; the sky's light "
              f"{light['sky']:.2f}, the sun's {light['key']:.2f}", flush=True)
        self.assertEqual(self.js(f"{store}.taken_j"), taken, "in the night its battery took something in")
        self.assertLessEqual(light["sky"], 0.5, "the night's sky is lit as the day's")
        self.assertLess(math.dist(self.position("rover"), rest), 0.02, "resting, it moved")
        self.click("mp-off")
        self.assertTrue(self.wait_for(f"{program}.doing === 'stopped'", 15),
                        f"Off did not reach the rover's program: {self.situation()}")
        self.no_page_errors("after the rover rested through the night")


class ABreakSaysWhatItCost(PageJourney):
    """What a break costs (docs/what-a-break-costs.md), in the tests-break room:
    an oak plank bridged between two iron piers, and a 200 mm iron ball a metre
    and a half above it.

    Nothing to do. The ball lands at about 5 m/s, above the 3.1 m/s the plank
    can take, and the room says what the break took: the energy that left with
    the bonds the lattice removed, over the crack they stand for, against what
    oak itself takes to crack and what this room charges. It is the one room
    that runs the energy-scaled law, so the charge is oak's own 1,000 J/m2."""

    CHAT = ("[...document.querySelectorAll('#chat p')].map((e) => e.textContent)"
            ".filter((t) => t.includes('J/m'))")

    def test_the_room_says_what_the_break_took(self):
        self.page.send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/world?scene=tests-break"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.status().scene === 'tests-break' && "
                                      "banjoRoom.ready()", 300), "the breaking room did not open")
        self.assertTrue(self.wait_for(f"{self.CHAT}.length > 0", 180),
                        f"the plank never broke, or the room never said what it cost: {self.situation()}")
        said = self.js(f"{self.CHAT}[0]")
        print(f"\n   {said}", flush=True)
        self.assertRegex(said, r"broke into \d+ pieces")
        self.assertRegex(said, r"It cost [\d.]+ (?:k?J) over \d+ cm. of new crack")
        self.assertIn("where oak itself takes 1,000 J/m", said)
        self.assertIn("this room charges 1,000 (energy-scaled)", said)
        self.no_page_errors("after the plank broke")


class AThrowIsAimedBeforeItIsMade(PageJourney):
    """Aiming a throw with the mouse (the owner, 2026-09-26): "if it is possible
    to throw there the line/circle should be green, if not it should be gray and
    you can't click to throw. you can also hit something like esc to just undo
    and put it back vs. throwing it."

    The engine was already foreseeing the whole throw and the page was already
    drawing it; what it would not say was whether to let go. Now the arc is
    green while the throw can be made AND the foreseen landing is where the
    crosshair is asking for, and grey when it is not -- and grey does not throw.

    In the Explore valley, because every block in it has "Set it down" authored
    on its primary button, which used to take the click before the throw ever
    saw it. A throw now goes ahead of an action that does nothing but set the
    thing down, and ahead of nothing else."""

    SCENE = "explore"
    # A block per test. These share a server and a server holds ONE room, so a
    # block one test has thrown is not where the next one would find it; the
    # valley has eight and they are identical but for what they are made of.
    # Light enough for one hand, each of them. A block the hand cannot swing at
    # all is grey wherever you point it, which is a different thing and belongs
    # to the arc's own case, not to the one about where it would land.
    BLOCKS = {"arc": "ceramic block", "grey": "oak block",
              "green": "rubber block", "escape": "aluminium block"}
    def open_valley(self):
        self.page.send("Page.navigate",
                       {"url": f"http://127.0.0.1:{self.port}/world?scene={self.SCENE}"})
        self.assertTrue(self.wait_for(f"window.banjoRoom && banjoRoom.status().scene === '{self.SCENE}'"
                                      " && banjoRoom.ready()", 300), "the valley did not open")
        # These share a server and a server holds ONE room, so the hand can
        # still have in it whatever the last journey was carrying.
        if self.js("!!banjoRoom.world.held"):
            self.page.evaluate("banjoRoom.dropIt(); true")
            self.assertTrue(self.wait_for("!banjoRoom.world.held", 60),
                            f"the hand would not let go of what was left in it: {self.situation()}")

    def take_the_block(self, which):
        block = self.BLOCKS[which]
        at = self.position(block)
        self.assertIsNotNone(at, f"there is no {block} in the valley")
        x, y, z = at
        q = json.dumps(block)
        ground = self.js(f"banjoRoom.groundAt({x}, {z + 1.0})") or 0.0
        self.page.evaluate(f"banjoRoom.standAt({x}, {ground + 1.62}, {z + 1.0}); "
                           f"banjoRoom.lookAt({x}, {y}, {z}); true")
        self.assertTrue(self.wait_for(f"banjoRoom.world.aim && banjoRoom.world.aim.name === {q}", 30),
                        f"the crosshair never found {block}: {self.situation()}")
        self.press_e()
        self.assertTrue(self.wait_for(f"banjoRoom.world.held && banjoRoom.world.held.name === {q}"
                                      " && banjoRoom.world.held.throwable", 60),
                        f"E did not pick up {block} as something throwable: {self.situation()}")
        self.assertTrue(self.when_idle(), "the hand was still busy")
        return x, y, z

    def look_at_the_ground(self, x, z, far):
        self.page.evaluate(f"banjoRoom.lookAt({x}, 0, {z - far}); true")
        time.sleep(2.2)          # the preview is asked a few times a second
        return self.js("banjoRoom.aiming()")

    def hold_the_button(self, seconds):
        for kind, buttons in (("mousePressed", 1), ("mouseReleased", 0)):
            if kind == "mouseReleased":
                time.sleep(seconds)
            self.page.send("Input.dispatchMouseEvent",
                           {"type": kind, "x": 400, "y": 350, "button": "left",
                            "buttons": buttons, "clickCount": 1})

    def press_escape(self):
        for kind in ("keyDown", "keyUp"):
            self.page.send("Input.dispatchKeyEvent",
                           {"type": kind, "key": "Escape", "code": "Escape",
                            "windowsVirtualKeyCode": 27, "nativeVirtualKeyCode": 27})
            time.sleep(0.05)

    def test_the_arc_goes_green_where_the_throw_would_land_and_grey_where_it_would_not(self):
        self.open_valley()
        x, _y, z = self.take_the_block("arc")
        near = self.look_at_the_ground(x, z, 2)
        far = self.look_at_the_ground(x, z, 18)
        print(f"\n   2 m: {near}\n  18 m: {far}", flush=True)
        # The arc is up either way. It used to vanish when the throw would not
        # work, which reads as the page having stopped rather than as an answer.
        for state in (near, far):
            self.assertTrue(state["shown"], "the arc is not up at all")
        self.assertTrue(near["onTarget"], "a throw at the ground two metres off is not on target")
        self.assertFalse(far["onTarget"], "a throw at the ground eighteen metres off is on target")
        self.assertNotEqual(near["colour"], far["colour"], "both read the same colour")
        self.no_page_errors("while aiming a throw")

    def test_grey_does_not_throw_and_says_why(self):
        self.open_valley()
        x, _y, z = self.take_the_block("grey")
        self.assertFalse(self.look_at_the_ground(x, z, 18)["onTarget"])
        # Wound all the way up and let go: the wind-up is NOT refused for being
        # off target, because the ring moves further out as it fills and that is
        # how you reach something far off. Letting go on grey is.
        self.hold_the_button(1.4)
        self.assertTrue(self.wait_for("(banjoRoom.world.use.mode === 'ready')", 30),
                        "it did not come back down after letting go on grey")
        self.assertEqual(self.js("banjoRoom.world.held && banjoRoom.world.held.name"),
                         self.BLOCKS["grey"], "it left the hand on a grey arc")
        said = self.js("banjoRoom.details().last")
        print(f"\n   {said}", flush=True)
        self.assertEqual(said["tone"], "refused")
        self.assertIn("where you are pointing", said["text"],
                      "grey for the wrong reason: this block is light enough to throw,"
                      " so the only thing wrong with it is where it would land")
        self.no_page_errors("after letting go on a grey arc")

    def test_green_throws_it(self):
        self.open_valley()
        x, _y, z = self.take_the_block("green")
        self.assertTrue(self.look_at_the_ground(x, z, 2)["onTarget"])
        self.hold_the_button(1.4)
        self.assertTrue(self.wait_for("!banjoRoom.world.held", 60),
                        f"it never left the hand: {self.js('banjoRoom.details().last')}")
        said = self.js("banjoRoom.details().last")
        print(f"\n   {said}", flush=True)
        self.assertIn("left your hand at", said["text"])
        self.no_page_errors("after a throw")

    def test_escape_puts_it_back_instead(self):
        self.open_valley()
        x, _y, z = self.take_the_block("escape")
        block = self.BLOCKS["escape"]
        # Esc is "never mind", and never a throw. Since 3e2b508d it gives the
        # person the cursor: the throw's ghost goes and the block stays in the
        # hand, neither thrown nor dropped.
        self.assertTrue(self.look_at_the_ground(x, z, 2)["onTarget"])
        self.press_escape()
        self.assertTrue(self.wait_for("banjoRoom.controls().cursorFree && !banjoRoom.world.placing", 10),
                        f"Esc did not stand the throw down: {self.situation()}")
        said = self.js("banjoRoom.details().last")
        print(f"\n   {said}", flush=True)
        self.assertNotIn("left your hand at", said["text"], "Esc threw it")
        self.assertEqual(block, self.js("banjoRoom.world.held && banjoRoom.world.held.name"), "Esc let go of it")
        # Put back instead: a click in the room takes back the view (and does
        # nothing else), and E sets it down where the copy shows.
        self.hold_the_button(0.05)
        self.assertTrue(self.wait_for("!banjoRoom.controls().cursorFree", 10), "a click did not take back the view")
        self.assertEqual(block, self.js("banjoRoom.world.held && banjoRoom.world.held.name"), "the click threw it")
        self.put_it_down(block)
        self.assertNotIn("left your hand at", self.js("banjoRoom.details().last")["text"], "it was thrown, not put back")
        self.no_page_errors("after Esc and putting it back")


class ADrawingOfTheMatterItIsMadeOf:
    """What both of the rooms below check about a hull.

    A body made of cells is drawn as the outside surface of those cells
    (playground/cellmesh.js). The page used to draw one solid cube per cell, so
    a body was a pile of blocks with every buried face of every one of them
    drawn as well. The hull is a picture of the SAME matter, and this says so in
    the only way that settles it: the volume the drawing encloses is the volume
    of the cells the engine is colliding. A hull with a hole in it, a face wound
    inside out, or a surface smoothed off the cell boundaries all fail that, and
    all three draw perfectly well.

    Exactly, while the body is still on its grid. A body that has moved -- and a
    piece just broken off something has moved a long way -- is drawn where its
    cells have got to, so its volume follows the matter rather than the grid and
    the check is that it is near, not that it is exact. Past a third of a cell
    the grid can no longer say which cell is beside which; then the mesher hands
    the body back and the page draws cubes, which are always right."""

    HULLS = """(() => {
      const r = banjoRoom, h = r.world.cellSize, out = [];
      for (const [name, held] of r.world.bodies) {
        const mesh = held.mesh;
        if (!mesh.userData.shaded) continue;
        const p = mesh.geometry.attributes.position.array;
        let volume = 0;
        for (let t = 0; t < p.length; t += 9) {
          const ax = p[t], ay = p[t+1], az = p[t+2];
          const ux = p[t+3]-ax, uy = p[t+4]-ay, uz = p[t+5]-az;
          const vx = p[t+6]-ax, vy = p[t+7]-ay, vz = p[t+8]-az;
          volume += (ax*(uy*vz - uz*vy) + ay*(uz*vx - ux*vz) + az*(ux*vy - uy*vx)) / 6;
        }
        out.push({name, cells: mesh.userData.hullCells, quads: mesh.userData.hullQuads,
                  bent: !!mesh.userData.hullBent, triangles: p.length / 9, volume,
                  matter: mesh.userData.hullCells * h * h * h});
      }
      return out;
    })()"""

    def open_world(self, scene):
        """The scene named, never whatever was left standing: a server holds
        ONE room, so a class that wants a room of its own asks for it by name
        and gets a server of its own to ask on."""
        self.page.send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/world?scene={scene}"})
        self.assertTrue(self.wait_for(f"window.banjoRoom && banjoRoom.status().scene === '{scene}'"
                                      " && banjoRoom.ready()", 300),
                        f"the {scene} room did not open")

    def wait_for_hulls(self, many=1, timeout_s=180):
        # A body's cells only travel when the set of bodies can have changed, so
        # a room that has just opened is a room whose geometry is still coming.
        self.assertTrue(self.wait_for(f"banjoRoom.hullsDrawn().hulls >= {many}", timeout_s),
                        f"fewer than {many} bodies were ever drawn as a hull:"
                        f" {self.js('banjoRoom.hullsDrawn()')}")

    def each_piece_holds_what_it_is_made_of(self, hulls):
        for piece in hulls:
            with self.subTest(piece["name"]):
                self.assertGreater(piece["cells"], 0)
                if piece["bent"]:
                    self.assertGreater(piece["volume"], 0.6 * piece["matter"])
                    self.assertLess(piece["volume"], 1.4 * piece["matter"])
                else:
                    # A LITTLE less than its cells, and never more. A hull has
                    # its edges taken off (cellmesh.BEVEL), which really does
                    # cost volume: about a sixteenth of a single cell, and far
                    # less of a bigger body, because an edge is a length and a
                    # body is a volume. What this is still looking for -- a face
                    # missing, a face wound inside out, a surface moved off the
                    # cell boundaries -- is out by a whole cell or more.
                    self.assertLessEqual(piece["volume"], piece["matter"] * 1.0001,
                                         f"{piece['name']} encloses more than it is made of")
                    self.assertGreater(
                        piece["volume"], 0.88 * piece["matter"],
                        f"{piece['name']} is drawn as {piece['volume']:.9f} m3 "
                        f"of matter and is made of {piece['matter']:.9f}")


class ARoomWhereThingsStandOnTheGround(ADrawingOfTheMatterItIsMadeOf, PageJourney):
    """The Explore valley -- one of everything the engine makes -- lit so that
    what is standing on the ground looks like it is standing on it, and with
    its lattice furniture drawn as its own surface rather than as cubes.

    Nothing in here is moving, which is the point: this is the room where a
    hull must come out exactly on the cell boundaries."""

    SCENE = "explore"

    def test_the_room_is_lit_with_a_sun_that_casts(self):
        self.open_world(self.SCENE)
        self.assertTrue(self.wait_for("banjoRoom.hullsDrawn().sunCasts", 60),
                        "the sun never began casting")
        lit = self.js("banjoRoom.hullsDrawn()")
        print(f"\n   {lit}", flush=True)
        self.assertTrue(lit["shadows"], "the shadow map is off")
        self.assertTrue(lit["environment"], "there is nothing for a polished surface to reflect")
        # ACESFilmicToneMapping. Without a tone curve a bright surface clips to
        # white and takes its shape with it.
        self.assertEqual(lit["toneMapping"], 4)
        self.no_page_errors("with the room lit")

class ThePiecesOfABreakAreDrawnAsTheyAre(ADrawingOfTheMatterItIsMadeOf, PageJourney):
    """The break room, where the plank comes apart under the falling ball.

    The pieces are the hard case and the room has both kinds in it: some still
    close enough to their grid to mesh, some thrown so far off it by the break
    that no grid can say which cell is beside which, which are handed back and
    drawn as cubes. Either way the drawing holds the matter it is made of."""

    def test_the_pieces_are_drawn_as_the_matter_they_are(self):
        self.open_world("tests-break")
        self.wait_for_hulls(2)
        hulls = self.js(self.HULLS)
        drawn = self.js("banjoRoom.hullsDrawn()")
        bent = [p["name"] for p in hulls if p["bent"]]
        print(f"\n   {drawn['hulls']} pieces as hulls ({len(bent)} of them bent),"
              f" {drawn['cubes']} thrown about too far to mesh and drawn as cubes",
              flush=True)
        self.assertGreaterEqual(len(hulls), 2)
        # NOT cheaper than cubes here, and that is worth writing down. A hull
        # saves on a big body because most of its cells are buried; a chip of
        # one or two cells has nothing buried to save, and taking the edges off
        # what little it has costs more than the cubes would have. It is still
        # a few thousand triangles for a plank in pieces, which is nothing --
        # but if this ever climbs past a few times the cubes, something has
        # gone wrong rather than merely been paid for.
        self.assertLess(drawn["triangles"], 4 * drawn["asCubes"])
        self.each_piece_holds_what_it_is_made_of(hulls)
        self.no_page_errors("after the plank broke")


class ASubstanceLooksLikeWhatItIs(PageJourney):
    """Every substance is drawn with its own grain (playground/surfaces.js).

    Each material used to be one flat colour at one roughness, so oak was a
    brown swatch and concrete a grey one and a wooden table and a concrete one
    differed only in hue. Each now carries a little noise, worked out in the
    body's OWN space so that it is solid rather than wrapped on -- a face that
    was on the outside and a face just broken open are cut from the same block.

    The way to check a surface has detail on it is to measure the detail: read
    the pixels back off the drawing buffer and look at how much they vary. A
    flat swatch lit by one sun varies smoothly and hardly at all across a small
    patch; a grained one varies several times as much. And because this is
    arithmetic on colour and roughness in a fragment shader, turning it off and
    on must leave every number the room reports exactly where it was."""

    SCENE = "explore"

    # Renders once and reads a patch out of the middle of the drawing buffer,
    # in the same turn so nothing has swapped it. `spread` is how much the
    # pixels in that patch differ from one another -- the detail on whatever
    # fills the middle of the view.
    PATCH = """(() => {
      const r = banjoRoom;
      r.renderer.render(r.scene, r.camera);
      const gl = r.renderer.getContext();
      const w = 96, h = 96;
      const px = new Uint8Array(w * h * 4);
      gl.readPixels(Math.floor((gl.drawingBufferWidth - w) / 2),
                    Math.floor((gl.drawingBufferHeight - h) / 2),
                    w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
      let sum = 0, sq = 0;
      const n = px.length / 4;
      for (let i = 0; i < px.length; i += 4) {
        const v = (px[i] + px[i + 1] + px[i + 2]) / 3;
        sum += v; sq += v * v;
      }
      const mean = sum / n;
      return { mean, spread: Math.sqrt(Math.max(0, sq / n - mean * mean)) };
    })()"""

    # What the room says about itself, which the grain must not touch.
    FACTS = """(() => [...banjoRoom.world.bodies].map(([n, h]) => [
      n, h.material, h.mesh.position.toArray().map((v) => v.toFixed(6)).join(","),
    ]).sort())()"""

    def open_valley(self):
        self.page.send("Page.navigate",
                       {"url": f"http://127.0.0.1:{self.port}/world?scene={self.SCENE}"})
        self.assertTrue(self.wait_for(f"window.banjoRoom && banjoRoom.status().scene === '{self.SCENE}'"
                                      " && banjoRoom.ready()", 300), "the valley did not open")
        # These share a server and a server holds ONE room, so the hand can
        # still have in it whatever the last journey was carrying.
        if self.js("!!banjoRoom.world.held"):
            self.page.evaluate("banjoRoom.dropIt(); true")
            self.assertTrue(self.wait_for("!banjoRoom.world.held", 60),
                            f"the hand would not let go of what was left in it: {self.situation()}")

    def look_at_a_block(self, name="oak block"):
        """Close up to one of the valley's blocks, so that it fills the middle
        of the view. The ground is not grained any more: since 59f4efec it is
        drawn with a material of its own that marks each column by what it is
        made of, so the grain is looked for on a thing the room's substances
        dress."""
        x, y, z = self.position(name)
        ground = self.js(f"banjoRoom.groundAt({x}, {z + 0.7})") or 0.0
        self.page.evaluate(f"banjoRoom.standAt({x}, {ground + 1.62}, {z + 0.7});"
                           f"banjoRoom.lookAt({x}, {y}, {z}); true")
        self.assertTrue(self.wait_for(f"banjoRoom.world.aim && banjoRoom.world.aim.name === {json.dumps(name)}", 30),
                        f"the {name} is not in the middle of the view: {self.situation()}")
        time.sleep(1.0)

    # A body the Workshop finished, and one it did not, built the same way the
    # room builds them. The finish reaches the page as part of the room's own
    # description (fracture_lab.normalise_skins), so what is set here is what a
    # room carrying a finished product hands over.
    FINISHED = """(() => {
      const was = banjoRoom.world.skins;
      banjoRoom.world.skins = new Map([["finished probe",
        { body: "finished probe", color: "#2b4a7a", roughness: 0.18, metalness: 0.85 }]]);
      const body = { name: "finished probe", material: "oak", shape: "box",
                     dimensions_m: [0.2, 0.2, 0.2] };
      const read = (m) => ({ color: "#" + m.material.color.getHexString(),
                             roughness: m.material.roughness,
                             metalness: m.material.metalness,
                             grainOf: m.material.userData.grainOf || null });
      const out = { finished: read(banjoRoom.buildMesh(body)),
                    plain: read(banjoRoom.buildMesh({ ...body, name: "plain probe" })) };
      banjoRoom.world.skins = was;
      return out;
    })()"""

    # A machine of several materials: an iron post through an oak deck. Drawn
    # with no finish, with one that names a colour, and with one that says only
    # how polished it is.
    MANY = """(() => {
      const was = banjoRoom.world.skins;
      const body = { name: "many probe", material: "oak",
        mechanical_model: "precise-rigid-v1",
        rigid_parts_local: [
          { shape: "box", center_local_m: [0, 0, 0], dimensions_m: [0.3, 0.05, 0.3],
            rotation_wxyz: [1, 0, 0, 0], material: "oak" },
          { shape: "cylinder", center_local_m: [0, 0.12, 0], dimensions_m: [0.05, 0.2, 0.05],
            rotation_wxyz: [1, 0, 0, 0], material: "iron" }] };
      const read = (m) => ({ color: "#" + m.material.color.getHexString(),
                             roughness: m.material.roughness,
                             perPart: !!m.material.vertexColors });
      const withSkin = (skin) => {
        banjoRoom.world.skins = skin ? new Map([["many probe", skin]]) : new Map();
        return read(banjoRoom.buildMesh(body));
      };
      const out = {
        bare: withSkin(null),
        painted: withSkin({ body: "many probe", color: "#2b4a7a", roughness: 0.2 }),
        polished: withSkin({ body: "many probe", roughness: 0.12 }) };
      banjoRoom.world.skins = was;
      return out;
    })()"""

    def test_a_finish_that_names_a_colour_paints_a_many_material_thing_whole(self):
        self.open_valley()
        got = self.js(self.MANY)
        print(f"\n   bare     {got['bare']}\n   painted  {got['painted']}"
              f"\n   polished {got['polished']}", flush=True)
        # Left alone, each part is drawn in the colour of what it is made of --
        # an iron post through an oak deck shows as that.
        self.assertTrue(got["bare"]["perPart"])
        self.assertEqual(got["bare"]["color"], "#ffffff")
        # A finish that names a colour means the whole thing: somebody has said
        # what this machine looks like and meant all of it.
        self.assertFalse(got["painted"]["perPart"])
        self.assertEqual(got["painted"]["color"], "#2b4a7a")
        # A finish that says only how polished it is leaves the parts their own
        # colours and changes the shine.
        self.assertTrue(got["polished"]["perPart"])
        self.assertEqual(got["polished"]["color"], "#ffffff")
        self.assertAlmostEqual(got["polished"]["roughness"], 0.12, places=4)
        self.no_page_errors("with a many-material thing finished")


    def test_a_thing_the_workshop_finished_is_drawn_with_that_finish(self):
        self.open_valley()
        got = self.js(self.FINISHED)
        print(f"\n   finished {got['finished']}\n   plain    {got['plain']}", flush=True)
        self.assertEqual(got["finished"]["color"], "#2b4a7a")
        self.assertAlmostEqual(got["finished"]["roughness"], 0.18, places=4)
        self.assertAlmostEqual(got["finished"]["metalness"], 0.85, places=4)
        # A finish must not cost the thing its grain. It did once: clone()
        # carries a material's data but not its functions, so a finished body
        # came back as a flat swatch, which is what this whole branch is about
        # not being.
        self.assertEqual(got["finished"]["grainOf"], "oak")
        # And a body nobody finished is still oak, sharing oak's material.
        self.assertEqual(got["plain"]["grainOf"], "oak")
        self.assertNotEqual(got["plain"]["color"], got["finished"]["color"])
        self.no_page_errors("with a finished thing drawn")


    def test_every_substance_in_the_room_is_drawn_with_a_grain(self):
        self.open_valley()
        self.assertTrue(self.wait_for("banjoRoom.grain().substances.length > 3", 60),
                        "hardly anything in the room was dressed")
        grain = self.js("banjoRoom.grain()")
        print(f"\n   {grain['substances']}", flush=True)
        # The valley is made of these, and the ground under them.
        for substance in ("oak", "concrete", "iron", "ground"):
            self.assertIn(substance, grain["substances"])
        self.assertEqual(grain["showing"], 1)
        # Sizes are in metres, so the across-the-grain figure is cycles per
        # metre: oak's is coarser than a fleck and finer than the hillside.
        self.assertGreater(grain["grain"]["oak"][0], grain["grain"]["ground"][0])
        self.no_page_errors("with every substance dressed")

    # Renders and keeps the patch, or -- if one is already kept -- answers how
    # far this one differs from it, grey level by grey level, and forgets it.
    # One number: the average absolute difference per pixel.
    CHANGED_BY = """(() => {
      const r = banjoRoom;
      r.renderer.render(r.scene, r.camera);
      const gl = r.renderer.getContext();
      const w = 96, h = 96;
      const px = new Uint8Array(w * h * 4);
      gl.readPixels(Math.floor((gl.drawingBufferWidth - w) / 2),
                    Math.floor((gl.drawingBufferHeight - h) / 2),
                    w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
      const before = window.__patchBefore;
      if (!before) { window.__patchBefore = px; return null; }
      window.__patchBefore = null;
      let apart = 0;
      for (let i = 0; i < px.length; i += 4)
        apart += Math.abs(px[i] - before[i]) + Math.abs(px[i + 1] - before[i + 1])
               + Math.abs(px[i + 2] - before[i + 2]);
      return apart / (px.length / 4) / 3;
    })()"""

    def test_the_grain_puts_detail_on_a_surface(self):
        """Turning the grain off and on has to change what is on the screen.

        WHAT IS MEASURED IS THE CHANGE, not how varied the picture is, and the
        history of this check is why.

        It used to read how much the pixels of a patch of ground varied among
        themselves, on the fair assumption that a flat swatch under one sun
        barely varies and a grained one does. The floor stopped being a flat
        swatch: the geology work paints it per-vertex from the beds under it,
        so it already varies by 44 before any grain, and a grain worth 0.2 on
        top cannot be seen against that. Moving to a body did not help either
        -- furniture has edges, gaps and shading in the frame, and every piece
        in the valley reads between 33 and 75 whatever the grain is doing. The
        spread of a picture is mostly its geometry.

        The difference BETWEEN two pictures is not. Render the same view with
        the grain off and with it on and compare them pixel by pixel: whatever
        the geometry, the shading and the background are, they are the same in
        both and cancel. What is left is the grain. That needs no assumption
        about what the camera is pointing at, which is what went wrong twice.

        The control below is the other half of it: the same comparison with
        nothing changed in between has to come out at zero, or the measurement
        is reading noise and would pass on anything.
        """
        self.open_valley()
        self.look_at_a_block()
        self.page.evaluate("window.__patchBefore = null; banjoRoom.showGrain(0); true")
        time.sleep(0.8)
        self.assertIsNone(self.js(self.CHANGED_BY), "the first reading is the one to compare against")
        time.sleep(0.2)
        nothing_changed = self.js(self.CHANGED_BY)
        self.page.evaluate("banjoRoom.showGrain(0); true")
        time.sleep(0.5)
        self.assertIsNone(self.js(self.CHANGED_BY), "keep a fresh one to compare against")
        self.page.evaluate("banjoRoom.showGrain(1); true")
        time.sleep(0.8)
        grain_changed = self.js(self.CHANGED_BY)
        print(f"\n   grain off to off changed {nothing_changed:.3f} grey levels a pixel;"
              f" off to on changed {grain_changed:.3f}", flush=True)
        self.assertLess(nothing_changed, 0.5,
                        "with nothing changed the picture should be the same picture")
        self.assertGreater(grain_changed, 1.0,
                           "turning the grain on should change what is on the screen")
        self.assertGreater(grain_changed, 4.0 * nothing_changed + 0.5,
                           "and change it by much more than the frame-to-frame noise")
        self.no_page_errors("with the grain on")

    def test_the_grain_changes_nothing_the_room_reports(self):
        self.open_valley()
        # Held still first. The room is RUNNING, and a bench settling on sand
        # moves seventy micrometres in the second between two readings, which
        # would drown out what this is looking for.
        self.page.evaluate("banjoRoom.world.paused = true; banjoRoom.world.lastTick = 0; true")
        self.assertTrue(self.when_idle(), "the room was still busy")
        time.sleep(0.8)
        was = self.js(self.FACTS)
        self.page.evaluate("banjoRoom.showGrain(0); true")
        time.sleep(0.5)
        self.page.evaluate("banjoRoom.showGrain(1); true")
        time.sleep(0.5)
        self.assertEqual(self.js(self.FACTS), was,
                         "something the room reports moved when the grain was turned off and on")
        self.assertGreater(len(was), 5)
        self.page.evaluate("banjoRoom.world.paused = false; banjoRoom.world.lastTick = 0; true")
        self.no_page_errors("after turning the grain off and on")


class ThreeMachinesRunWhereAPersonCanSeeThem(PageJourney):
    """A steam engine, a cannon and a rocket, in one room, on screen.

    tests/gas_pressure_tests.cpp pins the thermochemistry against a
    one-dimensional stand-in and tests/engines_room_tests.py runs the same three
    in the real engine. Neither of those looks at the PAGE, and the page is
    where the owner's rule lives: it is not done until it is watchable in 3D.
    So this opens /world?scene=tests-engines in a real browser and asks what a
    person would see.

    The sampler below runs every animation frame because the rocket's whole
    flight -- light, climb, fall -- is over in about three seconds of room time,
    and a check that polled from outside would step straight over it. For the
    same reason the jet is checked through `jetsSeen` rather than `jets`: a
    nozzle draws its plume only while it is actually pushing, which is under a
    second, so asking "is one drawing now" would be a test of timing.
    """

    SCENE = "tests-engines"

    WATCH = """(() => {
      window.__seen = { rocket: 0, piston: 0, ball: 0, breech: 0, breechAt: 0 };
      const dense = (r) => (r.p_pa / 101325) * (293 / r.t_k);
      (function watch() {
        const B = banjoRoom.world.bodies;
        const r = B.get("rocket"), p = B.get("piston"), b = B.get("ball");
        if (r) __seen.rocket = Math.max(__seen.rocket, r.mesh.position.y);
        if (p) __seen.piston = Math.max(__seen.piston, p.mesh.position.y);
        if (b) __seen.ball = Math.max(__seen.ball, b.mesh.position.x);
        const h = banjoRoom.heatState();
        const g = h && h.regions && h.regions.find((x) => x.name === "breech");
        if (g && dense(g) > __seen.breech) {
          __seen.breech = dense(g);
          __seen.breechAt = banjoRoom.status().time_s;
        }
        requestAnimationFrame(watch);
      })();
      return true;
    })()"""

    def open_room(self):
        self.page.send("Page.navigate",
                       {"url": f"http://127.0.0.1:{self.port}/world?scene={self.SCENE}"})
        self.assertTrue(
            self.wait_for(f"window.banjoRoom && banjoRoom.status().scene === '{self.SCENE}'"
                          " && banjoRoom.world.bodies.size >= 9", 300),
            "the engines room did not open")
        self.page.evaluate(self.WATCH)

    def test_all_three_machines_run_and_the_page_draws_what_they_do(self):
        self.open_room()
        # Past the cannon's primer at 3 s and the rocket's at 9 s, with room to
        # spare for the rocket to come down again.
        self.wait_world(18.0)
        seen = self.js("window.__seen")
        drawn = self.js("banjoRoom.heatDrawn()")
        start = {"piston": 1.65, "ball": 2.75, "rocket": 1.125}   # where they sit at rest
        print(f"\n   piston up to {seen['piston']:.2f} m, ball out to {seen['ball']:.2f} m,"
              f" rocket up to {seen['rocket']:.2f} m; drawn {drawn}", flush=True)

        # The steam engine: the piston climbs and the page moves it.
        self.assertGreater(seen["piston"], start["piston"] + 0.3,
                           "the piston should have been drawn climbing")
        # The cannon: the ball is thrown east, well off its rest.
        self.assertGreater(seen["ball"], start["ball"] + 1.0,
                           "the ball should have been drawn thrown down the bench")
        # The rocket: off the bench by more than any bounce would explain.
        self.assertGreater(seen["rocket"], start["rocket"] + 1.5,
                           "the rocket should have been drawn leaving the bench")

        # And the gas itself is drawn: a column in each vessel that has a
        # piston, and a jet at the one nozzle in the room.
        self.assertIn("cylinder gas", drawn["columns"], "the cylinder's steam should be drawn")
        self.assertIn("breech", drawn["columns"], "the breech's gas should be drawn")
        self.assertIn("motor", drawn["jetsSeen"], "the rocket's nozzle should have drawn a jet")
        self.assertEqual([], drawn["jets"], "and stopped drawing it once the motor was spent")
        self.no_page_errors("after the three machines ran")

    def test_a_gas_is_drawn_thicker_when_there_is_more_of_it(self):
        """The owner, 2026-09-28: gas should read as something being made rather
        than as a fixed pane of colour. A column's opacity follows the gas's own
        density -- pressure over temperature -- so the picture is of that number
        and not of the clock.

        The BREECH is where this shows, and two things about it are worth
        writing down because both surprised me.

        The cylinder does NOT thicken. It is balanced against the piston's
        weight, so as it takes on steam it holds the same pressure and GROWS
        instead: its density hardly moves (0.865 to 0.860 over eight seconds)
        and its column gets taller rather than denser.

        And the breech ends up THINNER than it started. Firing spikes it, but
        once the ball has gone the gas is left hot at nearly atmospheric
        pressure, and hot gas at atmospheric pressure is thin -- 0.38 against
        the 0.80 of cold air in the same box. So the thickening is a moment, not
        a state, and it has to be watched for frame by frame rather than
        compared before and after.

        Which is why this does not try to CATCH the spike. The spike is a few
        milliseconds of wall time and the page draws seven frames a second on
        CI, so a check that waited for it would be a check on luck. What is
        pinned instead is the link itself: every column the page is drawing is
        held against the gas the engine reported in the same breath, and its
        opacity has to be that gas's density put through the drawing's own rule.
        Get the wiring wrong -- draw a constant, read the wrong region, forget
        to update -- and this fails; a slow-moving number cannot hide it.
        """
        self.open_room()
        # The first heat block is a reply or two behind the room opening.
        self.assertTrue(self.wait_for("banjoRoom.heatState() && banjoRoom.heatState().regions"
                                      " && banjoRoom.heatState().regions.length >= 3", 120),
                        "the room never reported its gas")
        self.wait_world(5.0)          # over the cannon's primer at 3 s
        # Read the drawing and the gas in ONE turn, so nothing has moved between.
        both = self.js("""(() => {
          const drawn = banjoRoom.heatDrawn().columnOpacity;
          const gas = {};
          for (const r of banjoRoom.heatState().regions) {
            if (drawn[r.name] === undefined) continue;
            gas[r.name] = { density: (r.p_pa / 101325) * (293 / r.t_k), opacity: drawn[r.name] };
          }
          return gas;
        })()""")
        self.assertTrue(both, "the page should be drawing at least one gas column")
        for name, seen in sorted(both.items()):
            want = min(max(0.14 + 0.2 * seen["density"], 0.14), 0.75)
            print(f"\n   {name}: density {seen['density']:.3f} drawn at"
                  f" {seen['opacity']:.3f} (the rule says {want:.3f})", flush=True)
            self.assertAlmostEqual(
                seen["opacity"], want, places=3,
                msg=f"{name} is drawn at {seen['opacity']:.3f} but holds gas at "
                    f"{seen['density']:.3f} density, which the rule draws at {want:.3f}")
        self.no_page_errors("holding the drawing against the gas")


class AThingIsDrawnAsTheShapeItWasDrawnTo(PageJourney):
    """A room describes a thing as the boxes somebody laid out, and the engine
    compiles those onto its grid and collides the cells. The cells are the
    matter; the boxes are the design; and the difference between them is the
    voxelisation, up to sqrt(3)/2 of a cell.

    So a thing that is still WHOLE is drawn as the shape it was drawn to, and a
    thing that has broken is drawn from its cells -- because the moment it comes
    apart the boxes stop describing it. That second half is the important one:
    a break is exactly when a drawing that flattered the matter would start
    lying about it.

    And the drawn shape is checked against the cells before it is used: the
    design's box and the cells' box, in the body's own frame, must agree to
    within a cell and a half. That is what catches a frame worked out wrongly
    and a turn read the wrong way round, both of which draw perfectly well."""

    # Whether the plank is still being drawn as the board it was drawn to.
    PLANK = """(() => {
      const held = banjoRoom.world.bodies.get("plank");
      return held ? !!held.mesh.userData.drawnToDesign : null;
    })()"""

    def open_room(self, scene):
        self.page.send("Page.navigate",
                       {"url": f"http://127.0.0.1:{self.port}/world?scene={scene}"})
        self.assertTrue(self.wait_for(f"window.banjoRoom && banjoRoom.status().scene === '{scene}'"
                                      " && banjoRoom.ready()", 300), f"{scene} did not open")

    def test_the_valleys_furniture_is_drawn_to_its_design(self):
        self.open_room("explore")
        self.assertTrue(self.wait_for("banjoRoom.hullsDrawn().designs > 0", 120),
                        f"nothing was drawn to its design: {self.js('banjoRoom.hullsDrawn()')}")
        drawn = self.js("banjoRoom.hullsDrawn()")
        print(f"\n   {drawn}", flush=True)
        # Every piece of furniture in the valley: nothing left as cells, and
        # nothing fell all the way back to cubes.
        self.assertGreaterEqual(drawn["designs"], 5)
        self.assertEqual(drawn["hulls"], 0)
        self.assertEqual(drawn["cubes"], 0)
        # And it costs a fraction of what its cells did, because a board is a
        # board however many cells were needed to carry it.
        self.assertLess(drawn["triangles"], drawn["asCubes"] / 10)
        self.no_page_errors("with the furniture drawn to its design")


class AThingThatBreaksIsDrawnFromWhatIsLeft(AThingIsDrawnAsTheShapeItWasDrawnTo):
    """The other half, and the important one: the moment a thing comes apart,
    the shape it was drawn to stops describing it and the cells take over.

    Its own class because each of these gets a server and a server holds ONE
    room, so a class whose tests want two scenes cannot have the second."""

    def test_the_valleys_furniture_is_drawn_to_its_design(self):
        self.skipTest("this class is for the break room")

    def test_a_thing_that_breaks_goes_back_to_its_cells(self):
        # Nothing to do but watch: the ball lands above what the plank can take.
        # (A paused room is no good for catching it whole -- nothing is stepped,
        # so no body is ever drawn at all.)
        self.open_room("tests-break")
        self.assertTrue(self.wait_for("banjoRoom.hullsDrawn().hulls >= 2", 240),
                        f"the plank never came apart: {self.situation()}")
        broken = self.js("banjoRoom.hullsDrawn()")
        print(f"\n   after the break: {broken}", flush=True)
        # The pieces are drawn from what they are made of. The board it was
        # drawn to stopped describing it the moment it came apart, so nothing
        # is still being drawn to it.
        self.assertIn(self.js(self.PLANK), (None, False),
                      "a plank that has come apart is still being drawn as a whole board")
        self.assertGreaterEqual(broken["hulls"], 2)
        self.no_page_errors("after the plank broke")


class BrokenPiecesComeWithYou(PageJourney):
    """Walking near broken pieces collects them, and a piece in the hand goes
    into what you carry (the owner, 2026-09-22: "when I walk near broken pieces
    it should just collect them automatically into my inventory").

    Two things were wrong, and this pins both. The reach was measured from the
    camera, which sits at eye height, so a shard against your boots was 1.6 m
    away and nothing was ever within the 1.2 m reach: the sweep could only fire
    while crouching. And a piece in the hand was refused the bag -- "only whole
    things go in the bag", because a broken piece has no name of its own to
    come back under -- while the panel went on offering it. A piece is material
    now, and material goes into what you carry."""

    LOOSE = ("[...banjoRoom.world.bodies].filter(([n, e]) => e.shape === 'hull' && !e.anchored)"
             ".map(([n, e]) => [n, e.mesh.position.toArray()])")
    STOCK = "[...banjoRoom.world.stock].map(([what, have]) => [what, have.kg])"

    def pieces_in_the_room(self):
        """A room whose plank is whole, and then the pieces it breaks into.

        Started again rather than rejoined: the journeys that use this room
        share one world, and the first of them to walk through the pieces
        leaves the next with a floor that has already been swept. That
        failed about one run in three, and never the same test twice."""
        self.page.send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/world?scene=tests-break"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.status().scene === 'tests-break' && "
                                      "banjoRoom.ready()", 300), "the breaking room did not open")
        self.page.evaluate("document.getElementById('reset').click(); true")
        self.assertTrue(self.wait_for("banjoRoom.ready() && banjoRoom.status().time_s < 2", 120),
                        "the room did not start again")
        self.assertTrue(self.wait_for(f"{self.LOOSE}.length > 4", 120), "the plank never broke into pieces")
        return self.js(self.LOOSE)

    def when_settled(self, timeout_s=60.0):
        """Wait until the room has stopped breaking things.

        A piece that has just landed can be queued for a run of its own, and a
        piece taken up while that run is going is replaced by its pieces a
        moment later -- the hand is then empty for a reason that has nothing to
        do with what was pressed."""
        self.wait_for("!banjoRoom.world.workingOn", timeout_s)
        settled = ("(() => { const n = banjoRoom.world.bodies.size;"
                   " const same = window.__wasBodies === n; window.__wasBodies = n;"
                   " return same && !banjoRoom.world.workingOn; })()")
        self.page.evaluate("window.__wasBodies = -1; true")
        for _ in range(3):
            if not self.wait_for(settled, timeout_s):
                return False
            self.wait_world(0.6)
        return True

    def test_walking_over_them_collects_them(self):
        self.pieces_in_the_room()
        # Let them come to rest first: for the first seconds the pieces are
        # still falling and breaking again, and a position read then is not
        # where the piece will be by the time anyone stands on it.
        self.wait_world(3.0)
        loose = self.js(self.LOOSE)
        held_before = dict(self.js(self.STOCK)).get("oak", 0.0)
        # Standing on both feet, as a person does: eye height above the floor
        # the pieces are lying on. Before the fix this was the whole bug --
        # the reach was measured from the camera, so from standing height
        # nothing on the floor was ever within it.
        name, at = loose[0]
        self.page.evaluate(f"banjoRoom.standAt({at[0]}, {at[1] + 1.62}, {at[2]}); true")
        # What you carry is the claim, and it can only grow by collecting:
        # naming pieces instead made this flake, because a piece also leaves
        # the floor by breaking again.
        grew = f"Object.fromEntries({self.STOCK}).oak > {held_before} + 0.001"
        self.assertTrue(self.wait_for(grew, 45),
                        f"standing among the pieces collected nothing: {self.situation()}")
        stock = dict(self.js(self.STOCK))
        print(f"\n   standing among them, without walking: "
              + ", ".join(f"{kg * 1000:.0f} g of {what}" for what, kg in stock.items())
              + f" (was {held_before * 1000:.0f} g of oak)", flush=True)
        # And the Inventory says so: what you carry is listed by material.
        self.assertTrue(self.wait_for("!!document.querySelector('#mini-materials [data-material=\"oak\"]')", 10),
                        self.js("document.getElementById('mini-materials').innerText"))
        self.no_page_errors("after walking over the pieces")

    def test_a_piece_in_the_hand_goes_into_what_you_carry(self):
        self.pieces_in_the_room()
        # Out of a room that has finished breaking: a piece picked up while the
        # room is still working one out can be replaced by its own pieces while
        # it is in the hand.
        self.when_settled()
        loose = self.js(self.LOOSE)
        # Stand back from one, further than the sweep reaches, or it is
        # collected before the hand gets to it. Any of them will do, so each is
        # tried from either side until the crosshair is on one: a piece can be
        # behind another from one angle, and one that cannot be looked at is
        # not what this journey is about.
        name = None
        for candidate, at in loose[:8]:
            for aside in (2.0, -2.0):
                # Looked at once they are standing: a person stands on the floor
                # now (the gravity controller), which settles the eye a few
                # centimetres from where it was put -- and a line aimed from
                # where it was put passes over a piece this small.
                self.page.evaluate(f"banjoRoom.standAt({at[0] + aside}, {at[1] + 1.62}, {at[2] - 2.0}); true")
                self.page.evaluate("new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(() => "
                                   "requestAnimationFrame(done))))", await_promise=True, timeout=30)
                self.page.evaluate(f"banjoRoom.lookAt({at[0]}, {at[1]}, {at[2]}); true")
                if self.wait_for("banjoRoom.world.aim && banjoRoom.world.aim.name === "
                                 f"{json.dumps(candidate)}", 5):
                    name = candidate
                    break
            if name:
                break
        self.assertIsNotNone(name, f"the crosshair reached none of the pieces: {self.situation()}")
        self.press_e()
        self.assertTrue(self.wait_for(f"banjoRoom.held() && banjoRoom.held().name === {json.dumps(name)}", 15),
                        f"E did not take hold of the piece: {self.situation()}")
        # The panel says what the key really does with a piece, and then it
        # does it.
        offered = self.js("banjoRoom.details().rows.map((r) => r[1]).join(' / ')")
        self.assertIn("sweep it up into what you carry", offered)
        before = dict(self.js(self.STOCK)).get("oak", 0.0)
        self.when_idle()
        self.press_key("KeyQ", "q")
        self.assertTrue(self.wait_for(f"!banjoRoom.held() && Object.fromEntries({self.STOCK}).oak > {before}", 20),
                        f"the piece did not go into what you carry: {self.situation()}")
        said = self.js("document.getElementById('details-last-text').textContent")
        print(f"\n   with a piece in hand, Q said: {said}", flush=True)
        self.assertNotIn("only whole things", said)
        self.no_page_errors("after collecting a broken piece")


class WhatIsOfferedIsDone(PageJourney):
    """What the panel offers, the room does.

    The panel lists what a key will do with the thing you are looking at or
    holding, and the room can still refuse it: a broken piece was offered "put
    it in your bag" and answered "only whole things go in the bag" (the owner,
    2026-09-22). An offer that is refused is worse than no offer, because the
    person cannot tell a rule from a fault.

    So: in a room of authored things and one of broken pieces, take each thing
    the bag key is offered for, press it, and read what the room said back.
    Nothing is allowed to come back as a refusal."""

    # world.last is what the panel's Last line shows, with the tone the page
    # gave it: "did" or "refused".
    LAST = "banjoRoom.world.last || null"

    def offers_the_bag(self):
        return "put it in your bag" in self.js(
            "banjoRoom.details().rows.map((r) => r[1]).join(' / ')") or "sweep it up into what you carry" in self.js(
            "banjoRoom.details().rows.map((r) => r[1]).join(' / ')")

    def try_the_bag(self, name, targets):
        """Aim at each target, and where the bag key is offered, press it."""
        tried, refused = 0, []
        for target in targets:
            where = self.position(target)
            if not where:
                continue
            self.page.evaluate(f"banjoRoom.standAt({where[0] + 1.6}, {where[1] + 1.62}, {where[2] - 1.6}); "
                               f"banjoRoom.lookAt({where[0]}, {where[1]}, {where[2]}); true")
            if not self.wait_for(f"banjoRoom.world.aim && banjoRoom.world.aim.name === {json.dumps(target)}", 8):
                continue
            if not self.offers_the_bag():
                continue
            self.page.evaluate("banjoRoom.world.last = null; true")
            self.when_idle()
            self.press_key("KeyQ", "q")
            tried += 1
            said = None
            for _ in range(40):
                said = self.js(self.LAST)
                if said:
                    break
                time.sleep(0.2)
            if said and said.get("tone") == "refused":
                refused.append(f"{target}: {said.get('text')}")
        return tried, refused

    def test_the_bag_key_is_never_offered_and_then_refused(self):
        self.page.send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/world?scene=tests-break"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.status().scene === 'tests-break' && "
                                      "banjoRoom.ready()", 300), "the breaking room did not open")
        # Started again: the journeys that use this room share one world.
        self.page.evaluate("document.getElementById('reset').click(); true")
        self.assertTrue(self.wait_for("banjoRoom.ready() && banjoRoom.status().time_s < 2", 120),
                        "the room did not start again")
        self.assertTrue(self.wait_for("[...banjoRoom.world.bodies].filter(([n, e]) => e.shape === 'hull')"
                                      ".length > 4", 120), "the plank never broke into pieces")
        self.wait_world(3.0)
        pieces = self.js("[...banjoRoom.world.bodies].filter(([n, e]) => e.shape === 'hull' && !e.anchored)"
                         ".map(([n]) => n).slice(0, 5)")
        tried, refused = self.try_the_bag("tests-break", pieces)
        print(f"\n   broken pieces: the bag key was offered for {tried} of them", flush=True)
        self.assertEqual([], refused, "offered, then refused")
        self.no_page_errors("after trying the bag on broken pieces")


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


def kg_of(said: str) -> float:
    """The kilograms behind what a slot reads: "12.4 kg", "860 g", "402 kg"."""
    number = float(said.split()[0])
    return number / 1000.0 if said.endswith(" g") else number


class TheMineShowsWhatEachThingHolds(PageJourney):
    """Every holder in a room, and what is in it, in the side view as it moves
    (docs/machine-world.md, "Raw materials into finished goods").

    The owner, 2026-09-26: "there are too many windows open, have it open on
    the right under the chat. also have slots for anything that can hold
    things and show the material being held it is so we can see it happen more
    as it goes."

    The tests-mine room is the whole chain: a rover with a hopper digs copper
    ore out of a vein, docks at the smelter, the smelter makes copper of it, a
    drone flies the copper to the mill, and the mill draws wire onto the
    Workshop's rack. Its four machines open off.

    This opens a machine's panel the way a person does -- the Room tab's own
    Controls button -- and checks the panel is IN the side view under the
    conversation rather than floating over the room; switches all four on from
    it; and then watches the slots for a minute of the room's own time: the
    vein going down, the rover's hopper filling with ore and emptying into the
    smelter, and every heap along the chain taking what the one before it
    gave, with a slot lighting up as each one moves.
    """

    MACHINES = ("rover", "smelter", "mill", "drone")
    HOPPER = "Rover: its hopper"
    VEIN = "Copper Vein"

    def holds(self, which="holds-list"):
        return self.js(f"banjoRoom.holds({json.dumps(which)})")

    @staticmethod
    def holder(shown, name):
        return next((h for h in shown["holders"] if h["name"] == name), None)

    def much(self, shown, name, what):
        """What a holder's slot for a substance reads, in kilograms; 0.0 when
        it has no slot for it."""
        for slot in (self.holder(shown, name) or {}).get("slots") or []:
            if slot["what"] == what:
                return kg_of(slot["much"])
        return 0.0

    def click_where(self, selector):
        """A button pressed with the mouse, found by what it is rather than by
        an id: the Controls buttons are one per machine and have none. Scrolled
        into the panel's view first -- the Room tab's list scrolls -- and once
        it has stopped moving: the side panel slides in when a machine's panel
        opens it."""
        self.when_still(selector)
        where = self.js(
            f"(() => {{ const e = document.querySelector({json.dumps(selector)}); if (!e) return null;"
            f" e.scrollIntoView({{block: 'center'}}); const r = e.getBoundingClientRect();"
            f" return [r.left + r.width / 2, r.top + r.height / 2]; }})()")
        self.assertIsNotNone(where, f"nothing on the page matches {selector}")
        x, y = where
        self.page.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        for kind in ("mousePressed", "mouseReleased"):
            self.page.send("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left",
                                                        "clickCount": 1})
            time.sleep(0.05)

    def switch_on(self, machine):
        self.click_where(f'#machine-list button[aria-label="Control {machine}"]')
        self.assertTrue(self.wait_for("!document.getElementById('machine-panel').hidden", 10),
                        f"Controls did not open {machine}'s panel")
        self.assertTrue(self.wait_for(f"document.getElementById('mp-name').textContent.toLowerCase() === "
                                      f"{json.dumps(machine)}", 10),
                        "the panel opened on "
                        + repr(self.js("document.getElementById('mp-name').textContent")))
        self.click_where("#mp-on")
        self.assertTrue(self.wait_for("banjoRoom.world.machines.programs.some((p) => p.name === "
                                      f"{json.dumps(machine)} && p.power === true)", 20),
                        f"On did not reach {machine}: the panel said "
                        + repr(self.js("document.getElementById('mp-ack').textContent")))

    def test_the_chain_shows_the_ore_moving_from_holder_to_holder(self):
        self.page.send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/world?scene=tests-mine"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.status().scene === 'tests-mine' && "
                                      "banjoRoom.ready()", 300), "the mine did not open")
        self.assertTrue(self.wait_for("banjoRoom.world.machines && "
                                      "(banjoRoom.world.machines.programs || []).length === 4", 60),
                        f"the room's steps do not carry its four programs: {self.situation()}")
        self.page.evaluate("banjoRoom.showTab('room'); true")

        # -- every holder is on the page before anything has run ---------------
        at_open = self.holds()
        self.assertTrue(at_open["shown"], "the Room tab says nothing about what anything holds")
        self.assertEqual([h["name"] for h in at_open["holders"]],
                         ["Rover: its hopper", "Drone: its hopper", "Smelter Intake", "Smelter Output",
                          "Mill Intake", "Workshop Rack", "Copper Vein"],
                         "the room's holders are not all there, in the room's own order")
        self.assertEqual([s["what"] for s in self.holder(at_open, "Smelter Intake")["slots"]], [None],
                         "an empty heap does not say it is empty")
        self.assertEqual(self.much(at_open, self.VEIN, "copper ore"), 400.0,
                         "the vein does not say what is in the ground")
        # The bar, for a holder that has a full: the browser writes back what
        # the page set, tidied ("0.0%" comes back "0%"), so read the number.
        full = lambda name: float(self.holder(at_open, name)["full"].rstrip("%"))
        self.assertEqual(full(self.HOPPER), 0.0, "an empty hopper's bar is not empty")
        self.assertEqual(full(self.VEIN), 100.0, "an untouched vein's bar is not full")
        self.assertIsNone(self.holder(at_open, "Smelter Intake")["full"],
                          "a heap has no capacity, so it must have no bar")

        # -- the panel is in the side view, under the conversation -------------
        self.switch_on("rover")
        self.assertEqual(self.js("document.getElementById('machine-panel').parentElement.id"), "panel",
                         "the machine panel is not in the side view")
        self.assertTrue(self.js("document.body.classList.contains('machine-open')"))
        where = self.js("(() => { const p = document.getElementById('machine-panel').getBoundingClientRect(),"
                        " t = document.getElementById('talk').getBoundingClientRect(),"
                        " d = document.getElementById('details').getBoundingClientRect();"
                        " return {left: p.left, width: p.width, under_chat: p.top >= t.bottom - 1,"
                        " over_details: p.bottom <= d.top + 1, inner: innerWidth}; })()")
        self.assertTrue(where["under_chat"], f"the panel is not under the conversation: {where}")
        self.assertTrue(where["over_details"], f"the panel is not above what you look at: {where}")
        self.assertGreater(where["left"], where["inner"] - 400,
                           f"the panel is not in the right-hand column: {where}")
        self.assertGreater(where["width"], 100, f"the panel has no room: {where}")
        # And it says what THIS machine holds: its hopper, and the heap behind
        # each of its mouths.
        mine = self.holds("mp-holds-list")
        self.assertTrue(mine["shown"], "the machine's panel says nothing about what it holds")
        self.assertEqual([h["name"] for h in mine["holders"]], ["Rover: its hopper"],
                         "the rover's panel does not show its hopper")
        self.assertIn("Rover Store", mine["holders"][0]["of"],
                      f"the hopper's card does not say which mouth it is behind: {mine['holders'][0]['of']}")

        for machine in self.MACHINES[1:]:
            self.page.evaluate("banjoRoom.showTab('room'); true")
            self.switch_on(machine)
            if machine == "smelter":
                # A machine with two mouths shows the heap behind each, and
                # which way the goods go through it.
                two = self.holds("mp-holds-list")["holders"]
                self.assertEqual([h["name"] for h in two],
                                 ["Smelter Intake: smelter intake", "Smelter Outlet: smelter output"],
                                 "the smelter's panel does not show the heap behind each of its mouths")
                self.assertTrue(two[0]["of"].startswith("goods in"), two[0]["of"])
                self.assertTrue(two[1]["of"].startswith("goods out"), two[1]["of"])

        # -- watch the material move -------------------------------------------
        began = self.js("banjoRoom.status().time_s")
        most = {}          # holder, substance -> the most it was ever seen holding
        lit = {}           # holder, substance -> the ways it was seen lighting up
        vein = [self.much(at_open, self.VEIN, "copper ore")]
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline and self.js("banjoRoom.status().time_s") - began < 90.0:
            shown = self.holds()
            for holder in shown["holders"]:
                for slot in holder["slots"]:
                    if slot["what"] is None:
                        continue
                    key = (holder["name"], slot["what"])
                    most[key] = max(most.get(key, 0.0), kg_of(slot["much"]))
                    if slot["moved"]:
                        lit.setdefault(key, set()).add(slot["moved"])
            vein.append(self.much(shown, self.VEIN, "copper ore"))
            if self.much(shown, "Workshop Rack", "copper wire") > 0.0:
                break
            time.sleep(0.25)
        ran = self.js("banjoRoom.status().time_s") - began
        print(f"\n   in {ran:.0f} s of the mine: "
              + ", ".join(f"{name} held {kg:g} kg of {what}" for (name, what), kg in sorted(most.items()))
              + f"; the vein went {vein[0]:g} -> {vein[-1]:g} kg; slots lit: "
              + ", ".join(f"{name}/{what} {'+'.join(sorted(ways))}" for (name, what), ways in sorted(lit.items())),
              flush=True)

        # The vein emptied into the rover, the rover emptied into the smelter,
        # and what the smelter made went on down the chain.
        self.assertLess(vein[-1], vein[0], "nothing came out of the ground")
        self.assertGreater(most.get((self.HOPPER, "copper ore"), 0.0), 1.0, "the rover's hopper never held ore")
        self.assertGreater(most.get((self.HOPPER, "sand and soil"), 0.0), 1.0,
                           "the rover's hopper never held the spoil it digs with the ore")
        self.assertGreater(most.get(("Smelter Intake", "copper ore"), 0.0), 1.0,
                           "the ore never reached the smelter's heap")
        self.assertGreater(most.get(("Smelter Output", "copper"), 0.0), 0.0, "the smelter never made copper")
        self.assertGreater(most.get(("Workshop Rack", "copper wire"), 0.0), 0.0,
                           "no wire ever reached the Workshop's rack")
        # A slot that moved lights up: this is what makes the chain watchable.
        self.assertIn("up", lit.get((self.HOPPER, "copper ore"), set()),
                      f"the hopper's slot never lit as it filled: {sorted(lit)}")
        self.assertTrue(any("down" in ways for ways in lit.values()),
                        f"nothing ever lit as it emptied: {sorted(lit)}")
        self.no_page_errors("after the mine ran")

        # Closed, the panel goes and the column has its floor back.
        self.click("mp-close")
        self.assertTrue(self.wait_for("document.getElementById('machine-panel').hidden && "
                                      "!document.body.classList.contains('machine-open')", 10),
                        "closing the panel left it open")


class TheBottomOfThePanelCanBeReached(PageJourney):
    """A short window must not put the panel's own buttons out of reach.

    Found by a check that could not press the Fly button: "the control is off
    screen at 638,471". The panel is as tall as the window and its contents
    are not, and it had `overflow: visible` -- so on a short window the
    Settings tab's buttons fell below the fold with nothing to scroll.
    Measured at 960x460: the panel wanted 500 px and the button sat at 473.

    Not a checking artefact. A laptop, or a browser with a lot of chrome,
    gives a person the same window.
    """

    def test_the_settings_buttons_are_reachable_on_a_short_window(self):
        self.page.send("Page.navigate",
                       {"url": f"http://127.0.0.1:{self.port}/world?scene=tests-rover"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.ready()", 300),
                        "the room did not open")
        self.assertTrue(self.wait_for("!!document.getElementById('pane-settings')", 30),
                        "there are no machine driving controls in Menu")
        self.open_world_menu("settings")
        # The panel scrolls when it needs to, rather than hiding its own foot.
        panel = self.js("""JSON.stringify((() => {
          const p = document.getElementById('panel');
          return {taller: p.scrollHeight > p.clientHeight,
                  overflow: getComputedStyle(p).overflowY};
        })())""")
        self.assertIn(json.loads(panel)["overflow"], ("auto", "scroll"),
                      f"the panel cannot scroll, so its foot is unreachable: {panel}")
        # And the button can actually be pressed -- aim_at scrolls to it and
        # checks the press would land on it.
        self.click_selector("#game-menu-movement select")


class ClickingSomethingKeepsIt(PageJourney):
    """A click says THAT ONE, and the panel stays about it.

    Two owner reports on the same day. First: "it was like i was flying left
    when I hit ctrl+A to try to select all it started doing it" -- a key
    pressed as part of a browser shortcut was being taken as a held control,
    and the A never came back up. Second: "if I do click on something it would
    be good to highlight the thing i click on on the page and leave it in the
    right nav until I click on something else", and for land, "show me what it
    is composed of, a mineral and if so how much".
    """

    def open_rover_room(self):
        self.page.send("Page.navigate",
                       {"url": f"http://127.0.0.1:{self.port}/world?scene=tests-rover"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.status().scene === 'tests-rover'"
                                      " && banjoRoom.ready()", 300), "the rover room did not open")

    def keys_down(self):
        return self.js("JSON.stringify(banjoRoom.keysDown())")

    def test_a_key_held_with_ctrl_is_the_browsers_and_not_the_rooms(self):
        self.open_rover_room()
        where = "banjoRoom.camera.position"
        before = self.js(f"[{where}.x, {where}.z].map(v => +v.toFixed(3)).join()")
        # Ctrl+A, as a browser sends it when somebody tries to select all.
        self.js("(dispatchEvent(new KeyboardEvent('keydown', "
                "{code:'KeyA', key:'a', ctrlKey:true, bubbles:true})), true)")
        time.sleep(1.2)
        self.assertEqual(self.keys_down(), "[]",
                         "a key chorded with ctrl was taken as a held control")
        after = self.js(f"[{where}.x, {where}.z].map(v => +v.toFixed(3)).join()")
        self.assertEqual(before, after, "ctrl+A flew the camera sideways")
        # And it left nothing stuck: the camera is still where it was a
        # second later, with no keyup ever sent for that A.
        time.sleep(1.0)
        self.assertEqual(self.js(f"[{where}.x, {where}.z].map(v => +v.toFixed(3)).join()"), after,
                         "the camera kept drifting after a chorded key")

    def test_a_plain_key_still_walks(self):
        """The fix must not be 'the key does nothing now'."""
        self.open_rover_room()
        where = "banjoRoom.camera.position"
        before = [float(v) for v in self.js(f"[{where}.x, {where}.z].join()").split(",")]
        self.hold_key("KeyA", "a", 1.5)
        after = [float(v) for v in self.js(f"[{where}.x, {where}.z].join()").split(",")]
        moved = math.hypot(after[0] - before[0], after[1] - before[1])
        self.assertGreater(moved, 0.3, f"A no longer strafes: it moved {moved:.2f} m")

    def test_clicking_a_machine_keeps_it_in_the_panel_and_draws_a_box_round_it(self):
        self.open_rover_room()
        self.js("(banjoRoom.pick('rover'), true)")
        self.assertTrue(self.wait_for("!document.getElementById('picked').hidden", 15),
                        "clicking the rover showed nothing")
        # The panel starts folded away; Details shows what was clicked.
        self.open_details()
        said = self.js("document.getElementById('picked').innerText")
        self.assertIn("Rover", said)
        # The battery is a picture with a percentage, not a sentence.
        self.assertTrue(self.js("!!document.querySelector('#picked .battery')"),
                        "no battery symbol")
        self.assertRegex(said, r"\d+%", "the battery does not say how full it is")
        # And the words about the same battery are gone: it is said once.
        self.assertNotIn("a battery,", said, "the battery is written out as well as drawn")
        # A box round it in the room, following it.
        self.assertTrue(self.wait_for("banjoRoom.picked().outlined", 10),
                        "nothing was drawn round what was clicked")
        # It stays about the rover even though the view has moved on.
        self.js("(banjoRoom.lookAt(20, 0, 20), true)")
        time.sleep(1.0)
        self.assertEqual(self.js("banjoRoom.picked().name"), "rover",
                         "looking away let go of what was clicked")
        self.assertTrue(self.js("document.getElementById('details').hidden"),
                        "the hovering view is still up beside the pinned one")

    def test_clicking_land_says_what_it_is_made_of(self):
        self.open_rover_room()
        self.js("(banjoRoom.pickGround(-4.8, 0, 4.1), true)")
        self.assertTrue(self.wait_for("!document.getElementById('picked').hidden", 15),
                        "clicking the ground showed nothing")
        # The panel starts folded away, and the beds are under their own
        # disclosure in it (f978d1af): Details, then Ground layers.
        self.open_details()
        self.click_selector("#picked details > summary")
        self.assertTrue(self.wait_for("document.querySelector('#picked details').open", 5), "Ground layers did not open")
        # And it stays open while the card is built again: walking changes how far away it says it is.
        self.js("(banjoRoom.standAt(banjoRoom.camera.position.x + 0.5, banjoRoom.camera.position.y, banjoRoom.camera.position.z), true)")
        time.sleep(1.0)
        self.assertTrue(self.js("document.querySelector('#picked details').open"), "Ground layers closed when the card was built again")
        beds = json.loads(self.js(
            "JSON.stringify([...document.querySelectorAll('#picked .pk-bed')]"
            ".map(b => b.innerText))"))
        self.assertTrue(beds, "the ground has no beds in the panel")
        # Every bed says what it is and how thick, and each is drawn tall
        # enough to read -- a 60 cm bed under 30 m of rock used to be 7 px.
        for said in beds:
            self.assertRegex(said, r"\d+ (cm|m)\b", f"a bed with no thickness: {said!r}")
        tall = json.loads(self.js(
            "JSON.stringify([...document.querySelectorAll('#picked .pk-bed')]"
            ".map(b => b.getBoundingClientRect().height))"))
        self.assertGreater(min(tall), 12, f"a bed too thin to read: {tall}")
        self.assertIn("ore", self.js("document.getElementById('picked').innerText"),
                      "the panel says nothing about ore either way")

    def test_escape_frees_cursor_and_preserves_the_selected_item(self):
        self.open_rover_room()
        self.js("(banjoRoom.pick('rover'), true)")
        self.assertTrue(self.wait_for("banjoRoom.picked().name === 'rover'", 15))
        self.press_key("Escape", "Escape")
        self.assertTrue(self.wait_for("banjoRoom.controls().cursorFree", 10))
        self.assertEqual("rover",self.js("banjoRoom.picked().name"))


class TheHotListTakesWhatYouPutInIt(PageJourney):
    """The owner: "you can then move items from your inventory into your hot
    list which are the 10 slots you can see when in the world."

    Which slot a thing landed in used to be the bag's own choice, and the row
    was `pointer-events: none` -- something to look at, not to use.

    ONE check, because it is one journey and because the class shares a room:
    the harness keeps it between checks ("This is the room as you left it"),
    so four checks each wanting something on the floor was four checks
    fighting over one room, and the last of them found a single stone.

    The drop itself is not dispatched -- an HTML5 drag is not something CDP
    makes the way a person does -- so the check drives the call the drop
    makes, `putInSlot`, and reads the row's own properties to show it really
    is a target.
    """

    def bag(self):
        return json.loads(self.js(
            "JSON.stringify((banjoRoom.world.inventory.stowed || []).map(x => x && x.name))"))

    def loose_things(self):
        """What is on the floor, light enough to carry and not already yours,
        lightest first. Asked of the room as it is now."""
        return json.loads(self.js("""JSON.stringify((() => {
          const mine = new Set((banjoRoom.world.inventory.stowed || [])
            .filter(Boolean).map(x => x.name));
          const held = banjoRoom.held();
          if (held) mine.add(held.name);
          return [...banjoRoom.world.bodies.entries()]
            .filter(([name, b]) => !mine.has(name) && !b.anchored
                                   && b.mass > 0 && b.mass < 20)
            .sort((a, b) => a[1].mass - b[1].mass)
            .map(([name]) => name);
        })())"""))

    def stow(self, name):
        """Look at a thing, take it, put it in the bag -- as a person does.

        Standing at GROUND level with the eye 1.62 m up and a metre back, and
        waiting for the crosshair to land on it: guessing the eye height from
        the object's own y put the camera inside the table."""
        where = self.position(name)
        if where is None:
            return False
        x, y, z = where
        q = json.dumps(name)
        for back in (1.0, 1.4, 0.7):
            ground = self.js(f"banjoRoom.groundAt({x}, {z + back})") or 0.0
            self.js(f"(banjoRoom.standAt({x:.3f}, {ground + 1.62:.3f}, {z + back:.3f}),"
                    f" banjoRoom.lookAt({x:.3f}, {y:.3f}, {z:.3f}), true)")
            if self.wait_for(f"banjoRoom.world.aim && banjoRoom.world.aim.name === {q}", 10):
                break
        else:
            return False
        self.when_idle()
        self.press_e()
        if not self.wait_for(f"banjoRoom.held() && banjoRoom.held().name === {q}", 20):
            return False
        self.when_idle()
        held = self.js("(banjoRoom.world.inventory.stowed || []).filter(Boolean).length")
        self.press_key("KeyQ", "q")
        return self.wait_for(
            "(banjoRoom.world.inventory.stowed || []).filter(Boolean).length"
            f" > {held}", 20)

    def test_a_thing_goes_to_the_slot_you_put_it_in_and_stays_there(self):
        self.page.send("Page.navigate",
                       {"url": f"http://127.0.0.1:{self.port}/world?scene=tests-carry"})
        self.assertTrue(self.wait_for("window.banjoRoom && banjoRoom.ready()", 300),
                        "the carry room did not open")
        # The bodies arrive after ready(), and their masses later still.
        self.assertTrue(self.wait_for(
            "[...banjoRoom.world.bodies.values()].some(b => b.mass > 0 && b.mass < 20)", 120),
            "the room never reported anything light enough to pick up")

        got = []
        for name in self.loose_things():
            if self.stow(name):
                got.append(name)
            if len(got) >= 2:
                break
        self.assertGreaterEqual(len(got), 2,
                                f"only {got} reached the bag: {self.bag()}")

        # INTO THE SLOT YOU CHOSE. This is the call the drop makes.
        was = sorted(x for x in self.bag() if x)
        # Whatever the bag actually holds, by its own name: a body is not an
        # item, and aiming at "mace head" puts a "mace" in the bag.
        first = next(x for x in self.bag() if x)
        mine = json.dumps(first)
        ident = self.js(f"(banjoRoom.world.inventory.stowed.find("
                        f"x => x && x.name === {mine}) || {{}}).id")
        self.assertTrue(ident, f"{first} is not in the bag: {self.bag()}")
        self.js(f"(banjoRoom.putInSlot({json.dumps(ident)}, 6), true)")
        self.assertTrue(self.wait_for(
            f"((banjoRoom.world.inventory.stowed[6] || {{}}).name) === {mine}", 30),
            f"{first} did not go to slot 7: {self.bag()}")
        # The swap moved exactly two things: nothing lost, nothing doubled.
        now = sorted(x for x in self.bag() if x)
        self.assertEqual(was, now, f"the bag changed: {was} -> {now}")
        self.assertEqual(len(now), len(set(now)), f"a thing was duplicated: {now}")

        # AND IT STAYS THERE. Take it out with its own key and put it back:
        # that is what makes a hot list a hot list.
        self.when_idle()
        self.js("(banjoRoom.fromSlot(6), true)")
        self.assertTrue(self.wait_for("!!banjoRoom.held()", 30), "7 did not bring it to hand")
        self.when_idle()
        self.press_key("KeyQ", "q")
        self.assertTrue(self.wait_for(
            f"((banjoRoom.world.inventory.stowed[6] || {{}}).name) === {mine}", 30),
            f"it did not go back to the slot it was given: {self.bag()}")

        # THE ROW IS SOMETHING YOU CAN DROP ON. It was `pointer-events: none`.
        keys = json.loads(self.js(
            "JSON.stringify([...document.querySelectorAll('#hotbar .slot b')]"
            ".map(b => b.textContent))"))
        self.assertEqual(["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"], keys,
                         f"the hot list is not ten slots numbered 1-9 then 0: {keys}")
        self.assertEqual("auto", self.js(
            "getComputedStyle(document.querySelector('#hotbar .slot')).pointerEvents"),
            "a slot cannot be dropped on")
        self.assertEqual("none", self.js(
            "getComputedStyle(document.getElementById('hotbar')).pointerEvents"),
            "the whole row takes the pointer, so it covers the view")

        # An empty slot is hidden, so while a thing is carried every slot has
        # to show itself or there is nothing to aim at. One empty slot is
        # always drawn -- the one after the last full one -- so look past it.
        beyond = "#hotbar .slot.empty:not(.next)"
        self.assertTrue(self.js(f"!!document.querySelector('{beyond}')"),
                        "the row has no spare slots to check")
        hidden = self.js(f"getComputedStyle(document.querySelector('{beyond}')).display")
        self.js("(document.body.classList.add('moving-a-thing'), true)")
        shown = self.js(f"getComputedStyle(document.querySelector('{beyond}')).display")
        self.js("(document.body.classList.remove('moving-a-thing'), true)")
        self.assertEqual("none", hidden, "an empty slot is drawn when nothing is being moved")
        self.assertNotEqual("none", shown, "an empty slot stays hidden while a thing is carried")

        # And a thing in the bag can be picked up with the mouse at all.
        self.assertTrue(self.js("!!document.querySelector('#mini-products .mini-product[draggable=true]')"),
                        "a thing in the bag cannot be picked up with the mouse")

        # THE OTHER PLACE IT CAN BE DROPPED. The owner: "from the inventory
        # screen you can click on an item and drag it into the workshop,
        # which will then take you into the workshop where you can modify
        # it." The Workshop link takes the same drag the slots do.
        link = '#world-quickbar .game-tabs [data-screen="inventory"]'
        self.assertEqual("yes", self.js(f"document.querySelector('{link}').dataset.takesThings"),
                         "the Workshop link does not take a thing")
        over = self.js(f"""(() => {{
          const el = document.querySelector('{link}');
          const dt = new DataTransfer();
          dt.setData('application/x-banjo-item', {json.dumps(ident)});
          const e = new DragEvent('dragover', {{dataTransfer: dt, bubbles: true, cancelable: true}});
          el.dispatchEvent(e);
          return JSON.stringify({{lights: el.classList.contains('taking'),
                                  took: e.defaultPrevented}});
        }})()""")
        self.assertEqual({"lights": True, "took": True}, json.loads(over),
                         "the Workshop link does not answer a thing dragged over it")

        # Dropped, it opens that thing on the bench -- the drop itself, as the
        # dragover above, so the page says where it goes.
        self.js(f"""(() => {{
          const dt = new DataTransfer();
          dt.setData('application/x-banjo-item', {json.dumps(ident)});
          document.querySelector('{link}').dispatchEvent(
            new DragEvent('drop', {{dataTransfer: dt, bubbles: true, cancelable: true}}));
          return true;
        }})()""")
        self.assertTrue(self.wait_for(
            "[...document.querySelectorAll('.ws-tabs button')]"
            ".some(b => b.dataset.tab === 'lab' && b.getAttribute('aria-selected') === 'true')",
            120),
            "dropping a thing on the Workshop did not open the bench")
        self.assertTrue(self.wait_for("!!document.querySelector('#ws-name')"
                                      " && document.querySelector('#ws-name').textContent.trim()"
                                      " && document.querySelector('#ws-name').textContent.trim() !== 'Empty lab'", 60),
                        "the bench opened on nothing")


class CompactInventoryAndStableToolShape(PageJourney):
    """A fresh pick keeps its native geometry; the mini inventory uses its ledger."""

    def test_pickup_stow_equip_reload_and_compact_inventory_navigation(self):
        self.page.send("Runtime.enable")
        self.page.send("Page.navigate", {"url":f"http://127.0.0.1:{self.port}/world"})
        self.assertTrue(self.wait_for("window.banjoRoom?.ready()",60),self.situation())
        self.assertFalse(self.js("!!document.querySelector('#tabs, #panel [role=tablist], #tab-settings')"))
        self.assertTrue(self.wait_for("document.querySelector('#mini-energy').textContent.includes(' J')"))
        geometry = """(() => {
          const b=banjoRoom.world.bodies.get('field pick');
          return {cells:b.cells, mass:b.mass, design:!!b.mesh.userData.drawnToDesign,
            vertices:[...b.mesh.geometry.attributes.position.array]};
        })()"""
        before = self.js(geometry)
        self.assertTrue(before["cells"],"the first frame drew a slab instead of the pick")
        self.assertTrue(before["design"],"the handle/head did not draw before pickup")
        self.js("""(() => {const p=banjoRoom.world.bodies.get('field pick').mesh.position;
            banjoRoom.standAt(p.x,p.y+1.62,p.z+1.1);banjoRoom.lookAt(p.x,p.y,p.z);return true;})()""")
        self.assertTrue(self.wait_for("banjoRoom.world.aim?.name==='field pick'",15),self.situation())
        self.assertTrue(self.when_idle())
        self.press_e()
        self.assertTrue(self.wait_for("banjoRoom.held()?.name==='field pick'",20),self.situation())
        self.assertTrue(self.wait_for("banjoRoom.use().mode==='tool-ready'",20),self.situation())
        self.assertTrue(self.when_idle())
        self.assertEqual(before,self.js(geometry),"pickup changed the local mesh, matter or mass")
        self.assertTrue(self.wait_for("!!document.querySelector('.mini-product img')"))
        # What is in the hand is a card over the room, its Stow showing while
        # the mouse is over it; what is in the bag is the side panel's.
        hand = "#hand-slots [data-hand=right]"
        picture = self.js(f"document.querySelector('{hand} img').src")
        self.hover(hand)
        self.click_selector(f"{hand} button")
        self.assertTrue(self.wait_for("!banjoRoom.held() && document.querySelector('#mini-products .mini-product small')?.textContent.startsWith('Bag')"),self.situation())
        self.assertEqual(picture,self.js("document.querySelector('#mini-products .mini-product img').src"))
        self.page.send("Page.reload")
        self.assertTrue(self.wait_for("window.banjoRoom?.ready() && !!document.querySelector('#mini-products .mini-product img')",30))
        self.assertEqual(picture,self.js("document.querySelector('#mini-products .mini-product img').src"))
        self.open_details()
        self.click_selector("#mini-products .mini-product button")
        self.assertTrue(self.wait_for("banjoRoom.held()?.name==='field pick'",20),self.situation())
        self.assertEqual(before,self.js(geometry),"equipping after reload changed the tool")
        self.open_world_menu("keys")
        self.assertGreater(self.js("document.querySelectorAll('#keys-list dt').length"),0)
        self.press_key("KeyQ","q")
        self.assertEqual("field pick",self.js("banjoRoom.held()?.name"),"Menu keyboard help also stowed the tool")
        self.click("game-menu-close")
        # Menu gave the mouse its cursor, which freezes the room's keys (3e2b508d):
        # a click in the room takes it back, and does nothing else.
        self.click_selector("#stage")
        self.assertTrue(self.wait_for("!banjoRoom.controls().cursorFree",10),"a click did not take back the view")
        self.press_key("KeyK","k")
        self.assertTrue(self.wait_for("document.querySelector('#game-menu').open && document.querySelector('[data-world-menu=bench]').open"))
        self.assertTrue(self.wait_for("document.querySelector('#workbench-runs li') && !document.querySelector('#workbench-runs').textContent.includes('Looking for')"))
        self.click("game-menu-close")
        self.click_selector("#mini-inventory header a")
        self.assertTrue(self.wait_for("!!document.querySelector('#ws-inv-grid [data-product]')",30))
        self.assertIn("field pick",self.js("document.querySelector('#ws-inv-grid').textContent.toLowerCase()"))
        self.assertFalse([event for event in self.page.events if event.get("method")=="Runtime.exceptionThrown"])


# Workshop controls share the existing required Chrome/engine CI gate.
from workshop_browser_tests import WorkshopBrowserRegression  # noqa: E402,F401

if __name__ == "__main__":
    unittest.main()
