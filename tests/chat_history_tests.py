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
import math
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


class ThingsMadeAreGivenActions(unittest.TestCase):
    """A turn that made things and offered them nothing is asked once more: the
    room's chat, asked for a latched gate, answered without offer_actions. A turn
    that made nothing is not: asked after digging a channel, the chat told the
    person "You're right" and offered a marker post to hang actions on."""

    @unittest.skipUnless(LIBRARY and Path(LIBRARY).is_file(), "the library is not built")
    def test_asked_once_more_only_when_something_was_made(self):
        for makes in (True, False):
            sent: list[list[dict]] = []

            def model(api_key, model_name, conversation, makes=makes):
                sent.append(list(conversation))
                if len(sent) == 1:
                    call = ({"name": "add_object", "arguments": json.dumps({"object": {
                                "name": "test crate", "shape": "box", "material": "oak",
                                "size_m": [0.3, 0.3, 0.3], "position_m": [0.0, 1.0]}})}
                            if makes else {"name": "describe_world", "arguments": "{}"})
                    return {"status": "completed", "usage": {},
                            "output": [dict(call, type="function_call", call_id="c1")]}
                return {"status": "completed", "usage": {},
                        "output": [{"type": "message",
                                    "content": [{"type": "output_text", "text": f"answer {len(sent)}"}]}]}

            real, world_chat._call = world_chat._call, model
            try:
                answer = world_chat.ask("key", "a model", world_room.Room("yard"), {"bodies": []},
                                        "a crate, please", [])
            finally:
                world_chat._call = real
            noted = [m for m in sent[-1] if isinstance(m, dict)
                     and m.get("content") == world_chat.NOTHING_OFFERED]
            if makes:
                self.assertEqual((len(sent), len(noted), answer["reply"]), (3, 1, "answer 3"))
            else:
                self.assertEqual((len(sent), len(noted), answer["reply"]), (2, 0, "answer 2"))


class WhatWasDoneIsSaidInWords(unittest.TestCase):
    def test_a_recipe_built_is_said_by_what_it_is_and_where(self):
        """Under the chat's answer the page showed "did: build_recipe None to
        None" for a table and chair built by recipe."""
        said = world_chat._did("build_recipe", {"recipe": "table", "at_m": [10.4, -3.2]},
                               {"built": "a small oak table with a chair drawn up to it",
                                "at_m": [10.4, -3.2]})
        self.assertEqual(said, "built a small oak table with a chair drawn up to it at [10.40, -3.20]")


class AClaimWithNothingDoneIsQuestioned(unittest.TestCase):
    """Asked for a table and a chair, the room's chat called no tool and
    answered "Built a small oak table ... I tried it: the table stood on its
    legs" -- the recipe's own words from its guide -- and nothing was there. A
    turn that says it built something with nothing changed is asked once more;
    an answer that claims nothing is not."""

    @unittest.skipUnless(LIBRARY and Path(LIBRARY).is_file(), "the library is not built")
    def test_asked_again_only_when_it_says_it_built_and_nothing_changed(self):
        for first, again in (("Built a small oak table with an oak chair drawn up to it.", True),
                             ("That is the castle gate's winch.", False)):
            sent: list[list[dict]] = []

            def model(api_key, model_name, conversation, first=first):
                sent.append(list(conversation))
                text = first if len(sent) == 1 else "answer 2"
                return {"status": "completed", "usage": {},
                        "output": [{"type": "message",
                                    "content": [{"type": "output_text", "text": text}]}]}

            real, world_chat._call = world_chat._call, model
            try:
                answer = world_chat.ask("key", "a model", world_room.Room("yard"), {"bodies": []},
                                        "a table and a chair, please", [])
            finally:
                world_chat._call = real
            noted = [m for m in sent[-1] if isinstance(m, dict)
                     and m.get("content") == world_chat.NOTHING_DONE]
            if again:
                self.assertEqual((len(sent), len(noted), answer["reply"]), (2, 1, "answer 2"))
            else:
                self.assertEqual((len(sent), len(noted), answer["reply"]), (1, 0, first))


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
                                "content": [{"type": "output_text", "text": "Here is a tower."}]}]}

        trace: list = []
        real, world_chat._call = world_chat._call, model
        try:
            answer = world_chat.ask("key", "a model", world_room.Room("yard"), {"bodies": []},
                                    "a tower", [], history=[], trace=trace)
        finally:
            world_chat._call = real
        # (Not "Built it.": with no tool called, that is a claim the room
        # questions -- AClaimWithNothingDoneIsQuestioned.)
        self.assertEqual(answer["reply"], "Here is a tower.")
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


