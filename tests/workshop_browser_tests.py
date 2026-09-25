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
          build:document.querySelector('#ws-build-status')?.textContent,
          parts:document.querySelector('#ws-part-count')?.textContent,
          test:document.querySelector('#ws-bench-test')?.value,
          result:document.querySelector('#ws-bench-result')?.textContent,
          runDisabled:document.querySelector('#ws-run-bench')?.disabled,
          controls:[...document.querySelectorAll('[data-bench-control]')].map(e=>({
            name:e.dataset.benchControl,value:e.value,checked:e.checked}))})""")
        errors = [e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"]
        raise AssertionError(f"Workshop condition timed out: {condition}; {diagnostics}; runtimeErrors={json.dumps(errors)}")

    def reveal(self, selector):
        """Open any disclosure the control is inside before touching it.

        A closed <details> is content-visibility:hidden, not display:none, so a
        control in it still reports a size and cannot be clicked. The bench puts
        what the old tabs held under "Bench extras", and a person opens it.
        """
        self.js(f"""(()=>{{const e=document.querySelector({json.dumps(selector)}); if(!e) return 0;
          let n=e.parentElement, opened=0, step=null;
          while(n){{ if(n.tagName==='DETAILS' && !n.open){{ n.open=true; opened++; }}
                     if(n.classList && n.classList.contains('ws-step-pane') && n.hidden) step=n.dataset.mode;
                     n=n.parentElement; }}
          // A control in another step is reached by going to that step, which
          // is what a person does; the bench shows one step at a time.
          if(step) dispatchEvent(new CustomEvent('banjo-workshop-mode',{{detail:step}}));
          return opened;}})()""")

    def open_extras(self, mode="build"):
        """The bench is one screen now; what the old tabs held is one disclosure.

        Every panel the three tabs used to separate -- the component editor, the
        test bench, buildability, the bill, save, feedback, placement -- lives
        under "Bench extras". Opening it is what switching tab used to be, so a
        test that was about a panel goes on being about that panel.

        Switching to the Test tab also told the workspace, and that is what set
        a situation up. There is no tab to switch now, so the same word is said
        here; without it nothing is ever prepared to run.
        """
        self.js(f"""(()=>{{const d=document.querySelector('#ws-extras'); if(d) d.open=true;
          dispatchEvent(new CustomEvent('banjo-workshop-mode', {{detail:{json.dumps(mode)}}}));
          return 1;}})()""")

    @staticmethod
    def _mode_of(selector):
        """Which step of the bench a [data-mode=...] selector asks for.

        There are four now -- start, build, test, details -- and they are the
        same words the workspace has always been told. This used to fold every
        one that was not "test" into "build", so asking for Keep got Change.
        """
        for mode in ("start", "build", "test", "details"):
            if f'data-mode="{mode}"' in selector or f"data-mode='{mode}'" in selector:
                return mode
        return "build"

    def click(self, selector):
        if "data-mode" in selector:
            return self.open_extras(self._mode_of(selector))
        self.reveal(selector)
        self.js(f"document.querySelector({json.dumps(selector)}).click()")

    def pointer_click(self, selector):
        """Use actual hit testing, not HTMLElement.click through an overlay.

        A control the bench no longer SHOWS is clicked plainly instead. The
        owner took the right-hand panel off the page -- "since we can't make
        this work we should just leave it all up to the chat" -- so what is
        left in it is machinery the page and the chat drive, not a panel
        anybody points at. Hit-testing something deliberately off screen would
        be asserting that it is on screen. Everything still on the bench keeps
        the real hit test, which is what this method is for.
        """
        if "data-mode" in selector:
            return self.open_extras(self._mode_of(selector))
        self.reveal(selector)
        if self.js(f"Boolean(document.querySelector({json.dumps(selector)})"
                   f"?.closest('.ws-right[hidden], #ws-hidden-controls'))"):
            return self.js(f"document.querySelector({json.dumps(selector)}).click()")
        # 'center', not 'nearest': a control sitting on the pane's bottom edge
        # is scrolled far enough to be hit, not just far enough to be inside.
        self.js(f"document.querySelector({json.dumps(selector)}).scrollIntoView({{block:'center'}})")
        point=self.js(f"""(()=>{{const e=document.querySelector({json.dumps(selector)}),r=e.getBoundingClientRect();
          const x=r.left+r.width/2,y=r.top+r.height/2;
          const over=document.elementFromPoint(x,y);
          return {{x,y,visible:r.width>0&&r.height>0,hit:e.contains(over),
                   over:over?over.tagName+(over.id?'#'+over.id:'')+(over.className?'.'+String(over.className).split(' ')[0]:''):null,
                   inner:[innerWidth,innerHeight]}};}})()""")
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
        # And the person is told, over the view. The panel this is written in
        # is not on the bench any more, so a design the room cannot carry has
        # to reach them some other way than a paragraph nobody can see.
        self.assertFalse(self.js("document.querySelector('#ws-notice').hidden"))
        self.assertIn("Not buildable", self.js("document.querySelector('#ws-notice').textContent"))
        self.assertTrue(self.js("document.querySelector('#ws-notice').getBoundingClientRect().height>0"))
        self.assertIn("more than 50,000 cells", self.js("document.querySelector('#ws-matter-status').textContent").lower())
        # And it is said where it is read: over the object, not in a panel.
        self.assertLess(
            self.js("document.querySelector('#ws-notice').getBoundingClientRect().top"),
            self.js("document.querySelector('#workshop-stage').getBoundingClientRect().bottom"))

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
        self.wait("document.querySelector('#ws-test-catalog [data-value=try_in_a_room]')")
        self.pointer_click('#ws-test-catalog [data-value="try_in_a_room"]')
        self.wait("document.querySelector('#ws-setup-status')?.dataset.state === 'ready'",timeout=60)
        self.assertEqual("setup",self.js("document.querySelector('#workshop-stage').dataset.phase"))
        self.assertEqual("1",self.js("document.querySelector('#workshop-stage').dataset.physicsBodyCount"))
        self.assertEqual("0",self.js("document.querySelector('#workshop-stage').dataset.physicsTime"))
        self.assert_geometry_is_visible()
        # The object gets the page. The bench is the chat, the object and one
        # bar over it, so the only things allowed over the canvas are the bar,
        # a notice, and the player that a run leaves behind.
        layout=self.js("""(()=>{const c=document.querySelector('#workshop-stage').getBoundingClientRect();
            const over=[...document.querySelectorAll('.ws-viewport > *')].filter(e=>!e.hidden
              && e.id!=='workshop-stage' && getComputedStyle(e).position==='absolute'
              && e.getBoundingClientRect().height>0).map(e=>e.id||e.className);
            return {width:c.width,height:c.height,over};})()""")
        self.assertGreater(layout["width"],700);self.assertGreater(layout["height"],250)
        self.assertEqual([],layout["over"],"nothing floats over the object until a run does")
        self.field('[data-bench-control="seconds"]',1)
        self.field('[data-bench-control="load_kg"]',10)
        self.wait("document.querySelector('#ws-setup-status')?.dataset.state === 'ready' && document.querySelector('#ws-setup-status').textContent.includes('10 kg')",timeout=60)
        self.pointer_click('#ws-run-bench')
        self.wait("document.querySelector('#ws-simulation-status')?.dataset.state === 'complete'",timeout=60)
        self.assertFalse(self.js("document.querySelector('#ws-playback').hidden"))
        self.pointer_click('#ws-play')
        self.pointer_click('#ws-reset-setup')
        self.wait("document.querySelector('#ws-setup-status')?.dataset.state === 'ready'")
        self.assertEqual("0",self.js("document.querySelector('#workshop-stage').dataset.physicsTime"))
        self.assert_geometry_is_visible()
        self.assertEqual("",self.js("document.querySelector('#ws-bench-result').textContent"),
                         "Reset must not present the previous run's verdict as an unrun setup result")

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
                        # Only the ways of DRAWING it. The bar carries the product picker,
            # the points of view and the way out of the bench as well now.
            "[...document.querySelectorAll('.ws-viewbar button[data-view]')].filter(b=>b.disabled).map(b=>b.dataset.view)"))

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
                        # Only the ways of DRAWING it. The bar carries the product picker,
            # the points of view and the way out of the bench as well now.
            "[...document.querySelectorAll('.ws-viewbar button[data-view]')].filter(b=>b.disabled).map(b=>b.dataset.view)"))

    def test_the_bench_is_the_chat_the_object_and_one_bar(self):
        """Three goes at this pane, and what the owner said about each.

        It was one shut drawer called "Bench extras" holding about fifty
        working controls, and nobody opened it. Un-buried, it was six named
        sections: "there are so many buttons and fields in the right nav of the
        workshop I don't have a clue where to begin on it." Arranged as four
        steps: "I don't really understand how to use the try or change or keep
        functions, it makes no sense. Since we can't make this work we should
        just leave it all up to the chat."

        So: the chat down one side, the object, and one bar over it.
        """
        self.assertEqual(0, self.js(
            "document.querySelectorAll('#variant-list, #ws-library, #ws-more, #ws-reset-variants').length"))
        self.assertEqual(0, self.js("document.querySelectorAll('#ws-extras').length"))
        # The chat has the whole side, and it is the only thing on it.
        self.assertEqual(["ws-chat-home"],
                         self.js("[...document.querySelector('.ws-left').children].map(e=>e.id)"))
        self.assertEqual(["Chat"],
                         self.js("[...document.querySelectorAll('.ws-left h2')].map(h=>h.textContent)"))
        self.assertTrue(self.js("document.querySelector('#ws-chat-log').getBoundingClientRect().height>200"),
                        "the conversation gets the height, not a 340 px box")
        # No right nav, and no page header above the bar.
        self.assertTrue(self.js("document.querySelector('.ws-right').hidden"))
        self.assertTrue(self.js("document.querySelector('.ws-top').hidden"))
        # One bar: which product, how it is drawn, where you are looking from,
        # and the two acts that leave the bench.
        bar = self.js("[...document.querySelector('.ws-viewbar').children]"
                      ".map(e=>e.id||e.tagName.toLowerCase())")
        self.assertEqual(["ws-archetype", "button", "button", "ws-points-of-view", "span",
                          "ws-make-status", "ws-check", "ws-make", "a"], bar)
        # Wire and Skin are on the bar; the four that describe how it COMPILES
        # went to the plumbing drawer when the bench was first unburied.
        self.assertEqual(["Wire", "Skin"],
                         self.js("[...document.querySelectorAll('.ws-viewbar:not(.ws-viewbar-extra)"
                                 " > button[data-view]')].map(b=>b.textContent)"))
        self.assertEqual(["3/4", "Front", "Side", "Top"],
                         self.js("[...document.querySelectorAll('#ws-points-of-view button')]"
                                 ".map(b=>b.dataset.pointOfView)"))
        # Which product is a dropdown on that bar, not seven chips above it.
        self.assertEqual("SELECT", self.js("document.querySelector('#ws-archetype').tagName"))
        self.assertGreater(self.js("document.querySelector('#ws-archetype').getBoundingClientRect().width"), 0)
        # And the panel that told a person looking at a table that it was a
        # table is not on the page.
        self.assertTrue(self.js("Boolean(document.querySelector('#ws-view-context')"
                                "?.closest('#ws-hidden-controls'))"))

    def test_each_point_of_view_moves_the_camera(self):
        """They did nothing at all, and were called X, Y and Z.

        The wiring for Wire and Skin runs over every button in the bar at load
        time, and the points of view had already been put there -- so clicking
        "Top" ran the representation handler with no representation, set the
        drawing to undefined and moved no camera. The owner: "what does x y z
        do, I don't see it changing anything."
        """
        where = lambda: self.js("document.querySelector('#workshop-stage').pagePointOf([0.55,0.75,0.3])")
        seen = {}
        for name in ("3/4", "Front", "Side", "Top"):
            self.click(f'[data-point-of-view="{name}"]')
            self.wait(f"document.querySelector('[data-point-of-view=\"{name}\"]')"
                      f".getAttribute('aria-current')==='true'")
            seen[name] = [round(v) for v in where()]
        # Four places to stand, four different pictures.
        self.assertEqual(4, len({tuple(v) for v in seen.values()}), seen)
        # Looking down, a point 0.3 m in front of the middle is ABOVE one
        # 0.3 m behind it on the screen; looking from the front it is not.
        self.assertLess(seen["Top"][1], seen["Front"][1], seen)
        # And the drawing is untouched: a point of view is not a representation.
        self.assertEqual("skin", self.js("document.querySelector('.ws-viewbar [aria-pressed=true]').dataset.view"))

    def test_a_bubble_is_the_size_of_what_it_says(self):
        """A grid row takes an equal share of the box by default, so two short
        messages in a tall log were two tall bubbles of mostly nothing."""
        self.js("[...document.querySelectorAll('.ws-suggestion')][1].click()")
        self.wait("document.querySelectorAll('#ws-chat-log .ws-chat-message').length>1")
        sizes = self.js("""[...document.querySelectorAll('#ws-chat-log .ws-chat-message')].map(m=>{
          const box=m.getBoundingClientRect(), inner=m.querySelector('.ws-chat-body').getBoundingClientRect(),
                who=m.querySelector('.ws-chat-who').getBoundingClientRect();
          return Math.round(box.height - (inner.height + who.height));})""")
        # Whatever is left over is padding and the gap between the two lines,
        # not a bubble stretched to fill a row.
        for spare in sizes:
            self.assertLess(spare, 30, sizes)

    def test_the_chat_says_what_it_is_doing_while_it_does_it(self):
        """A turn is one POST that answers at the end. Waiting at a bubble that
        says "Working" and nothing else is waiting at a blank screen."""
        self.js("""window.__progress=[];
          const was=window.fetch.bind(window);
          window.fetch=async(r,i)=>{ if(String(r).endsWith('/api/workshop/progress'))
            window.__progress.push(JSON.parse(i.body).turn);
            if(String(r).endsWith('/api/workshop/candidates')){
              const body=JSON.parse(i.body); if(body.component_chat?.turn)window.__sentTurn=body.component_chat.turn; }
            return was(r,i); };""")
        # The page hands an id in with the turn and reads back what it has done.
        self.js("document.querySelector('#ws-component-chat-text').value='make the legs thicker';"
                "document.querySelector('#ws-component-chat').requestSubmit()")
        self.wait("window.__progress.length>0", timeout=20)
        self.assertTrue(self.js("window.__progress[0].length>10"), "a real turn id")
        # The id it polls with is the one it sent with the turn, or it is
        # reading somebody else's work.
        self.assertEqual(self.js("window.__sentTurn"), self.js("window.__progress[0]"))
        # What the steps SAY is checked in workshop_chat_tests, where the turn
        # can be driven without a model.

    def test_the_chat_offers_things_to_ask_for(self):
        """A blank box is the hardest question on the page.

        The owner: "perhaps we have some suggested chat messages below like
        'Ask me to drop a bowling ball on the item' and it will do that and
        show you."
        """
        said = self.js("[...document.querySelectorAll('.ws-suggestion')].map(b=>b.textContent)")
        self.assertGreaterEqual(len(said), 4)
        # And they point at finding a RANGE, because that is what testing is
        # for: one run only says whether the number you guessed was over or
        # under.
        self.assertTrue(any("breaks it" in line for line in said), said)
        self.assertTrue(any("light to heavy" in line for line in said), said)
        self.assertTrue(any("midnight" in line for line in said), said)
        # Each one is a real turn: clicking it puts that message in the box and
        # sends it, rather than printing a canned answer.
        self.js("[...document.querySelectorAll('.ws-suggestion')][1].click()")
        self.wait("document.querySelectorAll('#ws-chat-log .ws-chat-message.user').length>0")
        self.assertEqual(said[1],
                         self.js("document.querySelector('#ws-chat-log .ws-chat-message.user .ws-chat-body').textContent"))

    def test_each_step_holds_what_that_step_is_for(self):
        """Saving used to sit under the test bench, because an unnamed field
        follows the last heading and the heading before it was the bench's."""
        where = lambda sel: self.js(
            f"document.querySelector({json.dumps(sel)}).closest('.ws-step-pane')?.dataset.mode")
        self.assertEqual("start", where("#ws-product-catalog"))
        self.assertEqual("start", where("#ws-user-library"))
        self.assertEqual("start", where("#ws-saved-designs"))
        self.assertEqual("build", where("#ws-component-editor"))
        self.assertEqual("build", where("#ws-history"))
        self.assertEqual("test", where("#ws-test-catalog"))
        self.assertEqual("details", where("#ws-bom-box"))
        self.assertEqual("details", where("#ws-install-box"))
        self.assertEqual("details", where("#ws-save-name"))
        self.assertEqual("details", where("#ws-save-design"))

    def test_picking_a_part_takes_you_to_the_step_that_changes_it(self):
        self.click('[data-mode="test"]')
        self.assertEqual("test", self.js("document.querySelector('.ws-step-tab[aria-selected=true]').dataset.mode"))
        self.js("[...document.querySelectorAll('#ws-parts button')].find(b=>b.textContent==='leg-1').click()")
        self.wait("document.querySelector('.ws-step-tab[aria-selected=true]').dataset.mode==='build'")
        self.assertFalse(self.js("document.querySelector('#ws-step-build').hidden"))
        self.assertIn("leg-1", self.js("document.querySelector('#ws-selected-part').textContent"))

    def test_an_edit_can_be_taken_back_and_what_you_did_is_listed(self):
        """There was no undo. None.

        A wrong material applied to all eight parts stayed wrong: took() threw
        the previous design away on every edit and nothing kept a copy.
        """
        self.click('[data-mode="build"]')
        self.assertTrue(self.js("document.querySelector('#ws-undo').disabled"), "nothing to take back yet")
        was = self.js("document.querySelector('#ws-mass').textContent")
        self.js("[...document.querySelectorAll('#ws-parts button')].find(b=>b.textContent==='top').click()")
        self.field('#ws-edit-scope','all')
        self.field('#ws-part-material','glass')
        self.wait("document.querySelector('#ws-mass').textContent!=='" + was + "'")
        changed = self.js("document.querySelector('#ws-mass').textContent")
        # What you did is written down, in the words of what actually changed.
        self.wait("document.querySelector('#ws-history .ws-history-step')")
        self.assertIn("material set to glass",
                      self.js("document.querySelector('#ws-history').textContent"))
        self.assertIn("parts:", self.js("document.querySelector('#ws-history').textContent"),
                      "one material on every part is one thing done, not eight")
        self.assertFalse(self.js("document.querySelector('#ws-undo').disabled"))
        self.click('#ws-undo')
        self.wait("document.querySelector('#ws-mass').textContent==='" + was + "'")
        self.assertFalse(self.js("document.querySelector('#ws-redo').disabled"))
        self.click('#ws-redo')
        self.wait("document.querySelector('#ws-mass').textContent==='" + changed + "'")

    def test_a_saved_design_can_be_renamed_and_thrown_away(self):
        """Fourteen routes and not one of them removed anything."""
        self.click('[data-mode="details"]')
        self.field('#ws-save-name','Browser keep-or-bin table')
        self.click('#ws-save-design')
        # Its own row, by name: the store is shared with every other test here.
        mine = ("[...document.querySelectorAll('#ws-saved-designs .ws-keep-row')]"
                ".find(r=>r.textContent.includes(%s))")
        self.wait(f"{mine % repr('Browser keep-or-bin table')}")
        self.js("window.prompt=()=>'A better name'")
        self.js(f"{mine % repr('Browser keep-or-bin table')}.querySelector('.ws-keep-actions button').click()")
        self.wait(f"{mine % repr('A better name')}")
        # Renaming is not saving it again: the count of times it was saved holds.
        self.assertIn('saved 1 time', self.js(f"{mine % repr('A better name')}.textContent"))
        self.js("window.confirm=()=>true")
        self.js(f"{mine % repr('A better name')}.querySelector('.ws-keep-bin').click()")
        self.wait(f"!{mine % repr('A better name')}")
        # Everything you can OPEN is one step: the products to start from, your
        # own parts, and what you saved.
        for heading in ("Product library", "My library", "Saved designs"):
            self.assertIn(heading, self.js(
                "[...document.querySelectorAll('#ws-step-start h2, #ws-step-start h3')]"
                ".map(h=>h.textContent)"))
        # Only the two that describe the bench rather than the work are drawers.
        self.assertEqual(["ws-group-measure", "ws-group-plumbing"],
                         self.js("[...document.querySelectorAll('.ws-right > details.ws-group')]"
                                 ".map(d=>d.id)"))

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

    def test_limits_are_opt_in_and_settings_invalidate_the_verdict(self):
        self.click('[data-mode="test"]')
        self.click('#ws-test-catalog button[data-value="try_in_a_room"]')
        self.assertFalse(self.js("document.querySelector('[data-bench-control=\"evaluate_limits\"]').checked"))
        self.field('[data-bench-control="seconds"]', .5)
        self.click("#ws-run-bench")
        self.wait("!document.querySelector('#ws-run-bench').disabled && document.querySelector('#ws-acceptance-status')")
        self.assertEqual("not-declared", self.js("document.querySelector('#ws-acceptance-status').dataset.status"))
        self.js("document.querySelector('[data-bench-control=\"evaluate_limits\"]').checked=true")
        self.field('[data-bench-control="max_moved_m"]', 1)
        self.assertIsNone(self.js("document.querySelector('#ws-acceptance-status')"))
        self.click("#ws-run-bench")
        self.wait("!document.querySelector('#ws-run-bench').disabled && document.querySelector('#ws-acceptance-status')")
        self.assertEqual("passed", self.js("document.querySelector('#ws-acceptance-status').dataset.status"))
        self.field('[data-bench-control="max_moved_m"]', 0)
        self.assertIsNone(self.js("document.querySelector('#ws-acceptance-status')"))
        self.click("#ws-run-bench")
        self.wait("!document.querySelector('#ws-run-bench').disabled && document.querySelector('#ws-acceptance-status')")
        self.assertEqual("failed", self.js("document.querySelector('#ws-acceptance-status').dataset.status"))
        self.assertIn("moved_m", self.js("document.querySelector('#ws-bench-result').textContent"))

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
        self.wait("typeof window.__releaseHistory==='function' && document.querySelector('#ws-test-catalog button[data-value=try_in_a_room]')")
        self.click('[data-mode="test"]')
        self.click('#ws-test-catalog button[data-value="try_in_a_room"]')
        self.field('[data-bench-control="seconds"]', .5)
        self.field('[data-bench-control="max_moved_m"]', .123)
        self.click("#ws-run-bench")
        self.wait("typeof window.__releaseResult==='function'")
        self.js("window.__releaseHistory()")
        # A marker after a microtask/timer proves the history callback completed.
        self.js("new Promise(resolve=>setTimeout(resolve,200))")
        self.assertEqual("0.123", self.js("document.querySelector('[data-bench-control=max_moved_m]').value"))
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
        self.click('#ws-test-catalog button[data-value="try_in_a_room"]')
        self.field('[data-bench-control="seconds"]', .5)
        self.js("""window.__originalFetch=window.fetch;window.fetch=async function(resource,init){
          const response=await window.__originalFetch(resource,init);
          if(String(resource).endsWith('/api/workshop/plan') && JSON.parse(init.body).bench_test){
            await new Promise(resolve=>{window.__releaseTest=resolve});
          }return response;
        };""")
        self.click("#ws-run-bench")
        self.wait("typeof window.__releaseTest==='function'")
        self.field('[data-bench-control="max_moved_m"]', 0)
        self.js("window.__releaseTest();window.fetch=window.__originalFetch")
        self.wait("!document.querySelector('#ws-run-bench').disabled")
        self.assertEqual("", self.js("document.querySelector('#ws-bench-result').textContent"))

    def stock_the_rack(self, mass_kg=500.0):
        """Put material on the rack before anything is made.

        Installing spends stock, and the default rack cannot cover a table --
        so without this the preview reports a shortfall and refuses, which is
        the rack doing its job rather than installation being broken. The gate
        itself is covered by tests/workshop_rack_tests.py.
        """
        self.js(f"""(async()=>{{
          const status=await fetch('/api/status').then(r=>r.json());
          for (const material of ['oak','iron','glass','concrete','aluminum','rubber']) {{
            await fetch('/api/workshop/library',{{method:'POST',
              headers:{{'Content-Type':'application/json','X-Banjo-Token':status.csrf_token}},
              body:JSON.stringify({{action:'set_rack',material,mass_kg:{mass_kg}}})}});
          }}
          return 1;}})()""")

    def install_api(self, path, body):
        return self.js(f"""(async()=>{{
          const status=await fetch('/api/status').then(r=>r.json());
          const response=await fetch({json.dumps(path)},{{method:'POST',headers:{{'Content-Type':'application/json','X-Banjo-Token':status.csrf_token}},body:JSON.stringify({json.dumps(body)})}});
          return {{status:response.status,body:await response.json()}};
        }})()""")

    def test_installation_preview_confirm_retry_and_return_to_live_world(self):
        self.stock_the_rack()
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
        # Drawn as one geometry of its parts, each box its 36 vertices in the
        # order given: the first part's own height is how thick the top is drawn.
        observed=self.js("(()=>{const b=window.banjoRoom.world.bodies.get("+json.dumps(root)+");const p=b.mesh.geometry.attributes.position;let lo=Infinity,hi=-Infinity;for(let i=0;i<36;i++){lo=Math.min(lo,p.getY(i));hi=Math.max(hi,p.getY(i));}return {count:b.mesh.userData.collisionParts,scaleY:hi-lo,cells:b.fromCells,x:b.mesh.position.x,mass:b.mass,model:b.mechanicalModel};})()")
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
        self.assertEqual(5,self.js('window.banjoRoom.world.bodies.get('+json.dumps(root)+').mesh.userData.collisionParts'))

    def test_installation_stale_world_is_visible_and_does_not_install(self):
        self.stock_the_rack()
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
        # A design of exact bodies gets the same test as a design of cells: the
        # little world installs whatever the compiler drew.
        self.assertEqual('try_in_a_room',self.js("document.querySelector('#ws-bench-test').value"))
        self.field('[data-bench-control="seconds"]',1)
        self.click('#ws-run-bench')
        self.wait("document.querySelector('#ws-bench-result pre')?.textContent.includes('recorded-native-shapes')",timeout=120)
        proof=json.loads(self.js("document.querySelector('#ws-bench-result pre').textContent"))
        self.assertEqual('measured',proof['status'])
        self.assertEqual(0,proof['measured']['cells'],'finalized: nothing of it is cells')
        self.assertEqual('recorded-native-shapes',proof['playback']['geometry_basis'])
        self.assertGreater(proof['playback']['states'],2)
        # The evidence panel deliberately summarizes (rather than duplicates)
        # the full native trace. Exercise the actual rendered states too.
        if self.js("document.querySelector('#ws-play').textContent") == 'Pause':
            self.click('#ws-play')
        self.field('#ws-play-timeline',0,'input')
        before=self.js("document.querySelector('#workshop-stage').dataset.physicsPose")
        self.field('#ws-play-timeline',self.js("document.querySelector('#ws-play-timeline').max"),'input')
        self.assertNotEqual(before,self.js("document.querySelector('#workshop-stage').dataset.physicsPose"))
        # The table is one exact body of five parts.
        self.assertEqual('1',self.js("document.querySelector('#workshop-stage').dataset.physicsBodyCount"))
        self.capture_evidence('thin-rigid-native-motion.png')
        self.assertIn('its exact parts where it is exact',self.js("document.querySelector('#ws-play-note').textContent"))
        self.click('[data-mode="details"]');self.field('#ws-save-name','Browser precise rigid table');self.click('#ws-save-design')
        self.wait("document.querySelector('#ws-save-status').textContent.includes('Saved designs and My Library')")
        self.js('window.__thinPageBeforeReload=true')
        self.page.send('Page.reload',{})
        self.wait("!window.__thinPageBeforeReload && document.querySelector('#ws-mechanical-model')?.value==='rigid' && document.querySelector('#ws-mass')?.textContent==='3.416 kg'")
        self.wait("document.querySelector('#ws-buildability-summary')?.textContent.includes('anchored-scenery installation available')")


    def test_the_test_tab_offers_one_test_for_everything_it_can_make(self):
        """There were four rigs and none of them had ground under it.

        They are one test now, in a room with ground and a sky. It is offered
        wherever the thing can actually be MADE -- a table, a bench, and
        anything drawn part by part through the chat. A cart, a kettle, a
        chair, a stool and a shelf-unit cannot be installed at all today, and
        that is a gap in the compiler, not a reason to offer a test that would
        fail when someone pressed run.
        """
        self.click('[data-mode="test"]')
        values=self.js("[...document.querySelectorAll('#ws-test-catalog button')].map(b=>b.dataset.value)")
        self.assertEqual(["try_in_a_room"],values)
        self.assertEqual("try_in_a_room",self.js("document.querySelector('#ws-bench-test').value"))
        self.assertIsNone(self.js("document.querySelector('[data-bench-control=record_trace]')"))
        # A shelf-unit still cannot be MADE -- its template comes out with
        # disconnected components and never compiles -- so it is offered
        # nothing, rather than a test that would fail when it was run.
        self.open_product("shelf-unit")
        self.assertTrue(self.js("document.querySelector('#ws-run-bench').disabled"))
        self.assertEqual(0,self.js("document.querySelectorAll('#ws-test-catalog button').length"))
        self.assertIn("No working simulation",self.js("document.querySelector('#ws-bench-controls').textContent"))

    def test_a_glass_table_hit_hard_enough_is_seen_to_break_into_pieces(self):
        """And dropped onto soil from four metres, it is not.

        The rig this replaced dropped things onto a hard floor, where 4 m was
        just past the 8.70 m/s at which this glass first breaks. The little
        world's ground is 400 mm of soil, and glass that lands on soil at
        8.9 m/s does not break. That is the ground it will stand on out there.
        """
        self.click('[data-mode="build"]')
        self.js("[...document.querySelectorAll('#ws-parts button')].find(b=>b.textContent==='top').click()")
        self.field('#ws-edit-scope','all')
        self.field('#ws-part-material','glass')
        self.wait("document.querySelector('#ws-mass')?.textContent==='98.580 kg'")
        self.click('[data-mode="test"]')
        self.field('[data-bench-control=drop_m]',4,'input')
        self.field('[data-bench-control=seconds]',2)
        self.click('#ws-run-bench')
        self.wait("document.querySelector('#ws-room-outcome')",timeout=120)
        self.assertEqual('stood',self.js("document.querySelector('#ws-room-outcome').dataset.outcome"))
        self.assertRegex(self.js("document.querySelector('#ws-room-says').textContent"),
                         r'dropped from 4\.00 m')
        # Hit by 40 kg of iron at 12 m/s, it is in pieces.
        self.field('[data-bench-control=drop_m]',0,'input')
        self.field('[data-bench-control=strike_kg]',40,'input')
        self.field('[data-bench-control=strike_speed_m_s]',12,'input')
        self.click('#ws-run-bench')
        self.wait("document.querySelector('#ws-room-outcome')?.dataset.outcome==='broke'",timeout=120)
        self.assertIn('of it broke',self.js("document.querySelector('#ws-room-outcome').textContent"))
        said=self.js("document.querySelector('#ws-room-says').textContent")
        self.assertRegex(said,r'hit by 40 kg at 12 m/s')
        self.assertRegex(said,r'\d+ of it broke, into \d+ pieces, the first at \d+\.\d\d s')
        if self.js("document.querySelector('#ws-play').textContent") == 'Pause':
            self.click('#ws-play')
        # Whole at the start -- the table and the block thrown at it -- and at
        # the end every piece is a drawn body of its own cells.
        self.field('#ws-play-timeline',0,'input')
        self.assertEqual('2',self.js("document.querySelector('#workshop-stage').dataset.physicsBodyCount"))
        self.assertIn('2 simulated bodies',self.js("document.querySelector('#ws-simulation-readout').textContent"))
        self.field('#ws-play-timeline',self.js("document.querySelector('#ws-play-timeline').max"),'input')
        ended=int(self.js("document.querySelector('#workshop-stage').dataset.physicsBodyCount"))
        self.assertGreater(ended,4)
        self.assertIn(f'In {ended} pieces',self.js("document.querySelector('#ws-simulation-readout').textContent"))
        note=self.js("document.querySelector('#ws-play-note').textContent")
        self.assertIn('every piece as the cells the engine left it',note)
        self.assertNotIn('simplified collision shapes',note)
        self.capture_evidence('glass-table-broken.png')
        # The same table in oak, hit the same way, is still a table.
        self.click('[data-mode="build"]')
        self.field('#ws-part-material','oak')
        self.wait("document.querySelector('#ws-mass')?.textContent==='27.602 kg'")
        self.click('[data-mode="test"]')
        self.field('[data-bench-control=strike_kg]',40,'input')
        self.field('[data-bench-control=strike_speed_m_s]',3,'input')
        self.field('[data-bench-control=seconds]',2)
        self.click('#ws-run-bench')
        self.wait("document.querySelector('#ws-room-outcome')",timeout=120)
        self.assertEqual('0',self.js("document.querySelector('#ws-room-outcome').dataset.broke"))

    def test_a_load_says_whether_it_held_and_by_how_much(self):
        self.click('[data-mode="build"]')
        self.js("[...document.querySelectorAll('#ws-parts button')].find(b=>b.textContent==='top').click()")
        self.field('#ws-edit-scope','all')
        self.field('#ws-part-material','concrete')
        self.wait("document.querySelector('#ws-part-material').value==='concrete' && !document.querySelector('#ws-mass').textContent.startsWith('27.602')")
        self.click('[data-mode="test"]')
        self.click('#ws-test-catalog button[data-value="try_in_a_room"]')
        self.wait("document.querySelector('[data-bench-control=load_kg]')")
        self.field('[data-bench-control=load_kg]',400)
        self.field('[data-bench-control=seconds]',1.5)
        self.js("document.querySelector('[data-bench-control=evaluate_limits]').checked=true")
        self.field('[data-bench-control=max_moved_m]',.05)
        self.click('#ws-run-bench')
        self.wait("document.querySelector('#ws-room-outcome')",timeout=120)
        self.assertEqual('stood',self.js("document.querySelector('#ws-room-outcome').dataset.outcome"))
        self.assertEqual('0',self.js("document.querySelector('#ws-room-outcome').dataset.broke"))
        said=self.js("document.querySelector('#ws-room-says').textContent")
        self.assertIn('400 kg set on its top',said)
        self.assertIn('nothing broke',said)
        # 400 kg of iron is a 368 mm cube, and it is really there: the weight is
        # a body in the room, and at the end of the run it is on the table.
        proof=json.loads(self.js("document.querySelector('#ws-bench-result pre').textContent"))
        self.assertEqual('passed',self.js("document.querySelector('#ws-acceptance-status').dataset.status"))
        self.assertLess(float(proof['measured']['moved_m']),.05)
        self.capture_evidence('concrete-table-held-with-margin.png')

    def test_a_blow_from_a_weight_is_a_test_the_page_offers_and_runs(self):
        self.click('[data-mode="test"]')
        self.click('#ws-test-catalog button[data-value="try_in_a_room"]')
        self.wait("document.querySelector('[data-bench-control=strike_kg]')")
        self.field('[data-bench-control=strike_kg]',20,'input')
        self.field('[data-bench-control=strike_speed_m_s]',15,'input')
        self.field('[data-bench-control=seconds]',1.5)
        self.click('#ws-run-bench')
        self.wait("document.querySelector('#ws-room-outcome')?.dataset.outcome==='broke'",timeout=120)
        self.assertIn('hit by 20 kg at 15 m/s',self.js("document.querySelector('#ws-room-says').textContent"))
        self.assertRegex(self.js("document.querySelector('#ws-bench-result').textContent"),
                         r'broke into \d+ at \d+\.\d\d s')
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

    def test_the_way_in_is_reachable_on_a_small_screen_without_scrolling(self):
        """There is no Run button any more; you ask for a run.

        This test used to point a real mouse at "Run simulation" to prove it
        was not below the fold. The owner: "I don't know why we have the run
        simulation or reset to setup buttons ... we should just leave it all up
        to the chat." So what has to be reachable is the chat: the box you type
        in, the Send beside it, and the first thing to ask for.
        """
        self.page.send("Emulation.setDeviceMetricsOverride",{"width":1280,"height":720,"deviceScaleFactor":1,"mobile":False})
        for selector in ("#ws-component-chat-text", "#ws-component-chat button[type=submit]",
                         ".ws-suggestion"):
            point=self.js(f"""(()=>{{const e=document.querySelector({json.dumps(selector)}),r=e.getBoundingClientRect();
              return {{x:r.x+r.width/2,y:r.y+r.height/2,visible:r.top>=0&&r.bottom<=innerHeight&&r.width>0,
              hit:e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}};}})()""")
            self.assertTrue(point['visible'] and point['hit'],f"{selector}: {point}")
        # Real mouse input: a programmatic element.click() can pass for an
        # offscreen button and failed to catch the previous below-fold layout.
        point=self.js("""(()=>{const e=document.querySelector('.ws-suggestion'),r=e.getBoundingClientRect();
          return {x:r.x+r.width/2,y:r.y+r.height/2};})()""")
        for kind in ('mousePressed','mouseReleased'):
            self.page.send('Input.dispatchMouseEvent',{'type':kind,'x':point['x'],'y':point['y'],'button':'left','clickCount':1})
        # Without a key the chat answers deterministically, but the turn is a
        # real one either way: the message goes into the log.
        self.wait("document.querySelectorAll('#ws-chat-log .ws-chat-message.user').length>0")
        self.assertIn("Find the weight that breaks it",
                      self.js("document.querySelector('#ws-chat-log .ws-chat-message.user').textContent"))
        # And the run controls are not on the bench at all: "Run simulation"
        # and "Reset to setup" went with the Test tab nobody could read.
        self.assertTrue(self.js("Boolean(document.querySelector('#ws-run-bench')"
                                "?.closest('#ws-hidden-controls'))"))
        self.assertTrue(self.js("document.querySelector('.ws-right').hidden"))
        self.assertTrue(self.js("document.querySelector('.ws-top').hidden"))

    def test_heating_has_visible_changing_temperature_and_accelerated_display(self):
        self.open_product('kettle');self.click('[data-mode="test"]')
        # A kettle is a container and the installer will not take one into a
        # room, so the little world is not offered for it: its own run is.
        self.assertEqual(['kettle_heat'],
                         self.js("[...document.querySelectorAll('#ws-test-catalog button')].map(b=>b.dataset.value)"))
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
        # At 3 kN the handle assembly comes away from the rolling chassis, on the
        # two joints holding the arms to the deck. It comes away whole because no
        # joint law is in force (mcp/joint_efficiency.py, the owner's call): every
        # joint is the solid material, so nothing inside the assembly is weaker
        # than the arms. Were the end-grain quarter and the press fit put in force,
        # the handle and each arm would part on their own and this would read 4.
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
