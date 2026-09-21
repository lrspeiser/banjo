"""A thing's actions: what the room's chat works out a person does with
something it made -- a stool pulled out from its table, a beam stood upright --
each a label and a short program, kept with the thing, shown when the person
looks at it, and run when its number key is pressed.

    python tests/actions_tests.py -v

The owner, 2026-09-13: "when you looked at something it had an area that showed
you all your options and the llm would when making an item provide enough
comprehensive options for the item", and then: "it isn't just placement, the
llm should look at the item and think what the user would need to do. a bow and
arrow would have different actions than a chair, it needs to be asked what
actions and given the ability to program the execution of it".

offer_actions (the MCP) checks a program when it is offered; the room's spec
carries it through every edit and a restart; POST /api/world/action runs it on
the room as it is -- the hand's steps as the running room's own operations, a
stand step as turn_object. The MCP and the stand step need the built library.
The running room is a stand-in that records what the hand was asked to do and
answers the way the engine's step replies do.
"""
from __future__ import annotations

import http.client
from http.server import ThreadingHTTPServer
import json
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "playground"))

import fracture_lab  # noqa: E402
import room_world  # noqa: E402  (puts mcp/ on the path)
import room_store  # noqa: E402
import world_chat  # noqa: E402
import world_room  # noqa: E402
from playground_tests import PlaygroundTestCase, playground_server  # noqa: E402
from room_store_tests import StandInLive  # noqa: E402

LIBRARY = os.environ.get("BANJO_LIBRARY")
NEEDS_LIBRARY = unittest.skipUnless(LIBRARY and Path(LIBRARY).is_file(),
                                    "the library is not built")

STOOL = {"name": "stool", "shape": "box", "material": "oak",
         "size_mm": [350, 450, 350], "center_mm": [0, 225, 1000]}
TABLE = {"name": "table", "shape": "box", "material": "oak",
         "size_mm": [1000, 750, 600], "center_mm": [0, 375, 0], "anchored": True}
BEAM = {"name": "oak beam", "shape": "box", "material": "oak",
        "size_mm": [2000, 100, 200], "center_mm": [2500, 50, 0]}
BLOCK = {"name": "stone block", "shape": "box", "material": "concrete",
         "size_mm": [450, 450, 450], "center_mm": [-2500, 225, 0]}
BALL = {"name": "rubber ball", "shape": "sphere", "material": "rubber",
        "size_mm": [100, 100, 100], "center_mm": [1500, 50, 1500]}

PULL_OUT = {"label": "Pull it out", "steps": [
    {"do": "take_hold"},
    {"do": "carry_to", "to": {"beside": "table", "side": "near", "gap_m": 0.4}},
    {"do": "put_down"}]}
PUSH_IN = {"label": "Push it in", "steps": [
    {"do": "take_hold"},
    {"do": "carry_to", "to": {"beside": "table", "side": "near", "gap_m": 0.05}},
    {"do": "put_down"}]}
BRING = {"label": "Bring it to me", "steps": [
    {"do": "take_hold"},
    {"do": "carry_to", "to": {"in_front_m": 0.8, "height_m": 1.0}},
    {"do": "put_down"}]}
STAND_UP = {"label": "Stand the beam on end", "steps": [{"do": "stand", "stand": "upright"}]}
# Facing -z, three metres from the table: the table is in front of them.
PERSON = {"standing_m": [0.0, 0.0, 3.0], "facing": [0.0, 0.0, -1.0]}


def room_spec(*bodies, actions=None):
    """The empty yard, with these in it."""
    spec = dict(world_room.Room("yard").spec)
    spec["bodies"] = list(spec["bodies"]) + [dict(b) for b in bodies]
    if actions is not None:
        spec["actions"] = actions
    return spec


class TheShapeOfAnAction(unittest.TestCase):
    """What a saved room may say about actions (fracture_lab): no engine needed."""

    def test_actions_are_kept_as_written(self):
        bodies = [{"name": "stool"}, {"name": "table"}]
        kept = fracture_lab.normalise_actions([dict(PULL_OUT, body="stool")], bodies)
        self.assertEqual(kept[0]["label"], "Pull it out")
        self.assertEqual([s["do"] for s in kept[0]["steps"]], ["take_hold", "carry_to", "put_down"])

    def test_what_is_not_an_action_is_refused(self):
        bodies = [{"name": "stool"}, {"name": "table"}]
        for bad, why in [
                ({"body": "nothing", "label": "Up", "steps": [{"do": "let_go"}]}, "nothing called"),
                ({"body": "stool", "label": "", "steps": [{"do": "let_go"}]}, "label"),
                ({"body": "stool", "label": "Up", "steps": []}, "1 to 12 steps"),
                ({"body": "stool", "label": "Up", "steps": [{"do": "teleport"}]}, "do must be"),
                ({"body": "stool", "label": "Up", "steps": [{"do": "wait", "pose": 1}]}, "cannot say"),
                ({"body": "stool", "label": "Up", "steps": [{"do": "take_hold", "part": "lamp"}]},
                 "nothing called"),
                ({"body": "stool", "label": "Up",
                  "steps": [{"do": "carry_to", "to": {"on": "shelf"}}]}, "nothing called")]:
            with self.assertRaisesRegex(ValueError, why):
                fracture_lab.normalise_actions([bad], bodies)
        with self.assertRaisesRegex(ValueError, "more than 9"):
            fracture_lab.normalise_actions(
                [{"body": "stool", "label": f"Wait {i}", "steps": [{"do": "wait"}]}
                 for i in range(10)], bodies)


