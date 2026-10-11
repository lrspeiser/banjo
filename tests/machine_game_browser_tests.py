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
from pathlib import Path

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
        cls.piece_count = len([row for row in machine_game.free_build()['tray'] if not row.get('attach')])
        # An engine still closing as the tests end holds its log open a moment.
        cls.logs = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        # The game site as deployed: open to anyone, nothing else served.
        cls.server = lab.Server(('127.0.0.1', 0), ENGINE, Path(cls.logs.name), site='game', public=True)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.server.server_address[1]}'
        cls.chrome = chrome_driver.Chrome(1280, 860)
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
        said = self.js("document.getElementById('verdict').textContent + ' · ' + document.getElementById('clock').textContent")
        self.fail(f'waited {seconds:.0f} s for {expression}; the page says {said!r}')

    def open(self, level, width=1280, height=860, phone=False):
        self.page.send('Emulation.setDeviceMetricsOverride',
                       {'width': width, 'height': height, 'deviceScaleFactor': 2 if phone else 1, 'mobile': phone})
        self.page.send('Emulation.setTouchEmulationEnabled', {'enabled': phone, 'maxTouchPoints': 5})
        self.page.send('Page.navigate', {'url': f'{self.base}/play?level={level}'})
        self.wait(f"document.getElementById('clock') && {READY}", 90)
        # The view eases to its place as a level opens; a piece added before
        # it gets there lands where a slow page's view happened to be.
        self.wait('window.machineCamera().settled', 30)

    def ghost(self):
        self.wait(SETTLED, 20)
        return self.js('window.machineGhostState()')

    def press(self, name):
        """A button, by what it says or by its label."""
        # Large trays live in the library; use its ordinary scene entry point.
        if name.startswith('Add a ') and name != 'Add a piece' and self.js("!document.getElementById('tray-library').hidden && !document.getElementById('piece-picker').open"):
            self.press('Add a piece')
        self.reveal_control(f"[...document.querySelectorAll('button')].find(b => (b.getAttribute('aria-label') || b.textContent).trim() === {json.dumps(name)})")
        found = self.js(f"""(() => {{ const b = [...document.querySelectorAll('button')].find(b =>
            !b.disabled && b.offsetParent !== null && (!document.getElementById('piece-picker').open || b.closest('#piece-picker')) && ((b.getAttribute('aria-label') || b.textContent).trim() === {json.dumps(name)}));
            if (b) b.click(); return Boolean(b); }})()""")
        self.assertTrue(found, f'no button {name!r} to press')

    def slide(self, label, value):
        self.reveal_control(f"document.querySelector('[aria-label={json.dumps(label)}]')")
        self.assertTrue(self.js(f"""(() => {{ const el = document.querySelector('[aria-label={json.dumps(label)}]');
            if (!el) return false; el.value = {json.dumps(value)};
            el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', {{bubbles: true}})); return true; }})()"""),
            f'no control {label!r}')

    def screen_point(self, point):
        return self.js(f'window.machineScreenPoint({json.dumps(point)})')

    def mouse(self, kind, x, y):
        extra = {'button': 'left', 'clickCount': 1} if kind != 'mouseMoved' else {}
        self.page.send('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y, **extra})

    def drag(self, start, end, touch=False, button='left', steps=8, modifiers=0):
        if touch:
            self.page.send('Input.dispatchTouchEvent', {'type':'touchStart', 'touchPoints':[{'x':start[0],'y':start[1],'id':1}]})
        else:
            self.page.send('Input.dispatchMouseEvent', {'type':'mousePressed','x':start[0],'y':start[1],
                                                       'button':button,'buttons':{'left':1,'right':2,'middle':4}[button],'clickCount':1,'modifiers':modifiers})
        for k in range(1,steps+1):
            x=start[0]+(end[0]-start[0])*k/steps
            y=start[1]+(end[1]-start[1])*k/steps
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
        self.drag(self.screen_point([p['x_m'],bottom,p.get('z_m',0)]),self.screen_point([x,bottom,z]),touch=touch)
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
        self.reveal_control(f"[...document.querySelectorAll('button')].find(b => (b.getAttribute('aria-label') || b.textContent).trim() === {json.dumps(label)})")
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
        """Navigate the phone's real tabs before using a section's controls."""
        panel = self.js(f"(() => {{const el={expression}; const pane=el?.closest('.phone-pane'); return !document.querySelector('main').hidden && document.body.classList.contains('phone-panels') && pane?.hidden ? document.getElementById(pane.getAttribute('aria-labelledby')).textContent : null;}})()")
        if panel:
            self.click_visible(panel)
        tools = self.js(f"(() => {{const el={expression}; const d=el?.closest('#phone-tools'); return Boolean(d && !d.hidden && !d.open);}})()")
        if tools:
            self.js("document.querySelector('#phone-tools summary').scrollIntoView({block:'nearest',inline:'nearest'})")
            x,y = self.js("(() => {const r=document.querySelector('#phone-tools summary').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()")
            self.mouse('mousePressed',x,y); self.mouse('mouseReleased',x,y)
        self.js(f"(() => {{const el={expression}; if (document.body.classList.contains('phone-panels') && el?.closest('.phone-pane')) el.scrollIntoView({{block:'nearest',inline:'nearest'}});}})()")

    def assert_power_layout(self):
        # A rebuild reframes the camera; the anchors follow it each frame.
        self.wait('window.machineCamera().settled', 30)
        geometry = """(() => {const cards=[...document.querySelectorAll('.power-label')].filter(e=>!e.hidden),
            run=document.getElementById('start').getBoundingClientRect(), view=document.getElementById('view').getBoundingClientRect();
            const overlaps=(a,b)=>a.left<b.right && a.right>b.left && a.top<b.bottom && a.bottom>b.top;
            return cards.map((e,i)=>{const r=e.getBoundingClientRect();return {name:e.dataset.port,
                visible:r.left>=0 && r.right<=innerWidth && r.top>=0 && r.bottom<=innerHeight,
                inView:r.left>=view.left && r.right<=view.right && r.top>=view.top && r.bottom<=view.bottom,
                coversRun:overlaps(r,run),overlapsOther:cards.some((b,j)=>j!==i && overlaps(r,b.getBoundingClientRect()))};});})()"""
        # Readouts change card heights; allow the next render frame to lay
        # them out before trying to press the real on-screen targets.
        self.wait(f"(() => {{const rows={geometry};return rows.length>=2 && rows.every(r=>r.visible && r.inView && !r.coversRun && !r.overlapsOther);}})()", 10)
        layout = self.js(geometry)
        self.assertGreaterEqual(len(layout), 2, layout)
        self.assertTrue(all(r['visible'] and r['inView'] and not r['coversRun'] and not r['overlapsOther'] for r in layout), layout)

    # ---- the tests ---------------------------------------------------------------------
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
                self.assertTrue(self.js("['control-panel','phone-design-panel','phone-help-panel'].every(id=>!document.getElementById(id).hidden)"))
                self.assertEqual(self.js("document.querySelectorAll('#start').length"),1)
                self.assertEqual(self.js("document.getElementById('start').parentElement.id"),'scene-actions')
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
                    x,y=self.js("(() => {const r=document.getElementById('flow-summary').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()")
                    self.mouse('mousePressed',x,y); self.mouse('mouseReleased',x,y)
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
                        self.slide('Preview time',3)
                        self.wait('window.machineFlowPreviewState().time===3 && window.machineFlowPreviewState().index>=0',5)
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
                        self.slide('valve of your water_tank 1','closed'); self.ghost()
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
                        target = self.js(f"(() => {{const b=[...document.querySelectorAll('#control-panel button,#phone-runbar button')].find(b=>(b.getAttribute('aria-label')||b.textContent).trim()==={json.dumps(label)}),r=b?.getBoundingClientRect();return r?{{visible:r.x>=0 && r.right<=innerWidth && r.y>=0 && r.bottom<=innerHeight,uncovered:b.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)),h:r.height,w:r.width}}:null;}})()")
                        self.assertIsNotNone(target,label)
                        self.assertTrue(target['visible'] and target['uncovered'],(label,target))
                        self.assertGreaterEqual(target['h'],44); self.assertGreaterEqual(target['w'],44)
                    camera = self.js('window.machineCamera().azimuth')
                    self.click_visible('Turn the view left')
                    self.assertAlmostEqual(self.js('window.machineCamera().azimuth'), camera-.2)
                    self.assertEqual(self.ghost()['p'],setup[0], 'view controls do not move the piece')
                    self.click_visible('Turn the view right')
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

    def test_saved_solar_cable_survives_motion_renaming_reload_undo_and_version_restore(self):
        self.page.send('Emulation.setDeviceMetricsOverride', {'width':1280,'height':860,'deviceScaleFactor':1,'mobile':False})
        self.page.send('Emulation.setTouchEmulationEnabled', {'enabled':False})
        self.page.send('Page.navigate', {'url':f'{self.base}/machine'})
        self.wait("Boolean(document.getElementById('prebuilt-designs'))", 60)
        self.slide('New design name', 'Saved solar cable')
        self.press('Add New Design'); self.wait(READY, 60)
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
                self.slide('Easy challenge family', 'easy-loop')
                self.press('New easy challenge')
                self.wait(f"/easy-loop--v1--/.test(location.search) && {READY}", 60)
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
                self.assertGreaterEqual(self.js("document.getElementById('challenge-family').getBoundingClientRect().height"), 44)
                self.assertIn(title, self.js("document.querySelector('[aria-label=\"Recent easy challenges\"]').textContent"))
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
                self.wait("(() => { const b=document.querySelector('[data-terminal=\"lamp:minus\"]'); return b && !b.disabled && b.offsetParent!==null; })()", 10)
                self.click_visible('Connect supply plus'); self.ghost()
                self.click_visible('Connect control in')
                self.wait(f'!window.machineGhostState() && {READY}', 60)
                self.click_visible('Run it')
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Not this time', self.js("document.getElementById('level-done').textContent"),
                              'another supply lead cannot replace the missing return path')
                self.press('Start over'); self.wait(READY, 60)
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

    def test_easy_selection_and_saved_wiring_use_the_real_scene_controls(self):
        self.page.send('Page.navigate', {'url': f'{self.base}/play'})
        self.wait("document.getElementById('levels-screen') && !document.getElementById('levels-screen').hidden", 60)
        self.press('Easy: learn a piece')
        self.assertEqual(self.js("document.querySelectorAll('.ls-list li').length"), 20)
        self.press('Full chain reactions')
        self.assertEqual(self.js("document.querySelectorAll('.ls-list li').length"), 8)
        self.press('All challenges')
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

    def test_manual_switch_is_queued_before_running_and_reset_restores_saved_state(self):
        for width, height in ((1280, 860), (390, 844), (844, 390)):
            with self.subTest(viewport=(width, height)):
                self.page.send('Emulation.setDeviceMetricsOverride', {'width':width,'height':height,'deviceScaleFactor':1,'mobile':width != 1280})
                self.page.send('Page.navigate', {'url': f'{self.base}/machine'})
                self.wait("Boolean(document.getElementById('prebuilt-designs'))", 60)
                self.press('Start from Build your first circuit')
                self.wait(READY, 60)
                self.press('Save version')
                self.wait("window.machineDesign().versions.length > 0", 10)
                saved = self.js('window.machineDesign().versions.slice(-1)[0].draft')
                self.reveal_control("document.getElementById('machine-controls')")
                self.js("document.getElementById('machine-controls').open = true")
                targets = self.js("[...document.querySelectorAll('#machine-control-rows button')].map(b=>{const r=b.getBoundingClientRect();return {w:r.width,h:r.height,right:r.right};})")
                self.assertTrue(targets)
                self.assertTrue(all(row['h'] >= 44 and row['right'] <= width for row in targets), targets)
                self.press('Toggle control')
                self.press('Run it')
                self.wait("/controlopen/.test(document.getElementById('readings').textContent)", 15)
                self.assertEqual(self.js('window.machineDesign().versions.slice(-1)[0].draft'), saved)
                self.press('Set up again')
                self.wait(READY, 60)
                self.wait("/controlclosed/.test(document.getElementById('readings').textContent)", 15)

    def test_saved_terminal_graph_removal_undo_reload_and_restore(self):
        self.page.send('Page.navigate', {'url': f'{self.base}/machine'})
        self.wait("Boolean(document.getElementById('prebuilt-designs'))", 60)
        self.slide('New design name', 'Saved terminal graph')
        self.press('Add New Design')
        self.wait(READY, 60)
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
            self.wait("!window.machineWiringState().busy && [...document.querySelectorAll('#terminal-labels button')].some(b=>!b.disabled && b.offsetParent!==null)", 10)
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
                self.assertTrue(self.js("(() => {const a=document.getElementById('edit-guide-label').getBoundingClientRect(),b=document.getElementById('view').getBoundingClientRect();return a.left>=b.left && a.right<=b.right && a.top>=b.top && a.bottom<=b.bottom;})()"))
                self.assertTrue(self.js("(() => {const a=document.getElementById('edit-guide-label').getBoundingClientRect();return a.top>=0 && a.bottom<=innerHeight;})()"), 'the caption stays visible even when the toolbar wraps')
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
            self.wait(f"document.querySelectorAll('.ls-list li').length === {self.level_count} && document.querySelector('.ls-summary').textContent.startsWith('Landing test:')", 30)
            self.assertEqual(self.js('location.pathname + location.search'), '/play')
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

    def test_the_levels_screen_shows_each_players_own_progress(self):
        # /play on its own: every level and how far this player has got.
        self.page.send('Emulation.setDeviceMetricsOverride', {'width': 1280, 'height': 860, 'deviceScaleFactor': 1,
                                                              'mobile': False})
        self.page.send('Page.navigate', {'url': f'{self.base}/play'})
        self.wait("document.getElementById('levels-screen') && !document.getElementById('levels-screen').hidden", 90)
        # Use distinct known progress: earlier tests also earn real wins,
        # including the same 28.8 MJ result assigned to Tester below.
        self.js("localStorage.setItem('banjo-play-save',JSON.stringify({current:'Player 1',players:{'Player 1':{levels:{gap:{stars:1,energy_j:12300000}}}}}))")
        self.page.send('Page.navigate', {'url': f'{self.base}/play'})
        self.wait("document.querySelector('.ls-list li')?.textContent.includes('Best win: 12.3 MJ')",30)
        self.assertEqual(self.js("document.querySelectorAll('.ls-list li').length"), self.level_count)
        self.js("document.querySelector('.ls-player input').value = 'Tester'")
        self.press('Add player')
        self.assertIn(f'Tester: 0 of {self.level_count} levels won', self.js("document.querySelector('.ls-summary').textContent"))
        # A win kept for this player shows on the screen; another player's is
        # their own.
        self.js("""(() => { const s = JSON.parse(localStorage.getItem('banjo-play-save'));
            s.players.Tester.levels.gap = {stars: 3, energy_j: 28800000}; localStorage.setItem('banjo-play-save', JSON.stringify(s)); })()""")
        self.page.send('Page.navigate', {'url': f'{self.base}/play'})
        self.wait("!document.getElementById('levels-screen').hidden", 90)
        self.assertIn(f'Tester: 1 of {self.level_count} levels won, 3 of {self.level_count * 3} stars', self.js("document.querySelector('.ls-summary').textContent"))
        self.assertIn('Best win: 28.8 MJ', self.js("document.querySelector('.ls-list li').textContent"))
        self.js("(() => { const p = document.getElementById('player-pick'); p.value = 'Player 1'; p.dispatchEvent(new Event('change')); })()")
        self.assertTrue(self.js("document.querySelector('.ls-summary').textContent.startsWith('Player 1:')"))
        self.assertIn('Best win: 12.3 MJ',self.js("document.querySelector('.ls-list li').textContent"))
        self.assertNotIn('28.8 MJ', self.js("document.querySelector('.ls-list li').textContent"), 'Tester’s best is Tester’s')
        self.press('Play level 2, Cut it down')
        self.wait(READY, 90)
        self.assertTrue(self.js("document.getElementById('levels-screen').hidden"))
        self.assertTrue(self.js("document.getElementById('title').textContent.startsWith('2. ')"))

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
        self.js("localStorage.setItem('banjo-play-save', JSON.stringify({current:'Sandbox test',players:{'Sandbox test':{levels:{},free:{placements:[{piece:'marble',x_m:0,z_m:0}]}}}}))")
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
            self.slide('New design name', 'Second design')
            self.press('Add New Design')
            self.wait(READY, 60)
            self.assertEqual(self.js('window.machinePlacements()'), [])
            self.press('All designs')
            self.press('Open design My free build')
            self.wait(f"window.machinePlacements().length === 1 && {READY}", 60)
            self.assertEqual(self.js("document.getElementById('title').textContent"), 'My free build')
            before = self.js('window.machineDesign().versions.length')
            self.js("window.realStore = Storage.prototype.setItem; Storage.prototype.setItem = () => { throw new Error('storage full'); }")
            self.press('Save version')
            self.wait("/Version not saved/.test(document.getElementById('design-status').textContent)", 10)
            self.assertEqual(self.js('window.machineDesign().versions.length'), before)
            self.js('Storage.prototype.setItem = window.realStore')
            # Saving a refused setup must not create a green checkpoint.
            self.js("window.confirm = () => true; document.getElementById('design-versions').open = false")
            self.press('Add a plank')
            self.ghost()
            self.press('Save version')
            self.assertIn('Set your plank down first', self.js("document.getElementById('verdict').textContent"))
        finally:
            self.page.send('Page.navigate', {'url': f'{self.base}/machine'})
            self.wait("document.getElementById('sandbox-screen') && !document.getElementById('sandbox-screen').hidden", 60)
            self.js(f"localStorage.setItem('banjo-play-save', {json.dumps(old)})")

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
                self.assertTrue(self.js("[...document.querySelectorAll('#sandbox-screen button')].every(b => b.getBoundingClientRect().height >= 44 && b.getBoundingClientRect().right <= innerWidth)"))
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
                  "/Joined to the far end of your track 1/.test(document.querySelector('#ghost-bar .state').textContent); })()", 20)
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
        self.wait("/over par \\(30.6 MJ\\)/.test(document.querySelector('#ghost-bar .state').textContent)", 10)
        self.assertIn('34.1 MJ to make', self.js("document.querySelector('#ghost-bar .state').textContent"))
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
        self.assertTrue(self.js("document.getElementById('ghost-down').disabled"))
        self.assertIn('120 mm into wall', self.js("document.getElementById('ghost-state').textContent"))
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
