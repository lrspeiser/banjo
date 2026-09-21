"""The chat's tools are the MCP's tools, and this is what keeps them so.

The playground's chat used to carry a second, smaller tool set of its own, and
every capability the engine gained went into the MCP and never reached it. A
person asking the room for a gate on a hinge was talking to a model that had no
way to make a hinge.

Now the chat is handed the MCP's own tool definitions and every call runs the
MCP's own handler (playground/room_world.py). These tests fail the moment that
stops being true: when the MCP gains a tool the chat does not get and nobody
has said why, when a description or an argument drifts between the two, or
when a second tool list turns up in the playground again. And they fail when
the chat is given a tool that goes over HTTP to the playground's own room,
which is never the copy the chat builds in.

No model and no network: this is about what the model would be SENT.
"""
from __future__ import annotations

import inspect
import json
import math
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))

import room_world   # noqa: E402  (puts mcp/ on the path)
import banjo_mcp    # noqa: E402
import world_chat   # noqa: E402
import world_room   # noqa: E402
import expedition_mcp_tools     # noqa: E402
import fabrication_mcp_tools    # noqa: E402
import world_upgrade_mcp_tools  # noqa: E402

# The MCP's modules whose tools go over HTTP to the playground: the live
# expedition, the persistent funded fabrication room and a saved browser world.
PLAYGROUND_MODULES = (expedition_mcp_tools, fabrication_mcp_tools, world_upgrade_mcp_tools)

# What a module's source has in it when it can reach the playground over HTTP.
HTTP_MARKS = ("urlopen", "http.client", "BANJO_PLAYGROUND_URL", "_post(")


class TheChatUsesTheMCP(unittest.TestCase):
    def test_every_mcp_tool_reaches_the_chat_or_is_excluded_for_a_reason(self):
        offered = {t["name"] for t in room_world.chat_tools()}
        for tool in banjo_mcp.TOOLS:
            name = tool["name"]
            why = room_world.not_for_the_room(name)
            if why is not None:
                self.assertNotIn(name, offered)
                self.assertTrue(why.strip(), f"{name} is kept from the chat with no reason given")
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

    def test_what_works_the_room_as_it_stands_is_a_real_tool_and_opens_nothing(self):
        names = {t["name"] for t in banjo_mcp.TOOLS}
        self.assertLessEqual(room_world.LIVE, names)
        self.assertFalse(room_world.LIVE & room_world.AUTHORING,
                         "a call that works the room as it stands must not open it again")

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


