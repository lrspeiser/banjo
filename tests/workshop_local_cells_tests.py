"""Thin source fidelity, bounded compilation and real native quote admission."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import math
import os
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'playground'),str(ROOT/'mcp')]
from mcp import workshop_components as components, workshop_local_cells as local, engine_materials
import playable_recipes
import workshop_recipe
import workshop_install


class Geometry(unittest.TestCase):
    def test_bounded_working_motion_is_a_hand_target_not_a_yield(self):
        from mcp import interaction_profiles as profiles, tool_gestures
        source=playable_recipes.metal_shovel_recipe()
        design,_=components.design_from_spec(source)
        use=profiles.tool_use({'use':design.parameters['ground_tool']['use']})
        path=tool_gestures.contact_path([0,1,0],use,[-1,1,0],[0,0,0])
        self.assertAlmostEqual(.1,path[1][0]-path[2][0])
        for drag in (.001,.2,True,float('nan')):
            bad=deepcopy(source);bad['parameters']['ground_tool']['use']['contact_drag_m']=drag
            with self.assertRaises(ValueError):components.design_from_spec(bad)
    def compile(self,source=None):
        design,overrides=components.design_from_spec(source or playable_recipes.metal_shovel_recipe())
        return local.compile_design(design,overrides)

    def test_actual_blade_handle_mass_and_cell_budget(self):
        a=self.compile()
        self.assertEqual(28,a['cells'])
        self.assertAlmostEqual(2.30796,a['mass_kg'],places=12)
        self.assertAlmostEqual(1.458,a['material_mass_kg']['aluminum'],places=12)
        self.assertAlmostEqual(.84996,a['material_mass_kg']['iron'],places=12)
        blade=next(b for b in a['bodies'] if b['_components']==['blade'])
        self.assertTrue(all(c['dimensions_m'][1]==.003 for c in blade['parts']))
        self.assertEqual(1,len(a['joints']))
        self.assertAlmostEqual(.003*.03,a['joints'][0]['section_u_m']*a['joints'][0]['section_v_m'])

    def test_translation_changes_placement_without_rounding_matter(self):
        before=self.compile()
        for offset in (.0013,.0231,.049):
            source=playable_recipes.metal_shovel_recipe()
            for p in source['component_overrides']['@construction']['added']:
                p['center_m']=[v+offset for v in p['center_m']]
            after=self.compile(source)
            self.assertAlmostEqual(before['mass_kg'],after['mass_kg'],places=12)
            self.assertEqual(before['cells'],after['cells'])
            for a,b in zip(before['bodies'],after['bodies']):
                for c,d in zip(a['parts'],b['parts']):
                    self.assertEqual(c['dimensions_m'],d['dimensions_m'])
                    for x,y in zip(c['center_local_m'],d['center_local_m']):self.assertAlmostEqual(y-x,offset,places=12)

    def test_missing_gap_overlap_rotated_parts_and_excess_detail_are_refused(self):
        for kind in ('gap','overlap','rotate','budget','joint'):
            source=playable_recipes.metal_shovel_recipe();over=source['component_overrides']
            blade=next(p for p in over['@construction']['added'] if p['name']=='blade')
            if kind=='gap':blade['center_m'][0]+=.001
            if kind=='overlap':blade['center_m'][0]-=.001
            if kind=='rotate':blade['rotation_deg'][1]=15
            if kind=='budget':over[local.KEY]['cell_size_m']=.002
            if kind=='joint':over['@construction']['joints']=[]
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.compile(source)

    def test_invalid_declared_resolution_is_refused(self):
        for value in (0,-1,True,float('nan'),float('inf'),.001,.251):
            with self.assertRaises(ValueError):local.checked({'cell_size_m':value})

    def test_same_source_ready_in_lab_and_world_without_redraw(self):
        source=playable_recipes.metal_shovel_recipe();design,over=components.design_from_spec(source)
        out=workshop_recipe.assess(design,over,world_cell_m=.05)
        self.assertTrue(out['ready_as_drawn'],out)
        self.assertEqual([],out['world']['changes'])
        legacy=deepcopy(source);legacy['component_overrides'].pop(local.KEY)
        d,o=components.design_from_spec(legacy)
        self.assertFalse(workshop_recipe.assess(d,o,world_cell_m=.05)['ready_as_drawn'])

    def test_duplicate_fixings_cannot_multiply_strength(self):
        source=playable_recipes.metal_shovel_recipe()
        joints=source['component_overrides']['@construction']['joints']
        duplicate=deepcopy(joints[0]);duplicate['id']='joint-duplicate';joints.append(duplicate)
        with self.assertRaises(ValueError):self.compile(source)

    def test_saved_source_and_visual_plan_keep_the_actual_thin_cells(self):
        import workshop_api, workshop_store
        source=playable_recipes.metal_shovel_recipe();design,over=components.design_from_spec(source)
        with tempfile.TemporaryDirectory() as folder:
            record=workshop_store.save(Path(folder),design,label='My shovel')
            self.assertEqual('local-material-cells',record['mechanical_model'])
            self.assertFalse(record['measured']['native_qualification'])
            _,loaded=workshop_store.load(Path(folder),design.design_id)
            self.assertEqual(over,loaded.lineage['component_overrides'])
            self.assertAlmostEqual(2.30796,record['measured']['mass_kg'],places=12)
            app=SimpleNamespace(workshop_store=Path(folder))
            plan=workshop_api.plan(app,{**source,'visual':{'cell_size_m':.05}})
        self.assertEqual([],plan['objects'])
        self.assertEqual('clipped-box-cells-v1',plan['matter']['cell_geometry'])
        blade=[c for c in plan['matter']['cells'] if c['component']=='blade']
        self.assertEqual(16,len(blade))
        self.assertTrue(all(c['dimensions_m'][1]==.003 for c in blade))
        self.assertFalse(plan['buildability']['installation_ready'])


ENGINE=Path(os.environ['BANJO_LIVE_ENGINE']).resolve() if os.environ.get('BANJO_LIVE_ENGINE') else None
@unittest.skipUnless(ENGINE and ENGINE.is_file(),'BANJO_LIVE_ENGINE required')
class Native(unittest.TestCase):
    def test_same_thin_geometry_native_bill_and_tool_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            app=SimpleNamespace(engine_path=ENGINE,runs_path=Path(folder),world_id=None)
            for material in ('glass','oak','iron','aluminum'):
                source=playable_recipes.metal_shovel_recipe()
                for p in source['component_overrides']['@construction']['added']:p['material']=material
                design,overrides=components.design_from_spec(source)
                artifact,measured=workshop_install.measure_local_for_fabrication(app,design,overrides,.05)
                expected=(.6*.03*.03+.2*.003*.18)*engine_materials.density(material)
                self.assertAlmostEqual(expected,measured['mass_kg'],places=10)
                self.assertLessEqual(abs(measured['mechanical_mass_residual_kg']),2e-7*expected)
                self.assertLessEqual(abs(measured['material_mass_residual_kg']),1e-10)
                print('native local cells',material,measured)

if __name__=='__main__':unittest.main()
