"""Native geometry/mass/contact regressions; never a material-strength verdict."""
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'playground'),str(ROOT/'tests')]
from workshop_rigid_tests import design
from mcp import workshop_rigid as rigid, engine_materials
import workshop_bench, workshop_rigid_trial
ENGINE=Path(os.environ.get('BANJO_PLATFORM_ENGINE','build/ci/banjo_platform_cli')).resolve()
REQUIRED=os.environ.get('BANJO_RIGID_TESTS')=='required'


class NativePreciseRigid(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ENGINE.is_file():
            if REQUIRED:raise AssertionError('required precise-rigid native engine was not built')
            raise unittest.SkipTest('BANJO_PLATFORM_ENGINE is required')

    def invoke(self,package,steps=240,ok=True):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'package.json';source.write_text(json.dumps(package,allow_nan=False))
            run=subprocess.run([str(ENGINE),'--trace',str(source),str(steps)],capture_output=True,text=True,timeout=25)
        if ok:self.assertEqual(0,run.returncode,run.stdout+run.stderr)
        else:self.assertNotEqual(0,run.returncode,run.stdout)
        return json.loads(run.stdout)

    def test_thin_table_native_geometry_mass_motion_all_materials(self):
        for material in ('glass','oak','iron'):
            with self.subTest(material=material):
                # No live session or room exists on this app: the bench is isolated.
                result=workshop_bench.run(SimpleNamespace(platform_engine_path=ENGINE),design(material),
                    {'test':'rigid_motion','config':{'duration_s':1,'drop_height_m':.2}})
                measured=result['measured'];self.assertEqual('measured',result['status'])
                self.assertNotIn('passed',result);self.assertFalse(result['strength_certified'])
                self.assertTrue(result['native_geometry_verified']);self.assertEqual(5,measured['collision_boxes'])
                self.assertEqual(0,measured['stored_cells']);self.assertGreater(measured['displacement_m'],.15)
                self.assertLess(abs(measured['centre_of_mass_delta_m'][1]+.2),.01)
                trace=result['playback'];self.assertEqual('verified-precise-rigid-shapes',trace['geometry_basis'])
                self.assertFalse(trace['sampling']['interpolated'])
                for frame in trace['frames']:
                    self.assertEqual(5,len(frame['bodies']))
                    top=next(p for p in frame['bodies'] if p['name']=='top')
                    self.assertEqual([1.2,.005,.7],top['dimensions_m'])
                print('precise-rigid',material,json.dumps(measured,sort_keys=True))

    def test_free_flight_mass_momentum_energy_and_geometry_not_cell_dependent(self):
        for material in ('glass','oak','iron'):
            with self.subTest(material=material):
                a=rigid.compile_rigid(design(material));p=rigid.package(a,gravity_m_s2=0,horizontal_speed_m_s=.5)
                p['ground']=None
                result=self.invoke(p)
                workshop_rigid_trial._verify(a,p,result)
                actual=result['objects'][0]
                self.assertAlmostEqual(.5,actual['position_m'][0]-p['objects'][0]['position_m'][0],delta=2e-6)
                self.assertAlmostEqual(.5,actual['velocity_m_s'][0],delta=1e-6)
                self.assertAlmostEqual(.125*a['mass_kg'],result['mechanical_energy_j'],delta=1e-5*a['mass_kg'])
                residual=result['mechanical_energy_j']-result['initial_energy_j']
                self.assertAlmostEqual(0,residual,delta=1e-6*a['mass_kg'])
                # Fixed topology: all pairwise separations remain the actual source distances.
                initial,last=(result['trace']['frames'][i]['bodies'] for i in (0,-1))
                for i in range(1,len(initial)):
                    distance=lambda rows: math.dist(rows[0]['position_m'],rows[i]['position_m'])
                    self.assertAlmostEqual(distance(initial),distance(last),delta=1e-7)
                print('free-flight',material,'energy_residual_j',residual)

    def test_native_rotational_energy_uses_the_actual_thin_compound_inertia(self):
        for material in ('glass','oak','iron'):
            with self.subTest(material=material):
                a=rigid.compile_rigid(design(material));p=rigid.package(a,gravity_m_s2=0)
                p['ground']=None;p['objects'][0]['spin_rad_s']=[0,0,1.5]
                result=self.invoke(p)
                expected=.5*a['inertia_kg_m2'][2][2]*1.5**2
                self.assertAlmostEqual(expected,result['initial_energy_j'],delta=expected*5e-6)
                self.assertAlmostEqual(expected,result['mechanical_energy_j'],delta=expected*1e-4)
                # Jolt's velocity/orientation state is float32 even in the
                # double-position build. Use the same 1e-4 relative bound as
                # rotational energy, rather than claim exact angular constancy.
                self.assertAlmostEqual(1.5,result['objects'][0]['spin_rad_s'][2],delta=1.5e-4)
                print('free-spin',material,'relative_energy_drift',
                      (result['mechanical_energy_j']-result['initial_energy_j'])/expected,
                      'spin_drift_rad_s',result['objects'][0]['spin_rad_s'][2]-1.5)

    def test_hollow_leg_space_is_not_replaced_by_one_bounding_box(self):
        a=rigid.compile_rigid(design());p=rigid.package(a,drop_height_m=0,gravity_m_s2=0)
        p['ground']=None
        p['objects'].append({'id':2,'shape':'sphere','material':'iron','radius_m':.02,
            'position_m':[0,.1,0],'orientation_wxyz':[1,0,0,0],'velocity_m_s':[0,0,0],'spin_rad_s':[0,0,0]})
        result=self.invoke(p,24)
        self.assertTrue(result['state_valid'])
        self.assertEqual([0,.1,0],result['objects'][1]['position_m'])

    def test_ball_contacts_the_five_millimeter_top_not_an_erased_surface(self):
        p=rigid.package(rigid.compile_rigid(design()),drop_height_m=0)
        p['objects'].append({'id':2,'shape':'sphere','material':'iron','radius_m':.02,
            'position_m':[0,.96,0],'orientation_wxyz':[1,0,0,0],
            'velocity_m_s':[0,0,0],'spin_rad_s':[0,0,0]})
        result=self.invoke(p)
        heights=[next(b for b in f['bodies'] if b['object_id']==2)['position_m'][1]
                 for f in result['trace']['frames']]
        self.assertGreaterEqual(min(heights),.7799)
        self.assertAlmostEqual(.78,result['objects'][1]['position_m'][1],delta=1e-4)

    def test_native_overlap_and_disconnected_compounds_are_refused(self):
        original=rigid.package(rigid.compile_rigid(design()))
        for centers in (((0,0,0),(0,0,0)),((-.15,0,0),(.15,0,0)),((-.05,-.05,0),(.05,.05,0))):
            p=deepcopy(original)
            p['objects'][0]['parts']=[{'dimensions_m':[.1,.1,.1],'center_local_m':list(c)} for c in centers]
            result=self.invoke(p,1,ok=False)
            self.assertTrue(result.get('error') or result.get('errors'),result)

    def test_old_or_fracture_backend_cannot_accept_precise_rigid(self):
        original=rigid.package(rigid.compile_rigid(design()))
        for backend,capabilities in (('rigid-v1',['gravity']),('compiled-v1',['precise-rigid-compound']),('reference-v1',['precise-rigid-compound'])):
            p=deepcopy(original);p.update(backend=backend,required_capabilities=capabilities)
            self.invoke(p,1,ok=False)

    def test_native_shape_mutation_or_missing_proof_cannot_pass_python_verifier(self):
        a=rigid.compile_rigid(design());p=rigid.package(a);actual=self.invoke(p,24)
        for mutate in (lambda r:r['trace']['frames'][0]['bodies'][0]['dimensions_m'].__setitem__(1,.04),
                       lambda r:r['precise_rigid_bodies'][0].__setitem__('stored_cells',20),
                       lambda r:r['precise_rigid_bodies'][0].__setitem__('native_mass_kg',1),
                       lambda r:r['trace']['frames'][0]['bodies'].pop()):
            changed=deepcopy(actual);mutate(changed)
            with self.assertRaises(ValueError):workshop_rigid_trial._verify(a,p,changed)

    def test_one_millimeter_explicit_box_and_unknown_fields(self):
        p=rigid.package(rigid.compile_rigid(design()),gravity_m_s2=0)
        p['ground']=None;p['required_capabilities'].append('thin-rigid-box')
        p['objects'][0].pop('parts');p['objects'][0].update(shape='box',dimensions_m=[.001,.1,.1])
        result=self.invoke(p,24);self.assertEqual([.001,.1,.1],result['trace']['frames'][0]['bodies'][0]['dimensions_m'])
        p['required_capabilities'].remove('thin-rigid-box');self.invoke(p,1,ok=False)
        p=rigid.package(rigid.compile_rigid(design()));p['objects'][0]['parts'][0]['fracture']=False
        self.invoke(p,1,ok=False)

    def test_bounded_long_trace_declares_thinning_without_interpolation(self):
        result=workshop_rigid_trial.run(SimpleNamespace(platform_engine_path=ENGINE),design(),{'duration_s':5})
        sample=result['playback']['sampling']
        self.assertTrue(sample['thinned']);self.assertFalse(sample['interpolated'])
        self.assertEqual(1200,sample['source_steps']);self.assertLessEqual(sample['recorded_frames'],600)
        self.assertEqual(5,result['playback']['frames'][-1]['t_s'])

    def test_trace_toggle_does_not_change_physical_result(self):
        app=SimpleNamespace(platform_engine_path=ENGINE)
        a=workshop_rigid_trial.run(app,design(),{'duration_s':.5,'record_trace':True})
        b=workshop_rigid_trial.run(app,design(),{'duration_s':.5,'record_trace':False})
        self.assertEqual(a['measured'],b['measured']);self.assertNotIn('playback',b)

if __name__=='__main__':unittest.main()
