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

import workshop_library  # noqa: E402


class PhysicsTaggedLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.app = types.SimpleNamespace(runs_path=root / "runs", workshop_owner_id="owner")
        self.app.runs_path.mkdir(parents=True)

    def tearDown(self): self.tmp.cleanup()

    def test_tags_are_normalized_and_returned_with_library_items(self):
        item = workshop_library.save_item(
            self.app, item_type="component", name="Wheel module", payload={"x": 1},
            tags={"physics": ["Rolling Contact", "rotor"], "interface": ["shaft"]})
        self.assertEqual(["rolling_contact", "rotor"], item["tags"]["physics"])
        self.assertEqual(["shaft"], item["tags"]["interface"])
        self.assertEqual(item["tags"], workshop_library.list_items(self.app)[0]["tags"])

    def test_find_items_matches_physics_semantics_not_names(self):
        workshop_library.save_item(
            self.app, item_type="component", name="Alice", payload={}, item_id="a",
            tags={"physics": ["rotor", "rolling_contact"], "interface": ["shaft"]})
        workshop_library.save_item(
            self.app, item_type="component", name="Bob", payload={}, item_id="b",
            tags={"physics": ["structural_member", "beam"], "interface": ["surface"]})
        found = workshop_library.find_items(
            self.app, tags={"physics": ["rotor"], "interface": ["shaft"]})
        self.assertEqual(["a"], [row["item_id"] for row in found])
        either = workshop_library.find_items(
            self.app, tags={"physics": ["rotor", "beam"]}, match_all=False)
        self.assertEqual({"a", "b"}, {row["item_id"] for row in either})

    def test_updating_without_tags_preserves_existing_semantics(self):
        workshop_library.save_item(
            self.app, item_type="assembly", name="Machine", payload={"rev": 1}, item_id="machine",
            tags={"relationship": ["bearing"], "capability": ["powered"]})
        updated = workshop_library.save_item(
            self.app, item_type="assembly", name="Machine v2", payload={"rev": 2}, item_id="machine")
        self.assertEqual(["bearing"], updated["tags"]["relationship"])
        self.assertEqual(["powered"], updated["tags"]["capability"])

    def test_tag_search_is_owner_scoped(self):
        workshop_library.save_item(
            self.app, item_type="component", name="Mine", payload={}, item_id="mine",
            tags={"physics": ["heater"]})
        other = types.SimpleNamespace(runs_path=self.app.runs_path, workshop_owner_id="other")
        self.assertEqual([], workshop_library.find_items(other, tags={"physics": ["heater"]}))


if __name__ == "__main__": unittest.main()
