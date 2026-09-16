#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp import workshop_components  # noqa: E402


class IndependentComponents(unittest.TestCase):
    def base(self):
        return {"kind": "table", "design_id": "table-a", "parameters": {}}

    def test_thinning_one_leg_changes_only_that_leg(self):
        before, _ = workshop_components.design_from_spec(self.base())
        old = {p.name: p.size_m for p in before.parts}
        changed, overrides, names = workshop_components.edit(
            self.base(), part_name="leg-1", action="thinner", amount=0.2)
        self.assertEqual(["leg-1"], names)
        self.assertIn("leg-1", overrides)
        now = {p.name: p.size_m for p in changed.parts}
        self.assertLess(now["leg-1"][0], old["leg-1"][0])
        for name in ("leg-2", "leg-3", "leg-4", "top"):
            self.assertEqual(old[name], now[name])

    def test_similar_scope_changes_all_legs_but_not_the_top(self):
        changed, overrides, names = workshop_components.edit(
            self.base(), part_name="leg-1", action="thicker", scope="similar")
        self.assertEqual({"leg-1", "leg-2", "leg-3", "leg-4"}, set(names))
        self.assertEqual(set(names), set(overrides))
        self.assertNotIn("top", overrides)
        legs = [p for p in changed.parts if p.role == "leg"]
        self.assertTrue(all(p.size_m[0] > 0.06 for p in legs))

    def test_a_leg_length_edit_keeps_its_head_attachment(self):
        before, _ = workshop_components.design_from_spec(self.base())
        old = next(p for p in before.parts if p.name == "leg-1")
        old_head = max(old.ends_m(), key=lambda p: p[1])
        changed, _, _ = workshop_components.edit(
            self.base(), part_name="leg-1", action="longer", amount=0.2)
        new = next(p for p in changed.parts if p.name == "leg-1")
        new_head = max(new.ends_m(), key=lambda p: p[1])
        for a, b in zip(old_head, new_head):
            self.assertAlmostEqual(a, b, places=9)
        self.assertGreater(new.size_m[1], old.size_m[1])

    def test_material_edit_is_reproducible_from_overrides(self):
        changed, overrides, _ = workshop_components.edit(
            self.base(), part_name="leg-2", action="material", material="iron")
        reopened, checked = workshop_components.design_from_spec(
            {**self.base(), "component_overrides": overrides})
        self.assertEqual(overrides, checked)
        self.assertEqual("iron", next(p for p in changed.parts if p.name == "leg-2").material)
        self.assertEqual("iron", next(p for p in reopened.parts if p.name == "leg-2").material)

    def test_a_saved_leg_recipe_can_replace_another_leg(self):
        made, overrides, _ = workshop_components.edit(
            self.base(), part_name="leg-1", action="thicker", amount=0.25)
        recipe = workshop_components.component_recipe(made, "leg-1")
        reused, new_overrides, names = workshop_components.replace_with_recipe(
            {**self.base(), "component_overrides": overrides},
            part_name="leg-3", recipe=recipe)
        self.assertEqual(["leg-3"], names)
        leg1 = next(p for p in reused.parts if p.name == "leg-1")
        leg3 = next(p for p in reused.parts if p.name == "leg-3")
        self.assertAlmostEqual(leg1.size_m[0], leg3.size_m[0])
        self.assertEqual(leg1.material, leg3.material)
        self.assertIn("leg-3", new_overrides)

    def test_incompatible_recipe_is_refused(self):
        design, _ = workshop_components.design_from_spec(self.base())
        top = workshop_components.component_recipe(design, "top")
        with self.assertRaises(ValueError):
            workshop_components.replace_with_recipe(self.base(), part_name="leg-1", recipe=top)


if __name__ == "__main__":
    unittest.main()