class TheChatIsAskedWhatAThingIsFor(unittest.TestCase):
    def test_the_guide_asks_what_a_person_would_do_with_what_is_made(self):
        self.assertIn("ACTIONS", world_chat.GUIDE)
        self.assertIn("offer_actions", world_chat.GUIDE)
        self.assertIn("what a person would DO", world_chat.GUIDE)


@NEEDS_LIBRARY
class OfferActions(unittest.TestCase):
    """The MCP checks a thing's actions the way the room will run them, keeps
    them, and the room's spec carries them."""

    def setUp(self):
        self.world = room_world.open_room(room_spec(STOOL, TABLE, BEAM, BLOCK, BALL))
        self.addCleanup(room_world.close_room, self.world)

    def offer(self, name, actions):
        return room_world.call(self.world, "offer_actions", {"name": name, "actions": actions})

    def test_a_stool_and_a_beam_are_given_their_actions_and_the_room_keeps_them(self):
        answer = self.offer("stool", [PULL_OUT, PUSH_IN, BRING])
        self.assertNotIn("error", answer, answer)
        self.assertEqual([a["key"] for a in answer["actions"]], [1, 2, 3])
        self.assertNotIn("error", self.offer("oak beam", [STAND_UP]))
        spec = room_world.export_spec(room_world.entry_of(self.world))
        self.assertEqual([(a["body"], a["label"]) for a in spec["actions"]],
                         [("stool", "Pull it out"), ("stool", "Push it in"),
                          ("stool", "Bring it to me"), ("oak beam", "Stand the beam on end")])
        # Opened again from that spec -- after a restart, or the next edit --
        # they are all still there.
        again = room_world.open_room(spec)
        try:
            kept = room_world.entry_of(again)["actions"]
            self.assertEqual(sorted(kept), ["oak beam", "stool"])
            self.assertEqual(len(kept["stool"]), 3)
        finally:
            room_world.close_room(again)

    def test_what_a_hand_could_not_do_is_refused_and_nothing_changes(self):
        take = {"label": "Take it", "steps": [{"do": "take_hold"}, {"do": "put_down"}]}
        self.assertIn("fixed in place", self.offer("table", [take])["error"])
        self.assertIn("more than", self.offer("stone block", [take])["error"])
        self.assertIn("still in the hand", self.offer(
            "stool", [{"label": "Hold it", "steps": [{"do": "take_hold"}]}])["error"])
        self.assertIn("take_hold first", self.offer(
            "stool", [{"label": "Carry it", "steps": [
                {"do": "carry_to", "to": {"in_front_m": 1.0}}]}])["error"])
        self.assertIn("do is one of", self.offer(
            "stool", [{"label": "Fly", "steps": [{"do": "fly"}]}])["error"])
        self.assertIn("nothing called", self.offer(
            "stool", [{"label": "Shelve it", "steps": [
                {"do": "take_hold"}, {"do": "carry_to", "to": {"on": "shelf"}},
                {"do": "put_down"}]}])["error"])
        self.assertIn("ball", self.offer("rubber ball", [STAND_UP])["error"])
        self.assertFalse(room_world.entry_of(self.world).get("actions"))

    def test_a_model_that_fills_every_field_is_read_by_each_steps_kind(self):
        """What the room's chat sent for a stool, six times over: every step every
        field, every place every kind. It is read by what each step says it is."""
        every = {"kind": "in_front", "in_front_m": 0.8, "height_m": 1.0, "on": "table",
                 "beside": "table", "side": "near", "gap_m": 0.1, "from": "table",
                 "offset_m": [0, 0, 0]}
        filled = {"label": "Bring it to me", "steps": [
            {"do": "take_hold", "part": "stool", "stand": "upright", "along": "facing",
             "where": "here", "to": every},
            {"do": "carry_to", "part": "stool", "stand": "upright", "to": every},
            {"do": "put_down", "part": "stool", "to": dict(every, kind="on")}]}
        answer = self.offer("stool", [filled])
        self.assertNotIn("error", answer, answer)
        steps = answer["actions"][0]["steps"]
        self.assertEqual(steps[0], {"do": "take_hold", "part": "stool"})
        self.assertEqual(steps[1]["to"], {"kind": "in_front", "in_front_m": 0.8, "height_m": 1.0})
        self.assertIn("a take_hold step has none", answer["not_read"])
        # And a stand upright is not refused for a way along it has none of.
        stood = self.offer("oak beam", [{"label": "Stand it up", "steps": [
            {"do": "stand", "stand": "upright", "along": "facing", "where": "here"}]}])
        self.assertNotIn("error", stood, stood)
        self.assertNotIn("along", stood["actions"][0]["steps"][0])

    def test_a_place_given_two_kinds_and_no_kind_is_refused_with_what_to_say(self):
        answer = self.offer("stool", [{"label": "Bring it", "steps": [
            {"do": "take_hold"}, {"do": "carry_to", "to": {"in_front_m": 0.8, "on": "table"}},
            {"do": "put_down"}]}])
        self.assertIn("say which kind of place", answer["error"])

    def test_a_label_the_page_already_offers_is_refused(self):
        """The room's chat programmed "Release the latch" onto a latch bar three
        times; the page offers it on anything a latch holds shut."""
        import server
        for label in ("Release the latch", "Turn it all the way", "stand it upright"):
            said = self.offer("oak beam", [{"label": label,
                                            "steps": [{"do": "stand", "stand": "upright"}]}])
            self.assertIn("page's own menu", said.get("error", ""), label)
        page = ({label.lower() for label in server.JOINT_LABELS.values()}
                | {action["label"].lower() for action in server.BUILTIN_ACTIONS.values()}
                | {"release the latch"})
        self.assertEqual(page, set(room_world.banjo_mcp.PAGE_OFFERS))

    def test_an_action_naming_a_thing_that_is_gone_goes_with_it(self):
        self.offer("stool", [PULL_OUT, BRING])
        self.offer("oak beam", [STAND_UP])
        room_world.call(self.world, "remove_object", {"name": "table"})
        spec = room_world.export_spec(room_world.entry_of(self.world))
        self.assertEqual([(a["body"], a["label"]) for a in spec["actions"]],
                         [("stool", "Bring it to me"), ("oak beam", "Stand the beam on end")])



    def test_primary_selection_survives_export_and_reopening(self):
        answer = self.offer("stool", [
            {"label": "Look", "steps": [{"do": "inspect"}]},
            {"label": "Move forward", "primary": True, "steps": [{"do": "push_forward"}]}])
        self.assertNotIn("error", answer, answer)
        spec = room_world.export_spec(room_world.entry_of(self.world))
        again = room_world.open_room(spec)
        try:
            actions = room_world.entry_of(again)["actions"]["stool"]
            self.assertTrue(actions[1]["primary"])
            self.assertFalse(actions[0].get("primary", False))
        finally:
            room_world.close_room(again)
        primary = room_world.call(self.world, "use_action", {"name": "stool", "primary": True})
        self.assertIn("person\'s hand", primary["error"])
        inspect = room_world.call(self.world, "use_action", {"name": "stool", "action": "Look"})
        self.assertIn("mass_kg", inspect["done"][0])
        before = json.dumps(room_world.entry_of(self.world)["actions"])
        answer = self.offer("stool", [
            {"label": label, "primary": True, "steps": [{"do": "inspect"}]} for label in ("A", "B")])
        self.assertIn("exactly one", answer["error"])
        self.assertEqual(json.dumps(room_world.entry_of(self.world)["actions"]), before)

