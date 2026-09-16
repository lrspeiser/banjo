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

from mcp import workshop_components  # noqa: E402
import workshop_library  # noqa: E402


class PersonalLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.app = types.SimpleNamespace(runs_path=root / "runs", workshop_owner_id="owner")
        self.app.runs_path.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_database_lives_beside_the_persistent_runs_directory(self):
        self.assertEqual(self.app.runs_path.parent / "banjo.db", workshop_library.db_path(self.app))

    def test_saved_component_versions_and_reopens(self):
        design, _, _ = workshop_components.edit(
            {"kind": "table", "design_id": "a"}, part_name="leg-1", action="thicker")
        recipe = workshop_components.component_recipe(design, "leg-1")
        first = workshop_library.save_item(
            self.app, item_type="component", name="My table leg", payload=recipe,
            family=recipe["family"], role=recipe["role"], item_id="my-leg")
        second = workshop_library.save_item(
            self.app, item_type="component", name="My table leg v2", payload=recipe,
            family=recipe["family"], role=recipe["role"], item_id="my-leg")
        self.assertEqual(1, first["version"])
        self.assertEqual(2, second["version"])
        loaded = workshop_library.load_item(self.app, "my-leg")
        self.assertEqual("My table leg v2", loaded["name"])
        self.assertEqual(recipe, loaded["payload"])

    def test_owner_id_separates_libraries_in_one_database(self):
        recipe = {"schema": "banjo.workshop-component-recipe.v1", "role": "leg"}
        workshop_library.save_item(self.app, item_type="component", name="Mine", payload=recipe,
                                   role="leg", item_id="shared-name")
        other = types.SimpleNamespace(runs_path=self.app.runs_path, workshop_owner_id="someone-else")
        self.assertEqual([], workshop_library.list_items(other))
        with self.assertRaises(FileNotFoundError):
            workshop_library.load_item(other, "shared-name")

    def test_pricebook_is_explicitly_in_world_not_retail(self):
        book = workshop_library.pricebook(self.app)
        self.assertEqual("credits", book["currency"])
        self.assertIn("not a retail-price claim", book["basis"])
        self.assertTrue(any(row["material"] == "oak" for row in book["materials"]))

    def test_bom_changes_when_one_leg_changes_material(self):
        base, _ = workshop_components.design_from_spec({"kind": "table", "design_id": "a"})
        changed, _, _ = workshop_components.edit(
            {"kind": "table", "design_id": "a"}, part_name="leg-1", action="material", material="iron")
        before = workshop_library.bill_of_materials(self.app, base)
        after = workshop_library.bill_of_materials(self.app, changed)
        self.assertEqual(["oak"], [m["material"] for m in before["materials"]])
        self.assertEqual({"iron", "oak"}, {m["material"] for m in after["materials"]})
        self.assertNotEqual(before["material_cost"], after["material_cost"])


if __name__ == "__main__":
    unittest.main()
