"""Fast contracts for Workshop's isolated functional/compilation test bench."""
from __future__ import annotations
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "playground"))

import workshop_bench  # noqa: E402
import workshop_library  # noqa: E402
from mcp.workshop import assemble  # noqa: E402


class App:
    def __init__(self, root: Path) -> None:
        self.engine_path = root / "fake-engine"; self.runs_path = root / "runs"
        self.workshop_db = root / "banjo.db"; self.live = object()


class FakeKettleSession:
    def __init__(self, engine, spec, runs):
        self.spec, self.closed = spec, False; self.state = {"t": 0.0, "bodies": []}; self.thermo_calls = 0
    def send(self, **command):
        op = command.get("op")
        if op == "thermo":
            self.thermo_calls += 1; t = 293.15 if self.thermo_calls == 1 else 335.15
            return {"ok": True, "thermo": {"bodies": [
                {"name": "water charge", "temperature_k": t, "contents_kg": {"moisture": 1.0}},
                {"name": "kettle-bottom", "temperature_k": 350.0},
                {"name": "heater plate", "temperature_k": 500.0},
            ], "ledger": {"heater_in_j": 216000.0, "residual_j": 0.0}}}
        if op == "step":
            self.state = {"ok": True, "t": self.state["t"] + command.get("dt", 0) * command.get("n", 1), "bodies": []}
            return self.state
        raise AssertionError(op)
    def close(self): self.closed = True


class FakeMachineSession:
    def __init__(self):
        self.id = "scratch"
        self.state = {"t": 0.0, "bodies": [{"name": "load", "position_m": [0.1, 0.45, 0.0]}],
                      "machines": {"controls": [{"id": 7, "name": "hoist", "condition": "stopped"}]}}
    def send(self, **command):
        op = command.get("op")
        if op == "operate":
            self.state["machines"]["controls"] = [{"id": 7, "name": "hoist", "power": command.get("power"),
                "direction": command.get("direction"), "setting": command.get("setting"), "condition": "running", "speed_rpm": 55.0}]
            return {"ok": True, "operated": "applied", "control": self.state["machines"]["controls"][0]}
        if op == "step":
            self.state["t"] += command.get("dt", 0) * command.get("n", 1); self.state["bodies"][0]["position_m"][1] += 0.01
            self.state["machines"].update({"motors": [{"power_w": 120.0, "current_a": 5.0, "heat_j": 2.0}],
                "stores": [{"charge_j": 4800.0, "given_j": 200.0}], "ropes": [{"out_m": 1.2, "rope_speed_m_s": -0.1}]})
            return {"ok": True, **self.state}
        if op == "poses": return {"ok": True, **self.state}
        raise AssertionError(op)


class FakeLive:
    last = None
    def __init__(self): self.session = FakeMachineSession(); self.closed = False; FakeLive.last = self
    def open(self, app, body):
        return {"session": self.session.id, "machines": {"controls": [{"id": 7, "name": "hoist", "condition": "stopped"}]},
                "bodies": list(self.session.state["bodies"])}
    def shutdown(self): self.closed = True


class BenchCatalog(unittest.TestCase):
    def test_generic_force_cart_kettle_and_machine_are_bench_operations(self):
        tests = {t["test"]: t for t in workshop_bench.catalog()}
        self.assertTrue({"runtime_contract", "force_probe", "cart_roll", "kettle_heat", "machine_control"} <= set(tests))
        self.assertEqual(["cart"], tests["cart_roll"]["kinds"])
        self.assertEqual(["kettle"], tests["kettle_heat"]["kinds"])
        self.assertIn("water_kg", {c["name"] for c in tests["kettle_heat"]["controls"]})


