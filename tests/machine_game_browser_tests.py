"""The puzzle page (/play) in Chrome, used the way a person uses it.

A piece added from the tray is a see-through ghost, placed at once where the
view's middle meets the scene; dragging near it moves it. Clicking or tapping
switches to View without relocating it; a background drag turns the camera.
It can be changed and turned while it is a ghost, then set down and run. A
ghost stood inside a wall is red and says why. On a phone held upright the
scene comes into view when a piece is added, and the ghost's controls sit
just below the scene, out of its way.

    BANJO_LIVE_ENGINE=path/to/banjo_live_world_run python tests/machine_game_browser_tests.py

Needs Chrome (BANJO_CHROME, tests/chrome_driver.py) and the engine. Without them
it skips, unless BANJO_BROWSER_TESTS=required.
"""
import importlib.util
import base64
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import chrome_driver  # noqa: E402

ENGINE = Path(os.environ['BANJO_LIVE_ENGINE']) if os.environ.get('BANJO_LIVE_ENGINE') else None
SETTLED = "(() => { const g = window.machineGhostState(); return Boolean(g && g.answered && !g.busy); })()"
READY = "/ready: press Run it/.test(document.getElementById('clock')?.textContent || '')"


class Puzzles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [what for what, ok in (('the engine (BANJO_LIVE_ENGINE)', ENGINE and ENGINE.is_file()),
                                         ('Chrome (BANJO_CHROME)', chrome_driver.CHROME.is_file())) if not ok]
        if missing:
            if os.environ.get('BANJO_BROWSER_TESTS') == 'required':
                raise RuntimeError('required, and missing: ' + ', '.join(missing))
            raise unittest.SkipTest('missing ' + ', '.join(missing))
        spec = importlib.util.spec_from_file_location('machine_game_page', ROOT / 'scripts/voxel-lab.py')
        lab = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lab)
        import machine_game
        cls.level_count = len(machine_game.load_levels())
        cls.template_count = len(machine_game.sandbox_templates())
        cls.piece_count = len([row for row in machine_game.free_build()['tray'] if not row.get('attach') and not row.get('legacy')])
        cls.river_solution = dict(machine_game.sandbox_water_launch.RIVER_SOLUTION)
        import sandbox_variants
        cls.power_level = sandbox_variants.construct(machine_game.level_by_id('easy-power'),42,version=2)
        # An engine still closing as the tests end holds its log open a moment.
        cls.logs = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        # The game site as deployed: open to anyone, nothing else served.
        cls.server = lab.Server(('127.0.0.1', 0), ENGINE, Path(cls.logs.name), site='game', public=True,
                                profile_db=Path(cls.logs.name)/'profiles.sqlite3')
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.server.server_address[1]}'
        cls.chrome = chrome_driver.Chrome(1280, 860)
        cls.page = cls.chrome.page
        cls.page.send('Network.enable')

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
        said = self.js("document.getElementById('verdict').textContent + ' · ' + document.getElementById('clock').textContent")
        urls={e['params']['requestId']:e['params']['request']['url'] for e in self.page.events if e['method']=='Network.requestWillBeSent'}
        failed=[dict(url=urls.get(e['params']['requestId'],'untracked'),**e['params']) for e in self.page.events if e['method']=='Network.loadingFailed']
        if failed: print('BROWSER_NETWORK_FAILURES',json.dumps(failed),flush=True)
        self.fail(f'waited {seconds:.0f} s for {expression}; the page says {said!r}')

    def open(self, level, width=1280, height=860, phone=False):
        self.page.send('Emulation.setDeviceMetricsOverride',
                       {'width': width, 'height': height, 'deviceScaleFactor': 2 if phone else 1, 'mobile': phone})
        self.page.send('Emulation.setTouchEmulationEnabled', {'enabled': phone, 'maxTouchPoints': 5})
        destination=f'{self.base}/play?level={level}'
        previous=self.js('performance.timeOrigin')
        navigated=self.page.send('Page.navigate', {'url':destination})
        self.assertFalse(navigated.get('errorText'),navigated)
        expected=f'location.href==={json.dumps(destination)}'
        if level=='free':
            # The former Free URL opens its saved design in the one sandbox.
            expected=f"location.origin==={json.dumps(self.base)} && location.pathname==='/machine' && new URLSearchParams(location.search).get('design')===window.machineDesign?.()?.id"
        self.wait(f"performance.timeOrigin!=={previous} && ({expected}) && document.getElementById('clock') && {READY}",90)
        # The view eases to its place as a level opens; a piece added before
        # it gets there lands where a slow page's view happened to be.
        self.wait('window.machineCamera().settled', 30)

    def ghost(self):
        self.wait(SETTLED, 20)
        return self.js('window.machineGhostState()')

    def button_expression(self, name):
        # Duplicate actions may exist on inactive screens or in unopened help.
        # Select the current screen, then reveal its real tab/disclosure.
        return f"""(() => {{const buttons=[...document.querySelectorAll('button')].filter(b=>(b.getAttribute('aria-label')||b.textContent).trim()==={json.dumps(name)});
          return buttons.find(b=>b.getClientRects().length && !b.disabled) || buttons.find(b=>!b.closest('main[hidden],#levels-screen[hidden],#sandbox-screen[hidden],#piece-picker:not([open]),.save-help-panel:not(:popover-open)'));}})()"""

    def press(self, name):
        """A button, by what it says or by its label."""
        if name == 'Set it down':
            name = '✓ Set down'
        if name == 'Cancel' and self.js("Boolean(window.machineGhostState?.()) && ![...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='Cancel'&&b.offsetParent!==null)"):
            name = 'Throw the ghost away'
        # Large trays live in the library; use its ordinary scene entry point.
        if name.startswith('Add a ') and name != 'Add a piece' and self.js("!document.getElementById('tray-library').hidden && !document.getElementById('piece-picker').open"):
            self.press('Add a piece')
        self.reveal_control(self.button_expression(name))
        found = self.js(f"""(() => {{ const b = [...document.querySelectorAll('button')].find(b =>
            !b.disabled && b.offsetParent !== null && (!document.getElementById('piece-picker').open || b.closest('#piece-picker')) && ((b.getAttribute('aria-label') || b.textContent).trim() === {json.dumps(name)}));
            if (b) b.click(); return Boolean(b); }})()""")
        self.assertTrue(found, f'no button {name!r} to press')

    def slide(self, label, value):
        self.reveal_control(f"document.querySelector('[aria-label={json.dumps(label)}]')")
        self.assertTrue(self.js(f"""(() => {{ const el = document.querySelector('[aria-label={json.dumps(label)}]');
            if (!el) return false; el.value = {json.dumps(value)};
            el.dispatchEvent(new Event(el.tagName === 'SELECT' || el.type === 'number' ? 'change' : 'input', {{bubbles: true}})); return true; }})()"""),
            f'no control {label!r}')

    def screen_point(self, point):
        return self.js(f'window.machineScreenPoint({json.dumps(point)})')

    def mouse(self, kind, x, y):
        extra = {'button': 'left', 'clickCount': 1} if kind != 'mouseMoved' else {}
        self.page.send('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y, **extra})

    def drag(self, start, end, touch=False, button='left', steps=8, modifiers=0, via=None):
        if touch:
            self.page.send('Input.dispatchTouchEvent', {'type':'touchStart', 'touchPoints':[{'x':start[0],'y':start[1],'id':1}]})
        else:
            self.page.send('Input.dispatchMouseEvent', {'type':'mousePressed','x':start[0],'y':start[1],
                                                       'button':button,'buttons':{'left':1,'right':2,'middle':4}[button],'clickCount':1,'modifiers':modifiers})
        waypoints=[start]+([via] if via else [])+[end]
        moves=[(a[0]+(b[0]-a[0])*k/steps,a[1]+(b[1]-a[1])*k/steps)
               for a,b in zip(waypoints,waypoints[1:]) for k in range(1,steps+1)]
        for x,y in moves:
            if touch:
                self.page.send('Input.dispatchTouchEvent', {'type':'touchMove','touchPoints':[{'x':x,'y':y,'id':1}]})
            else:
                self.page.send('Input.dispatchMouseEvent', {'type':'mouseMoved','x':x,'y':y,
                                                           'button':button,'buttons':{'left':1,'right':2,'middle':4}[button],'modifiers':modifiers})
            time.sleep(.03)
        if touch:
            self.page.send('Input.dispatchTouchEvent', {'type':'touchEnd','touchPoints':[]})
        else:
            self.page.send('Input.dispatchMouseEvent', {'type':'mouseReleased','x':end[0],'y':end[1],
                                                       'button':button,'buttons':0,'clickCount':1,'modifiers':modifiers})

    def drag_ghost_to(self, x, z, touch=False):
        p=self.ghost()['p']
        bottom=self.js('window.machineGhostScreen().bottom')
        start=self.screen_point([p['x_m'],bottom,p.get('z_m',0)])
        end=self.screen_point([x,bottom,z])
        length=((end[0]-start[0])**2+(end[1]-start[1])**2)**.5
        # Intentional precision drags must first exceed the click guard.
        # At 320px a 3cm move projects to <7px; reach 12px, then come back
        # while still holding. Separate tests retain straight <7px gestures
        # and require them to leave the piece untouched.
        via=[start[i]+(end[i]-start[i])*12/length for i in range(2)] if 0<length<8 else None
        self.drag(start,end,touch=touch,via=via)
        return self.ghost()

    def empty_scene_point(self):
        point=self.js("""(() => {const r=document.querySelector('#view canvas').getBoundingClientRect(),b=window.machineGhostScreen();
            for(const fy of [.7,.5,.35,.85])for(const fx of [.85,.15,.5]){const x=r.left+r.width*fx,y=r.top+r.height*fy;
              if((!b || x<b.x0-40 || x>b.x1+40 || y<b.y0-40 || y>b.y1+40) && document.elementFromPoint(x,y)?.tagName==='CANVAS')return [x,y];}
            return null;})()""")
        self.assertIsNotNone(point,'there is an unobstructed background drag target outside the 40px grab margin')
        return point

    def key(self, key):
        self.js('document.activeElement && document.activeElement.blur()')
        named = {'Escape': 27, 'Enter': 13}
        code = named.get(key) or ord(key.upper())
        for kind in ('keyDown', 'keyUp'):
            self.page.send('Input.dispatchKeyEvent', {'type': kind, 'key': key,
                                                      'code': key if key in named else 'Key' + key.upper(),
                                                      'windowsVirtualKeyCode': code,
                                                      **({'text': key} if kind == 'keyDown' and key not in named else {})})

    def click_visible(self, label):
        """Hit the actual visible target, rather than invoking its DOM handler."""
        if label == 'Set it down':
            label = '✓ Set down'
        self.reveal_control(self.button_expression(label))
        target = self.js(f"""(() => {{ const el = [...document.querySelectorAll('button')].find(b =>
            !b.disabled && b.offsetParent !== null && (!document.getElementById('piece-picker').open || b.closest('#piece-picker')) && (b.getAttribute('aria-label') || b.textContent).trim() === {json.dumps(label)});
            if (!el) return null; const r = el.getBoundingClientRect(), x = r.left + r.width/2, y = r.top + r.height/2;
            return {{x,y,w:r.width,h:r.height,visible:r.left>=0 && r.right<=innerWidth && r.top>=0 && r.bottom<=innerHeight,
                uncovered:el.contains(document.elementFromPoint(x,y))}}; }})()""")
        self.assertIsNotNone(target, label)
        self.assertTrue(target['visible'] and target['uncovered'], (label, target))
        self.assertGreaterEqual(target['w'], 44, (label, target))
        self.assertGreaterEqual(target['h'], 44, (label, target))
        self.mouse('mousePressed', target['x'], target['y'])
        self.mouse('mouseReleased', target['x'], target['y'])

    def reveal_control(self, expression):
        """Use the real shared tabs and disclosures before touching a control."""
        if self.js(f"(()=>{{const el={expression};return Boolean(el?.closest('#power-pins,#terminal-pins')&&!el.getClientRects().length&&!document.getElementById('wire-mode').matches('[aria-pressed=true]'));}})()"):
            self.click_visible('Connect wires')
        panel = self.js(f"(() => {{const el={expression}; const pane=el?.closest('[role=tabpanel]'); return pane?.hidden ? document.getElementById(pane.getAttribute('aria-labelledby'))?.textContent : null;}})()")
        if panel:
            self.click_visible(panel.strip())
        # Precision controls, gallery sections and the chooser's More menu
        # remain collapsed until a player asks for them. Click each ancestor
        # summary, rather than toggling open directly to bypass the new UI.
        for _ in range(8):
            summary = self.js(f"(() => {{const el={expression}; const ds=[]; for(let p=el?.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS'&&!p.open&&!p.hidden&&!(el.tagName==='SUMMARY'&&p===el.parentElement))ds.push(p); const s=ds.at(-1)?.querySelector(':scope > summary'); if(!s)return null;s.scrollIntoView({{block:'nearest',inline:'nearest'}});const r=s.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];}})()")
            if not summary:
                break
            self.mouse('mousePressed',*summary); self.mouse('mouseReleased',*summary)
        else:
            self.fail('A closed disclosure could not be opened with its visible summary')
        self.js(f"(() => {{const el={expression}; if (el?.closest('.phone-pane')) el.scrollIntoView({{block:'nearest',inline:'nearest'}});}})()")

    def create_design(self, name=None):
        self.press('Add New Design'); self.wait(READY,90)
        self.assertEqual(self.js('machineDesign().name'),'Untitled design')
        if name:
            self.reveal_control("document.getElementById('design-name')")
            self.js(f"(()=>{{const el=document.getElementById('design-name');el.value={json.dumps(name)};el.dispatchEvent(new Event('change',{{bubbles:true}}));}})()")
            self.assertEqual(self.js('machineDesign().name'),name)

    def click_summary(self, selector):
        self.reveal_control(f'document.querySelector({json.dumps(selector)})')
        target=self.js(f"(()=>{{const el=document.querySelector({json.dumps(selector)});if(!el)return null;el.scrollIntoView({{block:'nearest'}});const r=el.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2;return {{x,y,w:r.width,h:r.height,visible:r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight,uncovered:el.contains(document.elementFromPoint(x,y))}};}})()")
        self.assertIsNotNone(target,selector)
        self.assertTrue(target['visible'] and target['uncovered'],(selector,target))
        self.assertGreaterEqual(target['h'],44,(selector,target))
        self.mouse('mousePressed',target['x'],target['y']);self.mouse('mouseReleased',target['x'],target['y'])

    def assert_power_layout(self):
        # A rebuild reframes the camera; the anchors follow it each frame.
        self.wait('window.machineCamera().settled', 30)
        geometry = """(() => {const cards=[...document.querySelectorAll('.power-pin')].filter(e=>!e.hidden),
            run=document.getElementById('start').getBoundingClientRect(), view=document.getElementById('view').getBoundingClientRect();
            const overlaps=(a,b)=>a.left<b.right && a.right>b.left && a.top<b.bottom && a.bottom>b.top;
            return cards.map((e,i)=>{const r=e.getBoundingClientRect();return {name:e.dataset.port,
                visible:r.left>=0 && r.right<=innerWidth && r.top>=0 && r.bottom<=innerHeight,
                inView:r.left>=view.left && r.right<=view.right && r.top>=view.top && r.bottom<=view.bottom,
                coversRun:overlaps(r,run),overlapsOther:cards.some((b,j)=>j!==i && overlaps(r,b.getBoundingClientRect()))};});})()"""
        # Readouts change card heights; allow the next render frame to lay
        # them out before trying to press the real on-screen targets.
        if not self.js("document.getElementById('wire-mode').getAttribute('aria-pressed')==='true'"):
            self.click_visible('Connect wires')
        self.wait(f"(() => {{const rows={geometry};return rows.length>=2 && rows.every(r=>r.visible && r.inView && !r.coversRun && !r.overlapsOther);}})()", 10)
        layout = self.js(geometry)
        self.assertGreaterEqual(len(layout), 2, layout)
        self.assertTrue(all(r['visible'] and r['inView'] and not r['coversRun'] and not r['overlapsOther'] for r in layout), layout)

    # ---- the tests ---------------------------------------------------------------------
    def test_laser_burn_has_native_cell_progress_inspection_and_a_visible_gap_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('laser',width,height,phone=width!=1280)
                for index,x,z,angle in [(1,.614,0,45),(2,.614,1.015,-45)]:
                    self.press('Add a mirror');self.ghost()
                    for label,value in [('x',x),('z',z),('turn',angle)]:
                        self.slide(f'{label} of your mirror {index}',value)
                    self.assertTrue(self.ghost()['fits'])
                    self.click_visible('Set it down');self.wait(f'!window.machineGhostState() && {READY}',60)
                self.click_visible('Run it')
                self.wait("window.machineThermalState().cells.some(c=>c.charring&&c.progress>0&&c.progress<1)",20)
                early=self.js('window.machineThermalState()')
                self.assertIn('Charring',early['text']);self.assertIn('300 °C',early['text'])
                self.click_visible('Inspect burn')
                self.wait('window.machineThermalState().inspecting',5)
                self.assertLessEqual(self.js('window.machineThermalState().rayPaths'),6,
                    'Inspecting uses a few real ray paths so the gap remains visible')
                self.assertTrue(self.js("document.getElementById('thermal-readout').getBoundingClientRect().right<=innerWidth"))
                self.assertTrue(self.js("document.getElementById('inspect-heat').getBoundingClientRect().height>=44"))
                try:self.wait("window.machineThermalState().text.includes('Cut through')",20)
                except AssertionError:
                    print('THERMAL_DISPLAY',self.js('window.machineThermalState()'),flush=True)
                    raise
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertFalse(self.js("Boolean(document.getElementById('level-done').closest('#view'))"),
                    'The win message must not cover the cut or falling load')
                after=self.js('window.machineThermalState()')
                self.assertTrue(after['taken'])
                self.assertFalse(any(c['body']==after['taken'][-1]['body'] for c in after['cells']),
                    'A removed segment cannot remain a char overlay; its neighbors may still be heated')
                self.click_visible('Whole machine')
                self.wait('!window.machineThermalState().inspecting',5)
                self.click_visible('Set up again');self.wait(READY,60)
                self.assertFalse(self.js('window.machineThermalState().visible'))

    def test_catalogue_audit_opens_every_level_with_attached_touch_controls(self):
        import machine_game as game
        for width,height in ((1280,860),(390,844),(844,390)):
            for level in game.load_levels():
                with self.subTest(level=level['id'],viewport=(width,height)):
                    self.open(level['id'],width,height,phone=width!=1280)
                    geometry=self.js("""(() => {const view=document.getElementById('view').getBoundingClientRect(),bar=document.getElementById('phone-toolbar').getBoundingClientRect();
                      const attached=(bar.left>=view.left&&bar.right<=view.right&&bar.top>=view.top&&bar.top<=view.bottom+12)||
                        (bar.left>=view.right&&bar.left<=view.right+12&&bar.top>=view.top&&bar.top<=view.top+12);
                      return ['start','reset'].map(id=>{const el=document.getElementById(id),r=el.getBoundingClientRect();
                        return {id,w:r.width,h:r.height,visible:r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight,
                          attached,
                          uncovered:el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))};});})()""")
                    self.assertTrue(all(r['w']>=44 and r['h']>=44 and r['visible'] and r['attached'] and r['uncovered'] for r in geometry),geometry)
                    self.assertFalse(self.js("document.getElementById('guide').open"))
                # This fixture owns these engines; close previous pages so
                # a catalogue sweep never consumes the live-session budget.
                self.server.machines.close_all()

    def test_edit_invalidates_power_feedback_before_a_delayed_placement_reply(self):
        self.open('easy-bulb')
        self.press('Add a bulb');self.ghost()
        self.click_visible('Set it down');self.wait(f'!window.machineGhostState() && {READY}',60)
        self.slide('Adjust a piece','0');self.ghost()
        self.wait("window.machinePowerFeedbackState().labels.some(r=>r.device)&&!document.getElementById('flow-preview').hidden",30)
        self.js("""window.auditOriginalFetch=window.fetch;
          window.auditGate=new Promise(resolve=>window.releaseAuditCheck=resolve);
          window.fetch=async (...args)=>{const hold=args[1]?.body&&JSON.parse(args[1].body).op==='level_ghost';
            const response=await window.auditOriginalFetch(...args);if(hold)await window.auditGate;return response;};""")
        try:
            self.slide('bulb size of your bulb 1','small')
            self.wait("window.machinePowerFeedbackState().labels.some(r=>r.device&&r.text.includes('Updating'))",5)
            self.assertEqual(self.js('window.machinePowerFeedbackState().dots'),0)
            self.assertTrue(self.js("document.getElementById('flow-preview').hidden"))
        finally:self.js('window.releaseAuditCheck();window.fetch=window.auditOriginalFetch')
        self.ghost()
        self.wait("window.machinePowerFeedbackState().labels.some(r=>r.device&&/12 V.*2\\.5 W/.test(r.text)&&!r.text.includes('Updating'))",30)

    def test_charge_lift_requires_a_drawn_panel_to_supply_lead_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-charge-lift',width,height,phone=width!=1280)
                self.press('Add a solar panel');self.ghost()
                for label,value in [('Position along (m)',.8),('Position across (m)',0),('turn',-90),('tip',70)]:
                    self.slide(f'{label} of your solar 1',value)
                self.assertTrue(self.ghost()['fits'])
                self.click_visible('Set it down');self.wait(f'!window.machineGhostState() && {READY}',60)
                self.assertIn('Output not wired',self.js("document.getElementById('power-labels').textContent"))
                self.click_visible('Run it');self.wait("/World [12]\\./.test(document.getElementById('clock').textContent)",30)
                self.click_visible('Pause')
                self.assertTrue(self.js("document.getElementById('level-done').hidden"))
                self.click_visible('Set up again');self.wait(READY,60)
                self.assert_power_layout()
                self.click_visible('Power output of your solar 1');self.click_visible('Power input of supply')
                self.wait(f'window.machinePlacements().length===2 && {READY}',60)
                self.click_visible('Run it');self.wait("!document.getElementById('level-done').hidden",30)

    def test_motor_lesson_requires_choosing_forward_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-motor',width,height,phone=width!=1280)
                self.press('Add a motor');state=self.ghost()
                self.assertEqual(state['p']['direction'],'reverse')
                self.slide('direction of your motor 1','forward');self.ghost()
                self.click_visible('Run it');self.wait("!document.getElementById('level-done').hidden",30)

    def test_bulb_shrinks_to_match_visible_supply_limit_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-bulb',width,height,phone=width!=1280)
                self.press('Add a bulb');self.ghost()
                self.assertEqual(self.js("document.querySelector('[aria-label=\"Its bulb size\"]').value"),'large')
                self.click_visible('Set it down');self.wait(f'!window.machineGhostState() && {READY}',60)
                self.wait("window.machinePowerFeedbackState().labels.some(r=>r.device==='bulb 1'&&/12 V.*12\\.0 W/.test(r.text))",30)
                self.wait("window.machinePowerFeedbackState().labels.some(r=>r.wire&&/Shared supply ≤ 2\\.5 W/.test(r.text))",30)
                self.click_visible('Run it');self.wait("/World [12]\\./.test(document.getElementById('clock').textContent)",30)
                self.click_visible('Pause')
                self.assertTrue(self.js("document.getElementById('level-done').hidden"))
                big=next(d for d in self.js('window.machineContactState()')['liveDevices'] if d['kind']=='bulb')
                self.assertAlmostEqual(big['power_w'],.520833333,places=6)
                self.reveal_control("document.getElementById('piece-edit')")
                self.js("(()=>{const s=document.getElementById('piece-edit');s.value='0';s.dispatchEvent(new Event('change',{bubbles:true}));})()")
                self.ghost();self.press('Change its bulb size');self.slide('Its bulb size','small');self.ghost()
                self.click_visible('Set it down');self.wait(f'!window.machineGhostState() && {READY}',60)
                self.wait("window.machinePowerFeedbackState().labels.some(r=>r.device==='bulb 1'&&/12 V.*2\\.5 W/.test(r.text))",30)
                self.click_visible('Run it');self.wait("!document.getElementById('level-done').hidden",30)
                small=next(d for d in self.js('window.machineContactState()')['liveDevices'] if d['kind']=='bulb')
                self.assertGreater(small['power_w'],2.4)

    def test_grounded_battery_voltage_and_drawn_wire_thickness_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-power',width,height,phone=width!=1280)
                self.press('Add a battery');self.ghost()
                self.assertFalse(self.js("Boolean(document.querySelector('[aria-label=\"along (m) of your battery 1\"]'))"))
                self.slide('Its voltage',12);self.ghost()
                self.click_visible('Set it down');self.wait(f'!window.machineGhostState() && {READY}',60)
                for a,b in [('your battery 1 plus','lamp plus'),('lamp minus','your battery 1 minus')]:
                    self.click_visible('Connect '+a)
                    self.wait("window.machineGhostState()?.answered && !window.machineGhostState()?.busy",20)
                    self.click_visible('Connect '+b)
                    self.wait(f'!window.machineGhostState() && {READY}',60)
                self.wait("window.machinePowerFeedbackState().labels.some(r=>r.device==='lamp'&&/8\\.8 V/.test(r.text))",30)
                self.assertTrue(self.js("window.machinePowerFeedbackState().labels.some(r=>r.device==='lamp'&&/1\\.6 W/.test(r.text))"))
                for index in (1,2):
                    self.reveal_control("document.getElementById('piece-edit')")
                    self.js(f"(()=>{{const s=document.getElementById('piece-edit');s.value='{index}';s.dispatchEvent(new Event('change',{{bubbles:true}}));}})()")
                    self.ghost();self.press('Change its wire thickness')
                    self.slide('Its wire thickness','standard');self.ghost()
                    self.click_visible('Set it down');self.wait(f'!window.machineGhostState() && {READY}',60)
                self.wait("window.machinePowerFeedbackState().labels.some(r=>r.device==='lamp'&&/11\\.9 V/.test(r.text))",30)
                self.assertTrue(self.js("window.machinePowerFeedbackState().labels.some(r=>r.device==='lamp'&&/3\\.0 W/.test(r.text))"))
                self.click_visible('Run it');self.wait("!document.getElementById('level-done').hidden",30)
                self.assertGreater(next(d for d in self.js('window.machineContactState()')['liveDevices'] if d['kind']=='bulb')['power_w'],2)

    def place_contact_battery(self, placement, charge=None):
        self.press('Add a battery'); self.ghost()
        knobs = next(t['knobs'] for t in self.power_level['tray'] if t['piece'] == 'battery')
        for key, value in placement.items():
            if key == 'piece': continue
            self.slide(f"{knobs[key].get('label', key)} of your battery 1", value)
        if charge is not None:
            self.slide(f"{knobs['charge_percent']['label']} of your battery 1", charge)
        self.assertTrue(self.ghost()['fits'])
        self.press('Set it down'); self.wait(f'!window.machineGhostState() && {READY}', 60)

    def test_contact_battery_drop_powers_lamp_on_desktop_and_phones(self):
        for width, height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open(self.power_level['id'],width,height,phone=width!=1280)
                self.place_contact_battery(self.power_level['solution'][0])
                start = self.js('window.machineContactState()')
                self.assertEqual(len(start['liveContacts']), 4)
                self.assertTrue(all(c['closed'] is False for c in start['liveContacts']))
                cap = next(name for name in start['liveTerminals'] if name.startswith('your battery 1:plus'))
                self.assertEqual(self.js("document.querySelectorAll('#power-labels .power-label').length"),0)
                self.assertTrue(self.js("[...document.querySelectorAll('#terminal-pins .terminal-buttons button')].every(b=>b.disabled)"))
                self.click_visible('Run it')
                self.assertTrue(self.js("document.getElementById('preview-legend').hidden"))
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertTrue(self.js("document.getElementById('preview-legend').hidden"))
                state = self.js('window.machineContactState()')
                self.assertFalse(state['preview'])
                self.assertGreaterEqual(sum(c['closed'] for c in state['liveContacts']),2)
                self.assertGreater(next(d for d in state['liveDevices'] if d['kind']=='bulb')['power_w'],2)
                self.assertLess(state['liveTerminals'][cap][1],start['liveTerminals'][cap][1]-.1)
                battery = next(b for b in state['batteries'] if b['name'].startswith('your battery 1'))
                self.assertLess(battery['charge_j'],battery['capacity_j'])
                self.assertIn('+ closed',self.js("document.querySelector('.terminal-label[data-kind=socket]').textContent"))
                self.assertIn('− closed',self.js("document.querySelector('.terminal-label[data-kind=socket]').textContent"))
                self.assertIn('W lamp',self.js("document.querySelector('.terminal-label[data-kind=bulb]').textContent"))

    def test_contact_battery_misalignment_and_empty_charge_stay_dark(self):
        for width, height in ((1280,860),(390,844),(844,390)):
            for mode in ('misaligned','empty'):
                with self.subTest(viewport=(width,height),mode=mode):
                    self.open(self.power_level['id'],width,height,phone=width!=1280)
                    placement = self.power_level['wrong'][0] if mode=='misaligned' else self.power_level['solution'][0]
                    self.place_contact_battery(placement,charge=0 if mode=='empty' else None)
                    self.click_visible('Run it')
                    self.wait("/World 2\\./.test(document.getElementById('clock').textContent)",30)
                    self.press('Pause')
                    state = self.js('window.machineContactState()')
                    self.assertLess(abs(next(d for d in state['liveDevices'] if d['kind']=='bulb')['power_w']),1e-9)
                    self.assertTrue(self.js("document.getElementById('level-done').hidden"))
                    if mode=='empty':
                        self.assertGreaterEqual(sum(c['closed'] for c in state['liveContacts']),2)
                        self.assertEqual(next(b for b in state['batteries'] if b['name'].startswith('your battery 1'))['charge_j'],0)
                    else:
                        self.assertFalse(any(c['closed'] for c in state['liveContacts']))

    def test_contact_battery_setup_saves_reloads_and_restores_versions(self):
        for width, height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.page.send('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':width!=1280})
                self.page.send('Emulation.setTouchEmulationEnabled',{'enabled':width!=1280,'maxTouchPoints':5})
                self.page.send('Page.navigate',{'url':f'{self.base}/machine'})
                self.wait("Boolean(document.querySelector('#prebuilt-designs button'))",30)
                self.press('Start from Drop a battery into its holder');self.wait(READY,60)
                initial=self.js('window.machinePlacements()')
                base=self.js('window.machineDesign().draft.base')
                first_version=self.js('Math.max(0,...window.machineDesign().versions.map(v=>v.number))+1')
                self.assertEqual(initial[0]['mount'],'contact pack')
                self.assertEqual(len(self.js('window.machineContactState().liveContacts')),4)
                self.click_visible('Save version');self.wait(f"/Version {first_version} saved/.test(document.getElementById('design-status').textContent)",10)
                self.press('Pick up your battery 1');self.ghost()
                self.slide('initial charge (%) of your battery 1',0)
                self.assertTrue(self.ghost()['fits'])
                self.press('Set it down');self.wait(f'!window.machineGhostState() && {READY}',60)
                self.click_visible('Save version');self.wait(f"/Version {first_version+1} saved/.test(document.getElementById('design-status').textContent)",10)
                self.page.send('Page.navigate',{'url':self.js('location.href')});self.wait(READY,60)
                self.assertEqual(self.js('window.machinePlacements()[0].charge_percent'),0)
                self.assertEqual(self.js('window.machineDesign().draft.base'),base)
                self.reveal_control("document.querySelector('#design-versions summary')")
                self.js("document.querySelector('#design-versions summary').scrollIntoView({block:'nearest'})")
                x,y=self.js("(() => {const r=document.querySelector('#design-versions summary').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()")
                self.mouse('mousePressed',x,y);self.mouse('mouseReleased',x,y)
                self.wait("document.getElementById('design-versions').open",5)
                self.reveal_control("document.getElementById('version-pick')")
                self.js(f"document.getElementById('version-pick').value='{first_version}';document.getElementById('version-pick').dispatchEvent(new Event('change',{{bubbles:true}}))")
                self.click_visible('Restore version');self.wait(READY,60)
                self.assertEqual(self.js('window.machinePlacements()'),initial)
                self.assertEqual(self.js('window.machineDesign().draft.base'),base)
                self.click_visible('Run it')
                self.wait("window.machineContactState().liveDevices.some(d=>d.kind==='bulb' && d.power_w>2)",30)
                self.press('Pause')
                self.assertGreaterEqual(sum(c['closed'] for c in self.js('window.machineContactState().liveContacts')),2)

    def test_contact_battery_solar_cable_and_input_follow_the_fallen_pack(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.page.send('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':width!=1280})
                self.page.send('Emulation.setTouchEmulationEnabled',{'enabled':width!=1280,'maxTouchPoints':5})
                self.page.send('Page.navigate',{'url':f'{self.base}/machine'})
                self.wait("Boolean(document.querySelector('#prebuilt-designs button'))",30)
                self.press('Start from Drop a battery into its holder');self.wait(READY,60)
                self.assertEqual(self.js("document.querySelectorAll('#power-labels .power-label').length"),0)
                self.press('Add a solar panel');self.ghost()
                self.slide('Position along (m) of your solar 2',0)
                self.slide('Position across (m) of your solar 2',.7)
                self.assertTrue(self.ghost()['fits'])
                self.press('Set it down');self.wait(f'!window.machineGhostState() && {READY}',60)
                self.assert_power_layout()
                self.click_visible('Power output of your solar 2')
                self.click_visible('Power input of your battery 1')
                self.wait(f'window.machinePlacements().length===3 && {READY}',60)
                before=self.js("window.machineWiringState().powerPorts['your battery 1:power']")
                self.click_visible('Run it')
                self.wait("window.machineContactState().liveDevices.some(d=>d.kind==='bulb' && d.power_w>2)",30)
                self.press('Pause')
                state=self.js('window.machineWiringState()')
                after=state['powerPorts']['your battery 1:power']
                self.assertLess(after[1],before[1]-.1)
                self.assertEqual(state['powerCables'][0]['points_m'][1],after)
                self.assertIn('Cable connected',self.js("document.getElementById('power-labels').textContent"))


    def test_lift_lessons_start_with_the_load_and_the_added_device_lifts_that_same_body(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            for ident,piece,target,control,value in [('easy-spring','spring','spring load','Its Relaxed length',.7),
                    ('easy-tackle','block and tackle','crate','Its Counterweight preset',4.7)]:
                with self.subTest(viewport=(width,height),level=ident):
                    self.open(ident,width,height,phone=width!=1280)
                    before=self.js(f'window.machineBodies()[{json.dumps(target)}]')
                    self.assertIsNotNone(before)
                    self.press('Add a '+piece);self.ghost()
                    self.slide(control,value);self.ghost()
                    self.assertEqual(self.ghost()['p']['load'],target)
                    self.click_visible('Run it');self.wait("!document.getElementById('level-done').hidden",30)
                    after=self.js(f'window.machineBodies()[{json.dumps(target)}]')
                    self.assertGreater(after[1],before[1]+(.049 if ident=='easy-spring' else .249))
                    self.assertFalse(self.js(f"Object.keys(window.machineBodies()).some(n=>/^your (spring|tackle) \\d+ load$/.test(n))"))

    def test_gear_lesson_requires_an_individual_sized_and_placed_gear(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-gears',width,height,phone=width!=1280)
                self.assertIn('target gear wheel',self.js('Object.keys(window.machineBodies())'))
                self.press('Add a gear');self.ghost()
                self.assertEqual(self.ghost()['p']['teeth'],18)
                self.slide('Its Teeth / size',12);self.ghost()
                self.wait('window.machineCamera().settled',30)
                self.drag_ghost_to(0,0,touch=width!=1280)
                self.assertTrue(self.ghost()['fits'],self.ghost())
                self.click_visible('Run it')
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Goal at',self.js("document.getElementById('verdict').textContent"))
                self.assertIn('target gear wheel',self.js('Object.keys(window.machineBodies())'))

    def test_individual_gear_example_library_and_saved_version_reopen(self):
        self.anonymous_levels(width=390,height=844)
        self.press('Sandbox: build anything')
        self.wait("!document.getElementById('sandbox-screen').hidden",10)
        self.press('Start from Fast wheel slow wheel');self.wait(READY,60)
        original=self.js('window.machinePlacements()')
        self.assertEqual([p['piece'] for p in original],['gear'])
        self.press('Add a piece');self.slide('Search pieces','gear')
        self.assertEqual(self.js("[...document.querySelectorAll('#piece-grid strong')].map(e=>e.textContent)"),['gear'])
        self.press('Back to sandbox')
        self.slide('Adjust a piece','0');self.ghost()
        self.slide('Position across (m) of your gear 1',.4);self.ghost()
        self.press('Set it down');self.wait(READY,60)
        before=self.js('window.machineDesign().versions.length')
        self.press('Save version')
        self.wait(f"window.machineDesign().versions.length==={before+1} && /Version .*saved/.test(document.getElementById('design-status').textContent)",10)
        self.anonymous_cloud_saved()
        self.page.send('Page.reload',{});self.wait(READY,60)
        self.assertEqual(self.js('window.machinePlacements()[0].z_m'),.4)
        self.reveal_control("document.getElementById('version-pick')")
        self.js("document.getElementById('version-pick').value='1'")
        self.press('Restore version');self.wait(READY,60)
        self.assertEqual(self.js('window.machinePlacements()'),original)

    def place_river_wheel(self):
        self.press('Add a water wheel');initial=self.ghost()['p']
        self.assertEqual(initial['radius_m'],self.river_solution['radius_m'],'The river base must provide its usable wheel size before editing')
        self.assertEqual(initial['side'],'off','The river wheel must start with its falling pour off')
        for key,label in [('x_m','along channel (m)'),('z_m','across river (m)'),
                          ('radius_m','wheel radius (m)')]:
            self.slide(f'{label} of your water_wheel 1',self.river_solution[key])
        self.press('Change its drum load')
        self.slide('drum load (optional) of your water_wheel 1','')
        self.ghost()
        self.assertEqual(self.js("document.querySelector('[aria-label=\"Its drum load\"]').value"),'')
        self.slide('drum load (optional) of your water_wheel 1',self.river_solution['load_part'])
        self.ghost()
        self.assertEqual(self.js("document.querySelector('[aria-label=\"Its drum load\"]').value"),'river gate',
                         'Changing the full connection selector must update the compact control')
        self.assertTrue(self.ghost()['fits'])
        self.press('Set it down');self.wait(f'!window.machineGhostState() && {READY}',60)

    def assert_measured_river_current(self):
        self.wait('window.machineRiverState()?.visible && window.machineRiverState().arrows>0',20)
        current=self.js('window.machineRiverState()')
        self.assertTrue(current['hasCurrent'])
        self.assertGreater(current['inflow_m3_s'],0)
        self.assertTrue(current['samples'])
        self.assertTrue(all(s['depth_m']>0 and len(s['velocity_m_s'])==2 for s in current['samples']))
        self.assertTrue(any(s['velocity_m_s'][0]>0 for s in current['samples']),'Native downstream velocity supplies the visible arrows')

    def test_separate_tank_teaches_opening_and_shows_native_water_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390),(320,568)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-water-wheel',width,height,phone=width!=1280)
                self.assertIn('wheel target',self.js('Object.keys(window.machineBodies())'))
                self.press('Add a water tank');self.ghost()
                self.assertEqual(self.ghost()['p']['opening_percent'],0)
                self.assertEqual(self.ghost()['p']['x_m'],-.2)
                self.wait('window.machineCamera().settled',30)
                for point in ((-.2,1.38,.52),(0,.15,0)):
                    screen=self.screen_point(point)
                    self.assertTrue(self.js(f"(()=>{{const r=document.getElementById('view').getBoundingClientRect();return {screen[0]}>=r.left && {screen[0]}<=r.right && {screen[1]}>=r.top && {screen[1]}<=r.bottom;}})()"),point)
                self.wait('window.machineWaterDisplay().length===1',10)
                self.assertAlmostEqual(self.js('window.machineWaterDisplay()[0].litres'),4)
                self.assertGreater(self.js('window.machineWaterDisplay()[0].height_m'),0)
                self.wait('window.machineWaterDisplay()[0].flow_l_s===0',60)
                self.assertEqual(self.js("document.querySelector('[aria-label=\"Its tap opening\"]').value"),'0')
                self.slide('Its tap opening',75);self.ghost()
                self.wait('window.machineWaterDisplay()[0].flow_l_s>0',60)
                self.assertEqual(self.ghost()['p']['opening_percent'],75)
                self.assertTrue(self.js(READY))
                self.click_visible('Run it')
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertEqual(len(self.js('window.machinePlacements()')),1)
                self.assertIn('Goal at',self.js("document.getElementById('verdict').textContent"))
                self.assertLess(self.js('window.machineWaterDisplay()[0].litres'),4)
                self.click_visible('Set up again');self.wait(READY,60)
                self.wait('window.machineWaterDisplay()[0].litres===4',10)
                self.assertEqual(self.js('window.machinePlacements()[0].opening_percent'),75)

    def test_water_shares_preserve_legacy_feeds_and_new_tap_versions(self):
        import sandbox_water_launch as water
        for name,placements in [('Legacy wheel',[dict(piece='water_wheel')]),
                ('Legacy tank',[dict(piece='water_tank')]),
                ('Gravity tank',[dict(piece='water_tank',outlet_model='gravity',opening_percent=38)])]:
            draft=dict(name=name,base=water.CHANNEL_BASE,placements=placements)
            packed=base64.urlsafe_b64encode(json.dumps(draft).encode()).decode().rstrip('=')
            self.page.send('Page.navigate',{'url':f'{self.base}/machine#build=j{packed}'})
            self.wait(f'window.machineDesign?.()?.name==={json.dumps(name)} && {READY}',60)
            saved=self.js('window.machinePlacements()[0]')
            if name=='Legacy wheel':self.assertEqual(saved['side'],'left')
            elif name=='Legacy tank':self.assertEqual(saved['outlet_model'],'metered')
            else:
                self.assertEqual(saved['opening_percent'],38)
                self.wait('window.machineWaterDisplay().length===1',10)
            count=self.js('window.machineDesign().versions.length')
            self.press('Save version')
            # The initial native check runs before profile sync becomes
            # pending. Wait for the save itself, not a previous sync receipt.
            self.wait(f'window.machineDesign().versions.length==={count+1} && /Version .*saved/.test(document.getElementById("design-status").textContent)',10)
            self.anonymous_cloud_saved()
            self.page.send('Page.navigate',{'url':self.js('location.href')});self.wait(READY,60)
            self.assertEqual(self.js('window.machinePlacements()[0]'),saved)
            self.assertEqual(self.js('window.machineDesign().versions.at(-1).draft.placements[0]'),saved)

    def test_simple_river_wheel_needs_dragging_off_the_bank(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-river-wheel',width,height,phone=width!=1280)
                self.press('Add a water wheel');self.ghost()
                self.assertEqual(self.ghost()['p']['z_m'],1)
                self.assertEqual(self.ghost()['p']['side'],'off')
                self.assertFalse(self.js('window.machineWaterDisplay().length'))
                self.drag_ghost_to(0,0,touch=width!=1280)
                self.assertLess(abs(self.ghost()['p']['z_m']),.025)
                self.click_visible('Run it');self.assert_measured_river_current()
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Goal at',self.js("document.getElementById('verdict').textContent"))

    def test_river_workbench_places_a_useful_wheel_and_restores_its_saved_connections(self):
        self.page.send('Emulation.setDeviceMetricsOverride',{'width':1280,'height':860,'deviceScaleFactor':1,'mobile':False})
        self.page.send('Emulation.setTouchEmulationEnabled',{'enabled':False})
        self.page.send('Page.navigate',{'url':f'{self.base}/machine'})
        self.wait("Boolean(document.querySelector('#prebuilt-designs button'))",60)
        self.press('Start from Build beside a river');self.wait(READY,60)
        self.assertEqual(self.js('window.machinePlacements()'),[])
        self.place_river_wheel()
        setup=self.js('window.machinePlacements()')
        base=self.js('window.machineDesign().draft.base')
        initial=self.js("window.machineBodies()['river gate'][1]")
        count=self.js('window.machineDesign().versions.length')
        self.press('Save version');self.wait(f'window.machineDesign().versions.length==={count+1}',10)
        self.click_visible('Run it');self.assert_measured_river_current()
        self.wait(f"window.machineBodies()['river gate'][1]>={initial+.08}",30)
        self.click_visible('Pause');self.click_visible('Set up again');self.wait(READY,60)
        self.assertEqual(self.js('window.machineDesign().draft.base'),base)
        self.assertEqual(self.js('window.machinePlacements()'),setup)
        self.page.send('Page.navigate',{'url':self.js('location.href')});self.wait(READY,60)
        self.assertEqual(self.js('window.machinePlacements()'),setup)
        self.assertEqual(self.js('window.machineDesign().draft.base'),base)
        self.press('Remove your water_wheel 1');self.wait(f'window.machinePlacements().length===0 && {READY}',60)
        self.anonymous_cloud_saved()
        # Hold the real save acknowledgement while the player chooses the
        # older version. Refreshing the options must preserve that choice.
        self.js("""window.riverSaveFetch=window.fetch;window.riverSaveHeld=true;
          window.fetch=async(...args)=>{const response=await riverSaveFetch(...args);
            if(window.riverSaveHeld&&String(args[0]).endsWith('/api/profile')&&JSON.parse(args[1]?.body||'null')?.op==='save')
              await new Promise(resolve=>{window.releaseRiverSave=resolve;});
            return response;};""")
        try:
            self.press('Save version');self.wait(f'window.machineDesign().versions.length==={count+2}',10)
            self.wait('typeof window.releaseRiverSave === "function"',10)
            self.reveal_control("document.getElementById('version-pick')")
            self.js(f"document.getElementById('version-pick').value='{count+1}';document.getElementById('version-pick').dispatchEvent(new Event('change',{{bubbles:true}}))")
        finally:
            self.js('window.riverSaveHeld=false;window.fetch=riverSaveFetch;window.releaseRiverSave?.()')
        self.anonymous_cloud_saved()
        self.wait('!document.getElementById("save-design").disabled',10)
        self.assertEqual(self.js("document.getElementById('version-pick').value"),str(count+1))
        self.press('Restore version');self.wait(f'window.machinePlacements().length===1 && {READY}',60)
        self.assertEqual(self.js('window.machinePlacements()'),setup)
        self.assertEqual(self.js('window.machineDesign().draft.base'),base)
        self.assertEqual(setup[0]['load_part'],'river gate')
        self.press('All designs')
        self.press('Start from Water turns a wheel');self.wait(READY,60)
        self.press('Pick up your water_wheel 1');self.ghost()
        normal=self.js("[Number(document.querySelector('[aria-label=\"wheel radius (m) of your water_wheel 1\"]').value),window.machineGhostState().p.side]")
        self.assertEqual(normal,[.4,'off'],'The new pour example uses its own separate tank')
        self.press('Cancel')

    def test_river_lift_lesson_is_won_by_a_wheel_in_the_measured_current_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-river-lift',width,height,phone=width!=1280)
                self.place_river_wheel()
                initial=self.js("window.machineBodies()['river gate'][1]")
                self.click_visible('Run it');self.assert_measured_river_current()
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Goal at',self.js("document.getElementById('verdict').textContent"))
                self.assertGreaterEqual(self.js("window.machineBodies()['river gate'][1]")-initial,.08)

    def test_tray_cards_live_at_the_add_controls_and_arrows_only_browse(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('gap',width,height,phone=width<1000)
                self.assertTrue(self.js("Boolean(document.getElementById('tray').closest('#scene-tray')) && Boolean(document.getElementById('tray').closest('#control-panel'))"))
                self.assertEqual(self.js("document.querySelectorAll('#tray-head').length"),1)
                self.assertTrue(self.js("document.getElementById('tray-prev').hidden && document.getElementById('tray-next').hidden"))
                self.wait("document.querySelector('#tray img')?.naturalWidth > 0",30)
                self.assertGreaterEqual(self.js("document.querySelector('#tray img').getBoundingClientRect().width"),72)
                self.click_visible('Add a plank'); self.ghost()
                self.assertTrue(self.js("document.getElementById('scene-tray').hidden"))
                self.press('Throw the ghost away')
                self.open('sun',width,height,phone=width<1000)
                before=self.js('window.machinePlacements()')
                self.page.events.clear()
                self.click_visible('Next piece')
                self.assertEqual(self.js("document.getElementById('tray-add').getAttribute('aria-label')"),'Add a power cable')
                self.assertEqual(self.js('window.machinePlacements()'),before)
                opens=[e for e in self.page.events if e['method']=='Network.requestWillBeSent' and e['params']['request'].get('postData') and json.loads(e['params']['request']['postData']).get('op')=='level_open']
                self.assertEqual(opens,[], 'browsing must not rebuild the live setup')
                self.assertIsNone(self.js('window.machineGhostState()'))
                self.click_visible('Next piece')
                self.assertEqual(self.js("document.getElementById('tray-add').getAttribute('aria-label')"),'Add a solar panel')
                self.click_visible('Previous piece')
                self.assertEqual(self.js("document.getElementById('tray-page').textContent"),'2 / 2')
                self.click_visible('Add a power cable'); self.ghost()
                self.assertEqual(self.js("window.machineGhostState().p.piece"),'power_cable')
                self.press('Throw the ghost away')
                self.assertEqual(self.js("document.getElementById('tray-add').getAttribute('aria-label')"),'Add a power cable')
                self.open('free',width,height,phone=width<1000)
                before=self.js('window.machinePlacements()')
                self.click_visible('Next piece')
                self.assertEqual(self.js("document.getElementById('tray-add').getAttribute('aria-label')"),'Add a track')
                self.assertEqual(self.js('window.machinePlacements()'),before)
                self.click_visible('Add a piece')
                self.assertTrue(self.js("document.getElementById('piece-picker').open"))
                self.press('Back to sandbox')
                self.assertEqual(self.js("document.getElementById('tray-add').getAttribute('aria-label')"),'Add a track')

    def test_exhausted_sandbox_battery_card_is_disabled_and_says_none_left(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('free',width,height,phone=width!=1280)
                self.press('All designs')
                self.press('Add New Design'); self.wait(READY,30)
                self.assertEqual(self.js('window.machinePlacements()'),[])
                positions=[(x,z) for z in (-.6,.6) for x in (-.9,-.3,.3,.9)]
                for number,(x,z) in enumerate(positions,1):
                    if number==1:
                        self.press('Add a battery')
                    else:
                        self.click_visible('Add a battery')
                    self.ghost()
                    self.slide(f'along (m) of your battery {number}',x)
                    self.slide(f'across (m) of your battery {number}',z)
                    self.assertTrue(self.ghost()['fits'])
                    self.press('Set it down')
                    self.wait(f'!window.machineGhostState() && window.machinePlacements().length==={number} && {READY}',30)
                self.assertEqual(self.js("document.getElementById('tray-add').getAttribute('aria-label')"),'Add a battery')
                self.assertTrue(self.js("document.getElementById('tray-add').disabled"))
                self.assertEqual(self.js("document.querySelector('#tray-add .tray-left').textContent"),'none left')
                self.assertTrue(self.js("window.machinePlacements().every(p=>p.piece==='battery')"))

    def test_run_places_new_and_adjusted_pieces_once_on_desktop_and_phones(self):
        self.page.send('Network.enable')
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('gap',width,height,phone=width!=1280)
                self.press('Add a plank'); self.ghost()
                self.drag_ghost_to(.3,0,touch=width!=1280)
                self.slide('Cut to length of your plank 1',.7)
                self.ghost()
                self.page.events.clear()
                self.click_visible('Run it')
                self.wait('!window.machineGhostState()',5)
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Goal at',self.js("document.getElementById('verdict').textContent"))
                self.assertEqual(len(self.js('window.machinePlacements()')),1)
                opens=[json.loads(e['params']['request']['postData']) for e in self.page.events if e['method']=='Network.requestWillBeSent' and e['params']['request']['url'].endswith('/api/machine') and e['params']['request'].get('postData') and json.loads(e['params']['request']['postData']).get('op')=='level_open']
                self.assertEqual(len(opens),1,'placing and running uses one setup')
                self.click_visible('Set up again'); self.wait(READY,30)
                self.press('Pick up your plank 1'); self.ghost()
                self.slide('Cut to length of your plank 1',.66)
                # Two clicks while validation is in flight cannot duplicate it.
                self.js("document.getElementById('start').click();document.getElementById('start').click()")
                self.wait('!window.machineGhostState()',5)
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Goal at',self.js("document.getElementById('verdict').textContent"))
                self.assertEqual(len(self.js('window.machinePlacements()')),1)
                self.assertEqual(self.js('window.machinePlacements()[0].length_m'),.66)
                self.click_visible('Set up again'); self.wait(READY,30)
                self.press('Undo'); self.wait(READY,30)
                self.assertEqual(self.js('window.machinePlacements()[0].length_m'),.7)
                # The same shortcut keeps a sandbox draft and saved version.
                self.page.send('Page.navigate',{'url':f'{self.base}/machine'})
                self.wait("document.getElementById('sandbox-screen')?.hidden===false",30)
                self.press('Add New Design'); self.wait(READY,30)
                self.press('Add a plank'); self.ghost()
                if width!=1280: self.click_visible('Help')
                self.click_visible('Run it')
                self.wait("/World (?!0\\.00)[0-9.]+ s/.test(document.getElementById('clock').textContent)",30)
                self.assertIsNone(self.js('window.machineGhostState()'))
                self.assertEqual(len(self.js('window.machineDesign().draft.placements')),1)
                self.click_visible('Pause'); self.click_visible('Set up again'); self.wait(READY,30)
                self.press('Save version')
                self.wait('window.machineDesign().versions.length===1',5)
                self.assertEqual(len(self.js('window.machineDesign().versions[0].draft.placements')),1)

    def test_run_waits_for_latest_placement_check_and_cancelling_cancels_the_run(self):
        self.open('laser')
        self.press('Add a mirror'); self.ghost()
        self.slide('x of your mirror 1',-.35); self.slide('z of your mirror 1',0)
        self.assertTrue(self.ghost()['fits'])
        # Delay a real server answer so the ghost stays blue while its
        # latest position is inside the wall. The queued answer must win.
        self.js("""window.runOriginalFetch=window.fetch; window.runHoldCheck=true;
            window.runCheckGate=new Promise(resolve=>window.releaseRunCheck=resolve);
            window.fetch=async (...args)=>{const op=args[1]?.body && JSON.parse(args[1].body).op;
              const hold=op==='level_ghost' && window.runHoldCheck;
              if(hold)window.runHoldCheck=false;
              const response=await window.runOriginalFetch(...args);
              if(hold){await window.runCheckGate;window.runCheckResolved=true;} return response;};""")
        self.slide('z of your mirror 1',.1)
        self.slide('z of your mirror 1',.5)
        self.press('Run it'); self.js('window.releaseRunCheck()')
        self.wait("/120 mm into wall/.test(document.getElementById('verdict').textContent)",5)
        self.assertFalse(self.ghost()['fits'])
        self.assertEqual(self.js('window.machinePlacements()'),[])
        self.assertTrue(self.js(READY))
        self.page.send('Network.enable'); self.page.events.clear()
        self.js("window.runCheckResolved=false;window.runHoldCheck=true;window.runCheckGate=new Promise(resolve=>window.releaseRunCheck=resolve)")
        self.slide('z of your mirror 1',0)
        self.press('Run it'); self.press('Cancel'); self.js('window.releaseRunCheck()')
        self.wait('window.runCheckResolved',5)
        self.page.evaluate('new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)))',await_promise=True)
        self.wait("document.getElementById('ghost-bar').hidden",5)
        self.assertEqual(self.js('window.machinePlacements()'),[])
        self.assertTrue(self.js(READY))
        opens=[e for e in self.page.events if e['method']=='Network.requestWillBeSent' and e['params']['request']['url'].endswith('/api/machine') and e['params']['request'].get('postData') and json.loads(e['params']['request']['postData']).get('op')=='level_open']
        self.assertEqual(opens,[],'cancelling the pending piece cannot start another setup')
        self.js('window.fetch=window.runOriginalFetch')

    def test_phone_tabs_scroll_independently_keep_run_visible_and_survive_rotation(self):
        for width,height in ((390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('free',width,height,phone=True)
                # Each viewport gets an empty design, regardless of the
                # preceding test's saved build or this test's first viewport.
                self.press('All designs')
                self.press('Add New Design'); self.wait(READY,30)
                self.assertEqual(self.js('window.machinePlacements()'),[])
                self.click_visible('Design')
                self.assertTrue(self.js("document.getElementById('control-panel').hidden && document.getElementById('phone-help-panel').hidden"))
                pane=self.js("document.getElementById('phone-design-panel').getBoundingClientRect().toJSON()")
                self.assertGreater(pane['height'],300 if width==390 else 230)
                # Scroll the content to its end: the fixed toolbar and scene
                # cannot be covered by settings or by a sticky controls box.
                geometry=self.js("document.getElementById('phone-toolbar').getBoundingClientRect().toJSON()")
                self.page.send('Input.dispatchMouseEvent',{'type':'mouseWheel','x':pane['x']+pane['width']/2,'y':pane['y']+pane['height']/2,'deltaX':0,'deltaY':10000})
                self.wait("document.getElementById('phone-design-panel').scrollTop>0",5)
                self.assertEqual(self.js("document.querySelector('aside').scrollTop"),0)
                self.assertEqual(self.js("document.getElementById('phone-toolbar').getBoundingClientRect().toJSON()"),geometry)
                self.assertLessEqual(self.js("document.getElementById('engine-assumptions').getBoundingClientRect().bottom"),pane['bottom'])
                self.click_visible('Help')
                self.js("document.getElementById('message').value='Keep this draft while I adjust the machine'")
                self.click_visible('Run it')
                self.wait("/World (?!0\\.00)[0-9.]+ s/.test(document.getElementById('clock').textContent)",30)
                self.click_visible('Pause'); self.click_visible('Set up again'); self.wait(READY,30)
                self.assertEqual(self.js("document.getElementById('phone-help-tab').getAttribute('aria-selected')"),'true')
                self.click_visible('Design')
                self.js("document.getElementById('save-design').scrollIntoView({block:'center'})")
                self.click_visible('Save version')
                self.wait("/saved/.test(document.getElementById('design-status').textContent)",5)
                self.click_visible('Controls'); self.click_visible('Add a piece')
                self.press('Add a plank'); self.ghost()
                self.assertEqual(self.js("document.getElementById('phone-controls-tab').getAttribute('aria-selected')"),'true')

                before=self.ghost()['p']
                self.click_visible('Controls')
                for key,code in [('ArrowRight',39),('ArrowLeft',37)]:
                    for kind in ('keyDown','keyUp'):
                        self.page.send('Input.dispatchKeyEvent',{'type':kind,'key':key,'code':key,'windowsVirtualKeyCode':code})
                    self.assertEqual(self.ghost()['p'],before,'tab navigation cannot nudge the selected piece')
                self.assertEqual(self.js("document.activeElement.id"),'phone-controls-tab')
                self.click_visible('✓ Set down'); self.wait(READY,30)
                self.click_visible('Design')
                self.press('Pick up your plank 1'); self.ghost()
                self.assertEqual(self.js("document.getElementById('phone-controls-tab').getAttribute('aria-selected')"),'true')
                self.click_visible('Throw the ghost away'); self.wait('!window.machineGhostState()',5)
                self.click_visible('Help')
                self.page.send('Emulation.setDeviceMetricsOverride',{'width':1280,'height':860,'deviceScaleFactor':1,'mobile':False})
                self.wait("!document.body.classList.contains('phone-panels')",5)
                self.assertTrue(self.js("document.getElementById('phone-toolbar').hidden===false && document.getElementById('control-panel').hidden && document.getElementById('phone-design-panel').hidden && !document.getElementById('phone-help-panel').hidden"))
                self.assertEqual(self.js("document.querySelectorAll('#start').length"),1)
                self.assertEqual(self.js("document.getElementById('start').parentElement.id"),'phone-runbar')
                self.page.send('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':True})
                self.wait("document.body.classList.contains('phone-panels')",5)
                self.assertEqual(self.js("document.getElementById('phone-help-tab').getAttribute('aria-selected')"),'true')
                self.assertEqual(self.js("document.getElementById('message').value"),'Keep this draft while I adjust the machine')
                # Keyboard navigation moves both the selected tab and focus.
                self.click_visible('Help')
                for kind in ('keyDown','keyUp'):
                    self.page.send('Input.dispatchKeyEvent',{'type':kind,'key':'Home','code':'Home','windowsVirtualKeyCode':36})
                self.assertEqual(self.js("document.activeElement.id"),'phone-controls-tab')
                self.assertEqual(self.js("document.getElementById('phone-controls-tab').getAttribute('aria-selected')"),'true')


    def test_shared_tabs_collapse_and_run_toolbar_work_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('gap',width,height,phone=width!=1280)
                self.assertFalse(self.js("document.getElementById('phone-toolbar').hidden"))
                self.assertEqual(self.js("document.getElementById('start').parentElement.id"),'phone-runbar')
                self.assertEqual(self.js("document.getElementById('reset').parentElement.id"),'phone-runbar')
                self.assertEqual(self.js("document.getElementById('phone-design-tab').textContent"),'Level')
                for label,pane in [('Controls','control-panel'),('Level','phone-design-panel'),('Help','phone-help-panel')]:
                    self.click_visible(label)
                    self.assertEqual(self.js("['control-panel','phone-design-panel','phone-help-panel'].filter(id=>!document.getElementById(id).hidden)"),[pane])
                    self.assertTrue(self.js("(()=>{const r=document.getElementById('scene-goal').getBoundingClientRect();return r.height>0&&r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight;})()"))
                before=self.js('machinePlacements()')
                self.click_visible('Collapse controls')
                self.assertTrue(self.js("['control-panel','phone-design-panel','phone-help-panel'].every(id=>document.getElementById(id).hidden)"))
                self.click_visible('Run it')
                self.wait("/World (?!0\\.00)[0-9.]+ s/.test(document.getElementById('clock').textContent)",30)
                self.click_visible('Pause');self.click_visible('Set up again');self.wait(READY,30)
                self.click_visible('Expand controls')
                self.assertFalse(self.js("document.getElementById('phone-help-panel').hidden"))
                self.assertEqual(self.js('machinePlacements()'),before)

    def test_active_piece_slider_exact_value_and_precision_disclosure_agree(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('gap',width,height,phone=width!=1280)
                self.press('Add a plank');self.ghost()
                self.assertFalse(self.js("document.getElementById('precision-controls').open"))
                self.assertTrue(self.js("Boolean(document.querySelector('#precision-controls [aria-label=\"Cut to length of your plank 1\"]'))"))
                self.assertTrue(self.js("Boolean(document.getElementById('precision-controls').closest('#control-panel'))"))
                self.assertFalse(self.js("Boolean(document.querySelector('#phone-design-panel [aria-label=\"Cut to length of your plank 1\"]'))"))
                self.reveal_control("""document.querySelector('[aria-label="Exact Cut to length"]')""")
                x,y=self.js("""(()=>{const r=document.querySelector('[aria-label="Exact Cut to length"]').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];})()""")
                self.mouse('mousePressed',x,y);self.mouse('mouseReleased',x,y)
                for kind in ('keyDown','keyUp'):
                    self.page.send('Input.dispatchKeyEvent',{'type':kind,'key':'a','code':'KeyA','windowsVirtualKeyCode':65,'modifiers':2})
                self.page.send('Input.insertText',{'text':'0.66'})
                self.assertEqual(self.ghost()['p']['length_m'],.66)
                self.assertEqual(self.js("Number(document.querySelector('[aria-label=\"Its Cut to length\"]').value)"),.66)
                for invalid in ('',99,.661):
                    self.slide('Exact Cut to length',invalid)
                    self.assertEqual(self.ghost()['p']['length_m'],.66,'Invalid numeric entry cannot change the physical setup')
                    self.assertEqual(self.js("Number(document.querySelector('[aria-label=\"Exact Cut to length\"]').value)"),.66)
                self.slide('Its Cut to length',.7)
                self.assertEqual(self.ghost()['p']['length_m'],.7)
                self.assertEqual(self.js("Number(document.querySelector('[aria-label=\"Exact Cut to length\"]').value)"),.7)
                geometry=self.js("(()=>{const input=document.querySelector('[aria-label=\"Its Cut to length\"]'),row=input.closest('.knob-row'),r=row.getBoundingClientRect(),s=input.getBoundingClientRect(),n=document.querySelector('[aria-label=\"Exact Cut to length\"]').getBoundingClientRect();return {row:r.toJSON(),slider:s.toJSON(),number:n.toJSON(),uncovered:input.contains(document.elementFromPoint(s.x+s.width/2,s.y+s.height/2))};})()")
                self.assertGreaterEqual(geometry['slider']['width'],geometry['row']['width']*.6,geometry)
                self.assertGreaterEqual(geometry['number']['height'],44,geometry)
                self.assertTrue(geometry['uncovered'],geometry)
                # Probe inside the buttons' 9px rounded corners; the full
                # rectangular bounds must still clear the scroll edge/footer.
                for label in ('Move it away from you','Move it left','Move it right','Move it toward you'):
                    self.reveal_control(self.button_expression(label))
                    touch=self.js(f"""(()=>{{const el={self.button_expression(label)},r=el.getBoundingClientRect(),fields=el.closest('.ghost-fields').getBoundingClientRect(),actions=document.querySelector('#ghost-bar .actions').getBoundingClientRect();
                      return {{h:r.height,w:r.width,inside:r.top>=fields.top&&r.bottom<=fields.bottom,
                        overlaps:r.left<actions.right&&r.right>actions.left&&r.top<actions.bottom&&r.bottom>actions.top,
                        corners:[[r.left+8,r.top+8],[r.right-8,r.top+8],[r.left+8,r.bottom-8],[r.right-8,r.bottom-8]].every(([x,y])=>el.contains(document.elementFromPoint(x,y)))}};}})()""")
                    self.assertGreaterEqual(touch['h'],44,(label,touch));self.assertGreaterEqual(touch['w'],44,(label,touch))
                    self.assertTrue(touch['inside'] and touch['corners'] and not touch['overlaps'],(label,touch))
                self.slide('Cut to length of your plank 1',.68)
                self.assertTrue(self.js("document.getElementById('precision-controls').open"))
                self.assertEqual(self.ghost()['p']['length_m'],.68)
                self.assertEqual(self.js("Number(document.querySelector('[aria-label=\"Exact Cut to length\"]').value)"),.68)
                self.press('Throw the ghost away')

    def test_sandbox_gallery_tabs_create_then_rename_without_name_form(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.anonymous_levels(width=width,height=height)
                self.press('Sandbox: build anything');self.wait("document.getElementById('sandbox-screen').hidden===false",10)
                self.assertIsNone(self.js("document.getElementById('new-design-name')"))
                self.assertEqual(self.js("document.getElementById('design-tab-owned').getAttribute('aria-selected')"),'true')
                self.assertFalse(self.js("document.getElementById('design-panel-owned').hidden"))
                self.assertTrue(self.js("document.getElementById('design-panel-examples').hidden"))
                self.click_visible('Examples')
                self.assertTrue(self.js("document.getElementById('design-panel-owned').hidden"))
                self.assertFalse(self.js("document.getElementById('design-panel-examples').hidden"))
                self.assertEqual(self.js("document.querySelectorAll('#prebuilt-designs button').length"),self.template_count)
                self.click_visible('Your designs')
                before=self.js('machineSave().players[machineSave().current].sandbox.items.length')
                self.click_visible('Add New Design');self.wait(READY,90)
                self.assertEqual(self.js('machineDesign().name'),'Untitled design')
                self.assertEqual(self.js('machinePlacements()'),[])
                self.assertEqual(self.js("document.getElementById('phone-design-tab').textContent"),'Design')
                self.reveal_control("document.getElementById('design-name')")
                name=f'Gallery {width} by {height}'
                self.js(f"(()=>{{const el=document.getElementById('design-name');el.value={json.dumps(name)};el.dispatchEvent(new Event('change',{{bubbles:true}}));}})()")
                self.anonymous_cloud_saved()
                self.click_summary('#design-versions > summary')
                self.assertTrue(self.js("document.getElementById('design-versions').open"))
                self.click_summary('#design-versions > summary')
                self.assertFalse(self.js("document.getElementById('design-versions').open"))
                self.press('All designs')
                self.assertEqual(self.js('machineSave().players[machineSave().current].sandbox.items.length'),before+1)
                self.assertTrue(self.js(f"Boolean(document.querySelector('#saved-designs button[aria-label={json.dumps('Open design '+name)}]'))"))
                self.assertLessEqual(self.js('document.body.scrollWidth'),width)

    def test_level_details_and_more_are_opt_in_without_starting_a_world(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.anonymous_levels(width=width,height=height)
                self.assertEqual(self.js("[...document.querySelectorAll('#levels-screen .level-card-title')].slice(5,7).map(e=>e.textContent)"),
                                 ['6. Bounce to the target','7. Bounce the beam'])
                self.assertFalse(self.js("document.getElementById('level-more').open"))
                self.assertEqual(self.js("document.querySelectorAll('#levels-screen .level-card-details').length"),self.level_count)
                self.assertTrue(self.js("[...document.querySelectorAll('#levels-screen .level-card-details')].every(d=>!d.open)"))
                self.assertFalse(self.js("document.getElementById('levels-screen').innerText.includes('Energy par:')"))
                self.assertFalse(self.js("document.getElementById('levels-screen').innerText.includes('New challenge')"))
                before=self.js('location.href')
                self.page.events.clear()
                self.click_summary('#levels-screen .level-card-details summary')
                self.assertTrue(self.js("document.querySelector('#levels-screen .level-card-details').open"))
                self.assertRegex(self.js("document.querySelector('#levels-screen .level-card-details').innerText"),'Energy par:|Best win:')
                self.assertEqual(self.js('location.href'),before)
                self.click_summary('#level-more > summary')
                self.assertTrue(self.js("document.getElementById('level-more').open"))
                self.assertTrue(self.js("Boolean(document.getElementById('visitor-return-link').closest('#level-more'))"))
                self.assertTrue(self.js("Boolean(document.querySelector('#level-more #challenge-family'))"))
                requests=[e['params']['request'] for e in self.page.events if e['method']=='Network.requestWillBeSent']
                opens=[r for r in requests if r['url'].endswith('/api/machine') and r.get('postData') and json.loads(r['postData']).get('op') in ('open','level_open')]
                self.assertEqual(opens,[],'Reading details and save tools cannot initialize a machine')
    def test_laser_stays_visible_while_editing_and_lens_focus_keeps_its_context_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390),(320,568)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-lens',width,height,phone=width!=1280)
                self.wait('window.machineLaserPreviewState()?.visible && !window.machineLaserPreviewState().pending',30)
                self.press('Add a lens'); self.ghost()
                self.wait('!window.machineLaserPreviewState().pending',30)
                self.assertTrue(self.js('window.machineLaserPreviewState().visible'))
                self.assertEqual(self.js('window.machineLaserPreviewState().error'),'','the default lens must mount, not retain a bare-scene beam after an error')
                self.assertTrue(self.js("(() => {const e=document.getElementById('lens-grip'),r=e.getBoundingClientRect();return !e.hidden && r.width>=44 && r.height>=44 && getComputedStyle(e).pointerEvents==='none';})()"))
                self.click_visible('Focus selected piece')
                self.assertTrue(self.js("(() => {const el=document.getElementById('focus-piece'),r=el.getBoundingClientRect(),p=el.closest('.ghost-fields').getBoundingClientRect();return r.top>=p.top && r.bottom<=p.bottom;})()"),'Focus must have its complete touch target inside the scrollable inspector')
                if width<=599:
                    self.assertTrue(self.js("document.getElementById('view').getBoundingClientRect().bottom<=document.getElementById('phone-toolbar').getBoundingClientRect().top"),'the smaller scene cannot overflow behind controls')
                self.wait('window.machineCamera().settled',30)
                for anchor in ([-.8,.575,0],[.29,.575,0]):
                    point=self.screen_point(anchor)
                    rect=self.js("(() => {const r=document.querySelector('#view canvas').getBoundingClientRect();return {l:r.left,r:r.right,t:r.top,b:r.bottom};})()")
                    self.assertTrue(rect['l']<=point[0]<=rect['r'] and rect['t']<=point[1]<=rect['b'],(anchor,point,rect))
                self.click_visible('Whole machine'); self.wait('window.machineCamera().settled',30)
                # Ordinary exact controls: no scene/test-hook placement shortcut.
                self.slide('Position along (m) of your lens 1',.1)
                self.slide('Position across (m) of your lens 1',0)
                self.slide('Diameter (m) of your lens 1',.12)
                self.ghost()
                self.wait('!window.machineLaserPreviewState().pending && window.machineLaserPreviewState().photocells[0]?.power_w>2',30)
                self.assertIn('7.31 W',self.js("document.getElementById('laser-preview-status').textContent"))
                self.slide('Position across (m) of your lens 1',.3)
                self.assertTrue(self.js('window.machineLaserPreviewState().visible'),'previous trace stays visible while the new one is requested')
                self.ghost();self.wait('!window.machineLaserPreviewState().pending && window.machineLaserPreviewState().photocells[0]?.power_w<2',30)
                self.assertEqual(self.js('JSON.parse(window.machineLaserPreviewState().stamp).placements[0].z_m'),.3)
                self.assertTrue(self.js('Number.isFinite(window.machineCamera().distance)'))
                self.slide('Position across (m) of your lens 1',0);self.ghost()
                self.press('Set it down');self.wait(READY,30)
                self.press('Run it');self.wait("/World (?!0.00)\\d/.test(document.getElementById('clock').textContent) && !window.machineLaserPreviewState().visible",30)
                self.assertFalse(self.js('window.machineLaserPreviewState().visible'),'Run shows actual native light instead of a setup prediction')
                self.press('Set up again');self.wait(READY,30)
                self.wait('window.machineLaserPreviewState().visible',30)
                for level in ('easy-mirror','laser'):
                    self.open(level,width,height,phone=width!=1280)
                    self.wait('window.machineLaserPreviewState().visible && !window.machineLaserPreviewState().pending',30)
                    self.press('Add a mirror');self.ghost()
                    self.click_visible('Focus selected piece');self.wait('window.machineCamera().settled',30)
                    self.assertTrue(self.js('Number.isFinite(window.machineCamera().distance)'))
                    if level=='easy-mirror':
                        for anchor in ([-.8,.575,0],[.5,.575,1]):
                            point=self.screen_point(anchor)
                            rect=self.js("(() => {const r=document.querySelector('#view canvas').getBoundingClientRect();return {l:r.left,r:r.right,t:r.top,b:r.bottom};})()")
                            self.assertTrue(rect['l']<=point[0]<=rect['r'] and rect['t']<=point[1]<=rect['b'],(level,anchor,point,rect))
                self.open('gap',width,height,phone=width!=1280)
                self.assertFalse(self.js('window.machineLaserPreviewState().visible'))

    def test_flow_preview_can_be_paused_scrubbed_and_edited_without_running_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.page.send('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':width!=1280})
                for template,channel in [('Build your first circuit','wires'),('A tank that runs dry','water')]:
                    self.page.send('Page.navigate',{'url':f'{self.base}/machine'})
                    self.wait("document.getElementById('sandbox-screen')?.hidden===false",30)
                    self.press('Start from '+template)
                    self.wait("window.machineFlowPreviewState()?.frames>2 && !document.getElementById('flow-preview').hidden",60)
                    setup=self.js('window.machinePlacements()')
                    # Open the actual disclosure and use real pointer clicks.
                    self.click_summary('#flow-preview > summary')
                    self.reveal_control("document.getElementById('flow-play')")
                    self.wait("document.getElementById('flow-play').getBoundingClientRect().bottom<=innerHeight",5)
                    self.click_visible('Pause preview')
                    self.slide('Preview time',1)
                    self.wait('!window.machineFlowPreviewState().playing && window.machineFlowPreviewState().time===1 && window.machineFlowPreviewState().index>=0',5)
                    state=self.js('window.machineFlowPreviewState()')
                    if channel=='wires':
                        self.assertTrue(any(w['value']>.24 for w in state['sample']['wires']))
                        self.assertGreater(state['drawn']['arrows'],0)
                        self.assertEqual(state['drawn']['bulbs'],1)
                        self.assertIn('current preview',self.js("document.getElementById('preview-legend').textContent"))
                    else:
                        self.assertTrue(state['sample']['water']['xyz_mm'])
                        self.assertGreater(state['drawn']['waterPoints'],0)
                        self.slide('Preview time',6)
                        self.wait('window.machineFlowPreviewState().time===6 && window.machineFlowPreviewState().index>=0',5)
                        self.assertEqual(self.js('window.machineFlowPreviewState().sample.water.xyz_mm'),[])
                        self.assertGreater(self.js('window.machineFlowPreviewState().sample.surface.wet_cells'),0)
                    self.assertEqual(self.js('window.machinePlacements()'),setup)
                    self.assertTrue(self.js(READY),'preview playback never advances the live world')
                    self.click_visible('Play preview')
                    self.wait('window.machineFlowPreviewState().playing',5)
                    # A tall preview module must still leave Save accessible.
                    self.reveal_control("document.getElementById('save-design')")
                    self.js("document.getElementById('save-design').scrollIntoView({block:'center'})")
                    self.click_visible('Save version')
                    self.wait("/saved/.test(document.getElementById('design-status').textContent)",5)
                    if channel=='water':
                        self.slide('Adjust a piece','0'); self.ghost()
                        self.slide('tap opening (%) of your water_tank 1',0); self.ghost()
                        self.wait('window.machineFlowPreviewState()?.frames>2',60)
                        self.slide('Preview time',1); self.wait('window.machineFlowPreviewState().time===1 && window.machineFlowPreviewState().index>=0',5)
                        self.assertEqual(self.js('window.machineFlowPreviewState().sample.water.xyz_mm'),[])
                        self.assertIn('Water valves closed',self.js("document.getElementById('flow-readings').textContent"))
                        self.press('Cancel'); self.wait('!window.machineGhostState()',5)
                    self.reveal_control("document.getElementById('designs-open')")
                    self.js("document.getElementById('designs-open').scrollIntoView({block:'center'})")
                    self.click_visible('All designs')
                    self.wait("document.getElementById('sandbox-screen')?.hidden===false",5)
                self.open('easy-mirror',width,height,phone=width!=1280)
                self.press('Add a mirror'); self.ghost()
                self.wait('window.machineFlowPreviewState()?.frames>2',60)
                self.wait('window.machineFlowPreviewState()?.drawn?.lightSegments>0',5)
                self.assertIn('light preview',self.js("document.getElementById('preview-legend').textContent"))
                self.assertTrue(self.js(READY))

    def test_tackle_rope_and_crate_reopen_adjustments_without_running_on_desktop_and_phones(self):
        for width, height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('tackle', width, height, phone=width != 1280)
                self.press('Add a block and tackle'); self.ghost()
                for label, value in [('counterweight (kg)',4.7),('pulleys',3),('hangs at x',-.5),('hung at height',1.75)]:
                    self.slide(f'{label} of your tackle 1', value)
                self.ghost(); self.press('Set it down'); self.wait(READY,60)
                setup = self.js('window.machinePlacements()')
                self.wait('window.machineCamera().settled', 30)
                for point in ((-.5,1.88,0),(.4,.06,0)):
                    x,y = self.screen_point(point)
                    self.assertTrue(self.js(f"document.elementFromPoint({x},{y}).tagName==='CANVAS'"), (point,x,y))
                    self.mouse('mousePressed',x,y); self.mouse('mouseReleased',x,y)
                    self.wait('Boolean(window.machineGhostState())',5)
                    self.assertEqual(self.ghost()['p'], setup[0])
                    self.assertTrue(self.js(READY), 'selecting a device never starts the live simulation')
                    for label in ('Run it','Set up again','Turn the view left','Zoom in','✓ Set down','Throw the ghost away'):
                        self.reveal_control(f"[...document.querySelectorAll('button')].find(b=>(b.getAttribute('aria-label')||b.textContent).trim()==={json.dumps(label)})")
                        target = self.js(f"(() => {{const b=[...document.querySelectorAll('#control-panel button,#phone-runbar button')].find(b=>(b.getAttribute('aria-label')||b.textContent).trim()==={json.dumps(label)}),r=b?.getBoundingClientRect();return r?{{visible:r.x>=0 && r.right<=innerWidth && r.y>=0 && r.bottom<=innerHeight,uncovered:b.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)),h:r.height,w:r.width}}:null;}})()")
                        self.assertIsNotNone(target,label)
                        self.assertTrue(target['visible'] and target['uncovered'],(label,target))
                        self.assertGreaterEqual(target['h'],44); self.assertGreaterEqual(target['w'],44)
                    camera = self.js('window.machineCamera().azimuth')
                    self.click_visible('Turn the view left')
                    self.assertAlmostEqual(self.js('window.machineCamera().azimuth'), camera-.2)
                    self.assertEqual(self.ghost()['p'],setup[0], 'view controls do not move the piece')
                    self.click_visible('Turn the view right')
                    if self.js("document.getElementById('phone-tools').open"):
                        self.click_summary('#phone-tools > summary')
                    self.press('Cancel'); self.wait('!window.machineGhostState()',5)
                self.press('Run it'); self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Goal at',self.js("document.getElementById('verdict').textContent"))
                # The selector remains reachable even when the win card covers geometry.
                self.slide('Adjust a piece','0'); self.ghost(); self.wait(READY,30)
                self.assertEqual(self.ghost()['p'],setup[0])
                self.press('Change its pulleys'); self.slide('Its pulleys',2); self.ghost()
                self.click_visible('✓ Set down'); self.wait(READY,30)
                self.assertEqual(self.js('window.machinePlacements()[0].ratio'),2)
                self.assertTrue(self.js(READY))

    def test_cable_power_and_load_estimates_update_while_editing_and_running(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('sun',width,height,phone=width!=1280)
                self.press('Add a solar panel');self.ghost()
                for key,value in [('x',1),('z',.4),('height',.6),('turn',-45),('tip',75)]:
                    self.slide(f'{key} of your solar 1',value)
                self.assertTrue(self.ghost()['fits'])
                self.press('Set it down');self.wait(READY,60)
                try:self.wait("/50\\.0 W charging/.test(document.getElementById('power-labels').textContent)",20)
                except AssertionError:
                    print('POWER_SETUP',self.js("({placements:machinePlacements(),power:document.getElementById('power-labels').textContent,clock:document.getElementById('clock').textContent,ghost:machineGhostState()})"),flush=True)
                    raise
                if not self.js("document.getElementById('wire-mode').getAttribute('aria-pressed')==='true'"):
                    self.click_visible('Connect wires')
                self.click_visible('Power output of your solar 1');self.click_visible('Power input of winch')
                self.wait(f'window.machinePlacements().length===2 && {READY}',60)
                self.wait('window.machineFlowPreviewState()?.sample?.wires?.some(w=>w.unit===\'W\'&&w.value>40)',60)
                self.wait("window.machinePowerFeedbackState().labels.some(r=>r.device==='winch motor'&&r.text.includes('14.3 W')&&r.text.includes('3.1 N·m'))",10)
                def peak():return self.js("Math.max(...window.machineFlowPreviewState().sample.wires.filter(w=>w.unit==='W').map(w=>Math.abs(w.value)))")
                self.assertGreater(peak(),40)
                self.assertGreater(self.js('window.machinePowerFeedbackState().dots'),0)
                self.slide('Adjust a piece','0');self.ghost()
                self.slide('tip of your solar 1',0);self.ghost()
                self.wait('window.machineFlowPreviewState()?.sample?.wires?.some(w=>w.unit===\'W\'&&w.value>0&&w.value<15)',60)
                self.assertLess(peak(),15)
                self.press('Set it down');self.wait(READY,60)
                self.slide('Speed of world time',.25)
                self.click_visible('Run it')
                self.wait("window.machinePowerFeedbackState().labels.some(r=>r.wire&&/ W/.test(r.text)&&!r.text.includes('Preview')&&!r.text.includes('Updating')) && window.machinePowerFeedbackState().dots>0",20)
                geometry=self.js("""(() => {const view=document.getElementById('view').getBoundingClientRect(),run=document.getElementById('start').getBoundingClientRect();
                    const rows=[...document.querySelectorAll('#power-feedback-labels section')].filter(e=>!e.hidden).map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,w:r.width,h:r.height}});
                    return {rows,inside:rows.every(r=>r.x>=view.x&&r.y>=view.y&&r.right<=view.right&&r.bottom<=view.bottom),
                      clear:rows.every(r=>!(r.x<run.right&&r.right>run.x&&r.y<run.bottom&&r.bottom>run.y))};})()""")
                self.assertTrue(geometry['rows']);self.assertTrue(geometry['inside'],geometry);self.assertTrue(geometry['clear'],geometry)
                self.click_visible('Pause')

    def test_solar_meters_and_explicit_winch_cable_work_on_desktop_and_phones(self):
        for width, height in ((1280, 860), (390, 844), (844, 390)):
            with self.subTest(viewport=(width, height)):
                self.open('sun', width, height, phone=width != 1280)
                self.press('Add a solar panel'); self.ghost()
                for label, value in [('x', 1), ('z', .4), ('height', .6), ('turn', -45), ('tip', 75)]:
                    self.slide(f'{label} of your solar 1', value)
                self.assertTrue(self.ghost()['fits'])
                self.press('Set it down'); self.wait(f'!window.machineGhostState() && {READY}', 60)
                self.wait("/50\\.0 W charging/.test(document.getElementById('power-labels').textContent) && /250 W sunlight/.test(document.getElementById('power-labels').textContent)", 20)
                self.assertIn('0.0 J stored', self.js("document.getElementById('power-labels').textContent"))
                self.assertIn('Output not wired', self.js("document.getElementById('power-labels').textContent"))
                self.assert_power_layout()
                self.click_visible('Power output of your solar 1')
                self.wait("document.querySelector('[aria-label=\"Power output of your solar 1\"]').getAttribute('aria-pressed') === 'true'", 5)
                self.assert_power_layout()
                self.click_visible('Power input of winch')
                self.wait(f'window.machinePlacements().length === 2 && {READY}', 60)
                cable = self.js('window.machinePlacements()[1]')
                self.assertEqual(cable, {'piece':'power_cable','a_port':'your solar 1:power','b_port':'winch:power'})
                self.assertIn('Cable connected', self.js("document.getElementById('power-labels').textContent"))
                self.assert_power_layout()
                self.click_visible('Run it')
                self.wait("!document.getElementById('level-done').hidden", 30)
                self.assertIn('Goal', self.js("document.getElementById('level-done').textContent"))

    def test_chain_trigger_contact_and_power_loop_are_inspectable_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('chain',width,height,phone=width!=1280)
                before=self.js('machineCamera().distance')
                self.click_visible('Collapse controls')
                self.click_visible('Inspect switch')
                self.assertFalse(self.js("document.body.classList.contains('panel-collapsed')"),'Inspection reveals its readings module')
                self.assertEqual(self.js('machineContactCircuitState().inspected'),'firing circuit')
                self.assertLess(self.js('machineCamera().distance'),before)
                self.assertTrue(self.js(READY),'Inspecting must not run or actuate the machine')
                state=self.js('machineContactCircuitState()')
                self.assertEqual([w['leg'] for w in state['wires']],['supply','switched','return'])
                self.assertEqual([w['color'] for w in state['wires']],[0xf19076,0xf19076,0x83bbff])
                self.assertFalse(state['circuits'][0]['reading']['closed'])
                self.assertIn('Pressure switch: open',self.js("document.getElementById('contact-circuit-readings').textContent"))
                self.assertTrue(self.js("[...document.querySelectorAll('#contact-switch-labels span')].every(e=>e.getClientRects().length&&e.offsetWidth>40)"))
                self.assertFalse(self.js('machineFlowPreviewState()?.visible===true'),'Inspection shows the current physical contacts')
                self.click_visible('Whole machine');self.assertIsNone(self.js('machineContactCircuitState().inspected'))
                self.press('Add a ramp');self.ghost()
                for label,value in [('Top at x',-.75),('Top height',.6),('Run',.7),('Foot height',.3),('z',0)]:
                    self.slide(f'{label} of your ramp 1',value)
                self.ghost();self.press('Set it down');self.wait(READY,60)
                self.wait('machineFlowPreviewState()?.frames>2',30)
                self.slide('Preview time',1)
                self.wait('machineFlowPreviewState()?.sample?.contact_circuits?.[0]?.closed===true',5)
                self.assertEqual(self.js('machineFlowPreviewState().sample.wires.length'),3)
                self.assertGreater(self.js('machineFlowPreviewState().sample.contact_circuits[0].coil_w'),0)
                self.click_visible('Inspect switch')
                self.assertIn('Pressure switch: open',self.js("document.getElementById('contact-circuit-readings').textContent"),'Future current must not be presented as live')
                self.click_visible('Run it');self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Goal',self.js("document.getElementById('level-done').textContent"))
                self.assertTrue(self.js("document.getElementById('control-panel').contains(document.getElementById('level-done'))"),'The win card must not cover the inspected contacts')
                self.assertGreater(self.js("document.getElementById('level-done').getBoundingClientRect().height"),150,'The result card must retain its natural height inside the scroll pane')
                self.click_visible('Play this level again');self.wait(READY,60)
                self.click_visible('Inspect switch');self.click_visible('Run it');self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Pressure switch: closed',self.js("document.getElementById('contact-circuit-readings').textContent"))
                state=self.js('machineContactCircuitState()')
                self.assertEqual(state['inspected'],'firing circuit','Run must keep the switch close-up so its motion is visible')
                self.assertGreater(state['circuits'][0]['reading']['coil_w'],0)
                self.assertTrue(all(w['color']==0xffd34d for w in state['wires']))
                self.assertTrue(all(o['color']==0x5fe08f for o in state['outlines']))
                self.click_visible('Whole machine')
                self.assertTrue(self.js("document.getElementById('view').contains(document.getElementById('level-done'))"))
                self.open('easy-solar',width,height,phone=width!=1280)
                self.assertTrue(self.js("document.getElementById('inspect-switch').hidden && document.getElementById('contact-switch-labels').hidden"),'Contact inspection does not leak onto other lessons')

    def test_solar_wall_shadow_and_explicit_storage_cable_on_desktop_and_phones(self):
        def assert_wall_in_view():
            self.wait('machineCamera().settled',30)
            rect=self.js("(()=>{const r=document.querySelector('#view canvas').getBoundingClientRect();return [r.left,r.top,r.right,r.bottom];})()")
            for x in (-1,1):
                for y in (0,1.6):
                    for z in (-.96,-.84):
                        px,py=self.screen_point([x,y,z])
                        self.assertTrue(rect[0]<=px<=rect[2] and rect[1]<=py<=rect[3],(rect,(px,py),'Full wall must fit, not only its center'))
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-solar',width,height,phone=width<1000)
                self.press('Add a solar panel');self.ghost()
                for label,value in [('Position along (m)',0),('Position across (m)',0),('Post height (m)',.5),('turn',-90),('tip',70)]:
                    self.slide(f'{label} of your solar 1',value)
                self.assertTrue(self.ghost()['fits'])
                self.press('Set it down');self.wait(f'!machineGhostState() && {READY}',60)
                assert_wall_in_view()
                self.wait("document.getElementById('power-labels').textContent.includes('In shadow')",20)
                self.assertIn('Output not wired',self.js("document.getElementById('power-labels').textContent"))
                self.assertIn('0.0 W charging',self.js("document.getElementById('power-labels').textContent"))
                self.click_visible('Power output of your solar 1');self.assert_power_layout()
                self.click_visible('Power input of battery');self.wait(f'machinePlacements().length===2 && {READY}',60)
                self.wait("document.getElementById('power-labels').textContent.includes('In shadow') && document.getElementById('power-labels').textContent.includes('Cable connected')",20)
                self.click_visible('Run it');self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Not this time',self.js("document.getElementById('level-done').textContent"))
                self.press('Keep my pieces');self.wait(READY,60)
                self.slide('Adjust a piece','0');self.ghost()
                self.slide('Position along (m) of your solar 1',1.4);self.ghost()
                self.press('Set it down');self.wait(f'!machineGhostState() && {READY}',60)
                self.wait("document.getElementById('power-labels').textContent.includes('50.0 W charging')",20)
                assert_wall_in_view()
                self.press('Collapse controls');assert_wall_in_view();self.press('Expand controls')
                self.assertNotIn('In shadow',self.js("document.getElementById('power-labels').textContent"))
                self.assertEqual(self.js('machinePlacements()[1].b_port'),'battery:power')
                self.click_visible('Run it');self.wait("!document.getElementById('level-done').hidden",30)
                self.assertNotIn('Not this time',self.js("document.getElementById('level-done').textContent"))
                self.press('Play this level again');self.wait(READY,60)
                self.press('Remove your power_cable 2');self.wait(f'machinePlacements().length===1 && {READY}',60)
                self.click_visible('Run it');self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Not this time',self.js("document.getElementById('level-done').textContent"),'Sunlight alone cannot fill the disconnected receiver')

    def test_scene_stays_clear_until_wiring_is_requested_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('sun',width,height,phone=width!=1280)
                self.assertFalse(self.js("document.getElementById('instrument-panel').open"))
                self.press('Add a solar panel');self.ghost()
                self.assertFalse(self.js("document.getElementById('precision-controls').open"))
                self.assertEqual(self.js("document.querySelector('#move-pad').getClientRects().length"),0,'Dragging is primary; nudge buttons are on demand')
                self.assertEqual(self.js("document.querySelectorAll('#view .power-label,#view .terminal-label,#view #preview-legend,#view #edit-guide-label').length"),0,'Reading cards and captions must not obscure the machine')
                for label,value in [('x',1),('z',.4),('height',.6),('turn',-45),('tip',75)]:
                    self.slide(f'{label} of your solar 1',value)
                placed=self.ghost()['p'];angle=self.js('machineCamera()')
                self.click_visible('Focus selected piece')
                self.assertEqual(self.ghost()['p'],placed,'Focusing changes only the camera')
                focused=self.js('machineCamera()')
                self.assertEqual((focused['azimuth'],focused['elevation']),(angle['azimuth'],angle['elevation']))
                self.assertTrue(self.js("(()=>{const b=machineGhostScreen(),r=document.querySelector('#view canvas').getBoundingClientRect();return b&&b.x0>=r.left&&b.x1<=r.right&&b.y0>=r.top&&b.y1<=r.bottom;})()"),'The selected piece fits the scene')
                self.click_visible('✓ Set down');self.wait(f'!machineGhostState() && {READY}',60)
                self.wait("[...document.querySelectorAll('.power-badge')].some(e=>e.getClientRects().length&&e.textContent==='50.0 W')",20)
                self.assertTrue(self.js("[...document.querySelectorAll('#power-pins button,#terminal-pins .terminal-buttons button')].every(e=>!e.getClientRects().length)"))
                area=self.js("(()=>{const view=document.getElementById('view').getBoundingClientRect();return [...document.querySelectorAll('.power-pin')].filter(e=>e.getClientRects().length&&!e.hidden).reduce((sum,e)=>{const r=e.getBoundingClientRect();return sum+r.width*r.height;},0)/(view.width*view.height);})()")
                self.assertLess(area,.03,'The always-visible solar meter uses less than 3% of the scene')
                self.wait('machineFlowPreviewState()?.frames>2',30)
                self.assertGreater(self.js('machinePowerFeedbackState().labels.length'),0,'Compact power and load readings remain visible while building')
                self.click_visible('Connect wires');self.assert_power_layout()
                self.click_visible('Power output of your solar 1');self.click_visible('Power input of winch')
                self.wait(f'machinePlacements().length===2 && {READY}',60)
                self.assertFalse(self.js("document.getElementById('wire-mode').matches('[aria-pressed=true]')"))
                self.assertTrue(self.js("[...document.querySelectorAll('#power-pins button')].every(e=>!e.getClientRects().length)"))
                self.click_visible('Run it');self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Goal',self.js("document.getElementById('level-done').textContent"))

    def test_saved_solar_cable_survives_motion_renaming_reload_undo_and_version_restore(self):
        self.page.send('Emulation.setDeviceMetricsOverride', {'width':1280,'height':860,'deviceScaleFactor':1,'mobile':False})
        self.page.send('Emulation.setTouchEmulationEnabled', {'enabled':False})
        self.page.send('Page.navigate', {'url':f'{self.base}/machine'})
        self.wait("Boolean(document.getElementById('prebuilt-designs'))", 60)
        self.create_design('Saved solar cable')
        for number, piece, x in [(1,'marble',-1.4),(2,'solar',0),(3,'battery',1)]:
            self.press('Add a solar panel' if piece == 'solar' else f'Add a {piece}'); self.ghost()
            label = {'battery':'along (m)', 'solar':'Position along (m)'}.get(piece, 'x')
            self.slide(f'{label} of your {piece} {number}', x)
            self.assertTrue(self.ghost()['fits'])
            self.press('Set it down'); self.wait(f'!window.machineGhostState() && {READY}', 60)
        self.click_visible('Power output of your solar 2')
        self.click_visible('Power input of your battery 3')
        self.wait(f'window.machinePlacements().length === 4 && {READY}', 60)
        self.press('Pick up your power_cable 4')
        cable_before=self.ghost()['p']
        box=self.js('window.machineGhostScreen()')
        x,y=(box['x0']+box['x1'])/2,(box['y0']+box['y1'])/2
        self.assertEqual(self.js(f'document.elementFromPoint({x},{y})?.tagName'),'CANVAS')
        turned=self.js('window.machineCamera().azimuth')
        self.drag([x,y],[x+60,y])
        self.assertEqual(self.ghost()['p'],cable_before,'a fixed-port cable cannot acquire meaningless position edits')
        self.assertNotEqual(self.js('window.machineCamera().azimuth'),turned,'dragging near a cable preview turns the camera')
        self.assertTrue(self.js("document.getElementById('move-pad').hidden"))
        self.press('Cancel')
        self.press('Pick up your battery 3'); self.ghost()
        self.slide('along (m) of your battery 3', 1.2)
        self.assertTrue(self.ghost()['fits'])
        self.press('Set it down'); self.wait(f'!window.machineGhostState() && {READY}', 60)
        self.press('Pick up your solar 2'); self.ghost()
        self.slide('Position along (m) of your solar 2', -.2)
        self.assertTrue(self.ghost()['fits'])
        self.press('Set it down'); self.wait(f'!window.machineGhostState() && {READY}', 60)
        first = self.js('window.machinePlacements()')
        self.press('Save version')
        self.wait("/Version 1 saved/.test(document.getElementById('design-status').textContent)", 10)
        self.press('Remove your marble 1'); self.wait(f'window.machinePlacements().length === 3 && {READY}', 60)
        self.assertEqual(self.js('window.machinePlacements()[2]'),
                         {'piece':'power_cable','a_port':'your solar 1:power','b_port':'your battery 2:power'})
        self.page.send('Page.navigate', {'url':self.js('location.href')}); self.wait(READY, 60)
        self.assertEqual(self.js('window.machinePlacements()[2].b_port'), 'your battery 2:power')
        self.press('Remove your solar 1'); self.wait(f'window.machinePlacements().length === 1 && {READY}', 60)
        self.assertEqual(self.js('window.machinePlacements()[0].piece'), 'battery')
        self.press('Undo'); self.wait(f'window.machinePlacements().length === 3 && {READY}', 60)
        self.assertEqual(self.js('window.machinePlacements()[2].a_port'), 'your solar 1:power')
        self.press('Save version')
        self.wait("/Version 2 saved/.test(document.getElementById('design-status').textContent)", 10)
        self.js("document.getElementById('design-versions').open=true;document.getElementById('version-pick').value='1'")
        self.press('Restore version'); self.wait(f'window.machinePlacements().length === 4 && {READY}', 60)
        self.assertEqual(self.js('window.machinePlacements()'), first)
        self.assertIn('Cable connected', self.js("document.getElementById('power-labels').textContent"))

    def test_fresh_easy_challenge_can_be_solved_shared_and_reopened_on_phones(self):
        for width, height in ((1280, 860), (390, 844), (844, 390)):
            with self.subTest(viewport=(width, height)):
                self.page.send('Emulation.setDeviceMetricsOverride', {'width':width,'height':height,'deviceScaleFactor':1,'mobile':width != 1280})
                self.page.send('Page.navigate', {'url': f'{self.base}/play'})
                self.wait("!document.getElementById('levels-screen').hidden", 60)
                self.assertLessEqual(self.js('document.body.scrollWidth'), width)
                self.slide('Challenge family', 'easy-loop')
                self.press('New challenge')
                self.wait(f"/easy-loop--v2--/.test(location.search) && {READY}", 60)
                link = self.js('location.href')
                title = self.js("document.getElementById('title').textContent")
                goal = self.js("document.getElementById('goal-line').textContent")
                self.assertIn('seed', title)
                self.assertIn('Fresh setup', goal)
                self.press('Share this challenge')
                self.assertEqual(self.js("document.getElementById('challenge-link').value"), link)
                self.page.send('Page.navigate', {'url':link})
                self.wait(READY, 60)
                self.assertEqual(self.js("document.getElementById('title').textContent"), title)
                self.assertEqual(self.js("document.getElementById('goal-line').textContent"), goal)
                self.press('Add a wire'); self.ghost()
                self.slide('from terminal of your wire 1', 'lamp:minus')
                self.slide('to terminal of your wire 1', 'supply:minus')
                self.assertTrue(self.ghost()['fits'])
                self.press('Set it down'); self.wait(READY, 60)
                self.press('Run it')
                self.wait("!document.getElementById('level-done').hidden", 30)
                self.assertNotIn('finished every level', self.js("document.getElementById('level-done').textContent"))
                self.assertFalse(self.js("Boolean(document.querySelector('#level-done [aria-label=\"Next level\"]'))"))
                self.press('All levels')
                self.assertLessEqual(self.js('document.body.scrollWidth'), width)
                self.reveal_control("document.getElementById('challenge-family')")
                self.assertGreaterEqual(self.js("document.getElementById('challenge-family').getBoundingClientRect().height"), 44)
                self.assertIn(title, self.js("document.querySelector('[aria-label=\"Recent challenges\"]').textContent"))
                self.press(title); self.wait(READY, 60)
                self.assertEqual(self.js('location.href'), link)

    def test_terminal_clicks_teach_wiring_and_prepared_leads_use_the_same_routes(self):
        for width, height in ((1280,860), (390,844), (844,390)):
            with self.subTest(width=width, height=height):
                self.open('easy-loop', width, height, phone=width<1000)
                self.assertEqual(len(self.js('window.machineWiringState().wires')), 2)
                self.click_visible('Connect lamp minus')
                self.ghost()
                self.assertEqual(self.js('window.machineWiringState().selected'), 'lamp:minus')
                self.key('Escape')
                self.assertIsNone(self.js('window.machineGhostState()'))
                self.assertEqual(self.js('window.machinePlacements()'), [])
                self.assertFalse(self.js("document.getElementById('wire-mode').matches('[aria-pressed=true]')"),'Escape leaves wiring mode')
                self.click_visible('Connect wires')
                self.wait("(() => { const b=document.querySelector('[data-terminal=\"lamp:minus\"]'); return b && !b.disabled && b.offsetParent!==null; })()", 10)
                self.click_visible('Connect supply plus'); self.ghost()
                self.click_visible('Connect control in')
                self.wait(f'!window.machineGhostState() && {READY}', 60)
                self.click_visible('Run it')
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Not this time', self.js("document.getElementById('level-done').textContent"),
                              'another supply lead cannot replace the missing return path')
                self.press('Start over'); self.wait(READY, 60)
                self.reveal_control(self.button_expression('Connect lamp minus'))
                self.wait("(() => { const b=document.querySelector('[data-terminal=\"lamp:minus\"]'); return b && !b.disabled && b.offsetParent!==null; })()", 10)
                self.click_visible('Connect lamp minus'); self.ghost()
                self.click_visible('Connect supply minus')
                self.wait(f'!window.machineGhostState() && {READY}', 60)
                self.assertEqual(self.js('window.machinePlacements().map(p=>[p.piece,p.a_terminal,p.b_terminal])'),
                                 [['wire','lamp:minus','supply:minus']])
                wires = self.js('window.machineWiringState().wires')
                self.assertEqual(len(wires),3)
                self.assertTrue(all(any(abs(p[1]-.012)<1e-9 for p in w['route']) for w in wires))
                self.click_visible('Run it')
                self.wait("!document.getElementById('level-done').hidden",30)
                self.wait('window.machineWiringState().wires.every(w=>w.color===0xffd34d)',10)
                self.open('easy-marble-light', width, height, phone=width<1000)
                self.assertEqual(len(self.js('window.machineWiringState().wires')), 1)
                self.press('Add a switch'); self.ghost()
                self.slide('along (m) of your switch 1', 0); self.slide('across (m) of your switch 1', 0)
                self.assertTrue(self.ghost()['fits'])
                self.assertEqual(self.js('window.machineWiringState().ghostWires'),3)
                self.wait("[...document.querySelectorAll('.terminal-label')].length===3 && [...document.querySelectorAll('.terminal-label')].every(c=>!c.hidden)", 10)
                self.click_visible('Run it')
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertEqual(len(self.js('window.machineWiringState().wires')),3)

    def test_level_task_counts_and_saved_wiring_use_the_real_scene_controls(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            self.anonymous_levels(width=width,height=height)
            self.assertEqual(self.js("document.querySelectorAll('#levels-screen .ls-list li').length"), self.level_count)
            self.assertFalse(self.js("Boolean(document.querySelector('[aria-label=\"Choose challenge difficulty\"]'))"))
            self.assertFalse(self.js("[...document.querySelectorAll('#levels-screen button')].some(b=>/^(All challenges|Easy: learn a piece|Full chain reactions)$/.test(b.textContent))"))
            # Counts belong to level IDs; ordering changes as lessons are added.
            for ident,count in [('gap',1),('sun',2),('laser',2),('easy-solar',2),
                    ('easy-water-wheel',1),('easy-river-wheel',1),('easy-water-gate',3)]:
                text=f'{count} '+('thing' if count==1 else 'things')+' to do'
                self.assertEqual(self.js(f"document.querySelector('[data-level=\"{ident}\"] .task-count').textContent"),text)
            self.assertTrue(self.js("[...document.querySelectorAll('#levels-screen .ls-list li .task-count')].every(el=>/^[1-9][0-9]* things? to do$/.test(el.textContent))"))
            self.assertFalse(self.js("[...document.querySelectorAll('#levels-screen .teaches')].some(el=>el.textContent.startsWith('Easy ·'))"))
            self.assertLessEqual(self.js('document.documentElement.scrollWidth'),width)
        self.page.send('Emulation.setDeviceMetricsOverride',{'width':1280,'height':860,'deviceScaleFactor':1,'mobile':False})
        self.open('easy-loop')
        self.press('Add a wire')
        self.ghost()
        self.slide('from terminal of your wire 1', 'lamp:minus')
        self.slide('to terminal of your wire 1', 'supply:minus')
        self.assertTrue(self.ghost()['fits'])
        self.press('Set it down')
        self.wait(f'!window.machineGhostState() && {READY}', 60)
        self.press('Run it')
        self.wait("!document.getElementById('level-done').hidden", 30)
        self.assertIn('Goal', self.js("document.getElementById('level-done').textContent"))

    def switch_handle_target(self,name='control'):
        label=f'Drag {name} handle'
        self.wait(f"[...document.querySelectorAll('button')].some(b=>b.getAttribute('aria-label')==={json.dumps(label)}&&!b.disabled&&b.offsetParent!==null)",15)
        self.wait('window.machineCamera().settled',30)
        target=self.js(f"(() => {{const b=[...document.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')==={json.dumps(label)}),r=b.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2;return {{x,y,w:r.width,h:r.height,visible:r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight,uncovered:b.contains(document.elementFromPoint(x,y))}};}})()")
        self.assertTrue(target['visible'] and target['uncovered'],target)
        self.assertGreaterEqual(target['w'],44);self.assertGreaterEqual(target['h'],44)
        return target['x'],target['y']

    def open_manual_circuit(self,width=1280,height=860):
        self.page.send('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':width!=1280})
        self.page.send('Emulation.setTouchEmulationEnabled',{'enabled':width!=1280,'maxTouchPoints':5})
        self.page.send('Page.navigate',{'url':f'{self.base}/machine'})
        self.wait("Boolean(document.querySelector('#prebuilt-designs button'))",60)
        self.press('Start from Build your first circuit');self.wait(READY,60)
        self.wait("window.machineSwitchState().handles.some(h=>h.name==='control')",15)

    def test_manual_switch_handle_drag_moves_real_rocker_and_reset_restores_saved_state(self):
        for width, height in ((1280, 860), (390, 844), (844, 390)):
            with self.subTest(viewport=(width, height)):
                self.open_manual_circuit(width,height)
                self.press('Save version')
                self.wait("window.machineDesign().versions.length > 0", 10)
                saved = self.js('window.machineDesign().versions.slice(-1)[0].draft')
                self.assertFalse(self.js("[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='Toggle control')"))
                before=self.js("window.machineSwitchState().handles.find(h=>h.name==='control').at_m")
                self.click_visible('Drag control handle')
                self.assertTrue(self.js(READY),'a simple tap does not start the machine')
                self.assertIsNone(self.js('window.machineSwitchState().drag'))
                x,y=self.switch_handle_target()
                self.drag([x,y],[x,y-85],touch=width!=1280,steps=12)
                self.wait("window.machineSwitchState().handles.find(h=>h.name==='control').closed===false",15)
                self.wait("/controlopen/.test(document.getElementById('readings').textContent)",15)
                opened=self.js("window.machineSwitchState().handles.find(h=>h.name==='control').at_m")
                self.assertGreater(opened[1],before[1]+.04,'the native grip rises as the rocker opens')
                self.assertIsNone(self.js('window.machineSwitchState().drag'))
                self.press('Pause')
                x,y=self.switch_handle_target()
                self.drag([x,y],[x,y+85],touch=width!=1280,steps=12)
                self.wait("window.machineSwitchState().handles.find(h=>h.name==='control').closed===true",15)
                self.wait("window.machineContactState().liveDevices.some(d=>d.kind==='bulb'&&d.power_w>2)",15)
                self.assertEqual(self.js('window.machineDesign().versions.slice(-1)[0].draft'), saved)
                self.press('Set up again')
                self.wait(READY, 60)
                self.wait("/controlclosed/.test(document.getElementById('readings').textContent)", 15)
                self.assertEqual(self.js('window.machineDesign().versions.slice(-1)[0].draft'),saved)

    def test_switch_handle_force_releases_on_second_touch_cancel_pause_and_zoom(self):
        self.open_manual_circuit()
        x,y=self.switch_handle_target()
        self.mouse('mousePressed',x,y)
        self.page.send('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x,'y':y-35,'button':'left','buttons':1})
        self.wait('window.machineSwitchState().drag?.active&&window.machineSwitchState().drag.force_n>0',10)
        distance=self.js('window.machineCamera().distance')
        self.page.send('Input.dispatchMouseEvent',{'type':'mouseWheel','x':x,'y':y-35,'deltaX':0,'deltaY':-120,'button':'left','buttons':1})
        self.assertEqual(self.js('window.machineCamera().distance'),distance,'zoom is quarantined while holding the real grip')
        self.mouse('mouseReleased',x,y-35)
        self.open_manual_circuit(390,844)
        self.page.send('Network.enable');self.page.events.clear()
        x,y=self.switch_handle_target()
        touch=lambda kind,points:self.page.send('Input.dispatchTouchEvent',{'type':kind,'touchPoints':points})
        touch('touchStart',[{'x':x,'y':y,'id':1}])
        touch('touchMove',[{'x':x,'y':y-35,'id':1}])
        self.wait('window.machineSwitchState().drag?.active&&window.machineSwitchState().drag.force_n>0',10)
        turned=self.js('window.machineCamera().azimuth');distance=self.js('window.machineCamera().distance')
        touch('touchStart',[{'x':x,'y':y-35,'id':1},{'x':x-80,'y':y-35,'id':2}])
        self.assertIsNone(self.js('window.machineSwitchState().drag'))
        touch('touchMove',[{'x':x+20,'y':y-35,'id':1},{'x':x-60,'y':y-35,'id':2}])
        self.wait(f'window.machineCamera().azimuth!=={turned}',5)
        self.assertAlmostEqual(self.js('window.machineCamera().distance'),distance,places=10,msg='moving both fingers together turns without changing zoom')
        touch('touchEnd',[])
        self.press('Pause')
        x,y=self.switch_handle_target()
        touch('touchStart',[{'x':x,'y':y,'id':1}]);touch('touchMove',[{'x':x,'y':y+30,'id':1}])
        self.wait('window.machineSwitchState().drag?.active',10)
        touch('touchCancel',[])
        self.assertIsNone(self.js('window.machineSwitchState().drag'))
        self.wait("document.getElementById('start').textContent==='Pause'",10)
        self.press('Pause')
        x,y=self.switch_handle_target()
        touch('touchStart',[{'x':x,'y':y,'id':1}]);touch('touchMove',[{'x':x,'y':y-30,'id':1}])
        self.wait('window.machineSwitchState().drag?.active',10)
        self.press('Pause')
        self.assertIsNone(self.js('window.machineSwitchState().drag'))
        touch('touchEnd',[])
        self.wait("document.getElementById('start').textContent!=='Pause'",10)
        self.js('true')
        requests=[json.loads(e['params']['request']['postData']) for e in self.page.events if e['method']=='Network.requestWillBeSent'
                  and e['params']['request']['url'].endswith('/api/machine') and e['params']['request'].get('postData')]
        forces=[p for p in requests if p.get('op')=='mechanical_switch_pull']
        self.assertTrue(any(p['force']!=[0,0,0] for p in forces))
        self.assertEqual(forces[-1]['force'],[0,0,0])
        self.assertFalse(any(p.get('op') in ('pull','electrical_switch') for p in requests),'dedicated handle operation uses actual force without general test Pull or Boolean toggles')

    def test_queued_pause_cannot_operate_a_new_design_after_navigation(self):
        self.open_manual_circuit()
        self.js("""window.realPlayFetch=window.fetch;window.playCommands=[];window.holdFirstPlay=true;
            window.playResponseGate=new Promise(resolve=>window.releasePlayResponse=resolve);
            window.fetch=async (...args)=>{const body=args[1]?.body && JSON.parse(args[1].body);
              if(body?.op==='play')window.playCommands.push({session:body.session,running:body.running});
              const hold=body?.op==='play'&&body.running&&window.holdFirstPlay;
              if(hold)window.holdFirstPlay=false;
              const response=await window.realPlayFetch(...args);
              if(hold){window.playResponseHeld=true;await window.playResponseGate;window.playResponseReleased=true;}
              return response;};""")
        x,y=self.switch_handle_target()
        self.mouse('mousePressed',x,y)
        self.page.send('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x,'y':y-35,'button':'left','buttons':1})
        self.wait("window.playResponseHeld&&document.getElementById('start').textContent==='Pause'",10)
        self.mouse('mouseReleased',x,y-35)
        self.press('Pause')
        self.assertEqual(len(self.js('window.playCommands')),1,'the pause waits behind the held play reply')
        self.press('All designs');self.press('Add New Design');self.wait(READY,30)
        self.assertEqual(self.js('window.machinePlacements()'),[])
        self.js('window.releasePlayResponse()')
        self.wait('window.playResponseReleased',10)
        self.page.evaluate('new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)))',await_promise=True)
        self.assertEqual(len(self.js('window.playCommands')),1,'the queued command from the previous scene cannot operate the new design')
        self.assertTrue(self.js(READY))
        self.js('window.fetch=window.realPlayFetch')

    def test_legitimate_switch_handle_operation_can_win_with_actual_work(self):
        self.open('easy-switch')
        self.press('Add a switch');self.ghost()
        self.slide('initial state of your switch 1','open')
        self.assertTrue(self.ghost()['fits'])
        self.press('Set it down');self.wait(f'!window.machineGhostState() && {READY}',60)
        self.switch_handle_target('your switch 1')
        grip=self.js("window.machineSwitchState().handles.find(h=>h.name==='your switch 1').at_m")
        x,y=self.screen_point(grip)
        self.assertTrue(self.js(f'document.elementFromPoint({x},{y})?.tagName==="CANVAS"'),'the actual handle can be grabbed in the field')
        self.drag([x,y],[x,y+85],steps=12)
        self.wait("!document.getElementById('level-done').hidden",30)
        result=self.js("document.getElementById('level-done').textContent")
        self.assertNotIn('A test run',result)
        self.assertIn('easy-switch',self.js('Object.keys(window.machineSave().players[window.machineSave().current].levels)'))
        self.assertIn('your pulls',result,'actual external work remains in the scored energy receipt')

    def test_cannon_player_draws_both_leads_and_operates_trigger_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('fire',width,height,phone=width<1000)
                self.press('Add a cannon');self.ghost()
                self.slide('Muzzle x of your cannon 1',1.4)
                self.slide('Bore height of your cannon 1',.48)
                self.slide('Muzzle z of your cannon 1',0)
                self.assertTrue(self.ghost()['fits'])
                self.press('Set it down');self.wait(f'!window.machineGhostState() && {READY}',60)
                self.assertEqual(len(self.js('window.machineWiringState().wires')),1,'placing does not wire the cannon')
                self.wait("[...document.querySelectorAll('#terminal-labels section')].some(c=>c.textContent.includes('cannon 1')&&c.textContent.includes('0.000 A'))",10)
                for a,b in [('Connect trigger out','Connect your cannon 1 plus'),
                            ('Connect your cannon 1 minus','Connect supply minus')]:
                    self.click_visible(a);self.ghost();self.click_visible(b)
                    self.wait(f'!window.machineGhostState() && {READY}',60)
                self.assertEqual(len(self.js('window.machineWiringState().wires')),3)
                self.assertEqual(self.js('window.machinePlacements().slice(1).map(p=>[p.a_terminal,p.b_terminal])'),
                    [['trigger:out','your cannon 1:plus'],['your cannon 1:minus','supply:minus']])
                self.key('Escape')
                self.wait("window.machinePreviewState()?.legend.includes('waiting for your handle drag')",20)
                self.click_visible('Run it')
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Not this time',self.js("document.getElementById('level-done').textContent"))
                self.assertFalse(self.js("window.machineSwitchState().handles.find(h=>h.name==='trigger').closed"))
                self.press('Keep my pieces');self.wait(READY,60)
                self.assertEqual(self.js("document.querySelector('[aria-label=\"Drag trigger handle\"]').textContent"),'Drag to fire ↓')
                self.click_visible('Drag trigger handle')
                self.assertTrue(self.js(READY),'a tap does not fire')
                x,y=self.switch_handle_target('trigger')
                self.drag([x,y],[x,y+85],touch=width<1000,steps=12)
                self.wait("!document.getElementById('level-done').hidden",30)
                result=self.js("document.getElementById('level-done').textContent")
                if 'Not this time' in result:
                    print('CANNON_DRAG_FAILURE',json.dumps(self.js('({switch:machineSwitchState(),contact:machineContactState(),placements:machinePlacements()})')),flush=True)
                    for native in self.server.machines.sessions.values():
                        if native.compiled['title']=='Knock it off':
                            frame=native.frame(0,0)
                            print('CANNON_NATIVE_FAILURE',json.dumps(dict(t=frame['t'],
                                readouts={key:frame['readouts'].get(key) for key in ('joints','pulls','heat','gas','stations')},
                                ledgers=[n['ledger'] for n in frame['readouts']['electrical']['networks']],
                                bodies=[b for b in frame['bodies'] if b['name'] in ('block','your cannon 1 ball','trigger handle')])) ,flush=True)
                self.assertNotIn('Not this time',result)
                self.assertNotIn('A test run',result)
                self.assertIn('your pulls',result)
                self.assertEqual(self.js('machineSave().players[machineSave().current].levels.fire.stars'),3)

    def test_saved_terminal_graph_removal_undo_reload_and_restore(self):
        self.page.send('Page.navigate', {'url': f'{self.base}/machine'})
        self.wait("Boolean(document.getElementById('prebuilt-designs'))", 60)
        self.create_design('Saved terminal graph')
        for piece, x in [('battery', -.6), ('bulb', .6)]:
            self.press(f'Add a {piece}')
            self.ghost()
            number = 1 if piece == 'battery' else 2
            self.slide(f'along (m) of your {piece} {number}', x)
            self.slide(f'across (m) of your {piece} {number}', 0)
            self.assertTrue(self.ghost()['fits'])
            self.press('Set it down')
            self.wait(f'!window.machineGhostState() && {READY}', 60)
        for terminal in ('plus', 'minus'):
            self.wait('window.machineCamera().settled', 30)
            self.reveal_control(self.button_expression(f'Connect your battery 1 {terminal}'))
            self.wait("!window.machineWiringState().busy && [...document.querySelectorAll('#terminal-pins .terminal-buttons button')].some(b=>!b.disabled && b.offsetParent!==null)", 10)
            self.click_visible(f'Connect your battery 1 {terminal}'); self.ghost()
            self.click_visible(f'Connect your bulb 2 {terminal}')
            self.wait(f'!window.machineGhostState() && {READY}', 60)
        first = self.js('window.machinePlacements()')
        self.press('Save version')
        self.wait("/Version 1 saved/.test(document.getElementById('design-status').textContent)", 10)
        self.press('Remove your battery 1')
        self.wait(f'window.machinePlacements().length === 1 && {READY}', 60)
        self.assertEqual(self.js('window.machinePlacements()[0].piece'), 'bulb')
        self.press('Undo')
        self.wait(f'window.machinePlacements().length === 4 && {READY}', 60)
        self.assertEqual(self.js('window.machinePlacements()'), first)
        self.page.send('Page.navigate', {'url': self.js('location.href')})
        self.wait(READY, 60)
        self.assertEqual(self.js('window.machinePlacements()'), first)
        self.press('Remove your battery 1')
        self.wait(f'window.machinePlacements().length === 1 && {READY}', 60)
        self.press('Save version')
        self.wait("/Version 2 saved/.test(document.getElementById('design-status').textContent)", 10)
        self.js("document.getElementById('design-versions').open = true; document.getElementById('version-pick').value = '1'")
        self.press('Restore version')
        self.wait(f'window.machinePlacements().length === 4 && {READY}', 60)
        self.assertEqual(self.js('window.machinePlacements()'), first)
        self.press('Run it')
        self.wait("/your bulb 2.*0\\.60 W light/.test(document.getElementById('readings').textContent)", 15)

    def test_selected_controls_highlight_the_piece_and_follow_its_orientation(self):
        self.open('gap')
        self.press('Add a plank')
        guide = self.ghost()['editGuide']
        self.assertEqual(guide['key'], 'length_m')
        self.assertEqual(len(guide['arrows']), 2)
        self.wait("!document.getElementById('edit-guide-label').hidden", 5)
        self.press('More Cut to length')
        changed = self.ghost()['editGuide']
        self.assertGreater(max(a['at'][0] for a in changed['arrows']), max(a['at'][0] for a in guide['arrows']))
        self.press('Change its turn')
        self.assertEqual(self.ghost()['editGuide']['key'], 'yaw_deg')
        self.slide('Its turn', 90)
        self.ghost()
        self.press('Change its Cut to length')
        guide = self.ghost()['editGuide']
        self.assertEqual(len(guide['arrows']), 2)
        self.assertTrue(all(abs(a['direction'][2]) > .99 for a in guide['arrows']))
        self.press('turn on 15 degrees')
        self.assertEqual(self.ghost()['editGuide']['key'], 'yaw_deg')
        self.assertEqual(self.ghost()['p']['yaw_deg'], 105)
        self.press('Throw the ghost away')
        self.wait("document.getElementById('edit-guide-label').hidden", 5)
        for width, height in ((1280, 860), (390, 844), (844, 390)):
            with self.subTest(viewport=(width, height)):
                self.open('free', width, height, phone=width != 1280)
                self.press('Add a track')
                self.ghost()
                self.press('Change its drop')
                guide = self.ghost()['editGuide']
                self.assertEqual(guide['key'], 'drop_m')
                self.assertEqual(len(guide['arrows']), 1)
                self.assertLess(guide['arrows'][0]['direction'][1], -.9)
                self.press('Change its far end')
                guide = self.ghost()['editGuide']
                self.assertEqual(guide['key'], 'end')
                self.assertIsNotNone(guide['marker'])
                self.slide('Its far end', 'gate')
                self.assertTrue(self.ghost()['editGuide']['focus'])
                self.wait("!document.getElementById('edit-guide-label').hidden", 5)
                self.reveal_control("document.getElementById('edit-guide-label')")
                self.assertTrue(self.js("document.getElementById('precision-controls').contains(document.getElementById('edit-guide-label'))"))
                self.assertFalse(self.js("document.getElementById('view').contains(document.getElementById('edit-guide-label'))"),'The guide remains on the object, with its caption in the inspector')
                self.press('Throw the ghost away')
                self.wait("document.getElementById('edit-guide-label').hidden", 5)

    def test_a_ghost_is_placed_at_once_dragged_changed_turned_set_down_and_run(self):
        self.open('gap')
        self.js("window.machineView({azimuth: -0.35, elevation: 0.75, distance: 3.2, at: [0.3, 0.2, 0]})")
        time.sleep(1.5)                       # the camera eases to its new view
        self.press('Add a plank')
        g = self.ghost()
        self.assertGreater(g['parts'],0,'it is placed at once, ready to change')
        self.assertFalse(self.js("[...document.querySelectorAll('button')].some(b=>b.textContent==='Follow the pointer')"))
        # Not in the machine yet: the engine's world has no plank.
        self.assertNotIn('your plank 1', self.js("[...document.querySelectorAll('#stations li')].map(l => l.textContent).join()"))
        self.mouse('mouseMoved',*self.screen_point([-.2,0,0]))
        self.assertEqual(self.ghost()['p'],g['p'],'hovering cannot relocate the piece')
        g=self.drag_ghost_to(.3,0)
        self.assertAlmostEqual(g['p']['x_m'],0.3,delta=0.02,msg='dragging puts the ghost there')
        x, y = self.screen_point([0.8, 0.0, 0.0])
        self.mouse('mousePressed', x, y)
        self.mouse('mouseReleased', x, y)
        self.assertEqual(self.ghost()['p'],g['p'],'a scene click cannot relocate it')
        self.assertEqual(self.js("document.getElementById('mode-view').getAttribute('aria-pressed')"),'true')
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
        self.wait('!window.machineGhostState()', 5)
        self.wait("Boolean(document.querySelector('#verdict .stars'))", 90)
        self.assertIn('★★★', self.js("document.getElementById('verdict').textContent"))
        # The goal says so, over the scene, and leads on to the next level.
        self.wait("!document.getElementById('level-done').hidden", 10)
        done = self.js("document.getElementById('level-done').textContent")
        self.assertIn('Achievement Unlocked', done)
        self.assertIn('Your first win with a plank!', done)
        self.assertIn('Energy used: 30.6 MJ', done)
        self.assertIn('Your plank 1: 2.94 kg, 30.6 MJ', done)
        self.press('Next level')
        self.wait("/^2\\. /.test(document.getElementById('title').textContent)", 30)

    def test_help_is_only_an_overlay_and_keeps_each_screen_and_setup_on_desktop_and_phones(self):
        def open_help():
            # A cloud acknowledgement updates cache metadata independently
            # of help. Settle the existing save before asserting no changes.
            self.anonymous_cloud_saved()
            self.assertFalse(self.js("document.getElementById('guide').open"), 'help does not appear automatically')
            before = self.js("({url:location.href,setup:window.machinePlacements(),save:localStorage.getItem('banjo-play-save'),screen:document.body.className,scroll:scrollY})")
            target = self.js("(() => {const e=document.getElementById('guide-open'),r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,w:r.width,h:r.height,visible:r.left>=0 && r.right<=innerWidth && r.top>=0 && r.bottom<=innerHeight,hit:e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))};})()")
            self.assertTrue(target['visible'] and target['hit'], target)
            self.assertGreaterEqual(target['w'], 44); self.assertGreaterEqual(target['h'], 44)
            self.page.events.clear()
            self.mouse('mousePressed', target['x'], target['y']); self.mouse('mouseReleased', target['x'], target['y'])
            self.wait("document.getElementById('guide').open", 5)
            self.assertEqual(self.js('location.href'), before['url'])
            self.assertEqual(self.js('window.machinePlacements()'), before['setup'])
            self.assertEqual(self.js("localStorage.getItem('banjo-play-save')"), before['save'])
            self.assertEqual(self.js("document.body.className.replace(' reading-guide','')"), before['screen'])
            self.assertEqual(self.js("document.activeElement.id"), 'guide-done')
            layout = self.js("(() => {const r=document.getElementById('guide').getBoundingClientRect(),b=document.querySelector('.guide-body');return {inView:r.left>=0 && r.right<=innerWidth && r.top>=0 && r.bottom<=innerHeight,overflows:b.scrollWidth>b.clientWidth,scrollable:getComputedStyle(b).overflowY==='auto'};})()")
            self.assertTrue(layout['inView'] and layout['scrollable'] and not layout['overflows'], layout)
            # Real keys cannot manipulate a ghost or place it behind the help.
            ghost_before = self.js('window.machineGhostState()')
            self.key('q'); self.key('Enter')
            self.assertEqual(self.js('window.machineGhostState()'), ghost_before)
            self.page.send('Input.dispatchKeyEvent', {'type':'keyDown','key':'Tab','code':'Tab','windowsVirtualKeyCode':9})
            self.page.send('Input.dispatchKeyEvent', {'type':'keyUp','key':'Tab','code':'Tab','windowsVirtualKeyCode':9})
            self.assertTrue(self.js("Boolean(document.activeElement.closest('#guide'))"), 'focus stays in the modal')
            requests = [e['params']['request'] for e in self.page.events if e['method'] == 'Network.requestWillBeSent']
            ops = [json.loads(r['postData'])['op'] for r in requests if r['url'].endswith('/api/machine') and 'postData' in r]
            self.assertFalse(any(op in ('open','level_open','check','play') for op in ops), ops)
            return before

        def assert_closed(before):
            self.wait("!document.getElementById('guide').open && !document.body.classList.contains('reading-guide')", 5)
            self.assertEqual(self.js('location.href'), before['url'])
            self.assertEqual(self.js('window.machinePlacements()'), before['setup'])
            self.assertEqual(self.js("localStorage.getItem('banjo-play-save')"), before['save'])
            self.assertEqual(self.js('scrollY'), before['scroll'])
            self.assertEqual(self.js('document.activeElement.id'), 'guide-open')

        self.page.send('Network.enable')
        for width, height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('tackle', width, height, phone=width != 1280)
                self.assertEqual(self.js("document.querySelectorAll('.station-label').length"), 0, 'no floating station notes')
                before = open_help(); self.click_visible('Close'); assert_closed(before)
                self.open('gap', width, height, phone=width != 1280)
                self.press('Add a plank'); self.ghost()
                self.js('scrollTo(0,0)')
                before = open_help(); self.key('Escape'); assert_closed(before)
                self.page.send('Page.navigate', {'url': self.base + '/play'})
                self.wait("!document.getElementById('levels-screen').hidden", 60)
                before = open_help()
                # A backdrop click dismisses, while content clicks do not.
                self.mouse('mousePressed', 2, 2); self.mouse('mouseReleased', 2, 2); assert_closed(before)
                self.page.send('Page.navigate', {'url': self.base + '/machine'})
                self.wait("document.getElementById('sandbox-screen')?.hidden===false", 60)
                before = open_help(); self.click_visible('Close'); assert_closed(before)
                self.press('Add New Design'); self.wait(READY, 60)
                before = open_help(); self.click_visible('Close'); assert_closed(before)

    def test_recent_changes_preserves_builds_and_fits_every_screen(self):
        def open_updates():
            self.anonymous_cloud_saved()
            self.assertFalse(self.js("document.getElementById('recent-changes').open"))
            before = self.js("({url:location.href,setup:window.machinePlacements(),ghost:window.machineGhostState(),save:localStorage.getItem('banjo-play-save'),scroll:scrollY})")
            navigation = self.js("[...document.querySelectorAll('header nav a')].map(e=>{const r=e.getBoundingClientRect();return {label:e.textContent,x:r.x+r.width/2,y:r.y+r.height/2,w:r.width,h:r.height,visible:r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight,hit:e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))};})")
            self.assertEqual([r['label'] for r in navigation], ['Levels','Sandbox','How to play','Recent Changes'])
            for target in navigation:
                self.assertTrue(target['visible'] and target['hit'], target)
                self.assertGreaterEqual(target['w'], 44); self.assertGreaterEqual(target['h'], 44)
            self.page.events.clear()
            target=navigation[-1]
            self.mouse('mousePressed',target['x'],target['y']); self.mouse('mouseReleased',target['x'],target['y'])
            self.wait("document.getElementById('recent-changes').open", 5)
            self.assertEqual(self.js('document.activeElement.id'), 'recent-changes-done')
            layout = self.js("(() => {const d=document.getElementById('recent-changes'),r=d.getBoundingClientRect(),b=d.querySelector('.guide-body');return {inView:r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight,overflow:b.scrollWidth>b.clientWidth,scrollable:getComputedStyle(b).overflowY==='auto',dates:[...d.querySelectorAll('time')].map(t=>t.dateTime)};})()")
            self.assertTrue(layout['inView'] and layout['scrollable'] and not layout['overflow'], layout)
            self.assertEqual(layout['dates'], sorted(layout['dates'], reverse=True))
            # Keys cannot tweak a piece or undo the setup behind the notes.
            for key, code, vk, modifiers in (('q','KeyQ',81,0),('ArrowRight','ArrowRight',39,0),('z','KeyZ',90,2)):
                for kind in ('keyDown','keyUp'):
                    self.page.send('Input.dispatchKeyEvent', {'type':kind,'key':key,'code':code,'windowsVirtualKeyCode':vk,'modifiers':modifiers})
            self.assertEqual(self.js('window.machineGhostState()'), before['ghost'])
            self.page.send('Input.dispatchKeyEvent', {'type':'keyDown','key':'Tab','code':'Tab','windowsVirtualKeyCode':9})
            self.page.send('Input.dispatchKeyEvent', {'type':'keyUp','key':'Tab','code':'Tab','windowsVirtualKeyCode':9})
            self.assertTrue(self.js("Boolean(document.activeElement.closest('#recent-changes'))"))
            # Older notes are reachable inside the dialog, not under the game.
            self.js("document.querySelector('.changes-body').scrollTop=10000")
            self.assertTrue(self.js("(() => {const p=document.querySelector('.changes-body'),e=[...p.querySelectorAll('article')].at(-1),r=e.getBoundingClientRect(),b=p.getBoundingClientRect();return r.top>=b.top&&r.bottom<=b.bottom+1;})()"))
            ops = [json.loads(e['params']['request']['postData'])['op'] for e in self.page.events
                   if e['method']=='Network.requestWillBeSent' and e['params']['request']['url'].endswith('/api/machine') and 'postData' in e['params']['request']]
            self.assertFalse(any(op in ('open','level_open','check','play') for op in ops), ops)
            return before

        def closed(before):
            self.wait("!document.getElementById('recent-changes').open&&!document.body.classList.contains('reading-guide')", 5)
            self.assertEqual(self.js('location.href'), before['url'])
            self.assertEqual(self.js('window.machinePlacements()'), before['setup'])
            self.assertEqual(self.js("localStorage.getItem('banjo-play-save')"), before['save'])
            self.assertEqual(self.js('scrollY'), before['scroll'])
            self.assertEqual(self.js('document.activeElement.id'), 'recent-changes-open')

        for width, height in ((1280,860),(390,844),(844,390),(320,568)):
            with self.subTest(viewport=(width,height)):
                self.open('gap', width, height, phone=width!=1280)
                self.press('Add a plank'); self.ghost(); self.js('scrollTo(0,0)')
                before=open_updates(); self.key('Escape'); closed(before)
                bounds=self.js("(() => {const m=document.querySelector('main').getBoundingClientRect(),h=document.querySelector('header').getBoundingClientRect();return {bottom:m.bottom,top:m.top,header:h.bottom,height:innerHeight};})()")
                self.assertLessEqual(bounds['bottom'], bounds['height']+1, bounds)
                self.assertAlmostEqual(bounds['top'], bounds['header'], delta=1)
                self.click_visible('Run it'); self.wait("/Pause/.test(document.getElementById('start').textContent)", 10)
                # Reading updates does not stop or reopen a running machine.
                before=open_updates(); self.click_visible('Close'); closed(before)
                self.assertRegex(self.js("document.getElementById('start').textContent"), 'Pause')
                self.click_visible('Pause')
                for path, screen in (('/play','levels-screen'),('/machine','sandbox-screen')):
                    self.page.send('Page.navigate', {'url':self.base+path})
                    self.wait(f"document.getElementById('{screen}')?.hidden===false",60)
                    before=open_updates()
                    self.mouse('mousePressed',2,2); self.mouse('mouseReleased',2,2); closed(before)
                self.press('Add New Design'); self.wait(READY,60)
                before=open_updates(); self.click_visible('Close'); closed(before)

    def test_a_player_can_tell_us_what_happened(self):
        self.open('gap')
        # Telling us: the words, with the level and its pieces, reach the log.
        self.js("document.getElementById('feedback').open = true")
        self.js("document.getElementById('feedback-text').value = 'The plank looked like it floated'")
        self.press('Send')
        self.wait("/Thank you/.test(document.getElementById('feedback-status').textContent)", 10)
        notes = [json.loads(line) for line in (Path(self.logs.name) / 'feedback.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual((notes[-1]['text'], notes[-1]['level']), ('The plank looked like it floated', 'gap'))
        self.assertNotIn('127.0.0.1', json.dumps(notes[-1]), 'nothing that names the player is kept')

    def test_root_opens_play_without_flashing_or_building_the_editor(self):
        # Even while the module is unavailable, the initial HTML keeps the
        # editor out of sight. The server redirects before sending a page.
        self.page.send('Network.enable')
        self.page.send('Network.setCacheDisabled', {'cacheDisabled': True})
        self.page.send('Network.setBlockedURLs', {'urls': ['*/machine.js']})
        try:
            self.page.send('Page.navigate', {'url': self.base + '/'})
            self.wait("location.pathname === '/play' && Boolean(document.getElementById('page-loading')) && !document.getElementById('page-loading').hidden", 10)
            self.assertEqual(self.js("document.querySelector('main').getBoundingClientRect().height"), 0)
            self.assertGreater(self.js("document.getElementById('page-loading').getBoundingClientRect().height"), 0)
        finally:
            self.page.send('Network.setBlockedURLs', {'urls': []})
            self.page.send('Network.setCacheDisabled', {'cacheDisabled': False})
        # Record actual API operations: browsing must not open a live world,
        # including for a returning player whose last choice was the sandbox.
        self.js("localStorage.setItem('banjo-play-save', JSON.stringify({current:'Landing test',players:{'Landing test':{levels:{},last:'free'}}})); localStorage.removeItem('banjo-play-guide-seen')")
        self.page.events.clear()
        try:
            self.page.send('Page.navigate', {'url': self.base + '/'})
            self.wait(f"document.querySelectorAll('.ls-list li').length === {self.level_count} && Boolean(document.getElementById('visitor-return-link'))", 30)
            self.assertNotIn('Landing test', self.js("document.getElementById('levels-screen').textContent"))
            self.assertEqual(self.js('location.pathname'), '/play')
            self.assertEqual(self.js("new URLSearchParams(location.search).get('visitor')"),self.js('machineSave().current'))
            self.assertEqual(self.js("document.querySelector('main').getBoundingClientRect().height"), 0)
            requests = [e['params']['request'] for e in self.page.events if e['method'] == 'Network.requestWillBeSent']
            ops = [json.loads(r['postData'])['op'] for r in requests if r['url'].endswith('/api/machine') and 'postData' in r]
            self.assertEqual(ops, ['levels'])
            self.assertFalse(self.js("document.getElementById('guide').open"))
            self.assertEqual(self.js("document.getElementById('guide').getBoundingClientRect().height"), 0)
            self.press('Play level 1, Mind the gap')
            self.wait(READY, 90)
            self.assertGreater(self.js("document.querySelector('main').getBoundingClientRect().height"), 0)
            self.assertEqual(self.js('location.pathname + location.search'), '/play?level=gap')
        finally:
            self.js("localStorage.removeItem('banjo-play-save')")

    def anonymous_levels(self, url=None, width=1280, height=860):
        self.page.send('Emulation.setDeviceMetricsOverride', {'width':width,'height':height,'deviceScaleFactor':1,'mobile':width!=1280})
        self.page.send('Emulation.setTouchEmulationEnabled', {'enabled':width!=1280,'maxTouchPoints':5})
        previous=self.js('performance.timeOrigin')
        response=self.page.send('Page.navigate',{'url':url or f'{self.base}/play'})
        self.assertFalse(response.get('errorText'),response)
        self.wait(f"performance.timeOrigin!=={previous} && document.getElementById('levels-screen')?.hidden===false && Boolean(document.getElementById('visitor-return-link'))",90)
        link=self.js("document.getElementById('visitor-return-link').href")
        visitor=parse_qs(urlsplit(link).query)['visitor'][0]
        self.assertEqual(str(uuid.UUID(visitor)),visitor,'Return links use canonical anonymous UUIDs')
        self.assertEqual(self.js('machineSave().current'),visitor)
        self.assertIsNone(self.js("document.getElementById('player-pick')"))
        self.assertFalse(self.js("[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='Add player')"))
        self.assertFalse(self.js("[...document.querySelectorAll('#levels-screen input')].some(e=>/player|your name/i.test(e.placeholder+' '+e.getAttribute('aria-label')))"))
        return visitor,link

    def anonymous_fixture_backup(self):
        self.anonymous_levels()
        return {'storage':self.js("Object.fromEntries(Object.entries(localStorage).filter(([key])=>key.startsWith('banjo-')))"),
                'cookies':self.page.send('Network.getCookies',{'urls':[self.base]})['cookies']}

    def anonymous_fixture_clear(self, clear_cookies=True):
        # A live page flushes its in-memory cache on pagehide. Park it first,
        # then clear the origin as browser settings would, with no old page
        # able to repopulate the intended fresh-device fixture.
        previous=self.js('performance.timeOrigin')
        parked=f'{self.base}/machine.css'
        self.page.send('Page.navigate',{'url':parked})
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            if self.js(f"location.href==={json.dumps(parked)} && performance.timeOrigin!=={previous}"):break
            time.sleep(.1)
        else:self.fail('The owned test browser did not leave the app before clearing its data')
        if clear_cookies:self.page.send('Network.clearBrowserCookies')
        self.js("Object.keys(localStorage).filter(k=>k.startsWith('banjo-')).forEach(k=>localStorage.removeItem(k))")

    def anonymous_storage_put(self, key, value):
        self.js(f'localStorage.setItem({json.dumps(key)},{json.dumps(value)})')

    def anonymous_fixture_restore(self, backup):
        self.anonymous_fixture_clear()
        for key,value in backup['storage'].items():self.anonymous_storage_put(key,value)
        cookies=[{k:v for k,v in cookie.items() if k in ('name','value','domain','path','secure','httpOnly','sameSite','expires') and not (k=='expires' and v<0)} for cookie in backup['cookies']]
        if cookies:self.page.send('Network.setCookies',{'cookies':cookies})

    def anonymous_cloud_saved(self):
        self.wait("(()=>{const s=window.machineProfileState?.();return s?.ready&&!s.pending&&!s.error;})()",30)

    def test_save_help_is_on_demand_and_keeps_the_design_and_focus(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            self.anonymous_levels(width=width,height=height)
            self.assertEqual(self.js("document.querySelectorAll('.save-help-panel:popover-open').length"),0)
            self.assertNotIn('Keep this link private',self.js("document.getElementById('levels-screen').innerText"))
            self.assertNotIn('restores progress',self.js("document.getElementById('levels-screen').innerText"))
            self.click_visible('About your return link')
            self.wait("Boolean(document.querySelector('.save-help-panel:popover-open'))",5)
            self.assertIn('Keep this link private',self.js("document.querySelector('.save-help-panel:popover-open').innerText"))
            self.assertTrue(self.js("(()=>{const r=document.querySelector('.save-help-panel:popover-open').getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight;})()"))
            self.click_visible('Close save help')
            self.assertEqual(self.js("document.activeElement.getAttribute('aria-label')"),'About your return link')
            self.click_visible('About your return link');self.key('Escape')
            self.assertEqual(self.js("document.querySelectorAll('.save-help-panel:popover-open').length"),0)
            self.assertEqual(self.js("document.activeElement.getAttribute('aria-label')"),'About your return link')
            self.click_visible('About your return link');self.click_visible('Copy return link')
            self.assertEqual(self.js("document.querySelectorAll('.save-help-panel:popover-open').length"),0,'Clicking outside dismisses the help')
            self.press('Sandbox: build anything');self.wait("document.getElementById('sandbox-screen').hidden===false",10)
            self.assertFalse(self.js("document.getElementById('sandbox-screen').innerText.includes('Save designs, reopen versions')"))
            self.press('Add New Design');self.wait(READY,60)
            self.anonymous_cloud_saved()
            before=self.js('machineDesign()');url=self.js('location.href')
            self.assertFalse(self.js("document.getElementById('design-status').textContent.includes('checkpoint')"))
            self.click_visible('About saving versions')
            self.assertIn('latest 30 checkpoints',self.js("document.querySelector('.save-help-panel:popover-open').innerText"))
            self.assertTrue(self.js("(()=>{const r=document.querySelector('.save-help-panel:popover-open').getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight;})()"))
            self.click_visible('Close save help')
            self.assertEqual(self.js('machineDesign()'),before)
            self.assertEqual(self.js('location.href'),url)
            self.assertEqual(self.js("document.activeElement.getAttribute('aria-label')"),'About saving versions')
            self.press('Save version')
            self.wait("document.getElementById('design-status').textContent==='Version 1 saved.'",10)
            self.anonymous_cloud_saved()
            self.assertEqual(len(self.js('machineDesign().versions')),1)

    def test_first_visit_has_anonymous_return_link_and_cookie_without_name_controls(self):
        backup=self.anonymous_fixture_backup()
        try:
            self.anonymous_fixture_clear()
            visitor,link=self.anonymous_levels()
            self.assertEqual(urlsplit(link).path,'/play')
            cookies=self.page.send('Network.getCookies',{'urls':[self.base]})['cookies']
            self.assertTrue(any(c['value']==visitor and c['httpOnly'] for c in cookies),'The server remembers the return identity in an HttpOnly cookie')
            for width,height in ((1280,860),(390,844),(844,390)):
                returned,_=self.anonymous_levels(width=width,height=height)
                self.assertEqual(returned,visitor)
                self.click_visible('Copy return link')
                self.wait("/Return link copied|copy its address/.test(document.querySelector('#levels-screen .visitor-return-status').textContent)",10)
            self.assertEqual(self.anonymous_levels(link)[0],visitor)
        finally:self.anonymous_fixture_restore(backup)

    def test_named_progress_migrates_to_isolated_anonymous_return_links(self):
        backup=self.anonymous_fixture_backup()
        try:
            self.anonymous_fixture_clear()
            self.anonymous_storage_put('banjo-play-save',json.dumps({'current':'Returning builder','players':{'Returning builder':{'levels':{'gap':{'stars':1,'energy_j':12300000}}},'Other builder':{'levels':{'gap':{'stars':3,'energy_j':28800000}}}}}))
            first,first_link=self.anonymous_levels()
            migrated=self.js('machineSave()')
            self.assertEqual(len(migrated['players']),2)
            for key in migrated['players']:self.assertEqual(str(uuid.UUID(key)),key)
            self.assertIn('Best win: 12.3 MJ',self.js("document.querySelector('.ls-list li').textContent"))
            self.assertNotIn('Returning builder',self.js("document.getElementById('levels-screen').textContent"))
            self.assertNotIn('Other builder',self.js("document.getElementById('levels-screen').textContent"))
            second=next(key for key in migrated['players'] if key!=first)
            second_link=f'{self.base}/play?visitor={second}'
            self.assertTrue(self.js(f"[...document.querySelectorAll('#levels-screen .previous-save')].some(a=>a.href==={json.dumps(second_link)})"))
            self.js(f"(()=>{{const a=[...document.querySelectorAll('#levels-screen .previous-save')].find(a=>a.href==={json.dumps(second_link)});a.closest('details').open=true;a.click();}})()")
            self.wait(f"window.machineSave?.().current==={json.dumps(second)} && document.querySelector('.ls-list li')?.textContent.includes('Best win: 28.8 MJ')",30)
            self.assertEqual(self.anonymous_levels()[0],second,'The Previous saves link updates the remembered cookie')
            self.assertIn('Best win: 28.8 MJ',self.js("document.querySelector('.ls-list li').textContent"))
            self.assertNotIn('12.3 MJ',self.js("document.querySelector('.ls-list li').textContent"))
            self.assertEqual(self.anonymous_levels(first_link)[0],first)
            self.assertIn('Best win: 12.3 MJ',self.js("document.querySelector('.ls-list li').textContent"))
            self.assertNotIn('28.8 MJ',self.js("document.querySelector('.ls-list li').textContent"))
            self.press('Play level 2, Cut it down');self.wait(READY,90)
            self.assertEqual(self.js('machineSave().current'),first)
        finally:self.anonymous_fixture_restore(backup)

    def test_return_url_and_cookie_reopen_saved_sandbox_versions(self):
        backup=self.anonymous_fixture_backup()
        try:
            self.anonymous_fixture_clear()
            visitor,link=self.anonymous_levels()
            self.test_legitimate_switch_handle_operation_can_win_with_actual_work()
            self.anonymous_cloud_saved()
            self.anonymous_levels()
            self.press('Sandbox: build anything')
            self.wait("document.getElementById('sandbox-screen')?.hidden===false",10)
            self.press('Add New Design');self.wait(READY,90)
            self.press('Add a marble');self.assertTrue(self.ghost()['fits'])
            self.press('Set it down');self.wait(f'!machineGhostState() && {READY}',60)
            self.press('Save version');self.wait('machineDesign().versions.length===1',10)
            design=self.js('machineDesign()');placed=self.js('machinePlacements()')
            self.anonymous_cloud_saved()
            original_page=self.page
            other=chrome_driver.Chrome(1280,860)
            try:
                self.page=other.page;self.page.send('Network.enable')
                self.assertEqual(self.page.send('Network.getCookies',{'urls':[self.base]})['cookies'],[],'A second browser has no identity or cached save')
                self.assertEqual(self.anonymous_levels(link)[0],visitor)
                self.assertGreater(self.js('machineSave().players[machineSave().current].levels["easy-switch"].stars'),0,'A real native win returns on the other device')
                self.press('Sandbox: build anything');self.wait("document.getElementById('sandbox-screen')?.hidden===false",10)
                self.press(f"Open design {design['name']}");self.wait(READY,90)
                self.assertEqual(self.js('machinePlacements()'),placed)
                self.assertEqual(self.js('machineDesign().versions'),design['versions'])
                self.anonymous_cloud_saved()
                self.anonymous_fixture_clear()
                separate,_=self.anonymous_levels()
                self.assertNotEqual(separate,visitor)
                self.assertEqual(self.js('machineSave().players[machineSave().current].levels'),{})
                self.assertFalse(self.js('machineSave().players[machineSave().current].sandbox?.items.length'))
                self.assertEqual(self.anonymous_levels(link)[0],visitor)
                self.assertGreater(self.js('machineSave().players[machineSave().current].levels["easy-switch"].stars'),0)
            finally:
                self.page=original_page;other.close()
            self.anonymous_fixture_clear()
            self.assertEqual(self.anonymous_levels(link)[0],visitor)
            self.press('Sandbox: build anything');self.wait("document.getElementById('sandbox-screen')?.hidden===false",10)
            self.press(f"Open design {design['name']}");self.wait(READY,90)
            self.assertEqual(self.js('machinePlacements()'),placed)
            self.assertEqual(self.js('machineDesign().versions'),design['versions'])
            self.page.send('Page.navigate',{'url':self.js('location.href')});self.wait(READY,90)
            self.assertEqual(self.js('machineSave().current'),visitor)
            self.assertEqual(self.js('machineDesign().versions'),design['versions'])
        finally:self.anonymous_fixture_restore(backup)

    def test_malformed_visitor_links_and_cookie_do_not_replace_saved_identity(self):
        backup=self.anonymous_fixture_backup()
        try:
            self.anonymous_fixture_clear()
            visitor,_=self.anonymous_levels()
            cookie=next(c for c in self.page.send('Network.getCookies',{'urls':[self.base]})['cookies'] if c['value']==visitor)
            for bad in ('not-a-uuid','__proto__','%3Cscript%3E','00000000-0000-0000-0000-00000000000'):
                self.assertEqual(self.anonymous_levels(f'{self.base}/play?visitor={bad}')[0],visitor)
                self.assertEqual(len(self.js('Object.keys(machineSave().players)')),1)
            self.page.send('Network.setCookie',{'name':cookie['name'],'value':'%E0%A4%A','url':self.base,'path':'/'})
            self.assertEqual(self.anonymous_levels()[0],visitor)
            self.assertEqual(len(self.js('Object.keys(machineSave().players)')),1)
        finally:self.anonymous_fixture_restore(backup)

    def test_cookie_only_recovery_keeps_saved_versions_without_orphan_previous_saves(self):
        backup=self.anonymous_fixture_backup()
        try:
            self.anonymous_fixture_clear()
            visitor,_=self.anonymous_levels()
            self.press('Sandbox: build anything');self.wait("document.getElementById('sandbox-screen')?.hidden===false",10)
            self.create_design('Cookie return')
            self.press('Save version');self.wait('machineDesign().versions.length===1',10)
            self.anonymous_cloud_saved();design=self.js('machineDesign()')
            self.anonymous_fixture_clear(clear_cookies=False)
            self.assertEqual(self.anonymous_levels()[0],visitor,'The server cookie alone restores the existing save')
            self.assertEqual(self.js('Object.keys(machineSave().players)'),[visitor])
            self.assertEqual(self.js("document.querySelectorAll('#levels-screen .previous-save').length"),0,'A temporary bootstrap ID must not become an orphan Previous save')
            self.press('Sandbox: build anything');self.wait("document.getElementById('sandbox-screen')?.hidden===false",10)
            self.press('Open design Cookie return');self.wait(READY,90)
            self.assertEqual(self.js('machineDesign().versions'),design['versions'])
        finally:self.anonymous_fixture_restore(backup)

    def test_large_unicode_design_is_acknowledged_and_recovers_in_a_fresh_browser(self):
        backup=self.anonymous_fixture_backup()
        try:
            self.anonymous_fixture_clear()
            visitor,link=self.anonymous_levels()
            self.press('Sandbox: build anything');self.wait("document.getElementById('sandbox-screen')?.hidden===false",10)
            self.create_design('Unicode declaration')
            self.js("""window.unicodeSaves=[];const original=window.fetch;
              window.fetch=async (...args)=>{let data;try{data=JSON.parse(args[1]?.body||'null');}catch{}
                const row=data?.op==='save'&&String(args[0]).endsWith('/api/profile')
                  ?{characters:args[1].body.length,bytes:new TextEncoder().encode(args[1].body).byteLength,keepalive:args[1].keepalive}:null;
                if(row)unicodeSaves.push(row);
                const response=await original(...args);if(row)row.status=response.status;return response;};
              document.getElementById('machine-data').open=true;
              const spec=JSON.parse(document.getElementById('spec').value);spec.description='水'.repeat(12000);
              document.getElementById('spec').value=JSON.stringify(spec);""")
            self.press('Build from this')
            self.wait(f"machineDesign().draft.base?.description==='水'.repeat(12000) && {READY}",60)
            self.press('Save version');self.wait('machineDesign().versions.length===1',10)
            self.anonymous_cloud_saved()
            requests=self.js('unicodeSaves')
            large=[r for r in requests if r['characters']<60000 and r['bytes']>65536]
            self.assertTrue(large,requests)
            self.assertTrue(all(r['keepalive'] is False and r.get('status')==200 for r in large),large)
            self.assertGreater(self.js('machineProfileState().revision'),0)
            original_page=self.page;other=chrome_driver.Chrome(1280,860)
            try:
                self.page=other.page;self.page.send('Network.enable')
                self.assertEqual(self.anonymous_levels(link)[0],visitor)
                self.press('Sandbox: build anything');self.wait("document.getElementById('sandbox-screen')?.hidden===false",10)
                self.press('Open design Unicode declaration');self.wait(READY,90)
                self.assertTrue(self.js("machineDesign().draft.base.description==='水'.repeat(12000)"))
                self.assertTrue(self.js("machineDesign().versions[0].draft.base.description==='水'.repeat(12000)"))
            finally:self.page=original_page;other.close()
        finally:self.anonymous_fixture_restore(backup)

    def test_the_free_build_has_every_piece_keeps_a_build_and_sets_out_the_example(self):
        # The levels screen's free build: every piece, no count, no goal. A
        # marble set down is kept for the player and is there again after a
        # reload. The example goes on the table and runs: the gate is opened
        # by a marble, and the marbles it held knock the dominoes down.
        self.page.send('Emulation.setDeviceMetricsOverride', {'width': 1280, 'height': 860, 'deviceScaleFactor': 1,
                                                              'mobile': False})
        self.page.send('Page.navigate', {'url': f'{self.base}/play'})
        self.wait("document.querySelector('.ls-free') && !document.getElementById('levels-screen').hidden", 90)
        self.press('Sandbox: build anything')
        self.wait("document.getElementById('sandbox-screen')?.hidden===false", 10)
        self.press('Add New Design')
        self.wait(READY, 90)
        # An empty table to start from, whatever this player built before.
        self.js('window.confirm = () => true')
        self.press('Clear the table')
        self.wait(f"window.machinePlacements().length === 0 && {READY}", 60)
        self.assertEqual(self.js("document.getElementById('title').textContent"), 'Untitled design')
        self.assertEqual(self.js("document.querySelectorAll('#tray button').length"), 1)
        self.press('Add a piece')
        self.assertGreaterEqual(self.js("document.querySelectorAll('#piece-grid button').length"), 11)
        self.assertNotIn('left', self.js("document.getElementById('piece-grid').textContent"))
        self.press('Back to sandbox')
        # Its chat builds from words; there is no level to place pieces for.
        self.assertEqual(self.js("document.getElementById('send').textContent"), 'Build it')
        self.assertTrue(self.js("document.getElementById('solve').hidden"))
        self.press('Add a marble')
        self.ghost()
        self.press('Set it down')
        self.wait("document.querySelectorAll('#placed li').length === 1 && /1 piece on the table/.test(document.getElementById('cost-line').textContent)", 60)
        self.page.send('Page.navigate', {'url': f'{self.base}/play?level=free'})
        self.wait(READY, 90)
        self.wait("document.querySelectorAll('#placed li').length === 1", 30)
        self.assertIn('your marble 1', self.js("document.getElementById('placed').textContent"))
        self.js('window.confirm = () => true')
        self.press('Set out the example')
        self.wait(f"document.querySelectorAll('#placed li').length === 11 && {READY}", 90)
        self.press('Run it')
        self.wait("(window.machineBodies()['your dominoes 11 6'] || [0, 1])[1] < 0.045", 60)
        self.assertTrue(self.js("document.getElementById('level-done').hidden"), 'no score: there is no goal')

    def test_sandbox_library_migrates_free_build_and_saves_reopens_and_restores_designs(self):
        # An old free build survives the upgrade. Two named designs keep
        # independent drafts, and checkpoints survive navigation/reloads.
        self.page.send('Page.navigate', {'url': f'{self.base}/machine'})
        self.wait("document.getElementById('sandbox-screen') && !document.getElementById('sandbox-screen').hidden", 60)
        old = self.js("localStorage.getItem('banjo-play-save')")
        cookies=self.page.send('Network.getCookies',{'urls':[self.base]})['cookies']
        self.anonymous_fixture_clear()
        self.anonymous_storage_put('banjo-play-save',json.dumps({'current':'Sandbox test','players':{'Sandbox test':{'levels':{},'free':{'placements':[{'piece':'marble','x_m':0,'z_m':0}]}}}}))
        try:
            self.page.send('Page.navigate', {'url': f'{self.base}/machine'})
            self.wait("document.getElementById('sandbox-screen') && !document.getElementById('sandbox-screen').hidden", 60)
            self.assertEqual(self.js("document.querySelectorAll('#prebuilt-designs button').length"), self.template_count)
            self.press('Open design My free build')
            self.wait(f"window.machinePlacements().length === 1 && {READY}", 60)
            self.press('Save version')
            self.wait("/Version 1 saved/.test(document.getElementById('design-status').textContent)", 10)
            first = self.js('window.machinePlacements()')
            self.js('window.confirm = () => true')
            self.press('Clear the table')
            self.wait(f"window.machinePlacements().length === 0 && {READY}", 60)
            self.press('Save version')
            self.wait("/Version 2 saved/.test(document.getElementById('design-status').textContent)", 10)
            self.page.send('Page.navigate', {'url': self.js('location.href')})
            self.wait(f"document.getElementById('clock') && {READY}", 60)
            self.assertEqual(self.js('window.machineDesign().versions.length'), 2)
            self.js("document.getElementById('design-versions').open = true; document.getElementById('version-pick').value = '1'")
            self.press('Restore version')
            self.wait(f"window.machinePlacements().length === 1 && {READY}", 60)
            self.assertEqual(self.js('window.machinePlacements()'), first)
            self.press('All designs')
            self.create_design('Second design')
            self.assertEqual(self.js('window.machinePlacements()'), [])
            self.press('All designs')
            self.press('Open design My free build')
            self.wait(f"window.machinePlacements().length === 1 && {READY}", 60)
            self.assertEqual(self.js("document.getElementById('title').textContent"), 'My free build')
            before = self.js('window.machineDesign().versions.length')
            self.anonymous_cloud_saved()
            revision = self.js('machineProfileState().revision')
            self.js("window.realStore = Storage.prototype.setItem; Storage.prototype.setItem = () => { throw new Error('storage full'); }")
            self.press('Save version')
            self.wait("/Version .* saved/.test(document.getElementById('design-status').textContent)", 10)
            self.anonymous_cloud_saved()
            self.assertEqual(self.js('window.machineDesign().versions.length'), before + 1)
            self.assertGreater(self.js('machineProfileState().revision'), revision,'The server acknowledged a new version despite a full local cache')
            kept = self.js('machineDesign()')
            visitor = self.js('machineSave().current')
            original_page=self.page
            other=chrome_driver.Chrome(1280,860)
            try:
                self.page=other.page;self.page.send('Network.enable')
                self.assertEqual(self.anonymous_levels(f'{self.base}/play?visitor={visitor}')[0],visitor)
                self.press('Sandbox: build anything');self.wait("document.getElementById('sandbox-screen')?.hidden===false",10)
                self.press('Open design My free build');self.wait(READY,90)
                self.assertEqual(self.js('machineDesign().versions'),kept['versions'])
                self.assertEqual(self.js('machinePlacements()'),first)
            finally:
                self.page=original_page;other.close()
            self.js('Storage.prototype.setItem = window.realStore')
            # Saving a refused setup must not create a green checkpoint.
            self.js("window.confirm = () => true; document.getElementById('design-versions').open = false")
            self.press('Add a plank')
            self.ghost()
            self.press('Save version')
            self.assertIn('Set your plank down first', self.js("document.getElementById('verdict').textContent"))
        finally:
            self.anonymous_fixture_restore({'storage':{'banjo-play-save':old} if old is not None else {},'cookies':cookies})

    def test_sandbox_chain_keeps_readings_tray_additions_and_base_in_shared_versions(self):
        self.page.send('Page.navigate', {'url': f'{self.base}/machine'})
        self.wait("Boolean(document.getElementById('prebuilt-designs'))", 60)
        self.press('Start from Chain reaction')
        self.wait(READY, 60)
        self.assertEqual(self.js("document.querySelectorAll('#stations li').length"), 9)

        self.assertFalse(self.js("document.getElementById('engine-readings').hidden"))
        self.press('Add a marble')
        self.ghost()
        self.slide('x of your marble 1', -1.8)
        self.slide('across (z, m) of your marble 1', -1.8)
        self.assertTrue(self.ghost()['fits'])
        self.press('Set it down')
        self.wait(f"window.machinePlacements().length === 1 && {READY}", 60)
        self.press('Save version')
        self.wait("/Version 2 saved/.test(document.getElementById('design-status').textContent)", 10)
        base = self.js('window.machineDesign().draft.base')
        self.js('window.confirm = () => true')
        self.press('Clear the table')
        self.wait(f"window.machinePlacements().length === 0 && {READY}", 60)
        self.assertIsNone(self.js('window.machineDesign().draft.base'))
        self.press('Undo')
        self.wait(f"window.machinePlacements().length === 1 && {READY}", 60)
        self.assertEqual(self.js('window.machineDesign().draft.base'), base)
        self.press('Share this design')
        self.wait("/#build=/.test(window.machineShareLink())", 10)
        link = self.js('window.machineShareLink()')
        self.page.send('Page.navigate', {'url': link})
        self.wait(f"document.getElementById('clock') && {READY}", 60)
        self.assertEqual(self.js('window.machineDesign().draft.base'), base)
        self.assertEqual(self.js('window.machinePlacements().length'), 1)
        self.press('Run it')
        self.wait("/World 2\\./.test(document.getElementById('clock').textContent)", 30)
        self.press('Pause')
        self.assertTrue(self.js("document.getElementById('level-done').hidden"))
        self.press('Set up again')
        self.wait(READY, 60)
        self.assertEqual(self.js("document.querySelectorAll('#stations li').length"), 9)


    def test_piece_library_search_filter_cancel_and_placement_on_desktop_and_phones(self):
        for width, height in ((1280, 860), (390, 844), (844, 390)):
            with self.subTest(viewport=(width, height)):
                self.page.send('Emulation.setDeviceMetricsOverride', {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': width != 1280})
                self.page.send('Page.navigate', {'url': f'{self.base}/machine'})
                self.wait("Boolean(document.querySelector('#prebuilt-designs button'))", 60)
                self.press('Start from Gate and split')
                self.wait(READY, 60)
                before = self.js('window.machinePlacements()')
                self.assertEqual(self.js("document.querySelectorAll('#tray button').length"), 1)
                self.press('Add a piece')
                self.assertTrue(self.js("document.getElementById('piece-picker').open"))
                self.assertTrue(self.js("Boolean(document.getElementById('tray').closest('#control-panel'))"))
                self.wait("[...document.querySelectorAll('#piece-grid img')].every(i => i.complete && i.naturalWidth >= 300)", 30)
                bounds = self.js("""(() => {const d=document.getElementById('piece-picker').getBoundingClientRect();
                    const c=document.getElementById('piece-picker-close').getBoundingClientRect();
                    return {x:d.x,y:d.y,w:d.width,h:d.height,closeRight:c.right,closeBottom:c.bottom,closeHeight:c.height};})()""")
                self.assertEqual((bounds['x'], bounds['y'], bounds['w'], bounds['h']), (0, 0, width, height))
                self.assertGreaterEqual(bounds['closeHeight'], 44)
                self.assertLessEqual(bounds['closeRight'], width)
                self.assertLessEqual(bounds['closeBottom'], height)
                cards = self.js("[...document.querySelectorAll('#piece-grid .piece-card')].map(b=>{const r=b.getBoundingClientRect();return {name:b.textContent,w:r.width,h:r.height,left:r.left,right:r.right};})")
                self.assertTrue(all(r['w'] >= 140 and r['h'] >= 180 and r['left'] >= 0 and r['right'] <= width for r in cards), cards)
                # Modal keyboard focus cannot escape to the live scene.
                self.js("document.getElementById('piece-picker-close').focus()")
                self.page.send('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'Tab', 'code': 'Tab', 'windowsVirtualKeyCode': 9, 'modifiers': 8})
                self.page.send('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'Tab', 'code': 'Tab', 'windowsVirtualKeyCode': 9, 'modifiers': 8})
                self.assertTrue(self.js("Boolean(document.activeElement.closest('#piece-picker'))"))
                self.slide('Search pieces', 'gate')
                self.assertEqual(self.js("[...document.querySelectorAll('#piece-grid strong')].map(e=>e.textContent)"), ['track', 'shelf'])
                self.slide('Category', 'power')
                self.assertFalse(self.js("document.getElementById('piece-empty').hidden"))
                self.slide('Search pieces', '')
                self.assertEqual(self.js("[...document.querySelectorAll('#piece-grid strong')].map(e=>e.textContent)"), ['cannon', 'steam'])
                self.press('Back to sandbox')
                self.assertEqual(self.js('window.machinePlacements()'), before)
                self.assertIsNone(self.js('window.machineGhostState()'))
                self.wait("document.activeElement.getAttribute('aria-label') === 'Add a piece'", 5)
                self.press('Add a piece')
                self.assertEqual(self.js("document.querySelectorAll('#piece-grid .piece-card').length"), self.piece_count)
                self.key('Escape')
                self.assertFalse(self.js("document.getElementById('piece-picker').open"))
                self.assertEqual(self.js('window.machinePlacements()'), before)
                self.press('Add a marble')
                self.assertFalse(self.js("document.getElementById('piece-picker').open"))
                self.assertEqual(self.ghost()['p']['piece'], 'marble')
                self.slide('x of your marble 12', -1.8)
                self.slide('across (z, m) of your marble 12', -1.8)
                self.assertTrue(self.ghost()['fits'])
                self.press('Set it down')
                self.wait(f"window.machinePlacements().length === 12 && {READY}", 60)
                self.assertEqual(self.js('window.machinePlacements()')[:11], before)
                self.press('Run it')
                self.wait("/World 2\\./.test(document.getElementById('clock').textContent)", 30)
                self.press('Pause')
                self.press('Set up again')
                self.wait(READY, 60)
                self.assertEqual(self.js('window.machinePlacements().length'), 12)

    def test_sandbox_library_and_controls_fit_phone_portrait_and_landscape(self):
        for width, height in ((390, 844), (844, 390)):
            with self.subTest(viewport=(width, height)):
                self.page.send('Emulation.setDeviceMetricsOverride', {'width': width, 'height': height, 'deviceScaleFactor': 2, 'mobile': True})
                self.page.send('Page.navigate', {'url': f'{self.base}/machine'})
                self.wait("Boolean(document.querySelector('#prebuilt-designs button'))", 60)
                self.assertLessEqual(self.js('document.body.scrollWidth'), width)
                self.assertTrue(self.js("[...document.querySelectorAll('#sandbox-screen button')].filter(b=>b.offsetParent!==null).every(b => b.getBoundingClientRect().height >= 44 && b.getBoundingClientRect().right <= innerWidth)"))
                self.press('Start from Gate and split')
                self.wait(READY, 60)
                self.assertLessEqual(self.js('document.body.scrollWidth'), width)
                for selector in ('#start', '#reset', '#pull-tool', '#attach-tool'):
                    self.reveal_control(f"document.querySelector('{selector}')")
                    box = self.js(f"(() => {{const r=document.querySelector('{selector}').getBoundingClientRect();return {{h:r.height,x:r.x,right:r.right,top:r.top,bottom:r.bottom}};}})()")
                    scene = self.js("(() => {const r=document.querySelector('#view').getBoundingClientRect();return {top:r.top,bottom:r.bottom};})()")
                    self.assertGreaterEqual(box['h'], 44)
                    self.assertGreaterEqual(box['x'], 0)
                    self.assertLessEqual(box['right'], width)
                    self.assertGreaterEqual(box['top'], 0)
                    self.assertLessEqual(box['bottom'], height, (selector,box))
                    self.assertTrue(self.js(f"Boolean(document.querySelector('{selector}').closest('#control-panel,#phone-toolbar'))"))
                self.press('All designs')

    def test_a_track_snaps_to_another_and_pieces_are_copied_undone_and_joined(self):
        # A second track put at the first's far end snaps under it. A piece
        # is copied, a change taken back and put back, and two parts are tied
        # by a string with Attach.
        self.page.send('Emulation.setDeviceMetricsOverride', {'width': 1280, 'height': 860, 'deviceScaleFactor': 1,
                                                              'mobile': False})
        self.page.send('Page.navigate', {'url': f'{self.base}/play?level=free'})
        self.wait(f"document.getElementById('clock') && {READY}", 90)
        self.js('window.confirm = () => true')
        self.press('Clear the table')
        self.wait(f"window.machinePlacements().length === 0 && {READY}", 60)
        self.wait('window.machineCamera().settled', 30)
        self.press('Add a track')
        self.ghost()
        self.press('Set it down')
        self.wait(f"window.machinePlacements().length === 1 && {READY}", 60)
        first = self.js('window.machinePlacements()[0]')
        far = [first['x_m'] + first['run_m'], first['top_height_m'] - first['drop_m'], first['z_m']]
        self.press('Add a track')
        self.ghost()
        # Start out of the way, then drag the actual ghost to the far end.
        self.slide('top end x of your track 2', -0.5)
        self.ghost()
        self.drag_ghost_to(far[0],far[2])
        self.wait("(() => { const g = window.machineGhostState(); return g && g.answered && !g.busy && "
                  "/joined to far end of your track 1/.test(document.querySelector('#ghost-bar .state').textContent); })()", 20)
        p = self.ghost()['p']
        self.assertAlmostEqual(p['x_m'], far[0] + 0.03, delta=0.011)
        self.assertAlmostEqual(p['top_height_m'], far[1] - 0.04, delta=0.011)
        self.press('Set it down')
        self.wait(f"window.machinePlacements().length === 2 && {READY}", 60)
        # A copy is a new ghost of it, 10 cm along; thrown away, nothing changes.
        self.press('Copy your track 2')
        self.assertEqual(self.ghost()['index'], 2)
        self.assertAlmostEqual(self.ghost()['p']['x_m'], p['x_m'] + 0.1, delta=0.011)
        self.press('Throw the ghost away')
        self.press('Remove your track 2')
        self.wait('window.machinePlacements().length === 1', 10)
        self.press('Undo')
        self.wait('window.machinePlacements().length === 2', 10)
        self.press('Redo')
        self.wait('window.machinePlacements().length === 1', 10)
        self.press('Undo')
        self.wait(f"window.machinePlacements().length === 2 && {READY}", 60)
        # Attach: the first track to the second, by a string.
        self.press('🔗 Attach')
        for name in ('your track 1', 'your track 2'):
            x, y = self.js(f'window.machineBodyScreen({json.dumps(name)})')
            self.mouse('mousePressed', x, y)
            self.mouse('mouseReleased', x, y)
            time.sleep(0.2)
        self.wait('window.machineAttachState().card', 10)
        self.assertIn('Both are fixed', self.js("document.getElementById('attach-card').textContent"),
                      'two fixed parts: a join would move nothing')
        self.press('Cancel')
        self.press('Add a marble')
        self.ghost()
        self.press('Set it down')
        self.wait(f"window.machinePlacements().length === 3 && {READY}", 60)
        self.press('🔗 Attach')
        for name in ('your track 1', 'your marble 3'):
            x, y = self.js(f'window.machineBodyScreen({json.dumps(name)})')
            self.mouse('mousePressed', x, y)
            self.mouse('mouseReleased', x, y)
            time.sleep(0.2)
        self.wait('window.machineAttachState().card', 10)
        self.press('Tie them with a string')
        self.wait(f"window.machinePlacements().length === 4 && {READY}", 60)
        link = self.js('window.machinePlacements()[3]')
        # Whatever part of the track was pressed first: its board or the rail in front of it.
        self.assertEqual((link['piece'], link['kind'], link['b']), ('link', 'string', 'your marble 3'))
        self.assertTrue(link['a'].startswith('your track 1'), link['a'])
        said = self.js("document.getElementById('placed').textContent")
        self.assertIn(f"A string between {link['a']} and your marble 3", said)
        # Taking away the first track takes its string with it, and the
        # others move up one.
        self.press('Remove your track 1')
        self.wait('window.machinePlacements().length === 2', 10)
        self.assertEqual([q['piece'] for q in self.js('window.machinePlacements()')], ['track', 'marble'])

    def test_a_build_is_shared_by_a_link(self):
        # The example, shared: the link holds every piece, and opening it on
        # an empty table sets them all out.
        self.page.send('Emulation.setDeviceMetricsOverride', {'width': 1280, 'height': 860, 'deviceScaleFactor': 1,
                                                              'mobile': False})
        self.page.send('Page.navigate', {'url': f'{self.base}/play?level=free'})
        self.wait(f"document.getElementById('clock') && {READY}", 90)
        self.js('window.confirm = () => true')
        self.press('Set out the example')
        self.wait(f"window.machinePlacements().length === 11 && {READY}", 60)
        made = self.js('window.machinePlacements()')
        self.press('Share this design')
        self.wait("/#build=z/.test(window.machineShareLink())", 10)
        link = self.js('window.machineShareLink()')
        self.press('Clear the table')
        self.wait(f"window.machinePlacements().length === 0 && {READY}", 60)
        self.page.send('Page.navigate', {'url': link})
        self.wait(f"typeof window.machinePlacements === 'function' && window.machinePlacements().length === 11 && {READY}", 90)
        self.assertEqual(self.js('window.machinePlacements()'), made)
        self.assertNotIn('#build', self.js('location.href'), 'the link is read once')
        self.assertEqual(self.js("document.getElementById('send').textContent"), 'Build it', 'the chat builds here')
        # Links made before named designs held an array, not a declaration.
        packed = base64.urlsafe_b64encode(json.dumps(made).encode()).decode().rstrip('=')
        self.page.send('Page.navigate', {'url': f'{self.base}/play?level=free#build=j{packed}'})
        self.wait(f"typeof window.machinePlacements === 'function' && window.machinePlacements().length === 11 && {READY}", 90)
        self.assertEqual(self.js('window.machinePlacements()'), made)

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

    def test_what_is_hidden_is_not_drawn_on_a_level_or_in_the_free_build(self):
        # The page hides things with the hidden attribute. A class that sets
        # display beats the attribute unless the stylesheet says otherwise:
        # level 1 showed the free build's Set out the example, Share this build
        # and Clear the table. Nothing hidden may take up any room.
        drawn = ("[...document.querySelectorAll('[hidden]')]"
                 ".filter(e => e.getClientRects().length).map(e => e.id || e.className)")
        self.open('gap')
        self.assertTrue(self.js("document.getElementById('free-actions').hidden"))
        self.assertEqual(self.js(drawn), [])
        self.page.send('Page.navigate', {'url': f'{self.base}/play?level=free'})
        self.wait(READY, 90)
        self.assertFalse(self.js("document.getElementById('free-actions').hidden"))
        self.assertEqual(self.js(drawn), [])

    def test_energy_against_par_is_said_while_a_piece_is_changed_and_on_a_win_over_par(self):
        # Level 1: a 0.78 m plank still bridges the gap, and takes 34.1 MJ to
        # make, 3.5 MJ over par. The ghost's bar says so as it is cut; the win
        # card says what each piece took and how much lighter reaches par.
        self.open('gap')
        self.press('Add a plank')
        self.ghost()
        self.slide('Cut to length of your plank 1', 0.78)
        self.slide('Set down at x of your plank 1', 0.3)
        self.slide('across (z, m) of your plank 1', 0.0)
        self.ghost()
        self.wait("/over par \\(30.6 MJ\\)/.test(document.querySelector('#ghost-bar .state').title)", 10)
        self.assertIn('34.1 MJ to make', self.js("document.querySelector('#ghost-bar .state').title"))
        self.press('Set it down')
        self.wait('!window.machineGhostState()', 5)
        self.wait(READY, 60)
        self.press('Run it')
        self.wait("!document.getElementById('level-done').hidden", 60)
        done = self.js("document.getElementById('level-done').textContent")
        self.assertIn('Your plank 1: 3.28 kg, 34.1 MJ', done)
        self.assertIn('your plank 1 about 11% lighter', done)
        # Details start folded away, then remain readable on desktop and on
        # a phone in either orientation, with the next actions reachable.
        self.assertTrue(self.js("document.getElementById('level-done-energy').hidden"))
        self.assertEqual(self.js("document.querySelector('#level-done .how-open').getAttribute('aria-expanded')"), 'false')
        self.press('Energy details')
        self.assertEqual(self.js("document.querySelector('#level-done .how-open').getAttribute('aria-expanded')"), 'true')
        for width, height in ((1280, 860), (390, 844), (844, 390)):
            with self.subTest(viewport=(width, height)):
                self.page.send('Emulation.setDeviceMetricsOverride',
                               {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': width != 1280})
                self.wait("(() => { const b = document.getElementById('level-done').getBoundingClientRect(); "
                          "const v = document.getElementById('view').getBoundingClientRect(); "
                          "return b.top >= v.top && b.bottom <= v.bottom + 1; })()", 10)
                self.assertIn('Your plank 1: 3.28 kg, 34.1 MJ',
                              self.js("document.getElementById('level-done-energy').innerText"))
                self.js("document.querySelector('#level-done .actions').scrollIntoView({block: 'nearest'})")
                self.assertTrue(self.js("[...document.querySelectorAll('#level-done .actions button')].every(b => { "
                                        "const r = b.getBoundingClientRect(), p = document.getElementById('level-done').getBoundingClientRect(); "
                                        "return r.left >= p.left && r.right <= p.right && r.top >= p.top && r.bottom <= p.bottom; })"))
        self.press('Energy details')
        self.assertTrue(self.js("document.getElementById('level-done-energy').hidden"))

    def test_view_move_buttons_stay_in_the_scene_corner_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390),(320,568)):
            with self.subTest(viewport=(width,height)):
                self.open('cut',width,height,phone=width!=1280)
                self.press('Add a knife'); p0=self.ghost()['p']
                self.assertEqual(self.js("document.getElementById('mode-move').getAttribute('aria-pressed')"),'true')
                self.assertEqual(self.js("document.querySelectorAll('#move-pad .mode').length"),0)
                geometry=self.js("(() => {const r=document.getElementById('scene-mode').getBoundingClientRect(),v=document.getElementById('view').getBoundingClientRect();return {left:r.left-v.left,bottom:v.bottom-r.bottom,right:r.right<=v.right,top:r.top>=v.top};})()")
                self.assertEqual(geometry,{'left':10,'bottom':10,'right':True,'top':True})
                if width!=1280: self.click_visible('Help')
                self.click_visible('View')
                self.assertIn('looking',self.js("document.getElementById('view').className"))
                self.assertEqual(self.js("document.getElementById('mode-view').getAttribute('aria-pressed')"),'true')
                self.assertEqual(self.ghost()['p'],p0)
                self.click_visible('Move')
                self.assertNotIn('looking',self.js("document.getElementById('view').className"))
                self.assertEqual(self.js("document.getElementById('mode-view').getAttribute('aria-pressed')"),'false')
                self.assertEqual(self.ghost()['p'],p0)
                self.key('Escape')
                self.assertEqual(self.js("document.getElementById('mode-view').getAttribute('aria-pressed')"),'true')
                self.click_visible('Move'); self.press('Cancel')
                self.assertTrue(self.js("document.getElementById('scene-mode').hidden"))

    def test_fine_ground_grid_gently_snaps_dragging_but_precision_stays_free(self):
        for width,height in ((1280,860),(390,844),(844,390),(320,568)):
            with self.subTest(viewport=(width,height)):
                self.open('cut',width,height,phone=width!=1280)
                self.press('Add a knife'); self.ghost()
                if not self.js('window.machinePlacementGrid().enabled'):
                    self.click_visible('Snap to grid')
                # Keep the grabbed knife in view before testing tiny moves;
                # an off-screen press is not a piece drag on a narrow phone.
                self.slide('Pivot x of your knife 1',.1)
                self.slide('Pivot z of your knife 1',.1)
                self.ghost()
                self.js('window.machineView({azimuth:0,elevation:.8,distance:1.4,at:[.2,1,.2]})')
                self.wait('window.machineCamera().settled',20)
                grid=self.js('window.machinePlacementGrid()')
                self.assertEqual(grid['step_m'],.05);self.assertEqual(grid['major_step_m'],.5)
                self.assertEqual(grid['fine_vertices'],804);self.assertEqual(grid['major_vertices'],324)
                self.assertTrue(grid['visible'] and grid['fine_opacity']>0,grid)
                before=self.ghost()['p']
                snapped=self.drag_ghost_to(.307,.207,touch=width!=1280)['p']
                self.assertAlmostEqual(snapped['x_m'],.3,delta=1e-6)
                self.assertAlmostEqual(snapped['z_m'],.2,delta=1e-6)
                for key,value in before.items():
                    if key not in ('x_m','z_m'):
                        self.assertEqual(snapped[key],value,'ground snapping cannot change height, angle or dimensions')
                self.wait("window.machinePlacementGrid().marker",5)
                self.assertEqual(self.js('window.machinePlacementGrid().aligned'),['x','z'])
                self.assertIn('aligned',self.js("document.getElementById('grid-snap-status').textContent"))
                # Outside the short release band the drag is free, not forced
                # to a crossing. The knife retains its 1cm x / 5mm z steps.
                released=self.drag_ghost_to(.327,.237,touch=width!=1280)['p']
                self.assertAlmostEqual(released['x_m'],.33,delta=1e-6)
                self.assertAlmostEqual(released['z_m'],.235,delta=1e-6)
                self.assertEqual(self.js('window.machinePlacementGrid().aligned'),[])
                self.click_visible('Snap to grid')
                self.assertEqual(self.ghost()['p'],released,'turning snapping off cannot reposition the piece')
                free=self.drag_ghost_to(.407,.307,touch=width!=1280)['p']
                self.assertAlmostEqual(free['x_m'],.41,delta=1e-6)
                self.assertAlmostEqual(free['z_m'],.305,delta=1e-6)
                self.assertFalse(self.js('window.machinePlacementGrid().enabled'))
                self.click_visible('Snap to grid')
                self.assertEqual(self.ghost()['p'],free,'turning snapping on is not a placement command')
                if width==1280:
                    bottom=self.js('window.machineGhostScreen().bottom')
                    self.drag(self.screen_point([free['x_m'],bottom,free['z_m']]),self.screen_point([.507,bottom,.407]),modifiers=1)
                    bypass=self.ghost()['p']
                    self.assertAlmostEqual(bypass['x_m'],.51,delta=1e-6)
                    self.assertAlmostEqual(bypass['z_m'],.405,delta=1e-6)
                    self.assertEqual(self.js('window.machinePlacementGrid().aligned'),[],'Alt bypasses snapping for this drag')
                self.slide('Pivot x of your knife 1',.31)
                self.slide('Pivot z of your knife 1',.23)
                precise=self.ghost()['p']
                self.assertEqual((precise['x_m'],precise['z_m']),(.31,.23),'precision controls do not round to the grid')
                self.assertEqual(self.js('window.machinePlacementGrid().aligned'),[])
                self.click_visible('Snap to grid')
                self.press('Set it down');self.wait(READY,60)
                self.assertEqual(self.js('window.machinePlacements()[0]'),precise)
                self.press('Pick up your knife 1')
                self.assertEqual(self.ghost()['p'],precise,'picking up an existing piece must not quantize its position')
                self.press('Cancel')
                self.page.send('Page.reload',{})
                self.wait(f"{READY} && typeof window.machinePlacementGrid==='function'",60)
                self.assertFalse(self.js('window.machinePlacementGrid().enabled'),'the free-placement preference survives reload')

        # Saved sandbox declarations and version restores stay exact even
        # when grid assistance is enabled. Ordinary levels reset on reload.
        self.page.send('Page.navigate',{'url':self.base+'/machine'})
        self.wait("document.getElementById('sandbox-screen')?.hidden===false",60)
        self.create_design('Fine placement')
        self.press('Add a knife');self.ghost()
        self.click_visible('Snap to grid')
        self.slide('Position along (m) of your knife 1',.31)
        self.slide('Position across (m) of your knife 1',.23)
        kept=self.ghost()['p']
        self.press('Set it down');self.wait(f"!window.machineGhostState() && {READY}",60)
        self.press('Save version')
        self.wait("/Version 1 saved/.test(document.getElementById('design-status').textContent)",10)
        self.anonymous_cloud_saved()
        self.page.send('Page.reload',{})
        self.wait(f"{READY} && window.machinePlacements().length===1",60)
        self.assertEqual(self.js('window.machinePlacements()[0]'),kept)
        self.press('Pick up your knife 1');self.ghost()
        self.slide('Position along (m) of your knife 1',.43)
        self.ghost()
        self.press('Set it down');self.wait(f"!window.machineGhostState() && {READY}",60)
        self.js("document.getElementById('design-versions').open=true;document.getElementById('version-pick').value='1'")
        self.press('Restore version');self.wait(f"window.machinePlacements()[0]?.x_m===.31 && {READY}",60)
        self.assertEqual(self.js('window.machinePlacements()[0]'),kept)

    def test_scene_clicks_and_subthreshold_drags_do_not_relocate_and_background_drags_rotate(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('laser',width,height,phone=width!=1280)
                self.press('Add a mirror');before=self.ghost()['p']
                x,y=self.empty_scene_point()
                if width==1280:
                    self.mouse('mousePressed',x,y);self.mouse('mouseReleased',x,y)
                else:
                    self.page.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x,'y':y,'id':1}]})
                    self.page.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
                self.assertEqual(self.ghost()['p'],before,'an empty scene click/tap cannot relocate the ghost')
                self.assertEqual(self.js("document.getElementById('mode-view').getAttribute('aria-pressed')"),'true')
                box=self.js('window.machineGhostScreen()')
                x,y=box['x1']+25,(box['y0']+box['y1'])/2
                turned=self.js('window.machineCamera().azimuth')
                self.drag([x,y],[x+5,y],touch=width!=1280,steps=1)
                self.assertEqual(self.ghost()['p'],before,'a 5px motion remains below the 6px drag threshold')
                self.assertEqual(self.js('window.machineCamera().azimuth'),turned)
                self.drag([x,y],[x+7,y],touch=width!=1280,steps=1)
                moved=self.ghost()['p']
                self.assertNotEqual(moved,before,'a 7px near-piece drag moves it from View')
                self.assertEqual(self.js('window.machineCamera().azimuth'),turned)
                self.assertEqual(self.js("document.getElementById('mode-move').getAttribute('aria-pressed')"),'true')
                x,y=self.empty_scene_point()
                self.drag([x,y],[x-60,y],touch=width!=1280)
                self.assertEqual(self.ghost()['p'],moved,'an empty scene drag cannot relocate it in Move')
                self.assertNotEqual(self.js('window.machineCamera().azimuth'),turned)
                if width==1280:
                    x,y=self.empty_scene_point()
                    self.mouse('mousePressed',x,y)
                    for px in (x-20,x):
                        self.page.send('Input.dispatchMouseEvent',{'type':'mouseMoved','x':px,'y':y,'button':'left','buttons':1})
                    self.mouse('mouseReleased',x,y)
                    self.assertEqual(self.ghost()['p'],moved,'an out-and-back background drag cannot relocate it')
                    self.assertEqual(self.js("document.getElementById('mode-move').getAttribute('aria-pressed')"),'true',
                                     'a drag ending where it began is still a drag, not a View click')

    def test_near_piece_drag_moves_in_view_and_secondary_drag_rotates_without_relocating(self):
        self.open('cut')
        self.press('Add a knife')
        p0 = self.ghost()['p']
        time.sleep(0.4)
        box = self.js('window.machineGhostScreen()')
        x, y = (box['x0'] + box['x1']) / 2, (box['y0'] + box['y1']) / 2

        self.click_visible('View')
        self.assertIn('looking', self.js("document.getElementById('view').className"))
        turned = self.js('window.machineCamera().azimuth')
        self.drag([x,y],[x+96,y])
        self.assertNotEqual(self.ghost()['p']['x_m'],p0['x_m'],'a primary drag near the piece moves it even in View')
        self.assertEqual(self.js('window.machineCamera().azimuth'),turned)
        for button,modifiers in (('right',0),('middle',0),('left',2)):
            box=self.js('window.machineGhostScreen()')
            x,y=(box['x0']+box['x1'])/2,(box['y0']+box['y1'])/2
            before=self.ghost()['p'];turned=self.js('window.machineCamera().azimuth')
            self.drag([x,y],[x+64,y],button=button,modifiers=modifiers)
            self.assertEqual(self.ghost()['p'],before,f'{button} drag with modifiers={modifiers} near the piece cannot move it')
            self.assertNotEqual(self.js('window.machineCamera().azimuth'),turned)
        self.click_visible('View')
        self.key('Escape')
        self.assertNotIn('looking', self.js("document.getElementById('view').className"), 'Esc: back to Move')
        self.assertTrue(self.js('Boolean(window.machineGhostState())'), 'the knife is still there to place')
        box = self.js('window.machineGhostScreen()')
        x, y = (box['x0'] + box['x1']) / 2, (box['y0'] + box['y1']) / 2
        self.drag([x,y],[x+96,y])
        self.assertNotEqual(self.ghost()['p']['x_m'],p0['x_m'],'in Move, the drag moves it')

    def test_zoom_during_a_held_piece_drag_does_not_relocate_a_stationary_pointer(self):
        self.open('laser')
        self.press('Add a mirror');self.ghost()
        box=self.js('window.machineGhostScreen()')
        x,y=box['x1']+25,(box['y0']+box['y1'])/2
        self.mouse('mousePressed',x,y)
        self.page.send('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x+20,'y':y,'button':'left','buttons':1})
        before=self.ghost()['p'];distance=self.js('window.machineCamera().distance')
        self.page.send('Input.dispatchMouseEvent',{'type':'mouseWheel','x':x+20,'y':y,'deltaX':0,'deltaY':-120,'button':'left','buttons':1})
        self.wait(f'window.machineCamera().distance < {distance}',5)
        self.page.send('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x+20,'y':y,'button':'left','buttons':1})
        self.assertEqual(self.ghost()['p'],before,'zooming with the pointer held still cannot relocate the piece')
        self.page.send('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x+60,'y':y,'button':'left','buttons':1})
        self.mouse('mouseReleased',x+60,y)
        self.assertNotEqual(self.ghost()['p'],before,'an intentional pointer movement still works after zooming')

    def test_a_part_pulled_by_hand_is_a_test_and_earns_nothing(self):
        # Level 5 with no ramp: Pull on, the lever's end pulled down -- the
        # engine's force at that point, no hand in the world. The ratchet
        # catches, the contact closes, the cannon fires and the block goes in.
        # A run pulled by hand tests the parts; it is not a win, and nothing
        # of it is kept.
        self.open('chain')
        self.js("window.machineView({azimuth: -0.2, elevation: 0.35, distance: 2.2, at: [0.4, 0.15, 0]})")
        time.sleep(1.5)
        x, y = self.screen_point([0.15, 0.16, 0.0])
        self.press('🖐 Pull')
        self.mouse('mouseMoved', x, y)
        self.mouse('mousePressed', x, y)
        for k in range(1, 16):
            self.page.send('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x, 'y': y + 12 * k,
                                                        'button': 'left', 'buttons': 1})
            time.sleep(0.04)
        self.wait("Boolean(window.machinePullState()) && window.machinePullState().force_n > 50", 10)
        self.wait("!document.getElementById('level-done').hidden", 60)
        self.mouse('mouseReleased', x, y + 180)
        done = self.js("document.getElementById('level-done').textContent")
        self.assertIn('A test run', done)
        self.assertIn('the goal happened', done)
        self.assertNotIn('chain', self.js("Object.keys(window.machineSave().players[window.machineSave().current].levels)"))

    def test_a_second_finger_releases_the_pull_before_turning_the_camera(self):
        self.open('chain')
        self.js("window.machineView({azimuth: -0.2, elevation: 0.35, distance: 2.2, at: [0.4, 0.15, 0]})")
        self.wait('window.machineCamera().settled',30)
        x,y=self.screen_point([0.15,0.16,0])
        self.press('🖐 Pull')
        self.page.send('Network.enable'); self.page.events.clear()
        touch=lambda kind,points:self.page.send('Input.dispatchTouchEvent',{'type':kind,'touchPoints':points})
        touch('touchStart',[{'x':x,'y':y,'id':1}])
        self.wait('Boolean(window.machinePullState())',5)
        touch('touchMove',[{'x':x,'y':y+12,'id':1}])
        self.wait('window.machinePullState().force_n > 0',5)
        def pull_requests():
            self.js('true')  # Drain pending network events through the browser channel.
            return [json.loads(e['params']['request']['postData']) for e in self.page.events
                    if e['method']=='Network.requestWillBeSent' and e['params']['request']['url'].endswith('/api/machine')
                    and e['params']['request'].get('postData') and json.loads(e['params']['request']['postData']).get('op')=='pull']
        until=time.monotonic()+5
        while time.monotonic()<until and not any(p['force'] != [0,0,0] for p in pull_requests()):
            time.sleep(.03)
        self.assertTrue(any(p['force'] != [0,0,0] for p in pull_requests()),'the engine receives the active pull')
        turned=self.js('window.machineCamera().azimuth')
        touch('touchStart',[{'x':x,'y':y+12,'id':1},{'x':x+80,'y':y+12,'id':2}])
        self.assertIsNone(self.js('window.machinePullState()'),'a second finger ends the force gesture')
        touch('touchMove',[{'x':x+20,'y':y+12,'id':1},{'x':x+100,'y':y+12,'id':2}])
        self.assertNotEqual(self.js('window.machineCamera().azimuth'),turned)
        touch('touchEnd',[])
        pulls=pull_requests()
        self.assertEqual(pulls[-1]['force'],[0,0,0],'the engine receives a zero-force release before camera motion')

    def test_a_ghost_inside_a_wall_is_red_says_why_and_cannot_be_set_down(self):
        self.open('laser')
        self.press('Add a mirror')
        self.ghost()
        self.slide('x of your mirror 1', -0.35)
        self.slide('z of your mirror 1', 0.5)
        g = self.ghost()
        self.assertFalse(g['fits'])
        self.assertEqual(g['problems'], ['your mirror 1 goes 120 mm into wall; move it'])
        self.assertTrue(self.js("document.querySelector('#ghost-bar .down').disabled"))
        self.assertIn('120 mm into wall', self.js("document.querySelector('#ghost-bar .state').textContent"))
        self.press('Run it')
        self.wait("/120 mm into wall/.test(document.getElementById('verdict').textContent)",5)
        self.assertFalse(self.ghost()['fits'])
        self.assertEqual(self.js('window.machinePlacements()'),[])
        self.assertTrue(self.js(READY))

    def test_on_a_phone_the_scene_comes_into_view_and_its_bar_turns_and_sets_the_ghost_down(self):
        self.open('gap', 390, 844, phone=True)
        # The panel's tray shows each piece, with a picture, and how many are left.
        self.wait("Boolean(document.querySelector('#tray img:not([hidden])'))", 30)
        self.assertEqual(self.js("document.querySelector('#tray li').textContent"), 'plank1 left')
        self.click_visible('Level')
        self.js("document.getElementById('phone-design-panel').scrollTop = document.getElementById('phone-design-panel').scrollHeight")
        self.assertGreaterEqual(self.js("document.getElementById('view').getBoundingClientRect().top"), 0,
                                'the scene remains visible while the phone panel scrolls')
        self.press('Add a plank')
        self.ghost()
        self.assertGreater(self.js("document.getElementById('view').getBoundingClientRect().top"), -41,
                           'adding a piece brings the scene, and its ghost, into view')
        g=self.drag_ghost_to(.3,0,touch=True)
        self.assertAlmostEqual(g['p']['x_m'],0.3,delta=0.03,msg='a drag puts it there')
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

    def test_a_small_piece_is_grabbed_from_beside_it_and_on_a_phone_two_fingers_turn_the_view(self):
        # Level 6's mirror is a thin thing, a few pixels across. A press just
        # beside it (not on it) takes hold of it, and a drag slides it from
        # where it was, with no jump and no turn of the view.
        self.open('laser')
        self.press('Add a mirror')
        g0 = self.ghost()
        time.sleep(0.4)
        box = self.js('window.machineGhostScreen()')
        self.assertTrue(self.js('window.machineCamera().guides'), 'the guide lines show while placing')
        x, y = box['x1'] + 25, (box['y0'] + box['y1']) / 2
        for k in (3, 2, 1, 0):                # the pointer comes to it, as a mouse does
            self.mouse('mouseMoved', x + 15 * k, y)
            time.sleep(0.05)
        # The cursor says it can be taken.
        self.wait("document.getElementById('view').classList.contains('grab')", 5)
        turned = self.js('window.machineCamera().azimuth')
        self.mouse('mousePressed', x, y)
        for k in range(1, 13):
            self.page.send('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x + 10 * k, 'y': y, 'button': 'left', 'buttons': 1})
            time.sleep(0.03)
        self.mouse('mouseReleased', x + 120, y)
        g1 = self.ghost()
        self.assertGreater(g1['p']['x_m'] - g0['p']['x_m'], 0.1, 'it moved the way it was dragged')
        self.assertEqual(self.js('window.machineCamera().azimuth'), turned, 'the view did not turn')
        # A phone: a near-piece finger moves it; background and two-finger
        # gestures turn the view without relocating it.
        self.open('laser', 390, 844, phone=True)
        self.press('Add a mirror')
        p0 = self.ghost()['p']
        self.click_visible('View')
        box=self.js('window.machineGhostScreen()')
        sx,sy=box['x1']+25,(box['y0']+box['y1'])/2
        touch = lambda kind, points: self.page.send('Input.dispatchTouchEvent', {'type': kind, 'touchPoints': points})
        touch('touchStart', [{'x': sx, 'y': sy}])
        for k in range(1, 9):                 # a finger's pace, a move a frame or so
            time.sleep(0.03)
            touch('touchMove', [{'x': sx + 10 * k, 'y': sy}])
        time.sleep(0.1)
        touch('touchEnd', [])
        p1 = self.ghost()['p']
        self.assertGreater(p1['x_m'] - p0['x_m'],0.1,'a near-piece finger moves it even in View')
        sx,sy=self.empty_scene_point()
        turned=self.js('window.machineCamera().azimuth')
        self.drag([sx,sy],[sx-60,sy],touch=True)
        self.assertEqual(self.ghost()['p'],p1,'a background finger cannot relocate the piece')
        self.assertNotEqual(self.js('window.machineCamera().azimuth'),turned)
        box=self.js('window.machineGhostScreen()')
        view=self.js("document.querySelector('#view canvas').getBoundingClientRect().toJSON()")
        sx=max(view['left']+16,min(view['right']-160,(box['x0']+box['x1'])/2))
        sy=max(view['top']+100,min(view['bottom']-100,(box['y0']+box['y1'])/2))
        turned = self.js('window.machineCamera().azimuth')
        touch('touchStart', [{'x': sx, 'y': sy, 'id': 1}, {'x': sx + 120, 'y': sy, 'id': 2}])
        for k in range(1, 9):
            time.sleep(0.03)
            touch('touchMove', [{'x': sx + 12 * k, 'y': sy, 'id': 1}, {'x': sx + 120 + 12 * k, 'y': sy, 'id': 2}])
        time.sleep(0.1)
        touch('touchEnd',[{'x':sx+96,'y':sy,'id':1}])
        touch('touchMove',[{'x':sx+116,'y':sy,'id':1}])
        self.assertEqual(self.ghost()['p'],p1,'the remaining finger cannot grab the piece before all fingers are up')
        touch('touchEnd', [])
        time.sleep(0.5)
        self.assertEqual(self.ghost()['p'],p1,'two fingers leave the whole placement unchanged')
        self.assertNotEqual(self.js('window.machineCamera().azimuth'), turned, 'two fingers turn the view')
        box=self.js('window.machineGhostScreen()')
        sx,sy=(box['x0']+box['x1'])/2,(box['y0']+box['y1'])/2
        touch('touchStart',[{'x':sx,'y':sy,'id':1}])
        touch('touchMove',[{'x':sx+15,'y':sy,'id':1}])
        touch('touchCancel',[])
        cancelled=self.ghost()['p']
        box=self.js('window.machineGhostScreen()')
        sx,sy=(box['x0']+box['x1'])/2,(box['y0']+box['y1'])/2
        self.drag([sx,sy],[sx+80,sy],touch=True)
        self.assertNotEqual(self.ghost()['p'],cancelled,'a new near-piece drag works after touchCancel')

    def test_arrows_move_a_piece_as_it_is_seen_and_a_piece_set_down_is_picked_up_by_clicking_it(self):
        # Level 7's solar panel has a height of its own, so all six arrows;
        # there is no x or z to pick: the arrows (and dragging) move it.
        self.open('sun')
        self.assertIn('1 left', self.js("document.getElementById('tray-add').textContent"))
        self.press('Add a solar panel')
        start = self.ghost()['p']
        self.assertFalse({'x', 'z'} & set(self.js("[...document.querySelectorAll('#ghost-bar .chips button')].map(b => b.textContent)")))
        # Looking along -z: right is +x (along the red guide line), toward you +z.
        self.js('window.machineView({azimuth: 0})')
        self.wait("document.querySelector('#move-pad [data-dir=right]').dataset.axis === 'x'", 5)
        self.press('Move it right')
        self.assertAlmostEqual(self.ghost()['p']['x_m'], start['x_m'] + 0.02, places=4)
        self.press('Move it toward you')
        self.assertAlmostEqual(self.ghost()['p']['z_m'], start['z_m'] + 0.02, places=4)
        self.press('Raise it')
        self.assertAlmostEqual(self.ghost()['p']['height_m'], start['height_m'] + 0.02, places=4)
        # A quarter turn round, looking along -x: right is now -z, along the blue line.
        self.js('window.machineView({azimuth: Math.PI / 2})')
        self.wait("document.querySelector('#move-pad [data-dir=right]').dataset.axis === 'z'", 5)
        z = self.ghost()['p']['z_m']
        self.press('Move it right')
        self.assertAlmostEqual(self.ghost()['p']['z_m'], z - 0.02, places=4)
        # Level 1 gives one plank: set down, there is none left to add. While
        # it runs, a click on it picks it up, and the level goes back to its start.
        self.open('gap')
        self.press('Add a plank')
        self.ghost()
        self.assertTrue(self.js("document.getElementById('move-pad').querySelectorAll('button[data-dir]').length === 4"),
                        'a plank rests on what is under it: no up or down')
        # Long enough to rest across the gap, so it is still there to click.
        self.slide('Cut to length of your plank 1', 0.7)
        self.slide('Set down at x of your plank 1', 0.3)
        self.slide('across (z, m) of your plank 1', 0.0)
        self.ghost()
        self.press('Set it down')
        self.wait('!window.machineGhostState()', 5)
        self.wait(READY, 60)
        self.assertTrue(self.js("document.getElementById('tray-add').disabled"))
        self.assertIn('none left', self.js("document.getElementById('tray-add').textContent"))
        self.press('Run it')
        self.wait("/calculating live/.test(document.getElementById('clock').textContent)", 30)
        x, y = self.js("window.machineBodyScreen('your plank 1')")
        self.mouse('mousePressed', x, y)
        self.mouse('mouseReleased', x, y)
        g = self.ghost()
        self.assertEqual(g['index'], 0, 'the plank set down is a ghost again')
        self.wait(READY, 60)


if __name__ == '__main__':
    unittest.main(verbosity=2)
