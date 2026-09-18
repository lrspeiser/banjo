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
        self.page.send("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/world?workshop=1"})
        self.wait("document.querySelector('#ws-product-catalog button') && document.querySelector('#ws-name').textContent.trim()")

    def js(self, expression):
        return self.page.evaluate(expression, await_promise=True)

    def wait(self, condition, timeout=25):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.js(condition):
                return
            time.sleep(.1)
        raise AssertionError(f"Workshop condition timed out: {condition}")

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
        self.assertIn("Simulation trace", self.js("document.querySelector('#ws-playback').textContent"))
        self.click("#ws-play-reset")
        self.assertEqual("0.00 s", self.js("document.querySelector('#ws-play-time').textContent"))


if __name__ == "__main__":
    unittest.main()
