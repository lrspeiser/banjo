#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import sys
import tempfile
import types
import pathlib
import unittest
from types import SimpleNamespace
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


class AReplyThatRanOutOfRoom(unittest.TestCase):
    """A turn the model never finished is not "no changes".

    The owner asked the Workshop for a shed, answered the three questions it
    put, and was told "I inspected the design but made no changes." The model
    had not decided that. Its reply came back with no words and the provider's
    status "incomplete" -- 1400 output tokens, shared with medium-effort
    reasoning, is not enough for a turn that thinks, calls a tool and then has
    to speak -- and that sentence was what the page showed when there were no
    words to show.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = types.SimpleNamespace(workshop_store=pathlib.Path(self.tmp.name) / "workshop",
                                         api_key="k", model="gpt-5-mini")

    def _answer(self, reply, changed_tool=None):
        candidate = assemble("table", design_id="chat-candidate").wireframe()
        candidate["component_overrides"] = {}
        replies = []
        if changed_tool:
            replies.append({"id": "r1", "output": [
                {"type": "function_call", "call_id": "c1", "name": changed_tool[0],
                 "arguments": changed_tool[1]}]})
        replies.append(reply)
        with mock.patch.object(workshop_chat, "_call_model", side_effect=replies):
            return workshop_chat.propose(
                self.app, message="make a small shed with a door", selected_part=None,
                candidate=candidate, materials=["oak"], library=[], history=[])

    def test_it_says_it_ran_out_rather_than_saying_nothing_changed(self):
        said = self._answer({"id": "r1", "status": "incomplete",
                             "incomplete_details": {"reason": "max_output_tokens"},
                             "output": []})["reply"]
        print(f"\n    cut off: {said}", flush=True)
        self.assertIn("ran out of room", said)
        self.assertNotIn("made no changes", said)

    def test_a_finished_reply_with_no_words_still_says_nothing_changed(self):
        said = self._answer({"id": "r1", "status": "completed", "output": []})["reply"]
        self.assertIn("made no changes", said)

    def test_no_call_puts_a_ceiling_on_how_far_the_model_may_think(self):
        """A ceiling on output tokens is a ceiling on THINKING.

        The provider counts reasoning against max_output_tokens, so a turn cut
        off mid-thought comes back with no words -- which is how "I inspected
        the design but made no changes" got said about a turn that had done
        neither. The owner: "we should not need to limit the tokens to get
        there." What bounds a turn is rounds and seconds, not words.
        """
        self.assertFalse(hasattr(workshop_chat, "MAX_OUTPUT_TOKENS"))
        candidate = assemble("table", design_id="chat-candidate").wireframe()
        candidate["component_overrides"] = {}
        sent = []

        def remember(app, payload):
            sent.append(payload)
            return {"id": "r1", "output": [{"type": "message", "content": [
                {"type": "output_text", "text": "Done."}]}]}

        with mock.patch.object(workshop_chat, "_call_model", side_effect=remember):
            workshop_chat.propose(self.app, message="make it taller", selected_part=None,
                                  candidate=candidate, materials=["oak"], library=[], history=[])
        self.assertTrue(sent)
        for payload in sent:
            self.assertNotIn("max_output_tokens", payload)

    def test_a_long_turn_wraps_up_instead_of_being_thrown_away(self):
        """It used to raise, and the person lost every edit it had made.

        "Workshop chat could not finish within its bounded reasoning loop" was
        what the owner saw, for a turn that had already done the work.
        """
        candidate = assemble("table", design_id="chat-candidate").wireframe()
        candidate["component_overrides"] = {}
        going = {"id": "r", "output": [{"type": "function_call", "call_id": "c",
                                        "name": "inspect_design", "arguments": "{}"}]}
        wrapped = {"id": "last", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": "I stopped there. The legs are longer; the top is not."}]}]}
        calls = []

        def answer(app, payload):
            calls.append(payload)
            # Every round asks for another tool, so the round budget runs out.
            return wrapped if payload.get("tool_choice") == "none" else going

        with mock.patch.object(workshop_chat, "_call_model", side_effect=answer):
            said = workshop_chat.propose(
                self.app, message="build me a shed", selected_part=None, candidate=candidate,
                materials=["oak"], library=[], history=[])["reply"]
        print("\n    wrapped up: " + said, flush=True)
        self.assertEqual("I stopped there. The legs are longer; the top is not.", said)
        self.assertEqual("none", calls[-1]["tool_choice"], "the last call has the tools off")
        self.assertEqual([], calls[-1]["tools"])
        self.assertEqual(workshop_chat.MAX_TOOL_ROUNDS + 2, len(calls))

    def test_a_long_turn_whose_wrap_up_is_silent_still_says_what_it_ran(self):
        candidate = assemble("table", design_id="chat-candidate").wireframe()
        candidate["component_overrides"] = {}
        going = {"id": "r", "output": [{"type": "function_call", "call_id": "c",
                                        "name": "inspect_design", "arguments": "{}"}]}

        def answer(app, payload):
            if payload.get("tool_choice") == "none":
                raise ValueError("the wrap-up call failed too")
            return going

        with mock.patch.object(workshop_chat, "_call_model", side_effect=answer):
            said = workshop_chat.propose(
                self.app, message="build me a shed", selected_part=None, candidate=candidate,
                materials=["oak"], library=[], history=[])["reply"]
        print(f"    silent wrap-up: {said}", flush=True)
        self.assertIn("inspect_design", said)
        self.assertIn("had to stop", said)
        self.assertNotIn("bounded reasoning loop", said)


class AQuestionComesWithAnswers(unittest.TestCase):
    """The owner: "Always give a suggested answer not an open ended question,
    as long as they can do other it is fine."

    A question in prose makes the person invent the option themselves, which is
    the work they came to the bench to be spared.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = types.SimpleNamespace(workshop_store=pathlib.Path(self.tmp.name) / "workshop",
                                         api_key="k", model="gpt-5-mini")

    @staticmethod
    def a_table():
        candidate = assemble("table", design_id="chat-candidate").wireframe()
        candidate["component_overrides"] = {}
        return candidate

    def asked(self, arguments):
        replies = [{"id": "r1", "output": [
            {"type": "function_call", "call_id": "q1", "name": "ask_the_person",
             "arguments": arguments}]}]
        with mock.patch.object(workshop_chat, "_call_model", side_effect=replies) as called:
            answer = workshop_chat.propose(
                self.app, message="make the legs stronger", selected_part=None,
                candidate=self.a_table(), materials=["oak", "iron"], library=[], history=[])
        return answer, called

    def test_the_tool_is_offered_at_all(self):
        names = {tool["name"] for tool in workshop_chat._tool_definitions(["oak"])}
        self.assertIn("ask_the_person", names)
        rule = workshop_chat.SYSTEM
        self.assertIn("NEVER END A TURN WITH AN OPEN QUESTION IN PROSE", rule)

    def test_asking_ends_the_turn_and_carries_the_options(self):
        answer, called = self.asked(
            '{"question":"How much stronger?","options":['
            '{"label":"Make it 50 mm","why":"the usual for a table this size"},'
            '{"label":"Add a sleeve"}]}')
        self.assertEqual(1, called.call_count, "it does not go round again to answer itself")
        self.assertEqual("How much stronger?", answer["reply"])
        asking = answer["asking"]
        self.assertEqual(["Make it 50 mm", "Add a sleeve"], [o["label"] for o in asking["options"]])
        self.assertEqual("the usual for a table this size", asking["options"][0]["why"])
        self.assertFalse(asking["several"])
        # Writing their own is never taken away: it is what makes a suggested
        # answer a suggestion rather than a cage.
        self.assertTrue(asking["allow_other"])

    def test_several_answers_can_be_picked_at_once(self):
        answer, _ = self.asked('{"question":"Which of these?","several":true,"options":['
                               '{"label":"Thicker legs"},{"label":"A stretcher"},{"label":"Iron feet"}]}')
        self.assertTrue(answer["asking"]["several"])
        self.assertEqual(3, len(answer["asking"]["options"]))

    def test_a_question_with_no_answers_is_refused(self):
        """Refusing it is the point: an open question is what it replaces."""
        replies = [
            {"id": "r1", "output": [{"type": "function_call", "call_id": "q1",
                                     "name": "ask_the_person",
                                     "arguments": '{"question":"What would you like?","options":[]}'}]},
            {"id": "r2", "output": [{"type": "message", "content": [
                {"type": "output_text", "text": "Made the legs 50 mm."}]}]},
        ]
        with mock.patch.object(workshop_chat, "_call_model", side_effect=replies):
            answer = workshop_chat.propose(
                self.app, message="make the legs stronger", selected_part=None,
                candidate=self.a_table(), materials=["oak"], library=[], history=[])
        self.assertIsNone(answer["asking"])
        self.assertEqual("Made the legs 50 mm.", answer["reply"])
        refused = [row for row in answer["tool_trace"] if row["tool"] == "ask_the_person"]
        self.assertEqual(1, len(refused))
        self.assertFalse(refused[0]["ok"])
        self.assertIn("two answers", refused[0]["summary"])

    def test_a_turn_that_asks_nothing_carries_no_question(self):
        replies = [{"id": "r1", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": "Done."}]}]}]
        with mock.patch.object(workshop_chat, "_call_model", side_effect=replies):
            answer = workshop_chat.propose(
                self.app, message="make it taller", selected_part=None, candidate=self.a_table(),
                materials=["oak"], library=[], history=[])
        self.assertIsNone(answer["asking"])


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
