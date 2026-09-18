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
import time
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

    def _every_body_is_drawn_as_its_own_cells(self, result):
        playback = result["playback"]
        for frame in (playback["frames"][0], playback["frames"][-1]):
            for body in frame["bodies"]:
                shape = playback["geometry"].get(body["name"])
                self.assertIsNotNone(shape, body["name"])
                self.assertEqual(int(body.get("revision") or 0), int(shape["revision"]), body["name"])
        drawn = sum(len(playback["geometry"][b["name"]]["offsets_m"]) for b in playback["frames"][-1]["bodies"]
                    if b["name"].startswith(result["prototype"]["root_body"]))
        self.assertEqual(result["prototype"]["matter_cells"], drawn, "matter was lost or made in the break")

    def test_a_glass_table_breaks_in_a_drop_an_oak_one_survives(self):
        results = {m: workshop_bench.run(self.app, assemble("table", parameters={"material": m}),
                   {"test": "drop_product", "config": {"height_m": 4.0, "duration_s": 1.7}}) for m in ("glass", "oak")}
        glass, oak = results["glass"]["measured"], results["oak"]["measured"]
        for m in (glass, oak):
            self.assertTrue(m["landed"], m)
            self.assertAlmostEqual((2 * 9.81 * 4) ** .5, m["hardest_impact"]["closing_speed_m_s"], delta=.2)
        # The engine's own bar is what separates them, not a rule written here.
        self.assertGreater(glass["hardest_impact"]["closing_speed_m_s"], glass["hardest_impact"]["threshold_speed_m_s"])
        self.assertLess(oak["hardest_impact"]["closing_speed_m_s"], oak["hardest_impact"]["threshold_speed_m_s"])
        self.assertEqual("broke", glass["outcome"], glass)
        self.assertGreater(glass["pieces"], 4, glass)
        self.assertEqual(glass["pieces"], len([b for b in results["glass"]["playback"]["frames"][-1]["bodies"]]))
        self.assertEqual(("held", 1, 0), (oak["outcome"], oak["pieces"], oak["fracture_events"]), oak)
        for result in results.values():
            self._every_body_is_drawn_as_its_own_cells(result)

    def test_a_harder_landing_never_holds_where_a_softer_one_broke(self):
        # At 1/120 s a table landing at 10.8 m/s is caught up to 90 mm into the
        # floor, and the engine used to refuse that run as "buried": 4 m broke
        # into 40, and 6, 10 and 16 m said would_break and answered "held".
        for height in (4.0, 6.0, 10.0, 16.0):
            with self.subTest(height=height):
                r = workshop_bench.run(self.app, assemble("table", parameters={"material": "glass"}),
                    {"test": "drop_product", "config": {"height_m": height, "duration_s": round((2*height/9.81)**.5 + .3, 2),
                                                        "record_trace": False}})
                self.assertTrue(r["measured"]["hardest_impact"]["would_break"], r["measured"])
                self.assertEqual("broke", r["measured"]["outcome"], r["measured"])
                self.assertGreater(r["measured"]["pieces"], 4, r["measured"])

    def test_a_blow_breaks_glass_and_only_shoves_oak(self):
        config = {"striker_kg": 5.0, "speed_m_s": 8.0, "height_fraction": 1.0, "duration_s": 1.0}
        results = {m: workshop_bench.run(self.app, assemble("table", parameters={"material": m}),
                   {"test": "impact_product", "config": config}) for m in ("glass", "oak")}
        for result in results.values():
            striker = result["requested"]["striker"]
            self.assertAlmostEqual(.5 * striker["actual_kg"] * 64, striker["energy_j"], places=6)
            self.assertEqual("workshop/striker", result["measured"]["hardest_impact"]["by"])
            self.assertAlmostEqual(8.0, result["measured"]["hardest_impact"]["closing_speed_m_s"], delta=.1)
            self._every_body_is_drawn_as_its_own_cells(result)
        self.assertEqual("broke", results["glass"]["measured"]["outcome"], results["glass"]["measured"])
        self.assertGreater(results["glass"]["measured"]["pieces"], 1)
        oak = results["oak"]["measured"]
        self.assertEqual(("held", 1), (oak["outcome"], oak["pieces"]), oak)
        self.assertGreater(oak["prototype_displacement_m"], .001, "the blow did not even move it")

    def test_a_load_its_material_cannot_carry_makes_a_table_give(self):
        # A table is one body with nothing under it but the ground, and the
        # engine's load survey looked only for a beam held up by other bodies:
        # five tonnes on a glass table was never once asked about. Its feet, the
        # span between them and the section bridging it are now its own cells.
        # Two metres of 40 mm concrete, two cells deep, under 300 kg.
        long_table = assemble("table", parameters={"material": "concrete", "width_m": 2.0, "depth_m": .5})
        started = time.monotonic()
        r = workshop_bench.run(self.app, long_table, {"test": "declared_static_load",
            "config": {"load_kg": 300.0, "duration_s": 1.5, "cell_size_m": .02}})
        m = r["measured"]
        self.assertEqual("broke", m["outcome"], m)
        self.assertGreater(m["pieces"], 1, m)
        self.assertGreater(m["overload"]["stress_mpa"], m["overload"]["holds_mpa"], m["overload"])
        self.assertAlmostEqual(1.84, m["overload"]["span_m"], delta=.05)
        self.assertEqual("broke", m["statics"]["stop"], m["statics"])
        self.assertGreater(m["statics"]["ratio"], 1.0, m["statics"])
        # The wreck is shown falling and then the run stops: what lands on what
        # is not asked about, which went on without end.
        self.assertLess(m["clock_s"], m["first_break_s"] + .6 + 1e-6)
        self.assertLess(time.monotonic() - started, 60)
        self._every_body_is_drawn_as_its_own_cells(r)

    def test_a_load_it_can_carry_is_held_and_says_by_how_much(self):
        r = workshop_bench.run(self.app, assemble("table", parameters={"material": "concrete"}),
            {"test": "declared_static_load", "config": {"load_kg": 400.0, "duration_s": 1.0, "cell_size_m": .02}})
        m = r["measured"]
        self.assertEqual(("held", 1), (m["outcome"], m["pieces"]), m)
        # Beam theory called it overloaded, which is what that bound is for...
        self.assertGreater(m["overload"]["stress_mpa"], m["overload"]["holds_mpa"], m["overload"])
        # ...and statics on its own cells said it holds, and how near it came.
        self.assertEqual("held", m["statics"]["stop"], m["statics"])
        self.assertGreater(m["statics"]["ratio"], .3)
        self.assertLess(m["statics"]["ratio"], 1.0)
        # Oak under the same load is never asked about at all.
        oak = workshop_bench.run(self.app, assemble("table"), {"test": "declared_static_load",
            "config": {"load_kg": 400.0, "duration_s": .5, "cell_size_m": .02, "record_trace": False}})["measured"]
        self.assertEqual(("held", None, None), (oak["outcome"], oak["overload"], oak["statics"]), oak)

    def test_a_ceramic_table_can_be_tested_at_all(self):
        design = assemble("table", parameters={"material": "alumina ceramic"})
        for request in ({"test": "declared_static_load", "config": {"load_kg": 50.0, "duration_s": .3}},
                        {"test": "drop_product", "config": {"height_m": .4, "duration_s": .5}}):
            with self.subTest(test=request["test"]):
                self.assertTrue(workshop_bench.run(self.app, design, request)["prototype"]["engine_grid_verified"])

    def test_a_broken_table_comes_apart_at_its_joints_into_its_own_parts(self):
        # The product is one fused body, and it is still a top on four legs: what
        # a blow or a landing parts is the joint, and each leg comes away whole
        # -- all of it but the one cell let into the top -- whichever way it broke.
        import workshop_motion
        for material, test, config in (("oak", "impact_product", {"striker_kg": 20.0, "speed_m_s": 15.0}),
                                       ("glass", "drop_product", {"height_m": 4.0, "duration_s": 1.7}),
                                       ("oak", "drop_product", {"height_m": 10.0, "duration_s": 2.2})):
            with self.subTest(material=material, test=test):
                design = assemble("table", parameters={"material": material})
                parts = workshop_motion.scene(design, test, config)["matter"]["component_cell_counts"]
                r = workshop_bench.run(self.app, design, {"test": test, "config": config})
                shapes = r["playback"]["geometry"]
                sizes = sorted((len(shapes[b["name"]]["offsets_m"]) for b in r["playback"]["frames"][-1]["bodies"]
                                if b["name"].startswith(r["prototype"]["root_body"])), reverse=True)
                legs = [n for n in sizes if parts["leg-1"] - 1 <= n <= parts["leg-1"]]
                self.assertEqual(4, len(legs), sizes)
                self.assertGreater(sizes[0], .85 * parts["top"], sizes)
                self.assertEqual(sum(parts.values()), sum(sizes))

    def test_a_drop_that_ended_in_the_air_says_so(self):
        r = workshop_bench.run(self.app, assemble("table", parameters={"material": "glass"}),
            {"test": "drop_product", "config": {"height_m": 10.0, "duration_s": .5}})
        self.assertFalse(r["measured"]["landed"])
        self.assertEqual("held", r["measured"]["outcome"])
        self.assertAlmostEqual(.5, r["measured"]["clock_s"], places=6)
        self.assertGreater(r["requested"]["settled_duration_s"], r["requested"]["fall_time_s"])
        self.assertAlmostEqual((2 * 10.0 / 9.81) ** .5, r["requested"]["fall_time_s"], delta=.02)

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


