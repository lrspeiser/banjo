"""Autonomous guest isolation, model decisions, restart and read-only watching."""
from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "playground"), str(ROOT / "tests"), str(ROOT)]
import server
import room_store
import ai_player
import world_hub_tests as hub
import qa_browser
import knowledge_tests


class ControllerBoundaries(unittest.TestCase):
    def test_reference_controller_stops_at_the_decision_budget(self):
        manager = ai_player.Manager.__new__(ai_player.Manager)
        manager.app = SimpleNamespace()
        manager.cadence_s = 0
        profile = {"pose": {}, "ai": {"mode": "reference", "history": [], "decisions": 0}}
        goals = {"complete": False, "next_goal": "bank-solar"}
        manager._post = lambda p, path, body, cookie: goals if path.endswith("goals") else {}
        manager._save = lambda p, **updates: p["ai"].update(updates)
        actions = []
        def execute(*args):
            actions.append(args[3]); return {"unit_fixture": True}
        manager._execute = execute
        manager._run(profile, threading.Event(), "")
        self.assertEqual(ai_player.MAX_DECISIONS, len(actions))
        self.assertEqual("blocked", profile["ai"]["status"])
        self.assertIn("budget", profile["ai"]["message"])

    def test_named_ground_work_is_attributed_to_the_striking_player_and_tool(self):
        with tempfile.TemporaryDirectory() as temp:
            alice, bob = "a" * 32, "b" * 32
            session = SimpleNamespace(id="fixture", room_spec=knowledge_tests.PICK_ROOM,
                state={"player_hands": {alice: {"holding": "pick haft"}, bob: {"holding": "other tool"}}})
            app = SimpleNamespace(world_id="c" * 32, journal_lock=threading.RLock(), player_journals={},
                store=room_store.RoomStore(temp), room=SimpleNamespace(spec=knowledge_tests.PICK_ROOM),
                live=SimpleNamespace(session=session))
            for owner in (alice, bob):
                scope = server.workshop_library.REQUEST_OWNER.set(owner)
                try: server.note_strike(app, {"t": 3.1})
                finally: server.workshop_library.REQUEST_OWNER.reset(scope)
            server.hear(app, session, {"ground_work": [knowledge_tests.closed("broke out")]})
            self.assertEqual(1, len(server.journal_of(app, alice).data["evidence"]))
            self.assertEqual({}, server.journal_of(app, bob).data["evidence"])
            scope = server.workshop_library.REQUEST_OWNER.set(bob)
            try:
                self.assertIs(server.journal_of(app), server.journal_of(app, bob))
                self.assertIsNot(server.journal_of(app), server.journal_of(app, shared=True))
            finally: server.workshop_library.REQUEST_OWNER.reset(scope)
            server.hear(app, session, {"ground_work": [knowledge_tests.closed("broke out")]})
            self.assertEqual(1, len(server.journal_of(app, alice).data["evidence"]))
            server.hear(app, session, {"ground_work": [knowledge_tests.closed("broke out", at_s=20)]})
            self.assertEqual(1, len(server.journal_of(app, alice).data["evidence"]))


