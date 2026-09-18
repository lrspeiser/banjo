"""Exact thin-part compilation and persistent, explicit mechanical intent."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'playground')]
from mcp import engine_materials, workshop_components as components, workshop_rigid as rigid
from mcp.workshop import materialize, WorkshopDesign, WirePart
import workshop_api, workshop_store, workshop_bench, workshop_trials

THIN={"kind":"table","design_id":"thin-table","parameters":{"top_thickness_m":.005,"leg_section_m":.015}}


def design(material="oak", overrides=None):
    spec=deepcopy(THIN);spec["parameters"]["material"]=material
    plain,_=components.design_from_spec(spec)
    spec["component_overrides"]={p.name:{"mechanics":{"model":"rigid"}} for p in plain.parts}
    for name, change in (overrides or {}).items():spec["component_overrides"][name].update(change)
    return components.design_from_spec(spec)[0]


class PreciseCompiler(unittest.TestCase):
    def test_exact_dimensions_mass_tensor_and_zero_lattice_all_materials(self):
        for material in ("glass","oak","iron"):
            with self.subTest(material=material):
                d=design(material);before=deepcopy(d.wireframe());a=rigid.compile_rigid(d)
                self.assertEqual(5,a["collision_boxes"]);self.assertEqual(0,a["stored_cells"])
                self.assertFalse(a["internal_fracture_supported"]);self.assertFalse(a["strength_certified"])
                self.assertTrue(a["live_installation_supported"])
                self.assertIn("anchored-scenery",a["live_installation_scope"])
                top=next(p for p in a["components"] if p["component"]=="top")
                self.assertEqual([1.2,.005,.7],top["dimensions_m"])
                self.assertAlmostEqual(engine_materials.density(material)*(.005*1.2*.7+4*.015**2*.755),a["mass_kg"],places=11)
                for axis in range(3):
                    oracle=0
                    for p in d.parts:
                        mass=engine_materials.density(material)*p.size_m[0]*p.size_m[1]*p.size_m[2]
                        oracle+=mass*sum(p.size_m[j]**2/12+(p.center_m[j]-a["centre_of_mass_m"][j])**2 for j in range(3) if j!=axis)
                    self.assertAlmostEqual(oracle,a["inertia_kg_m2"][axis][axis],places=11)
                self.assertEqual(before,d.wireframe())

    def test_appearance_does_not_change_physics_and_physical_curve_is_refused(self):
        original=rigid.compile_rigid(design())
        cosmetic=rigid.compile_rigid(design(overrides={"leg-1":{"skin":{"profile":"curve","bend_m":.1,"physical":False}}}))
        self.assertEqual(original["physics_hash"],cosmetic["physics_hash"])
        with self.assertRaisesRegex(ValueError,"axis-aligned"):
            rigid.compile_rigid(design(overrides={"leg-1":{"skin":{"profile":"curve","bend_m":.1,"physical":True}}}))

    def test_no_auto_rigid_selection_or_mixed_coupling(self):
        plain,_=components.design_from_spec(THIN)
        with self.assertRaisesRegex(ValueError,"whole candidate"):rigid.compile_rigid(plain)
        mixed=components.apply_overrides(plain,{"top":{"mechanics":{"model":"rigid"}}})
        with self.assertRaisesRegex(ValueError,"mixed mechanics"):rigid.compile_rigid(mixed)
        self.assertEqual([],materialize(mixed)["objects"])

    def test_future_models_are_not_claimed_implemented(self):
        for model in ("beam","sheet","cable","auto",True,17):
            with self.subTest(model=model),self.assertRaises(ValueError):rigid.checked_mechanics({"model":model})
        for value in (False,[],"rigid",{"model":"rigid","fracture":True}):
            with self.subTest(value=value),self.assertRaises(ValueError):rigid.checked_mechanics(value)

    def test_no_grid_dependence_in_rigid_plan(self):
        d=design()
        plans=[materialize(d,cell_size_m=h) for h in (.04,.02,.01,.005)]
        self.assertEqual(1,len({p["fingerprint"] for p in plans}))
        for plan in plans:
            self.assertEqual([],plan["objects"]);self.assertEqual(0,plan["snapping"]["members_changed"])
            self.assertEqual("rigid",plan["mechanical_model"])

    def test_unsupported_geometry_never_replaced_with_bounds(self):
        for change, phrase in (({"rotation_deg":[0,1,0]},"axis-aligned"),
                               ({"material":"glass"},"one material"),
                               ({"scale":[1,1,1]},None)):
            if phrase is None:continue
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,phrase):
                rigid.compile_rigid(design(overrides={"leg-1":change}))

    def test_overlap_gap_and_edge_contacts_are_not_fixed_connections(self):
        # Use semantic box parts to independently exercise admission geometry.
        from dataclasses import replace
        source=design();base=source.parts[0]
        for offset, phrase in (((0,0,0),"overlaps"),((2,0,0),"share faces"),((1,1,0),"share faces")):
            parts=[replace(base,name="a",size_m=(1,1,1),center_m=(0,0,0)),
                   replace(base,name="b",size_m=(1,1,1),center_m=offset)]
            test=deepcopy(source);test.parts=parts;test.lineage={"component_overrides":{n:{"mechanics":{"model":"rigid"}} for n in ("a","b")}}
            with self.subTest(offset=offset),self.assertRaisesRegex(ValueError,phrase):rigid.compile_rigid(test)

    def test_source_and_model_survive_saved_recipe_roundtrip(self):
        d=design()
        with tempfile.TemporaryDirectory() as folder:
            saved=workshop_store.save(Path(folder),d)
            record, reopened=workshop_store.load(Path(folder),d.design_id)
            self.assertEqual("rigid",saved["mechanical_model"])
            self.assertEqual("precise-rigid-geometry",saved["measured"]["basis"])
            self.assertEqual(rigid.compile_rigid(d),rigid.compile_rigid(reopened))
            self.assertEqual(record["fingerprint"],rigid.compile_rigid(d)["physics_hash"])

    def test_unbuildable_physical_source_can_be_saved_without_certifying_it(self):
        d=design(overrides={"leg-1":{"skin":{"profile":"curve","bend_m":.12,"physical":True}}})
        with tempfile.TemporaryDirectory() as folder:
            saved=workshop_store.save(Path(folder),d)
            _,reopened=workshop_store.load(Path(folder),d.design_id)
            self.assertTrue(saved["physical_preview_error"])
            self.assertFalse(saved["measured"]["geometry_coherent"])
            self.assertEqual(d.wireframe(),reopened.wireframe())

    def test_api_edit_preview_feedback_reopen_and_fail_closed_tests(self):
        with tempfile.TemporaryDirectory() as folder:
            app=SimpleNamespace(runs_path=Path(folder))
            candidate=workshop_api.candidates(app,{**THIN,"mechanics_edit":{"model":"rigid"}})["candidates"][0]
            self.assertEqual("rigid",candidate["mechanical_model"])
            self.assertEqual([],candidate["analytical"]["static_loads"])
            hashes=[]
            for h in (.04,.01,.005):
                result=workshop_api.plan(app,{**candidate,"visual":{"cell_size_m":h}})
                self.assertEqual([],result["objects"]);self.assertFalse(result["buildability"]["installation_ready"])
                self.assertEqual(0,result["rigid"]["stored_cells"])
                hashes.append(result["rigid"]["physics_hash"])
            self.assertEqual(1,len(set(hashes)))
            answer=workshop_api.remember(app,{**candidate,"save_design":True,"note":"Keep the thin source"})
            self.assertEqual("rigid",answer["design"]["mechanical_model"])
            with self.assertRaisesRegex(ValueError,"declared rigid"):
                workshop_bench.run(app,design(),{"test":"static_load","config":{}})
            with self.assertRaisesRegex(ValueError,"declared rigid"):
                workshop_trials.run_declared_static_load(app,design())

    def test_lattice_motion_boundaries_do_not_override_rigid_choice(self):
        import workshop_motion, workshop_sparse_trial
        for test in ("drop_product", "slide_product"):
            with self.subTest(test=test), self.assertRaisesRegex(ValueError, "declared rigid"):
                workshop_motion.scene(design(), test, {})
        with self.assertRaisesRegex(ValueError, "declared rigid"):
            workshop_sparse_trial.prototype_scene(design(), load_kg=25)

    def test_bench_catalog_separates_mechanical_models(self):
        for kind in ("table", "bench"):
            tests = workshop_bench.catalog(kind)
            rigid_tests = [t for t in tests if t.get("required_model") == "rigid"]
            self.assertEqual(["rigid_motion"], [t["test"] for t in rigid_tests])
            self.assertEqual("simulation", rigid_tests[0]["category"])
            self.assertEqual("selected-product", rigid_tests[0]["subject"])
            self.assertTrue(all(t["required_model"] == "lattice" for t in tests if t["test"] != "rigid_motion"))
        for kind in ("cart", "kettle", "shelf-unit"):
            self.assertFalse(any(t["test"] == "rigid_motion" for t in workshop_bench.catalog(kind)))

    def test_numeric_invalid_config_never_runs_a_substitute(self):
        import workshop_rigid_trial
        for config in ({"strength_pass":True},{"record_trace":"true"},{"duration_s":float("nan")},{"drop_height_m":3}):
            with self.subTest(config=config),self.assertRaises(ValueError):workshop_rigid_trial.run(SimpleNamespace(),design(),config)

if __name__=="__main__":unittest.main()