class TheChatStaysOutOfThePlayground(unittest.TestCase):
    """The chat builds in a copy of the room. A tool that goes over HTTP to the
    playground works one of the playground's own rooms instead. That is how
    fabrication_recover, fabrication_retrieve_ground and fabrication_store_ground
    reached the chat: they were added to the MCP after NOT_FOR_THE_ROOM was
    written, and the first test above could not notice, because a tool the chat
    is given passes it."""

    def setUp(self):
        # Should anything get past these tests it would find a closed port, not
        # a room someone has open on 8765 -- and it fails the test before that.
        address = mock.patch.dict(os.environ, {"BANJO_PLAYGROUND_URL": "http://127.0.0.1:9"})
        address.start()
        self.addCleanup(address.stop)
        network = mock.patch("urllib.request.urlopen",
                             side_effect=AssertionError("the room's chat made an HTTP request"))
        self.urlopen = network.start()
        self.addCleanup(network.stop)

    def test_no_tool_that_goes_over_http_to_the_playground_reaches_the_chat(self):
        offered = {t["name"] for t in room_world.chat_tools()}
        for module in PLAYGROUND_MODULES:
            for tool in module.TOOLS:
                with self.subTest(tool=tool["name"]):
                    self.assertNotIn(tool["name"], offered,
                                     f"{tool['name']} ({module.__name__}.py) goes over HTTP "
                                     f"to the playground's own room, not the chat's copy")

    def test_the_rooms_rule_knows_every_one_of_them_named_or_not(self):
        # Each is also named in NOT_FOR_THE_ROOM, with its own reason; the rule
        # is what still keeps it out if that line is lost.
        for module in PLAYGROUND_MODULES:
            for tool in module.TOOLS:
                with self.subTest(tool=tool["name"]):
                    self.assertTrue(room_world.through_the_playground(tool["name"]))

    def test_the_room_refuses_each_one_before_any_request_is_made(self):
        # A model can call a tool by a name it was not given this turn.
        for module in PLAYGROUND_MODULES:
            for tool in module.TOOLS:
                with self.subTest(tool=tool["name"]):
                    answer = room_world.call("a-room", tool["name"], {})
                    self.assertIn("is not available in the room", answer.get("error", ""))
        self.urlopen.assert_not_called()

    def test_a_later_tool_that_goes_to_the_playground_is_kept_out_unnamed(self):
        """Written the way the fabrication tools are, and named nowhere."""
        module = types.ModuleType("a_later_playground_tool")
        exec("from expedition_mcp_tools import _post\n\n"
             "def handler(args):\n"
             "    return _post('/api/world/open', {'scene': 'fabrication'})\n",
             module.__dict__)
        tool = {"name": "a_later_playground_tool", "description": "Opens the fabrication room.",
                "inputSchema": {"type": "object", "properties": {}}}
        banjo_mcp.TOOLS.append(tool)
        self.addCleanup(banjo_mcp.TOOLS.remove, tool)
        banjo_mcp.HANDLERS[tool["name"]] = module.handler
        self.addCleanup(banjo_mcp.HANDLERS.pop, tool["name"])

        self.assertNotIn(tool["name"], room_world.NOT_FOR_THE_ROOM)
        self.assertNotIn(tool["name"], {t["name"] for t in room_world.chat_tools()})
        self.assertEqual(room_world.not_for_the_room(tool["name"]),
                         room_world.THROUGH_THE_PLAYGROUND)
        answer = room_world.call("a-room", tool["name"], {})
        self.assertIn("is not available in the room", answer["error"])
        self.urlopen.assert_not_called()

    def test_no_tool_the_chat_is_given_is_written_where_the_playground_is_reached(self):
        """The room's rule looks for expedition_mcp_tools._post. A module that
        reached the playground some other way would pass the rule, so this reads
        what the source of each handler the chat is given has in it."""
        for module in PLAYGROUND_MODULES:
            source = Path(module.__file__).read_text(encoding="utf-8")
            self.assertTrue(any(mark in source for mark in HTTP_MARKS),
                            f"{module.__name__}.py goes to the playground and none of "
                            f"{HTTP_MARKS} says so: this test would see nothing")
        written_in: dict[str, list[str]] = {}
        for tool in room_world.chat_tools():
            handler = inspect.unwrap(banjo_mcp.HANDLERS[tool["name"]])
            written_in.setdefault(inspect.getsourcefile(handler), []).append(tool["name"])
        self.assertTrue(written_in)
        for path, names in written_in.items():
            source = Path(path).read_text(encoding="utf-8")
            marks = [mark for mark in HTTP_MARKS if mark in source]
            self.assertFalse(marks,
                             f"the chat is given {', '.join(sorted(names))}, whose handlers are "
                             f"written in {Path(path).name}, which makes HTTP requests "
                             f"({', '.join(map(repr, marks))}). The chat works a copy of the "
                             f"room: name them in room_world.NOT_FOR_THE_ROOM with the reason, "
                             f"or, if they go to the playground, post through "
                             f"expedition_mcp_tools._post, which the room keeps out by itself.")


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

    def test_what_they_hold_is_this(self):
        """"Turn this upright": the page says what is in their hand, and the chat
        is told it by name, before anything they are looking at."""
        said = world_chat.where_the_person_is({"standing_m": [0.0, 0.0, 2.0],
                                               "facing": [0.0, 0.0, -1.0],
                                               "holding": "stone pillar",
                                               "holding_at_m": [0.4, 1.2, 1.5],
                                               "looking_at": "oak crate"})
        self.assertEqual(said["holding"], "stone pillar")
        self.assertEqual(said["holding_at_m"], [0.4, 1.2, 1.5])
        self.assertEqual(said["looking_at"], "oak crate")
        self.assertEqual(said["one_metre_in_front_m"], [0.0, 1.0])
        junk = world_chat.where_the_person_is({"standing_m": [0.0, 0.0, 2.0],
                                               "facing": [0.0, 0.0, -1.0], "holding": 42,
                                               "holding_at_m": ["a", 1, 2]})
        self.assertNotIn("holding", junk)
        self.assertNotIn("holding_at_m", junk)
        for words in ("holding", "\"This\"", "turn_object", "one_metre_in_front_m"):
            self.assertIn(words, world_chat.GUIDE)

    def test_what_is_not_a_place_is_dropped_not_guessed(self):
        for junk in (None, "here", {}, {"standing_m": [1, 2], "facing": [0, 0, -1]},
                     {"standing_m": [0, 0, 0], "facing": [0, 1, 0]},
                     {"standing_m": [float("nan"), 0, 0], "facing": [0, 0, -1]},
                     {"standing_m": ["a", 0, 0], "facing": [0, 0, -1]}):
            self.assertIsNone(world_chat.where_the_person_is(junk), junk)

    def test_new_things_go_on_clear_ground_close_in_front(self):
        """The owner: "put the item on the ground in front of them (close)". On
        empty ground: a metre ahead, then a step to their left and to their
        right of that."""
        person = world_chat.where_the_person_is({"standing_m": [0.0, 0.0, 3.0],
                                                 "facing": [0.0, 0.0, -1.0]})
        self.assertEqual(world_chat.clear_spots(person, []),
                         [[0.0, 2.0], [-0.8, 2.0], [0.8, 2.0]])
        # A floor slab, a lamp overhead and what they hold take no ground.
        free = [{"name": "floor", "shape": "box", "position_m": [0.0, -0.05, 0.0],
                 "dimensions_m": [20.0, 0.1, 20.0]},
                {"name": "lamp", "shape": "sphere", "position_m": [0.0, 2.5, 2.0],
                 "dimensions_m": [0.3, 0.3, 0.3]},
                {"name": "cup", "shape": "box", "position_m": [0.0, 0.6, 2.0],
                 "dimensions_m": [0.1, 0.1, 0.1], "held": True}]
        self.assertEqual(world_chat.clear_spots(person, free),
                         [[0.0, 2.0], [-0.8, 2.0], [0.8, 2.0]])

    def test_new_things_go_round_what_is_there_and_not_on_each_other(self):
        person = world_chat.where_the_person_is({"standing_m": [0.0, 0.0, 3.0],
                                                 "facing": [0.0, 0.0, -1.0]})
        # A table a metre ahead, turned a quarter so its long side runs toward
        # them: 0.6 m across and 1.6 m deep.
        table = {"name": "table", "shape": "box", "position_m": [0.0, 0.4, 2.0],
                 "dimensions_m": [1.6, 0.8, 0.6],
                 "orientation_wxyz": [0.7071068, 0.0, 0.7071068, 0.0]}
        spots = world_chat.clear_spots(person, [table])
        self.assertEqual(spots, [[-0.8, 2.0], [0.8, 2.0], [-1.6, 2.0]])
        for x, z in spots:
            gap = math.hypot(max(abs(x) - 0.3, 0.0), max(abs(z - 2.0) - 0.8, 0.0))
            self.assertGreaterEqual(gap, world_chat.NEW_THING_CLEAR_M, (x, z))
            self.assertLess(z, 3.0, "in front of them, never behind")
            self.assertLessEqual(math.hypot(x, z - 3.0), 2.5, "close")
        for i, a in enumerate(spots):
            for b in spots[i + 1:]:
                self.assertGreaterEqual(math.hypot(a[0] - b[0], a[1] - b[1]),
                                        world_chat.NEW_THING_APART_M)
        self.assertEqual(spots[0], [-0.8, 2.0], "beside the table before past it")
        self.assertIn("put_new_things_m", world_chat.GUIDE)
        # A thing to take, that is: a structure goes where there is room for
        # it, the size its use needs (STRUCTURES; the owner's review of
        # 2026-09-15, docs/building-from-language.md).
        guide = " ".join(world_chat.GUIDE.split())
        self.assertIn("A THING TO TAKE -- anything a person picks up, carries or uses in the hand -- goes "
                      "on the ground close in front of them", guide)
        self.assertIn("A STRUCTURE -- a ramp to ride, a bridge, a stair, a tower -- is not a thing to take",
                      guide)

    def test_a_structure_goes_out_in_front_across_the_view_where_nothing_stands(self):
        """A structure is not a thing to take: its middle out in front of them,
        its line across their view, and not where something already stands --
        a second one asked for from the same place went onto the first (the
        owner's review of 2026-09-15; STRUCTURES in the guide)."""
        person = world_chat.where_the_person_is({"standing_m": [0.0, 0.0, 3.0], "facing": [0.0, 0.0, -1.0]})
        middle, way = world_chat._structure_place(person, [])
        self.assertEqual((middle, way), ([0.0, -3.0], [1.0, 0.0, 0.0]), "6 m out, across their view")
        jump = {"name": "ski jump", "shape": "box", "position_m": [0.0, 1.2, -3.0], "dimensions_m": [6.5, 2.4, 0.6]}
        middle, _ = world_chat._structure_place(person, [jump])
        self.assertEqual(middle, [0.0, -7.0], "past the ski jump already there")
        # Turned a little, the line keeps to the room's nearest axis.
        person = world_chat.where_the_person_is({"standing_m": [0.0, 0.0, 0.0], "facing": [0.3, 0.0, -1.0]})
        self.assertEqual(world_chat._structure_place(person, [])[1], [1.0, 0.0, 0.0])

    def test_new_places_are_on_the_rooms_cell_grid(self):
        """A recipe worked out from the place keeps a joined piece on the grid:
        off it, a haft was lost from its pick (0.36 kg of 1.21)."""
        person = world_chat.where_the_person_is({"standing_m": [0.37, 0.0, 2.13],
                                                 "facing": [0.3, 0.0, -1.0]})
        for x, z in world_chat.clear_spots(person, [], grid_m=0.04):
            self.assertAlmostEqual(x / 0.04, round(x / 0.04), places=6)
            self.assertAlmostEqual(z / 0.04, round(z / 0.04), places=6)

    def test_the_guides_pick_is_the_recipe_the_ground_work_suite_tries(self):
        # tests/ground_work_mcp_tests.py builds and swings exactly these; the
        # guide's worked example for the place [0.0, 1.2] must come to them.
        for words in ("haft at [0.0, 0.02, 1.22]", "arm at [0.38, 0.02, 1.06]",
                      "tip at [0.38, 0.02, 0.92]", "grip at\n  [-0.36, 0.02, 1.22]",
                      "[px + 0.38, 0.02, pz - 0.16]", "[px - 0.36, 0.02, pz]"):
            self.assertIn(words, world_chat.GUIDE)

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