class IsolatedBench(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name); self.app = App(self.root)
    def tearDown(self): self.tmp.cleanup()

    def test_runtime_contract_compiles_current_design_without_an_engine(self):
        design = assemble("table", design_id="candidate"); outside = self.app.live
        result = workshop_bench.run(self.app, design, {"test": "runtime_contract", "config": {}})
        self.assertIs(self.app.live, outside)
        self.assertEqual("banjo.product-graph.v1", result["product_graph"]["schema"])
        self.assertEqual("banjo.physics-contract.v1", result["physics_contract"]["schema"])
        self.assertEqual(len(design.parts), result["summary"]["detailed_components"])
        self.assertAlmostEqual(design.measure()["mass_kg"], result["summary"]["mass_kg"], places=2)

    def test_force_probe_uses_clicked_point_and_authored_load_paths(self):
        design = assemble("table", design_id="force-table")
        top = next(p for p in design.parts if p.name == "top")
        result = workshop_bench.run(self.app, design, {"test": "force_probe", "config": {
            "component": "top", "point_m": [0.2, top.center_m[1] + top.size_m[1] / 2, 0.1],
            "direction": [0, -1, 0], "force_n": 800, "duration_s": 0.05}})
        self.assertEqual("analytical-estimate", result["evidence"])
        self.assertAlmostEqual(40.0, result["impulse_magnitude_n_s"])
        self.assertTrue(result["load_paths"])
        self.assertTrue(result["support_reactions"])
        self.assertAlmostEqual(800.0, result["downward_force_n"])

    def test_kettle_uses_selected_design_capacity_material_and_geometry(self):
        design = assemble("kettle", design_id="candidate-kettle",
                          parameters={"width_m": 0.30, "depth_m": 0.24, "vessel_height_m": 0.20,
                                      "wall_thickness_m": 0.01, "material": "aluminium"})
        outside = self.app.live
        with mock.patch.object(workshop_bench.live_session, "Session", FakeKettleSession):
            result = workshop_bench.run(self.app, design, {"test": "kettle_heat", "config": {
                "water_kg": 1.0, "duration_s": 120, "heater_power_w": 1800}})
        self.assertIs(self.app.live, outside); self.assertEqual("engine-trial", result["evidence"])
        self.assertGreater(result["design"]["capacity_l"], 1.0)
        self.assertEqual("aluminium", result["design"]["material"])
        self.assertEqual([0.3, 0.01, 0.24], result["design"]["bottom_m"])
        self.assertEqual(293.15, result["measured"]["water_start_k"])
        self.assertEqual(335.15, result["measured"]["water_end_k"])
        self.assertIn("free-surface", result["limitations"][0])

    def test_cart_scratch_spec_has_two_free_pins_and_four_wheels(self):
        design = assemble("cart", design_id="rolling-cart")
        spec, root, axles = workshop_bench._cart_spec(design, 0.8)
        self.assertEqual("deck", root); self.assertEqual(["axle-1", "axle-2"], axles)
        hinges = [j for j in spec["joints"] if j["kind"] == "hinge"]
        fixing = [j for j in spec["joints"] if j["kind"] == "fixing"]
        self.assertEqual(2, len(hinges)); self.assertEqual(4, len(fixing))
        self.assertEqual(4, len([b for b in spec["bodies"] if b["shape"] == "sphere"]))
        self.assertTrue(all(j["lower_deg"] == -180 and j["upper_deg"] == 180 for j in hinges))

    def test_machine_edits_the_real_controller_contract_and_owns_its_session(self):
        design = assemble("table", design_id="candidate"); outside = self.app.live
        with mock.patch.object(workshop_bench.live_session, "Live", FakeLive):
            result = workshop_bench.run(self.app, design, {"test": "machine_control", "config": {
                "power": True, "direction": -1, "setting": 35, "duration_s": 0.5, "load_kg": 20}})
        self.assertIs(self.app.live, outside); self.assertTrue(FakeLive.last.closed)
        self.assertEqual("applied", result["measured"]["acknowledgement"])
        self.assertEqual(-1, result["measured"]["control"]["direction"])
        self.assertAlmostEqual(0.35, result["measured"]["control"]["setting"])

    def test_bench_presets_are_owner_scoped_and_persistent(self):
        one = workshop_library.save_bench_preset(self.app, name="Half speed lift", test_name="machine_control",
                                                  config={"power": True, "direction": 1, "setting": 50})
        self.assertEqual("machine_control", one["test"])
        other = App(self.root); other.workshop_owner_id = "someone-else"
        self.assertEqual([], workshop_library.list_bench_presets(other))



