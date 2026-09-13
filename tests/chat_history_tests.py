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


if __name__ == "__main__":
    unittest.main(verbosity=2)
