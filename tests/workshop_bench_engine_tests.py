"""Real-engine acceptance cases for Workshop's functional bench.

CI supplies BANJO_LIVE_ENGINE after building banjo_live_world_run. These are
small isolated worlds compiled from the selected Workshop products, never the
owner's live room.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "playground"))

import workshop_bench  # noqa: E402
from mcp.workshop import assemble  # noqa: E402

ENGINE = Path(os.environ["BANJO_LIVE_ENGINE"]).resolve() if os.environ.get("BANJO_LIVE_ENGINE") else None


@unittest.skipUnless(ENGINE is not None and ENGINE.is_file(), "the live world runner is not built")
class TheWorkshopRunsRealThings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.app = type("App", (), {"engine_path": ENGINE, "runs_path": root / "runs"})()

    def tearDown(self): self.tmp.cleanup()

    def test_selected_kettle_holds_water_and_heat_below_warms_it(self):
        design = assemble("kettle", design_id="bench-kettle",
                          parameters={"width_m": 0.28, "depth_m": 0.24,
                                      "vessel_height_m": 0.18,
                                      "wall_thickness_m": 0.01,
                                      "material": "iron"})
        result = workshop_bench.run(self.app, design, {
            "test": "kettle_heat",
            "config": {"water_kg": 1.0, "heater_power_w": 5000.0, "duration_s": 60.0},
        })
        measured = result["measured"]
        playback = result["playback"]
        self.assertGreater(len(playback["frames"]), 8, playback)
        self.assertGreater(playback["duration_s"], 0, playback)
        self.assertLessEqual(playback["sampling"]["max_gap_s"], 0.54, playback["sampling"])
        self.assertGreater(result["design"]["capacity_l"], 1.0, result)
        self.assertEqual("iron", result["design"]["material"], result)
        self.assertIsNotNone(measured["water_start_k"], result)
        self.assertIsNotNone(measured["water_end_k"], result)
        self.assertGreater(measured["water_end_k"], measured["water_start_k"] + 0.01, result)
        self.assertGreater((measured["ledger"] or {}).get("heater_in_j", 0), 0, result)

    def test_selected_cart_moves_and_both_axles_turn_in_real_joints(self):
        design = assemble("cart", design_id="bench-cart")
        result = workshop_bench.run(self.app, design, {
            "test": "cart_roll", "config": {"speed_m_s": 0.8, "duration_s": 0.4},
        })
        measured = result["measured"]
        playback = result["playback"]
        self.assertGreater(len(playback["frames"]), 8, playback)
        self.assertGreater(playback["duration_s"], 0, playback)
        self.assertLessEqual(playback["sampling"]["max_gap_s"], 0.54, playback["sampling"])
        # Four, not two: each axle is carried by TWO bearing mounts, which is
        # how an axle is actually borne. The trial simplifies each pair into one
        # hinge, so the design has four bearing relationships and the scratch
        # world has two rotating joints; this asserted the realised count
        # against the design's.
        self.assertEqual(4, result["design"]["bearing_relationships"], result)
        # The pins must actually be hung. Session() starts a world without
        # them, so this trial once reported joint_count 0 with no axle turns
        # and a chassis that slid instead of rolling.
        self.assertGreater(measured["joint_count"], 0, result)
        self.assertGreater(measured["chassis_delta_m"][2], 0.03, result)
        self.assertEqual(2, len(measured["axle_turns"]), result)
        self.assertTrue(all(abs(row["degrees"]) > 2.0 for row in measured["axle_turns"]), result)

    def test_an_edited_machine_control_moves_the_load_and_draws_energy(self):
        design = assemble("table", design_id="bench-source")
        result = workshop_bench.run(self.app, design, {
            "test": "machine_control",
            "config": {"power": True, "direction": 1, "setting": 60.0,
                       "duration_s": 0.8, "load_kg": 20.0},
        })
        measured = result["measured"]
        playback = result["playback"]
        self.assertGreater(len(playback["frames"]), 8, playback)
        self.assertGreater(playback["duration_s"], 0, playback)
        self.assertLessEqual(playback["sampling"]["max_gap_s"], 0.54, playback["sampling"])
        self.assertEqual("applied", measured["acknowledgement"], result)
        self.assertEqual(1, measured["control"].get("direction"), result)
        self.assertAlmostEqual(0.6, measured["control"].get("setting"), delta=0.01, msg=result)
        self.assertGreater(measured["load_delta_y_m"], 0.01, result)
        self.assertGreater(measured["battery"].get("given_j", 0), 0, result)
        self.assertGreater(abs(measured["motor"].get("speed_rad_s", 0)), 0.01, result)



@unittest.skipUnless(ENGINE is not None and ENGINE.is_file(), "the live world runner is not built")
class ExactNativeMatter(unittest.TestCase):
    setUp = TheWorkshopRunsRealThings.setUp
    tearDown = TheWorkshopRunsRealThings.tearDown

    def test_native_grid_matches_glass_oak_iron_at_two_resolutions(self):
        import workshop_sparse_trial,live_session
        from mcp import workshop_components
        for material in ("glass","oak","iron"):
            for cell in (.04,.02):
                with self.subTest(material=material,cell=cell):
                    design,_ = workshop_components.design_from_spec({"kind":"table",
                        "parameters":{"material":material},"component_overrides":{
                            "leg-1":{"skin":{"profile":"curve","bend_m":.12,"physical":True}}}})
                    setup = workshop_sparse_trial.prototype_scene(design,load_kg=10,cell_size_m=cell)
                    session = live_session.Session(ENGINE,setup["spec"],self.app.runs_path)
                    try:
                        snap = session.send(op="snapshot")["snapshot"]
                        proof = workshop_sparse_trial.verify_engine_matter(snap,setup["matter"],setup["root_body"],
                            placement_grid=setup["placement_grid"])
                        self.assertTrue(proof["engine_grid_verified"])
                        self.assertEqual(setup["matter_cells"],proof["engine_cells"])
                    finally:session.close()

    def test_trace_toggle_does_not_change_cart_physics(self):
        design=assemble("cart")
        request={"test":"cart_roll","config":{"speed_m_s":.8,"duration_s":.4}}
        traced=workshop_bench.run(self.app,design,request)
        plain=workshop_bench.run(self.app,design,{"test":"cart_roll",
            "config":{**request["config"],"record_trace":False}})
        self.assertIn("playback",traced)
        self.assertNotIn("playback",plain)
        self.assertEqual(traced["measured"],plain["measured"])

    def test_static_load_proves_native_geometry_and_returns_cell_playback(self):
        result = workshop_bench.run(self.app,assemble("table"),{
            "test":"declared_static_load","config":{"cell_size_m":.04,"duration_s":.2}})
        self.assertTrue(result["prototype"]["engine_grid_verified"])
        self.assertGreater(len(result["playback"]["frames"]),5)
        self.assertEqual("not-declared",result["acceptance"]["status"])
        root=result["prototype"]["root_body"]
        self.assertEqual(result["prototype"]["matter_cells"],len(result["playback"]["geometry"][root]["offsets_m"]))



@unittest.skipUnless(ENGINE is not None and ENGINE.is_file(), "the live world runner is not built")
class DeclaredLimitsUseNativeResults(unittest.TestCase):
    setUp = TheWorkshopRunsRealThings.setUp
    tearDown = TheWorkshopRunsRealThings.tearDown

    def test_declared_limits_do_not_change_glass_oak_iron_physics(self):
        from mcp.workshop_acceptance import evaluate
        for material in ("glass", "oak", "iron"):
            with self.subTest(material=material):
                design = assemble("table", parameters={"material": material})
                config = {"duration_s": .2, "cell_size_m": .04, "record_trace": False}
                observed = workshop_bench.run(self.app, design, {"test": "declared_static_load", "config": config})
                accepted = workshop_bench.run(self.app, design, {"test": "declared_static_load", "config": config,
                    "acceptance_limits": {"max_displacement_m": 1.0, "max_rotation_deg": 180.0}})
                self.assertEqual(observed["measured"], accepted["measured"])
                self.assertEqual("not-declared", observed["acceptance"]["status"])
                self.assertEqual("passed", accepted["acceptance"]["status"], accepted["acceptance"])
                self.assertEqual("failed", evaluate(accepted, {"min_actual_load_kg": 1e9})["status"])
                self.assertNotIn("playback", accepted)



@unittest.skipUnless(ENGINE is not None and ENGINE.is_file(), "the live world runner is not built")
class VisibleSimulationEngine(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.app=type("App",(),{"engine_path":ENGINE,"runs_path":Path(self.tmp.name)})()
        self.app.live=object()

    def test_default_drop_and_slide_complete_for_every_offered_solid(self):
        for kind in ("table","bench"):
            for test in ("drop_product","slide_product"):
                with self.subTest(kind=kind,test=test):
                    outside=self.app.live
                    result=workshop_bench.run(self.app,assemble(kind),{"test":test,"config":{}})
                    self.assertIs(outside,self.app.live)
                    self.assertTrue(result["prototype"]["engine_grid_verified"])
                    self.assertAlmostEqual(1.5,result["measured"]["clock_s"],places=6)
                    frames=result["playback"]["frames"]
                    self.assertGreater(len(frames),20)
                    self.assertNotEqual(frames[0]["bodies"][0]["position_m"],frames[-1]["bodies"][0]["position_m"])
                    self.assertGreater(result["measured"]["prototype_displacement_m"],.02)

    def test_gravity_not_a_script_moves_glass_oak_and_iron(self):
        for material in ("glass","oak","iron"):
            with self.subTest(material=material):
                r=workshop_bench.run(self.app,assemble("table",parameters={"material":material}),
                    {"test":"drop_product","config":{"height_m":.4,"duration_s":.15}})
                m=r["measured"];fall=m["start_position_m"][1]-m["end_position_m"][1]
                # Native semi-implicit 1/120 s gravity: finite-step error bounded explicitly.
                self.assertAlmostEqual(.5*9.81*.15**2,fall,delta=.008)
                self.assertTrue(r["prototype"]["engine_grid_verified"])
                self.assertEqual(0,m["fracture_events"])

    def test_kettle_has_intermediate_measured_temperatures_not_only_final_numbers(self):
        r=workshop_bench.run(self.app,assemble("kettle"),{"test":"kettle_heat","config":{"duration_s":30}})
        frames=r["playback"]["frames"]
        temperatures=[next(b["temperature_k"] for b in f["thermo"]["bodies"] if b["name"]=="water charge")
                      for f in frames if f.get("thermo")]
        self.assertGreater(len(temperatures),10)
        self.assertGreater(temperatures[-1],temperatures[0]+.1)
        self.assertGreater(temperatures[len(temperatures)//2],temperatures[0])

    def test_load_control_changes_the_actual_native_test_mass(self):
        results=[workshop_bench.run(self.app,assemble("table"),{"test":"declared_static_load",
                 "config":{"load_kg":load,"duration_s":.2}}) for load in (5,30)]
        self.assertLess(results[0]["measured"]["actual_grid_load_kg"],results[1]["measured"]["actual_grid_load_kg"])
        self.assertEqual(5,results[0]["requested"]["load_kg"])
        self.assertEqual(30,results[1]["requested"]["load_kg"])


if __name__ == "__main__": unittest.main()
