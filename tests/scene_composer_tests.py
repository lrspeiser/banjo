from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))
import scene_composer as composer


def entry(preset="glass_panel", **changes):
    value = {
        "preset": preset, "position_m": [1, 2, 3], "velocity_m_s": [4, 5, 6],
        "dimensions_m": None, "orientation_wxyz": None, "spin_rad_s": None,
        "representation": "network", "resolution": None, "pin_boundary": None,
    }
    value.update(changes)
    return value


def scene(objects=None, **environment):
    env = {"gravity_m_s2": [0, -9.81, 0], "ground": True, "ground_friction": .35}
    env.update(environment)
    return {"objects": objects or [entry()], "environment": env}


class SceneComposerTests(unittest.TestCase):
    def test_geometry_orientation_motion_and_environment_compile(self):
        quaternion = [math.sqrt(.5), 0, math.sqrt(.5), 0]
        spec = scene([entry(dimensions_m=[.3, .2, .04], orientation_wxyz=quaternion,
                            spin_rad_s=[1, 2, 3], resolution=[3, 4, 5])],
                     gravity_m_s2=[1, -2, 3], ground_friction=.7)
        package = composer.compile_scene({"name": "Free composition", "scene": spec})[0]
        obj = package["objects"][0]
        self.assertEqual(package["name"], "Free composition")
        self.assertEqual(package["gravity_m_s2"], [1.0, -2.0, 3.0])
        self.assertEqual(package["ground"]["friction"], .7)
        self.assertEqual(obj["dimensions_m"], [.3, .2, .04])
        self.assertEqual(obj["orientation_wxyz"], quaternion)
        self.assertEqual(obj["spin_rad_s"], [1, 2, 3])
        self.assertEqual(obj["resolution"], [3, 4, 5])
        self.assertEqual(package["damage_integration"], {
            "maximum_depth": 2,
            "maximum_damage_increment": .05,
            "maximum_plastic_strain_increment": .002,
            "maximum_brittle_opening_overshoot": .05,
            "on_limit": "reject",
        })

    def test_explicit_pin_and_unpin_are_preserved(self):
        package = composer.compile_scene(scene([
            entry(pin_boundary=False), entry("wood_panel", pin_boundary=True,
                                             position_m=[0, 0, 0]),
        ]))[0]
        self.assertEqual([obj["pin_boundary"] for obj in package["objects"]], [False, True])

    def test_explicit_network_overrides_a_rigid_capable_box_preset(self):
        package = composer.compile_scene(scene([
            entry("iron_cube", representation="network", resolution=[2, 3, 4],
                  pin_boundary=True),
        ]))[0]
        obj = package["objects"][0]
        self.assertEqual(obj["representation"], "network")
        self.assertEqual(obj["resolution"], [2, 3, 4])
        self.assertTrue(obj["pin_boundary"])
        self.assertIn("damage_integration", package)

    def test_explicit_rigid_converts_network_box_and_removes_network_fields(self):
        package = composer.compile_scene(scene([
            entry("wood_panel", representation="rigid"),
        ]))[0]
        obj = package["objects"][0]
        self.assertEqual(obj["representation"], "rigid")
        self.assertNotIn("resolution", obj)
        self.assertNotIn("pin_boundary", obj)
        self.assertNotIn("grain_wxyz", obj)

    def test_rigid_override_removes_every_network_only_field(self):
        package = composer.compile_scene(scene([entry("wood_panel", representation="rigid")]))[0]
        obj = package["objects"][0]
        self.assertEqual(obj["representation"], "rigid")
        for field in ("resolution", "pin_boundary", "grain_wxyz"):
            self.assertNotIn(field, obj)
        self.assertNotIn("damage_integration", package)

    def test_mixed_scene_keeps_strict_damage_admission_for_network_matter(self):
        package = composer.compile_scene(scene([
            entry(position_m=[-.2, .2, 0]),
            entry("iron_ball", position_m=[.2, .5, 0], representation="rigid"),
        ]))[0]
        self.assertEqual([obj["representation"] for obj in package["objects"]],
                         ["network", "rigid"])
        self.assertEqual(package["damage_integration"]["on_limit"], "reject")

    def test_rejects_rigid_network_fields_and_unsupported_rigid_shape(self):
        invalid = [
            entry(representation="rigid", resolution=[2, 2, 2]),
            entry(representation="rigid", pin_boundary=False),
            entry("iron_ball", representation="rigid", resolution=[2, 2, 2]),
            entry("iron_ball", representation="rigid", dimensions_m=[.08, .09, .08]),
            entry("tomato_proxy", representation="rigid"),
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                composer.validate_scene(scene([value]))

    def test_strict_fields_finite_unit_quaternion_and_budgets(self):
        cases = []
        unknown = scene(); unknown["command"] = "never"
        cases.append(unknown)
        bad_object = entry(); del bad_object["spin_rad_s"]
        cases.append(scene([bad_object]))
        cases.append(scene([entry(orientation_wxyz=[1, 0, 0, .01])]))
        cases.append(scene([entry(velocity_m_s=[math.inf, 0, 0])]))
        cases.append(scene([entry(pin_boundary="true")]))
        cases.append(scene([entry(resolution=[12, 12, 12])]))
        dense = [entry("glass_matter_ball"), entry("wood_matter_ball", position_m=[1, 0, 0]),
                 entry("iron_matter_ball", position_m=[2, 0, 0])]
        cases.append(scene(dense))
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                composer.validate_scene(value)

    def test_schema_is_nonnullable_and_requires_every_field(self):
        self.assertEqual(composer.SCENE_SCHEMA["type"], "object")
        self.assertNotIn("anyOf", composer.SCENE_SCHEMA)
        object_schema = composer.SCENE_SCHEMA["properties"]["objects"]["items"]
        self.assertEqual(set(object_schema["required"]), set(object_schema["properties"]))
        self.assertFalse(object_schema["additionalProperties"])
        self.assertEqual(object_schema["properties"]["representation"]["enum"],
                         ["network", "rigid"])

    def test_legacy_preset_representation_remains_readable(self):
        legacy_scene = scene([entry(representation="preset")])
        self.assertIs(composer.validate_scene(legacy_scene), legacy_scene)


if __name__ == "__main__":
    unittest.main()
