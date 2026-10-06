"""Paid thin metal shovel: real stock, native manufacture, carry, use and reload."""
from pathlib import Path
import base64
import json
import sys
import threading
import time
import unittest
from copy import deepcopy
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'playground'),str(ROOT)]
import workshop_navigation_tests as navigation
import playable_recipes


class Journey(navigation.GameScreens):
    def tearDown(self):
        if getattr(self,'page',None):
            try:
                state=self.page.evaluate('({remake:document.querySelector("#ws-remake")?.textContent,shovel:document.querySelector(\'[data-recipe="custom:Metal shovel"]\')?.textContent,notice:document.querySelector("#ws-notice")?.textContent})')
                out=ROOT/'build/metal-shovel';out.mkdir(parents=True,exist_ok=True)
                (out/'last-ui-state.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
            except Exception:pass
        super().tearDown()
    def screenshot(self,name):
        if 'recipe' in name:
            self.page.evaluate('document.querySelector(\'[data-recipe="custom:Metal shovel"]\').scrollIntoView({block:"start"})')
        if 'shovel-mobile' in name:
            self.page.evaluate('[...document.querySelectorAll("#ws-inv-grid article")].find(e=>e.textContent.includes("Metal shovel")).scrollIntoView({block:"start"})')
        out=ROOT/'build/metal-shovel';out.mkdir(parents=True,exist_ok=True)
        (out/name).write_bytes(base64.b64decode(self.page.send('Page.captureScreenshot')['data']))

    def test_paid_shovel_from_finite_starter_stock_to_dig_and_reload(self):
        began=time.monotonic()
        world,owner,app=self.setup_world(surface='columns')
        before=deepcopy(app.room.fabrication_record)
        bad=playable_recipes.metal_shovel_recipe()
        bad['component_overrides']['@construction']['added'][1]['center_m'][0]+=.001
        with self.assertRaises(urllib.error.HTTPError):
            self.post('/api/world/fabrication/plan_make',{'session':app.live.session.id,
                'scene':app.room.scene,'candidate':bad},world)
        self.assertEqual(before,app.room.fabrication_record,'invalid source must not charge materials or start work')
        for material in ('iron','aluminum'):
            pile=next(p for p in app.brains.goods.stockpiles if p.get('holds',{}).get(material,0)>=3)
            at=pile['at_m']
            floor=self.post('/api/live/act',{'session':app.live.session.id,'op':'survey','at':at},world)['survey']['ground_m']
            collected=self.post('/api/world/goods/collect',{'session':app.live.session.id,
                'pile':pile['name'],'request_id':'shovel-stock-'+material,
                'person':{'eyes_m':[at[0],floor+1.62,at[1]],'facing':[0,0,-1]}},world)
            self.assertGreater(collected['collected'][material],0)
        self.browser(world,owner)
        # Landscape phone viewport exercises the same visible Make controls.
        self.page.send('Emulation.setDeviceMetricsOverride',{'width':844,'height':390,
            'deviceScaleFactor':1,'mobile':True})
        self.navigate(world,'workshop=1&tab=recipes')
        selector='[data-recipe="custom:Metal shovel"]'
        self.wait(f'!!document.querySelector({json.dumps(selector)})')
        self.screenshot('01-recipe-mobile.png')
        self.click(selector+' .ws-recipe-acts button:first-child')
        self.wait('!!document.querySelector("#ws-remake-prepare")')
        for _ in range(12):
            self.click('#ws-remake-prepare')
            self.wait('!document.querySelector("#ws-remake-start").disabled || !!document.querySelector("#ws-remake-prepare:not(:disabled)")')
            if self.page.evaluate('!document.querySelector("#ws-remake-start").disabled'):break
        self.wait('!document.querySelector("#ws-remake-start").disabled')
        self.screenshot('02-paid-review-mobile.png')
        self.click('#ws-remake-start');self.wait('!!document.querySelector("#ws-remake-step")')
        for _ in range(5):
            self.click('#ws-remake-step')
            self.wait('!!document.querySelector("#ws-remake-collect") || !!document.querySelector("#ws-remake-step:not(:disabled)")')
            if self.page.evaluate('!!document.querySelector("#ws-remake-collect")'):break
        self.wait('!!document.querySelector("#ws-remake-collect")')
        self.click('#ws-remake-collect')
        self.wait('document.querySelector("#ws-remake").textContent.includes("In your Inventory")')
        receipt=next(r for r in reversed(app.room.workshop_installs) if r.get('owner_id')==owner['id'])
        self.assertTrue(receipt['resources_charged'])
        self.assertTrue(receipt['native_precise_geometry_verified'])
        self.assertEqual(playable_recipes.metal_shovel_recipe()['component_overrides'],receipt['recipe']['component_overrides'])
        job=app.room.fabrication_record['jobs'][receipt['fabrication_job_id']]
        self.assertAlmostEqual(2.30796,sum(job['product_materials_kg'].values()),places=6)
        self.assertGreater(job['required_j'],0);self.assertGreaterEqual(job['work_j'],job['required_j'])
        self.click('.game-tabs [data-screen="inventory"]')
        self.wait('document.querySelector("#ws-inv-grid").textContent.includes("Metal shovel")')
        self.screenshot('03-owned-shovel-mobile.png')
        carried=self.post('/api/workshop/inventory',{},world)['carried']
        own=next(i for i in carried if i['label']=='Metal shovel')
        self.assertAlmostEqual(2.30796,own['kg'],places=5)
        make_s=time.monotonic()-began
        x,z=-.9,.025
        floor=self.post('/api/live/act',{'session':app.live.session.id,'op':'survey','at':[x,z]},world)['survey']['ground_m']
        person={'standing_m':[x,floor,z],'eyes_m':[x,floor+1.62,z],'facing':[1,0,0]}
        equipped=self.post('/api/world/inventory',{'session':app.live.session.id,'op':'equip',
            'item':own['id'],'request':'equip-paid-shovel','person':person},world)
        self.assertTrue(equipped['ok'],equipped)
        target_floor=self.post('/api/live/act',{'session':app.live.session.id,'op':'survey',
            'at':[x+1,z]},world)['survey']['ground_m']
        target=[x+1,target_floor,z]
        person['look_direction']=[target[0]-x,target[1]-floor-1.62,target[2]-z]
        replies=[];errors=[]
        def use():
            try:replies.append(self.post('/api/world/tool/use',{'session':app.live.session.id,
                'person':person,'at_m':target},world))
            except Exception as exc:errors.append(exc)
        strike_started=time.monotonic()
        worker=threading.Thread(target=use,daemon=True);worker.start();deadline=time.monotonic()+25
        while worker.is_alive() and time.monotonic()<deadline:
            app.clock._tick(.05);time.sleep(.015)
        worker.join(1);self.assertFalse(worker.is_alive());self.assertEqual([],errors)
        used=replies[0];self.assertNotIn('refused',used,used)
        self.assertGreater(used['result']['loosened_kg'],0,used)
        strike_s=time.monotonic()-strike_started
        # Save the actual equipped native matter, then reload through the server.
        self.page.send('Page.navigate',{'url':'about:blank'})
        self.stop();self.start();self.post('/api/world/player/join',{'token':owner['token']},world)
        opened=self.post('/api/world/open',{},world)
        restored=self.app.hub.get(world)
        after=self.post('/api/workshop/inventory',{},world)['carried']
        self.assertEqual(1,len([i for i in after if i['id']==own['id']]))
        item=next(i for i in after if i['id']==own['id'])
        self.assertAlmostEqual(own['kg'],item['kg'],places=6)
        saved,reason=restored.live.snapshot()
        self.assertIsNotNone(saved,reason)
        bodies=saved['bodies']
        local=[b for b in bodies if b.get('precise_rigid_definition',{}).get('cell_geometry')=='clipped-box-cells-v1']
        self.assertEqual(2,len(local),[b['name'] for b in bodies])
        blade=next(b for b in local if any(abs(p['dimensions_m'][1]-.003)<1e-12
            for p in b['precise_rigid_definition']['parts']))
        self.assertTrue(all(abs(p['dimensions_m'][1]-.003)<1e-12 for p in blade['precise_rigid_definition']['parts']))
        self.assertTrue(opened.get('session'))
        self.navigate(world,'workshop=1&tab=inventory')
        self.wait('document.querySelector("#ws-inv-grid").textContent.includes("Metal shovel")')
        self.screenshot('04-reloaded-shovel-mobile.png')
        self.assertFalse([e for e in self.page.events if e.get('method')=='Runtime.exceptionThrown'])
        out=ROOT/'build/metal-shovel';out.mkdir(parents=True,exist_ok=True)
        (out/'journey.json').write_text(json.dumps({'make_wall_s':make_s,'strike_wall_s':strike_s,
            'walking_included':False,'job':job,'hand_use':used,'restored_item':item},indent=2),encoding='utf-8')


for name in dir(navigation.GameScreens):
    if name.startswith('test_'):setattr(Journey,name,None)
if __name__=='__main__':unittest.main()
