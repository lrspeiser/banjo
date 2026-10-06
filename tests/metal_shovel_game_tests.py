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
import workshop_chat
import workshop_store
from workshop_api_core import _store


def unfamiliar_tool(app):
    """Use bounded LLM calls, starting from an anonymous source beam."""
    source={'kind':'custom','design_id':'delta-trench-cutter','purpose':'Delta trench cutter',
            'parameters':{},'component_overrides':{'@construction':{'joints_authored':True,
                'added':[{'name':'spine-A','role':'beam','shape':'box','material':'aluminum',
                    'size_m':[.5,.03,.03],'center_m':[0,.015,0],'rotation_deg':[0,0,0]}]}}}
    state=workshop_chat._State(app,source,None,['iron','aluminum'],[])
    state.execute('add_part',{'name':'edge-B','role':'panel','material':'iron',
        'size_m':[.2,.012,.18],'center_m':[.35,.006,0],'fasten_to':'spine-A','kind':'fixed'})
    state.execute('set_local_cells',{'cell_size_m':.05})
    # A common chat ordering: generic points first, then functional capability.
    state.execute('define_interaction_points',{'points':[]})
    state.execute('define_ground_tool',{'point':{'component':'edge-B',
        'tip_local_m':[.1,0,0],'direction_local':[1,0,0],'width_m':.18,
        'thickness_m':.012,'angle_deg':30,'length_m':.2},
        'grip':{'component':'spine-A','position_local_m':[-.15,0,0]},
        'use':{'contact_drag_m':.1}})
    state.execute('program_use',{'label':'Study tool','steps':[{'do':'inspect'}]})
    report=state.execute('inspect_design',{})['recipe_contract']['tool_authoring']
    assert report['ground_work']['status']=='configured-unqualified'
    workshop_store.save(_store(app),state.design,label='Delta trench cutter')
    return state.current_spec()


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
            self.page.evaluate(f'document.querySelector({json.dumps(self.selector)}).scrollIntoView({{block:"start"}})')
        if 'shovel-mobile' in name:
            self.page.evaluate(f'[...document.querySelectorAll("#ws-inv-grid article")].find(e=>e.textContent.includes({json.dumps(self.label)})).scrollIntoView({{block:"start"}})')
        out=ROOT/'build'/self.evidence_dir;out.mkdir(parents=True,exist_ok=True)
        (out/name).write_bytes(base64.b64decode(self.page.send('Page.captureScreenshot')['data']))

    def test_paid_shovel_from_finite_starter_stock_to_dig_and_reload(self):
        self.run_journey(novel=False)

    def test_unfamiliar_chat_authored_tool_paid_make_pickup_use_and_reload(self):
        self.run_journey(novel=True)

    def run_journey(self,novel):
        began=time.monotonic()
        world,owner,app=self.setup_world(surface='columns')
        source=unfamiliar_tool(app) if novel else playable_recipes.metal_shovel_recipe()
        self.label='Delta trench cutter' if novel else 'Metal shovel'
        self.selector='[data-recipe="delta-trench-cutter"]' if novel else '[data-recipe="custom:Metal shovel"]'
        self.evidence_dir='unfamiliar-tool' if novel else 'metal-shovel'
        expected_mass=4.61484 if novel else 2.30796
        blade_thickness=.012 if novel else .003
        before=deepcopy(app.room.fabrication_record)
        bad=deepcopy(source)
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
        selector=self.selector
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
        self.assertEqual(source['component_overrides'],receipt['recipe']['component_overrides'])
        job=app.room.fabrication_record['jobs'][receipt['fabrication_job_id']]
        self.assertAlmostEqual(expected_mass,sum(job['product_materials_kg'].values()),places=6)
        self.assertGreater(job['required_j'],0);self.assertGreaterEqual(job['work_j'],job['required_j'])
        self.click('.game-tabs [data-screen="inventory"]')
        self.wait(f'document.querySelector("#ws-inv-grid").textContent.includes({json.dumps(self.label)})')
        self.screenshot('03-owned-shovel-mobile.png')
        carried=self.post('/api/workshop/inventory',{},world)['carried']
        own=next(i for i in carried if i['label']==self.label)
        self.assertAlmostEqual(expected_mass,own['kg'],places=5)
        make_s=time.monotonic()-began
        x,z=-.9,.025
        floor=self.post('/api/live/act',{'session':app.live.session.id,'op':'survey','at':[x,z]},world)['survey']['ground_m']
        person={'standing_m':[x,floor,z],'eyes_m':[x,floor+1.62,z],'facing':[1,0,0]}
        equipped=self.post('/api/world/inventory',{'session':app.live.session.id,'op':'equip',
            'item':own['id'],'request':'equip-paid-shovel','person':person},world)
        self.assertTrue(equipped['ok'],equipped)
        if novel:
            self.pickup_each_component(world,own['id'],own['parts'],app)
            self.page.send('Page.navigate',{'url':'about:blank'})
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
        blade=next(b for b in local if any(abs(p['dimensions_m'][1]-blade_thickness)<1e-12
            for p in b['precise_rigid_definition']['parts']))
        self.assertTrue(all(abs(p['dimensions_m'][1]-blade_thickness)<1e-12 for p in blade['precise_rigid_definition']['parts']))
        self.assertTrue(opened.get('session'))
        if novel:
            # Chat/actions can leave a plain native carry hold. Restoration
            # must recover the capability, rather than treating its fixing
            # as a joint to haul. Exercise the real native grab and UI reload.
            self.post('/api/live/act',{'session':restored.live.session.id,
                'op':'grab','name':own['name']},world)
            self.assertNotEqual('grip',restored.live.session.state['hand']['mode'])
            self.page.send('Page.navigate',{'url':self.base+f'/world?world={world}'})
            self.wait('banjoRoom?.ready() && banjoRoom.use().mode==="tool-ready"')
            self.assertEqual(own['name'],self.page.evaluate('banjoRoom.world.held.pick.tool'))
            self.assertEqual('grip',restored.live.session.state['hand']['mode'])
            self.screenshot('06-restored-tool-ready.png')
        self.navigate(world,'workshop=1&tab=inventory')
        self.wait(f'document.querySelector("#ws-inv-grid").textContent.includes({json.dumps(self.label)})')
        self.screenshot('04-reloaded-shovel-mobile.png')
        self.assertFalse([e for e in self.page.events if e.get('method')=='Runtime.exceptionThrown'])
        out=ROOT/'build'/self.evidence_dir;out.mkdir(parents=True,exist_ok=True)
        (out/'journey.json').write_text(json.dumps({'make_wall_s':make_s,'strike_wall_s':strike_s,
            'walking_included':False,'job':job,'hand_use':used,'restored_item':item},indent=2),encoding='utf-8')

    def pickup_each_component(self,world,item,parts,app):
        # Hold simulation/camera between press and ray verification. Walking
        # and gravity remain covered by the normal World navigation suite.
        self.page.evaluate('localStorage.setItem("banjo.movement","fly")')
        for index,part in enumerate(parts):
            dropped=self.post('/api/world/inventory',{'session':app.live.session.id,'op':'drop',
                'item':item,'request':f'novel-drop-{index}'},world)
            self.assertTrue(dropped['ok'],dropped)
            touch=index==1
            self.page.send('Emulation.setDeviceMetricsOverride',{'width':844 if touch else 1440,
                'height':390 if touch else 900,'deviceScaleFactor':1,'mobile':touch})
            self.page.send('Page.navigate',{'url':self.base+f'/world?world={world}&hold=1'})
            self.wait('banjoRoom?.ready() && document.querySelector("#panel-state").textContent==="Live."')
            actual=next(b['position_m'] for b in app.live.session.state['bodies'] if b['name']==part)
            self.wait(f'banjoRoom.world.bodies.get({json.dumps(part)}).mesh.position.distanceTo(new banjoRoom.THREE.Vector3(...{json.dumps(actual)}))<.001')
            self.page.evaluate(f'''(()=>{{const r=banjoRoom,p=r.world.bodies.get({json.dumps(part)}).mesh.position;
                r.standAt(p.x,r.groundAt(p.x,p.z+1)+1.62,p.z+1);r.lookAt(p.x,p.y,p.z);
                r.camera.updateMatrixWorld(true);}})()''')
            self.wait('!banjoRoom.world.busy && !banjoRoom.world.acting')
            point=self.page.evaluate(f'''(()=>{{const r=banjoRoom,
                v=r.world.bodies.get({json.dumps(part)}).mesh.getWorldPosition(new r.THREE.Vector3()).project(r.camera);
                return {{x:(v.x+1)*innerWidth/2,y:(1-v.y)*innerHeight/2}};}})()''')
            ray=self.page.evaluate(f'''(()=>{{const r=banjoRoom,p=r.world.bodies.get({json.dumps(part)}).mesh.position;
                return {{from:r.camera.position.toArray(),dir:p.clone().sub(r.camera.position).normalize().toArray()}};}})()''')
            native_hit=self.post('/api/live/act',{'session':app.live.session.id,'op':'pick',**ray,'max_m':4},world)
            self.assertEqual(part,native_hit.get('name'),native_hit)
            if touch:
                self.page.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[point]})
                self.page.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
            else:
                for kind in ('mousePressed','mouseReleased'):
                    self.page.send('Input.dispatchMouseEvent',{'type':kind,**point,'button':'left','clickCount':1})
            self.wait(f'banjoRoom.world.held?.pick?.tool==={json.dumps(parts[0])}',seconds=12)
            self.page.evaluate('banjoRoom.resume()')
            try:
                self.wait(f'banjoRoom.held()?.name==={json.dumps(parts[0])} && banjoRoom.use().mode==="tool-ready"',seconds=12)
            except AssertionError:
                self.screenshot(f'failed-pickup-{index}.png')
                self.fail(str(self.page.evaluate(f'''({{part:{json.dumps(part)},point:{json.dumps(point)},
                    held:banjoRoom.held(),last:banjoRoom.world.last,aim:banjoRoom.world.aim,
                    controls:banjoRoom.controls(),camera:banjoRoom.camera.position.toArray(),
                    at:banjoRoom.world.bodies.get({json.dumps(part)}).mesh.position.toArray(),
                    hit:document.elementFromPoint({point['x']},{point['y']})?.id}})''')))
            self.assertEqual(parts[0],app.live.session.state['hand']['holding'])
            self.assertTrue(self.page.evaluate('document.body.classList.contains("panel-away")'))
            self.screenshot(f'05-pickup-{index}.png')


for name in dir(navigation.GameScreens):
    if name.startswith('test_'):setattr(Journey,name,None)
if __name__=='__main__':unittest.main()