class WorkingTheRoomAsItStands(unittest.TestCase):
    """The owner, 2026-09-15: "nothing should be resetting rooms". Asked to work
    something, the chat presses its action on the room as it stands
    (use_action) or tells its motor (drive): both go to the running room
    through `live`, and nothing in the turn opens the room again."""

    @unittest.skipUnless(LIBRARY and Path(LIBRARY).is_file(), "the library is not built")
    def test_a_things_action_and_its_motor_go_to_the_running_room(self):
        rounds = iter([
            [{"type": "function_call", "call_id": "c1", "name": "use_action",
              "arguments": json.dumps({"name": "hoist: drum", "action": "Wind it up"})}],
            [{"type": "function_call", "call_id": "c2", "name": "drive",
              "arguments": json.dumps({"part": "hoist: drum", "command": 0.5})}],
            [{"type": "message", "content": [{"type": "output_text", "text": "Winding it, at half."}]}]])

        def model(api_key, model_name, conversation):
            return {"status": "completed", "usage": {}, "output": next(rounds)}

        worked: list = []

        def live(name, args):
            worked.append((name, dict(args)))
            if name == "use_action":
                return {"used": "hoist: drum", "action": "Wind it up", "done": ["wound"]}
            return {"in_the_room": "told"}

        room = world_room.Room("tests-machines")
        real, world_chat._call = world_chat._call, model
        try:
            answer = world_chat.ask("key", "a model", room, {"bodies": []},
                                    "wind it up, then run it at half", [], live=live)
        finally:
            world_chat._call = real
        self.assertEqual([name for name, _ in worked], ["use_action", "drive"])
        self.assertEqual(worked[0][1], {"name": "hoist: drum", "action": "Wind it up"})
        self.assertEqual((worked[1][1]["command"], worked[1][1]["brake"]), (0.5, False))
        self.assertFalse(answer["changed"], "working the hoist would open the room again")
        self.assertTrue(answer["worked"])
        self.assertEqual(answer["reply"], "Winding it, at half.")
        self.assertIn("Wind it up on hoist: drum", " ".join(answer["did"]))
        # What its motor was told is written into the room, so it goes on doing
        # it if the room is opened again.
        motor = room.spec["machines"]["motors"][0]
        self.assertEqual((motor["command"], motor["brake"]), (0.5, False))

    @unittest.skipUnless(LIBRARY and Path(LIBRARY).is_file(), "the library is not built")
    def test_a_machine_worked_from_its_controller_goes_to_the_running_room(self):
        """Asked to raise the hoist, the chat works its controller (operate), as
        the person's panel does: what its copy made of the words -- power on,
        raise, at the setting it had -- goes to the running room through `live`,
        is written into the room, and opens nothing."""
        rounds = iter([
            [{"type": "function_call", "call_id": "c1", "name": "operate",
              "arguments": json.dumps({"machine": "hoist", "direction": "raise"})}],
            [{"type": "message", "content": [{"type": "output_text", "text": "Raising it."}]}]])

        def model(api_key, model_name, conversation):
            return {"status": "completed", "usage": {}, "output": next(rounds)}

        worked: list = []

        def live(name, args):
            worked.append((name, dict(args)))
            return {"in_the_room": "told"}

        room = world_room.Room("tests-machines")
        real, world_chat._call = world_chat._call, model
        try:
            answer = world_chat.ask("key", "a model", room, {"bodies": []}, "raise the hoist", [], live=live)
        finally:
            world_chat._call = real
        self.assertEqual([name for name, _ in worked], ["operate"])
        told = worked[0][1]
        self.assertEqual((told["machine"], told["power"], told["direction"], told["setting"]),
                         ("hoist", True, 1, 1.0))
        self.assertFalse(answer["changed"], "working the hoist would open the room again")
        self.assertTrue(answer["worked"])
        self.assertIn("worked hoist", " ".join(answer["did"]))
        # Written into the room, as a motor's command is.
        control = room.spec["machines"]["controls"][0]
        self.assertEqual((control["name"], control["power"], control["direction"]), ("hoist", True, 1))

    @unittest.skipUnless(LIBRARY and Path(LIBRARY).is_file(), "the library is not built")
    def test_what_works_the_running_room_after_a_change_waits_for_the_change(self):
        """Asked to wind a hoist up onto a block it had just added, the chat
        pressed "Wind it up" on the running room, where the block was not yet --
        the change goes in as the turn ends -- and described the crate stopping
        on it from its own copy. A call that works the running room after a
        change in the same turn is held back, for the server to make once the
        change is in."""
        rounds = iter([
            [_function_call("c1", "add_object", {"object": {
                "name": "stop block", "shape": "box", "material": "oak", "size_m": [0.3, 0.3, 0.3],
                "position_m": [6.0, 6.0], "anchored": True}})],
            [_function_call("c2", "use_action", {"name": "hoist: drum", "action": "Wind it up"})],
            [_function_call("c3", "drive", {"part": "hoist: drum", "command": 0.5})],
            _message("It will wind up once the block is in.")])

        def model(api_key, model_name, conversation):
            return {"status": "completed", "usage": {}, "output": next(rounds)}

        worked: list = []

        def live(name, args):
            worked.append(name)
            return {"in_the_room": "told"}

        room = world_room.Room("tests-machines")
        real, world_chat._call = world_chat._call, model
        try:
            answer = world_chat.ask("key", "a model", room, {"bodies": []},
                                    "put a block under the crate and wind it up onto it", [], live=live)
        finally:
            world_chat._call = real
        self.assertEqual(worked, [], "the running room was worked before the block was in it")
        self.assertTrue(answer["changed"])
        self.assertEqual([held["name"] for held in answer["deferred"]], ["use_action", "drive"])
        self.assertEqual(answer["deferred"][0]["args"], {"name": "hoist: drum", "action": "Wind it up"})
        told = answer["deferred"][1]["args"]
        self.assertEqual((told["command"], told["brake"]), (0.5, False))
        self.assertIn("pressed Wind it up on hoist: drum once the change was in", answer["did"])


