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
        self.wait("document.querySelector('#ws-product-catalog button') && document.querySelector('#ws-name').textContent.trim()")

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
        raise AssertionError(f"Workshop condition timed out: {condition}; {diagnostics}")

    def click(self, selector):
        self.js(f"document.querySelector({json.dumps(selector)}).click()")

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
        out = ROOT / "build/workshop-browser-evidence"
        out.mkdir(parents=True, exist_ok=True)
        image = self.page.send("Page.captureScreenshot", {"format": "png"})
        (out / f"{self._testMethodName}.png").write_bytes(base64.b64decode(image["data"]))
        errors = [e for e in self.page.events if e.get("method") == "Runtime.exceptionThrown"]
        self.assertEqual([], errors, errors)

    def test_rebuild_error_is_visible_and_does_not_keep_stale_matter(self):
        self.click("#ws-refresh-matter")
        self.wait("document.querySelector('#ws-matter-status').dataset.state==='current'")
        self.field("#ws-matter-cell", .005)
        self.click("#ws-refresh-matter")
        self.wait("document.querySelector('#ws-matter-status').dataset.state==='error'")
        self.assertTrue(self.js("!document.querySelector('#ws-notice').hidden && document.querySelector('#ws-notice').getBoundingClientRect().height>0"))
        self.assertIn("No current Matter", self.js("document.querySelector('#ws-matter-status').textContent"))
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
        self.js("document.querySelector('#ws-saved-designs').closest('details').open=true")
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


    def test_test_tab_only_shows_working_simulations_and_disables_unsupported_products(self):
        self.click('[data-mode="test"]')
        values=self.js("[...document.querySelectorAll('#ws-test-catalog button')].map(b=>b.dataset.value)")
        self.assertEqual(["drop_product","slide_product","declared_static_load"],values)
        self.assertEqual("drop_product",self.js("document.querySelector('#ws-bench-test').value"))
        self.assertIsNone(self.js("document.querySelector('[data-bench-control=record_trace]')"))
        self.open_product("shelf-unit")
        self.assertTrue(self.js("document.querySelector('#ws-run-bench').disabled"))
        self.assertEqual(0,self.js("document.querySelectorAll('#ws-test-catalog button').length"))
        self.assertIn("No working simulation",self.js("document.querySelector('#ws-bench-controls').textContent"))

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