class ExplicitLoadAcceptance(unittest.TestCase):
    def result(self):
        return {"evidence": "engine-trial", "trial": "static_load", "design_id": "table-1",
                "requested": {"duration_s": 2.0, "load_kg": 100.0},
                "prototype": {"engine_grid_verified": True, "matter_physics_hash": "a" * 64,
                              "effective_cell_size_m": .04},
                "measured": {"clock_s": 2.0, "prototype_present": True, "load_present": True,
                             "prototype_displacement_m": .005, "prototype_rotation_change_deg": .5,
                             "fractures": [], "actual_grid_load_kg": 99.3},
                "acceptance": {"status": "not-declared"}}

    def test_no_limits_leave_an_observation_not_a_pass(self):
        from mcp import workshop_acceptance as acceptance
        self.assertEqual("not-declared", acceptance.evaluate(self.result(), None)["status"])

    def test_limits_pass_only_for_the_measured_run_and_keep_exact_basis(self):
        from mcp import workshop_acceptance as acceptance
        result = acceptance.evaluate(self.result(), {"max_displacement_m": .01, "max_fractures": 0})
        self.assertEqual("passed", result["status"])
        self.assertEqual("this-exact-run", result["scope"])
        self.assertEqual("a" * 64, result["basis"]["matter_physics_hash"])
        self.assertEqual(99.3, result["basis"]["actual_grid_load_kg"])
        self.assertNotIn("validated_range", result)

    def test_exceeded_limit_is_failed_and_names_the_measurement(self):
        from mcp import workshop_acceptance as acceptance
        result = acceptance.evaluate(self.result(), {"max_displacement_m": .004})
        self.assertEqual("failed", result["status"])
        failure = next(c for c in result["checks"] if c["status"] == "failed")
        self.assertEqual("prototype_displacement_m", failure["metric"])
        self.assertEqual(.005, failure["measured"])

    def test_missing_nonfinite_boolean_and_negative_measurements_cannot_pass(self):
        from mcp import workshop_acceptance as acceptance
        for value in (None, float("nan"), float("inf"), True, -.01):
            with self.subTest(value=value):
                trial = self.result(); trial["measured"]["prototype_displacement_m"] = value
                checked = acceptance.evaluate(trial, {"max_displacement_m": .01})
                self.assertEqual("unsupported", checked["status"])
                self.assertIsNone(checked["checks"][-1]["measured"])

    def test_early_stop_lost_body_or_unverified_geometry_cannot_pass(self):
        from mcp import workshop_acceptance as acceptance
        for section, key, value in (("measured", "clock_s", 1.0),
                                    ("measured", "prototype_present", False),
                                    ("measured", "load_present", False),
                                    ("prototype", "engine_grid_verified", False),
                                    ("prototype", "matter_physics_hash", None)):
            with self.subTest(key=key):
                trial = self.result(); trial[section][key] = value
                self.assertEqual("failed", acceptance.evaluate(trial, {"max_fractures": 0})["status"])

    def test_actual_quantized_load_can_be_required_not_just_requested_load(self):
        from mcp import workshop_acceptance as acceptance
        checked = acceptance.evaluate(self.result(), {"min_actual_load_kg": 100.0})
        self.assertEqual("failed", checked["status"])

    def test_bad_limits_are_refused_before_engine_work(self):
        import workshop_trials
        for limits in ({}, [], {"guess": 1}, {"max_displacement_m": True},
                       {"max_fractures": .5}, {"max_rotation_deg": -1},
                       {"max_displacement_m": float("nan")}, {"max_fractures": 10 ** 400}):
            with self.subTest(limits=str(limits)[:60]), mock.patch.object(workshop_trials, "_BASE_RUN_STATIC") as run:
                with self.assertRaises(ValueError):
                    workshop_trials.run_static_load(None, assemble("table"), load_kg=10,
                                                   acceptance_limits=limits)
                run.assert_not_called()

    def test_request_can_tighten_but_not_relax_declared_limits(self):
        from mcp import workshop_acceptance as acceptance
        self.assertEqual({"max_displacement_m": .01, "min_actual_load_kg": 120.0},
            acceptance.merge_limits({"max_displacement_m": .01, "min_actual_load_kg": 100},
                                    {"max_displacement_m": .1, "min_actual_load_kg": 120}))

    def test_browser_limits_are_opt_in_and_forwarded_through_shared_bench(self):
        with mock.patch.object(workshop_bench.workshop_trials, "run_declared_static_load", return_value={}) as run:
            config = {"max_displacement_m": .01, "max_rotation_deg": 2.0, "max_fractures": 0}
            workshop_bench.run(None, assemble("table"), {"test": "declared_static_load", "config": config})
            self.assertIsNone(run.call_args.kwargs["acceptance_limits"])
            workshop_bench.run(None, assemble("table"), {"test": "declared_static_load",
                               "config": {**config, "evaluate_limits": True}})
            self.assertEqual(config, run.call_args.kwargs["acceptance_limits"])

    def test_mcp_config_limits_reach_the_same_trial_and_presets_keep_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = App(Path(tmp))
            config = {"acceptance_limits": {"max_fractures": 0}, "record_trace": False}
            saved = workshop_library.save_bench_preset(app, name="No fracture", test_name="declared_static_load", config=config)
            self.assertEqual(config, saved["config"])
            with mock.patch.object(workshop_bench.workshop_trials, "run_declared_static_load", return_value={}) as run:
                workshop_bench.run(app, assemble("table"), {"test": saved["test"], "config": saved["config"]})
                self.assertEqual({"max_fractures": 0}, run.call_args.kwargs["acceptance_limits"])

    def test_limits_do_not_certify_a_different_reference_fixture(self):
        with mock.patch.object(workshop_bench._core, "run") as run:
            with self.assertRaisesRegex(ValueError, "exact-Matter"):
                workshop_bench.run(None, assemble("table"), {"test": "machine_control", "acceptance_limits": {"max_fractures": 0}})
            run.assert_not_called()

    def test_static_observation_import_keeps_geometry_and_does_not_alias(self):
        from mcp.product_evidence import from_bench
        original = self.result()
        item = from_bench(original, evidence_id="test-1")
        self.assertEqual("observed", item["acceptance"]["status"])
        self.assertEqual("not-declared", item["acceptance"]["original_status"])
        self.assertEqual("a" * 64, item["conditions"]["prototype"]["matter_physics_hash"])
        original["measured"]["fractures"].append({"name": "bad"})
        original["prototype"]["matter_physics_hash"] = "changed"
        self.assertEqual([], item["measured"]["fractures"])
        self.assertEqual("a" * 64, item["conditions"]["prototype"]["matter_physics_hash"])

    def test_passed_run_import_does_not_invent_a_validated_range(self):
        from mcp import workshop_acceptance
        from mcp.product_evidence import from_bench, envelope
        original = self.result()
        original["acceptance"] = workshop_acceptance.evaluate(original, {"max_fractures": 0})
        item = from_bench(original, evidence_id="test-2")
        original["acceptance"]["checks"][0]["status"] = "failed"
        self.assertEqual("passed", item["acceptance"]["checks"][0]["status"])
        self.assertEqual({}, envelope([item]))