def _function_call(call_id: str, name: str, args: dict) -> dict:
    return {"type": "function_call", "call_id": call_id, "name": name, "arguments": json.dumps(args)}


def _message(text: str) -> list[dict]:
    return [{"type": "message", "content": [{"type": "output_text", "text": text}]}]


CELL = 0.04


def _board(name: str, start: list, facing: list, top_s: float, top_y: float, angle: float,
           length: float, width: float, thick: float = 0.04):
    """An anchored oak board along a line on the ground (start [x, z], facing),
    whose top starts top_s along it at top_y and runs `length` -- made a whole
    number of cells -- at `angle` degrees; and the height of its underside at s
    along the line."""
    length = round(length / CELL) * CELL
    a = math.radians(angle)
    s = top_s + math.cos(a) * length / 2 + math.sin(a) * thick / 2
    y = top_y + math.sin(a) * length / 2 - math.cos(a) * thick / 2
    yaw = math.degrees(math.atan2(-facing[2], facing[0]))
    made = {"name": name, "shape": "box", "material": "oak", "size_m": [length, thick, width],
            "position_m": [start[0] + facing[0] * s, y, start[1] + facing[2] * s],
            "rotation_deg": [0, yaw, angle], "anchored": True}
    return made, (lambda at: top_y + (at - top_s) * math.tan(a) - thick / math.cos(a))


def _post(name: str, start: list, facing: list, s: float, under: float, aside: float = 0.0,
          short_by: float = 0.0) -> dict:
    """An anchored 80 mm square post s along the line and `aside` of it, from
    the ground to as high as fits under `under` in whole cells, less short_by."""
    height = math.floor(under / CELL + 1e-9) * CELL - short_by
    return {"name": name, "shape": "box", "material": "oak", "size_m": [0.08, height, 0.08],
            "position_m": [start[0] + facing[0] * s - facing[2] * aside, height / 2,
                           start[1] + facing[2] * s + facing[0] * aside], "anchored": True}


