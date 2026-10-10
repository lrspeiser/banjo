"""Native-backed admission, lifecycle and persistent failure evidence."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('sheets',Path(__file__).resolve().parents[1]/'scripts/sheet-world.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
BINARY=Path(sys.argv.pop(1)).resolve()

class GatewayTests(unittest.TestCase):
    def test_bounds_receipts_and_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            manager=module.SheetManager(BINARY,directory)
            try:
                for value in ({},{'op':'create','material':'glass','pick':'iron','point_m':[0,0,0],'arbitrary':1},
                              {'op':'create','material':'unknown','pick':'iron','point_m':[0,0,0]},
                              {'op':'create','material':'glass','pick':'iron','point_m':[.02,0,0]}):
                    with self.assertRaises(ValueError):manager.request(value)
                r=manager.request({'op':'create','material':'glass','pick':'iron','point_m':[.0007808484689576858,0,.0004226478800741229]})
                key=r['session'];self.assertTrue(r['ok']);self.assertEqual(len(r['state']['positions']),800)
                after=manager.request({'op':'advance','session':key})
                # The same native contact stage refuses this interval on every
                # platform; MSVC reaches the affine stencil bound first, GCC the
                # manifold search budget. Either is a named physical refusal.
                self.assertFalse(after['ok'])
                self.assertTrue(any(reason in after['error'] for reason in
                                    ('affine','manifold did not converge within its search budget')),after['error'])
                self.assertLess(abs(after['state']['energy_residual_j']),1e-9)
                records=[json.loads(line) for line in (Path(directory)/(key+'.jsonl')).read_text().splitlines()]
                self.assertEqual(records[-1]['receipt'],after)
                self.assertEqual(records[0]['request']['point_m'],[.0007808484689576858,0,.0004226478800741229])
                manager.sessions[key]['sequence']=80
                with self.assertRaises(ValueError):manager.request({'op':'advance','session':key})
                self.assertTrue(manager.request({'op':'close','session':key})['closed'])
                self.assertTrue(manager.request({'op':'close','session':key})['closed'])
                with self.assertRaises(ValueError):manager.request({'op':'advance','session':key})
            finally:manager.close()

    def test_process_budget_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            manager=module.SheetManager(BINARY,directory)
            try:
                for _ in range(8):manager.request({'op':'create','material':'iron','pick':'glass','point_m':[0,0,0]})
                with self.assertRaises(ValueError):manager.request({'op':'create','material':'iron','pick':'glass','point_m':[0,0,0]})
                children=[x['child'] for x in manager.sessions.values()]
                manager.close();self.assertTrue(all(child.poll() is not None for child in children))
                self.assertEqual(manager.sessions,{})
            finally:manager.close()

if __name__=='__main__':unittest.main()
