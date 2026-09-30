"""Inventory selection, an empty Lab and shared right-side navigation."""
from __future__ import annotations
import base64
import json
import os
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "playground"), str(ROOT)]
import ai_player_tests as guests
import qa_browser


@unittest.skipUnless(guests.hub.RUNNER.is_file() and guests.hub.ENGINE.is_file(), "native world engine not built")
class GameScreens(unittest.TestCase):
    get, post, join = guests.AutonomousGuests.get, guests.AutonomousGuests.post, guests.AutonomousGuests.join
    setUp, tearDown = guests.AutonomousGuests.setUp, guests.AutonomousGuests.tearDown
    start, stop, setup_world = guests.AutonomousGuests.start, guests.AutonomousGuests.stop, guests.AutonomousGuests.setup_world

    def browser(self, world, owner):
        if not qa_browser.CHROME.is_file():
            if os.environ.get("BANJO_BROWSER_TESTS") == "required": self.fail("Chrome is required")
            self.skipTest("Chrome not installed")
        chrome = qa_browser.Chrome(1440, 900); self.addCleanup(chrome.close)
        self.page = chrome.page
        self.page.send("Page.enable"); self.page.send("Runtime.enable")
        self.page.send("Page.navigate", {"url":self.base + "/api/status"})
        self.wait('location.pathname === "/api/status"')
        self.page.evaluate(f'localStorage.setItem("banjo.player.{world}", {json.dumps(owner["token"])})')
        return self.page

    def wait(self, expression, seconds=30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                if self.page.evaluate(expression): return
            except (RuntimeError, TimeoutError): pass
            time.sleep(.1)
        self.fail("Browser did not reach " + expression + "; " + str(self.page.evaluate('document.querySelector("#ws-notice")?.textContent')))

    def navigate(self, world, query):
        self.page.send("Page.navigate", {"url":self.base + f"/world?world={world}&" + query})
        self.wait('!!document.querySelector("#ws-screen-status") && !!document.querySelector("#ws-chat-log")')

    def click(self, selector):
        self.page.evaluate(f'document.querySelector({json.dumps(selector)}).scrollIntoView({{block:"center"}})')
        point = self.page.evaluate(f'(()=>{{const e=document.querySelector({json.dumps(selector)}),r=e.getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2}}}})()')
        for event in ("mousePressed", "mouseReleased"):
            self.page.send("Input.dispatchMouseEvent", {"type":event, **point, "button":"left", "clickCount":1})

    def assert_empty(self):
        self.wait('document.querySelector("#workshop-stage").dataset.showing === "empty"')
        self.assertIsNone(self.page.evaluate('document.querySelector("#workshop-stage").visibleGeometry()'))
        self.assertTrue(self.page.evaluate('document.querySelector("#ws-empty").offsetParent !== null'))
        self.assertTrue(self.page.evaluate('document.querySelector("#ws-component-chat-text").disabled'))

    def screenshot(self, name):
        out = ROOT / "build/workshop-navigation"; out.mkdir(parents=True, exist_ok=True)
        (out / name).write_bytes(base64.b64decode(self.page.send("Page.captureScreenshot")["data"]))

    def test_empty_lab_ignores_templates_memory_and_missing_inventory(self):
        world, owner, app = self.setup_world(); self.browser(world, owner)
        self.page.evaluate('localStorage.setItem("banjo.workshop.opened", JSON.stringify({kind:"cart"}))')
        self.navigate(world, "workshop=1&tab=lab&kind=table")
        self.assert_empty()
        self.assertEqual(["World", "Inventory", "Lab", "Skills", "Recipes", "Market", "Goals"],
            self.page.evaluate('[...document.querySelectorAll(".game-tabs [data-screen]")].map(e=>e.textContent)'))
        self.assertTrue(self.page.evaluate('document.querySelector(".ws-left").getBoundingClientRect().left >= document.querySelector("#workshop-stage").getBoundingClientRect().right - 1'))
        self.screenshot("empty.png")
        self.navigate(world, "workshop=1&tab=lab&carry=missing-item")
        self.assert_empty()
        self.assertFalse(self.page.evaluate('location.search.includes("carry=")'))
        self.page.send("Page.reload"); self.assert_empty()
        self.assertFalse([e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"])

    def test_saved_selection_and_world_tabs_preserve_player_and_clear_explicitly(self):
        world, owner, app = self.setup_world()
        source = self.post("/api/workshop/candidates", {"kind":"table", "generation":0}, world)
        candidate = source["candidates"][0]
        saved = self.post("/api/workshop/feedback", {"kind":"table", "generation":0,
            "design_id":candidate["design_id"], "parameters":candidate["parameters"],
            "component_overrides":candidate.get("component_overrides", {}), "save_design":True,
            "label":"My selected table"}, world)["design"]["design_id"]
        self.browser(world, owner); self.navigate(world, "workshop=1&tab=inventory")
        self.wait(f'!!document.querySelector("[data-lab-source=saved][data-item=\\"{saved}\\"]")')
        self.click("#ws-inv-more summary")
        self.click(f'[data-lab-source="saved"][data-item="{saved}"]')
        self.wait('document.querySelector("#workshop-stage").visibleGeometry()?.meshes > 0')
        self.assertEqual(saved, self.page.evaluate('new URLSearchParams(location.search).get("design")'))
        self.screenshot("selected.png")
        self.click('.game-tabs [data-screen="world"]')
        self.wait('!!window.banjoRoom?.status().ready')
        self.assertEqual(owner["id"], self.page.evaluate('window.banjoRoom.status().player_id'))
        self.assertEqual(7, self.page.evaluate('document.querySelectorAll(".game-tabs [data-screen]").length'))
        self.click('.game-tabs [data-screen="skills"]')
        self.wait('document.querySelector("#ws-pane-skills")?.hidden === false && !!document.querySelector("#ws-tree button")')
        self.click('.game-tabs [data-screen="lab"]')
        self.wait('document.querySelector("#workshop-stage").visibleGeometry()?.meshes > 0')
        self.page.send("Page.reload"); self.wait('document.querySelector("#workshop-stage")?.visibleGeometry()?.meshes > 0')
        self.click("#ws-clear-lab"); self.assert_empty()
        self.page.send("Page.reload"); self.assert_empty()
        self.assertFalse([e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"])

    def test_carried_item_requires_own_inventory_and_lab_leaves_it_unchanged(self):
        world, owner, app = self.setup_world()
        recipe = self.post("/api/workshop/goals", {}, world)["recipe"]
        context = self.post("/api/world/workshop/context", {}, world)
        preview = self.post("/api/world/workshop/preview", {"session":context["session"], "scene":context["scene"],
            "candidate":recipe, "mode":"authoring", "position_m":[3, 0]}, world)
        built = self.post("/api/world/workshop/commit", {"session":preview["session"], "scene":preview["scene"],
            "preview_id":preview["preview_id"], "request_id":"navigation-fixture"}, world)
        taken = self.post("/api/world/inventory", {"session":built["session"], "op":"take",
            "item":built["root_body"], "request":"navigation-take"}, world)
        self.assertTrue(taken["ok"], taken)
        carried = self.post("/api/workshop/inventory", {}, world)["carried"][0]
        before = self.post("/api/world/inventory/shown", {"session":built["session"]}, world)["record"]
        self.browser(world, owner); self.navigate(world, "workshop=1&tab=inventory")
        self.wait('!!document.querySelector(".ws-tile:not([disabled])")')
        self.click(".ws-tile:not([disabled])")
        self.wait('document.querySelector("#workshop-stage").visibleGeometry()?.meshes > 0')
        self.assertEqual(str(carried["id"]), self.page.evaluate('new URLSearchParams(location.search).get("carry")'))
        self.assertEqual("5", self.page.evaluate('document.querySelector("#ws-part-count").textContent'))
        self.assertEqual("2.509 kg", self.page.evaluate('document.querySelector("#ws-mass").textContent'))
        self.click("#ws-clear-lab"); self.assert_empty()
        after = self.post("/api/world/inventory/shown", {"session":built["session"]}, world)["record"]
        self.assertEqual(before, after)
        equipped = self.post("/api/world/inventory", {"session":built["session"], "op":"equip",
            "item":carried["id"], "request":"navigation-equip", "person":{"standing_m":[3, 0, 0],
            "eyes_m":[3, 1.62, 0], "facing":[0, 0, -1], "look_direction":[0, 0, -1]}}, world)
        self.assertTrue(equipped["ok"], equipped)
        hand_before = self.post("/api/world/inventory/shown", {"session":built["session"]}, world)["record"]
        self.navigate(world, "workshop=1&tab=inventory")
        self.wait('!!document.querySelector(".ws-tile:not([disabled])")')
        self.click(".ws-tile:not([disabled])")
        self.wait('document.querySelector("#workshop-stage").visibleGeometry()?.meshes > 0')
        self.click("#ws-clear-lab"); self.assert_empty()
        self.assertEqual(hand_before, self.post("/api/world/inventory/shown", {"session":built["session"]}, world)["record"])
        other = self.join(world, "Other guest")
        self.page.evaluate(f'localStorage.setItem("banjo.player.{world}", {json.dumps(other["token"])})')
        self.navigate(world, "workshop=1&tab=lab&carry=" + str(carried["id"]))
        self.assert_empty()


if __name__ == "__main__": unittest.main()
