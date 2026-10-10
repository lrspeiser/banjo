"""The puzzle page (/play) in Chrome, used the way a person uses it.

A piece added from the tray is a see-through ghost, placed at once where the
view's middle meets the scene; it can be moved by a click, a tap or the
pointer, changed and turned while it is a ghost, then set down and run. A
ghost stood inside a wall is red and says why. On a phone held upright the
scene comes into view when a piece is added, and the ghost's controls sit
just below the scene, out of its way.

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
    def test_a_ghost_is_placed_at_once_follows_on_request_changed_turned_set_down_and_run(self):
        self.open('gap')
        self.js("window.machineView({azimuth: -0.35, elevation: 0.75, distance: 3.2, at: [0.3, 0.2, 0]})")
        time.sleep(1.5)                       # the camera eases to its new view
        self.press('Add')
        g = self.ghost()
        self.assertTrue(not g['follow'] and g['parts'] > 0, 'it is placed at once, ready to change')
        self.press('Follow the pointer')
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
        # Where the ball will go with the ghost as it is: the engine's own
        # rehearsal, drawn before anything is set down or run.
        self.wait("(() => { const p = window.machinePreviewState(); return Boolean(p && p.goal_at_s != null); })()", 30)
        shown = self.js('window.machinePreviewState()')
        self.assertEqual(shown['goal_at_s'], 1.9)
        self.assertIn('after it hits your plank 1', shown['legend'])
        self.press('Run it')
        self.assertIn('Set your plank down first', self.js("document.getElementById('verdict').textContent"))
        self.press('Set it down')
        self.wait('!window.machineGhostState()', 5)
        self.wait(READY, 90)
        self.press('Run it')
        self.wait("Boolean(document.querySelector('#verdict .stars'))", 90)
        self.assertIn('★★★', self.js("document.getElementById('verdict').textContent"))
        # The goal says so, over the scene, and leads on to the next level.
        self.wait("!document.getElementById('level-done').hidden", 10)
        done = self.js("document.getElementById('level-done').textContent")
        self.assertIn('Level complete!', done)
        self.assertIn('Energy used: 30.6 MJ', done)
        self.press('Next level')
        self.wait("/^2\\. /.test(document.getElementById('title').textContent)", 30)

    def test_a_first_visit_shows_how_to_play_and_a_player_can_tell_us_what_happened(self):
        self.open('gap')
        self.js("localStorage.removeItem('banjo-play-guide-seen')")
        self.open('gap')
        self.assertFalse(self.js("document.getElementById('guide').hidden"), 'a first visit shows how to play')
        self.press('Got it')
        self.open('gap')
        self.assertTrue(self.js("document.getElementById('guide').hidden"), 'once read, it stays out of the way')
        self.js("document.getElementById('guide-open').click()")
        self.assertFalse(self.js("document.getElementById('guide').hidden"), 'How to play brings it back')
        self.press('Got it')
        # Telling us: the words, with the level and its pieces, reach the log.
        self.js("document.getElementById('feedback').open = true")
        self.js("document.getElementById('feedback-text').value = 'The plank looked like it floated'")
        self.press('Send')
        self.wait("/Thank you/.test(document.getElementById('feedback-status').textContent)", 10)
        notes = [json.loads(line) for line in (Path(self.logs.name) / 'feedback.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual((notes[-1]['text'], notes[-1]['level']), ('The plank looked like it floated', 'gap'))
        self.assertNotIn('127.0.0.1', json.dumps(notes[-1]), 'nothing that names the player is kept')

    def test_the_levels_screen_shows_each_players_own_progress(self):
        # /play on its own: every level and how far this player has got.
        self.page.send('Emulation.setDeviceMetricsOverride', {'width': 1280, 'height': 860, 'deviceScaleFactor': 1,
                                                              'mobile': False})
        self.page.send('Page.navigate', {'url': f'{self.base}/play'})
        self.wait("document.getElementById('levels-screen') && !document.getElementById('levels-screen').hidden", 90)
        self.assertEqual(self.js("document.querySelectorAll('.ls-list li').length"), 8)
        self.js("document.querySelector('.ls-player input').value = 'Tester'")
        self.press('Add player')
        self.assertIn('Tester: 0 of 8 levels won', self.js("document.querySelector('.ls-summary').textContent"))
        # A win kept for this player shows on the screen; another player's is
        # their own.
        self.js("""(() => { const s = JSON.parse(localStorage.getItem('banjo-play-save'));
            s.players.Tester.levels.gap = {stars: 3, energy_j: 28800000}; localStorage.setItem('banjo-play-save', JSON.stringify(s)); })()""")
        self.page.send('Page.navigate', {'url': f'{self.base}/play'})
        self.wait("!document.getElementById('levels-screen').hidden", 90)
        self.assertIn('Tester: 1 of 8 levels won, 3 of 24 stars', self.js("document.querySelector('.ls-summary').textContent"))
        self.assertIn('Best win: 28.8 MJ', self.js("document.querySelector('.ls-list li').textContent"))
        self.js("(() => { const p = document.getElementById('player-pick'); p.value = 'Player 1'; p.dispatchEvent(new Event('change')); })()")
        self.assertTrue(self.js("document.querySelector('.ls-summary').textContent.startsWith('Player 1:')"))
        self.assertNotIn('28.8 MJ', self.js("document.querySelector('.ls-list li').textContent"), 'Tester’s best is Tester’s')
        self.press('Play level 2, Cut it down')
        self.wait(READY, 90)
        self.assertTrue(self.js("document.getElementById('levels-screen').hidden"))
        self.assertTrue(self.js("document.getElementById('title').textContent.startsWith('2. ')"))

    def test_a_level_opens_before_its_goal_piece_and_a_missed_goal_starts_over(self):
        # Level 4's goal is its engine's piston: before there is one, the
        # level is shown, ready, with what it needs -- not "could not build".
        self.open('steam')
        self.assertEqual(self.js("document.getElementById('verdict').textContent"),
                         'Place a steam engine: the goal is its piston')
        self.assertFalse(self.js("document.getElementById('scene-tray').hidden"), 'pieces are added from the scene')
        # Level 1 with the plank as it comes (too short, off the line): the
        # goal is missed, and Start over clears the pieces, not runs them again.
        self.open('gap')
        self.press('Add a plank')
        self.ghost()
        self.press('Set it down')
        self.wait('!window.machineGhostState()', 5)
        self.wait("/to make/.test(document.getElementById('placed').textContent)", 60)
        self.press('Run it')
        self.wait("!document.getElementById('level-done').hidden", 30)
        self.assertIn('Not this time', self.js("document.getElementById('level-done').textContent"))
        self.press('Start over')
        self.wait(READY, 60)
        self.assertEqual(self.js("document.querySelectorAll('#placed li').length"), 0)
        self.assertFalse(self.js("document.getElementById('scene-tray').hidden"))

    def test_a_ghost_inside_a_wall_is_red_says_why_and_cannot_be_set_down(self):
        self.open('laser')
        self.press('Add')
        self.ghost()
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
        self.assertAlmostEqual(g['p']['x_m'], 0.3, delta=0.03, msg='a tap puts it there')
        # Its controls are just below the scene, out of its way, and in sight:
        # a chip picks the knob, + turns it on.
        card = self.js("document.getElementById('ghost-bar').getBoundingClientRect().toJSON()")
        scene = self.js("document.getElementById('view').getBoundingClientRect().toJSON()")
        self.assertGreaterEqual(card['top'], scene['bottom'] - 1, (card, scene))
        self.assertLessEqual(card['bottom'], 844, 'the controls are on the screen with the scene')
        self.press('Change its turn')
        self.press('More turn')
        self.assertEqual(self.ghost()['p']['yaw_deg'], 15)
        self.press('✓ Set down')
        self.wait('!window.machineGhostState()', 5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
