"""Opening-goal playthrough over real HTTP + native simulation, no free stock.

The bounded agent chooses its next action from observed goals, market quotes
and refusals. This is a reproducible planner, not an LLM-success judgement.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import unittest
import urllib.error
import uuid
from types import SimpleNamespace
from unittest import mock
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "playground"), str(ROOT)]
import world_hub_tests as hub
import qa_browser
import starter_goals
import room_store


def play_first_camp(client, world, player):
    """An agent reads server evidence, then executes only normal player APIs."""
    trace = []
    for _ in range(32):
        goals = client.post("/api/workshop/goals", {}, world, player)
        step = goals["next_goal"]
        if step is None:
            return {"complete": True, "trace": trace, "goals": goals}
        key = uuid.uuid4().hex
        if step == "bank-solar":
            reply = client.post("/api/workshop/market", {"action": "bank", "joules": 500,
                                                       "request_id": key}, world, player)
        elif step == "stock-oak":
            market = client.post("/api/workshop/market", {}, world, player)
            oak = next(o for o in market["offers"] if o["id"] == "oak-stock")
            if market["balance_j"] < oak["price_j"]:
                reply = client.post("/api/workshop/market", {"action": "bank", "joules": 500,
                                                           "request_id": key}, world, player)
            else:
                if not oak["remaining"]:
                    raise AssertionError("Oak sold out; goal awaits trader restock")
                reply = client.post("/api/workshop/market", {"action": "buy", "item_id": oak["id"],
                    "quoted_price_j": oak["price_j"], "request_id": key}, world, player)
        elif step == "build-camp":
            source = client.post("/api/world/workshop/context", {}, world, player)
            preview = client.post("/api/world/workshop/preview", {"session": source["session"],
                "scene": source["scene"], "mode": "authoring", "candidate": goals["recipe"],
                "position_m": [3, 0]}, world, player)
            if not preview["needs"]["enough"]:
                raise AssertionError("The purchased starter supplies cannot cover the build")
            room_path = Path(client.temp.name) / "rooms" / "worlds" / world / "rooms" / "new-game.json"
            before_players = json.loads(room_path.read_text())["players"]
            reply = client.post("/api/world/workshop/commit", {"session": preview["session"],
                "scene": preview["scene"], "preview_id": preview["preview_id"], "request_id": key}, world, player)
            if not reply["native_precise_geometry_verified"] or not reply["resources_charged"]:
                raise AssertionError("Build did not pass native admission and resource debit")
            saved = json.loads(room_path.read_text())
            if saved.get("players") != before_players:
                raise AssertionError("Installation changed or omitted a guest profile or bag")
        elif step == "carry-camp":
            reply = client.post("/api/world/inventory", {"session": goals["session"], "op": "take",
                "item": goals["camp_body"], "request": key}, world, player)
            if not reply["ok"]:
                raise AssertionError(reply)
        else:
            raise AssertionError(f"No supported action for {step}")
        trace.append({"goal": step, "request_id": key,
                      "balance_j": reply.get("balance_j"), "status": reply.get("status"),
                      "mass_kg": reply.get("mass_kg"), "ok": reply.get("ok")})
    raise AssertionError("Opening goals exceeded the bounded 32-action budget")


@unittest.skipUnless(hub.RUNNER.is_file() and hub.ENGINE.is_file(), "native world engine not built")
class StarterGoals(unittest.TestCase):
    setUp, tearDown = hub.NamedWorlds.setUp, hub.NamedWorlds.tearDown
    start, stop = hub.NamedWorlds.start, hub.NamedWorlds.stop
    get, post, join = hub.NamedWorlds.get, hub.NamedWorlds.post, hub.NamedWorlds.join

    def test_two_players_complete_from_earned_energy_and_keep_progress_after_restart(self):
        world = self.post("/api/worlds", {"name": "First camp"})["id"]
        alice, bob = self.join(world, "Alice"), self.join(world, "Bob")
        self.players = {world: alice}
        opened = self.post("/api/world/open", {}, world)
        source = next(s for s in opened["machines"]["stores"] if s["body"] == "solar farm")
        result = play_first_camp(self, world, alice["token"])
        self.assertTrue(result["complete"])
        self.assertAlmostEqual(2.5088, result["goals"]["recipe_mass_kg"])
        # Only purchased personal stock is used; the communal rack is intact.
        rack = self.post("/api/workshop/inventory", {}, world)
        oak = next(r for r in rack["materials"] if r["material"] == "oak")
        self.assertAlmostEqual(.4912, oak["personal_kg"])
        self.assertAlmostEqual(12.4, oak["shared_kg"])
        bob_view = self.post("/api/workshop/goals", {}, world, bob["token"])
        self.assertEqual("bank-solar", bob_view["next_goal"])
        self.assertTrue(all(not g["complete"] for g in bob_view["goals"]))
        second = play_first_camp(self, world, bob["token"])
        self.assertTrue(second["complete"])
        self.assertNotEqual(result["goals"]["camp_body"], second["goals"]["camp_body"])
        native = self.post("/api/world/open", {}, world)
        charge = next(s["charge_j"] for s in native["machines"]["stores"] if s["id"] == source["id"])
        self.assertAlmostEqual(source["charge_j"] - 2000, charge, places=4)
        # Another player's recipe cannot be reported as my build by name alone.
        with self.assertRaises(urllib.error.HTTPError):
            self.post("/api/workshop/goals", {"complete": True}, world)
        self.stop(); self.start()
        for player in (alice, bob):
            self.post("/api/world/player/join", {"token": player["token"]}, world)
            self.post("/api/world/open", {}, world, player["token"])
            restored = self.post("/api/workshop/goals", {}, world, player["token"])
            self.assertTrue(restored["complete"])
            bag = self.post("/api/world/inventory/shown", {"session": restored["session"]}, world, player["token"])
            self.assertIn(restored["camp_body"], bag["record"]["stowed"])

    def test_wrong_geometry_or_another_builders_receipt_does_not_earn_goal(self):
        world = self.post("/api/worlds", {"name": "Evidence"})["id"]
        alice = self.join(world, "Alice"); self.players = {world: alice}
        self.post("/api/world/open", {}, world)
        context = self.post("/api/world/workshop/context", {}, world)
        candidate = starter_goals.recipe()
        candidate["parameters"]["width_m"] = .3
        preview = self.post("/api/world/workshop/preview", {"session": context["session"],
            "scene": context["scene"], "mode": "authoring", "candidate": candidate,
            "position_m": [3, 0]}, world)
        self.post("/api/world/workshop/commit", {"session": preview["session"], "scene": preview["scene"],
            "preview_id": preview["preview_id"], "request_id": "wrong-stool-geometry"}, world)
        self.assertFalse(self.post("/api/workshop/goals", {}, world)["goals"][2]["complete"])

    def test_browser_can_complete_every_goal_using_visible_controls(self):
        if not qa_browser.CHROME.is_file():
            if os.environ.get("BANJO_BROWSER_TESTS") == "required": self.fail("Chrome is required")
            self.skipTest("Chrome not installed")
        world = self.post("/api/worlds", {"name": "Browser camp"})["id"]
        chrome = qa_browser.Chrome(1280, 800); self.addCleanup(chrome.close)
        page = chrome.page; page.send("Page.enable"); page.send("Runtime.enable")
        def wait_for(expression):
            until = time.monotonic() + 30
            while time.monotonic() < until:
                try:
                    if page.evaluate(expression): return
                except (RuntimeError, TimeoutError): pass
                time.sleep(.15)
            self.fail(f"Browser did not reach {expression}; status=" + str(page.evaluate(
                'document.querySelector("#ws-goals-status")?.textContent')))
        page.send("Page.navigate", {"url": self.base + f"/world?world={world}&workshop=1&tab=goals"})
        wait_for('!!document.querySelector("[data-goal-action=bank-solar]")')
        page.evaluate('document.querySelector("[data-goal-action=bank-solar]").click()')
        wait_for('!!document.querySelector("[data-goal-action=stock-oak]")')
        page.evaluate('document.querySelector("[data-goal-bank]").click()')
        wait_for('document.querySelector("#ws-goals-progress").textContent.includes("1000 J")')
        for count in range(6):
            page.evaluate('document.querySelector("[data-goal-action=stock-oak]").click()')
            if count < 5:
                wait_for(f'document.querySelector("[data-goal=stock-oak]").textContent.includes("{(count+1)*.5:g} / 3 kg")')
            else:
                wait_for('!!document.querySelector("[data-goal-action=build-camp]")')
        page.evaluate('document.querySelector("[data-goal-action=build-camp]").click()')
        wait_for('!!document.querySelector("[data-goal-action=carry-camp]")')
        page.evaluate('document.querySelector("[data-goal-action=carry-camp]").click()')
        wait_for('document.querySelector("#ws-goals-progress").textContent.includes("First camp complete")')
        page.send("Page.reload")
        wait_for('document.querySelector("#ws-goals-progress")?.textContent.includes("First camp complete")')
        self.assertFalse([e for e in page.events if e.get("method") == "Runtime.exceptionThrown"])
        out = ROOT / "build" / "starter-goals"; out.mkdir(parents=True, exist_ok=True)
        import base64
        (out / "completed.png").write_bytes(base64.b64decode(page.send("Page.captureScreenshot")["data"]))


class DurableEvidence(unittest.TestCase):
    def test_unsaved_inventory_does_not_award_packing(self):
        with tempfile.TemporaryDirectory() as temp:
            store = room_store.RoomStore(Path(temp))
            body = "workshop-camp"
            receipt = {"status": "installed", "owner_id": "alice", "root_body": body,
                       "request_id": "native-build", "resources_charged": True,
                       "matter_physics_hash": starter_goals._recipe()[1]}
            room = SimpleNamespace(scene="new-game", spec={"precise_rigid_bodies": [{"name": body}]},
                chat=[], workshop_installs=[receipt], player_records={"alice": {"inventory": {}}})
            store.save(room)
            app = SimpleNamespace(world_id="world", room=room, store=store,
                live_holder="world", live=SimpleNamespace(session=SimpleNamespace(id="native")),
                runs_path=Path(temp) / "runs")
            shown = {"record": {"stowed": [body], "hands": {}, "revision": 1}}
            with mock.patch.object(starter_goals.inventory_room, "shown", return_value=shown):
                self.assertFalse(starter_goals.view(app, "alice", {})["goals"][3]["complete"])
                room.player_records["alice"]["inventory"] = shown["record"]
                store.save(room)
                self.assertTrue(starter_goals.view(app, "alice", {})["goals"][3]["complete"])


if __name__ == "__main__": unittest.main()
