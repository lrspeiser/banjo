"""Fixed constituent admission, paid native publication and local accounts."""
from copy import deepcopy
import json
import math
from pathlib import Path
import sys
import unittest
from unittest import mock
from types import SimpleNamespace
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'playground'),str(ROOT/'tests')]
from mcp import workshop_components, workshop_fixed_assembly as fixed, workshop_material_support
import fabrication_tests as paid


def pick(material='iron'):
    design=paid.workshop_install.w.assemble('field-pick',design_id='field-pick')
    recipe=paid.workshop_install.recipe_of(design,{})
    recipe['component_overrides']={'arm':{'material':material}}
    return recipe


class Mounts(unittest.TestCase):
    def layout(self,recipe=None):
        design,overrides=workshop_components.design_from_spec(recipe or pick())
        return fixed.layout(design,overrides,cell_m=.04)

    def test_matched_heads_retain_allocation_and_finite_catalog_mount(self):
        from mcp import workshop_buildability as build
        for material in ('glass','oak','iron'):
            out=self.layout(pick(material))
            groups={g['component']:g for g in out['groups']}
            self.assertEqual(material,groups['arm']['material'])
            self.assertEqual('oak',groups['haft']['material'])
            self.assertAlmostEqual(out['mass_kg'],sum(g['mass_kg'] for g in groups.values()))
            self.assertGreater(out['connections'][0]['holds_tension_n'],0)
            self.assertGreater(out['connections'][0]['holds_shear_n'],0)
            design,overrides=workshop_components.design_from_spec(pick(material))
            self.assertIsNone(workshop_material_support.fixed_lattice_blocker(design,overrides,cell_m=.04))
        # Two collinear constituents look like one box as a union, but the
        # native bridge must keep both materials and budget two separate boxes.
        candidate={'kind':'custom','component_overrides':{'@construction':{'added':[
            {'name':'one','role':'panel','family':'panel','shape':'box','material':'oak',
             'size_m':[.08,.08,.08],'center_m':[.04,.04,.04],'rotation_deg':[0,0,0]},
            {'name':'two','role':'panel','family':'panel','shape':'box','material':'iron',
             'size_m':[.08,.08,.08],'center_m':[.12,.04,.04],'rotation_deg':[0,0,0]}]}}}
        design,overrides=workshop_components.design_from_spec(candidate)
        report,_,_=build.assess(design,overrides,cell_size_m=.04)
        self.assertTrue(report['compilation_ready'],report)
        self.assertEqual(report['costs']['collision_boxes'],2)
        with mock.patch.object(build,'MAX_SCENE_BOXES',1):
            report,_,_=build.assess(design,overrides,cell_size_m=.04)
        self.assertFalse(report['compilation_ready'])
        self.assertTrue(any('2 joined boxes exceed' in e for e in report['errors']))

    def test_absent_overlap_and_unconnected_authored_mounts_refuse(self):
        for overrides in ({'arm':{'material':'iron','center_m':[.375,.025,-.2]}},
                          {'arm':{'material':'iron','center_m':[.375,.025,.2]}},
                          {'arm':{'material':'iron'},'@construction':{'joints_authored':True}}):
            recipe=pick();recipe['component_overrides']=overrides
            with self.subTest(overrides=overrides),self.assertRaises(ValueError):self.layout(recipe)

    def test_physical_hash_and_mounts_are_deterministic_and_material_sensitive(self):
        self.assertEqual(self.layout(),self.layout())
        self.assertNotEqual(self.layout()['physics_hash'],self.layout(pick('glass'))['physics_hash'])

    def test_separate_handle_frame_reads_one_native_instant(self):
        import tool_use
        point={'body':'head','grip_body':'handle','attached':True,'grip_connected':True,
            'tip':[.375,0,-.325],'grip':[-.35,0,0],'pointing':[0,0,-1]}
        stale={'bodies':[{'name':'handle','position_m':[50,20,30],
                         'orientation_wxyz':[0,0,1,0]}]}
        session=SimpleNamespace(id='test',state=stale)
        def act(body):
            if body['op']=='tool_points':return {'tool_points':[point]}
            return {'bodies':[{'name':'handle','position_m':[0,0,0],
                               'orientation_wxyz':[1,0,0,0]}]}
        live=SimpleNamespace(session=session,_lock=threading.RLock(),act=mock.Mock(side_effect=act))
        actual=tool_use._native_point(SimpleNamespace(live=live),'handle')
        self.assertEqual(point['tip'],actual['tip_local'])
        self.assertEqual(point['grip'],actual['grip_local'])
        self.assertEqual(point['pointing'],actual['pointing_local'])