class HandInLive(StandInLive):
    """The running room, as far as a hand goes: it keeps what the hand is asked
    to do, moves what the hand holds to where a stroke ends -- unless it is told
    the stroke is blocked -- and says so the way the engine's step replies do."""

    def __init__(self):
        super().__init__()
        self.acts = []
        self.stroke_ends = "reached"

    def open(self, app, body):
        opened = super().open(app, body)
        self.session.state = {"hand": {}, "bodies": [
            {"name": b["name"], "shape": b["shape"],
             "position_m": [v / 1000.0 for v in b["center_mm"]],
             "dimensions_m": [v / 1000.0 for v in b["size_mm"]],
             "orientation_wxyz": [1.0, 0.0, 0.0, 0.0]} for b in body["spec"]["bodies"]]}
        return opened

    def act(self, body):
        # As the running room does: an operation is for the world it names.
        # The action's first run in the page sent none, and every step of it
        # was refused as being for a world that was no longer open.
        if body.get("session") != self.session.id:
            raise ValueError("that live world is no longer open; start a new one")
        self.acts.append(json.loads(json.dumps(body)))
        state = self.session.state
        hand = state.setdefault("hand", {})
        if body["op"] == "wield":
            hand.update(holding=True, name=body["name"], grip_m=list(body["grip"]))
        elif body["op"] == "stroke":
            end = list(body["path"][-1])
            if self.stroke_ends == "reached" and hand.get("holding"):
                held = next(b for b in state["bodies"] if b["name"] == hand["name"])
                held["position_m"] = end
            hand.update(stroking=False, stroke_ended=self.stroke_ends, grip_m=end)
        elif body["op"] == "release":
            hand.update(holding=False)
        return {"ok": True}


