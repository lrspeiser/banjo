from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp.product_graph import ProductGraph, component  # noqa: E402
from mcp.product_contract import compile_contract  # noqa: E402
from mcp.product_evidence import record, from_bench, envelope  # noqa: E402
from mcp.product_runtime import decision  # noqa: E402


def product_with_evidence():
    evidence = [record(
        evidence_id="impact-1", test="top-impact",
        measured={"held": True}, acceptance={"status": "passed", "criteria": "no failure"},
        validated_range={"impact_energy_j": [0, 8000], "temperature_k": [250, 500]})]
    return ProductGraph("table-like", components=[component(
        "top", "surface", geometry={"shape":"box", "mass_kg":10,
        "center_m":[0,0,0], "size_m":[1,.1,1]}, physics_tags=("plate","collision_surface"))],
        evidence=evidence)


class Evidence(unittest.TestCase):
    def test_observation_cannot_silently_become_validation(self):
        with self.assertRaisesRegex(ValueError, "passed"):
            record(evidence_id="x", test="heat", measured={},
                   acceptance={"status":"observed"}, validated_range={"temperature_k":[250,400]})

    def test_bench_observation_stays_observed(self):
        item = from_bench({"test":"kettle_heat", "measured":{"water_end_k":330},
                           "requested":{"duration_s":60},
                           "acceptance":{"status":"observed"}, "evidence":"engine-trial"},
                          evidence_id="kettle-1")
        self.assertEqual("observed", item["acceptance"]["status"])
        self.assertNotIn("validated_range", item)

    def test_envelope_keeps_separate_intervals_instead_of_inventing_the_gap(self):
        rows = [record(evidence_id="a", test="x", measured={}, acceptance={"status":"passed"},
                       validated_range={"load_kg":[0,100]}),
                record(evidence_id="b", test="x", measured={}, acceptance={"status":"passed"},
                       validated_range={"load_kg":[200,300]})]
        self.assertEqual([[0.0,100.0],[200.0,300.0]], envelope(rows)["load_kg"])


class RuntimeRefinement(unittest.TestCase):
    def setUp(self):
        self.contract = compile_contract(product_with_evidence())

    def test_event_inside_evidence_stays_reduced(self):
        answer = decision(self.contract, {"metrics":{"impact_energy_j":4000,"temperature_k":300}})
        self.assertEqual("stay-reduced", answer["decision"])

    def test_event_outside_evidence_refines_locally(self):
        answer = decision(self.contract, {"components":["top"],
            "metrics":{"impact_energy_j":12000,"temperature_k":300}})
        self.assertEqual("refine", answer["decision"])
        self.assertEqual("local", answer["scope"])
        self.assertIn("impact_energy_j=12000", " ".join(answer["reasons"]))

    def test_unknown_required_metric_refines_instead_of_extrapolating(self):
        answer = decision(self.contract, {"metrics":{"torsion_n_m":10}})
        self.assertEqual("refine", answer["decision"])
        self.assertIn("no validated runtime range", " ".join(answer["reasons"]))

    def test_near_failure_refines_even_inside_tested_range(self):
        answer = decision(self.contract, {"components":["top"], "failure_fraction":0.92,
            "metrics":{"impact_energy_j":1000}})
        self.assertEqual("refine", answer["decision"])
        self.assertIn("failure indicator", " ".join(answer["reasons"]))

    def test_missing_required_collision_zone_refines(self):
        answer = decision(self.contract, {"requires_collision_zone":True,
                                          "collision_zone":"not-a-zone"})
        self.assertEqual("refine", answer["decision"])
        self.assertIn("collision zone", " ".join(answer["reasons"]))


if __name__ == "__main__": unittest.main()
