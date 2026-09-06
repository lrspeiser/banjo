from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))
from dynamic_material import execute_impact, native_request, validate_impact, validate_recording


def elastic(material_id="elastic", name="Fictional elastic", density=1000):
    return {"material_id": material_id, "name": name, "density_kg_m3": density,
            "mechanical_law": "isotropic_elastic",
            "parameters": {"young_modulus_pa": 1e6, "poisson_ratio": .25,
                           "maximum_total_strain_norm": .08}}


def j2(material_id="j2", name="Fictional J2"):
    return {"material_id": material_id, "name": name, "density_kg_m3": 1000,
            "mechanical_law": "j2_plastic",
            "parameters": {"young_modulus_pa": 1e6, "poisson_ratio": .25,
                           "maximum_total_strain_norm": .08,
                           "initial_yield_stress_pa": 1200,
                           "isotropic_hardening_modulus_pa": 20000}}


def orthotropic(material_id="ortho", name="Fictional orthotropic"):
    return {"material_id": material_id, "name": name, "density_kg_m3": 700,
            "mechanical_law": "orthotropic_elastic",
            "parameters": {"young_modulus_pa": [12e6, 1.2e6, .8e6],
                           "poisson_xy_yz_zx": [.1, .1, .005],
                           "shear_xy_yz_zx_pa": [.8e6, .35e6, .55e6],
                           "maximum_total_strain_norm": .08}}


def catalog_materials():
    glass=elastic("glass","Glass catalog coefficients",2500)
    glass["parameters"].update(young_modulus_pa=70e9,maximum_total_strain_norm=.1)
    oak=orthotropic("oak","Oak catalog coefficients")
    oak["parameters"].update(young_modulus_pa=[12e9,1.2e9,.8e9],
                             shear_xy_yz_zx_pa=[.8e9,.35e9,.55e9],
                             maximum_total_strain_norm=.05)
    iron=j2("iron","Iron catalog coefficients");iron["density_kg_m3"]=7870
    iron["parameters"].update(young_modulus_pa=211e9,poisson_ratio=.3,
                              initial_yield_stress_pa=250e6,
                              isotropic_hardening_modulus_pa=1e9,
                              maximum_total_strain_norm=.05)
    return [glass,oak,iron]


def impact(materials=None, *, sphere_density=7870, clearance=.0005, speed=0,
           max_calls=200000, energy=3e-6):
    return {"materials": materials or [elastic()], "dimensions_m": [.08, .02, .08],
            "mesh_refinement": 1,
            "sphere": {"radius_m": .012, "density_kg_m3": sphere_density,
                       "clearance_m": clearance, "offset_xz_m": [.007, .009],
                       "speed_m_s": speed},
            "energy_budget_j": energy, "max_step_calls": max_calls}


def rejects(value):
    with unittest.TestCase().assertRaises(ValueError):
        validate_impact(value)


class ContractTests(unittest.TestCase):
    def test_closed_schema_rejects_missing_extra_bool_nonfinite_and_range(self):
        for mutate in (
            lambda x: x.pop("sphere"),
            lambda x: x.update(extra=1),
            lambda x: x.update(mesh_refinement=True),
            lambda x: x["sphere"].update(radius_m=float("nan")),
            lambda x: x["sphere"].update(radius_m=.5),
        ):
            value=impact();mutate(value);rejects(value)

    def test_law_specific_coefficients_and_duplicate_ids_reject(self):
        value=impact();value["materials"][0]["parameters"]["initial_yield_stress_pa"]=1
        rejects(value)
        rejects(impact([elastic("same"), j2("same")]))

    def test_sphere_footprint_and_duration_bounds(self):
        value=impact();value["sphere"]["offset_xz_m"]=[.04,0];rejects(value)
        with self.assertRaises(ValueError): native_request(impact(), .0009)
        with self.assertRaises(ValueError): native_request(impact(), float("inf"))

    def test_validate_recording_rejects_forged_completion_or_request(self):
        request=native_request(impact(),.001)
        material=request["materials"][0]
        frame={"time_s":0,"sphere_center_m":[0,0,0],"sphere_velocity_m_s":[0,0,0],
               "positions_m":[[0,0,0]],"maximum_equivalent_plastic_strain":0,
               "plastic_dissipation_j":0}
        recording={"schema":"banjo.dynamic-material-playback.v1","status":"complete",
                   "physical_response_validated":False,"request":request,"cases":[{
                       "material_id":material["material_id"],"material":material,"status":"complete",
                       "mesh":{"reference_positions_m":[[0,0,0]]},"frames":[frame],
                       "summary":{"completed_duration_s":0}}]}
        with self.assertRaises(ValueError): validate_recording(recording,request)
        forged=copy.deepcopy(recording);forged["request"]["duration_s"]=.002
        with self.assertRaises(ValueError): validate_recording(forged,request)


