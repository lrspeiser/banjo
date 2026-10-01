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
        page.evaluate(f'banjoRoom.standAt({person["eyes_m"][0]}, {person["eyes_m"][1]}, {person["eyes_m"][2]+1.4})')
        page.evaluate(f'banjoRoom.lookAt({person["eyes_m"][0]}, {person["eyes_m"][1]-1.4}, {person["eyes_m"][2]})')
        self.process_batch(app,pile)
        wait('banjoRoom.scene.getObjectByName("resource-packets").children.some(c=>c.userData.transferKind === "input" || c.userData.transferKind === "output")')
        wait(f'document.querySelector("#collect-output")?.dataset.pile === {json.dumps(pile["name"])}')
        viewer=page.evaluate(f'localStorage.getItem("banjo.player.{world}")')
        player=next(p for p in app.room.player_records.values() if p['token']==viewer)
        before=deepcopy(pile['holds'])
        import base64
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        shot=page.send('Page.captureScreenshot',{'format':'png'})['data']
        (out/'output-ready.png').write_bytes(base64.b64decode(shot))
        page.evaluate('document.querySelector("#collect-output").click()')
        wait('document.querySelector("#collect-output").hidden')
        self.assertEqual({},pile['holds']);self.assertEqual(before,self.personal(app,player))
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        shot=page.send('Page.captureScreenshot',{'format':'png'})['data']
        (out/'collected.png').write_bytes(base64.b64decode(shot))
        self.assertEqual([],[e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])

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
