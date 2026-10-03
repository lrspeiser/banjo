"""Authenticated native ground accounts, independent budgets and durable restore.

API excavation here is the bounded terrain-edit lane. Actual tool work and
owner attribution during shared stepping are tested by banjo_ground_work_tests.
"""
from copy import deepcopy
import base64
import json
from pathlib import Path
import time
import unittest
from unittest import mock
import urllib.error
import world_goods_tests as flow

ROOT=Path(__file__).resolve().parents[1]


class PrivateGround(unittest.TestCase):
    setUp=flow.GoodsJourney.setUp
    tearDown=flow.GoodsJourney.tearDown
    start=flow.GoodsJourney.start
    stop=flow.GoodsJourney.stop
    get=flow.GoodsJourney.get
    post=flow.GoodsJourney.post
    join=flow.GoodsJourney.join
    setup_world=flow.GoodsJourney.setup_world

    def storage_fixture(self):
        with mock.patch.object(flow.server.secrets,'randbelow',side_effect=[0,851269740]):
            world,alice,app=self.setup_world()
        bob=self.join(world,'Other gatherer')
        def dig(x,z,player=None):
            return self.post('/api/live/act',{'session':app.live.session.id,'op':'dig',
                'from':[x,z],'to':[x,z],'width_m':.4,'depth_m':.1},world,player)['carried']
        a=dig(-1,0);b=dig(2,-1,bob['token'])
        legacy=app.live.act({'session':app.live.session.id,'op':'dig',
            'from':[3,1],'to':[3,1],'width_m':.4,'depth_m':.1})['carried']
        self.assertGreater(a['total_kg'],0);self.assertGreater(b['total_kg'],0);self.assertGreater(legacy['total_kg'],0)
        self.assertTrue(flow.server.keep_world(app,'save raw storage source fixture'))
        return world,alice,bob,app,a,b,legacy

    def raw_request(self,app,ident,account,**extra):
        return {'scene':app.room.scene,'session':app.live.session.id,'request_id':ident,
            'revision':app.room.fabrication_record['revision'],
            **{s+'_m3':account.get(s+'_m3',0) for s in ('sand','soil','rock')},**extra}

    def test_authenticated_storage_recovery_ownership_failures_and_full_restart(self):
        world,alice,bob,app,a,b,legacy=self.storage_fixture()
        def inv(token=None):return self.post('/api/workshop/inventory',{},world,token)
        def call(op,request,token=None):
            try:return self.post('/api/world/fabrication/'+op,request,world,token)
            except urllib.error.HTTPError as exc:
                exc.add_note(exc.read().decode());raise
        request=self.raw_request(app,'owned-raw-store-0001',a)
        before=deepcopy(app.room.world_record['ground'])
        with mock.patch.object(app.store,'save',side_effect=OSError('disk full')):
            with self.assertRaises(urllib.error.HTTPError) as refused:call('store_ground',request)
            self.assertEqual(503,refused.exception.code)
        self.assertEqual(before,flow.server.workshop_install._snapshot(app.live)['ground'])
        self.assertEqual([],inv()['stored_ground'])
        result=call('store_ground',request)
        self.assertEqual(alice['id'],result['state']['raw_lot_ownership'][request['request_id']]['owner'])
        self.assertTrue(call('store_ground',request)['replayed'])
        self.assertEqual(0,inv()['ground_load']['total_kg'])
        self.assertAlmostEqual(b['total_kg'],inv(bob['token'])['ground_load']['total_kg'],places=5)
        self.assertAlmostEqual(legacy['total_kg'],inv()['unassigned_ground']['total_kg'],places=5)
        self.assertEqual([],inv(bob['token'])['stored_ground'])
        with self.assertRaises(urllib.error.HTTPError):call('store_ground',request,bob['token'])
        returned=self.raw_request(app,'owned-raw-return-0001',a,lot_id=request['request_id'])
        with self.assertRaises(urllib.error.HTTPError):call('retrieve_ground',returned,bob['token'])
        with mock.patch.object(app.store,'save',side_effect=OSError('disk full')):
            with self.assertRaises(urllib.error.HTTPError):call('retrieve_ground',returned)
        self.assertEqual(0,inv()['ground_load']['total_kg'])
        call('retrieve_ground',returned)
        self.assertTrue(call('retrieve_ground',returned)['replayed'])
        with self.assertRaises(urllib.error.HTTPError):call('retrieve_ground',returned,bob['token'])
        self.assertAlmostEqual(a['total_kg'],inv()['ground_load']['total_kg'],places=5)
        # Recovery names its unknown source explicitly and never changes a
        # private native account. A lost durable-save acknowledgement restarts
        # into the one already received lot, then replays without duplication.
        recovery=self.raw_request(app,'legacy-raw-recovery-0001',legacy)
        save=app.store.save
        def lost_ack(record):
            self.assertTrue(save(record));raise OSError('save acknowledgement lost')
        with mock.patch.object(app.store,'save',side_effect=lost_ack):
            with self.assertRaises(urllib.error.HTTPError):call('recover_ground',recovery)
        self.stop();self.start()
        for guest in (alice,bob):self.post('/api/world/player/join',{'token':guest['token']},world)
        self.post('/api/world/open',{},world);app=self.app.hub.get(world)
        self.assertTrue(call('recover_ground',recovery)['replayed'])
        with self.assertRaises(urllib.error.HTTPError):call('recover_ground',recovery,bob['token'])
        own=inv();peer=inv(bob['token'])
        self.assertEqual(0,own['unassigned_ground']['total_kg'])
        self.assertAlmostEqual(a['total_kg'],own['ground_load']['total_kg'],places=5)
        self.assertAlmostEqual(b['total_kg'],peer['ground_load']['total_kg'],places=5)
        self.assertEqual([],peer['stored_ground'])
        self.assertAlmostEqual(legacy['total_kg'],sum(v['mass_kg'] for v in own['stored_ground']),places=5)
        self.assertTrue(all(v['recovered'] for v in own['stored_ground']))
        provenance=app.room.fabrication_record['raw_lot_ownership'][recovery['request_id']]
        self.assertEqual({'owner':alice['id'],'source_actor':''},provenance)
        # Capacity refusal cannot spend the lot; use an actual fresh private
        # dig to fill the bag, not a fabricated balance or weakened limit.
        self.post('/api/live/act',{'session':app.live.session.id,'op':'dig',
            'from':[-2,-1],'to':[-2,-1],'width_m':.8,'depth_m':.4},world)
        full=self.raw_request(app,'recovered-return-full-0001',legacy,lot_id=recovery['request_id'])
        with self.assertRaises(urllib.error.HTTPError):call('retrieve_ground',full)
        self.assertAlmostEqual(legacy['total_kg'],sum(v['mass_kg'] for v in inv()['stored_ground']),places=5)
        load=inv()['ground_load']
        store_again=self.raw_request(app,'owned-raw-store-0002',load)
        call('store_ground',store_again)
        full['revision']=app.room.fabrication_record['revision'];full['session']=app.live.session.id
        call('retrieve_ground',full)
        final=inv()
        self.assertAlmostEqual(legacy['total_kg'],final['ground_load']['total_kg'],places=5)
        self.assertAlmostEqual(load['total_kg'],sum(v['mass_kg'] for v in final['stored_ground']),places=5)
        self.assertEqual('',getattr(app.live.session._actor_local,'actor',''))
        self.assertTrue(flow.server.keep_world(app,'save completed raw storage journey'))
        self.stop();self.start()
        self.post('/api/world/open',{},world);app=self.app.hub.get(world)
        self.assertTrue(call('retrieve_ground',full)['replayed'])
        self.assertEqual(final['stored_ground'],inv()['stored_ground'])
        self.assertAlmostEqual(legacy['total_kg'],inv()['ground_load']['total_kg'],places=5)
        self.assertAlmostEqual(b['total_kg'],inv(bob['token'])['ground_load']['total_kg'],places=5)

    def test_browser_store_retrieve_recovery_and_pending_retry(self):
        if not flow.qa_browser.CHROME.is_file():self.skipTest('Chrome not installed')
        world,alice,bob,app,a,b,legacy=self.storage_fixture()
        chrome=flow.qa_browser.Chrome(1280,900);self.addCleanup(chrome.close)
        p=chrome.page;p.send('Page.enable');p.send('Runtime.enable')
        p.send('Page.addScriptToEvaluateOnNewDocument',{'source':
            'localStorage.setItem('+json.dumps('banjo.player.'+world)+','+json.dumps(alice['token'])+');'})
        def wait(expr):
            deadline=time.monotonic()+35
            while time.monotonic()<deadline:
                if p.evaluate('Boolean('+expr+')'):return
                time.sleep(.1)
            self.fail(expr+'; '+str(p.evaluate('document.querySelector("#ws-notice")?.textContent')))
        def click(selector):
            spot=p.evaluate('(()=>{const b=document.querySelector('+json.dumps(selector)+');b.scrollIntoView({block:"center"});const r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()')
            for kind in ('mousePressed','mouseReleased'):
                p.send('Input.dispatchMouseEvent',{'type':kind,'button':'left','clickCount':1,**spot})
        p.send('Page.navigate',{'url':self.base+f'/world?world={world}&workshop=1&tab=inventory&hold=1'})
        wait('document.querySelector("[data-ground-action=store_ground]")')
        material=p.evaluate('document.querySelector("[data-ground-action=store_ground]").closest("article").dataset.groundLoad')
        source_kg=a[material+'_kg']
        self.assertTrue(p.evaluate('Boolean(document.querySelector("[data-ground-load] canvas"))'))
        with mock.patch.object(app.store,'save',side_effect=OSError('disk full')):
            click('[data-ground-action=store_ground]')
            wait('document.querySelector("[data-ground-retry]")')
        self.assertAlmostEqual(a['total_kg'],self.post('/api/workshop/inventory',{},world)['ground_load']['total_kg'],places=5)
        p.send('Page.reload',{})
        wait('document.querySelector("[data-ground-retry]")')
        self.assertTrue(p.evaluate('document.querySelector("[data-ground-action=store_ground]").disabled'))
        click('[data-ground-retry]')
        wait('document.querySelector("#ws-inv-stored-ground [data-ground-lot]") && !document.querySelector("[data-ground-retry]")')
        own=self.post('/api/workshop/inventory',{},world)
        self.assertAlmostEqual(source_kg,sum(v['mass_kg'] for v in own['stored_ground']),places=5)
        click('[data-ground-action=retrieve_ground]')
        wait('!document.querySelector("[data-ground-action=retrieve_ground]:disabled") && document.querySelector("#ws-inv-ground").textContent.includes("5 kg")')
        retrieved=self.post('/api/workshop/inventory',{},world)
        self.assertAlmostEqual(min(5,source_kg),retrieved['ground_load'][material+'_kg'],places=5)
        for substance in ('sand','soil','rock'):
            if legacy.get(substance+'_kg',0)<=.0005:continue
            selector=f'#ws-inv-unassigned [data-ground-load="{substance}"] [data-ground-action=recover_ground]'
            click(selector)
            wait('!document.querySelector('+json.dumps(selector)+')')
        recovered=self.post('/api/workshop/inventory',{},world)
        self.assertAlmostEqual(legacy['total_kg'],sum(v['mass_kg'] for v in recovered['stored_ground'] if v['recovered']),places=5)
        self.assertEqual(0,recovered['unassigned_ground']['total_kg'])
        peer=self.post('/api/workshop/inventory',{},world,bob['token'])
        self.assertEqual([],peer['stored_ground']);self.assertAlmostEqual(b['total_kg'],peer['ground_load']['total_kg'],places=5)
        self.assertEqual(0,p.evaluate('document.querySelectorAll("button button").length'))
        self.assertEqual([],[e for e in p.events if e.get('method')=='Runtime.exceptionThrown'])
        p.evaluate('document.querySelector("#ws-inv-stored-ground").scrollIntoView({block:"center"})')
        (ROOT/'build/resource-flow/raw-storage-inventory.png').write_bytes(
            base64.b64decode(p.send('Page.captureScreenshot',{'format':'png'})['data']))

    def test_independent_capacity_deposit_spoof_refusal_and_restart(self):
        with mock.patch.object(flow.server.secrets,'randbelow',side_effect=[0,851269740]):
            world,alice,app=self.setup_world()
        bob=self.join(world,'Other gatherer');sid=app.live.session.id
        def act(op,token=None,**more):
            return self.post('/api/live/act',{'session':sid,'op':op,**more},world,token)
        def carrying(token=None):
            return self.post('/api/world/inventory/shown',{'session':sid},world,token)['carried']
        a=act('dig',**{'from':[-1,0],'to':[-1,0],'width_m':.8,'depth_m':.4})
        self.assertAlmostEqual(80,a['carried']['total_kg'],places=5)
        self.assertEqual(0,carrying(bob['token'])['total_kg'])
        # The server derives actor identity from the authenticated token.
        with self.assertRaises(urllib.error.HTTPError) as refusal:
            act('ground_withdraw',bob['token'],actor=alice['id'],
                sand_m3=a['carried']['sand_m3'],soil_m3=a['carried']['soil_m3'])
        self.assertEqual(400,refusal.exception.code)
        b=act('dig',bob['token'],actor=alice['id'],**{'from':[2,-1],'to':[2,-1],'width_m':.8,'depth_m':.4})
        self.assertAlmostEqual(80,b['carried']['total_kg'],places=5)
        self.assertAlmostEqual(80,carrying()['total_kg'],places=5)
        # An actual rover scoop uses its server-owned machine account even
        # when invoked inside a full player's request context.
        import machine_tools
        program=next(p for p in app.live.session.state['machines']['programs'] if p['kind']=='roam')
        brain=app.brains.of(program['name'])
        with app.live.as_actor(alice['id']):
            machine_tools.run(brain.context(app.brains._ask(app,sid)),machine_tools.Call('dig',{},'routine'))
        self.assertGreater(brain.routine.kg,0)
        self.assertAlmostEqual(80,carrying()['total_kg'],places=5)
        self.assertAlmostEqual(80,carrying(bob['token'])['total_kg'],places=5)
        self.assertEqual(0,app.live.session.state['player_carried']['machine:'+program['name']]['total_kg'])
        app.clock._tick(.05) # unattended stepping must not select another player's stock
        self.assertAlmostEqual(80,carrying()['total_kg'],places=5)
        self.assertAlmostEqual(80,carrying(bob['token'])['total_kg'],places=5)
        self.assertTrue(flow.server.keep_world(app,'save independent ground accounts'))
        saved=deepcopy(app.room.world_record)
        self.assertEqual('banjo.ground-state.v5',saved['ground']['schema'])
        self.assertGreater(saved['ground']['carriers'][alice['id']]['sand_m3'],0)
        self.assertGreater(sum(saved['ground']['carriers'][bob['id']].values()),0)
        self.stop();self.start()
        for guest in (alice,bob):
            rejoined=self.post('/api/world/player/join',{'token':guest['token']},world)
            self.assertEqual(guest['id'],rejoined['id'])
        opened=self.post('/api/world/open',{},world);sid=opened['session']
        self.assertEqual('whole',opened['restored']['tier'])
        self.assertAlmostEqual(80,opened['terrain']['carried']['total_kg'],places=5)
        self.assertAlmostEqual(80,carrying(bob['token'])['total_kg'],places=5)
        emptied=act('deposit',at=[-2,-1],radius_m=.8,
            sand_m3=a['carried']['sand_m3'],soil_m3=a['carried']['soil_m3'])
        self.assertAlmostEqual(0,emptied['carried']['total_kg'],places=6)
        self.assertAlmostEqual(80,carrying(bob['token'])['total_kg'],places=5)
        # Global native export counters cannot fund a raw player return.
        # Server-owned machine/storage receipts authorize those operations.
        with self.assertRaises(urllib.error.HTTPError) as unfunded:
            act('ground_return',sand_m3=0,soil_m3=.001)
        self.assertEqual(400,unfunded.exception.code)
        self.assertEqual(0,carrying()['total_kg'])
        with self.assertRaises(urllib.error.HTTPError):
            act('deposit',actor=bob['id'],at=[-2,-1],radius_m=.8,
                sand_m3=b['carried']['sand_m3'],soil_m3=b['carried']['soil_m3'])
        report=act('environment')['environment']['ground']
        self.assertAlmostEqual(80,sum(report['carried_all'][k+'_kg'] for k in ('sand','soil','rock')),places=5)
        for substance in ('sand','soil'):
            key=substance+'_m3'
            self.assertAlmostEqual(0,report['residual'][key],places=9)
            self.assertAlmostEqual(report['ledger']['dug'][key],
                report['ledger']['deposited'][key]+report['carried_all'][key]
                +report['exported'][key]-report['returned'][key],places=9)
        (ROOT/'build/resource-flow/private-ground-api.json').write_text(json.dumps(
            {'alice':a['carried'],'bob':b['carried'],'after_alice_heap':report},indent=2))

    def test_browser_reads_its_own_load_after_another_player_digs(self):
        if not flow.qa_browser.CHROME.is_file():self.skipTest('Chrome not installed')
        world,alice,app=self.setup_world();sid=app.live.session.id
        chrome=flow.qa_browser.Chrome(1280,800);self.addCleanup(chrome.close)
        p=chrome.page;p.send('Page.enable');p.send('Runtime.enable')
        p.send('Page.navigate',{'url':self.base+f'/world?world={world}'})
        def wait(expr):
            deadline=time.monotonic()+40
            while time.monotonic()<deadline:
                if p.evaluate('Boolean('+expr+')'):return
                time.sleep(.1)
            self.fail(expr)
        wait('window.banjoRoom?.ready()')
        browser_id=p.evaluate('banjoRoom.status().player_id')
        self.assertNotEqual(alice['id'],browser_id)
        self.post('/api/live/act',{'session':sid,'op':'dig','from':[-1,0],'to':[-1,0],
            'width_m':.8,'depth_m':.4},world)
        wait('banjoRoom.world.carriedGround && banjoRoom.world.carriedGround.total_kg===0')
        self.assertIn('0.0 / 80 kg',p.evaluate('document.querySelector("#world-load-meter").textContent'))
        self.assertEqual('false',p.evaluate('document.querySelector("#world-load-meter").dataset.full'))
        peer=next(g for g in app.room.player_records.values() if g['id']==browser_id)
        self.post('/api/live/act',{'session':sid,'op':'dig','from':[2,-1],'to':[2,-1],
            'width_m':.8,'depth_m':.4},world,peer['token'])
        wait('document.querySelector("#world-load-meter").dataset.full==="true"')
        self.assertAlmostEqual(80,p.evaluate('banjoRoom.world.carriedGround.total_kg'),places=5)
        # Earlier saves may carry an anonymous world load. It stays separate
        # and visible rather than becoming the next joining player's property.
        legacy=app.live.act({'session':sid,'op':'dig','from':[3,1],'to':[3,1],
            'width_m':.4,'depth_m':.1})['carried']
        self.assertGreater(legacy['total_kg'],0)
        p.send('Page.navigate',{'url':self.base+f'/world?world={world}&workshop=1&tab=inventory'})
        wait('document.querySelector("#ws-inv-ground [data-ground-load]")')
        wait('document.querySelector("#ws-inv-unassigned [data-ground-load]")')
        wait('document.querySelector("#ws-inv-energy .ws-energy-card")')
        self.assertIn('80 kg',p.evaluate('document.querySelector("#ws-inv-ground").textContent'))
        self.assertIn('Unassigned',p.evaluate('document.querySelector("#ws-inv-unassigned").textContent'))
        self.assertIn('Heap → World',p.evaluate('document.querySelector("#ws-inv-ground").textContent'))
        loaded=self.post('/api/workshop/inventory',{},world,peer['token'])
        self.assertAlmostEqual(80,loaded['ground_load']['total_kg'],places=5)
        self.assertAlmostEqual(legacy['total_kg'],loaded['unassigned_ground']['total_kg'],places=5)
        p.evaluate('document.querySelector("#ws-inv-unassigned").scrollIntoView({block:"end"})')
        (ROOT/'build/resource-flow/private-ground-inventory.png').write_bytes(
            base64.b64decode(p.send('Page.captureScreenshot',{'format':'png'})['data']))
        self.assertEqual([],[e for e in p.events if e.get('method')=='Runtime.exceptionThrown'])


if __name__=='__main__':unittest.main()