@unittest.skipUnless(paid.ENGINE and paid.ENGINE.is_file(),'BANJO_LIVE_ENGINE required')
class PaidFixed(unittest.TestCase):
    setUp=paid.NativeFabrication.setUp
    context=paid.NativeFabrication.context
    call=paid.NativeFabrication.call
    step=paid.NativeFabrication.step

    def test_invalid_native_handle_quote_refuses_before_any_payment(self):
        state=deepcopy(self.room.fabrication_record)
        snapshot=paid.workshop_install._snapshot(self.live)
        installed=paid.workshop_install.fixed_lattice_plan
        def invalid(*args,**kwargs):
            result=installed(*args,**kwargs)
            result['tool']['point']['grip_body']='missing-native-handle'
            return result
        with mock.patch.object(paid.workshop_install,'fixed_lattice_plan',side_effect=invalid):
            with self.assertRaises(ValueError):
                self.call('start',candidate=pick(),stock_kg=10,revision=state['revision'],request_id='invalid-fixed')
        self.assertEqual(state,self.room.fabrication_record)
        self.assertEqual(snapshot,paid.workshop_install._snapshot(self.live))

    def finish(self,material='iron'):
        ident='fixed-paid-'+material
        quote=self.call('quote',candidate=pick(material),stock_kg=10)['quote']
        before=deepcopy(self.room.fabrication_record)
        self.call('start',candidate=pick(material),stock_kg=10,
            revision=before['revision'],request_id=ident)
        self.step(2)
        preview=paid.room_api.preview(self.app,{**self.context(),'job_id':ident,'position_m':[0,0]})
        request={**self.context(),'job_id':ident,'preview_id':preview['preview_id'],'request_id':'place-'+ident}
        return ident,quote,before,preview,request

    def test_matched_paid_heads_native_geometry_heat_and_reopen_close_local_accounts(self):
        evidence=[]
        for index,material in enumerate(('glass','oak','iron')):
            ident='fixed-compare-'+material
            quote=self.call('quote',candidate=pick(material),stock_kg=10)['quote']
            before=deepcopy(self.room.fabrication_record)
            self.call('start',candidate=pick(material),stock_kg=10,
                revision=before['revision'],request_id=ident);self.step(2)
            preview=paid.room_api.preview(self.app,{**self.context(),'job_id':ident,'position_m':[index*2,0]})
            self.assertEqual(quote['matter_physics_hash'],preview['matter_physics_hash'])
            request={**self.context(),'job_id':ident,'preview_id':preview['preview_id'],'request_id':'place-'+ident}
            receipt=paid.room_api.commit(self.app,request)
            roots=set(receipt.get('root_bodies') or [receipt['root_body']])
            snap=paid.workshop_install._snapshot(self.live)
            bodies=[b for b in snap['bodies'] if b['name'] in roots]
            mass=sum(b['mass_kg'] for b in self.live.session.state['bodies'] if b['name'] in roots)
            self.assertTrue(math.isclose(mass,quote['product_kg'],rel_tol=2e-7,abs_tol=1e-9))
            self.assertEqual({material,'oak'},{b['material'] for b in bodies})
            thermal=receipt.get('thermal_transfers') or [receipt['thermal_transfer']]
            self.assertAlmostEqual(sum(t['mass_kg'] for t in thermal),quote['product_kg'],places=6)
            self.assertEqual(roots,{t['body'] for t in thermal})
            self.assertTrue(paid.room_api.commit(self.app,request)['replayed'])
            self.assertAlmostEqual(before['energy_j']-quote['supply_required_j'],self.room.fabrication_record['energy_j'])
            for m,kg in paid.model.materials(quote,'stock').items():
                self.assertAlmostEqual(before['stock_kg'][m]-kg,self.room.fabrication_record['stock_kg'][m])
            audit=paid.model.audit(self.room.fabrication_record)
            self.assertAlmostEqual(0,audit['energy_residual_j'],places=7)
            loaded=self.app.store.load('fabrication')
            self.live.open(self.app,{'spec':loaded.spec,'snapshot':loaded.world_record})
            self.room=self.app.room=loaded
            point=(self.live.act({'session':self.live.session.id,'op':'tool_points'})['tool_points'])[-1]
            self.assertTrue(point['attached']);self.assertTrue(point.get('grip_connected',True))
            self.assertIn(point.get('grip_body') or point['body'],roots)
            evidence.append({'head':material,'product_kg':quote['product_kg'],
                'stock_materials_kg':paid.model.materials(quote,'stock'),'work_j':quote['required_j'],
                'mechanical_mass_residual_kg':mass-quote['product_kg'],
                'energy_residual_j':audit['energy_residual_j'],'fixed_interfaces':quote.get('fixed_interfaces',[])})
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/'paid-fixed-materials.json').write_text(json.dumps(evidence,indent=2)+'\n')

    def test_failed_install_and_retry_preserve_paid_source_and_debit_once(self):
        ident,quote,before,preview,request=self.finish()
        state=deepcopy(self.room.fabrication_record);snapshot=paid.workshop_install._snapshot(self.live)
        with mock.patch.object(self.app.store,'save',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):paid.room_api.commit(self.app,request)
        self.assertEqual(state,self.room.fabrication_record)
        self.assertEqual(snapshot,paid.workshop_install._snapshot(self.live))
        result=paid.room_api.commit(self.app,request)
        self.assertTrue(paid.room_api.commit(self.app,request)['replayed'])
        self.assertEqual(quote['product_materials_kg'],result['product_materials_kg'])
        self.assertAlmostEqual(before['energy_j']-quote['supply_required_j'],self.room.fabrication_record['energy_j'])

    def test_tampered_native_fixing_and_handle_binding_fail_preservation(self):
        ident,quote,before,preview,request=self.finish()
        plan=self.app._workshop_install_previews[preview['preview_id']]
        staged,saved=paid.workshop_install._stage(self.app,self.live,self.live.session,
            plan['spec'],paid.workshop_install._snapshot(self.live),plan['matter'],plan['root'],plan['shift'])
        self.addCleanup(staged.shutdown)
        prior=paid.workshop_install._snapshot(self.live)
        definitions=plan['matter']['joints']
        points=[p for p in plan['spec']['tool_points'] if p['body'] in plan['root']]
        for field in ('fixing','binding'):
            bad=deepcopy(saved)
            if field=='fixing':bad['joints'][-1]['holds_shear_n']+=1
            else:bad['tool_points'][-1]['grip_body']=bad['tool_points'][-1]['body']
            with self.subTest(field=field),self.assertRaises(ValueError):
                paid.workshop_install._preserved(prior,bad,plan['root'],added_joints=definitions,added_tool_points=points)


if __name__=='__main__':unittest.main()
