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
from live_session import LiveError


class GoodsJourney(unittest.TestCase):
    setUp=fixture.AutonomousGuests.setUp
    tearDown=fixture.AutonomousGuests.tearDown
    start=fixture.AutonomousGuests.start
    stop=fixture.AutonomousGuests.stop
    get=fixture.AutonomousGuests.get
    post=fixture.AutonomousGuests.post

    def test_older_owned_ground_moves_to_separate_piles_and_bulk_collection_is_durable(self):
        import live_session
        from mcp import ground_transfers, fabrication
        world,owner,app,_,_,_=self.batch(process=False)
        peer=self.join(world,'Other gatherer');sid=app.live.session.id
        def native(op,**args):return app.live.act({'session':sid,'op':op,**args})
        target=[.3,.025]
        with app.live.as_actor(owner['id']):
            native('dig',**{'from':target,'width_m':1.,'depth_m':.3})
            original=live_session.current_carried(app.live.session)
            self.assertGreater(original['sand_kg']+original['soil_kg'],70)
            floor=native('survey',at=target)['survey']['ground_m']
            body={'at_m':[target[0],floor,target[1]],'person':{'eyes_m':[target[0]-1.2,floor+1.62,target[1]]}}
            first=world_goods.heap_excavation(app,body)
            self.assertTrue(first)
            self.assertEqual([],world_goods.heap_excavation(app,body),'Retry cannot duplicate source output')
            native('dig',**{'from':target,'width_m':1.,'depth_m':.3})
            second=world_goods.heap_excavation(app,body)
            self.assertTrue(second)
            self.assertEqual(0,live_session.current_carried(app.live.session)['sand_kg'])
        piles=[p for p in app.brains.goods.stockpiles if p.get('excavated')]
        self.assertEqual(len(piles),len({p['excavated'] for p in piles}))
        self.assertGreater(sum(sum(p['holds'].values()) for p in piles),80)
        self.assertEqual(0,live_session.current_carried(app.live.session,peer['id'])['sand_kg'])
        self.assertTrue(server.keep_world(app,'save automatic pile receiver'))
        saved=app.room.world_record
        fabrication.validate_ground_stock(app.room.fabrication_record or {},saved,app.room.ground_transfers)
        self.assertEqual(len(piles),len(app.room.ground_transfers['receipts']),'Repeated source receipts compact per material')
        self.stop();self.start();self.post('/api/world/open',{},world);app=self.app.hub.get(world);sid=app.live.session.id
        self.assertEqual(piles,[p for p in app.brains.goods.stockpiles if p.get('excavated')])
        received={}
        for pile in piles:
            at=pile['at_m'];floor=app.live.act({'session':sid,'op':'survey','at':at})['survey']['ground_m']
            request={'session':sid,'pile':pile['name'],'request_id':'bulk-'+pile['excavated'],
                'person':{'eyes_m':[at[0],floor+1.62,at[1]],'facing':[1,0,0]}}
            initial=deepcopy(pile['holds'])
            balance_before=self.personal(app,owner)
            with mock.patch.object(server,'keep_world',return_value=False):
                with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/goods/collect',request,world)
            self.assertEqual(balance_before,self.personal(app,owner),'Failed save cannot credit unsaved stock')
            self.assertEqual(initial,self.post('/api/world/goods/collect',request,world)['collected'])
            self.assertTrue(self.post('/api/world/goods/collect',request,world)['repeated'])
            received.update(initial)
        self.assertEqual(set(received),set(self.personal(app,owner)))
        for s,kg in received.items():self.assertAlmostEqual(kg,self.personal(app,owner)[s],delta=5e-5)
        self.assertEqual({},self.personal(app,peer))
        self.stop();self.start();self.post('/api/world/open',{},world);app=self.app.hub.get(world)
        for s,kg in received.items():self.assertAlmostEqual(kg,self.personal(app,owner)[s],delta=5e-5)
        self.assertTrue(all(not p['holds'] for p in app.brains.goods.stockpiles if p.get('excavated')))
    join=fixture.AutonomousGuests.join
    setup_world=fixture.AutonomousGuests.setup_world

    def batch(self,process=True,legacy_process=False):
        with mock.patch.object(server.secrets,'randbelow',side_effect=[1,851269741]):
            world,owner,app=self.setup_world(legacy_process=legacy_process)
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

    def recovery_fixture(self,seed=1):
        with mock.patch.object(server.secrets,'randbelow',side_effect=[seed,851269740+seed]):
            world,owner,app=self.setup_world()
        app.live.act({'session':app.live.session.id,'op':'poses'})
        program=next(p for p in app.live.session.state['machines']['programs'] if p['kind']=='roam')
        root=next(b for b in app.live.session.state['bodies'] if b['name']==program['body'])
        x,y,z=root['position_m']
        person={'standing_m':[x+.8,y,z+.5],'eyes_m':[x+.8,y+1.1,z+.5],
                'facing':[-.8,0,-.5],'look_direction':[-.8,-1.1,-.5]}
        request={'session':app.live.session.id,'program':program['id'],'recovery':'start','person':person}
        return world,owner,app,program,request

    def test_rover_recovery_is_nearby_personal_bounded_durable_and_preserves_goods(self):
        for seed in (0,1):
            with self.subTest(seed=seed):
                world,owner,app,program,request=self.recovery_fixture(seed)
                other=self.join(world,'Other recovering player')
                sid=app.live.session.id
                def act(op,**args):return app.live.act({'session':sid,'actor':owner['id'],'op':op,**args})
                import machine_tools
                brain=app.brains.of(program['name'])
                machine_tools.run(brain.context(app.brains._ask(app,sid)),machine_tools.Call('dig',{},'routine'))
                self.assertGreater(brain.routine.kg,0,'Recovery must preserve an actually collected load')
                act('poses')
                initial=deepcopy(app.live.session.state['bodies'])
                goods=deepcopy(app.brains.goods.block)
                routines=deepcopy(app.brains.runtime())
                malformed=dict(request,recovery=[])
                with self.assertRaises(urllib.error.HTTPError) as bad:self.post('/api/world/machine',malformed,world)
                self.assertEqual(400,bad.exception.code)
                wheel=next(b for b in initial if b['name'] in program['parts'] and b['name']!=program['body'])
                app.live.act({'session':sid,'actor':other['id'],'op':'wield','name':wheel['name'],'grip':wheel['position_m']})
                with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/machine',request,world)
                app.live.act({'session':sid,'actor':other['id'],'op':'release'})
                tool=next(b for b in initial if b['name'] not in program['parts'] and not b['anchored'])
                act('wield',name=tool['name'],grip=tool['position_m'])
                with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/machine',request,world)
                act('release')
                far=deepcopy(request);far['person']['eyes_m'][0]+=20
                with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/machine',far,world)
                with mock.patch.object(server,'keep_world',return_value=False):
                    with self.assertRaises(urllib.error.HTTPError) as failed:self.post('/api/world/machine',request,world)
                    self.assertEqual(503,failed.exception.code)
                self.assertFalse((app.live.session.state['player_hands'].get(owner['id']) or {}).get('holding'))
                act('poses')
                self.assertEqual(initial,app.live.session.state['bodies'],'Failed/distant acquisition never moves bodies')
                answer=self.post('/api/world/machine',request,world)
                self.assertEqual('grip',answer['hand']['mode']);self.assertFalse(answer['program']['power'])
                self.assertEqual(800,answer['strength_n']);self.assertEqual(60,answer['torque_n_m'])
                # The inorganic starter rover: 43.7416 kg of iron and 5 kg of
                # glass (docs/inorganic-generated-world-checkpoint.md); the
                # 43.5471 kg here was the retired oak-wheel rover.
                self.assertAlmostEqual(48.74162,answer['assembly_mass_kg'],places=3)
                repeated=self.post('/api/world/machine',request,world)
                self.assertEqual(answer['hand'],repeated['hand'],'Retry retains the same grip and accumulated work')
                with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/machine',request,world,other['token'])
                with self.assertRaises(urllib.error.HTTPError):
                    self.post('/api/world/machine',{'session':sid,'program':program['id'],'power':True,
                        'sender':'other guest','seq':1},world,other['token'])
                for command in ({'op':'run','program':program['id'],'power':True},
                                {'op':'behave','program':str(program['id']),'doing':'forward','sender':'recovery-bypass','seq':1,'for_s':1}):
                    with self.assertRaises(urllib.error.HTTPError):
                        self.post('/api/live/act',{'session':sid,**command},world,other['token'])
                self.assertFalse(next(p for p in app.live.session.state['machines']['programs'] if p['id']==program['id'])['power'])
                target=answer['hand']['grip_m'][:];target[1]+=.8
                peak=0
                for _ in range(8):
                    moved=act('step',dt=1/240,n=120,hand=target)
                    hand=moved['player_hands'][owner['id']]
                    peak=max(peak,sum(v*v for v in hand['force_n'])**.5)
                self.assertLessEqual(peak,800.00001);self.assertGreater(hand['work_j'],0)
                self.assertGreater(hand['grip_m'][1],answer['hand']['grip_m'][1]+.2)
                self.assertEqual(goods,app.brains.goods.block,'Recovery preserves actual hopper/processor ledger')
                self.assertEqual(routines,app.brains.runtime(),'Recovery preserves collected hopper load and routine')
                self.assertTrue(server.keep_world(app,'recovery test restart'))
                held_before=deepcopy(hand)
                # Reopen the persisted native world without applying a new grasp/target.
                saved=app.room.world_record
                app.live.shutdown();app.live.session=None;app.live_holder=None
                try:opened=self.post('/api/world/open',{},world)
                except urllib.error.HTTPError as failure:self.fail(failure.read().decode())
                self.assertEqual('grip',opened['hand']['mode']);self.assertEqual(program['body'],opened['hand']['holding'])
                self.assertAlmostEqual(held_before['work_j'],opened['hand']['work_j'],places=4)
                self.assertEqual(saved['t_s'],app.room.world_record['t_s'])
                self.assertEqual(len(saved['joints']),len(app.room.world_record['joints']))
                self.assertEqual(len(saved['bodies']),len(app.room.world_record['bodies']))
                # Native hinge angles are recomputed from restored float poses;
                # work/time/load remain durable, with existing pose wire precision.
                for a,b in zip(moved['bodies'],opened['bodies']):
                    self.assertEqual(a['name'],b['name']);self.assertEqual(a['mass_kg'],b['mass_kg'])
                    for x,y in zip(a['position_m'],b['position_m']):self.assertAlmostEqual(x,y,places=5)
                request['session']=app.live.session.id
                request['recovery']='release'
                with mock.patch.object(server,'keep_world',return_value=False):
                    with self.assertRaises(urllib.error.HTTPError) as failed:self.post('/api/world/machine',request,world)
                    self.assertEqual(503,failed.exception.code)
                    self.assertFalse((app.live.session.state['player_hands'][owner['id']]).get('holding'))
                self.post('/api/world/machine',request,world)
                released=self.post('/api/world/machine',request,world)
                self.assertFalse(released['recovering']);self.assertFalse(released['program']['power'])
                self.assertEqual(goods,app.brains.goods.block)
                self.assertEqual(routines,app.brains.runtime())

    def test_browser_rover_recovery_click_lift_readouts_reload_and_release(self):
        if not qa_browser.CHROME.is_file():self.skipTest('Chrome not installed')
        world,owner,app,program,request=self.recovery_fixture()
        # Declare the UI recovery-needed predicate, as the routine regression
        # does. Hand lifting/work remain measured by the real native assembly;
        # this fixture does not claim to reproduce natural escape exhaustion.
        brain=app.brains.of(program['name'])
        brain.routine.recovery={'at_m':[program['at_m'][0],program['at_m'][2]],'since_s':0.,
            'reason':'Controlled recovery-needed browser fixture'}
        brain.routine.paused_by='recovery needed'
        self.assertTrue(server.keep_world(app,'recovery UI fixture'))
        chrome=qa_browser.Chrome(1280,800);self.addCleanup(chrome.close)
        page=chrome.page;page.send('Page.enable');page.send('Runtime.enable')
        def wait(expression):
            deadline=time.monotonic()+35
            while time.monotonic()<deadline:
                try:
                    if page.evaluate(expression):return
                except (RuntimeError,TimeoutError):pass
                time.sleep(.1)
            info=page.evaluate('({last:document.querySelector("#details-last-text")?.textContent,picked:document.querySelector("#picked")?.textContent,programs:banjoRoom.world.machines?.programs?.map(p=>({name:p.name,kind:p.kind,parts:p.parts}))})')
            errors=[e for e in page.events if e.get('method')=='Runtime.exceptionThrown']
            self.fail('Recovery browser did not reach '+expression+'; '+str(info)+'; '+str(errors))
        def click(selector):
            # Press only once the element itself is under the pointer, so a
            # click can never land on whatever a re-render left there.
            under=('(()=>{const b=document.querySelector('+json.dumps(selector)+');if(!b||b.disabled)return null;b.scrollIntoView({block:"center"});'
                   'const r=b.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2,e=document.elementFromPoint(x,y);'
                   'return e && b.contains(e) ? {x,y} : null})()')
            wait(under)
            spot=page.evaluate(under)
            # Held for 0.2 s like a person's click, longer than the picked
            # card's 150 ms rebuild: the rebuild must not swallow the click.
            page.send('Input.dispatchMouseEvent',{'type':'mousePressed','button':'left','clickCount':1,**spot})
            time.sleep(.2)
            page.send('Input.dispatchMouseEvent',{'type':'mouseReleased','button':'left','clickCount':1,**spot})
        def details():
            # The picked card lives in the right rail, which starts folded
            # away (dcd94bae); Details in the bottom bar opens it (68bad3ca).
            if page.evaluate('document.body.classList.contains("panel-away")'):click('#panel-details')
            wait('!document.body.classList.contains("panel-away")')
        page.send('Page.navigate',{'url':self.base+f'/world?world={world}&hold=1'})
        wait('window.banjoRoom?.ready()')
        # Position the test observer beside the actual chassis; acquire through
        # the visible button and move it through ordinary hand targets/keys.
        page.evaluate('(()=>{const p=banjoRoom.world.bodies.get("rover").mesh.position;banjoRoom.standAt(p.x+.8,p.y+1.1,p.z+.5);banjoRoom.lookAt(p.x,p.y,p.z);banjoRoom.pick("rover");})()')
        wait('!!document.querySelector("#picked [data-rover-command=recover]")')
        details()
        click('#picked [data-rover-command=recover]')
        wait('banjoRoom.world.held?.recovery')
        self.assertTrue(page.evaluate('banjoRoom.controls().cursorFree'),
                        'Clicking recovery safely leaves the player in Cursor mode')
        self.assertFalse(page.evaluate('banjoRoom.world.held.guide || false'))
        initial=page.evaluate('banjoRoom.world.held.hand.grip_m')
        page.evaluate('(()=>{const p=banjoRoom.camera.position;banjoRoom.lookAt(p.x,p.y+1,p.z-.3);banjoRoom.resume();})()')
        wait(f'banjoRoom.world.held.hand.grip_m[1]>{initial[1]+.3}')
        wait('banjoRoom.world.held.hand.work_j>0')
        self.assertGreater(sum(v*v for v in page.evaluate('banjoRoom.world.held.hand.force_n')),0.)
        page.send('Input.dispatchKeyEvent',{'type':'keyDown','code':'KeyQ','key':'q'})
        page.send('Input.dispatchKeyEvent',{'type':'keyUp','code':'KeyQ','key':'q'})
        wait('document.querySelector("#details-last-text").textContent.includes("Release the rover before packing")')
        self.assertTrue(page.evaluate('document.querySelector("#details-last").checkVisibility()'),
                        'The selected component card must not hide the refusal')
        self.assertTrue(page.evaluate('!!banjoRoom.world.held?.recovery'))
        page.evaluate('banjoRoom.hold()')
        wait('!banjoRoom.world.busy')
        held=page.evaluate('banjoRoom.world.held.hand')
        self.assertTrue(server.keep_world(app,'browser recovery reload'))
        page.send('Page.reload',{'ignoreCache':True})
        wait('window.banjoRoom?.ready() && banjoRoom.world.held?.recovery')
        self.assertFalse(page.evaluate('banjoRoom.world.held.guide || false'))
        self.assertAlmostEqual(held['work_j'],page.evaluate('banjoRoom.world.held.hand.work_j'),places=3)
        page.evaluate('(()=>{const p=banjoRoom.world.bodies.get("rover").mesh.position;banjoRoom.lookAt(p.x,p.y,p.z);banjoRoom.pick("rover");})()')
        wait('document.querySelector("#picked [data-rover-command=recover]")?.textContent==="Release rover"')
        details()
        self.assertFalse(page.evaluate('!!document.querySelector("#picked .pk-component-grid")'))
        import base64
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/'rover-recovery.png').write_bytes(base64.b64decode(page.send('Page.captureScreenshot',{'format':'png'})['data']))
        click('#picked [data-rover-command=recover]')
        wait('!banjoRoom.world.held')
        self.assertFalse(page.evaluate('banjoRoom.world.machines.programs.find(p=>p.body==="rover").power'))
        self.assertEqual([],[e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])

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

    def test_browser_shows_output_stock_and_collects_without_fabricated_flights(self):
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
        wait(f'banjoRoom.world.goods.stockpiles.some(p=>p.name==={json.dumps(pile["name"])} && p.holds_kg.copper>0)')
        self.assertFalse(page.evaluate('banjoRoom.scene.getObjectByName("resource-packets").children.some(c=>c.userData.transferKind)'))
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
        self.assertFalse(page.evaluate('banjoRoom.scene.getObjectByName("resource-packets").children.some(c=>c.userData.transferKind)'))
        self.assertEqual({},pile['holds']);self.assertEqual(before,self.personal(app,player))
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        shot=page.send('Page.captureScreenshot',{'format':'png'})['data']
        (out/'collected.png').write_bytes(base64.b64decode(shot))
        self.assertEqual([],[e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])

    def test_generated_rover_dig_clearance_preserves_support_and_still_collects_a_load(self):
        import machine_tools
        for terrain_seed,resource_seed in ((1,851269741),(0,851269742)):
            with self.subTest(terrain_seed=terrain_seed),mock.patch.object(server.secrets,'randbelow',side_effect=[terrain_seed,resource_seed]):
                world,owner,app=self.setup_world()
                programs=app.live.act({'session':app.live.session.id,'op':'poses'})['machines']['programs']
                program=next(p for p in programs if p['name']=='rover')
                x,y,z=program['at_m'];sid=app.live.session.id
                before=app.live.session.send(op='snapshot')['snapshot']
                with self.assertRaises(LiveError) as blocked:
                    app.live.act({'session':sid,'op':'dig','program':program['id'],'from':[x,z],
                                  'to':[x,z],'width_m':.5,'depth_m':.15})
                self.assertIn('support below',str(blocked.exception))
                self.assertEqual(before,app.live.session.send(op='snapshot')['snapshot'])
                brain=app.brains.of('rover')
                ctx=brain.context(app.brains._ask(app,sid))
                answer=machine_tools.run(ctx,machine_tools.Call('dig',{},'routine'))
                self.assertFalse(answer.get('failed'),answer)
                self.assertGreater(brain.routine.kg,0,answer)
                self.assertLessEqual(brain.routine.kg,brain.routine.hopper_kg)
                self.assertIn('dug',answer['did'])
                print(f"    generated terrain {terrain_seed}: support refused without mutation; actual hopper {brain.routine.kg:.6f} kg")

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
        wait('document.querySelector("#picked .rover-card")')
        probes=page.evaluate('banjoRoom.world.machines.programs.find(p=>p.body==="rover").sensors')
        self.assertEqual(10,len(probes));self.assertEqual(5,sum(p['kind']=='ground' for p in probes))
        self.assertEqual(2,sum(p['kind']=='ground' and p['stops']<0 for p in probes))
        self.assertFalse(page.evaluate('!!document.querySelector("[data-rover-sensors]")'))
        self.assertTrue(all('reading_m' in p and 'sees' in p for p in probes))
        middle=next(p for p in probes if p['kind']=='ground' and p['side']==0 and p['stops']>0)
        x,y,z=middle['at_m']
        # The real native dig/report path, not injected sensor readings.
        page.evaluate(f'banjoRoom.standAt({x},banjoRoom.groundAt({x},{z})+1.6,{z+1})')
        answer=page.evaluate(f'banjoRoom.digAt({x},{z},.5,.6)',await_promise=True)
        self.assertGreater((answer.get('dug') or {}).get('kg',0),0,'The native excavation must actually happen')
        page.evaluate('banjoRoom.resume()')
        wait('banjoRoom.world.machines.programs.find(p=>p.body==="rover").sensors.some(p=>p.kind==="ground"&&p.sees)')
        self.assertGreater(max(abs(p['reading_m']) for p in page.evaluate('banjoRoom.world.machines.programs.find(p=>p.body==="rover").sensors') if p['kind']=='ground'),0.)
        page.evaluate('banjoRoom.hold()')
        page.evaluate('document.querySelector("#panel-details").click()')
        wait('!document.body.classList.contains("panel-away")')
        page.evaluate('document.querySelector("#picked .rover-card button:not([data-rover-command])").click()')
        wait('document.querySelector("#chat-recipient").value==="robot:rover"')
        page.evaluate('document.querySelector("#ask-text").value="status";document.querySelector("#ask").requestSubmit()')
        wait('document.querySelector("#chat").textContent.includes("My battery is at") && !document.querySelector("#ask-send").disabled')
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
        pick=next(r for r in recipes['templates'] if r['name']=='Personal field pick')
        self.assertTrue(pick['readiness']['ready_as_drawn'],pick)
        chrome=qa_browser.Chrome(1280,800);self.addCleanup(chrome.close)
        page=chrome.page;page.send('Page.enable');page.send('Runtime.enable')
        page.send('Page.addScriptToEvaluateOnNewDocument',{'source':
            'if(location.origin==='+json.dumps(self.base)+')localStorage.setItem('+json.dumps('banjo.player.'+world)+','+json.dumps(owner['token'])+');'})
        def wait(expression):
            deadline=time.monotonic()+40
            while time.monotonic()<deadline:
                if page.evaluate('Boolean('+expression+')'):return
                time.sleep(.12)
            self.fail('Browser did not reach '+expression+'; '+str(page.evaluate('document.body.innerText.slice(-1200)')))
        def click(selector):
            target=json.dumps(selector)
            under=f'(()=>{{const e=document.querySelector({target});if(!e||e.disabled)return false;e.scrollIntoView({{block:"center"}});const r=e.getBoundingClientRect(),h=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return r.width>0&&r.height>0&&!!h&&(h===e||e.contains(h))}})()'
            wait(under)
            point=page.evaluate(f'(()=>{{const r=document.querySelector({target}).getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2}}}})()')
            for kind in ('mousePressed','mouseReleased'):
                page.send('Input.dispatchMouseEvent',{'type':kind,'button':'left','clickCount':1,**point})
        page.send('Page.navigate',{'url':self.base+f'/world?world={world}&workshop=1&tab=recipes'})
        click('[data-open-recipe="field-pick:Personal field pick"]')
        wait('document.querySelectorAll("#ws-parts li").length===2 && !document.querySelector("#ws-component-chat-text").disabled')
        selected_url=page.evaluate('location.href')
        page.send('Page.navigate',{'url':'about:blank'})
        wait('location.href === "about:blank"')
        page.send('Page.navigate',{'url':selected_url})
        wait('document.querySelectorAll("#ws-parts li").length===2 && !document.querySelector("#ws-component-chat-text").disabled')
        def chat(text):
            if not page.evaluate('document.body.classList.contains("ws-chat-open")'):click('[data-customize-item]')
            click('#ws-component-chat-text')
            page.send('Input.insertText',{'text':text})
            self.assertEqual(text,page.evaluate('document.querySelector("#ws-component-chat-text").value'))
            page.evaluate('document.querySelector("#ws-component-chat").requestSubmit()')
            wait('!document.querySelector("#ws-component-chat-text").disabled && document.querySelector("#ws-component-chat-text").value===""')
        chat('make the head iron')
        parts=page.evaluate('[...document.querySelectorAll("#ws-lab-components [data-component]")].map(e=>e.textContent)')
        self.assertTrue(any('haft' in p and 'oak' in p for p in parts),parts)
        self.assertTrue(any('arm' in p and 'iron' in p for p in parts),parts)
        click('#ws-draft-save')
        wait('document.querySelector("#ws-lab-draft").textContent.includes("Saved to Recipes")')
        # Review the monolithic oak source and prove actual installation/debit.
        chat('make the whole object oak')
        before=workshop_library.rack(app)
        # New worlds start with generated installations (starter machines and
        # their foundation pads, 23e48727); Make must add exactly one more and
        # leave those exactly as they were.
        installs=json.loads(json.dumps(app.room.workshop_installs))
        installed={r['root_body'] for r in installs}
        page.evaluate('document.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",bubbles:true}))')
        click('#ws-draft-build')
        def paid_click(selector):
            wait(f'document.querySelector({json.dumps(selector)}) && !document.querySelector({json.dumps(selector)}).disabled')
            if page.evaluate(f'document.querySelector({json.dumps(selector)}).closest("#ws-remake-supplies") && !document.querySelector("#ws-remake-supplies").open'):
                click('#ws-remake-supplies summary')
            click(selector)
        # Ordinary generated workbench, with explicit shared-stock selection
        # and an actual native battery debit; no seeded process supply.
        wait('document.querySelector("#ws-remake-supplies summary")')
        click('#ws-remake-supplies summary')
        paid_click('#ws-remake-stock-shared')
        paid_click('#ws-remake-connect')
        paid_click('#ws-remake-charge-wait')
        paid_click('#ws-remake-energy')
        paid_click('#ws-remake-start')
        paid_click('#ws-remake-step')
        paid_click('#ws-remake-place')
        wait('document.querySelector("#ws-remake a")?.textContent==="Collect in World"')
        made=[r for r in app.room.workshop_installs if r['root_body'] not in installed]
        self.assertEqual(1,len(made),made)
        self.assertEqual(installs,[r for r in app.room.workshop_installs if r['root_body'] in installed])
        before_oak=next(r['mass_kg'] for r in before['materials'] if r['material']=='oak')
        after_oak=next(r['mass_kg'] for r in workshop_library.rack(app)['materials'] if r['material']=='oak')
        self.assertGreater(before_oak,after_oak)
        self.assertEqual(0,app.room.fabrication_record['config']['energy_j'])
        self.assertEqual('installed',next(iter(app.room.fabrication_record['jobs'].values()))['status'])
        self.assertEqual([],[e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])

    def test_component_thumbnails_keep_rover_and_pick_assembled_without_native_changes(self):
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
        geometry='[...banjoRoom.world.bodies].map(([name,b])=>({name,position:b.mesh.position.toArray(),rotation:b.mesh.quaternion.toArray(),vertices:[...b.mesh.geometry.attributes.position.array],opacity:(Array.isArray(b.mesh.material)?b.mesh.material:[b.mesh.material]).map(m=>m.opacity)}))'
        drawing=page.evaluate(geometry)
        def inspect(name):
            page.evaluate('(()=>{const r=banjoRoom,p=r.world.bodies.get('+json.dumps(name)+').mesh.position;r.standAt(p.x,p.y+1.62,p.z+1.1);r.lookAt(p.x,p.y,p.z)})()')
            x,y=page.evaluate('(()=>{const b=document.querySelector("canvas").getBoundingClientRect();return [b.x+b.width/2,b.y+b.height/2]})()')
            page.send('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x,'y':y})
            wait('banjoRoom.world.aim?.name==='+json.dumps(name))
            # Alt+click inspects without starting/stopping a machine or lifting a tool.
            for kind in ('mousePressed','mouseReleased'):
                page.send('Input.dispatchMouseEvent',{'type':kind,'x':x,'y':y,'button':'left','clickCount':1,'modifiers':1})
            wait('banjoRoom.picked().name==='+json.dumps(name))
        inspect('rover')
        wait('banjoRoom.components()?.length>6')
        components=page.evaluate('banjoRoom.components()')
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
        self.assertTrue(all(c['name'] and c['material'] for c in components))
        self.assertEqual(1,page.evaluate('document.querySelectorAll("#picked .rover-card").length'))
        self.assertEqual(1,page.evaluate('document.querySelectorAll("#picked .rover-card > canvas, #picked .rover-card > img").length'))
        self.assertIn('Energy',page.evaluate('document.querySelector("#picked .rover-card").textContent'))
        self.assertTrue(page.evaluate('!!document.querySelector("#picked .rover-card [data-rover-command]")'))
        self.assertFalse(page.evaluate('!!document.querySelector("#picked .pk-component-grid")'))
        self.assertIsNone(page.evaluate('banjoRoom.reveal()'))
        self.assertFalse(page.evaluate('!!banjoRoom.scene.getObjectByName("selection-structure-reveal")'))
        self.assertEqual(drawing,page.evaluate(geometry),'inspection moved or faded the world geometry')
        time.sleep(3.3);self.assertEqual(components,page.evaluate('banjoRoom.components()'))
        import base64
        output=ROOT/'build/resource-flow';output.mkdir(parents=True,exist_ok=True)
        (output/'component-thumbnails.png').write_bytes(base64.b64decode(page.send('Page.captureScreenshot',{'format':'png'})['data']))
        self.assertFalse(page.evaluate('!!document.querySelector("#picked .pk-reveal")'))
        self.assertIsNone(page.evaluate('banjoRoom.reveal()'))
        inspect('field pick')
        wait('banjoRoom.components()?.length===2')
        parts=page.evaluate('banjoRoom.components()')
        self.assertEqual({'haft','arm'},{p['name'] for p in parts})
        self.assertEqual(len(parts),page.evaluate('document.querySelectorAll("#picked .pk-component-grid figure").length'))
        wait('[...document.querySelectorAll("#picked .pk-component-grid img")].every(i=>i.complete && i.naturalWidth>0)')
        self.assertEqual(len(parts),page.evaluate('document.querySelectorAll("#picked .pk-component-grid img").length'))
        self.assertEqual(page.evaluate('banjoRoom.world.bodies.get("field pick").cells.length'),sum(p['cells'] for p in parts))
        self.assertIsNone(page.evaluate('banjoRoom.reveal()'))
        self.assertEqual(drawing,page.evaluate(geometry))
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
        # Paid native cuts create reachable physical material; collecting it
        # is explicit. Raw storage retains its existing unlimited mass policy.
        wait('document.querySelector("#world-load-meter b").textContent==="Loosen → Click → Inventory"')
        self.assertIn('Raw storage',page.evaluate('document.querySelector("#world-load-meter").textContent'))
        self.assertIn('loose material',page.evaluate('document.querySelector("#world-load-meter").textContent'))
        self.assertEqual(0,page.evaluate('banjoRoom.scene.getObjectByName("resource-packets").children.filter(c=>c.userData.resourceDeposit).length'))
        wait('document.querySelector("#material-preview details canvas")')
        self.assertIn('Nearby materials',page.evaluate('document.querySelector("#material-preview").textContent'))
        def mode(value):
            page.evaluate('document.querySelector("[data-game-menu]").click()')
            page.evaluate(f'(()=>{{const e=document.querySelector("#game-menu-movement select");e.value={json.dumps(value)};e.dispatchEvent(new Event("change"))}})()')
        mode('fly');page.evaluate('banjoRoom.standAt(0,8,0)')
        mode('gravity')
        wait('banjoRoom.camera.position.y<5')
        room=self.app.hub.get(first)
        floor=room.live.act({'session':room.live.session.id,'op':'survey','at':[0,0]})['survey']['ground_m']
        wait(f'Math.abs(banjoRoom.camera.position.y-{floor+1.6})<.03')
        # Within 3 cm can still be the last frames of the fall; a jump only
        # starts from standing (and a held key never relaunches), so press
        # Space once the player has actually come to rest.
        base_y=None
        for _ in range(100):
            y=page.evaluate('banjoRoom.camera.position.y')
            if base_y is not None and abs(y-base_y)<1e-6:break
            base_y=y;time.sleep(.15)
        else:self.fail('The player never came to rest after falling')
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
                entry=page.evaluate('({pose:banjoRoom.camera.position.toArray(),water:banjoRoom.world.inWater})')
                self.assertLess(entry['pose'][1]-1.6,entry['water']['level']-.25)
                wait('document.querySelector("[data-movement]").textContent.includes("immersed")')
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
                    'shore':spots['shore'],'hill_rise_m':pose[1]-(y+1.6),'actual_water_entry':entry})
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
        page.evaluate('banjoRoom.waterForThePerson((x,z)=>({level:poolLevel,depth:poolLevel-banjoRoom.groundAt(x,z),u:.4,w:0}))')
        wait('banjoRoom.world.inWater?.carried>.5')
        start=page.evaluate('banjoRoom.camera.position.toArray()');time.sleep(.8)
        finish=page.evaluate('banjoRoom.camera.position.toArray()')
        self.assertGreater(finish[0]-start[0],.15,'declared deep current carries the controller without keys')
        wait('document.querySelector("[data-water-flow]").textContent.includes("Flow E")')
        page.evaluate('banjoRoom.waterForThePerson(null)')
        self.assertEqual([],[e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/'movement-acceptance.json').write_text(json.dumps({'generated_crossings':reports,
            'declared_deep_pool_m':2.3,'swim_rise_dive_recovery':True,
            'declared_current_m_s':.4,'declared_current_drift_m':finish[0]-start[0],
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
        # A playable world holds only inorganic stock (game_materials, since
        # caeb6424): the loose recovered aluminum is its raw build material.
        pile=next(p for p in app.brains.goods.stockpiles if (p.get('holds') or {}).get('aluminum',0)>25)
        at=pile['at_m'];sid=app.live.session.id
        floor=app.live.act({'session':sid,'op':'survey','at':at})['survey']['ground_m']
        initial=pile['holds']['aluminum']
        def shared():
            token=workshop_library.REQUEST_OWNER.set(owner['id'])
            try:return {r['material']:r['shared_kg'] for r in workshop_library.rack(app)['materials']}
            finally:workshop_library.REQUEST_OWNER.reset(token)
        shared_before=shared()
        answer=self.post('/api/world/goods/collect',{'session':sid,'pile':pile['name'],
            'request_id':'collect-aluminum','person':{'eyes_m':[at[0],floor+1.62,at[1]],'facing':[0,0,-1]}},world)
        self.assertEqual({'aluminum':initial},answer['collected'])
        self.assertEqual({},pile['holds'])
        self.assertEqual({'aluminum':initial},self.personal(app,owner))
        self.assertEqual(shared_before,shared(),'Personal collection leaves the shared rack as it was')

    def delivery_fixture(self):
        world,owner,app,source,output,_=self.batch(process=False)
        program=next(p for p in app.live.session.state['machines']['programs'] if p['kind']=='roam')
        self.post('/api/world/machine',{'session':app.live.session.id,'program':program['id'],
                  'power':False,'sender':'delivery-test','seq':1},world)
        intake=app.brains.goods.by_name(app.brains.of(source['machine']).routine.intake)
        x,z=intake['at_m']
        floor=app.live.act({'session':app.live.session.id,'op':'survey','at':[x,z]})['survey']['ground_m']
        person={'eyes_m':[x,floor+1.62,z],'facing':[0,0,-1]}
        collected=self.post('/api/world/goods/collect',{'session':app.live.session.id,'pile':intake['name'],
                            'person':person,'request_id':'finite-input-stock'},world)['collected']
        self.assertGreater(collected['copper ore'],5)
        self.assertEqual({},intake['holds'])
        request={'session':app.live.session.id,'pile':intake['name'],'person':person,
                 'request_id':'personal-input','substance':'copper ore','mass_kg':5.}
        return world,owner,app,source,intake,output,collected,request

    def test_personal_input_delivery_failed_save_retry_processing_peer_and_restart(self):
        world,owner,app,source,intake,output,initial,request=self.delivery_fixture()
        peer=self.join(world,'Other loader')
        for invalid in ({'mass_kg':25.},{'mass_kg':True},{'mass_kg':.0000001},{'substance':'copper'},
                        {'pile':output['name']},{'person':{'eyes_m':[99,1.62,99],'facing':[0,0,-1]}}):
            with self.assertRaises(urllib.error.HTTPError):
                self.post('/api/world/goods/deliver',{**request,**invalid},world)
            self.assertEqual({},intake['holds']);self.assertEqual(initial,self.personal(app,owner))
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/goods/deliver',request,world,peer['token'])
        with mock.patch.object(app.store,'save',side_effect=OSError('disk full')):
            with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/goods/deliver',request,world)
        self.assertEqual({'copper ore':5.},intake['holds'])
        self.assertEqual(initial['copper ore']-5,self.personal(app,owner)['copper ore'])
        self.assertTrue(world_goods.pending_deliveries(app,owner['id'])[0]['received'])
        release={'session':app.live.session.id,'action':'release','request_id':request['request_id']}
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/goods/deliver',release,world)
        for _ in range(2):self.assertTrue(self.post('/api/world/goods/deliver',request,world)['repeated'])
        self.assertEqual({'copper ore':5.},intake['holds'])
        self.assertEqual([],world_goods.pending_deliveries(app,owner['id']))
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/goods/deliver',request,world,peer['token'])
        self.process_batch(app,output)
        self.assertEqual({},intake['holds']);self.assertEqual({'copper':1.5},output['holds'])
        x,z=output['at_m'];floor=app.live.act({'session':app.live.session.id,'op':'survey','at':[x,z]})['survey']['ground_m']
        pickup={'session':app.live.session.id,'pile':output['name'],'request_id':'delivered-copper-output',
                'person':{'eyes_m':[x,floor+1.62,z],'facing':[0,0,-1]}}
        self.post('/api/world/goods/collect',pickup,world)
        remaining={'copper ore':initial['copper ore']-5,'copper':1.5}
        self.assertEqual(remaining,self.personal(app,owner));self.assertEqual({},self.personal(app,peer))
        self.stop();self.start();self.post('/api/world/open',{},world)
        app=self.app.hub.get(world);request['session']=app.live.session.id
        self.assertTrue(self.post('/api/world/goods/deliver',request,world)['repeated'])
        self.assertEqual({},app.brains.goods.by_name(intake['name'])['holds'])
        self.assertEqual(remaining,self.personal(app,owner));self.assertEqual({},self.personal(app,peer))

    def test_input_source_reservation_restart_return_and_lost_save_ack(self):
        world,owner,app,source,intake,output,initial,request=self.delivery_fixture()
        put=app.brains.goods.put
        def lost_receiving_ack(*args,**kwargs):
            put(*args,**kwargs);raise OSError('receiving write unavailable after mutation')
        with mock.patch.object(app.brains.goods,'put',side_effect=lost_receiving_ack):
            with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/goods/deliver',request,world)
        self.assertEqual({},intake['holds'])
        self.assertEqual(initial['copper ore']-5,self.personal(app,owner)['copper ore'])
        self.stop();self.start();self.post('/api/world/open',{},world)
        app=self.app.hub.get(world)
        pending=world_goods.pending_deliveries(app,owner['id']);self.assertEqual(1,len(pending))
        self.assertFalse(pending[0]['received'])
        release={'session':app.live.session.id,'action':'release','request_id':request['request_id']}
        for _ in range(2):self.assertTrue(self.post('/api/world/goods/deliver',release,world)['released'])
        self.assertEqual(initial,self.personal(app,owner))
        request.update(session=app.live.session.id,request_id='delivery-lost-ack')
        save=app.store.save
        def lost_ack(room):save(room);raise OSError('saved but acknowledgement lost')
        with mock.patch.object(app.store,'save',side_effect=lost_ack):
            with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/goods/deliver',request,world)
        self.assertIn(request['request_id'],app.room.goods_durable_deliveries)
        self.stop();self.start();self.post('/api/world/open',{},world)
        app=self.app.hub.get(world);request['session']=app.live.session.id
        self.assertTrue(self.post('/api/world/goods/deliver',request,world)['repeated'])
        self.assertEqual({'copper ore':5.},app.brains.goods.by_name(intake['name'])['holds'])
        self.assertEqual(initial['copper ore']-5,self.personal(app,owner)['copper ore'])
        self.assertEqual([],world_goods.pending_deliveries(app,owner['id']))
        with self.assertRaises(urllib.error.HTTPError):
            self.post('/api/world/goods/deliver',{**release,'session':app.live.session.id,'request_id':request['request_id']},world)

    def test_browser_loads_personal_ore_into_selected_machine_input(self):
        if not qa_browser.CHROME.is_file():self.skipTest('Chrome not installed')
        world,owner,app,source,intake,output,initial,request=self.delivery_fixture()
        chrome=qa_browser.Chrome(1280,800);self.addCleanup(chrome.close)
        page=chrome.page;page.send('Page.enable');page.send('Runtime.enable')
        page.send('Page.addScriptToEvaluateOnNewDocument',{'source':
            'localStorage.setItem('+json.dumps('banjo.player.'+world)+','+json.dumps(owner['token'])+');'})
        def wait(expression):
            deadline=time.monotonic()+35
            while time.monotonic()<deadline:
                if page.evaluate('Boolean('+expression+')'):return
                time.sleep(.1)
            self.fail(expression+'; '+str(page.evaluate('({picked:document.querySelector("#picked")?.textContent,programs:window.banjoRoom?.world.machines?.programs,goods:window.banjoRoom?.world.goods,position:window.banjoRoom?.camera.position.toArray(),errors:document.querySelector("#panel-state")?.textContent,notice:document.querySelector("#ws-notice")?.textContent,deliveries:document.querySelector("#ws-inv-deliveries")?.textContent})')))
        def click(selector):
            wait('(()=>{const b=document.querySelector('+json.dumps(selector)+');if(!b||b.disabled)return false;b.scrollIntoView({block:"center"});const r=b.getBoundingClientRect(),e=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return r.width>0&&r.height>0&&!!e&&(e===b||b.contains(e))})()')
            spot=page.evaluate('(()=>{const b=document.querySelector('+json.dumps(selector)+');b.scrollIntoView({block:"center"});const r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()')
            for kind in ('mousePressed','mouseReleased'):
                page.send('Input.dispatchMouseEvent',{'type':kind,'button':'left','clickCount':1,**spot})
        page.send('Page.navigate',{'url':self.base+f'/world?world={world}&hold=1'})
        wait('window.banjoRoom?.ready()')
        eyes=request['person']['eyes_m']
        program=next(p for p in app.live.session.state['machines']['programs'] if p['name']==source['machine'])
        page.evaluate('banjoRoom.standAt('+','.join(map(str,eyes))+');banjoRoom.pick('+json.dumps(program['body'])+');')
        wait('document.querySelector("[data-input-delivery] button:not(:disabled)")')
        # The picked card lives in the right rail, which starts folded away
        # (dcd94bae); Details in the bottom bar opens it (68bad3ca).
        click('#panel-details')
        wait('!document.body.classList.contains("panel-away")')
        wait('(()=>{const b=document.querySelector("[data-input-delivery] button");b.scrollIntoView({block:"center"});'
             'const r=b.getBoundingClientRect(),e=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return !!e && b.contains(e)})()')
        click('[data-input-delivery] button')
        wait('document.querySelector("[data-deliver-substance=\\"copper ore\\"]:not(:disabled)")')
        click('[data-deliver-substance="copper ore"]')
        wait('document.querySelector("#details-last-text")?.textContent.includes("→ Input")')
        self.assertEqual({'copper ore':5.},app.brains.goods.by_name(intake['name'])['holds'])
        self.assertEqual(initial['copper ore']-5,self.personal(app,owner)['copper ore'])
        self.assertEqual([],[e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])
        import base64
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/'personal-input-delivery.png').write_bytes(base64.b64decode(page.send('Page.captureScreenshot',{'format':'png'})['data']))
        put=app.brains.goods.put
        def unavailable(*args,**kwargs):put(*args,**kwargs);raise OSError('receiving acknowledgement lost')
        with mock.patch.object(app.brains.goods,'put',side_effect=unavailable):
            with self.assertRaises(urllib.error.HTTPError):
                self.post('/api/world/goods/deliver',{**request,'session':app.live.session.id,
                          'request_id':'browser-reserved-input'},world)
        self.assertEqual(initial['copper ore']-10,self.personal(app,owner)['copper ore'])
        page.send('Page.navigate',{'url':self.base+f'/world?world={world}&workshop=1&tab=inventory'})
        wait('document.querySelector("[data-delivery-reservation=browser-reserved-input]")')
        self.assertIn('5 kg',page.evaluate('document.querySelector("[data-delivery-reservation=browser-reserved-input]").textContent'))
        click('[data-delivery-reservation=browser-reserved-input] .ws-inventory-actions button:last-child')
        wait('!document.querySelector("[data-delivery-reservation=browser-reserved-input]")')
        self.assertEqual(initial['copper ore']-5,self.personal(app,owner)['copper ore'])
        self.assertEqual({'copper ore':5.},app.brains.goods.by_name(intake['name'])['holds'])
        self.assertEqual([],[e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])


if __name__=='__main__':unittest.main()
