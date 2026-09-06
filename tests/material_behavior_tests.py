from pathlib import Path
import math
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "authoring"))
from material_behavior import (
    MaterialBehavior, UnsupportedBehaviorError, assess_backend_capability,
)


def isotropic(material_id="specimen-17", name="Unseen basalt composite", **changes):
    parameters = {
        "young_modulus_pa": 48.25e9,
        "poisson_ratio": 0.19,
        "maximum_total_strain_norm": 0.0065,
    }
    parameters.update(changes)
    return MaterialBehavior(material_id, name, 2937.4, "isotropic_elastic", parameters)


class MaterialBehaviorTests(unittest.TestCase):
    def test_unseen_name_and_parameters_are_validated_by_law_not_catalog_name(self):
        behavior = isotropic()
        self.assertEqual(behavior.material_id, "specimen-17")
        self.assertEqual(behavior.name, "Unseen basalt composite")
        self.assertEqual(behavior.to_dict()["units"], "SI")
        self.assertEqual(len(behavior.physical_hash), 64)

    def test_display_identity_and_name_do_not_change_physical_hash(self):
        first = isotropic("draft-a", "Workshop draft")
        renamed = isotropic("published-908", "Finished public name")
        changed = isotropic("draft-a", "Workshop draft", young_modulus_pa=49e9)
        self.assertEqual(first.physical_hash, renamed.physical_hash)
        self.assertNotEqual(first.physical_hash, changed.physical_hash)

    def test_all_three_laws_accept_finite_physical_parameters(self):
        orthotropic = MaterialBehavior("wood-x", "Unseen timber", 615.0, "orthotropic_elastic", {
            "young_modulus_pa": [11.2e9, 0.91e9, 0.63e9],
            "poisson_xy_yz_zx": [0.035, 0.42, 0.028],
            "shear_xy_yz_zx_pa": [0.72e9, 0.075e9, 0.61e9],
            "maximum_total_strain_norm": 0.008,
        })
        plastic = MaterialBehavior("alloy-q", "Unseen alloy", 7811.0, "j2_plastic", {
            "young_modulus_pa": 203.4e9,
            "poisson_ratio": 0.287,
            "initial_yield_stress_pa": 317e6,
            "isotropic_hardening_modulus_pa": 1.17e9,
            "maximum_total_strain_norm": 0.045,
        })
        self.assertEqual(orthotropic.parameters["young_modulus_pa"][0], 11.2e9)
        self.assertEqual(plastic.parameters["initial_yield_stress_pa"], 317e6)

    def test_invalid_nonphysical_and_nan_values_are_rejected(self):
        cases = [
            lambda: MaterialBehavior("x", "x", 0, "isotropic_elastic", isotropic().parameters),
            lambda: MaterialBehavior("x", "x", 1e9 + 1, "isotropic_elastic", isotropic().parameters),
            lambda: isotropic(young_modulus_pa=math.nan),
            lambda: isotropic(poisson_ratio=0.5),
            lambda: isotropic(maximum_total_strain_norm=-0.1),
            lambda: MaterialBehavior("x", "x", 1, "j2_plastic", {
                "young_modulus_pa": 1e9, "poisson_ratio": .2,
                "initial_yield_stress_pa": 1e6,
                "isotropic_hardening_modulus_pa": -1,
                "maximum_total_strain_norm": .01,
            }),
        ]
        for build in cases:
            with self.subTest(build=build), self.assertRaises(ValueError):
                build()

    def test_parameters_are_immutable_and_serialization_is_a_defensive_copy(self):
        source = {
            "young_modulus_pa": [11.2e9, 0.91e9, 0.63e9],
            "poisson_xy_yz_zx": [0.035, 0.42, 0.028],
            "shear_xy_yz_zx_pa": [0.72e9, 0.075e9, 0.61e9],
            "maximum_total_strain_norm": 0.008,
        }
        behavior = MaterialBehavior("wood-x", "Unseen timber", 615, "orthotropic_elastic", source)
        original_hash = behavior.physical_hash
        source["young_modulus_pa"][0] = 999
        exported = behavior.to_dict()
        exported["parameters"]["young_modulus_pa"][0] = 888
        self.assertEqual(behavior.parameters["young_modulus_pa"][0], 11.2e9)
        self.assertEqual(behavior.physical_hash, original_hash)
        with self.assertRaises(TypeError):
            behavior.parameters["maximum_total_strain_norm"] = 1

    def test_non_spd_orthotropic_compliance_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "positive definite"):
            MaterialBehavior("bad", "bad", 500, "orthotropic_elastic", {
                "young_modulus_pa": [1e9, 1e9, 1e9],
                "poisson_xy_yz_zx": [2.0, 2.0, 2.0],
                "shear_xy_yz_zx_pa": [1e8, 1e8, 1e8],
                "maximum_total_strain_norm": .01,
            })

    def test_backend_reports_and_rejects_unsupported_behavior_without_downgrade(self):
        assessment = assess_backend_capability(
            ["small_strain_reference", "dynamic_contact", "dents", "fracture", "viscoelasticity"])
        self.assertFalse(assessment.supported)
        self.assertEqual(assessment.supported_capabilities, ("small_strain_reference",))
        self.assertEqual(
            assessment.unsupported_capabilities,
            ("dents", "dynamic_contact", "fracture", "viscoelasticity"))
        with self.assertRaisesRegex(UnsupportedBehaviorError, "dynamic_contact"):
            assessment.require_supported()
        with self.assertRaises(UnsupportedBehaviorError):
            MaterialBehavior(
                "rubber", "Rate-sensitive rubber", 1100, "isotropic_elastic",
                isotropic().parameters,
                required_capabilities=("small_strain_reference", "viscoelasticity"))
        with self.assertRaisesRegex(UnsupportedBehaviorError, "exactly"):
            MaterialBehavior("x", "x", 1000, "isotropic_elastic", isotropic().parameters,
                             required_capabilities=())

    def test_unknown_law_is_rejected_instead_of_mapped_to_elasticity(self):
        with self.assertRaisesRegex(UnsupportedBehaviorError, "hyperelastic"):
            MaterialBehavior("x", "x", 1000, "hyperelastic", {})


if __name__ == "__main__":
    unittest.main()