class AStructureIsHeldToWhatItWasDeclaredToDo(unittest.TestCase):
    """The owner's review of 2026-09-15 (docs/building-from-language.md): asked
    for a long ski ramp, both chats built one tilted board and called it a ski
    ramp, and the room accepted it. A structure is declared before it is built
    (plan_construction) and measured against what its kind must do from the
    world's own geometry (check_construction) -- in the room's own MCP world,
    as the chat builds it. Done when a flat board cannot satisfy a ski-jump
    request merely by being named "ramp"."""

    def setUp(self):
        if not (LIBRARY and Path(LIBRARY).is_file()):
            self.skipTest("the library is not built")
        self.world_id = room_world.open_room(world_room.Room("yard").spec)
        self.addCleanup(room_world.close_room, self.world_id)

    def call(self, tool: str, /, **args) -> dict:
        answer = room_world.call(self.world_id, tool, args)
        self.assertNotIn("error", answer, f"{tool} refused")
        return answer

    def refused(self, tool: str, /, **args) -> str:
        answer = room_world.call(self.world_id, tool, args)
        self.assertIn("error", answer, f"{tool} was expected to refuse")
        return answer["error"]

    def build(self, name: str, parts, declared: dict, start: list, facing: list, changed=None) -> dict:
        """One of the guide's worked structures, from its numbers, along a line
        -- each part `changed` first when given -- and its measurements."""
        planned = self.call("plan_construction", name=name, reading=f"the guide's {declared['kind']}",
                            start_m=start, facing=facing, **declared)
        ux, uz = facing[0], facing[2]
        for part in parts:
            part = changed(dict(part)) if changed else part
            s, aside = part["s_m"], part.get("aside_m", 0.0)
            self.call("add_object", object={
                "name": f"{name} {part['name']}", "shape": "box", "material": "oak", "size_m": part["size_m"],
                "position_m": [start[0] + ux * s - uz * aside, part["y_m"], start[1] + uz * s + ux * aside],
                "rotation_deg": [0, planned["line"]["yaw_deg"], part["tilt_deg"]], "anchored": True})
        return self.call("check_construction", name=name)

    def build_the_guides_ski_jump(self, name: str, start: list, facing: list) -> dict:
        return self.build(name, world_chat.SKI_JUMP_EXAMPLE, world_chat.SKI_JUMP_DECLARED, start, facing)

    def test_the_guides_staircase_and_bridge_pass_every_check_along_two_lines(self):
        for i, (title, parts, declared, _) in enumerate(world_chat.WORKED_STRUCTURES[1:]):
            for name, start, facing in ((f"{title} along x", [0.0, 4.0 * i], [1, 0, 0]),
                                        (f"{title} along -z", [10.0 + 4.0 * i, 12.0], [0, 0, -1])):
                with self.subTest(name=name):
                    checked = self.build(name, parts, declared, start, facing)
                    self.assertTrue(checked["passed"], checked["results"])
                    self.assertEqual(len(checked["parts"]), len(parts))

    def test_a_bridge_short_of_its_far_end_does_not_reach_it(self):
        def shorter(part):
            if part["name"] == "deck":
                part.update(size_m=[3.0, 0.04, 1.0], s_m=1.5)
            elif part["s_m"] > 3.0:
                part["s_m"] = 2.9
            return part
        checked = self.build("bridge", world_chat.BRIDGE_EXAMPLE, world_chat.BRIDGE_DECLARED, [0.0, 0.0], [1, 0, 0],
                             changed=shorter)
        self.assertEqual(checked["failed"], ["reaches"])

    def test_a_bridge_laid_on_the_ground_is_not_clear_of_what_it_crosses(self):
        checked = self.build("bridge", [dict(world_chat.BRIDGE_EXAMPLE[0], y_m=0.02)], world_chat.BRIDGE_DECLARED,
                             [0.0, 0.0], [1, 0, 0])
        self.assertEqual(checked["failed"], ["clear of what it crosses"])

    def test_stairs_with_one_high_step_are_not_even(self):
        def higher(part):
            if part["name"] == "step 6":
                part["y_m"] += 0.08
            elif part["name"] == "riser 6":
                part.update(size_m=[0.04, part["size_m"][1] + 0.08, 0.8], y_m=part["y_m"] + 0.04)
            return part
        checked = self.build("stairs", world_chat.STAIRCASE_EXAMPLE, world_chat.STAIRCASE_DECLARED, [0.0, 0.0],
                             [1, 0, 0], changed=higher)
        self.assertEqual(checked["failed"], ["steps"])
        self.assertIn("step 6 rises 0.24 m", next(r for r in checked["results"] if r["requirement"] == "steps")
                      ["measured"])

    def test_a_board_named_a_ramp_is_not_a_ski_jump(self):
        """The lab's own baseline: one 1600 x 600 x 100 mm oak board tilted 12
        degrees, named "ramp", declared a ski jump of the kind's own size."""
        self.call("plan_construction", name="ski ramp", kind="ski_jump", reading="a long ski jump",
                  start_m=[0.0, 0.0], facing=[1, 0, 0])
        self.call("add_object", object={"name": "ramp", "shape": "box", "material": "oak", "size_m": [1.6, 0.1, 0.6],
                                        "position_m": [0.78, 0.0], "rotation_deg": [0, 0, -12], "anchored": True})
        checked = self.call("check_construction", name="ski ramp")
        self.assertFalse(checked["passed"])
        self.assertEqual(checked["failed"], ["length", "width", "start height", "coming down", "takeoff"])

    def test_a_ramp_as_long_and_high_as_a_ski_jump_that_never_turns_up_is_not_one(self):
        """Two boards end to end on posts, 6.5 m from 2.4 m up: everything a
        ski jump must be but its takeoff."""
        start, facing = [0.0, 0.0], [1, 0, 0]
        self.call("plan_construction", name="ski jump", kind="ski_jump", reading="a ski jump",
                  start_m=start, facing=facing, length_m=6.5, width_m=0.6, height_m=2.4)
        one, under_one = _board("run 1", start, facing, 0.0, 2.4, -19.8, 3.48, 0.6)
        end = (3.48 * math.cos(math.radians(19.8)), 2.4 - 3.48 * math.sin(math.radians(19.8)))
        two, under_two = _board("run 2", start, facing, end[0] + 0.01, end[1], -19.8, 3.48, 0.6)
        for part in (one, two, _post("post 1", start, facing, 0.2, under_one(0.24)),
                     _post("post 2", start, facing, 3.0, under_one(3.04)),
                     _post("post 3", start, facing, 6.2, under_two(6.24))):
            self.call("add_object", object=part)
        checked = self.call("check_construction", name="ski jump")
        self.assertEqual(checked["failed"], ["takeoff"])
        takeoff = next(r for r in checked["results"] if r["requirement"] == "takeoff")
        self.assertEqual(takeoff["measured"], "falling 19.8 degrees")

    def test_the_guides_ski_jump_passes_every_check_along_two_lines(self):
        """The worked ski jump the room's guide gives, built from its numbers
        along +x and along +z, with the turn plan_construction's answer gives."""
        for name, start, facing in (("jump along x", [0.0, 0.0], [1, 0, 0]),
                                    ("jump along z", [10.0, 0.0], [0, 0, 1])):
            with self.subTest(name=name):
                checked = self.build_the_guides_ski_jump(name, start, facing)
                self.assertTrue(checked["passed"], checked["failed"])
                self.assertEqual(len(checked["results"]), 9)
                self.assertEqual(len(checked["parts"]), len(world_chat.SKI_JUMP_EXAMPLE))

    def test_a_board_on_four_feet_two_taller_is_a_downhill_ramp(self):
        """The owner's question, 2026-09-15: "a ski ramp could also be a rotated
        board on a base of 4 feet with two higher than the others". It is judged
        by what it does, not its shape."""
        start, facing, length = [0.0, 0.0], [1, 0, 0], 3.6
        self.call("plan_construction", name="board on feet", kind="downhill_ramp",
                  reading="a board on four feet, two taller than the others", start_m=start, facing=facing,
                  length_m=length, width_m=0.8, height_m=1.2)
        deck, under = _board("board", start, facing, 0.0, 1.2, -15.0, length / math.cos(math.radians(15)), 0.8)
        self.call("add_object", object=deck)
        feet = [_post(f"foot {i}", start, facing, s, under(s + 0.04), aside)
                for i, (s, aside) in enumerate(((0.3, 0.32), (0.3, -0.32), (3.3, 0.32), (3.3, -0.32)), 1)]
        for foot in feet:
            self.call("add_object", object=foot)
        self.assertEqual(len({foot["size_m"][1] for foot in feet}), 2, "two feet taller than the other two")
        checked = self.call("check_construction", name="board on feet")
        self.assertTrue(checked["passed"], checked["failed"])

    def test_a_post_short_of_what_it_holds_up_does_not_hold_it_up(self):
        """A level box round a tilted board is far bigger than the board: a post
        half a metre short of its underside would have counted as touching it."""
        start, facing = [0.0, 0.0], [1, 0, 0]
        self.call("plan_construction", name="ramp", kind="downhill_ramp", reading="a ramp",
                  start_m=start, facing=facing, length_m=3.5, width_m=0.8, height_m=1.2)
        deck, under = _board("high board", start, facing, 0.0, 1.6, -10.0, 3.6 / math.cos(math.radians(10)), 0.8)
        self.call("add_object", object=deck)
        self.call("add_object", object=_post("short post 1", start, facing, 0.3, under(0.34), short_by=0.5))
        self.call("add_object", object=_post("short post 2", start, facing, 3.3, under(3.34), short_by=0.5))
        checked = self.call("check_construction", name="ramp")
        self.assertEqual(checked["failed"], ["supported"])
        self.assertIn("high board", next(r for r in checked["results"] if r["requirement"] == "supported")["measured"])

    def test_what_it_must_do_is_raised_never_lowered(self):
        self.call("plan_construction", name="jump", kind="ski_jump", reading="a ski jump", start_m=[0.0, 0.0],
                  facing=[1, 0, 0], length_m=6.5, width_m=0.6, height_m=2.4)
        self.assertIn("never lowered", self.refused("plan_construction", name="jump", kind="ski_jump",
                                                    reading="a ski jump", start_m=[0.0, 0.0], facing=[1, 0, 0],
                                                    length_m=6.5, width_m=0.6, height_m=2.1))
        self.assertIn("another name", self.refused("plan_construction", name="jump", kind="downhill_ramp",
                                                   reading="a ramp", start_m=[0.0, 0.0], facing=[1, 0, 0]))
        self.assertIn("at least 6 m long", self.refused("plan_construction", name="small jump", kind="ski_jump",
                                                        reading="a ski jump", start_m=[0.0, 0.0],
                                                        facing=[1, 0, 0], length_m=4.0))
        raised = self.call("plan_construction", name="jump", kind="ski_jump", reading="a higher ski jump",
                           start_m=[0.0, 0.0], facing=[1, 0, 0], length_m=6.5, width_m=0.6, height_m=2.6)
        self.assertIn("its start at least 2.6 m above the ground there", raised["must"])

    def test_a_declared_structure_is_kept_with_the_room_and_takes_nothing_made_later(self):
        self.assertTrue(self.build_the_guides_ski_jump("jump", [0.0, 0.0], [1, 0, 0])["passed"])
        spec = room_world.export_spec(room_world.entry_of(self.world_id))
        kept = spec["constructions"]
        self.assertEqual([(c["name"], c["kind"], len(c["parts"])) for c in kept],
                         [("jump", "ski_jump", len(world_chat.SKI_JUMP_EXAMPLE))])
        again = room_world.open_room(spec)
        self.addCleanup(room_world.close_room, again)
        room_world.call(again, "add_object", {"object": {"name": "later ball", "shape": "sphere",
                                                         "material": "rubber", "size_m": [0.2, 0.2, 0.2],
                                                         "position_m": [20.0, 20.0]}})
        checked = room_world.call(again, "check_construction", {"name": "jump"})
        self.assertTrue(checked["passed"], checked.get("failed"))
        self.assertNotIn("later ball", checked["parts"])

    def test_a_side_over_four_metres_is_said_to_be_cut(self):
        answer = self.call("add_object", object={"name": "long plank", "shape": "box", "material": "oak",
                                                 "size_m": [7.0, 0.04, 0.3], "position_m": [0.0, 20.0]})
        self.assertEqual(answer["size_cut"]["made_m"][0], 4.0)


