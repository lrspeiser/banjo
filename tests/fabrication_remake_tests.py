"""Selected native source binding, finite remake and ordinary Lab controls."""
import base64
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import sys
import time
import unittest
import urllib.error
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'playground'),str(ROOT/'tests')]
from mcp import fabrication as model
import fabrication_room as api
import fabrication_remake as remake
import fabrication_stock_tests as funded
import inventory_room
import workshop_install as install
import workshop_library as library
import world_goods_tests as flow
import body_condition_tests as condition_flow
ENGINE=funded.ENGINE


@unittest.skipUnless(ENGINE and ENGINE.is_file(),'BANJO_LIVE_ENGINE is required')
class NativeRemake(unittest.TestCase):
    setUp=funded.NativeStock.setUp
    call=funded.NativeStock.call
    context=funded.NativeStock.context
    source=funded.NativeStock.source
    request=funded.NativeStock.request

    def take_source(self,material):
        name='selected '+material
        self.room.spec['bodies'].append({'name':name,'shape':'box','material':material,
            'size_mm':[80,80,80],'center_mm':[1000,150,1000]})
        self.live.open(self.app,{'spec':self.room.spec})
        person={'standing_m':[1,0,1],'eyes_m':[1,1.62,1],
            'facing':[0,0,-1],'look_direction':[0,-1,0]}
        self.source_person=person
        def act(op):
            shown=inventory_room.shown(self.app)
            return inventory_room.request(self.app,{'session':self.live.session.id,'op':op,'item':name,
                'revision':shown['record']['revision'],'request':'remake-source-'+material+'-'+op,'person':person})
        self.assertTrue(act('take_up')['ok']);self.assertTrue(act('stow')['ok'])
        return name

    def plan(self,name,design):return self.call('plan_remake',source_item=name,candidate=design)

    def fund(self,plan,material,ident):
        api.request(self.app,'fund_stock',self.request(plan['quote']['stock_kg'],material,'remake-stock-'+ident))
        reading=self.call('state');source=reading['energy_sources'][0]
        self.call('connect_energy',store=source['id'],store_hash=source['store_hash'],power_w=250.,
            revision=reading['state']['revision'],request_id='remake-connect-'+ident)
        api.wait(self.app,{**self.context(),'seconds':max(1,math.ceil(plan['quote']['supply_required_j']/250.))})
        reading=self.call('state');source=reading['energy_sources'][0]
        self.call('fund_energy',store_hash=source['store_hash'],joules=plan['quote']['supply_required_j'],
            revision=reading['state']['revision'],request_id='remake-energy-'+ident)

    def test_glass_oak_iron_frozen_source_funded_remake_admission_and_restart(self):
        measurements=[]
        for index,material in enumerate(('glass','oak','iron')):
            if index:
                self.live.shutdown();funded.NativeStock.setUp(self)
            name=self.take_source(material);design=funded.candidate(material)
            design['component_overrides']['@construction']['added'][0].update(size_m=[.08,.08,.08],center_m=[0,.04,0])
            before=install._snapshot(self.live);rack=library.rack(self.app);ledger=deepcopy(self.room.fabrication_record)
            plan=self.plan(name,design)
            self.assertFalse(plan['changes_world']);self.assertEqual(before,install._snapshot(self.live))
            self.assertEqual(rack,library.rack(self.app));self.assertEqual(ledger,self.room.fabrication_record)
            self.assertEqual(plan['source']['draft_hash'],model.digest(design))
            self.fund(plan,material,material)
            plan=self.plan(name,design);ident='selected-job-'+material
            request={**self.context(),'plan_id':plan['plan_id'],'revision':plan['revision'],'request_id':ident}
            before=install._snapshot(self.live);ledger=deepcopy(self.room.fabrication_record)
            with mock.patch.object(self.app.store,'save',side_effect=OSError('remake save failed')):
                with self.assertRaises(OSError):api.request(self.app,'start_remake',request)
            self.assertEqual(before,install._snapshot(self.live));self.assertEqual(ledger,self.room.fabrication_record)
            accepted=api.request(self.app,'start_remake',request)
            self.assertTrue(api.request(self.app,'start_remake',request)['replayed'])
            self.assertEqual(plan['source']['source_hash'],accepted['state']['jobs'][ident]['remake_source']['source_hash'])
            api.wait(self.app,{**self.context(),'seconds':1})
            preview=api.preview(self.app,{**self.context(),'job_id':ident,'position_m':[index*.5,0]})
            old=next(b for b in install._snapshot(self.live)['bodies'] if b['name']==name)
            result=api.commit(self.app,{**self.context(),'job_id':ident,'preview_id':preview['preview_id'],'request_id':'selected-install-'+material})
            self.assertEqual(old,next(b for b in install._snapshot(self.live)['bodies'] if b['name']==name))
            self.assertEqual(plan['source']['source_hash'],result['remake_source']['source_hash'])
            saved=self.app.store.load('fabrication');self.live.open(self.app,{'spec':saved.spec,'snapshot':saved.world_record})
            self.room=self.app.room=saved
            self.assertTrue(api.request(self.app,'start_remake',request)['replayed'])
            self.assertEqual('installed',self.room.fabrication_record['jobs'][ident]['status'])
            self.assertLess(abs(model.audit(self.room.fabrication_record)['energy_residual_j']),1e-7)
            measurements.append({'material':material,'native_mass_kg':result['mass_kg'],
                'stock_kg':plan['quote']['stock_kg'],'supplied_j':plan['quote']['supply_required_j'],
                'old_native_body_preserved':True,'cell_m':.04,'dt_s':1/240})
        self.native_evidence=measurements

    def test_source_move_expiry_shortages_and_invalid_bindings_refuse_without_spend(self):
        name=self.take_source('oak');design=funded.candidate('oak')
        plan=self.plan(name,design);before=deepcopy(self.room.fabrication_record)
        request={**self.context(),'plan_id':plan['plan_id'],'revision':plan['revision'],'request_id':'remake-poor-0001'}
        with self.assertRaisesRegex(ValueError,'Charge'):api.request(self.app,'start_remake',request)
        self.assertEqual(before,self.room.fabrication_record)
        self.fund(plan,'oak','stale');plan=self.plan(name,design)
        remake._cache(self.app)[plan['plan_id']]['expires']=0
        with self.assertRaisesRegex(ValueError,'expired'):
            self.call('start_remake',plan_id=plan['plan_id'],revision=plan['revision'],request_id='remake-expired-0001')
        plan=self.plan(name,design);shown=inventory_room.shown(self.app)
        answer=inventory_room.request(self.app,{'session':self.live.session.id,'op':'equip','item':name,
            'request':'remake-equip-source','revision':shown['record']['revision'],'person':self.source_person})
        self.assertTrue(answer['ok'],answer)
        with self.assertRaisesRegex(ValueError,'Selected item changed'):
            self.call('start_remake',plan_id=plan['plan_id'],revision=plan['revision'],request_id='remake-changed-0001')
        self.assertEqual({},self.room.fabrication_record['jobs'])
        for changes in ({'source_bodies':[[]]},{'owner':''},{'draft_hash':'z'*64},{'condition':[]},{'unknown':1}):
            with self.assertRaises(ValueError):model.remake_source({**plan['source'],**changes})

    def test_actual_cut_source_in_bag_remakes_without_healing_original(self):
        self.room.spec['cell_m']=.01
        self.room.spec['bodies'] += [
            {'name':'cut oak','shape':'box','material':'oak','size_mm':[100,100,100],'center_mm':[0,20000,0]},
            {'name':'edge','shape':'box','material':'iron','size_mm':[200,10,30],'center_mm':[0,20000,66],'velocity_m_s':[0,0,-6]}]
        self.room.spec['blades']=[{'body':'edge','heel_mm':[-90,20000,51],'tip_mm':[90,20000,51],
            'facing':[0,0,-1],'thickness_mm':10,'edge_radius_mm':.05,'bevel_deg':30,'grip_mm':[90,20000,66]}]
        self.live.open(self.app,{'spec':self.room.spec})
        for _ in range(120):
            stepped=self.live.session.send(op='step',dt=1/240,n=1)
            for name in stepped.get('breakable',[]):self.live.session.send(op='decline',name=name)
        self.live.session.send(op='grab',name='edge')
        edge=next(b for b in self.live.session.send(op='poses')['bodies'] if b['name']=='edge')
        target=edge['position_m'][:];target[2]+=.2
        self.live.session.send(op='move',to=target)
        self.live.session.send(op='step',dt=1/240,n=10);self.live.session.send(op='release')
        self.live.session.send(op='step',dt=1/240,n=10)
        self.live.session.send(op='park',name='edge')
        source=next(b for b in self.live.session.send(op='poses')['bodies'] if b['name']=='cut oak')
        x,y,z=source['position_m'];person={'standing_m':[x,y,z],'eyes_m':[x,y+1.62,z],
            'facing':[0,0,-1],'look_direction':[0,-1,0]}
        for op in ('take_up','stow'):
            shown=inventory_room.shown(self.app)
            answer=inventory_room.request(self.app,{'session':self.live.session.id,'op':op,'item':'cut oak',
                'request':'cut-remake-'+op,'revision':shown['record']['revision'],'person':person})
            self.assertTrue(answer['ok'],answer)
        design=funded.candidate();design['component_overrides']['@construction']['added'][0].update(size_m=[.1,.1,.1],center_m=[0,.05,0])
        plan=self.plan('cut oak',design)
        diagnostic=plan['source']['condition'][0]
        self.assertGreater(diagnostic['broken_bonds'],0);self.assertLess(diagnostic['fraction'],1)
        self.fund(plan,'oak','cut');plan=self.plan('cut oak',design)
        before=deepcopy(next(b for b in install._snapshot(self.live)['bodies'] if b['name']=='cut oak'))
        accepted=self.call('start_remake',plan_id=plan['plan_id'],revision=plan['revision'],request_id='cut-remake-job-0001')
        self.assertEqual(plan['source']['condition'],accepted['state']['jobs']['cut-remake-job-0001']['remake_source']['condition'])
        api.wait(self.app,{**self.context(),'seconds':1})
        preview=api.preview(self.app,{**self.context(),'job_id':'cut-remake-job-0001','position_m':[0,0]})
        result=api.commit(self.app,{**self.context(),'job_id':'cut-remake-job-0001','preview_id':preview['preview_id'],'request_id':'cut-remake-install-0001'})
        self.assertEqual(before,next(b for b in install._snapshot(self.live)['bodies'] if b['name']=='cut oak'))
        condition=self.live.session.send(op='condition',names=['cut oak',result['root_body']])['condition']['bodies']
        self.assertEqual(diagnostic,condition[0]);self.assertEqual(0,condition[1]['broken_bonds'])
        self.assertAlmostEqual(1,condition[1]['fraction'],places=12)
        self.native_evidence={'old_broken_bonds':diagnostic['broken_bonds'],'old_bonds':diagnostic['bonds'],
            'old_fraction':diagnostic['fraction'],'new_mass_kg':result['mass_kg'],
            'paid_stock_kg':plan['quote']['stock_kg'],'paid_j':plan['quote']['supply_required_j'],
            'cell_m':.01,'dt_s':1/240,'old_body_retained':True}


