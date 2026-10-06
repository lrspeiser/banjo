"""Native constituent receipt -> private paid forming allocation or refusal.

Pure tests use explicit adapter receipts, not simulated collection evidence.
The native tests compare the same generic shape/material compilation path.
"""
from copy import deepcopy
import json
from pathlib import Path
import math
import sys
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'playground'),str(ROOT/'tests')]
from mcp import fabrication as f, matter_fabrication as matter
from fabrication_tests import settings
import fabrication_room as api
import workshop_fixed_assembly_tests as fixed
import player_guidance


def receipt():
    cells=[{'id':'terrain:0:0:rock:'+str(i),'material':'concrete','run_kind':'rock',
        'density_kg_m3':2400.,'volume_m3':.000125,'mass_kg':.3,'size_m':[.05]*3,
        'source_center_m':[i*.05,0.,0.],'damage':.2} for i in range(30)]
    return {'schema':'banjo.ground-matter-transfer.v1','id':'detached-0001','cells':cells,
        'volumes':{'rock_m3':.00375,'soil_m3':0.,'sand_m3':0.},'mass_kg':9.,
        'source_work_j':112500.,'model':'work-cut-v2','provenance':'recorded-terrain-cut',
        'work_source':'finite-test-source'}


def quote():
    return {'candidate':matter.stone_pick_recipe(),'material':'concrete','stock_kg':7.,'product_kg':6.,
        'stock_materials_kg':{'concrete':5.,'oak':2.},'product_materials_kg':{'concrete':4.5,'oak':1.5},
        'offcut_kg':1.,'required_j':700.,'supply_required_j':700.,'minimum_duration_s':1.4,
        'cell_m':.04,'cells':40,'matter_physics_hash':'test-adapter-hash'}