@NEEDS_LIBRARY
class OfferingATurnOrASlide(unittest.TestCase):
    """The chat can program a winch: a turn step on what turns on a pin -- its
    own, or through what it is fixed to -- and a slide on what slides. A last
    turn keeps hold, so the gate it raised stays up."""

    def setUp(self):
        import world_room
        self.world_id = room_world.open_room(world_room.Room("tests-gates").spec)
        self.addCleanup(room_world.close_room, self.world_id)

    def offer(self, name, actions):
        return room_world.call(self.world_id, "offer_actions", {"name": name, "actions": actions})

    def test_a_winch_is_raised_and_lowered_by_turning_its_handle(self):
        said = self.offer("castle-gate-winch: winch handle", [
            {"label": "Raise the gate", "steps": [{"do": "turn", "stop": "all_the_way"}]},
            {"label": "Lower the gate", "steps": [{"do": "turn", "stop": "back_to_start"},
                                                  {"do": "let_go"}]},
            {"label": "Give it a quarter turn", "steps": [{"do": "turn", "degrees": 90}]}])
        self.assertNotIn("error", said)
        first = [action["steps"][0] for action in said["actions"]]
        self.assertEqual(first[0], {"do": "turn", "part": "castle-gate-winch: winch handle",
                                    "stop": "all_the_way"})
        self.assertEqual(first[2]["degrees"], 90.0)

    def test_a_turn_needs_a_pin_and_a_slide_a_groove(self):
        refused = self.offer("castle-gate-winch: castle gate", [
            {"label": "Spin it", "steps": [{"do": "turn", "degrees": 90}]}])
        self.assertIn("does not turn on a pin", refused["error"])
        slid = self.offer("castle-gate-winch: castle gate", [
            {"label": "Lift the gate", "steps": [{"do": "slide", "stop": "all_the_way"}]}])
        self.assertNotIn("error", slid)
        held = self.offer("castle-gate-winch: winch handle", [
            {"label": "Hold it", "steps": [{"do": "take_hold"}]}])
        self.assertIn("still in the hand", held["error"])


class WhatElseATurnMoved(unittest.TestCase):
    """A turn or a slide says what else it moved: what is joined to the thing
    worked, and nothing else. Measured on the world: a bell still swinging on
    the far terrace from being rung was said to have moved 0.28 m with a turn
    of the bow."""

    JOINTS = [
        {"kind": "hinge", "a": "winch post", "b": "winch wheel", "attached": True},
        {"kind": "fixing", "a": "winch wheel", "b": "winch handle", "attached": True},
        {"kind": "pulley", "a": "winch wheel", "b": "portcullis", "attached": True},
        {"kind": "slider", "a": "gateway post", "b": "portcullis", "attached": True},
        {"kind": "link", "a": "gateway post", "b": "lantern", "attached": True},
        {"kind": "link", "a": "bell beam", "b": "iron bell", "attached": True},
    ]
    THINGS = {"winch post": {"anchored": True}, "gateway post": {"anchored": True},
              "bell beam": {"anchored": True}}
    BEFORE = {"winch wheel": [0.0, 1.0, 0.0], "winch handle": [0.0, 1.24, 0.16],
              "portcullis": [2.0, 0.5, 0.0], "lantern": [2.0, 2.0, 0.0], "iron bell": [9.0, 1.0, 0.0]}

    def test_what_a_winch_can_move_goes_through_its_rope_and_stops_at_posts(self):
        joined = playground_server._joined({"winch wheel", "winch handle"}, self.JOINTS, self.THINGS)
        self.assertEqual(joined, {"winch wheel", "winch handle", "portcullis"})

    def test_the_gate_a_winch_raises_is_said_and_a_swinging_bell_is_not(self):
        group = {"winch wheel", "winch handle"}
        joined = playground_server._joined(group, self.JOINTS, self.THINGS)
        after = dict(self.BEFORE, **{"winch handle": [0.0, 0.76, 0.16], "portcullis": [2.0, 0.6, 0.0],
                                     "iron bell": [9.28, 1.0, 0.0]})
        self.assertEqual(playground_server._what_else_moved(self.BEFORE, after, group, joined),
                         "portcullis rose 0.10 m")
        after = dict(self.BEFORE, **{"iron bell": [9.28, 1.0, 0.0]})
        self.assertIsNone(playground_server._what_else_moved(self.BEFORE, after, group, joined))


