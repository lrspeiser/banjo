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

    def test_stiffness_and_strengths_match_the_engine_catalogue_preset_by_preset(self):
        text = (ROOT / "src" / "material" / "MaterialCatalog.cpp").read_text(encoding="utf-8")
        body = text[text.index("MaterialDefinition makeReferenceMaterial"):
                    text.index("RollingResistanceSource rollingResistanceSource")]
        engine: dict[str, dict[str, float]] = {}
        for block in re.split(r"\bcase MaterialPreset::", body)[1:]:
            base = re.search(r'baseMaterial\(\s*"([a-z0-9_]+)",\s*MaterialModel::\w+,\s*([0-9.e+-]+),'
                             r'\s*([0-9.e+-]+),\s*([0-9.e+-]+)\)', block)
            self.assertIsNotNone(base, block[:80])
            row = {"density_kg_m3": float(base.group(2)), "young_modulus_pa": float(base.group(3)),
                   "poisson_ratio": float(base.group(4))}
            for key in ("yield_strength_pa", "tensile_strength_pa", "compressive_strength_pa",
                        "shear_strength_pa", "fracture_energy_j_m2"):
                found = re.search(r"material\." + key + r"\s*=\s*([0-9.e+-]+);", block)
                if found:
                    row[key] = float(found.group(1))
            engine[base.group(1)] = row
        self.assertEqual(8, len(engine))
        for name, declared in engine_materials.MATERIALS.items():
            in_engine = engine[declared["engine_name"]]
            self.assertEqual(in_engine.pop("density_kg_m3"), declared["density_kg_m3"], name)
            # Every number, and the same set of them: a brittle preset has no
            # yield strength on either side.
            self.assertEqual(in_engine, engine_materials.mechanics(name), name)

    def test_a_name_the_engine_does_not_have_has_no_strength(self):
        with self.assertRaisesRegex(KeyError, "no declared strength"):
            engine_materials.mechanics("pine")
        self.assertEqual(engine_materials.mechanics("aluminum"), engine_materials.mechanics("aluminium"))

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
