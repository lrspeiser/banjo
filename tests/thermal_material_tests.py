import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))
from thermal_material import (EXECUTION_TIMEOUT_S, LIMITATIONS, execute_experiment,
                              native_request, validate_experiment, validate_response)


def inert(material_id=1, name="renamed inert material", density=2500.0,
          heat_capacity=840.0, conductivity=1.0):
    return {"id": material_id, "name": name, "density_kg_m3": density,
            "heat_capacity_j_kg_k": heat_capacity,
            "conductivity_w_m_k": conductivity}


def oak(name="glass label on numeric reactive material"):
    value = inert(1, name, 700.0, 1700.0, 0.12)
    value.update({"fuel_fraction": 0.1, "oxygen_per_kg_solid": 0.15,
                  "reaction": {"activation_temperature_k": 600.0,
                               "rate_per_s": 20.0,
                               "heat_of_combustion_j_kg": 16e6,
                               "oxygen_per_kg_fuel": 1.5}})
    return value


def experiment(material=None, limits=None):
    return {"voxel_size_m": 0.02, "materials": [material or oak()],
            "cells": [
                {"chunk": [0, 0, 0], "local": [8, 8, 8], "material": 1,
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


def response(request, status="complete"):
    completed = 0.1 if status == "complete" else 0.01
    remaining = 0.0 if status == "complete" else 0.09
    ledger = {"external_work_j": 3000.0, "reaction_heat_j": 100.0,
              "combined_energy_residual_j": 0.0, "mass_residual_kg": 0.0,
              "lag_s": 0.0}
    cells = [{"temperature_k": 600.0}, {"temperature_k": 300.0}]
    frames = [{"time_s": 0.0, "cells": cells, "ledger": ledger}]
    if completed:
        frames.append({"time_s": completed, "cells": cells, "ledger": ledger})
    result = {"schema": "banjo.thermal-experiment-response.v1", "status": status,
              "request": request, "frames": frames, "completed_time_s": completed,
              "requested_horizon_s": 0.1, "remaining_duration_s": remaining,
              "scheduler_backlog_s": 0.0,
              "work": {"completed_jobs": 1, "cell_operations": 6,
                       "wall_ms": 0.01, "maximum_frames": 16},
              "final_ledger": ledger,
              "limitations": [LIMITATIONS[0], LIMITATIONS[1], LIMITATIONS[3]]}
    if status == "solver_limit":
        result["error"] = "Cumulative experiment work limit exhausted"
    return result


class ThermalMaterialTests(unittest.TestCase):
    def test_lowers_explicit_oak_glass_and_iron_without_name_dispatch(self):
        controls = [oak(), inert(name="oak display label"),
                    inert(name="iron numeric control", density=7870.0,
                          heat_capacity=450.0, conductivity=80.0)]
        for descriptor in controls:
            authored = experiment(descriptor)
            lowered = native_request(authored)
            self.assertEqual(lowered["schema"], "banjo.thermal-experiment-request.v1")
            self.assertEqual(lowered["materials"], [descriptor])
            self.assertEqual(authored, experiment(descriptor))
        self.assertIn("reaction", native_request(experiment(controls[0]))["materials"][0])
        self.assertNotIn("reaction", native_request(experiment(controls[1]))["materials"][0])

    def test_rejects_malformed_unknown_duplicate_and_overbudget_descriptors(self):
        bad = experiment()
        bad["airflow_m_s"] = 2.0
        with self.assertRaisesRegex(ValueError, "Unknown"):
            validate_experiment(bad)
        bad = experiment()
        bad["cells"][1]["local"] = bad["cells"][0]["local"]
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_experiment(bad)
        bad = experiment()
        bad["limits"]["maximum_cell_operations"] = 10_000_001
        with self.assertRaisesRegex(ValueError, "bounds"):
            validate_experiment(bad)
        bad = experiment()
        bad["materials"][0]["phase_change"] = {
            "liquid_heat_capacity_j_kg_k": 2000.0,
            "melting_temperature_k": 500.0, "latent_heat_j_kg": 100.0}
        with self.assertRaisesRegex(ValueError, "Combined"):
            validate_experiment(bad)

    def test_preserves_complete_and_solver_limit_ledgers(self):
        request = native_request(experiment())
        for status in ("complete", "solver_limit"):
            source = response(request, status)
            original = copy.deepcopy(source)
            validated = validate_response(source, request)
            self.assertEqual(validated["status"], status)
            self.assertEqual(validated["final_ledger"], original["final_ledger"])
            self.assertEqual(source, original)

    def test_bounded_execution_adds_explicit_playground_scope(self):
        authored = experiment()
        request = native_request(authored)
        native = response(request, "solver_limit")
        completed = subprocess.CompletedProcess([], 0, json.dumps(native).encode(), b"")
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "thermal-cli"
            executable.write_bytes(b"bounded-test-executable")
            with mock.patch("thermal_material.subprocess.run", return_value=completed) as run:
                recording, provenance = execute_experiment(executable, authored)
        self.assertEqual(recording["status"], "solver_limit")
        self.assertEqual(recording["final_ledger"], native["final_ledger"])
        self.assertIn(LIMITATIONS[2], recording["limitations"])
        self.assertEqual(provenance["native_schema"], native["schema"])
        self.assertEqual(run.call_args.kwargs["timeout"], EXECUTION_TIMEOUT_S)
        self.assertLessEqual(len(run.call_args.kwargs["input"]), 256 * 1024)

    def test_rejects_timeout_and_oversized_native_output(self):
        authored = experiment()
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "thermal-cli"
            executable.write_bytes(b"x")
            with mock.patch("thermal_material.subprocess.run",
                            side_effect=subprocess.TimeoutExpired(str(executable), 75)):
                with self.assertRaisesRegex(ValueError, "75-second"):
                    execute_experiment(executable, authored)
            huge = subprocess.CompletedProcess([], 0, b" " * (8 * 1024 * 1024 + 1), b"")
            with mock.patch("thermal_material.subprocess.run", return_value=huge):
                with self.assertRaisesRegex(ValueError, "8 MiB"):
                    execute_experiment(executable, authored)


if __name__ == "__main__":
    unittest.main()
