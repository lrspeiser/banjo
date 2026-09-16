from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "playground"))

from mcp.workshop import assemble, materialize  # noqa: E402
import workshop_store  # noqa: E402


class SavedDesigns(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_saved_design_reopens_through_the_authoritative_model(self):
        design = assemble("table", design_id="work-table",
                          parameters={"leg_style": "splayed", "splay_deg": 9})
        saved = workshop_store.save(
            self.root, design, label="Wide work table",
            parent_design_id="table-g0-v2", world_revision="world:44")
        self.assertEqual(1, saved["revision"])
        self.assertEqual("world:44", saved["world_revision"])

        record, reopened = workshop_store.load(self.root, "work-table")
        self.assertEqual("table", record["kind"])
        self.assertEqual("splayed", reopened.parameters["leg_style"])
        self.assertEqual(9, reopened.parameters["splay_deg"])
        self.assertEqual(saved["fingerprint"], materialize(reopened)["fingerprint"])
        self.assertEqual("table-g0-v2", reopened.lineage["parent_design_id"])

    def test_saving_the_same_identity_creates_a_new_revision(self):
        first = assemble("chair", design_id="chair-a")
        second = assemble("chair", design_id="chair-a",
                          parameters={"back_height_m": 0.6})
        self.assertEqual(1, workshop_store.save(self.root, first)["revision"])
        self.assertEqual(2, workshop_store.save(self.root, second)["revision"])
        _, reopened = workshop_store.load(self.root, "chair-a")
        self.assertEqual(0.6, reopened.parameters["back_height_m"])

    def test_the_library_lists_saved_designs(self):
        workshop_store.save(self.root, assemble("table", design_id="a"), label="A")
        workshop_store.save(self.root, assemble("stool", design_id="b"), label="B")
        rows = workshop_store.list_saved(self.root)
        self.assertEqual({"a", "b"}, {r["design_id"] for r in rows})
        self.assertTrue(all("fingerprint" in r and "measured" in r for r in rows))

    def test_path_escape_and_unsupported_records_are_refused(self):
        for bad in ("../x", "a/b", ".", "", "x" * 100):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                workshop_store.safe_design_id(bad)

        folder = self.root / "designs"
        folder.mkdir()
        (folder / "bad.json").write_text('{"schema":"wrong"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            workshop_store.load(self.root, "bad")

    def test_save_keeps_semantic_recipe_not_a_second_geometry_copy(self):
        design = assemble("cart", design_id="cart-1")
        saved = workshop_store.save(self.root, design)
        self.assertIn("parameters", saved)
        self.assertNotIn("parts", saved)
        self.assertNotIn("objects", saved)


if __name__ == "__main__":
    unittest.main()
