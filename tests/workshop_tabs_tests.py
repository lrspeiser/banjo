"""The Workshop's tabs (docs/workshop-mode.md, "Lab, Inventory, Skills and
Recipes") and what the bench chat does with a power part: a solar panel
becomes a glass plate on the part it sits on, wired to the design's store,
and what is missing is said in words a person or a model can act on.

    python tests/workshop_tabs_tests.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground"), str(ROOT / "mcp")]
import mcp  # noqa: E402,F401
from mcp import workshop as w, workshop_machines  # noqa: E402
import workshop_chat, workshop_library, workshop_tabs  # noqa: E402


def an_app(tmp: str) -> SimpleNamespace:
    return SimpleNamespace(runs_path=Path(tmp) / "runs", workshop_owner_id="owner", room=None)


class AddingSolar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = an_app(self.tmp.name)
        design = w.assemble("cart", design_id="c")
        candidate = design.wireframe()
        candidate["component_overrides"] = {}
        self.state = workshop_chat._State(self.app, candidate, None, ["oak", "iron", "glass"], [])

    def test_a_panel_needs_a_store_and_says_so(self):
        with self.assertRaisesRegex(ValueError, "A panel charges a battery, and this design has none"):
            self.state.execute("add_power_part", {"kind": "panel", "on": "deck", "area_m2": 0.2})
        with self.assertRaisesRegex(ValueError, "no part called that; the parts are"):
            self.state.execute("add_power_part", {"kind": "store", "name": "battery", "in": "roof",
                                                  "capacity_j": 5000, "charge_j": 1000, "voltage_v": 24})
        self.assertEqual({}, workshop_machines.of(self.state.design), "nothing was recorded by a refusal")

    def test_a_panel_becomes_a_glass_plate_on_its_part_wired_to_the_one_store(self):
        self.state.execute("add_power_part", {"kind": "store", "name": "battery", "in": "deck",
                                              "capacity_j": 5000, "charge_j": 1000, "voltage_v": 24})
        out = self.state.execute("add_power_part", {"kind": "panel", "on": "deck", "area_m2": 0.25})
        self.assertIn("added a 0.25 m2 glass panel, 'solar panel', on top of deck, charging battery", out["summary"])
        plate = next(p for p in self.state.design.parts if p.name == "solar panel")
        deck = next(p for p in self.state.design.parts if p.name == "deck")
        self.assertEqual(("solar-panel", "glass"), (plate.family, plate.material))
        self.assertAlmostEqual(0.5, plate.size_m[0], places=6, msg="square, of the panel's area")
        self.assertGreater(plate.center_m[1], max(c[1] for c in deck.corners_m()), "on top of the deck")
        record = workshop_machines.of(self.state.design)
        [panel] = record["panels"]
        self.assertEqual(("solar panel", "battery", 0.25, 0.2), (panel["on"], panel["store"], panel["area_m2"],
                                                                 panel["efficiency"]))
        self.assertEqual("1 store, 1 panel", workshop_machines.described(self.state.design)["says"])
        # A second store makes the choice ambiguous, and a wrong store name is refused.
        self.state.execute("add_power_part", {"kind": "store", "name": "spare", "in": "deck",
                                              "capacity_j": 500, "charge_j": 100, "voltage_v": 24})
        with self.assertRaisesRegex(ValueError, "which store does the panel charge"):
            self.state.execute("add_power_part", {"kind": "panel", "name": "second panel", "on": "deck"})
        with self.assertRaisesRegex(ValueError, "names the store 'cell', and there is none"):
            self.state.execute("add_power_part", {"kind": "panel", "name": "second panel", "on": "deck", "store": "cell"})

    def test_a_motor_needs_two_parts_that_are_there_and_a_store(self):
        with self.assertRaisesRegex(ValueError, "turns two parts"):
            self.state.execute("add_power_part", {"kind": "motor", "turns": ["axle-1"]})
        with self.assertRaisesRegex(ValueError, "add a store first"):
            self.state.execute("add_power_part", {"kind": "motor", "turns": ["bearing-mount-11", "axle-1"],
                                                  "stall_torque_n_m": 20, "no_load_rpm": 60})


class TheTabs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = an_app(self.tmp.name)

    def test_inventory_lists_racks_library_and_families(self):
        workshop_library.set_rack(self.app, "oak", 12.5)
        workshop_library.add_goods(self.app, "copper wire", 1.47)
        inv = workshop_tabs.inventory(self.app)
        self.assertIn({"material": "oak", "mass_kg": 12.5}, [{k: r[k] for k in ("material", "mass_kg")} for r in inv["materials"]])
        self.assertEqual([("copper wire", 1.47)], [(g["substance"], g["mass_kg"]) for g in inv["goods"]])
        self.assertIn("rotor", [f["name"] for f in inv["families"]])
        self.assertTrue(all(f["about"] for f in inv["families"]))
        self.assertEqual(([], []), (inv["components"], inv["designs"]))

    def test_recipes_say_what_each_template_takes_and_can_do(self):
        for material in ("oak", "iron", "glass"):
            workshop_library.set_rack(self.app, material, 500.0)
        r = workshop_tabs.recipes(self.app)
        by_name = {t["name"]: t for t in r["templates"]}
        rover = by_name["rover"]
        self.assertEqual([("copper", 1.0), ("copper wire", 2.3)], [(g["substance"], g["kg"]) for g in rover["goods"]])
        self.assertFalse(rover["enough"], "no goods on the rack")
        self.assertIn("digs at a site and carries the load to a depot", rover["can_do"])
        self.assertIn("drives itself and turns away from water", rover["can_do"])
        self.assertTrue(by_name["chair"]["enough"])
        self.assertIn("works the recipe 'smelt copper' from its intake to its output", by_name["processor"]["can_do"])
        self.assertEqual([], r["room_recipes"], "no room open")
        # With the mine open, its recipes and its vein are listed.
        import json
        spec = json.loads((ROOT / "playground" / "rooms" / "tests-mine.json").read_text(encoding="utf-8"))
        self.app.room = SimpleNamespace(spec=spec)
        r = workshop_tabs.recipes(self.app)
        self.assertEqual({"smelt copper": ["smelter"], "draw wire": ["mill"]},
                         {x["name"]: x["worked_by"] for x in r["room_recipes"]})
        self.assertEqual([("copper vein", "copper ore", 400.0)],
                         [(d["name"], d["substance"], d["left_kg"]) for d in r["deposits"]])

    def test_skills_read_the_notebook_as_achievements(self):
        self.app.knowledge = lambda: {"techniques": [], "designs": [], "blocked": [], "not_modelled": [], "revision": 0}
        s = workshop_tabs.skills(self.app)
        self.assertEqual((0, len(s["techniques"])), (s["known"], s["of"]))
        wood = next(t for t in s["techniques"] if t["id"] == "rough-shaping-wood")
        self.assertEqual((False, True, ["One-piece wooden pick"]), (wood["known"], wood["within_reach"], wood["opens"]))
        self.app.knowledge = lambda: {"techniques": [{"id": "rough-shaping-wood", "name": "Rough-shaping wood"}],
                                      "designs": [{"design": "pick@1", "name": "pick", "registered": True, "standing": [],
                                                   "demonstrated": ["dig"], "evidence": [{"id": "e1"}]}],
                                      "blocked": [], "not_modelled": ["hard rock"], "revision": 3}
        s = workshop_tabs.skills(self.app)
        self.assertEqual(1, s["known"])
        self.assertTrue(next(t for t in s["techniques"] if t["id"] == "rough-shaping-wood")["known"])
        self.assertEqual(["hard rock"], s["not_modelled"])


if __name__ == "__main__":
    unittest.main()