@unittest.skipUnless(hub.RUNNER.is_file() and hub.ENGINE.is_file(), "native world engine not built")
class AutonomousGuests(unittest.TestCase):
    get, post, join = hub.NamedWorlds.get, hub.NamedWorlds.post, hub.NamedWorlds.join

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.port = hub.free_port(); self.base = f"http://127.0.0.1:{self.port}"
        self.config = mock.patch.object(server, "local_configuration", return_value=("", "gpt-5-mini"))
        self.config.start(); self.addCleanup(self.config.stop)
        self.environment = mock.patch.dict(os.environ, {"BANJO_WORLD_CLOCK": "0", "BANJO_LIVE_ENGINE": str(hub.RUNNER)})
        self.environment.start(); self.addCleanup(self.environment.stop)
        self.start()

    def start(self):
        self.app = server.Playground(hub.ENGINE, hub.ENGINE, Path(self.temp.name) / "runs")
        self.app.store = room_store.RoomStore(Path(self.temp.name) / "rooms")
        self.app.hub = server.WorldHub(self.app)
        self.app.password = None; self.app.public_host = None
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), server.Handler)
        self.httpd.app = self.app
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True); self.thread.start()
        self.token = self.get("/api/status")["csrf_token"]

    def stop(self):
        for app in list(self.app.hub.apps.values()):
            if getattr(app, "ai_players", None):
                app.ai_players.shutdown()
                for worker, _ in app.ai_players.workers.values(): worker.join(timeout=8)
        self.httpd.shutdown(); self.httpd.server_close(); self.thread.join(timeout=3)
        self.app.hub.shutdown(); self.app.live.shutdown(); self.app.pool.shutdown(wait=False)

    def tearDown(self):
        self.stop(); self.temp.cleanup()

    def setup_world(self):
        world = self.post("/api/worlds", {"name": "AI camp"})["id"]
        owner = self.join(world, "Human"); self.players = {world: owner}
        self.post("/api/world/open", {}, world)
        self.post("/api/world/ai", {"action": "list"}, world)
        app = self.app.hub.get(world)
        app.ai_players.cadence_s = .02
        return world, owner, app

    def wait_character(self, world, ident, states=("complete", "blocked"), seconds=40):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            view = self.post("/api/world/ai", {"action": "watch", "id": ident}, world)
            if view["character"]["status"] in states: return view
            time.sleep(.15)
        self.fail("Character never reached a terminal state")

    def test_model_selected_actions_complete_real_goals_with_separate_bag_and_tech_tree(self):
        world, owner, app = self.setup_world()
        calls = []
        class FakeModel:
            def ask(self, state, questions):
                offered = list(questions["next"]["criteria"])
                desired = {"bank-solar": "bank", "stock-oak": "buy_oak", "build-camp": "build_stool",
                           "carry-camp": "pack_stool"}[state["next_goal"]]
                pick = desired if desired in offered else "bank"
                calls.append(state)
                return {"next": {"choice": pick, "confidence": .9}}
        app.api_key = "test-only-key"
        app.ai_players.decider_factory = FakeModel
        bot = self.post("/api/world/ai", {"action": "start", "mode": "openai", "name": "AI explorer"}, world)
        final = self.wait_character(world, bot["id"])
        self.assertEqual("complete", final["character"]["status"], final["character"])
        self.assertTrue(final["goals"]["complete"])
        self.assertEqual(10, len(calls))
        self.assertIn("inventory", calls[0])
        self.assertIn("tech_tree", calls[0])
        self.assertTrue(all(e["mode"] == "openai" and e["result"] == "committed" for e in final["character"]["history"]))
        self.assertEqual([3, 1.2], [final["character"]["pose"]["eyes_m"][i] for i in (0, 2)])
        self.assertIn(final["goals"]["camp_body"], final["state"]["inventory"]["record"]["stowed"])
        human = self.post("/api/world/inventory/shown", {"session": final["state"]["session"]}, world)
        self.assertEqual([], human["record"]["stowed"])
        self.assertEqual(0, self.post("/api/workshop/market", {}, world)["balance_j"])
        self.assertFalse(self.post("/api/workshop/goals", {}, world)["complete"])
        bot_profile = app.room.player_records[bot["id"]]
        self.assertNotIn(bot_profile["token"], json.dumps(final))
        # Controlled journal fixture checks ownership/routing, not earned physics.
        server.journal_of(app, bot["id"]).learn("rough-shaping-wood", {"kind": "unit-fixture"}, "test")
        bot_tree = self.post("/api/world/ai", {"action": "watch", "id": bot["id"]}, world)["skills"]
        self.assertTrue(next(s for s in bot_tree if s["id"] == "rough-shaping-wood")["known"])
        self.assertFalse(next(s for s in self.post("/api/workshop/skills", {}, world)["techniques"]
                              if s["id"] == "rough-shaping-wood")["known"])
        headers = {"X-Banjo-World": world, "X-Banjo-Player": owner["token"]}
        with urllib.request.urlopen(urllib.request.Request(self.base + "/api/knowledge", headers=headers)) as response:
            self.assertEqual([], json.load(response)["techniques"])
        self.stop(); self.start()
        self.post("/api/world/player/join", {"token": owner["token"]}, world)
        self.post("/api/world/open", {}, world)
        restored = self.post("/api/world/ai", {"action": "watch", "id": bot["id"]}, world)
        self.assertTrue(restored["goals"]["complete"])
        self.assertIn(restored["goals"]["camp_body"], restored["state"]["inventory"]["record"]["stowed"])
        self.assertTrue(next(s for s in restored["skills"] if s["id"] == "rough-shaping-wood")["known"])

    def test_pause_during_model_call_executes_no_choice_and_foreign_guest_cannot_control(self):
        world, owner, app = self.setup_world()
        entered, release = threading.Event(), threading.Event()
        class WaitingModel:
            def ask(self, state, questions):
                entered.set(); release.wait(5)
                return {"next": {"choice": "bank", "confidence": .9}}
        app.api_key = "test-only-key"; app.ai_players.decider_factory = WaitingModel
        bot = self.post("/api/world/ai", {"action": "start", "mode": "openai"}, world)
        self.assertTrue(entered.wait(15))
        other = self.join(world, "Other")
        with self.assertRaises(urllib.error.HTTPError):
            self.post("/api/world/ai", {"action": "pause", "id": bot["id"]}, world, other["token"])
        self.post("/api/world/ai", {"action": "pause", "id": bot["id"]}, world)
        release.set(); app.ai_players.workers[bot["id"]][0].join(timeout=8)
        view = self.post("/api/world/ai", {"action": "watch", "id": bot["id"]}, world)
        self.assertEqual("paused", view["character"]["status"])
        self.assertEqual(0, view["goals"]["balance_j"])
        self.assertEqual(0, view["character"]["decisions"])
        self.stop(); self.start()
        self.post("/api/world/open", {}, world)
        self.assertEqual("paused", self.post("/api/world/ai", {"action": "list"}, world)["characters"][0]["status"])

    def test_unsupported_model_choice_is_refused_without_a_game_action(self):
        world, owner, app = self.setup_world()
        class InvalidModel:
            def ask(self, state, questions):
                return {"next": {"choice": "invent_money", "confidence": 1}}
        app.api_key = "test-only-key"; app.ai_players.decider_factory = InvalidModel
        bot = self.post("/api/world/ai", {"action": "start", "mode": "openai"}, world)
        view = self.wait_character(world, bot["id"])
        self.assertEqual("blocked", view["character"]["status"])
        self.assertEqual(0, view["character"]["decisions"])
        self.assertEqual(0, view["goals"]["balance_j"])
        self.assertFalse(view["goals"]["complete"])

    def test_stepping_guest_does_not_inherit_an_unowned_machine_batch(self):
        world, owner, app = self.setup_world()
        scope = server.workshop_library.REQUEST_OWNER.set(owner["id"])
        try: app.brains.on_made("smelt copper", {"copper": 1.5}, {"copper ore": 5.0})
        finally: server.workshop_library.REQUEST_OWNER.reset(scope)
        self.assertIn("smelting-copper", server.journal_of(app, shared=True).knows())
        self.assertNotIn("smelting-copper", server.journal_of(app, owner["id"]).knows())

    def test_menu_starts_reference_bot_and_camera_watches_without_control(self):
        if not qa_browser.CHROME.is_file():
            if os.environ.get("BANJO_BROWSER_TESTS") == "required": self.fail("Chrome is required")
            self.skipTest("Chrome not installed")
        world, owner, app = self.setup_world()
        chrome = qa_browser.Chrome(1280, 800); self.addCleanup(chrome.close)
        page = chrome.page; page.send("Page.enable"); page.send("Runtime.enable"); page.send("Network.enable")
        def wait_for(expression, seconds=45):
            until = time.monotonic() + seconds
            while time.monotonic() < until:
                try:
                    if page.evaluate(expression): return
                except (RuntimeError, TimeoutError): pass
                time.sleep(.15)
            self.fail(f"Browser did not reach {expression}; " + str(page.evaluate('document.querySelector("#panel-state")?.textContent')))
        page.send("Page.navigate", {"url": self.base + f"/world?world={world}"})
        wait_for('!!window.banjoRoom?.status().ready')
        viewer_id = page.evaluate('window.banjoRoom.status().player_id')
        viewer_token = page.evaluate(f'localStorage.getItem("banjo.player.{world}")')
        before = self.post("/api/world/inventory/shown", {"session": page.evaluate('window.banjoRoom.status().session')}, world, viewer_token)
        page.evaluate('document.querySelector("[data-game-menu]").click()')
        wait_for('document.querySelector("#game-menu-ai-start select").value === "reference"')
        page.evaluate('document.querySelector("#game-menu-ai-start").requestSubmit()')
        wait_for('location.search.includes("watch=") && !!window.banjoRoom?.status().ready && !!document.querySelector("#watch-status")')
        bot_id = page.evaluate('new URLSearchParams(location.search).get("watch")')
        wait_for('document.querySelector("#watch-status").textContent.includes("complete")')
        view = self.post("/api/world/ai", {"action": "watch", "id": bot_id}, world)
        self.assertEqual(viewer_id, page.evaluate('window.banjoRoom.status().player_id'))
        camera = page.evaluate('window.banjoRoom.camera.position.toArray()')
        for a, b in zip(camera, view["character"]["pose"]["eyes_m"]): self.assertAlmostEqual(a, b, places=2)
        after = self.post("/api/world/inventory/shown", {"session": view["state"]["session"]}, world, viewer_token)
        self.assertEqual(before["record"], after["record"])
        self.assertTrue(page.evaluate('document.querySelector("#watch-tech").textContent.startsWith("Its tech tree: 0 /")'))
        self.assertEqual("4 / 4 goals", page.evaluate('document.querySelector("#watch-progress").textContent').split(' · ')[0])
        # Clear navigation/agent startup events. Watching renders and polls;
        # it never sends live controls, human pose updates or inventory writes.
        self.assertFalse([e for e in page.events if e.get("method") == "Runtime.exceptionThrown"])
        page.events.clear(); page.send("Input.dispatchKeyEvent", {"type":"keyDown", "key":"w", "code":"KeyW"})
        time.sleep(.6); page.send("Input.dispatchKeyEvent", {"type":"keyUp", "key":"w", "code":"KeyW"})
        urls = [e["params"]["request"]["url"] for e in page.events if e.get("method") == "Network.requestWillBeSent"]
        self.assertFalse([u for u in urls if "/api/live/act" in u or "/api/world/inventory" in u])
        self.assertFalse([e for e in page.events if e.get("method") == "Runtime.exceptionThrown"])
        out = ROOT / "build/ai-player"; out.mkdir(parents=True, exist_ok=True)
        import base64
        (out / "watching.png").write_bytes(base64.b64decode(page.send("Page.captureScreenshot")["data"]))
        page.evaluate('document.querySelector("#watch-return").click()')
        wait_for('!location.search.includes("watch=") && !!window.banjoRoom?.status().ready')
        self.assertEqual(viewer_id, page.evaluate('window.banjoRoom.status().player_id'))


if __name__ == "__main__": unittest.main()