class TheRoomLaysAStructureOutItself(unittest.TestCase):
    """Increment 2 (docs/building-from-language.md): build_structure lays a
    declared structure on the ground as it is -- boards along its profile,
    posts from the ground under them up to what they hold -- so the chat places
    nothing by hand. Measured before it: asked for a long ski ramp in the
    valley, the chat laid the guide's flat-ground ski jump on a hillside,
    patched it for 30 rounds and ended "Not finished"."""

    def setUp(self):
        if not (LIBRARY and Path(LIBRARY).is_file()):
            self.skipTest("the library is not built")

    def built(self, scene: str, name: str, **declared) -> dict:
        """One structure in a room of its own: three of them fill a room's
        16,000 cells, and the third is refused."""
        world_id = room_world.open_room(world_room.SCENES[scene]())
        self.addCleanup(room_world.close_room, world_id)
        planned = room_world.call(world_id, "plan_construction",
                                  {"name": name, "start_m": [2.0, -2.0], "facing": [1, 0, 0], **declared})
        self.assertNotIn("error", planned, "the declaration was refused")
        answer = room_world.call(world_id, "build_structure", {"name": name})
        self.assertNotIn("error", answer, "the room would not build it")
        return answer

    def test_it_builds_each_kind_on_flat_ground(self):
        for name, declared, parts in (
                ("ski jump", {"kind": "ski_jump", "reading": "a ski jump", "length_m": 6.5, "width_m": 0.6,
                              "height_m": 2.4}, 11),
                ("stairs", {"kind": "staircase", "reading": "stairs up a metre", "height_m": 1.0,
                            "width_m": 0.8}, 12),
                ("bridge", {"kind": "bridge", "reading": "a bridge four metres long", "length_m": 4.0,
                            "width_m": 1.0, "height_m": 0.5}, 8)):
            with self.subTest(name=name):
                answer = self.built("yard", name, **declared)
                self.assertTrue(answer["checked"]["passed"], answer["checked"]["results"])
                self.assertEqual(answer["parts"], parts)

    def test_it_builds_a_ski_jump_on_the_valleys_hillside(self):
        """The ground under that line falls and rises by 0.76 m; every height
        comes from a survey under it."""
        answer = self.built("valley", "ski jump", kind="ski_jump", reading="a ski jump", length_m=6.5,
                            width_m=0.6, height_m=2.4)
        checked = answer["checked"]
        self.assertTrue(checked["passed"], checked["results"])
        self.assertEqual(len(checked["failed"]), 0)

    def test_nothing_is_left_half_built(self):
        """A part that will not go in takes the rest out again, as
        build_recipe does: the room is as it was."""
        world_id = room_world.open_room(world_room.SCENES["yard"]())
        self.addCleanup(room_world.close_room, world_id)
        before = {b["name"] for b in room_world.entry_of(world_id)["scene"]["bodies"]}
        room_world.call(world_id, "plan_construction",
                        {"name": "huge jump", "kind": "ski_jump", "reading": "a very long ski jump",
                         "start_m": [0.0, 0.0], "facing": [1, 0, 0], "length_m": 60.0, "width_m": 3.0,
                         "height_m": 12.0})
        answer = room_world.call(world_id, "build_structure", {"name": "huge jump"})
        self.assertIn("error", answer, "a ski jump far past the room's cells was built")
        self.assertIn("none of it was built", answer["error"])
        self.assertEqual({b["name"] for b in room_world.entry_of(world_id)["scene"]["bodies"]}, before)