@unittest.skipUnless(ENGINE is not None and ENGINE.is_file(), "the live world runner is not built")
class VisibleTestSetup(unittest.TestCase):
    setUp = TheWorkshopRunsRealThings.setUp
    tearDown = TheWorkshopRunsRealThings.tearDown

    def test_every_offered_lattice_scene_is_visible_at_zero_without_advancing(self):
        import workshop_setup, live_session
        from unittest.mock import patch
        send=live_session.Session.send
        operations=[]
        def checked(session, **kwargs):
            operations.append(kwargs.get("op"))
            self.assertNotIn(kwargs.get("op"), {"step","advance","fracture"})
            return send(session, **kwargs)
        with patch.object(live_session.Session,"send",checked):
            for kind,test in [("table","drop_product"),("table","slide_product"),
                              ("table","impact_product"),("table","declared_static_load"),
                              ("cart","cart_roll"),("kettle","kettle_heat")]:
                with self.subTest(test=test):
                    answer=workshop_setup.preview(self.app,assemble(kind),{"test":test,"config":{}})
                    self.assertTrue(answer["native_verified"])
                    self.assertFalse(answer["physics_advanced"])
                    self.assertEqual("setup",answer["phase"])
                    self.assertEqual(1,len(answer["frames"]))
                    self.assertEqual(0,answer["frames"][0]["t_s"])
                    self.assertTrue(answer["frames"][0]["bodies"])
                    self.assertTrue(answer["geometry"])
                    if test in {"declared_static_load","impact_product"}:
                        self.assertEqual(2,len(answer["frames"][0]["bodies"]))
        self.assertIn("snapshot",operations)
        self.assertEqual([], list((Path(self.app.runs_path) / "workshop-setup").iterdir()), "Setup previews must not accumulate scene files")

    def test_preview_and_run_share_initial_native_cells_for_glass_oak_iron(self):
        import workshop_setup, json
        for material in ("glass","oak","iron"):
            with self.subTest(material=material):
                design=assemble("table",parameters={"material":material})
                config={"height_m":.2,"duration_s":.3,"cell_size_m":.04}
                preview=workshop_setup.preview(self.app,design,{"test":"drop_product","config":config})
                actual=workshop_bench.run(self.app,design,{"test":"drop_product","config":config})
                self.assertTrue(json.dumps(preview["geometry"],sort_keys=True) == json.dumps({k:v for k,v in actual["playback"]["geometry"].items() if k in preview["geometry"]},sort_keys=True), "Initial native cell geometry must match")
                self.assertTrue(preview["frames"][0]["bodies"] == actual["playback"]["frames"][0]["bodies"], "Initial native poses must match")
                self.assertGreater(actual["playback"]["duration_s"],0)

    def test_rigid_setup_preserves_thin_dimensions_without_claiming_native_validation(self):
        import workshop_setup
        from mcp import workshop_components
        design,_=workshop_components.design_from_spec({"kind":"table","parameters":{
            "top_thickness_m":.005,"leg_section_m":.015},"component_overrides":{
                n:{"mechanics":{"model":"rigid"}} for n in ("top","leg-1","leg-2","leg-3","leg-4")}})
        preview=workshop_setup.preview(self.app,design,{"test":"rigid_motion","config":{}})
        self.assertFalse(preview["native_verified"])
        self.assertEqual(5,len(preview["frames"][0]["bodies"]))
        self.assertEqual(.005,preview["frames"][0]["bodies"][0]["dimensions_m"][1])

    def test_setup_rejects_unavailable_tests_and_invalid_settings(self):
        import workshop_setup
        for request in ({"test":"force_probe"},{"test":"drop_product","config":{"height_m":True}},
                        {"test":"drop_product","config":{"height_m":float("nan")}},
                        {"test":"drop_product","geometry":{}},{"test":"drop_product","config":[] } ):
            with self.subTest(request=request),self.assertRaises(ValueError):
                workshop_setup.preview(self.app,assemble("table"),request)


if __name__ == "__main__": unittest.main()
