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

    def test_waiting_action_allows_world_clock_and_other_guest_to_run(self):
        world, owner, app = self.setup_world()
        guest = self.join(world, "Other guest")
        session = app.live.session.id
        target = app.room.spec["precise_rigid_bodies"][0]["name"]
        # An ordinary server-authored wait step exercises the real action
        # route. No tool outcome or physical result is mocked here.
        app.room.spec.setdefault("actions", []).append({"body": target,
            "label": "Observe briefly", "steps": [{"do": "wait", "seconds": .8}]})
        started = threading.Event()
        original = server.run_action
        def run(*args, **kwargs):
            started.set()
            return original(*args, **kwargs)
        result = []
        with mock.patch.object(server, "run_action", side_effect=run):
            worker = threading.Thread(target=lambda: result.append(self.post("/api/world/action",
                {"session": session, "object": target, "action": 0}, world)))
            worker.start()
            self.assertTrue(started.wait(3))
            before = app.live.session.state["t"]
            began = time.monotonic()
            self.assertTrue(app.clock._tick(.05))
            other = self.post("/api/live/act", {"session": session, "op": "poses"}, world, guest["token"])
            self.assertGreater(other["t"], before)
            self.assertLess(time.monotonic() - began, .6, "world waited for the action's sleep")
            worker.join(timeout=4)
        self.assertFalse(worker.is_alive())
        self.assertEqual(["Observe briefly"], result[0]["did"])

    def test_actual_machine_batch_is_personal_and_learning_outbox_recovers_after_restart(self):
        import machine_witness
        world, owner, app = self.setup_world()
        other = self.join(world, "Distant observer")
        session = app.live.session.id
        source = next(m for m in machine_witness.machines(app) if m["recipe"] == "smelt copper")
        at = source["at_m"]
        person = {"eyes_m": [at[0], at[1]+1.2, at[2]+2], "facing": [0,0,-1],
                  "look_direction": [0,-1.2,-2]}
        request = {"session": session, "machine": source["machine"], "person": person}
        self.post("/api/world/watch-machine", request, world)
        self.post("/api/world/watch-machine", request, world, other["token"])
        # Watching is not a remote subscription: this guest walks away before
        # the real source batch. The normal pose route supplies the position.
        self.post("/api/live/act", {"session":session,"op":"step","dt":1/60,"n":1,
            "person":{"eyes_m":[70,2,70],"facing":[1,0,0]}}, world, other["token"])
        journal = server.journal_of(app,owner["id"])
        with mock.patch.object(journal,"add_evidence",side_effect=OSError("journal write unavailable")):
            for i in range(200):
                if i % 30 == 0:
                    self.post("/api/world/watch-machine", request, world)
                app.clock._tick(.2)  # accelerated wall time, unchanged native dt
                if machine_witness.pending_of(app):
                    break
            self.assertTrue(machine_witness.pending_of(app), "No actual processing receipt")
            self.assertEqual(set(),journal.knows())
            saved = json.loads(app.store.path_of(app.room.scene).read_text(encoding="utf-8"))
            receipt = saved["machine_evidence_pending"][0]
            from copy import deepcopy
            for change in ("batch", "observer", "id", "quantities"):
                corrupt = deepcopy(receipt)
                if change == "batch": corrupt["batch"] += 100
                elif change == "observer": corrupt["evidence"]["observer"]["player"] = other["id"]
                elif change == "id": corrupt["evidence"]["id"] = "ev-0000000000"
                else: corrupt["evidence"]["result"]["made"] = {"copper":-1}
                with self.assertRaises(ValueError):
                    machine_witness.validate_pending([corrupt],saved["machine_runtime"],saved["players"])
            self.assertEqual(owner["id"],receipt["owner"])
            self.assertGreater(receipt["evidence"]["result"]["made_kg"],0)
            self.assertGreater(receipt["evidence"]["result"]["drawn_j"],0)
            self.assertEqual(set(),server.journal_of(app,other["id"]).knows())
            self.stop()
        self.start()
        self.post("/api/world/player/join", {"token":owner["token"]}, world)
        self.post("/api/world/open", {}, world)
        restored = self.app.hub.get(world)
        recovered = server.journal_of(restored,owner["id"])
        self.assertEqual({"smelting-copper"},recovered.knows())
        self.assertEqual({receipt["evidence"]["id"]},set(recovered.data["evidence"]))
        self.assertEqual(set(),server.journal_of(restored,other["id"]).knows())
        revision = recovered.data["revision"]
        server.keep_world(restored,"repeat observation checkpoint")
        self.assertEqual(revision,recovered.data["revision"])
        report = {"schema":"banjo.player-learning-acceptance.v1",
            "native_dt_s":1/240,"scene_cell_m":.05,"accelerated_clock_slice_s":.2,
            "source_machine":receipt["machine"],"source_batch":receipt["batch"],
            "observed_t_s":receipt["evidence"]["observer"]["t_s"],
            "saved_t_s":saved["world"]["t_s"],"result":receipt["evidence"]["result"],
            "learned":sorted(recovered.knows()),"other_guest_learned":[],
            "evidence_count":len(recovered.data["evidence"]),"restart_outbox_replayed_once":True,
            "provider_calls":0,"limits":receipt["evidence"]["limitations"]}
        output = ROOT/"build/player-learning"; output.mkdir(parents=True,exist_ok=True)
        (output/"acceptance.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        print("\n    personal machine witness: "+json.dumps(report))

    def test_skill_and_market_guidance_resolve_world_equipment_and_input_shortages(self):
        world, owner, app = self.setup_world()
        skills = self.post("/api/workshop/skills",{},world)
        tree = {t["id"]:t for t in skills["techniques"]}
        self.assertFalse(tree["rough-shaping-wood"]["within_reach"])
        self.assertIn("Missing example",tree["rough-shaping-wood"]["earned_by"][0]["says"])
        self.assertFalse(tree["burning-lime"]["within_reach"])
        self.assertIn("Missing equipment",tree["burning-lime"]["earned_by"][0]["says"])
        copper = tree["smelting-copper"]
        self.assertTrue(copper["within_reach"])
        location = copper["earned_by"][0]["locations"][0]
        self.assertEqual("watch-machine",location["action"])
        self.assertEqual(3,len(location["at_m"]))
        self.assertEqual("smelting-copper",self.post("/api/workshop/market",{},world)["guidance"]["skill"]["id"])
        # A shortage fixture removes input; it grants no stock or skill.
        intake = next(p for p in app.room.spec["goods"]["stockpiles"] if p["name"] == location["intake"])
        intake["holds"].clear()
        changed = next(t for t in self.post("/api/workshop/skills",{},world)["techniques"] if t["id"] == "smelting-copper")
        self.assertFalse(changed["within_reach"])
        self.assertTrue(any("intake needs" in m for m in changed["world_missing"]))

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
        # An unsourced compatibility callback is not a named-world batch.
        self.assertNotIn("smelting-copper", server.journal_of(app, shared=True).knows())
        self.assertNotIn("smelting-copper", server.journal_of(app, owner["id"]).knows())

    def test_realtime_rover_returns_bank_retries_reload_and_restart_agree(self):
        from mcp import ground_transfers, fabrication
        import world_access
        # A persistence experiment needs a reproducible source route. These
        # select ordinary generator seeds from the published playthrough;
        # they do not grant stock, change terrain or steer the native rover.
        # Random route viability is a separate, still-open navigation gate.
        with mock.patch.object(server.secrets,"randbelow",side_effect=[1,851269741]):
            world,owner,app=self.setup_world()
        app.clock.start()
        self.addCleanup(app.clock.stop)
        began=time.monotonic(); returned=False; requests=[]
        while time.monotonic()-began<150:
            receipt="realtime-bank-"+str(len(requests))
            bank=self.post("/api/workshop/market",{"action":"bank","joules":100,"request_id":receipt},world)
            requests.append(receipt)
            again=self.post("/api/workshop/market",{"action":"bank","joules":100,"request_id":receipt},world)
            self.assertEqual(bank["balance_j"],again["balance_j"])
            with world_access.state_lock(app):
                totals=ground_transfers.totals(getattr(app.room,"ground_transfers",None))
                returned=sum(totals["returned"].values())>.001
            if returned: break
            time.sleep(3)
        if not returned:
            output = ROOT/"build/player-learning"; output.mkdir(parents=True,exist_ok=True)
            diagnostic = {"terrain":app.room.spec.get("terrain"),
                "machines":app.live.session.state.get("machines"),
                "routines":{n:b.routine.summary() for n,b in app.brains.brains.items()},
                "ground_totals":totals,"t":app.live.session.state.get("t"),
                "elapsed_s":time.monotonic()-began,"clock":{"ticks":app.clock.ticks,
                    "world_s":app.clock.world_s,"trouble":app.clock.trouble}}
            (output/"rover-timeout.json").write_text(json.dumps(diagnostic,indent=2),encoding="utf-8")
        self.assertTrue(returned,"Generated realtime rover never returned a measurable load; see build/player-learning/rover-timeout.json")
        self.assertGreater(app.live.session.state["t"],.5*(time.monotonic()-began))
        # A disk refusal must not credit the attempted draw or hide the error.
        balance=again["balance_j"]
        with mock.patch.object(app.store,"_save",side_effect=OSError("test disk unavailable")):
            with self.assertRaises(urllib.error.HTTPError) as failed:
                self.post("/api/workshop/market",{"action":"bank","joules":100,"request_id":"recover-bank"},world)
            failure=json.load(failed.exception)
            self.assertEqual("failed",failure["persistence"]["state"])
            self.assertEqual(balance,self.post("/api/workshop/market",{},world)["balance_j"])
        recovered=self.post("/api/workshop/market",{"action":"bank","joules":100,"request_id":"recover-bank"},world)
        self.assertEqual(balance+100,recovered["balance_j"])
        for _ in range(2):
            self.assertEqual(balance+100,self.post("/api/workshop/market",{"action":"bank","joules":100,"request_id":"recover-bank"},world)["balance_j"])
        rejoined=self.post("/api/world/player/join",{"token":owner["token"]},world)
        self.assertEqual(owner["id"],rejoined["id"])
        self.post("/api/world/open",{},world)
        app.clock.stop()
        with world_access.state_lock(app):
            self.assertTrue(server.keep_world(app,"realtime acceptance checkpoint"))
            book=json.loads(json.dumps(app.room.ground_transfers))
            runtime=app.brains.runtime()
            fabrication.validate_ground_stock({},app.room.world_record,book)
        duration=time.monotonic()-began; native_t=app.room.world_record["t_s"]
        self.stop(); self.start()
        self.post("/api/world/player/join",{"token":owner["token"]},world)
        restored=self.post("/api/world/open",{},world)
        restarted=self.app.hub.get(world)
        self.assertEqual("whole",restored["restored"]["tier"])
        self.assertEqual(book,restarted.room.ground_transfers)
        self.assertEqual(runtime,restarted.brains.runtime())
        self.assertEqual(balance+100,self.post("/api/workshop/market",{},world)["balance_j"])
        fabrication.validate_ground_stock({},restarted.room.world_record,book)
        print(f"\n    generated realtime: {native_t:.3f} native s / {duration:.3f} wall s; "
              f"{len(book['receipts'])} ground receipts; returned {totals['returned']}; "
              f"wallet {balance+100} J, duplicate/failure/rejoin/restart checked")

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
        # Inspection may read native geometry while watching, but does not
        # permit controls or change either character's physical state.
        session_id = view["state"]["session"]
        native_before = self.post("/api/live/act", {"session":session_id, "op":"poses"}, world)
        page.evaluate('(()=>{const r=banjoRoom,n=[...r.world.bodies].find(([n,e])=>e.mechanicalModel!=="precise-rigid-v1")?.[0];r.pick(n)})()')
        wait_for('banjoRoom.reveal()?.kind === "cells"')
        native_after = self.post("/api/live/act", {"session":session_id, "op":"poses"}, world)
        for key in ("t", "bodies", "machines"):
            self.assertEqual(native_before[key], native_after[key], "watch inspection changed " + key)
        page.evaluate('banjoRoom.pick(null)')
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