class ATurnIsNotDoneWhileItsStructureFails(unittest.TestCase):
    """As the room's chat answers, a structure it declared that turn is
    measured; one that fails goes back to it, at most MAX_REPAIRS times, and
    after that its answer starts "Not finished:". "The engine accepted it" is
    not "it does what was asked"."""

    def ask(self, rounds: list, message: str) -> tuple[dict, list, world_room.Room]:
        replies = iter(rounds)
        sent: list[list[dict]] = []

        def model(api_key, model_name, conversation):
            sent.append(list(conversation))
            return {"status": "completed", "usage": {}, "output": next(replies)}

        room = world_room.Room("yard")
        real, world_chat._call = world_chat._call, model
        try:
            answer = world_chat.ask("key", "a model", room, {"bodies": []}, message, [])
        finally:
            world_chat._call = real
        return answer, sent, room

    @unittest.skipUnless(LIBRARY and Path(LIBRARY).is_file(), "the library is not built")
    def test_a_ski_jump_built_as_one_board_is_not_finished(self):
        answer, sent, room = self.ask([
            [_function_call("c1", "plan_construction", {"name": "ski ramp", "kind": "ski_jump",
                                                         "reading": "a long ski jump", "start_m": [0.0, 0.0],
                                                         "facing": [1, 0, 0]})],
            [_function_call("c2", "add_object", {"object": {
                "name": "ramp", "shape": "box", "material": "oak", "size_m": [1.6, 0.1, 0.6],
                "position_m": [0.78, 0.0], "rotation_deg": [0, 0, -12], "anchored": True}})],
            _message("I built you a long ski ramp."),
            _message("It is a fine ski ramp."),
            _message("Here is your ski ramp.")], "Build a long ski ramp.")
        notes = [m for m in sent[-1] if isinstance(m, dict) and "does not yet do what it was declared to do"
                 in str(m.get("content", ""))]
        self.assertEqual(len(notes), world_chat.MAX_REPAIRS)
        self.assertEqual(len(sent), 3 + world_chat.MAX_REPAIRS)
        self.assertTrue(answer["reply"].startswith("Not finished: ski ramp: "), answer["reply"])
        self.assertIn("takeoff falling 12.0 degrees", answer["reply"])
        self.assertTrue(answer["reply"].endswith("Here is your ski ramp."))
        self.assertEqual([(c["construction"], c["passed"]) for c in answer["checked"]], [("ski ramp", False)])
        # An anchored board is not a thing to take: it is not asked for actions.
        self.assertFalse([m for m in sent[-1] if isinstance(m, dict)
                          and m.get("content") == world_chat.NOTHING_OFFERED])
        # The room keeps what was declared, and its part.
        self.assertEqual([(c["name"], c["kind"], c["parts"]) for c in room.spec["constructions"]],
                         [("ski ramp", "ski_jump", ["ramp"])])

    @unittest.skipUnless(LIBRARY and Path(LIBRARY).is_file(), "the library is not built")
    def test_the_guides_ski_jump_built_in_a_turn_is_finished(self):
        parts = [_function_call(f"p{i}", "add_object", {"object": {
            "name": part["name"], "shape": "box", "material": "oak", "size_m": part["size_m"],
            "position_m": [part["s_m"], part["y_m"], 0.0], "rotation_deg": [0, 0, part["tilt_deg"]],
            "anchored": True}}) for i, part in enumerate(world_chat.SKI_JUMP_EXAMPLE)]
        answer, sent, _ = self.ask([
            [_function_call("c1", "plan_construction", {"name": "ski jump", "reading": "a ski jump",
                                                         "start_m": [0.0, 0.0], "facing": [1, 0, 0],
                                                         **world_chat.SKI_JUMP_DECLARED})],
            parts,
            _message("Built a ski jump.")], "Build a long ski ramp.")
        self.assertEqual(answer["reply"], "Built a ski jump.")
        self.assertEqual([(c["construction"], c["passed"]) for c in answer["checked"]], [("ski jump", True)])
        self.assertEqual(len(sent), 3, "a structure that passes is not sent back")


