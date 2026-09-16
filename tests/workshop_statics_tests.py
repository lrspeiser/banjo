from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp.workshop import assemble  # noqa: E402
from mcp.workshop_statics import declared_statics, static_load  # noqa: E402


class StaticLoads(unittest.TestCase):
    def test_symmetric_table_shares_centered_load_equally(self):
        design = assemble("table", design_id="table")
        result = static_load(design, load_kg=100, on="top")
        self.assertEqual(4, len(result["supports"]))
        loads = [r["equivalent_load_kg"] for r in result["supports"]]
        self.assertLess(max(loads) - min(loads), 0.002)
        expected = (100 + design.measure()["mass_kg"]) / 4
        self.assertAlmostEqual(expected, loads[0], places=2)
        self.assertLess(result["equilibrium_error_n"], 1e-5)
        self.assertEqual("analytical-estimate", result["evidence"])

    def test_declared_load_uses_the_assemblys_requirement(self):
        table = declared_statics(assemble("table", design_id="t"))[0]
        chair = declared_statics(assemble("chair", design_id="c"))[0]
        bench = declared_statics(assemble("bench", design_id="b"))[0]
        self.assertEqual(100, table["external_load_kg"])
        self.assertEqual(120, chair["external_load_kg"])
        self.assertEqual(240, bench["external_load_kg"])

    def test_wider_splay_changes_support_locations_but_not_fabricates_failure(self):
        straight = static_load(assemble("table", design_id="a"), load_kg=100)
        splayed = static_load(assemble(
            "table", design_id="b", parameters={"leg_style": "splayed", "splay_deg": 12}),
            load_kg=100)
        straight_x = max(abs(r["at_m"][0]) for r in straight["supports"])
        splayed_x = max(abs(r["at_m"][0]) for r in splayed["supports"])
        self.assertGreater(splayed_x, straight_x)
        self.assertIn("ignores member/joint compliance", splayed["model"])

    def test_load_names_a_real_part_or_role(self):
        with self.assertRaises(ValueError):
            static_load(assemble("table", design_id="t"), load_kg=10, on="roof")

    def test_negative_load_is_refused(self):
        with self.assertRaises(ValueError):
            static_load(assemble("stool", design_id="s"), load_kg=-1)


if __name__ == "__main__":
    unittest.main()
