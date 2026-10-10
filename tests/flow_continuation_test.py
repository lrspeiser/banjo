import copy
import ctypes
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import flowing_matter as flow
LIBRARY=Path(sys.argv.pop()).resolve()

class ContinuationTests(unittest.TestCase):
    def test_reflected_wave_above_initial_authoring_height_continues(self):
        declaration={'nx':12,'nz':8,'initial':[[2,2,0]]*96,'duration_s':.05,'frames':4}
        first=flow.run(declaration,LIBRARY)
        self.assertGreater(max(c[0] for c in first['frames'][-1]['cells']),2)
        second=flow.run({'duration_s':.05,'frames':4},LIBRARY,first['checkpoint'])
        full=flow.run({**declaration,'duration_s':.1,'frames':7},LIBRARY)
        self.assertEqual(second['frames'],full['frames'][3:])
        self.assertEqual(second['instance']['matter_ids'],first['instance']['matter_ids'])
    def test_same_native_trajectory_and_persistent_accounts(self):
        full=flow.run({'duration_s':2,'frames':121},LIBRARY)
        first=flow.run({'duration_s':1,'frames':61},LIBRARY)
        checkpoint=copy.deepcopy(first['checkpoint'])
        second=flow.run({'duration_s':1,'frames':61},LIBRARY,checkpoint=checkpoint)
        self.assertEqual(first['instance']['id'],second['instance']['id'])
        self.assertEqual(first['instance']['matter_ids'],second['instance']['matter_ids'])
        self.assertEqual(first['instance']['control_volume_ids'],second['instance']['control_volume_ids'])
        self.assertEqual(checkpoint,first['checkpoint'])
        self.assertEqual(second['frames'][0],first['frames'][-1])
        self.assertEqual(first['frames'],full['frames'][:61])
        self.assertEqual(second['frames'],full['frames'][60:])
        self.assertEqual(second['instance']['accepted_time_s'],full['instance']['accepted_time_s'])
        self.assertEqual(flow._open_checkpoint(second['checkpoint'])['continuation'],flow._open_checkpoint(full['checkpoint'])['continuation'])
        print('Exact native continuation frames/account parity: 1+1 physical s vs 2 s; persistent original balances retained')
    def test_restore_refusal_keeps_caller_checkpoint(self):
        first=flow.run({'duration_s':.1,'frames':7},LIBRARY);saved=copy.deepcopy(first['checkpoint'])
        for field in ['source_sha256','native_sha256']:
            decoded=flow._open_checkpoint(saved);decoded[field]='bad';bad=flow._seal_checkpoint(decoded)
            with self.assertRaises(ValueError):flow.run({},LIBRARY,bad)
        decoded=flow._open_checkpoint(saved);decoded['continuation'][0]+=1
        with self.assertRaises(ValueError):flow.run({},LIBRARY,flow._seal_checkpoint(decoded))
        decoded=flow._open_checkpoint(saved);decoded['continuation'][6]+=1
        with self.assertRaises(ValueError):flow.run({},LIBRARY,flow._seal_checkpoint(decoded))
        decoded=flow._open_checkpoint(saved);decoded['continuation'][5]+=1
        with self.assertRaises(ValueError):flow.run({},LIBRARY,flow._seal_checkpoint(decoded))
        decoded=flow._open_checkpoint(saved);decoded['instance']['matter_ids']=['other']
        with self.assertRaises(ValueError):flow.run({},LIBRARY,flow._seal_checkpoint(decoded))
        with self.assertRaises(ValueError):flow.run({'density_kg_m3':700},LIBRARY,saved)
        self.assertEqual(saved,first['checkpoint'])
    def test_native_restore_and_work_failures_leave_every_output_unchanged(self):
        native=ctypes.CDLL(str(LIBRARY));ptr=ctypes.POINTER(ctypes.c_double)
        native.banjo_flow_continue.argtypes=[ptr]*6;native.banjo_flow_continue.restype=ctypes.c_int
        source=flow.run({'nx':2,'nz':2,'duration_s':.1,'frames':2},LIBRARY);decoded=flow._open_checkpoint(source['checkpoint'])
        config=(ctypes.c_double*7)(2,2,.1,1000,9.81,.1,2);state=(ctypes.c_double*12)(*[x for c in decoded['cells'] for x in c]);continuation=(ctypes.c_double*12)(*decoded['continuation']);continuation[6]+=1
        output=(ctypes.c_double*24)(*([1234]*24));accounts=(ctypes.c_double*36)(*([5678]*36));continued=(ctypes.c_double*12)(*([9012]*12))
        self.assertEqual(native.banjo_flow_continue(config,state,continuation,output,accounts,continued),-1)
        self.assertEqual(list(output),[1234]*24);self.assertEqual(list(accounts),[5678]*36);self.assertEqual(list(continued),[9012]*12)
        # Repeated output intervals share ONE request work cap, not one per frame.
        config=(ctypes.c_double*7)(128,32,.01,1000,9.81,5,61);state=(ctypes.c_double*(4096*3))(*([.2,.2,0]*4096))
        output=(ctypes.c_double*(61*4096*3))(*([1234]*(61*4096*3)));accounts=(ctypes.c_double*(61*18))(*([5678]*(61*18)))
        self.assertEqual(native.banjo_flow_continue(config,state,None,output,accounts,continued),-4)
        self.assertEqual(list(output),[1234]*(61*4096*3));self.assertEqual(list(accounts),[5678]*(61*18));self.assertEqual(list(continued),[9012]*12)

if __name__=='__main__':unittest.main()
