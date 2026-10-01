"""Native goods flow, personal pickup, failure/retry/restart and browser proof."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest import mock
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'playground'),str(ROOT/'tests'),str(ROOT)]
import ai_player_tests as fixture
import machine_witness
import server
import workshop_library
import world_goods
import qa_browser


class GoodsJourney(unittest.TestCase):
    setUp=fixture.AutonomousGuests.setUp
    tearDown=fixture.AutonomousGuests.tearDown
    start=fixture.AutonomousGuests.start
    stop=fixture.AutonomousGuests.stop
    get=fixture.AutonomousGuests.get
    post=fixture.AutonomousGuests.post
    join=fixture.AutonomousGuests.join
    setup_world=fixture.AutonomousGuests.setup_world

    def batch(self,process=True):
        with mock.patch.object(server.secrets,'randbelow',side_effect=[1,851269741]):
            world,owner,app=self.setup_world()
        source=next(m for m in machine_witness.machines(app) if m['recipe']=='smelt copper')
        output=app.brains.goods.by_name(app.brains.of(source['machine']).routine.output)
        self.assertFalse(output.get('rack'), 'New games leave output awaiting pickup')
        if process:self.process_batch(app,output)
        point=output['at_m']
        floor=app.live.act({'session':app.live.session.id,'op':'survey','at':point})['survey']['ground_m']
        person={'eyes_m':[point[0],floor+1.62,point[1]],'facing':[0,0,-1]}
        return world,owner,app,source,output,person

    def process_batch(self,app,output):
        before=deepcopy(output.get('holds') or {})
        for _ in range(200):
            app.clock._tick(.2)
            if (output.get('holds') or {})!=before:break
        self.assertGreater(output['holds'].get('copper',0),0,'Actual source batch must produce copper')
        self.assertTrue(any(e['kind']=='input' and e['goods_kg']=={'copper ore':5.0} for e in app.brains.goods.activities))
        self.assertTrue(any(e['kind']=='output' and e['goods_kg'].get('copper')==1.5 for e in app.brains.goods.activities))

    def personal(self,app,owner):
        token=workshop_library.REQUEST_OWNER.set(owner['id'])
        try:
            result={r['substance']:r['personal_kg'] for r in workshop_library.goods_rack(app)['goods'] if r['personal_kg']>0}
            result.update({r['material']:r['personal_kg'] for r in workshop_library.rack(app)['materials'] if r['personal_kg']>0})
            return result
        finally: workshop_library.REQUEST_OWNER.reset(token)

    def test_output_collect_requires_nearby_player_and_survives_failures_retry_two_guests_restart(self):
        world,owner,app,source,pile,person=self.batch()
        other=self.join(world,'Second collector')
        initial=deepcopy(pile['holds']);sid=app.live.session.id
        request={'session':sid,'pile':pile['name'],'request_id':'actual-output','person':person}
        far={**request,'person':{'eyes_m':[70,2,70],'facing':[0,0,-1]}}
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/goods/collect',far,world)
        self.assertEqual(initial,pile['holds'])
        high={**request,'person':{**person,'eyes_m':[person['eyes_m'][0],person['eyes_m'][1]+10,person['eyes_m'][2]]}}
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/goods/collect',high,world)
        self.assertEqual(initial,pile['holds'])
        # Physical withdrawal and pending claim stay paired. No credit until save.
        with mock.patch.object(server,'keep_world',return_value=False):
            with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/goods/collect',request,world)
            self.assertEqual({},self.personal(app,owner))
        self.assertEqual({},pile['holds'])
        self.assertEqual(initial,app.room.goods_claims[0]['goods'])
        with self.assertRaises(urllib.error.HTTPError):
            self.post('/api/world/goods/collect',request,world,other['token'])
        for _ in range(2):
            answer=self.post('/api/world/goods/collect',request,world)
            self.assertTrue(answer['repeated']);self.assertEqual(initial,answer['collected'])
        self.assertEqual(initial,self.personal(app,owner));self.assertEqual({},self.personal(app,other))
        self.assertEqual(1,sum(e['kind']=='collect' for e in app.brains.goods.activities))
        with self.assertRaises(urllib.error.HTTPError):
            self.post('/api/world/goods/collect',{**request,'request_id':'other-copy'},world,other['token'])
        self.stop();self.start();self.post('/api/world/open',{},world)
        restored=self.app.hub.get(world);request['session']=restored.live.session.id
        self.post('/api/world/goods/collect',request,world)
        self.assertEqual({},restored.brains.goods.by_name(pile['name'])['holds'])
        self.assertEqual(initial,self.personal(restored,owner));self.assertEqual({},self.personal(restored,other))
        # No rendering packets are persisted/replayed as new production.
        self.assertEqual([],restored.brains.goods.activities)
        report={'schema':'banjo.resource-flow-acceptance.v1','native_dt_s':1/240,'cell_m':.05,
                'collected':initial,'other_guest_collected':{},'restart_retained':True,
                'save_failure_no_credit':True,'retries_no_duplicate':True,'provider_calls':0}
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/'acceptance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')

    def test_saved_withdrawal_recovers_credit_after_sql_failure_and_server_restart(self):
        world,owner,app,source,pile,person=self.batch()
        initial=deepcopy(pile['holds']);request={'session':app.live.session.id,'pile':pile['name'],
            'request_id':'sql-recovery','person':person}
        with mock.patch.object(world_goods,'settle',side_effect=OSError('collection database unavailable')):
            with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/goods/collect',request,world)
            self.assertIn('sql-recovery',app.room.goods_durable_claims)
            self.stop()
        self.start();self.post('/api/world/open',{},world)
        restored=self.app.hub.get(world)
        self.assertEqual(initial,self.personal(restored,owner))
        request['session']=restored.live.session.id
        self.post('/api/world/goods/collect',request,world)
        self.assertEqual(initial,self.personal(restored,owner))

    def test_browser_shows_output_packets_and_collects_into_personal_inventory(self):
        if not qa_browser.CHROME.is_file():self.skipTest('Chrome not installed')
        world,owner,app,source,pile,person=self.batch(process=False)
        chrome=qa_browser.Chrome(1280,800);self.addCleanup(chrome.close)
        page=chrome.page;page.send('Page.enable');page.send('Runtime.enable')
        def wait(expression):
            deadline=time.monotonic()+40
            while time.monotonic()<deadline:
                try:
                    if page.evaluate(expression):return
                except (RuntimeError,TimeoutError):pass
                time.sleep(.12)
            self.fail('Browser did not reach '+expression+'; '+str(page.evaluate('document.querySelector("#panel-state")?.textContent'))+'; '+str([e for e in page.events if e.get('method')=='Runtime.exceptionThrown']))
        page.send('Page.navigate',{'url':self.base+f'/world?world={world}'})
        wait('window.banjoRoom?.ready()')
        self.assertGreater(page.evaluate('banjoRoom.scene.getObjectByName("resource-packets").children.length'),0)
        # Every ordinary opened page starts from its baseline, not past events.
        page.evaluate(f'banjoRoom.standAt({person["eyes_m"][0]}, {person["eyes_m"][1]}, {person["eyes_m"][2]+3.3})')
        page.evaluate(f'banjoRoom.lookAt({person["eyes_m"][0]}, {person["eyes_m"][1]-1.4}, {person["eyes_m"][2]})')
        self.process_batch(app,pile)
        wait('banjoRoom.scene.getObjectByName("resource-packets").children.some(c=>c.userData.transferKind === "input" || c.userData.transferKind === "output")')
        wait('banjoRoom.scene.getObjectByName("resource-packets").children.some(c=>c.userData.resourceStorage === "input" && c.children.some(v=>v.geometry?.type==="BoxGeometry"))')
        viewer=page.evaluate(f'localStorage.getItem("banjo.player.{world}")')
        player=next(p for p in app.room.player_records.values() if p['token']==viewer)
        before=deepcopy(pile['holds'])
        page.evaluate('window.dispatchEvent(new CustomEvent("banjo-movement-mode",{detail:"fly"}))')
        page.evaluate(f'banjoRoom.standAt({person["eyes_m"][0]}, {person["eyes_m"][1]}, {person["eyes_m"][2]+1.2})')
        time.sleep(.7)
        self.assertEqual(before,pile['holds'],'Inspection flight must not auto-collect output')
        intake=app.brains.goods.by_name(app.brains.of(source['machine']).routine.intake)
        page.evaluate(f'(()=>{{const p=banjoRoom.scene.getObjectByName("resource-packets").children.find(c=>c.userData.resourcePile==={json.dumps(intake["name"])}).position;banjoRoom.standAt(p.x+1.8,p.y+1.6,p.z+1.6);banjoRoom.lookAt(p.x,p.y+.15,p.z)}})()')
        time.sleep(.25)
        import base64
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        shot=page.send('Page.captureScreenshot',{'format':'png'})['data']
        (out/'input-hopper.png').write_bytes(base64.b64decode(shot))
        page.evaluate(f'banjoRoom.standAt({person["eyes_m"][0]}, {person["eyes_m"][1]}, {person["eyes_m"][2]+3.3});banjoRoom.lookAt({person["eyes_m"][0]}, {person["eyes_m"][1]-1.4}, {person["eyes_m"][2]});window.dispatchEvent(new CustomEvent("banjo-movement-mode",{{detail:"gravity"}}))')
        shot=page.send('Page.captureScreenshot',{'format':'png'})['data']
        (out/'output-ready.png').write_bytes(base64.b64decode(shot))
        page.send('Input.dispatchKeyEvent',{'type':'keyDown','key':'w','code':'KeyW','windowsVirtualKeyCode':87})
        try:wait(f'!banjoRoom.world.goods.stockpiles.find(p=>p.name==={json.dumps(pile["name"])}).holds_kg.copper')
        finally:page.send('Input.dispatchKeyEvent',{'type':'keyUp','key':'w','code':'KeyW','windowsVirtualKeyCode':87})
        wait('banjoRoom.scene.getObjectByName("resource-packets").children.some(c=>c.userData.transferKind === "collect")')
        self.assertEqual({},pile['holds']);self.assertEqual(before,self.personal(app,player))
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        shot=page.send('Page.captureScreenshot',{'format':'png'})['data']
        (out/'collected.png').write_bytes(base64.b64decode(shot))
        self.assertEqual([],[e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])

    def test_selected_rover_reports_actual_ground_hazard_probes_in_right_panel(self):
        if not qa_browser.CHROME.is_file():self.skipTest('Chrome not installed')
        world,owner,app,*_=self.batch(False)
        chrome=qa_browser.Chrome(1280,800);self.addCleanup(chrome.close)
        page=chrome.page;page.send('Page.enable');page.send('Runtime.enable')
        page.send('Page.navigate',{'url':self.base+f'/world?world={world}&hold=1'})
        def wait(expression):
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                if page.evaluate('Boolean('+expression+')'):return
                time.sleep(.1)
            self.fail(expression+'; '+str(page.evaluate('document.querySelector("#picked")?.textContent')))
        wait('window.banjoRoom?.ready()')
        page.evaluate('banjoRoom.pick("rover")')
        wait('document.querySelector("[data-rover-sensors]")')
        probes=page.evaluate('banjoRoom.world.machines.programs.find(p=>p.body==="rover").sensors')
        self.assertEqual(10,len(probes));self.assertEqual(5,sum(p['kind']=='ground' for p in probes))
        self.assertEqual(2,sum(p['kind']=='ground' and p['stops']<0 for p in probes))
        text=page.evaluate('document.querySelector("[data-rover-sensors]").textContent')
        self.assertIn('Rear left · ground',text);self.assertIn('Front middle · ground',text)
        middle=next(p for p in probes if p['kind']=='ground' and p['side']==0 and p['stops']>0)
        x,y,z=middle['at_m']
        # The real native dig/report path, not injected sensor readings.
        page.evaluate(f'banjoRoom.standAt({x},banjoRoom.groundAt({x},{z})+1.6,{z+1})')
        answer=page.evaluate(f'banjoRoom.digAt({x},{z},.5,.6)',await_promise=True)
        self.assertGreater((answer.get('dug') or {}).get('kg',0),0,'The native excavation must actually happen')
        page.evaluate('banjoRoom.resume()')
        wait('banjoRoom.world.machines.programs.find(p=>p.body==="rover").sensors.some(p=>p.kind==="ground"&&p.sees)')
        wait('document.querySelector("[data-rover-sensors]").textContent.includes("⚠")')
        page.evaluate('banjoRoom.hold()')
        import base64
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/'rover-ground-sensors.png').write_bytes(base64.b64decode(page.send('Page.captureScreenshot',{'format':'png'})['data']))
        self.assertEqual([],[e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])

    def test_automatic_collection_refuses_processor_input_and_preserves_output_receipts(self):
        world,owner,app,source,pile,person=self.batch()
        intake=app.brains.goods.by_name(app.brains.of(source['machine']).routine.intake)
        before=deepcopy(intake['holds'])
        request={'session':app.live.session.id,'pile':intake['name'],'automatic':True,
                 'request_id':'auto-input-refusal','person':person}
        with self.assertRaises(urllib.error.HTTPError) as error:self.post('/api/world/goods/collect',request,world)
        self.assertIn('inputs stay in their hopper',error.exception.read().decode())
        self.assertEqual(before,intake['holds']);self.assertEqual({},self.personal(app,owner))
        expected=deepcopy(pile['holds']);request.update(pile=pile['name'],request_id='auto-output')
        for _ in range(2):self.post('/api/world/goods/collect',request,world)
        self.assertEqual(expected,self.personal(app,owner));self.assertEqual({},pile['holds'])
        event=next(e for e in app.brains.goods.activities if e['kind']=='collect')
        self.assertEqual(owner['id'],event['to']['player']);self.assertEqual(3,len(event['to']['point_m']))

    def test_bootstrap_recipe_and_browser_typing_head_edit_save_and_paid_make(self):
        if not qa_browser.CHROME.is_file():self.skipTest('Chrome not installed')
        world,owner,app,source,pile,person=self.batch(process=False)
        made=self.post('/api/world/workshop/what_made',{'body':'field pick'},world)
        self.assertEqual('field-pick',made['recipe']['kind'])
        self.assertGreaterEqual(len(made['bodies']),2)
        recipes=self.post('/api/workshop/recipes',{},world)
        pick=next(r for r in recipes['templates'] if r['kind']=='field-pick')
        self.assertTrue(pick['readiness']['ready_as_drawn'],pick)
        chrome=qa_browser.Chrome(1280,800);self.addCleanup(chrome.close)
        page=chrome.page;page.send('Page.enable');page.send('Runtime.enable')
        def wait(expression):
            deadline=time.monotonic()+40
            while time.monotonic()<deadline:
                if page.evaluate('Boolean('+expression+')'):return
                time.sleep(.12)
            self.fail('Browser did not reach '+expression+'; '+str(page.evaluate('document.body.innerText.slice(-1200)')))
        page.send('Page.navigate',{'url':self.base+f'/world?world={world}&workshop=1&tab=recipes'})
        wait('document.querySelector("[data-open-recipe=\\"field-pick:field-pick\\"]")')
        page.evaluate('document.querySelector("[data-open-recipe=\\"field-pick:field-pick\\"]").click()')
        wait('document.querySelectorAll("#ws-parts li").length===2 && !document.querySelector("#ws-component-chat-text").disabled')
        selected_url=page.evaluate('location.href')
        page.send('Page.navigate',{'url':'about:blank'})
        wait('location.href === "about:blank"')
        page.send('Page.navigate',{'url':selected_url})
        wait('document.querySelectorAll("#ws-parts li").length===2 && !document.querySelector("#ws-component-chat-text").disabled')
        def chat(text):
            page.evaluate('document.querySelector("#ws-component-chat-text").focus()')
            page.send('Input.insertText',{'text':text})
            page.evaluate('document.querySelector("#ws-component-chat").requestSubmit()')
            wait('!document.querySelector("#ws-component-chat-text").disabled && document.querySelector("#ws-component-chat-text").value===""')
        chat('make the head iron')
        parts=page.evaluate('[...document.querySelectorAll("#ws-parts li")].map(e=>e.textContent)')
        self.assertTrue(any('haft' in p and 'oak' in p for p in parts),parts)
        self.assertTrue(any('arm' in p and 'iron' in p for p in parts),parts)
        page.evaluate('document.querySelector("#ws-quick-save").click()')
        wait('document.querySelector("#ws-save-status").textContent.includes("Saved")')
        # Fused mixed material is deliberately refused by native admission;
        # the supported monolithic oak source must really install and charge.
        chat('make the whole object oak')
        before=workshop_library.rack(app)
        page.evaluate('document.querySelector("#ws-make").click()')
        wait('document.querySelector("#ws-make-status").textContent.startsWith("Made.")')
        self.assertEqual(1,len(app.room.workshop_installs))
        before_oak=next(r['mass_kg'] for r in before['materials'] if r['material']=='oak')
        after_oak=next(r['mass_kg'] for r in workshop_library.rack(app)['materials'] if r['material']=='oak')
        self.assertGreater(before_oak,after_oak)
        self.assertEqual([],[e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])

    def test_component_inspection_explodes_full_rover_and_actual_pick_cells_without_native_changes(self):
        if not qa_browser.CHROME.is_file():self.skipTest('Chrome not installed')
        world,owner,app,*_=self.batch(process=False)
        chrome=qa_browser.Chrome(1440,900);self.addCleanup(chrome.close)
        page=chrome.page;page.send('Page.enable');page.send('Runtime.enable')
        def wait(expression):
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                if page.evaluate('Boolean('+expression+')'):return
                time.sleep(.1)
            self.fail('Browser did not reach '+expression)
        page.send('Page.navigate',{'url':self.base+f'/world?world={world}&hold=1'})
        wait('window.banjoRoom?.ready()')
        sid=app.live.session.id
        before=app.live.act({'session':sid,'op':'poses'})
        page.evaluate('(()=>{const r=banjoRoom,p=r.world.bodies.get("rover").mesh.position;r.standAt(p.x+3,p.y+2,p.z+3);r.lookAt(p.x,p.y,p.z);r.pick("rover")})()')
        wait('banjoRoom.reveal()?.components?.length>6 && banjoRoom.reveal().amount===1')
        components=page.evaluate('banjoRoom.reveal().components')
        members={'rover'}
        while True:
            expanded=members | {end for j in before.get('joints',[]) if j.get('attached')
                and (j['a'] in members or j['b'] in members) for end in (j['a'],j['b'])}
            if expanded==members:break
            members=expanded
        native_parts=[(b['name'],p) for b in before['bodies'] if b['name'] in members for p in b.get('rigid_parts_local',[])]
        self.assertEqual(len(native_parts),len(components))
        self.assertEqual({b for b,p in native_parts},{c['body'] for c in components})
        self.assertGreater(len({c['body'] for c in components}),3,components)
        self.assertTrue(all(c['name'] and c['material'] and sum(v*v for v in c['offset'])>.2 for c in components))
        self.assertEqual(len(components),page.evaluate('document.querySelectorAll("#picked .pk-components dt").length'))
        time.sleep(3.3);self.assertTrue(page.evaluate('!!banjoRoom.reveal()?.components'))
        import base64
        output=ROOT/'build/resource-flow';output.mkdir(parents=True,exist_ok=True)
        (output/'rover-components.png').write_bytes(base64.b64decode(page.send('Page.captureScreenshot',{'format':'png'})['data']))
        page.evaluate('document.querySelector("#picked .pk-reveal").click()')
        self.assertIsNone(page.evaluate('banjoRoom.reveal()'))
        page.evaluate('banjoRoom.pick("field pick")')
        wait('banjoRoom.reveal()?.components?.length===2')
        parts=page.evaluate('banjoRoom.reveal().components')
        self.assertEqual({'haft','arm'},{p['name'] for p in parts})
        self.assertEqual(page.evaluate('banjoRoom.world.bodies.get("field pick").cells.length'),sum(p['cells'] for p in parts))
        page.evaluate('[...document.querySelectorAll("#picked button")].find(b=>b.textContent==="Show native cells").click()')
        wait('banjoRoom.reveal()?.kind==="cells"')
        page.evaluate('banjoRoom.pick(null)')
        after=app.live.act({'session':sid,'op':'poses'})
        for key in ('t','bodies','machines'):self.assertEqual(before[key],after[key],key)
        self.assertEqual([],[e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])

    def test_day_cycle_charges_real_store_and_night_lamp_consumes_it(self):
        world,owner,app,*_=self.batch(process=False)
        session=app.live.session
        self.assertEqual(600,session.spec['sun']['day_s'])
        # Explicit accelerated experiment, native dt 1/240; production is 600 s.
        session.send(op='sun',day_s=10,noon_elevation_deg=60,hour=8,irradiance_w_m2=1000)
        initial=next(s for s in session.state['machines']['stores'] if s['name']=='array battery')['charge_j']
        seen_day=seen_night=seen_dawn=False
        direction=None
        for _ in range(60):
            out=app.live.act({'session':session.id,'op':'step','dt':1/30,'n':6})
            sun=out['sun'];lamp=out['machines']['lamps'][0]
            store=next(s for s in out['machines']['stores'] if s['id']==lamp['store'])
            self.assertAlmostEqual(initial+store['taken_j']-store['given_j'],store['charge_j'],delta=3e-5)
            if direction is None:direction=sun['toward']
            elif .5<out['t']<2:self.assertNotEqual(direction,sun['toward'])
            if 1<out['t']<2:
                seen_day=True;self.assertGreater(store['taken_j'],0);self.assertFalse(lamp['lit'])
            if 5<out['t']<8:
                seen_night=True;self.assertLess(sun['elevation_deg'],0)
                self.assertTrue(lamp['lit']);self.assertEqual(20,lamp['drawn_w'])
                self.assertGreater(lamp['drawn_j'],0);self.assertEqual(0,sun['irradiance_w_m2'])
            if out['t']>10:
                seen_dawn=True;self.assertFalse(lamp['on']);self.assertFalse(lamp['lit'])
        self.assertTrue(seen_day and seen_night and seen_dawn)
        self.assertAlmostEqual(100,lamp['drawn_j'],delta=1e-5)

    def test_plain_entry_generates_world_and_menu_switches_fall_jump_and_fly(self):
        if not qa_browser.CHROME.is_file():self.skipTest('Chrome not installed')
        chrome=qa_browser.Chrome(1280,800);self.addCleanup(chrome.close)
        page=chrome.page;page.send('Page.enable');page.send('Runtime.enable')
        def wait(expression):
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                try:
                    if page.evaluate('Boolean('+expression+')'):return
                except (RuntimeError,TimeoutError):pass
                time.sleep(.1)
            self.fail('Browser did not reach '+expression)
        page.send('Page.navigate',{'url':self.base+'/world'})
        wait('window.banjoRoom?.ready() && new URL(location.href).searchParams.has("world")')
        first=page.evaluate('new URL(location.href).searchParams.get("world")')
        self.assertTrue(self.app.hub.get(first).room.spec['sun']['day_s']>0)
        wait('document.querySelector("#world-load-meter")')
        self.assertIn('Ground materials',page.evaluate('document.querySelector("#world-load-meter").textContent'))
        self.assertGreater(page.evaluate('banjoRoom.scene.getObjectByName("resource-packets").children.filter(c=>c.userData.resourceDeposit).length'),0)
        def mode(value):
            page.evaluate('document.querySelector("[data-game-menu]").click()')
            page.evaluate(f'(()=>{{const e=document.querySelector("#game-menu-movement select");e.value={json.dumps(value)};e.dispatchEvent(new Event("change"))}})()')
        mode('fly');page.evaluate('banjoRoom.standAt(0,8,0)')
        mode('gravity')
        wait('banjoRoom.camera.position.y<5')
        room=self.app.hub.get(first)
        floor=room.live.act({'session':room.live.session.id,'op':'survey','at':[0,0]})['survey']['ground_m']
        wait(f'Math.abs(banjoRoom.camera.position.y-{floor+1.6})<.03')
        base_y=page.evaluate('banjoRoom.camera.position.y')
        page.send('Input.dispatchKeyEvent',{'type':'keyDown','key':' ','code':'Space','windowsVirtualKeyCode':32})
        wait(f'banjoRoom.camera.position.y>{base_y+.3}')
        time.sleep(1.3)
        self.assertAlmostEqual(base_y,page.evaluate('banjoRoom.camera.position.y'),delta=.04,msg='Held jump must not launch repeatedly')
        page.send('Input.dispatchKeyEvent',{'type':'keyUp','key':' ','code':'Space','windowsVirtualKeyCode':32})
        mode('fly');page.evaluate('banjoRoom.standAt(0,8,0)');time.sleep(.4)
        self.assertAlmostEqual(8,page.evaluate('banjoRoom.camera.position.y'),delta=.02)
        page.send('Page.navigate',{'url':self.base+'/world'})
        wait(f'window.banjoRoom?.ready() && new URL(location.href).searchParams.get("world")!=={json.dumps(first)}')
        self.assertEqual([],[e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])

    def test_gravity_player_exits_real_river_walks_hills_and_can_swim_up(self):
        if not qa_browser.CHROME.is_file():self.skipTest('Chrome not installed')
        chrome=qa_browser.Chrome(1280,800);self.addCleanup(chrome.close)
        page=chrome.page;page.send('Page.enable');page.send('Runtime.enable')
        def wait(expression,seconds=20):
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline:
                if page.evaluate('Boolean('+expression+')'):return
                time.sleep(.08)
            self.fail(expression+'; pose='+str(page.evaluate('banjoRoom.camera.position.toArray()')))
        def key(code,down):
            page.send('Input.dispatchKeyEvent',{'type':'keyDown' if down else 'keyUp',
                'key':{'KeyW':'w','KeyS':'s','Space':' '}.get(code,code),'code':code,
                'windowsVirtualKeyCode':{'KeyW':87,'KeyS':83,'Space':32}.get(code,16)})
        reports=[]
        for terrain_choice,seed in enumerate((851269741,851269742)):
            with self.subTest(seed=seed),mock.patch.object(server.secrets,'randbelow',side_effect=[terrain_choice,seed]):
                world,owner,app=self.setup_world()
                page.send('Page.navigate',{'url':self.base+f'/world?world={world}&hold=1'})
                wait('window.banjoRoom?.ready()')
                page.evaluate('window.dispatchEvent(new CustomEvent("banjo-movement-mode",{detail:"gravity"}))')
                # Discover a real wet-to-dry crossing and an ordinary uphill
                # segment from the native report, rather than a mocked floor.
                spots=page.evaluate('''(()=>{
                  const R=banjoRoom, g=R.groundDrawn(); let shore=null,hill=null;
                  for(let z=g.z0+2;z<g.z0+(g.nz-1)*g.dx-2;z+=.5)
                  for(let x=g.x0+2;x<g.x0+(g.nx-1)*g.dx-2;x+=.5){
                    const h=R.groundAt(x,z), w=R.waterAt(x,z), d=w?w.level-h:0;
                    if(!shore && d>.35 && d<1.1) for(const [dx,dz] of [[1,0],[-1,0],[0,1],[0,-1]]){
                      const sx=x+3*dx,sz=z+3*dz,sw=R.waterAt(sx,sz),sh=R.groundAt(sx,sz);
                      if(sw&&sw.level-sh>.02)continue;
                      let good=true,prev=h;
                      for(let t=.1;t<=3.001;t+=.1){const now=R.groundAt(x+dx*t,z+dz*t);
                        if(Math.abs(now-prev)>.085)good=false;prev=now;}
                      if(good){shore={wet:[x,z],dry:[sx,sz]};break;}
                    }
                    if(!hill && d<.02){const end=R.groundAt(x+2,z);let good=end-h>.4&&end-h<1.1,prev=h;
                      for(let t=.1;t<=2.001;t+=.1){const now=R.groundAt(x+t,z),ww=R.waterAt(x+t,z);
                        if(Math.abs(now-prev)>.085 || ww&&ww.level-now>.02)good=false;prev=now;}
                      if(good)hill={start:[x,h,z],end:[x+2,end,z]};}
                  }return {shore,hill};})()''')
                self.assertIsNotNone(spots['shore']);self.assertIsNotNone(spots['hill'])
                wet,dry=spots['shore']['wet'],spots['shore']['dry']
                x,z=dry
                page.evaluate(f'banjoRoom.standAt({x},banjoRoom.groundAt({x},{z})+1.6,{z});banjoRoom.lookAt({2*x-wet[0]},banjoRoom.camera.position.y,{2*z-wet[1]})')
                key('KeyS',True)
                try:wait('banjoRoom.world.inWater?.under>.3')
                finally:key('KeyS',False)
                key('KeyW',True);key('Space',True)
                try:wait('!banjoRoom.world.inWater')
                finally:key('KeyW',False);key('Space',False)
                hill=spots['hill'];x,y,z=hill['start'];end=hill['end']
                page.evaluate(f'banjoRoom.standAt({x},{y+1.6},{z});banjoRoom.lookAt({end[0]},{y+1.6},{z})')
                key('KeyW',True)
                try:wait(f'banjoRoom.camera.position.x>{end[0]-.05}')
                finally:key('KeyW',False)
                pose=page.evaluate('banjoRoom.camera.position.toArray()')
                floor=page.evaluate('banjoRoom.groundAt(banjoRoom.camera.position.x,banjoRoom.camera.position.z)')
                self.assertAlmostEqual(floor+1.6,pose[1],delta=.04)
                self.assertGreater(pose[1]-(y+1.6),.35)
                reports.append({'goods_seed':seed,'terrain_seed':app.room.spec['terrain']['generate']['seed'],
                    'shore':spots['shore'],'hill_rise_m':pose[1]-(y+1.6)})
        # A declared deep pool checks the camera approximation separately from
        # the native shallow river. No native water volume/force claim is made.
        page.evaluate('banjoRoom.standAt(0,banjoRoom.groundAt(0,0)+1.6,0);window.poolLevel=banjoRoom.groundAt(0,0)+2.3;banjoRoom.waterForThePerson((x,z)=>({level:poolLevel,depth:poolLevel-banjoRoom.groundAt(x,z),u:0,w:0}))')
        wait('banjoRoom.world.inWater?.head_under')
        key('Space',True)
        try:wait('banjoRoom.camera.position.y>poolLevel+.05')
        finally:key('Space',False)
        wait('document.querySelector("[data-movement]").textContent.includes("Swim")')
        time.sleep(4)
        self.assertGreater(page.evaluate('banjoRoom.camera.position.y'),page.evaluate('poolLevel')-.1,
                           'Buoyancy must keep the controller near the surface without held jump')
        key('ShiftLeft',True);key('Space',True)
        try:wait('banjoRoom.world.inWater?.head_under')
        finally:key('Space',False);key('ShiftLeft',False)
        key('Space',True)
        try:wait('banjoRoom.camera.position.y>poolLevel')
        finally:key('Space',False)
        page.evaluate('banjoRoom.waterForThePerson(null)')
        self.assertEqual([],[e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/'movement-acceptance.json').write_text(json.dumps({'generated_crossings':reports,
            'declared_deep_pool_m':2.3,'swim_rise_dive_recovery':True,
            'scope':'kinematic player controller; native avatar and rover unchanged'},indent=2),encoding='utf-8')

    def test_two_collectors_race_for_one_actual_output_without_duplicate_credit(self):
        from concurrent.futures import ThreadPoolExecutor
        world,owner,app,source,pile,person=self.batch()
        other=self.join(world,'Simultaneous collector');initial=deepcopy(pile['holds'])
        def take(player):
            try:
                return self.post('/api/world/goods/collect',{'session':app.live.session.id,'pile':pile['name'],
                    'request_id':'race-'+player['id'],'person':person},world,player['token'])
            except urllib.error.HTTPError as exc:
                self.assertEqual(400,exc.code);return None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(take,[owner,other]))
        self.assertEqual(1,sum(r is not None for r in results))
        self.assertEqual({},pile['holds'])
        balances=[self.personal(app,p) for p in (owner,other)]
        self.assertEqual(initial,{k:sum(b.get(k,0) for b in balances) for k in initial})

    def test_raw_material_collection_credits_personal_build_stock_and_preserves_shared_stock(self):
        world,owner,app,source,output,person=self.batch(process=False)
        pile=next(p for p in app.brains.goods.stockpiles if (p.get('holds') or {}).get('oak',0)>25)
        at=pile['at_m'];sid=app.live.session.id
        floor=app.live.act({'session':sid,'op':'survey','at':at})['survey']['ground_m']
        initial=pile['holds']['oak']
        answer=self.post('/api/world/goods/collect',{'session':sid,'pile':pile['name'],
            'request_id':'collect-oak','person':{'eyes_m':[at[0],floor+1.62,at[1]],'facing':[0,0,-1]}},world)
        self.assertEqual({'oak':25.0},answer['collected'])
        self.assertAlmostEqual(initial-25,pile['holds']['oak'],places=6)
        self.assertEqual({'oak':25.0},self.personal(app,owner))
        token=workshop_library.REQUEST_OWNER.set(owner['id'])
        try:
            oak=next(r for r in workshop_library.rack(app)['materials'] if r['material']=='oak')
            self.assertEqual(12.4,oak['shared_kg'])
        finally:workshop_library.REQUEST_OWNER.reset(token)


if __name__=='__main__':unittest.main()
