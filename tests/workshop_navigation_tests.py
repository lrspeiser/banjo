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

    def test_material_cards_open_filtered_recipes_and_all_materials_restores_catalog(self):
        world, owner, app = self.setup_world()
        table = self.post("/api/workshop/candidates", {"kind":"table", "generation":0}, world)["candidates"][0]
        saved = self.post("/api/workshop/feedback", {"kind":"table", "design_id":table["design_id"],
            "parameters":table["parameters"], "component_overrides":table.get("component_overrides", {}),
            "save_design":True, "label":"Oak filter design"}, world)["design"]["design_id"]
        stock = self.post("/api/workshop/inventory", {}, world)
        self.browser(world, owner); self.navigate(world, "workshop=1&tab=inventory")
        self.wait('document.querySelectorAll("#ws-inv-stock .ws-tile").length > 0')
        self.assertTrue(self.page.evaluate('[...document.querySelectorAll("#ws-inv-stock .ws-tile")].every(c => !c.disabled && getComputedStyle(c).userSelect === "none" && c.querySelector(".ws-tile-count").parentElement === c && getComputedStyle(c.querySelector(".ws-tile-count")).position === "static")'))
        self.assertEqual(f'{next(r["mass_kg"] for r in stock["materials"] if r["material"] == "oak"):g} kg', self.page.evaluate('document.querySelector("#ws-inv-stock [title=oak] .ws-tile-count").textContent'))
        self.screenshot("material-quantities.png")
        self.click('#ws-inv-stock [title="oak"]')
        self.wait('new URLSearchParams(location.search).get("tab") === "recipes" && document.querySelectorAll("#ws-recipe-filter button").length > 1 && !!document.querySelector("#ws-rec-saved [data-recipe]")')
        self.assertEqual("oak", self.page.evaluate('new URLSearchParams(location.search).get("material")'))
        self.assertTrue(self.page.evaluate('[...document.querySelectorAll("#ws-pane-recipes [data-recipe]")].filter(c=>!c.hidden).every(c=>JSON.parse(c.dataset.materials).includes("oak"))'))
        self.assertTrue(self.page.evaluate(f'!!document.querySelector("[data-recipe=\\"{saved}\\"]:not([hidden])")'))
        total = self.page.evaluate('document.querySelectorAll("#ws-pane-recipes [data-recipe]").length')
        shown = self.page.evaluate('document.querySelectorAll("#ws-pane-recipes [data-recipe]:not([hidden])").length')
        self.assertGreater(shown, 0); self.assertLess(shown, total)
        self.assertIsNone(self.page.evaluate('document.querySelector("#workshop-stage").visibleGeometry()'))
        self.screenshot("oak-recipes.png")
        self.page.send("Page.reload")
        self.wait('document.querySelector("#ws-recipe-filter [data-recipe-material=oak]")?.getAttribute("aria-pressed") === "true"')
        self.click('[data-recipe-material="glass"]')
        self.assertEqual("glass", self.page.evaluate('new URLSearchParams(location.search).get("material")'))
        self.assertTrue(self.page.evaluate('[...document.querySelectorAll("#ws-pane-recipes [data-recipe]:not([hidden])")].every(c=>JSON.parse(c.dataset.materials).includes("glass"))'))
        self.click('[data-recipe-material=""]')
        self.assertFalse(self.page.evaluate('new URLSearchParams(location.search).has("material")'))
        self.assertEqual(total, self.page.evaluate('document.querySelectorAll("#ws-pane-recipes [data-recipe]:not([hidden])").length'))
        self.assertFalse(self.page.evaluate('document.querySelector("#ws-rec-blocks-section").hidden'))
        self.page.send("Page.reload"); self.wait('document.querySelectorAll("#ws-recipe-filter button").length > 1')
        self.assertEqual("true", self.page.evaluate('document.querySelector("[data-recipe-material=\\"\\"]").getAttribute("aria-pressed")'))
        self.navigate(world, "workshop=1&tab=recipes&material=unavailable-material")
        self.wait('document.querySelector("#ws-recipe-filter-status")?.textContent.includes("No matches")')
        self.assertFalse(self.page.evaluate('document.querySelectorAll("#ws-pane-recipes [data-recipe]:not([hidden])").length'))
        self.click('[data-recipe-material=""]')
        self.assertEqual(total, self.page.evaluate('document.querySelectorAll("#ws-pane-recipes [data-recipe]:not([hidden])").length'))
        after = self.post("/api/workshop/inventory", {}, world)
        for key in ("materials", "goods", "carried"): self.assertEqual(stock[key], after[key])
        self.assertFalse([e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"])

    def test_inventory_shows_private_wallet_and_native_meters_without_spending_or_stepping(self):
        world, owner, app = self.setup_world()
        self.post("/api/workshop/market", {"action":"bank", "joules":200,
            "request_id":"inventory-meter-fixture"}, world)
        session = app.live.session.id
        self.post("/api/live/act", {"session":session, "op":"step", "dt":1/240, "n":1}, world)
        before = self.post("/api/live/act", {"session":session, "op":"poses"}, world)
        self.assertGreater(sum(p["power_w"] for p in before["machines"]["panels"]), 0)
        self.browser(world, owner); self.navigate(world, "workshop=1&tab=inventory")
        self.wait('!!document.querySelector("#ws-inv-energy").dataset.updated')
        def displayed():
            return self.page.evaluate('[...document.querySelectorAll(".ws-energy-card")].map(c => ({title:c.querySelector("h4").textContent,values:Object.fromEntries([...c.querySelectorAll(".ws-recipe-value")].map(v=>[v.querySelector("span").textContent,v.querySelector("b").textContent]))}))')
        cards = displayed()
        self.assertEqual("200 J", cards[0]["values"]["Spendable"])
        self.assertEqual("0 J/s", cards[0]["values"]["Auto income"])
        solar = next(s for s in before["machines"]["stores"] if s["body"] == "solar farm")
        num = lambda text: float(text.split(" J")[0].replace(",", ""))
        self.assertAlmostEqual(solar["charge_j"], num(cards[1]["values"]["Stored"]), delta=.051)
        self.assertAlmostEqual(sum(p["power_w"] for p in before["machines"]["panels"]), num(cards[1]["values"]["Generating now"]), delta=.051)
        self.assertEqual("Not metered", cards[2]["values"]["Goods rate"])
        self.assertEqual("0 J/s", cards[2]["values"]["Currency income"])
        self.assertFalse(self.page.evaluate('!!document.querySelector("#ws-pane-inventory [data-building-block], #ws-pane-inventory [data-lab-source], #ws-pane-inventory input")'))
        self.assertNotRegex(self.page.evaluate('document.querySelector("#ws-pane-inventory").textContent'), r'width_m|Saved designs|Building blocks')
        self.screenshot("inventory-energy.png")
        stamp = self.page.evaluate('document.querySelector("#ws-inv-energy").dataset.updated')
        self.wait('document.querySelector("#ws-inv-energy").dataset.updated !== ' + json.dumps(stamp), seconds=12)
        after = self.post("/api/live/act", {"session":session, "op":"poses"}, world)
        self.assertEqual(before["t"], after["t"])
        self.assertEqual(before["machines"], after["machines"])
        self.assertEqual(200, self.post("/api/workshop/market", {}, world)["balance_j"])
        other = self.join(world, "Other wallet")
        self.page.evaluate(f'localStorage.setItem("banjo.player.{world}", {json.dumps(other["token"])})')
        self.navigate(world, "workshop=1&tab=inventory")
        self.wait('!!document.querySelector("#ws-inv-energy").dataset.updated')
        self.assertEqual("0 J", displayed()[0]["values"]["Spendable"])
        self.assertFalse([e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"])

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
        self.browser(world, owner); self.navigate(world, "workshop=1&tab=recipes")
        self.wait(f'!!document.querySelector("[data-lab-source=saved][data-item=\\"{saved}\\"]")')
        self.assertEqual(1, self.page.evaluate(f'document.querySelectorAll("[data-recipe=\\"{saved}\\"]").length'))
        self.assertTrue(self.page.evaluate(f'!!document.querySelector("[data-lab-source=saved][data-item=\\"{saved}\\"]").closest("#ws-rec-saved")'))
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

    def test_recipes_building_blocks_create_saved_designs_without_spending_stock(self):
        world, owner, app = self.setup_world(); self.browser(world, owner)
        before = self.post("/api/workshop/inventory", {}, world)
        self.navigate(world, "workshop=1&tab=recipes")
        self.wait('document.querySelectorAll("[data-building-block]").length === 16')
        self.assertNotRegex(self.page.evaluate('document.querySelector("#ws-pane-recipes").textContent'),
                            r'width_m|height_m|depth_m|splay_deg|lean_x|component_overrides')
        self.assertEqual(["Frames & supports", "Surfaces & panels", "Wheels & axles", "Machine housings"],
            self.page.evaluate('[...document.querySelectorAll("#ws-rec-blocks h4")].map(e=>e.textContent)'))
        self.assertEqual(16, self.page.evaluate('document.querySelectorAll("#ws-rec-blocks canvas[data-preview=ready]").length'))
        self.assertIn("AI design is not connected", self.page.evaluate('document.querySelector("#ws-rec-ai-help").textContent'))
        self.assertIsNone(self.page.evaluate('document.querySelector("#workshop-stage").visibleGeometry()'))
        # Every offered block really starts a source design; none relies on an
        # invented machine behavior or physical inventory to appear on screen.
        families = self.page.evaluate('[...document.querySelectorAll("[data-building-block]")].map(e=>e.dataset.buildingBlock)')
        ids = set()
        for family in families:
            previous = self.page.evaluate('new URLSearchParams(location.search).get("library")')
            self.click(f'[data-building-block="{family}"]')
            self.wait('document.querySelector("#workshop-stage").visibleGeometry()?.meshes > 0 && document.querySelector(".ws-viewport").hidden === false && new URLSearchParams(location.search).has("library") && new URLSearchParams(location.search).get("library") !== ' + json.dumps(previous))
            ids.add(self.page.evaluate('new URLSearchParams(location.search).get("library")'))
            self.assertEqual("1", self.page.evaluate('document.querySelector("#ws-part-count").textContent'))
            self.assertFalse(self.page.evaluate('document.querySelector("#ws-component-chat-text").disabled'))
            self.click('.game-tabs [data-screen="recipes"]')
            self.wait('document.querySelectorAll("[data-building-block]").length === 16')
        self.assertEqual(16, len(ids))
        after = self.post("/api/workshop/inventory", {}, world)
        for key in ("carried", "materials", "goods", "in_world"): self.assertEqual(before[key], after[key])
        self.assertEqual(16, len(after["designs"]))
        self.wait('document.querySelectorAll("#ws-rec-saved canvas[data-preview=ready]").length === 16')
        self.screenshot("inventory-categories.png")
        self.page.evaluate('document.querySelector("#ws-pane-recipes").scrollTop = 0')
        self.screenshot("inventory-overview.png")
        # Saved component cards create a new editable design, leaving the
        # reusable original intact and keeping the selected item on reload.
        table = self.post("/api/workshop/candidates", {"kind":"table", "generation":0}, world)["candidates"][0]
        component = self.post("/api/workshop/library", {"action":"save_component", "kind":"table",
            "parameters":table["parameters"], "component_overrides":table.get("component_overrides", {}),
            "part_name":"top", "name":"Reusable tabletop"}, world)["library_item"]
        self.navigate(world, "workshop=1&tab=recipes")
        self.wait(f'!!document.querySelector("[data-lab-component=\\"{component["item_id"]}\\"]")')
        self.click(f'[data-lab-component="{component["item_id"]}"]')
        self.wait('document.querySelector("#workshop-stage").visibleGeometry()?.meshes > 0')
        selected = self.page.evaluate('new URLSearchParams(location.search).get("library")')
        self.page.send("Page.reload"); self.wait('document.querySelector("#workshop-stage")?.visibleGeometry()?.meshes > 0')
        self.assertEqual(selected, self.page.evaluate('new URLSearchParams(location.search).get("library")'))
        unchanged = self.post("/api/workshop/library", {"action":"load", "item_id":component["item_id"]}, world)["library_item"]
        self.assertEqual(component["payload"], unchanged["payload"])
        self.assertFalse([e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"])

    def test_recipe_make_reports_world_output_and_adds_independent_copies(self):
        world, owner, app = self.setup_world(); self.browser(world, owner)
        before = self.post("/api/workshop/inventory", {}, world)
        self.navigate(world, "workshop=1&tab=recipes")
        card = '[data-recipe="stool:Camp stool"]'
        self.wait(f'!!document.querySelector({json.dumps(card)})')
        self.wait('document.querySelectorAll("#ws-recipes-templates canvas[data-preview=ready]").length >= 10')
        self.assertIsNone(self.page.evaluate('document.querySelector("#workshop-stage").visibleGeometry()'))
        self.assertIn("SkillNone required", self.page.evaluate(f'document.querySelector({json.dumps(card)}).textContent'))
        bodies = set()
        for _ in range(2):
            self.click(card + ' .ws-recipe-acts button')
            self.wait(f'document.querySelector({json.dumps(card + " .ws-recipe-result a")})?.dataset.madeBody && document.querySelector({json.dumps(card + " .ws-recipe-acts button")})?.disabled === false')
            bodies.add(self.page.evaluate(f'document.querySelector({json.dumps(card + " .ws-recipe-result a")}).dataset.madeBody'))
            self.assertIn("tab=recipes", self.page.evaluate('location.search'))
            self.assertIsNone(self.page.evaluate('document.querySelector("#workshop-stage").visibleGeometry()'))
        self.assertEqual(2, len(bodies), "Make replaced the previous copy")
        after = self.post("/api/workshop/inventory", {}, world)
        self.assertEqual(before["carried"], after["carried"])
        oak = lambda rows: next(r["mass_kg"] for r in rows if r["material"] == "oak")
        self.assertAlmostEqual(2 * 2.5088, oak(before["materials"]) - oak(after["materials"]), places=4)
        self.assertEqual(bodies, {r["root_body"] for r in app.room.workshop_installs})
        self.assertTrue(all(r.get("owner_id") == owner["id"] for r in app.room.workshop_installs))
        self.screenshot("recipes-made.png")
        self.click(card + ' .ws-recipe-result a')
        self.wait('location.pathname === "/world" && !new URLSearchParams(location.search).has("workshop")')
        self.assertEqual(world, self.page.evaluate('new URLSearchParams(location.search).get("world")'))
        self.wait('window.banjoRoom?.status().ready && window.banjoRoom.world.bodies.has(new URLSearchParams(location.search).get("focus"))')
        self.assertEqual(owner["id"], self.page.evaluate('window.banjoRoom.status().player_id'))
        self.assertTrue(self.page.evaluate('(()=>{const r=window.banjoRoom,c=r.camera,m=r.world.bodies.get(new URLSearchParams(location.search).get("focus")).mesh,p=m.getWorldPosition(c.position.clone()).sub(c.position).normalize();return c.getWorldDirection(c.position.clone()).dot(p) > .99})()'))
        self.screenshot("recipe-world.png")
        self.assertFalse([e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"])

    def test_recipe_make_shows_a_stock_race_refusal_on_the_card(self):
        world, owner, app = self.setup_world(); self.browser(world, owner)
        table = self.post("/api/workshop/candidates", {"kind":"table", "generation":0}, world)["candidates"][0]
        saved = self.post("/api/workshop/feedback", {"kind":"table", "design_id":table["design_id"],
            "parameters":table["parameters"], "component_overrides":table.get("component_overrides", {}),
            "save_design":True, "label":"Keep my Lab item"}, world)["design"]["design_id"]
        self.navigate(world, "workshop=1&tab=recipes")
        selected = f'[data-lab-source="saved"][data-item="{saved}"]'
        self.wait(f'!!document.querySelector({json.dumps(selected)})'); self.click(selected)
        self.wait('document.querySelector("#workshop-stage").visibleGeometry()?.meshes > 0')
        meshes = self.page.evaluate('document.querySelector("#workshop-stage").visibleGeometry().meshes')
        self.click('.game-tabs [data-screen="recipes"]')
        card = '[data-recipe="stool:Camp stool"]'
        self.wait(f'document.querySelector({json.dumps(card + " .ws-recipe-acts button")})?.disabled === false')
        # Another actor can spend shared stock after this page displayed it.
        with guests.server.workshop_library._connect(app) as db:
            db.execute("UPDATE workshop_material_rack SET mass_kg=0 WHERE material='oak'")
        self.click(card + ' .ws-recipe-acts button')
        self.wait(f'document.querySelector({json.dumps(card + " .ws-recipe-result")})?.dataset.bad === "yes" && document.querySelector({json.dumps(card + " .ws-recipe-acts button")})?.disabled === true')
        self.assertIn("Nothing has been spent", self.page.evaluate(f'document.querySelector({json.dumps(card + " .ws-recipe-result")}).textContent'))
        self.assertIn("tab=recipes", self.page.evaluate('location.search'))
        self.assertFalse(app.room.workshop_installs)
        self.assertEqual(saved, self.page.evaluate('new URLSearchParams(location.search).get("design")'))
        self.assertEqual(meshes, self.page.evaluate('document.querySelector("#workshop-stage").visibleGeometry().meshes'))
        self.screenshot("recipes-short.png")

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
