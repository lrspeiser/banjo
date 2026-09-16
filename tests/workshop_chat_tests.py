#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "playground"))

import access_gate  # noqa: E402
import workshop_chat  # noqa: E402
from mcp.workshop import assemble  # noqa: E402


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


class ConversationalWorkshop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.app = types.SimpleNamespace(workshop_store=root / "workshop", api_key="")
        self.app.workshop_store.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def candidate(kind: str = "table") -> dict:
        wire = assemble(kind, design_id="chat-candidate").wireframe()
        wire["component_overrides"] = {}
        return wire

    def test_all_legs_longer_changes_every_leg_not_only_selected_one(self):
        candidate = self.candidate()
        before = {p["name"]: list(p["size_m"]) for p in candidate["parts"]}
        selected = next(p for p in candidate["parts"] if p["name"] == "leg-1")
        result = workshop_chat.propose(
            self.app, message="make all the legs longer", selected_part=selected,
            candidate=candidate, materials=["oak", "iron", "aluminum"], library=[])
        legs = [p for p in candidate["parts"] if p["role"] == "leg"]
        self.assertEqual(4, len(legs))
        self.assertEqual({"leg-1", "leg-2", "leg-3", "leg-4"}, set(result["changed"]))
        for leg in legs:
            self.assertGreater(leg["size_m"][1], before[leg["name"]][1])
        self.assertEqual(before["top"], next(p for p in candidate["parts"] if p["name"] == "top")["size_m"])

    def test_one_turn_can_make_all_legs_longer_and_thinner(self):
        candidate = self.candidate()
        before = {p["name"]: list(p["size_m"]) for p in candidate["parts"]}
        selected = next(p for p in candidate["parts"] if p["name"] == "leg-1")
        result = workshop_chat.propose(
            self.app, message="make all the legs longer and thinner", selected_part=selected,
            candidate=candidate, materials=["oak", "iron"], library=[])
        legs = [p for p in candidate["parts"] if p["role"] == "leg"]
        for leg in legs:
            old = before[leg["name"]]
            self.assertGreater(leg["size_m"][1], old[1])
            self.assertLess(leg["size_m"][0], old[0])
            self.assertLess(leg["size_m"][2], old[2])
        edits = [row for row in result["tool_trace"] if row["tool"] == "edit_components"]
        self.assertEqual(2, len(edits))

    def test_chat_can_inspect_physics_without_changing_geometry(self):
        candidate = self.candidate()
        before = [dict(part) for part in candidate["parts"]]
        selected = candidate["parts"][0]
        result = workshop_chat.propose(
            self.app, message="what does the physics say about its mass and support?",
            selected_part=selected, candidate=candidate, materials=["oak", "iron"], library=[])
        self.assertEqual(before, candidate["parts"])
        self.assertEqual([], result["changed"])
        self.assertTrue(any(row["tool"] == "inspect_physics" for row in result["tool_trace"]))

    def test_tool_contract_exposes_position_subcomponents_physics_and_library(self):
        names = {tool["name"] for tool in workshop_chat._tool_definitions(["oak", "iron"])}
        self.assertTrue({
            "inspect_design", "inspect_component", "inspect_physics", "search_library",
            "edit_components", "set_parameter", "reuse_library_component",
        } <= names)

    def test_llm_path_can_inspect_then_apply_multiple_tools_in_one_turn(self):
        candidate = self.candidate()
        before = {p["name"]: list(p["size_m"]) for p in candidate["parts"]}
        self.app.api_key = "fake-key"
        self.app.model = "fake-model"
        replies = [
            {"id": "r1", "output": [
                {"type": "function_call", "call_id": "inspect-1",
                 "name": "inspect_design", "arguments": "{}"},
            ]},
            {"id": "r2", "output": [
                {"type": "function_call", "call_id": "edit-1", "name": "edit_components",
                 "arguments": '{"selector":{"roles":["leg"]},"action":"longer","amount":0.12,"material":null}'},
                {"type": "function_call", "call_id": "edit-2", "name": "edit_components",
                 "arguments": '{"selector":{"roles":["leg"]},"action":"thinner","amount":0.12,"material":null}'},
            ]},
            {"id": "r3", "output": [
                {"type": "message", "content": [
                    {"type": "output_text", "text": "I made all four legs longer and thinner."},
                ]},
            ]},
        ]
        with mock.patch.object(workshop_chat, "_call_model", side_effect=replies) as called:
            result = workshop_chat.propose(
                self.app, message="make all the legs longer and thinner",
                selected_part=None, candidate=candidate, materials=["oak", "iron"], library=[],
                history=[{"role": "user", "content": "We are working on the table."},
                         {"role": "assistant", "content": "I can inspect it first."}])
        self.assertEqual(3, called.call_count)
        self.assertEqual("I made all four legs longer and thinner.", result["reply"])
        self.assertEqual(["inspect_design", "edit_components", "edit_components"],
                         [row["tool"] for row in result["tool_trace"]])
        legs = [p for p in candidate["parts"] if p["role"] == "leg"]
        for leg in legs:
            old = before[leg["name"]]
            self.assertGreater(leg["size_m"][1], old[1])
            self.assertLess(leg["size_m"][0], old[0])


class ChatSurface(unittest.TestCase):
    def test_world_page_has_transcript_working_state_and_tool_trace_ui(self):
        page = (ROOT / "playground" / "world.html").read_text(encoding="utf-8")
        for marker in ("ws-chat-log", "Workshop assistant", "Working —",
                       "tool_trace", "CURRENT USER REQUEST", "Shift+Enter"):
            # Shift+Enter is described by behavior rather than visible copy in
            # the source, so the key handler itself is the durable assertion.
            if marker == "Shift+Enter":
                self.assertIn('event.key==="Enter"&&!event.shiftKey', page)
            else:
                self.assertIn(marker, page)
        self.assertIn("make all four legs longer and thinner", page)

    def test_world_csp_hashes_every_added_inline_workshop_block(self):
        scripts = access_gate._world_inline_hashes(r'<script\s+type=["\']module["\']>(.*?)</script>')
        styles = access_gate._world_inline_hashes(r"<style\b[^>]*>(.*?)</style>")
        self.assertGreaterEqual(len(scripts), 2)
        self.assertGreaterEqual(len(styles), 1)
        self.assertTrue(all(value.startswith("'sha256-") for value in scripts + styles))


if __name__ == "__main__":
    unittest.main()
