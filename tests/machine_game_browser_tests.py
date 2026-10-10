"""The puzzle page (/play) in Chrome, used the way a person uses it.

A piece added from the tray is a see-through ghost: it follows the pointer, a
click pins it, it is changed and turned while it is a ghost, then set down
and run. A ghost stood inside a wall is red and says why. On a phone held
upright the scene comes into view when a piece is added, and the bar over
the scene turns the ghost and sets it down.

    BANJO_LIVE_ENGINE=path/to/banjo_live_world_run python tests/machine_game_browser_tests.py

Needs Chrome (BANJO_CHROME, tests/qa_browser.py) and the engine. Without them
it skips, unless BANJO_BROWSER_TESTS=required.
"""
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import qa_browser  # noqa: E402

ENGINE = Path(os.environ['BANJO_LIVE_ENGINE']) if os.environ.get('BANJO_LIVE_ENGINE') else None
SETTLED = "(() => { const g = window.machineGhostState(); return Boolean(g && g.answered && !g.busy); })()"
READY = "/ready: press Start/.test(document.getElementById('clock').textContent)"


class Puzzles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [what for what, ok in (('the engine (BANJO_LIVE_ENGINE)', ENGINE and ENGINE.is_file()),
                                         ('Chrome (BANJO_CHROME)', qa_browser.CHROME.is_file())) if not ok]
        if missing:
            if os.environ.get('BANJO_BROWSER_TESTS') == 'required':
                raise RuntimeError('required, and missing: ' + ', '.join(missing))
            raise unittest.SkipTest('missing ' + ', '.join(missing))
        spec = importlib.util.spec_from_file_location('machine_game_page', ROOT / 'scripts/voxel-lab.py')
        lab = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lab)
        cls.logs = tempfile.TemporaryDirectory()
        # The game site as deployed: open to anyone, nothing else served.
        cls.server = lab.Server(('127.0.0.1', 0), ENGINE, Path(cls.logs.name), site='game', public=True)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.server.server_address[1]}'
        cls.chrome = qa_browser.Chrome(1280, 860)
        cls.page = cls.chrome.page

    @classmethod
    def tearDownClass(cls):
        cls.chrome.close()
        cls.server.shutdown()
        cls.server.machines.close_all()
        cls.server.server_close()
        cls.logs.cleanup()

    # ---- what a person does -------------------------------------------------------
    def js(self, expression):
        return self.page.evaluate(expression)

    def wait(self, expression, seconds=60.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.js(expression):
                return
            time.sleep(0.1)
        said = self.js("document.getElementById('verdict').textContent")
        self.fail(f'waited {seconds:.0f} s for {expression}; the page says {said!r}')

    def open(self, level, width=1280, height=860, phone=False):
        self.page.send('Emulation.setDeviceMetricsOverride',
                       {'width': width, 'height': height, 'deviceScaleFactor': 2 if phone else 1, 'mobile': phone})
        self.page.send('Emulation.setTouchEmulationEnabled', {'enabled': phone, 'maxTouchPoints': 5})
        self.page.send('Page.navigate', {'url': f'{self.base}/play?level={level}'})
        self.wait(f"document.getElementById('clock') && {READY}", 90)

    def ghost(self):
        self.wait(SETTLED, 20)
        return self.js('window.machineGhostState()')

    def press(self, name):
        """A button, by what it says or by its label."""
        found = self.js(f"""(() => {{ const b = [...document.querySelectorAll('button')].find(b =>
            !b.disabled && b.offsetParent !== null && ((b.getAttribute('aria-label') || b.textContent).trim() === {json.dumps(name)}));
            if (b) b.click(); return Boolean(b); }})()""")
        self.assertTrue(found, f'no button {name!r} to press')

    def slide(self, label, value):
        self.assertTrue(self.js(f"""(() => {{ const el = document.querySelector('[aria-label={json.dumps(label)}]');
            if (!el) return false; el.value = {json.dumps(value)};
            el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', {{bubbles: true}})); return true; }})()"""),
            f'no control {label!r}')

    def screen_point(self, point):
        return self.js(f'window.machineScreenPoint({json.dumps(point)})')

    def mouse(self, kind, x, y):
        extra = {'button': 'left', 'clickCount': 1} if kind != 'mouseMoved' else {}
        self.page.send('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y, **extra})

    def key(self, key):
        self.js('document.activeElement && document.activeElement.blur()')
        code = ord(key.upper())
        for kind in ('keyDown', 'keyUp'):
            self.page.send('Input.dispatchKeyEvent', {'type': kind, 'key': key, 'code': 'Key' + key.upper(),
                                                      'windowsVirtualKeyCode': code,
                                                      **({'text': key} if kind == 'keyDown' else {})})

    # ---- the tests ---------------------------------------------------------------------
    def test_a_ghost_follows_the_pointer_is_pinned_changed_turned_set_down_and_run(self):
        self.open('gap')
        self.js("window.machineView({azimuth: -0.35, elevation: 0.75, distance: 3.2, at: [0.3, 0.2, 0]})")
        time.sleep(1.5)                       # the camera eases to its new view
        self.press('Add')
        g = self.ghost()
        self.assertTrue(g['follow'] and g['parts'] > 0, g)
        # Not in the machine yet: the engine's world has no plank.
        self.assertNotIn('your plank 1', self.js("[...document.querySelectorAll('#stations li')].map(l => l.textContent).join()"))
        for x in (-0.2, 0.3):
            self.mouse('mouseMoved', *self.screen_point([x, 0.0, 0.0]))
            g = self.ghost()
        self.assertAlmostEqual(g['p']['x_m'], 0.3, delta=0.02, msg='the ghost follows the pointer')
        x, y = self.screen_point([0.3, 0.0, 0.0])
        self.mouse('mousePressed', x, y)
        self.mouse('mouseReleased', x, y)
        g = self.ghost()
        self.assertFalse(g['follow'], 'a click pins it')
        self.mouse('mouseMoved', *self.screen_point([0.8, 0.0, 0.0]))
        self.assertAlmostEqual(self.ghost()['p']['x_m'], g['p']['x_m'], delta=1e-9, msg='pinned, it stays')
        # Changed and turned as a ghost.
        self.slide('Cut to length of your plank 1', 0.7)
        self.key('q')
        self.key('q')
        self.press('tip on 15 degrees')
        g = self.ghost()
        self.assertEqual((g['p']['length_m'], g['p']['yaw_deg'], g['p']['pitch_deg']), (0.7, 30, 15))
        self.assertTrue(g['fits'], g['problems'])
        self.press('Square it up')
        g = self.ghost()
        self.assertEqual((g['p']['yaw_deg'], g['p']['pitch_deg']), (0, 0))
        self.press('Run it')
        self.assertIn('Set your plank down first', self.js("document.getElementById('verdict').textContent"))
        self.press('Set it down')
        self.wait('!window.machineGhostState()', 5)
        self.wait(READY, 90)
        self.press('Run it')
        self.wait("Boolean(document.querySelector('#verdict .stars'))", 90)
        self.assertIn('★★★', self.js("document.getElementById('verdict').textContent"))

    def test_a_ghost_inside_a_wall_is_red_says_why_and_cannot_be_set_down(self):
        self.open('laser')
        self.press('Add')
        self.ghost()
        self.press('Following the pointer')       # stop following; place it by its knobs
        self.slide('x of your mirror 1', -0.35)
        self.slide('z of your mirror 1', 0.5)
        g = self.ghost()
        self.assertFalse(g['fits'])
        self.assertEqual(g['problems'], ['your mirror 1 goes 120 mm into wall; move it'])
        self.assertTrue(self.js("document.getElementById('ghost-down').disabled"))
        self.assertIn('120 mm into wall', self.js("document.getElementById('ghost-state').textContent"))

    def test_on_a_phone_the_scene_comes_into_view_and_its_bar_turns_and_sets_the_ghost_down(self):
        self.open('gap', 390, 844, phone=True)
        self.js("document.getElementById('tray').scrollIntoView()")
        self.assertLess(self.js("document.getElementById('view').getBoundingClientRect().bottom"), 200,
                        'the tray is below the scene, so the scene has scrolled away')
        self.press('Add')
        self.ghost()
        self.assertGreater(self.js("document.getElementById('view').getBoundingClientRect().top"), -41,
                           'adding a piece brings the scene, and its ghost, into view')
        x, y = self.screen_point([0.3, 0.0, 0.0])
        self.page.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': x, 'y': y}]})
        self.page.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
        g = self.ghost()
        self.assertFalse(g['follow'], 'a tap pins it')
        self.press('Turn it on 15 degrees')
        self.assertEqual(self.ghost()['p']['yaw_deg'], 15)
        self.press('✓ Set down')
        self.wait('!window.machineGhostState()', 5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
