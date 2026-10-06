"""Native loose component click collection and its real recipe source in UI.

Uses an explicit flat column/cutter/work fixture, never the owner's world.
"""
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'playground'),str(ROOT)]
import workshop_navigation_tests as navigation


class NativeMatterBrowser(navigation.GameScreens):
    pass
for name in dir(navigation.GameScreens):
    if name.startswith('test_'):setattr(NativeMatterBrowser,name,None)


def test_native_component_click_collection_and_real_pick_source(self):
    world,owner,app=self.setup_world(surface='columns');app.clock.stop()
    # Authored experiment fixture: flat 25 cm soil on rock, an iron cutter
    # and two declared 1 MJ native work budgets. This verifies the UI path;
    # it is not a fresh-player supply/energy acceptance experiment.
    app.room.spec['terrain']={'surface':'columns','generate':{'kind':'flat','nx':160,'nz':160,
        'cell_m':.25,'soil_m':.25,'sand_m':0.,'discharge_m3_s':0.}}
    app.room.spec['bodies'].append({'name':'fixture cutter','shape':'box','material':'iron',
        'size_mm':[800,100,100],'center_mm':[0,1000,0]})
    app.room.spec.setdefault('tool_points',[]).append({'body':'fixture cutter','tip_mm':[400,1000,0],
        'pointing':[0,-1,0],'grip_mm':[-300,1000,0],'width_mm':100,'thickness_mm':100,'angle_deg':30.,'length_mm':200})
    app.live.open(app,{'spec':app.room.spec});app.live_holder='world'
    app.room.fabrication_record['time_s']=0.
    with app.live.as_actor(owner['id']):
        app.live.session.send(op='wield',name='fixture cutter',grip=[-.3,1.,0.])
        soil=app.live.session.send(op='strike-cell',at_m=[0.,.24,0.],work_j=1e6,
            work_source='browser-soil-fixture')['ground_cut']
    self.assertTrue(soil['supported'],soil)
    self.browser(world,owner)
    self.page.evaluate('localStorage.setItem("banjo.movement","fly")')
    self.page.send('Page.navigate',{'url':self.base+f'/world?world={world}'})
    self.wait('window.banjoRoom?.ready()')
    self.page.evaluate('(async()=>{window.__matterThree=await import("/vendor/three.module.js")})()',await_promise=True)

    def collect(body_id,label):
        self.wait(f'window.banjoRoom.scene.getObjectByName("ground-matter-{body_id}")?.children.length>0')
        # The native body pose determines the test camera target. It is never
        # assigned a trajectory, launch velocity or cosmetic collection path.
        self.page.evaluate(f'''(()=>{{const r=banjoRoom.scene.getObjectByName("ground-matter-{body_id}");
            r.updateMatrixWorld(true);const p=new __matterThree.Box3().setFromObject(r).getCenter(new __matterThree.Vector3());
            banjoRoom.standAt(p.x,p.y+1.7,p.z+.02);banjoRoom.lookAt(p.x,p.y,p.z);banjoRoom.camera.updateMatrixWorld(true);}})()''')
        hit=self.page.evaluate(f'''(()=>{{const r=banjoRoom.scene.getObjectByName("ground-matter-{body_id}"),ray=new __matterThree.Raycaster();
            ray.set(banjoRoom.camera.position,banjoRoom.camera.getWorldDirection(new __matterThree.Vector3()));
            return {{hits:ray.intersectObject(r,true).length,position:r.position.toArray(),children:r.children.map(m=>m.count)}};}})()''')
        self.assertGreater(hit['hits'],0,hit)
        point=self.page.evaluate('(()=>{const r=document.querySelector("#stage").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()')
        self.page.send('Input.dispatchMouseEvent',{'type':'mouseMoved',**point})
        for event in ('mousePressed','mouseReleased'):
            self.page.send('Input.dispatchMouseEvent',{'type':event,**point,'button':'left','clickCount':1})
        try:self.wait(f'!window.banjoRoom.scene.getObjectByName("ground-matter-{body_id}")',seconds=15)
        except AssertionError:
            self.screenshot('native-click-failure.png')
            self.fail(str(self.page.evaluate('({last:banjoRoom.world.last,controls:banjoRoom.controls(),camera:banjoRoom.camera.position.toArray()})')))
        self.wait('window.banjoRoom.world.last?.text.includes("Collected")')
        self.screenshot(label)

    collect(soil['body_id'],'native-soil-click-collected.png')
    with app.live.as_actor(owner['id']):
        app.live.session.send(op='wield',name='fixture cutter',grip=[-.3,1.,0.])
        rock=app.live.session.send(op='strike-cell',at_m=[0.,-.01,0.],work_j=1e6,
            work_source='browser-rock-fixture')['ground_cut']
    self.assertTrue(rock['supported'],rock)
    self.wait(f'window.banjoRoom.scene.getObjectByName("ground-matter-{rock["body_id"]}")?.children.length>0')
    self.screenshot('native-rock-loose-desktop.png')
    self.page.send('Emulation.setDeviceMetricsOverride',{'width':844,'height':390,'deviceScaleFactor':1,'mobile':True})
    self.screenshot('native-rock-loose-landscape.png')
    self.page.send('Emulation.setDeviceMetricsOverride',{'width':1440,'height':900,'deviceScaleFactor':1,'mobile':False})
    collect(rock['body_id'],'native-rock-click-collected.png')
    inv=self.post('/api/workshop/inventory',{},world)
    self.assertGreater(sum(lot.get('mass_kg',0) for lot in inv['stored_ground'] if lot.get('substance')=='rock'),0)
    peer=self.join(world,'Peer')
    peer_inv=self.post('/api/workshop/inventory',{},world,player=peer['token'])
    self.assertEqual([],peer_inv['stored_ground'],'Peer cannot access private collected lots')
    # Stone head + inorganic handle: rock alone does not supply aluminum.
    # Collect actual finite starter stock instead of asserting a free handle.
    pile=next(p for p in app.brains.goods.stockpiles if p.get('holds',{}).get('aluminum',0)>=3)
    x,z=pile['at_m']
    floor=self.post('/api/live/act',{'session':app.live.session.id,'op':'survey','at':[x,z]},world)['survey']['ground_m']
    stock=self.post('/api/world/goods/collect',{'session':app.live.session.id,'pile':pile['name'],
        'request_id':'native-stone-pick-handle','person':{'eyes_m':[x,floor+1.62,z],'facing':[0,0,-1]}},world)
    self.assertGreater(stock['collected']['aluminum'],0)
    self.click('.game-tabs [data-screen="inventory"]')
    self.wait('!!document.querySelector("[data-ground-material=rock]")')
    self.click('[data-ground-material="rock"] .ws-tile')
    self.wait('!!document.querySelector("#ws-pane-recipes [data-recipe]")')
    self.wait('!!document.querySelector(\'[data-recipe="field-pick:Stone field pick"]\')')
    self.assertNotIn('No supported recipe',self.page.evaluate('document.querySelector("#ws-recipe-filter-status").textContent'))
    self.assertEqual('ready',self.page.evaluate('document.querySelector(\'[data-recipe="field-pick:Stone field pick"]\').dataset.state'))
    if self.page.evaluate('!!document.querySelector(\'[data-recipe="field-pick:Stone field pick"]\').closest("details:not([open])")'):
        self.click('details:not([open]):has([data-recipe="field-pick:Stone field pick"]) > summary')
    self.click('[data-recipe="field-pick:Stone field pick"] [data-open-recipe]')
    self.wait('document.querySelector("#ws-lab-draft")?.textContent.includes("Stone field pick") && document.querySelector("#ws-draft-save")?.offsetParent!==null')
    self.assertIn('concrete',self.page.evaluate('document.querySelector("#ws-lab-draft").textContent').lower())
    self.screenshot('native-rock-pick-source-lab.png')
    self.click('#ws-draft-build')
    self.wait('!!document.querySelector("#ws-remake-review")')
    self.click('#ws-remake-review')
    self.wait('!!document.querySelector("#ws-remake-prepare")')
    self.assertFalse(self.page.evaluate('document.querySelector("#ws-remake-prepare").disabled'))
    self.screenshot('native-rock-pick-review-make.png')
    self.assertFalse(app.room.fabrication_record['jobs'],'Opening a supported source cannot manufacture it')
    self.assertEqual([], [e for e in self.page.events if e.get('method')=='Runtime.exceptionThrown'])

NativeMatterBrowser.test_native_component_click_collection_and_real_pick_source=test_native_component_click_collection_and_real_pick_source
if __name__=='__main__':unittest.main()
