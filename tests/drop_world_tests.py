"""Registered real-native world integration gates, separate from physics qualification."""
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

BINARY=Path(sys.argv.pop(1)).resolve()
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('drop',ROOT/'scripts/drop-world.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
EVIDENCE=[]

class World:
    def __init__(self,**values):
        self.child=subprocess.Popen([str(BINARY),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        self.initial=self.send(dict(op='create',sheet='glass',ball='iron',mass_kg=1,height_m=10,offset_m=0,mode='rigid',speed_m_s=0,**values))
    def send(self,value):
        self.child.stdin.write(json.dumps(value)+'\n');self.child.stdin.flush()
        result=json.loads(self.child.stdout.readline());assert result['ok'],result.get('error')
        self.receipt=result;self.state=result['state'];return self.state
    def advance(self,steps):
        for _ in range(steps//4):self.send(dict(op='advance',steps=4))
        return self.state
    def close(self):
        self.child.terminate();self.child.wait(timeout=3);self.child.stdin.close();self.child.stdout.close()

def obj(state,id):return next(o for o in state['report']['objects'] if o['id']==id)

class DropTests(unittest.TestCase):
    def test_native_freefall_contact_and_mass(self):
        w=World();start=time.perf_counter()
        try:
            initial=obj(w.initial,2);self.assertEqual(w.initial['report']['cells'],4)
            self.assertAlmostEqual(initial['mass_kg'],1,places=10)
            s=w.advance(24);t=s['report']['elapsed_s'];b=obj(s,2)
            self.assertAlmostEqual(b['velocity_m_s'][1],-9.81*t,delta=1e-4)
            self.assertAlmostEqual(b['position_m'][1],initial['position_m'][1]-.5*9.81*t*t,delta=.003)
            lowest=b['position_m'][1]
            for _ in range(90):
                s=w.advance(4);lowest=min(lowest,obj(s,2)['position_m'][1])
            self.assertLess(lowest,.8,'Ball must reach the physical sheet')
            self.assertGreater(obj(s,2)['velocity_m_s'][1],-9.81*s['report']['elapsed_s']+1,
                               'Actual contact must change the free-fall velocity')
            self.assertGreater(s['report']['contact_budget']['peak_manifolds'],0)
            self.assertEqual(s['report']['broken_links'],0)
            self.assertAlmostEqual(obj(s,2)['mass_kg'],1,places=10)
            self.assertEqual(len(s['instances']),4)
            self.assertLess(time.perf_counter()-start,10,'Native 10 m baseline must stay usable')
            EVIDENCE.append(dict(case='10m rigid native drop',wall_s=time.perf_counter()-start,report=s['report']))
        finally:w.close()

    def test_deformable_material_comparison_and_ball(self):
        for sheet,ball in [('glass','iron'),('oak','iron'),('iron','iron'),('iron','glass')]:
            # Same declared experiment except chosen material; ball volume
            # follows density to preserve the requested mass.
            w=World.__new__(World)
            w.child=subprocess.Popen([str(BINARY),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
            try:
                initial=w.send(dict(op='create',sheet=sheet,ball=ball,mass_kg=1,height_m=0,offset_m=0,mode='deformable',speed_m_s=14))
                self.assertEqual(obj(initial,1)['cells'],72);self.assertEqual(obj(initial,2)['cells'],32)
                self.assertAlmostEqual(obj(initial,2)['mass_kg'],1,places=10)
                target_cells=[i for i in initial['instances'] if i['object_id']==1]
                ball_cells=[i for i in initial['instances'] if i['object_id']==2]
                for a in target_cells:
                    for b in ball_cells:
                        self.assertGreaterEqual(math.dist(a['position_m'],b['position_m'])-a['radius_m']-b['radius_m'],-1e-12,
                                                'Impact must begin without hidden source/target interpenetration')
                start=time.perf_counter();s=w.advance(4)
                self.assertFalse(s['report']['network_substepping']['limited_by_budget'])
                self.assertTrue(s['report']['state_valid'])
                self.assertEqual(len(s['instances']),106,'All physical cells and posts remain present')
                self.assertAlmostEqual(s['report']['elapsed_s'],4/4800,places=12)
                self.assertEqual(len(w.receipt['frames']),4)
                self.assertEqual(w.receipt['frames'][-1]['instances'],s['instances'])
                self.assertEqual([f['time_s'] for f in w.receipt['frames']],sorted(f['time_s'] for f in w.receipt['frames']))
                for id in range(1,5):self.assertEqual(obj(s,id)['mass_kg'],obj(initial,id)['mass_kg'])
                self.assertFalse(s['qualification']['release_ready'])
                if sheet=='glass':self.assertGreater(obj(s,1)['broken_links'],0)
                if ball=='glass':self.assertGreater(obj(s,2)['broken_links'],0,'The ball must participate in material response')
                EVIDENCE.append(dict(case=sheet+'/'+ball,wall_s=time.perf_counter()-start,report=s['report']))
                if ball=='iron':
                    w.send(dict(op='create',sheet=sheet,ball=ball,mass_kg=1,height_m=0,offset_m=0,mode='deformable',speed_m_s=0))
                    control=w.advance(4)
                    self.assertTrue(control['report']['state_valid'])
                    self.assertEqual(control['report']['broken_links'],0,'Gravity-only control must not fabricate fracture')
                    self.assertLess(control['report']['plastic_work_j'],1e-6)
                    EVIDENCE.append(dict(case=sheet+'/iron gravity-only control',report=control['report']))
            finally:w.close()

    def test_catalog_gateway_receipts_and_invalid_intentions(self):
        with tempfile.TemporaryDirectory() as folder:
            manager=module.DropManager(BINARY,folder)
            valid=dict(op='create',sheet='glass',ball='iron',mass_kg=1,height_m=10,offset_m=0,mode='rigid',speed_m_s=0)
            try:
                for update in ({'mass_kg':True},{'height_m':11},{'mode':'fake'},{'ball':'unobtainium'},{'arbitrary':1}):
                    with self.assertRaises(ValueError):manager.request(dict(valid,**update))
                for name in module.shared.MATERIALS:
                    r=manager.request(dict(valid,sheet=name,ball=name));self.assertTrue(r['ok'],r)
                    key=r['session'];after=manager.request(dict(op='advance',session=key));self.assertTrue(after['ok'])
                    lines=[json.loads(line) for line in (Path(folder)/(key+'.jsonl')).read_text().splitlines()]
                    self.assertEqual(lines[-1]['receipt'],after);self.assertEqual(lines[0]['request']['sheet'],name)
                    self.assertEqual(len(after['native_sha256']),64)
                    manager.request(dict(op='close',session=key))
                    with self.assertRaises(ValueError):manager.request(dict(op='advance',session=key))
            finally:manager.close()

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(DropTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    path=ROOT/'build/drop-world-results.json';path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({'integration_passed':result.wasSuccessful(),'release_ready':False,'experiments':EVIDENCE},indent=2))
    sys.exit(0 if result.wasSuccessful() else 1)