CLI = Path(os.environ.get("BANJO_DYNAMIC_MATERIAL_CLI",
    ROOT / "build/win-joint-double/Release/banjo_dynamic_material_cli.exe"))


@unittest.skipUnless(CLI.is_file(), "banjo_dynamic_material_cli is not built")
class NativeTests(unittest.TestCase):
    def run_native(self, authored, duration):
        return execute_impact(CLI,native_request(authored,duration))[0]

    def test_native_rejects_duplicate_json_keys_and_bad_parameters(self):
        duplicate=b'{"schema":"banjo.dynamic-material-request.v1","schema":"x"}'
        result=subprocess.run([str(CLI)],input=duplicate,capture_output=True,check=False)
        self.assertNotEqual(result.returncode,0)
        bad=native_request(impact(),.001);bad["sphere"]["radius_m"]=-1
        result=subprocess.run([str(CLI)],input=json.dumps(bad).encode(),capture_output=True,check=False)
        self.assertNotEqual(result.returncode,0)

    def test_label_rename_preserves_numerical_trajectory(self):
        first=self.run_native(impact([elastic(name="Alpha")],clearance=0,speed=.05),.001)
        second=self.run_native(impact([elastic(name="Renamed")],clearance=0,speed=.05),.001)
        a,b=first["cases"][0],second["cases"][0]
        self.assertEqual(a["frames"],b["frames"])
        ignored={"wall_ms"}
        self.assertEqual({k:v for k,v in a["summary"].items() if k not in ignored},
                         {k:v for k,v in b["summary"].items() if k not in ignored})

    def test_sphere_density_changes_native_motion(self):
        light=self.run_native(impact(sphere_density=1000,clearance=0,speed=.05),.001)
        heavy=self.run_native(impact(sphere_density=7870,clearance=0,speed=.05),.001)
        self.assertNotEqual(light["cases"][0]["frames"][-1]["sphere_velocity_m_s"],
                            heavy["cases"][0]["frames"][-1]["sphere_velocity_m_s"])

    def test_initial_frame_matches_authored_offset_and_clearance(self):
        authored=impact(clearance=.0005)
        recording=self.run_native(authored,.001)
        case=recording["cases"][0];reference=case["mesh"]["reference_positions_m"]
        center=case["frames"][0]["sphere_center_m"]
        mesh_center_x=(min(p[0] for p in reference)+max(p[0] for p in reference))/2
        mesh_center_z=(min(p[2] for p in reference)+max(p[2] for p in reference))/2
        top=max(p[1] for p in reference)
        self.assertAlmostEqual(center[0]-mesh_center_x,authored["sphere"]["offset_xz_m"][0])
        self.assertAlmostEqual(center[2]-mesh_center_z,authored["sphere"]["offset_xz_m"][1])
        self.assertAlmostEqual(center[1]-authored["sphere"]["radius_m"]-top,
                               authored["sphere"]["clearance_m"])

    def test_full_reference_run_has_contact_deformation_and_only_j2_plasticity(self):
        recording=self.run_native(impact([elastic(),j2()]),.1)
        self.assertEqual(recording["status"],"complete")
        for case in recording["cases"]:
            self.assertGreater(case["summary"]["accepted_contacts"],0)
            reference=case["mesh"]["reference_positions_m"]
            self.assertTrue(any(p!=q for p,q in zip(case["frames"][-1]["positions_m"],reference)))
            maximum=max(frame["maximum_equivalent_plastic_strain"] for frame in case["frames"])
            self.assertEqual(maximum>0,case["material"]["mechanical_law"]=="j2_plastic")

    def test_small_work_budget_returns_honest_solver_limit(self):
        recording=self.run_native(impact(max_calls=3,clearance=0,speed=.1),.01)
        self.assertEqual(recording["status"],"solver_limit")
        case=recording["cases"][0]
        self.assertEqual(case["status"],"solver_limit")
        self.assertLess(case["summary"]["completed_duration_s"],.01)
        self.assertEqual(case["frames"][0]["time_s"],0)

    def test_three_law_matched_input_smoke(self):
        recording=self.run_native(impact([elastic("glass-scale"),orthotropic("oak-scale"),
                                          j2("iron-scale")],clearance=0,speed=.02,
                                         energy=1e-4),.001)
        self.assertEqual(len(recording["cases"]),3)
        self.assertTrue(all(case["summary"]["requested_duration_s"]==.001
                            for case in recording["cases"]))

    def test_catalog_glass_oak_iron_short_flight_is_retained(self):
        recording=self.run_native(impact(catalog_materials(),energy=6e-6),.001)
        self.assertEqual(recording["status"],"complete")
        self.assertEqual([case["material_id"] for case in recording["cases"]],
                         ["glass","oak","iron"])
        self.assertTrue(all(case["summary"]["completed_duration_s"]==.001
                            for case in recording["cases"]))
        self.assertTrue(all(case["summary"]["accepted_contacts"]==0
                            for case in recording["cases"]))


if __name__ == "__main__":
    unittest.main()
