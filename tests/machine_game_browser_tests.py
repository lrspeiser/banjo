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
import math
import re
import os
import sys
import tempfile
from unittest.mock import patch
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
READY = "/ready: press Try It!/.test(document.getElementById('clock')?.textContent || '')"


class LiveBrowserResult(unittest.TextTestResult):
    """Keep failures available even when a later case reaches the batch deadline."""
    def report_now(self, test, err):
        self.stream.write('\n'+self._exc_info_to_string(err,test)+'\n');self.stream.flush()
        try:
            proof=ROOT/'build'/'ui-proof';proof.mkdir(parents=True,exist_ok=True)
            name=re.sub('[^a-zA-Z0-9_-]','_',test.id())
            count=len(self.failures)+len(self.errors)
            (proof/f'browser-failure-{name}-{count}.png').write_bytes(base64.b64decode(
                test.page.send('Page.captureScreenshot',{'format':'png'})['data']))
        except Exception as diagnostic_error:
            self.stream.write('Failure screenshot unavailable: '+type(diagnostic_error).__name__+'\n')
            self.stream.flush()

    def addFailure(self,test,err):
        super().addFailure(test,err);self.report_now(test,err)

    def addError(self,test,err):
        super().addError(test,err);self.report_now(test,err)

    def addSubTest(self,test,subtest,err):
        super().addSubTest(test,subtest,err)
        if err:self.report_now(test,err)


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
        cls.archived_templates = {row['name']:row for row in machine_game.archived_sandbox_templates()}
        cls.showcase_names = {row['name'] for row in machine_game.sandbox_templates()}
        cls.piece_count = len([row for row in machine_game.free_build()['tray'] if not row.get('attach') and not row.get('legacy')])
        cls.river_solution = dict(machine_game.sandbox_water_launch.RIVER_SOLUTION)
        import sandbox_variants
        cls.power_level = sandbox_variants.construct(machine_game.level_by_id('easy-power'),42,version=2)
        # An engine still closing as the tests end holds its log open a moment.
        cls.logs = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        # The game site as deployed: open to anyone, nothing else served.
        cls.server = lab.Server(('127.0.0.1', 0), ENGINE, Path(cls.logs.name), site='game', public=True,
                                profile_db=Path(cls.logs.name)/'profiles.sqlite3')
        # Provider-fixture guide steps share one test visitor across cases.
        # Keep production's spending quota unchanged; test its limits in the
        # host suite instead of exhausting it with mocked browser requests.
        cls.server.chat_allowance = lab.Allowance(1000,1000,'fixture chat')
        # Fresh browser cases create independent visitors. Keep the public
        # 20/hour creation limit in production; this isolated suite needs one
        # per scenario plus its explicit recovery/namespace cases.
        cls.server.profile_creations = lab.Allowance(1000,1000,'fixture visitors')
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.server.server_address[1]}'
        cls.chrome = chrome_driver.Chrome(1280, 860)
        cls.page = cls.chrome.page
        cls.page.send('Network.enable')
        cls.page.send('Runtime.enable')

    @classmethod
    def tearDownClass(cls):
        cls.chrome.close()
        cls.server.shutdown()
        cls.server.machines.close_all()
        cls.server.server_close()
        cls.logs.cleanup()

    def setUp(self):
        # Each scenario owns a fresh browser and visitor. Long catalogue
        # sweeps otherwise leave WebGL/module resources in the next case.
        # Reopening a design within one scenario still exercises persistence;
        # another scenario must not inherit its parts or an open dialog.
        type(self).chrome.close()
        self.server.machines.close_all()
        # Independent scenarios share a loopback IP, but must not inherit
        # another scenario's request history. Production quotas are covered
        # in machine_host_tests; keep the existing limits within each case.
        for name in ('preview_allowance','optical_allowance'):
            allowance=getattr(self.server,name)
            if allowance:
                with allowance.lock:
                    allowance.recent.clear();allowance.day.clear()
        type(self).chrome=chrome_driver.Chrome(1280,860)
        type(self).page=type(self).chrome.page
        self.page.send('Network.enable');self.page.send('Runtime.enable')

    # ---- what a person does -------------------------------------------------------
    def test_header_and_camera_share_single_rows_without_an_idle_banner(self):
        for width, height in ((390,844),(320,568),(844,390),(1280,860)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-weight',width,height,phone=width<600 or height<500)
                self.assertTrue(self.js("document.getElementById('clock').hidden"))
                self.assertTrue(self.js("document.getElementById('undo-pieces').checkVisibility() && document.getElementById('undo-pieces').disabled"))
                for test_badge in (False,True):
                    self.js(f"document.getElementById('environment-badge').hidden={str(not test_badge).lower()}")
                    header=self.js("""(()=>{const h=document.querySelector('header').getBoundingClientRect(),b=document.querySelector('.brand').getBoundingClientRect();
                        return {height:h.height,links:[...document.querySelectorAll('header nav a')].map(e=>{const r=e.getBoundingClientRect();return {w:r.width,h:r.height,inside:r.left>=0&&r.right<=innerWidth,sameRow:Math.abs(r.top+r.height/2-b.top-b.height/2)<2,hit:e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))};})};})()""")
                    self.assertLessEqual(header['height'],54,header)
                    for link in header['links']:
                        self.assertTrue(link['inside'] and link['sameRow'] and link['hit'],header)
                        self.assertGreaterEqual(link['w'],44);self.assertGreaterEqual(link['h'],44)
                self.js("document.getElementById('environment-badge').hidden=true")
                def check_row():
                    row=self.js("""(()=>{const v=document.getElementById('view').getBoundingClientRect(),t=document.getElementById('viewer-corner').getBoundingClientRect();
                        return {top:t.top-v.top,height:t.height,buttons:[...document.querySelectorAll('#viewer-corner button')].filter(b=>b.checkVisibility()).map(b=>{const r=b.getBoundingClientRect();return {w:r.width,h:r.height,top:r.top-t.top,inside:r.left>=v.left&&r.right<=v.right,hit:b.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))};})};})()""")
                    self.assertLessEqual(row['top'],4,row);self.assertLessEqual(row['height'],46,row)
                    for b in row['buttons']:
                        self.assertGreaterEqual(b['w'],44);self.assertGreaterEqual(b['h'],44)
                        self.assertLess(abs(b['top']),2,row)
                        if width>=360 or len(row['buttons'])<8:self.assertTrue(b['hit'] and b['inside'],row)
                    if width<360 and len(row['buttons'])==8:
                        y=self.js("document.getElementById('viewer-corner').getBoundingClientRect().top+22")
                        self.drag([280,y],[140,y],touch=True)
                        self.assertTrue(self.js("document.getElementById('viewer-corner').scrollLeft>0"))
                check_row()
                self.click_visible('Add a weight');self.ghost();self.click_visible('Place')
                self.wait(READY,15);check_row()
                self.click_visible('Undo');self.wait('machinePlacements().length===0 && '+READY,15)
                check_row()
                self.click_visible('Redo');self.wait('machinePlacements().length===1 && '+READY,15)
                proof=ROOT/'build/ui-proof';proof.mkdir(parents=True,exist_ok=True)
                (proof/f'compact-toolbar-ready-{width}x{height}.png').write_bytes(base64.b64decode(self.page.send('Page.captureScreenshot',{'format':'png'})['data']))
                self.click_visible('Try It!')
                self.wait("!document.getElementById('clock').hidden && document.getElementById('clock').textContent.startsWith('World ')",15)
                proof=ROOT/'build/ui-proof';proof.mkdir(parents=True,exist_ok=True)
                (proof/f'compact-toolbar-{width}x{height}.png').write_bytes(base64.b64decode(self.page.send('Page.captureScreenshot',{'format':'png'})['data']))

    def test_test_busy_panel_can_switch_the_simulation_to_this_browser(self):
        import machine_game
        host=self.server.machines;host.close_all();previous_limit=host.limit;host.limit=1
        try:
            other=host.open(machine_game.compose(machine_game.level_by_id('easy-weight'),[])[0])
            with patch.object(self.server,'environment','test'):
                self.navigate(self.base+'/play?level=easy-weight')
                self.wait("document.getElementById('test-busy')?.hidden===false",15)
                self.assertEqual(list(host.sessions),[other['session']])
                self.click_visible('Use this browser');self.wait(READY,15)
                self.assertFalse(self.js("document.getElementById('test-busy').checkVisibility()"))
                self.assertNotIn(other['session'],host.sessions);self.assertEqual(len(host.sessions),1)
                host.close(next(iter(host.sessions)))
                self.wait("document.getElementById('test-busy').hidden===false",10)
                self.click_visible('Use this browser');self.wait(READY,15)
                self.assertEqual(len(host.sessions),1)
        finally:host.close_all();host.limit=previous_limit

    def test_settings_are_in_changes_and_share_is_a_header_link(self):
        for width,height in ((1280,860),(390,844),(320,568),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-weight',width,height,phone=width<600 or height<500)
                self.assertTrue(self.js("document.getElementById('help-settings').closest('#recent-changes')!==null"))
                self.assertFalse(self.js("document.getElementById('control-panel').contains(document.getElementById('help-settings'))"))
                self.wait("document.getElementById('header-share').href==='https://banjo.is/play?level=easy-weight'",5)
                self.assertTrue(self.js("document.getElementById('header-share').tagName==='A' && document.getElementById('header-share').previousElementSibling.id==='recent-changes-open'"))
                self.js("document.getElementById('recent-changes-open').click()")
                self.click_summary('#help-settings > summary')
                self.click_visible('Snap to grid')
                self.assertEqual(self.js("document.getElementById('grid-snap').getAttribute('aria-pressed')"),'false')
                self.click_visible('Close')
                self.press('Share')
                self.assertEqual(self.js("document.getElementById('header-share').href"),'https://banjo.is/play?level=easy-weight')

    def test_one_slot_rebuild_waits_for_close_and_levels_release_the_world(self):
        host = self.server.machines
        host.close_all()
        previous_limit = host.limit
        host.limit = 1
        close = host.close
        def slow_close(key):
            time.sleep(.3)
            return close(key)
        try:
            with patch.object(host, 'close', side_effect=slow_close):
                self.open('easy-weight')
                original = next(iter(host.sessions))
                self.press('Add a weight'); self.ghost()
                self.click_visible('Place')
                self.wait('machinePlacements().length === 1 && '+READY, 15)
                deadline = time.monotonic() + 5
                while original in host.sessions and time.monotonic() < deadline: time.sleep(.05)
                self.assertNotIn(original, host.sessions)
                self.assertEqual(len(host.sessions), 1)
                self.js("document.getElementById('levels-open').click()")
                self.wait("document.body.classList.contains('on-levels')")
                deadline = time.monotonic() + 5
                while host.sessions and time.monotonic() < deadline: time.sleep(.05)
                self.assertFalse(host.sessions)
                self.click_visible('Back to Tip the lever')
                self.wait(READY, 15)
                self.assertEqual(len(host.sessions), 1)
                self.assertEqual(self.js('machinePlacements().length'), 1)
                self.assertNotIn('Could not build', self.js("document.getElementById('clock').textContent"))
                self.js("document.getElementById('sandbox-open').click()")
                self.wait("document.body.classList.contains('on-sandbox')")
                deadline = time.monotonic() + 5
                while host.sessions and time.monotonic() < deadline: time.sleep(.05)
                self.assertFalse(host.sessions)
        finally:
            host.close_all()
            host.limit = previous_limit

    def test_leaving_during_an_open_closes_the_abandoned_world(self):
        host = self.server.machines
        host.close_all()
        entered = threading.Event()
        proceed = threading.Event()
        closed = threading.Event()
        open_world = host.open
        close_world = host.close
        def delayed_open(spec):
            entered.set()
            if not proceed.wait(10): raise RuntimeError('test did not release open')
            return open_world(spec)
        def record_close(key):
            result = close_world(key)
            closed.set()
            return result
        try:
            with patch.object(host, 'open', side_effect=delayed_open), patch.object(host, 'close', side_effect=record_close):
                self.navigate(self.base+'/play?level=easy-weight')
                self.assertTrue(entered.wait(10))
                self.js("document.getElementById('levels-open').click()")
                proceed.set()
                self.wait("document.body.classList.contains('on-levels')")
                self.assertTrue(closed.wait(10))
                self.assertFalse(host.sessions)
                self.assertFalse(self.js("document.getElementById('level-intro').open"))
        finally:
            proceed.set()
            host.close_all()

    def test_a_busy_slot_does_not_close_another_players_world_and_can_retry(self):
        import machine_game
        host = self.server.machines
        host.close_all()
        previous_limit = host.limit
        host.limit = 1
        try:
            other = host.open(machine_game.compose(machine_game.level_by_id('easy-weight'), [])[0])
            self.navigate(self.base+'/play?level=easy-weight')
            self.wait("document.getElementById('clock')?.textContent.startsWith('Simulation busy.')", 15)
            self.assertFalse(self.js("document.getElementById('clock').hidden"))
            self.assertEqual(list(host.sessions), [other['session']])
            self.assertFalse(self.js("document.getElementById('level-intro').open"))
            host.close(other['session'])
            self.click_visible('Try It!')
            self.wait("document.getElementById('clock').textContent.startsWith('World ')", 15)
            self.assertEqual(len(host.sessions), 1)
        finally:
            host.close_all()
            host.limit = previous_limit

    def js(self, expression):
        return self.page.evaluate(expression)

    def navigate(self, url):
        previous=self.js('performance.timeOrigin')
        response=self.page.send('Page.navigate',{'url':url})
        self.assertFalse(response.get('errorText'),response)
        # Page.navigate acknowledges before the old document is replaced.
        # Its controls must never satisfy the destination's readiness checks.
        # A same-document fragment navigation has no new loader/epoch.
        if response.get('loaderId'):
            self.wait(f"performance.timeOrigin!=={previous} && document.readyState==='complete'",60)
        return response

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
        errors=[e['params'].get('exceptionDetails') for e in self.page.events if e['method']=='Runtime.exceptionThrown']
        if errors:print('BROWSER_SCRIPT_ERRORS',json.dumps(errors[-3:]),flush=True)
        http_errors=[{'path':urlsplit(e['params']['response']['url']).path,'status':e['params']['response']['status']}
                     for e in self.page.events if e['method']=='Network.responseReceived' and e['params']['response']['status']>=400]
        if http_errors:print('BROWSER_HTTP_ERRORS',json.dumps(http_errors[-5:]),flush=True)
        if 'piece-grid img' in expression:
            print('MISSING_PIECE_IMAGES',json.dumps(self.js("[...document.querySelectorAll('#piece-grid .piece-card')].filter(b=>!b.querySelector('img').naturalWidth).map(b=>b.dataset.piece)")),flush=True)
        if 'machinePlacements' in expression or 'machineContactState' in expression or expression==SETTLED:
            print('MACHINE_WAIT_STATE',json.dumps(self.js("({placements:machinePlacements(),ghost:machineGhostState(),design:machineDesign(),status:document.getElementById('design-status').textContent,wiring:machineWiringState().busy,contact:machineContactState().liveDevices})")),flush=True)
        if http_errors:
            failures=[]
            for event in self.page.events:
                if event['method']=='Network.responseReceived' and event['params']['response']['status']>=400:
                    try:failures.append(self.page.send('Network.getResponseBody',{'requestId':event['params']['requestId']})['body'])
                    except Exception:pass
            print('HTTP_FAILURE_DETAILS',json.dumps(failures[-5:]),flush=True)
        print('FIXTURE_REQUEST_COUNTS',json.dumps({name:{'used':len(getattr(self.server,name).day),
            'hour_limit':getattr(self.server,name).per_hour} for name in ('preview_allowance','optical_allowance')
            if getattr(self.server,name)}),flush=True)
        if 'machinePowerFeedbackState' in expression:
            print('POWER_READING_DIAGNOSTIC',json.dumps(self.js("""(() => ({placements:machinePlacements(),
                readings:[...document.querySelectorAll('.power-feedback-label')].map(e=>({device:e.dataset.device,wire:e.dataset.wire,hidden:e.hidden,text:e.innerText})),
                view:document.getElementById('view').getBoundingClientRect().toJSON()}))()""")),flush=True)
        self.fail(f'waited {seconds:.0f} s for {expression}; the page says {said!r}')

    def open(self, level, width=1280, height=860, phone=False, dismiss_intro=True):
        self.page.send('Emulation.setDeviceMetricsOverride',
                       {'width': width, 'height': height, 'deviceScaleFactor': 2 if phone else 1, 'mobile': phone})
        self.page.send('Emulation.setTouchEmulationEnabled', {'enabled': phone, 'maxTouchPoints': 5})
        destination=f'{self.base}/play?level={level}'
        previous=self.js('performance.timeOrigin')
        navigated=self.navigate(destination)
        self.assertFalse(navigated.get('errorText'),navigated)
        expected=f'location.href==={json.dumps(destination)}'
        if level=='free':
            # The former Free URL opens its saved design in the one sandbox.
            expected=f"location.origin==={json.dumps(self.base)} && location.pathname==='/machine' && new URLSearchParams(location.search).get('design')===window.machineDesign?.()?.id"
        self.wait(f"performance.timeOrigin!=={previous} && ({expected}) && document.getElementById('clock') && {READY}",90)
        if level!='free':
            self.wait("document.getElementById('level-intro').open",30)
            if dismiss_intro:self.click_visible('GO')
        # The view eases to its place as a level opens; a piece added before
        # it gets there lands where a slow page's view happened to be.
        self.wait('window.machineCamera().settled', 30)

    def ghost(self):
        self.wait(SETTLED, 20)
        self.paint()
        return self.js('window.machineGhostState()')

    def paint(self):
        # Native replies and camera edits precede the next rendered scene.
        # A person acts on that scene, not the intermediate message state.
        self.page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true))))',await_promise=True)

    def assert_wire_gauges_readable(self,gauge,area):
        text=json.dumps(gauge);unit=json.dumps(area)
        if self.js(f"machinePowerFeedbackState().labels.filter(r=>r.wire&&r.text.includes({text})&&r.text.includes({unit})).length===2"):return
        # Crowded scenes keep both actual gauges in the adjacent controls
        # rather than putting another opaque label over a solid or a button.
        self.reveal_control("document.getElementById('wire-adjustments')")
        labels=self.js("[...document.querySelectorAll('#wire-adjustments button')].map(b=>b.textContent)")
        self.assertEqual(len(labels),2)
        self.assertTrue(all(gauge in label and area in label for label in labels),labels)
        for label in self.js("[...document.querySelectorAll('#wire-adjustments button')].map(b=>b.getAttribute('aria-label'))"):
            self.reveal_control(self.button_expression(label))
            self.assertTrue(self.js(f"(()=>{{const b={self.button_expression(label)},r=b.getBoundingClientRect();return r.height>=44&&r.width>=44&&r.top>=0&&r.bottom<=innerHeight&&b.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}})()"))

    def button_expression(self, name):
        # Duplicate actions may exist on inactive screens or in unopened help.
        # Select the current screen, then reveal its real tab/disclosure.
        return f"""(() => {{const buttons=[...document.querySelectorAll('button')].filter(b=>(b.getAttribute('aria-label')||b.textContent).trim()==={json.dumps(name)});
          return buttons.find(b=>b.getClientRects().length && !b.disabled) || buttons.find(b=>!b.closest('main[hidden],#levels-screen[hidden],#sandbox-screen[hidden],#piece-picker:not([open]),.save-help-panel:not(:popover-open)'));}})()"""

    def press(self, name):
        if name.startswith('Start from ') and name[11:] not in self.showcase_names:
            # Removed cards remain covered as historical shared designs. This
            # uses the public import flow and never restores them to the gallery.
            row=self.archived_templates[name[11:]]
            draft={key:row[key] for key in ('name','base','placements')}
            packed='j'+base64.urlsafe_b64encode(json.dumps(draft).encode()).decode().rstrip('=')
            self.navigate(self.base+'/machine#build='+packed)
            self.wait(f"window.machineDesign()?.name==={json.dumps(row['name'])} && {READY}",90)
            self.click_visible('Save version');self.anonymous_cloud_saved()
            self.wait("machineDesign().versions.length===1 && !document.getElementById('save-design').disabled",30)
            self.wait('machineCamera().settled',30);self.paint()
            return
        if name!='GO' and self.js("Boolean(document.getElementById('level-intro')?.open)"):self.click_visible('GO')
        if name in ('Share','Share this design'):
            point=self.js("(()=>{const a=document.getElementById('header-share');a.scrollIntoView({block:'nearest',inline:'nearest'});const r=a.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];})()")
            self.mouse('mousePressed',*point);self.mouse('mouseReleased',*point)
            self.wait("document.getElementById('header-share').textContent==='Copied'",10)
            return
        """A button, by what it says or by its label."""
        if name.startswith('Play level ') and ', ' in name:
            title=name.split(', ',1)[1]
            current=self.js(f"[...document.querySelectorAll('.level-card-main')].find(b=>b.querySelector('.level-card-title')?.textContent==={json.dumps(title)})?.getAttribute('aria-label')")
            if current:name=current
        if name=='Restart with my pieces':return self.retry_existing_setup()
        if name=='Keep my pieces':
            self.click_visible('Try again');self.ghost();return self.press('Cancel')
        if name=='Start over':name='Reset'
        if name.startswith('Adjust ') and name!='Adjust a piece':
            index=self.js(f"machineEditableObjects().find(o=>o.name.startsWith('your ')&&o.name.split(' ')[1]==={json.dumps(name[7:].replace(' ','_'))})?.index")
            if index is not None:return self.click_piece(index)
        if name.startswith('Change its '):
            return self.choose_adjustment(name[len('Change its '):])
        if name.startswith('Pick up your '):
            return self.click_piece(int(name.rsplit(' ',1)[1])-1)
        if name.startswith('Remove your '):
            self.click_piece(int(name.rsplit(' ',1)[1])-1);return self.press('Delete selected piece')
        if name in ('Set it down','✓ Set down'):
            name = 'Place'
        if name=='Place':self.ghost()
        if name == 'Cancel' and self.js("Boolean(window.machineGhostState?.()) && ![...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='Cancel'&&b.offsetParent!==null)"):
            name = 'Throw the ghost away'
        # Large trays live in the library; use its ordinary scene entry point.
        if name.startswith('Add a ') and name != 'Add a piece' and self.js("!document.getElementById('tray-library').hidden && !document.getElementById('piece-picker').open"):
            self.press('Add a piece')
        self.reveal_control(self.button_expression(name))
        found = self.js(f"""(() => {{ const b = [...document.querySelectorAll('button')].find(b =>
            !b.disabled && b.offsetParent !== null && (!document.getElementById('piece-picker').open || b.closest('#piece-picker')) && ((b.getAttribute('aria-label') || b.textContent).trim() === {json.dumps(name)}));
            if (b) b.click(); return Boolean(b); }})()""")
        self.assertTrue(found, f'no button {name!r} to press: '+str(self.js("({ghost:machineGhostState(),editorHidden:document.getElementById('piece-editor').hidden,down:[...document.querySelectorAll('#piece-editor .down')].map(b=>({hidden:b.hidden,disabled:b.disabled}))})")))
        if name=='Add New Design' or name.startswith(('Start from ','Open design ')):
            # Gallery actions await design creation and the native rebuild.
            # The old ready clock can remain while that action starts.
            self.wait(f"""(() => {{const button=[...document.querySelectorAll('#sandbox-screen button')]
                .find(b=>(b.getAttribute('aria-label')||b.textContent).trim()==={json.dumps(name)});
                return button?.disabled===false && document.getElementById('sandbox-screen').hidden;
            }})() && {READY}""",90)
            self.wait('machineCamera().settled',30)
            self.paint()

    def slide(self, label, value):
        if label=='Adjust a piece':
            self.click_piece(int(value));return
        self.reveal_control(f"document.querySelector('[aria-label={json.dumps(label)}]')")
        self.assertTrue(self.js(f"""(() => {{ const el = document.querySelector('[aria-label={json.dumps(label)}]');
            if (!el) return false; el.value = {json.dumps(value)};
            el.dispatchEvent(new Event(el.tagName === 'SELECT' || el.type === 'number' ? 'change' : 'input', {{bubbles: true}})); return true; }})()"""),
            f'no control {label!r}: '+str(self.js("({ghost:window.machineGhostState()?.p,inputs:[...document.querySelectorAll('#ghost-bar input')].map(e=>e.getAttribute('aria-label'))})")))
        if self.js("document.getElementById('recent-changes').open"):self.click_visible('Close')

    def click_piece(self,index):
        if self.js(f"machineGhostState()?.index==={index}"):return self.ghost()
        self.click_visible('Controls')
        self.wait('machineCamera().settled',30)
        candidate=self.js(f"machineEditableObjects().find(o=>o.index==={index})")
        self.assertIsNotNone(candidate)
        selected=f"machineGhostState()?.p.object==={json.dumps(candidate['id'])}" if candidate.get('id') else f"machineGhostState()?.index==={index}&&!machineGhostState()?.p.object"
        if re.match(r'^your (wire|power_cable) ',candidate['name']):
            label='Adjust '+candidate['name']
            if not self.js(f"document.querySelector('[aria-label={json.dumps(label)}]')?.checkVisibility()"):
                # Labels deliberately yield to objects/connection rings. Use
                # the existing Controls entry when that callout cannot fit.
                prefix=f"Adjust placed {'Wire' if candidate['name'].startswith('your wire ') else 'Power cable'} {index+1}"
                label=self.js(f"[...document.querySelectorAll('#wire-adjustments button')].find(b=>b.getAttribute('aria-label').startsWith({json.dumps(prefix)}))?.getAttribute('aria-label')")
                self.assertIsNotNone(label)
            self.click_visible(label);self.ghost();return
        if self.js("document.getElementById('wire-mode').getAttribute('aria-pressed')==='true'"):
            self.click_visible('Connect wires')
        for framing in range(6):
            for part in candidate['parts']:
                for point in self.js(f"machineBodyHitPoints({json.dumps(part)})"):
                    if not self.js(f"document.elementFromPoint({point[0]},{point[1]})?.tagName==='CANVAS'"):continue
                    pick=self.js(f"machineScenePick({point[0]},{point[1]})")
                    if index not in pick['pieces'] or ((pick['wire'] or pick['socket']) and not pick['ambiguous']):continue
                    self.mouse('mousePressed',*point);self.mouse('mouseReleased',*point)
                    option=self.js(f"document.querySelector('#socket-choices:not([hidden]) [data-piece-index=\"{index}\"]')?.textContent")
                    if option:self.click_visible(option)
                    if self.js("!/World 0\\.00 s/.test(document.getElementById('clock').textContent)"):
                        deadline=time.monotonic()+2
                        while time.monotonic()<deadline and not self.js('Boolean(machineGhostState())'):time.sleep(.05)
                    if self.js(selected):return
                    if self.js('Boolean(machineGhostState())'):self.press('Cancel');self.wait(READY,30)
            self.click_visible('Zoom out');self.wait('machineCamera().settled',30)
        details=self.js(f"({{camera:machineCamera(),parts:{json.dumps(candidate['parts'])}.map(name=>({{name,at:machineBodies()[name],points:machineBodyHitPoints(name).slice(0,3).map(p=>({{point:p,pick:machineScenePick(...p),hit:document.elementFromPoint(...p)?.tagName}}))}}))}})")
        self.fail(f'No visible selectable body for {candidate["name"]}: {details}')

    def choose_adjustment(self,name):
        self.click_visible('Controls')
        key=self.js(f"(()=>{{const s=document.getElementById('adjustment-choice');return [...s.options].find(o=>o.textContent.replace(/\\s*\\(.*\\)\\s*$/,'')==={json.dumps(name)})?.value;}})()")
        if key is None:
            if name in ('turn','tip','roll'):
                self.click_visible('Turn selected piece')
            self.click_summary('#precision-controls > summary')
            key=self.js(f"(()=>{{const s=document.getElementById('adjustment-choice');return [...s.options].find(o=>o.textContent.replace(/\\s*\\(.*\\)\\s*$/,'')==={json.dumps(name)})?.value;}})()")
        self.assertIsNotNone(key,f'No adjustment {name}')
        self.slide('Adjustment',key);self.ghost()

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
        self.paint()

    def drag_ghost_to(self, x, z, touch=False):
        self.click_visible('Move selected piece')
        p=self.ghost()['p']
        bottom=self.js('window.machineGhostScreen().bottom')
        start=self.js("(()=>{const b=machineGhostScreen();return [(b.x0+b.x1)/2,(b.y0+b.y1)/2];})()")
        # Scene corner tools can cover a deliberately close camera's grab
        # point. Zoom out through the ordinary control before dragging.
        for _ in range(6):
            if self.js(f"document.elementFromPoint({start[0]},{start[1]})?.tagName==='CANVAS'"):break
            self.click_visible('Zoom out');self.wait('machineCamera().settled',30)
            start=self.js("(()=>{const b=machineGhostScreen();return [(b.x0+b.x1)/2,(b.y0+b.y1)/2];})()")
        self.assertTrue(self.js(f"document.elementFromPoint({start[0]},{start[1]})?.tagName==='CANVAS'"),'The drag must start on the scene, not a corner control')
        at=self.js(f'machineDragPoint({start[0]},{start[1]})')
        end=self.screen_point([at[0]+x-p['x_m'],bottom,at[2]+z-p.get('z_m',0)])
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
        if label!='GO' and self.js("Boolean(document.getElementById('level-intro')?.open)"):self.click_visible('GO')
        if label=='View':return self.key('Escape')
        if label=='Move':label='Move selected piece'
        if label=='Restart with my pieces':return self.retry_existing_setup()
        if label=='Keep my pieces':
            self.click_visible('Try again');self.ghost();return self.press('Cancel')
        if label=='Start over':label='Reset'
        if label.startswith('Adjust ') and label!='Adjust a piece':
            index=self.js(f"machineEditableObjects().find(o=>o.name.startsWith('your ')&&o.name.split(' ')[1]==={json.dumps(label[7:].replace(' ','_'))})?.index")
            if index is not None:return self.click_piece(index)
        """Hit the actual visible target, rather than invoking its DOM handler."""
        if label.startswith('Change its '):return self.choose_adjustment(label[len('Change its '):])
        if label in ('Set it down','✓ Set down'):
            label = 'Place'
        if label=='Place':self.ghost()
        self.reveal_control(self.button_expression(label))
        # Layout is updated in the game's render loop after a rebuild/edit.
        # Match a browser driver's next-paint actionability check before hit testing.
        self.page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true))))',await_promise=True)
        target = self.js(f"""(() => {{ const el = [...document.querySelectorAll('button')].find(b =>
            !b.disabled && b.offsetParent !== null && (!document.getElementById('piece-picker').open || b.closest('#piece-picker')) && (b.getAttribute('aria-label') || b.textContent).trim() === {json.dumps(label)});
            if (!el) return null; const r = el.getBoundingClientRect(), x = r.left + r.width/2, y = r.top + r.height/2;
            return {{x,y,w:r.width,h:r.height,visible:r.left>=0 && r.right<=innerWidth && r.top>=0 && r.bottom<=innerHeight,
                uncovered:el.contains(document.elementFromPoint(x,y)),blocker:document.elementFromPoint(x,y)?.outerHTML.slice(0,300)}}; }})()""")
        self.assertIsNotNone(target,(label,self.js(f"[...document.querySelectorAll('button')].filter(b=>(b.getAttribute('aria-label')||b.textContent).trim()==={json.dumps(label)}).map(b=>({{disabled:b.disabled,rect:b.getBoundingClientRect().toJSON(),parent:b.parentElement.className,ghost:machineGhostState()?.p,wire:document.getElementById('wire-mode').getAttribute('aria-pressed')}}))")))
        if label!='Close level complete' and not target['uncovered'] and self.js("Boolean(document.querySelector('#level-done:not([hidden]) .result-close'))"):
            self.click_visible('Close level complete')
            return self.click_visible(label)
        if not (target['visible'] and target['uncovered']):
            proof=ROOT/'build/ui-proof';proof.mkdir(parents=True,exist_ok=True)
            (proof/f'blocked-{self._testMethodName}.png').write_bytes(base64.b64decode(self.page.send('Page.captureScreenshot',{'format':'png'})['data']))
        self.assertTrue(target['visible'] and target['uncovered'], (label, target))
        self.assertGreaterEqual(target['w'], 44, (label, target))
        self.assertGreaterEqual(target['h'], 44, (label, target))
        self.mouse('mousePressed', target['x'], target['y'])
        self.mouse('mouseReleased', target['x'], target['y'])

    def retry_existing_setup(self):
        """Old fixtures now use the actual retry/edit/reset path, never a hidden button."""
        if self.js("location.pathname==='/machine'"):return self.click_visible('Reset')
        result=self.js("document.getElementById('level-done').hidden?null:document.getElementById('level-done').innerText")
        if result:
            if result.strip().startswith('Try again'):
                self.click_visible('Try again');self.ghost();return self.press('Cancel')
            return self.click_visible('Play this level again')
        self.click_piece(self.js('machinePlacements().length-1'));self.ghost();self.press('Cancel')

    def reveal_control(self, expression):
        """Use the real shared tabs and disclosures before touching a control."""
        if self.js(f"Boolean({expression}) && !({expression}).closest('#level-done') && Boolean(document.querySelector('#level-done:not([hidden]) .result-close'))"):
            self.click_visible('Close level complete')
        if self.js(f"Boolean({expression}) && !({expression}).closest('#recent-changes') && document.getElementById('recent-changes').open"):
            self.click_visible('Close')
        if self.js(f"Boolean(({expression})?.closest('#recent-changes')) && !document.getElementById('recent-changes').open"):
            self.js("document.getElementById('recent-changes-open').click()")
            self.wait("document.getElementById('recent-changes').open",5)
        if self.js(f"(()=>{{const el={expression};return Boolean(el?.closest('#power-pins,#terminal-pins')&&!el.getClientRects().length&&!document.getElementById('wire-mode').matches('[aria-pressed=true]'));}})()"):
            self.click_visible('Connect wires')
        panel = self.js(f"(() => {{const el={expression}; const pane=el?.closest('[role=tabpanel]'); return pane?.hidden ? document.getElementById(pane.getAttribute('aria-labelledby'))?.textContent : null;}})()")
        if panel:
            self.click_visible(panel.strip())
        # Precision controls, gallery sections and the chooser's More menu
        # remain collapsed until a player asks for them. Click each ancestor
        # summary, rather than toggling open directly to bypass the new UI.
        for _ in range(8):
            summary = self.js(f"(() => {{const el={expression}; const ds=[]; for(let p=el?.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS'&&!p.open&&!p.hidden&&!(el.tagName==='SUMMARY'&&p===el.parentElement))ds.push(p); const s=ds.at(-1)?.querySelector(':scope > summary'); if(!s)return null;s.scrollIntoView({{block:'center',inline:'nearest'}});const r=s.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2;return {{x,y,uncovered:s.contains(document.elementFromPoint(x,y)),hit:document.elementFromPoint(x,y)?.textContent}};}})()")
            if not summary:
                break
            self.assertTrue(summary['uncovered'],summary)
            self.mouse('mousePressed',summary['x'],summary['y']); self.mouse('mouseReleased',summary['x'],summary['y'])
        else:
            self.fail('A closed disclosure could not be opened with its visible summary')
        self.js(f"(() => {{const el={expression}; if (el?.closest('.phone-pane,#level-done,#recent-changes')) el.scrollIntoView({{block:el.closest('#recent-changes')?'center':'nearest',inline:'nearest'}});}})()")

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
        self.assertTrue(target['visible'] and target['uncovered'],(selector,target,self.js("['control-panel','help-settings','help-settings-content','precision-controls'].map(id=>{const e=document.getElementById(id),r=e?.getBoundingClientRect();return {id,rect:r?.toJSON(),scroll:e?.scrollTop,client:e?.clientHeight,height:e?.scrollHeight};})")))
        self.assertGreaterEqual(target['h'],44,(selector,target))
        self.mouse('mousePressed',target['x'],target['y']);self.mouse('mouseReleased',target['x'],target['y'])

    def set_precision_controls(self, enabled):
        if self.js("document.getElementById('precision-controls').open") != enabled:
            self.click_summary('#precision-controls > summary')
        self.wait(f"document.getElementById('precision-controls').open==={str(enabled).lower()}",10)
        if self.ghost()['p']['piece']=='gear' and self.js("location.pathname==='/machine'"):
            self.wait(f"[...document.getElementById('adjustment-choice').options].some(o=>o.value==='material')==={str(enabled).lower()}",10)
        self.click_visible('Controls')

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
    def test_capacitor_charges_has_live_scene_meter_and_resets_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('advanced-capacitor',width,height,phone=width!=1280)
                self.click_visible('Add a capacitor');self.ghost()
                self.slide('Its capacitance',.1);self.ghost()
                self.click_visible('Set it down');self.wait(f'!window.machineGhostState() && {READY}',60)
                self.click_visible('Try It!')
                self.wait("window.machineContactState().liveDevices.some(d=>d.kind==='capacitor'&&d.stored_j>=4)",30)
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertTrue(self.js("document.getElementById('level-done').closest('#view')!==null"))
                self.assertNotIn('finished every level',self.js("document.getElementById('level-done').textContent"))
                # The result card intentionally takes priority over optional
                # edge readings on short screens. Close it to inspect the meter.
                self.click_visible('Close level complete')
                self.wait("/run over/.test(document.getElementById('clock').textContent)",15)
                if (width,height)==(844,390):
                    # A short pending reading can be positioned near the right
                    # edge. Its measured text must grow and relocate instead
                    # of staying wrapped into a tall, permanently hidden card.
                    self.js("document.querySelector('[data-device=\"capacitor 1\"].power-feedback-label').style.left='790px';window.meterRepainted=false;requestAnimationFrame(()=>requestAnimationFrame(()=>window.meterRepainted=true))")
                    self.wait('window.meterRepainted',5)
                self.wait("window.machinePowerFeedbackState().labels.some(r=>r.device==='capacitor 1'&&/Now .* V.* J/.test(r.text)&&!r.text.includes('Updating'))",15)
                self.wait("window.machinePowerFeedbackState().labels.some(r=>r.device==='capacitor 1'&&!r.hidden)",10)
                self.assertTrue(self.js("(()=>{const el=document.querySelector('[data-device=\"capacitor 1\"].power-feedback-label'),r=el.getBoundingClientRect(),view=document.getElementById('view').getBoundingClientRect(),run=document.getElementById('start').getBoundingClientRect();return r.left>=view.left&&r.right<=view.right&&r.top>=view.top&&r.bottom<=view.bottom&&!(r.left<run.right&&r.right>run.left&&r.top<run.bottom&&r.bottom>run.top);})()"))
                self.click_visible('Restart with my pieces');self.wait(READY,60)
                self.assertTrue(all(d['stored_j']==0 for d in self.js('window.machineContactState().liveDevices') if d['kind']=='capacitor'))

    def test_parallel_activity_draws_actual_feeds_and_returns_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('advanced-parallel',width,height,phone=width!=1280)
                for lamp in ('first lamp','second lamp'):
                    for terminal in ('plus','minus'):
                        self.click_visible('Connect supply '+terminal)
                        self.wait(SETTLED,20)
                        self.click_visible('Connect '+lamp+' '+terminal)
                        self.wait(f'!window.machineGhostState() && {READY}',60)
                self.assertEqual(len(self.js('window.machinePlacements()')),4)
                self.click_visible('Try It!');self.wait("!document.getElementById('level-done').hidden",30)
                lamps=[d for d in self.js('window.machineContactState().liveDevices') if d['kind']=='bulb']
                self.assertEqual(len(lamps),2)
                self.assertTrue(all(d['power_w']>2 for d in lamps),lamps)

    def test_rc_sandbox_library_and_saved_version_preserve_component_ratings_and_wires(self):
        self.navigate(self.base+'/machine')
        self.wait("Boolean(document.querySelector('#prebuilt-designs button'))",30)
        self.press('Start from Charge and release');self.wait(READY,60)
        base=self.js('window.machineDesign().draft.base')
        cap=next(d for d in base['electrical']['devices'] if d['kind']=='capacitor')
        self.assertEqual(cap['capacitance_f'],.1)
        self.assertEqual(len(base['electrical']['wires']),6)
        version=self.js('Math.max(0,...window.machineDesign().versions.map(v=>v.number))+1')
        self.click_visible('Save version');self.wait(f"/Version {version} saved/.test(document.getElementById('design-status').textContent)",10)
        self.press('Add a piece')
        self.assertTrue(self.js("[...document.querySelectorAll('#piece-grid button')].some(b=>b.textContent.includes('capacitor'))"))
        self.assertTrue(self.js("[...document.querySelectorAll('#piece-grid button')].some(b=>b.textContent.includes('resistor'))"))
        self.navigate(self.js('location.href'));self.wait(READY,60)
        self.assertEqual(self.js('window.machineDesign().draft.base'),base)
        self.assertIn(version,[v['number'] for v in self.js('window.machineDesign().versions')])
        self.click_visible('Try It!')
        self.wait("window.machineContactState().liveDevices.some(d=>d.kind==='capacitor'&&d.stored_j>1)",30)
        self.click_visible('Pause')

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
                self.click_visible('Try It!')
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
                self.assertTrue(self.js("Boolean(document.getElementById('level-done').closest('#view'))"),
                    'The completion card is in the scene, with Close to inspect the result')
                after=self.js('window.machineThermalState()')
                self.assertTrue(after['taken'])
                self.assertFalse(any(c['body']==after['taken'][-1]['body'] for c in after['cells']),
                    'A removed segment cannot remain a char overlay; its neighbors may still be heated')
                self.click_visible('Back to scene')
                self.wait('!window.machineThermalState().inspecting',5)
                self.click_visible('Restart with my pieces');self.wait(READY,60)
                self.assertFalse(self.js('window.machineThermalState().visible'))

    def test_catalogue_audit_opens_every_level_with_attached_touch_controls(self):
        import machine_game as game
        timings=[]
        for width,height in ((1280,860),(390,844),(844,390)):
            # A long browser sweep reported ERR_NO_BUFFER_SPACE while fetching
            # a module. Bound fixture accumulation with a fresh owned profile
            # per viewport, retaining the same waits and assertions. Keep the
            # class-owned handles current for subsequent methods and cleanup.
            type(self).chrome.close()
            type(self).chrome=chrome_driver.Chrome(width,height)
            type(self).page=type(self).chrome.page;self.page.send('Network.enable');self.page.send('Runtime.enable')
            for level in game.load_levels():
                with self.subTest(level=level['id'],viewport=(width,height)):
                    opened_at=time.perf_counter()
                    self.open(level['id'],width,height,phone=width!=1280)
                    timings.append(dict(id=level['id'],viewport=[width,height],load_wall_s=round(time.perf_counter()-opened_at,3)))
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
        if os.environ.get('BANJO_ONBOARDING_UI_REPORT'):
            Path(os.environ['BANJO_ONBOARDING_UI_REPORT']).write_text(json.dumps(timings,indent=2),encoding='utf-8')

    def test_audited_level_order_estimates_and_primary_controls(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            self.anonymous_levels(width=width,height=height)
            ids=self.js("[...document.querySelectorAll('#levels-screen .level-card')].map(n=>n.dataset.level)")
            self.assertEqual(len(ids),34);self.assertEqual(ids[0],'easy-weight');self.assertEqual(ids[-1],'fire')
            self.assertLess(ids.index('easy-mirror'),ids.index('laser'))
            self.assertLess(ids.index('easy-loop'),ids.index('advanced-parallel'))
            self.assertEqual(self.js("document.querySelectorAll('.level-time-estimate').length"),34)
            self.assertTrue(self.js(r"[...document.querySelectorAll('.level-time-estimate')].every(n=>/^Est\. [0-9]+–[0-9]+ min$/.test(n.textContent)&&n.title.includes('not measured human'))"))
            self.assertLessEqual(self.js('document.documentElement.scrollWidth'),width)
            self.open('easy-weight',width,height,phone=width!=1280)
            self.press('Add a weight');self.ghost()
            self.assertEqual(self.js("[...document.getElementById('adjustment-choice').options].map(o=>o.value)"),['x_m','z_m','height_m'])
            self.press('Cancel')
            self.open('easy-river-lift',width,height,phone=width!=1280)
            self.press('Add a water wheel');self.ghost()
            self.assertEqual(self.js("document.getElementById('adjustment-choice').value"),'z_m')
            self.assertFalse(self.js("[...document.getElementById('adjustment-choice').options].some(o=>o.value==='discharge_l_s')"))
            self.press('Cancel')
            self.open('sun',width,height,phone=width!=1280)
            self.assertFalse(self.js("document.getElementById('sun-bearing').hidden"))
            self.press('Add a solar panel');self.ghost()
            self.assertEqual(self.js("document.getElementById('adjustment-choice').value"),'pitch_deg')
            self.assertFalse(self.js("[...document.getElementById('adjustment-choice').options].some(o=>o.value==='roll_deg')"))
            self.click_summary('#precision-controls > summary')
            self.assertFalse(self.js("[...document.getElementById('adjustment-choice').options].some(o=>o.value==='roll_deg')"))
            self.press('Cancel')

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
                self.click_visible('Try It!');self.wait("/World [12]\\./.test(document.getElementById('clock').textContent)",30)
                self.click_visible('Pause')
                self.assertTrue(self.js("document.getElementById('level-done').hidden"))
                self.click_visible('Restart with my pieces');self.wait(READY,60)
                self.assert_power_layout()
                self.click_visible('Power output of your solar 1');self.click_visible('Power input of supply')
                self.wait(f'window.machinePlacements().length===2 && {READY}',60)
                self.click_visible('Try It!');self.wait("!document.getElementById('level-done').hidden",30)

    def test_motor_lesson_requires_choosing_forward_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-motor',width,height,phone=width!=1280)
                self.press('Add a motor');state=self.ghost()
                self.assertEqual(state['p']['direction'],'reverse')
                self.slide('direction of your motor 1','forward');self.ghost()
                self.click_visible('Try It!');self.wait("!document.getElementById('level-done').hidden",30)
                cables=self.js('machineWiringState().wires')
                self.assertEqual(len(cables),2)
                for cable in cables:
                    physical=cable['mechanical']
                    self.assertTrue(physical['connected'])
                    self.assertGreater(physical['mass_kg'],.01)
                    self.assertGreater(len(physical['segments_m']),8)
                    self.assertLess(physical['max_joint_gap_m'],.003)
                    self.assertGreater(cable['vertices'],len(physical['segments_m'])*12)
                # The swept rotor box is y=.1246..5554, z=±.06.
                # Read the actual rendered polylines: no segment may enter it.
                for cable in cables:
                    for a,b in zip(cable['route'],cable['route'][1:]):
                        for i in range(101):
                            p=[a[k]+(b[k]-a[k])*i/100 for k in range(3)]
                            self.assertTrue(p[1]<.12 or abs(p[2])>.08 or abs(p[0])>.24,(cable,p))

    def test_motor_leads_fall_after_placing_before_try_it_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-motor',width,height,phone=width!=1280)
                self.press('Add a motor');self.ghost()
                self.slide('direction of your motor 1','forward');self.ghost()
                self.click_visible('Set it down');self.wait(f'!window.machineGhostState() && {READY}',60)
                self.wait('machineWiringState().wires.length===2 && machineWiringState().wires.every(w=>w.mechanical)',10)
                first=self.js('machineWiringState().wires.map(w=>w.mechanical)')
                # Sample actual native endpoints while the user has not run.
                self.wait('machineWiringState().wires.some(w=>w.mechanical.kinetic_j>0.00001)',10)
                import time
                time.sleep(.6)
                settled=self.js('machineWiringState().wires.map(w=>w.mechanical)')
                self.assertNotEqual([c['segments_m'] for c in first],[c['segments_m'] for c in settled])
                self.assertTrue(self.js('machineWiringState().wires.every(w=>w.visible)'))
                self.assertTrue(self.js("document.getElementById('start').textContent.includes('Try It')"))
                setup=self.js('window.machineCableSetupState()')
                self.assertTrue(setup['active'])
                self.assertEqual(setup['t'],0)
                self.click_visible('Try It!');self.wait("!document.getElementById('level-done').hidden",30)
                self.assertEqual(self.js('window.machineCableSetupState().session'),setup['session'])
                self.assertTrue(all(w['mechanical']['connected'] for w in self.js('machineWiringState().wires')))

    def test_bulb_shrinks_to_match_visible_supply_limit_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-bulb',width,height,phone=width!=1280)
                self.press('Add a bulb');self.ghost()
                self.assertEqual(self.js("document.querySelector('[aria-label=\"Its bulb size\"]').value"),'large')
                self.click_visible('Set it down');self.wait(f'!window.machineGhostState() && {READY}',60)
                self.wait("window.machinePowerFeedbackState().labels.some(r=>r.device==='bulb 1'&&/12 V.*12\\.0 W/.test(r.text))",30)
                self.wait("window.machinePowerFeedbackState().labels.some(r=>/Shared supply ≤ 2\\.5 W/.test(r.text))",30)
                self.click_visible('Try It!');self.wait("/World [12]\\./.test(document.getElementById('clock').textContent)",30)
                self.click_visible('Pause')
                self.assertTrue(self.js("document.getElementById('level-done').hidden"))
                big=next(d for d in self.js('window.machineContactState()')['liveDevices'] if d['kind']=='bulb')
                self.assertAlmostEqual(big['power_w'],.520833333,places=6)
                self.click_piece(0)
                self.ghost();self.press('Change its bulb size');self.slide('Its bulb size','small');self.ghost()
                self.click_visible('Set it down');self.wait(f'!window.machineGhostState() && {READY}',60)
                self.wait("window.machinePowerFeedbackState().labels.some(r=>r.device==='bulb 1'&&/12 V.*2\\.5 W/.test(r.text))",30)
                self.click_visible('Try It!');self.wait("!document.getElementById('level-done').hidden",30)
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
                self.wait('window.machineCamera().settled',30)
                x,y=self.js("machineBodyScreen('your battery 1 housing')")
                if width!=1280:
                    self.page.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x,'y':y,'id':1}]})
                    self.page.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
                else:
                    self.mouse('mousePressed',x,y);self.mouse('mouseReleased',x,y)
                self.ghost();self.assertEqual(self.js('machineGhostState().p.piece'),'battery')
                self.assertEqual(self.js('machineGhostState().p.voltage_v'),12)
                self.press('Throw the ghost away')
                self.wait(READY,60)
                self.click_visible('Adjust battery');self.ghost()
                self.assertEqual(self.js('machineGhostState().p.voltage_v'),12)
                self.press('Throw the ghost away');self.wait(READY,60)
                self.wait("!document.getElementById('scene-wire-hint').hidden",5)
                # A mistaken feed and return can share lamp minus. Remove only
                # the clicked lead, then start drawing again from the real rings.
                for a,b in [('your battery 1:plus','lamp:minus'),('lamp:minus','your battery 1:minus')]:
                    self.click_scene_socket(a,touch=width!=1280);self.ghost()
                    self.click_scene_socket(b,touch=width!=1280)
                    self.wait(f'!window.machineGhostState() && {READY}',60)
                self.assertEqual(self.js("machinePlacements().filter(p=>p.piece==='wire'&&(p.a_terminal==='lamp:minus'||p.b_terminal==='lamp:minus')).length"),2)
                self.click_existing_wire('your wire 2',touch=width!=1280,hold=.2)
                self.wait(f'machinePlacements().length===2 && {READY}',60)
                self.assertEqual(self.js('machinePlacements()[1].a_terminal'),'lamp:minus')
                self.assertEqual(self.js('machinePlacements()[1].b_terminal'),'your battery 1:minus')
                self.click_visible('Undo');self.wait(f'machinePlacements().length===3 && {READY}',60)
                self.click_existing_wire('your wire 2',touch=width!=1280)
                self.wait(f'machinePlacements().length===2 && {READY}',60)
                self.click_existing_wire('your wire 2',touch=width!=1280)
                self.wait(f'machinePlacements().length===1 && {READY}',60)
                for a,b in [('your battery 1:plus','lamp:plus'),('lamp:minus','your battery 1:minus')]:
                    self.click_scene_socket(a,touch=width!=1280)
                    self.wait("window.machineGhostState()?.answered && !window.machineGhostState()?.busy",20)
                    for gauge in ('Thin','Standard','Thick','Thin'):
                        self.click_visible(gauge+' wire');self.ghost()
                        self.assertEqual(self.js('machineGhostState().p.size'),gauge.lower())
                        self.assertEqual(self.js(f"document.querySelector('[aria-label=\"{gauge} wire\"]').getAttribute('aria-pressed')"),'true')
                    self.click_scene_socket(b,touch=width!=1280)
                    self.wait(f'!window.machineGhostState() && {READY}',60)
                self.wait('window.machineFlowPreviewState()?.frames>0',30)
                self.reveal_control("document.getElementById('flow-play')")
                self.wait("document.getElementById('flow-play').getClientRects().length && /^(Play|Pause) preview$/.test(document.getElementById('flow-play').textContent)",10)
                if self.js("document.getElementById('flow-play').textContent==='Play preview'"):
                    self.click_visible('Play preview')
                self.wait("window.machinePowerFeedbackState().labels.some(r=>r.device==='lamp'&&/8\\.8 V/.test(r.text))",30)
                self.assert_wire_gauges_readable('Thin','0.01 mm²')
                self.assertTrue(self.js("window.machinePowerFeedbackState().labels.some(r=>r.device==='lamp'&&/1\\.6 W/.test(r.text))"))
                for index in (1,2):
                    self.click_piece(index)
                    self.ghost();self.press('Change its wire thickness')
                    self.click_visible('Standard wire');self.ghost()
                    self.click_visible('Set it down');self.wait(f'!window.machineGhostState() && {READY}',60)
                self.wait('window.machineFlowPreviewState()?.frames>0',30)
                self.reveal_control("document.getElementById('flow-play')")
                self.wait("document.getElementById('flow-play').getClientRects().length && /^(Play|Pause) preview$/.test(document.getElementById('flow-play').textContent)",10)
                if self.js("document.getElementById('flow-play').textContent==='Play preview'"):
                    self.click_visible('Play preview')
                self.wait("window.machinePowerFeedbackState().labels.some(r=>r.device==='lamp'&&/11\\.9 V/.test(r.text))",30)
                self.assert_wire_gauges_readable('Standard','0.5 mm²')
                self.assertTrue(self.js("window.machinePowerFeedbackState().labels.some(r=>r.device==='lamp'&&/3\\.0 W/.test(r.text))"))
                self.click_visible('Try It!');self.wait("!document.getElementById('level-done').hidden",30)
                self.assertGreater(next(d for d in self.js('window.machineContactState()')['liveDevices'] if d['kind']=='bulb')['power_w'],2)

    def test_wire_readings_stay_at_scene_edges_with_leaders_and_do_not_cover_components(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-power',width,height,phone=width!=1280)
                self.press('Add a battery');self.ghost();self.slide('Its voltage',12);self.ghost()
                self.press('Set it down');self.wait(READY,30)
                for count,terminal in enumerate(('plus','minus'),2):
                    self.click_scene_socket('your battery 1:'+terminal,touch=width!=1280);self.ghost()
                    self.click_scene_socket('lamp:'+terminal,touch=width!=1280)
                    self.wait(f'!machineGhostState() && {READY}',30)
                    # Connection picking keeps the view clear. Change gauge
                    # through the existing placed-wire control afterwards.
                    self.wait(f"[...document.querySelectorAll('#wire-adjustments button')].some(b=>b.textContent.startsWith('Wire {count} '))",5)
                    label=self.js(f"[...document.querySelectorAll('#wire-adjustments button')].find(b=>b.textContent.startsWith('Wire {count} ')).getAttribute('aria-label')")
                    self.click_visible(label);self.ghost();self.click_visible('Standard wire');self.ghost()
                    self.click_visible('Place');self.wait(READY,30)
                # The always-open dock leaves less space in landscape. Optional
                # wire cards may yield; the lamp rating must stay readable.
                label_count='machineReadoutCallouts().labels.length'+('>=1' if height<500 else '===3')
                self.wait(label_count,30)
                self.assertIsNone(self.js("document.getElementById('panel-toggle')"))
                self.wait('machineCamera().settled',30)
                for moved in (False,True):
                    if moved:
                        start=self.empty_scene_point()
                        self.drag(start,[start[0]-35,start[1]+10],touch=width!=1280)
                        self.wait('machineCamera().settled',30)
                    self.wait(label_count,10)
                    # Preview wires can move between CDP requests even after
                    # the camera settles. Capture every compared coordinate in
                    # one frame; the Python assertions must not resample it.
                    snapshot=self.page.evaluate('''new Promise(resolve=>requestAnimationFrame(()=>{
                        const layout=machineReadoutCallouts();
                        const view=document.getElementById('view').getBoundingClientRect().toJSON();
                        const anchors=Object.fromEntries(layout.labels.filter(label=>label.wire)
                            .map(label=>[label.wire,machineWireScreen(label.wire)]));
                        resolve({layout,view,anchors});
                    }))''',await_promise=True)
                    layout=snapshot['layout']
                    self.assertTrue(any(label.get('device')=='lamp' for label in layout['labels']),layout)
                    for label in layout['labels']:
                        self.assertTrue(label['x']<=8 or label['x']+label['w']>=layout['width']-8,(label,layout))
                        self.assertTrue(label['leader'],label)
                        self.assertGreaterEqual(label['y'],0);self.assertLessEqual(label['y']+label['h'],layout['height'])
                        for body in layout['bodies']:
                            overlap=(label['x']<body['x']+body['w'] and label['x']+label['w']>body['x'] and
                                     label['y']<body['y']+body['h'] and label['y']+label['h']>body['y'])
                            self.assertFalse(overlap,(label,body))
                        self.assertTrue(label['x']<=label['to'][0]<=label['x']+label['w'] and
                                        label['y']<=label['to'][1]<=label['y']+label['h'],label)
                        if label.get('wire'):
                            anchor=snapshot['anchors'][label['wire']]
                            view=snapshot['view']
                            self.assertAlmostEqual(label['from'][0]+view['x'],anchor[0],delta=2)
                            self.assertAlmostEqual(label['from'][1]+view['y'],anchor[1],delta=2)

    def place_contact_battery(self, placement, charge=None):
        self.press('Add a battery'); self.ghost()
        knobs = next(t['knobs'] for t in self.power_level['tray'] if t['piece'] == 'battery')
        for key, value in placement.items():
            if key == 'piece': continue
            if self.ghost()['p'].get(key)==value:continue
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
                self.click_visible('Try It!')
                self.wait("document.getElementById('preview-legend').hidden",5)
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
                    if mode=='empty':
                        # Charge is a Sandbox setting; lessons expose only
                        # their relevant adjustments. Use its real example.
                        self.navigate(f'{self.base}/machine')
                        self.wait("Boolean(document.querySelector('#prebuilt-designs button'))",30)
                        self.press('Start from Drop a battery into its holder');self.wait(READY,60)
                        self.click_piece(0);self.ghost()
                        self.slide('initial charge (%) of your battery 1',0);self.ghost()
                        self.press('Set it down');self.wait(READY,60)
                    else:self.place_contact_battery(placement)
                    self.click_visible('Try It!')
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
                self.navigate(f'{self.base}/machine')
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
                self.navigate(self.js('location.href'));self.wait(READY,60)
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
                self.click_visible('Try It!')
                self.wait("window.machineContactState().liveDevices.some(d=>d.kind==='bulb' && d.power_w>2)",30)
                self.press('Pause')
                self.assertGreaterEqual(sum(c['closed'] for c in self.js('window.machineContactState().liveContacts')),2)

    def test_contact_battery_solar_cable_and_input_follow_the_fallen_pack(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.page.send('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':width!=1280})
                self.page.send('Emulation.setTouchEmulationEnabled',{'enabled':width!=1280,'maxTouchPoints':5})
                self.navigate(f'{self.base}/machine')
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
                self.click_visible('Try It!')
                self.wait("window.machineContactState().liveDevices.some(d=>d.kind==='bulb' && d.power_w>2)",30)
                # First electrical contact precedes the pack settling. Wait
                # for its actual input port to fall the declared distance,
                # instead of pausing at whichever contact frame arrived first.
                self.wait(f"machineWiringState().powerPorts['your battery 1:power'][1]<{before[1]-.1}",10)
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
                    self.click_visible('Controls');self.click_visible('Try It!')
                    if ident=='easy-spring':
                        self.wait("document.getElementById('clock').textContent.includes('Release spring')",30)
                        self.assertAlmostEqual(self.js(f'window.machineBodies()[{json.dumps(target)}]')[1],before[1],places=3)
                        self.assertTrue(self.js("[...document.querySelectorAll('#device-live-controls button')].some(b=>b.textContent==='Release spring' && b.checkVisibility())"))
                        self.click_visible('Release spring')
                    self.wait("!document.getElementById('level-done').hidden",30)
                    after=self.js(f'window.machineBodies()[{json.dumps(target)}]')
                    self.assertGreater(after[1],before[1]+(.049 if ident=='easy-spring' else .249))
                    self.assertFalse(self.js(f"Object.keys(window.machineBodies()).some(n=>/^your (spring|tackle) \\d+ load$/.test(n))"))

    def test_gear_lesson_requires_an_individual_sized_and_placed_gear(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-gears',width,height,phone=width!=1280)
                self.assertIn('target gear wheel',self.js('Object.keys(window.machineBodies())'))
                self.press('Add a gear');self.ghost()
                self.assertEqual(self.js('machineWorkingGuide().primary.label'),'wheel axle')
                self.wait("machineWorkingGuide().wheels.length===2",10)
                self.assertTrue(all(not row['samePlane'] for row in self.js('machineWorkingGuide().wheels')))
                self.assertIn('Plane off',self.js("document.getElementById('gear-plane-feedback').textContent"))
                self.slide('Position across (m) of your gear 1',0);self.ghost()
                self.wait("machineWorkingGuide().wheels.every(row=>row.samePlane&&row.sameHeight)",10)
                self.assertTrue(all(row['ring_color']==0x50ffb0 for row in self.js('machineWorkingGuide().wheels')))
                self.assertIn('Plane aligned',self.js("document.getElementById('gear-plane-feedback').textContent"))
                self.wait("document.getElementById('gear-motion-feedback').textContent.includes('Teeth apart')",10)
                self.slide('Position along (m) of your gear 1',.15);self.ghost()
                self.assertFalse(self.ghost()['fits'])
                self.wait("document.getElementById('gear-motion-feedback').textContent.includes('Clear the overlap')",10)
                self.slide('Position along (m) of your gear 1',-1);self.ghost()
                self.slide('Axle height (m) of your gear 1',.70);self.ghost()
                self.wait("machineWorkingGuide().wheels.every(row=>row.samePlane&&!row.sameHeight)",10)
                self.assertIn('Height off 5.0 cm',self.js("document.getElementById('gear-plane-feedback').textContent"))
                self.slide('Axle height (m) of your gear 1',.65);self.ghost()
                self.choose_adjustment('Teeth')
                self.set_precision_controls(False)
                self.assertEqual(self.ghost()['p']['teeth'],18)
                self.assertFalse(self.js("document.querySelector('[aria-label=\"Its Teeth\"]').checkVisibility()"))
                self.assertEqual(self.js("[...document.querySelectorAll('#piece-editor [data-gear-key]')].map(b=>b.dataset.gearKey)"),['teeth','module_m','height_m'])
                self.assertFalse(self.js("document.getElementById('adjustment-choice').checkVisibility()"))
                self.assertEqual(self.js("[...document.getElementById('adjustment-choice').options].map(o=>o.value)"),['teeth','module_m','height_m'])
                self.click_visible('Choose Teeth');self.click_visible('Set Teeth to 12 teeth');self.ghost()
                self.assertEqual(self.ghost()['p']['teeth'],12)
                self.assertEqual(len(self.ghost()['editGuide']['arrows']),4)
                self.assertEqual(self.ghost()['editGuide']['focus'],['your gear 1 wheel'])
                self.set_precision_controls(True)
                self.assertFalse(self.js("document.querySelector('[aria-label=\"Change its Tooth alignment\"]')!==null"))
                self.click_visible('Change its Teeth');self.ghost()
                self.wait('window.machineCamera().settled',30)
                self.drag_ghost_to(0,0,touch=width!=1280)
                self.assertTrue(self.ghost()['fits'],self.ghost())
                self.wait("machineFlowPreviewState()?.visible&&!machineFlowPreviewState().pending&&machineFlowPreviewState().playing",30)
                self.wait("machineFlowPreviewState().drawn?.mechanisms?.some(b=>b.name==='drive gear wheel'&&Math.abs(b.orientation_wxyz[3])>.01)",30)
                self.assertIn('Preview',self.js("document.getElementById('gear-motion-feedback').textContent"))
                self.paint()
                self.assertTrue(self.js("['drive gear wheel','target gear wheel'].every(name=>{const p=machineBodyScreen(name);return p&&!document.elementFromPoint(...p)?.closest('#piece-editor');})"),'The editor must leave both wheel centres visible')
                sample=self.js("(()=>{const s=machineFlowPreviewState(),d=s.drawn.mechanisms.find(b=>b.name==='drive gear wheel'),p=s.sample.mechanisms.find(b=>b.name===d.name);return [d,p];})()")
                self.assertEqual(sample[0]['position_m'],sample[1]['position_m'])
                self.assertEqual(sample[0]['orientation_wxyz'],sample[1]['orientation_wxyz'])
                self.assertRegex(self.js("document.getElementById('clock').textContent"),r'World 0\.00 s')
                self.click_visible('Try It!')
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Goal at',self.js("document.getElementById('verdict').textContent"))
                self.assertIn('target gear wheel',self.js('Object.keys(window.machineBodies())'))
                for cable in self.js('machineWiringState().wires'):
                    for a,b in zip(cable['route'],cable['route'][1:]):
                        for i in range(101):
                            p=[a[k]+(b[k]-a[k])*i/100 for k in range(3)]
                            self.assertTrue(p[1]<.32 or p[2]<-.05,(cable,p))

    def test_gear_radius_choices_show_real_size_and_keep_secondary_settings_in_help(self):
        for width,height in ((1280,860),(390,844),(844,390),(320,568)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-gears',width,height,phone=width!=1280)
                self.press('Add a gear');self.ghost()
                self.set_precision_controls(False)
                self.wait('machineCamera().settled',30)
                geometry="""(() => {const v=document.getElementById('view').getBoundingClientRect(),body=machineGhostScreen();
                  return [...document.querySelectorAll('#piece-editor [data-gear-key]')].map(b=>{const r=b.getBoundingClientRect();return {key:b.dataset.gearKey,
                    value:b.querySelector('.gear-value').textContent,w:r.width,h:r.height,visible:r.left>=v.left&&r.right<=v.right&&r.top>=v.top&&r.bottom<=v.bottom,
                    uncovered:b.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)),
                    coversGear:body&&r.left<body.x1&&r.right>body.x0&&r.top<body.y1&&r.bottom>body.y0};});})()"""
                self.wait(f"({geometry}).every(b=>b.visible&&b.uncovered&&!b.coversGear)",10)
                fields=self.js(geometry)
                self.assertEqual([b['value'] for b in fields],['18','23.3 cm','65 cm'])
                self.assertTrue(all(b['w']>=44 and b['h']>=44 for b in fields),fields)
                self.assertFalse(self.js("document.querySelector('#piece-editor select')!==null"))
                self.assertIn('23.3 cm radius',self.js("document.getElementById('adjustment-feedback').textContent"))
                self.click_visible('Choose Radius')
                self.click_visible('Set Radius to 15.5 cm radius');self.ghost()
                self.assertEqual(self.ghost()['p']['module_m'],.016)
                self.assertEqual(self.ghost()['p']['teeth'],18)
                self.assertIn('15.5 cm radius',self.js("document.getElementById('adjustment-feedback').textContent"))
                self.click_visible('Choose Teeth');self.click_visible('Set Teeth to 24 teeth');self.ghost()
                self.assertIn('20.3 cm radius',self.js("document.getElementById('adjustment-feedback').textContent"))
                self.assertEqual(self.js("document.querySelector('[data-gear-key=module_m] .gear-value').textContent"),'20.3 cm')
                self.click_visible('Adjust Axle height');self.ghost()
                self.wait("machineGhostState().editGuide?.key==='height_m'",10)
                self.click_visible('Increase Axle height on object');self.ghost()
                self.assertEqual(self.ghost()['p']['height_m'],.66)
                self.assertEqual(self.js("document.querySelector('[data-gear-key=height_m] .gear-value').textContent"),'66 cm')
                self.set_precision_controls(True)
                self.assertNotIn('material',self.js("[...document.getElementById('adjustment-choice').options].map(o=>o.value)"))
                self.set_precision_controls(False)
                self.assertEqual(self.js("[...document.getElementById('adjustment-choice').options].map(o=>o.value)"),['teeth','module_m','height_m'])

    def test_holding_adjustment_buttons_repeats_and_release_or_touch_cancel_stops(self):
        for level,piece,key,adjustment,width,height,touch in (
                ('easy-gears','gear','height_m','Axle height',1280,860,False),
                ('easy-lens','lens','radius_m','Focus / face radius',844,390,True),
                ('easy-power','battery','voltage_v','voltage',320,568,True)):
            with self.subTest(level=level,viewport=(width,height)):
                self.open(level,width,height,phone=width!=1280)
                self.press('Add a '+('battery' if piece=='battery' else 'gear' if piece=='gear' else 'lens'));self.ghost()
                if piece=='gear':self.click_visible('Adjust Axle height')
                else:self.choose_adjustment(adjustment)
                self.ghost();self.wait('machineCamera().settled',20);self.paint()
                label='Increase '+adjustment+' on object'
                # Lens naming follows the visible schema's shortened label.
                if piece=='lens':label='Increase Face radius on object'
                self.wait(f"document.querySelector('[aria-label={json.dumps(label)}]')?.checkVisibility()",10)
                b=f"document.querySelector('[aria-label={json.dumps(label)}]')"
                xy=self.js(f"(()=>{{const b={b},r=b.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];}})()")
                before=self.ghost()['p'][key]
                if touch:self.page.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':xy[0],'y':xy[1]}]})
                else:self.mouse('mousePressed',*xy)
                time.sleep(.85)
                if touch:self.page.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
                else:self.mouse('mouseReleased',*xy)
                after=self.ghost()['p'][key]
                self.assertGreaterEqual(after-before,6 if piece=='battery' else .029,'A stationary hold repeats, within the declared range')
                step=self.js(f"machineGhostState().editGuide?.key==={json.dumps(key)}")
                self.assertTrue(step)
                time.sleep(.3);self.assertEqual(self.ghost()['p'][key],after,'Release stops further changes')
                if piece=='battery':
                    self.assertEqual(after,12,'Repeated steps clamp at the battery maximum')
                    self.click_visible('Decrease voltage on object')
                    self.assertEqual(self.ghost()['p'][key],6)
                else:
                    self.click_visible(label);tapped=self.ghost()['p'][key]
                    self.assertAlmostEqual(tapped-after,.01,msg='A subsequent tap makes exactly one increment')
        # The direct spring buttons use the same hold behavior and clamp at
        # declared limits. Cancel a touch without generating a release click.
        self.open('easy-spring',390,844,phone=True);self.press('Add a spring');self.ghost()
        def touch_hold(label,cancel=False,seconds=.85):
            xy=self.js(f"(()=>{{const b=document.querySelector('[aria-label={json.dumps(label)}]'),r=b.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];}})()")
            self.page.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':xy[0],'y':xy[1]}]})
            time.sleep(seconds)
            self.page.send('Input.dispatchTouchEvent',{'type':'touchCancel' if cancel else 'touchEnd','touchPoints':[]})
            return self.ghost()['p']['rest_m']
        length=touch_hold('Lengthen spring',True)
        self.assertGreaterEqual(length,.35)
        time.sleep(.3);self.assertEqual(self.ghost()['p']['rest_m'],length)
        self.assertEqual(touch_hold('Shorten spring',seconds=2),.2)
        self.assertTrue(self.js("document.querySelector('[aria-label=\"Shorten spring\"]').disabled"))
        self.click_visible('Lengthen spring');self.assertEqual(self.ghost()['p']['rest_m'],.25)
        self.wait('machineCamera().settled',20)
        before=self.js('machineCamera().distance')
        xy=self.js("(()=>{const r=document.getElementById('view-out').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];})()")
        self.mouse('mousePressed',*xy);time.sleep(.75);self.mouse('mouseReleased',*xy)
        self.wait('machineCamera().settled',20)
        after=self.js('machineCamera().distance')
        self.assertGreater(after,before*1.44,'Zoom buttons repeat too')
        time.sleep(.3);self.assertEqual(self.js('machineCamera().distance'),after)
        self.paint()
        b="document.querySelector('[aria-label=\"Increase Relaxed length on object\"]')"
        xy=self.js(f"(()=>{{const r={b}.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];}})()")
        axis=self.js(f"[{b}.dataset.dx,{b}.dataset.dy].map(Number)")
        self.mouse('mousePressed',*xy);time.sleep(.55)
        end=[xy[i]+40*axis[i] for i in range(2)]
        self.mouse('mouseMoved',*end);time.sleep(.3)
        dragged=self.js('machineGhostState().p.rest_m')
        time.sleep(.3)
        self.assertEqual(self.js('machineGhostState().p.rest_m'),dragged,'Dragging cancels stationary hold repetition')
        self.mouse('mouseReleased',*end);self.ghost()
        self.assertEqual(self.js('machineGhostState().p.rest_m'),dragged,'Drag release cannot add a tap')

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

    def test_plumbing_library_radius_controls_saved_versions_and_phone_scene(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(width=width,height=height):
                self.anonymous_levels(width=width,height=height)
                self.press('Sandbox: build anything');self.wait("!document.getElementById('sandbox-screen').hidden",10)
                self.press('Start from Water through pipes');self.wait(READY,60)
                self.assertEqual([p['piece'] for p in self.js('machinePlacements()')],
                                 ['water_tank','pipe_elbow','pipe_reducer','water_collector'])
                self.press('Add a piece');self.slide('Search pieces','pipe')
                self.assertEqual(self.js("[...document.querySelectorAll('#piece-grid strong')].map(e=>e.textContent)"),
                                 ['straight pipe','pipe elbow','pipe reducer'])
                self.press('Back to sandbox')
                self.slide('Adjust a piece','2');self.ghost()
                self.slide('outlet inside radius (m) of your pipe_reducer 3',.09)
                self.assertTrue(self.ghost()['fits'])
                self.assertEqual(self.ghost()['p']['outlet_radius_m'],.09)
                self.press('Set it down');self.wait(READY,60)
                before=self.js('machineDesign().versions.length')
                self.press('Save version');self.wait(f'machineDesign().versions.length==={before+1}',10)
                self.page.send('Page.reload',{});self.wait(READY,60)
                self.assertEqual(self.js('machinePlacements()[2].outlet_radius_m'),.09)
                self.click_visible('Try It!')
                self.wait("Number(document.getElementById('collector-status').textContent.match(/Container ([\\d.]+)/)?.[1])>0",30)
                self.click_visible('Pause')
                self.assertTrue(self.js("Number(document.getElementById('collector-status').textContent.match(/Container ([\\d.]+)/)?.[1])>0"))
                self.press('Restart with my pieces');self.wait(READY,60)
                self.slide('Adjust a piece','1');self.ghost()
                self.slide('support of your pipe_elbow 2','loose')
                self.assertTrue(self.ghost()['fits'])
                self.assertEqual(self.js("machineGhostState().p.support"),'loose')
                self.press('Cancel')

    def test_pipe_marble_and_removable_platform_work_through_ordinary_controls(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(width=width,height=height):
                self.anonymous_levels(width=width,height=height)
                self.press('Sandbox: build anything');self.wait("!document.getElementById('sandbox-screen').hidden",10)
                self.press('Start from Marble through a pipe');self.wait(READY,60)
                self.click_visible('Try It!')
                self.wait("machineBodies()['your marble 2'][0]>.65",30)
                self.click_visible('Pause');self.press('Restart with my pieces');self.wait(READY,60)
                self.slide('Adjust a piece','1');self.ghost()
                self.slide('starting position of your marble 2','on surface');self.ghost()
                self.assertFalse(self.js("Boolean(document.querySelector('[aria-label=\"center height (m) of your marble 2\"]')?.getClientRects().length)"))
                self.slide('starting position of your marble 2','at height');self.ghost()
                self.assertTrue(self.ghost()['fits'])
                self.press('Set it down');self.wait(READY,60)
                self.js("document.getElementById('sandbox-open').click()")
                self.wait("!document.getElementById('sandbox-screen').hidden",10)
                self.press('Start from Support a loose board');self.wait(READY,60)
                self.click_visible('Try It!');self.wait("/World [1-9]/.test(document.getElementById('clock').textContent)",30)
                self.click_visible('Pause')
                self.assertAlmostEqual(self.js("machineBodies()['loose board'][1]"),.62,delta=.001)
                self.press('Restart with my pieces');self.wait(READY,60)
                self.press('Remove your scaffold 1');self.wait(f'machinePlacements().length===0 && {READY}',60)
                self.click_visible('Try It!');self.wait("machineBodies()['loose board'][1]<.1",30)
                self.click_visible('Pause')

    def place_river_wheel(self):
        self.press('Add a water wheel');initial=self.ghost()['p']
        self.assertEqual(initial['radius_m'],self.river_solution['radius_m'],'The river base must provide its usable wheel size before editing')
        self.assertEqual(initial['side'],'off','The river wheel must start with its falling pour off')
        lesson_button=self.js("Boolean([...document.querySelectorAll('button')].find(b=>b.textContent==='Connect rope to gate'))")
        fields=[('x_m','along channel (m)'),('z_m','across river (m)')]
        if not lesson_button:fields.append(('radius_m','wheel radius (m)'))
        for key,label in fields:
            self.slide(f'{label} of your water_wheel 1',self.river_solution[key])
        if lesson_button:
            self.click_visible('Controls')
            self.wait("(()=>{const b=[...document.querySelectorAll('#piece-editor button')].find(b=>b.textContent==='Connect rope to gate');if(!b)return false;const r=b.getBoundingClientRect();return r.width>0&&b.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})()",5)
            self.click_visible('Connect rope to gate');self.ghost()
            self.assertEqual(self.ghost()['p']['load_part'],'river gate')
            self.click_visible('Disconnect rope from gate');self.ghost()
            self.assertEqual(self.ghost()['p']['load_part'],'')
            self.click_visible('Connect rope to gate');self.ghost()
            self.click_visible('Set it down');self.wait(f'!window.machineGhostState() && {READY}',60)
            return
        self.press('Change its load to lift')
        self.slide('load to lift (optional) of your water_wheel 1','')
        self.ghost()
        self.assertEqual(self.js("document.querySelector('[aria-label=\"Its load to lift\"]').value"),'')
        self.slide('load to lift (optional) of your water_wheel 1',self.river_solution['load_part'])
        self.ghost()
        self.assertEqual(self.js("document.querySelector('[aria-label=\"Its load to lift\"]').value"),'river gate',
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
                self.click_visible('Try It!')
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertEqual(len(self.js('window.machinePlacements()')),1)
                self.assertIn('Goal at',self.js("document.getElementById('verdict').textContent"))
                self.assertLess(self.js('window.machineWaterDisplay()[0].litres'),4)
                self.click_visible('Restart with my pieces');self.wait(READY,60)
                self.wait('window.machineWaterDisplay()[0].litres===4',10)
                self.assertEqual(self.js('window.machinePlacements()[0].opening_percent'),75)

    def test_divert_water_starts_automatically_and_has_no_unneeded_valve(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-divert-water',width,height,phone=width!=1280,dismiss_intro=False)
                self.assertIn('starts the water automatically',self.js("document.getElementById('level-intro-works').textContent"))
                self.click_visible('GO')
                self.assertFalse(self.js("Boolean(document.querySelector('#device-live-controls button,#device-live-controls input'))"))
                self.press('Add a water chute');self.ghost();self.slide('Adjustment','yaw_deg');self.ghost()
                self.slide('Its aim',0);self.ghost()
                self.click_visible('Controls');self.click_visible('Try It!')
                self.wait("document.body.classList.contains('scene-win')",30)
                self.assertFalse(self.js("Boolean(document.querySelector('#device-live-controls button,#device-live-controls input'))"))
                self.assertGreaterEqual(self.js("Number(document.getElementById('collector-status').textContent.match(/Container ([\\d.]+)/)[1])"),3)
                self.click_visible('Close level complete');self.click_visible('Reset');self.wait(READY,30)
                self.assertEqual(self.js('machinePlacements()'),[])
                self.assertFalse(self.js("Boolean(document.querySelector('#device-live-controls button,#device-live-controls input'))"))
        self.anonymous_levels(width=1280,height=860);self.press('Sandbox: build anything')
        self.wait("Boolean(document.querySelector('#prebuilt-designs button'))",30)
        self.press('Start from Divert water into a container');self.wait(READY,30)
        self.assertTrue(self.js("[...document.querySelectorAll('#device-live-controls button')].some(b=>b.textContent==='Toggle water supply valve')"))
        self.open('easy-water-receiver');self.press('Add a water tank');self.ghost()
        self.click_visible('Place');self.wait(READY,30)
        self.assertTrue(self.js("Boolean(document.querySelector('#device-live-controls input[aria-label^=\"Live tap opening\"]'))"))

    def test_fill_receiver_requires_a_faster_tap_before_the_deadline(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-water-receiver',width,height,phone=width!=1280)
                self.assertIn('receiving box',self.js('Object.keys(machineBodies())'))
                self.assertIn('3 L in 5 seconds',self.js("document.getElementById('scene-goal').textContent"))
                self.press('Add a water tank');self.ghost()
                self.assertEqual(self.ghost()['p']['opening_percent'],10)
                self.assertTrue(self.ghost()['fits'])
                self.click_visible('Try It!')
                self.wait("!document.getElementById('level-done').hidden",20)
                self.assertIn('Try again',self.js("document.getElementById('level-done').textContent"))
                self.wait("/run over/.test(document.getElementById('clock').textContent)",10)
                self.wait("document.getElementById('collector-status').textContent.includes('Time up')",5)
                self.assertLess(self.js("Number(document.getElementById('collector-status').textContent.match(/Container ([\\d.]+)/)[1])"),3)
                self.press('Keep my pieces');self.wait(READY,60)
                self.slide('Adjust a piece','0');self.ghost()
                self.click_visible('Change its tap opening');self.slide('Its tap opening',100);self.assertTrue(self.ghost()['fits'])
                self.click_visible('Try It!')
                self.wait("/Container [1-2]\\./.test(document.getElementById('collector-status').textContent)",15)
                self.assertIn('s left',self.js("document.getElementById('collector-status').textContent"))
                self.assertNotIn('Preview',self.js("document.getElementById('collector-status').textContent"))
                for point in ((0,1.1,0),(0,.42,0)):
                    screen=self.screen_point(point)
                    self.assertTrue(self.js(f"(()=>{{const r=document.getElementById('view').getBoundingClientRect();return {screen[0]}>=r.left&&{screen[0]}<=r.right&&{screen[1]}>=r.top&&{screen[1]}<=r.bottom}})()"))
                self.wait("!document.getElementById('level-done').hidden",20)
                self.assertIn('★★★',self.js("document.getElementById('level-done').textContent"))
                self.wait("document.getElementById('collector-status').textContent.includes('Filled in')",5)
                self.assertEqual(self.js("document.getElementById('level-done').parentElement.id"),'view')
                self.assertGreaterEqual(self.js("Number(document.getElementById('collector-status').textContent.match(/Container ([\\d.]+)/)[1])"),3)
                self.click_visible('Restart with my pieces');self.wait(READY,60)
                self.wait("/Container 0.00/.test(document.getElementById('collector-status').textContent)",10)

    def test_water_diversion_shows_retained_litres_and_resets_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-divert-water',width,height,phone=width!=1280)
                self.assertIn('receiving container',self.js('Object.keys(window.machineBodies())'))
                self.wait("!document.getElementById('collector-status').hidden",10)
                self.assertIn('0.00 / 3 L',self.js("document.getElementById('collector-status').textContent"))
                self.press('Add a water chute');self.ghost()
                self.assertEqual(self.ghost()['p']['yaw_deg'],90)
                self.click_visible('Change its aim');self.slide('Its aim',0);self.ghost()
                self.click_visible('Try It!')
                self.wait("/Container [1-2]\\./.test(document.getElementById('collector-status').textContent)",15)
                for point in ((-.6,1.25,.7),(1,.42,.7)):
                    screen=self.screen_point(point)
                    self.assertTrue(self.js(f"(()=>{{const r=document.getElementById('view').getBoundingClientRect();return {screen[0]}>=r.left&&{screen[0]}<=r.right&&{screen[1]}>=r.top&&{screen[1]}<=r.bottom;}})()"),point)
                self.assertTrue(self.js("(()=>{const e=document.getElementById('collector-status'),r=e.getBoundingClientRect(),v=document.getElementById('view').getBoundingClientRect();return !e.hidden&&r.left>=v.left&&r.right<=v.right&&r.top>=v.top&&r.bottom<=v.bottom;})()"))
                self.wait("!document.getElementById('level-done').hidden",20)
                self.assertIn('★★★',self.js("document.getElementById('level-done').textContent"))
                self.assertEqual(self.js("document.getElementById('level-done').parentElement.id"),'view')
                self.assertGreaterEqual(self.js("Number(document.getElementById('collector-status').textContent.match(/Container ([\\d.]+)/)[1])"),3)
                self.click_visible('Restart with my pieces');self.wait(READY,60)
                self.wait("/Container 0.00/.test(document.getElementById('collector-status').textContent)",10)

    def test_water_shares_preserve_legacy_feeds_and_new_tap_versions(self):
        import sandbox_water_launch as water
        for name,placements in [('Legacy wheel',[dict(piece='water_wheel')]),
                ('Legacy tank',[dict(piece='water_tank')]),
                ('Gravity tank',[dict(piece='water_tank',outlet_model='gravity',opening_percent=38)])]:
            draft=dict(name=name,base=water.CHANNEL_BASE,placements=placements)
            packed=base64.urlsafe_b64encode(json.dumps(draft).encode()).decode().rstrip('=')
            self.navigate(f'{self.base}/machine#build=j{packed}')
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
            self.navigate(self.js('location.href'));self.wait(READY,60)
            self.assertEqual(self.js('window.machinePlacements()[0]'),saved)
            self.assertEqual(self.js('window.machineDesign().versions.at(-1).draft.placements[0]'),saved)

    def test_level_introduction_clears_the_working_scene_and_can_be_reopened_in_help(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            for ident in ('easy-river-wheel','easy-river-lift','gap'):
                with self.subTest(viewport=(width,height),level=ident):
                    self.open(ident,width,height,phone=width!=1280,dismiss_intro=False)
                    self.assertTrue(self.js("document.getElementById('level-intro').matches(':modal')"))
                    for field in ('title','place','works','goal'):
                        self.assertTrue(self.js(f"document.getElementById('level-intro-{field}').textContent.trim().length>0"))
                    self.assertTrue(self.js("document.getElementById('level-intro-go')===document.activeElement"))
                    self.assertEqual(self.js('machinePlacements().length'),0)
                    self.assertTrue(self.js("machineGoalGuideState().length>0 && machineGoalGuideState().every(z=>z.textLabels===0)"))
                    self.assertTrue(self.js("(()=>{const d=document.getElementById('level-intro'),b=document.getElementById('level-intro-go'),r=b.getBoundingClientRect(),a=d.getBoundingClientRect();return r.width>=44&&r.height>=44&&a.left>=0&&a.top>=0&&a.right<=innerWidth&&a.bottom<=innerHeight&&b.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})()"))
                    self.click_visible('GO');self.wait("!document.getElementById('level-intro').open",5)
                    self.assertTrue(self.js(READY))
                    self.click_visible('Reset');self.wait(READY,30)
                    self.assertFalse(self.js("document.getElementById('level-intro').open"))
                    self.click_visible('Help');self.click_visible('Level instructions')
                    self.assertTrue(self.js("document.getElementById('level-intro').open"))
                    self.key('Escape');self.wait("!document.getElementById('level-intro').open",5)

    def test_simple_river_wheel_needs_dragging_off_the_bank(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-river-wheel',width,height,phone=width!=1280)
                self.press('Add a water wheel');self.ghost()
                self.assertEqual(self.ghost()['index'],0,(self.ghost(),self.js('machinePlacements()')))
                self.assertTrue(self.js("Boolean(document.querySelector('[aria-label=\"along channel (m) of your water_wheel 1\"]'))"),self.js("[...document.querySelectorAll('#ghost-bar [aria-label]')].map(e=>e.getAttribute('aria-label'))"))
                self.assertEqual(self.ghost()['p']['z_m'],1)
                self.assertEqual(self.ghost()['p']['side'],'off')
                self.assertFalse(self.js("[...document.getElementById('adjustment-choice').options].some(o=>o.value==='load_part')"),'The spin-only lesson has no load to connect')
                self.assertFalse(self.js('window.machineWaterDisplay().length'))
                self.drag_ghost_to(0,0,touch=width!=1280)
                self.assertLess(abs(self.ghost()['p']['z_m']),.025)
                self.click_visible('Try It!');self.assert_measured_river_current()
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Goal at',self.js("document.getElementById('verdict').textContent"))

    def test_river_workbench_places_a_useful_wheel_and_restores_its_saved_connections(self):
        self.page.send('Emulation.setDeviceMetricsOverride',{'width':1280,'height':860,'deviceScaleFactor':1,'mobile':False})
        self.page.send('Emulation.setTouchEmulationEnabled',{'enabled':False})
        self.navigate(f'{self.base}/machine')
        self.wait("Boolean(document.querySelector('#prebuilt-designs button'))",60)
        self.press('Start from Build beside a river');self.wait(READY,60)
        self.assertEqual(self.js('window.machinePlacements()'),[])
        self.place_river_wheel()
        setup=self.js('window.machinePlacements()')
        base=self.js('window.machineDesign().draft.base')
        initial=self.js("window.machineBodies()['river gate'][1]")
        count=self.js('window.machineDesign().versions.length')
        self.press('Save version');self.wait(f'window.machineDesign().versions.length==={count+1}',10)
        self.click_visible('Try It!');self.assert_measured_river_current()
        self.wait(f"window.machineBodies()['river gate'][1]>={initial+.08}",30)
        self.click_visible('Pause');self.click_visible('Restart with my pieces');self.wait(READY,60)
        self.assertEqual(self.js('window.machineDesign().draft.base'),base)
        self.assertEqual(self.js('window.machinePlacements()'),setup)
        self.navigate(self.js('location.href'));self.wait(READY,60)
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
                self.click_visible('Try It!');self.assert_measured_river_current()
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Goal at',self.js("document.getElementById('verdict').textContent"))
                self.wait(f"window.machineBodies()['river gate'][1]-{initial}>=.08",10)
                self.assertGreaterEqual(self.js("window.machineBodies()['river gate'][1]")-initial,.08)

    def test_river_lift_has_a_clear_connection_and_native_moving_preview(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-river-lift',width,height,phone=width!=1280)
                initial=self.js("window.machineBodies()['river gate'][1]")
                self.press('Add a water wheel');self.ghost()
                self.wait("/on bank/.test(document.getElementById('river-wheel-status').textContent)",10)
                self.assertFalse(self.js("Boolean(document.querySelector('[aria-label=\"Its load to lift\"]'))"))
                self.assertFalse(self.js("Boolean(document.querySelector('[aria-label=\"Its wheel radius\"]'))"))
                self.assertTrue(self.js("(()=>{const b=document.querySelector('.connection-action'),r=b.getBoundingClientRect();return r.width>=44&&r.height>=44&&r.left>=0&&r.right<=innerWidth&&b.scrollWidth<=b.clientWidth})()"),'The complete connection label must fit the edge card with a 44 px touch target')
                self.drag_ghost_to(0,0,touch=width!=1280)
                self.wait("window.machineFlowPreviewState()?.sample?.mechanism_joints?.some(j=>j.kind==='hinge'&&Math.abs(j.turned_deg)>30)",20)
                self.assertEqual(self.js("window.machineGhostState().p.load_part"),'')
                self.click_visible('Connect rope to gate');self.ghost()
                self.wait("window.machineFlowPreviewState()?.sample?.mechanisms?.some(b=>b.name==='river gate'&&b.position_m[1]-b.initial_position_m[1]>=.08)",20)
                drawn=self.js('window.machineFlowPreviewState()')
                self.assertEqual(drawn['drawn']['mechanisms'],[{k:b[k] for k in ('name','position_m','orientation_wxyz')} for b in drawn['sample']['mechanisms']])
                self.assertTrue(any(j['kind']=='drum' and j.get('tension_n',0)>0 for j in drawn['sample']['mechanism_joints']))
                self.assertIn('Preview',self.js("document.getElementById('river-wheel-status').textContent"))
                self.assertAlmostEqual(self.js("window.machineBodies()['river gate'][1]"),initial)
                self.assertTrue(self.js(READY),'Preview must leave the real setup at time zero')
                self.click_visible('Try It!')
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertEqual(self.js("document.getElementById('level-done').parentElement.id"),'view')
                self.assertGreaterEqual(self.js("window.machineBodies()['river gate'][1]")-initial,.08)

    def test_tray_cards_live_at_the_add_controls_and_arrows_only_browse(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('gap',width,height,phone=width<1000)
                self.assertTrue(self.js("Boolean(document.getElementById('tray').closest('#scene-tray')) && Boolean(document.getElementById('tray').closest('#control-panel'))"))
                self.assertEqual(self.js("document.querySelectorAll('#tray-head').length"),1)
                self.assertTrue(self.js("document.getElementById('tray-prev').hidden && document.getElementById('tray-next').hidden"))
                self.wait("document.querySelector('#tray img')?.naturalWidth > 0",30)
                self.assertGreaterEqual(self.js("document.querySelector('#tray img').getBoundingClientRect().width"),44)
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
                self.click_visible('Try It!')
                self.wait('!window.machineGhostState()',5)
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Goal at',self.js("document.getElementById('verdict').textContent"))
                self.assertEqual(len(self.js('window.machinePlacements()')),1)
                opens=[json.loads(e['params']['request']['postData']) for e in self.page.events if e['method']=='Network.requestWillBeSent' and e['params']['request']['url'].endswith('/api/machine') and e['params']['request'].get('postData') and json.loads(e['params']['request']['postData']).get('op')=='level_open']
                self.assertEqual(len(opens),1,'placing and running uses one setup')
                self.click_visible('Restart with my pieces'); self.wait(READY,30)
                self.press('Pick up your plank 1'); self.ghost()
                self.slide('Cut to length of your plank 1',.66)
                # Two clicks while validation is in flight cannot duplicate it.
                self.js("document.getElementById('start').click();document.getElementById('start').click()")
                self.wait('!window.machineGhostState()',5)
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Goal at',self.js("document.getElementById('verdict').textContent"))
                self.assertEqual(len(self.js('window.machinePlacements()')),1)
                self.assertEqual(self.js('window.machinePlacements()[0].length_m'),.66)
                self.click_visible('Restart with my pieces'); self.wait(READY,30)
                self.press('Undo'); self.wait(READY,30)
                self.assertEqual(self.js('window.machinePlacements()[0].length_m'),.7)
                # The same shortcut keeps a sandbox draft and saved version.
                self.navigate(f'{self.base}/machine')
                self.wait("document.getElementById('sandbox-screen')?.hidden===false",30)
                self.press('Add New Design'); self.wait(READY,30)
                self.press('Add a plank'); self.ghost()
                if width!=1280: self.click_visible('Help')
                self.click_visible('Try It!')
                self.wait("/World (?!0\\.00)[0-9.]+ s/.test(document.getElementById('clock').textContent)",30)
                self.assertIsNone(self.js('window.machineGhostState()'))
                self.assertEqual(len(self.js('window.machineDesign().draft.placements')),1)
                self.click_visible('Pause'); self.click_visible('Restart with my pieces'); self.wait(READY,30)
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
        self.press('Try It!'); self.js('window.releaseRunCheck()')
        self.wait("/120 mm into wall/.test(document.getElementById('verdict').textContent)",5)
        self.assertFalse(self.ghost()['fits'])
        self.assertEqual(self.js('window.machinePlacements()'),[])
        self.assertTrue(self.js(READY))
        self.page.send('Network.enable'); self.page.events.clear()
        self.js("window.runCheckResolved=false;window.runHoldCheck=true;window.runCheckGate=new Promise(resolve=>window.releaseRunCheck=resolve)")
        self.slide('z of your mirror 1',0)
        self.press('Try It!'); self.press('Cancel'); self.js('window.releaseRunCheck()')
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
                # The level/design title and one-line task now have their
                # own reserved row; the pane still fits four touch rows.
                self.assertGreaterEqual(pane['height'],2*44,'The expanded scene leaves two touch rows in the scrollable design pane')
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
                self.click_visible('Try It!')
                self.wait("/World (?!0\\.00)[0-9.]+ s/.test(document.getElementById('clock').textContent)",30)
                self.click_visible('Pause'); self.click_visible('Reset'); self.wait(READY,30)
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


    def test_shared_tabs_and_run_toolbar_work_without_a_collapse_button(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('gap',width,height,phone=width!=1280)
                self.assertFalse(self.js("document.getElementById('phone-toolbar').hidden"))
                self.assertEqual(self.js("document.getElementById('start').parentElement.id"),'phone-runbar')
                self.assertEqual(self.js("document.getElementById('reset').parentElement.id"),'phone-runbar')
                self.assertTrue(self.js("document.getElementById('phone-design-tab').hidden"))
                for label,pane in [('Controls','control-panel'),('Help','phone-help-panel')]:
                    self.click_visible(label)
                    self.assertEqual(self.js("['control-panel','phone-design-panel','phone-help-panel'].filter(id=>!document.getElementById(id).hidden)"),[pane])
                    if label=='Controls':
                        self.assertTrue(self.js("(()=>{const r=document.getElementById('scene-goal').getBoundingClientRect();return r.height>0&&r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight;})()"))
                    else:
                        # Help already contains the task; reserve the dock for
                        # its content rather than duplicating the goal row.
                        self.assertFalse(self.js("document.getElementById('scene-goal').checkVisibility()"))
                        self.assertFalse(self.js("document.getElementById('brief').checkVisibility()"))
                        self.assertTrue(self.js("document.getElementById('message').checkVisibility()"))
                before=self.js('machinePlacements()')
                self.assertIsNone(self.js("document.getElementById('panel-toggle')"))
                self.assertTrue(self.js("document.getElementById('phone-help-panel').checkVisibility()"))
                self.click_visible('Try It!')
                self.wait("/World (?!0\\.00)[0-9.]+ s/.test(document.getElementById('clock').textContent)",30)
                self.click_visible('Pause');self.click_visible('Reset');self.wait(READY,30)
                self.assertFalse(self.js("document.getElementById('phone-help-panel').hidden"))
                self.assertEqual(self.js('machinePlacements()'),before)

    def test_reset_returns_challenge_to_authored_beginning_and_undo_restores_attempt(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('gap',width,height,phone=width!=1280)
                self.press('Add a plank');self.ghost()
                self.slide('Cut to length of your plank 1',.7)
                self.slide('Set down at x of your plank 1',.3)
                self.slide('across (z, m) of your plank 1',0)
                self.ghost();self.click_visible('Try It!')
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Goal at',self.js("document.getElementById('verdict').textContent"))
                kept=self.js('machinePlacements()')
                self.click_visible('Help')
                self.click_visible('Reset');self.wait(READY,30)
                self.assertEqual(self.js('machinePlacements()'),[])
                self.assertIsNone(self.js('machineGhostState()'))
                self.assertTrue(self.js("document.getElementById('level-done').hidden"))
                self.assertEqual(self.js("document.getElementById('tray-add').disabled"),False)
                self.assertIn('World 0.00 s',self.js("document.getElementById('clock').textContent"))
                self.click_visible('Undo');self.wait(READY,30)
                self.assertEqual(self.js('machinePlacements()'),kept)
                self.click_visible('Controls');self.press('Pick up your plank 1');self.ghost()
                self.slide('Cut to length of your plank 1',.66);self.ghost()
                self.click_visible('Reset');self.wait(READY,30)
                self.assertIsNone(self.js('machineGhostState()'))
                self.assertEqual(self.js('machinePlacements()'),[])
                self.click_visible('Undo');self.wait(READY,30)
                self.assertEqual(self.js('machinePlacements()'),kept,'Reset discards the uncommitted edit; Undo restores the completed setup')

    def test_sandbox_reset_rewinds_machine_and_cancels_pending_edits_without_erasing_design(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.anonymous_levels(width=width,height=height)
                self.press('Sandbox: build anything');self.wait("!document.getElementById('sandbox-screen').hidden",10)
                self.press('Start from Gate and split');self.wait(READY,60)
                kept=self.js('machinePlacements()');base=self.js('machineDesign().draft.base')
                versions=self.js('machineDesign().versions')
                self.click_visible('Try It!');self.wait("/World [12]\\./.test(document.getElementById('clock').textContent)",30)
                self.click_visible('Help');self.click_visible('Reset');self.wait(READY,30)
                self.assertEqual(self.js('machinePlacements()'),kept)
                self.assertEqual(self.js('machineDesign().draft.base'),base)
                self.assertEqual(self.js('machineDesign().versions'),versions)
                self.assertIn('World 0.00 s',self.js("document.getElementById('clock').textContent"))
                self.assertEqual(self.js("document.getElementById('phone-help-tab').getAttribute('aria-selected')"),'true')
                self.click_visible('Controls');self.slide('Adjust a piece','0')
                self.ghost();self.click_visible('Reset');self.wait(READY,30)
                self.assertIsNone(self.js('machineGhostState()'))
                self.assertEqual(self.js('machinePlacements()'),kept)
                self.assertEqual(self.js('machineDesign().draft.placements'),kept)

    def test_undo_is_visible_on_every_tab_and_restores_setup(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            for level in ('gap','free'):
                with self.subTest(viewport=(width,height),level=level):
                    self.open(level,width,height,phone=width!=1280)
                    if level=='free':
                        self.press('All designs')
                        self.create_design()
                    self.assertTrue(self.js("document.getElementById('undo-pieces').disabled"))
                    self.press('Add a plank');self.ghost();self.press('Set it down');self.wait(READY,30)
                    placed=self.js('machinePlacements()')
                    self.assertEqual(len(placed),1)
                    for tab in (('Controls','Help') if level=='gap' else ('Controls','Design','Help')):
                        self.click_visible(tab)
                        # Check before the helper can reveal any hidden tab or disclosure.
                        visible=self.js("""(()=>{const b=document.getElementById('undo-pieces'),r=b.getBoundingClientRect();
                          return {parent:b.parentElement.id,text:b.textContent.trim(),disabled:b.disabled,
                            visible:r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight&&r.width>=44&&r.height>=44,
                            uncovered:b.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))};})()""")
                        self.assertEqual(visible['parent'],'viewer-history',visible)
                        self.assertIn('Undo',visible['text'])
                        self.assertTrue(visible['visible'] and visible['uncovered'] and not visible['disabled'],visible)
                    self.click_visible('Undo')
                    self.wait(f'machinePlacements().length===0 && {READY}',30)
                    self.assertTrue(self.js("document.getElementById('phone-help-panel').checkVisibility()"))
                    self.assertTrue(self.js("document.getElementById('undo-pieces').disabled"))
                    self.click_visible('Controls');self.press('Redo')
                    self.wait(READY,30);self.assertEqual(self.js('machinePlacements()'),placed)
                    self.press('Pick up your plank 1');self.ghost()
                    self.slide(('Cut to length' if level=='gap' else 'length')+' of your plank 1',.66)
                    self.ghost();self.press('Set it down');self.wait(READY,30)
                    self.assertNotEqual(self.js('machinePlacements()'),placed)
                    self.click_visible('Undo');self.wait(READY,30)
                    self.assertEqual(self.js('machinePlacements()'),placed)
                    self.press('Remove your plank 1');self.wait(READY,30)
                    self.click_visible('Undo');self.wait(READY,30)
                    self.assertEqual(self.js('machinePlacements()'),placed)
                    if level=='free':
                        self.assertEqual(self.js('machineDesign().draft.placements'),placed)

    def test_active_piece_slider_exact_value_and_precision_disclosure_agree(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('gap',width,height,phone=width!=1280)
                self.press('Add a plank');self.ghost()
                self.assertFalse(self.js("document.getElementById('precision-controls').open"))
                self.assertTrue(self.js("Boolean(document.querySelector('#precision-controls [aria-label=\"Cut to length of your plank 1\"]'))"))
                self.assertTrue(self.js("Boolean(document.getElementById('precision-controls').closest('#recent-changes'))"))
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
                self.reveal_control("document.querySelector('[aria-label=\"Its Cut to length\"]')")
                geometry=self.js("(()=>{const input=document.querySelector('[aria-label=\"Its Cut to length\"]'),row=input.closest('.knob-row'),r=row.getBoundingClientRect(),s=input.getBoundingClientRect(),n=document.querySelector('[aria-label=\"Exact Cut to length\"]').getBoundingClientRect();return {row:r.toJSON(),slider:s.toJSON(),number:n.toJSON(),uncovered:input.contains(document.elementFromPoint(s.x+s.width/2,s.y+s.height/2))};})()")
                self.assertGreaterEqual(geometry['slider']['width'],geometry['row']['width']*.6,geometry)
                self.assertGreaterEqual(geometry['number']['height'],44,geometry)
                self.assertTrue(geometry['uncovered'],geometry)
                # Precision controls now live in Changes; reopen the dialog
                # before measuring its slider and then return to the scene.
                self.reveal_control("document.querySelector('[aria-label=\"Its Cut to length\"]')")
                self.slide('Cut to length of your plank 1',.68)
                self.assertTrue(self.js("document.getElementById('precision-controls').open"))
                self.assertEqual(self.ghost()['p']['length_m'],.68)
                self.assertEqual(self.js("Number(document.querySelector('[aria-label=\"Exact Cut to length\"]').value)"),.68)
                self.press('Throw the ghost away')


    def test_sandbox_existing_apparatus_can_move_remove_undo_and_reload(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.anonymous_levels(width=width,height=height)
                self.press('Sandbox: build anything')
                self.wait("Boolean(document.querySelector('#prebuilt-designs button'))",60)
                self.press('Start from Chain reaction');self.wait(READY,90)
                before=self.js('machineDesign().draft.base')
                self.wait('machineCamera().settled',30)
                # Native cables can cover the former case-centre pick. Use
                # an exposed solid hit or the ordinary overlap chooser.
                index=self.js("machineEditableObjects().find(o=>o.id==='part:battery box').index")
                self.click_piece(index)
                self.assertEqual(self.ghost()['p']['object'],'part:battery box')
                self.click_visible('Throw the ghost away')
                # Choose a prepared kit via the ordinary inspector, not JSON.
                self.slide('Adjust a piece',self.js("machineEditableObjects().find(o=>o.name==='ramp').index"))
                self.assertEqual(self.ghost()['p']['piece'],'base_object')
                self.click_visible('Change its height change')
                self.slide('Exact height change',.1);self.ghost()
                self.click_visible('✓ Set down');self.wait(READY,90)
                self.assertEqual(self.js("machineDesign().draft.base.kits.find(k=>k.name==='ramp').translated_m"),[0,.1,0])
                self.click_visible('Undo');self.wait(READY,90)
                self.assertEqual(self.js('machineDesign().draft.base'),before)
                self.slide('Adjust a piece',self.js("machineEditableObjects().find(o=>o.name==='ramp').index"));self.ghost()
                self.click_visible('Delete selected piece');self.wait("!machineDesign().draft.base.kits.some(k=>k.name==='ramp')",30);self.wait(READY,90)
                self.assertFalse(self.js("machineDesign().draft.base.kits.some(k=>k.name==='ramp')"))
                self.assertFalse(self.js("machineDesign().draft.base.joints.some(j=>j.load==='ramp gate')"))
                self.click_visible('Undo');self.wait(READY,90)
                self.assertEqual(self.js('machineDesign().draft.base'),before)
                self.slide('Adjust a piece',self.js("machineEditableObjects().find(o=>o.name==='ramp').index"));self.ghost()
                self.slide('Exact height change',.1);self.ghost();self.click_visible('✓ Set down');self.wait(READY,90)
                self.press('Save version');self.anonymous_cloud_saved()
                expected=self.js('machineDesign().draft');url=self.js('location.href')
                self.navigate(url);self.wait(READY,90)
                self.assertEqual(self.js('machineDesign().draft'),expected)
                self.assertLessEqual(self.js('document.body.scrollWidth'),width)

    def test_sandbox_add_remove_and_river_environment_keep_design_and_history(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.anonymous_levels(width=width,height=height);self.press('Sandbox: build anything')
                self.wait("Boolean(document.querySelector('#prebuilt-designs button'))",60);self.create_design()
                self.press('Add a battery');self.ghost();self.slide('along (m) of your battery 1',1);self.ghost()
                self.click_visible('✓ Set down');self.wait(READY,90)
                placed=self.js('machinePlacements()')
                self.press('Add a water wheel');self.ghost()
                self.assertEqual(self.js('machineDesign().draft.base.ground.discharge_m3_s'),0)
                self.assertTrue(self.ghost()['fits'],self.ghost())
                self.click_visible('Throw the ghost away');self.click_visible('Undo');self.wait(READY,90)
                self.assertIsNone(self.js('machineDesign().draft.base'))
                self.assertEqual(self.js('machinePlacements()'),placed)
                self.slide('Sandbox ground','river');self.slide('River flow (L/s)',100)
                self.click_visible('Apply ground');self.wait("machineDesign().draft.base?.ground?.discharge_m3_s===.1",30);self.wait(READY,90)
                self.assertEqual(self.js('machineDesign().draft.base.ground.discharge_m3_s'),.1)
                self.assertEqual(self.js('machinePlacements()'),placed)
                self.press('Add a water wheel');self.ghost()
                self.assertEqual(self.ghost()['p']['side'],'off')
                self.slide('along channel (m) of your water_wheel 2',-.7);self.slide('across river (m) of your water_wheel 2',0);self.ghost()
                self.click_visible('✓ Set down');self.wait(READY,90)
                self.click_visible('Try It!');self.assert_measured_river_current()
                self.wait("Math.abs(machineBodies()['your water_wheel 2'][0]+.7)<.03",20)
                self.click_visible('Pause');self.click_visible('Reset');self.wait(READY,90)
                self.slide('Adjust a piece','0');self.ghost();self.click_visible('Delete selected piece');self.wait(READY,90)
                self.assertEqual(len(self.js('machinePlacements()')),1)
                self.click_visible('Undo');self.wait(READY,90);self.assertEqual(len(self.js('machinePlacements()')),2)
                self.press('Save version');self.anonymous_cloud_saved();expected=self.js('machineDesign().draft')
                self.navigate(self.js('location.href'));self.wait(READY,90)
                self.assertEqual(self.js('machineDesign().draft'),expected)

    def test_sandbox_gallery_shows_saved_designs_before_all_examples_without_filters(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.anonymous_levels(width=width,height=height)
                self.press('Sandbox: build anything');self.wait("document.getElementById('sandbox-screen').hidden===false",10)
                self.assertIsNone(self.js("document.getElementById('new-design-name')"))
                self.assertIsNone(self.js("document.querySelector('.design-gallery [role=tablist]')"))
                self.assertFalse(self.js("document.getElementById('design-panel-owned').hidden"))
                self.assertFalse(self.js("document.getElementById('design-panel-examples').hidden"))
                self.assertEqual(self.js("document.querySelectorAll('#prebuilt-designs button').length"),self.template_count)
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
                self.assertTrue(self.js("Boolean(document.getElementById('saved-designs').compareDocumentPosition(document.getElementById('prebuilt-designs')) & Node.DOCUMENT_POSITION_FOLLOWING)"))
                self.assertLessEqual(self.js('document.body.scrollWidth'),width)

    def test_level_details_and_more_are_opt_in_without_starting_a_world(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.anonymous_levels(width=width,height=height)
                titles=self.js("[...document.querySelectorAll('#levels-screen .level-card-title')].map(e=>e.textContent)")
                self.assertLess(titles.index('Bounce to the target'),titles.index('Bounce the beam'))
                self.assertFalse(self.js("document.getElementById('level-more').open"))
                self.assertEqual(self.js("document.querySelectorAll('#levels-screen .level-card-details').length"),0)
                self.assertTrue(self.js("[...document.querySelectorAll('#levels-screen .level-card-details')].every(d=>!d.open)"))
                self.assertFalse(self.js("document.getElementById('levels-screen').innerText.includes('Energy par:')"))
                self.assertFalse(self.js("document.getElementById('levels-screen').innerText.includes('New challenge')"))
                before=self.js('location.href')
                self.page.events.clear()
                self.assertEqual(self.js("document.querySelectorAll('.level-chapter').length"),4)
                self.assertEqual(self.js('location.href'),before)
                self.click_summary('#level-more > summary')
                self.assertTrue(self.js("document.getElementById('level-more').open"))
                self.assertTrue(self.js("Boolean(document.getElementById('visitor-return-link').closest('#level-more'))"))
                self.assertFalse(self.js("Boolean(document.querySelector('#level-more #challenge-family'))"))
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
                self.reveal_control("document.getElementById('focus-piece')")
                focus=self.js("(() => {const el=document.getElementById('focus-piece'),r=el.getBoundingClientRect(),p=el.closest('#recent-changes .guide-body').getBoundingClientRect();return {target:r.toJSON(),pane:p.toJSON(),visible:r.height>=44 && r.top>=p.top && r.bottom<=p.bottom};})()")
                self.assertTrue(focus['visible'],('Focus must have its complete touch target inside Settings',focus))
                if width<=599:
                    self.assertTrue(self.js("document.getElementById('view').getBoundingClientRect().bottom<=document.getElementById('phone-toolbar').getBoundingClientRect().top"),'the smaller scene cannot overflow behind controls')
                self.wait('window.machineCamera().settled',30)
                for anchor in ([-.8,.575,0],[.29,.575,0]):
                    point=self.screen_point(anchor)
                    rect=self.js("(() => {const r=document.querySelector('#view canvas').getBoundingClientRect();return {l:r.left,r:r.right,t:r.top,b:r.bottom};})()")
                    self.assertTrue(rect['l']<=point[0]<=rect['r'] and rect['t']<=point[1]<=rect['b'],(anchor,point,rect))
                self.click_visible('Zoom out'); self.wait('window.machineCamera().settled',30)
                # Ordinary exact controls: no scene/test-hook placement shortcut.
                self.slide('Position along (m) of your lens 1',.1)
                self.slide('Position across (m) of your lens 1',0)
                self.slide('Diameter (m) of your lens 1',.12)
                self.ghost()
                self.wait("!window.machineLaserPreviewState().pending && window.machineLaserPreviewState().photocells[0]?.power_w>2 && document.getElementById('laser-preview-status').textContent.includes('7.31 W')",30)
                self.assertIn('7.31 W',self.js("document.getElementById('laser-preview-status').textContent"))
                self.slide('Position across (m) of your lens 1',.3)
                self.assertTrue(self.js('window.machineLaserPreviewState().visible'),'previous trace stays visible while the new one is requested')
                self.ghost();self.wait('!window.machineLaserPreviewState().pending && window.machineLaserPreviewState().photocells[0]?.power_w<2',30)
                self.assertEqual(self.js('JSON.parse(window.machineLaserPreviewState().stamp).placements[0].z_m'),.3)
                self.assertTrue(self.js('Number.isFinite(window.machineCamera().distance)'))
                self.slide('Position across (m) of your lens 1',0);self.ghost()
                self.press('Set it down');self.wait(READY,30)
                self.press('Try It!');self.wait("/World (?!0.00)\\d/.test(document.getElementById('clock').textContent) && !window.machineLaserPreviewState().visible",30)
                self.assertFalse(self.js('window.machineLaserPreviewState().visible'),'Run shows actual native light instead of a setup prediction')
                self.press('Restart with my pieces');self.wait(READY,30)
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
                    self.navigate(f'{self.base}/machine')
                    self.wait("document.getElementById('sandbox-screen')?.hidden===false",30)
                    self.press('Start from '+template)
                    self.wait("window.machineFlowPreviewState()?.frames>2 && !document.getElementById('flow-preview').hidden",60)
                    setup=self.js('window.machinePlacements()')
                    # Open the actual disclosure and use real pointer clicks.
                    self.click_summary('#flow-preview > summary')
                    self.reveal_control("document.getElementById('flow-play')")
                    self.wait("document.getElementById('flow-play').getBoundingClientRect().bottom<=innerHeight",5)
                    self.click_visible('Play preview' if channel=='wires' else 'Pause preview')
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
                    for label in ('Try It!','Reset','Turn the view left','Zoom in','Place','Throw the ghost away'):
                        self.reveal_control(f"[...document.querySelectorAll('button')].find(b=>(b.getAttribute('aria-label')||b.textContent).trim()==={json.dumps(label)})")
                        target = self.js(f"(() => {{const b=[...document.querySelectorAll('#control-panel button,#phone-runbar button,#viewer-corner button,#piece-editor button')].find(b=>(b.getAttribute('aria-label')||b.textContent).trim()==={json.dumps(label)}),r=b?.getBoundingClientRect();return r?{{visible:r.x>=0 && r.right<=innerWidth && r.y>=0 && r.bottom<=innerHeight,uncovered:b.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)),h:r.height,w:r.width}}:null;}})()")
                        self.assertIsNotNone(target,label)
                        self.assertTrue(target['visible'] and target['uncovered'],(label,target))
                        self.assertGreaterEqual(target['h'],44); self.assertGreaterEqual(target['w'],44)
                    camera=self.js('machineCamera().distance')
                    self.click_visible('Zoom in')
                    self.assertLess(self.js('machineCamera().distance'),camera)
                    self.assertEqual(self.ghost()['p'],setup[0],'Zoom does not move the piece')
                    self.click_visible('Zoom out')
                    self.press('Cancel'); self.wait('!window.machineGhostState()',5)
                self.press('Try It!'); self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Goal at',self.js("document.getElementById('verdict').textContent"))
                # Results stay in Controls, so the device is still clickable.
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
                self.click_visible('Try It!')
                # On short screens optional wire cards yield to the device
                # and its required power. Native current still drives dots.
                self.wait("window.machinePowerFeedbackState().labels.some(r=>(r.wire||r.device==='winch motor')&&/ W/.test(r.text)&&!r.text.includes('Preview')&&!r.text.includes('Updating')) && window.machinePowerFeedbackState().dots>0",20)
                geometry=self.js("""(() => {const view=document.getElementById('view').getBoundingClientRect(),run=document.getElementById('start').getBoundingClientRect();
                    const rows=[...document.querySelectorAll('#power-feedback-labels section')].filter(e=>!e.hidden).map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,w:r.width,h:r.height}});
                    return {rows,inside:rows.every(r=>r.x>=view.x&&r.y>=view.y&&r.right<=view.right&&r.bottom<=view.bottom),
                      clear:rows.every(r=>!(r.x<run.right&&r.right>run.x&&r.y<run.bottom&&r.bottom>run.y))};})()""")
                self.assertTrue(geometry['rows']);self.assertTrue(geometry['inside'],geometry);self.assertTrue(geometry['clear'],geometry)
                self.click_visible('Pause')

    def test_solar_shade_feedback_follows_the_ghost_and_matches_rendered_geometry(self):
        for identity in ('sun','easy-solar'):
            for width,height in ((1280,860),(390,844),(844,390)):
                with self.subTest(level=identity,viewport=(width,height)):
                    self.open(identity,width,height,phone=width!=1280)
                    self.press('Add a solar panel');self.ghost()
                    values=([('x',-.8),('z',.6),('height',.6),('turn',-45),('tip',75)] if identity=='sun' else
                        [('Position along (m)',0),('Position across (m)',0),('Post height (m)',.5),('turn',-90),('tip',70)])
                    for label,value in values:self.slide(f'{label} of your solar 1',value)
                    self.ghost();self.press('Set it down');self.wait(f'!machineGhostState() && {READY}',60)
                    self.wait("document.getElementById('power-labels').textContent.includes('In shadow at panel center')",20)
                    state=self.js('machineSolarState()');panel=state['panels'][0]
                    self.assertEqual(state['renderedHits'][0]['part'],'shade wall')
                    for a,b in zip(state['renderedHits'][0]['point'],panel['shadow_hit_m']):self.assertAlmostEqual(a,b,delta=.0001)
                    for a,b in zip(state['lightDirection'],panel['toward_sun']):self.assertAlmostEqual(a,b,delta=1e-5)
                    self.slide('Adjust a piece','0');self.ghost()
                    self.wait("machineSolarState().preview && !machineSolarState().pending && machineSolarState().panels[0]?.shaded",30)
                    # Delay only this observation so stale visible labels are measurable.
                    self.js("(()=>{const previous=window.fetch;window.fetch=async(...args)=>{const response=await previous(...args);if(args[1]?.body?.includes('level_sunlight'))await new Promise(resolve=>setTimeout(resolve,500));return response;};})()")
                    self.slide(('x' if identity=='sun' else 'Position along (m)')+' of your solar 1',1.4)
                    self.wait("machineSolarState().pending && !document.getElementById('power-labels').textContent.includes('In shadow') && machineSolarState().guides.length===0 && document.querySelector('#ghost-bar .state').textContent.includes('measuring sunlight')",10)
                    self.ghost()
                    self.wait("!machineSolarState().pending && machineSolarState().panels[0]?.sunlight_w>249",30)
                    self.assertIn('Preview',self.js("document.getElementById('power-labels').textContent"))
                    self.assertIn('Panel center in sunlight',self.js("document.getElementById('power-labels').textContent"))
                    self.assertTrue(self.js('machineSolarState().livePanels[0].shaded'),'a proposed move must not change the live world')
                    state=self.js('machineSolarState()')
                    self.assertIsNone(state['renderedHits'][0]['part'])
                    self.assertGreater(state['panels'][0]['ray_from_m'][0],1)
                    self.assertTrue(all(store['charge_j']==0 for store in state['batteries']))
                    self.assertTrue(self.js(READY),'the preview must not run the live machine')
                    self.press('Set it down');self.wait(f'!machineGhostState() && {READY}',60)
                    self.wait("!machineSolarState().preview && machineSolarState().panels[0]?.sunlight_w>249",20)

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
                self.click_visible('Try It!')
                self.wait("!document.getElementById('level-done').hidden", 30)
                self.assertIn('Goal', self.js("document.getElementById('level-done').textContent"))

    def test_chain_trigger_contact_and_power_loop_are_inspectable_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('chain',width,height,phone=width!=1280)
                before=self.js('machineCamera().distance')
                self.click_visible('Help')
                self.click_visible('Inspect switch')
                self.assertTrue(self.js("document.getElementById('control-panel').checkVisibility()"),'Inspection reveals its readings module')
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
                self.click_visible('Back to scene');self.assertIsNone(self.js('machineContactCircuitState().inspected'))
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
                self.click_visible('Try It!');self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Goal',self.js("document.getElementById('level-done').textContent"))
                self.assertTrue(self.js("document.getElementById('view').contains(document.getElementById('level-done'))"),'The win card belongs over the scene')
                self.assertGreater(self.js("document.getElementById('level-done').getBoundingClientRect().height"),150,'The result card must retain its natural height inside the scroll pane')
                self.click_visible('Play this level again');self.wait(READY,60)
                self.click_visible('Inspect switch');self.click_visible('Try It!');self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Pressure switch: closed',self.js("document.getElementById('contact-circuit-readings').textContent"))
                state=self.js('machineContactCircuitState()')
                self.assertEqual(state['inspected'],'firing circuit','Run must keep the switch close-up so its motion is visible')
                self.assertGreater(state['circuits'][0]['reading']['coil_w'],0)
                self.assertTrue(all(w['color']==0xffd34d for w in state['wires']))
                self.assertTrue(all(o['color']==0x5fe08f for o in state['outlines']))
                self.click_visible('Back to scene')
                self.assertTrue(self.js("document.getElementById('view').contains(document.getElementById('level-done'))"))
                self.open('easy-solar',width,height,phone=width!=1280)
                self.assertTrue(self.js("document.getElementById('inspect-switch').hidden && document.getElementById('contact-switch-labels').hidden"),'Contact inspection does not leak onto other lessons')

    def test_chain_ramp_can_be_dragged_outside_the_old_placement_strip(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('chain',width,height,phone=width!=1280)
                self.press('Add a ramp');self.ghost()
                self.assertTrue(self.ghost()['fits'],'A new ramp starts clear of the cannon')
                for x,z in ((-.75,.8),(1.1,-.8)):
                    state=self.drag_ghost_to(x,z,touch=width!=1280)
                    self.assertAlmostEqual(state['p']['x_m'],x,delta=.025)
                    self.assertAlmostEqual(state['p']['z_m'],z,delta=.025)
                    self.assertTrue(state['fits'],state)
                self.click_visible('Place');self.wait(READY,60)
                self.click_piece(0);state=self.ghost()
                self.assertAlmostEqual(state['p']['x_m'],1.1,delta=.025)
                self.assertAlmostEqual(state['p']['z_m'],-.8,delta=.025)
                self.click_visible('Place');self.wait(READY,60)
                self.click_visible('Try It!');self.wait("!document.getElementById('level-done').hidden",30)
                self.assertNotIn('Level Complete',self.js("document.getElementById('level-done').textContent"),'The off-axis marble must miss the switch physically')

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
                self.click_visible('Try It!');self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Try again',self.js("document.getElementById('level-done').textContent"))
                self.press('Keep my pieces');self.wait(READY,60)
                self.slide('Adjust a piece','0');self.ghost()
                self.slide('Position along (m) of your solar 1',1.4);self.ghost()
                self.press('Set it down');self.wait(f'!machineGhostState() && {READY}',60)
                self.wait("document.getElementById('power-labels').textContent.includes('50.0 W charging')",20)
                assert_wall_in_view()
                self.click_visible('Help');assert_wall_in_view();self.click_visible('Controls')
                self.assertNotIn('In shadow',self.js("document.getElementById('power-labels').textContent"))
                self.assertEqual(self.js('machinePlacements()[1].b_port'),'battery:power')
                self.click_visible('Try It!');self.wait("!document.getElementById('level-done').hidden",30)
                self.assertNotIn('Try again',self.js("document.getElementById('level-done').textContent"))
                self.press('Play this level again');self.wait(READY,60)
                self.press('Remove your power_cable 2');self.wait(f'machinePlacements().length===1 && {READY}',60)
                self.click_visible('Try It!');self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Try again',self.js("document.getElementById('level-done').textContent"),'Sunlight alone cannot fill the disconnected receiver')

    def test_sun_powered_lift_explains_source_and_connects_from_main_controls(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-charge-lift',width,height,phone=width!=1280)
                self.assertIn('Sun-powered lift',self.js("document.getElementById('title').textContent"))
                self.assertFalse(self.js("document.getElementById('solar-lift-guide').hidden"))
                self.assertIn('Sun → Panel → Battery → Motor → Arm',self.js("document.getElementById('solar-lift-guide').textContent"))
                self.assertTrue(self.js("document.getElementById('solar-out-connect').disabled"))
                self.assertFalse(self.js("document.getElementById('sun-bearing').hidden"))
                self.assertIn('20 degrees',self.js("document.getElementById('sun-bearing').getAttribute('aria-label')"))
                self.assertIn('Bulb · shared load',self.js("document.getElementById('power-feedback-labels').textContent"))
                self.press('Add a solar panel');self.ghost()
                for label,value in [('turn',-90),('tip',70)]:self.slide(f'{label} of your solar 1',value)
                self.assertTrue(self.ghost()['fits'])
                self.press('Set it down');self.wait(f'!machineGhostState() && {READY}',60)
                self.wait("!document.getElementById('solar-out-connect').disabled",10)
                print('SOLAR LIFT UI',width,height,'panel placed',flush=True)
                self.assertFalse(self.js("document.getElementById('instrument-panel').tagName!=='SECTION'"),'Connection controls must be discoverable without opening readings')
                for id in ('solar-out-connect','solar-in-connect'):
                    self.assertTrue(self.js(f"(()=>{{const b=document.getElementById('{id}'),r=b.getBoundingClientRect();return r.width>=100&&r.height>=44&&b.scrollWidth<=b.clientWidth}})()"))
                self.click_visible('Panel Out')
                self.wait("document.getElementById('solar-out-connect').getAttribute('aria-pressed')==='true'",5)
                self.click_visible('Battery In');self.wait(f'machinePlacements().length===2 && {READY}',60)
                print('SOLAR LIFT UI',width,height,'cable drawn',flush=True)
                self.assertEqual(self.js('machinePlacements()[1]'),dict(piece='power_cable',a_port='your solar 1:power',b_port='supply:power'))
                self.wait("document.getElementById('solar-lift-connection').textContent.includes('Cable connected')",10)
                self.assertFalse(self.js("document.getElementById('instrument-panel').open"),'Compact wiring must not expand the detailed readings')
                self.wait("machineFlowPreviewState()?.sample?.solar_panels?.some(p=>p.power_w>49)",30)
                receipt=self.js("({sample:machineFlowPreviewState().sample,text:document.getElementById('solar-lift-reading').textContent})")
                sample,reading=receipt['sample'],receipt['text']
                self.assertIn('Preview',reading)
                self.assertIn(f"Panel {sample['solar_panels'][0]['power_w']:.1f} W",reading)
                battery=next(b for b in sample['batteries'] if b['name']=='supply battery')
                motor=next(d for d in sample['devices'] if d['name']=='drive')
                self.assertIn(f"Battery {battery['charge_j']:.1f} J",reading)
                self.assertIn(f"Motor {motor['power_w']:.1f} W",reading)
                if not self.js('machineFlowPreviewState().playing'):
                    self.click_visible('Play preview')
                self.wait("machineFlowPreviewState()?.sample?.light?.length>0&&machineFlowPreviewState()?.drawn?.bulbs>0",20)
                self.assertEqual(self.js('machineFlowPreviewState().drawn.lightSegments'),0,'Keep the native bulb glow without confusing ray guides in the sunlight lesson')
                self.assertTrue(self.js(READY),'Power preview must not consume the live starting battery')
                self.click_visible('Try It!');self.wait("!document.getElementById('level-done').hidden",30)
                self.assertNotIn('Try again',self.js("document.getElementById('level-done').textContent"))
        self.page.send('Emulation.setDeviceMetricsOverride',{'width':1280,'height':860,'deviceScaleFactor':1,'mobile':False})
        self.navigate(f'{self.base}/machine')
        self.wait("Boolean(document.querySelector('#prebuilt-designs button'))",60)
        self.press('Start from Sun powers the flag');self.wait(READY,60)
        self.assertFalse(self.js("document.getElementById('solar-lift-guide').hidden"))
        self.wait("document.getElementById('solar-lift-connection').textContent.includes('Cable connected')",10)
        initial=self.js("machineBodies()['flag'][1]")
        self.click_visible('Try It!');self.wait(f"machineBodies()['flag'][1]>={initial+.05}",30)
        self.click_visible('Pause')
        self.press('All designs');self.press('Start from Motor and finite supply');self.wait(READY,60)
        self.assertTrue(self.js("document.getElementById('solar-lift-guide').hidden"),'An unrelated motor example must keep its own controls')
        self.open('easy-charge-lift--v1--0000002a--0')
        self.press('Add a solar panel');self.ghost()
        # This archived recipe predates today's explicit charging cord.
        # Keep its panel clear of the now physical motor leads rather than
        # assuming the camera-centre drop is a valid manufactured layout.
        for label,value in [('Position along (m)',.8),('Position across (m)',0),('turn',-90),('tip',74)]:
            self.slide(f'{label} of your solar 1',value)
        self.assertTrue(self.ghost()['fits'])
        self.press('Set it down');self.wait(f'!machineGhostState() && {READY}',60)
        self.wait("document.getElementById('solar-lift-connection').textContent.includes('already connected')",10)
        self.assertTrue(self.js("document.getElementById('solar-out-connect').disabled&&document.getElementById('solar-in-connect').disabled"))
        self.assertEqual(len(self.js('machinePlacements()')),1,'The earlier direct-store recipe must not acquire a manufactured cable')

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
                self.click_visible('Try It!');self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Goal',self.js("document.getElementById('level-done').textContent"))

    def test_saved_solar_cable_survives_motion_renaming_reload_undo_and_version_restore(self):
        self.page.send('Emulation.setDeviceMetricsOverride', {'width':1280,'height':860,'deviceScaleFactor':1,'mobile':False})
        self.page.send('Emulation.setTouchEmulationEnabled', {'enabled':False})
        self.navigate(f'{self.base}/machine')
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
        self.navigate(self.js('location.href')); self.wait(READY, 60)
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

    def test_legacy_seeded_challenge_can_be_solved_shared_and_reopened_on_phones(self):
        for width, height in ((1280, 860), (390, 844), (844, 390)):
            with self.subTest(viewport=(width, height)):
                self.page.send('Emulation.setDeviceMetricsOverride', {'width':width,'height':height,'deviceScaleFactor':1,'mobile':width != 1280})
                self.navigate(f'{self.base}/play')
                self.wait("document.getElementById('levels-screen')?.hidden===false", 60)
                self.assertLessEqual(self.js('document.body.scrollWidth'), width)
                self.open('easy-loop--v2--0000002a--0',width,height,phone=width!=1280)
                self.wait(f"/easy-loop--v2--/.test(location.search) && {READY}", 60)
                link = self.js('location.href')
                title = self.js("document.getElementById('title').textContent")
                goal = self.js("document.getElementById('goal-line').textContent")
                self.assertIn('seed', title)
                self.assertIn('Fresh setup', goal)
                self.press('Share')
                self.assertEqual(self.js("document.getElementById('header-share').href"), link.replace(self.base,'https://banjo.is',1))
                self.navigate(link)
                self.wait(READY, 60)
                self.assertEqual(self.js("document.getElementById('title').textContent"), title)
                self.assertEqual(self.js("document.getElementById('goal-line').textContent"), goal)
                self.press('Add a wire'); self.ghost()
                self.slide('from terminal of your wire 1', 'lamp:minus')
                self.slide('to terminal of your wire 1', 'supply:minus')
                self.assertTrue(self.ghost()['fits'])
                self.press('Set it down'); self.wait(READY, 60)
                self.press('Try It!')
                self.wait("!document.getElementById('level-done').hidden", 30)
                self.assertNotIn('finished every level', self.js("document.getElementById('level-done').textContent"))
                self.assertFalse(self.js("Boolean(document.querySelector('#level-done [aria-label=\"Next level\"]'))"))
                self.press('All levels')
                self.assertLessEqual(self.js('document.body.scrollWidth'), width)
                self.assertFalse(self.js("Boolean(document.getElementById('challenge-family'))"))
                self.assertIn(title, self.js("document.querySelector('[aria-label=\"Recent challenges\"]').textContent"))
                self.press(title); self.wait(READY, 60)
                self.assertEqual(self.js('location.href'), link)

    def click_scene_socket(self,name,touch=False):
        if self.js(READY):self.wait('machineCamera().settled',30)
        self.paint()
        self.wait(f"window.machineSceneSockets().points.some(p=>p.name==={json.dumps(name)})",15)
        point=self.js(f"window.machineSceneSockets().points.find(p=>p.name==={json.dumps(name)})")
        self.assertTrue(self.js(f"document.elementFromPoint({point['x']},{point['y']})===document.querySelector('#view canvas')"),point)
        if touch:
            self.page.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':point['x'],'y':point['y'],'id':1}]})
            self.page.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
        else:
            self.mouse('mousePressed',point['x'],point['y']);self.mouse('mouseReleased',point['x'],point['y'])
        self.paint()
        option=self.js(f"document.querySelector('#socket-choices:not([hidden]) [data-socket-name={json.dumps(name)}]')?.textContent")
        if option:self.click_visible(option)

    def test_click_actual_scene_sockets_draws_a_wire_without_dropdowns_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-loop',width,height,phone=width!=1280)
                self.wait('window.machineFlowPreviewState()?.frames>2',30)
                self.assertTrue(self.js("(() => {const labels=[...document.querySelectorAll('.power-feedback-label')].filter(e=>!e.hidden).map(e=>e.getBoundingClientRect());return [...document.querySelectorAll('#scene-sockets circle')].every(e=>{const p=e.getBoundingClientRect();return labels.every(r=>p.right<r.left||p.left>r.right||p.bottom<r.top||p.top>r.bottom);});})()"),'power labels must leave actual connection rings visible')
                self.assertFalse(self.js("document.getElementById('wire-mode').matches('[aria-pressed=true]')"))
                self.click_scene_socket('lamp:minus',touch=width!=1280)
                self.ghost()
                self.assertEqual(self.js('window.machineWiringState().selected'),'lamp:minus')
                self.assertEqual(self.js("document.querySelector('#ghost-bar .state').textContent"),'Choose the other connection point.')
                self.assertEqual(self.js('window.machinePlacements()'),[],'the first click creates no saved wire')
                self.wait("document.getElementById('scene-wire-hint').textContent.includes('lamp:minus')",5)
                self.assertFalse(self.js("[...document.querySelectorAll('#ghost-bar select')].some(e=>!e.closest('#precision-controls')&&/terminal/.test(e.getAttribute('aria-label'))&&e.getClientRects().length)"))
                self.key('Escape');self.wait('!window.machineGhostState()',5)
                self.assertEqual(self.js('window.machinePlacements()'),[])
                self.click_scene_socket('lamp:minus',touch=width!=1280);self.ghost()
                self.click_scene_socket('supply:minus',touch=width!=1280)
                self.wait(f'!window.machineGhostState() && {READY}',60)
                self.assertEqual(self.js('window.machinePlacements().map(p=>[p.piece,p.a_terminal,p.b_terminal])'),
                                 [['wire','lamp:minus','supply:minus']])
                self.assertEqual(len(self.js('window.machineWiringState().wires')),3)
                self.click_visible('Try It!');self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Goal at',self.js("document.getElementById('level-done').textContent"))
                self.assertEqual(self.js('window.machineSceneSockets().points'),[],'live runs do not accept wiring edits')
                self.open('easy-loop',width,height,phone=width!=1280)
                self.press('Add a wire');self.ghost()
                self.click_scene_socket('lamp:minus',touch=width!=1280);self.ghost()
                self.click_scene_socket('supply:minus',touch=width!=1280)
                self.wait(f'!window.machineGhostState() && {READY}',60)
                self.assertEqual(self.js('window.machinePlacements()[0].b_terminal'),'supply:minus')

    def test_scene_socket_drag_and_two_fingers_do_not_connect_or_move_components(self):
        self.open('easy-loop');self.click_scene_socket('lamp:minus');self.ghost()
        target=self.js("window.machineSceneSockets().points.find(p=>p.name==='supply:minus')")
        self.mouse('mouseMoved',target['x'],target['y'])
        self.wait('window.machineSceneSockets().pending',5)
        self.drag([target['x'],target['y']],[target['x']+45,target['y']])
        self.assertEqual(self.js('window.machinePlacements()'),[])
        self.assertEqual(self.js('window.machineWiringState().selected'),'lamp:minus')
        self.assertEqual(self.ghost()['p']['b_terminal'],'')
        self.click_scene_socket('lamp:minus');self.wait('!window.machineGhostState()',5)
        self.open('easy-loop',390,844,phone=True)
        target=self.js("window.machineSceneSockets().points.find(p=>p.name==='lamp:minus')")
        self.page.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':target['x'],'y':target['y'],'id':1}]})
        self.page.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':target['x'],'y':target['y'],'id':1},{'x':target['x']-60,'y':target['y'],'id':2}]})
        self.page.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
        self.assertIsNone(self.js('window.machineGhostState()'))
        self.assertEqual(self.js('window.machinePlacements()'),[])

    def test_solar_scene_points_connect_in_either_order_and_from_the_cable_tray(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('sun',width,height,phone=width!=1280)
                self.press('Add a solar panel');self.ghost()
                for label,value in [('x',1),('z',.4),('height',.6),('turn',-45),('tip',75)]:
                    self.slide(f'{label} of your solar 1',value)
                self.ghost();self.press('Set it down');self.wait(f'!window.machineGhostState() && {READY}',60)
                kept=self.js('window.machinePlacements()')
                self.click_scene_socket('winch:power',touch=width!=1280)
                self.assertEqual(self.js('window.machineSceneSockets().selected'),'winch:power')
                self.assertEqual(self.js('window.machinePlacements()'),kept)
                self.click_scene_socket('your solar 1:power',touch=width!=1280)
                self.wait(f'window.machinePlacements().length===2 && {READY}',60)
                self.assertEqual(self.js('window.machinePlacements()[1]'),dict(piece='power_cable',a_port='your solar 1:power',b_port='winch:power'))
                self.press('Undo');self.wait(f'window.machinePlacements().length===1 && {READY}',60)
                self.press('Add a power cable');self.ghost()
                self.assertFalse(self.js("[...document.querySelectorAll('#ghost-bar select')].some(e=>!e.closest('#precision-controls')&&e.getClientRects().length)"))
                self.click_scene_socket('winch:power',touch=width!=1280);self.ghost()
                self.click_scene_socket('your solar 1:power',touch=width!=1280)
                self.wait(f'!window.machineGhostState() && window.machinePlacements().length===2 && {READY}',60)
                self.click_visible('Try It!');self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Goal at',self.js("document.getElementById('level-done').textContent"))

    def click_existing_wire(self,name,touch=False,fraction=.5,hold=0):
        self.wait('machineCamera().settled',30)
        self.wait(f'Boolean(window.machineWireScreen({json.dumps(name)},{fraction}))',10)
        # Native cords sag during setup. A projected point can be behind a
        # case or inside a terminal's touch area; canvas ownership alone does
        # not mean the visible wire can receive that click.
        removable=f'machineScenePick(...p).wires.includes({json.dumps(name)})' if name.startswith('your ') else 'true'
        expression=f"[{fraction},...Array.from({{length:39}},(_,i)=>(i+1)/40)].map(f=>machineWireScreen({json.dumps(name)},f)).find(p=>p&&document.elementFromPoint(...p)?.tagName==='CANVAS'&&{removable}&&!machineScenePick(...p).socket&&!machineScenePick(...p).pieces.length)"
        point=None;deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            # A fast live run can finish while we find a moving cord. Dismiss
            # the ordinary result overlay before trying to touch the scene.
            if self.js("Boolean(document.querySelector('#level-done:not([hidden]) .result-close'))"):
                self.click_visible('Close level complete')
            point=self.js(expression)
            if point:break
            time.sleep(.05)
        self.assertIsNotNone(point,'A visible wire segment must remain clickable')
        x,y=point
        self.assertEqual(self.js(f'document.elementFromPoint({x},{y})?.tagName'),'CANVAS')
        if touch:
            self.page.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x,'y':y,'id':1}]})
            if hold:time.sleep(hold)
            self.page.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
        else:
            self.mouse('mousePressed',x,y)
            if hold:time.sleep(hold)
            self.mouse('mouseReleased',x,y)
        if self.js("!document.getElementById('socket-choices').hidden"):
            self.click_visible('Remove '+name.removeprefix('your '))

    def test_existing_wire_click_removes_it_and_undo_redo_restore_the_exact_connection(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-loop',width,height,phone=width!=1280)
                self.click_scene_socket('lamp:minus',touch=width!=1280);self.ghost()
                # Finish the loop uses its prepared low-resistance leads;
                # wire sizing has separate lesson/Sandbox coverage.
                self.ghost();self.click_scene_socket('supply:minus',touch=width!=1280)
                self.wait(f'!window.machineGhostState() && {READY}',60)
                kept=self.js('window.machinePlacements()')
                self.click_existing_wire('your wire 1',touch=width!=1280)
                self.wait(f'window.machinePlacements().length===0 && !window.machineGhostState() && {READY}',60)
                self.click_visible('Try It!');self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Try again',self.js("document.getElementById('level-done').textContent"),'removing the return must physically open the circuit')
                self.press('Undo');self.wait(f'window.machinePlacements().length===1 && {READY}',60)
                self.assertEqual(self.js('window.machinePlacements()'),kept)
                self.press('Redo');self.wait(f'window.machinePlacements().length===0 && {READY}',60)
                self.press('Undo');self.wait(f'window.machinePlacements().length===1 && {READY}',60)
                self.assertEqual(self.js('window.machinePlacements()'),kept)
                self.click_visible('Try It!');self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Goal at',self.js("document.getElementById('level-done').textContent"))

    def test_close_scene_pins_offer_labelled_touch_targets_instead_of_guessing(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-loop',width,height,phone=width!=1280)
                self.js('window.machineView({distance:14})')
                a,b=self.js("['supply:plus','supply:minus'].map(name=>window.machineSceneSockets().points.find(p=>p.name===name))")
                x,y=(a['x']+b['x'])/2,(a['y']+b['y'])/2
                self.assertLess(((a['x']-b['x'])**2+(a['y']-b['y'])**2)**.5,44,'both connection points are within the click area')
                if width!=1280:
                    self.page.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x,'y':y,'id':1}]})
                    self.page.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
                else:
                    self.mouse('mousePressed',x,y);self.mouse('mouseReleased',x,y)
                self.wait("!document.getElementById('socket-choices').hidden",5)
                self.assertIsNone(self.js('window.machineGhostState()'),'an ambiguous click does not choose a conductor')
                self.click_visible('supply · minus (−)');self.ghost()
                self.assertEqual(self.js('window.machineWiringState().selected'),'supply:minus')
                self.key('Escape');self.wait('!window.machineGhostState()',5)
                self.assertEqual(self.js('window.machinePlacements()'),[])

    def test_reopening_solar_after_a_run_keeps_the_scene_during_rebuild(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.anonymous_levels(width=width,height=height)
                self.press('Sandbox: build anything')
                self.wait("Boolean(document.querySelector('#prebuilt-designs button'))",30)
                self.press('Start from Sun powers the flag')
                initial=set(self.js('machineRenderedBodies()'))
                self.assertGreaterEqual(len(initial),9)
                self.click_visible('Try It!')
                self.wait("/World [1-9]/.test(document.getElementById('clock').textContent)",30)
                self.click_visible('Pause')
                self.js("""window.solarRebuildFetch=window.fetch;
                    window.solarRebuildGate=new Promise(resolve=>window.releaseSolarRebuild=resolve);
                    window.fetch=async (...args)=>{const response=await window.solarRebuildFetch(...args);
                      if(JSON.parse(args[1]?.body||'null')?.op==='level_open'){
                        window.solarRebuildHeld=true;await window.solarRebuildGate;
                      }return response;};""")
                try:
                    self.click_piece(0)
                    self.wait('window.solarRebuildHeld===true',30)
                    self.assertEqual(set(self.js('machineRenderedBodies()')),initial,
                        'The old scene must remain present until the replacement is ready')
                finally:self.js('window.releaseSolarRebuild();window.fetch=window.solarRebuildFetch')
                self.wait(READY,30);self.ghost()
                self.assertEqual(set(self.js('machineRenderedBodies()')),initial)
                self.assertEqual(self.ghost()['p']['piece'],'solar')
                self.click_visible('Place');self.wait(READY,30)
                self.assertEqual(set(self.js('machineRenderedBodies()')),initial)

    def test_solar_cable_click_removes_from_either_end_and_undo_restores_it_even_live(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('sun',width,height,phone=width!=1280)
                self.press('Add a solar panel');self.ghost()
                for label,value in [('x',1),('z',.4),('height',.6),('turn',-45),('tip',75)]:
                    self.slide(f'{label} of your solar 1',value)
                self.ghost();self.press('Set it down');self.wait(f'!window.machineGhostState() && {READY}',60)
                self.click_scene_socket('your solar 1:power',touch=width!=1280)
                self.click_scene_socket('winch:power',touch=width!=1280)
                self.wait(f'window.machinePlacements().length===2 && {READY}',60)
                kept=self.js('window.machinePlacements()')
                for fraction in (.3,.7):
                    self.click_existing_wire('your power_cable 2',touch=width!=1280,fraction=fraction)
                    self.wait(f'window.machinePlacements().length===1 && {READY}',60)
                    self.assertIsNone(self.js('window.machineGhostState()'))
                    self.wait("!window.machineWiringState().powerCables.some(w=>w.visible)",5)
                    self.press('Undo');self.wait(f'window.machinePlacements().length===2 && {READY}',60)
                    self.assertEqual(self.js('window.machinePlacements().length'),2)
                    self.assertEqual(self.js('window.machinePlacements()[1].a_port'),kept[1]['a_port'])
                    self.assertEqual(self.js('window.machinePlacements()[1].b_port'),kept[1]['b_port'])
                self.click_visible('Try It!');self.wait("/calculating live/.test(document.getElementById('clock').textContent)",10)
                self.click_existing_wire('your power_cable 2',touch=width!=1280)
                self.wait(f'window.machinePlacements().length===1 && {READY}',60)
                self.press('Undo');self.wait(f'window.machinePlacements().length===2 && {READY}',60)
                self.assertEqual(self.js('window.machinePlacements()'),kept)

    def test_wire_drags_turn_the_camera_and_prepared_puzzle_wires_stay_fixed(self):
        self.open('easy-loop')
        prepared=self.js('window.machineWiringState().wires[0].name')
        self.assertFalse(prepared.startswith('your '))
        self.click_existing_wire(prepared)
        self.assertIsNone(self.js('window.machineGhostState()'))
        self.assertEqual(self.js('window.machinePlacements()'),[])
        self.click_scene_socket('lamp:minus');self.ghost();self.click_scene_socket('supply:minus')
        self.wait(f'!window.machineGhostState() && {READY}',60)
        kept=self.js('window.machinePlacements()')
        x,y=self.js("[.5,.25,.75,.15,.85].map(f=>machineWireScreen('your wire 1',f)).find(p=>p&&document.elementFromPoint(...p)?.tagName==='CANVAS'&&!machineScenePick(...p).socket)")
        angle=self.js('window.machineCamera().azimuth')
        self.drag([x,y],[x+50,y])
        self.assertNotEqual(self.js('window.machineCamera().azimuth'),angle)
        self.assertIsNone(self.js('window.machineGhostState()'))
        self.assertEqual(self.js('window.machinePlacements()'),kept)

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
                self.click_visible('Try It!')
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Try again', self.js("document.getElementById('level-done').textContent"),
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
                # Routes are now native sagging cables, not a fixed-height
                # schematic. All three leads must expose real rod geometry.
                self.assertTrue(all(w['mechanical'] and w['mechanical']['segments_m'] and w['vertices']>0 for w in wires),wires)
                self.click_visible('Try It!')
                self.wait("!document.getElementById('level-done').hidden",30)
                self.wait('window.machineWiringState().wires.every(w=>w.color===0xffd34d)',10)
                self.open('easy-marble-light', width, height, phone=width<1000)
                self.assertEqual(len(self.js('window.machineWiringState().wires')), 1)
                self.press('Add a switch'); self.ghost()
                self.slide('along (m) of your switch 1', 0); self.slide('across (m) of your switch 1', 0)
                self.assertTrue(self.ghost()['fits'])
                self.assertEqual(self.js('window.machineWiringState().ghostWires'),3)
                self.wait("[...document.querySelectorAll('.terminal-label')].length===3 && [...document.querySelectorAll('.terminal-label')].every(c=>!c.hidden)", 10)
                self.click_visible('Try It!')
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertEqual(len(self.js('window.machineWiringState().wires')),3)

    def test_level_task_counts_and_saved_wiring_use_the_real_scene_controls(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            self.anonymous_levels(width=width,height=height)
            self.assertEqual(self.js("document.querySelectorAll('#levels-screen .ls-list .level-card').length"), self.level_count)
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
        self.press('Try It!')
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
        self.navigate(f'{self.base}/machine')
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
                self.press('Restart with my pieces')
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
        self.assertEqual(self.ghost()['p']['state'],'open')
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

    def test_heat_clip_and_two_scene_wires_release_the_weight_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-heat',width,height,phone=width<1000)
                self.press('Add a heating coil');self.ghost()
                self.assertEqual(self.ghost()['p']['target'],'')
                self.assertFalse(self.js("Boolean(document.querySelector('#ghost-bar select[aria-label=\"Its attached target\"]'))"))
                self.wait("document.getElementById('heater-attach').checkVisibility()",10)
                self.assertTrue(self.js("(()=>{const e=document.getElementById('heater-attach'),r=e.getBoundingClientRect();return r.width>=44&&r.height>=56&&r.left>=0&&r.right<=innerWidth&&r.top>=document.getElementById('clock').getBoundingClientRect().bottom&&r.bottom<=document.getElementById('view').getBoundingClientRect().bottom&&document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===e;})()"))
                self.assertEqual([p['name'] for p in self.js('machineSceneSockets().points')],['heat:weight rope'])
                self.click_visible('Help')
                with patch('machine_chat.configuration',return_value=(None,'no-model')):
                    self.js("document.getElementById('message').value='How do I attach this heater?' ")
                    self.click_visible('Ask for a hint')
                    self.wait("document.querySelector('#chat-log .model')?.textContent.includes('Click Clip to cord')",10)
                    self.assertFalse(self.js("document.getElementById('coach-open').checkVisibility()"))
                self.click_visible('Controls')
                self.click_visible('Clip heater to hanging cord')
                self.wait("window.machineGhostState()?.p.target==='weight rope' && "+SETTLED,30)
                self.assertTrue(self.ghost()['fits'])
                self.click_visible('Toggle coil preset');self.ghost()
                self.assertEqual(self.ghost()['p']['preset'],'hot')
                self.assertIn('Hot',self.js("document.getElementById('piece-choice-toggle').textContent"))
                self.click_visible('Place');self.wait(READY,60)
                self.assertEqual(len(self.js('window.machineWiringState().wires')),0,'attachment alone does not power the heater')
                for a,b in [('supply:plus','your ignition 1:plus'),('your ignition 1:minus','supply:minus')]:
                    self.click_scene_socket(a,touch=width<1000);self.ghost()
                    self.click_scene_socket(b,touch=width<1000)
                    self.wait('!window.machineGhostState() && '+READY,60)
                self.assertEqual(len(self.js('window.machineWiringState().wires')),2)
                self.click_visible('Try It!')
                self.wait("document.getElementById('power-feedback-labels').textContent.includes('Material')",20)
                self.wait("!document.getElementById('level-done').hidden",45)
                self.assertRegex(self.js("document.getElementById('level-done').textContent"),'Level Complete|Achievement Unlocked')
                self.click_visible('Reset');self.wait(READY,60)
                self.assertEqual(self.js('window.machinePlacements().length'),0)

    def test_marble_switch_wires_stay_dark_until_actual_contact_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-marble-light',width,height,phone=width<1000)
                self.press('Add a switch');self.ghost()
                self.slide('along (m) of your switch 1',0);self.slide('across (m) of your switch 1',0)
                self.assertTrue(self.ghost()['fits'])
                self.click_visible('✓ Set down')
                self.wait(f'!window.machineGhostState() && {READY}',60)
                self.wait('window.machineFlowPreviewState()?.frames>2 && window.machineFlowPreviewState().index===0',60)
                preview=self.js('window.machineFlowPreviewState()')
                self.assertFalse(preview['playing'])
                self.assertEqual(preview['time'],0)
                self.assertEqual(preview['drawn']['arrows'],0)
                self.assertEqual(preview['drawn']['bulbs'],0)
                self.assertEqual(self.js('window.machinePowerFeedbackState().dots'),0)
                self.assertTrue(all(w['color']!=0xffd34d for w in self.js('window.machineWiringState().wires')))
                self.assertTrue(all(abs(w['value'])<1e-10 for w in preview['sample']['wires']))
                self.assertIn('your switch 1 contact leaf',[p['name'] for p in preview['drawn']['mechanisms']])
                self.click_visible('Try It!')
                self.wait('window.machineWiringState().wires.every(w=>w.color===0xffd34d)',10)
                self.wait('window.machinePowerFeedbackState().dots>0',5)
                self.assertFalse(self.js('Boolean(window.machineFlowPreviewState()?.visible)'))
                self.assertTrue(self.js("window.machineContactState().liveDevices.find(d=>d.kind==='switch').closed"))
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertTrue(self.js("document.getElementById('level-done').parentElement===document.getElementById('view')"),'the success is over the scene')
                self.click_visible('Close level complete')
                self.click_visible('Inspect your switch 1 contacts')
                self.wait('window.machineCamera().settled',15)
                self.assertTrue(self.js("document.getElementById('level-done').hidden"),'closing the result restores inspection controls')
                for terminal in ('your switch 1:in','your switch 1:out'):
                    x,y=self.screen_point(self.js(f'window.machineContactState().liveTerminals[{json.dumps(terminal)}]'))
                    bounds=self.js("(()=>{const r=document.getElementById('view').getBoundingClientRect();return [r.left,r.top,r.right,r.bottom];})()")
                    self.assertTrue(bounds[0]<=x<=bounds[2] and bounds[1]<=y<=bounds[3],(terminal,x,y,bounds))
                self.click_visible('Restart with my pieces')
                self.wait(READY,60)
                self.wait('window.machinePowerFeedbackState().dots===0',15)

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
                self.wait("window.machinePreviewState()?.legend.includes('to start') && document.querySelector('[aria-label=\"Drag trigger handle\"]')?.checkVisibility()",20)
                self.click_visible('Try It!')
                self.wait("!document.getElementById('level-done').hidden",30)
                self.assertIn('Try again',self.js("document.getElementById('level-done').textContent"))
                self.assertFalse(self.js("window.machineSwitchState().handles.find(h=>h.name==='trigger').closed"))
                self.press('Keep my pieces');self.wait(READY,60)
                self.assertEqual(self.js("document.querySelector('[aria-label=\"Drag trigger handle\"]').textContent"),'Drag to fire ↓')
                self.click_visible('Drag trigger handle')
                self.assertTrue(self.js(READY),'a tap does not fire')
                x,y=self.switch_handle_target('trigger')
                self.drag([x,y],[x,y+85],touch=width<1000,steps=12)
                self.wait("!document.getElementById('level-done').hidden",30)
                result=self.js("document.getElementById('level-done').textContent")
                if 'Try again' in result:
                    print('CANNON_DRAG_FAILURE',json.dumps(self.js('({switch:machineSwitchState(),contact:machineContactState(),placements:machinePlacements()})')),flush=True)
                    for native in self.server.machines.sessions.values():
                        if native.compiled['title']=='Knock it off':
                            frame=native.frame(0,0)
                            print('CANNON_NATIVE_FAILURE',json.dumps(dict(t=frame['t'],
                                readouts={key:frame['readouts'].get(key) for key in ('joints','pulls','heat','gas','stations')},
                                ledgers=[n['ledger'] for n in frame['readouts']['electrical']['networks']],
                                bodies=[b for b in frame['bodies'] if b['name'] in ('block','your cannon 1 ball','trigger handle')])) ,flush=True)
                self.assertNotIn('Try again',result)
                self.assertNotIn('A test run',result)
                self.assertIn('your pulls',result)
                self.assertEqual(self.js('machineSave().players[machineSave().current].levels.fire.stars'),3)

    def test_saved_terminal_graph_removal_undo_reload_and_restore(self):
        self.page.send('Emulation.setDeviceMetricsOverride',{'width':1280,'height':860,'deviceScaleFactor':1,'mobile':False})
        self.page.send('Emulation.setTouchEmulationEnabled',{'enabled':False})
        self.navigate(f'{self.base}/machine')
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
            self.click_scene_socket(f'your battery 1:{terminal}');self.ghost()
            self.click_scene_socket(f'your bulb 2:{terminal}')
            self.wait(f'!window.machineGhostState() && {READY}', 60)
        first = self.js('window.machinePlacements()')
        self.press('Save version')
        self.wait("/Version 1 saved/.test(document.getElementById('design-status').textContent)", 10)
        self.click_existing_wire('your wire 3');self.wait(f'window.machinePlacements().length===3 && {READY}',60)
        rewired=self.js('window.machinePlacements()')
        self.assertNotEqual(rewired,first)
        self.assertEqual(len(rewired),3)
        self.press('Save version');self.wait("/Version 2 saved/.test(document.getElementById('design-status').textContent)",10)
        self.anonymous_cloud_saved()
        self.page.send('Page.reload',{});self.wait(READY,60)
        self.assertEqual(self.js('window.machinePlacements()'),rewired)
        self.js("document.getElementById('design-versions').open=true;document.getElementById('version-pick').value='1'")
        self.press('Restore version');self.wait(f'window.machinePlacements().length===4 && {READY}',60)
        self.assertEqual(self.js('window.machinePlacements()'),first)
        self.assertEqual(self.js('window.machineDesign().versions.map(v=>v.number)'),[1,2,3],'restoring keeps a Before restore checkpoint')
        self.press('Remove your battery 1')
        self.wait(f'window.machinePlacements().length === 1 && {READY}', 60)
        self.assertEqual(self.js('window.machinePlacements()[0].piece'), 'bulb')
        self.press('Undo')
        self.wait(f'window.machinePlacements().length === 4 && {READY}', 60)
        self.assertEqual(self.js('window.machinePlacements()'), first)
        self.navigate(self.js('location.href'))
        self.wait(READY, 60)
        self.assertEqual(self.js('window.machinePlacements()'), first)
        self.press('Remove your battery 1')
        self.wait(f'window.machinePlacements().length === 1 && {READY}', 60)
        self.press('Save version')
        self.wait("/Version 4 saved/.test(document.getElementById('design-status').textContent)", 10)
        self.js("document.getElementById('design-versions').open = true; document.getElementById('version-pick').value = '1'")
        self.press('Restore version')
        self.wait(f'window.machinePlacements().length === 4 && {READY}', 60)
        self.assertEqual(self.js('window.machinePlacements()'), first)
        self.press('Try It!')
        self.wait("/your bulb 2.*0\\.60 W light/.test(document.getElementById('readings').textContent)", 15)

    def test_selected_controls_highlight_the_piece_and_follow_its_orientation(self):
        self.open('free')
        self.press('Add a plank')
        guide = self.ghost()['editGuide']
        self.assertEqual(guide['key'], 'length_m')
        self.assertEqual(len(guide['arrows']), 2)
        self.wait("!document.getElementById('edit-guide-label').hidden", 5)
        # A full 2 cm native cell changes the measured surface extent.
        self.slide('Its length',self.ghost()['p']['length_m']+.02)
        old_extent=max(a['at'][0] for a in guide['arrows'])
        self.wait(f"machineGhostState().editGuide.arrows.some(a=>a.at[0]>{old_extent})",5)
        changed = self.ghost()['editGuide']
        self.assertGreater(max(a['at'][0] for a in changed['arrows']), max(a['at'][0] for a in guide['arrows']))
        self.press('Change its turn')
        self.assertEqual(self.ghost()['editGuide']['key'], 'yaw_deg')
        self.slide('Its turn', 90)
        self.ghost()
        self.press('Change its length')
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
        # This lesson exposes length; its prepared orientation stays flat.
        g = self.ghost()
        self.assertEqual((g['p']['length_m'], g['p']['yaw_deg'], g['p']['pitch_deg']), (0.7, 0, 0))
        self.assertTrue(g['fits'], g['problems'])
        # Where the ball will go with the ghost as it is: the engine's own
        # rehearsal, drawn before anything is set down or run.
        self.wait("(() => { const p = window.machinePreviewState(); return Boolean(p && p.goal_at_s != null); })()", 30)
        shown = self.js('window.machinePreviewState()')
        self.assertEqual(shown['goal_at_s'], 1.9)
        self.assertIn('after it hits your plank 1', shown['legend'])
        self.press('Try It!')
        self.wait('!window.machineGhostState()', 5)
        self.wait("Boolean(document.querySelector('#verdict .stars'))", 90)
        self.assertIn('★★★', self.js("document.getElementById('verdict').textContent"))
        # The result in Controls leads on to the next catalogue entry.
        self.wait("!document.getElementById('level-done').hidden", 10)
        done = self.js("document.getElementById('level-done').textContent")
        self.assertIn('Achievement Unlocked', done)
        self.assertIn('Your first win with a plank!', done)
        self.assertIn('Energy used: 30.6 MJ', done)
        self.assertIn('Your plank 1: 2.94 kg, 30.6 MJ', done)
        import machine_game
        catalogue = machine_game.load_levels()
        next_level = catalogue[next(i for i, row in enumerate(catalogue) if row['id'] == 'gap') + 1]['id']
        self.press('Next level')
        self.wait(f"new URLSearchParams(location.search).get('level') === {json.dumps(next_level)} && {READY}", 30)

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
                self.navigate(self.base + '/play')
                self.wait("document.getElementById('levels-screen')?.hidden===false", 60)
                before = open_help()
                # A backdrop click dismisses, while content clicks do not.
                self.mouse('mousePressed', 2, 2); self.mouse('mouseReleased', 2, 2); assert_closed(before)
                self.navigate(self.base + '/machine')
                self.wait("document.getElementById('sandbox-screen')?.hidden===false", 60)
                before = open_help(); self.click_visible('Close'); assert_closed(before)
                self.press('Add New Design'); self.wait(READY, 60)
                before = open_help(); self.click_visible('Close'); assert_closed(before)

    def test_recent_changes_preserves_builds_and_fits_every_screen(self):
        def open_updates():
            self.anonymous_cloud_saved()
            self.assertFalse(self.js("document.getElementById('recent-changes').open"))
            before = self.js("({url:location.href,setup:window.machinePlacements(),ghost:window.machineGhostState(),save:localStorage.getItem('banjo-play-save'),scroll:scrollY})")
            navigation = self.js("[...document.querySelectorAll('header nav a')].map(e=>{const r=e.getBoundingClientRect();return {label:e.getAttribute('aria-label')||e.textContent,x:r.x+r.width/2,y:r.y+r.height/2,w:r.width,h:r.height,visible:r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight,hit:e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))};})")
            self.assertEqual([r['label'] for r in navigation], ['Levels','Sandbox','How to play','Recent Changes','Share'])
            for target in navigation:
                self.assertTrue(target['visible'] and target['hit'], target)
                self.assertGreaterEqual(target['w'], 44); self.assertGreaterEqual(target['h'], 44)
            self.page.events.clear()
            target=navigation[-2]
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
            self.js("(()=>{const notes=document.querySelector('.changes-body');notes.scrollTop=notes.scrollHeight;})()")
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
                self.click_visible('Try It!'); self.wait("/Pause/.test(document.getElementById('start').textContent)", 10)
                # Reading updates does not stop or reopen a running machine.
                before=open_updates(); self.click_visible('Close'); closed(before)
                self.assertRegex(self.js("document.getElementById('start').textContent"), 'Pause')
                self.click_visible('Pause')
                for path, screen in (('/play','levels-screen'),('/machine','sandbox-screen')):
                    self.navigate(self.base+path)
                    self.wait(f"document.getElementById('{screen}')?.hidden===false",60)
                    before=open_updates()
                    self.mouse('mousePressed',2,2); self.mouse('mouseReleased',2,2); closed(before)
                self.press('Add New Design'); self.wait(READY,60)
                before=open_updates(); self.click_visible('Close'); closed(before)

    def test_combined_help_public_share_and_sandbox_word_builder_on_all_screens(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-cut',width,height,phone=width!=1280)
                self.assertEqual(self.js("[...document.querySelectorAll('#phone-tabs button')].filter(b=>b.checkVisibility()).map(b=>b.textContent)"),['Controls','Help'])
                self.assertFalse(self.js("document.getElementById('pull-tool').checkVisibility()"))
                self.assertFalse(self.js("Boolean(document.getElementById('challenge-fresh'))"))
                self.click_visible('Help')
                self.assertTrue(self.js("!document.getElementById('phone-help-panel').contains(document.getElementById('game')) && document.getElementById('phone-help-panel').contains(document.getElementById('feedback'))"))
                self.assertEqual(self.js("document.querySelector('#level-details summary')"),None)
                self.assertFalse(self.js("document.getElementById('brief').checkVisibility()"))
                self.press('Share')
                self.assertEqual(self.js("document.getElementById('header-share').href"),'https://banjo.is/play?level=easy-cut')
                self.click_summary('#feedback > summary')
                self.assertTrue(self.js("document.getElementById('feedback-form').checkVisibility()"))
                self.assertTrue(self.js("(()=>{const r=document.getElementById('feedback-send').getBoundingClientRect();return r.height>=44&&r.right<=innerWidth;})()"))
                self.open('free',width,height,phone=width!=1280)
                self.press('All designs'); self.press('Start from Tip the lever'); self.wait(READY,60)
                base=self.js('machineDesign().draft.base')
                self.assertIsNotNone(base)
                self.click_visible('Controls'); self.click_visible('Describe a design')
                self.assertEqual(self.js("document.getElementById('phone-help-tab').getAttribute('aria-selected')"),'true')
                self.assertEqual(self.js('document.activeElement.id'),'message')
                self.js("document.getElementById('message').value='Add a glass marble on the table'")
                answer={'reply':'Added a marble.','clear':False,'add':[{'piece':'marble','x_m':1,'z_m':1}]}
                with patch('machine_chat.configuration',return_value=('fixture-key','fixture-model')), patch('machine_chat._call',return_value=(answer,{})):
                    self.press('Build it')
                    self.wait("/Added a marble/.test(document.getElementById('chat-log').textContent) && machinePlacements().some(p=>p.piece==='marble') && "+READY,60)
                self.assertEqual(self.js('machineDesign().draft.base'),base)
                self.assertTrue(self.js("machineBodies()['your marble 2'] || machinePlacements().some(p=>p.piece==='marble')"))
                self.press('Share this design'); self.wait("Boolean(machineShareLink())",10)
                self.assertTrue(self.js('machineShareLink()').startswith('https://banjo.is/machine#build='))

    def test_a_player_can_tell_us_what_happened(self):
        self.open('gap')
        # Telling us: the words, with the level and its pieces, reach the log.
        self.js("document.getElementById('feedback').open = true")
        self.js("document.getElementById('feedback-text').value = 'The plank looked like it floated'")
        self.press('Send report')
        self.wait("/Report saved/.test(document.getElementById('feedback-status').textContent)", 10)
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
            self.navigate(self.base + '/')
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
            self.navigate(self.base + '/')
            self.wait(f"document.querySelectorAll('.ls-list .level-card').length === {self.level_count} && Boolean(document.getElementById('visitor-return-link'))", 30)
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
        response=self.navigate(url or f'{self.base}/play')
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
        self.navigate(parked)
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
            self.assertIn('Best win: 12.3 MJ',self.js("document.querySelector('.ls-list .level-card[data-level=gap]').textContent"))
            self.assertNotIn('Returning builder',self.js("document.getElementById('levels-screen').textContent"))
            self.assertNotIn('Other builder',self.js("document.getElementById('levels-screen').textContent"))
            second=next(key for key in migrated['players'] if key!=first)
            second_link=f'{self.base}/play?visitor={second}'
            self.assertTrue(self.js(f"[...document.querySelectorAll('#levels-screen .previous-save')].some(a=>a.href==={json.dumps(second_link)})"))
            self.js(f"(()=>{{const a=[...document.querySelectorAll('#levels-screen .previous-save')].find(a=>a.href==={json.dumps(second_link)});a.closest('details').open=true;a.click();}})()")
            self.wait(f"window.machineSave?.().current==={json.dumps(second)} && document.querySelector('.ls-list .level-card[data-level=gap]')?.textContent.includes('Best win: 28.8 MJ')",30)
            self.assertEqual(self.anonymous_levels()[0],second,'The Previous saves link updates the remembered cookie')
            self.assertIn('Best win: 28.8 MJ',self.js("document.querySelector('.ls-list .level-card[data-level=gap]').textContent"))
            self.assertNotIn('12.3 MJ',self.js("document.querySelector('.ls-list .level-card[data-level=gap]').textContent"))
            self.assertEqual(self.anonymous_levels(first_link)[0],first)
            self.assertIn('Best win: 12.3 MJ',self.js("document.querySelector('.ls-list .level-card[data-level=gap]').textContent"))
            self.assertNotIn('28.8 MJ',self.js("document.querySelector('.ls-list .level-card[data-level=gap]').textContent"))
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
            self.navigate(self.js('location.href'));self.wait(READY,90)
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
        self.navigate(f'{self.base}/play')
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
        self.wait("machinePlacements().length === 1 && /1 piece on the table/.test(document.getElementById('cost-line').textContent)", 60)
        self.navigate(f'{self.base}/play?level=free')
        self.wait(READY, 90)
        self.wait("machinePlacements().length === 1", 30)
        self.assertEqual(self.js('machinePlacements()[0].piece'),'marble')
        self.js('window.confirm = () => true')
        self.press('Set out the example')
        self.wait(f"machinePlacements().length === 11 && {READY}", 90)
        self.press('Try It!')
        self.wait("(window.machineBodies()['your dominoes 11 6'] || [0, 1])[1] < 0.045", 60)
        self.assertTrue(self.js("document.getElementById('level-done').hidden"), 'no score: there is no goal')

    def test_sandbox_library_migrates_free_build_and_saves_reopens_and_restores_designs(self):
        # An old free build survives the upgrade. Two named designs keep
        # independent drafts, and checkpoints survive navigation/reloads.
        self.navigate(f'{self.base}/machine')
        self.wait("document.getElementById('sandbox-screen') && !document.getElementById('sandbox-screen').hidden", 60)
        old = self.js("localStorage.getItem('banjo-play-save')")
        cookies=self.page.send('Network.getCookies',{'urls':[self.base]})['cookies']
        self.anonymous_fixture_clear()
        self.anonymous_storage_put('banjo-play-save',json.dumps({'current':'Sandbox test','players':{'Sandbox test':{'levels':{},'free':{'placements':[{'piece':'marble','x_m':0,'z_m':0}]}}}}))
        try:
            self.navigate(f'{self.base}/machine')
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
            self.navigate(self.js('location.href'))
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
        self.navigate(f'{self.base}/machine')
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
        self.assertTrue(link.startswith('https://banjo.is/machine#build='))
        self.navigate(link.replace('https://banjo.is',self.base,1))
        self.wait(f"document.getElementById('clock') && {READY}", 60)
        self.assertEqual(self.js('window.machineDesign().draft.base'), base)
        self.assertEqual(self.js('window.machinePlacements().length'), 1)
        self.press('Try It!')
        self.wait("/World 2\\./.test(document.getElementById('clock').textContent)", 30)
        self.press('Pause')
        self.assertTrue(self.js("document.getElementById('level-done').hidden"))
        self.press('Restart with my pieces')
        self.wait(READY, 60)
        self.assertEqual(self.js("document.querySelectorAll('#stations li').length"), 9)


    def test_piece_library_search_filter_cancel_and_placement_on_desktop_and_phones(self):
        for width, height in ((1280, 860), (390, 844), (844, 390)):
            with self.subTest(viewport=(width, height)):
                self.page.send('Emulation.setDeviceMetricsOverride', {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': width != 1280})
                self.navigate(f'{self.base}/machine')
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
                self.assertEqual(self.js("[...document.querySelectorAll('#piece-grid strong')].map(e=>e.textContent)"), ['cannon', 'steam', 'open airflow'])
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
                self.press('Try It!')
                self.wait("/World 2\\./.test(document.getElementById('clock').textContent)", 30)
                self.press('Pause')
                self.press('Restart with my pieces')
                self.wait(READY, 60)
                self.assertEqual(self.js('window.machinePlacements().length'), 12)

    def test_sandbox_library_and_controls_fit_phone_portrait_and_landscape(self):
        for width, height in ((390, 844), (844, 390)):
            with self.subTest(viewport=(width, height)):
                self.page.send('Emulation.setDeviceMetricsOverride', {'width': width, 'height': height, 'deviceScaleFactor': 2, 'mobile': True})
                self.navigate(f'{self.base}/machine')
                self.wait("Boolean(document.querySelector('#prebuilt-designs button'))", 60)
                self.assertLessEqual(self.js('document.body.scrollWidth'), width)
                self.assertTrue(self.js("[...document.querySelectorAll('#sandbox-screen button')].filter(b=>b.offsetParent!==null).every(b => b.getBoundingClientRect().height >= 44 && b.getBoundingClientRect().right <= innerWidth)"))
                self.press('Start from Gate and split')
                self.wait(READY, 60)
                self.assertLessEqual(self.js('document.body.scrollWidth'), width)
                for selector in ('#start', '#reset', '#attach-tool'):
                    self.reveal_control(f"document.querySelector('{selector}')")
                    box = self.js(f"(() => {{const r=document.querySelector('{selector}').getBoundingClientRect();return {{h:r.height,x:r.x,right:r.right,top:r.top,bottom:r.bottom}};}})()")
                    scene = self.js("(() => {const r=document.querySelector('#view').getBoundingClientRect();return {top:r.top,bottom:r.bottom};})()")
                    self.assertGreaterEqual(box['h'], 44)
                    self.assertGreaterEqual(box['x'], 0)
                    self.assertLessEqual(box['right'], width)
                    self.assertGreaterEqual(box['top'], 0)
                    self.assertLessEqual(box['bottom'], height, (selector,box))
                    self.assertTrue(self.js(f"Boolean(document.querySelector('{selector}').closest('#control-panel,#phone-toolbar,#help-settings'))"))
                self.press('All designs')

    def test_a_track_snaps_to_another_and_pieces_are_copied_undone_and_joined(self):
        # A second track put at the first's far end snaps under it. A piece
        # is copied, a change taken back and put back, and two parts are tied
        # by a string with Attach.
        self.page.send('Emulation.setDeviceMetricsOverride', {'width': 1280, 'height': 860, 'deviceScaleFactor': 1,
                                                              'mobile': False})
        self.navigate(f'{self.base}/play?level=free')
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
        # Nearby-object capture requires proximity in height as well as the
        # ground plane; set the inlet at the outlet height before dragging.
        self.slide('top end height of your track 2',far[1])
        self.ghost()
        self.drag_ghost_to(far[0],far[2])
        self.wait("(() => { const g = window.machineGhostState(); return g && g.answered && !g.busy && "
                  "/joined to far end of your track 1/.test(document.querySelector('#ghost-bar .state').textContent); })()", 20)
        p = self.ghost()['p']
        self.assertAlmostEqual(p['x_m'], far[0] + 0.03, delta=0.011)
        self.assertAlmostEqual(p['top_height_m'], far[1] - 0.04, delta=0.011)
        self.press('Set it down')
        self.wait(f"window.machinePlacements().length === 2 && {READY}", 60)
        self.assertFalse(self.js("[...document.querySelectorAll('button')].some(b=>b.textContent==='Copy')"))
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
        self.assertEqual(link['b'],'your marble 3')
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
        self.navigate(f'{self.base}/play?level=free')
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
        self.assertTrue(link.startswith('https://banjo.is/machine#build='))
        self.navigate(link.replace('https://banjo.is',self.base,1))
        self.wait(f"typeof window.machinePlacements === 'function' && window.machinePlacements().length === 11 && {READY}", 90)
        self.assertEqual(self.js('window.machinePlacements()'), made)
        self.assertNotIn('#build', self.js('location.href'), 'the link is read once')
        self.assertEqual(self.js("document.getElementById('send').textContent"), 'Build it', 'the chat builds here')
        # Links made before named designs held an array, not a declaration.
        packed = base64.urlsafe_b64encode(json.dumps(made).encode()).decode().rstrip('=')
        self.navigate(f'{self.base}/play?level=free#build=j{packed}')
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
        self.wait("/to make/.test(document.getElementById('cost-line').textContent)", 60)
        self.press('Try It!')
        self.wait("!document.getElementById('level-done').hidden", 30)
        self.assertIn('Try again', self.js("document.getElementById('level-done').textContent"))
        self.assertEqual(self.js("[...document.querySelectorAll('#level-done button')].map(b=>b.textContent)"),['Try again','Ask for Help'])
        self.press('Keep my pieces'); self.wait(READY, 60)
        self.assertEqual(len(self.js('machinePlacements()')), 1)
        self.press('Try It!'); self.wait("!document.getElementById('level-done').hidden", 30)
        self.assertIn('Try again', self.js("document.getElementById('level-done').textContent"))
        self.assertEqual(self.js("[...document.querySelectorAll('#level-done button')].map(b=>b.textContent)"),['Try again','Ask for Help'])
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
        self.navigate(f'{self.base}/play?level=free')
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
        self.press('Try It!')
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
                self.assertTrue(self.js("document.getElementById('view').contains(document.getElementById('level-done'))"))
                self.assertIn('Your plank 1: 3.28 kg, 34.1 MJ',
                              self.js("document.getElementById('level-done-energy').innerText"))
                self.js("document.querySelector('#level-done .actions').scrollIntoView({block: 'nearest'})")
                self.assertTrue(self.js("[...document.querySelectorAll('#level-done .actions button')].every(b => { "
                                        "const r = b.getBoundingClientRect(), p = document.getElementById('level-done').getBoundingClientRect(); "
                                        "return r.left >= p.left && r.right <= p.right && r.top >= p.top && r.bottom <= p.bottom + 1; })"))
        self.press('Energy details')
        self.assertTrue(self.js("document.getElementById('level-done-energy').hidden"))

    def test_kept_pieces_reruns_show_current_energy_against_perfect_score_on_all_screens(self):
        for width, height in ((1280, 860), (390, 844), (844, 390)):
            with self.subTest(viewport=(width, height)):
                self.open('gap', width, height, phone=width != 1280)
                self.press('Add a plank'); self.ghost()
                for label, value in [('Cut to length', .78), ('Set down at x', .3), ('across (z, m)', 0)]:
                    self.slide(label + ' of your plank 1', value)
                self.ghost(); self.press('Set it down'); self.wait(READY)
                # A first win and two ordinary reruns: same build, then a lighter one.
                for attempt, length in enumerate((.78, .78, .70)):
                    if attempt:
                        self.press('Restart with my pieces' if attempt == 1 else 'Play this level again'); self.wait(READY)
                        self.assertTrue(self.js("document.getElementById('level-done').hidden"))
                        self.assertEqual(len(self.js('machinePlacements()')), 1)
                    if attempt == 2:
                        self.click_piece(0)
                        self.slide('Cut to length of your plank 1', length)
                        self.ghost(); self.press('Set it down'); self.wait(READY)
                    self.press('Try It!')
                    self.wait("!document.getElementById('level-done').hidden")
                    self.assertTrue(self.js("document.getElementById('level-done-energy').hidden"))
                    summary = self.js("document.getElementById('level-done-score').innerText")
                    self.assertIn('Perfect score target: 30.6 MJ or less.', summary)
                    self.assertIn('Energy used: ' + ('34.1 MJ' if attempt < 2 else '30.6 MJ'), summary)
                    self.assertIn('above target.' if attempt < 2 else 'Energy target met.', summary)
                    self.assertEqual(self.js("document.querySelector('#level-done .stars').textContent"),
                                     '★★☆' if attempt < 2 else '★★★')
                    # The actual comparison is visible over the scene, with no disclosure.
                    self.assertTrue(self.js("(() => {const e=document.getElementById('level-done-score'), r=e.getBoundingClientRect(), p=document.getElementById('level-done').getBoundingClientRect(); return e.checkVisibility() && r.left>=p.left && r.right<=p.right+1 && r.top>=p.top && r.bottom<=p.bottom+1;})()"))

    def test_object_snap_starts_on_after_old_preference_reload_and_level_switch(self):
        import machine_game
        catalogue = machine_game.load_levels()
        rank = next(i for i, row in enumerate(catalogue, 1) if row['id'] == 'cut')
        for width, height in ((1280, 860), (390, 844), (844, 390)):
            with self.subTest(viewport=(width, height)):
                self.open('easy-cut', width, height, phone=width != 1280)
                self.js("localStorage.setItem('banjo-object-snap','off')")
                self.open('easy-cut', width, height, phone=width != 1280)
                self.press('Add a knife'); self.ghost()
                self.assertTrue(self.js('machineWorkingGuide().objects_enabled'))
                self.assertEqual(self.js("document.getElementById('object-snap').getAttribute('aria-pressed')"), 'true')
                self.click_visible('Snap to objects')
                self.assertFalse(self.js('machineWorkingGuide().objects_enabled'))
                self.press('Cancel'); self.press('Add a knife'); self.ghost()
                self.assertFalse(self.js('machineWorkingGuide().objects_enabled'), 'Off remains available in this setup')
                self.press('Cancel')
                point = self.js("(()=>{const r=document.getElementById('levels-open').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];})()")
                self.mouse('mousePressed', *point); self.mouse('mouseReleased', *point)
                self.wait("!document.getElementById('levels-screen').hidden", 10)
                self.press(f'Play level {rank}, Cut it down'); self.wait(READY)
                self.press('Add a knife'); self.ghost()
                self.assertTrue(self.js('machineWorkingGuide().objects_enabled'), 'Opening another level restores the default')
                self.press('Cancel'); self.open('free', width, height, phone=width != 1280)
                self.press('Add a knife'); self.ghost()
                self.assertTrue(self.js('machineWorkingGuide().objects_enabled'), 'Sandbox also starts with snapping on')

    def test_knife_drag_captures_cord_and_colors_its_working_guide_on_all_screens(self):
        for width, height in ((1280, 860), (390, 844), (844, 390)):
            with self.subTest(viewport=(width, height)):
                self.open('easy-cut', width, height, phone=width != 1280)
                self.press('Add a knife'); self.ghost()
                if not self.js('machineWorkingGuide().objects_enabled'):
                    self.click_visible('Snap to objects')
                if self.js('machinePlacementGrid().enabled'):
                    self.click_visible('Snap to grid')
                self.slide('Position along (m) of your knife 1', -.08)
                self.slide('Position across (m) of your knife 1', .29)
                self.ghost()
                self.assertFalse(self.js("machineWorkingGuide().match.axes.includes('x')"))
                self.drag_ghost_to(-.08, .275, touch=width != 1280)
                self.wait("machineWorkingGuide().joined?.includes('cutting plane') && machineWorkingGuide().match.axes.includes('x')", 20)
                snapped = self.ghost()['p']
                self.assertAlmostEqual(snapped['z_m'], .235, delta=.006)
                self.assertAlmostEqual(snapped['x_m'], -.08, delta=.011)
                self.assertTrue(self.js("document.getElementById('grid-snap-status').classList.contains('aligned')"))
                self.drag_ghost_to(-.08, .4, touch=width != 1280)
                self.wait("!machineWorkingGuide().joined && !machineWorkingGuide().match.axes.includes('x')", 20)
                self.assertGreater(self.ghost()['p']['z_m'], .35)
                self.drag_ghost_to(-.08, .275, touch=width != 1280)
                self.wait("machineWorkingGuide().match.axes.includes('x')", 20)
                self.press('Try It!')
                self.wait("!document.getElementById('level-done').hidden", 20)
                self.assertIn('Goal at', self.js("document.getElementById('verdict').textContent"), 'the snapped build still needs and completes a native cut')

    def test_new_oversized_piece_fits_before_placement_without_overriding_later_camera_edits(self):
        for width, height in ((1280, 860), (390, 844), (844, 390)):
            with self.subTest(viewport=(width, height)):
                self.open('easy-cut', width, height, phone=width != 1280)
                before = self.js('machineCamera()')
                self.press('Add a knife'); proposed = self.ghost()['p']
                self.wait('machineCamera().settled', 20)
                self.assertGreater(self.js('machineCamera().distance'), before['distance'])
                self.assertTrue(self.js("(()=>{const b=machineGhostScreen(),r=document.querySelector('#view canvas').getBoundingClientRect();return b&&b.x0>=r.left+10&&b.x1<=r.right-10&&b.y0>=r.top+10&&b.y1<=r.bottom-10;})()"), 'The entire default knife fits while it is still being placed')
                self.assertEqual(len(self.js('machinePlacements()')), 0)
                camera = self.js('machineCamera()')
                self.assertEqual((camera['azimuth'], camera['elevation']), (before['azimuth'], before['elevation']))
                self.click_visible('Zoom in')
                closer = self.js('machineCamera()')
                self.slide('Position along (m) of your knife 1', proposed['x_m'] + .02)
                self.ghost()
                self.assertEqual(self.js('machineCamera().distance'), closer['distance'], 'Later edits respect the player zoom')
                self.press('Cancel')
                self.open('gap', width, height, phone=width != 1280)
                before = self.js('machineCamera()')
                self.press('Add a plank'); self.ghost()
                self.assertGreaterEqual(self.js('machineCamera().distance'), before['distance'], 'Adding a piece never zooms in; phones also fit the prepared apparatus')
                self.assertEqual((self.js('machineCamera().azimuth'),self.js('machineCamera().elevation')),(before['azimuth'],before['elevation']))

    def test_piece_modes_follow_selection_and_escape_keeps_placement(self):
        for width,height in ((1280,860),(390,844),(844,390),(320,568)):
            with self.subTest(viewport=(width,height)):
                self.open('cut',width,height,phone=width!=1280)
                self.press('Add a knife');p0=self.ghost()['p']
                self.assertTrue(self.js("document.getElementById('scene-mode').hidden"))
                self.click_visible('Move selected piece')
                self.key('Escape')
                self.assertIn('looking',self.js("document.getElementById('view').className"))
                self.assertEqual(self.ghost()['p'],p0)
                self.click_visible('Move selected piece')
                self.assertNotIn('looking',self.js("document.getElementById('view').className"))
                self.assertEqual(self.ghost()['p'],p0)
                self.press('Cancel')
                self.assertTrue(self.js("document.getElementById('piece-editor').hidden"))

    def test_marble_object_snap_and_working_guides_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('free',width,height,phone=width!=1280)
                self.js('window.confirm=()=>true');self.press('Clear the table');self.wait(READY,60)
                self.press('Add a track');self.ghost()
                for label,value in [('top end x',0),('across (z, m)',0),('top end height',.6),('length',.6),('drop',.1)]:
                    self.slide(label+' of your track 1',value)
                self.ghost();self.press('Set it down');self.wait(READY,60)
                self.press('Add a marble');self.ghost()
                if not self.js('machineWorkingGuide().objects_enabled'):self.click_visible('Snap to objects')
                self.slide('x of your marble 2',.3);self.slide('across (z, m) of your marble 2',.16);self.ghost()
                self.js('machineView({azimuth:0,elevation:1.1,distance:2.5,at:[.3,.4,0]})');self.wait('machineCamera().settled',20)
                snapped=self.drag_ghost_to(.3,.045,touch=width!=1280)['p']
                self.assertAlmostEqual(snapped['z_m'],0,delta=.006)
                self.assertIn('your track 1',self.js('machineWorkingGuide().joined'))
                self.wait("machineWorkingGuide().match.axes.length>0",5)
                self.assertTrue(self.js("document.getElementById('grid-snap-status').textContent.includes('Snapped')"))
                released=self.drag_ghost_to(.3,.17,touch=width!=1280)['p']
                self.assertGreater(released['z_m'],.15);self.assertIsNone(self.js('machineWorkingGuide().joined'))
                self.click_visible('Snap to objects')
                before=self.ghost()['p'];self.assertEqual(before,released,'toggle does not move the ball')
                free=self.drag_ghost_to(.3,.045,touch=width!=1280)['p']
                self.assertGreater(free['z_m'],.03,'disabled object snapping leaves grid-only placement')
                self.click_visible('Snap to objects')
                self.drag_ghost_to(.31,.02,touch=width!=1280)
                self.press('Set it down');self.wait(READY,60)
                self.click_visible('Try It!')
                self.wait("machineBodies()['your marble 2'][0]>.5",30)
                self.assertGreater(self.js("machineBodies()['your marble 2'][0]"),.5,'native gravity/contact moves the snapped ball along the track')
                self.click_visible('Pause')
                self.open('easy-mirror',width,height,phone=width!=1280);self.press('Add a mirror');self.ghost()
                self.assertEqual(self.js('machineWorkingGuide().primary.label'),'mirror center')
                self.slide('Mirror angle of your mirror 1',30);self.ghost()
                direction=self.js('machineWorkingGuide().primary.dir')
                self.assertAlmostEqual(abs(direction[0]),3**.5/2,places=5)
                self.assertAlmostEqual(abs(direction[2]),.5,places=5)
                self.reveal_control("document.getElementById('object-snap')")
                self.assertTrue(self.js("(()=>{const b=document.getElementById('object-snap'),r=b.getBoundingClientRect();return r.height>=44&&r.right<=innerWidth;})()"))
                self.press('Cancel')

        # Prepared marbles in examples use the same scene assistance, while
        # their exact base declaration and Undo history remain authoritative.
        draft=dict(name='Prepared lane snapping',placements=[],base={'schema':'banjo.machine.v1','cell_m':.02,'parts':[
            {'name':'board','shape':'box','material':'oak','size_m':[.6,.02,.12],'at_m':[0,.3,0],'fixed':True},
            {'name':'ball','shape':'sphere','material':'glass','size_m':[.04]*3,'at_m':[.1,.34,.045],'fixed':False}]})
        packed=base64.urlsafe_b64encode(json.dumps(draft).encode()).decode().rstrip('=')
        self.navigate(self.base+'/machine#build=j'+packed);self.wait(READY,60)
        index=self.js("machineEditableObjects().find(o=>o.name==='ball').index")
        self.click_piece(index);self.ghost()
        self.js('machineView({azimuth:0,elevation:1.1,distance:1.5,at:[0,.3,0]})');self.wait('machineCamera().settled',20)
        self.drag_ghost_to(.1,.035,touch=True)
        self.assertIn('board',self.js('machineWorkingGuide().joined'))
        self.click_visible('Set it down');self.wait(READY,60)
        self.assertAlmostEqual(self.js("machineDesign().draft.base.parts.find(p=>p.name==='ball').at_m[2]"),0,delta=.006)
        self.click_visible('Undo');self.wait(READY,60)
        self.assertAlmostEqual(self.js("machineDesign().draft.base.parts.find(p=>p.name==='ball').at_m[2]"),.045,places=5)

    def test_fine_ground_grid_gently_snaps_dragging_but_precision_stays_free(self):
        for width,height in ((1280,860),(390,844),(844,390),(320,568)):
            with self.subTest(viewport=(width,height)):
                self.open('cut',width,height,phone=width!=1280)
                self.press('Add a knife'); self.ghost()
                if not self.js('window.machinePlacementGrid().enabled'):
                    self.click_visible('Snap to grid')
                if self.js("document.getElementById('recent-changes').open"):self.click_visible('Close')
                # Keep the grabbed knife in view before testing tiny moves;
                # an off-screen press is not a piece drag on a narrow phone.
                self.slide('Pivot x of your knife 1',.1)
                self.slide('Pivot z of your knife 1',.1)
                self.ghost()
                # Keep the floor grab clear of the new touch zoom corner.
                # Touch browsers otherwise retarget a near-edge finger to
                # the slider even when elementFromPoint reports canvas.
                self.js('window.machineView({azimuth:0,elevation:1.1,distance:4,at:[.2,.2,.2]})')
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
                if self.js("document.getElementById('recent-changes').open"):self.click_visible('Close')
                self.assertEqual(self.ghost()['p'],released,'turning snapping off cannot reposition the piece')
                free=self.drag_ghost_to(.407,.307,touch=width!=1280)['p']
                self.assertAlmostEqual(free['x_m'],.41,delta=1e-6)
                self.assertAlmostEqual(free['z_m'],.305,delta=1e-6)
                self.assertFalse(self.js('window.machinePlacementGrid().enabled'))
                self.click_visible('Snap to grid')
                if self.js("document.getElementById('recent-changes').open"):self.click_visible('Close')
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
                if self.js("document.getElementById('recent-changes').open"):self.click_visible('Close')
                self.press('Set it down');self.wait(READY,60)
                self.assertEqual(self.js('window.machinePlacements()[0]'),precise)
                self.press('Pick up your knife 1')
                self.assertEqual(self.ghost()['p'],precise,'picking up an existing piece must not quantize its position')
                self.press('Cancel')
                self.page.send('Page.reload',{})
                self.wait(f"{READY} && typeof window.machinePlacementGrid==='function'",60)
                self.assertTrue(self.js('window.machinePlacementGrid().enabled'),'grid snapping starts on when a design reopens')

        # Saved sandbox declarations and version restores stay exact even
        # when grid assistance is enabled. Ordinary levels reset on reload.
        self.navigate(self.base+'/machine')
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

    def test_desktop_trackpad_pinch_zooms_the_scene_without_changing_the_page_or_design(self):
        self.open('free')
        self.press('Add a plank');before=self.ghost()['p']
        x,y=self.empty_scene_point()
        distance=self.js('window.machineCamera().distance')
        page=self.js('[innerWidth,innerHeight,visualViewport.scale,scrollX,scrollY]')
        # Chromium emits trackpad pinch as Ctrl+wheel, with small pixel deltas.
        for delta in [-3]*10:
            self.page.send('Input.dispatchMouseEvent',{'type':'mouseWheel','x':x,'y':y,
                           'deltaX':0,'deltaY':delta,'modifiers':2})
        self.wait(f'window.machineCamera().distance < {distance}*.8',5)
        self.assertEqual(self.js('[innerWidth,innerHeight,visualViewport.scale,scrollX,scrollY]'),page)
        self.assertEqual(self.ghost()['p'],before,'a pinch is a camera gesture, not a piece edit')
        for delta in [3]*10:
            self.page.send('Input.dispatchMouseEvent',{'type':'mouseWheel','x':x,'y':y,
                           'deltaX':0,'deltaY':delta,'modifiers':2})
        self.wait(f'Math.abs(window.machineCamera().distance-{distance})<1e-6',5)
        self.assertEqual(self.ghost()['p'],before)
        self.page.send('Input.dispatchMouseEvent',{'type':'mouseWheel','x':x,'y':y,'deltaX':0,'deltaY':-120})
        self.wait(f'window.machineCamera().distance < {distance}*.9',5)
        self.assertGreater(self.js('window.machineCamera().distance'),distance*.8,'ordinary wheel sensitivity is retained')
        # Firefox may report line/page wheel units instead of pixels. Check
        # those DOM event forms too, including the scene's safety bounds.
        for mode,delta in [(1,-2),(2,-.1),(0,-1e6),(0,1e6)]:
            prior=self.js('window.machineCamera().distance')
            cancelled=self.js(f"!document.querySelector('#view canvas').dispatchEvent(new WheelEvent('wheel',{{bubbles:true,cancelable:true,ctrlKey:true,deltaMode:{mode},deltaY:{delta}}}))")
            self.assertTrue(cancelled,'the scene consumes pinch rather than zooming the page')
            current=self.js('window.machineCamera().distance')
            if delta<0:self.assertLess(current,prior)
            else:self.assertGreater(current,prior)
            self.assertGreaterEqual(current,.4);self.assertLessEqual(current,40)
            self.assertEqual(self.ghost()['p'],before)
        self.assertEqual(self.js('[innerWidth,innerHeight,visualViewport.scale,scrollX,scrollY]'),page)
        # Scene sockets must not swallow a trackpad pinch or start a cable.
        # Ordinary wheel scrolling over controls remains available.
        self.open('sun');self.press('Add a solar panel');self.ghost()
        for label,value in [('x',1),('z',.4),('height',.6),('turn',-45),('tip',75)]:
            self.slide(f'{label} of your solar 1',value)
        self.ghost()
        self.press('Set it down');self.wait(f'!window.machineGhostState() && {READY}',60)
        self.click_visible('Connect wires')
        kept=self.js('window.machinePlacements()')
        x,y=self.js("(() => {const e=[...document.querySelectorAll('#power-pins button')].find(e=>e.getClientRects().length),r=e.getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2];})()")
        self.assertTrue(self.js(f"Boolean(document.elementFromPoint({x},{y}).closest('#power-pins button'))"))
        distance=self.js('window.machineCamera().distance')
        self.page.send('Input.dispatchMouseEvent',{'type':'mouseWheel','x':x,'y':y,'deltaX':0,'deltaY':-30,'modifiers':2})
        self.wait(f'window.machineCamera().distance < {distance}*.8',5)
        self.assertEqual(self.js('window.machinePlacements()'),kept)
        self.assertIsNone(self.js('window.machineGhostState()'),'pinching over a socket cannot start a wire')
        # Socket positions follow the camera. Aim at its current position,
        # rather than the canvas it occupied before zooming.
        x,y=self.js("(() => {const e=[...document.querySelectorAll('#power-pins button')].find(e=>e.getClientRects().length),r=e.getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2];})()")
        self.assertTrue(self.js(f"Boolean(document.elementFromPoint({x},{y}).closest('#power-pins button'))"))
        distance=self.js('window.machineCamera().distance')
        self.page.send('Input.dispatchMouseEvent',{'type':'mouseWheel','x':x,'y':y,'deltaX':0,'deltaY':-30})
        time.sleep(.1)
        self.assertEqual(self.js('window.machineCamera().distance'),distance)
        self.click_visible('Finish wiring')
        self.click_visible('Try It!')
        self.wait("!window.machineGhostState() && /calculating live/.test(document.getElementById('clock').textContent)",30)
        self.click_visible('Pause')

    def test_zoom_during_a_held_piece_drag_does_not_relocate_a_stationary_pointer(self):
        self.open('laser')
        self.press('Add a mirror');self.ghost()
        box=self.js('window.machineGhostScreen()')
        x,y=box['x1']+25,(box['y0']+box['y1'])/2
        self.mouse('mousePressed',x,y)
        self.page.send('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x+20,'y':y,'button':'left','buttons':1})
        before=self.ghost()['p'];distance=self.js('window.machineCamera().distance')
        self.page.send('Input.dispatchMouseEvent',{'type':'mouseWheel','x':x+20,'y':y,'deltaX':0,'deltaY':-30,'button':'left','buttons':1,'modifiers':2})
        self.wait(f'window.machineCamera().distance < {distance}',5)
        self.page.send('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x+20,'y':y,'button':'left','buttons':1})
        self.assertEqual(self.ghost()['p'],before,'zooming with the pointer held still cannot relocate the piece')
        self.page.send('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x+60,'y':y,'button':'left','buttons':1})
        self.mouse('mouseReleased',x+60,y)
        self.assertNotEqual(self.ghost()['p'],before,'an intentional pointer movement still works after zooming')

    def test_internal_force_test_is_unavailable_in_player_controls_and_earns_nothing(self):
        # Level 5 with no ramp: Pull on, the lever's end pulled down -- the
        # engine's force at that point, no hand in the world. The ratchet
        # catches, the contact closes, the cannon fires and the block goes in.
        # A run pulled by hand tests the parts; it is not a win, and nothing
        # of it is kept.
        self.open('chain')
        previous_record=self.js("machineSave().players[machineSave().current].levels.chain||null")
        self.js("window.machineView({azimuth: -0.2, elevation: 0.35, distance: 2.2, at: [0.4, 0.15, 0]})")
        time.sleep(1.5)
        x, y = self.screen_point([0.15, 0.16, 0.0])
        self.assertTrue(self.js("document.getElementById('pull-tool').hidden"))
        self.js("document.getElementById('pull-tool').click()")  # Internal diagnostic fixture, not a player action.
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
        self.assertEqual(self.js("machineSave().players[machineSave().current].levels.chain||null"),previous_record)

    def test_internal_force_fixture_releases_before_a_second_finger_turns_the_camera(self):
        self.open('chain')
        self.js("window.machineView({azimuth: -0.2, elevation: 0.35, distance: 2.2, at: [0.4, 0.15, 0]})")
        self.wait('window.machineCamera().settled',30)
        x,y=self.screen_point([0.15,0.16,0])
        self.assertTrue(self.js("document.getElementById('pull-tool').hidden"))
        self.js("document.getElementById('pull-tool').click()")  # Retain force-release coverage after retiring the menu control.
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
        self.assertTrue(self.js("document.querySelector('#piece-editor .down').disabled"))
        self.assertIn('120 mm into wall', self.js("document.querySelector('#ghost-bar .state').textContent"))
        self.press('Try It!')
        self.wait("/120 mm into wall/.test(document.getElementById('verdict').textContent)",5)
        self.assertFalse(self.ghost()['fits'])
        self.assertEqual(self.js('window.machinePlacements()'),[])
        self.assertTrue(self.js(READY))

    def test_on_a_phone_the_scene_comes_into_view_and_its_bar_turns_and_sets_the_ghost_down(self):
        self.open('gap', 390, 844, phone=True)
        # The panel's tray shows each piece, with a picture, and how many are left.
        self.wait("Boolean(document.querySelector('#tray img:not([hidden])'))", 30)
        self.assertEqual(self.js("document.querySelector('#tray li').textContent"), 'plank1 left')
        self.click_visible('Help')
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
        card = self.js("document.getElementById('piece-editor').getBoundingClientRect().toJSON()")
        scene = self.js("document.getElementById('view').getBoundingClientRect().toJSON()")
        self.assertGreaterEqual(card['top'],scene['top'],(card,scene))
        self.assertLessEqual(card['bottom'],scene['bottom'],(card,scene))
        self.assertLessEqual(card['bottom'], 844, 'the controls are on the screen with the scene')
        self.assertFalse(self.js("document.querySelector('[aria-label=\"Turn selected piece\"]').checkVisibility()"))
        self.press('✓ Set down');self.wait(READY,30)
        self.open('free',390,844,phone=True)
        self.press('Add a plank');self.ghost()
        self.press('Change its turn')
        self.slide('Its turn',15)
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
        x,y=self.js("(()=>{const b=machineGhostScreen(),y=(b.y0+b.y1)/2;return [[b.x1+25,y],[b.x0-25,y]].find(p=>document.elementFromPoint(...p)?.tagName==='CANVAS');})()")
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
        sx,sy=self.js("(()=>{const b=machineGhostScreen(),y=(b.y0+b.y1)/2;return [[b.x1+25,y],[b.x0-25,y]].find(p=>document.elementFromPoint(...p)?.tagName==='CANVAS');})()")
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
        sx,sy=self.js("(()=>{const r=document.getElementById('view').getBoundingClientRect();for(let y=r.top+60;y<r.bottom-100;y+=20)for(let x=r.left+16;x<r.right-150;x+=20)if(document.elementFromPoint(x,y)?.tagName==='CANVAS'&&document.elementFromPoint(x+120,y)?.tagName==='CANVAS')return [x,y];})()")
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
        self.assertTrue(self.js("document.getElementById('scene-tray').hidden"))
        self.press('Try It!')
        self.wait("/calculating live/.test(document.getElementById('clock').textContent)", 30)
        x, y = self.js("window.machineBodyScreen('your plank 1')")
        self.mouse('mousePressed', x, y)
        self.mouse('mouseReleased', x, y)
        g = self.ghost()
        self.assertEqual(g['index'], 0, 'the plank set down is a ghost again')
        self.wait(READY, 60)


    def test_new_motion_examples_and_airflow_controls_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('free',width,height,phone=width!=1280)
                self.js("document.getElementById('sandbox-open').click()")
                self.wait("Boolean(document.querySelector('#prebuilt-designs button'))",30)
                self.press('Start from Wind opens a door');self.wait(READY,30)
                self.assertEqual(len(self.js('machineAirflowState().fields')),1)
                self.assertEqual(self.js('machineAirflowState().arrows'),6)
                self.press('Add a pendulum');self.assertTrue(self.ghost()['fits']);self.press('Cancel')
                self.slide('Adjust a piece','1')
                self.ghost();self.slide('Air direction of your wind 2',0)
                self.assertTrue(self.ghost()['fits'])
                self.press('Set it down');self.wait(READY,30)
                self.assertAlmostEqual(self.js('machineAirflowState().fields[0].velocity_m_s[0]'),12)
                self.click_visible('Undo');self.wait(READY,30)
                self.assertAlmostEqual(self.js('machineAirflowState().fields[0].velocity_m_s[2]'),-12)
                before=self.js("machineBodies()['your door 1 leaf']")
                self.click_visible('Try It!')
                self.wait("machineAirflowState().loads.some(l=>l.work_j>0.01)",30)
                self.wait(f"Math.abs(machineBodies()['your door 1 leaf'][2]-{before[2]})>.1",30)
                self.click_visible('Pause')
                after=self.js("machineBodies()['your door 1 leaf']")
                self.assertGreater(abs(after[2]-before[2]),.01)
                self.click_visible('Reset');self.wait(READY,30)
                self.assertAlmostEqual(self.js("machineBodies()['your door 1 leaf'][2]"),before[2],places=3)
                self.press('Save version');self.wait('machineDesign().versions.length>0',10)
                self.navigate(self.js('location.href'));self.wait(READY,30)
                self.assertEqual(len(self.js('machineAirflowState().fields')),1)
                self.js("document.getElementById('sandbox-open').click()");self.press('Start from Spring trampoline');self.wait(READY,30)
                self.assertIn('your trampoline 1 deck',self.js('Object.keys(machineBodies())'))
                self.click_visible('Try It!')
                self.wait("machineBodies()['your marble 2'][1]<.8",30)
                self.click_visible('Pause')


    def test_simplified_level_editor_zoom_history_and_electrical_rating_on_all_screens(self):
        for width,height in ((1280,860),(390,844),(844,390),(320,568)):
            with self.subTest(viewport=(width,height)):
                self.open('gap',width,height,phone=width!=1280)
                self.assertIn('Mind the gap',self.js("document.getElementById('scene-goal').textContent"))
                self.assertTrue(self.js("document.querySelector('#scene-goal span').textContent.length>10"))
                self.assertFalse(self.js("Boolean(document.getElementById('phone-tools')||document.getElementById('piece-edit'))"))
                self.assertEqual(self.js("document.getElementById('instrument-panel').tagName"),'SECTION')
                for label in ['Zoom in','Zoom out']:
                    before=self.js('machineCamera().distance');self.click_visible(label)
                    after=self.js('machineCamera().distance')
                    self.assertTrue(after<before if label=='Zoom in' else after>before)
                self.press('Add a plank');self.ghost()
                self.assertEqual(self.js("document.querySelector('#ghost-bar .chips')"),None)
                self.assertEqual(self.js("document.querySelector('[aria-label=\"Adjustment\"]').value"),'length_m')
                self.slide('Its Cut to length',.66);self.assertEqual(self.ghost()['p']['length_m'],.66)
                placed=self.ghost()['p'];self.slide('Scene zoom',80)
                self.assertEqual(self.ghost()['p'],placed)
                self.assertTrue(self.js("document.querySelector('[aria-label=\"Its Cut to length\"]').getAttribute('list').startsWith('slider-ticks-')"))
                self.press('Set it down');self.wait(READY,30)
                self.click_visible('Undo');self.wait(f'machinePlacements().length===0&&{READY}',30)
                self.click_visible('Redo');self.wait(f'machinePlacements().length===1&&{READY}',30)
                self.click_piece(0);self.assertEqual(self.ghost()['index'],0)
                self.press('Delete selected piece');self.wait(f'machinePlacements().length===0&&{READY}',30)
                self.open('easy-power',width,height,phone=width!=1280)
                self.press('Add a battery');self.ghost()
                self.slide('Its voltage',12)
                self.ghost();self.slide('Its voltage',6)
                self.ghost();self.assertIn('6 V',self.js("document.getElementById('adjustment-feedback').textContent"))
                self.wait("machinePowerFeedbackState().labels.some(l=>l.text.includes('Proposed 6 V'))",10)
                self.press('Cancel')

    def test_crowded_scene_keeps_placed_wire_gauge_editing_available_in_controls(self):
        self.open('easy-power',844,390,phone=True)
        self.press('Add a battery');self.ghost();self.slide('Its voltage',12)
        self.press('Set it down');self.wait(READY,30)
        self.click_scene_socket('your battery 1:plus',touch=True);self.ghost()
        self.click_scene_socket('lamp:plus',touch=True);self.wait(READY,30)
        self.wait("document.querySelector('#wire-adjustments button')?.textContent.includes('0.01 mm²')",30)
        self.click_visible('Adjust placed Wire 2 · Thin · 0.01 mm²');self.ghost()
        self.assertEqual(self.ghost()['index'],1)
        self.click_visible('Thick wire')
        self.ghost()
        self.press('Set it down');self.wait(READY,30)
        self.wait("document.querySelector('#wire-adjustments button')?.textContent.includes('2.5 mm²')",30)

    def test_connected_wire_length_handles_edit_declared_copper_length_in_sandbox(self):
        self.open('free',844,390,phone=True)
        self.js('window.confirm=()=>true');self.press('Clear the table');self.wait(READY,30)
        for label,x in [('battery',-.5),('bulb',.6)]:
            self.press('Add a '+label);self.ghost();self.drag_ghost_to(x,0,touch=True);self.ghost()
            self.press('Place');self.wait(READY,30)
        self.click_scene_socket('your battery 1:plus',touch=True);self.ghost()
        self.click_scene_socket('your bulb 2:plus',touch=True);self.wait(READY,30)
        self.wait("Boolean(document.querySelector('#wire-adjustments button'))",10)
        label=self.js("document.querySelector('#wire-adjustments button').getAttribute('aria-label')")
        self.click_visible(label);self.ghost();self.click_visible('Thick wire');self.ghost()
        self.slide('Adjustment','length_m');before=self.ghost()['p']['length_m']
        self.wait("Boolean(document.querySelector('#piece-handles button:not([hidden])'))",10)
        self.click_visible('Increase stock length including slack on object')
        self.assertAlmostEqual(self.ghost()['p']['length_m'],before+.1)
        self.assertFalse(self.js("Boolean(document.querySelector('#piece-editor #piece-grip'))"))
        self.press('Place');self.wait(READY,30)
        self.assertAlmostEqual(self.js('machinePlacements()[2].length_m'),before+.1)

    def test_loose_board_is_individually_selectable_repositionable_and_saved(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.anonymous_levels(width=width,height=height);self.press('Sandbox: build anything')
                self.wait("Boolean(document.querySelector('#prebuilt-designs button'))",60)
                self.press('Start from Support a loose board');self.wait(READY,60)
                original=self.js('machineDesign().draft.base')
                index=self.js("machineEditableObjects().find(o=>o.name==='loose board').index")
                self.click_piece(index);self.ghost()
                self.assertEqual(self.ghost()['p']['object'],'part:loose board')
                self.assertIn('Adjust loose board',self.js("document.querySelector('#ghost-bar .head').textContent"))
                self.slide('along X (m) of loose board',1)
                self.ghost();self.click_visible('Set it down');self.wait(READY,60)
                self.assertEqual(self.js("machineDesign().draft.base.parts.find(p=>p.name==='loose board').at_m[0]"),1)
                self.click_visible('Undo');self.wait(READY,60)
                self.assertEqual(self.js('machineDesign().draft.base'),original)
                self.click_visible('Redo');self.wait(READY,60)
                self.press('Save version');self.anonymous_cloud_saved()
                draft=self.js('machineDesign().draft');url=self.js('location.href')
                self.navigate(url);self.wait(READY,60)
                self.assertEqual(self.js('machineDesign().draft'),draft)
                self.click_visible('Try It!');self.wait("machineBodies()['loose board'][1]<.1",30)
                self.click_visible('Pause')


    def test_plain_help_has_only_question_response_and_a_quiet_bug_report(self):
        for width,height in ((1280,860),(390,844),(844,390),(320,568)):
            with self.subTest(viewport=(width,height)):
                self.open('gap',width,height,phone=width<1000)
                self.click_visible('Help')
                self.assertFalse(self.js("document.getElementById('coach-open').checkVisibility()"))
                self.assertFalse(self.js("document.getElementById('solve').checkVisibility()"))
                self.assertFalse(self.js("document.getElementById('phone-help-panel').contains(document.getElementById('help-settings'))"))
                before=self.js('machinePlacements()')
                seen=[]
                def call(api_key,model,messages,**kwargs):
                    seen.append(messages);return {'reply':'Make the board longer to bridge the gap.'},{}
                with patch('machine_chat.configuration',return_value=('fixture-key','fixture-model')),patch('machine_chat._call',side_effect=call):
                    self.slide('Your question','Why does the marble fall short?')
                    self.click_visible('Ask for a hint')
                    self.wait("document.querySelector('#chat-log .model')?.textContent.includes('Make the board longer')",10)
                self.assertEqual(len(seen),1)
                self.assertEqual(self.js('machinePlacements()'),before)
                self.assertTrue(self.js("document.getElementById('coach-overlay').hasAttribute('hidden')"))
                self.click_summary('#feedback > summary')
                self.assertTrue(self.js("document.getElementById('feedback-form').checkVisibility()"))

    def test_failed_attempt_llm_help_is_dismissible_and_preserves_retry_and_question(self):
        for width,height in ((1280,860),(390,844),(844,390),(320,568)):
            with self.subTest(viewport=(width,height)):
                self.open('gap',width,height,phone=width<1000)
                self.press('Add a plank');self.ghost()
                self.slide('Its Cut to length',.2);self.ghost()
                self.js("document.getElementById('message').value='Keep my question'")
                seen=[]
                def call(api_key,model,messages,**kwargs):
                    seen.append(messages)
                    return {'reply':'Your board ends before the gap. Increase its length, then try again.','placements':[]},{}
                with patch('machine_chat.configuration',return_value=('fixture-key','fixture-model')),patch('machine_chat._call',side_effect=call):
                    self.click_visible('Try It!');self.wait("!document.getElementById('level-done').hidden",30)
                    kept=self.js('machinePlacements()')
                    self.assertEqual(seen,[],'A failed attempt must not call the model automatically')
                    self.click_visible('Ask for Help')
                    self.wait("document.getElementById('run-help').open&&document.getElementById('run-help-reply').textContent.includes('Your board ends')",10)
                self.assertEqual(len(seen),1)
                context=json.loads(seen[0][-1]['content'])
                self.assertEqual(context['placements'],kept)
                self.assertIsNone(context['last_run']['goal_at_s'])
                self.assertGreater(context['last_run']['world_t'],0)
                self.assertFalse(context['last_run']['measurements']['stations'][0]['done'])
                self.assertEqual(self.js('machinePlacements()'),kept)
                self.click_visible('Dismiss')
                self.assertFalse(self.js("document.getElementById('run-help').open"))
                self.assertEqual(self.js("document.getElementById('message').value"),'Keep my question')
                self.click_visible('Try again');selected=self.ghost()
                self.assertEqual(selected['index'],0);self.assertEqual(selected['p']['length_m'],.2)
                self.assertEqual(self.js('machinePlacements()'),kept)
                self.click_visible('Help')
                self.assertIn('Your board ends',self.js("document.getElementById('chat-log').textContent"))

    def test_failed_attempt_help_reports_unavailable_model_without_losing_the_setup(self):
        self.open('gap');self.press('Add a plank');self.ghost()
        self.slide('Its Cut to length',.2);self.ghost();self.click_visible('Try It!')
        self.wait("!document.getElementById('level-done').hidden",30)
        kept=self.js('machinePlacements()')
        with patch('machine_chat.configuration',return_value=(None,'fixture-model')):
            self.click_visible('Ask for Help')
            self.wait("/No model/.test(document.getElementById('run-help-reply').textContent)",10)
        self.click_visible('Dismiss')
        self.assertEqual(self.js('machinePlacements()'),kept)
        self.click_visible('Try again');self.assertEqual(self.ghost()['p']['length_m'],.2)

    def test_scene_and_bottom_dock_share_one_layout_on_desktop_and_phones(self):
        for width,height in ((1440,900),(1280,720),(390,844),(844,390),(320,568)):
            with self.subTest(viewport=(width,height)):
                self.open('gap',width,height,phone=width<1000)
                layout=self.js("""(() => {const box=id=>{const r=document.querySelector(id).getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,b:r.bottom};};return {view:box('#view'),dock:box('main>aside'),run:box('#start'),goal:box('#scene-goal'),overflow:document.documentElement.scrollWidth>innerWidth};})()""")
                self.assertAlmostEqual(layout['view']['w'],width,delta=2)
                self.assertAlmostEqual(layout['dock']['w'],width,delta=2)
                self.assertGreaterEqual(layout['dock']['y'],layout['view']['b']-1)
                self.assertGreaterEqual(layout['view']['h'],140)
                self.assertGreaterEqual(layout['run']['h'],44)
                self.assertLessEqual(layout['run']['b'],height)
                self.assertLessEqual(layout['goal']['b'],height)
                self.assertFalse(layout['overflow'])
                self.assertEqual(self.js("document.getElementById('start').textContent"),'Try It!')
                self.assertTrue(self.js("(()=>{const r=id=>document.getElementById(id).getBoundingClientRect();return Math.abs((r('start').left+r('start').right)/2-innerWidth/2)<2&&r('start').width>=160&&r('phone-tabs').width<230;})()"))
                self.click_visible('Help')
                self.assertTrue(self.js("document.getElementById('phone-help-panel').checkVisibility()&&!document.getElementById('control-panel').checkVisibility()"))
                self.assertIsNone(self.js("document.getElementById('panel-toggle')"))
                self.assertTrue(self.js("document.getElementById('phone-help-panel').checkVisibility()"))
                self.assertTrue(self.js("document.getElementById('start').checkVisibility()"))
                self.click_visible('Controls')
                self.press('Add a plank');self.ghost()
                self.assertTrue(self.js("(()=>{const b=document.getElementById('piece-grip'),r=b.getBoundingClientRect(),p=document.getElementById('view').getBoundingClientRect();return b.checkVisibility()&&r.top>=p.top&&r.bottom<=p.bottom&&r.height>=44;})()"))
                self.click_visible('Place');self.wait(READY,30)
                self.click_visible('Try It!');self.wait("!document.getElementById('level-done').hidden",20)
                self.click_visible('Try again');self.assertEqual(self.ghost()['index'],0)

    def test_piece_toolbar_direct_adjustment_and_camera_buttons_on_desktop_and_phones(self):
        for width,height in ((1280,860),(390,844),(844,390),(320,568)):
            with self.subTest(viewport=(width,height)):
                self.open('gap',width,height,phone=width!=1280)
                self.press('Add a plank');before=self.ghost()['p']
                self.assertTrue(self.js("document.getElementById('help-settings').closest('#recent-changes')!==null"))
                self.assertFalse(self.js("document.getElementById('help-settings').open"))
                self.assertTrue(self.js("document.getElementById('restart-pieces').hidden&&document.getElementById('view-overview').hidden&&document.getElementById('scene-mode').hidden"))
                self.assertEqual(self.js("document.querySelector('#level-details summary')"),None)
                self.assertFalse(self.js("[...document.querySelectorAll('#control-panel input[type=range]')].some(e=>e.checkVisibility())"))
                self.wait("(()=>{const b=machineGhostScreen(),r=document.getElementById('piece-editor').getBoundingClientRect();return r.right<=b.x0||r.left>=b.x1||r.bottom<=b.y0||r.top>=b.y1;})()",10)
                self.click_visible('Move selected piece')
                point=self.js("(()=>{const b=machineGhostScreen();return [(b.x0+b.x1)/2,(b.y0+b.y1)/2];})()")
                if self.js(f"document.elementFromPoint({point[0]},{point[1]})?.tagName==='CANVAS'"):
                    self.drag(point,[point[0]+20,point[1]],touch=width!=1280)
                    self.assertNotEqual(self.ghost()['p']['x_m'],before['x_m'])
                handle=self.js("(()=>{const b=document.getElementById('piece-grip'),r=b.getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2,Number(b.dataset.dx),Number(b.dataset.dy)];})()")
                self.drag(handle[:2],[handle[0]+24*handle[2],handle[1]+24*handle[3]],touch=width!=1280)
                edited=self.ghost()['p'];self.assertGreater(edited['length_m'],before['length_m'])
                # Mind the gap teaches length with a prepared orientation;
                # the October 14 lesson whitelist intentionally hides Turn.
                self.assertFalse(self.js("document.querySelector('[aria-label=\"Turn selected piece\"]').checkVisibility()"))
                turned=self.ghost()['p']
                before_camera=self.js('machineCamera()')
                self.click_visible('Turn the view left');self.click_visible('Look from above')
                self.assertLess(self.js('machineCamera().azimuth'),before_camera['azimuth'])
                self.assertGreater(self.js('machineCamera().elevation'),before_camera['elevation'])
                self.assertEqual(self.ghost()['p'],turned)
                self.click_visible('Place');self.wait(READY,30)
                self.assertTrue(self.js("document.getElementById('scene-tray').hidden"))
                self.click_piece(0);self.assertEqual(self.ghost()['p'],turned)
                proof=ROOT/'build'/'ui-proof';proof.mkdir(parents=True,exist_ok=True)
                (proof/f'piece-toolbar-{width}x{height}.png').write_bytes(base64.b64decode(self.page.send('Page.captureScreenshot',{'format':'png'})['data']))

    def test_phone_piece_callouts_leave_the_seesaw_and_placement_guides_clear(self):
        for width,height in ((1280,860),(1920,1080),(390,844),(320,568),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-weight',width,height,phone=True)
                self.click_visible('Add a weight');self.ghost()
                check="""(()=>{const view=document.getElementById('view').getBoundingClientRect(),
                    card=document.getElementById('piece-editor').getBoundingClientRect(),
                    line=document.querySelector('#object-control-leaders [data-for="piece-editor"]'),
                    piece=machineGhostScreen(),target=machineBodyScreen('lever');
                    return {edge:Math.abs(card.left-view.left-6)<1||Math.abs(view.right-card.right-6)<1,
                        inside:card.top>=view.top&&card.bottom<=view.bottom,
                        selectedClear:card.right<=piece.x0||card.left>=piece.x1||card.bottom<=piece.y0||card.top>=piece.y1,
                        targetClear:document.elementFromPoint(...target)?.tagName==='CANVAS',
                        leader:line?.style.display!== 'none',
                        from:[Number(line?.getAttribute('x1')),Number(line?.getAttribute('y1'))]};})()"""
                self.wait(f'({check}).edge&&({check}).inside&&({check}).selectedClear&&({check}).targetClear',10)
                first=self.js(check);self.assertTrue(first['leader'])
                self.click_visible('Turn the view left');self.wait('machineCamera().settled',10)
                changed=self.js(check);self.assertTrue(changed['edge']);self.assertTrue(changed['leader'])
                self.wait("(()=>{const p=machineGhostScreen(),v=document.getElementById('view').getBoundingClientRect(),l=document.querySelector('#object-control-leaders [data-for=\"piece-editor\"]');return Math.abs(Number(l.getAttribute('x1'))-((p.x0+p.x1)/2-v.left))<1&&Math.abs(Number(l.getAttribute('y1'))-((p.y0+p.y1)/2-v.top))<1;})()",10)
                self.click_visible('Place');self.wait(READY,30)
                self.wait("document.querySelector('#object-control-leaders [data-for=\"piece-editor\"]').style.display==='none'",5)

    def test_failed_run_has_one_retry_and_restores_last_selected_piece(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('gap',width,height,phone=width!=1280)
                self.press('Add a plank');self.ghost()
                self.slide('Its Cut to length',.2);self.ghost()
                self.click_visible('Try It!')
                self.wait("!document.getElementById('level-done').hidden",35)
                self.assertEqual(self.js("[...document.querySelectorAll('#level-done button')].map(b=>b.textContent)"),['Try again','Ask for Help'])
                self.wait("document.getElementById('start').hidden&&/run over/.test(document.getElementById('clock').textContent)",5)
                kept=self.js('machinePlacements()')
                self.click_visible('Try again');selected=self.ghost()
                self.assertEqual(selected['index'],0)
                self.assertEqual(selected['p']['length_m'],.2)
                self.assertEqual(self.js('machinePlacements()'),kept)
                self.assertRegex(self.js("document.getElementById('clock').textContent"),r'World 0\.00 s')

        # Re-edit the first of three pieces: retry must not select the last
        # item in the placement list, or discard the two drawn connections.
        self.open('easy-power')
        self.press('Add a battery');self.ghost();self.press('Place');self.wait(READY,30)
        for count,(a,b) in enumerate([('your battery 1:plus','lamp:plus'),('your battery 1:minus','lamp:minus')],2):
            self.click_scene_socket(a);self.ghost();self.click_scene_socket(b)
            self.wait(f'machinePlacements().length==={count}&&!machineGhostState()&&{READY}',30)
        self.click_piece(0);self.slide('Its voltage',12);self.assertEqual(self.ghost()['p']['voltage_v'],12)
        self.press('Place');self.wait(READY,30)
        kept=self.js('machinePlacements()');self.assertEqual(len(kept),3)
        self.click_visible('Try It!');self.wait("!document.getElementById('level-done').hidden",20)
        self.click_visible('Try again');edited=self.ghost()
        self.assertEqual(edited['index'],0);self.assertEqual(edited['p']['voltage_v'],12)
        self.assertEqual(self.js('machinePlacements()'),kept)

    def test_chapter_catalogue_and_snap_defaults_are_visible_without_filters(self):
        self.open('gap')
        self.click_visible('Help');self.click_summary('#help-settings > summary')
        self.click_visible('Snap to grid');self.click_visible('Snap to objects')
        self.open('gap')
        for key in ['grid-snap','object-snap']:
            self.assertEqual(self.js(f"document.getElementById('{key}').getAttribute('aria-pressed')"),'true')
        self.js("document.getElementById('levels-open').click()")
        self.wait("!document.getElementById('levels-screen').hidden",10)
        self.assertEqual(self.js("[...document.querySelectorAll('.level-chapter h2')].map(x=>x.textContent)"),
                         ['Level 1: Mechanics','Level 2: Electricity','Level 3: Water','Level 4: Heat and chain reactions'])
        self.assertEqual(self.js("document.querySelectorAll('.level-card').length"),34)
        self.assertEqual(self.js("document.querySelectorAll('.level-card-details').length"),0)
        self.assertEqual(self.js("document.querySelectorAll('#levels-screen select').length"),0)

    def test_lens_curvature_and_receiver_opening_are_direct_scene_edits(self):
        for width,height in ((1280,720),(390,844),(844,390),(320,568)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-lens',width,height,phone=width<1000)
                self.click_visible('Add a lens');self.ghost()
                self.slide('Adjustment','radius_m');before=self.ghost()['p']['radius_m']
                self.wait("machineLaserPreviewState().visible&&!machineLaserPreviewState().pending",30)
                stamp=self.js('machineLaserPreviewState().stamp')
                self.wait("Boolean(document.querySelector('#piece-handles button:not([hidden])'))",10)
                handle=self.js("(()=>{const b=document.querySelector('#piece-handles button:not([hidden])'),r=b.getBoundingClientRect();return {x:r.x+22,y:r.y+22,dx:Number(b.dataset.dx),dy:Number(b.dataset.dy),hit:b.contains(document.elementFromPoint(r.x+22,r.y+22))};})()")
                self.assertTrue(handle['hit'])
                self.drag([handle['x'],handle['y']],[handle['x']+handle['dx']*36,handle['y']+handle['dy']*36],touch=width<1000)
                self.assertGreater(self.ghost()['p']['radius_m'],before)
                self.wait(f"!machineLaserPreviewState().pending&&machineLaserPreviewState().stamp!=={json.dumps(stamp)}",30)
                self.assertEqual(self.js('JSON.parse(machineLaserPreviewState().stamp).placements[0].radius_m'),self.ghost()['p']['radius_m'])
                self.assertNotIn('shape',self.js("[...document.getElementById('adjustment-choice').options].map(o=>o.value)"))
                self.assertEqual(self.ghost()['p']['shape'],'convex','The focusing lesson keeps its prepared lens shape')
                self.assertFalse(self.js("Boolean(document.querySelector('#piece-editor select:not(#adjustment-choice)'))"))
                self.open('easy-water-receiver',width,height,phone=width<1000)
                self.click_visible('Add a water tank');self.ghost()
                self.assertEqual(self.js("document.getElementById('adjustment-choice').value"),'opening_percent')
                self.assertEqual(self.js("document.getElementById('piece-grip').closest('#view').id"),'view')
                for _ in range(5):
                    point=self.js("(()=>{const b=document.getElementById('piece-grip'),r=b.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2,Number(b.dataset.dx),Number(b.dataset.dy)];})()")
                    self.assertTrue(self.js(f"document.elementFromPoint({point[0]},{point[1]}).id==='piece-grip'"))
                    self.drag(point[:2],[point[0]+48*point[2],point[1]+48*point[3]],touch=width<1000);self.ghost()
                self.assertEqual(self.ghost()['p']['opening_percent'],100)
                self.click_visible('Place');self.wait(READY,30)
                self.wait("Boolean(document.querySelector('#device-live-controls input'))",10)
                self.assertTrue(self.js("(()=>{const c=document.querySelector('.device-live-card'),r=c.getBoundingClientRect(),v=document.getElementById('view').getBoundingClientRect();return !c.hidden&&r.left>=v.left&&r.right<=v.right&&r.top>=v.top&&r.bottom<=v.bottom;})()"))
                self.click_visible('Try It!');self.wait("document.body.classList.contains('scene-win')",25)
                self.assertTrue(self.js("(()=>{const c=document.getElementById('level-done'),r=c.getBoundingClientRect(),v=document.getElementById('view').getBoundingClientRect();return c.parentElement.id==='view'&&r.left>=v.left&&r.right<=v.right&&r.top>=v.top&&r.bottom<=v.bottom;})()"))
                self.assertTrue(self.js("(()=>{const c=document.getElementById('level-done').getBoundingClientRect(),v=document.getElementById('view').getBoundingClientRect();return c.top-v.top<=56&&c.top-v.top>=48;})()"))
                self.assertIn('Level Complete!',self.js("document.getElementById('level-done').textContent"))
                self.click_visible('Close level complete')
                self.assertFalse(self.js("document.body.classList.contains('scene-win')"))
                self.click_visible('Controls')


    def test_lesson_control_audit_excludes_sandbox_settings_even_in_precision_controls(self):
        import machine_game as game
        levels=game.load_levels()
        for width,height in ((1280,860),(390,844),(844,390)):
            selected=levels if width==1280 else [l for l in levels if l['id'] in
                ('easy-spring','easy-gears','easy-lens','advanced-capacitor','easy-water-wheel','easy-switch')]
            for level in selected:
                self.open(level['id'],width,height,phone=width!=1280)
                for tray in level['tray']:
                    if tray.get('attach') or tray['piece'] in ('wire','power_cable'):continue # Actual sockets have separate wiring regressions.
                    with self.subTest(level=level['id'],piece=tray['piece'],viewport=(width,height)):
                        for _ in level['tray']:
                            if self.js("document.getElementById('tray-add')?.dataset.piece")==tray['piece']:break
                            self.press('Next piece')
                        label=self.js("document.getElementById('tray-add')?.getAttribute('aria-label')")
                        self.assertIsNotNone(label);self.press(label);self.ghost()
                        before=self.ghost()['p']
                        self.set_precision_controls(True)
                        state=self.js("""(() => {const s=document.getElementById('adjustment-choice');return {
                            offered:[...s.options].map(o=>o.value),
                            exact:[...document.querySelectorAll('#precision-controls [data-knob]')].map(e=>e.dataset.knob),
                            turn:document.querySelector('[aria-label="Turn selected piece"]').checkVisibility(),
                            editor:document.getElementById('piece-editor').getBoundingClientRect().toJSON()};})()""")
                        self.assertTrue(set(state['offered'])<=set(tray['lesson_knobs']),state)
                        self.assertTrue(set(state['exact'])<=set(tray['lesson_knobs']),state)
                        self.assertEqual(state['turn'],any(tray['knobs'][k].get('turning') for k in tray['lesson_knobs']))
                        self.assertEqual(self.ghost()['p'],before,'Opening exact controls cannot change prepared values')
                        self.set_precision_controls(False)
                        if tray['piece']!='ignition':
                            self.wait("(()=>{const b=document.querySelector('#piece-editor .down'),r=b.getBoundingClientRect(),v=document.getElementById('view').getBoundingClientRect();return b.checkVisibility()&&r.width>=44&&r.height>=44&&r.left>=v.left&&r.right<=v.right&&r.top>=v.top&&r.bottom<=v.bottom&&b.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})()",10)
                        self.press('Cancel');self.wait(READY,30)
                self.server.machines.close_all()

    def test_all_placeable_catalogue_properties_are_reachable_beside_the_piece(self):
        import machine_game
        self.open('free',1280,860)
        catalogue=[t for t in machine_game.free_build()['tray'] if not t.get('attach') and not t.get('legacy') and t['piece'] not in ('wire','power_cable')]
        for item in catalogue:
            with self.subTest(piece=item['piece']):
                if self.js('Boolean(machineGhostState())'):self.press('Cancel');self.wait(READY,30)
                self.click_visible('Controls')
                self.press('Add a piece')
                label=self.js(f"document.querySelector('#piece-picker [data-piece=\"{item['piece']}\"]')?.getAttribute('aria-label')")
                if not label:
                    label=self.js(f"[...document.querySelectorAll('#piece-picker button')].find(b=>b.dataset.piece==={json.dumps(item['piece'])})?.getAttribute('aria-label')")
                self.assertIsNotNone(label,item['piece']);self.press(label);self.ghost()
                if item['piece']=='gear':
                    self.assertEqual(self.js("document.querySelectorAll('#piece-editor [data-gear-key]').length"),3)
                    self.assertFalse(self.js("document.querySelector('#piece-editor select')!==null"))
                    self.set_precision_controls(True)
                else:self.assertTrue(self.js("document.getElementById('piece-editor').contains(document.getElementById('adjustment-choice'))"))
                variants=[None]
                for key in ('mount','mode','outlet_model','side','plane','placement'):
                    variants.extend((key,value) for value in item['knobs'].get(key,{}).get('choices',[]))
                for variant in variants:
                    if variant:
                        if variant[0] not in self.js("[...document.getElementById('adjustment-choice').options].map(o=>o.value)"):continue
                        # Exact controls remain in Help/Settings; use their
                        # ordinary change event to expose each device mode.
                        self.slide('Adjustment',variant[0]);self.ghost()
                        self.slide('Its '+item['knobs'][variant[0]].get('label',variant[0]).split(' (')[0],variant[1]);self.ghost()
                        self.click_visible('Controls')
                    keys=self.js("[...document.getElementById('adjustment-choice').options].map(o=>o.value)")
                    for key in keys:
                        self.slide('Adjustment',key);self.ghost()
                        rule=item['knobs'][key]
                        if rule.get('choices'):
                            self.assertFalse(self.js("Boolean(document.querySelector('#piece-editor select:not(#adjustment-choice)'))"))
                            if len(rule['choices'])==2:
                                self.assertTrue(self.js("Boolean(document.querySelector('#piece-editor button[aria-label^=\"Toggle \"]'))"))
                        elif rule.get('part') or rule.get('hinge'):
                            self.assertTrue(self.js("Boolean(document.querySelector('#piece-editor button[aria-label^=\"Choose \"]'))"))
                        if (len(rule.get('choices',[]))>1 and all(isinstance(v,(int,float)) for v in rule['choices'])) or (not rule.get('choices') and rule.get('max',0)>rule.get('min',0)):
                            self.wait("Boolean(document.querySelector('#piece-handles button:not([hidden])'))",10)
                            self.assertFalse(self.js("Boolean(document.querySelector('#piece-editor #piece-grip'))"))
                            self.wait("(()=>{const b=document.querySelector('#piece-handles button:not([hidden])');if(!b)return false;const r=b.getBoundingClientRect();return r.width>=56&&r.height>=56&&b.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})()",3)
                self.press('Cancel');self.wait(READY,30)


    def test_scene_reference_pick_and_live_tap_reach_the_engine(self):
        self.open('free')
        self.js('window.confirm=()=>true');self.press('Clear the table');self.wait(READY,30)
        self.press('Add a gear');self.ghost();self.click_visible('Place');self.wait(READY,30)
        self.press('Add a motor');self.ghost()
        self.drag_ghost_to(1,0);self.ghost()
        self.slide('Adjustment','hinge');self.ghost()
        self.click_visible('Choose driven axle in scene')
        self.click_visible('Pick in scene')
        self.wait('machineCamera().settled',30)
        for point in self.js("machineBodyHitPoints('your gear 1 wheel')"):
            if not self.js(f"document.elementFromPoint({point[0]},{point[1]})?.tagName==='CANVAS'"):continue
            self.mouse('mousePressed',*point);self.mouse('mouseReleased',*point)
            if self.js("machineGhostState()?.p.hinge==='your gear 1 axle'"):break
        self.assertEqual(self.ghost()['p']['hinge'],'your gear 1 axle')
        self.click_visible('Place');self.wait(READY,30)
        self.assertEqual(self.js('machinePlacements()[1].hinge'),'your gear 1 axle')
        self.open('easy-water-receiver')
        self.press('Add a water tank');self.ghost();self.slide('Its tap opening',100);self.ghost()
        self.click_visible('Place');self.wait(READY,30)
        slider=self.js("(()=>{const el=document.querySelector('#device-live-controls input'),r=el.getBoundingClientRect();return {l:r.left+12,r:r.right-12,y:r.y+r.height/2,visible:el.checkVisibility()};})()")
        self.assertTrue(slider['visible']);self.drag([slider['r'],slider['y']],[slider['l'],slider['y']])
        self.wait("document.querySelector('.device-control-status').textContent.includes('queued')",10)
        self.click_visible('Try It!')
        self.wait("machineWaterDisplay().some(s=>s.opening===0)",10)
        self.assertEqual(self.js('machinePlacements()[0].opening_percent'),100,'live state does not silently rewrite saved initial settings')
        self.click_visible('Pause');self.click_visible('Reset');self.wait(READY,30)
        self.assertEqual(self.js('machinePlacements()'),[])


    def test_named_wheel_load_picker_is_readable_and_connects_the_actual_gate(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('free',width,height,phone=width!=1280)
                if width==1280:
                    self.js('window.confirm=()=>true');self.press('Clear the table');self.wait(READY,30)
                    self.press('Add a water wheel');self.ghost();self.choose_adjustment('load to lift')
                    self.assertTrue(self.js("document.querySelector('#piece-editor .scene-reference button').disabled"))
                    self.assertIn('Add a weight or loose box',self.js("document.querySelector('#piece-editor .reference-hint').textContent"))
                    self.press('Cancel')
                self.press('All designs');self.press('Start from Build beside a river');self.wait(READY,60)
                self.press('Add a water wheel');self.ghost()
                self.choose_adjustment('load to lift')
                self.assertTrue(self.js("(()=>{const p=document.querySelector('#piece-editor .reference-hint');return getComputedStyle(p).whiteSpace==='normal'&&p.scrollHeight<=p.clientHeight+1;})()"))
                self.click_visible('Choose load to lift in scene')
                self.assertTrue(self.js("document.getElementById('piece-value-choices').matches(':popover-open')"))
                if width==1280:
                    for rw,rh in ((390,844),(844,390),(1280,860)):
                        self.page.send('Emulation.setDeviceMetricsOverride',{'width':rw,'height':rh,'deviceScaleFactor':1,'mobile':False})
                        self.wait("(()=>{const r=document.getElementById('piece-value-choices').getBoundingClientRect();return r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight;})()",10)
                self.assertFalse(self.js("[...document.querySelectorAll('#piece-value-choices button')].some(b=>b.textContent.startsWith('your water_wheel'))"),'A wheel cannot choose itself as its rope load')
                self.click_visible('Connect load to lift to river gate');self.ghost()
                self.assertEqual(self.ghost()['p']['load_part'],'river gate')
                self.assertFalse(self.js("document.getElementById('piece-value-choices').matches(':popover-open')"))
                self.click_visible('Place');self.wait(READY,60)
                self.assertEqual(self.js('machinePlacements()[0].load_part'),'river gate')
                self.wait("machineFlowPreviewState()?.sample?.mechanism_joints?.some(j=>j.kind==='drum')",30)

    def test_gold_gear_handle_changes_only_declared_tooth_sizes(self):
        self.open('free',1280,860)
        placed_before=self.js('machinePlacements()')
        self.press('Add a gear');self.ghost();self.slide('Adjustment','teeth');self.ghost()
        self.wait("Boolean(document.querySelector('#piece-handles button:not([hidden])'))",10)
        handle=self.js("(()=>{const b=document.querySelector('#piece-handles button:not([hidden])'),r=b.getBoundingClientRect();return {x:r.x+22,y:r.y+22,dx:Number(b.dataset.dx),dy:Number(b.dataset.dy)};})()")
        before=self.ghost()['p']['teeth']
        self.drag([handle['x'],handle['y']],[handle['x']+handle['dx']*96,handle['y']+handle['dy']*96])
        after=self.ghost()['p']['teeth'];self.assertIn(after,[12,18,24,36]);self.assertGreater(after,before)
        self.assertEqual(str(after),self.js("document.querySelector('#piece-editor [data-gear-key=teeth] .gear-value').textContent"))
        self.assertEqual(self.js('machinePlacements()'),placed_before)

    def test_large_object_size_handles_and_named_choices_replace_cycle_arrows(self):
        for width,height in ((1280,860),(390,844),(844,390)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-gears',width,height,phone=width<1000)
                self.click_visible('Add a gear');self.ghost()
                self.assertFalse(self.js("document.querySelector('#piece-editor [aria-label^=\"Previous \"]')!==null"))
                self.wait("document.querySelector('#piece-handles [aria-label^=\"Decrease \"]:not([hidden])')!==null",10)
                handle=self.js("(()=>{const b=document.querySelector('#piece-handles [aria-label^=\"Decrease \"]:not([hidden])'),r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,w:r.width,h:r.height};})()")
                self.assertGreaterEqual(handle['w'],56);self.assertGreaterEqual(handle['h'],56)
                self.mouse('mousePressed',handle['x'],handle['y']);self.mouse('mouseReleased',handle['x'],handle['y'])
                self.assertEqual(self.ghost()['p']['teeth'],12)
                self.click_visible('Choose Teeth')
                self.assertTrue(self.js("document.getElementById('piece-value-choices').matches(':popover-open')"))
                self.assertTrue(self.js("(()=>{const b=document.getElementById('piece-value-choices'),r=b.getBoundingClientRect();return Number.isFinite(parseFloat(b.style.left))&&Number.isFinite(parseFloat(b.style.top))&&r.left>=0&&r.top>=document.getElementById('view').getBoundingClientRect().top&&r.right<=innerWidth&&r.bottom<=innerHeight;})()"))
                self.click_visible('Set Teeth to 24 teeth');self.assertEqual(self.ghost()['p']['teeth'],24)
                self.assertFalse(self.js("document.getElementById('piece-value-choices').matches(':popover-open')"))
                self.set_precision_controls(True)
                self.assertFalse(self.js("[...document.getElementById('adjustment-choice').options].some(o=>o.value==='material')"))
                self.assertFalse(self.js('machinePlacements().length'))


    def test_sandbox_trial_and_three_tabs_fit_small_phone(self):
        self.open('free',320,568,phone=True)
        for ident in ('start','reset','phone-controls-tab','phone-design-tab','phone-help-tab'):
            self.assertTrue(self.js(f"(()=>{{const el=document.getElementById('{ident}'),r=el.getBoundingClientRect();return el.checkVisibility()&&r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight&&r.width>=44&&r.height>=44;}})()"),ident)
        self.assertEqual(self.js("document.getElementById('start').textContent"),'Try It!')


    def test_adjustment_handle_keyboard_changes_one_step_without_moving_piece(self):
        self.open('gap')
        self.press('Add a plank');self.ghost()
        for label in ('Increase Cut to length on object','Decrease Cut to length on object'):
            self.wait("document.querySelector('#piece-handles button:not([hidden])')!==null",10)
            self.click_visible(label)
            before=self.ghost()['p']
            for kind in ('keyDown','keyUp'):
                self.page.send('Input.dispatchKeyEvent',{'type':kind,'key':'ArrowRight','code':'ArrowRight','windowsVirtualKeyCode':39})
            after=self.ghost()['p']
            self.assertAlmostEqual(after['length_m'],before['length_m']+.01,places=4)
            self.assertEqual(after['x_m'],before['x_m']);self.assertEqual(after['z_m'],before['z_m'])

    def test_spring_length_scene_handles_reach_the_native_latch_and_lift(self):
        for width,height in ((1280,860),(390,844),(844,390),(320,568)):
            with self.subTest(viewport=(width,height)):
                self.open('easy-spring',width,height,phone=width!=1280)
                self.click_visible('Add a spring');before=self.ghost()['p']
                self.assertEqual(before['rest_m'],.2)
                self.wait("document.querySelector('#piece-editor .spring-length-value')?.textContent==='20 cm'",5)
                self.assertTrue(self.js("document.querySelector('[aria-label=\"Shorten spring\"]').disabled"))
                for label in ('Shorten spring','Lengthen spring'):
                    self.assertTrue(self.js(f"(()=>{{const b=document.querySelector('[aria-label=\"{label}\"]'),r=b.getBoundingClientRect(),v=document.getElementById('view').getBoundingClientRect();return b.checkVisibility()&&r.width>=44&&r.height>=44&&r.left>=v.left&&r.right<=v.right&&r.top>=v.top&&r.bottom<=v.bottom;}})()"),label)
                self.click_visible('Help')
                self.assertTrue(self.js("document.querySelector('[aria-label=\"Lengthen spring\"]').checkVisibility()"))
                self.click_visible('Lengthen spring');longer=self.ghost()
                self.assertEqual(self.js("document.getElementById('phone-help-tab').getAttribute('aria-selected')"),'true')
                self.assertAlmostEqual(longer['p']['rest_m'],.25)
                self.assertAlmostEqual(math.dist(*longer['editGuide']['rest_span']),.25)
                self.assertEqual((longer['p']['x_m'],longer['p']['z_m'],longer['p']['compressed_m']),
                                 (before['x_m'],before['z_m'],before['compressed_m']))
                self.wait("document.querySelector('#piece-editor .spring-length-value').textContent==='25 cm'",5)
                self.click_visible('Shorten spring');self.ghost();self.click_visible('Controls')
                self.assertFalse(self.js("Boolean(document.querySelector('#piece-editor #piece-grip'))"))
                self.click_visible('Increase Relaxed length on object');after=self.ghost()
                self.assertAlmostEqual(after['p']['rest_m'],.21)
                self.assertAlmostEqual(math.dist(*after['editGuide']['rest_span']),.21)
                self.assertEqual(after['p']['compressed_m'],before['compressed_m'])
                self.assertEqual((after['p']['x_m'],after['p']['z_m']),(before['x_m'],before['z_m']))
                for _ in range(2):
                    handle=self.js("(()=>{const b=document.querySelector('#piece-handles [aria-label^=\"Increase \"]:not([hidden])'),r=b.getBoundingClientRect();return [r.x+28,r.y+28,Number(b.dataset.dx),Number(b.dataset.dy)];})()")
                    self.drag(handle[:2],[handle[0]+120*handle[2],handle[1]+120*handle[3]],touch=width!=1280);self.ghost()
                self.assertEqual(self.ghost()['p']['rest_m'],.7)
                self.assertTrue(self.js("document.querySelector('[aria-label=\"Lengthen spring\"]').disabled"))
                proof=ROOT/'build'/'ui-proof';proof.mkdir(parents=True,exist_ok=True)
                (proof/f'spring-length-handles-{width}x{height}.png').write_bytes(base64.b64decode(self.page.send('Page.captureScreenshot',{'format':'png'})['data']))
                self.click_visible('Place');self.wait(READY,30)
                adjust_hit="(()=>{const b=document.querySelector('.spring-adjust');if(!b||!b.checkVisibility())return false;const r=b.getBoundingClientRect(),v=document.getElementById('view').getBoundingClientRect();return !b.disabled&&r.width>=44&&r.height>=44&&r.left>=v.left&&r.right<=v.right&&r.top>=v.top&&r.bottom<=v.bottom&&b.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})()"
                # Visibility precedes session readiness and the next layout frame.
                # Keep every touch-target/hit-test condition, and wait for it.
                self.wait(adjust_hit,10)
                self.assertTrue(self.js(adjust_hit))
                self.click_visible('Adjust spring');self.ghost()
                self.assertEqual(self.js("document.querySelector('#piece-editor .spring-length-value').textContent"),'70 cm')
                self.click_visible('Shorten spring');self.assertAlmostEqual(self.ghost()['p']['rest_m'],.65)
                self.click_visible('Lengthen spring');self.assertAlmostEqual(self.ghost()['p']['rest_m'],.7)
                self.click_visible('Place');self.wait(READY,30)
                self.click_piece(0);self.ghost()
                self.assertEqual(self.js("document.querySelector('#piece-editor .spring-length-value').textContent"),'70 cm')
                self.click_visible('Shorten spring');self.assertAlmostEqual(self.ghost()['p']['rest_m'],.65)
                self.click_visible('Lengthen spring');self.assertAlmostEqual(self.ghost()['p']['rest_m'],.7)
                self.click_visible('Place');self.wait(READY,30)
                load=self.js("machineBodies()['spring load']")
                host=self.server.machines;original_open=host.open;allow_open=threading.Event()
                def pending_open(spec):
                    allow_open.wait(10)
                    return original_open(spec)
                with patch.object(host,'open',side_effect=pending_open):
                    try:
                        self.click_visible('Try It!')
                        self.wait("document.getElementById('clock').textContent.includes('Building')&&document.querySelector('.spring-adjust')?.disabled",5)
                    finally:allow_open.set()
                    self.wait("document.getElementById('clock').textContent.includes('Release spring')",30)
                self.click_visible('Adjust spring');self.ghost()
                self.assertEqual(self.js("document.querySelector('#piece-editor .spring-length-value').textContent"),'70 cm')
                self.click_visible('Place');self.wait(READY,30)
                self.assertAlmostEqual(self.js("machineBodies()['spring load'][1]"),load[1],places=3)
                self.click_visible('Release spring');self.wait("document.body.classList.contains('scene-win')",30)
                self.assertGreater(self.js("machineBodies()['spring load'][1]"),load[1]+.049)


if __name__ == '__main__':
    shard=next((a for a in sys.argv[1:] if a.startswith('--shard=')),None)
    if shard:
        index,count=map(int,shard.split('=',1)[1].split('/'))
        if not 0<=index<count<=16:raise SystemExit('shard must be INDEX/COUNT with 0 <= INDEX < COUNT <= 16')
        tests=list(unittest.defaultTestLoader.loadTestsFromTestCase(Puzzles))
        suite=unittest.TestSuite(test for i,test in enumerate(tests) if i%count==index)
        print(f'Browser batch {index+1}/{count}: {suite.countTestCases()} of {len(tests)} cases',flush=True)
        result=unittest.TextTestRunner(verbosity=2,resultclass=LiveBrowserResult).run(suite)
        raise SystemExit(0 if result.wasSuccessful() else 1)
    unittest.main(verbosity=2,testRunner=unittest.TextTestRunner(verbosity=2,resultclass=LiveBrowserResult))