@unittest.skipUnless(ENGINE and ENGINE.is_file(),'BANJO_LIVE_ENGINE is required')
class LabRemake(unittest.TestCase):
    setUp=flow.GoodsJourney.setUp
    start=flow.GoodsJourney.start
    stop=flow.GoodsJourney.stop
    get=flow.GoodsJourney.get
    post=flow.GoodsJourney.post
    join=flow.GoodsJourney.join
    setup_world=flow.GoodsJourney.setup_world
    batch=flow.GoodsJourney.batch
    take_pick=condition_flow.BodyCondition.take_pick
    def tearDown(self):
        if getattr(self,'chrome',None):self.chrome.close()
        flow.GoodsJourney.tearDown(self)

    def test_lab_source_plan_native_paid_start_progress_placement_and_private_owner(self):
        self.assertTrue(flow.qa_browser.CHROME.is_file(),'Chrome required for Lab remake acceptance')
        world,owner,app,_,_,_=self.batch(process=False)
        peer=self.join(world,'Remake peer')
        app.room.spec['bodies'].append({'name':'remake battery host','shape':'box','material':'iron',
            'size_mm':[100,100,100],'center_mm':[25000,50,25000],'anchored':True})
        app.room.spec.setdefault('machines',{}).setdefault('stores',[]).append({
            'name':'remake battery','body':'remake battery host','capacity_j':2000.,'charge_j':2000.,'max_power_w':300.,'voltage_v':24.})
        app.live.open(app,{'spec':app.room.spec})
        pile=next(p for p in app.brains.goods.stockpiles if (p.get('holds') or {}).get('oak',0)>25)
        at=pile['at_m'];sid=app.live.session.id
        floor=app.live.act({'session':sid,'op':'survey','at':at})['survey']['ground_m']
        self.post('/api/world/goods/collect',{'session':sid,'pile':pile['name'],'request_id':'remake-collect-oak',
            'person':{'eyes_m':[at[0],floor+1.62,at[1]],'facing':[0,0,-1]}},world)
        person=self.take_pick(world,app);sid=app.live.session.id
        shown=self.post('/api/world/inventory/shown',{'session':sid},world)
        self.post('/api/world/inventory',{'session':sid,'op':'stow','item':'field pick',
            'request':'remake-stow-pick','revision':shown['record']['revision'],'person':person},world)
        recipe=self.post('/api/world/workshop/what_made',{'body':'field pick'},world)['recipe']
        context={'scene':app.room.scene,'session':sid}
        raw={**context,'source_item':'field pick','candidate':recipe}
        unavailable=self.post('/api/world/fabrication/plan_remake',raw,world)
        self.assertFalse(unavailable['available'])
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/fabrication/plan_remake',raw,world,peer['token'])
        self.post('/api/world/fabrication/configure',{**context,'settings':funded.settings(stock_kg={},energy_j=0),
            'request_id':'lab-remake-config-0001'},world)
        plan=self.post('/api/world/fabrication/plan_remake',raw,world)
        stock=next(s for s in plan['stock_sources'] if s['pool']=='personal')
        self.post('/api/world/fabrication/fund_stock',{**context,'material':'oak','mass_kg':plan['quote']['stock_kg'],
            'pool':'personal','rack_hash':stock['rack_hash'],'revision':plan['revision'],'request_id':'lab-remake-stock-0001'},world)
        reading=self.post('/api/world/fabrication/state',context,world)
        battery=next(s for s in reading['energy_sources'] if s['name']=='remake battery')
        self.post('/api/world/fabrication/connect_energy',{**context,'store':battery['id'],'store_hash':battery['store_hash'],
            'power_w':250.,'revision':reading['state']['revision'],'request_id':'lab-remake-connect-0001'},world)
        self.post('/api/world/fabrication/wait',{**context,'seconds':2},world)
        reading=self.post('/api/world/fabrication/state',context,world)
        battery=next(s for s in reading['energy_sources'] if s['name']=='remake battery')
        energy=self.post('/api/world/fabrication/fund_energy',{**context,'store_hash':battery['store_hash'],
            'joules':plan['quote']['supply_required_j'],'revision':reading['state']['revision'],'request_id':'lab-remake-energy-0001'},world)
        context['session']=energy['session']
        original=deepcopy(next(b for b in install._snapshot(app.live)['bodies'] if b['name']=='field pick'))
        chrome=flow.qa_browser.Chrome(1280,800);self.chrome=chrome;p=chrome.page
        p.send('Page.enable');p.send('Runtime.enable')
        p.send('Page.addScriptToEvaluateOnNewDocument',{'source':f'localStorage.setItem("banjo.player.{world}",{json.dumps(owner["token"])});'})
        def wait(expr):
            end=time.monotonic()+30
            while time.monotonic()<end:
                if p.evaluate('Boolean('+expr+')'):return
                time.sleep(.1)
            self.fail(expr+'; '+str(p.evaluate('document.body.innerText.slice(-1800)')))
        url=self.base+f'/world?world={world}&workshop=1&tab=lab&carry=field%20pick'
        p.send('Page.navigate',{'url':url})
        wait('document.querySelector("#ws-remake-review") && !document.querySelector("#ws-remake").hidden')
        p.evaluate('document.querySelector("#ws-remake-review").click()')
        wait('document.querySelector("#ws-remake-start") && !document.querySelector("#ws-remake-start").disabled')
        p.evaluate('document.querySelector("#ws-remake-start").click()')
        wait('document.querySelector("#ws-remake-step")')
        ident=next(iter(app.room.fabrication_record['jobs']))
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/fabrication/pause',{**context,'job_id':ident,
            'revision':app.room.fabrication_record['revision'],'request_id':'peer-remake-pause-0001'},world,peer['token'])
        self.post('/api/world/fabrication/pause',{**context,'job_id':ident,
            'revision':app.room.fabrication_record['revision'],'request_id':'owner-remake-pause-0001'},world)
        p.send('Page.navigate',{'url':url})
        wait('document.querySelector("#ws-remake-review") && !document.querySelector("#ws-remake").hidden')
        p.evaluate('document.querySelector("#ws-remake-review").click()')
        wait('document.querySelector("#ws-remake-resume")')
        self.assertFalse(p.evaluate('Boolean(document.querySelector("#ws-remake-step"))'))
        p.evaluate('document.querySelector("#ws-remake-resume").click()')
        wait('document.querySelector("#ws-remake-step")')
        p.evaluate('document.querySelector("#ws-remake-step").click()')
        wait('document.querySelector("#ws-remake-place")')
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/fabrication/preview',{**context,'job_id':ident,'position_m':[3,0]},world,peer['token'])
        p.evaluate('document.querySelector("#ws-remake-place").click()')
        wait('document.querySelector("#ws-remake a")?.textContent==="Collect in World"')
        self.assertEqual('installed',app.room.fabrication_record['jobs'][ident]['status'])
        self.assertEqual(original,next(b for b in install._snapshot(app.live)['bodies'] if b['name']=='field pick'))
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/'lab-remake.png').write_bytes(base64.b64decode(p.send('Page.captureScreenshot',{'format':'png'})['data']))
        self.assertEqual([], [e for e in p.events if e.get('method')=='Runtime.exceptionThrown'])
        context['session']=app.live.session.id
        more=self.post('/api/world/goods/collect',{'session':context['session'],'pile':pile['name'],'request_id':'remake-more-oak',
            'person':{'eyes_m':[at[0],floor+1.62,at[1]],'facing':[0,0,-1]}},world)
        self.assertEqual({'oak':25.},more['collected'])
        mass=app.room.fabrication_record['jobs'][ident]['stock_kg']
        self.assertAlmostEqual(50.-mass,flow.GoodsJourney.personal(self,app,owner)['oak'],places=6)


if __name__=='__main__':unittest.main()
