"""The chat's tools are the MCP's tools, and this is what keeps them so.

The playground's chat used to carry a second, smaller tool set of its own, and
every capability the engine gained went into the MCP and never reached it. A
person asking the room for a gate on a hinge was talking to a model that had no
way to make a hinge.

Now the chat is handed the MCP's own tool definitions and every call runs the
MCP's own handler (playground/room_world.py). These tests fail the moment that
stops being true: when the MCP gains a tool the chat does not get and nobody
has said why, when a description or an argument drifts between the two, or
when a second tool list turns up in the playground again.

No model and no network: this is about what the model would be SENT.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))

import room_world   # noqa: E402  (puts mcp/ on the path)
import banjo_mcp    # noqa: E402
import world_chat   # noqa: E402
import world_room   # noqa: E402


class TheChatUsesTheMCP(unittest.TestCase):
    def test_every_mcp_tool_reaches_the_chat_or_is_excluded_for_a_reason(self):
        offered = {t["name"] for t in room_world.chat_tools()}
        for tool in banjo_mcp.TOOLS:
            name = tool["name"]
            if name in room_world.NOT_FOR_THE_ROOM:
                self.assertNotIn(name, offered)
                self.assertTrue(room_world.NOT_FOR_THE_ROOM[name].strip(),
                                f"{name} is kept from the chat with no reason given")
            else:
                self.assertIn(name, offered,
                              f"the MCP has {name!r} and the chat does not. Give it to "
                              f"the chat, or name it in room_world.NOT_FOR_THE_ROOM "
                              f"with the reason it does not belong in the room.")

    def test_no_exclusion_names_a_tool_that_is_gone(self):
        names = {t["name"] for t in banjo_mcp.TOOLS}
        for name in room_world.NOT_FOR_THE_ROOM:
            self.assertIn(name, names, f"{name} is excluded but the MCP has no such tool")

    def test_the_chat_is_told_exactly_what_the_mcp_publishes(self):
        by_name = {t["name"]: t for t in banjo_mcp.TOOLS}
        for tool in room_world.chat_tools():
            published = by_name[tool["name"]]
            self.assertEqual(tool["description"], published["description"])
            wanted = {k: v for k, v in
                      (published["inputSchema"].get("properties") or {}).items()
                      if k != "world_id"}
            self.assertEqual(tool["parameters"]["properties"], wanted,
                             f"{tool['name']}: the chat's arguments have drifted from "
                             f"the MCP's")
            self.assertNotIn("world_id", tool["parameters"].get("required", []))

    def test_every_published_tool_has_a_handler_and_the_other_way_round(self):
        self.assertEqual({t["name"] for t in banjo_mcp.TOOLS}, set(banjo_mcp.HANDLERS))

    def test_the_changes_that_reopen_the_room_are_real_tools(self):
        names = {t["name"] for t in banjo_mcp.TOOLS}
        self.assertLessEqual(room_world.AUTHORING, names)

    def test_what_is_sent_to_the_model_is_the_mcp_list(self):
        sent = world_chat.payload("a-model", [])["tools"]
        self.assertEqual(sent, room_world.chat_tools())

    def test_there_is_no_second_tool_list(self):
        self.assertFalse(hasattr(world_room, "TOOLS"),
                         "world_room has a TOOLS list again: the chat's tools are the "
                         "MCP's, through room_world, and nowhere else")
        for gone in ("add_object", "move_object", "remove_object", "clear_room"):
            self.assertFalse(hasattr(world_room.Room, gone),
                             f"Room.{gone} is back: a second implementation of a tool "
                             f"the MCP already has")


class TheRoomIsToldWhereThePersonIs(unittest.TestCase):
    """The page says where the person stands and faces. The chat is told it in
    words it can place things by, and nothing the page sent is taken on trust."""

    def test_a_person_is_said_with_the_point_a_metre_in_front(self):
        said = world_chat.where_the_person_is({"standing_m": [1.6, 0.0, 2.2],
                                               "facing": [-4.0, 1.0, -3.0],
                                               "looking_at": "the floor",
                                               "looking_at_m": [0.4, 0.0, 1.3]})
        self.assertEqual(said["facing"], [-0.8, 0.0, -0.6])
        self.assertEqual(said["one_metre_in_front_m"], [0.8, 1.6])
        # Facing (-0.8, -0.6): their left is (-0.6, +0.8), their right (+0.6, -0.8).
        self.assertEqual(said["one_metre_to_the_left_m"], [1.0, 3.0])
        self.assertEqual(said["one_metre_to_the_right_m"], [2.2, 1.4])
        self.assertEqual(said["looking_at"], "the floor")
        self.assertEqual(said["looking_at_m"], [0.4, 0.0, 1.3])

    def test_what_is_not_a_place_is_dropped_not_guessed(self):
        for junk in (None, "here", {}, {"standing_m": [1, 2], "facing": [0, 0, -1]},
                     {"standing_m": [0, 0, 0], "facing": [0, 1, 0]},
                     {"standing_m": [float("nan"), 0, 0], "facing": [0, 0, -1]},
                     {"standing_m": ["a", 0, 0], "facing": [0, 0, -1]}):
            self.assertIsNone(world_chat.where_the_person_is(junk), junk)

    def test_the_guide_and_the_tool_say_how_to_put_a_thing_down(self):
        for words in ("the_person", "one_metre_in_front_m", "position_m [x, z]", "in_water"):
            self.assertIn(words, world_chat.GUIDE)
        add = next(t for t in banjo_mcp.TOOLS if t["name"] == "add_object")
        place = add["inputSchema"]["properties"]["object"]["properties"]["position_m"]
        self.assertEqual((place["minItems"], place["maxItems"]), (2, 3))
        offered = next(t for t in room_world.chat_tools() if t["name"] == "add_object")
        self.assertIn("[x, z]", json.dumps(offered))


if __name__ == "__main__":
    unittest.main(verbosity=2)
