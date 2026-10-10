import ctypes
import json
from pathlib import Path
import sys
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import flowing_matter as flow
LIBRARY=Path(sys.argv.pop()).resolve()

class FlowApiTests(unittest.TestCase):
    def test_actual_states_and_accounts(self):
        result=flow.run({},LIBRARY)
        self.assertTrue(result['ok']);self.assertEqual(len(result['frames']),121)
        self.assertEqual(len(result['instance']['matter_ids']),1)
        self.assertEqual(len(result['instance']['control_volume_ids']),1152)
        first,last=result['frames'][0],result['frames'][-1]
        self.assertNotEqual(first['cells'],last['cells'])
        self.assertAlmostEqual(last['account']['time_s'],2)
        for name in ['mass_residual_kg','momentum_x_residual_n_s','momentum_z_residual_n_s','angular_y_residual_n_m_s','energy_residual_j']:
            self.assertLess(abs(last['account'][name]),1e-8)
        self.assertLess(last['account']['numerical_energy_j'],0)
        print('native flow measured',result['measured'],'native_sha256',result['native_sha256'],'source_sha256',result['source_sha256'])
    def test_editable_authoring_and_no_name_laws(self):
        initial=[[.1,0,0],[.2,0,0],[0,0,0],[.05,0,0]]
        a=flow.run({'nx':2,'nz':2,'initial':initial,'duration_s':.01,'frames':2},LIBRARY)
        b=flow.run({'nx':2,'nz':2,'initial':initial,'density_kg_m3':700,'duration_s':.01,'frames':2},LIBRARY)
        self.assertEqual(a['frames'][-1]['cells'],b['frames'][-1]['cells'])
        self.assertNotEqual(a['definition']['id'],b['definition']['id'])
        self.assertNotEqual(a['instance']['id'],b['instance']['id'])
        self.assertEqual(a['frames'][0]['cells'],initial)
        for declaration in [{'material':'oak'},{'nx':True},{'duration_s':float('nan')},{'nx':128,'nz':128},{'nx':128,'nz':32,'frames':241},{'initial':[[0,1,0]]}]:
            with self.assertRaises(ValueError):flow.run(declaration,LIBRARY)
        with self.assertRaises(ValueError):flow.run({},None)
    def test_native_atomic_refusal(self):
        native=ctypes.CDLL(str(LIBRARY));ptr=ctypes.POINTER(ctypes.c_double)
        native.banjo_flow_run.argtypes=[ptr,ptr,ptr,ptr];native.banjo_flow_run.restype=ctypes.c_int
        config=(ctypes.c_double*7)(2,2,.1,1000,9.81,1,2)
        initial=(ctypes.c_double*12)(-1,0,0,0,0,0,0,0,0,0,0,0)
        output=(ctypes.c_double*24)(*([1234]*24));accounts=(ctypes.c_double*36)(*([5678]*36))
        self.assertEqual(native.banjo_flow_run(config,initial,output,accounts),-1)
        self.assertEqual(list(output),[1234]*24);self.assertEqual(list(accounts),[5678]*36)
        config=(ctypes.c_double*7)(128,32,.01,1000,9.81,5,2)
        initial=(ctypes.c_double*(4096*3))(*([.2,.2,0]*4096))
        output=(ctypes.c_double*(4096*3*2))(*([1234]*(4096*3*2)))
        self.assertEqual(native.banjo_flow_run(config,initial,output,accounts),-4)
        self.assertEqual(list(output),[1234]*(4096*3*2));self.assertEqual(list(accounts),[5678]*36)

if __name__=='__main__':unittest.main()