class VisibleSimulationContract(unittest.TestCase):
    def test_motion_does_not_ignore_bad_flags_or_unsupported_limits(self):
        for request in ({"test":"drop_product","config":{"record_trace":"false"}},
                        {"test":"drop_product","acceptance_limits":{"max_displacement_m":1}}):
            with self.subTest(request=request), self.assertRaises(ValueError):
                workshop_bench.run(None, assemble("table"), request)

    def test_only_real_selected_subjects_are_offered_as_simulations(self):
        for kind, expected in {"table":{"drop_product","slide_product","declared_static_load"},
                               "bench":{"drop_product","slide_product","declared_static_load"},
                               "cart":{"cart_roll"},"kettle":{"kettle_heat"},
                               "chair":set(),"stool":set(),"shelf-unit":set()}.items():
            visible = {t["test"] for t in workshop_bench.catalog(kind)
                       if t.get("category")=="simulation" and t.get("subject")=="selected-product"}
            self.assertEqual(expected,visible,kind)

    def test_motion_recipe_keeps_exact_cells_and_declares_only_initial_motion(self):
        import workshop_motion as motion
        design=assemble("table")
        drop=motion.scene(design,"drop_product",{"height_m":.21})
        slide=motion.scene(design,"slide_product",{"speed_m_s":2})
        self.assertEqual(drop["matter"]["physics_hash"],slide["matter"]["physics_hash"])
        self.assertAlmostEqual(.2,drop["applied_height_m"])
        self.assertTrue(all(b["velocity_m_s"]==[0,0,0] for b in drop["spec"]["bodies"]))
        self.assertTrue(all(b["velocity_m_s"]==[2,0,0] for b in slide["spec"]["bodies"]))
        self.assertTrue(all(b["name"].startswith("workshop/product") for b in drop["spec"]["bodies"]))

    def test_motion_rejects_invalid_inputs_without_starting_engine(self):
        import workshop_motion as motion
        with mock.patch.object(motion.live_session,"Session") as engine:
            for field,value in [("height_m",float("nan")),("height_m",True),("height_m",-1),
                                ("duration_s",100),("cell_size_m",0),("cell_size_m","0.04")]:
                with self.subTest(field=field,value=value), self.assertRaises(ValueError):
                    motion.run(None,assemble("table"),"drop_product",{field:value})
            engine.assert_not_called()

    def test_missing_parts_and_articulated_products_never_become_a_different_test(self):
        import workshop_motion as motion
        with self.assertRaisesRegex(ValueError,"disappear"):
            motion.scene(assemble("table",parameters={"top_thickness_m":.005,"leg_section_m":.015}),"drop_product",{})
        for kind in ["cart","kettle"]:
            with self.assertRaisesRegex(ValueError,"structural solids"):
                motion.scene(assemble(kind),"drop_product",{})

    def test_chosen_load_is_forwarded_without_replacing_the_target(self):
        design=assemble("table")
        with mock.patch.object(workshop_bench.workshop_trials,"run_static_load",return_value={}) as run:
            workshop_bench.run(None,design,{"test":"declared_static_load","config":{"load_kg":12.5}})
        self.assertEqual(12.5,run.call_args.kwargs["load_kg"])
        self.assertEqual("top",run.call_args.kwargs["on"])

    def test_load_does_not_test_a_product_with_a_missing_top(self):
        from workshop_sparse_trial import prototype_scene
        with self.assertRaisesRegex(ValueError,"disappear"):
            prototype_scene(assemble("table",parameters={"top_thickness_m":.005}),load_kg=10)


if __name__ == "__main__": unittest.main()
