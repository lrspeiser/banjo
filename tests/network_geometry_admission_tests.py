from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"examples"/"authoring"))
from banjo_authoring import EngineCLI,EngineError,make_object,make_package,validate_network_geometry
sys.path.insert(0,str(ROOT/"playground"))
from drop_builder import validate_drop
import scene_composer


def drop(thickness,resolution,representation="network"):
    return {"target_dimensions_m":[.08,.08,thickness],"projectile":"iron_ball",
        "projectile_dimensions_m":[.012,.012,.012],
        "support":"clamped_edges" if representation=="network" else "free_on_ground",
        "impact_offset_m":[0,0],"heights_m":[.01],"representation":representation,
        "resolution":resolution}


def scene_entry(thickness,resolution):
    return {"preset":"glass_panel","position_m":[0,0,0],"velocity_m_s":[0,0,0],
        "dimensions_m":[.08,.08,thickness],"orientation_wxyz":None,"spin_rad_s":None,
        "representation":"network","resolution":resolution,"pin_boundary":True}


class NetworkGeometryAdmissionTests(unittest.TestCase):
    def test_exact_thickness_resolution_boundary_cases(self):
        with self.assertRaisesRegex(ValueError,r"0\.98 mm radius.*at least 1 mm"):
            validate_network_geometry([.08,.08,.004],[2,2,2])
        self.assertAlmostEqual(validate_network_geometry([.08,.08,.0041],[2,2,2]),.0010045)
        with self.assertRaisesRegex(ValueError,r"0\.98 mm radius"):
            validate_network_geometry([.08,.08,.006],[2,2,3])
        self.assertAlmostEqual(validate_network_geometry([.08,.08,.006],[2,2,2]),.00147)

    def test_lateral_overresolution_rejects_even_with_fine_thickness(self):
        with self.assertRaisesRegex(ValueError,"collision cells are too small"):
            validate_network_geometry([.02,.08,.02],[16,2,2])

    def test_bool_nonfinite_and_noninteger_inputs_reject(self):
        for dimensions,resolution in (([.08,.08,float("nan")],[2,2,2]),
                                      ([.08,.08,.006],[2,True,2]),
                                      ([.08,.08,.006],[2,2,2.0])):
            with self.assertRaises(ValueError):validate_network_geometry(dimensions,resolution)

    def test_drop_and_scene_surface_specific_geometry_reason(self):
        with self.assertRaisesRegex(ValueError,r"0\.98 mm radius.*Dimensions.*resolution"):
            validate_drop(drop(.004,[2,2,2]))
        spec={"objects":[scene_entry(.006,[2,2,3])],
              "environment":{"gravity_m_s2":[0,-9.81,0],"ground":True,"ground_friction":.3}}
        with self.assertRaisesRegex(ValueError,r"0\.98 mm radius.*Dimensions.*resolution"):
            scene_composer.validate_scene(spec)

    def test_rigid_four_millimeter_path_is_unaffected(self):
        value=drop(.004,[12,12,12],"rigid")
        self.assertIs(validate_drop(value),value)

    def test_make_package_and_native_engine_have_admission_parity(self):
        objects=[]
        for index,material in enumerate(("glass","oak","iron"),1):
            objects.append(make_object("glass_panel",index,material=material,
                dimensions_m=[.08,.08,.006],resolution=[2,2,2],
                position_m=[(index-2)*.1,.04,0]))
        package=make_package(objects)
        candidates=[ROOT/"build/win-joint-double/Release/banjo_platform_cli.exe",
                    ROOT/"build/win-integration/Release/banjo_platform_cli.exe",
                    ROOT/"build/ci/banjo_platform_cli"]
        executable=next((path for path in candidates if path.is_file()),None)
        if executable is None:self.skipTest("native platform CLI is not built")
        engine=EngineCLI(executable)
        with tempfile.TemporaryDirectory() as directory:
            valid=Path(directory)/"valid.json";valid.write_text(json.dumps(package),encoding="utf-8")
            report=engine.validate(valid)
            self.assertEqual(len(report["objects"]),3)
            self.assertEqual([obj["material"] for obj in package["objects"]],["glass","oak","iron"])

            for thickness,resolution in ((.004,[2,2,2]),(.006,[2,2,3])):
                raw=copy.deepcopy(package)
                raw["objects"][0]["dimensions_m"]=[.08,.08,thickness]
                raw["objects"][0]["resolution"]=resolution
                path=Path(directory)/f"thin-{thickness}-{resolution[2]}.json"
                path.write_text(json.dumps(raw),encoding="utf-8")
                with self.subTest(thickness=thickness,resolution=resolution),self.assertRaises(EngineError):
                    engine.validate(path)

            lateral=copy.deepcopy(package)
            lateral["objects"][0]["dimensions_m"]=[.02,.08,.02]
            lateral["objects"][0]["resolution"]=[16,2,2]
            path=Path(directory)/"lateral.json";path.write_text(json.dumps(lateral),encoding="utf-8")
            with self.assertRaises(EngineError):engine.validate(path)


if __name__=="__main__":unittest.main()
