"""Selected native source binding, finite remake and ordinary Lab controls."""
import base64
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import sys
import time
import threading
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

    def test_paid_manufactured_mount_failure_retains_receipt_and_paid_replacement_works(self):
        """Real paid source and catalog mount; failure is during lift, not a target hit."""
        import object_strike_tests as strikes
        import workshop_fixed_assembly_tests as mixed
        import tool_use
        marker=deepcopy(self.room.spec['bodies'][0])
        marker.update(center_mm=[-3000,1500,0],size_mm=[40,40,40],anchored=True)
        spec=strikes.fixture('glass');spec.update(cell_m=.005,tool_points=[],interactions=[])
        spec['bodies']=spec['bodies'][2:]+[marker];spec['joints']=spec['joints'][1:]
        spec['bodies'][0]['size_mm']=[60,60,60];spec['bodies'][1]['size_mm']=[40,40,40]
        spec['joints'][0].update(holds_tension_n=1e9,holds_shear_n=1e9)
        spec['machines']=deepcopy(self.room.spec['machines'])
        self.room.spec=spec;self.app.reply_listeners=[]
        self.app.on_live_reply=lambda session,reply:[f(session,reply) for f in list(self.app.reply_listeners)]
        self.live.open(self.app,{'spec':spec})
        self.assertEqual(0,self.live.session.send(op='survey',at=[0,0])['survey']['floor_m'])
        def paid(design,ident,at,source=None):
            plan=self.plan(source,design) if source else self.call('plan_make',candidate=design)
            for material,mass in model.materials(plan['quote'],'stock').items():
                api.request(self.app,'fund_stock',self.request(mass,material,ident+'-feed-'+material))
            reading=self.call('state');store=reading['energy_sources'][0]
            self.call('connect_energy',store=store['id'],store_hash=store['store_hash'],power_w=250,
                revision=reading['state']['revision'],request_id=ident+'-connect')
            api.wait(self.app,{**self.context(),'seconds':math.ceil(plan['quote']['supply_required_j']/250)})
            reading=self.call('state');store=reading['energy_sources'][0]
            self.call('fund_energy',store_hash=store['store_hash'],joules=plan['quote']['supply_required_j'],
                revision=reading['state']['revision'],request_id=ident+'-energy')
            plan=self.plan(source,design) if source else self.call('plan_make',candidate=design)
            operation='start_remake' if source else 'start_make'
            request={**self.context(),'plan_id':plan['plan_id'],'revision':plan['revision'],'request_id':ident}
            if source:
                before=install._snapshot(self.live);ledger=deepcopy(self.room.fabrication_record)
                with mock.patch.object(self.app.store,'save',side_effect=OSError('paid source save failure')):
                    with self.assertRaises(OSError):api.request(self.app,operation,request)
                self.assertEqual(before,install._snapshot(self.live));self.assertEqual(ledger,self.room.fabrication_record)
            api.request(self.app,operation,request)
            self.assertTrue(api.request(self.app,operation,request)['replayed'])
            job=self.room.fabrication_record['jobs'][ident]
            api.wait(self.app,{**self.context(),'seconds':math.ceil(job['minimum_duration_s'])})
            preview=api.preview(self.app,{**self.context(),'job_id':ident,'position_m':at})
            placement={**self.context(),'job_id':ident,'preview_id':preview['preview_id'],
                       'request_id':ident+'-place'}
            if source:
                before=install._snapshot(self.live);ledger=deepcopy(self.room.fabrication_record)
                inventory_before=inventory_room.inventory_of(self.app).record()
                with mock.patch.object(self.app.store,'save',side_effect=OSError('paid placement save failure')):
                    with self.assertRaisesRegex(OSError,'paid placement save failure'):
                        api.commit(self.app,placement)
                self.assertEqual(before,install._snapshot(self.live))
                self.assertEqual(ledger,self.room.fabrication_record)
                self.assertEqual(inventory_before,inventory_room.inventory_of(self.app).record())
                self.assertEqual('ready',self.room.fabrication_record['jobs'][ident]['status'])
                placement['session']=self.live.session.id
            made=api.commit(self.app,placement)
            after=install._snapshot(self.live);ledger=deepcopy(self.room.fabrication_record)
            self.assertTrue(api.commit(self.app,{**placement,'session':self.live.session.id})['replayed'])
            self.assertEqual(after,install._snapshot(self.live))
            self.assertEqual(ledger,self.room.fabrication_record)
            return made,request
        design=mixed.pick();design['parameters'].update(length_m=.4,arm_m=.16,section_m=.02)
        design['parameters']['ground_tool']['point'].update(tip_local_m=[0,0,-.08],width_m=.08,thickness_m=.08)
        design['parameters']['ground_tool']['grip']['position_local_m']=[-.18,0,0]
        design['component_overrides'].update(haft={'size_m':[.4,.005,.005],'center_m':[0,.0025,.0825]},
            arm={'material':'iron','size_m':[.08,.08,.16],'center_m':[.2375,.04,0]})
        original,_=paid(design,'paid-thin-source',[0,1.5])
        self.assertEqual(275,original['fixed_interfaces'][0]['holds_shear_n'])
        person={'standing_m':[-1.25,-.12,0],'eyes_m':[-1.25,1.5,0],
                'facing':[1,0,0],'look_direction':[1,0,0]}
        def inventory(op,item,key):
            shown=inventory_room.shown(self.app)
            answer=inventory_room.request(self.app,{'session':self.live.session.id,'op':op,'item':item,
                'revision':shown['record']['revision'],'request':key,'person':person})
            self.assertTrue(answer['ok'],answer)
            return answer
        def use():
            stop=threading.Event();errors=[]
            def clock():
                try:
                    while not stop.is_set():
                        self.live.act({'session':self.live.session.id,'op':'step','dt':1/240,'n':1});time.sleep(1/240)
                except Exception as error:errors.append(str(error))
            pump=threading.Thread(target=clock,daemon=True);pump.start()
            try:return tool_use.run(self.app,{'person':person,'target_name':'target'})
            finally:stop.set();pump.join(5);self.assertEqual([],errors)
        source=original['root_body'];inventory('take_up',source,'paid-source-pickup')
        failed=use();self.assertIn('refused',failed,failed)
        self.assertEqual('lift',failed['result']['phase']);self.assertEqual([],failed['result']['impacts'])
        self.assertEqual('tool-connection-failed',failed['result']['outcome'])
        self.assertEqual([],failed['result']['target_connections_failed'])
        self.assertEqual([],failed['did']);self.assertFalse(failed['repeat'])
        failure=failed['result']['parted_joints'][0]
        self.assertIn('axial and bending',failure['parted_because'])
        self.assertGreater(failure['parted_load_n'],2250);self.assertEqual(2250,failure['parted_capacity_n'])
        stored=inventory('stow',source,'paid-broken-source-stow')
        self.assertEqual([source],stored['room']['parts'])
        replacement=mixed.pick();replacement['parameters'].update(length_m=.4,arm_m=.16,section_m=.03)
        replacement['parameters']['ground_tool']['point']['tip_local_m']=[0,0,-.08]
        replacement['parameters']['ground_tool']['grip']['position_local_m']=[-.17,0,0]
        before=install._snapshot(self.live)
        made,request=paid(replacement,'paid-source-replacement',[0,1],source)
        after=install._snapshot(self.live)
        # Funding advances the clock; the parked original's failure history
        # stays exact rather than claiming that a moving loose head is frozen.
        original_joint=next(j for j in before['joints'] if j['id']==failure['id'])
        self.assertEqual(original_joint,next(j for j in after['joints'] if j['id']==failure['id']))
        inventory('take_up',made['root_body'],'paid-replacement-pickup')
        used=use();self.assertNotIn('refused',used,used)
        self.assertTrue(used['result']['impacts'],used);self.assertTrue(used['result']['working_point_connected'])
        final=install._snapshot(self.live);ledger=deepcopy(self.room.fabrication_record);model.advance(ledger,final['t_s'])
        api._persist(self.app,self.room,final,ledger)
        saved=self.app.store.load('fabrication');opened=self.live.open(self.app,{'spec':saved.spec,'snapshot':saved.world_record})
        self.app.room=self.room=saved;shown=inventory_room.after_open(self.app,opened)
        self.assertEqual(source,shown['stowed'][0]['id'])
        reopened_failure=next(j for j in self.live.session.send(op='joints')['joints'] if j['id']==failure['id'])
        self.assertFalse(reopened_failure['attached'])
        self.assertEqual(failure['parted_because'],reopened_failure['parted_because'])
        self.assertTrue(api.request(self.app,'start_remake',{**request,'session':self.live.session.id})['replayed'])
        binding=self.room.fabrication_record['jobs']['paid-source-replacement']['remake_source']
        self.assertTrue(any(j['id']==failure['id'] and not j['attached'] for r in binding['condition'] for j in r['joints']))
        audit=model.audit(self.room.fabrication_record)
        self.assertLess(abs(audit['energy_residual_j']),1e-7)
        self.assertLess(max(abs(v) for v in audit['material_residual_kg'].values()),1e-12)
        (ROOT/'build/resource-flow/paid-source-lift-replacement.json').write_text(json.dumps({
            'original':original,'failure':failed,'replacement':made,'used':used,'audit':audit,
            'limits':'5 mm finite-supply fixture; original fails while lifting, not from target contact. No fresh-world, internal fracture, wear or genuine repair qualification.'},indent=2),encoding='utf-8')

    def test_paid_made_target_strike_separates_and_paid_replacement_retains_damage(self):
        """Actual sampled catalog mount, paid target, ordinary Use, paid reuse.

        Finite-rack 5 mm fixture; the other native actor supports the head.
        This is not a fresh-map supply or private peer inventory qualification.
        """
        import workshop_fixed_assembly_tests as mixed
        import tool_use
        self.room.spec['cell_m']=.005
        self.room.spec['bodies'][0].update(size_mm=[40,40,40],center_mm=[-3000,1500,0],anchored=True)
        self.app.reply_listeners=[]
        self.app.on_live_reply=lambda s,r:[f(s,r) for f in list(self.app.reply_listeners)]
        self.live.open(self.app,{'spec':self.room.spec})
        def paid(design,key,at,source=None):
            plan=self.plan(source,design) if source else self.call('plan_make',candidate=design)
            for material,mass in model.materials(plan['quote'],'stock').items():
                api.request(self.app,'fund_stock',self.request(mass,material,key+'-feed-'+material))
            reading=self.call('state');energy=reading['energy_sources'][0]
            self.call('connect_energy',store=energy['id'],store_hash=energy['store_hash'],power_w=250,
                revision=reading['state']['revision'],request_id=key+'-connect')
            api.wait(self.app,{**self.context(),'seconds':math.ceil(plan['quote']['supply_required_j']/250)})
            reading=self.call('state');energy=reading['energy_sources'][0]
            self.call('fund_energy',store_hash=energy['store_hash'],joules=plan['quote']['supply_required_j'],
                revision=reading['state']['revision'],request_id=key+'-energy')
            plan=self.plan(source,design) if source else self.call('plan_make',candidate=design)
            request={**self.context(),'plan_id':plan['plan_id'],'revision':plan['revision'],'request_id':key}
            api.request(self.app,'start_remake' if source else 'start_make',request)
            job=self.room.fabrication_record['jobs'][key]
            api.wait(self.app,{**self.context(),'seconds':math.ceil(job['minimum_duration_s'])})
            preview=api.preview(self.app,{**self.context(),'job_id':key,'position_m':at})
            placement={**self.context(),'job_id':key,'preview_id':preview['preview_id'],'request_id':key+'-place'}
            if source:
                before=install._snapshot(self.live);ledger=deepcopy(self.room.fabrication_record)
                inv=inventory_room.inventory_of(self.app).record()
                with mock.patch.object(self.app.store,'save',side_effect=OSError('made target placement save failed')):
                    with self.assertRaises(OSError):api.commit(self.app,placement)
                self.assertEqual(before,install._snapshot(self.live));self.assertEqual(ledger,self.room.fabrication_record)
                self.assertEqual(inv,inventory_room.inventory_of(self.app).record())
            receipt=api.commit(self.app,placement)
            before=install._snapshot(self.live);ledger=deepcopy(self.room.fabrication_record)
            self.assertTrue(api.commit(self.app,placement)['replayed'])
            self.assertEqual(before,install._snapshot(self.live));self.assertEqual(ledger,self.room.fabrication_record)
            return receipt,request
        sturdy=mixed.pick();sturdy['parameters'].update(length_m=.4,arm_m=.16,section_m=.04)
        sturdy['parameters']['ground_tool']['point']['tip_local_m']=[0,0,-.08]
        sturdy['parameters']['ground_tool']['grip']['position_local_m']=[-.16,0,0]
        source,_=paid(sturdy,'strike-source',[-.9,1])
        fragile=deepcopy(sturdy)
        fragile['parameters']['ground_tool']['point'].update(tip_local_m=[0,0,-.06],width_m=.06,thickness_m=.06)
        fragile['parameters']['ground_tool']['grip']['position_local_m']=[-.18,0,0]
        fragile['component_overrides'].update(haft={'size_m':[.8,.005,.005],'center_m':[0,.0025,.0625]},
            arm={'material':'iron','size_m':[.06,.06,.12],'center_m':[.4275,.03,0]})
        target,_=paid(fragile,'strike-target',[.4,0])
        head=target['component_to_body']['arm'];root=target['root_body']
        grip=next(b['position_m'] for b in self.live.session.send(op='poses')['bodies'] if b['name']==head)
        self.live.act({'session':self.live.session.id,'actor':'supporter','op':'wield','name':head,'grip':grip})
        with self.live.as_actor('supporter'):
            grip=self.live.session.send(op='poses')['hand']['grip_m'];high=[grip[0],grip[1]+1,grip[2]]
            self.live.act({'session':self.live.session.id,'op':'stroke','path':[grip,high],
                'speed_m_s':.3,'accel_m_s2':1,'lead_m':.025,'give_up_s':4,'let_go':False})
        for _ in range(10):self.live.act({'session':self.live.session.id,'op':'step','dt':1/240,'n':120})
        joint=next(j for j in self.live.session.send(op='joints')['joints'] if root in (j['a'],j['b']))
        self.assertTrue(joint['attached']);self.assertEqual(2250,joint['holds_tension_n'])
        person={'standing_m':[-.8,0,0],'eyes_m':[-.8,1.62,0],'facing':[1,0,0]}
        def inventory(op,item,key):
            shown=inventory_room.shown(self.app)
            answer=inventory_room.request(self.app,{'session':self.live.session.id,'op':op,'item':item,
                'revision':shown['record']['revision'],'request':key,'person':person})
            self.assertTrue(answer['ok'],answer);return answer
        def use(name):
            at=next(b['position_m'] for b in self.live.session.send(op='poses')['bodies'] if b['name']==name)
            direction=[at[i]-person['eyes_m'][i] for i in range(3)];norm=math.sqrt(sum(v*v for v in direction))
            person['look_direction']=[v/norm for v in direction]
            stop=threading.Event();errors=[]
            def clock():
                try:
                    while not stop.is_set():
                        self.live.act({'session':self.live.session.id,'op':'step','dt':1/240,'n':1});time.sleep(1/240)
                except Exception as error:errors.append(str(error))
            pump=threading.Thread(target=clock,daemon=True);pump.start()
            try:return tool_use.run(self.app,{'session':self.live.session.id,'person':person,'target_name':name})
            finally:stop.set();pump.join(5);self.assertEqual([],errors)
        inventory('take_up',source['root_body'],'strike-source-take')
        hit=use(root);self.assertNotIn('refused',hit,hit)
        self.assertEqual('target-connection-failed',hit['result']['outcome'],hit)
        self.assertTrue(hit['result']['impacts']);self.assertEqual([],hit['result']['tool_connections_failed'])
        failure=next(j for j in hit['result']['parted_joints'] if j['id']==joint['id'])
        self.assertIn('axial and bending',failure['parted_because'])
        self.assertGreater(failure['parted_load_n'],failure['parted_capacity_n'])
        masses={b['name']:b['mass_kg'] for b in self.live.session.send(op='poses')['bodies']}
        self.assertAlmostEqual(target['mass_kg'],sum(masses[n] for n in target['component_to_body'].values()))
        inventory('stow',source['root_body'],'strike-source-stow')
        inventory('take_up',root,'strike-damaged-take')
        stored=inventory('stow',root,'strike-damaged-stow')
        self.assertEqual([root],stored['room']['parts'])
        before=install._snapshot(self.live)
        replacement_design=deepcopy(sturdy)
        replacement_design['parameters']['section_m']=.03
        replacement_design['parameters']['ground_tool']['grip']['position_local_m']=[-.17,0,0]
        replacement,request=paid(replacement_design,'struck-replacement',[0,1],root)
        after=install._snapshot(self.live)
        self.assertEqual(next(j for j in before['joints'] if j['id']==joint['id']),
            next(j for j in after['joints'] if j['id']==joint['id']))
        inventory('take_up',replacement['root_body'],'struck-replacement-take')
        reused=use(head);self.assertNotIn('refused',reused,reused)
        self.assertTrue(reused['result']['impacts'],reused);self.assertTrue(reused['result']['working_point_connected'])
        final=install._snapshot(self.live);ledger=deepcopy(self.room.fabrication_record);model.advance(ledger,final['t_s'])
        api._persist(self.app,self.room,final,ledger)
        saved=self.app.store.load('fabrication');opened=self.live.open(self.app,{'spec':saved.spec,'snapshot':saved.world_record})
        self.room=self.app.room=saved;shown=inventory_room.after_open(self.app,opened)
        self.assertIn(root,[i['id'] for i in shown['stowed']])
        restored=next(j for j in self.live.session.send(op='joints')['joints'] if j['id']==joint['id'])
        self.assertFalse(restored['attached']);self.assertEqual(failure['parted_because'],restored['parted_because'])
        self.assertTrue(api.request(self.app,'start_remake',{**request,'session':self.live.session.id})['replayed'])
        binding=self.room.fabrication_record['jobs']['struck-replacement']['remake_source']
        self.assertTrue(any(j['id']==joint['id'] and not j['attached'] for row in binding['condition'] for j in row['joints']))
        audit=model.audit(self.room.fabrication_record)
        self.assertLess(abs(audit['energy_residual_j']),1e-7)
        self.assertLess(max(abs(v) for v in audit['material_residual_kg'].values()),1e-12)
        (ROOT/'build/resource-flow/paid-made-target-replacement.json').write_text(json.dumps({
            'source':source,'target':target,'hit':hit,'replacement':replacement,'reused':reused,'audit':audit,
            'limits':'5 mm finite rack; native actor supports the head. Not a fresh-map/private-peer journey, internal fracture, wear or genuine repair qualification.'},indent=2),encoding='utf-8')

    def test_failed_connection_paid_mixed_replacement_retains_original_and_works(self):
        import object_strike_tests as strikes
        import workshop_fixed_assembly_tests as mixed
        import tool_use
        marker=deepcopy(next(b for b in self.room.spec['bodies'] if b['name']=='marker stone'))
        marker.update(center_mm=[-3000,1500,0],anchored=True)
        spec=strikes.fixture('glass',tool_capacity=60)
        spec['cell_m']=.04
        spec['bodies'].append(marker);spec['machines']=deepcopy(self.room.spec['machines'])
        self.app.reply_listeners=[]
        def heard(session,reply):
            for listener in list(self.app.reply_listeners):listener(session,reply)
        self.app.on_live_reply=heard
        self.room.spec=spec;self.live.open(self.app,{'spec':spec})
        sid=self.live.session.id
        person={'standing_m':[-1.25,-.12,0],'eyes_m':[-1.25,1.5,0],
                'facing':[1,0,0],'look_direction':[1,0,0]}
        shown=inventory_room.shown(self.app)
        taken=inventory_room.request(self.app,{'session':sid,'op':'take_up','item':'field pick',
            'grip':[0,1.3,0],'revision':shown['record']['revision'],'request':'breakable-take','person':person})
        self.assertTrue(taken['ok'],taken)
        source_id=next(e['id'] for e in inventory_room.shown(self.app)['hands'].values() if e)
        grip=self.live.session.send(op='poses')['hand']['grip_m'];end=grip[:];end[0]+=.14
        self.live.act({'session':sid,'op':'stroke','path':[grip,end],'speed_m_s':4,
            'accel_m_s2':80,'lead_m':.025,'give_up_s':.125})
        self.live.act({'session':sid,'op':'step','dt':1/240,'n':120})
        damaged=self.live.session.send(op='condition',names=['field pick'])['condition']['bodies'][0]
        self.assertFalse(damaged['joints'][0]['attached'])
        shown=inventory_room.shown(self.app)
        source_id=next(e['id'] for e in shown['hands'].values() if e)
        self.assertEqual('field pick',source_id)
        stored=inventory_room.request(self.app,{'session':sid,'op':'stow','item':source_id,
            'revision':shown['record']['revision'],'request':'broken-source-stow','person':person})
        self.assertTrue(stored['ok'],stored)
        self.assertEqual(['field pick'],stored['room']['parts'])
        design=mixed.pick('iron');plan=self.plan(source_id,design)
        for material,mass in model.materials(plan['quote'],'stock').items():
            self.call('fund_stock',**{k:v for k,v in self.request(mass,material,'broken-feed-'+material).items()
                                     if k not in ('scene','session')})
        reading=self.call('state');store=reading['energy_sources'][0]
        self.call('connect_energy',store=store['id'],store_hash=store['store_hash'],power_w=250,
            revision=reading['state']['revision'],request_id='broken-energy-connect')
        api.wait(self.app,{**self.context(),'seconds':max(1,math.ceil(plan['quote']['supply_required_j']/250))})
        reading=self.call('state');store=reading['energy_sources'][0]
        self.call('fund_energy',store_hash=store['store_hash'],joules=plan['quote']['supply_required_j'],
            revision=reading['state']['revision'],request_id='broken-energy-feed')
        plan=self.plan(source_id,design);ident='broken-replacement-job'
        request={**self.context(),'plan_id':plan['plan_id'],'revision':plan['revision'],'request_id':ident}
        ledger=deepcopy(self.room.fabrication_record);before=install._snapshot(self.live)
        with mock.patch.object(self.app.store,'save',side_effect=OSError('broken replacement save failed')):
            with self.assertRaises(OSError):api.request(self.app,'start_remake',request)
        self.assertEqual(ledger,self.room.fabrication_record);self.assertEqual(before,install._snapshot(self.live))
        accepted=api.request(self.app,'start_remake',request)
        self.assertTrue(api.request(self.app,'start_remake',request)['replayed'])
        job=accepted['state']['jobs'][ident]
        self.assertEqual(plan['source']['condition'],job['remake_source']['condition'])
        self.assertTrue(any(not j['attached'] for r in job['remake_source']['condition'] for j in r['joints']))
        api.wait(self.app,{**self.context(),'seconds':max(1,math.ceil(job['minimum_duration_s']))})
        preview=api.preview(self.app,{**self.context(),'job_id':ident,'position_m':[0,1.5]})
        original=install._snapshot(self.live)
        result=api.commit(self.app,{**self.context(),'job_id':ident,'preview_id':preview['preview_id'],
            'request_id':'broken-replacement-install'})
        after=install._snapshot(self.live)
        for name in ('field pick','head'):
            self.assertEqual(next(b for b in original['bodies'] if b['name']==name),
                             next(b for b in after['bodies'] if b['name']==name))
        self.assertEqual(original['joints'],after['joints'][:len(original['joints'])])
        root=result['root_body']
        shown=inventory_room.shown(self.app)
        taken=inventory_room.request(self.app,{'session':self.live.session.id,'op':'take_up','item':root,
            'revision':shown['record']['revision'],'request':'replacement-take','person':person})
        self.assertTrue(taken['ok'],taken)
        stop=threading.Event();errors=[]
        def clock():
            try:
                while not stop.is_set():
                    self.live.act({'session':self.live.session.id,'op':'step','dt':1/240,'n':1})
                    time.sleep(1/240)
            except Exception as error:errors.append(str(error))
        pump=threading.Thread(target=clock,daemon=True);pump.start()
        try:used=tool_use.run(self.app,{'session':self.live.session.id,'person':person,'target_name':'target'})
        finally:stop.set();pump.join(5)
        self.assertEqual([],errors);self.assertNotIn('refused',used,{
            'answer':used,'poses':self.live.session.send(op='poses'),
            'points':self.live.session.send(op='tool_points')})
        self.assertTrue(used['result']['impacts'],used)
        self.assertTrue(used['result']['working_point_connected'],used)
        self.assertTrue(used['result']['parted_joints'],used)
        # Persist the post-use native state before the whole reopen, as a host
        # completion checkpoint does. The paid ledger and source stay intact.
        final_snapshot=install._snapshot(self.live);final_ledger=deepcopy(self.room.fabrication_record)
        model.advance(final_ledger,final_snapshot['t_s'])
        api._persist(self.app,self.room,final_snapshot,final_ledger)
        saved=self.app.store.load('fabrication')
        reopened=self.live.open(self.app,{'spec':saved.spec,'snapshot':saved.world_record});self.room=self.app.room=saved
        kept=inventory_room.after_open(self.app,reopened)
        self.assertEqual('field pick',kept['stowed'][0]['name'])
        self.assertTrue(api.request(self.app,'start_remake',{**request,'session':self.live.session.id})['replayed'])
        binding=self.room.fabrication_record['jobs'][ident]['remake_source']
        self.assertEqual(job['remake_source'],binding)
        self.assertFalse(self.live.session.send(op='condition',names=['field pick'])['condition']['bodies'][0]['joints'][0]['attached'])
        audit=model.audit(self.room.fabrication_record)
        self.assertLess(abs(audit['energy_residual_j']),1e-7)
        self.assertLess(max(abs(v) for v in audit['material_residual_kg'].values()),1e-12)
        self.assertAlmostEqual(sum(model.materials(job,'product').values()),result['mass_kg'],places=12)
        self.native_evidence={'source_failure':damaged['joints'][0],
            'stock_materials_kg':model.materials(job,'stock'),'paid_j':job['supply_required_j'],
            'replacement_mass_kg':result['mass_kg'],'replacement_strike':used['result'],
            'save_failure_rollback_and_retry':True,'whole_reopen_preserves_source_history':True,
            'dt_s':1/240,'cell_m':.04,
            'audit':audit,
            'separated_handle_stored_and_reopened':True,
            'limits':'Explicit finite test rack/battery and authored weak source; not a paid manufactured-source journey, held internal fracture or genuine repair.'}
        (ROOT/'build/resource-flow/broken-replacement-native.json').write_text(
            json.dumps(self.native_evidence,indent=2)+'\n',encoding='utf-8')


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

    def test_fractional_native_meter_bank_failed_save_retry_peer_and_server_restart(self):
        world,owner,app=self.setup_world()
        peer=self.join(world,'Other trader')
        source=next(s for s in app.live.session.state['machines']['stores'] if s['body']=='solar farm')
        # A real external energy draw, with the clock stopped by this fixture.
        # Its old rounded receipt was 4 microjoules ahead of the native snapshot.
        app.live.act({'session':app.live.session.id,'op':'draw','store':source['id'],'joules':.000006})
        before=install._snapshot(app.live)
        bank={'action':'bank','joules':500,'request_id':'fractional-meter-bank'}
        with mock.patch.object(app.store,'save',side_effect=OSError('disk full')):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.post('/api/workshop/market',bank,world)
            self.assertIn('durable world save',error.exception.read().decode('utf-8'))
        self.assertEqual(0,self.post('/api/workshop/market',{'action':'view'},world)['balance_j'])
        after=install._snapshot(app.live)
        meter=next(s for s in after['energy_stores'] if s['id']==source['id'])
        old=next(s for s in before['energy_stores'] if s['id']==source['id'])
        self.assertEqual(old['charge_j']-500.,meter['charge_j'])
        self.assertEqual(500.000006,meter['given_j'])
        for _ in range(2):
            self.assertEqual(500,self.post('/api/workshop/market',bank,world)['balance_j'])
        self.assertEqual(0,self.post('/api/workshop/market',{'action':'view'},world,peer['token'])['balance_j'])
        self.assertEqual(after,install._snapshot(app.live))
        self.stop();self.start()
        self.post('/api/world/player/join',{'token':owner['token']},world)
        self.post('/api/world/open',{},world)
        reopened=self.app.hub.get(world)
        self.assertEqual(meter,next(s for s in install._snapshot(reopened.live)['energy_stores'] if s['id']==source['id']))
        self.assertEqual(500,self.post('/api/workshop/market',bank,world)['balance_j'])

    def test_fresh_mined_processed_personal_copper_funds_saved_lamp_use_and_server_restart(self):
        self.material_build_journey()

    def test_gathered_sand_processed_glass_funds_saved_lamp_use_and_server_restart(self):
        self.material_build_journey(gathered_sand=True)

    def material_build_journey(self,gathered_sand=False):
        """Real rover supply, private output, saved design and finite manufacture.

        Copper is the existing assembly-supply ledger; its constituent native
        mass/thermal law remains unmodeled. This is the supported R1 journey.
        """
        with mock.patch.object(flow.server.secrets,'randbelow',side_effect=[0,851269740]):
            world,owner,app=self.setup_world()
        peer=self.join(world,'Other crafter')
        def post(path,body,token=None):
            try:return self.post(path,body,world,token)
            except urllib.error.HTTPError as exc:
                self.fail(path+': '+exc.read().decode('utf-8'))
        def context():return {'session':app.live.session.id,'scene':app.room.scene}
        def exact_copper(player):
            with library._connect(app) as db:
                row=db.execute("SELECT mass_kg FROM workshop_goods_rack WHERE owner_id=? AND substance='copper'",
                               (player['id'],)).fetchone()
            return float(row['mass_kg']) if row else 0.
        def exact_material(player,material):
            with library._connect(app) as db:
                row=db.execute('SELECT mass_kg FROM workshop_material_rack WHERE owner_id=? AND material=?',
                    (player['id'],material)).fetchone()
            return float(row['mass_kg']) if row else 0.
        self.assertEqual({},app.room.fabrication_record['stock_kg'])
        self.assertEqual(0.,app.room.fabrication_record['energy_j'])
        program=next(p for p in app.live.session.state['machines']['programs'] if p['kind']=='roam')
        rover=app.brains.of(program['name']).routine
        processor=next(b.routine for b in app.brains.brains.values() if b.routine and b.routine.recipe=='smelt copper')
        intake=app.brains.goods.by_name(processor.intake)
        output=app.brains.goods.by_name(processor.output)
        starter=intake['holds'].get('copper ore',0.)
        for _ in range(1500):
            app.clock._tick(.2)
            if rover.trips:break
        self.assertGreater(rover.trips,0,rover.summary())
        delivered=next(e for e in app.brains.goods.activities if e['kind']=='dump' and e['machine']==program['name'])
        mined=delivered['goods_kg']['copper ore'];self.assertGreater(mined,0.)
        self.assertEqual({'pile':processor.intake},delivered['to'])
        self.assertTrue(any(e['kind']=='dig' and e['machine']==program['name'] for e in app.brains.goods.activities))
        post('/api/world/machine',{'session':app.live.session.id,'program':program['id'],
            'power':False,'sender':'material-build-acceptance','seq':1})
        # Move finite raw ore from the receiving heap through this player's
        # Inventory, then deliver it back through the ordinary input contract.
        # The initial/mined total is unchanged; no stock is injected.
        ix,iz=intake['at_m']
        floor=app.live.act({'session':app.live.session.id,'op':'survey','at':[ix,iz]})['survey']['ground_m']
        input_person={'eyes_m':[ix,floor+1.62,iz],'facing':[0,0,-1]}
        raw=post('/api/world/goods/collect',{'session':app.live.session.id,'pile':intake['name'],
                 'person':input_person,'request_id':'material-build-raw-pickup'})['collected']
        self.assertGreater(raw['copper ore'],0.)
        delivery={'session':app.live.session.id,'pile':intake['name'],'person':input_person,
                  'request_id':'material-build-input','substance':'copper ore','mass_kg':raw['copper ore']}
        post('/api/world/goods/deliver',delivery)
        self.assertTrue(post('/api/world/goods/deliver',delivery)['repeated'])
        expected=(starter+mined)*.3
        for _ in range(800):
            app.clock._tick(.2)
            if abs(output['holds'].get('copper',0.)-expected)<1e-6:break
        copper=output['holds'].get('copper',0.)
        self.assertAlmostEqual(expected,copper,delta=1e-6)
        self.assertLess(intake['holds'].get('copper ore',0.),1e-8)
        self.assertEqual(0.,exact_copper(owner));self.assertEqual(0.,exact_copper(peer))
        x,z=output['at_m']
        ground=app.live.act({'session':app.live.session.id,'op':'survey','at':[x,z]})['survey']['ground_m']
        collection={'session':app.live.session.id,'pile':output['name'],'request_id':'material-build-copper',
                    'person':{'eyes_m':[x,ground+1.62,z],'facing':[0,0,-1]}}
        self.assertEqual(copper,post('/api/world/goods/collect',collection)['collected']['copper'])
        self.assertEqual(copper,exact_copper(owner));self.assertEqual(0.,exact_copper(peer))
        sand_proof=None
        if gathered_sand:
            # Use the real Field pick and shared clock; terrain edits or a
            # granted bag balance cannot qualify this player journey.
            person=condition_flow.BodyCondition.take_pick(self,world,app)
            target=[-1.,0.]
            ground=app.live.act({**context(),'op':'survey','at':target})['survey']['ground_m']
            floor=app.live.act({**context(),'op':'survey','at':[-2.2,0.]})['survey']['ground_m']
            person={'standing_m':[-2.2,floor,0.],'eyes_m':[-2.2,floor+1.62,0.],
                'facing':[1,0,0],'look_direction':[1.2,ground-floor-1.62,0.]}
            replies=[]
            def inventory():return post('/api/workshop/inventory',{})
            for attempt in range(50):
                if inventory()['ground_load']['sand_kg']>=4.32/.85+.00001:break
                answer=[];errors=[]
                def use():
                    try:answer.append(post('/api/world/tool/use',{**context(),'person':person,'at_m':[-1.,ground,0.]}))
                    except BaseException as exc:errors.append(exc)
                worker=threading.Thread(target=use,daemon=True);worker.start()
                deadline=time.monotonic()+25
                while worker.is_alive() and time.monotonic()<deadline:
                    app.clock._tick(.05);time.sleep(.015)
                worker.join(1);self.assertFalse(worker.is_alive());self.assertEqual([],errors)
                replies.extend(answer)
            load=inventory()['ground_load'];sand=load['sand_kg']
            self.assertGreaterEqual(sand,4.32/.85)
            self.assertTrue(any((a.get('result') or {}).get('loosened_kg',0)>0 for a in replies))
            shown=post('/api/world/inventory/shown',context())
            post('/api/world/inventory',{**context(),'op':'stow','item':'field pick',
                'request':'glass-journey-stow','revision':shown['record']['revision'],'person':person})
            state=post('/api/world/fabrication/state',context())
            raw={**context(),'request_id':'glass-journey-store','revision':state['state']['revision'],
                **{s+'_m3':load.get(s+'_m3',0) for s in ('sand','soil','rock')}}
            post('/api/world/fabrication/store_ground',raw)
            machine=next(p for p in app.live.session.state['machines']['programs'] if p['name']==processor.name)
            post('/api/world/machine',{'session':app.live.session.id,'program':machine['id'],
                'power':False,'sender':'glass-journey','seq':1})
            # A produced batch still owns its declared duration while stopped.
            issued=processor.frame.issued or {}
            while app.live.session.state['t']<processor.frame.issued_t+issued.get('took_s',0)+.1:
                app.clock._tick(.2)
            post('/api/world/process',{'session':app.live.session.id,'program':machine['id'],
                'action':'select','recipe':'melt glass','expected_recipe':processor.recipe,'person':input_person})
            intake=app.brains.goods.by_name(processor.intake);output=app.brains.goods.by_name(processor.output)
            state=post('/api/world/fabrication/state',context())
            sand_mass=math.floor(sand*1e6)/1e6
            sand_input={'session':app.live.session.id,'pile':intake['name'],'substance':'sand','mass_kg':sand_mass,
                'lot_id':raw['request_id'],'revision':state['state']['revision'],
                'request_id':'glass-journey-input','person':input_person}
            post('/api/world/goods/deliver',sand_input)
            before=sum(s['given_j'] for s in app.live.session.state['machines']['stores'])
            post('/api/world/machine',{'session':app.live.session.id,'program':machine['id'],
                'power':True,'sender':'glass-journey','seq':2})
            for _ in range(700):
                app.clock._tick(.2)
                output=app.brains.goods.by_name(output['name'])
                if output.get('holds',{}).get('glass',0)>=sand_mass*.85-1e-6:break
            glass=output.get('holds',{}).get('glass',0);self.assertAlmostEqual(sand_mass*.85,glass,delta=1e-6)
            draw=sum(s['given_j'] for s in app.live.session.state['machines']['stores'])-before
            self.assertGreater(draw,sand_mass*800)
            post('/api/world/machine',{'session':app.live.session.id,'program':machine['id'],
                'power':False,'sender':'glass-journey','seq':3})
            glass_pickup={**collection,'session':app.live.session.id,'request_id':'glass-journey-output'}
            self.assertEqual(glass,post('/api/world/goods/collect',glass_pickup)['collected']['glass'])
            sand_proof={'gathered_sand_kg':sand,'delivered_sand_kg':sand_mass,'glass_kg':glass,
                'native_process_draw_j':draw,'native_work_receipts':len(replies)}
        from mcp import workshop_components
        _,overrides=workshop_components.design_from_spec({'kind':'mine-lamp'})
        overrides['@machines']={
                'stores':[{'name':'camp battery','in':'foot','capacity_j':1000.,'charge_j':500.,
                           'voltage_v':24.,'max_power_w':25.}],
                'lamps':[{'name':'camp light','on':'globe','store':'camp battery','watts':10.,'on_at_first':False}]}
        candidate={'kind':'mine-lamp','design_id':'processed-copper-lamp','parameters':{},'component_overrides':overrides}
        saved=post('/api/workshop/library',{'action':'save_design','name':'Copper camp lamp',**candidate})['library_item']
        loaded=post('/api/workshop/library',{'action':'load','item_id':saved['item_id']})
        candidate=loaded['library_item']['payload']
        plan=post('/api/world/fabrication/plan_make',{**context(),'candidate':candidate})
        self.assertEqual({'copper':.5},plan['quote']['assembly_goods_kg'])
        self.assertEqual(.5,plan['missing_goods_kg']['copper'])
        state=post('/api/world/fabrication/state',context())
        source=next(s for s in state['goods_sources'] if s['material']=='copper' and s['pool']=='personal')
        transfer={**context(),'material':'copper','mass_kg':.5,'pool':'personal','rack_hash':source['rack_hash'],
                  'revision':state['state']['revision'],'request_id':'material-build-fund-copper'}
        post('/api/world/fabrication/fund_goods',transfer)
        post('/api/world/fabrication/fund_goods',transfer)
        self.assertEqual(copper-.5,exact_copper(owner));self.assertEqual(0.,exact_copper(peer))
        bank=0;restock_wait_s=0
        for material,mass in model.materials(plan['quote'],'stock').items():
            market=post('/api/workshop/market',{'action':'view'})
            offer=next(o for o in market['offers'] if o['substance']==material)
            for index in range(0 if gathered_sand and material=='glass' else math.ceil(mass/offer['mass_kg'])):
                offer=next(o for o in market['offers'] if o['substance']==material)
                for _ in range(13):
                    if offer['remaining']>0:break
                    post('/api/world/fabrication/wait',{**context(),'seconds':10})
                    restock_wait_s+=10
                    market=post('/api/workshop/market',{'action':'view'})
                    offer=next(o for o in market['offers'] if o['substance']==material)
                self.assertGreater(offer['remaining'],0,'The finite trader must restock through accepted world time')
                while market['balance_j']<offer['price_j']:
                    market=post('/api/workshop/market',{'action':'bank','joules':500,
                        'request_id':'material-build-bank-'+str(bank)});bank+=1
                market=post('/api/workshop/market',{'action':'buy','item_id':offer['id'],
                    'quoted_price_j':offer['price_j'],'request_id':f'material-build-buy-{material}-{index}'})
            state=post('/api/world/fabrication/state',context())
            source=next(s for s in state['stock_sources'] if s['material']==material and s['pool']=='personal')
            post('/api/world/fabrication/fund_stock',{**context(),'material':material,'mass_kg':mass,
                'pool':'personal','rack_hash':source['rack_hash'],'revision':state['state']['revision'],
                'request_id':'material-build-stock-'+material})
        state=post('/api/world/fabrication/state',context())
        source=next(s for s in state['energy_sources'] if s['max_power_w']>=500.)
        post('/api/world/fabrication/connect_energy',{**context(),'store':source['id'],'store_hash':source['store_hash'],
            'power_w':500.,'revision':state['state']['revision'],'request_id':'material-build-connect'})
        remaining=math.ceil(plan['quote']['supply_required_j']/500.)
        while remaining:
            seconds=min(10,remaining);post('/api/world/fabrication/wait',{**context(),'seconds':seconds});remaining-=seconds
        state=post('/api/world/fabrication/state',context())
        source=next(s for s in state['energy_sources'] if s['connected'])
        post('/api/world/fabrication/fund_energy',{**context(),'store_hash':source['store_hash'],
            'joules':plan['quote']['supply_required_j'],'revision':state['state']['revision'],'request_id':'material-build-energy'})
        plan=post('/api/world/fabrication/plan_make',{**context(),'candidate':candidate})
        self.assertEqual(0.,plan['missing_goods_kg']['copper'])
        started=post('/api/world/fabrication/start_make',{**context(),'plan_id':plan['plan_id'],
            'revision':plan['revision'],'request_id':'material-build-lamp'})
        remaining=math.ceil(started['state']['jobs']['material-build-lamp']['minimum_duration_s'])
        while remaining:
            seconds=min(10,remaining);post('/api/world/fabrication/wait',{**context(),'seconds':seconds});remaining-=seconds
        preview=post('/api/world/fabrication/preview',{**context(),'job_id':'material-build-lamp','position_m':[-2.,0.]})
        commit={**context(),'job_id':'material-build-lamp','preview_id':preview['preview_id'],'request_id':'material-build-place'}
        made=post('/api/world/fabrication/commit',commit)
        self.assertTrue(post('/api/world/fabrication/commit',commit)['replayed'])
        self.assertEqual('installed',made['status'])
        root=made['root_body'];roots=set(made['root_bodies'])
        app.live.act({'session':app.live.session.id,'op':'poses'})
        pose=next(b for b in app.live.session.state['bodies'] if b['name']==root)['position_m']
        person={'eyes_m':[pose[0],pose[1]+1.,pose[2]+1.],
                'standing_m':[pose[0],pose[1],pose[2]+1.],'facing':[0,0,-1]}
        used=post('/api/world/action',{**context(),'object':root,'primary':True,'person':person})
        self.assertNotIn('refused',used,used)
        for _ in range(10):app.clock._tick(.2)
        native=install._snapshot(app.live)
        battery=next(s for s in native['energy_stores'] if s['body'] in roots)
        lamp=next(l for l in app.live.session.state['machines']['lamps'] if l['body'] in roots)
        self.assertTrue(lamp['lit']);self.assertGreater(battery['given_j'],0.)
        self.assertAlmostEqual(500.,battery['charge_j']+battery['given_j'],places=7)
        ledger=deepcopy(app.room.fabrication_record);audit=model.audit(ledger)
        self.assertLess(abs(audit['assembly_goods_residual_kg']['copper']),1e-9)
        self.assertTrue(flow.server.keep_world(app,'complete material-to-build journey'))
        wallet=post('/api/workshop/market',{'action':'view'})
        self.stop();self.start()
        post('/api/world/player/join',{'token':owner['token']})
        post('/api/world/open',{})
        app=self.app.hub.get(world)
        self.assertEqual(ledger,app.room.fabrication_record)
        self.assertEqual(copper-.5,exact_copper(owner));self.assertEqual(0.,exact_copper(peer))
        self.assertEqual(wallet,post('/api/workshop/market',{'action':'view'}))
        post('/api/world/goods/collect',{**collection,'session':app.live.session.id})
        post('/api/world/fabrication/fund_goods',transfer)
        self.assertEqual(copper-.5,exact_copper(owner))
        post('/api/world/goods/deliver',{**delivery,'session':app.live.session.id})
        self.assertLess(sum(app.brains.goods.by_name(intake['name'])['holds'].values()),1e-6)
        if gathered_sand:
            post('/api/world/goods/deliver',{**sand_input,'session':app.live.session.id})
            post('/api/world/goods/collect',{**glass_pickup,'session':app.live.session.id})
            # Inventory deliberately rounds display values. Audit the exact
            # durable account, rather than widening a physical tolerance.
            self.assertAlmostEqual(glass-model.materials(plan['quote'],'stock')['glass'],
                exact_material(owner,'glass'),delta=1e-9)
            self.assertEqual(0,exact_material(peer,'glass'))
            self.assertEqual(native['ground'],install._snapshot(app.live)['ground'])
        reopened=install._snapshot(app.live)
        self.assertEqual(battery,next(s for s in reopened['energy_stores'] if s['id']==battery['id']))
        self.assertEqual(candidate,post('/api/workshop/library',{'action':'load','item_id':saved['item_id']})['library_item']['payload'])
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/('gathered-sand-build-lamp.json' if gathered_sand else 'material-build-lamp.json')).write_text(json.dumps({'sand_route':sand_proof,'starter_ore_kg':starter,'mined_ore_kg':mined,
            'processed_copper_kg':copper,'assembly_copper_kg':.5,'product':made,'audit':audit,
            'battery':battery,'trader_restock_wait_s':restock_wait_s,'restart_no_duplicate':True},indent=2),encoding='utf-8')

    def test_fresh_market_paid_pick_contacts_peer_product_and_server_restart_keeps_both(self):
        """Default 50 mm world and public supplies, without authored weak fixings.

        This qualifies contact/ownership/persistence, not normal-grid destruction:
        the current sampled catalog mounts can remain intact after a strike.
        """
        import workshop_fixed_assembly_tests as mixed
        with mock.patch.object(flow.server.secrets,'randbelow',side_effect=[0,1]):
            world,owner,app=self.setup_world()
        peer=self.join(world,'Product holder')
        self.assertEqual(.05,app.room.spec['cell_m'])
        self.assertEqual({},app.room.fabrication_record['stock_kg'])
        self.assertEqual(0,app.room.fabrication_record['energy_j'])
        def post(path,body,player=None):return self.post(path,body,world,player)
        def context():return {'session':app.live.session.id,'scene':app.room.scene}
        def stock(material,mass,key):
            reading=post('/api/workshop/market',{'action':'view'});bank_index=0
            lot=next(o['mass_kg'] for o in reading['offers'] if o['substance']==material)
            for index in range(math.ceil(mass/lot)):
                offer=next(o for o in reading['offers'] if o['substance']==material)
                while reading['balance_j']<offer['price_j']:
                    reading=post('/api/workshop/market',{'action':'bank','joules':500,
                        'request_id':key+'-bank-'+str(bank_index)})
                    bank_index+=1
                reading=post('/api/workshop/market',{'action':'buy','item_id':offer['id'],
                    'quoted_price_j':offer['price_j'],'request_id':key+'-buy-'+str(index)})
            reading=post('/api/world/fabrication/state',context())
            source=next(s for s in reading['stock_sources'] if s['material']==material and s['pool']=='personal')
            post('/api/world/fabrication/fund_stock',{**context(),'material':material,'mass_kg':mass,
                'pool':'personal','rack_hash':source['rack_hash'],'revision':reading['state']['revision'],
                'request_id':key+'-fund'})
        def paid(candidate,key,position):
            plan=post('/api/world/fabrication/plan_make',{**context(),'candidate':candidate})
            for material,mass in model.materials(plan['quote'],'stock').items():stock(material,mass,key+'-'+material)
            reading=post('/api/world/fabrication/state',context())
            source=next(s for s in reading['energy_sources'] if s['max_power_w']>0)
            post('/api/world/fabrication/connect_energy',{**context(),'store':source['id'],
                'store_hash':source['store_hash'],'power_w':500,'revision':reading['state']['revision'],
                'request_id':key+'-connect'})
            post('/api/world/fabrication/wait',{**context(),'seconds':math.ceil(plan['quote']['supply_required_j']/500)})
            reading=post('/api/world/fabrication/state',context())
            source=next(s for s in reading['energy_sources'] if s['connected'])
            post('/api/world/fabrication/fund_energy',{**context(),'store_hash':source['store_hash'],
                'joules':plan['quote']['supply_required_j'],'revision':reading['state']['revision'],
                'request_id':key+'-energy'})
            plan=post('/api/world/fabrication/plan_make',{**context(),'candidate':candidate})
            made=post('/api/world/fabrication/start_make',{**context(),'plan_id':plan['plan_id'],
                'revision':plan['revision'],'request_id':key})
            post('/api/world/fabrication/wait',{**context(),'seconds':math.ceil(made['state']['jobs'][key]['minimum_duration_s'])})
            preview=post('/api/world/fabrication/preview',{**context(),'job_id':key,'position_m':position})
            return post('/api/world/fabrication/commit',{**context(),'job_id':key,
                'preview_id':preview['preview_id'],'request_id':key+'-place'})
        target_design={'kind':'custom','parameters':{'primary_use':{'label':'Push','steps':[
            {'do':'push_forward','distance_m':.2,'speed_m_s':.4}]}},
            'component_overrides':{'@construction':{'added':[
                {'name':'beam','role':'panel','family':'panel','shape':'box','material':'oak',
                 'size_m':[2.5,.05,.05],'center_m':[0,.025,.075],'rotation_deg':[0,0,0]},
                {'name':'head','role':'panel','family':'panel','shape':'box','material':'iron',
                 'size_m':[.1,.1,.1],'center_m':[1.275,.05,0],'rotation_deg':[0,0,0]}]}}}
        target=paid(target_design,'fresh-target',[-2,0])
        design=mixed.pick();design['parameters'].update(length_m=.5,arm_m=.2,section_m=.05)
        design['parameters']['ground_tool']['point']['tip_local_m']=[0,0,-.1]
        design['parameters']['ground_tool']['grip']['position_local_m']=[-.2,0,0]
        source=paid(design,'fresh-source',[-.9,1]);sid=app.live.session.id
        self.assertTrue(source['resources_charged']);self.assertTrue(target['resources_charged'])
        head=target['component_to_body']['head'];root=target['component_to_body']['beam']
        def position(name):return next(b['position_m'] for b in post('/api/live/act',{'session':sid,'op':'poses'})['bodies'] if b['name']==name)
        def person_at(x,z):
            floor=post('/api/live/act',{'session':sid,'op':'survey','at':[x,z]})['survey']['ground_m']
            return {'standing_m':[x,floor,z],'eyes_m':[x,floor+1.62,z],'facing':[0,0,-1]}
        def inventory(op,item,key,person,player=None,**extra):
            shown=post('/api/world/inventory/shown',{'session':sid},player)
            answer=post('/api/world/inventory',{'session':sid,'op':op,'item':item,'request':key,
                'revision':shown['record']['revision'],'person':person,**extra},player)
            self.assertTrue(answer['ok'],answer);return answer
        at=position(head);peer_person=person_at(at[0],at[2]+.8)
        inventory('take_up',head,'fresh-peer-take',peer_person,peer['token'],grip=at)
        post('/api/live/act',{'session':sid,'op':'stroke','path':[at,[at[0],at[1]+1.5,at[2]]],
            'speed_m_s':.3,'accel_m_s2':1,'lead_m':.025,'give_up_s':8,'let_go':False},peer['token'])
        # Named-world public steps share elapsed wall time. Tight n=120 loops
        # do not grant eight seconds and would leave this peer mid-stroke.
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            post('/api/live/act',{'session':sid,'op':'step','dt':1/240,'n':60})
            hand=post('/api/live/act',{'session':sid,'op':'poses'},peer['token'])['hand']
            if not hand.get('stroking'):break
            time.sleep(.02)
        self.assertFalse(hand.get('stroking'),hand);self.assertEqual('reached',hand.get('stroke_ended'))
        joint=next(j for j in post('/api/live/act',{'session':sid,'op':'joints'})['joints'] if root in (j['a'],j['b']))
        self.assertTrue(joint['attached']);self.assertAlmostEqual(225000,joint['holds_tension_n'])
        at=position(root);person=person_at(at[0],at[2]+1.3)
        inventory('take_up',source['root_body'],'fresh-owner-take',person)
        direction=[at[i]-person['eyes_m'][i] for i in range(3)];length=math.sqrt(sum(v*v for v in direction))
        person['look_direction']=[v/length for v in direction]
        stop=threading.Event();errors=[]
        def clock():
            try:
                while not stop.is_set():
                    post('/api/live/act',{'session':sid,'op':'step','dt':1/240,'n':60});time.sleep(.02)
            except Exception as error:errors.append(str(error))
        pump=threading.Thread(target=clock,daemon=True);pump.start()
        try:hit=post('/api/world/tool/use',{'session':sid,'person':person,'target_name':root})
        finally:stop.set();pump.join(5)
        self.assertFalse(pump.is_alive());self.assertEqual([],errors)
        self.assertNotIn('refused',hit,hit);self.assertTrue(hit['result']['impacts'],hit)
        self.assertTrue(hit['result']['complete']);self.assertTrue(hit['result']['working_point_connected'])
        self.assertFalse(hit['result']['internal_fracture_supported']);self.assertFalse(hit['result']['wear_supported'])
        owner_shown=post('/api/world/inventory/shown',{'session':sid})
        carried_id=next(e['id'] for e in owner_shown['hands'].values() if e)
        inventory('stow',carried_id,'fresh-owner-stow',person)
        owner_shown=post('/api/world/inventory/shown',{'session':sid})
        peer_shown=post('/api/world/inventory/shown',{'session':sid},peer['token'])
        self.assertEqual(set(source['component_to_body'].values()),set(owner_shown['stowed'][0]['parts']))
        peer_item=next(e for e in peer_shown['hands'].values() if e)
        self.assertEqual(set(target['component_to_body'].values()),set(peer_item['parts']))
        self.assertEqual(head,post('/api/live/act',{'session':sid,'op':'poses'},peer['token'])['hand']['holding'])
        self.assertTrue(flow.server.keep_world(app,'fresh paid strike and private inventories'))
        before=install._snapshot(app.live);ledger=deepcopy(app.room.fabrication_record)
        owner_market=post('/api/workshop/market',{'action':'view'})
        peer_market=post('/api/workshop/market',{'action':'view'},peer['token'])
        self.assertEqual(0,peer_market['balance_j']);self.assertEqual([],peer_market['orders'])
        self.stop();self.start()
        post('/api/world/player/join',{'token':owner['token']})
        reopened=post('/api/world/open',{});sid=reopened['session'];app=self.app.hub.get(world)
        after=install._snapshot(app.live)
        # Whole-world restoration uses the existing bounded native hinge-angle
        # comparison (1e-6 rad); recomputing the rover angle is not bit-exact.
        # The two manufactured fixings and their retained history stay exact.
        install._preserved(before,after,set())
        made_names=set(source['component_to_body'].values())|set(target['component_to_body'].values())
        self.assertEqual([j for j in before['joints'] if j['a'] in made_names],
                         [j for j in after['joints'] if j['a'] in made_names])
        self.assertEqual(before.get('player_hands'),after.get('player_hands'))
        self.assertEqual(ledger,app.room.fabrication_record)
        self.assertEqual(owner_shown['record'],post('/api/world/inventory/shown',{'session':sid})['record'])
        self.assertEqual(peer_shown['record'],post('/api/world/inventory/shown',{'session':sid},peer['token'])['record'])
        self.assertEqual(owner_market['balance_j'],post('/api/workshop/market',{'action':'view'})['balance_j'])
        audit=model.audit(app.room.fabrication_record)
        self.assertLess(abs(audit['energy_residual_j']),1e-7)
        self.assertLess(max(abs(v) for v in audit['material_residual_kg'].values()),1e-12)
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/'fresh-paid-peer-strike-restart.json').write_text(json.dumps({
            'cell_m':.05,'dt_s':1/240,'source':source,'target':target,'hit':hit,'audit':audit,
            'limits':'Default generated world and public Market/solar supplies. Contact and private server restart; no target separation, held internal fracture, repair, wear or full strike conservation qualification.'},indent=2)+'\n',encoding='utf-8')

    def test_mixed_pick_chat_edit_save_paid_make_pickup_dig_and_restart(self):
        self.assertTrue(flow.qa_browser.CHROME.is_file(), 'Chrome required')
        with mock.patch.object(flow.server.secrets, 'randbelow', side_effect=[0, 1]):
            world, owner, app = self.setup_world()
        person = self.take_pick(world, app)
        sid = app.live.session.id
        shown = self.post('/api/world/inventory/shown', {'session': sid}, world)
        self.post('/api/world/inventory', {'session': sid, 'op': 'stow', 'item': 'field pick',
            'request': 'mixed-stow', 'revision': shown['record']['revision'], 'person': person}, world)
        original = deepcopy(next(b for b in install._snapshot(app.live)['bodies'] if b['name'] == 'field pick'))
        rack = self.post('/api/workshop/library', {}, world)['rack']
        before = deepcopy(app.room.fabrication_record)
        recipe = self.post('/api/world/workshop/what_made', {'body': 'field pick'}, world)['recipe']
        from mcp import workshop_components
        design, _ = workshop_components.design_from_spec(recipe)
        head = next(p.name for p in design.parts if 'arm' in p.name)
        self.chrome = flow.qa_browser.Chrome(1280, 900)
        p = self.chrome.page
        p.send('Page.enable'); p.send('Runtime.enable')
        p.send('Page.addScriptToEvaluateOnNewDocument', {'source':
            f'if(location.protocol==="http:" && location.hostname==="127.0.0.1") '
            f'localStorage.setItem("banjo.player.{world}",{json.dumps(owner["token"])});'})
        def wait(expr):
            end = time.monotonic() + 30
            while time.monotonic() < end:
                if p.evaluate('Boolean(' + expr + ')'): return
                time.sleep(.05)
            (ROOT / 'build/resource-flow/mixed-pick-failure.png').write_bytes(base64.b64decode(p.send('Page.captureScreenshot', {'format': 'png'})['data']))
            self.fail(expr + '; ' + str(p.evaluate('document.body.innerText.slice(-1800)')))
        def click(selector):
            wait('document.querySelector(' + json.dumps(selector) + ') && !document.querySelector(' + json.dumps(selector) + ').disabled')
            point = p.evaluate('(()=>{const e=document.querySelector(%s);e.scrollIntoView({block:"center"});const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()' % json.dumps(selector))
            for event in ('mousePressed', 'mouseReleased'):
                p.send('Input.dispatchMouseEvent', {'type': event, **point, 'button': 'left', 'clickCount': 1})
        p.send('Page.navigate', {'url': self.base + f'/world?world={world}&workshop=1&tab=lab&carry=field%20pick'})
        wait('document.querySelector("#workshop-stage")?.visibleGeometry?.()?.meshes>0')
        point = p.evaluate('document.querySelector("#workshop-stage").pagePointOf(%s)' % json.dumps(next(part.center_m for part in design.parts if part.name == head)))
        for event in ('mousePressed', 'mouseReleased'):
            p.send('Input.dispatchMouseEvent', {'type': event, 'x': point[0], 'y': point[1], 'button': 'left', 'clickCount': 1})
        wait('document.querySelector("#ws-selected-part").textContent.includes(' + json.dumps(head) + ')')
        wait('!document.querySelector("#ws-component-chat-text").disabled')
        p.evaluate('document.querySelector("#ws-component-chat-text").value="make this iron"')
        click('#ws-component-chat button[type=submit]')
        wait('document.querySelector("#ws-part-material").value==="iron" && !document.querySelector("#ws-component-chat-text").disabled')
        click('#ws-quick-save')
        wait('document.querySelector("#ws-save-status").textContent.includes("Saved") && new URL(location.href).searchParams.has("design")')
        saved_url = p.evaluate('location.href')
        items = self.post('/api/workshop/library', {}, world)['personal_library']
        item = next(i for i in items if i['item_type'] == 'assembly')
        # Library listings omit the draft; inspect the stored payload through
        # the normal library route before checking materials.
        stored = self.post('/api/workshop/library', {'action': 'load', 'item_id': item['item_id']}, world)
        payload = stored['library_item']['payload']
        edited, overrides = workshop_components.design_from_spec(payload)
        materials = {part.name: part.material for part in edited.parts}
        self.assertEqual('iron', materials[head])
        self.assertEqual({'oak'}, {m for name, m in materials.items() if name != head})
        from mcp import workshop_buildability
        report, _, _ = workshop_buildability.assess(edited, overrides, cell_size_m=.05)
        self.assertTrue(report['compilation_ready'],report)
        p.send('Page.navigate', {'url': saved_url})
        wait('document.querySelector("#workshop-stage")?.visibleGeometry?.()?.meshes>0')
        wait('!document.querySelector("#ws-buildability-summary").textContent.includes("Make: Unavailable")')
        rows = p.evaluate('[...document.querySelectorAll("#ws-parts li")].map(e=>e.textContent)')
        self.assertTrue(any(head in row and 'iron' in row for row in rows), rows)
        self.assertTrue(any('oak' in row for row in rows), rows)
        p.evaluate('window.mixedMakeReplies=[];const oldFetch=window.fetch;window.fetch=async function(url){const r=await oldFetch.apply(this,arguments);if(String(url).includes("/fabrication/plan_"))mixedMakeReplies.push({status:r.status,body:await r.clone().json()});return r}')
        click('#ws-make')
        wait('mixedMakeReplies.length>0')
        answer = p.evaluate('mixedMakeReplies[0]')
        self.assertEqual(200,answer['status'],answer)
        self.assertEqual(original, next(b for b in install._snapshot(app.live)['bodies'] if b['name'] == 'field pick'))
        self.assertEqual(rack, self.post('/api/workshop/library', {}, world)['rack'])
        for key in ('stock_kg', 'energy_j', 'jobs', 'stock_imports'):
            self.assertEqual(before.get(key), app.room.fabrication_record.get(key), key)
        wait('document.querySelector("#ws-remake-review")')
        click('#ws-remake-review')
        wait('document.querySelector("#ws-remake-start")')
        self.assertTrue(p.evaluate('document.querySelector("#ws-remake-start").disabled'))
        # Explicit finite test supplies, collected through ordinary private
        # receipts. This qualifies Make; it does not close all supply routes.
        pile=app.brains.goods.put(0,0,{'oak':20.,'iron':20.},named='mixed pick test supplies')['onto']
        floor=app.live.act({'session':app.live.session.id,'op':'survey','at':[0,0]})['survey']['ground_m']
        for number in range(2):
            self.post('/api/world/goods/collect',{'session':app.live.session.id,'pile':pile,
                'request_id':'mixed-pick-supplies-'+str(number),'person':{'eyes_m':[0,floor+1.62,0],'facing':[0,0,-1]}},world)
        click('#ws-remake-review')
        wait('document.querySelector("#ws-remake-stock-personal-oak")')
        click('#ws-remake-stock-personal-oak');wait('!document.querySelector("#ws-remake-stock-personal-oak")')
        click('#ws-remake-stock-personal-iron');wait('!document.querySelector("#ws-remake-stock-personal-iron")')
        wait('document.querySelector("#ws-remake-connect")')
        click('#ws-remake-connect');wait('document.querySelector("#ws-remake-energy")')
        for _ in range(5):
            wait('document.querySelector("#ws-remake-start") && (!document.querySelector("#ws-remake-start").disabled || '
                 '(document.querySelector("#ws-remake-charge-wait") && !document.querySelector("#ws-remake-charge-wait").disabled))')
            if p.evaluate('!document.querySelector("#ws-remake-start").disabled'):break
            click('#ws-remake-charge-wait')
            click('#ws-remake-energy')
            wait('!document.querySelector("#ws-remake-energy") || document.querySelector("#ws-remake-energy").disabled')
        click('#ws-remake-start')
        for _ in range(5):
            wait('document.querySelector("#ws-remake-step") || document.querySelector("#ws-remake-place")')
            if p.evaluate('Boolean(document.querySelector("#ws-remake-place"))'):break
            previous=app.room.fabrication_record['jobs'][next(iter(app.room.fabrication_record['jobs']))]['work_j']
            click('#ws-remake-step')
            wait('!document.querySelector("#ws-remake-step") || !document.querySelector("#ws-remake-step").disabled')
            end=time.monotonic()+10
            while time.monotonic()<end and app.room.fabrication_record['jobs'][next(iter(app.room.fabrication_record['jobs']))]['work_j']<=previous:time.sleep(.01)
        click('#ws-remake-place')
        wait('document.querySelector("#ws-remake a")?.textContent==="Collect in World"')
        ident=next(iter(app.room.fabrication_record['jobs']))
        job=app.room.fabrication_record['jobs'][ident];root=job['root_body']
        self.assertEqual({'oak','iron'},set(job['product_materials_kg']))
        self.assertEqual(original,next(b for b in install._snapshot(app.live)['bodies'] if b['name']=='field pick'))
        p.send('Page.navigate',{'url':p.evaluate('document.querySelector("#ws-remake a").href')})
        wait('window.banjoRoom?.ready()')
        def key(code):
            for event in ('keyDown','keyUp'):p.send('Input.dispatchKeyEvent',{'type':event,'code':code,'key':code[-1].lower()})
        p.evaluate('''(()=>{const at=banjoRoom.world.bodies.get(%s).mesh.position;
            banjoRoom.standAt(at.x-.8,banjoRoom.groundAt(at.x,at.z)+1.62,at.z);
            banjoRoom.lookAt(at.x,at.y,at.z);document.activeElement.blur();banjoRoom.resume();})()'''%json.dumps(root))
        wait('banjoRoom.world.aim?.name===%s'%json.dumps(root));key('KeyE')
        wait('banjoRoom.held()?.name===%s && banjoRoom.use().mode==="tool-ready"'%json.dumps(root))
        # Work nearby after pickup. Teleporting the camera across the map
        # while holding a physical tool injects an unrelated carry transient.
        p.evaluate('''(()=>{const at=banjoRoom.camera.position;
            banjoRoom.lookAt(at.x+1.2,banjoRoom.groundAt(at.x+1.2,at.z),at.z);
            document.activeElement.blur();})()''')
        contact_trace={}
        original_contact=flow.server.tool_use._contact
        def observed_contact(*args):
            result=original_contact(*args)
            contact_trace['native']=deepcopy(app.live.session.state)
            contact_trace['ready']=deepcopy(args[1].get('ready'))
            contact_trace['points']=flow.server.tool_use._native_point(app,args[3])
            return result
        contact_patch=mock.patch.object(flow.server.tool_use,'_contact',side_effect=observed_contact)
        contact_patch.start();self.addCleanup(contact_patch.stop)
        wait('banjoRoom.use().target?.enabled && banjoRoom.use().target.target.distance_m>=1.15');key('KeyJ')
        wait('banjoRoom.use().last && banjoRoom.use().mode==="tool-ready"')
        used=p.evaluate('banjoRoom.use().last')
        if used.get('refused'):
            trace={'used':{k:v for k,v in used.items() if k!='notebook'},
                'target':p.evaluate('banjoRoom.use().target'),
                'native':app.live.session.state,
                'points':self.post('/api/live/act',{'session':app.live.session.id,'op':'tool_points'},world),
                'snapshot':install._snapshot(app.live),'contact_trace':contact_trace}
            (ROOT/'build/resource-flow/paid-mixed-use-failure.json').write_text(json.dumps(trace,indent=2),encoding='utf-8')
        self.assertFalse(used.get('refused'),used.get('refused'));self.assertGreater(used['result']['loosened_kg'],0)
        point=self.post('/api/live/act',{'session':app.live.session.id,'op':'tool_points'},world)['tool_points'][-1]
        self.assertEqual(root,point['grip_body']);self.assertTrue(point['grip_connected'])
        in_bag='banjoRoom.world.inventory.stowed.some(t=>t?.name===%s || t?.parts?.includes(%s))'%(json.dumps(root),json.dumps(root))
        key('KeyQ');wait('!banjoRoom.held() && '+in_bag)
        p.send('Page.navigate',{'url':'about:blank'});self.stop();self.start()
        self.post('/api/world/player/join',{'token':owner['token']},world)
        reopened=self.post('/api/world/open',{},world);app=self.app.hub.get(world)
        p.send('Page.navigate',{'url':self.base+f'/world?world={world}'})
        wait('window.banjoRoom?.ready() && '+in_bag)
        key('Digit2')
        wait('banjoRoom.held()?.name===%s && banjoRoom.use().mode==="tool-ready"'%json.dumps(root))
        point=self.post('/api/live/act',{'session':reopened['session'],'op':'tool_points'},world)['tool_points'][-1]
        self.assertEqual(root,point['grip_body']);self.assertTrue(point['attached']);self.assertTrue(point['grip_connected'])
        key('KeyQ');wait('!banjoRoom.held() && '+in_bag)
        self.native_evidence = {'materials': materials, 'source_preserved': True,
            'saved_reload': True, 'paid_make': True, 'native_use': used['result'],
            'bag_server_restart': True, 'provider_calls': 0,
            'boundary': 'Explicit collected test supplies; no complete raw supply or live-provider qualification.'}
        p.send('Page.navigate',{'url':self.base+f'/world?world={world}&workshop=1&tab=inventory'})
        wait('document.body.innerText.includes("Field pick")')
        wait('document.querySelector("#ws-inv-grid canvas[data-preview=ready]")')
        self.native_evidence['inventory_source_thumbnail']=True
        out = ROOT / 'build/resource-flow'; out.mkdir(parents=True, exist_ok=True)
        (out / 'mixed-pick-paid-restart.png').write_bytes(base64.b64decode(p.send('Page.captureScreenshot', {'format': 'png'})['data']))
        self.assertEqual([], [e for e in p.events if e.get('method') == 'Runtime.exceptionThrown'])

    def test_canonical_rover_paid_build_and_primary_use_in_browser(self):
        self.assertTrue(flow.qa_browser.CHROME.is_file(),'Chrome required')
        world,owner,app,*_=self.batch(process=False,legacy_process=True)
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
        world,owner,app,_,_,_=self.batch(process=False,legacy_process=True)
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
        world,owner,app,_,_,_=self.batch(process=False,legacy_process=True)
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
        wait('document.querySelector("#workshop-stage")?.visibleGeometry?.()?.meshes>0')
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
