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

    def test_new_design_glass_oak_iron_paid_make_has_no_carried_source_and_survives_restart(self):
        measurements=[]
        for index,material in enumerate(('glass','oak','iron')):
            if index:
                self.live.shutdown();funded.NativeStock.setUp(self)
            design=funded.candidate(material)
            before=install._snapshot(self.live);rack=library.rack(self.app)
            plan=self.call('plan_make',candidate=design)
            self.assertEqual('banjo.make-plan.v1',plan['schema']);self.assertFalse(plan['original_retained'])
            self.assertNotIn('source_item',plan['source'])
            self.assertEqual(before,install._snapshot(self.live));self.assertEqual(rack,library.rack(self.app))
            self.fund(plan,material,'new-'+material)
            # A caller changing its mutable copy cannot alter the frozen plan.
            design['component_overrides']['@construction']['added'][0]['material']='concrete'
            reading=self.call('state');ident='new-design-'+material
            request={**self.context(),'plan_id':plan['plan_id'],'revision':reading['state']['revision'],'request_id':ident}
            accepted=api.request(self.app,'start_make',request)
            job=accepted['state']['jobs'][ident]
            self.assertEqual(material,job['material']);self.assertEqual(plan['source'],job['make_source'])
            self.assertNotIn('remake_source',job)
            api.wait(self.app,{**self.context(),'seconds':max(1,math.ceil(job['minimum_duration_s']))})
            preview=api.preview(self.app,{**self.context(),'job_id':ident,'position_m':[index*.5,0]})
            result=api.commit(self.app,{**self.context(),'job_id':ident,'preview_id':preview['preview_id'],'request_id':'new-install-'+material})
            self.assertEqual(plan['source'],result['make_source'])
            saved=self.app.store.load('fabrication');self.live.open(self.app,{'spec':saved.spec,'snapshot':saved.world_record})
            self.room=self.app.room=saved
            self.assertTrue(api.request(self.app,'start_make',request)['replayed'])
            self.assertEqual('installed',self.room.fabrication_record['jobs'][ident]['status'])
            self.assertLess(abs(model.audit(self.room.fabrication_record)['energy_residual_j']),1e-7)
            measurements.append({'material':material,'native_mass_kg':result['mass_kg'],
                'paid_stock_kg':plan['quote']['stock_kg'],'paid_j':plan['quote']['supply_required_j'],
                'carried_source_required':False,'restart_replay':True,'cell_m':.04,'dt_s':1/240})
        self.native_evidence=measurements

    def test_new_design_plan_peer_wrong_operation_expiry_and_saved_binding_refuse_without_spend(self):
        plan=self.call('plan_make',candidate=funded.candidate());self.fund(plan,'oak','new-boundary')
        self.app.world_id='a'*32
        before=deepcopy(self.room.fabrication_record)
        request={**self.context(),'plan_id':plan['plan_id'],
                 'revision':before['revision'],'request_id':'new-boundary-job'}
        with self.assertRaisesRegex(ValueError,'operation'):
            api.request(self.app,'start_remake',request)
        scope=library.REQUEST_OWNER.set('other-player')
        try:
            with self.assertRaisesRegex(ValueError,'another world or player'):
                api.request(self.app,'start_make',request)
        finally:library.REQUEST_OWNER.reset(scope)
        self.assertEqual(before,self.room.fabrication_record)
        remake._cache(self.app)[plan['plan_id']]['expires']=0
        with self.assertRaisesRegex(ValueError,'expired'):api.request(self.app,'start_make',request)
        plan=self.call('plan_make',candidate=funded.candidate());request['plan_id']=plan['plan_id']
        accepted=api.request(self.app,'start_make',request)
        scope=library.REQUEST_OWNER.set('other-player')
        try:
            with self.assertRaisesRegex(ValueError,'Only the player'):
                self.call('pause',job_id=request['request_id'],revision=accepted['state']['revision'],request_id='new-peer-pause')
        finally:library.REQUEST_OWNER.reset(scope)
        bad=deepcopy(self.room.fabrication_record)
        bad['jobs'][request['request_id']]['make_source']['draft_hash']='0'*64
        with self.assertRaisesRegex(ValueError,'draft'):model.validate_state(bad)
        for changes in ({'owner':''},{'draft_hash':'z'*64},{'unknown':1}):
            with self.assertRaises(ValueError):model.make_source({**plan['source'],**changes})

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

    def test_canonical_rover_paid_build_and_primary_use_in_browser(self):
        self.assertTrue(flow.qa_browser.CHROME.is_file(),'Chrome required')
        world,owner,app,*_=self.batch(process=False)
        pile=app.brains.goods.put(0,0,{'oak':40.,'iron':12.,'glass':5.,'copper':.5,'copper wire':2.3},
            named='explicit canonical build fixture supplies')['onto']
        sid=app.live.session.id
        floor=app.live.act({'session':sid,'op':'survey','at':[0,0]})['survey']['ground_m']
        collected={}
        for index in range(3):
            receipt=self.post('/api/world/goods/collect',{'session':sid,'pile':pile,
                'request_id':f'canonical-browser-collect-{index}',
                'person':{'eyes_m':[0,floor+1.62,0],'facing':[0,0,-1]}},world)
            for material,mass in receipt['collected'].items():
                collected[material]=collected.get(material,0)+mass
        self.assertEqual({'oak':40.,'iron':12.,'glass':5.,'copper':.5,'copper wire':2.3},collected)
        self.post('/api/world/fabrication/configure',{'session':sid,'scene':app.room.scene,
            'settings':funded.settings(stock_kg={},energy_j=0),'request_id':'canonical-browser-process'},world)
        candidate={'kind':'rover','parameters':{'capacity_j':1000.,'charge_j':1000.}}
        saved=self.post('/api/workshop/feedback',{**candidate,'save_design':True,'label':'Canonical rover'},world)
        self.chrome=flow.qa_browser.Chrome(1280,900);p=self.chrome.page
        p.send('Page.enable');p.send('Runtime.enable')
        p.send('Page.addScriptToEvaluateOnNewDocument',{'source':f'localStorage.setItem("banjo.player.{world}",{json.dumps(owner["token"])});'})
        def wait(expr):
            end=time.monotonic()+35
            while time.monotonic()<end:
                if p.evaluate('Boolean('+expr+')'):return
                time.sleep(.1)
            self.fail(expr+'; '+str(p.evaluate('document.body.innerText.slice(-1600)')))
        def click(selector):
            wait('document.querySelector("#ws-remake").getAttribute("aria-busy")!=="true"')
            point=p.evaluate('(()=>{const b=document.querySelector(%s);b.scrollIntoView({block:"center"});const r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()'%json.dumps(selector))
            for event in ('mousePressed','mouseReleased'):
                p.send('Input.dispatchMouseEvent',{'type':event,**point,'button':'left','clickCount':1})
            wait('document.querySelector("#ws-remake").getAttribute("aria-busy")!=="true"')
        p.send('Page.navigate',{'url':self.base+f'/world?world={world}&workshop=1&tab=recipes'})
        selector='#ws-pane-recipes [data-recipe="'+saved['design']['design_id']+'"] .ws-recipe-acts button:first-child'
        wait('document.querySelector(%s) && !document.querySelector(%s).disabled'%(json.dumps(selector),json.dumps(selector)))
        p.evaluate('document.querySelector(%s).click()'%json.dumps(selector))
        wait('document.querySelector("#ws-remake-stock-personal-oak")')
        for material in ('oak','iron','glass'):
            wait('document.querySelector("#ws-remake-stock-personal-'+material+'")')
            click('#ws-remake-stock-personal-'+material)
            wait('!document.querySelector("#ws-remake-stock-personal-'+material+'")')
        for substance in ('copper','copper wire'):
            selector='#ws-remake-goods-personal-'+substance.replace(' ','-')
            wait('document.querySelector('+json.dumps(selector)+')')
            click(selector);wait('!document.querySelector('+json.dumps(selector)+')')
        click('#ws-remake-connect');wait('document.querySelector("#ws-remake-charge-wait")')
        for _ in range(20):
            if p.evaluate('!document.querySelector("#ws-remake-start").disabled'):break
            if p.evaluate('document.querySelector("#ws-remake-energy").disabled'):
                click('#ws-remake-charge-wait');wait('!document.querySelector("#ws-remake-energy").disabled')
            click('#ws-remake-energy')
        wait('!document.querySelector("#ws-remake-start").disabled')
        click('#ws-remake-start');wait('document.querySelector("#ws-remake-step")')
        for _ in range(20):
            if p.evaluate('!!document.querySelector("#ws-remake-place")'):break
            click('#ws-remake-step')
        wait('document.querySelector("#ws-remake-place")');click('#ws-remake-place')
        wait('document.querySelector("#ws-remake a")?.textContent==="Collect in World"')
        job=next(iter(app.room.fabrication_record['jobs'].values()));root=job['root_body']
        p.send('Page.navigate',{'url':self.base+f'/world?world={world}&hold=1'})
        wait('window.banjoRoom?.ready()')
        p.evaluate('(()=>{const r=banjoRoom,b=r.world.bodies.get('+json.dumps(root)+');r.standAt(b.mesh.position.x,b.mesh.position.y+1,b.mesh.position.z+1);r.lookAt(...b.mesh.position.toArray())})()')
        wait('banjoRoom.world.aim?.name==='+json.dumps(root))
        # J runs the installed primary action through the ordinary server route.
        p.evaluate('banjoRoom.resume()')
        for event in ('keyDown','keyUp'):
            p.send('Input.dispatchKeyEvent',{'type':event,'code':'KeyJ','key':'j','windowsVirtualKeyCode':74})
        wait('banjoRoom.world.last?.text?.includes("Switched rover")')
        program=next(p for p in app.live.session.state['machines']['programs'] if p['body'] in job['root_bodies'])
        self.assertTrue(program['power'])
        wait('banjoRoom.world.machines.stores.some(s=>'+json.dumps(job['root_bodies'])+'.includes(s.body) && s.given_j>0)')
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        p.evaluate('banjoRoom.pick('+json.dumps(root)+')')
        (out/'canonical-paid-rover-use.png').write_bytes(base64.b64decode(p.send('Page.captureScreenshot',{'format':'png'})['data']))
        self.assertEqual([], [e for e in p.events if e.get('method')=='Runtime.exceptionThrown'])
        self.native_evidence={'quote':{k:job[k] for k in ('product_materials_kg','assembly_goods_kg','required_j','output_energy_j')},
            'use_program_power':program['power'],'audit':model.audit(app.room.fabrication_record),
            'supplies':'explicit collected fixture heap; generated native solar battery'}

    def test_lab_saved_mixed_machine_reviews_each_material_and_funds_initial_charge(self):
        from fabrication_tests import mixed_machine
        self.assertTrue(flow.qa_browser.CHROME.is_file(),'Chrome required for Lab machine acceptance')
        world,owner,app,_,_,_=self.batch(process=False)
        pile=app.brains.goods.put(0,0,{'oak':10.,'iron':10.,'copper':.5},named='machine browser test supplies')['onto']
        sid=app.live.session.id;floor=app.live.act({'session':sid,'op':'survey','at':[0,0]})['survey']['ground_m']
        self.post('/api/world/goods/collect',{'session':sid,'pile':pile,'request_id':'machine-lab-collect',
            'person':{'eyes_m':[0,floor+1.62,0],'facing':[0,0,-1]}},world)
        self.post('/api/world/fabrication/configure',{'session':sid,'scene':app.room.scene,
            'settings':funded.settings(stock_kg={},energy_j=0),'request_id':'machine-lab-empty-process'},world)
        saved=self.post('/api/workshop/feedback',{**mixed_machine(),'save_design':True,'label':'Mixed battery housing'},world)
        saved_id=saved['design']['design_id']
        self.chrome=flow.qa_browser.Chrome(1280,800);p=self.chrome.page
        p.send('Page.enable');p.send('Runtime.enable')
        p.send('Page.addScriptToEvaluateOnNewDocument',{'source':f'localStorage.setItem("banjo.player.{world}",{json.dumps(owner["token"])});'})
        def wait(expr):
            end=time.monotonic()+35
            while time.monotonic()<end:
                if p.evaluate('Boolean('+expr+')'):return
                time.sleep(.1)
            self.fail(expr+'; '+str(p.evaluate('document.body.innerText.slice(-1800)')))
        def click(selector):
            wait('document.querySelector("#ws-remake").getAttribute("aria-busy")!=="true"')
            box=p.evaluate('(()=>{const b=document.querySelector(%s);b.scrollIntoView({block:"center"});const r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()'%json.dumps(selector))
            p.send('Input.dispatchMouseEvent',{'type':'mousePressed',**box,'button':'left','clickCount':1})
            p.send('Input.dispatchMouseEvent',{'type':'mouseReleased',**box,'button':'left','clickCount':1})
            wait('document.querySelector("#ws-remake").getAttribute("aria-busy")!=="true"')
        p.send('Page.navigate',{'url':self.base+f'/world?world={world}&workshop=1&tab=recipes'})
        selector='#ws-pane-recipes [data-recipe="'+saved_id+'"] .ws-recipe-acts button:first-child'
        wait('document.querySelector(%s) && !document.querySelector(%s).disabled'%(json.dumps(selector),json.dumps(selector)))
        p.evaluate('document.querySelector(%s).click()'%json.dumps(selector))
        wait('document.querySelector("#ws-remake-stock-personal-oak") && document.querySelector("#ws-remake-stock-personal-iron")')
        self.assertTrue(p.evaluate('document.querySelector("#ws-remake-start").disabled'))
        self.assertIn('Battery charge',p.evaluate('document.querySelector("#ws-remake").textContent'))
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/'lab-machine-costs.png').write_bytes(base64.b64decode(p.send('Page.captureScreenshot',{'format':'png'})['data']))
        click('#ws-remake-stock-personal-oak')
        wait('!document.querySelector("#ws-remake-stock-personal-oak")')
        self.assertTrue(p.evaluate('document.querySelector("#ws-remake-start").disabled'))
        self.assertTrue(p.evaluate('Boolean(document.querySelector("#ws-remake-stock-personal-iron"))'))
        click('#ws-remake-stock-personal-iron')
        wait('!document.querySelector("#ws-remake-stock-personal-iron")')
        self.assertTrue(p.evaluate('document.querySelector("#ws-remake-start").disabled'))
        self.assertIn('Copper needed',p.evaluate('document.querySelector("#ws-remake").textContent'))
        # Real processed inventory, explicit funding button and one debit. A
        # lost acknowledgement must retain the same transfer across reload.
        p.evaluate('''(()=>{const original=window.fetch;let lose=true;window.fetch=async(...args)=>{
            const result=await original(...args);if(lose && args[0].endsWith('/fabrication/fund_goods')){
                lose=false;throw Error('Injected lost processed goods acknowledgement');}return result;};})()''')
        click('#ws-remake-goods-personal-copper')
        wait('document.querySelector("#ws-remake-retry-fund_goods")')
        p.send('Page.reload',{'ignoreCache':True})
        wait('document.querySelector("#ws-remake-review") && !document.querySelector("#ws-remake").hidden')
        click('#ws-remake-review');wait('document.querySelector("#ws-remake-retry-fund_goods")')
        click('#ws-remake-retry-fund_goods')
        wait('!document.querySelector("#ws-remake-retry-fund_goods") && document.querySelector("#ws-remake-connect")')
        self.assertEqual({'copper':.5},app.room.fabrication_record['goods_stock_kg'])
        click('#ws-remake-connect')
        wait('document.querySelector("#ws-remake-charge-wait")')
        for _ in range(3):
            if p.evaluate('!document.querySelector("#ws-remake-start").disabled'):break
            if p.evaluate('document.querySelector("#ws-remake-energy").disabled'):
                click('#ws-remake-charge-wait')
                wait('!document.querySelector("#ws-remake-energy").disabled')
            click('#ws-remake-energy')
            wait('!document.querySelector("#ws-remake-start").disabled || document.querySelector("#ws-remake-energy")?.disabled')
        wait('!document.querySelector("#ws-remake-start").disabled')
        click('#ws-remake-start');wait('document.querySelector("#ws-remake-step")')
        click('#ws-remake-step');wait('document.querySelector("#ws-remake-place")')
        click('#ws-remake-place')
        wait('document.querySelector("#ws-remake a")?.textContent==="Collect in World"')
        job=next(iter(app.room.fabrication_record['jobs'].values()))
        receipt=next(r for r in app.room.workshop_installs if r.get('fabrication_job_id'))
        native=install._snapshot(app.live)
        battery=next(s for s in native['energy_stores'] if s['body'] in job['root_bodies'])
        self.assertEqual(200.,battery['charge_j']);self.assertEqual('unmodeled',receipt['thermal_state'])
        self.assertEqual(3,len(app.room.fabrication_record['stock_imports']))
        self.assertEqual({'copper':.5},job['assembly_goods_kg'])
        self.assertEqual({'copper':0.},app.room.fabrication_record['goods_stock_kg'])
        self.assertEqual('installed',job['status'])
        self.assertLess(abs(model.audit(app.room.fabrication_record)['energy_residual_j']),1e-7)
        self.native_evidence={'materials_kg':job['stock_materials_kg'],'work_j':job['required_j'],
            'initial_battery_j':battery['charge_j'],'supplies':'explicit collected fixture heap; generated solar source',
            'audit':model.audit(app.room.fabrication_record)}
        (out/'lab-machine-installed.png').write_bytes(base64.b64decode(p.send('Page.captureScreenshot',{'format':'png'})['data']))
        self.assertEqual([], [e for e in p.events if e.get('method')=='Runtime.exceptionThrown'])

    def test_lab_source_plan_native_paid_start_progress_placement_and_private_owner(self):
        self.assertTrue(flow.qa_browser.CHROME.is_file(),'Chrome required for Lab remake acceptance')
        world,owner,app,_,_,_=self.batch(process=False)
        peer=self.join(world,'Remake peer')
        # Use the generated solar yard's actual finite store. No fixture
        # battery, initial charge refill, extra body or native reopen.
        meters=self.post('/api/world/fabrication/state',{'session':app.live.session.id,'scene':app.room.scene},world)['energy_sources']
        solar=next(s for s in meters if s['max_power_w']>0)
        self.assertEqual(10000.,solar['max_power_w']);self.assertEqual(2e7,solar['capacity_j'])
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
        original=deepcopy(next(b for b in install._snapshot(app.live)['bodies'] if b['name']=='field pick'))
        chrome=flow.qa_browser.Chrome(1280,800);self.chrome=chrome;p=chrome.page
        p.send('Page.enable');p.send('Runtime.enable')
        p.send('Page.addScriptToEvaluateOnNewDocument',{'source':'''window.__fundedFailures=[];
            const fetchObserved=window.fetch;window.fetch=async(url,options)=>{
                const response=await fetchObserved(url,options);
                if(!response.ok){let body={};try{body=JSON.parse(options?.body || '{}');}catch{}
                    window.__fundedFailures.push({url:String(url),op:body.op,error:(await response.clone().json()).error});}
                return response;};'''})
        p.send('Page.addScriptToEvaluateOnNewDocument',{'source':f'localStorage.setItem("banjo.player.{world}",{json.dumps(owner["token"])});'})
        def wait(expr):
            end=time.monotonic()+30
            while time.monotonic()<end:
                if p.evaluate('Boolean('+expr+')'):return
                time.sleep(.1)
            self.fail(expr+'; '+str(p.evaluate('window.__fundedFailures'))+'; '+str(p.evaluate('document.body.innerText.slice(-1800)')))
        url=self.base+f'/world?world={world}&workshop=1&tab=lab&carry=field%20pick'
        p.send('Page.navigate',{'url':url})
        wait('document.querySelector("#ws-remake-review") && !document.querySelector("#ws-remake").hidden')
        p.evaluate('document.querySelector("#ws-remake-review").click()')
        wait('document.querySelector("#ws-remake-stock-personal")')
        self.assertTrue(p.evaluate('document.querySelector("#ws-remake-start").disabled'))
        self.assertTrue(p.evaluate('document.querySelector(".ws-left > .game-tabs").getBoundingClientRect().bottom <= document.querySelector("#ws-remake").getBoundingClientRect().top'))
        fund_shots=ROOT/'build/resource-flow';fund_shots.mkdir(parents=True,exist_ok=True)
        wait('document.querySelector("#workshop-stage").visibleGeometry()?.meshes>0')
        p.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))',await_promise=True)
        (fund_shots/'lab-remake-funding.png').write_bytes(base64.b64decode(p.send('Page.captureScreenshot',{'format':'png'})['data']))
        shared_before=deepcopy(self.post('/api/world/fabrication/state',context,world)['stock_sources'])
        # The real operation commits; its acknowledgement is lost at the client.
        # Reload + retry must confirm the original transfer, not spend again.
        p.evaluate('''(()=>{const original=window.fetch;let lose=true;window.fetch=async(...args)=>{
            const result=await original(...args);if(lose && args[0].endsWith('/fabrication/fund_stock')){
                lose=false;throw Error('Injected lost transfer acknowledgement');}return result;};})()''')
        p.evaluate('document.querySelector("#ws-remake-stock-personal").click()')
        wait('document.body.textContent.includes("Injected lost transfer acknowledgement")')
        self.assertEqual(1,len(app.room.fabrication_record['stock_imports']))
        self.assertAlmostEqual(25.-plan['quote']['stock_kg'],flow.GoodsJourney.personal(self,app,owner)['oak'],places=6)
        p.send('Page.navigate',{'url':url})
        wait('document.querySelector("#ws-remake-review") && !document.querySelector("#ws-remake").hidden')
        p.evaluate('document.querySelector("#ws-remake-review").click()')
        wait('document.querySelector("#ws-remake-retry-fund_stock")')
        p.evaluate('document.querySelector("#ws-remake-retry-fund_stock").click()')
        wait('document.querySelector("#ws-remake-connect") && !document.querySelector("#ws-remake-retry-fund_stock")')
        self.assertEqual(1,len(app.room.fabrication_record['stock_imports']))
        current=self.post('/api/world/fabrication/state',context,world)['stock_sources']
        self.assertEqual([s for s in shared_before if s['pool']=='shared'],[s for s in current if s['pool']=='shared'])
        p.evaluate('document.querySelector("#ws-remake-connect").click()')
        wait('document.querySelector("#ws-remake-charge-wait")')
        self.assertTrue(p.evaluate('document.querySelector("#ws-remake-energy").disabled'))
        plans_before_wait=len(app._fabrication_remake_plans)
        p.evaluate('document.querySelector("#ws-remake-charge-wait").click()')
        wait('document.querySelector("#ws-remake-energy") && !document.querySelector("#ws-remake-energy").disabled')
        self.assertEqual(plans_before_wait,len(app._fabrication_remake_plans),'Supply refresh allocated another frozen plan')
        p.evaluate('''(()=>{const original=window.fetch;let lose=true;window.fetch=async(...args)=>{
            const result=await original(...args);if(lose && args[0].endsWith('/fabrication/fund_energy')){
                lose=false;throw Error('Injected lost energy acknowledgement');}return result;};})()''')
        p.evaluate('document.querySelector("#ws-remake-energy").click()')
        wait('document.body.textContent.includes("Injected lost energy acknowledgement")')
        p.send('Page.navigate',{'url':url})
        wait('document.querySelector("#ws-remake-review") && !document.querySelector("#ws-remake").hidden')
        p.evaluate('document.querySelector("#ws-remake-review").click()')
        wait('document.querySelector("#ws-remake-retry-fund_energy")')
        self.assertTrue(p.evaluate('document.querySelector("#ws-remake-start").disabled'))
        p.evaluate('document.querySelector("#ws-remake-retry-fund_energy").click()')
        wait('document.querySelector("#ws-remake-start") && !document.querySelector("#ws-remake-start").disabled')
        context['session']=app.live.session.id
        self.assertEqual(1,len(app.room.fabrication_record['energy_imports']))
        self.assertAlmostEqual(plan['quote']['supply_required_j'],app.room.fabrication_record['energy_j'],places=6)
        p.evaluate('document.querySelector("#ws-remake-start").click()')
        wait('document.querySelector("#ws-remake-step")')
        ident=next(iter(app.room.fabrication_record['jobs']))
        with self.assertRaises(urllib.error.HTTPError) as peer_pause:self.post('/api/world/fabrication/pause',{**context,'job_id':ident,
            'revision':app.room.fabrication_record['revision'],'request_id':'peer-remake-pause-0001'},world,peer['token'])
        self.assertIn('Only the player who started',peer_pause.exception.read().decode())
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
        with self.assertRaises(urllib.error.HTTPError) as peer_preview:self.post('/api/world/fabrication/preview',{**context,'job_id':ident,'position_m':[3,0]},world,peer['token'])
        self.assertIn('Only the player who started',peer_preview.exception.read().decode())
        p.evaluate('document.querySelector("#ws-remake-place").click()')
        wait('document.querySelector("#ws-remake a")?.textContent==="Collect in World"')
        self.assertEqual('installed',app.room.fabrication_record['jobs'][ident]['status'])
        self.assertEqual(original,next(b for b in install._snapshot(app.live)['bodies'] if b['name']=='field pick'))
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/'lab-remake.png').write_bytes(base64.b64decode(p.send('Page.captureScreenshot',{'format':'png'})['data']))
        root=app.room.fabrication_record['jobs'][ident]['root_body']
        # Native collection admits actual fragments only. The new whole hull
        # must stay available for pickup even inside a large collection radius.
        swept=self.post('/api/live/act',{'session':app.live.session.id,'op':'collect',
            'at':next(b for b in app.live.session.state['bodies'] if b['name']==root)['position_m'],
            'radius_m':2.,'largest_cells':10000},world)
        self.assertEqual([],swept['collected'])
        for op,args in (('draw',{'store':1,'joules':1}),('energy_store',{}),('close',{})):
            with self.assertRaises(urllib.error.HTTPError) as authoring:
                self.post('/api/live/act',{'session':app.live.session.id,'op':op,**args},world)
            self.assertIn('authoring operation is not allowed',authoring.exception.read().decode())
        world_link=p.evaluate('document.querySelector("#ws-remake a").href')
        p.send('Page.navigate',{'url':world_link})
        wait('window.banjoRoom?.ready()')
        self.assertEqual(root,p.evaluate('banjoRoom.picked().name'))
        def key(code):
            for kind in ('keyDown','keyUp'):p.send('Input.dispatchKeyEvent',{'type':kind,'code':code,'key':code[-1].lower()})
        p.evaluate('''(()=>{const at=banjoRoom.world.bodies.get(%s).mesh.position;
            banjoRoom.standAt(at.x-.8,banjoRoom.groundAt(at.x,at.z)+1.62,at.z);
            banjoRoom.lookAt(at.x,at.y,at.z);document.activeElement.blur();banjoRoom.resume();})()'''%json.dumps(root))
        time.sleep(.6);key('KeyE')
        wait('banjoRoom.world.held?.name===%s && banjoRoom.world.use.mode==="tool-ready"'%json.dumps(root))
        self.assertIn('put it in your bag',p.evaluate('banjoRoom.details().rows.map(r=>r[1]).join(" · ")'))
        self.assertNotIn('sweep it up',p.evaluate('banjoRoom.details().rows.map(r=>r[1]).join(" · ")'))
        key('KeyQ')
        wait('!banjoRoom.world.held && banjoRoom.world.inventory.stowed.some(t=>t?.name===%s)'%json.dumps(root))
        slot=p.evaluate('banjoRoom.world.inventory.stowed.findIndex(t=>t?.name===%s)'%json.dumps(root))
        self.assertGreaterEqual(slot,0)
        p.evaluate(f'banjoRoom.fromSlot({slot})',await_promise=True)
        wait('banjoRoom.world.held?.name===%s && banjoRoom.world.use.mode==="tool-ready"'%json.dumps(root))
        p.evaluate('banjoRoom.standAt(-.9,banjoRoom.groundAt(-.9,.025)+1.62,.025);'
            'banjoRoom.lookAt(.3,banjoRoom.groundAt(.3,.025),.025);document.activeElement.blur()')
        time.sleep(.4)
        p.evaluate('banjoRoom.world.use.last=null');key('KeyJ')
        wait('banjoRoom.world.use.last && banjoRoom.world.use.mode==="tool-ready"')
        used=p.evaluate('banjoRoom.world.use.last')
        self.assertNotIn('refused',used,used)
        self.assertGreater(used['result']['loosened_kg'],0,used)
        self.assertGreater(used['result']['work_j'],0,used)
        self.assertTrue(used['result']['supported'],used)
        self.assertEqual(original,next(b for b in install._snapshot(app.live)['bodies'] if b['name']=='field pick'))
        peer_shown=self.post('/api/world/inventory/shown',{'session':app.live.session.id},world,peer['token'])
        self.assertEqual(0,peer_shown['carried']['sand_kg']+peer_shown['carried']['soil_kg'])
        self.assertFalse(any(t and t['name']==root for t in list(peer_shown['hands'].values())+peer_shown['stowed']))
        (out/'lab-remake-used.png').write_bytes(base64.b64decode(p.send('Page.captureScreenshot',{'format':'png'})['data']))
        self.native_evidence={'material':'oak','stock_kg':plan['quote']['stock_kg'],
            'supply_j':plan['quote']['supply_required_j'],'collect_bag_equip_use':True,
            'tool_result':used['result'],'lost_stock_ack_retry':True,'lost_energy_ack_retry':True,
            'generated_solar_source':solar['name'],'generated_source_power_w':solar['max_power_w']}
        self.assertEqual([], [e for e in p.events if e.get('method')=='Runtime.exceptionThrown'])
        context['session']=app.live.session.id
        more=self.post('/api/world/goods/collect',{'session':context['session'],'pile':pile['name'],'request_id':'remake-more-oak',
            'person':{'eyes_m':[at[0],floor+1.62,at[1]],'facing':[0,0,-1]}},world)
        self.assertEqual({'oak':25.},more['collected'])
        mass=app.room.fabrication_record['jobs'][ident]['stock_kg']
        self.assertAlmostEqual(50.-mass,flow.GoodsJourney.personal(self,app,owner)['oak'],places=6)

        # Save the actual recovered recipe, then use Recipes Make. This must
        # open the reviewed paid flow without a physical carried source.
        p.evaluate('banjoRoom.hold()');wait('!banjoRoom.world.busy')
        saved=self.post('/api/workshop/feedback',{**recipe,'save_design':True,'label':'Saved funded pick'},world)
        saved_id=saved['design']['design_id']
        p.send('Page.navigate',{'url':self.base+f'/world?world={world}&workshop=1&tab=recipes'})
        selector='#ws-pane-recipes [data-recipe="'+saved_id+'"] .ws-recipe-acts button:first-child'
        wait('document.querySelector(%s) && !document.querySelector(%s).disabled'%(json.dumps(selector),json.dumps(selector)))
        jobs_before=len(app.room.fabrication_record['jobs']);rack_before=flow.GoodsJourney.personal(self,app,owner)['oak']
        p.evaluate('document.querySelector(%s).click()'%json.dumps(selector))
        wait('document.querySelector("#ws-remake-start")?.textContent==="Start make"')
        self.assertEqual(jobs_before,len(app.room.fabrication_record['jobs']))
        self.assertEqual(rack_before,flow.GoodsJourney.personal(self,app,owner)['oak'])
        self.assertNotIn('Damage retained',p.evaluate('document.querySelector("#ws-remake").textContent'))
        p.evaluate('document.querySelector("#ws-remake-stock-personal").click()')
        wait('!document.querySelector("#ws-remake-stock-personal")')
        if p.evaluate('Boolean(document.querySelector("#ws-remake-energy")?.disabled)'):
            p.evaluate('document.querySelector("#ws-remake-charge-wait").click()')
        wait('document.querySelector("#ws-remake-energy") && !document.querySelector("#ws-remake-energy").disabled')
        p.evaluate('document.querySelector("#ws-remake-energy").click()')
        wait('document.querySelector("#ws-remake-start") && !document.querySelector("#ws-remake-start").disabled')
        p.evaluate('document.querySelector("#ws-remake-start").click()')
        wait('document.querySelector("#ws-remake-step")')
        new_ident=next(k for k,j in app.room.fabrication_record['jobs'].items() if j.get('make_source'))
        with self.assertRaises(urllib.error.HTTPError) as private_make:
            self.post('/api/world/fabrication/pause',{'scene':app.room.scene,'session':app.live.session.id,
                'job_id':new_ident,'revision':app.room.fabrication_record['revision'],'request_id':'peer-new-make-pause'},world,peer['token'])
        self.assertIn('Only the player',private_make.exception.read().decode())
        p.evaluate('document.querySelector("#ws-remake-step").click()')
        wait('document.querySelector("#ws-remake-place")');p.evaluate('document.querySelector("#ws-remake-place").click()')
        wait('document.querySelector("#ws-remake a")?.textContent==="Collect in World"')
        made=next(j for j in app.room.fabrication_record['jobs'].values() if j.get('make_source'))
        self.assertEqual(owner['id'],made['make_source']['owner']);self.assertNotIn('remake_source',made)
        self.assertEqual('installed',made['status']);self.assertAlmostEqual(mass,made['stock_kg'],places=10)
        self.assertAlmostEqual(rack_before-mass,flow.GoodsJourney.personal(self,app,owner)['oak'],places=6)
        self.assertEqual(original,next(b for b in install._snapshot(app.live)['bodies'] if b['name']=='field pick'))
        self.native_evidence['saved_design_paid_make']=True
        (out/'lab-paid-saved-design.png').write_bytes(base64.b64decode(p.send('Page.captureScreenshot',{'format':'png'})['data']))
        self.assertEqual([], [e for e in p.events if e.get('method')=='Runtime.exceptionThrown'])


if __name__=='__main__':unittest.main()
