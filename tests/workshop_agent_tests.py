from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp import workshop_agent  # noqa: E402


class Contract(unittest.TestCase):
    def test_contract_exposes_only_workshop_operations(self):
        contract = workshop_agent.contract()
        self.assertEqual("banjo.workshop-agent.v1", contract["schema"])
        self.assertIn("compose_design", contract["operations"])
        self.assertIn("compare_candidates", contract["operations"])
        for forbidden in ("add_object", "drive", "operate", "inventory", "world"):
            self.assertNotIn(forbidden, contract["operations"])

    def test_source_has_no_live_world_capability(self):
        source = (ROOT / "mcp" / "workshop_agent.py").read_text(encoding="utf-8")
        for forbidden in ("live_session", "room_world", "world_chat", "subprocess",
                          "BANJO_LIBRARY", "app.room", "inventory_room"):
            self.assertNotIn(forbidden, source)


class Designing(unittest.TestCase):
    def test_compose_and_change_rebuild_geometry(self):
        base = workshop_agent.execute("compose_design", {
            "kind": "table", "design_id": "t"})["candidate"]
        changed = workshop_agent.execute("change_parameters", {
            "kind": "table", "design_id": "t",
            "changes": {"leg_style": "splayed", "splay_deg": 12},
        })["candidate"]
        self.assertEqual("t", changed["lineage"]["parent"])
        self.assertEqual(12, changed["lineage"]["changes"]["splay_deg"])
        self.assertNotEqual(base["measured"]["support_footprint_m"],
                            changed["measured"]["support_footprint_m"])

    def test_variant_sweep_is_bounded(self):
        answer = workshop_agent.execute("fork_variants", {
            "kind": "chair", "design_id": "c",
            "sweeps": {"back_height_m": [0.3, 0.4, 0.5],
                       "leg_style": ["straight", "splayed"]},
        })
        self.assertEqual(6, len(answer["candidates"]))
        with self.assertRaises(ValueError):
            workshop_agent.execute("fork_variants", {
                "kind": "table", "sweeps": {"splay_deg": list(range(201))},
                "limit": 200,
            })

    def test_unknown_parameter_is_refused(self):
        with self.assertRaises(KeyError):
            workshop_agent.execute("change_parameters", {
                "kind": "table", "changes": {"magic": 1}})


class Comparing(unittest.TestCase):
    def test_compare_keeps_a_pareto_frontier_instead_of_one_fake_best(self):
        specs = [
            {"kind": "table", "design_id": "light",
             "parameters": {"leg_section_m": 0.035, "leg_style": "straight"}},
            {"kind": "table", "design_id": "stable",
             "parameters": {"leg_section_m": 0.07, "leg_style": "splayed",
                            "splay_deg": 14}},
        ]
        answer = workshop_agent.execute("compare_candidates", {
            "candidates": specs,
            "objectives": [
                {"metric": "mass_kg", "direction": "min"},
                {"metric": "tip_angle_deg", "direction": "max"},
            ],
        })
        self.assertEqual({"light", "stable"}, set(answer["pareto_design_ids"]))
        rows = {r["design_id"]: r for r in answer["candidates"]}
        self.assertLess(rows["light"]["metrics"]["mass_kg"],
                        rows["stable"]["metrics"]["mass_kg"])
        self.assertGreater(rows["stable"]["metrics"]["tip_angle_deg"],
                           rows["light"]["metrics"]["tip_angle_deg"])

    def test_compare_can_use_support_area_and_part_count(self):
        answer = workshop_agent.execute("compare_candidates", {
            "candidates": [{"kind": "stool", "design_id": "s"}],
            "objectives": ["support_area_m2", "part_count"],
        })
        metrics = answer["candidates"][0]["metrics"]
        self.assertGreater(metrics["support_area_m2"], 0)
        self.assertGreater(metrics["part_count"], 0)


class Boundary(unittest.TestCase):
    def test_materialization_is_still_not_a_world_commit(self):
        answer = workshop_agent.execute("materialize_candidate", {
            "kind": "cart", "design_id": "cart"})
        self.assertEqual("not-committed", answer["plan"]["commit"]["status"])

    def test_feedback_is_structured_but_not_persisted_here(self):
        answer = workshop_agent.execute("record_feedback", {
            "kind": "bench", "design_id": "b", "rating": 5,
            "selected": True, "note": "keep this proportion"})
        self.assertEqual(5, answer["feedback"]["rating"])
        self.assertTrue(answer["feedback"]["selected"])


if __name__ == "__main__":
    unittest.main()
