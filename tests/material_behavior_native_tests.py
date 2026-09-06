"""Held-out native constitutive paths; no material-name dispatch."""
import json, random, subprocess, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'examples/authoring'))
from material_behavior import MaterialBehavior
from material_behavior_client import evaluate_material_path
EXE=ROOT/'build/win-joint-double/Release/banjo_material_behavior_probe.exe'

class NativeMaterialTests(unittest.TestCase):
    def run_path(self,m,strains):
        return evaluate_material_path(EXE,m,strains)["samples"]

    def test_held_out_isotropic_parameters_and_name_invariance(self):
        rng=random.Random(603)
        for i in range(12):
            e=rng.uniform(1e6,200e9);nu=rng.uniform(.05,.4);strain=rng.uniform(1e-6,1e-4)
            params=dict(young_modulus_pa=e,poisson_ratio=nu,maximum_total_strain_norm=.01)
            m=MaterialBehavior(f'generated-{i}',f'Unseen {i}',rng.uniform(500,9000),'isotropic_elastic',params)
            path=[[0]*6,[strain,0,0,0,0,0],[0]*6]
            response=self.run_path(m,path)
            expected=e*(1-nu)/((1+nu)*(1-2*nu))*strain
            self.assertAlmostEqual(response[1]['stress_pa'][0]/expected,1,places=12)
            self.assertEqual(response[-1]['stress_pa'],[0]*6)
            renamed=MaterialBehavior('glass','arbitrary rubber name',m.density_kg_m3,m.mechanical_law,params)
            self.assertEqual(response,self.run_path(renamed,path))

    def test_known_and_new_plastic_parameters_retain_history(self):
        for name,e,y in [('iron',200e9,250e6),('unseen-alloy',123e9,120e6)]:
            m=MaterialBehavior(name,name,7800,'j2_plastic',dict(young_modulus_pa=e,poisson_ratio=.3,initial_yield_stress_pa=y,isotropic_hardening_modulus_pa=1e9,maximum_total_strain_norm=.05))
            result=self.run_path(m,[[0]*6,[.008,0,0,0,0,0],[.004,0,0,0,0,0]])
            self.assertTrue(result[1]['yielded'])
            self.assertGreater(result[-1]['plastic_dissipation_j_m3'],0)
            self.assertGreater(result[-1]['equivalent_plastic_strain'],0)

    def test_glass_oak_iron_reference_laws(self):
        for name,e in [('glass',70e9),('iron',200e9)]:
            m=MaterialBehavior(name,name,2500,'isotropic_elastic',dict(young_modulus_pa=e,poisson_ratio=.2,maximum_total_strain_norm=.01))
            self.assertGreater(self.run_path(m,[[1e-5,0,0,0,0,0]])[0]['stress_pa'][0],0)
        m=MaterialBehavior('oak','oak',700,'orthotropic_elastic',dict(young_modulus_pa=[11e9,1e9,.7e9],poisson_xy_yz_zx=[.3,.2,.02],shear_xy_yz_zx_pa=[.6e9,.3e9,.5e9],maximum_total_strain_norm=.01))
        self.assertGreater(self.run_path(m,[[1e-5,0,0,0,0,0]])[0]['stored_free_energy_j_m3'],0)

    def test_native_rejects_unknown_capability_and_duplicate_json(self):
        for raw in ['{"material":{},"material":{},"strains":[]}',json.dumps({'material':{},'strains':[]})]:
            p=subprocess.run([str(EXE)],input=raw,text=True,capture_output=True)
            self.assertEqual(p.returncode,1)
            self.assertEqual(json.loads(p.stdout)['status'],'rejected')

if __name__=='__main__':unittest.main()
