"""Public typed-plan and archive coverage for numeric thermal experiments."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))
sys.path.insert(0, str(ROOT / "tests"))
from control_contract import default_ui
import experiment_language as language
import server
from thermal_material import execute_experiment, native_request
from playground_tests import InlineExecutor


def material(reactive=True, name="renamed reactive material"):
    value = {"id": 1, "name": name, "density_kg_m3": 700.0,
             "heat_capacity_j_kg_k": 1700.0, "conductivity_w_m_k": 0.12}
    if reactive:
        value.update({"fuel_fraction": 0.1, "oxygen_per_kg_solid": 0.15,
                      "reaction": {"activation_temperature_k": 600.0,
                                   "rate_per_s": 20.0,
                                   "heat_of_combustion_j_kg": 16e6,
                                   "oxygen_per_kg_fuel": 1.5}})
    return value


def thermal(material_value=None, limits=None):
    return {"voxel_size_m": 0.02, "materials": [material_value or material()],
            "cells": [{"chunk": [0, 0, 0], "local": [8, 8, 8], "material": 1,
                       "temperature_k": 300.0},
                      {"chunk": [0, 0, 0], "local": [9, 8, 8], "material": 1,
                       "temperature_k": 300.0}],
            "heater": {"cell_index": 0, "energy_j": 3000.0,
                       "maximum_energy_j": 3000.0},
            "step_s": 0.01, "horizon_s": 0.1,
            "limits": limits or {"maximum_jobs": 64,
                                 "maximum_cell_operations": 10000,
                                 "maximum_wall_ms": 1000.0,
                                 "maximum_frames": 16}}


def proposal(material_value=None, limits=None):
    specification = thermal(material_value, limits)
    return {"name": "Authored thermal cells",
            "explanation": "Run explicit numeric solid thermal properties.",
            "limitations": ["No airflow or mechanical coupling."],
            "duration_s": specification["horizon_s"],
            "ui": default_ui("thermal_material_experiment"),
            "requirements": [], "fidelity": "experimental",
            "setup": {"kind": "thermal_material_experiment", "thermal": specification}}


def phase_proposal():
    phase = {"id": 1, "name": "fictional phase plateau demonstrator",
             "density_kg_m3": 1000.0, "heat_capacity_j_kg_k": 2100.0,
             "conductivity_w_m_k": 2.2,
             "phase_change": {"liquid_heat_capacity_j_kg_k": 4180.0,
                              "melting_temperature_k": 273.15,
                              "latent_heat_j_kg": 334000.0}}
    value = proposal(phase)
    value["explanation"] = "Illustrative uncalibrated numeric phase-change plateau."
    for cell in value["setup"]["thermal"]["cells"]:
        cell["temperature_k"] = 270.0
    value["setup"]["thermal"]["heater"] = {
        "cell_index": 0, "energy_j": 1000.0, "maximum_energy_j": 1000.0}
    return value


def recording(request, limited=False):
    completed = 0.01 if limited else 0.1
    ledger = {"external_work_j": 3000.0, "reaction_heat_j": 100.0,
              "combined_energy_residual_j": 0.0, "mass_residual_kg": 0.0,
              "lag_s": 0.0}
    frames = [{"time_s": 0.0, "cells": [{}, {}], "ledger": ledger},
              {"time_s": completed, "cells": [{}, {}], "ledger": ledger}]
    result = {"schema": "banjo.thermal-experiment-response.v1",
              "status": "solver_limit" if limited else "complete", "request": request,
              "frames": frames, "completed_time_s": completed,
              "requested_horizon_s": 0.1,
              "remaining_duration_s": 0.09 if limited else 0.0,
              "scheduler_backlog_s": 0.0,
              "work": {"completed_jobs": 1, "cell_operations": 6,
                       "wall_ms": 0.01, "maximum_frames": 16},
              "final_ledger": ledger,
              "limitations": ["insulated fixed-grid solid thermal reference",
                              "no airflow, smoke, radiation, moisture transport or calibrated combustion",
                              "phase change and reaction cannot be combined",
                              "no mechanical deformation, contact, fracture or thermal expansion coupling"]}
    if limited:
        result["error"] = "Cumulative experiment work limit exhausted"
    return result


class ThermalMaterialRouteTests(unittest.TestCase):
    def test_planner_guidance_matches_fixed_cell_playback_capability(self):
        thermal_guidance = language.SYSTEM.split("Use thermal_material_experiment", 1)[1]
        self.assertIn("fixed-cell 3D playback", thermal_guidance)
        self.assertIn("labeled temperature color", thermal_guidance)
        self.assertIn("no flame, smoke or fake motion", thermal_guidance)
        self.assertIn("no physical rerun controls", thermal_guidance)
        self.assertNotIn("no 3D thermal playback", thermal_guidance)

    def test_typed_route_preserves_renamed_reactive_and_inert_controls(self):
        descriptors = [material(True, "glass label"),
                       material(False, "oak inert label"),
                       {"id": 1, "name": "iron control", "density_kg_m3": 7870.0,
                        "heat_capacity_j_kg_k": 450.0, "conductivity_w_m_k": 80.0}]
        for descriptor in descriptors:
            source = proposal(descriptor)
            original = deepcopy(source)
            plan = language.lower_proposal(source)
            self.assertEqual(plan["thermal"]["materials"], [descriptor])
            self.assertEqual([control["action"] for control in plan["ui"]["controls"]],
                             ["play_pause", "reset", "step_forward", "step_back",
                              "playback_speed", "frame"])
            self.assertEqual(language.compile_plan(plan), [])
            self.assertEqual(source, original)
        self.assertIn("reaction", language.lower_proposal(proposal(descriptors[0]))["thermal"]["materials"][0])
        self.assertNotIn("reaction", language.lower_proposal(proposal(descriptors[1]))["thermal"]["materials"][0])

    def test_route_rejects_duration_mismatch_and_unsupported_payload(self):
        plan = language.lower_proposal(proposal())
        with self.assertRaisesRegex(ValueError, "must equal"):
            language.validate_plan(dict(plan, duration_s=0.2))
        bad = deepcopy(plan)
        bad["thermal"]["airflow_m_s"] = 2.0
        with self.assertRaisesRegex(ValueError, "Unknown"):
            language.validate_plan(bad)
        bad = deepcopy(plan)
        bad["thermal"]["limits"]["maximum_jobs"] = 4097
        with self.assertRaisesRegex(ValueError, "bounds"):
            language.validate_plan(bad)

    def test_mocked_public_chat_route_archives_full_complete_and_limited_response(self):
        for limited in (False, True):
            with self.subTest(limited=limited), tempfile.TemporaryDirectory() as temp:
                base = Path(temp); engine = base / "engine.exe"; engine.touch()
                plan = language.lower_proposal(proposal())
                request = native_request(plan["thermal"])
                data = recording(request, limited)
                with mock.patch.object(server, "local_configuration", return_value=("", "fake")):
                    app = server.Playground(engine, base / "studio.exe", base / "runs",
                        planner=lambda *args: (deepcopy(plan), {"model": "mock"}))
                app.pool.shutdown(); app.pool = InlineExecutor()
                with mock.patch.object(server, "execute_experiment",
                                       return_value=(data, {"request_sha256": "test"})) as execute:
                    job_id = app.submit({"message": "Run explicit renamed reactive cells",
                                         "request_id": "thermal-request", "auto_open": False})["job_id"]
                job = app.get(job_id); case = job["cases"][0]
                self.assertEqual(job["status"], "complete")
                self.assertEqual(execute.call_args.args[1], plan["thermal"])
                self.assertEqual(case["package"], request)
                self.assertEqual(case["report"], data)
                self.assertEqual(case["status"], data["status"])
                self.assertEqual(case["measured_evidence"]["final_ledger"], data["final_ledger"])
                self.assertTrue(case["playback_available"])
                self.assertIn("temperature legend", job["message"])
                archived = json.loads((base / "runs" / job_id / "thermal-response.json").read_text())
                self.assertEqual(archived, data)
                self.assertEqual(json.loads(app.playback(job_id, 0)), data)
                self.assertEqual(case["diagnostics"]["source_schema"], data["schema"])
                events = (base / "runs" / job_id / "events.jsonl").read_text()
                self.assertIn("thermal_material_recorded", events)
                app.jobs.clear(); app.playbacks.clear()
                restored = app.get(job_id)
                self.assertTrue(restored["cases"][0]["playback_available"])
                self.assertEqual(json.loads(app.playback(job_id, 0)), data)

    def test_actual_native_cli_returns_reaction_and_inert_control_ledgers(self):
        configured = os.environ.get("BANJO_THERMAL_EXPERIMENT_CLI")
        candidates = ([Path(configured)] if configured else []) + [
            ROOT / "build/win-joint-double/Release/banjo_thermal_experiment_cli.exe",
            ROOT / "build/banjo_thermal_experiment_cli"]
        executable = next((path for path in candidates if path.is_file()), None)
        if executable is None:
            self.skipTest("banjo_thermal_experiment_cli is not built")
        reactive, _ = execute_experiment(executable, thermal(material(True, "inert-looking label")))
        inert, _ = execute_experiment(executable, thermal(material(False, "oak display label")))
        self.assertEqual(reactive["status"], "complete")
        self.assertEqual(inert["status"], "complete")
        self.assertGreater(reactive["final_ledger"]["reaction_heat_j"], 0)
        self.assertEqual(inert["final_ledger"]["reaction_heat_j"], 0)
        self.assertEqual(reactive["remaining_duration_s"], 0)
        self.assertEqual(inert["remaining_duration_s"], 0)

    def test_actual_public_route_serves_exact_accepted_cell_states(self):
        engine = ROOT / "build/win-joint-double/Release/banjo_platform_cli.exe"
        thermal_cli = engine.with_name("banjo_thermal_experiment_cli.exe")
        if not engine.is_file() or not thermal_cli.is_file():
            self.skipTest("native playground and thermal executables are not built")
        plan = language.lower_proposal(proposal())
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(
                server, "local_configuration", return_value=("", "fake")):
            app = server.Playground(engine, Path(temp) / "studio.exe", Path(temp) / "runs",
                                    planner=lambda *args: (deepcopy(plan), {"model": "mock"}))
            app.pool.shutdown(); app.pool = InlineExecutor()
            job_id = app.submit({"message": "Run numeric reactive cells",
                                 "request_id": "thermal-native-route",
                                 "auto_open": False})["job_id"]
            job = app.get(job_id)
            playback = json.loads(app.playback(job_id, 0))
        self.assertEqual(job["status"], "complete")
        self.assertEqual(playback, job["cases"][0]["report"])
        authored = {(tuple(cell["chunk"]), tuple(cell["local"]))
                    for cell in job["cases"][0]["package"]["cells"]}
        for frame in playback["frames"]:
            accepted = {(tuple(cell["chunk"]), tuple(cell["local"]))
                        for cell in frame["cells"]}
            self.assertEqual(accepted, authored)
            self.assertTrue(all(cell["temperature_k"] >= 0 for cell in frame["cells"]))
        self.assertEqual(playback["final_ledger"], playback["frames"][-1]["ledger"])

    def test_actual_phase_route_archives_plateau_fraction_and_energy_for_3d(self):
        engine = ROOT / "build/win-joint-double/Release/banjo_platform_cli.exe"
        thermal_cli = engine.with_name("banjo_thermal_experiment_cli.exe")
        if not engine.is_file() or not thermal_cli.is_file():
            self.skipTest("native playground and thermal executables are not built")
        plan = language.lower_proposal(phase_proposal())
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(
                server, "local_configuration", return_value=("", "fake")):
            app = server.Playground(engine, Path(temp) / "studio.exe", Path(temp) / "runs",
                                    planner=lambda *args: (deepcopy(plan), {"model": "mock"}))
            app.pool.shutdown(); app.pool = InlineExecutor()
            job_id = app.submit({"message": "Run explicit fictional phase plateau",
                                 "request_id": "thermal-phase-route",
                                 "auto_open": False})["job_id"]
            job = app.get(job_id)
            playback = json.loads(app.playback(job_id, 0))
        heated = [frame["cells"][0] for frame in playback["frames"]]
        self.assertTrue(all(cell["phase_change"] for cell in heated))
        self.assertTrue(any(0 < cell["liquid_fraction"] < 1 for cell in heated))
        self.assertGreater(max(cell["liquid_fraction"] for cell in heated) -
                           min(cell["liquid_fraction"] for cell in heated), 0)
        plateau = [cell["temperature_k"] for cell in heated if 0 < cell["liquid_fraction"] < 1]
        self.assertTrue(all(abs(value - 273.15) < 1e-9 for value in plateau))
        self.assertEqual(playback["final_ledger"]["external_work_j"], 1000.0)
        self.assertEqual(playback["final_ledger"]["reaction_heat_j"], 0.0)
        self.assertEqual(playback["final_ledger"]["mass_residual_kg"], 0.0)
        self.assertLess(abs(playback["final_ledger"]["combined_energy_residual_j"]), 1e-9)
        self.assertEqual(job["cases"][0]["diagnostics"]["native_facts"]["final_ledger"],
                         playback["final_ledger"])
        scene_source = (ROOT / "playground/scene.js").read_text(encoding="utf-8")
        self.assertIn("liquid_fraction: state.liquid_fraction", scene_source)
        self.assertIn("thermal_enthalpy_j_region", scene_source)


if __name__ == "__main__":
    unittest.main()
