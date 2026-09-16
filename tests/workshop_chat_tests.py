#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))

import workshop_chat  # noqa: E402


class WorkshopChatFallback(unittest.TestCase):
    def test_all_legs_thinner_is_a_similar_scope_edit(self):
        answer = workshop_chat.fallback(
            "make all legs thinner", materials=["oak", "iron"], library=[])
        self.assertEqual("thinner", answer["action"])
        self.assertEqual("similar", answer["scope"])

    def test_material_is_chosen_only_from_available_materials(self):
        answer = workshop_chat.fallback(
            "make this iron", materials=["oak", "iron"], library=[])
        self.assertEqual("material", answer["action"])
        self.assertEqual("iron", answer["material"])

    def test_named_saved_component_can_be_reused(self):
        answer = workshop_chat.fallback(
            "use my sturdy leg", materials=["oak"],
            library=[{"item_id": "lib-1", "item_type": "component", "name": "Sturdy Leg"}])
        self.assertEqual("reuse", answer["action"])
        self.assertEqual("lib-1", answer["library_item_id"])

    def test_unknown_request_refuses_to_invent_an_edit(self):
        answer = workshop_chat.fallback(
            "make it feel magical", materials=["oak"], library=[])
        self.assertEqual("none", answer["action"])


if __name__ == "__main__":
    unittest.main()
