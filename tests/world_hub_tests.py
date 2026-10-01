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
sys.path.insert(0, str(ROOT / "playground"))
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

    def post(self, path, body, world=None, player=None):
        headers = {"Content-Type": "application/json", "X-Banjo-Token": self.token}
        if world: headers["X-Banjo-World"] = world
        if world and path != "/api/world/player/join":
            headers["X-Banjo-Player"] = player or self.players[world]["token"]
        request = urllib.request.Request(self.base + path, method="POST", headers=headers,
                                         data=json.dumps(body).encode())
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def join(self, world, name):
        return self.post("/api/world/player/join", {"name": name}, world)

    def test_generated_worlds_are_isolated_and_joinable(self):
        first = self.post("/api/worlds", {"name": "First map"})
        second = self.post("/api/worlds", {"name": "Second map"})
        self.players = {first["id"]: self.join(first["id"], "Alice"),
                        second["id"]: self.join(second["id"], "Alice")}
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

    def test_each_guest_has_an_avatar_and_inventory(self):
        import inventory
        world = self.post("/api/worlds", {"name": "Together"})
        ident = world["id"]
        # Two lightweight world items are an explicit inventory fixture. The
        # generated starter map otherwise consists of installed machinery.
        room_path = Path(self.temp.name) / "rooms" / "worlds" / ident / "rooms" / "new-game.json"
        room = json.loads(room_path.read_text())
        for index, material in enumerate(("oak", "iron")):
            room["spec"]["bodies"].append({"name": f"player-test-{material}",
                "shape": "box", "material": material, "size_mm": [100, 100, 100],
                "center_mm": [-10000 + 20000 * index, 5000, 10000]})
        room_path.write_text(json.dumps(room))
        alice = self.join(ident, "Alice")
        bob = self.join(ident, "Bob")
        self.players = {ident: alice}
        opened = self.post("/api/world/open", {"scene": "new-game"}, ident)
        session = opened["session"]
        loose = [item for item in inventory.items_of(opened["spec"])
                 if item["name"].startswith("player-test-")]
        self.assertGreaterEqual(len(loose), 2)
        first, second = loose[:2]
        taken = self.post("/api/world/inventory", {"session": session, "request": "alice-take",
                          "op": "take", "item": first["name"]}, ident, alice["token"])
        self.assertTrue(taken["ok"], taken)
        bob_view = self.post("/api/world/inventory/shown", {"session": session}, ident, bob["token"])
        self.assertEqual([], bob_view["record"]["stowed"])
        refused = self.post("/api/world/inventory", {"session": session, "request": "bob-steal",
                            "op": "take", "item": first["name"]}, ident, bob["token"])
        self.assertFalse(refused["ok"])
        self.assertIn("another player", refused["why"])
        bob_took = self.post("/api/world/inventory", {"session": session, "request": "bob-take",
                             "op": "take", "item": second["name"]}, ident, bob["token"])
        self.assertTrue(bob_took["ok"], bob_took)
        self.assertNotEqual(taken["shown"]["record"]["stowed"], bob_took["shown"]["record"]["stowed"])
        def person_at(x):
            return {"standing_m": [x, 0, 10], "eyes_m": [x, 1.62, 10],
                    "facing": [0, 0, -1], "look_direction": [0, 0, -1]}
        alice_held = self.post("/api/world/inventory", {"session": session, "request": "alice-equip",
                                "revision": taken["record"]["revision"], "op": "equip",
                                "item": first["name"], "person": person_at(-10)}, ident, alice["token"])
        self.assertTrue(alice_held["ok"], alice_held)
        bob_held = self.post("/api/world/inventory", {"session": session, "request": "bob-equip-first",
                                "revision": bob_took["record"]["revision"], "op": "equip",
                                "item": second["name"], "person": person_at(10)}, ident, bob["token"])
        self.assertTrue(bob_held["ok"], bob_held)
        bob_rejoin = self.post("/api/world/open", {"scene": "new-game"}, ident, bob["token"])
        self.assertEqual(bob["id"], bob_rejoin["hand_owner"])
        self.assertEqual(second["name"], bob_rejoin["hand"]["holding"])
        self.assertEqual(first["name"], bob_rejoin["player_hands"][alice["id"]]["holding"])
        self.assertNotEqual({"right": None, "left": None}, bob_rejoin["inventory"]["record"]["hands"])
        # Each page sets only its own target. One shared physics step must
        # advance both grips; release by one guest must leave the other held.
        first_body = next(b for b in bob_rejoin["bodies"] if b["name"] == first["name"])
        second_body = next(b for b in bob_rejoin["bodies"] if b["name"] == second["name"])
        self.assertGreater(second_body["position_m"][0] - first_body["position_m"][0], 15)
        one_target = [first_body["position_m"][0] + .3, *first_body["position_m"][1:]]
        two_target = [second_body["position_m"][0] - .3, *second_body["position_m"][1:]]
        self.post("/api/live/act", {"session": session, "op": "move", "to": one_target},
                  ident, alice["token"])
        self.post("/api/live/act", {"session": session, "op": "move", "to": two_target},
                  ident, bob["token"])
        time.sleep(.12)
        moving = self.post("/api/live/act", {"session": session, "op": "step",
                           "dt": 1/240, "n": 24}, ident, alice["token"])
        self.assertEqual({first["name"], second["name"]},
                         {h["holding"] for h in moving["player_hands"].values() if h["holding"]})
        self.assertEqual(one_target, moving["player_hands"][alice["id"]]["target_m"])
        self.assertEqual(two_target, moving["player_hands"][bob["id"]]["target_m"])
        self.assertTrue(all(next(b for b in moving["bodies"] if b["name"] == name)["held"]
                            for name in (first["name"], second["name"])))
        one_moved = next(b for b in moving["bodies"] if b["name"] == first["name"])
        two_moved = next(b for b in moving["bodies"] if b["name"] == second["name"])
        self.assertGreater(one_moved["position_m"][0], first_body["position_m"][0] + .01)
        self.assertLess(two_moved["position_m"][0], second_body["position_m"][0] - .01)
        self.stop()
        self.start()
        self.post("/api/world/player/join", {"token": alice["token"]}, ident)
        self.post("/api/world/player/join", {"token": bob["token"]}, ident)
        resumed = self.post("/api/world/open", {"scene": "new-game"}, ident, bob["token"])
        session = resumed["session"]
        self.assertEqual(first["name"], resumed["player_hands"][alice["id"]]["holding"])
        self.assertEqual(second["name"], resumed["player_hands"][bob["id"]]["holding"])
        alice_stowed = self.post("/api/world/inventory", {"session": session, "request": "alice-stow",
                                  "op": "stow", "item": first["name"]}, ident, alice["token"])
        self.assertTrue(alice_stowed["ok"], alice_stowed)
        after_alice = self.post("/api/live/act", {"session": session, "op": "poses"}, ident, bob["token"])
        self.assertEqual(second["name"], after_alice["hand"]["holding"])
        bob_stowed = self.post("/api/world/inventory", {"session": session, "request": "bob-stow",
                                "op": "stow", "item": second["name"]}, ident, bob["token"])
        self.assertTrue(bob_stowed["ok"], bob_stowed)
        alice_bench = self.post("/api/workshop/inventory", {}, ident, alice["token"])
        bob_bench = self.post("/api/workshop/inventory", {}, ident, bob["token"])
        self.assertEqual({first["name"]}, {i["name"] for i in alice_bench["carried"]})
        self.assertEqual({second["name"]}, {i["name"] for i in bob_bench["carried"]})
        for person, eye in ((alice, [-10, 1.62, 10]), (bob, [10, 1.62, 10])):
            state = self.post("/api/live/act", {"session": session, "op": "step", "dt": 1/240,
                              "n": 1, "person": {"eyes_m": eye, "facing": [0, 0, -1]}},
                              ident, person["token"])
        self.assertEqual({alice["id"], bob["id"]}, {p["id"] for p in state["players"]})
        self.assertEqual([10, 1.62, 10], next(p["pose"]["eyes_m"] for p in state["players"]
                                            if p["id"] == bob["id"]))
        self.assertTrue(all("token" not in p for p in state["players"]))
        with self.assertRaises(urllib.error.HTTPError):
            self.post("/api/world/inventory/shown", {"session": session}, ident, "0" * 64)
        self.stop()
        self.start()
        alice = self.post("/api/world/player/join", {"token": alice["token"]}, ident)
        bob = self.post("/api/world/player/join", {"token": bob["token"]}, ident)
        self.players[ident] = alice
        restored = self.post("/api/world/open", {"scene": "new-game"}, ident, alice["token"])
        self.assertIn(first["name"], restored["inventory"]["record"]["stowed"])
        bob_view = self.post("/api/world/inventory/shown", {"session": restored["session"]},
                             ident, bob["token"])
        self.assertIn(second["name"], bob_view["record"]["stowed"])

    def test_solar_energy_market_is_personal_and_durable(self):
        world = self.post("/api/worlds", {"name": "Solar traders"})
        ident = world["id"]
        alice, bob = self.join(ident, "Alice"), self.join(ident, "Bob")
        self.players = {ident: alice}
        opened = self.post("/api/world/open", {"scene": "new-game"}, ident)
        source = next(s for s in opened["machines"]["stores"] if s["body"] == "solar farm")
        before = self.post("/api/workshop/market", {"action": "view"}, ident)
        self.assertEqual(0, before["balance_j"])
        self.assertTrue(before["bankable"])
        self.assertTrue(before["guidance"]["skill"])
        before_plan=before['guidance']['plan']
        self.assertEqual('build-camp',before_plan['goal']['id'])
        self.assertEqual('Camp stool',before_plan['name'])
        self.assertEqual(0,before_plan['lines'][0]['lots']) # Shared rack already funds this geometry.
        self.assertEqual(6,before['guidance']['supply_goal']['lines'][0]['lots'])
        self.assertIsNotNone(before_plan['estimated_total_j'])
        bob_before = self.post("/api/workshop/inventory", {}, ident, bob["token"])
        alice_before = self.post("/api/workshop/inventory", {}, ident, alice["token"])
        bank = {"action": "bank", "joules": 200, "request_id": "alice-first-deposit"}
        funded = self.post("/api/workshop/market", bank, ident)
        self.assertEqual(200, funded["balance_j"])
        self.assertEqual(200, self.post("/api/workshop/market", bank, ident)["balance_j"])
        native = self.post("/api/live/act", {"session": opened["session"], "op": "poses"}, ident)
        after_store = next(s for s in native["machines"]["stores"] if s["id"] == source["id"])
        self.assertAlmostEqual(source["charge_j"] - 200, after_store["charge_j"], places=4)
        oak = next(o for o in funded["offers"] if o["id"] == "oak-stock")
        bought = self.post("/api/workshop/market", {"action": "buy", "item_id": oak["id"],
                           "quoted_price_j": oak["price_j"], "request_id": "alice-oak"}, ident)
        self.assertEqual(200 - oak["price_j"], bought["balance_j"])
        after_plan=bought['guidance']['plan']
        self.assertAlmostEqual(.5,after_plan['lines'][0]['personal_kg'])
        self.assertEqual(0,after_plan['estimated_total_j'])
        self.assertEqual(before['guidance']['supply_goal']['estimated_total_j']-oak['price_j'],
                         bought['guidance']['supply_goal']['estimated_total_j'])
        self.assertEqual(5,bought['guidance']['supply_goal']['lines'][0]['lots'])
        bob_plan=self.post('/api/workshop/market',{},ident,bob['token'])['guidance']['plan']
        self.assertEqual(0,bob_plan['lines'][0]['personal_kg'])
        self.assertEqual(0,bob_plan['lines'][0]['lots'])
        self.assertEqual(6,self.post('/api/workshop/market',{},ident,bob['token'])['guidance']['supply_goal']['lines'][0]['lots'])
        self.assertGreater(next(o for o in bought["offers"] if o["id"] == "oak-stock")["price_j"],
                           oak["price_j"])
        alice_after = self.post("/api/workshop/inventory", {}, ident, alice["token"])
        bob_after = self.post("/api/workshop/inventory", {}, ident, bob["token"])
        def oak_kg(inventory):
            return next(r["mass_kg"] for r in inventory["materials"] if r["material"] == "oak")
        self.assertAlmostEqual(oak_kg(alice_before) + 0.5, oak_kg(alice_after), places=4)
        self.assertEqual(oak_kg(bob_before), oak_kg(bob_after))
        def recipe_oak(player_token):
            recipes = self.post("/api/workshop/recipes", {}, ident, player_token)["templates"]
            return next(line["held_kg"] for recipe in recipes if recipe.get("source") == "built-in"
                        for line in recipe.get("materials", []) if line["material"] == "oak")
        self.assertAlmostEqual(recipe_oak(bob["token"]) + 0.5,
                               recipe_oak(alice["token"]), places=2)
        self.assertEqual(0, self.post("/api/workshop/market", {}, ident, bob["token"])["balance_j"])
        with self.assertRaises(urllib.error.HTTPError):
            self.post("/api/workshop/market", {"action": "buy", "item_id": oak["id"],
                      "quoted_price_j": oak["price_j"], "request_id": "stale-oak"}, ident)
        self.stop()
        self.start()
        self.post("/api/world/player/join", {"token": alice["token"]}, ident)
        self.post("/api/world/player/join", {"token": bob["token"]}, ident)
        restored = self.post("/api/world/open", {"scene": "new-game"}, ident, alice["token"])
        saved_source = next(s for s in restored["machines"]["stores"] if s["body"] == "solar farm")
        self.assertAlmostEqual(after_store["charge_j"], saved_source["charge_j"], places=4)
        self.assertEqual(bought["balance_j"],
                         self.post("/api/workshop/market", {}, ident, alice["token"])["balance_j"])
        self.assertAlmostEqual(oak_kg(alice_after), oak_kg(
            self.post("/api/workshop/inventory", {}, ident, alice["token"])), places=4)

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
            self.fail(f"Browser did not reach: {expression}; URL={page.evaluate('location.href')}; "
                      f"exceptions={[e for e in page.events if e.get('method') == 'Runtime.exceptionThrown'][-2:]}")

        page.send("Page.navigate", {"url": self.base + "/world"})
        wait_for('!!document.querySelector("#game-menu")')
        page.evaluate('document.querySelector("[data-game-menu]").click()')
        self.assertTrue(page.evaluate('document.querySelector("#game-menu").open'))
        page.evaluate('document.querySelector("#game-menu-new input").value="Browser game";'
                      'document.querySelector("#game-menu-new").requestSubmit()')
        wait_for('location.search.includes("world=") && !!window.banjoRoom?.status().ready')
        world_id = page.evaluate('new URLSearchParams(location.search).get("world")')
        self.assertEqual("Browser game", self.get(f"/api/worlds/{world_id}")["name"])

        self.assertIn(world_id, page.evaluate('document.querySelector(".market-entry").href'))
        page.evaluate('document.querySelector(".market-entry").click()')
        wait_for('document.body.classList.contains("workshop-mode") && '
                 'document.querySelectorAll("[data-game-menu]").length === 2 && '
                 '!!document.querySelector("#game-menu")')
        wait_for('document.querySelector("[data-tab=market]")?.getAttribute("aria-selected") === "true" && '
                 'document.querySelector("#ws-market-offers")?.children.length > 0')
        self.assertEqual("0 J", page.evaluate('document.querySelector("#ws-market-balance").textContent'))
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
        self.assertNotEqual(page.evaluate('window.banjoRoom.status().player_id'),
                            other_page.evaluate('window.banjoRoom.status().player_id'))
        wait_for('window.banjoRoom.status().avatars === 1')
        self.assertEqual(1, other_page.evaluate('window.banjoRoom.status().avatars'))
        page.evaluate('window.banjoRoom.standAt(-10, 2, 10)')
        other_page.evaluate('window.banjoRoom.standAt(10, 2, 10)')
        self.assertAlmostEqual(-10, page.evaluate('window.banjoRoom.camera.position.x'))
        self.assertAlmostEqual(10, other_page.evaluate('window.banjoRoom.camera.position.x'))
        self.assertLessEqual(page.evaluate('window.banjoRoom.status().time_s') - first_time,
                             time.monotonic() - together_at + .3)
        exceptions = [event for event in page.events
                      if event.get("method") == "Runtime.exceptionThrown"]
        self.assertEqual([], exceptions[-3:])


if __name__ == "__main__":
    unittest.main()
