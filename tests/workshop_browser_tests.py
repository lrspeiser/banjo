"""Workshop controls exercised in Chrome against an isolated local server.

Use BANJO_LIVE_ENGINE and BANJO_CHROME; BANJO_BROWSER_TESTS=required makes a
missing prerequisite a failure. No model service, video encoder or user room is
used. qa_browser is the existing, dependency-free DevTools test harness.
"""
from __future__ import annotations

import base64
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import qa_browser


class WorkshopBrowserRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine = os.environ.get("BANJO_LIVE_ENGINE")
        if not engine and os.environ.get("BANJO_BUILD_DIR"):
            engine = str(Path(os.environ["BANJO_BUILD_DIR"]) / ("banjo_live_world_run.exe" if os.name == "nt" else "banjo_live_world_run"))
        if not engine or not Path(engine).is_file() or not qa_browser.CHROME.is_file():
            message = "Workshop browser tests need BANJO_LIVE_ENGINE and BANJO_CHROME"
            if os.environ.get("BANJO_BROWSER_TESTS") == "required":
                raise RuntimeError(message)
            raise unittest.SkipTest(message)
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0)); cls.port = sock.getsockname()[1]
        cls.log = (root / "server.log").open("w", encoding="utf-8")
        cls.addClassCleanup(cls.log.close)
        cls.server = subprocess.Popen([
            sys.executable, "-u", str(ROOT / "playground/server.py"),
            "--port", str(cls.port), "--engine", str(Path(engine).resolve()),
            "--runs", str(root / "runs"), "--rooms", str(root / "rooms"),
        ], cwd=ROOT, env={**os.environ, "OPENAI_API_KEY": ""}, stdout=cls.log, stderr=cls.log)
        cls.addClassCleanup(cls.stop_server)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if cls.server.poll() is not None:
                raise RuntimeError("Isolated Workshop server exited before startup")
            connection = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=1)
            try:
                connection.request("GET", "/api/status")
                if connection.getresponse().status == 200:
                    return
            except OSError:
                pass
            finally:
                connection.close()
            time.sleep(.1)
        raise RuntimeError("Isolated Workshop server did not start")

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill(); cls.server.wait(timeout=5)

    def setUp(self):
        self.chrome = qa_browser.Chrome(width=1440, height=1000)
        self.addCleanup(self.chrome.close)
        self.page = self.chrome.page
        self.page.send("Runtime.enable")
        self.page.send("Page.enable")
        self.page.send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/world?workshop=1"})
        try:
            self.wait("document.querySelector('#ws-product-catalog button') && document.querySelector('#ws-name').textContent.trim()")
        except Exception:
            # unittest skips tearDown when setUp fails. Keep startup evidence
            # before the registered Chrome cleanup closes this page.
            self.capture_evidence(f"{self._testMethodName}-startup.png")
            raise

    def capture_evidence(self, name):
        folder = os.environ.get("BANJO_BROWSER_ARTIFACTS")
        if folder:
            output = Path(folder); output.mkdir(parents=True, exist_ok=True)
            image = self.page.send("Page.captureScreenshot", {"format":"png"})["data"]
            (output / name).write_bytes(base64.b64decode(image))

    def js(self, expression):
        return self.page.evaluate(expression, await_promise=True)

    def wait(self, condition, timeout=25):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # DOM elements serialize as empty objects through DevTools.
            # Evaluate presence in JavaScript, not Python dict truthiness.
            if self.js(f"Boolean({condition})"):
                return
            time.sleep(.1)
        diagnostics = self.js("""JSON.stringify({
          notice:document.querySelector('#ws-notice')?.textContent,
          test:document.querySelector('#ws-bench-test')?.value,
          result:document.querySelector('#ws-bench-result')?.textContent,
          runDisabled:document.querySelector('#ws-run-bench')?.disabled,
          controls:[...document.querySelectorAll('[data-bench-control]')].map(e=>({
            name:e.dataset.benchControl,value:e.value,checked:e.checked}))})""")
        errors = [e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"]
        raise AssertionError(f"Workshop condition timed out: {condition}; {diagnostics}; runtimeErrors={json.dumps(errors)}")

    def click(self, selector):
        self.js(f"document.querySelector({json.dumps(selector)}).click()")

    def pointer_click(self, selector):
        """Use actual hit testing, not HTMLElement.click through an overlay."""
        self.js(f"document.querySelector({json.dumps(selector)}).scrollIntoView({{block:'nearest'}})")
        point=self.js(f"""(()=>{{const e=document.querySelector({json.dumps(selector)}),r=e.getBoundingClientRect();
          const x=r.left+r.width/2,y=r.top+r.height/2;
          return {{x,y,visible:r.width>0&&r.height>0,hit:e.contains(document.elementFromPoint(x,y))}};}})()""")
        self.assertTrue(point["visible"] and point["hit"], f"Hidden/obscured control {selector}: {point}")
        for event in ("mousePressed","mouseReleased"):
            self.page.send("Input.dispatchMouseEvent",{"type":event,"x":point["x"],"y":point["y"],"button":"left","clickCount":1})

    def assert_geometry_is_visible(self):
        info=self.js("document.querySelector('#workshop-stage').visibleGeometry()")
        self.assertIsNotNone(info); self.assertGreater(info["meshes"],0)
        self.assertEqual(0,info["clipped"])
        rect=self.js("document.querySelector('#workshop-stage').getBoundingClientRect().toJSON()")
        xs=[p[0] for p in info["points"]];ys=[p[1] for p in info["points"]]
        self.assertGreater(min(xs),rect["left"]-1); self.assertLess(max(xs),rect["right"]+1)
        self.assertGreater(min(ys),rect["top"]-1); self.assertLess(max(ys),rect["bottom"]+1)
        self.assertGreater(max(max(xs)-min(xs),max(ys)-min(ys)),min(rect["width"],rect["height"])*.2)
        self.assertTrue(all(-1<=point[2]<=1 for point in info["points"]))
        # The whole mesh's projected bounding region must hit the canvas, not
        # a control panel positioned on top of it.
        self.assertTrue(self.js(f"document.elementFromPoint({(max(xs)+min(xs))/2},{(max(ys)+min(ys))/2}) === document.querySelector('#workshop-stage')"))

    def field(self, selector, value, event="change"):
        self.js(f"{{const e=document.querySelector({json.dumps(selector)}); e.value={json.dumps(str(value))}; e.dispatchEvent(new Event({json.dumps(event)},{{bubbles:true}}));}}")

    def open_product(self, kind):
        revision = self.js("document.querySelector('#workshop-stage').dataset.revision")
        self.click(f'#ws-product-catalog button[data-value="{kind}"]')
        self.wait(f"document.querySelector('#workshop-stage').dataset.kind === {json.dumps(kind)} && document.querySelector('#workshop-stage').dataset.revision !== {json.dumps(revision)}")

    def curve_leg(self):
        self.click('[data-mode="build"]')
        self.js("[...document.querySelectorAll('#ws-parts button')].find(b=>b.textContent==='leg-1').click()")
        self.field("#ws-skin-profile", "curve")
        self.field("#ws-skin-bend", .35, "input")
        self.js("document.querySelector('#ws-skin-physical').checked=true")
        self.click("#ws-apply-skin")
        self.wait("!document.querySelector('#ws-apply-skin').disabled && document.querySelector('#ws-measurement-basis').textContent.includes('Mass/balance from Matter')")

    def tearDown(self):
        # Captures support debugging and are never committed as product assets.
        out = Path(os.environ.get("BANJO_BROWSER_ARTIFACTS", str(ROOT / "build/workshop-browser-evidence")))
        out.mkdir(parents=True, exist_ok=True)
        image = self.page.send("Page.captureScreenshot", {"format": "png"})
        (out / f"{self._testMethodName}.png").write_bytes(base64.b64decode(image["data"]))
        errors = [e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"]
        self.assertEqual([], errors, errors)

    def test_cellskin_and_contract_views_preserve_matter_and_clipping_is_display_only(self):
        self.click('[data-mode="build"]')
        self.click('[data-view="matter"]')
        self.wait("document.querySelector('#ws-matter-status').dataset.state==='current'")
        status = self.js("document.querySelector('#ws-matter-status').textContent")
        mass = self.js("document.querySelector('#ws-mass').textContent")
        self.field('#ws-matter-mode', 'solid')
        self.wait("Number(document.querySelector('#workshop-stage').dataset.cellSkinFaces)>0")
        faces = self.js("document.querySelector('#workshop-stage').dataset.cellSkinFaces")
        self.js("document.querySelector('#ws-clip-enabled').checked=true;document.querySelector('#ws-clip-enabled').dispatchEvent(new Event('change',{bubbles:true}))")
        self.field('#ws-clip-axis', 'y')
        self.field('#ws-clip-position', .4, 'input')
        self.assertEqual(mass, self.js("document.querySelector('#ws-mass').textContent"))
        self.assertEqual(status, self.js("document.querySelector('#ws-matter-status').textContent"))
        self.assertEqual(faces, self.js("document.querySelector('#workshop-stage').dataset.cellSkinFaces"))
        self.click('[data-view="collision"]')
        self.wait("document.querySelector('#workshop-stage').dataset.debugBasis==='design-contract-not-native-collision'")
        self.assertIn('not a native contact',self.js("document.querySelector('#ws-inspection-basis').textContent"))
        self.click('[data-view="relations"]')
        self.wait("document.querySelector('[data-view=relations]').getAttribute('aria-pressed')==='true'")
        self.assertEqual(mass, self.js("document.querySelector('#ws-mass').textContent"))
        self.capture_evidence('workshop-section-and-contract.png')

    def test_physical_skin_does_not_reinstate_obsolete_contract_geometry(self):
        self.curve_leg()
        self.click('[data-view="collision"]')
        self.wait("document.querySelector('#workshop-stage').dataset.debugBasis==='unavailable-physical-skin'")
        self.assertIn('does not consume physical skin',self.js("document.querySelector('#ws-inspection-basis').textContent"))
        self.click('[data-view="matter"]')
        self.field('#ws-matter-mode','solid')
        self.wait("Number(document.querySelector('#workshop-stage').dataset.cellSkinFaces)>0")

    def test_rebuild_budget_limit_is_visible_and_does_not_keep_stale_matter(self):
        self.click("#ws-refresh-matter")
        self.wait("document.querySelector('#ws-matter-status').dataset.state==='current'")
        self.field("#ws-matter-cell", .005)
        self.click("#ws-refresh-matter")
        self.wait("document.querySelector('#ws-matter-status').dataset.state==='blocked'")
        self.assertIn("Not buildable", self.js("document.querySelector('#ws-buildability-summary').textContent"))
        self.assertTrue(self.js("document.querySelector('#ws-buildability-summary').getBoundingClientRect().height>0"))
        self.assertIn("more than 50,000 cells", self.js("document.querySelector('#ws-matter-status').textContent").lower())
        self.assertTrue(self.js("document.querySelector('#ws-mode-test').hidden"))

    def test_physical_measurements_and_product_switch_are_current(self):
        mass = self.js("document.querySelector('#ws-mass').textContent")
        self.curve_leg()
        self.assertNotEqual(mass, self.js("document.querySelector('#ws-mass').textContent"))
        self.open_product("chair")
        self.wait("document.querySelector('#ws-matter-status').dataset.state==='unbuilt'")
        self.assertFalse(self.js("document.querySelector('#ws-skin-physical').checked"))
        self.assertEqual("0", self.js("document.querySelector('#ws-skin-bend').value"))
        self.assertEqual("design", self.js("document.querySelector('#ws-skin-profile').value"))

    def test_saved_edited_design_reopens_from_saved_designs(self):
        self.curve_leg()
        mass = self.js("document.querySelector('#ws-mass').textContent")
        self.click('[data-mode="details"]')
        self.field("#ws-save-name", "Browser curved table")
        self.click("#ws-save-design")
        self.wait("document.querySelector('#ws-save-status').textContent.includes('Saved designs and My Library')")
        self.open_product("stool")
        self.js("[...document.querySelectorAll('#ws-saved-designs button')].find(b=>b.textContent.includes('Browser curved table')).click()")
        self.wait("document.querySelector('#ws-archetype').value==='table' && document.querySelector('#ws-measurement-basis').textContent.includes('Mass/balance from Matter')")
        self.assertEqual(mass, self.js("document.querySelector('#ws-mass').textContent"))
        self.click('[data-mode="build"]')
        self.js("[...document.querySelectorAll('#ws-parts button')].find(b=>b.textContent==='leg-1').click()")
        self.assertAlmostEqual(.35, float(self.js("document.querySelector('#ws-skin-bend').value")))
        self.assertTrue(self.js("document.querySelector('#ws-skin-physical').checked"))

    def test_older_candidate_response_cannot_replace_newer_product(self):
        self.js("""window.__originalFetch=window.fetch;window.fetch=async function(resource,init){
          const response=await window.__originalFetch(resource,init);
          if(String(resource).endsWith('/api/workshop/candidates') && JSON.parse(init.body).kind==='chair'){
            await new Promise(resolve=>{window.__releaseOld=resolve});
          }return response;
        };""")
        self.click('#ws-product-catalog button[data-value="chair"]')
        self.wait("typeof window.__releaseOld==='function'")
        self.open_product("stool")
        name = self.js("document.querySelector('#ws-name').textContent")
        self.js("window.__releaseOld();window.fetch=window.__originalFetch")
        self.wait("document.querySelector('#ws-archetype').value==='stool'")
        time.sleep(.2)
        self.assertEqual(name, self.js("document.querySelector('#ws-name').textContent"))

    def test_workspace_preview_load_run_and_controls_never_cover_canvas(self):
        self.pointer_click('[data-mode="test"]')
        self.wait("document.querySelector('#ws-test-catalog [data-value=declared_static_load]')")
        self.pointer_click('#ws-test-catalog [data-value="declared_static_load"]')
        self.wait("document.querySelector('#ws-setup-status')?.dataset.state === 'ready'")
        self.assertEqual("setup",self.js("document.querySelector('#workshop-stage').dataset.phase"))
        self.assertEqual("2",self.js("document.querySelector('#workshop-stage').dataset.physicsBodyCount"))
        self.assertEqual("0",self.js("document.querySelector('#workshop-stage').dataset.physicsTime"))
        self.assert_geometry_is_visible()
        layout=self.js("""(()=>{const c=document.querySelector('#workshop-stage').getBoundingClientRect(),
            d=document.querySelector('#ws-simulation-dock').getBoundingClientRect();
            return {width:c.width,height:c.height,overlap:d.top<c.bottom-.1,advanced:document.querySelector('.ws-advanced').open};})()""")
        self.assertGreater(layout["width"],700);self.assertGreater(layout["height"],250)
        self.assertFalse(layout["overlap"]);self.assertFalse(layout["advanced"])
        self.field('[data-bench-control="load_kg"]',10)
        self.wait("document.querySelector('#ws-setup-status')?.dataset.state === 'ready' && document.querySelector('#ws-setup-status').textContent.includes('10.')")
        self.pointer_click('#ws-run-bench')
        self.wait("document.querySelector('#ws-simulation-status')?.dataset.state === 'complete'",timeout=60)
        self.assertFalse(self.js("document.querySelector('#ws-playback').hidden"))
        self.pointer_click('#ws-play')
        self.pointer_click('#ws-reset-setup')
        self.wait("document.querySelector('#ws-setup-status')?.dataset.state === 'ready'")
        self.assertEqual("0",self.js("document.querySelector('#workshop-stage').dataset.physicsTime"))
        self.assert_geometry_is_visible()

    def test_component_copy_and_saved_inspection_show_solid_geometry_without_replacing_product(self):
        self.open_product("cart")
        # A prior section plane must not hide the next component opened.
        self.js("document.querySelector('#ws-clip-enabled').checked=true; document.querySelector('#ws-clip-enabled').dispatchEvent(new Event('change'))")
        self.pointer_click('#ws-product-catalog .ws-part-open[data-part="wheel-11"]')
        self.wait("document.querySelector('#workshop-stage').dataset.showing === 'wheel-11'")
        self.assertEqual("true",self.js("document.querySelector('[data-view=skin]').getAttribute('aria-pressed')"))
        self.assert_geometry_is_visible()
        revision=self.js("document.querySelector('#workshop-stage').dataset.revision")
        count=self.js("document.querySelectorAll('#ws-user-library .ws-library-item').length")
        self.pointer_click('#ws-product-catalog .ws-part-row:has([data-part="wheel-11"]) .ws-part-copy')
        self.wait(f"document.querySelectorAll('#ws-user-library .ws-library-item').length === {count+1}")
        self.wait("!document.querySelector('#ws-product-catalog .ws-part-row:has([data-part=wheel-11]) .ws-part-copy').disabled")
        self.assert_geometry_is_visible()
        # Saved item lookup is explicit, read-only, and remains centered even
        # though the source wheel originally sat off to one side of the cart.
        self.js("[...document.querySelectorAll('#ws-user-library .ws-library-item')].find(e=>e.textContent.includes('cart wheel')).id='saved-wheel-inspect'")
        self.pointer_click('#saved-wheel-inspect')
        self.wait("document.querySelector('#workshop-stage').dataset.showing === 'saved-component'")
        self.assert_geometry_is_visible()
        self.assertEqual(revision,self.js("document.querySelector('#workshop-stage').dataset.revision"))
        self.assertIn("Read-only",self.js("document.querySelector('#ws-view-description').textContent"))
        self.assertFalse(self.js("document.querySelector('#ws-inspector-use').hidden"))
        self.pointer_click('#ws-inspector-back')
        self.wait("document.querySelector('#workshop-stage').dataset.showing === 'product'")
        self.assertEqual("14",self.js("document.querySelector('#ws-part-count').textContent"))
        self.assertEqual(revision,self.js("document.querySelector('#workshop-stage').dataset.revision"))

    def test_setup_response_cannot_replace_newer_component_or_product(self):
        self.js("""window.__originalFetch=window.fetch;window.fetch=async function(url,options){
            if(String(url).includes('/api/workshop/plan') && JSON.parse(options?.body||'{}').bench_preview){
                const response=await window.__originalFetch(url,options);
                return await new Promise(resolve=>window.__releaseSetup=()=>resolve(response));
            }return window.__originalFetch(url,options);};""")
        self.pointer_click('[data-mode="test"]')
        self.wait("typeof window.__releaseSetup === 'function'")
        self.pointer_click('[data-mode="build"]')
        self.pointer_click('#ws-product-catalog .ws-part-open[data-part="leg-1"]')
        self.js("window.__releaseSetup()")
        self.wait("document.querySelector('#workshop-stage').dataset.showing === 'leg-1'")
        self.assert_geometry_is_visible()
        self.assertEqual("true",self.js("document.querySelector('[data-view=skin]').getAttribute('aria-pressed')"))

    def test_finished_run_cannot_replace_component_opened_while_it_was_calculating(self):
        self.pointer_click('[data-mode="test"]')
        self.wait("document.querySelector('#ws-setup-status')?.dataset.state === 'ready'")
        self.js("""window.__originalFetch=window.fetch;window.fetch=async function(url,options){
            if(String(url).includes('/api/workshop/plan') && JSON.parse(options?.body||'{}').bench_test){
                const response=await window.__originalFetch(url,options);
                return await new Promise(resolve=>window.__releaseRun=()=>resolve(response));
            }return window.__originalFetch(url,options);};""")
        self.pointer_click('#ws-run-bench')
        self.wait("typeof window.__releaseRun === 'function'")
        self.pointer_click('[data-mode="build"]')
        self.pointer_click('#ws-product-catalog .ws-part-open[data-part="leg-1"]')
        self.js("window.__releaseRun()")
        self.wait("!document.querySelector('#ws-run-bench').disabled")
        self.assertEqual('leg-1', self.js("document.querySelector('#workshop-stage').dataset.showing"))
        self.assertEqual('true', self.js("document.querySelector('[data-view=skin]').getAttribute('aria-pressed')"))
        self.assert_geometry_is_visible()

    def test_small_component_remains_visible_after_narrow_viewport_resize(self):
        self.open_product("cart")
        self.pointer_click('#ws-product-catalog .ws-part-open[data-part="bearing-mount-11"]')
        self.wait("document.querySelector('#workshop-stage').dataset.showing === 'bearing-mount-11'")
        self.assert_geometry_is_visible()
        self.page.send("Emulation.setDeviceMetricsOverride",{"width":640,"height":900,"deviceScaleFactor":1,"mobile":False})
        self.wait("document.querySelector('#workshop-stage').getBoundingClientRect().width < 650")
        self.pointer_click('#ws-fit-view')
        self.assert_geometry_is_visible()

    def test_library_rows_are_names_and_open_a_product_to_its_components(self):
        """A library row is a name; the open product lists its components.

        Every card used to carry a second line saying to click it, which a
        button already says. The room under a row is worth more: the open
        product's components, how many of each, and a way into each one.
        """
        rows = self.js("""[...document.querySelectorAll('#ws-product-catalog .ws-product-card')]
          .map(card=>({name:card.textContent.trim(),extra:card.querySelectorAll('small').length}))""")
        self.assertEqual([], [row for row in rows if row["extra"]])
        self.assertIn("cart", [row["name"].lower() for row in rows])
        self.assertEqual([], self.js(
            "[...document.querySelectorAll('#ws-test-catalog .ws-test-card small')].map(n=>n.textContent)"))

        self.open_product("cart")
        self.wait("document.querySelectorAll('#ws-product-catalog .ws-part-row').length")
        listed = self.js(r"""[...document.querySelectorAll('#ws-product-catalog .ws-part-row')].map(row=>[
          row.querySelector('.ws-part-name').textContent,
          row.querySelector('.ws-part-qty')?.textContent.replace(/\D/g,'')||'1'])""")
        self.assertEqual([["deck","1"],["axle","2"],["bearing-mount","4"],
                          ["wheel","4"],["handle-arm","2"],["handle","1"]], listed)
        # The components belong to the open product only.
        self.assertEqual(1, self.js(
            "document.querySelectorAll('#ws-product-catalog .ws-product-parts').length"))

        # Copy puts a component in My library, where it can be reused.
        saved = self.js("document.querySelectorAll('#ws-user-library .ws-library-item').length")
        self.click('#ws-product-catalog .ws-part-row:nth-child(1) .ws-part-copy')
        self.wait(f"document.querySelectorAll('#ws-user-library .ws-library-item').length === {saved + 1}")
        self.assertIn("cart deck", self.js("document.querySelector('#ws-user-library').textContent"))

        # Copy also opens the component. The product row first returns to the
        # whole product; a second click folds its component list away.
        self.wait("document.querySelector('#workshop-stage').dataset.showing === 'deck'")
        self.pointer_click('#ws-product-catalog button[data-value="cart"]')
        self.wait("document.querySelector('#workshop-stage').dataset.showing === 'product'")
        self.assertEqual('14', self.js("document.querySelector('#ws-part-count').textContent"))
        self.pointer_click('#ws-product-catalog button[data-value="cart"]')
        self.wait("!document.querySelectorAll('#ws-product-catalog .ws-part-row').length")

    def test_a_component_opens_on_its_own_and_saves_under_a_new_name(self):
        """Clicking a component shows that piece alone, editable and saveable.

        The product's own headline numbers -- part count, balance, tip angle --
        say nothing about one wheel, so while it is alone on screen the panel
        reports the wheel instead, and the whole-product views are refused.
        """
        self.open_product("cart")
        self.wait("document.querySelectorAll('#ws-product-catalog .ws-part-row').length")
        self.click('#ws-product-catalog .ws-part-open[data-part="wheel-11"]')
        self.wait("document.querySelector('#workshop-stage').dataset.showing === 'wheel-11'")
        self.assertFalse(self.js("document.querySelector('#ws-isolation').hidden"))
        self.assertEqual("wheel-11", self.js("document.querySelector('#ws-name').textContent"))
        self.assertEqual("220 x 60 x 220 mm", self.js(
            "document.querySelector('#ws-base').textContent").replace("×", "x"))
        self.assertTrue(self.js("document.querySelector('#ws-buildability').hidden"))
        self.assertEqual(["matter", "physics", "collision", "relations"], self.js(
            "[...document.querySelectorAll('.ws-viewbar button')].filter(b=>b.disabled).map(b=>b.dataset.view)"))

        # It is edited as itself, and the reported size follows.
        self.click('[data-component-edit="thicker"]')
        self.wait("document.querySelector('#ws-base').textContent.includes('67')")
        self.assertEqual("wheel-11", self.js("document.querySelector('#workshop-stage').dataset.showing"))

        # It is saved under a name of the user's choosing, not a generated one.
        self.field("#ws-component-name", "Fat oak wheel", event="input")
        saved = self.js("document.querySelectorAll('#ws-user-library .ws-library-item').length")
        self.click("#ws-save-component")
        self.wait(f"document.querySelectorAll('#ws-user-library .ws-library-item').length === {saved + 1}")
        self.assertIn("Fat oak wheel", self.js("document.querySelector('#ws-user-library').textContent"))

        # And the whole product comes back with its own numbers.
        self.click("#ws-show-whole")
        self.wait("document.querySelector('#workshop-stage').dataset.showing === 'product'")
        self.assertTrue(self.js("document.querySelector('#ws-isolation').hidden"))
        self.assertEqual("14", self.js("document.querySelector('#ws-part-count').textContent"))
        self.assertEqual([], self.js(
            "[...document.querySelectorAll('.ws-viewbar button')].filter(b=>b.disabled).map(b=>b.dataset.view)"))

    def test_the_left_pane_has_no_dead_reference_sections(self):
        """Variants and the component-family reference are gone.

        Both sat folded inside one another, so neither could be found, and
        neither made a product. What is left is the product library, what the
        user saved, and their saved designs.
        """
        self.assertEqual(0, self.js(
            "document.querySelectorAll('#variant-list, #ws-library, #ws-more, #ws-reset-variants').length"))
        self.assertEqual(["Product library", "My library", "Saved designs"], self.js(
            "[...document.querySelectorAll('.ws-left h2')].map(h=>h.textContent)"))
        self.assertEqual(0, self.js("document.querySelectorAll('.ws-left details').length"))

    def test_cart_trace_has_actual_intermediate_simulation_states(self):
        self.open_product("cart")
        self.click('[data-mode="test"]')
        self.click('#ws-test-catalog button[data-value="cart_roll"]')
        self.click("#ws-run-bench")
        self.wait("!document.querySelector('#ws-run-bench').disabled && !document.querySelector('#ws-playback').hidden")
        self.assertGreater(int(self.js("document.querySelector('#ws-play-timeline').max")), 8)
        self.assertIn("Simulation result", self.js("document.querySelector('#ws-playback').textContent"))
        self.click("#ws-play-reset")
        self.assertEqual("0.00 s", self.js("document.querySelector('#ws-play-time').textContent"))

    def test_static_load_limits_are_opt_in_and_settings_invalidate_the_verdict(self):
        self.click('[data-mode="test"]')
        self.click('#ws-test-catalog button[data-value="declared_static_load"]')
        self.assertFalse(self.js("document.querySelector('[data-bench-control=\"evaluate_limits\"]').checked"))
        self.field('[data-bench-control="duration_s"]', .2)
        self.click("#ws-run-bench")
        self.wait("!document.querySelector('#ws-run-bench').disabled && document.querySelector('#ws-acceptance-status')")
        self.assertEqual("not-declared", self.js("document.querySelector('#ws-acceptance-status').dataset.status"))
        self.js("document.querySelector('[data-bench-control=\"evaluate_limits\"]').checked=true")
        self.field('[data-bench-control="max_displacement_m"]', 1)
        self.assertIsNone(self.js("document.querySelector('#ws-acceptance-status')"))
        self.click("#ws-run-bench")
        self.wait("!document.querySelector('#ws-run-bench').disabled && document.querySelector('#ws-acceptance-status')")
        self.assertEqual("passed", self.js("document.querySelector('#ws-acceptance-status').dataset.status"))
        self.field('[data-bench-control="max_displacement_m"]', 0)
        self.assertIsNone(self.js("document.querySelector('#ws-acceptance-status')"))
        self.click("#ws-run-bench")
        self.wait("!document.querySelector('#ws-run-bench').disabled && document.querySelector('#ws-acceptance-status')")
        self.assertEqual("failed", self.js("document.querySelector('#ws-acceptance-status').dataset.status"))
        self.assertIn("prototype_displacement_m", self.js("document.querySelector('#ws-bench-result').textContent"))

    def test_late_history_keeps_changed_test_controls_and_pending_result(self):
        # Hold optional startup history and release it during a native load test.
        # It must not recreate controls or increment the test request generation.
        self.page.send("Page.addScriptToEvaluateOnNewDocument", {"source": """
          const originalFetch=window.fetch.bind(window);
          window.fetch=async function(resource,init){
            const response=await originalFetch(resource,init);
            if(String(resource).endsWith('/api/workshop/remembered')){
              await new Promise(resolve=>window.__releaseHistory=resolve);
            }
            if(String(resource).endsWith('/api/workshop/plan') && JSON.parse(init.body).bench_test){
              await new Promise(resolve=>window.__releaseResult=resolve);
            }
            return response;
          };
        """})
        self.page.send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/world?workshop=1&history-test=1"})
        self.wait("typeof window.__releaseHistory==='function' && document.querySelector('#ws-test-catalog button[data-value=declared_static_load]')")
        self.click('[data-mode="test"]')
        self.click('#ws-test-catalog button[data-value="declared_static_load"]')
        self.field('[data-bench-control="duration_s"]', .2)
        self.field('[data-bench-control="max_displacement_m"]', .123)
        self.click("#ws-run-bench")
        self.wait("typeof window.__releaseResult==='function'")
        self.js("window.__releaseHistory()")
        # A marker after a microtask/timer proves the history callback completed.
        self.js("new Promise(resolve=>setTimeout(resolve,200))")
        self.assertEqual("0.123", self.js("document.querySelector('[data-bench-control=max_displacement_m]').value"))
        self.assertIsNone(self.js("document.querySelector('[data-bench-control=record_trace]')"))
        self.js("window.__releaseResult()")
        self.wait("!document.querySelector('#ws-run-bench').disabled && document.querySelector('#ws-acceptance-status')")
        self.assertEqual("not-declared", self.js("document.querySelector('#ws-acceptance-status').dataset.status"))

    def test_late_history_does_not_erase_unsubmitted_skin_edits(self):
        self.page.send("Page.addScriptToEvaluateOnNewDocument", {"source": """
          const originalFetch=window.fetch.bind(window);
          window.fetch=async function(resource,init){
            const response=await originalFetch(resource,init);
            if(String(resource).endsWith('/api/workshop/remembered')){
              await new Promise(resolve=>window.__releaseHistory=resolve);
            }
            return response;
          };
        """})
        self.page.send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/world?workshop=1&dirty-editor-test=1"})
        self.wait("typeof window.__releaseHistory==='function' && document.querySelector('#ws-parts button')")
        self.click('[data-mode="build"]')
        self.js("[...document.querySelectorAll('#ws-parts button')].find(b=>b.textContent==='leg-1').click()")
        self.field("#ws-skin-profile", "curve")
        self.field("#ws-skin-bend", .35, "input")
        self.js("document.querySelector('#ws-skin-physical').checked=true")
        self.js("window.__releaseHistory();new Promise(resolve=>setTimeout(resolve,200))")
        self.assertEqual("curve", self.js("document.querySelector('#ws-skin-profile').value"))
        self.assertAlmostEqual(.35, float(self.js("document.querySelector('#ws-skin-bend').value")))
        self.assertTrue(self.js("document.querySelector('#ws-skin-physical').checked"))
        self.click("#ws-apply-skin")
        self.wait("!document.querySelector('#ws-apply-skin').disabled && document.querySelector('#ws-measurement-basis').textContent.includes('Mass/balance from Matter')")
        self.assertAlmostEqual(.35, float(self.js("document.querySelector('#ws-skin-bend').value")))

    def test_changing_limits_during_a_run_discards_the_outdated_answer(self):
        self.click('[data-mode="test"]')
        self.click('#ws-test-catalog button[data-value="declared_static_load"]')
        self.field('[data-bench-control="duration_s"]', .2)
        self.js("""window.__originalFetch=window.fetch;window.fetch=async function(resource,init){
          const response=await window.__originalFetch(resource,init);
          if(String(resource).endsWith('/api/workshop/plan') && JSON.parse(init.body).bench_test){
            await new Promise(resolve=>{window.__releaseTest=resolve});
          }return response;
        };""")
        self.click("#ws-run-bench")
        self.wait("typeof window.__releaseTest==='function'")
        self.field('[data-bench-control="max_displacement_m"]', 0)
        self.js("window.__releaseTest();window.fetch=window.__originalFetch")
        self.wait("!document.querySelector('#ws-run-bench').disabled")
        self.assertEqual("", self.js("document.querySelector('#ws-bench-result').textContent"))

    def install_api(self, path, body):
        return self.js(f"""(async()=>{{
          const status=await fetch('/api/status').then(r=>r.json());
          const response=await fetch({json.dumps(path)},{{method:'POST',headers:{{'Content-Type':'application/json','X-Banjo-Token':status.csrf_token}},body:JSON.stringify({json.dumps(body)})}});
          return {{status:response.status,body:await response.json()}};
        }})()""")

    def test_installation_preview_confirm_retry_and_return_to_live_world(self):
        opened=self.install_api('/api/world/open',{'scene':'yard','fresh':True})
        self.assertEqual(200,opened['status'],opened)
        self.click('[data-mode="details"]')
        self.assertFalse(self.js("document.querySelector('#ws-install-authoring').checked"))
        self.assertTrue(self.js("document.querySelector('#ws-install-confirm').disabled"))
        self.click('#ws-install-preview')
        self.wait("!document.querySelector('#ws-install-preview').disabled")
        self.assertIn('Acknowledge',self.js("document.querySelector('#ws-notice').textContent"))
        self.click('#ws-install-authoring');self.click('#ws-install-preview')
        self.wait("document.querySelector('#ws-install-result').dataset.status==='preview'")
        self.assertIn('40 mm',self.js("document.querySelector('#ws-install-context').textContent"))
        self.field('#ws-install-x',3.5)
        self.assertTrue(self.js("document.querySelector('#ws-install-confirm').disabled"))
        self.click('#ws-install-preview')
        self.wait("document.querySelector('#ws-install-result').dataset.status==='preview'")
        self.js("""window.__nativeInstallFetch=window.fetch;window.fetch=(url,init)=>{
          if(String(url).endsWith('/api/world/workshop/commit'))window.__lastInstall=JSON.parse(init.body);
          return window.__nativeInstallFetch(url,init);
        };""")
        self.click('#ws-install-confirm')
        self.wait("document.querySelector('#ws-install-result').dataset.status==='installed'")
        request=self.js('window.__lastInstall');replay=self.install_api('/api/world/workshop/commit',request)
        self.assertEqual(200,replay['status'],replay);self.assertTrue(replay['body']['replayed'])
        root=replay['body']['root_body'];link=self.js("document.querySelector('#ws-install-result a').href")
        self.page.send('Page.navigate',{'url':link})
        self.wait("window.banjoRoom?.world.session")
        self.wait(f"window.banjoRoom.world.bodies.has({json.dumps(root)})")
        self.assertEqual(1,self.js(f"[...window.banjoRoom.world.bodies.keys()].filter(name=>name==={json.dumps(root)}).length"))
        self.assertGreater(self.js("document.querySelector('canvas').width"),0)

    def test_precise_thin_table_installs_renders_picks_and_reloads_in_live_world(self):
        seed=self.install_api('/api/workshop/feedback', {
            'kind':'table','design_id':'browser-live-thin',
            'parameters':{'top_thickness_m':.005,'leg_section_m':.015},
            'save_design':True,'label':'Thin table for live world'})
        self.assertEqual(200,seed['status'],seed)
        self.page.send('Page.navigate',{'url':f'http://127.0.0.1:{self.port}/world?workshop=1&design=browser-live-thin'})
        self.wait("document.querySelector('#ws-buildability-summary')?.textContent.includes('Not buildable')")
        opened=self.install_api('/api/world/open',{'scene':'yard','fresh':True})
        self.assertEqual(200,opened['status'],opened)
        self.click('[data-mode="build"]');self.field('#ws-mechanical-model','rigid');self.click('#ws-apply-mechanics')
        self.wait("document.querySelector('#ws-matter-status')?.textContent.includes('5 precise rigid boxes')")
        self.click('[data-mode="details"]');self.field('#ws-install-x',3.123)
        self.click('#ws-install-authoring');self.click('#ws-install-preview')
        self.wait("document.querySelector('#ws-install-result').dataset.status==='preview'")
        self.assertIn('5 precise collision boxes, zero lattice cells',self.js("document.querySelector('#ws-install-result').textContent"))
        self.assertIn('continuous placement',self.js("document.querySelector('#ws-install-context').textContent"))
        self.click('#ws-install-confirm')
        self.wait("document.querySelector('#ws-install-result').dataset.status==='installed'")
        self.page.send('Page.navigate',{'url':self.js("document.querySelector('#ws-install-result a').href")})
        self.wait("window.banjoRoom?.ready() && [...window.banjoRoom.world.bodies.values()].some(b=>b.fromPrecise)")
        root=self.js("[...window.banjoRoom.world.bodies].find(([name,b])=>b.fromPrecise)[0]")
        observed=self.js("(()=>{const b=window.banjoRoom.world.bodies.get("+json.dumps(root)+");const m=new window.banjoRoom.THREE.Matrix4();b.mesh.getMatrixAt(0,m);return {count:b.mesh.count,scaleY:m.elements[5],cells:b.fromCells,x:b.mesh.position.x,mass:b.mass,model:b.mechanicalModel};})()")
        self.assertEqual(5,observed['count']);self.assertAlmostEqual(.005,observed['scaleY'],places=8)
        self.assertFalse(observed['cells']);self.assertAlmostEqual(3.123,observed['x'],places=5)
        self.assertAlmostEqual(3.41565,observed['mass'],places=4);self.assertEqual('precise-rigid-v1',observed['model'])
        session=self.js('window.banjoRoom.world.session')
        hit=self.install_api('/api/live/act',{'session':session,'op':'pick','from':[3.123,1,0],'dir':[0,-1,0],'max_m':1})
        self.assertEqual(root,hit['body']['name'])
        self.js('window.banjoRoom.standAt(5,2,3);window.banjoRoom.lookAt(3.123,.5,0)')
        self.capture_evidence('thin-rigid-live-world.png')
        self.js('window.__beforeRigidReload=true');self.page.send('Page.reload',{})
        self.wait('!window.__beforeRigidReload && window.banjoRoom?.ready() && window.banjoRoom.world.bodies.has('+json.dumps(root)+')')
        self.assertEqual(5,self.js('window.banjoRoom.world.bodies.get('+json.dumps(root)+').mesh.count'))

    def test_installation_stale_world_is_visible_and_does_not_install(self):
        opened=self.install_api('/api/world/open',{'scene':'yard','fresh':True})['body']
        self.click('[data-mode="details"]');self.click('#ws-install-authoring');self.click('#ws-install-preview')
        self.wait("document.querySelector('#ws-install-result').dataset.status==='preview'")
        advanced=self.install_api('/api/live/act',{'session':opened['session'],'op':'step','dt':1/120,'n':1})
        self.assertEqual(200,advanced['status'],advanced)
        self.click('#ws-install-confirm');self.wait("!document.querySelector('#ws-install-confirm').disabled")
        self.assertIn('changed after preview',self.js("document.querySelector('#ws-notice').textContent"))
        state=self.install_api('/api/live/act',{'session':opened['session'],'op':'poses'})
        self.assertEqual(200,state['status'],state)
        self.assertFalse(any(b['name'].startswith('workshop-') for b in state['body']['bodies']))

    def test_late_installation_preview_cannot_apply_to_another_candidate(self):
        self.install_api('/api/world/open',{'scene':'yard','fresh':True})
        self.click('[data-mode="details"]');self.click('#ws-install-authoring')
        self.js("""window.__nativeInstallFetch=window.fetch;window.fetch=async (url,init)=>{
          const response=await window.__nativeInstallFetch(url,init);
          if(String(url).endsWith('/api/world/workshop/preview'))await new Promise(resolve=>window.__releaseInstall=resolve);
          return response;
        };""")
        self.click('#ws-install-preview');self.wait("typeof window.__releaseInstall==='function'")
        self.open_product('chair')
        self.js('window.__releaseInstall();window.fetch=window.__nativeInstallFetch')
        self.wait("!document.querySelector('#ws-install-preview').disabled")
        self.assertTrue(self.js("document.querySelector('#ws-install-confirm').disabled"))
        self.assertNotEqual('preview',self.js("document.querySelector('#ws-install-result').dataset.status"))

    def test_thin_rigid_product_roundtrip_and_actual_native_playback(self):
        # Seed a normal saved source through the public API, then operate real UI controls.
        seed = self.install_api('/api/workshop/feedback', {
            'kind':'table', 'design_id':'browser-thin-rigid',
            'parameters':{'top_thickness_m':.005,'leg_section_m':.015},
            'save_design':True, 'label':'Browser thin table'})
        self.assertEqual(200, seed['status'], seed)
        self.page.send("Page.navigate", {"url":f"http://127.0.0.1:{self.port}/world?workshop=1&design=browser-thin-rigid"})
        self.wait("document.querySelector('#ws-buildability-summary')?.textContent.includes('Not buildable')")
        self.assertIn('top',self.js("document.querySelector('#ws-buildability-parts').textContent"))
        self.capture_evidence('thin-grid-warning.png')
        self.click('[data-mode="build"]')
        self.js("[...document.querySelectorAll('#ws-parts button')].find(b=>b.textContent==='leg-1').click()")
        self.field('#ws-mechanical-model','rigid');self.click('#ws-apply-mechanics')
        self.wait("document.querySelector('#ws-matter-status')?.textContent.includes('5 precise rigid boxes')")
        self.assertEqual('3.416 kg',self.js("document.querySelector('#ws-mass').textContent"))
        self.assertIn('zero lattice cells',self.js("document.querySelector('#ws-buildability-summary').textContent"))
        self.field('#ws-matter-cell',.01);self.click('#ws-refresh-matter')
        self.wait("document.querySelector('#ws-matter-status')?.textContent.includes('5 precise rigid boxes')")
        self.assertEqual('3.416 kg',self.js("document.querySelector('#ws-mass').textContent"))
        self.click('[data-mode="test"]')
        self.assertEqual('rigid_motion',self.js("document.querySelector('#ws-bench-test').value"))
        self.field('[data-bench-control="duration_s"]',.5)
        self.click('#ws-run-bench')
        self.wait("document.querySelector('#ws-bench-result pre')?.textContent.includes('verified-precise-rigid-shapes')")
        proof=json.loads(self.js("document.querySelector('#ws-bench-result pre').textContent"))
        self.assertEqual('measured',proof['status']);self.assertFalse(proof['strength_certified'])
        self.assertEqual(0,proof['measured']['stored_cells'])
        self.assertEqual(5,proof['measured']['collision_boxes'])
        self.assertTrue(proof['native_geometry_verified'])
        self.assertEqual('verified-precise-rigid-shapes',proof['playback']['geometry_basis'])
        self.assertGreater(proof['playback']['states'],2)
        # The evidence panel deliberately summarizes (rather than duplicates)
        # the full native trace. Exercise the actual rendered states too.
        if self.js("document.querySelector('#ws-play').textContent") == 'Pause':
            self.click('#ws-play')
        self.field('#ws-play-timeline',0,'input')
        before=self.js("document.querySelector('#workshop-stage').dataset.physicsPose")
        self.field('#ws-play-timeline',self.js("document.querySelector('#ws-play-timeline').max"),'input')
        self.assertNotEqual(before,self.js("document.querySelector('#workshop-stage').dataset.physicsPose"))
        self.assertEqual('5',self.js("document.querySelector('#workshop-stage').dataset.physicsBodyCount"))
        self.assertIn('5 collision shapes · 1 rigid body',self.js("document.querySelector('#ws-simulation-readout').textContent"))
        self.capture_evidence('thin-rigid-native-motion.png')
        self.assertIn('Exact rigid',self.js("document.querySelector('#ws-play-note').textContent"))
        self.click('[data-mode="details"]');self.field('#ws-save-name','Browser precise rigid table');self.click('#ws-save-design')
        self.wait("document.querySelector('#ws-save-status').textContent.includes('Saved designs and My Library')")
        self.js('window.__thinPageBeforeReload=true')
        self.page.send('Page.reload',{})
        self.wait("!window.__thinPageBeforeReload && document.querySelector('#ws-mechanical-model')?.value==='rigid' && document.querySelector('#ws-mass')?.textContent==='3.416 kg'")
        self.wait("document.querySelector('#ws-buildability-summary')?.textContent.includes('anchored-scenery installation available')")


    def test_test_tab_only_shows_working_simulations_and_disables_unsupported_products(self):
        self.click('[data-mode="test"]')
        values=self.js("[...document.querySelectorAll('#ws-test-catalog button')].map(b=>b.dataset.value)")
        self.assertEqual(["drop_product","slide_product","impact_product","declared_static_load"],values)
        self.assertEqual("drop_product",self.js("document.querySelector('#ws-bench-test').value"))
        self.assertIsNone(self.js("document.querySelector('[data-bench-control=record_trace]')"))
        self.open_product("shelf-unit")
        self.assertTrue(self.js("document.querySelector('#ws-run-bench').disabled"))
        self.assertEqual(0,self.js("document.querySelectorAll('#ws-test-catalog button').length"))
        self.assertIn("No working simulation",self.js("document.querySelector('#ws-bench-controls').textContent"))

    def test_a_glass_table_dropped_far_enough_is_seen_to_break_into_pieces(self):
        self.click('[data-mode="build"]')
        self.js("[...document.querySelectorAll('#ws-parts button')].find(b=>b.textContent==='top').click()")
        self.field('#ws-edit-scope','all')
        self.field('#ws-part-material','glass')
        self.wait("document.querySelector('#ws-mass')?.textContent==='98.580 kg'")
        self.click('[data-mode="test"]')
        # Raising the drop raises the time beside it, in plain sight, so the run sees the landing.
        self.assertEqual('20',self.js("document.querySelector('[data-bench-control=height_m]').max"))
        self.field('[data-bench-control=height_m]',4)
        self.assertGreaterEqual(float(self.js("document.querySelector('[data-bench-control=duration_s]').value")),1.6)
        self.click('#ws-run-bench')
        self.wait("document.querySelector('#ws-break-outcome')?.dataset.outcome==='broke'")
        pieces=int(self.js("document.querySelector('#ws-break-outcome').dataset.pieces"))
        self.assertGreater(pieces,4)
        self.assertIn(f'Broke into {pieces} pieces',self.js("document.querySelector('#ws-break-outcome').textContent"))
        # The engine's own reading of the landing, not a rule the page made up.
        self.assertRegex(self.js("document.querySelector('#ws-break-reading').textContent"),
                         r'Met the ground at 8\.\d\d m/s\. Against that, this can first break at 8\.70 m/s')
        if self.js("document.querySelector('#ws-play').textContent") == 'Pause':
            self.click('#ws-play')
        # Whole at the start, and at the end every piece is a drawn body of its own cells.
        self.field('#ws-play-timeline',0,'input')
        self.assertEqual('1',self.js("document.querySelector('#workshop-stage').dataset.physicsBodyCount"))
        self.assertIn('1 simulated body',self.js("document.querySelector('#ws-simulation-readout').textContent"))
        self.field('#ws-play-timeline',self.js("document.querySelector('#ws-play-timeline').max"),'input')
        self.assertEqual(str(pieces),self.js("document.querySelector('#workshop-stage').dataset.physicsBodyCount"))
        self.assertIn(f'In {pieces} pieces',self.js("document.querySelector('#ws-simulation-readout').textContent"))
        note=self.js("document.querySelector('#ws-play-note').textContent")
        self.assertIn('every piece as the cells the engine left it',note)
        self.assertNotIn('simplified collision shapes',note)
        self.capture_evidence('glass-table-broken.png')
        # The same table in oak, from the same height, is still a table.
        self.click('[data-mode="build"]')
        self.field('#ws-part-material','oak')
        self.wait("document.querySelector('#ws-mass')?.textContent==='27.602 kg'")
        self.click('[data-mode="test"]')
        self.field('[data-bench-control=height_m]',4)
        self.click('#ws-run-bench')
        self.wait("document.querySelector('#ws-break-outcome')?.dataset.outcome==='held'")
        self.assertIn('still in one piece',self.js("document.querySelector('#ws-break-outcome').textContent"))

    def test_a_load_says_whether_it_held_and_by_how_much(self):
        self.click('[data-mode="build"]')
        self.js("[...document.querySelectorAll('#ws-parts button')].find(b=>b.textContent==='top').click()")
        self.field('#ws-edit-scope','all')
        self.field('#ws-part-material','concrete')
        self.wait("document.querySelector('#ws-part-material').value==='concrete' && !document.querySelector('#ws-mass').textContent.startsWith('27.602')")
        self.click('[data-mode="test"]')
        self.click('#ws-test-catalog button[data-value="declared_static_load"]')
        self.wait("document.querySelector('[data-bench-control=load_kg]')")
        self.field('[data-bench-control=load_kg]',400)
        self.field('[data-bench-control=cell_size_m]',.02)
        self.field('[data-bench-control=duration_s]',1)
        self.click('#ws-run-bench')
        self.wait("document.querySelector('#ws-load-outcome')")
        self.assertEqual('held',self.js("document.querySelector('#ws-load-outcome').dataset.outcome"))
        self.assertRegex(self.js("document.querySelector('#ws-load-outcome').textContent"),r'^Held 400\.\d kg, at \d\d% of what breaks it$')
        reading=self.js("document.querySelector('#ws-load-reading').textContent")
        self.assertRegex(reading,r'MPa of bending in it over the 1\.0\d m between its feet, against the 3\.0 MPa it can take')
        self.assertIn('Statics on its own cells: held',reading)
        self.capture_evidence('concrete-table-held-with-margin.png')

    def test_a_blow_from_a_weight_is_a_test_the_page_offers_and_runs(self):
        self.click('[data-mode="test"]')
        self.click('#ws-test-catalog button[data-value="impact_product"]')
        self.wait("document.querySelector('[data-bench-control=striker_kg]')")
        self.field('[data-bench-control=striker_kg]',20)
        self.field('[data-bench-control=speed_m_s]',15)
        self.click('#ws-run-bench')
        self.wait("document.querySelector('#ws-break-outcome')?.dataset.outcome==='broke'")
        self.assertRegex(self.js("document.querySelector('#ws-bench-result').textContent"),r'Struck by 18\.1 kg of iron at 15\.0 m/s: 2,0\d\d J')
        self.assertIn('Met workshop/striker at 15.00 m/s',self.js("document.querySelector('#ws-break-reading').textContent"))
        self.capture_evidence('oak-table-struck.png')

    def test_run_moves_visible_object_automatically_and_replay_restarts(self):
        self.click('[data-mode="test"]')
        self.click('#ws-run-bench')
        self.wait("document.querySelector('#ws-simulation-status')?.dataset.state==='complete' && Number(document.querySelector('#workshop-stage').dataset.physicsTime)>0")
        self.click('#ws-play')  # pause the automatically started run
        self.assertIn("computed",self.js("document.querySelector('#ws-play-note').textContent"))
        before=self.js("document.querySelector('#workshop-stage').dataset.physicsPose")
        builds=self.js("document.querySelector('#workshop-stage').dataset.physicsMeshBuilds")
        rect=self.js("(()=>{const r=document.querySelector('#workshop-stage').getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,scale:1};})()")
        first=self.page.send('Page.captureScreenshot',{'format':'png','clip':rect})['data']
        end=self.js("document.querySelector('#ws-play-timeline').max")
        self.field('#ws-play-timeline',end,'input')
        self.assertNotEqual(before,self.js("document.querySelector('#workshop-stage').dataset.physicsPose"))
        self.assertEqual(builds,self.js("document.querySelector('#workshop-stage').dataset.physicsMeshBuilds"),"Do not rebuild voxel meshes each frame")
        time.sleep(.1)
        last=self.page.send('Page.captureScreenshot',{'format':'png','clip':rect})['data']
        self.assertNotEqual(first,last,"The 3D viewport itself must change, not only status text")
        self.click('#ws-play')
        self.wait("Number(document.querySelector('#ws-play-timeline').value)<Number(document.querySelector('#ws-play-timeline').max)")
        self.assertEqual("Pause",self.js("document.querySelector('#ws-play').textContent"))

    def test_run_and_readout_are_visible_and_clickable_without_sidebar_scrolling(self):
        self.page.send("Emulation.setDeviceMetricsOverride",{"width":1280,"height":720,"deviceScaleFactor":1,"mobile":False})
        self.click('[data-mode="test"]')
        self.wait("!document.querySelector('#ws-simulation-dock').hidden")
        point=self.js("""(()=>{const e=document.querySelector('#ws-run-bench'),r=e.getBoundingClientRect();
          return {x:r.x+r.width/2,y:r.y+r.height/2,visible:r.top>=0&&r.bottom<=innerHeight&&r.width>0,
          hit:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===e};})()""")
        self.assertTrue(point['visible'] and point['hit'],point)
        # Real mouse input: a programmatic element.click() can pass for an
        # offscreen button and failed to catch the previous below-fold layout.
        for kind in ('mousePressed','mouseReleased'):
            self.page.send('Input.dispatchMouseEvent',{'type':kind,'x':point['x'],'y':point['y'],'button':'left','clickCount':1})
        self.wait("document.querySelector('#ws-simulation-status')?.dataset.state==='complete'")
        self.assertTrue(self.js("(()=>{const r=document.querySelector('#ws-simulation-readout').getBoundingClientRect();return r.height>0&&r.top>=0&&r.bottom<=innerHeight;})()"))
        self.assertEqual(.25,float(self.js("document.querySelector('#ws-play-speed').value")))
        self.click('[data-mode="build"]')
        self.assertTrue(self.js("document.querySelector('#ws-simulation-dock').hidden"))

    def test_heating_has_visible_changing_temperature_and_accelerated_display(self):
        self.open_product('kettle');self.click('[data-mode="test"]')
        self.click('#ws-run-bench')
        self.wait("document.querySelector('#ws-simulation-status')?.dataset.state==='complete'")
        self.click('#ws-play-reset')
        first=self.js("document.querySelector('#ws-simulation-readout').textContent")
        self.assertIn('20.0',first)
        self.assertEqual('30',self.js("document.querySelector('#ws-play-speed').value"))
        self.field('#ws-play-timeline',self.js("document.querySelector('#ws-play-timeline').max"),'input')
        self.assertNotEqual(first,self.js("document.querySelector('#ws-simulation-readout').textContent"))
        self.assertIn('Water',self.js("document.querySelector('#ws-simulation-readout').textContent"))

    def click_object_at(self, point_m):
        """A real mouse click on a point of the object, wherever the camera has put it."""
        x, y = self.js(f"document.querySelector('#workshop-stage').pagePointOf({json.dumps(point_m)})")
        for kind in ("mousePressed", "mouseReleased"):
            self.page.send("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1})

    def test_a_part_is_placed_on_a_clicked_face_added_saved_and_reopened_as_built(self):
        self.open_product('cart'); self.click('[data-mode="build"]')
        self.assertIn('still the template', self.js("document.querySelector('#ws-build-joints').textContent"))
        self.field('#ws-build-what', 'family:post'); self.field('#ws-build-length', .3)
        # The turn and sink buttons belong to a part being placed, and are not on show before one is.
        self.assertEqual('none', self.js("getComputedStyle(document.querySelector('#ws-build-adjust')).display"))
        self.click('#ws-build-place')
        self.wait("document.querySelector('#workshop-stage').classList.contains('ws-placing')")
        self.assertEqual('skin', self.js("document.querySelector('.ws-viewbar [aria-pressed=true]').dataset.view"))
        # The first seeded cart has its deck top at 0.30 m; click 0.2 m along it.
        self.click_object_at([0.2, 0.30, 0.0])
        self.wait("!document.querySelector('#ws-build-adjust').hidden")
        said = self.js("document.querySelector('#ws-build-status').textContent")
        self.assertIn('post-1', said); self.assertIn('Meets deck over 25.0 cm²', said)
        self.assertEqual('14', self.js("document.querySelector('#ws-part-count').textContent"))   # a preview adds nothing
        self.click('#ws-build-add')
        self.wait("document.querySelector('#ws-part-count').textContent==='15'")
        self.assertEqual('15 parts · built part by part', self.js("document.querySelector('#ws-name').textContent"))
        self.assertIn('post-1', self.js("document.querySelector('#ws-selected-part').textContent"))
        self.assertEqual(1, self.js("document.querySelectorAll('.ws-joint-row[data-joint]').length"))
        self.assertIn('deck ↔ post-1', self.js("document.querySelector('.ws-joint-row[data-joint]').textContent"))
        self.assertFalse(self.js("document.querySelector('#workshop-stage').classList.contains('ws-placing')"))
        self.assertEqual('none', self.js("getComputedStyle(document.querySelector('#ws-build-adjust')).display"))

        self.click('[data-mode="details"]'); self.field('#ws-save-name', 'cart with a post')
        self.click('#ws-save-design')
        self.wait("document.querySelector('#ws-save-status').textContent.includes('Saved')")
        self.page.send("Page.reload")
        self.wait("document.querySelector('#ws-user-library .ws-library-item')")
        self.js("[...document.querySelectorAll('#ws-user-library .ws-library-item')].find(c=>c.textContent.includes('cart with a post')).click()")
        self.wait("document.querySelector('#ws-part-count').textContent==='15'")
        self.click('[data-mode="build"]')
        self.assertIn('17 joints', self.js("document.querySelector('#ws-build-joints').textContent"))

        self.js("[...document.querySelectorAll('#ws-parts .ws-part-link')].find(b=>b.textContent==='handle').click()")
        self.click('#ws-build-remove')
        self.wait("document.querySelector('#ws-part-count').textContent==='14'")
        self.assertIn('15 joints', self.js("document.querySelector('#ws-build-joints').textContent"))

    def test_a_push_on_the_handle_says_which_joint_goes_first_and_marks_it(self):
        self.open_product('cart'); self.click('[data-mode="build"]')
        self.click('#ws-build-adopt')
        self.wait("document.querySelectorAll('.ws-joint-row[data-joint]').length===16")
        self.js("[...document.querySelectorAll('#ws-parts .ws-part-link')].find(b=>b.textContent==='handle').click()")
        self.field('#ws-push-force', 3000); self.click('#ws-push-go')
        self.wait("document.querySelector('#ws-joint-screen')")
        self.assertEqual('2', self.js("document.querySelector('#ws-joint-screen').dataset.givesWay"))
        self.assertIn('handle-arm', self.js("document.querySelector('#ws-first-to-give').textContent"))
        self.assertIn('2 pieces', self.js("document.querySelector('#ws-comes-apart').textContent"))
        self.assertEqual(2, self.js("document.querySelectorAll('#ws-joint-screen .ws-joint-row.gives-way').length"))
        # The analysis is a Build aid; the Test tab still offers only simulations.
        self.click('[data-mode="test"]')
        self.assertNotIn('force_probe', self.js("[...document.querySelector('#ws-bench-test').options].map(o=>o.value).join(',')"))
        # A lighter push holds, and a new spot clears the old answer.
        self.click('[data-mode="build"]'); self.field('#ws-push-force', 100)
        self.wait("document.querySelector('#ws-joint-screen')?.dataset.givesWay==='0'")
        self.js("[...document.querySelectorAll('#ws-parts .ws-part-link')].find(b=>b.textContent==='deck').click()")
        self.assertTrue(self.js("!!document.querySelector('#ws-joint-screen')"))

    def test_placing_and_pushing_bring_the_whole_product_back_from_one_component_shown_alone(self):
        self.open_product('cart')
        self.click('#ws-product-catalog .ws-part-open[data-part="deck"]')
        self.wait("document.querySelector('#workshop-stage').dataset.showing==='deck'")
        # A part goes against the product, not against one piece of it shown alone.
        self.click('[data-mode="build"]'); self.click('#ws-build-place')
        self.wait("document.querySelector('#workshop-stage').dataset.showing==='product'")
        self.click('#ws-build-cancel')
        self.click('#ws-build-adopt')
        # The deck is still the selected part, so the list shows the six joints that hold it.
        self.wait("document.querySelector('#ws-build-joints').textContent.includes('6 of 16 joints hold deck')")
        self.click('#ws-product-catalog .ws-part-open[data-part="handle"]')
        self.wait("document.querySelector('#workshop-stage').dataset.showing==='handle'")
        self.click('#ws-push-go')
        self.wait("document.querySelector('#ws-joint-screen')")
        self.assertEqual('product', self.js("document.querySelector('#workshop-stage').dataset.showing"))
        self.assertIn('handle', self.js("document.querySelector('#ws-selected-part').textContent"))

    def test_a_new_build_starts_from_one_part_and_joins_the_product_list(self):
        self.click('[data-mode="build"]')
        self.field('#ws-build-what', 'family:surface')
        self.click('#ws-build-new')
        self.wait("document.querySelector('#workshop-stage').dataset.kind==='custom'")
        self.assertEqual('1 part · built part by part', self.js("document.querySelector('#ws-name').textContent"))
        self.assertEqual('true', self.js("document.querySelector('#ws-product-catalog button[data-value=custom]').getAttribute('aria-current')"))
        self.field('#ws-build-what', 'family:post'); self.field('#ws-build-length', .4)
        self.click('#ws-build-place')
        self.click_object_at([0.0, 0.04, 0.0])
        self.wait("!document.querySelector('#ws-build-adjust').hidden")
        self.click('#ws-build-add')
        self.wait("document.querySelector('#ws-part-count').textContent==='2'")
        self.assertIn('surface-1 ↔ post-1', self.js("document.querySelector('.ws-joint-row[data-joint]').textContent"))

    def test_no_simulation_response_is_a_visible_failure_not_a_success(self):
        self.click('[data-mode="test"]')
        self.js("""window.__oldFetch=window.fetch;window.fetch=(url,init)=>{
          if(String(url).endsWith('/api/workshop/plan') && JSON.parse(init.body).bench_test)
            return Promise.resolve(new Response(JSON.stringify({bench:{evidence:'report-only'}}),{status:200}));
          return window.__oldFetch(url,init);
        };""")
        self.click('#ws-run-bench')
        self.wait("document.querySelector('#ws-simulation-status')?.dataset.state==='error'")
        self.assertTrue(self.js("document.querySelector('#ws-playback').hidden"))
        self.assertIn('No visible simulation',self.js("document.querySelector('#ws-simulation-status').textContent"))


if __name__ == "__main__":
    unittest.main()