class TheGuidesSayWhatARampIsFor(unittest.TestCase):
    """The review found both prompts building every ramp as one board, and the
    lab's cell arithmetic out by five."""

    def test_a_ramp_is_read_for_what_it_is_for(self):
        import scene_chat
        lab = " ".join(scene_chat.SYSTEM.split())
        self.assertNotIn("A ramp is one anchored box", lab)
        self.assertIn("read what the ramp is FOR", lab)
        room = " ".join(world_chat.GUIDE.split())
        self.assertNotIn("EVERYTHING YOU MAKE goes on the ground", room)
        for words in ("A THING TO TAKE", "STRUCTURES.", "plan_construction", "ski_jump", "structure_middle_m",
                      "across_the_view", "none more than 4 m long"):
            self.assertIn(words, room)

    def test_the_lab_is_told_what_cells_cost_rightly(self):
        import scene_chat
        lab = " ".join(scene_chat.SYSTEM.split())
        self.assertIn(f"30 x 2 x 12 = {(600 // 20) * (40 // 20) * (240 // 20)} cells", lab)
        self.assertIn(f"2 x (100 x 3 x 20) = {2 * (2000 // 20) * (60 // 20) * (400 // 20)}", lab)
        self.assertIn(f"is {(12000 // 20) * (2000 // 20) * (80 // 20)} cells at 20 mm, and "
                      f"{(12000 // 40) * (2000 // 40) * (80 // 40)} at 40 mm", lab)
        self.assertNotIn("60000", lab)


