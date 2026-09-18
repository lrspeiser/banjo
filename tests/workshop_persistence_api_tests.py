from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "playground"))

import workshop_api  # noqa: E402


class Bench:
    def __init__(self, where: Path) -> None:
        self.workshop_store = where


class PersistentWorkshopAPI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Bench(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_selected_candidate_can_be_saved_and_reopened(self):
        opened = workshop_api.open_workshop(self.app, {"kind": "table"})
        candidate = opened["candidates"][3]
        answer = workshop_api.remember(self.app, {
            "kind": "table",
            "design_id": "shop-table",
            "parameters": candidate["parameters"],
            "save_design": True,
            "label": "Shop table",
            "parent_design_id": candidate["design_id"],
            "world_revision": "room-17",
        })
        self.assertEqual(1, answer["design"]["revision"])
        self.assertEqual(1, answer["designs_kept"])

        reopened = workshop_api.open_workshop(
            self.app, {"saved_design_id": "shop-table"})
        self.assertEqual("table", reopened["kind"])
        self.assertEqual("room-17", reopened["session"]["world_revision"])
        self.assertEqual(1, len(reopened["candidates"]))
        rebuilt = reopened["candidates"][0]
        self.assertEqual(candidate["parameters"], rebuilt["parameters"])
        self.assertEqual("shop-table", rebuilt["design_id"])
        self.assertEqual(candidate["design_id"],
                         rebuilt["lineage"]["parent_design_id"])

    def test_remembered_lists_feedback_and_saved_designs_separately(self):
        workshop_api.remember(self.app, {
            "kind": "chair", "design_id": "chair-a",
            "save_design": True, "label": "Chair A"})
        workshop_api.remember(self.app, {
            "kind": "chair", "design_id": "chair-a",
            "rating": 5, "note": "keep the back"})
        kept = workshop_api.remembered(self.app)
        self.assertEqual(1, kept["designs_kept"])
        self.assertEqual("chair-a", kept["saved_designs"][0]["design_id"])
        self.assertEqual(1, kept["kept"])
        self.assertEqual("keep the back", kept["feedback"][0]["note"])

    def test_saving_without_feedback_does_not_create_empty_feedback(self):
        answer = workshop_api.remember(self.app, {
            "kind": "stool", "design_id": "stool-a", "save_design": True})
        self.assertIsNone(answer["saved"])
        self.assertEqual(0, answer["kept"])
        self.assertEqual(1, answer["designs_kept"])



class EditedDesignPersistence(unittest.TestCase):
    setUp = PersistentWorkshopAPI.setUp
    tearDown = PersistentWorkshopAPI.tearDown

    def test_physical_design_is_saved_listed_and_reopened_exactly(self):
        overrides = {"leg-1":{"skin":{"profile":"curve","physical":True,"bend_m":.35}}}
        saved = workshop_api.remember(self.app, {"kind":"table","design_id":"curved-table",
            "component_overrides":overrides,"save_design":True,"label":"Curved table"})
        self.assertEqual(1,saved["designs_kept"])
        self.assertTrue(saved["design"]["component_overrides"]["leg-1"]["skin"]["physical"])
        reopened = workshop_api.open_workshop(self.app,{"saved_design_id":"curved-table"})["candidates"][0]
        library = workshop_api.open_workshop(self.app,{"library_item_id":saved["library_item"]["item_id"]})["candidates"][0]
        self.assertEqual(reopened["component_overrides"],library["component_overrides"])
        self.assertEqual(saved["design"]["matter_physics_hash"],reopened["measured"]["matter_physics_hash"])
        self.assertIn("requires-retest",saved["library_item"]["tags"]["evidence"])

    def test_geometric_and_cosmetic_overrides_survive_saved_design_load(self):
        overrides = {"leg-1":{"size_m":[.09,.72,.09],"skin":{"profile":"curve","physical":False,"bend_m":.1}}}
        saved = workshop_api.remember(self.app, {"kind":"table","design_id":"edited-table",
            "component_overrides":overrides,"save_design":True})
        reopened = workshop_api.open_workshop(self.app,{"saved_design_id":"edited-table"})["candidates"][0]
        self.assertEqual(saved["design"]["component_overrides"],reopened["component_overrides"])
        self.assertEqual([.09,.72,.09],next(p for p in reopened["parts"] if p["name"]=="leg-1")["size_m"])


if __name__ == "__main__":
    unittest.main()
