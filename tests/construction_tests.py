"""Construction declarations and free native starter foundations.

No browser driver, provider calls, pose correction or friction overrides.
Settling checks do not certify soil bearing, fracture or full conservation.
"""
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'playground'),str(ROOT/'tools')]
from mcp import workshop_components,workshop_placement,engine_materials
import build_new_world as builder
import build_explore_world as grounds
import fracture_lab
import live_session
import rigid_assembly
import world_seed


def tilt(body):
    w,x,y,z=body['orientation_wxyz']
    return math.degrees(math.acos(max(-1.,min(1.,1-2*(x*x+z*z)))))


class Contracts(unittest.TestCase):
    def test_design_chat_defines_the_same_validated_installation_contract(self):
        import workshop_chat
        from types import SimpleNamespace
        recipe={'kind':'foundation-pad','parameters':{}}
        state=workshop_chat._State(SimpleNamespace(),recipe,selected_name=None,materials=['concrete'],library=[])
        result=state.execute('define_installation',{'support_components':['footing-1','footing-2','footing-3','footing-4'],
            'upright':True,'clearance_m':.25,'ports':[],'skills':[]})
        self.assertEqual(.25,result['installation']['clearance_m'])
        reopened,_=workshop_components.design_from_spec(state.current_spec())
        self.assertEqual(result['installation'],reopened.wireframe()['installation'])
        with self.assertRaises(ValueError):state.execute('define_installation',{'support_components':['invented']})

    def test_authored_requirements_roundtrip_and_reject_invented_parts_and_state(self):
        recipe={'kind':'foundation-pad','parameters':{'material':'oak'}}
        design,overrides=workshop_components.design_from_spec(recipe)
        contract=workshop_placement.for_design(design)
        self.assertEqual(contract,design.wireframe()['installation'])
        restored,_=workshop_components.design_from_spec({**recipe,'component_overrides':overrides})
        self.assertEqual(contract,workshop_placement.for_design(restored))
        for patch in ({'support_components':['missing']},{'clearance_m':float('nan')},
                      {'stock_kg':999},{'skills':['x','x']}):
            bad=deepcopy(overrides);bad[workshop_placement.KEY].update(patch)
            with self.assertRaises(ValueError):
                workshop_components.design_from_spec({**recipe,'component_overrides':bad})

    def test_changed_geometry_refreshes_contract_and_preserves_component_construction(self):
        recipe={'kind':'foundation-pad','parameters':{}}
        first,_=workshop_components.design_from_spec(recipe)
        changed,_,_=workshop_components.edit(recipe,part_name='platform',action='wider')
        before=workshop_placement.for_design(first);after=workshop_placement.for_design(changed)
        # Footings have not moved just because a platform is wider; requirements
        # are derived from the declared support parts, not the platform envelope.
        self.assertEqual(before['support_bounds_m'],after['support_bounds_m'])
        self.assertNotEqual(first.measure()['bounding_box_m'],changed.measure()['bounding_box_m'])
        self.assertEqual(4,len(after['connections']))
        for kind in ('electric-furnace','processor'):
            design,_=workshop_components.design_from_spec({'kind':kind,'parameters':{}})
            self.assertEqual({'input','output'},{p['kind'] for p in workshop_placement.for_design(design)['ports']})


@unittest.skipUnless(os.environ.get('BANJO_LIVE_ENGINE'),'needs native engine')
class NativeFoundations(unittest.TestCase):
    def test_actual_free_supported_mass_settling_and_exact_reopen(self):
        engine=Path(os.environ['BANJO_LIVE_ENGINE']);reports=[]
        for surface in ('smooth','columns'):
            ground=grounds.read_ground(engine,4,surface=surface)
            # Same geometry and conditions for glass/oak/iron; material changes
            # only native material inputs. Concrete retained as starter material.
            for material in ('glass','oak','iron','concrete'):
                machine,overrides=workshop_components.design_from_spec({'kind':'electric-furnace','parameters':{}})
                artifact=rigid_assembly.compile_design(machine,overrides,root='furnace')
                flat=rigid_assembly.placed(artifact,[10.,0.,3.],0.,0.)
                pads,lift=builder._foundation_for(ground,flat,'furnace')
                for pad in pads:
                    pad['material']=engine_materials.scene_name(material)
                    for part in pad['parts']:part['material']=engine_materials.scene_name(material)
                spec={'algorithm':'lattice','cell_m':.05,
                    'terrain':{'generate':{'kind':'valley','seed':4},'surface':surface},
                    'bodies':[{'name':'marker','shape':'box','material':'concrete','anchored':True,
                               'size_mm':[50,50,50],'center_mm':[-15000,-3000,-12000]}],
                    'precise_rigid_bodies':pads+rigid_assembly.scene_bodies(rigid_assembly.placed(artifact,[10.,lift,3.],0.,0.))}
                checked=fracture_lab.validate(spec)
                with tempfile.TemporaryDirectory() as temp:
                    session=live_session.Session(engine,checked,Path(temp))
                    try:
                        initial={b['name']:b for b in session.send(op='poses')['bodies']}
                        for _ in range(20):session.send(op='step',dt=1/240,n=240)
                        final=session.send(op='poses');have={b['name']:b for b in final['bodies']}
                        foundation=have['furnace foundation'];furnace=have['furnace']
                        self.assertFalse(foundation['anchored']);self.assertFalse(furnace['anchored'])
                        drift=math.hypot(*(furnace['position_m'][a]-initial['furnace']['position_m'][a] for a in (0,2)))
                        self.assertLess(drift,.15);self.assertLess(tilt(furnace),5.)
                        self.assertLess(tilt(foundation),5.)
                        volume=sum(math.prod(p['dimensions_m']) for p in pads[0]['parts'])
                        expected=volume*engine_materials.density(material)
                        self.assertAlmostEqual(expected,foundation['mass_kg'],delta=expected*2e-7)
                        saved=session.send(op='snapshot')['snapshot']
                    finally:session.close()
                    restored=live_session.Session(engine,checked,Path(temp)/'restored',snapshot=saved)
                    try:
                        self.assertEqual(final['bodies'],restored.send(op='poses')['bodies'])
                    finally:restored.close()
                reports.append({'surface':surface,'material':material,'dt_s':1/240,'elapsed_s':20,
                    'mass_kg':foundation['mass_kg'],'mass_residual_kg':foundation['mass_kg']-expected,
                    'drift_m':drift,'foundation_tilt_deg':tilt(foundation),'machine_tilt_deg':tilt(furnace),
                    'reopened_exact':True,'limits':'Free rigid contact; no soil bearing, joint failure or full work/reaction closure'})
        folder=ROOT/'build/construction';folder.mkdir(parents=True,exist_ok=True)
        (folder/'foundations.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
        print(json.dumps(reports))


if __name__=='__main__':unittest.main()
