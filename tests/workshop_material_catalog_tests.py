from __future__ import annotations

from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp import engine_materials  # noqa: E402
from mcp import workshop  # noqa: E402


class MaterialParity(unittest.TestCase):
    def test_densities_match_the_engine_catalogue(self):
        text = (ROOT / "src" / "material" / "MaterialCatalog.cpp").read_text(encoding="utf-8")
        expected = {
            "iron": 7870.0,
            "aluminum": 2700.0,
            "glass": 2500.0,
            "alumina ceramic": 3900.0,
            "oak": 700.0,
            "rubber": 1100.0,
            "ice": 917.0,
            "concrete": 2400.0,
        }
        # Pin both sides: if the C++ numbers move, this test must be deliberately
        # updated rather than silently letting Workshop keep an old mass model.
        for name, density in expected.items():
            self.assertEqual(density, engine_materials.density(name))
            self.assertRegex(text, re.compile(r"\b" + re.escape(str(density)) + r"\b"))

    def test_workshop_mass_arithmetic_can_be_synchronized(self):
        before_oak = workshop.DENSITY_KG_M3["oak"]
        before_rubber = workshop.DENSITY_KG_M3["rubber"]
        try:
            engine_materials.synchronize_workshop_model()
            self.assertEqual(700.0, workshop.DENSITY_KG_M3["oak"])
            self.assertEqual(1100.0, workshop.DENSITY_KG_M3["rubber"])
            self.assertEqual(2700.0, workshop.DENSITY_KG_M3["aluminium"])
        finally:
            workshop.DENSITY_KG_M3["oak"] = before_oak
            workshop.DENSITY_KG_M3["rubber"] = before_rubber

    def test_display_aliases_map_to_engine_presets(self):
        self.assertEqual("aluminum", engine_materials.canonical("aluminium"))
        self.assertEqual("glass", engine_materials.canonical("soda_lime_glass"))
        self.assertFalse(engine_materials.known("pine"))
        self.assertFalse(engine_materials.known("steel"))


if __name__ == "__main__":
    unittest.main()