class ObjectListsSentToTheModel(unittest.TestCase):
    def setUp(self):
        from chat_tool_results import ObjectResultTransport
        self.transport = ObjectResultTransport({"add_object", "move_object", "remove_object"})
        self.objects = [{"name": f"part-{i}", "position_m": [i, 0, 0],
                         "material": "oak", "shape": "box", "size_m": [.2, .3, .4]}
                        for i in range(50)]

    def send(self, tool, answer):
        return json.loads(self.transport.encode(tool, answer))

    def baseline(self):
        source = {"objects": self.objects}
        self.assertEqual(source, self.send("describe_world", source))

    def test_first_objects_reply_is_complete(self):
        source = {"added": "part-49", "objects": self.objects}
        self.assertEqual(source, self.send("add_object", source))
        self.assertEqual(0, self.transport.described()["delta_calls"])

    def test_additions_and_diagnostics_are_kept_without_changing_the_source(self):
        self.baseline()
        added = {"name": "new-part", "position_m": [100, 1, 0]}
        source = {"added": "new-part", "objects": self.objects + [added],
                  "set_down": {"from_m": 0, "to_m": 1}, "joints_lost": ["hinge"],
                  "note": "lifted onto the ground"}
        before = json.dumps(source)
        answer = self.send("add_object", source)
        self.assertEqual([added], answer["objects"])
        self.assertEqual({"mode": "delta", "basis": "previous-objects-result-in-this-turn",
                          "removed_names": [], "total_count": 51, "unchanged_count": 50},
                         answer["object_listing"])
        for key in ("added", "set_down", "joints_lost", "note"):
            self.assertEqual(source[key], answer[key])
        self.assertEqual(before, json.dumps(source), "audit/native response must stay complete")

    def test_all_changed_objects_are_kept_not_only_the_requested_one(self):
        self.baseline()
        # A rebuild moves a different object too: that side effect must not disappear.
        self.objects[2]["position_m"] = [2, 4, 0]
        self.objects[17]["position_m"] = [17, 2, 0]
        answer = self.send("move_object", {"moved": "part-2", "objects": self.objects})
        self.assertEqual(["part-2", "part-17"], [r["name"] for r in answer["objects"]])
        self.assertEqual(48, answer["object_listing"]["unchanged_count"])

    def test_removals_are_explicit_and_deltas_can_follow_deltas(self):
        self.baseline()
        answer = self.send("remove_object", {"removed": "part-4", "objects": self.objects[:4] + self.objects[5:]})
        self.assertEqual(["part-4"], answer["object_listing"]["removed_names"])
        self.assertEqual([], answer["objects"])
        answer = self.send("add_object", {"added": "part-4", "objects": self.objects})
        self.assertEqual([self.objects[4]], answer["objects"])
        self.assertEqual([], answer["object_listing"]["removed_names"])

    def test_reads_and_unknown_tools_are_never_compressed(self):
        self.baseline()
        for name in ("describe_world", "new_tool_not_yet_classified"):
            source = {"objects": self.objects, "report": "full"}
            self.assertEqual(source, self.send(name, source))

    def test_errors_and_missing_mutation_snapshots_reset_the_baseline(self):
        for source in ({"error": "failed", "objects": self.objects}, {"moved": "part-4"}):
            self.baseline()
            self.assertEqual(source, self.send("move_object", source))
            next_answer = {"added": "part-49", "objects": self.objects}
            self.assertEqual(next_answer, self.send("add_object", next_answer))

    def test_ambiguous_or_oversized_identity_is_full_and_resets_baseline(self):
        from chat_tool_results import MAX_TRACKED_OBJECTS
        bad_arrays = [[{"name": "same"}, {"name": "same"}], [{"position_m": [0, 0, 0]}],
                      ["part"], [{"name": f"p{i}"} for i in range(MAX_TRACKED_OBJECTS + 1)]]
        for rows in bad_arrays:
            self.baseline()
            source = {"objects": rows}
            self.assertEqual(source, self.send("add_object", source))
            self.assertEqual({"objects": self.objects}, self.send("add_object", {"objects": self.objects}))

    def test_small_replies_do_not_grow(self):
        source = {"objects": [{"name": "a"}]}
        self.assertEqual(source, self.send("add_object", source))
        self.assertEqual(source, self.send("add_object", source))
        self.assertEqual(0, self.transport.described()["saved_json_bytes"])

    def test_json_type_changes_are_not_hidden_by_python_equality(self):
        self.objects[0]["state"] = 1
        self.baseline()
        self.objects[0]["state"] = True
        answer = self.send("move_object", {"objects": self.objects})
        self.assertEqual([self.objects[0]], answer["objects"])

    def test_a_new_turn_has_no_previous_turns_baseline(self):
        from chat_tool_results import ObjectResultTransport
        self.baseline()
        next_turn = ObjectResultTransport({"add_object"})
        source = {"objects": self.objects}
        self.assertEqual(source, json.loads(next_turn.encode("add_object", source)))

    def test_large_world_byte_accounting_is_measured_and_lossless(self):
        original = sent = 0
        reconstructed = {}
        current = self.objects.copy()
        for i in range(30):
            current.append({"name": f"new-{i}", "position_m": [i, 2, 3]})
            source = {"objects": current, "added": f"new-{i}"}
            encoded = self.transport.encode("add_object", source)
            original += len(json.dumps(source, allow_nan=False).encode("utf-8"))
            sent += len(encoded.encode("utf-8"))
            answer = json.loads(encoded)
            if "object_listing" not in answer:
                reconstructed = {r["name"]: r for r in answer["objects"]}
            else:
                for name in answer["object_listing"]["removed_names"]:
                    reconstructed.pop(name)
                reconstructed.update({r["name"]: r for r in answer["objects"]})
            self.assertEqual({r["name"]: r for r in current}, reconstructed)
        stats = self.transport.described()
        self.assertEqual((original, sent, original - sent),
                         (stats["original_json_bytes"], stats["sent_json_bytes"], stats["saved_json_bytes"]))
        self.assertLess(sent, original * .15)
        self.assertEqual(29, stats["delta_calls"])

    @unittest.skipUnless(LIBRARY and Path(LIBRARY).is_file(), "the library is not built")
    def test_real_room_calls_compact_model_outputs_but_not_the_audit_log(self):
        sent = []
        trace = []
        def model(api_key, model_name, conversation):
            sent.append(list(conversation))
            if len(sent) <= 2:
                n = len(sent)
                return {"status": "completed", "usage": {}, "output": [
                    _function_call(f"add-{n}", "add_object", {"object": {
                        "name": f"transport-crate-{n}", "shape": "box", "material": "oak",
                        "size_m": [.12, .12, .12], "position_m": [8.0 + n, 0.0]}})]}
            return {"status": "completed", "usage": {}, "output": _message("The crates are there.")}
        real, world_chat._call = world_chat._call, model
        try:
            result = world_chat.ask("test", "scripted", world_room.Room("yard"), {"bodies": []},
                                    "Add two crates.", [], trace=trace)
        finally:
            world_chat._call = real
        calls = [json.loads(m["output"]) for m in sent[-1] if m.get("type") == "function_call_output"]
        self.assertNotIn("object_listing", calls[0])
        self.assertEqual("delta", calls[1]["object_listing"]["mode"])
        self.assertTrue(any(r["name"] == "transport-crate-2" for r in calls[1]["objects"]))
        audit = [call["answer"] for round_ in trace for call in round_.get("calls", [])]
        self.assertNotIn("object_listing", audit[1])
        self.assertGreater(len(audit[1]["objects"]), len(calls[1]["objects"]))
        self.assertGreater(result["tool_transport"]["saved_json_bytes"], 0)
        self.assertIn("TOOL OBJECT LISTS", json.loads(sent[0][0]["content"])["tool_object_lists"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
