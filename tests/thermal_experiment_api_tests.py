import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def find_executable():
    candidates = []
    if os.environ.get("BANJO_THERMAL_EXPERIMENT_CLI"):
        candidates.append(Path(os.environ["BANJO_THERMAL_EXPERIMENT_CLI"]))
    candidates.extend([
        ROOT / "build/win-joint-double/Release/banjo_thermal_experiment_cli.exe",
        ROOT / "build/agent-test/banjo_thermal_experiment_cli",
        ROOT / "build/banjo_thermal_experiment_cli",
    ])
    return next((path for path in candidates if path.is_file()), None)


EXE = find_executable()


def material(name="renamed reactive block", reactive=True):
    value = {
        "id": 1,
        "name": name,
        "density_kg_m3": 700.0,
        "heat_capacity_j_kg_k": 1700.0,
        "conductivity_w_m_k": 0.12,
    }
    if reactive:
        value.update({
            "fuel_fraction": 0.1,
            "oxygen_per_kg_solid": 0.01,
            "reaction": {
                "activation_temperature_k": 600.0,
                "rate_per_s": 20.0,
                "heat_of_combustion_j_kg": 100000.0,
                "oxygen_per_kg_fuel": 1.0,
            },
        })
    return value


def request(name="renamed reactive block", reactive=True, limits=None):
    return {
        "schema": "banjo.thermal-experiment-request.v1",
        "voxel_size_m": 0.02,
        "materials": [material(name, reactive)],
        "cells": [
            {"chunk": [0, 0, 0], "local": [8, 8, 8], "material": 1,
             "temperature_k": 650.0},
            {"chunk": [0, 0, 0], "local": [9, 8, 8], "material": 1,
             "temperature_k": 650.0},
        ],
        "heater": {"cell_index": 0, "energy_j": 10.0, "maximum_energy_j": 10.0},
        "step_s": 0.01,
        "horizon_s": 0.05,
        "limits": limits or {
            "maximum_jobs": 64,
            "maximum_cell_operations": 10000,
            "maximum_wall_ms": 1000.0,
            "maximum_frames": 16,
        },
    }


class ThermalExperimentApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if EXE is None:
            raise unittest.SkipTest(
                "banjo_thermal_experiment_cli is not built; set BANJO_THERMAL_EXPERIMENT_CLI")

    def run_raw(self, raw):
        process = subprocess.run([str(EXE)], input=raw, text=True,
                                 capture_output=True, check=False)
        return process.returncode, json.loads(process.stdout)

    def run_request(self, value):
        return self.run_raw(json.dumps(value, separators=(",", ":")))

    def test_numeric_reaction_and_inert_controls_ignore_names(self):
        code, reactive = self.run_request(request("glass display name", True))
        self.assertEqual(code, 0)
        self.assertEqual(reactive["status"], "complete")
        self.assertLess(reactive["frames"][-1]["cells"][0]["fuel_kg"],
                        reactive["frames"][0]["cells"][0]["fuel_kg"])
        self.assertGreater(reactive["final_ledger"]["reaction_heat_j"], 0)
        code, inert = self.run_request(request("oak display name", False))
        self.assertEqual(code, 0)
        self.assertEqual(inert["status"], "complete")
        self.assertEqual(inert["final_ledger"]["reaction_heat_j"], 0)
        self.assertEqual(inert["frames"][-1]["cells"][0]["fuel_kg"], 0)

    def test_matched_heater_ignites_numeric_oak_only_and_closes_ledgers(self):
        descriptors = {
            "glass": {"id": 1, "name": "glass numeric control",
                      "density_kg_m3": 2500.0, "heat_capacity_j_kg_k": 840.0,
                      "conductivity_w_m_k": 1.0},
            "oak": {"id": 1, "name": "renamed reactive specimen",
                    "density_kg_m3": 700.0, "heat_capacity_j_kg_k": 1700.0,
                    "conductivity_w_m_k": 0.12, "fuel_fraction": 0.1,
                    "oxygen_per_kg_solid": 0.15,
                    "reaction": {"activation_temperature_k": 600.0,
                                 "rate_per_s": 20.0,
                                 "heat_of_combustion_j_kg": 16e6,
                                 "oxygen_per_kg_fuel": 1.5}},
            "iron": {"id": 1, "name": "iron numeric control",
                     "density_kg_m3": 7870.0, "heat_capacity_j_kg_k": 450.0,
                     "conductivity_w_m_k": 80.0},
        }
        results = {}
        for label, descriptor in descriptors.items():
            value = request(reactive=False)
            value["materials"] = [descriptor]
            value["cells"][0]["temperature_k"] = 300.0
            value["cells"][1]["temperature_k"] = 300.0
            value["heater"] = {"cell_index": 0, "energy_j": 3000.0,
                               "maximum_energy_j": 3000.0}
            value["horizon_s"] = 0.1
            results[label] = self.run_request(value)[1]

        for result in results.values():
            self.assertEqual(result["status"], "complete")
            self.assertAlmostEqual(result["completed_time_s"], 0.1)
            self.assertEqual(result["remaining_duration_s"], 0.0)
            self.assertAlmostEqual(result["scheduler_backlog_s"], 0.0)
            self.assertAlmostEqual(result["final_ledger"]["external_work_j"], 3000.0)
            self.assertAlmostEqual(result["final_ledger"]["mass_residual_kg"], 0.0)
            self.assertLessEqual(abs(result["final_ledger"]["combined_energy_residual_j"]),
                                 5e-11)
        self.assertGreater(results["oak"]["final_ledger"]["reaction_heat_j"], 0.0)
        self.assertEqual(results["glass"]["final_ledger"]["reaction_heat_j"], 0.0)
        self.assertEqual(results["iron"]["final_ledger"]["reaction_heat_j"], 0.0)
        oak_initial = results["oak"]["frames"][0]["cells"][0]
        oak_final = results["oak"]["frames"][-1]["cells"][0]
        consumed_fuel = oak_initial["fuel_kg"] - oak_final["fuel_kg"]
        self.assertAlmostEqual(results["oak"]["final_ledger"]["reaction_heat_j"],
                               consumed_fuel * 16e6, places=8)
        self.assertGreater(oak_final["temperature_k"], oak_initial["temperature_k"])

    def test_rejects_unknown_duplicate_and_inconsistent_cells(self):
        bad = request()
        bad["execute_python"] = "print('no')"
        code, rejected = self.run_request(bad)
        self.assertEqual(code, 1)
        self.assertEqual(rejected["error"], "Unknown field")
        duplicate = '{"schema":"banjo.thermal-experiment-request.v1","schema":"x"}'
        code, rejected = self.run_raw(duplicate)
        self.assertEqual(code, 1)
        self.assertEqual(rejected["error"], "Duplicate field")
        code, rejected = self.run_raw("{")
        self.assertEqual(code, 1)
        self.assertEqual(rejected["error"], "Malformed JSON thermal experiment request")
        bad = request()
        bad["cells"][1]["temperature_k"] = 400.0
        self.assertEqual(self.run_request(bad)[0], 1)
        bad = request()
        bad["cells"][1]["local"] = bad["cells"][0]["local"]
        self.assertEqual(self.run_request(bad)[0], 1)

    def test_cumulative_work_limit_reports_last_accepted_backlog(self):
        value = request(limits={
            "maximum_jobs": 1,
            "maximum_cell_operations": 10000,
            "maximum_wall_ms": 1000.0,
            "maximum_frames": 16,
        })
        code, result = self.run_request(value)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "solver_limit")
        self.assertEqual(result["work"]["completed_jobs"], 1)
        self.assertAlmostEqual(result["completed_time_s"], 0.01)
        self.assertLess(result["completed_time_s"], result["requested_horizon_s"])
        self.assertAlmostEqual(result["remaining_duration_s"], 0.04)
        self.assertEqual(result["scheduler_backlog_s"], 0)
        self.assertEqual(result["frames"][-1]["time_s"], result["completed_time_s"])

    def test_frame_cap_reports_experiment_remaining_without_scheduler_lag(self):
        value = request()
        value["limits"]["maximum_frames"] = 2
        code, result = self.run_request(value)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "solver_limit")
        self.assertEqual(len(result["frames"]), 2)
        self.assertAlmostEqual(result["completed_time_s"], 0.01)
        self.assertAlmostEqual(result["remaining_duration_s"], 0.04)
        self.assertEqual(result["scheduler_backlog_s"], 0)
        self.assertIn("Frame limit", result["error"])

    def test_repeated_request_has_identical_physical_fields(self):
        first = self.run_request(request("first name"))[1]
        second = self.run_request(request("first name"))[1]
        self.assertEqual(first["status"], "complete")
        self.assertEqual(first["frames"], second["frames"])
        self.assertEqual(first["final_ledger"], second["final_ledger"])
        self.assertEqual(first["work"]["completed_jobs"],
                         second["work"]["completed_jobs"])
        self.assertEqual(first["work"]["cell_operations"],
                         second["work"]["cell_operations"])


if __name__ == "__main__":
    unittest.main()
