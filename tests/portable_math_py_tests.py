"""playground/portable_math.py against the engine's own table.

The rows are read from tests/portable_math_tests.cpp, the table
banjo_portable_math_tests holds banjo::pm to: each is the correctly rounded
result, computed to 240 bits with mpmath. Passing it here, on Windows and on
Linux, is the game's Python giving the same bits as the engine's C++ and as
each other (docs/floating-point-model.md, profile banjo-cpu-precise-v2).

    python tests/portable_math_py_tests.py
"""
import math
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'playground'))
import portable_math as pm  # noqa: E402

H = float.fromhex

ROW = re.compile(r'\{"(\w+)", (-?0x[0-9a-fA-F.]+p[-+]\d+), (-?0x[0-9a-fA-F.]+p[-+]\d+), (-?0x[0-9a-fA-F.]+p[-+]\d+)\}')
TWO = {'pow', 'atan2', 'hypot'}
FUNCTIONS = {'exp': pm.exp, 'expm1': pm.expm1, 'log': pm.log, 'log1p': pm.log1p, 'pow': pm.pow, 'sin': pm.sin,
             'cos': pm.cos, 'tan': pm.tan, 'atan': pm.atan, 'atan2': pm.atan2, 'asin': pm.asin, 'acos': pm.acos,
             'cbrt': pm.cbrt, 'hypot': math.hypot}


def same(a, b):
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    return a == b and math.copysign(1.0, a) == math.copysign(1.0, b)


class EngineTable(unittest.TestCase):
    def test_every_row_of_the_engine_table_is_the_same_double(self):
        rows = ROW.findall((ROOT / 'tests' / 'portable_math_tests.cpp').read_text(encoding='utf-8'))
        self.assertGreater(len(rows), 250, 'the engine table was not found')
        wrong = []
        for name, x, y, want in rows:
            args = (float.fromhex(x), float.fromhex(y)) if name in TWO else (float.fromhex(x),)
            got = FUNCTIONS[name](*args)
            if not same(got, float.fromhex(want)):
                wrong.append(f'{name}{tuple(a.hex() for a in args)} = {got.hex()}, correctly rounded {want}')
        self.assertEqual(wrong, [])
        print(f'  {len(rows)} rows of the engine table, each the same double')

    def test_math_hypot_is_already_the_engines(self):
        # CPython computes hypot and dist itself, correctly rounded, so the game
        # keeps them: the table's hypot rows above pass through math.hypot.
        self.assertEqual(math.hypot(3.0, 4.0), 5.0)
        self.assertEqual(math.hypot(1.0, 2.0, 2.0), 3.0)


class PythonSemantics(unittest.TestCase):
    """Where `math` raises, these raise; where it keeps a signed zero, so do they."""

    def test_domain_and_range_errors_are_maths(self):
        for f, x in ((pm.log, 0.0), (pm.log, -1.0), (pm.log1p, -1.0), (pm.asin, 1.5), (pm.acos, -1.5),
                     (pm.sin, math.inf), (pm.cos, -math.inf), (pm.tan, math.inf)):
            with self.assertRaises(ValueError, msg=f'{f.__name__}({x})'):
                f(x)
        with self.assertRaises(OverflowError):
            pm.exp(710.0)
        with self.assertRaises(OverflowError):
            pm.expm1(710.0)
        with self.assertRaises(ValueError):
            pm.pow(-8.0, 1.0 / 3.0)

    def test_special_values(self):
        pi, half_pi = H('0x1.921fb54442d18p+1'), H('0x1.921fb54442d18p+0')
        self.assertTrue(same(pm.sin(-0.0), -0.0) and same(pm.tan(-0.0), -0.0) and same(pm.atan(-0.0), -0.0))
        self.assertTrue(same(pm.cos(0.0), 1.0) and same(pm.exp(0.0), 1.0) and same(pm.expm1(-0.0), -0.0))
        self.assertTrue(same(pm.log1p(-0.0), -0.0) and same(pm.log(1.0), 0.0))
        self.assertTrue(same(pm.atan2(0.0, -1.0), pi) and same(pm.atan2(-0.0, -1.0), -pi))
        self.assertTrue(same(pm.atan2(1.0, 0.0), half_pi) and same(pm.atan(math.inf), half_pi))
        self.assertTrue(same(pm.asin(1.0), half_pi) and same(pm.acos(-1.0), pi) and same(pm.acos(1.0), 0.0))
        self.assertTrue(same(pm.sin(pi), H('0x1.1a62633145c07p-53')) and same(pm.cos(half_pi), H('0x1.1a62633145c07p-54')))
        self.assertTrue(same(pm.pow(2.0, 10.0), 1024.0) and same(pm.pow(-2.0, 3.0), -8.0) and same(pm.pow(4.0, 0.5), 2.0))
        self.assertTrue(same(pm.exp(-746.0), 0.0) and same(pm.expm1(-50.0), -1.0))
        self.assertTrue(same(pm.cbrt(-27.0), -3.0) and same(pm.cbrt(H('0x1p-1074')), H('0x1p-358')))
        self.assertTrue(same(pm.atan2(H('0x3p-1074'), 2.0), H('0x1p-1074')), 'a quotient halfway between denormals rounds below')

    def test_integers_are_taken_as_math_takes_them(self):
        self.assertEqual(pm.sin(1), pm.sin(1.0))
        self.assertEqual(pm.atan2(1, 2), pm.atan2(1.0, 2.0))


if __name__ == '__main__':
    unittest.main(verbosity=2)