class RunningAnAction(PlaygroundTestCase):
    """POST /api/world/action runs a thing's program on the room as it is."""

    def start(self, actions):
        app = self.make_app(mock.Mock())
        app.store = room_store.RoomStore(self.base / "rooms")
        app.live = HandInLive()
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), playground_server.Handler)
        httpd.app = app
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        def stop():
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=3)
        self.addCleanup(stop)
        app.port = httpd.server_port
        status, _ = self.post(app, "/api/world/open", {"scene": "yard"})
        self.assertEqual(status, 200)
        app.room.spec = room_spec(STOOL, TABLE, BEAM, actions=actions)
        app.live.open(app, {"spec": app.room.spec})
        app.live.acts.clear()
        return app

    def post(self, app, path, body):
        connection = http.client.HTTPConnection("127.0.0.1", app.port, timeout=120)
        try:
            connection.request("POST", path, body=json.dumps(body),
                               headers={"Content-Type": "application/json",
                                        "X-Banjo-Token": app.csrf_token})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def press(self, app, name, index):
        return self.post(app, "/api/world/action",
                         {"session": app.live.session.id, "object": name, "action": index,
                          "person": PERSON})


    def test_primary_selects_designated_program_not_menu_order(self):
        app = self.start([
            {"body": "stool", "label": "Read", "steps": [{"do": "inspect"}]},
            {"body": "stool", "label": "Roll forward", "primary": True,
             "steps": [{"do": "push_forward", "distance_m": .4, "speed_m_s": .4}]}])
        status, answer = self.post(app, "/api/world/action", {
            "session": app.live.session.id, "object": "stool", "primary": True, "person": PERSON})
        self.assertEqual(status, 200, answer)
        self.assertEqual(answer["action"], "Roll forward")
        self.assertEqual([a["op"] for a in app.live.acts], ["wield", "stroke", "release"])
        self.assertAlmostEqual(app.live.acts[1]["path"][-1][2], .6)

    def test_primary_push_blocked_or_out_of_reach_does_not_claim_success(self):
        app = self.start([{"body": "stool", "label": "Roll", "primary": True,
                           "steps": [{"do": "push_forward"}]}])
        app.live.stroke_ends = "blocked"
        _, answer = self.post(app, "/api/world/action", {
            "session": app.live.session.id, "object": "stool", "primary": True, "person": PERSON})
        self.assertIn("did not move", answer["refused"])
        self.assertNotIn("did", answer)
        self.assertFalse(app.live.session.state["hand"]["holding"])
        app.live.acts.clear()
        _, answer = self.post(app, "/api/world/action", {
            "session": app.live.session.id, "object": "stool", "primary": True,
            "person": dict(PERSON, standing_m=[0, 0, 30])})
        self.assertIn("within 3 m", answer["refused"])
        self.assertEqual(app.live.acts, [])

    def test_strike_uses_real_grip_keeps_tool_and_can_repeat(self):
        app = self.start([{"body": "stool", "label": "Strike", "primary": True,
                           "steps": [{"do": "strike", "distance_m": .3, "speed_m_s": 3}]}])
        app.live.session.state["hand"] = {"holding": True, "name": "stool", "grip_m": [0, 1, 1]}
        for _ in range(2):
            status, answer = self.post(app, "/api/world/action", {
                "session": app.live.session.id, "object": "stool", "primary": True,
                "person": dict(PERSON, look_direction=[0, -.6, -.8])})
            self.assertEqual(status, 200, answer)
            self.assertEqual(answer["holding"], "stool")
            self.assertNotIn("refused", answer)
        self.assertEqual([a["op"] for a in app.live.acts], ["stroke"] * 4)
        self.assertEqual(app.live.acts[0]["path"][0], [0, 1, 1])
        self.assertAlmostEqual(app.live.acts[0]["path"][-1][1], .82)
        self.assertEqual(app.live.acts[-1]["path"][-1], [0, 1, 1])

    def test_unheld_strike_and_concurrent_use_are_refused(self):
        app = self.start([{"body": "stool", "label": "Strike", "primary": True,
                           "steps": [{"do": "strike"}]}])
        request = {"session": app.live.session.id, "object": "stool", "primary": True, "person": PERSON}
        _, answer = self.post(app, "/api/world/action", request)
        self.assertIn("pick up", answer["refused"])
        app.action_lock.acquire()
        try:
            status, answer = self.post(app, "/api/world/action", request)
            self.assertEqual(status, 400)
            self.assertIn("already running", answer["error"])
        finally:
            app.action_lock.release()
        self.assertEqual(app.live.acts, [])


    def test_timed_out_strike_cancels_without_releasing_tool(self):
        app = self.start([{"body": "stool", "label": "Strike", "primary": True,
                           "steps": [{"do": "strike"}]}])
        app.live.session.state["hand"] = {"holding": True, "name": "stool", "grip_m": [0, 1, 1]}
        with mock.patch.object(playground_server, "_stroke_to", return_value="ran out of time"):
            _, answer = self.post(app, "/api/world/action", {
                "session": app.live.session.id, "object": "stool", "primary": True, "person": PERSON})
        self.assertIn("ran out of time", answer["refused"])
        self.assertEqual(answer["holding"], "stool")
        self.assertEqual([a["op"] for a in app.live.acts], ["cancel_stroke"])

    def test_legacy_object_inspection_is_read_only(self):
        app = self.start([])
        _, answer = self.post(app, "/api/world/action", {
            "session": app.live.session.id, "object": "stool", "primary": True})
        self.assertEqual(answer["action"], "Inspect")
        self.assertIn("position_m", answer["done"][0])
        self.assertEqual(app.live.acts, [])

    def test_bring_it_to_me_is_a_grip_a_stroke_and_setting_it_down(self):
        app = self.start([dict(BRING, body="stool")])
        status, answer = self.press(app, "stool", 0)
        self.assertEqual(status, 200, answer)
        self.assertEqual(answer["did"], ["Bring it to me"], answer)
        self.assertEqual([a["op"] for a in app.live.acts], ["wield", "stroke", "stroke", "release"])
        self.assertEqual(app.live.acts[0]["grip"], [0.0, 0.225, 1.0], "gripped at its middle")
        carried = app.live.acts[1]["path"][-1]
        # 0.8 m in front of them, its bottom a metre (and 2 cm) off the ground:
        # its middle half the stool's 0.45 m above that. height_m is where its
        # bottom is -- read as its middle, "on the ground" (height_m 0) carried
        # a crate half into the ground and the stroke was blocked.
        self.assertEqual([round(v, 3) for v in carried], [0.0, 1.245, 2.2])
        self.assertLess(app.live.acts[2]["path"][-1][1], carried[1] - 1.5,
                        "put down: lowered until what is under it stops it")

    def test_pull_it_out_goes_beside_the_table_on_the_persons_side(self):
        app = self.start([dict(PULL_OUT, body="stool")])
        status, answer = self.press(app, "stool", 0)
        self.assertEqual(status, 200, answer)
        carried = app.live.acts[1]["path"][-1]
        # The table's near face (z 0.3), the gap (0.4) and half the stool (0.175).
        self.assertAlmostEqual(carried[0], 0.0, places=3)
        self.assertAlmostEqual(carried[2], 0.875, places=3)

    def test_a_blocked_stroke_stops_the_action_and_opens_the_hand(self):
        app = self.start([dict(BRING, body="stool")])
        app.live.stroke_ends = "blocked"
        status, answer = self.press(app, "stool", 0)
        self.assertEqual(status, 200, answer)
        self.assertIn("did not get there", answer["refused"])
        self.assertEqual(answer["done"], ["took hold of stool"])
        self.assertEqual([a["op"] for a in app.live.acts], ["wield", "stroke", "release"])

    PUSH = {"label": "Push it away", "steps": [
        {"do": "push", "part": "stool", "distance_m": 0.3,
         "toward": {"kind": "from", "from": "table", "offset_m": [0.0, 0.0, -2.0]}}]}

    def test_a_push_says_how_far_it_went(self):
        app = self.start([dict(self.PUSH, body="stool")])
        status, answer = self.press(app, "stool", 0)
        self.assertEqual(status, 200, answer)
        self.assertEqual(answer["did"], ["Push it away"], answer)
        self.assertEqual(answer["done"], ["pushed stool 0.30 m"])
        self.assertEqual([a["op"] for a in app.live.acts], ["wield", "stroke", "release"])

    def test_a_push_the_hand_cannot_make_is_said_and_not_claimed(self):
        # A 151 kg oak table the chat built as one block did not move under the
        # hand's 800 N, and the first action said "pushed" all the same.
        app = self.start([dict(self.PUSH, body="stool")])
        app.live.stroke_ends = "gave up"
        status, answer = self.press(app, "stool", 0)
        self.assertEqual(status, 200, answer)
        self.assertIn("could not push it", answer["refused"])
        self.assertNotIn("did", answer)

    def test_a_built_in_puts_a_loose_thing_on_the_ground_in_front(self):
        # What anything loose has without the chat thinking of it: "place on
        # ground", the owner's words.
        app = self.start([])
        status, answer = self.post(app, "/api/world/action",
                                   {"session": app.live.session.id, "object": "stool",
                                    "builtin": "put_on_ground", "person": PERSON})
        self.assertEqual(status, 200, answer)
        self.assertEqual(answer["did"], ["Put it on the ground in front of me"], answer)
        self.assertEqual([a["op"] for a in app.live.acts], ["wield", "stroke", "stroke", "release"])
        carried = app.live.acts[1]["path"][-1]
        self.assertEqual([round(carried[0], 3), round(carried[2], 3)], [0.0, 2.0],
                         "a metre in front of them")
        # Clear of the ground: 5 cm above where it rests now. Worked out from
        # its box instead, a joined stool -- whose centre of mass is not its
        # box's middle -- went with its legs in the ground and was blocked.
        rests = app.live.acts[0]["grip"][1]          # where it stood when taken hold of
        self.assertGreaterEqual(carried[1], rests + 0.05 - 1e-9)

    def test_a_built_in_a_hand_cannot_do_is_refused_before_the_hand_moves(self):
        app = self.start([])
        stool = next(b for b in app.live.session.state["bodies"] if b["name"] == "stool")
        stool["mass_kg"] = 140.0
        status, answer = self.post(app, "/api/world/action",
                                   {"session": app.live.session.id, "object": "stool",
                                    "builtin": "put_on_ground", "person": PERSON})
        self.assertEqual(status, 200, answer)
        self.assertIn("more than", answer["refused"])
        self.assertEqual(app.live.acts, [])

    def test_a_built_in_that_is_not_there_is_an_error(self):
        app = self.start([])
        status, answer = self.post(app, "/api/world/action",
                                   {"session": app.live.session.id, "object": "stool",
                                    "builtin": "juggle", "person": PERSON})
        self.assertEqual(status, 400)
        self.assertIn("no built-in action", answer["error"])

    def test_with_something_in_hand_the_action_waits(self):
        app = self.start([dict(BRING, body="stool")])
        app.live.session.state["hand"] = {"holding": True}
        status, answer = self.press(app, "stool", 0)
        self.assertEqual(status, 400)
        self.assertIn("put down what you are holding first", answer["error"])
        self.assertEqual(app.live.acts, [])

    def test_only_putting_down_may_act_on_the_thing_in_the_hand(self):
        # The owner, of the Explorer: "hitting e doesn't put it down". Putting a
        # cart down ran the cart's own use, which wanted the free hand the cart
        # was in -- so the only way to put down what you held was to put down
        # what you held. put_it_down may run put_on_ground on the thing already
        # in the hand (own_hold). Nothing pressed over HTTP may: letting every
        # action through for "the same thing" put a winch handle on the ground
        # mid-turn (world_room_tests, the castle gate).
        import server
        app = self.start([dict(BRING, body="stool")])
        app.live.session.state["hand"] = {"holding": True, "name": "stool", "grip_m": [0, 1, 1]}
        status, answer = self.press(app, "stool", 0)
        self.assertEqual(status, 400)
        self.assertIn("put down what you are holding first", answer["error"])
        status, answer = self.post(app, "/api/world/action",
                                   {"session": app.live.session.id, "object": "stool",
                                    "builtin": "put_on_ground", "person": PERSON, "own_hold": True})
        self.assertEqual(status, 400, "a request cannot claim own_hold")
        self.assertIn("put down what you are holding first", answer["error"])
        self.assertEqual(app.live.acts, [])
        said = server.run_action(app, {"session": app.live.session.id, "object": "stool",
                                       "builtin": "put_on_ground", "person": PERSON}, own_hold=True)
        self.assertNotIn("put down what you are holding first", str(said))
        self.assertTrue(app.live.acts, "the hand never moved")

    def test_a_page_that_no_longer_has_the_room_is_refused_and_nothing_moves(self):
        # The playground runs one room at a time. Measured on 8781: a checker's
        # page that had lost its room to the owner's went on pressing "Put it
        # on the ground in front of me", and each press carried the oak plank
        # about in the owner's room, from where the checker stood.
        app = self.start([dict(BRING, body="stool")])
        stale = app.live.session.id
        app.live.open(app, {"spec": app.room.spec})      # opened again, by another page
        app.live.acts.clear()
        for body in ({"session": stale, "object": "stool", "action": 0, "person": PERSON},
                     {"session": stale, "object": "stool", "builtin": "put_on_ground",
                      "person": PERSON},
                     {"object": "stool", "action": 0, "person": PERSON}):
            status, answer = self.post(app, "/api/world/action", body)
            self.assertEqual(status, 400, answer)
            self.assertIn("no longer has the room", answer["error"])
        self.assertEqual(app.live.acts, [], "the hand never moved")

    def test_an_action_that_is_not_there_is_an_error(self):
        app = self.start([dict(BRING, body="stool")])
        status, answer = self.press(app, "stool", 7)
        self.assertEqual(status, 400)
        self.assertIn("no action 8", answer["error"])

    @NEEDS_LIBRARY
    def test_a_stand_step_is_turn_object_and_the_room_opened_again(self):
        app = self.start([dict(STAND_UP, body="oak beam")])
        status, answer = self.press(app, "oak beam", 0)
        self.assertEqual(status, 200, answer)
        self.assertTrue(answer.get("reopened"), answer)
        beam = next(b for b in app.room.spec["bodies"] if b["name"] == "oak beam")
        self.assertEqual(max(beam["size_mm"]), beam["size_mm"][1], "its long side is vertical now")
        opened = app.live.opened[-1]
        self.assertEqual(len(opened["actions"]), 1, "the room opened again keeps its actions")



