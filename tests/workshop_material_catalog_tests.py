from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
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
            # anisotropy_ratio is the one property with a non-zero default in
            # Material.hpp, so an absent line means 1.0 and not "unset".
            row["anisotropy_ratio"] = 1.0
            for key in ("yield_strength_pa", "tensile_strength_pa", "compressive_strength_pa",
                        "shear_strength_pa", "fracture_energy_j_m2", "anisotropy_ratio"):
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

    def test_only_oak_is_declared_to_have_a_grain(self):
        grained = {name for name in engine_materials.MATERIALS
                   if engine_materials.mechanics(name)["anisotropy_ratio"] > 1.0}
        self.assertEqual({"oak"}, grained)
        self.assertEqual(8.0, engine_materials.mechanics("oak")["anisotropy_ratio"])
        self.assertEqual(1.0, engine_materials.mechanics("iron")["anisotropy_ratio"])

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

    def test_a_design_has_one_mass_whichever_module_was_loaded_first(self):
        # (Not "weighs_the_same": CI's log masks anything after "ghs_", GitHub's
        # token prefix, so a failure would have printed as "test_a_design_wei***".)
        # mcp.workshop kept its own oak (750) and rubber (1200) until a module
        # that synchronises it was imported, so one oak table weighed 102.0 kg
        # in a suite run on its own, as CI runs them, and 95.2 kg in the running
        # Workshop. A run of many suites in one process hides that, so ask a
        # fresh interpreter what a bare import holds.
        script = "\n".join([
            "import json, sys",
            f"sys.path.insert(0, {str(ROOT)!r})",
            "from mcp import engine_materials, workshop",
            "def weigh():",
            "    return workshop.assemble('table', parameters={'material': 'oak'}).measure()['mass_kg']",
            "bare = [dict(workshop.DENSITY_KG_M3), weigh()]",
            "engine_materials.synchronize_workshop_model()",
            "print(json.dumps([bare, [dict(workshop.DENSITY_KG_M3), weigh()]]))",
        ])
        done = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True,
                              text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        (bare, bare_kg), (synchronized, synchronized_kg) = json.loads(done.stdout)
        self.assertEqual(synchronized_kg, bare_kg)
        for name, density in bare.items():
            self.assertEqual(synchronized[name], density, name)
            if engine_materials.known(name):
                self.assertEqual(engine_materials.density(name), density, name)

    def test_display_aliases_map_to_engine_presets(self):
        self.assertEqual("aluminum", engine_materials.canonical("aluminium"))
        self.assertEqual("glass", engine_materials.canonical("soda_lime_glass"))
        self.assertFalse(engine_materials.known("pine"))
        self.assertFalse(engine_materials.known("steel"))


if __name__ == "__main__":
    unittest.main()