class RawCrafting(unittest.TestCase):
    def setUp(self):
        self.initial=f.new(settings(stock_kg={'oak':2.},energy_j=1000.),0.)
        self.action={'request_id':'collect-matter-0001','revision':0,'op':'collect-ground-matter','id':'detached-0001'}
        self.state,_=matter.receive_matter(self.initial,self.action,receipt(),'alice')

    def start(self,state=None,q=None):
        state=self.state if state is None else state
        q=matter.plan(state,'alice',quote()) if q is None else q
        action={'op':'start','requested_by':'alice','revision':state['revision'],'request_id':'raw-pick-job-0001'}
        return f.mutate(state,action,quote=q),action

    def test_collection_private_retry_and_duplicate_cells(self):
        self.assertEqual(self.initial['stock_kg'],self.state['stock_kg'])
        self.assertEqual((self.state,True),matter.receive_matter(self.state,self.action,receipt(),'alice'))
        with self.assertRaisesRegex(ValueError,'another collection or player'):
            matter.receive_matter(self.state,self.action,receipt(),'bob')
        with self.assertRaisesRegex(ValueError,'already collected'):
            matter.receive_matter(self.state,{**self.action,'revision':1,'request_id':'collect-matter-0002'},receipt(),'alice')
        self.assertEqual({},matter.available_materials(self.state,'bob'))
        self.assertAlmostEqual(9.,matter.available_materials(self.state,'alice')['concrete'])

    def test_quote_read_only_partial_cell_allocation_and_exact_source_state(self):
        before=deepcopy(self.state);planned=matter.plan(self.state,'alice',quote())
        self.assertEqual(before,self.state)
        source=planned['raw_matter'];self.assertAlmostEqual(5.,sum(c['mass_kg'] for c in source['allocations']))
        self.assertLess(source['allocations'][-1]['source_fraction'],1.)
        self.assertEqual(.2,source['allocations'][-1]['source_cell']['damage'])
        self.assertNotIn('raw_matter',matter.plan(self.state,'bob',quote()))
        reading=player_guidance.build_readiness(planned,self.state)
        self.assertEqual('Ready to make',reading['status']);self.assertTrue(reading['ready_to_start'])
        self.assertAlmostEqual(5.,next(r for r in reading['lines'] if r['substance']=='concrete')['native_raw_kg'])

    def test_paid_work_waste_transfer_reload_and_replay_close_accounts(self):
        (out,replayed),action=self.start();self.assertFalse(replayed)
        self.assertEqual((out,True),f.mutate(out,action,quote=quote()))
        self.assertAlmostEqual(4.,matter.available_materials(out,'alice')['concrete'])
        self.assertAlmostEqual(0.,out['stock_kg']['concrete'],places=12);self.assertEqual(0.,out['stock_kg']['oak'])
        f.advance(out,2.);job=out['jobs'][action['request_id']]
        self.assertEqual('ready',job['status']);self.assertEqual({'concrete':.5,'oak':.5},out['waste_kg'])
        published=f.transfer(out,action['request_id'],{'matter_physics_hash':job['matter_physics_hash'],
            'mass_kg':6.,'product_materials_kg':job['product_materials_kg'],'root_body':'physical-pick'},'raw-pick-place-0001')
        loaded=json.loads(json.dumps(published));f.validate_state(loaded)
        self.assertEqual(published,loaded)
        audit=f.audit(loaded);self.assertTrue(all(abs(v)<1e-9 for v in audit['material_residual_kg'].values()))
        self.assertAlmostEqual(0.,audit['energy_residual_j']);self.assertAlmostEqual(5.,audit['native_matter_received_kg']['concrete'],places=12)
        self.assertEqual(job['raw_matter'],loaded['jobs'][action['request_id']]['raw_matter'])

    def test_insufficient_wood_and_changed_inputs_leave_all_cells_untouched(self):
        poor=deepcopy(self.state);poor['stock_kg']['oak']=poor['config']['stock_kg']['oak']=.1
        before=deepcopy(poor)
        with self.assertRaisesRegex(ValueError,'Insufficient stock'):self.start(poor)
        self.assertEqual(before,poor)
        planned=matter.plan(self.state,'alice',quote());changed=deepcopy(self.state)
        changed['stock_kg']['concrete']=1.;changed['config']['stock_kg']['concrete']=1.
        before=deepcopy(changed)
        with self.assertRaisesRegex(ValueError,'inputs changed'):self.start(changed,planned)
        self.assertEqual(before,changed)

    def test_empty_legacy_rock_and_other_substances_cannot_be_concrete(self):
        legacy=f.new(settings(stock_kg={'oak':2.}),0.)
        bulk={'schema':'banjo.bulk-material.v1','source':'excavated_ground','form':'rubble',
            'thermal_state':'unmodeled','contents':[{'substance':'rock','volume_m3':.00375,'mass_kg':9.}]}
        legacy,_=f.receive_bulk(legacy,self.action,bulk)
        self.assertNotIn('raw_matter',matter.plan(legacy,'alice',quote()))
        with self.assertRaisesRegex(ValueError,'Insufficient stock'):self.start(legacy)
        for change in ('volume','mass','material','duplicate'):
            invalid=receipt()
            if change=='volume':invalid['cells'][0]['volume_m3']*=2
            elif change=='mass':invalid['cells'][0]['mass_kg']*=2
            elif change=='material':invalid['cells'][0]['material']='iron'
            else:invalid['cells'][1]['id']=invalid['cells'][0]['id']
            with self.subTest(change=change),self.assertRaises(ValueError):matter.packet(invalid)

    def test_legacy_bulk_note_is_read_only_private_and_never_grants_cell_stock(self):
        legacy=f.new(settings(stock_kg={'oak':2.}),0.)
        bulk={'schema':'banjo.bulk-material.v1','source':'excavated_ground','form':'rubble',
            'thermal_state':'unmodeled','contents':[{'substance':'rock','volume_m3':.09375,'mass_kg':225.}]}
        legacy,_=f.receive_bulk(legacy,self.action,bulk)
        legacy['raw_lot_ownership']={self.action['request_id']:{'owner':'alice','source_actor':'alice'}}
        before=deepcopy(legacy)
        note=matter.source_note(legacy,'alice',{'concrete':5.})
        self.assertIn('225 kg remains stored',note);self.assertIn('no constituent cell record',note)
        self.assertIn('collect native cells',note)
        self.assertIsNone(matter.source_note(legacy,'bob',{'concrete':5.}))
        self.assertIsNone(matter.source_note(legacy,'alice',{'oak':5.}))
        self.assertEqual({},matter.available_materials(legacy,'alice'))
        self.assertNotIn('raw_matter',matter.plan(legacy,'alice',quote()))
        self.assertEqual(before,legacy)

    def test_source_state_owner_and_paid_job_tampering_refuse_reopen(self):
        (out,_),action=self.start()
        for kind in ('cell','owner','job','mass','double'):
            bad=deepcopy(out);entry=bad['raw_make_inputs'][action['request_id']]
            if kind=='cell':entry['allocations'][0]['source_cell']['damage']=0.
            elif kind=='owner':entry['owner']='bob'
            elif kind=='job':bad['jobs'][action['request_id']].pop('raw_matter')
            elif kind=='mass':entry['materials_kg']['concrete']+=1.
            else:
                entry['allocations'].append(deepcopy(entry['allocations'][0]))
                entry['materials_kg']['concrete']+=.3
            with self.subTest(kind=kind),self.assertRaises(ValueError):f.validate_state(bad)

    def test_exact_formed_cells_and_offcuts_cover_every_source_fraction(self):
        q=quote();q['cell_m']=.05
        q['formation_cells']=[{'grid':[i,0,0],'material':'concrete','component':'arm'} for i in range(15)]
        q=matter.plan(self.state,'alice',q)
        (out,_),action=self.start(q=q)
        mapped=out['jobs'][action['request_id']]['raw_matter']
        self.assertAlmostEqual(4.5,sum(p['mass_kg'] for c in mapped['formed_cells'] for p in c['raw_sources']))
        self.assertAlmostEqual(.5,sum(p['mass_kg'] for p in mapped['raw_offcuts']))
        bad=deepcopy(out)
        for entry in (bad['raw_make_inputs'][action['request_id']],bad['jobs'][action['request_id']]['raw_matter']):
            entry['formed_cells'][0]['raw_sources'][0]['mass_kg']+=.01
        with self.assertRaisesRegex(ValueError,'unrelated source'):f.validate_state(bad)


