"""The chat is sent the conversation, not only the last thing typed.

Asked "which pit, and how many bars?", a person answered "confirmed" -- and the
chat, sent only that word, described the room, built nothing, and then said no
gold had been placed. The turns before this one now go to the model ahead of
it, each room keeps its own conversation, and these tests pin both.

No model and no network: the model's side is a stand-in that records what it
was sent.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))

import room_world   # noqa: E402,F401  (puts mcp/ on the path, finds the library)
import world_chat   # noqa: E402
import world_room   # noqa: E402

LIBRARY = os.environ.get("BANJO_LIBRARY")


class TheConversationGoesToTheModel(unittest.TestCase):
    @unittest.skipUnless(LIBRARY and Path(LIBRARY).is_file(), "the library is not built")
    def test_earlier_turns_come_before_this_one(self):
        sent: list[list[dict]] = []

        def model(api_key, model_name, conversation):
            sent.append(list(conversation))
            return {"status": "completed", "usage": {},
                    "output": [{"type": "message",
                                "content": [{"type": "output_text", "text": "Three, then."}]}]}

        real, world_chat._call = world_chat._call, model
        try:
            history: list[dict] = []
            world_chat.remember_turn(history, "I'd like some crates. Ask me how many first.",
                                     {"reply": "How many would you like?", "did": []})
            answer = world_chat.ask("key", "a model", world_room.Room("yard"), {"bodies": []},
                                    "Three.", [], history=history)
        finally:
            world_chat._call = real
        first = sent[0]
        self.assertEqual(first[0], {"role": "user",
                                    "content": "I'd like some crates. Ask me how many first."})
        self.assertEqual(first[1]["role"], "assistant")
        self.assertIn("How many would you like?", first[1]["content"])
        self.assertEqual(json.loads(first[2]["content"])["what_you_were_asked"], "Three.")
        self.assertEqual(answer["reply"], "Three, then.")

    def test_what_was_done_is_said_with_the_answer(self):
        history: list[dict] = []
        world_chat.remember_turn(history, "a ball", {"reply": "Done.", "did": ["added rubber ball"]})
        said = world_chat._earlier_turns(history)
        self.assertEqual(said[1]["content"], "Done. [did: added rubber ball]")

    def test_a_turn_is_kept_short_and_the_conversation_bounded(self):
        history: list[dict] = []
        for k in range(world_chat.KEEP_TURNS + 10):
            world_chat.remember_turn(history, f"message {k}", {"reply": "x" * 5000, "did": []})
        self.assertEqual(len(history), world_chat.KEEP_TURNS)
        self.assertEqual(history[-1]["asked"], f"message {world_chat.KEEP_TURNS + 9}")
        self.assertLessEqual(len(history[-1]["replied"]), world_chat.SAID_CHARS)
        self.assertEqual(len(world_chat._earlier_turns(history)), 2 * world_chat.SEND_TURNS)
        world_chat.remember_turn(history, "boom", None, failure="the model timed out")
        self.assertIn("failed", history[-1]["replied"])

    def test_each_room_keeps_its_own_conversation(self):
        yard, bench = world_room.Room("yard"), world_room.Room("bench")
        self.assertEqual((yard.chat, bench.chat), ([], []))
        world_chat.remember_turn(yard.chat, "hello", {"reply": "Hello.", "did": []})
        self.assertEqual(len(yard.chat), 1)
        self.assertEqual(bench.chat, [])

    def test_the_guide_says_what_a_short_answer_means_and_what_there_is(self):
        for words in ("THE CONVERSATION", "confirmed", "MATERIALS", "gold"):
            self.assertIn(words, world_chat.GUIDE)


class WhyAnAnswerCameBackUnfinished(unittest.TestCase):
    """The page said "try a shorter request" whatever had gone wrong, and a
    one-line request once failed that way. The answer says why, so that is
    what the person is told."""

    def test_an_answer_that_ran_out_says_so(self):
        said = world_chat.unfinished({"status": "incomplete",
                                      "incomplete_details": {"reason": "max_output_tokens"}})
        self.assertIn(f"{world_chat.MAX_OUTPUT_TOKENS} tokens", said)
        self.assertIn("asking again", said)
        self.assertNotIn("shorter request", said)

    def test_other_reasons_are_named(self):
        self.assertIn("content filter", world_chat.unfinished(
            {"status": "incomplete", "incomplete_details": {"reason": "content_filter"}}))
        said = world_chat.unfinished({"status": "failed", "error": {"code": "server_error"}})
        self.assertIn("came back failed (server_error)", said)
        self.assertIn("came back no status", world_chat.unfinished({}))

    @unittest.skipUnless(LIBRARY and Path(LIBRARY).is_file(), "the library is not built")
    def test_the_room_is_told_why_and_is_not_changed(self):
        calls = []

        def model(api_key, model_name, conversation):
            calls.append(1)
            return {"status": "incomplete", "usage": {}, "output": [],
                    "incomplete_details": {"reason": "max_output_tokens"}}

        room = world_room.Room("yard")
        before = json.dumps(room.spec, sort_keys=True)
        real, world_chat._call = world_chat._call, model
        try:
            with self.assertRaises(ValueError) as failed:
                world_chat.ask("key", "a model", room, {"bodies": []}, "a crate", [], history=[])
        finally:
            world_chat._call = real
        self.assertIn("used up its whole answer", str(failed.exception))
        # Asked for once more, and only once, before the person is told.
        self.assertEqual(len(calls), 2)
        self.assertIn("asked once more", str(failed.exception))
        self.assertEqual(json.dumps(room.spec, sort_keys=True), before)

    @unittest.skipUnless(LIBRARY and Path(LIBRARY).is_file(), "the library is not built")
    def test_an_answer_that_ran_out_is_asked_for_once_more(self):
        """On Render a tower ran out at 6000 tokens in its first round; asked
        again, the same request took 727. The person should not have to ask."""
        sent: list[str] = []

        def model(api_key, model_name, conversation):
            sent.append(json.dumps(conversation))
            if len(sent) == 1:
                return {"status": "incomplete", "usage": {"output_tokens": 6000}, "output": [],
                        "incomplete_details": {"reason": "max_output_tokens"}}
            return {"status": "completed", "usage": {"output_tokens": 700},
                    "output": [{"type": "message",
                                "content": [{"type": "output_text", "text": "Built it."}]}]}

        trace: list = []
        real, world_chat._call = world_chat._call, model
        try:
            answer = world_chat.ask("key", "a model", world_room.Room("yard"), {"bodies": []},
                                    "a tower", [], history=[], trace=trace)
        finally:
            world_chat._call = real
        self.assertEqual(answer["reply"], "Built it.")
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0], sent[1], "nothing of the unfinished answer goes with the second")
        self.assertEqual(answer["usage"]["output_tokens"], 6700, "both answers are paid for and counted")
        self.assertTrue(any(isinstance(r, dict) and r.get("asked_again") for r in trace))

    @unittest.skipUnless(LIBRARY and Path(LIBRARY).is_file(), "the library is not built")
    def test_only_an_answer_that_ran_out_is_asked_for_again(self):
        calls = []

        def model(api_key, model_name, conversation):
            calls.append(1)
            return {"status": "incomplete", "usage": {}, "output": [],
                    "incomplete_details": {"reason": "content_filter"}}

        real, world_chat._call = world_chat._call, model
        try:
            with self.assertRaises(ValueError) as failed:
                world_chat.ask("key", "a model", world_room.Room("yard"), {"bodies": []},
                               "a crate", [], history=[])
        finally:
            world_chat._call = real
        self.assertEqual(len(calls), 1)
        self.assertIn("content filter", str(failed.exception))


class WhatThePersonCarries(unittest.TestCase):
    """The page tells the room what the person carries -- the soil a pick broke
    out, the glass swept up -- so "heap what I'm carrying here" means something.
    It arrives over HTTP, so only names and weights that make sense go on."""

    @unittest.skipUnless(LIBRARY and Path(LIBRARY).is_file(), "the library is not built")
    def test_the_model_is_sent_clear_ground_in_front_of_them_and_the_log_gets_it(self):
        """The owner: "when making something always pass the view the user has
        and put the item on the ground in front of them (close)". The model is
        sent where they are and clear places on the ground a metre ahead -- not
        on the crate already there -- and the turn's log is given exactly that,
        which it was not: the server logged its own copy, without the places."""
        sent: list[list[dict]] = []

        def model(api_key, model_name, conversation):
            sent.append(list(conversation))
            return {"status": "completed", "usage": {},
                    "output": [{"type": "message",
                                "content": [{"type": "output_text", "text": "Made."}]}]}

        crate = {"name": "crate", "shape": "box", "position_m": [0.0, 0.2, 2.2],
                 "dimensions_m": [0.4, 0.4, 0.4], "orientation_wxyz": [1.0, 0.0, 0.0, 0.0]}
        real, world_chat._call = world_chat._call, model
        try:
            answer = world_chat.ask("key", "a model", world_room.Room("yard"), {"bodies": [crate]},
                                    "make me a stool", [], history=[],
                                    person={"standing_m": [0.0, 0.0, 3.2], "facing": [0.0, 0.0, -1.0]})
        finally:
            world_chat._call = real
        told = json.loads(sent[0][-1]["content"])["the_person"]
        # A step to either side of the crate, then further round it: 1.5 m
        # ahead is within 0.4 m of it, or of the first two.
        self.assertEqual(told["put_new_things_m"], [[-0.8, 2.2], [0.8, 2.2], [-1.6, 2.2]])
        self.assertEqual(answer["the_person"], told)

    def test_what_they_carry_goes_to_the_room_and_nonsense_does_not(self):
        said = world_chat.where_the_person_is({
            "standing_m": [0, 0, 2.2], "facing": [0, 0, -1],
            "carrying": [{"what": "soil", "kg": 9.17}, {"what": "glass", "kg": "0.25"},
                         {"what": " ", "kg": 2}, {"what": "sand", "kg": -1}, {"kg": 3}, "junk",
                         {"what": "iron", "kg": float("nan")}]})
        self.assertEqual(said["carrying"], [{"what": "soil", "kg": 9.17}, {"what": "glass", "kg": 0.25}])

    def test_carrying_nothing_says_nothing(self):
        said = world_chat.where_the_person_is({"standing_m": [0, 0, 2.2], "facing": [0, 0, -1]})
        self.assertNotIn("carrying", said)


if __name__ == "__main__":
    unittest.main(verbosity=2)
