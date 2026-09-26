#!/usr/bin/env python3
"""What the Workshop remembers: versions you can read, names you can change,
things you can throw away, and what a test said about an exact shape.

Before this, `workshop_library_versions` had been written on every save since
the table was made and had no reader anywhere in the repo; nothing in fourteen
HTTP routes removed anything; a name could only be changed by saving again,
which counted as a new revision; and no test result was kept at all, so "did
this pass last time" had no answer.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground")]

from mcp import workshop_components   # noqa: E402
import workshop_api_core              # noqa: E402
import workshop_library               # noqa: E402
import workshop_store                 # noqa: E402


def a_recipe(part="leg-1"):
    design, _, _ = workshop_components.edit({"kind": "table", "design_id": "a"},
                                            part_name=part, action="thicker")
    return workshop_components.component_recipe(design, part)


class WhatWasSavedBefore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.app = types.SimpleNamespace(runs_path=root / "runs", workshop_owner_id="owner",
                                         workshop_store=root / "workshop")
        self.app.runs_path.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, name, item_id="my-leg"):
        return workshop_library.save_item(self.app, item_type="component", name=name,
                                          payload=a_recipe(), item_id=item_id)

    def test_every_version_that_was_written_can_now_be_read(self):
        for name in ("first", "second", "third"):
            self.save(name)
        rows = workshop_library.list_versions(self.app, "my-leg")
        self.assertEqual([3, 2, 1], [r["version"] for r in rows], "newest first")
        self.assertEqual([True, False, False], [r["current"] for r in rows])
        # A version row keeps only the payload, so the name is the item's name
        # now -- renaming renames its history, and that is worth knowing.
        self.assertEqual({"third"}, {r["name"] for r in rows})
        one = workshop_library.load_version(self.app, "my-leg", 2)
        self.assertEqual(2, one["version"])
        self.assertFalse(one["current"])
        self.assertEqual(rows[1]["payload"], one["payload"])

    def test_a_version_that_was_never_saved_is_refused(self):
        self.save("only one")
        with self.assertRaises(FileNotFoundError):
            workshop_library.load_version(self.app, "my-leg", 2)
        with self.assertRaises(FileNotFoundError):
            workshop_library.list_versions(self.app, "no-such-thing")

    def test_renaming_does_not_count_as_changing_it(self):
        self.save("My tabel leg")
        renamed = workshop_library.rename_item(self.app, "my-leg", "My table leg")
        self.assertEqual("My table leg", renamed["name"])
        self.assertEqual(1, renamed["version"], "correcting a typo is not a new version")
        self.assertEqual(1, len(workshop_library.list_versions(self.app, "my-leg")))
        with self.assertRaises(ValueError):
            workshop_library.rename_item(self.app, "my-leg", "   ")

    def test_a_saved_thing_can_be_thrown_away_with_its_versions_and_tags(self):
        for name in ("one", "two"):
            self.save(name)
        self.save("elsewhere", item_id="other-leg")
        gone = workshop_library.delete_item(self.app, "my-leg")
        self.assertEqual(2, gone["versions_deleted"])
        self.assertEqual(["other-leg"], [i["item_id"] for i in workshop_library.list_items(self.app)])
        with self.assertRaises(FileNotFoundError):
            workshop_library.load_item(self.app, "my-leg")
        with self.assertRaises(FileNotFoundError):
            workshop_library.list_versions(self.app, "my-leg")
        # And the tags went with it: nothing is left pointing at a thing that
        # is not there.
        with workshop_library._connect(self.app) as db:
            left = db.execute("SELECT COUNT(*) AS n FROM workshop_library_tags WHERE item_id=?",
                              ("my-leg",)).fetchone()["n"]
        self.assertEqual(0, left)
        with self.assertRaises(FileNotFoundError):
            workshop_library.delete_item(self.app, "my-leg")

    def test_a_database_written_before_the_results_table_had_a_key_still_opens(self):
        """CREATE TABLE IF NOT EXISTS does nothing to a table already there.

        A database written while the results table was keyed by its own
        contents has no result_id, and every read of it failed with "no such
        column". Kept results are a cache of runs, so the table is dropped and
        remade; nothing else in this database is ever dropped.
        """
        with workshop_library._connect(self.app) as db:
            db.execute("DROP TABLE workshop_test_results")
            db.execute("""CREATE TABLE workshop_test_results (
                owner_id TEXT, design_id TEXT, fingerprint TEXT, test_name TEXT,
                ran_at TEXT, verdict TEXT, says TEXT, requested_json TEXT, measured_json TEXT)""")
        self.save("a leg")                      # any use of the database at all
        self.assertEqual([], workshop_library.results_for(self.app, design_id="anything"))
        workshop_library.keep_result(self.app, design_id="d", fingerprint="f", test_name="t",
                                     verdict="passed", says="", requested={}, measured={})
        self.assertEqual(1, len(workshop_library.results_for(self.app, design_id="d")))

    def test_a_test_preset_can_be_thrown_away(self):
        kept = workshop_library.save_bench_preset(self.app, name="a hard blow",
                                                  test_name="try_in_a_room", config={"strike_kg": 40})
        workshop_library.delete_bench_preset(self.app, kept["preset_id"])
        self.assertEqual([], workshop_library.list_bench_presets(self.app))


class WhatATestSaid(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.app = types.SimpleNamespace(runs_path=root / "runs", workshop_owner_id="owner",
                                         workshop_store=root / "workshop")
        self.app.runs_path.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def keep(self, fingerprint, verdict="passed", says="it stayed up"):
        return workshop_library.keep_result(
            self.app, design_id="my-table", fingerprint=fingerprint, test_name="try_in_a_room",
            verdict=verdict, says=says, requested={"load_kg": 120}, measured={"moved_m": 0.004})

    def test_a_result_belongs_to_the_shape_it_was_run_on(self):
        self.keep("a" * 64)
        self.keep("b" * 64, verdict="failed", says="it went over")
        # Asking about one shape gets that shape's runs and nobody else's,
        # which is the whole point: edit a leg and the fingerprint moves, so
        # yesterday's pass stops being claimed for today's geometry.
        only = workshop_library.results_for(self.app, design_id="my-table", fingerprint="a" * 64)
        self.assertEqual(1, len(only))
        self.assertEqual("passed", only[0]["verdict"])
        self.assertTrue(only[0]["this_shape"])
        both = workshop_library.results_for(self.app, design_id="my-table")
        self.assertEqual(2, len(both))
        self.assertEqual({"passed", "failed"}, {r["verdict"] for r in both})
        self.assertEqual({"moved_m": 0.004}, both[0]["measured"])

    def test_a_result_needs_a_shape_to_belong_to(self):
        for bad in ({"design_id": "", "fingerprint": "a"}, {"design_id": "d", "fingerprint": ""}):
            with self.assertRaises(ValueError):
                workshop_library.keep_result(self.app, test_name="t", verdict="v", says="s",
                                             requested={}, measured={}, **bad)

    def test_two_runs_in_the_same_second_are_two_runs(self):
        # The timestamp here is whole seconds, so a row keyed by its own time
        # swallowed every run after the first. Each one counts up instead.
        first, second = self.keep("a" * 64, says="one"), self.keep("a" * 64, says="two")
        self.assertNotEqual(first["result_id"], second["result_id"])
        self.assertEqual(["two", "one"],
                         [r["says"] for r in workshop_library.results_for(self.app, design_id="my-table")])

    def test_only_the_last_fifty_runs_of_a_design_are_kept(self):
        for i in range(workshop_library.RESULTS_KEPT + 5):
            self.keep("a" * 64, says=f"run {i}")
        kept = workshop_library.results_for(self.app, design_id="my-table", limit=200)
        self.assertEqual(workshop_library.RESULTS_KEPT, len(kept))
        self.assertEqual(f"run {workshop_library.RESULTS_KEPT + 4}", kept[0]["says"])
        self.assertEqual("run 5", kept[-1]["says"], "the oldest went first")


class ThroughTheRoute(unittest.TestCase):
    """The same, through /api/workshop/library's action dispatch."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.app = types.SimpleNamespace(runs_path=root / "runs", workshop_owner_id="owner",
                                         workshop_store=root / "workshop")
        self.app.runs_path.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, **body):
        return workshop_api_core.library(self.app, body)

    def test_versions_rename_and_delete_all_answer(self):
        workshop_library.save_item(self.app, item_type="component", name="a leg",
                                   payload=a_recipe(), item_id="my-leg")
        workshop_library.save_item(self.app, item_type="component", name="a leg",
                                   payload=a_recipe(), item_id="my-leg")
        self.assertEqual([2, 1], [v["version"] for v in self.call(action="versions", item_id="my-leg")["versions"]])
        self.assertEqual(1, self.call(action="open_version", item_id="my-leg", version=1)["version"]["version"])
        self.assertEqual("a better leg",
                         self.call(action="rename_component", item_id="my-leg", name="a better leg")["item"]["name"])
        gone = self.call(action="delete_component", item_id="my-leg")
        self.assertEqual("my-leg", gone["deleted"]["deleted"])
        self.assertEqual([], gone["personal_library"])

    def test_a_saved_design_can_be_renamed_and_thrown_away(self):
        design, _ = workshop_components.design_from_spec({"kind": "table", "design_id": "my-table"})
        workshop_store.save(workshop_api_core._store(self.app), design, label="Tabel")
        renamed = self.call(action="rename_design", design_id="my-table", name="Table")
        self.assertEqual("Table", renamed["saved"]["label"])
        self.assertEqual(1, renamed["saved"]["revision"], "renaming is not saving it again")
        gone = self.call(action="delete_design", design_id="my-table")
        self.assertEqual("my-table", gone["deleted"]["deleted"])
        self.assertEqual([], gone["saved_designs"])

    def test_an_action_nobody_recognises_is_refused_rather_than_ignored(self):
        # It used to fall through and hand back the whole catalogue, so a typo
        # looked like it had worked.
        with self.assertRaises(ValueError) as caught:
            self.call(action="delete_everything")
        self.assertIn("delete_everything", str(caught.exception))
        # No action at all is still the catalogue, which is how the page opens.
        self.assertIn("bench_tests", self.call())


if __name__ == "__main__":
    unittest.main()