@unittest.skipUnless(fixed.paid.ENGINE and fixed.paid.ENGINE.is_file(),'BANJO_LIVE_ENGINE required')
class NativeToolMaterials(unittest.TestCase):
    setUp=fixed.PaidFixed.setUp
    context=fixed.PaidFixed.context
    call=fixed.PaidFixed.call
    step=fixed.PaidFixed.step
    def test_gathered_pick_shape_native_quote_glass_oak_iron_concrete(self):
        from mcp import engine_materials
        results=[]
        for material in ('glass','oak','iron','concrete'):
            candidate=matter.stone_pick_recipe();candidate['component_overrides']['arm']['material']=material
            q=self.call('quote',candidate=candidate,stock_kg=25.)['quote']
            self.assertGreater(q['product_kg'],0.)
            self.assertAlmostEqual(25.*100.,q['required_j'])
            if material!='oak':self.assertEqual({material,'oak'},set(q['product_materials_kg']))
            results.append({'head_material':material,'density_kg_m3':engine_materials.density(material),
                'young_modulus_pa':engine_materials.mechanics(material)['young_modulus_pa'],
                'product_mass_kg':q['product_kg'],'product_materials_kg':f.materials(q,'product'),
                'stock_kg':25.,'required_work_j':q['required_j'],'installation_cell_m':.04,
                'fixed_interfaces':q.get('fixed_interfaces',[]),
                'limits':'Native admitted geometry/material quote. Not a per-material excavation/fracture/wear experiment.'})
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/'raw-crafting-material-quotes.json').write_text(json.dumps(results,indent=2),encoding='utf-8')


