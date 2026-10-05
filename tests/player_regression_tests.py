"""The player regression: the game played the way a person plays it, checked
for what a person would notice.

The bugs a player feels are rarely the ones a unit test sees: a click that
answers late or waits in a queue behind other clicks, a hole that does not get
deeper, a pile heaped over the hole, being pulled or flung across the map, a
walk that stutters, a tooltip that never comes. Each journey here drives the
real page in headless Chrome with real input (DevTools Input.dispatchKeyEvent
and Input.dispatchMouseEvent), on a real world of 25 cm cubes (`surface:
columns`) run by the real engine, as a player who starts as a body, measures
what that player would notice, and fails saying so in plain English.

1. Dig in one spot: take up the field pick, put it in the bag and take it out
   again from the strip, then facing east, south and north in turn, aim at one
   cube about two metres ahead and click six times a quarter of a second apart.
2. Walk: hold W, S, A and D; jump; climb out of a pit one cube deep.
3. Operate the rover: click it, its panel opens; get into it, drive it with W,
   let go, it stops.
4. The Workshop: open it from the world's bar, change the Camp stool, make it,
   find it in the inventory strip with its picture, hold it.
5. Point and click: hovering names things, clicking opens their panels, a click
   with the pick in hand opens a machine rather than swinging at it.

Each journey leaves build/player-regression/<journey>.json (what was measured,
and every problem found) and <journey>.png (the page at the end).

    BANJO_LIVE_ENGINE=<build>/banjo_live_world_run.exe python tests/player_regression_tests.py -v
    python tools/player_regression.py          # the same, with the engine found for you

It needs the engine (BANJO_LIVE_ENGINE, with banjo_platform_cli beside it) and
Chrome (BANJO_CHROME). Without them it skips, unless BANJO_BROWSER_TESTS=required,
as CI sets, when it fails instead. See docs/player-regression.md.
"""
from __future__ import annotations

import base64
import json
import logging
import math
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "playground"), str(ROOT)]

import ai_player_tests as fixture  # noqa: E402
import qa_browser  # noqa: E402
import world_hub_tests as hub  # noqa: E402

OUT = ROOT / "build" / "player-regression"
REQUIRED = os.environ.get("BANJO_BROWSER_TESTS") == "required"
# One world for every journey, so that a failure is the same world each time:
# the valley the starter world grows from seed 7, on 25 cm cubes.
SEEDS = {"terrain": 7, "goods": 851269742}
CELL_M = 0.25
VIEWPORT = (1280, 800)

# What a player notices, as numbers.
CLICK_ANSWER_S = 0.4          # a click on the ground answered within this
BURST_DONE_S = 1.5            # a burst of clicks over this long after the last one
PILE_CLEAR_M = 1.0            # a pile at least this far from the hole
STAY_PUT_M = 0.3              # digging moves the digger no further than this
TOP_SPEED_WITHIN_S = 0.4      # a walk is at speed this soon
STUTTER_FRACTION = 0.7        # below this share of top speed...
STUTTER_LONGEST_S = 0.2       # ...for no longer than this
STOPS_WITHIN_S = 0.5          # a released key stops the body this soon
JUMP_RISE_M = 0.5
NAME_WITHIN_S = 0.5           # hovering names a thing this soon
PANEL_WITHIN_S = 1.0          # a click opens a panel this soon


def tilt_deg(native):
    w, x, y, z = native["orientation_wxyz"]
    return math.degrees(math.acos(max(-1.0, min(1.0, 1.0 - 2.0 * (x * x + z * z)))))


