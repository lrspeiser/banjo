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