@unittest.skipUnless(fixed.paid.ENGINE and fixed.paid.ENGINE.is_file(),'BANJO_LIVE_ENGINE required')
class NativeMatterTool(unittest.TestCase):
    WORLD_CELL_M=.04
    def setUp(self):
        import fabrication_stock_tests as funded
        funded.NativeStock.setUp(self)
        self.app.world_id='raw-crafting-native-fixture'
        person={'standing_m':[0.,.25,0.],'eyes_m':[0.,1.87,0.],'facing':[0.,0.,-1.]}
        self.room.player_records={who:{'id':who,'token':letter*64,'name':who,
            'inventory':{},'pose':deepcopy(person)} for who,letter in (('alice','a'),('bob','b'))}
        self.room.spec['terrain']={'surface':'columns','generate':{'kind':'flat','nx':24,'nz':24,
            'cell_m':.25,'soil_m':.25,'sand_m':0.,'discharge_m3_s':0.}}
        self.room.spec['cell_m']=self.WORLD_CELL_M
        fixture_section=80 if self.WORLD_CELL_M==.04 else 100
        self.room.spec['bodies'][0].update(size_mm=[fixture_section]*3,
            center_mm=[-5000,fixture_section/2,-5000])
        self.room.spec['bodies'].append({'name':'fixture cutter','shape':'box','material':'iron',
            'size_mm':[800,fixture_section,fixture_section],'center_mm':[0,1000,0]})
        self.room.spec.setdefault('tool_points',[]).append({'body':'fixture cutter','tip_mm':[400,1000,0],
            'pointing':[0,-1,0],'grip_mm':[-300,1000,0],'width_mm':fixture_section,
            'thickness_mm':fixture_section,'angle_deg':30.,'length_mm':200})
        self.live.open(self.app,{'spec':self.room.spec})
        self.owner_token=fixed.paid.workshop_install.workshop_library.REQUEST_OWNER.set('alice')
        self.addCleanup(fixed.paid.workshop_install.workshop_library.REQUEST_OWNER.reset,self.owner_token)
        self.live.session._actor_local.actor='alice'
        self.live.session.send(op='wield',name='fixture cutter',grip=[-.3,1.,0.])
        self.person=person

    def context(self):return {'scene':self.room.scene,'session':self.live.session.id}
    def call(self,op,**body):return api.request(self.app,op,{**self.context(),**body})
    def persist(self,_app,_message):
        saved=fixed.paid.workshop_install._snapshot(self.live)
        state=deepcopy(self.room.fabrication_record);f.advance(state,saved['t_s'])
        api._persist(self.app,self.room,saved,state)
        return True

    def test_native_rock_private_collection_paid_pick_inventory_use_and_restart(self):
        import physical_matter,inventory_room,workshop_library as library,tool_use,market,playable_recipes
        # Explicit experiment sources: a supplied iron cutter, finite 20 kg
        # catalog aluminum, two 1 MJ cut budgets, 4 kJ native battery and 10 kJ
        # later economic work reservoir. This is not a fresh-player opening.
        native_cuts=[]
        for n,y in enumerate((.24,-.01)):
            cut=self.live.session.send(op='strike-cell',at_m=[0.,y,0.],work_j=1e6,
                work_source='fixture-cut-'+str(n))['ground_cut']
            self.assertTrue(cut['supported'],cut);self.assertIsNotNone(cut['body_id'],cut)
            self.assertLessEqual(cut['consumed_work_j'],1e6)
            api.wait(self.app,{**self.context(),'seconds':1})
            native_cuts.append(cut)
            body={**self.context(),'id':cut['body_id'],'request_id':'native-collect-'+str(n)}
            before=fixed.paid.workshop_install._snapshot(self.live);state=deepcopy(self.room.fabrication_record)
            with mock.patch.object(self.app.store,'save',side_effect=OSError('fixture disk failure')):
                with self.assertRaises(OSError):physical_matter.collect(self.app,body,'alice')
            self.assertEqual(before,fixed.paid.workshop_install._snapshot(self.live));self.assertEqual(state,self.room.fabrication_record)
            if n==1:
                real_save=self.app.store.save
                def lost_ack(record):real_save(record);raise OSError('fixture reply lost after save')
                with mock.patch.object(self.app.store,'save',side_effect=lost_ack):
                    with self.assertRaises(OSError):physical_matter.collect(self.app,body,'alice')
                saved=self.app.store.load(self.room.scene)
                self.live.open(self.app,{'spec':saved.spec,'snapshot':saved.world_record})
                self.app.room=self.room=saved;self.live.session._actor_local.actor='alice'
            else:physical_matter.collect(self.app,body,'alice')
            self.assertTrue(physical_matter.collect(self.app,body,'alice')['replayed'])
            with self.assertRaisesRegex(ValueError,'another item or player'):physical_matter.collect(self.app,body,'bob')
            self.assertEqual([],self.live.session.send(op='ground-debris')['ground_debris']['bodies'])
        with library._connect(self.app) as db:
            db.execute('INSERT INTO workshop_material_rack VALUES (?,?,?,?)',('alice','aluminum',20.,library._now()))
        import workshop_tabs
        stone=next(r for r in workshop_tabs.recipes(self.app)['templates'] if r['name']=='Stone field pick')
        self.assertTrue(stone['readiness']['ready_as_drawn'],stone['readiness'])
        self.assertEqual(self.WORLD_CELL_M,stone['readiness']['world']['cell_size_m'])
        product=playable_recipes.stone_pick_recipe();plan=self.call('plan_make',candidate=product)
        self.assertEqual(self.WORLD_CELL_M,plan['quote']['cell_m'])
        self.assertGreater(plan['quote']['raw_matter']['materials_kg']['concrete'],0.)
        self.assertAlmostEqual(0.,plan['missing_materials_kg']['concrete'],delta=1e-10)
        peer=library.REQUEST_OWNER.set('bob')
        try:self.assertNotIn('raw_matter',self.call('plan_make',candidate=product)['quote'])
        finally:library.REQUEST_OWNER.reset(peer)
        metal=plan['missing_materials_kg']['aluminum'];reading=self.call('state')
        source=next(s for s in reading['stock_sources'] if s['material']=='aluminum' and s['pool']=='personal')
        self.call('fund_stock',material='aluminum',mass_kg=metal,pool='personal',rack_hash=source['rack_hash'],
            revision=self.room.fabrication_record['revision'],request_id='raw-pick-metal')
        reading=self.call('state');battery=reading['energy_sources'][0]
        self.call('connect_energy',store=battery['id'],store_hash=battery['store_hash'],power_w=250.,
            revision=self.room.fabrication_record['revision'],request_id='raw-pick-connect')
        api.wait(self.app,{**self.context(),'seconds':math.ceil(plan['quote']['supply_required_j']/250.)})
        reading=self.call('state');battery=reading['energy_sources'][0]
        self.call('fund_energy',store_hash=battery['store_hash'],joules=plan['quote']['supply_required_j'],
            revision=self.room.fabrication_record['revision'],request_id='raw-pick-energy')
        plan=self.call('plan_make',candidate=product)
        self.assertTrue(plan['build_readiness']['ready_to_start'],plan['build_readiness'])
        self.call('start_make',plan_id=plan['plan_id'],revision=plan['revision'],request_id='native-raw-pick')
        api.wait(self.app,{**self.context(),'seconds':math.ceil(plan['quote']['minimum_duration_s'])})
        preview=api.preview(self.app,{**self.context(),'job_id':'native-raw-pick','position_m':[1.,1.]})
        installed=api.commit(self.app,{**self.context(),'job_id':'native-raw-pick','preview_id':preview['preview_id'],'request_id':'raw-pick-install'})
        self.live.session._actor_local.actor='alice'
        self.assertEqual(plan['quote']['raw_matter'],installed['raw_matter'])
        source_ids={c['id'] for c in self.room.fabrication_record['matter_lots']['native-collect-1']['packet']['cells']}
        self.assertTrue(all(a['source_id'] in source_ids for a in installed['raw_matter']['allocations']))
        root=installed['root_body'];self.live.session.send(op='release')
        self.person={'standing_m':[1.,.25,1.],'eyes_m':[1.,1.87,1.],'facing':[1.,0.,0.]}
        self.room.player_records['alice']['pose']=deepcopy(self.person)
        shown=inventory_room.shown(self.app,'alice')
        taken=inventory_room.request(self.app,{'op':'take','item':root,'request':'raw-pick-bag',
            'revision':shown['record']['revision'],'person':self.person},'alice')
        self.assertTrue(taken['ok'],taken)
        shown=inventory_room.shown(self.app,'alice')
        equipped=inventory_room.request(self.app,{'op':'equip','item':root,'request':'raw-pick-equip',
            'revision':shown['record']['revision'],'person':self.person},'alice')
        self.assertTrue(equipped['ok'],equipped)
        self.assertIsNotNone(tool_use.profile_held(self.app))
        with library._connect(self.app) as db:
            market._schema(db)
            db.execute('INSERT INTO market_wallet(owner_id,balance_j) VALUES (?,?) ON CONFLICT(owner_id) DO UPDATE SET balance_j=?',('alice',10000,10000))
        used=tool_use.run(self.app,{'person':self.person,'at_m':[2.,.24,1.],
            'energy_assist':True,'request_id':'raw-pick-use'},cut_persist=self.persist)
        self.assertNotIn('refused',used,used)
        self.assertGreater(used['cut']['mass_kg'],0.)
        shown=inventory_room.shown(self.app,'alice')
        stowed=inventory_room.request(self.app,{'op':'stow','item':root,'request':'raw-pick-restow',
            'revision':shown['record']['revision'],'person':self.person},'alice')
        self.assertTrue(stowed['ok'],stowed);self.persist(self.app,'raw tool in bag')
        before=deepcopy(self.room.fabrication_record)
        loaded=self.app.store.load(self.room.scene)
        self.live.open(self.app,{'spec':loaded.spec,'snapshot':loaded.world_record})
        self.app.room=self.room=loaded;self.live.session._actor_local.actor='alice'
        self.assertEqual(before,self.room.fabrication_record)
        shown=inventory_room.shown(self.app,'alice')
        self.assertTrue(any(i and root in (i.get('parts') or [i['name']]) for i in shown['stowed']))
        equipped=inventory_room.request(self.app,{'op':'equip','item':root,'request':'raw-pick-requip',
            'revision':shown['record']['revision'],'person':self.person},'alice')
        self.assertTrue(equipped['ok'],equipped)
        point=tool_use._native_point(self.app,tool_use.profile_held(self.app)['tool'])
        self.assertTrue(point['attached']);self.assertTrue(point.get('grip_connected',True))
        audit=f.audit(self.room.fabrication_record)
        self.assertLess(max(abs(v) for v in audit['material_residual_kg'].values()),1e-7)
        self.assertLess(abs(audit['energy_residual_j']),1e-7)
        evidence={'native_cuts':native_cuts,'formed_mass_kg':installed['mass_kg'],'raw_matter':installed['raw_matter'],
            'native_paid_use':used['cut'],'audit':audit,'private_collection_retry_and_failure':True,
            'inventory_equip_bag_whole_restart':True,'dt_s':1/240,'source_cell_m':.05,'product_cell_m':self.WORLD_CELL_M,
            'limits':'Explicit supplied cutter/aluminum/work/battery experiment. Cold forming reduction; no calibrated stone fracture or complete fresh-player acceptance.'}
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        name='raw-crafting-native.json' if self.WORLD_CELL_M==.04 else 'raw-crafting-native-50mm.json'
        (out/name).write_text(json.dumps(evidence,indent=2),encoding='utf-8')


class NativeMatterToolWorld50mm(NativeMatterTool):
    WORLD_CELL_M=.05


class StoneReadiness(unittest.TestCase):
    def test_actual_grids_admit_implicit_fixed_mounts_but_refuse_missing_authored_mounts(self):
        import workshop_recipe
        from mcp import workshop_components
        candidate=matter.stone_pick_recipe();design,overrides=workshop_components.design_from_spec(candidate)
        for grid in (.04,.05):
            ready=workshop_recipe.assess(design,overrides,world_cell_m=grid)
            self.assertTrue(ready['ready_as_drawn'],ready)
            self.assertTrue(ready['native_preview_required']);self.assertTrue(ready['functional_test_required'])
        for patch in ({'@construction':{'schema':'banjo.workshop-construction.v1','joints':[],'joints_authored':True}},
                      {'arm':{'material':'concrete','center_m':[2.,2.,2.]}}):
            broken={**candidate,'component_overrides':{**overrides,**patch}}
            design,changed=workshop_components.design_from_spec(broken)
            self.assertFalse(workshop_recipe.assess(design,changed,world_cell_m=.05)['ready_as_drawn'])


if __name__=='__main__':unittest.main()
