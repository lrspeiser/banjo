"""Generated worlds and shared sessions through the real HTTP/native path.

Run with BANJO_LIVE_ENGINE beside a built banjo_platform_cli. The test makes
two worlds on an isolated server, joins one twice, and opens the other without
evicting the first. It also checks the generated maps survive a restart.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import qa_browser  # noqa: E402
RUNNER = Path(os.environ.get("BANJO_LIVE_ENGINE", ""))
SUFFIX = ".exe" if os.name == "nt" else ""
ENGINE = RUNNER.with_name(f"banjo_platform_cli{SUFFIX}")


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@unittest.skipUnless(RUNNER.is_file() and ENGINE.is_file(), "native world engine not built")
class NamedWorlds(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.start()

    def tearDown(self):
        self.stop()
        self.temp.cleanup()

    def start(self):
        env = dict(os.environ, BANJO_LIVE_ENGINE=str(RUNNER), BANJO_WORLD_CLOCK="0",
                   OPENAI_API_KEY="")
        self.server = subprocess.Popen(
            [sys.executable, "-u", str(ROOT / "playground/server.py"),
             "--port", str(self.port), "--engine", str(ENGINE),
             "--rooms", str(Path(self.temp.name) / "rooms"),
             "--runs", str(Path(self.temp.name) / "runs")],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                self.token = self.get("/api/status")["csrf_token"]
                return
            except Exception:
                if self.server.poll() is not None: break
                time.sleep(.1)
        self.fail("world server did not start")

    def stop(self):
        self.server.terminate()
        try: self.server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.server.kill()
            self.server.wait(timeout=15)

    def get(self, path, world=None):
        headers = {"X-Banjo-World": world} if world else {}
        with urllib.request.urlopen(urllib.request.Request(self.base + path, headers=headers),
                                    timeout=30) as response:
            return json.load(response)

    def post(self, path, body, world=None):
        headers = {"Content-Type": "application/json", "X-Banjo-Token": self.token}
        if world: headers["X-Banjo-World"] = world
        request = urllib.request.Request(self.base + path, method="POST", headers=headers,
                                         data=json.dumps(body).encode())
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def test_generated_worlds_are_isolated_and_joinable(self):
        first = self.post("/api/worlds", {"name": "First map"})
        second = self.post("/api/worlds", {"name": "Second map"})
        self.assertNotEqual(first["id"], second["id"])
        self.assertIn(first["id"], first["url"])
        self.assertEqual("First map", self.get(f"/api/worlds/{first['id']}")["name"])
        saved = Path(self.temp.name) / "rooms" / "worlds"
        specs = [json.loads((saved / w["id"] / "rooms" / "new-game.json").read_text())
                 ["spec"] for w in (first, second)]
        self.assertNotEqual(specs[0]["goods"]["deposits"], specs[1]["goods"]["deposits"])
        self.assertNotEqual(saved / first["id"], saved / second["id"])

        a = self.post("/api/world/open", {"scene": "world"}, first["id"])
        b = self.post("/api/world/open", {"scene": "world"}, second["id"])
        joined = self.post("/api/world/open", {"scene": "new-game"}, first["id"])
        self.assertEqual("new-game", a["scene"])
        self.assertEqual(a["session"], joined["session"])
        self.assertNotEqual(a["session"], b["session"])
        self.assertEqual(first["id"], self.get("/api/status", first["id"])["world_id"])
        self.assertEqual(second["id"], self.get("/api/status", second["id"])["world_id"])

        began = time.monotonic()
        initial = a["t"]
        for _ in range(12):
            for session in (a["session"], joined["session"]):
                reply = self.post("/api/live/act", {"session": session, "op": "step",
                                                     "dt": 1/240, "n": 8, "moved": True}, first["id"])
                self.assertEqual(len(a["bodies"]), len(reply["bodies"]))
        self.assertLessEqual(reply["t"] - initial, time.monotonic() - began + .3,
                             "two viewers must not double the simulation rate")

        with self.assertRaises(urllib.error.HTTPError) as invalid:
            self.post("/api/world/open", {"scene": "new-game", "fresh": True}, first["id"])
        self.assertEqual(400, invalid.exception.code)
        with self.assertRaises(urllib.error.HTTPError) as missing:
            self.get("/api/status", "0" * 32)
        self.assertEqual(400, missing.exception.code)

        # The native state, including its clock, must survive a process that
        # exits without a final save. The normal five-second checkpoint is
        # exercised here against actual wall-time-limited steps.
        record = saved / first["id"] / "rooms" / "new-game.json"
        saved_time = 0.0
        for _ in range(40):
            time.sleep(.2)
            self.post("/api/live/act", {"session": a["session"], "op": "step",
                                        "dt": 1/240, "n": 48}, first["id"])
            saved_time = float(json.loads(record.read_text())["world"]["t_s"])
            if saved_time >= 5.0: break
        self.assertGreaterEqual(saved_time, 5.0, "native checkpoint was not kept")

        self.stop()
        self.start()
        reopened = self.post("/api/world/open", {"scene": "new-game"}, first["id"])
        def map_points(spec):
            return [(deposit["name"], deposit["at_m"])
                    for deposit in spec["goods"]["deposits"]]
        self.assertEqual(map_points(specs[0]), map_points(reopened["spec"]))
        self.assertGreaterEqual(reopened["t"], saved_time)
        self.assertEqual(first["id"], self.get("/api/status", first["id"])["world_id"])

    def test_menu_creates_and_joins_a_game_in_the_browser(self):
        if not qa_browser.CHROME.is_file():
            if os.environ.get("BANJO_BROWSER_TESTS") == "required":
                self.fail(f"Chrome is required at {qa_browser.CHROME}")
            self.skipTest("Chrome is not installed")
        chrome = qa_browser.Chrome(960, 600)
        self.addCleanup(chrome.close)
        page = chrome.page
        page.send("Page.enable")
        page.send("Runtime.enable")

        def wait_for(expression, seconds=30):
            until = time.monotonic() + seconds
            while time.monotonic() < until:
                try:
                    if page.evaluate(expression): return
                except (RuntimeError, TimeoutError): pass
                time.sleep(.2)
            self.fail(f"Browser did not reach: {expression}")

        page.send("Page.navigate", {"url": self.base + "/world"})
        wait_for('!!document.querySelector("#game-menu")')
        page.evaluate('document.querySelector("[data-game-menu]").click()')
        self.assertTrue(page.evaluate('document.querySelector("#game-menu").open'))
        page.evaluate('document.querySelector("#game-menu-new input").value="Browser game";'
                      'document.querySelector("#game-menu-new").requestSubmit()')
        wait_for('location.search.includes("world=") && !!window.banjoRoom?.status().ready')
        world_id = page.evaluate('new URLSearchParams(location.search).get("world")')
        self.assertEqual("Browser game", self.get(f"/api/worlds/{world_id}")["name"])

        page.send("Page.navigate", {"url": self.base + f"/world?world={world_id}&workshop=1"})
        wait_for('document.body.classList.contains("workshop-mode") && '
                 'document.querySelectorAll("[data-game-menu]").length === 2 && '
                 '!!document.querySelector("#game-menu")')
        self.assertTrue(page.evaluate('getComputedStyle(document.querySelectorAll("[data-game-menu]")[1]).display !== "none"'))
        page.evaluate('document.querySelectorAll("[data-game-menu]")[1].click()')
        self.assertTrue(page.evaluate('document.querySelector("#game-menu").open'))

        page.send("Page.navigate", {"url": self.base + "/world"})
        wait_for('!!document.querySelector("#game-menu-join")')
        page.evaluate('document.querySelector("[data-game-menu]").click();'
                      f'document.querySelector("#game-menu-join input").value="{world_id}";'
                      'document.querySelector("#game-menu-join").requestSubmit()')
        wait_for(f'location.search.includes("world={world_id}") && !!window.banjoRoom?.status().ready')
        first_session = page.evaluate('window.banjoRoom.status().session')
        first_time = page.evaluate('window.banjoRoom.status().time_s')
        together_at = time.monotonic()
        other_chrome = qa_browser.Chrome(960, 600)
        self.addCleanup(other_chrome.close)
        other_page = other_chrome.page
        other_page.send("Page.enable")
        other_page.send("Page.navigate", {"url": self.base + f"/world?world={world_id}&scene=new-game"})
        until = time.monotonic() + 30
        while time.monotonic() < until:
            try:
                if other_page.evaluate('!!window.banjoRoom?.status().ready'): break
            except (RuntimeError, TimeoutError): pass
            time.sleep(.2)
        else: self.fail("Second browser could not join the running world")
        self.assertEqual(first_session, other_page.evaluate('window.banjoRoom.status().session'))
        self.assertEqual(first_session, page.evaluate('window.banjoRoom.status().session'))
        self.assertLessEqual(page.evaluate('window.banjoRoom.status().time_s') - first_time,
                             time.monotonic() - together_at + .3)
        exceptions = [event for event in page.events
                      if event.get("method") == "Runtime.exceptionThrown"]
        self.assertEqual([], exceptions[-3:])


if __name__ == "__main__":
    unittest.main()
