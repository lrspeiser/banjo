"""Inventory selection, an empty Lab and shared right-side navigation."""
from __future__ import annotations
import base64
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "playground"), str(ROOT)]
import ai_player_tests as guests
import qa_browser


@unittest.skipUnless(guests.hub.RUNNER.is_file() and guests.hub.ENGINE.is_file(), "native world engine not built")
class GameScreens(unittest.TestCase):
    get, post, join = guests.AutonomousGuests.get, guests.AutonomousGuests.post, guests.AutonomousGuests.join
    setUp = guests.AutonomousGuests.setUp
    start, stop, setup_world = guests.AutonomousGuests.start, guests.AutonomousGuests.stop, guests.AutonomousGuests.setup_world

    def tearDown(self):
        # Stop browser polling before removing the server's SQLite directory.
        if getattr(self,"chrome",None): self.chrome.close()
        guests.AutonomousGuests.tearDown(self)

    def browser(self, world, owner):
        if not qa_browser.CHROME.is_file():
            if os.environ.get("BANJO_BROWSER_TESTS") == "required": self.fail("Chrome is required")
            self.skipTest("Chrome not installed")
        chrome = qa_browser.Chrome(1440, 900); self.addCleanup(chrome.close)
        self.chrome = chrome
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

    def test_watch_batch_button_earns_personal_skill_and_skills_link_to_real_equipment(self):
        import machine_witness
        world, owner, app = self.setup_world(); self.browser(world,owner)
        source = next(m for m in machine_witness.machines(app) if m["recipe"] == "smelt copper")
        self.page.send("Page.navigate", {"url":self.base + f"/world?world={world}"})
        self.wait('window.banjoRoom?.ready()',seconds=60)
        at = source["at_m"]
        self.page.evaluate(f'banjoRoom.standAt({at[0]},{at[1]+1.2},{at[2]+2}); banjoRoom.lookAt({at[0]},{at[1]},{at[2]})')
        self.click('[data-game-menu]')
        self.click('[data-world-menu="room"] summary')
        selector = f'[aria-label="Control {source["machine"]}"]'
        self.wait(f'!!document.querySelector({json.dumps(selector)})')
        self.click(selector)
        self.page.evaluate('document.querySelector("#game-menu").close()')
        self.wait('document.querySelector("#mp-watch-batch")?.offsetParent !== null')
        self.click("#mp-watch-batch")
        self.wait('document.querySelector("#mp-ack").textContent.includes("Stay nearby")')
        self.screenshot("watch-next-batch.png")
        for _ in range(200):
            app.clock._tick(.2)
            if "smelting-copper" in guests.server.journal_of(app,owner["id"]).knows(): break
        self.assertIn("smelting-copper",guests.server.journal_of(app,owner["id"]).knows())
        self.assertFalse([e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"])
        self.navigate(world,"workshop=1&tab=skills")
        self.wait('!!document.querySelector("[data-technique=rough-shaping-wood]")')
        self.click('[data-technique="rough-shaping-wood"]')
        self.wait('document.querySelector("#ws-tree-about").textContent.includes("Missing example")')
        self.assertIn('Not available in this world yet',self.page.evaluate('document.querySelector("#ws-tree-about").innerText'))
        self.assertIn('You cannot unlock it by collecting supplies',self.page.evaluate('document.querySelector("#ws-tree-about").innerText'))
        self.assertFalse(self.page.evaluate('document.querySelector("#ws-skills-diagnostics").open'))
        self.assertNotIn("you were given",self.page.evaluate('document.querySelector("#ws-tree-about").textContent'))
        self.assertIn("Making not available yet",self.page.evaluate('document.querySelector("#ws-tree-about").textContent'))
        self.assertNotIn("shape-wood-v1",self.page.evaluate('document.querySelector("#ws-tree-about").textContent'))
        self.click('[data-technique="smelting-copper"]')
        self.assertIn('Learned ✓ · No further action needed',self.page.evaluate('document.querySelector("#ws-tree-about").innerText'))
        self.assertTrue(self.page.evaluate('!!document.querySelector("a.ws-link[href*=focus]")'))
        self.screenshot("world-aware-skills.png")
        self.click('a.ws-link[href*=focus]')
        self.wait('window.banjoRoom?.ready() && location.search.includes("focus=")',seconds=60)
        self.assertIn("focus=",self.page.evaluate('location.search'))
        self.assertFalse([e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"])

    def test_failed_bank_notice_is_visible_and_reload_retry_draws_only_once(self):
        world,owner,app=self.setup_world(); self.browser(world,owner)
        self.navigate(world,"workshop=1&tab=market")
        self.wait('document.querySelectorAll("#ws-market-offers li").length > 0 && !document.querySelector("#ws-market-bank").disabled')
        charge=next(s["given_j"] for s in app.live.session.state["machines"]["stores"] if s["body"]=="solar farm")
        with mock.patch.object(app.store,"_save",side_effect=OSError("test disk unavailable")):
            self.click("#ws-market-bank")
            self.wait('document.querySelector("#world-save-status")?.offsetParent !== null && document.querySelector("#world-save-status").textContent.includes("test disk unavailable")')
            self.wait('document.querySelector("#ws-market-bank").textContent.startsWith("Retry") && !document.querySelector("#ws-market-bank").disabled')
            self.screenshot("save-failure.png")
        self.navigate(world,"workshop=1&tab=market")
        self.wait('document.querySelector("#ws-market-bank")?.textContent === "Retry bank 100 J"')
        self.click("#ws-market-bank")
        self.wait('document.querySelector("#ws-market-balance").textContent === "100 J" && document.querySelector("#world-save-status").hidden')
        given=next(s["given_j"] for s in app.live.session.state["machines"]["stores"] if s["body"]=="solar farm")
        self.assertAlmostEqual(100,given-charge,places=6)
        self.assertFalse([e for e in self.page.events if e.get("method")=="Runtime.exceptionThrown"])
        self.screenshot("save-recovered.png")

    def test_world_selection_reveals_reported_structure_then_restores_skin_without_stepping(self):
        import server
        with mock.patch.object(server.secrets,'randbelow',side_effect=[1,851269741]):
            world, owner, app = self.setup_world()
        self.browser(world, owner)
        self.page.send("Page.navigate", {"url":self.base + f"/world?world={world}&hold=1"})
        self.wait('window.banjoRoom?.ready()', seconds=60)
        session = app.live.session.id
        before = self.post("/api/live/act", {"session":session, "op":"poses"}, world)
        self.page.evaluate('window.revealTarget=[...banjoRoom.world.bodies].find(([n,e])=>e.mechanicalModel!=="precise-rigid-v1")?.[0]')
        self.assertTrue(self.page.evaluate('!!window.revealTarget'), "fixture needs reported cell geometry")
        self.page.evaluate('(()=>{const r=banjoRoom,p=r.world.bodies.get(revealTarget).mesh.position;r.standAt(p.x+.3,p.y+.25,p.z+.35);r.lookAt(p.x,p.y,p.z)})()')
        self.page.evaluate('window.originalSkin=banjoRoom.world.bodies.get(revealTarget).mesh.material; banjoRoom.pick(revealTarget,"cells")')
        self.wait('banjoRoom.reveal()?.kind === "cells" && banjoRoom.reveal().amount > .95')
        # Read the actual GPU vertex buffer. Each native cell gets twelve
        # orthogonal edges centred on that cell, with no triangle diagonals.
        self.assertTrue(self.page.evaluate('(()=>{const r=banjoRoom,mesh=r.scene.getObjectByName("selection-structure-reveal").children[0],cells=r.reveal().cellCentres,a=mesh.geometry.attributes.position.array,h=r.world.cellSize/2;return a.length===cells.length*72 && cells.every((p,i)=>{const mean=[0,0,0];for(let k=0;k<72;k++) {const v=a[i*72+k];if(Math.abs(Math.abs(v-p[k%3])-h)>1e-6)return false;mean[k%3]+=v/24;}for(let k=0;k<72;k+=6)if([0,1,2].filter(j=>Math.abs(a[i*72+k+j]-a[i*72+k+3+j])>1e-6).length!==1)return false;return p.every((v,k)=>Math.abs(v-mean[k])<1e-6)})})()'))
        self.assertLess(self.page.evaluate('banjoRoom.reveal().skinOpacity'), .3)
        self.assertTrue(self.page.evaluate('banjoRoom.world.bodies.get(revealTarget).mesh.material === originalSkin'))
        self.assertIn("Tool dependent", self.page.evaluate('document.querySelector("#picked").textContent'))
        # Frame interpolation and movement carry the reveal with the same body.
        self.assertTrue(self.page.evaluate('(()=>{const r=banjoRoom,g=r.scene.getObjectByName("selection-structure-reveal"),m=r.world.bodies.get(revealTarget).mesh;return g.matrix.equals(m.matrixWorld)})()'))
        self.screenshot("world-cell-reveal.png")
        self.wait('banjoRoom.reveal() === null', seconds=6)
        self.assertTrue(self.page.evaluate('banjoRoom.world.bodies.get(revealTarget).mesh.material === originalSkin && !banjoRoom.scene.getObjectByName("selection-structure-reveal")'))
        self.page.evaluate('[...document.querySelectorAll("#picked button")].find(b=>b.textContent==="Show native cells").click()')
        self.wait('!!banjoRoom.reveal()')
        self.click('#pk-close'); self.wait('banjoRoom.reveal() === null && document.querySelector("#picked").hidden')
        # Switching selection disposes the old overlay rather than stacking it.
        self.page.evaluate('banjoRoom.pick(revealTarget); banjoRoom.pick("solar farm")')
        self.page.evaluate('(()=>{const r=banjoRoom,p=r.world.bodies.get("solar farm").mesh.position;r.standAt(p.x+2,p.y+2,p.z+3);r.lookAt(p.x,p.y,p.z)})()')
        self.assertEqual("solar farm", self.page.evaluate('banjoRoom.picked().name'))
        self.assertEqual(0, self.page.evaluate('banjoRoom.scene.children.filter(c=>c.name === "selection-structure-reveal").length'))
        # The solar farm in the native starter room is a precise assembly.
        self.assertIsNone(self.page.evaluate('banjoRoom.reveal()'))
        self.assertGreater(self.page.evaluate('document.querySelectorAll("#picked .pk-component-grid img").length'),0)
        self.assertIn("No cell fracture", self.page.evaluate('document.querySelector("#picked").textContent'))
        self.screenshot("world-part-reveal.png")
        self.page.evaluate('banjoRoom.pick(null)')
        after = self.post("/api/live/act", {"session":session, "op":"poses"}, world)
        for key in ("t", "machines", "bodies"):
            self.assertEqual(before[key], after[key], key + " changed during inspection")
        self.assertFalse([e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"])

    def test_ground_reveal_uses_native_layers_and_reduced_motion_and_escape_clear_it(self):
        import server
        with mock.patch.object(server.secrets,'randbelow',side_effect=[1,851269741]):
            world, owner, app = self.setup_world()
        self.browser(world, owner)
        self.page.send("Emulation.setEmulatedMedia", {"features":[{"name":"prefers-reduced-motion", "value":"reduce"}]})
        self.page.send("Page.navigate", {"url":self.base + f"/world?world={world}&hold=1"})
        self.wait('window.banjoRoom?.ready()', seconds=60)
        session = app.live.session.id
        before = self.post("/api/live/act", {"session":session, "op":"poses"}, world)
        # Normal cursor/pointer events: Alt+click inspects the native terrain
        # under the centre without executing an interaction action.
        self.page.evaluate('const r=banjoRoom,y=r.groundAt(0,0);r.standAt(0,y+2,2);r.lookAt(0,y,0)')
        point = self.page.evaluate('(()=>{const r=document.querySelector("#stage").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()')
        self.page.send("Input.dispatchMouseEvent", {"type":"mouseMoved", **point, "modifiers":1})
        self.wait('!!banjoRoom.world.groundAim')
        for event in ("mousePressed", "mouseReleased"):
            self.page.send("Input.dispatchMouseEvent", {"type":event, **point, "button":"left", "clickCount":1, "modifiers":1})
        self.wait('banjoRoom.reveal()?.kind === "layers" && banjoRoom.reveal().amount === 1')
        layers = self.page.evaluate('banjoRoom.reveal().layers')
        self.assertTrue(layers)
        self.assertTrue(self.page.evaluate('(()=>{const r=banjoRoom,b=r.reveal().layers.filter(b=>!b.hole),m=r.scene.getObjectByName("selection-structure-reveal").children,g=r.groundDrawn();return m.length===b.length && b.every((bed,i)=>{m[i].geometry.computeBoundingBox();const s=m[i].geometry.boundingBox.getSize(new r.THREE.Vector3());return Math.abs(s.y-bed.thick_m)<1e-5 && Math.abs(m[i].position.y-(bed.top_m-bed.thick_m/2))<1e-6 && Math.abs(s.x-g.dx)<1e-6})})()'))
        self.assertEqual(len(layers), self.page.evaluate('document.querySelectorAll("#picked .pk-bed").length'))
        self.assertIn("Layers", self.page.evaluate('document.querySelector("#picked").textContent'))
        self.assertNotIn("kg", self.page.evaluate('document.querySelector("#picked").textContent'))
        self.screenshot("world-ground-reveal.png")
        self.page.send("Input.dispatchKeyEvent", {"type":"keyDown", "code":"Escape", "key":"Escape"})
        self.page.send("Input.dispatchKeyEvent", {"type":"keyUp", "code":"Escape", "key":"Escape"})
        self.wait('banjoRoom.reveal() === null && document.querySelector("#picked").hidden')
        after = self.post("/api/live/act", {"session":session, "op":"poses"}, world)
        for key in ("t", "machines", "ground"):
            self.assertEqual(before.get(key), after.get(key), key + " changed during inspection")
        self.assertFalse([e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"])

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
        self.assertEqual(f'{next(r["mass_kg"] for r in stock["materials"] if r["material"] == "oak"):g} kg', self.page.evaluate('document.querySelector("#ws-inv-stock [data-resource=oak] .ws-tile-count").textContent'))
        self.assertIn('Personal',self.page.evaluate('document.querySelector("#ws-inv-stock [data-resource=oak]").textContent'))
        self.assertIn('Shared',self.page.evaluate('document.querySelector("#ws-inv-stock [data-resource=oak]").textContent'))
        self.screenshot("material-quantities.png")
        self.click('#ws-inv-stock [data-resource="oak"]')
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
        # Empty geometry is shown before the asynchronous source lookup has
        # removed an invalid carried-item route. Wait for that completed state.
        self.wait('!location.search.includes("carry=")')
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
        self.wait('document.querySelector(".ws-product-card .ws-tile-name")?.textContent === "Camp stool" && document.querySelector(".ws-product-card canvas")?.dataset.preview === "ready"')
        self.assertFalse(self.page.evaluate('document.querySelector(".ws-product-debug").open'))
        self.assertIn('Hold / place in World',self.page.evaluate('document.querySelector(".ws-product-card").textContent'))
        self.assertEqual('2.51 kg',self.page.evaluate('document.querySelector(".ws-product-card .ws-tile-count").textContent'))
        self.wait('!!document.querySelector("#ws-inv-energy").dataset.updated')
        self.screenshot('named-product.png')
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