class PlayerJourney(unittest.TestCase):
    """A server of the test's own (in this process), one world on 25 cm cubes,
    and one headless Chrome playing it as a new player: as a body."""

    get, post, join = hub.NamedWorlds.get, hub.NamedWorlds.post, hub.NamedWorlds.join
    start = fixture.AutonomousGuests.start
    stop = fixture.AutonomousGuests.stop

    @classmethod
    def setUpClass(cls):
        missing = [what for what, there in (("the live engine (BANJO_LIVE_ENGINE)", hub.RUNNER.is_file()),
                                            ("banjo_platform_cli beside it", hub.ENGINE.is_file()),
                                            ("Chrome (BANJO_CHROME)", qa_browser.CHROME.is_file())) if not there]
        if missing:
            why = " and ".join(missing) + " not found"
            if REQUIRED:
                raise RuntimeError(why)
            raise unittest.SkipTest(why)

    def setUp(self):
        fixture.AutonomousGuests.setUp(self)
        self.journey = self._testMethodName.removeprefix("test_")
        # `passed` turns true only when a journey has run to its end and found
        # nothing: a journey stopped by an error is not a pass.
        self.report = {"journey": self.journey, "passed": False, "measured": {}, "problems": [], "steps": []}
        self.began = time.monotonic()
        self.chrome = None
        self.page = None
        # The server says when a request held the room for more than a quarter
        # of a second (server.Handler.do_POST); a stall a player feels is
        # usually one of those, so they go in the report.
        slow = self.report["server_slow_requests"] = []
        began = time.time()

        class Slow(logging.Handler):
            def emit(self, record):
                if "slow request" in record.getMessage():
                    slow.append(f"{record.created - began:6.1f} s  {record.getMessage()}")
        handler, logger = Slow(), logging.getLogger("banjo")
        was = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        self.addCleanup(lambda: (logger.removeHandler(handler), logger.setLevel(was)))
        # Last in, first out: the evidence is written while Chrome is still up.
        self.addCleanup(self.write_evidence)

    def tearDown(self):
        self.doCleanups()
        fixture.AutonomousGuests.tearDown(self)

    # -- the world and the page ---------------------------------------------
    def open_world(self):
        self.world = self.post("/api/worlds", {"name": "Player regression", "surface": "columns",
                                               "seeds": SEEDS})["id"]
        self.me = self.join(self.world, "Player")
        self.players = {self.world: self.me}
        self.post("/api/world/open", {}, self.world)
        self.game = self.app.hub.get(self.world)
        # A new player starts as a body. qa_browser's Chrome would otherwise
        # choose the old camera walk for the page (BANJO_TEST_MOVEMENT).
        with mock.patch.dict(os.environ, {"BANJO_TEST_MOVEMENT": ""}):
            self.chrome = qa_browser.Chrome(*VIEWPORT)
        self.addCleanup(self.close_chrome)
        self.addCleanup(self.write_evidence)     # before Chrome closes: last in, first out
        self.page = self.chrome.page
        for method in ("Page.enable", "Runtime.enable", "Log.enable"):
            self.page.send(method)
        self.page.send("Page.addScriptToEvaluateOnNewDocument", {"source":
            f"localStorage.setItem('banjo.player.{self.world}',{json.dumps(self.me['token'])});"
            "localStorage.removeItem('banjo.movement');"})
        asked = time.monotonic()
        self.page.send("Page.navigate", {"url": self.base + f"/world?world={self.world}"})
        self.need(self.wait("window.banjoRoom?.ready() && document.querySelector('#panel-state')"
                            "?.textContent === 'Live.'", 120),
                  "the world never came up in the page")
        self.need(self.wait("banjoRoom.controls().movementMode === 'native'", 10),
                  "a new player should start as a body, but the page chose "
                  + str(self.js("banjoRoom.controls().movementMode")))
        deadline = time.monotonic() + 30
        while self.body() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        self.need(self.body() is not None, "the server never gave the player a body")
        self.report["measured"]["world_open_s"] = round(time.monotonic() - asked, 2)
        # Let the page settle: opening a world asks for guidance, the market and
        # the inventory, and the first of each is worked out cold. What a
        # journey measures is play, not the first seconds after loading.
        slow = self.report["server_slow_requests"]
        quiet_from, deadline = (time.monotonic(), len(slow)), time.monotonic() + 20
        while time.monotonic() < deadline:
            if len(slow) != quiet_from[1]:
                quiet_from = (time.monotonic(), len(slow))
            elif time.monotonic() - quiet_from[0] >= 3.0:
                break
            time.sleep(0.1)
        self.report["measured"]["settled_after_open_s"] = round(time.monotonic() - asked, 2)
        self.step("the world is open and has settled")
        surface = (self.game.room.spec.get("terrain") or {}).get("surface")
        self.need(surface == "columns", f"the world is not on 25 cm cubes: its surface is {surface!r}")

    def close_chrome(self):
        if self.chrome is not None:
            self.chrome.close()
            self.chrome = None

    def write_evidence(self):
        if getattr(self, "_evidence_written", False):
            return
        self._evidence_written = True
        OUT.mkdir(parents=True, exist_ok=True)
        self.report["wall_s"] = round(time.monotonic() - self.began, 1)
        if self.page is not None and self.chrome is not None:
            try:
                shot = self.page.send("Page.captureScreenshot", {"format": "png"}, timeout=30)
                (OUT / f"{self.journey}.png").write_bytes(base64.b64decode(shot["data"]))
                self.report["screenshot"] = str(OUT / f"{self.journey}.png")
            except Exception as error:  # the page is gone; the numbers still matter
                self.report["screenshot_error"] = str(error)
        (OUT / f"{self.journey}.json").write_text(json.dumps(self.report, indent=1, default=str) + "\n",
                                                  encoding="utf-8")

    # -- reading the page -----------------------------------------------------
    def js(self, expression, timeout=30):
        return json.loads(self.page.evaluate(f"JSON.stringify({expression})", timeout=timeout) or "null")

    def wait(self, expression, seconds=30.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                if self.page.evaluate(f"Boolean({expression})", timeout=10):
                    return True
            except (RuntimeError, TimeoutError):
                pass   # between documents
            time.sleep(0.05)
        return False

    def need(self, ok, why):
        """Something the rest of the journey cannot go on without."""
        if not ok:
            self.report["problems"].append(why)
            self.fail(why)

    def expect(self, ok, why):
        """Something a player would notice. Every one is checked and reported
        before the journey fails, so one run says all that is wrong."""
        if not ok:
            self.report["problems"].append(why)
        return ok

    def step(self, said):
        self.report["steps"].append(f"{time.monotonic() - self.began:6.1f} s  {said}")

    def finish(self):
        errors = self.page_errors()
        self.report["page_errors"] = errors
        self.expect(not errors, f"the page reported {len(errors)} error(s); the first: {errors[0] if errors else ''}")
        self.report["passed"] = not self.report["problems"]
        if self.report["problems"]:
            self.fail(f"{self.journey}: " + "\n  - ".join([""] + self.report["problems"]))

    def page_errors(self):
        """Exceptions thrown in the page, console errors, and the errors the page
        itself noted (banjoRoom.status().errors)."""
        found = []
        for event in self.page.events:
            method, params = event.get("method"), event.get("params") or {}
            if method == "Runtime.exceptionThrown":
                detail = params.get("exceptionDetails") or {}
                found.append("exception: " + str((detail.get("exception") or {}).get("description")
                                                 or detail.get("text"))[:300])
            elif method == "Runtime.consoleAPICalled" and params.get("type") in ("error", "assert"):
                found.append("console: " + " ".join(str(a.get("value", a.get("description", "")))
                                                    for a in params.get("args") or [])[:300])
        try:
            noted = self.js("banjoRoom.status().errors") or []
        except Exception:
            noted = []
        found += [f"the page noted: {e.get('what')}" for e in noted]
        return found

    # -- the player's body ----------------------------------------------------
    def body(self):
        """The engine's own account of this player's body: where it is, how it
        is turned, and whether its feet are on something."""
        native = (self.game.live.session.state.get("native_players") or {}).get(self.me["id"])
        return native

    def survey(self, x, z):
        return self.post("/api/live/act", {"session": self.game.live.session.id, "op": "survey",
                                           "at": [x, z]}, self.world)["survey"]

    def column(self, x, z):
        """The middle of the 25 cm column (x, z) is in, as the engine counts them."""
        grid = self.js("(({x0, z0, dx}) => ({x0, z0, dx}))(banjoRoom.groundDrawn())")
        i = math.floor((x - grid["x0"]) / grid["dx"] + 0.5)
        j = math.floor((z - grid["z0"]) / grid["dx"] + 0.5)
        return grid["x0"] + i * grid["dx"], grid["z0"] + j * grid["dx"]

    def ground_extent(self):
        return self.js("(({x0, z0, dx, nx, nz}) => ({x0, z0, x1: x0 + (nx - 1) * dx, z1: z0 + (nz - 1) * dx}))"
                       "(banjoRoom.groundDrawn())")

    # -- input, as a person gives it ------------------------------------------
    NAMED_KEYS = {"Escape": 27, "Enter": 13, "Tab": 9, " ": 32}

    def key(self, kind, code, key):
        named = key in self.NAMED_KEYS and key != " "
        vk = self.NAMED_KEYS.get(key, ord(key.upper()) if len(key) == 1 else 0)
        self.page.send("Input.dispatchKeyEvent", {
            "type": "rawKeyDown" if named and kind == "keyDown" else kind, "key": key, "code": code,
            "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk,
            **({"text": key, "unmodifiedText": key} if kind == "keyDown" and not named else {})})

    def press(self, code, key):
        self.key("keyDown", code, key)
        time.sleep(0.05)
        self.key("keyUp", code, key)

    def mouse(self, kind, x, y, button="left"):
        self.page.send("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y,
                                                    **({"button": button, "clickCount": 1}
                                                       if kind != "mouseMoved" else {})})

    def click_at(self, x, y):
        self.mouse("mouseMoved", x, y)
        self.mouse("mousePressed", x, y)
        self.mouse("mouseReleased", x, y)

    def click(self, selector, why=""):
        """A control pressed with the mouse at its middle, once it is there and
        nothing is drawn over it."""
        target = json.dumps(selector)
        self.need(self.wait(f"!!document.querySelector({target}) && !document.querySelector({target}).disabled", 30),
                  f"there is no {selector} to press {why}".strip())
        where = f"""(() => {{
          const e = document.querySelector({target});
          const d = e.closest('details:not([open])'); if (d) d.open = true;
          e.scrollIntoView({{block: 'center'}});
          const r = e.getBoundingClientRect(), x = r.x + r.width / 2, y = r.y + r.height / 2;
          const on = document.elementFromPoint(x, y);
          return {{x, y, reached: !!on && (on === e || e.contains(on)),
                   over: on ? (on.id || on.className || on.tagName) : 'nothing (it is off the screen)'}};
        }})()"""
        # A panel slides in when it opens: press once it has stopped moving.
        at, last = None, None
        for _ in range(40):
            at = self.js(where)
            if at["reached"] and last and abs(at["x"] - last["x"]) < 0.5 and abs(at["y"] - last["y"]) < 0.5:
                break
            last = at
            time.sleep(0.1)
        self.need(at["reached"], f"{selector} cannot be pressed: {at['over']} is over it")
        self.click_at(at["x"], at["y"])

    def stage_middle(self):
        return self.js("(() => { const r = document.querySelector('#stage').getBoundingClientRect();"
                       " return {x: r.x + r.width / 2, y: r.y + r.height / 2}; })()")

    def on_screen(self, name):
        """Where a thing's middle is drawn on the screen, in page pixels."""
        return self.js(f"""(() => {{
          const r = banjoRoom, e = r.world.bodies.get({json.dumps(name)}); if (!e) return null;
          const v = e.mesh.getWorldPosition(new r.THREE.Vector3()).project(r.camera);
          const b = document.querySelector('#stage').getBoundingClientRect();
          return {{x: b.left + (v.x + 1) / 2 * b.width, y: b.top + (1 - v.y) / 2 * b.height,
                   ahead: v.z < 1}};
        }})()""")

    def look_at(self, x, y, z):
        self.js(f"(banjoRoom.lookAt({x}, {y}, {z}), true)")

    def look_at_thing(self, name):
        at = self.js(f"banjoRoom.world.bodies.get({json.dumps(name)})?.mesh.position.toArray()")
        self.need(at is not None, f"there is no {name} in the world")
        self.look_at(*at)
        time.sleep(0.3)
        return self.on_screen(name)

    def take_up_the_pick(self):
        """Look at the field pick and press E, as the side view says to."""
        self.look_at_thing("field pick")
        self.press("KeyE", "e")
        self.need(self.wait("banjoRoom.held()?.name === 'field pick' && banjoRoom.use().mode === 'tool-ready'", 20),
                  "E with the field pick in view did not take it up: the hand holds "
                  + str(self.js("banjoRoom.held()")))
        self.step("took up the field pick with E")

    def watch_fetches(self, *fragments):
        """Count the page's requests whose URL holds any of `fragments`: when
        each started and ended, and the most in flight at once."""
        self.page.evaluate("""(() => {
          if (window.__watched) return;
          window.__watched = {calls: [], active: 0, most: 0, fragments: %s};
          const original = window.fetch;
          window.fetch = async function (url, options) {
            const w = window.__watched, which = w.fragments.find((f) => String(url).includes(f));
            if (!which) return original.apply(this, arguments);
            const call = {url: which, start: performance.now(), end: null, body: null};
            w.calls.push(call); w.most = Math.max(w.most, ++w.active);
            try {
              const reply = await original.apply(this, arguments);
              call.status = reply.status;
              try {
                const body = await reply.clone().json();
                // A walk reply is the whole body's state, a dozen times a
                // second: keep only what says whether it was refused.
                call.body = which.includes('/player/walk')
                  ? {refused: body.refused || body.error || null, moved: body.native?.velocity_m_s || null}
                  : body;
              } catch { call.body = null; }
              return reply;
            } catch (error) {
              call.error = String(error.message || error);
              throw error;
            } finally { call.end = performance.now(); w.active--; }
          };
        })()""" % json.dumps(list(fragments)))

    def calls(self, fragment):
        return [c for c in self.js("window.__watched.calls") if c["url"] == fragment]

    # =========================================================================
    # 1. Dig in one spot
    # =========================================================================
    # Which way the player faces for each hole. A hole is dug looking more
    # than one way because which cube a click took once a hole was a cube deep
    # depended on it: looking east or south the hole grew away from the player
    # instead of down. Not west as well: the first hole's pile is heaped behind
    # the digger, on the line of sight to a hole to the west, and a click on a
    # pile collects it (which is checked, and is not what is measured here).
    FACING = {"east (+x)": 0, "south (+z)": 90, "north (-z)": 270}
    CLICKS = 6

    def a_spot_to_dig(self, stood, facing_deg, taken):
        """A cube about two metres away in the direction faced, as a player
        picks a spot: on dry ground, with soil and sand under it at least four
        cubes deep where the valley has that (so each click should take one
        whole cube), and clear of the holes already dug and of the piles they
        made: a pile in the line of sight takes the click (it is collected)."""
        piles = [p["at_m"] for p in self.game.brains.goods.stockpiles if p.get("excavated")]

        def blocked(x, z):
            for px, pz in piles:
                if math.hypot(x - px, z - pz) < 1.5:
                    return True
                # The nearest point of the line from the player to the spot.
                vx, vz = x - stood[0], z - stood[2]
                t = max(0.0, min(1.0, ((px - stood[0]) * vx + (pz - stood[2]) * vz) / (vx * vx + vz * vz)))
                if math.hypot(stood[0] + t * vx - px, stood[2] + t * vz - pz) < 0.7:
                    return True
            return False

        found, looked = [], set()
        for ahead in (1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0):
            for turn in range(facing_deg - 60, facing_deg + 61, 10):
                x, z = self.column(stood[0] + ahead * math.cos(math.radians(turn)),
                                   stood[2] + ahead * math.sin(math.radians(turn)))
                if (x, z) in looked or any(math.hypot(x - tx, z - tz) < 1.5 for tx, tz in taken) or blocked(x, z):
                    continue
                looked.add((x, z))
                ground = self.survey(x, z)
                if ground.get("water") or not ground.get("on_the_ground"):
                    continue
                found.append((x, z, ground["ground_m"] - ground["rock_top_m"], ground,
                              math.hypot(x - stood[0], z - stood[2])))
        deep = max((f[2] for f in found), default=0.0)
        enough = [f for f in found if f[2] >= min(4 * CELL_M, deep - 0.01)]
        return min(enough, key=lambda f: (abs(f[4] - 2.0), -f[2]))[:4] if enough else None

    def dig_a_hole(self, facing, stood, taken):
        """Aim at one cube and click six times, a quarter of a second apart,
        with the mouse held still at the middle of the view. Returns what a
        player would notice, and records each problem under `facing`."""
        spot = self.a_spot_to_dig(stood, self.FACING[facing], taken)
        if spot is None:
            self.expect(False, f"facing {facing} there is no dry ground about two metres away to dig")
            return None
        x, z, loose, ground = spot
        taken.append((x, z))
        neighbours = [(dx, dz) for dx in (-1, 0, 1) for dz in (-1, 0, 1)]

        def heights():
            return {(dx, dz): self.survey(x + dx * CELL_M, z + dz * CELL_M)["ground_m"] for dx, dz in neighbours}

        before = heights()
        piles_before = {p["name"]: sum(p["holds"].values()) for p in self.game.brains.goods.stockpiles
                        if p.get("excavated")}
        self.look_at(x, before[(0, 0)], z)
        middle = self.stage_middle()
        self.mouse("mouseMoved", middle["x"], middle["y"])
        if not self.expect(self.wait("banjoRoom.use().target?.enabled", 10),
                           f"facing {facing}, with the pick in hand and the cursor on the ground, the page does "
                           f"not offer to dig: {self.js('banjoRoom.use().target')}"):
            return None
        first = len(self.js("window.__watched.calls"))
        self.page.evaluate("window.__downs = []; window.__watched.most = window.__watched.active")
        for n in range(self.CLICKS):
            began = time.monotonic()
            self.mouse("mousePressed", middle["x"], middle["y"])
            self.mouse("mouseReleased", middle["x"], middle["y"])
            if n < self.CLICKS - 1:
                time.sleep(max(0.0, 0.25 - (time.monotonic() - began)))
        last_click = time.monotonic()
        settled = self.wait("window.__watched.active === 0 && banjoRoom.use().mode === 'tool-ready'"
                            " && !banjoRoom.use().queued && !banjoRoom.use().timer", 15)
        done_s = time.monotonic() - last_click
        downs = self.js("window.__downs")
        calls = self.js("window.__watched.calls")[first:]
        uses = [c for c in calls if c["url"] == "/api/world/tool/use"]
        collected = [c for c in calls if c["url"] == "/api/world/goods/collect"]
        most = self.js("window.__watched.most")
        after = heights()
        time.sleep(0.5)   # the next step reply carries the ground to the page
        drawn = self.js(f"banjoRoom.groundAt({x}, {z})")
        piles = [p for p in self.game.brains.goods.stockpiles if p.get("excavated")]

        answers = []
        for down in downs:
            reply = next((u for u in uses if u["end"] and u["end"] >= down), None)
            answers.append(round((reply["end"] - down) / 1000, 3) if reply else None)
        strikes = [u for u in uses if u["body"] and not u["body"].get("refused")
                   and (u["body"].get("result") or {}).get("loosened_kg", 0) > 0]
        struck = []
        for u in strikes:
            at = (u["body"].get("result") or {}).get("at_m") or [None, None, None]
            if at[0] is not None:
                cx, cz = self.column(at[0], at[2])
                struck.append([round((cx - x) / CELL_M), round((cz - z) / CELL_M)])
        changed = {f"{dx},{dz}": round(after[(dx, dz)] - before[(dx, dz)], 3) for dx, dz in neighbours}
        dug_kg = sum(float(u["body"]["result"]["loosened_kg"]) for u in strikes)
        piled_kg = sum(sum(p["holds"].values()) for p in piles) - sum(piles_before.values())
        measured = {
            "column_m": [x, z], "loose_cover_m": round(loose, 3), "top": ground["surface"],
            "level_distance_m": round(math.hypot(x - stood[0], z - stood[2]), 2),
            "clicks": len(downs), "requests": len(uses), "strikes": len(strikes),
            "click_to_answer_s": answers, "request_ms": [round(u["end"] - u["start"]) for u in uses if u["end"]],
            "most_requests_at_once": most, "burst_done_after_last_click_s": round(done_s, 2),
            "struck_columns_from_aimed": struck, "height_change_m": changed,
            "drawn_height_m": drawn, "engine_height_m": after[(0, 0)],
            "dug_kg": round(dug_kg, 3), "piled_kg": round(piled_kg, 3), "piles_collected": len(collected)}
        self.step(f"facing {facing}, clicked {self.CLICKS} times at one cube: the aimed column went "
                  f"{changed['0,0']:+.2f} m; the digs landed on {struck}")

        said = f"facing {facing}: "
        self.expect(len(downs) == self.CLICKS, said + f"the page saw {len(downs)} of the {self.CLICKS} clicks")
        self.expect(not collected, said + f"{len(collected)} click(s) at the ground collected a pile instead of digging")
        slow = [a for a in answers if a is None or a > CLICK_ANSWER_S]
        self.expect(not slow, said + f"clicks should each be answered within {CLICK_ANSWER_S * 1000:.0f} ms; "
                                     f"from press to reply they took {answers} s")
        self.expect(most <= 1, said + f"clicks queued up: {most} digs were in flight at once")
        self.expect(settled and done_s <= BURST_DONE_S,
                    said + f"the burst of clicks should be over within {BURST_DONE_S} s of the last click; "
                           f"it took {done_s:.2f} s" + ("" if settled else " and never settled"))
        self.expect(len(strikes) >= 2, said + f"only {len(strikes)} of {self.CLICKS} clicks dug anything")
        # A strike takes a whole cube of soil or sand, down to the rock and no
        # further; clay and rock come away a share at a time.
        whole = [u for u in strikes if (u["body"].get("result") or {}).get("ground") in ("sand", "soil", "loose soil")]
        expected = -min(CELL_M * len(whole), loose)
        self.expect(expected - 0.01 - CELL_M * (len(strikes) - len(whole)) <= changed["0,0"] <= expected + 0.01,
                    said + f"each click should take the aimed column one cube (0.25 m) deeper: {len(whole)} digs "
                           f"into soil and sand ({loose:.2f} m of it above the rock) should have lowered it "
                           f"{expected:.2f} m, and it went {changed['0,0']:+.3f} m. The digs landed on these "
                           f"columns, counted in cubes along x and z from the aimed one: {struck}")
        others = {k: v for k, v in changed.items() if k != "0,0" and abs(v) > 0.005}
        self.expect(not others, said + f"digging one spot changed the columns beside it (metres, keyed by "
                                       f"cubes along x,z from the aimed one): {others}")
        self.expect(drawn is not None and abs(drawn - after[(0, 0)]) < 0.02,
                    said + f"the hole is drawn at {drawn} m but the engine has the ground there at "
                           f"{after[(0, 0)]:.3f} m")
        self.expect(dug_kg > 0 and abs(piled_kg - dug_kg) < 0.05 * dug_kg + 0.01,
                    said + f"what was dug ({dug_kg:.1f} kg) should all be in piles; the piles grew {piled_kg:.1f} kg")
        return measured

    def a_place_to_dig_from(self, near):
        """Where to stand: dry, nearly level ground with soil and sand at least
        four cubes deep two metres east, south and north of it -- the valley
        has rock and the river close to where a new player starts."""
        sid = self.game.live.session.id

        def survey(x, z):
            return self.game.live.act({"session": sid, "op": "survey", "at": [x, z]})["survey"]

        sites = sorted(((near[0] + dx * 0.5, near[2] + dz * 0.5) for dx in range(-24, 25) for dz in range(-24, 25)),
                       key=lambda p: math.hypot(p[0] - near[0], p[1] - near[2]))
        for x, z in sites:
            x, z = self.column(x, z)
            here = survey(x, z)
            if here.get("water") or not here.get("on_the_ground") or here.get("slope_deg", 90) > 15:
                continue
            good = True
            for deg in self.FACING.values():
                ground = survey(x + 2.0 * round(math.cos(math.radians(deg))), z + 2.0 * round(math.sin(math.radians(deg))))
                if ground.get("water") or ground["ground_m"] - ground["rock_top_m"] < 4 * CELL_M + 0.02 \
                        or abs(ground["ground_m"] - here["ground_m"]) > 0.6:
                    good = False
                    break
            if good:
                return [x, here["ground_m"], z]
        return None

    def test_dig_in_one_spot(self):
        self.open_world()
        # The pick, taken up where it lies and put in the bag (Q) to carry.
        self.take_up_the_pick()
        self.press("KeyQ", "q")
        self.need(self.wait("!banjoRoom.held() && (banjoRoom.world.inventory?.record?.stowed || []).includes('field pick')", 15),
                  "Q did not put the field pick in the bag: the hand holds " + str(self.js("banjoRoom.held()")))
        # Stood where there is ground to dig on every side that is dug (the
        # test moves the body there, as a teleport would).
        site = self.a_place_to_dig_from(self.body()["position_m"])
        self.need(site is not None, "there is nowhere in the valley with soil four cubes deep on three sides to dig")
        self.game.live.session.send(op="player-remove", actor=self.me["id"])
        self.game.live.session.send(op="player-spawn", actor=self.me["id"], feet_m=[site[0], site[1] + 0.02, site[2]])
        self.need(self.wait(f"Math.hypot(banjoRoom.camera.position.x - {site[0]}, banjoRoom.camera.position.z - {site[2]}) < 0.3", 15),
                  f"the player's view did not follow their body to {site}")
        time.sleep(1.0)
        self.step(f"stood at {[round(v, 2) for v in site]}")
        # And out of the bag again from the strip.
        self.click("#inventory-strip .strip-item[title*='Field pick' i]", "(the pick in the bag)")
        self.need(self.wait("banjoRoom.held()?.name === 'field pick' && banjoRoom.use().mode === 'tool-ready'", 20),
                  "clicking the field pick in the inventory strip did not put it in the hand: "
                  + str(self.js("banjoRoom.held()")))
        self.step("took the field pick out of the bag from the strip")
        native = self.body()
        self.need(native is not None, "the player has no body to dig from")
        stood = native["position_m"]
        self.watch_fetches("/api/world/tool/use", "/api/world/goods/collect")
        self.page.evaluate("""(() => { window.__downs = [];
          document.querySelector('#stage').addEventListener('pointerdown',
            () => __downs.push(performance.now()), true); })()""")
        holes, taken = {}, []
        for facing in self.FACING:
            holes[facing] = self.dig_a_hole(facing, stood, taken)
        self.report["measured"]["holes"] = holes
        # The piles: every one at least a metre from every hole, and the page
        # draws what was dug.
        piles = [p for p in self.game.brains.goods.stockpiles if p.get("excavated")]
        self.report["measured"]["piles"] = [{"name": p["name"], "at_m": p["at_m"],
                                             "kg": round(sum(p["holds"].values()), 2)} for p in piles]
        dug = [(name, h["column_m"]) for name, h in holes.items() if h]
        on_holes = [(p["name"], name, round(math.hypot(p["at_m"][0] - at[0], p["at_m"][1] - at[1]), 2))
                    for p in piles for name, at in dug
                    if math.hypot(p["at_m"][0] - at[0], p["at_m"][1] - at[1]) < PILE_CLEAR_M]
        self.report["measured"]["piles_on_holes"] = on_holes
        self.expect(piles, "nothing that was dug went into a pile")
        self.expect(not on_holes, f"a pile should sit at least {PILE_CLEAR_M} m from every hole; these are "
                                  f"closer (pile, the hole dug facing, metres): {on_holes}")
        shown = self.js("(banjoRoom.world.goods?.stockpiles || []).filter(p => p.excavated)"
                        ".map(p => Object.values(p.holds_kg || {}).reduce((a, b) => a + b, 0))")
        self.expect(shown and sum(shown) > 0, "the page shows no pile of what was dug")
        # The digger: where they stood, upright, on their feet.
        after = self.body()
        moved = math.hypot(after["position_m"][0] - stood[0], after["position_m"][2] - stood[2])
        self.report["measured"]["digger"] = {"moved_m": round(moved, 3), "tilt_deg": round(tilt_deg(after), 1),
                                             "supported": after["walk"].get("supported")}
        self.expect(moved <= STAY_PUT_M, f"digging moved the player {moved:.2f} m: they should stay where "
                                         f"they stood (within {STAY_PUT_M} m)")
        self.expect(tilt_deg(after) < 10, f"the player is tipped {tilt_deg(after):.0f} degrees after digging")
        self.expect(after["walk"].get("supported"), "after digging the player's feet are on nothing")
        self.finish()

    # =========================================================================
    # 2. Walk
    # =========================================================================
    SAMPLER = """(() => {
      window.__walk = {samples: [], keys: []};
      const each = () => { const p = banjoRoom.camera.position;
        __walk.samples.push([performance.now(), p.x, p.y, p.z]); requestAnimationFrame(each); };
      requestAnimationFrame(each);
      addEventListener('keydown', (e) => { if (!e.repeat) __walk.keys.push([e.code, 'down', performance.now()]); }, true);
      addEventListener('keyup', (e) => __walk.keys.push([e.code, 'up', performance.now()]), true);
    })()"""

    @staticmethod
    def speeds(samples, window_ms=100.0):
        """Speed along the ground over `window_ms`, at each frame: [t_ms, m/s],
        timed at the middle of the window it is measured over. Frame to frame
        the eye follows the body between replies, so one frame's step is
        noise; a tenth of a second is what is felt."""
        out, j = [], 0
        for t, x, _, z in samples:
            while samples[j][0] < t - window_ms:
                j += 1
            t0, x0, _, z0 = samples[j]
            if t - t0 >= window_ms * 0.5:
                out.append((0.5 * (t + t0), math.hypot(x - x0, z - z0) / ((t - t0) / 1000.0)))
        return out

    def held_walk(self, code, key, hold_s=2.0, after_s=1.5):
        self.key("keyDown", code, key)
        time.sleep(hold_s)
        self.key("keyUp", code, key)
        time.sleep(after_s)
        keys = self.js("window.__walk.keys")
        down = [t for c, kind, t in keys if c == code and kind == "down"][-1]
        up = [t for c, kind, t in keys if c == code and kind == "up"][-1]
        samples = [s for s in self.js("window.__walk.samples") if down - 200 <= s[0] <= up + after_s * 1000]
        # Measured to the nearest frame: CI draws in software at a few frames a
        # second, where a tenth of a second is less than one frame.
        gaps = sorted(b[0] - a[0] for a, b in zip(samples, samples[1:]))
        frame_ms = gaps[len(gaps) // 2] if gaps else 16.7
        speed = self.speeds(samples, max(100.0, 2.5 * frame_ms))
        holding = sorted(v for t, v in speed if down + 500 <= t <= up)
        top = holding[len(holding) // 2] if holding else 0.0
        reached = next((t for t, v in speed if t >= down and v >= 0.9 * top), None)
        longest, run_from = 0.0, None
        for t, v in speed:
            if not (reached is not None and reached <= t <= up):
                continue
            if v < STUTTER_FRACTION * top:
                run_from = t if run_from is None else run_from
                longest = max(longest, t - run_from)
            else:
                run_from = None
        moving = [t for t, v in speed if t > up and v >= max(0.15, 0.1 * top)]
        stopped_after = ((moving[-1] - up) / 1000.0) if moving else 0.0
        start, end = samples[0], samples[-1]
        return {"key": key.upper(), "top_m_s": round(top, 2), "frame_s": round(frame_ms / 1000.0, 3),
                "top_reached_s": None if reached is None else round((reached - down) / 1000.0, 3),
                "longest_dip_s": round(longest / 1000.0, 3),
                "stopped_after_release_s": round(stopped_after, 3),
                "went_m": round(math.hypot(end[1] - start[1], end[3] - start[3]), 2),
                "frames": len(samples), "fps": round(len(samples) / max(1e-6, (end[0] - start[0]) / 1000.0), 1),
                # Speed every 50 ms from the key going down, for reading a failure.
                "speed_every_50ms": [round(v, 2) for t, v in speed if t >= down][::3]}

    def check_walk(self, walked):
        key, frame = walked["key"], walked["frame_s"]
        self.expect(walked["top_m_s"] >= 1.0, f"holding {key} the body only reached {walked['top_m_s']} m/s")
        self.expect(walked["top_reached_s"] is not None and walked["top_reached_s"] <= TOP_SPEED_WITHIN_S + frame,
                    f"holding {key}, the body should be at speed (90% of its {walked['top_m_s']} m/s) within "
                    f"{TOP_SPEED_WITHIN_S} s; it took {walked['top_reached_s']} s")
        self.expect(walked["longest_dip_s"] <= STUTTER_LONGEST_S + frame,
                    f"walking with {key} stuttered: it fell below {STUTTER_FRACTION:.0%} of its steady speed "
                    f"({walked['top_m_s']} m/s) for {walked['longest_dip_s']} s at a time")
        self.expect(walked["stopped_after_release_s"] <= STOPS_WITHIN_S + frame,
                    f"letting go of {key}, the body should stop within {STOPS_WITHIN_S} s; it was still "
                    f"moving {walked['stopped_after_release_s']} s later")

    def test_walk(self):
        self.open_world()
        start = self.body()["position_m"]
        extent = self.ground_extent()
        # The walks go 4 m forward, back, left and back again: face the way
        # the ground is most level for that, so what is measured is the walk
        # and not a hill (uphill a body is slower to get going, by physics).
        eye = self.js("banjoRoom.camera.position.toArray()")
        level = self.js(f"""(() => {{
          const [x, , z] = {json.dumps(eye)}, h0 = banjoRoom.groundAt(x, z), out = [];
          for (let deg = 0; deg < 360; deg += 15) {{
            const a = deg * Math.PI / 180, f = [Math.cos(a), Math.sin(a)], left = [f[1], -f[0]];
            let worst = 0;
            const at = (px, pz) => {{
              const wet = banjoRoom.waterAt(px, pz);
              worst = Math.max(worst, wet && wet.depth > 0.01 ? Infinity : Math.abs(banjoRoom.groundAt(px, pz) - h0));
            }};
            for (let s = -4.5; s <= 4.5; s += 0.25) at(x + f[0] * s, z + f[1] * s);
            for (let s = 0; s <= 4.5; s += 0.25) at(x + left[0] * s, z + left[1] * s);
            out.push([worst, deg]);
          }}
          return out.sort((a, b) => a[0] - b[0])[0];
        }})()""")
        self.need(level[0] is not None and level[0] < 1.5,
                  f"there is no dry, fairly level ground to walk on round the player: {level}")
        heading = math.radians(level[1])
        self.report["measured"]["heading"] = {"deg": level[1], "ground_varies_m": round(level[0], 3)}
        self.look_at(eye[0] + 10 * math.cos(heading), eye[1] - 1.0, eye[2] + 10 * math.sin(heading))
        self.page.evaluate(self.SAMPLER)
        self.watch_fetches("/api/world/player/walk")
        time.sleep(0.5)
        walks = []
        for code, key in (("KeyW", "w"), ("KeyS", "s"), ("KeyA", "a"), ("KeyD", "d")):
            walked = self.held_walk(code, key)
            walks.append(walked)
            self.step(f"held {key.upper()} for 2 s: {walked}")
            self.check_walk(walked)
        self.report["measured"]["walks"] = walks
        asked = self.calls("/api/world/player/walk")
        failed = [c for c in asked if c.get("error") or (c.get("status") or 200) >= 400 or (c.get("body") or {}).get("refused")]
        slowest = sorted(((c["end"] or self.js("performance.now()")) - c["start"]) / 1000.0 for c in asked)[-3:]
        self.report["measured"]["walk_requests"] = {"sent": len(asked), "failed": len(failed),
                                                    "first_failures": failed[:3],
                                                    "unanswered": sum(1 for c in asked if c["end"] is None),
                                                    "slowest_s": [round(v, 2) for v in slowest]}
        self.expect(not slowest or slowest[-1] < 0.5,
                    f"a walk request took {slowest[-1]:.1f} s to answer: the page sends the next one only after "
                    "it, so the body is held at its last speed meanwhile")
        self.expect(not failed, f"{len(failed)} of {len(asked)} walk requests failed; the first: {failed[:1]}")

        # Space: a jump.
        time.sleep(0.5)
        self.press("Space", " ")
        time.sleep(2.0)
        keys = self.js("window.__walk.keys")
        pressed = [t for c, kind, t in keys if c == "Space" and kind == "down"][-1]
        samples = [s for s in self.js("window.__walk.samples") if pressed - 100 <= s[0]]
        base = samples[0][2]
        rise = max(s[2] for s in samples) - base
        landed = samples[-1][2] - base
        native = self.body()
        self.report["measured"]["jump"] = {"rise_m": round(rise, 3), "end_vs_start_m": round(landed, 3),
                                           "supported_after": native["walk"].get("supported")}
        self.step(f"pressed Space: rose {rise:.2f} m")
        self.expect(rise >= JUMP_RISE_M, f"Space should jump at least {JUMP_RISE_M} m; the eye rose {rise:.2f} m")
        self.expect(abs(landed) < 0.1 and native["walk"].get("supported"),
                    f"after the jump the body should be back on the ground: it is {landed:+.2f} m from where it "
                    f"started and its feet are {'on' if native['walk'].get('supported') else 'on nothing'}")

        # A step one cube high: a pit dug round the player, walked out of.
        self.climb_out_of_a_pit()

        # Never off the map.
        samples = self.js("window.__walk.samples")
        off = [s for s in samples if not (extent["x0"] - 0.5 <= s[1] <= extent["x1"] + 0.5
                                         and extent["z0"] - 0.5 <= s[3] <= extent["z1"] + 0.5)]
        lowest = min(s[2] for s in samples)
        self.report["measured"]["map"] = {"extent": extent, "frames_off_the_map": len(off),
                                          "lowest_eye_m": round(lowest, 3), "start_m": start}
        self.expect(not off, f"the body left the map: {len(off)} frames outside it, the first at {off[:1]}")
        native = self.body()
        ground = self.survey(native["position_m"][0], native["position_m"][2])["ground_m"]
        self.expect(native["position_m"][1] > ground - 0.2,
                    f"the body ended under the ground: at {native['position_m'][1]:.2f} m, ground {ground:.2f} m")
        self.expect(tilt_deg(native) < 10, f"the body ended tipped over: {tilt_deg(native):.0f} degrees")
        self.finish()

    def climb_out_of_a_pit(self):
        """Dig a pit round where the player stands, its floor one cube (25 cm)
        below the ground ahead of it -- with the server's own spade, the dig op
        the page's digAt uses, heaping what it carries well away -- then walk
        out of it with W. The far side is a step of 25 cm, and the body must
        climb it."""
        here = self.body()["position_m"]
        cx, cz = self.column(here[0], here[2])
        sid = self.game.live.session.id
        dump = [cx - 6.0, cz + 3.0]
        rim = min(self.survey(cx + 3 * CELL_M, cz + dj * CELL_M)["ground_m"] for dj in (-1, 0, 1))
        target = rim - CELL_M
        pit = [(di, dj) for di in (-1, 0, 1, 2) for dj in (-1, 0, 1)]
        for di, dj in pit:
            x, z = cx + di * CELL_M, cz + dj * CELL_M
            for _ in range(4):
                depth = self.survey(x, z)["ground_m"] - target
                if depth < 0.01:
                    break
                self.post("/api/live/act", {"session": sid, "op": "dig", "from": [x, z], "width_m": 0.2,
                                            "depth_m": max(0.02, depth)}, self.world)
                carried = self.post("/api/live/act", {"session": sid, "op": "step", "dt": 1 / 240, "n": 1},
                                    self.world).get("carried") or {}
                sand, soil = float(carried.get("sand_m3") or 0), float(carried.get("soil_m3") or 0)
                if sand + soil > 0:
                    self.post("/api/live/act", {"session": sid, "op": "deposit", "at": dump, "radius_m": 1.5,
                                                "sand_m3": sand, "soil_m3": soil}, self.world)
        floors = [self.survey(cx + di * CELL_M, cz + dj * CELL_M)["ground_m"] for di, dj in pit]
        step_m = rim - max(floors)
        self.report["measured"]["pit"] = {"rim_m": round(rim, 3), "floors_m": [round(f, 3) for f in floors],
                                          "step_m": round(step_m, 3)}
        self.need(0.2 <= step_m <= 0.3, f"could not make a 25 cm step to climb: the pit's edge is {step_m:.2f} m")
        time.sleep(1.5)   # the body settles onto the pit floor
        inside = self.body()["position_m"]
        eye = self.js("banjoRoom.camera.position.toArray()")
        self.look_at(eye[0] + 10, eye[1] - 1.0, eye[2])
        edge = cx + 2.5 * CELL_M - inside[0]
        self.key("keyDown", "KeyW", "w")
        time.sleep(2.0)
        self.key("keyUp", "KeyW", "w")
        time.sleep(1.0)
        out = self.body()
        went = out["position_m"][0] - inside[0]
        rose = out["position_m"][1] - inside[1]
        self.report["measured"]["climb"] = {"from_m": inside, "to_m": out["position_m"], "edge_ahead_m": round(edge, 2),
                                            "went_m": round(went, 2), "rose_m": round(rose, 3),
                                            "supported": out["walk"].get("supported")}
        self.step(f"walked at a 25 cm step {edge:.2f} m ahead: went {went:.2f} m, rose {rose:.2f} m")
        self.expect(went > edge + 0.5 and out["walk"].get("supported"),
                    f"walking at a 25 cm step should climb it: the edge was {edge:.2f} m ahead of the body in "
                    f"the pit, and holding W for 2 s took it {went:.2f} m (rising {rose:.2f} m)")

    # =========================================================================
    # 3. Operate the rover
    # =========================================================================
    def rover_program(self):
        return "banjoRoom.world.machines.programs.find((p) => p.body === 'rover' || (p.parts || []).includes('rover'))"

    def test_operate_the_rover(self):
        self.open_world()
        program = self.rover_program()
        self.need(self.wait(f"!!({program})", 30), "the world lists no rover program")
        at = self.look_at_thing("rover")
        self.need(at and at["ahead"], "the rover is not in view")
        asked = time.monotonic()
        self.click_at(at["x"], at["y"])
        opened = self.wait("!document.getElementById('machine-panel').hidden && "
                           "getComputedStyle(document.getElementById('panel')).visibility === 'visible'", 5)
        panel_s = time.monotonic() - asked
        title = self.js("document.getElementById('machine-panel').innerText.slice(0, 120)")
        self.report["measured"]["panel_open_s"] = round(panel_s, 2)
        self.expect(opened and panel_s <= PANEL_WITHIN_S and "Rover" in (title or ""),
                    f"clicking the rover should open its panel within {PANEL_WITHIN_S} s: "
                    + (f"it took {panel_s:.2f} s" if opened else "it never opened") + f" ({title!r})")
        self.step(f"clicked the rover; its panel opened in {panel_s:.2f} s")
        if opened:
            self.click("#mp-close")

        # Drive it with the keys: Menu, Drive a machine, the rover.
        if not self.js("document.querySelector('#game-menu').open"):
            self.click(".game-bottom-tabs [data-game-menu]")
        if not self.js("document.querySelector('[data-world-menu=\"settings\"]').open"):
            self.click('[data-world-menu="settings"] > summary')
        self.click('[data-rides="rover"]', "(Menu: Drive a machine)")
        self.need(self.wait("document.getElementById('settings-said').textContent.includes('You are rover')", 15),
                  "choosing the rover in the Menu did not put the player in it: "
                  + str(self.js("document.getElementById('settings-said').textContent")))
        self.need(self.wait(f"({program}).power === true", 30), "getting into the rover did not turn it on")
        if self.js("document.querySelector('#game-menu').open"):
            self.press("Escape", "Escape")
        self.js("(document.activeElement && document.activeElement.blur(), true)")
        time.sleep(1.0)

        def where():
            return self.js(f"({program}).at_m")

        was = where()
        self.key("keyDown", "KeyW", "w")
        time.sleep(4.0)
        driving = self.js(f"({program}).speed_m_s")
        self.key("keyUp", "KeyW", "w")
        drove = where()
        went = math.dist(was, drove)
        time.sleep(3.0)
        settled = where()
        time.sleep(1.0)
        rest = where()
        crept = math.dist(settled, rest)
        self.report["measured"]["drive"] = {"from_m": was, "to_m": drove, "went_m": round(went, 2),
                                            "speed_while_held_m_s": driving,
                                            "moved_in_last_second_m": round(crept, 3)}
        self.step(f"held W in the rover for 4 s: it went {went:.2f} m; a second, 3 s after letting go: {crept:.2f} m")
        self.expect(went > 0.5, f"holding W in the rover should drive it: it went {went:.2f} m in 4 s")
        self.expect(crept < 0.5, f"after letting go of W the rover should stop: three seconds later it still "
                                 f"moved {crept:.2f} m in one second")
        self.finish()

    # =========================================================================
    # 4. The Workshop: change a design, make it, hold it
    # =========================================================================
    def lab_says(self, text):
        """Type into the Lab's chat and send it with Enter, as a player does."""
        before = self.js("document.querySelectorAll('#ws-chat-log .ws-chat-message.assistant').length")
        self.click("#ws-component-chat-text")
        self.page.send("Input.insertText", {"text": text})
        self.key("keyDown", "Enter", "Enter")
        self.key("keyUp", "Enter", "Enter")
        self.need(self.wait(f"document.querySelectorAll('#ws-chat-log .ws-chat-message.assistant').length > {before}"
                            " && !document.querySelector('#ws-component-chat-text').disabled", 60),
                  f"the Lab never answered {text!r}")
        return self.js("[...document.querySelectorAll('#ws-chat-log .ws-chat-message.assistant')].at(-1).innerText")

    def parts(self):
        return self.js("[...document.querySelectorAll('#ws-parts li')].map((e) => e.textContent)")

    def test_workshop_change_and_make(self):
        self.open_world()
        stowed_before = set(filter(None, self.js("banjoRoom.world.inventory?.record?.stowed || []") or []))
        # From the world's bar to the Workshop's Recipes, and the Camp stool into the Lab.
        self.click('.game-tabs [data-screen="recipes"]', "(the bar at the bottom of the world)")
        self.need(self.wait("!!document.querySelector('[data-recipe=\"stool:Camp stool\"]')", 30),
                  "Recipes does not list the Camp stool")
        self.click('[data-recipe="stool:Camp stool"] .ws-recipe-acts button:nth-child(2)')
        self.need(self.wait("document.querySelector('#workshop-stage')?.visibleGeometry?.()?.meshes > 0", 60),
                  "the Camp stool never appeared on the Lab's bench")
        self.need(self.wait("document.querySelectorAll('#ws-parts li').length >= 5", 20),
                  "the Lab lists none of the stool's parts")
        before = self.parts()
        self.step(f"opened the Camp stool in the Lab: {before}")
        said = self.lab_says("make the legs thicker")
        self.need(self.wait(f"JSON.stringify([...document.querySelectorAll('#ws-parts li')].map((e) => e.textContent))"
                            f" !== {json.dumps(json.dumps(before))}", 20),
                  f"asking the Lab to make the legs thicker changed nothing: it said {said!r}")
        after = self.parts()
        self.report["measured"]["design"] = {"before": before, "after": after, "lab_said": said}
        self.step(f"the Lab made the legs thicker: {after}")
        # Make it, the paid way: Make, review, prepare supplies, start, step, collect.
        time.sleep(1.0)
        ready = self.js("document.querySelector('#ws-make') && document.body.innerText.match(/Needs changes[^\\n]*/)?.[0]")
        self.need(not ready, f"the changed stool cannot be made: the Workshop says {ready!r} "
                             f"({self.js('document.body.innerText.match(/[^\\n]*overlaps[^\\n]*/)?.[0]')})")
        self.click("#ws-make")
        self.click("#ws-remake-review")
        for _ in range(10):
            self.need(self.wait("(document.querySelector('#ws-remake-start') && !document.querySelector('#ws-remake-start').disabled)"
                                " || document.querySelector('#ws-remake-prepare:not(:disabled)')", 30),
                      "the make never became ready: " + str(self.js("document.querySelector('#ws-remake')?.innerText.slice(0, 600)")))
            if self.js("!!document.querySelector('#ws-remake-start') && !document.querySelector('#ws-remake-start').disabled"):
                break
            self.click("#ws-remake-prepare")
            time.sleep(0.5)
        self.click("#ws-remake-start")
        for _ in range(20):
            self.need(self.wait("document.querySelector('#ws-remake-step:not(:disabled)') || "
                                "document.querySelector('#ws-remake-collect:not(:disabled)') || "
                                "document.querySelector('#ws-remake-place:not(:disabled)')", 60),
                      "making stalled: " + str(self.js("document.querySelector('#ws-remake')?.innerText.slice(0, 600)")))
            if self.js("!!document.querySelector('#ws-remake-collect:not(:disabled)')"):
                break
            self.click("#ws-remake-step")
            time.sleep(0.3)
        made = self.js("document.querySelector('#ws-remake')?.innerText.slice(0, 400)")
        self.step(f"made it: {made!r}")
        self.need(self.js("!!document.querySelector('#ws-remake-collect:not(:disabled)')"),
                  "the finished stool cannot be added to the inventory: " + str(made))
        self.click("#ws-remake-collect")
        self.need(self.wait("document.querySelector('#ws-remake')?.innerText.includes('In your Inventory')", 120),
                  "Add to Inventory never finished: " + str(self.js("document.querySelector('#ws-remake')?.innerText.slice(0, 600)")
                                                          + " " + str(self.js("document.querySelector('#ws-notice')?.textContent"))))
        self.step("added the stool to the inventory")
        jobs = (self.game.room.fabrication_record or {}).get("jobs") or {}
        self.need(jobs, "making left no job in the workbench's record")
        root = list(jobs.values())[-1].get("root_body")
        self.report["measured"]["made"] = {"root_body": root, "workshop_said": made}
        # Back to the world: the new stool in the strip, with a picture, and held from it.
        self.click('.game-tabs [data-screen="world"]')
        self.need(self.wait("window.banjoRoom?.ready()", 60), "the world did not come back from the Workshop")
        strip_item = f"#inventory-strip .strip-item[title*='stool' i]"
        found = self.wait(f"!!document.querySelector({json.dumps(strip_item)})", 20)
        strip = self.js("[...document.querySelectorAll('#inventory-strip .strip-item')].map((b) => "
                        "({title: b.title, img: !!b.querySelector('img'), loaded: !!b.querySelector('img')?.naturalWidth}))")
        self.report["measured"]["strip"] = strip
        self.expect(found, f"the new stool is not in the inventory strip: it holds {strip}")
        if found:
            pictured = self.wait(f"document.querySelector({json.dumps(strip_item + ' img')})?.naturalWidth > 0", 20)
            self.expect(pictured, "the new stool is in the inventory strip without a picture")
            stowed = set(filter(None, self.js("banjoRoom.world.inventory?.record?.stowed || []") or []))
            self.report["measured"]["new_in_bag"] = sorted(stowed - stowed_before)
            self.click(strip_item)
            held = self.wait("!!banjoRoom.held()", 15)
            self.report["measured"]["held"] = self.js("banjoRoom.held()")
            self.expect(held, "clicking the stool in the inventory strip did not put it in the hand")
        self.finish()

    # =========================================================================
    # 5. Point and click
    # =========================================================================
    def hover_names(self, name, label):
        at = self.look_at_thing(name)
        self.need(at and at["ahead"], f"the {name} is not in view")
        # Off it first, so the name has to come because of this move -- to a
        # point still inside the middle of the view, where the cursor turns
        # nothing (world.js LOOK_DEAD): near an edge it turns the view.
        aside = self.js("(() => { const r = document.querySelector('#stage').getBoundingClientRect();"
                        " return {x: r.x + r.width * 0.25, y: r.y + r.height * 0.35}; })()")
        self.mouse("mouseMoved", aside["x"], aside["y"])
        time.sleep(0.4)
        asked = time.monotonic()
        self.mouse("mouseMoved", at["x"], at["y"])
        named = self.wait("!document.getElementById('label').hidden && "
                          f"document.getElementById('label').textContent.toLowerCase().includes({json.dumps(label.lower())})",
                          3)
        took = time.monotonic() - asked
        self.report["measured"].setdefault("hover_name_s", {})[name] = round(took, 2) if named else None
        self.expect(named and took <= NAME_WITHIN_S,
                    f"hovering the {name} should show its name within {NAME_WITHIN_S} s: "
                    + (f"it took {took:.2f} s" if named else "it never showed ("
                       + str(self.js("document.getElementById('label').textContent")) + ")"))
        return at

    def panel_for(self, name):
        """A card about `name` that a player can see: the machine panel, or the
        side view's pinned card, on screen and not folded away."""
        return self.js(f"""(() => {{
          const seen = (e) => e && !e.hidden && e.getClientRects().length && getComputedStyle(e).visibility === 'visible'
            && e.getBoundingClientRect().right <= innerWidth + 1 && e.getBoundingClientRect().left >= -1;
          const said = (e) => (e.innerText || '').toLowerCase();
          const name = {json.dumps(name.lower())};
          for (const id of ['machine-panel', 'picked']) {{
            const e = document.getElementById(id);
            if (seen(e) && said(e).includes(name)) return id;
          }}
          return null;
        }})()""")

    def test_point_and_click(self):
        self.open_world()
        self.hover_names("solar farm", "Solar Farm")
        self.hover_names("camp light", "Camp Light")
        for name in ("rover", "solar farm"):
            notes = len(self.js("banjoRoom.status().errors") or [])
            self.hover_names(name, name)
            # The rover roams: press where it is now, not where it was hovered.
            at = self.on_screen(name)
            asked = time.monotonic()
            self.click_at(at["x"], at["y"])
            shown, took = None, None
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                shown = self.panel_for(name)
                if shown:
                    took = time.monotonic() - asked
                    break
                time.sleep(0.05)
            refused = (self.js("banjoRoom.status().errors") or [])[notes:]
            self.report["measured"].setdefault("click_panel", {})[name] = {
                "shown_in": shown, "after_s": None if took is None else round(took, 2),
                "refusals": [e.get("what") for e in refused]}
            self.expect(shown and took <= PANEL_WITHIN_S,
                        f"clicking the {name} should open its panel within {PANEL_WITHIN_S} s: "
                        + (f"it took {took:.2f} s" if shown else "nothing about it came on screen"))
            self.expect(not refused, f"clicking the {name} tried something the game refused: "
                                     f"{[e.get('what') for e in refused]}")
            self.step(f"clicked the {name}: {shown} after {took} s; refusals {[e.get('what') for e in refused]}")
            if self.js("!document.getElementById('machine-panel').hidden"):
                self.click("#mp-close")
            time.sleep(0.5)

        # The pick in hand: a click on a machine opens it instead of swinging.
        self.take_up_the_pick()
        self.watch_fetches("/api/world/tool/use")
        # No name shows while the hand holds something (world.js aim): the
        # crosshair being on the rover is what the player goes by.
        at = self.look_at_thing("rover")
        self.mouse("mouseMoved", at["x"], at["y"])
        on = self.wait("banjoRoom.world.aim?.name === 'rover'", 3)
        at = self.on_screen("rover")
        self.click_at(at["x"], at["y"])
        opened = self.wait("!document.getElementById('machine-panel').hidden", 3)
        time.sleep(0.5)
        swings = len(self.calls("/api/world/tool/use"))
        self.report["measured"]["pick_click_on_rover"] = {"crosshair_on_it": on, "panel": opened, "swings": swings}
        self.expect(opened, "with the pick in hand, clicking the rover should open its panel; it did not")
        self.expect(swings == 0, f"with the pick in hand, clicking the rover swung the pick {swings} time(s)")
        self.finish()


if __name__ == "__main__":
    unittest.main()
