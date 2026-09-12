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


if __name__ == "__main__":
    unittest.main(verbosity=2)
