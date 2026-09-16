#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "playground"))

import workshop_api  # noqa: E402


class ComponentRoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.app = types.SimpleNamespace(workshop_store=root / "workshop")
        self.app.workshop_store.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_editing_one_part_returns_override_and_updated_bom(self):
        opened = workshop_api.open_workshop(self.app, {"kind": "table"})
        base = opened["candidates"][0]
        answer = workshop_api.candidates(self.app, {
            "kind": "table", "design_id": base["design_id"],
            "parameters": base["parameters"], "component_overrides": {},
            "component_edit": {"part_name": "leg-1", "action": "material", "material": "iron"},
        })
        edited = answer["candidates"][0]
        self.assertEqual("iron", next(p for p in edited["parts"] if p["name"] == "leg-1")["material"])
        self.assertIn("leg-1", edited["component_overrides"])
        self.assertEqual({"iron", "oak"}, {r["material"] for r in edited["bom"]["materials"]})

    def test_component_can_be_saved_then_reused_on_another_leg(self):
        edited = workshop_api.candidates(self.app, {
            "kind": "table", "design_id": "table-a", "parameters": {},
            "component_edit": {"part_name": "leg-1", "action": "thicker", "amount": 0.25},
        })["candidates"][0]
        saved = workshop_api.library(self.app, {
            "action": "save_component", "kind": "table", "design_id": edited["design_id"],
            "parameters": edited["parameters"], "component_overrides": edited["component_overrides"],
            "part_name": "leg-1", "name": "Sturdy leg",
        })["library_item"]
        reused = workshop_api.candidates(self.app, {
            "kind": "table", "design_id": edited["design_id"], "parameters": edited["parameters"],
            "component_overrides": edited["component_overrides"],
            "reuse_library_item": {"item_id": saved["item_id"], "part_name": "leg-3"},
        })["candidates"][0]
        sizes = {p["name"]: p["size_m"] for p in reused["parts"]}
        self.assertAlmostEqual(sizes["leg-1"][0], sizes["leg-3"][0])

    def test_edited_assembly_saves_to_personal_library_and_reopens(self):
        edited = workshop_api.candidates(self.app, {
            "kind": "chair", "design_id": "chair-a", "parameters": {},
            "component_edit": {"part_name": "leg-1", "action": "thinner"},
        })["candidates"][0]
        saved = workshop_api.remember(self.app, {
            "kind": "chair", "design_id": "chair-a", "parameters": edited["parameters"],
            "component_overrides": edited["component_overrides"], "save_design": True,
            "label": "Light chair",
        })
        item = saved["library_item"]
        self.assertEqual("assembly", item["item_type"])
        reopened = workshop_api.open_workshop(self.app, {"library_item_id": item["item_id"]})
        candidate = reopened["candidates"][0]
        self.assertIn("leg-1", candidate["component_overrides"])
        self.assertEqual("Light chair", reopened["library_item"]["name"])

    def test_price_changes_flow_into_candidate_cost(self):
        before = workshop_api.open_workshop(self.app, {"kind": "table"})["candidates"][0]["bom"]["material_cost"]
        workshop_api.library(self.app, {"action": "set_price", "material": "oak", "price_per_kg": 30})
        after = workshop_api.open_workshop(self.app, {"kind": "table"})["candidates"][0]["bom"]["material_cost"]
        self.assertGreater(after, before)


if __name__ == "__main__":
    unittest.main()