class CoreUseContract(unittest.TestCase):
    def test_bad_core_programs_and_ambiguous_primaries_fail(self):
        import core_use
        for bad in (True, float("inf"), float("nan"), -1, "3", 100):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                core_use.checked_program({"label": "Strike", "steps": [{"do": "strike", "speed_m_s": bad}]})
        for steps in ([{"do": "python", "code": "x"}], [{"do": "strike", "force_n": 1e9}],
                      [{"do": "strike"}, {"do": "push_forward"}]):
            with self.assertRaises(ValueError):
                core_use.checked_program({"label": "Use", "steps": steps})
        with self.assertRaisesRegex(ValueError, "exactly one"):
            fracture_lab.normalise_actions([
                {"body": "stool", "label": name, "primary": True, "steps": [{"do": "inspect"}]}
                for name in ("One", "Two")], [STOOL])

    def test_workshop_program_survives_edit_graph_contract_and_install_mapping(self):
        from mcp import core_use, workshop, workshop_components, workshop_graph, product_contract
        program = {"label": "Push cart", "steps": [{"do": "push_forward", "distance_m": .5, "speed_m_s": .4}]}
        design = workshop.assemble("cart", parameters={"primary_use": program})
        spec = design.wireframe()
        part = design.parts[0].name
        edited, _, _ = workshop_components.edit(spec, part_name=part, action="thicker")
        self.assertEqual(edited.parameters["primary_use"], program)
        graph = workshop_graph.product(edited)
        controls = product_contract.compile_contract(graph)["controls"]
        self.assertTrue(controls[0]["programmed"])
        self.assertEqual(controls[0]["program"]["label"], "Push cart")
        self.assertEqual(core_use.installed(edited, "installed-root")["body"], "installed-root")
        self.assertEqual(core_use.installed(edited, "installed-root")["steps"], program["steps"])
        import tempfile
        import workshop_store
        with tempfile.TemporaryDirectory() as folder:
            workshop_store.save(Path(folder), edited)
            _, reopened = workshop_store.load(Path(folder), edited.design_id)
            self.assertEqual(reopened.parameters["primary_use"], program)


    def test_model_tool_call_programs_the_candidate(self):
        from mcp import workshop
        import workshop_chat
        from types import SimpleNamespace
        candidate = workshop.assemble("table").wireframe()
        app = SimpleNamespace(api_key="test-only", model="test-model")
        replies = [
            {"output": [{"type": "function_call", "call_id": "use-1", "name": "program_use",
                         "arguments": json.dumps({"label": "Push forward", "steps": [{"do": "push_forward"}]})}]},
            {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Use pushes the table."}]}]},
        ]
        with mock.patch.object(workshop_chat, "_call_model", side_effect=replies) as model, \
             mock.patch.object(workshop_chat, "_refresh", side_effect=lambda app, candidate, design, overrides: candidate.update(design.wireframe())):
            result = workshop_chat.propose(app, message="program its core use", selected_part=None,
                                           candidate=candidate, materials=["oak"], library=[])
        self.assertEqual(result["changed"], ["primary_use"])
        self.assertEqual(candidate["parameters"]["primary_use"]["steps"][0]["do"], "push_forward")
        self.assertIn("program_use", [t["name"] for t in model.call_args_list[0].args[1]["tools"]])

    def test_workshop_llm_can_program_use_and_invalid_edit_is_atomic(self):
        from mcp import workshop
        import workshop_chat
        from types import SimpleNamespace
        candidate = workshop.assemble("table").wireframe()
        app = SimpleNamespace()
        state = workshop_chat._State(app, candidate, None, ["oak"], [])
        with mock.patch.object(workshop_chat, "_refresh", side_effect=lambda app, candidate, design, overrides: candidate.update(design.wireframe())):
            result = state.execute("program_use", {"label": "Push it forward", "steps": [{"do": "push_forward"}]})
            self.assertEqual(result["primary_use"]["label"], "Push it forward")
            before = json.dumps(candidate)
            with self.assertRaises(ValueError):
                state.execute("program_use", {"label": "Fly", "steps": [{"do": "teleport"}]})
            self.assertEqual(json.dumps(candidate), before)


if __name__ == "__main__":
    unittest.main()
