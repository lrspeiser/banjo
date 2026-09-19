"""A room is kept on disk, so a server started again opens it as it was left.

    python tests/room_store_tests.py -v

The sims are restarted whenever work lands, and every restart used to throw
away everything the chat had built and every pit dug by hand: rooms lived only
in the server's memory. Now each change is written to one file for the room
(playground/room_store.py) and read back the first time the room is opened
after a restart. These tests start a server, change a room the ways the chat
and the page do, start ANOTHER server on the same folder, and open the room
again. They hold a stand-in for the live world, so they need no engine and no
model.
"""
from __future__ import annotations

import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "playground"))

from playground_tests import PlaygroundTestCase, playground_server  # noqa: E402
import inventory_room  # noqa: E402
import live_session  # noqa: E402
import room_store   # noqa: E402
import world_chat   # noqa: E402
import world_room   # noqa: E402

CRATE = {"name": "oak crate", "shape": "box", "material": "oak",
         "size_mm": [320, 320, 320], "center_mm": [0, 160, 0]}


def names(spec):
    return {body["name"] for body in spec["bodies"]}


class StandInLive:
    """The live world, as far as opening one goes: it keeps what it was asked to
    open, and refuses a room with a body called "will not open" in it. It saves
    a stand-in world (snapshot, as live_session.Live does, carrying the digest of
    the spec it was opened from) and opens into one it is given, as the engine
    would: whole, or -- for one marked `refuse` -- from its spec, saying why; one
    marked `crash` it will not open at all."""

    def __init__(self):
        self.opened = []
        self.given = []        # the saved world each open was asked to open into, or None
        self.snapshots = []    # every world it saved
        self.rejoined = 0
        self.session = None

    def snapshot(self):
        if self.session is None:
            return None, "no world is open"
        saved = {"format": "banjo.world.v1", "spec_digest": self.session.spec_digest, "t_s": 0.0,
                 "saved": len(self.snapshots)}
        self.snapshots.append(saved)
        return json.loads(json.dumps(saved)), ""

    def rejoin(self, app):
        """The room that is running, as a page opening it again gets it: the same
        world under a new id, so a page holding the old one has lost the room."""
        if self.session is None:
            return None
        self.rejoined += 1
        self.session.id = f"{self.session.id}-again"
        return {"session": self.session.id, "rejoined": True,
                "bodies": [{"name": n} for n in sorted(names(self.opened[-1]))]}

    def open(self, app, body):
        spec = json.loads(json.dumps(body["spec"]))
        if "will not open" in names(spec):
            raise ValueError("the engine refused it")
        world = body.get("snapshot")
        if isinstance(world, dict) and world.get("crash"):
            raise ValueError("the engine fell over opening the saved world")
        self.opened.append(spec)
        self.given.append(world)
        self.session = SimpleNamespace(id=f"session-{len(self.opened)}", state={"bodies": []},
                                       send=lambda **_: {},
                                       spec_digest=live_session.spec_digest(body["spec"]))
        opened = {"session": self.session.id, "bodies": [{"name": n} for n in sorted(names(spec))]}
        if isinstance(world, dict):
            opened["restored"] = (
                {"tier": "none", "why": world["refuse"], "saved_t_s": 0.0, "bodies": 0,
                 "not_kept": [], "parked": []} if world.get("refuse") else
                {"tier": "whole", "why": "", "saved_t_s": 0.0, "bodies": len(names(spec)),
                 "not_kept": ["heat, char and fuel"], "parked": []})
        return opened

    def shutdown(self):
        pass


def the_chat_builds_a_crate(api_key, model, room, state, message, story, **_):
    """What world_chat.ask does to a room when it builds: the spec becomes the
    room as built (export_spec), and the answer says it changed."""
    room.spec = dict(room.spec, bodies=room.spec["bodies"] + [dict(CRATE)])
    return {"reply": "I built an oak crate.", "did": ["added oak crate"], "changed": True,
            "usage": {}, "rounds": 1}


class KeptRoomsTestCase(PlaygroundTestCase):
    def setUp(self):
        super().setUp()
        self.folder = self.base / "rooms"
        # The chat's transcript goes to the repository's build folder, and a
        # test has nothing to say there.
        patcher = mock.patch.object(playground_server, "remember_chat")
        patcher.start()
        self.addCleanup(patcher.stop)

    def start(self, folder=None):
        """A server as `main` makes one, keeping its rooms in `folder`."""
        app = self.make_app(mock.Mock())
        app.store = room_store.RoomStore(folder or self.folder)
        app.live = StandInLive()
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
        return app

    def post(self, app, path, body):
        connection = http.client.HTTPConnection("127.0.0.1", app.port, timeout=60)
        try:
            connection.request("POST", path, body=json.dumps(body),
                               headers={"Content-Type": "application/json",
                                        "X-Banjo-Token": app.csrf_token})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def open(self, app, **body):
        status, answer = self.post(app, "/api/world/open", body)
        self.assertEqual(status, 200, answer)
        return answer

    def ask(self, app, message, chat=the_chat_builds_a_crate):
        with mock.patch.object(world_chat, "ask", side_effect=chat):
            status, answer = self.post(app, "/api/world/ask",
                                       {"session": app.live.session.id, "message": message})
        self.assertEqual(status, 200, answer)
        return answer


class APageThatLostItsRoom(KeptRoomsTestCase):
    """The playground runs one room at a time, and a page whose room was opened
    again -- in another tab, by another person -- no longer has it. Its chat
    would build in the room somebody else has open."""

    def test_its_chat_is_refused_and_asks_no_model(self):
        app = self.start()
        stale = self.open(app, scene="yard")["session"]
        self.open(app, scene="yard")               # opened again, by another page
        with mock.patch.object(world_chat, "ask", side_effect=the_chat_builds_a_crate) as chat:
            status, answer = self.post(app, "/api/world/ask",
                                       {"session": stale, "message": "an oak crate, please"})
        self.assertEqual(status, 400, answer)
        self.assertIn("no longer has the room", answer["error"])
        chat.assert_not_called()


class APageOpeningItsRoomAgain(KeptRoomsTestCase):
    """A reload is not a new room. A page opening the room that is running here
    joins it as it stands -- moved, broken, the hand holding what it held --
    rather than opening it again from its spec, which put all of that back as
    authored."""

    def test_a_reload_rejoins_the_running_room_and_fresh_opens_it_again(self):
        app = self.start()
        first = self.open(app, scene="yard")
        again = self.open(app, scene="yard")
        self.assertTrue(again.get("rejoined"), again)
        self.assertEqual(len(app.live.opened), 1, "the room was opened again from its spec")
        self.assertEqual(app.live.rejoined, 1)
        self.assertNotEqual(again["session"], first["session"])
        self.assertEqual(again["scene"], "yard")
        self.assertIn("inventory", again)
        self.assertIn("chat", again)
        # The page that had it has lost it, as when opening replaced the room.
        with mock.patch.object(world_chat, "ask", side_effect=the_chat_builds_a_crate) as chat:
            status, answer = self.post(app, "/api/world/ask",
                                       {"session": first["session"], "message": "an oak crate, please"})
        self.assertEqual(status, 400, answer)
        chat.assert_not_called()
        # "Start the room again" opens it again from what it is held as.
        replayed = self.open(app, scene="yard", again=True)
        self.assertFalse(replayed.get("rejoined"))
        self.assertEqual(len(app.live.opened), 2, "Start the room again did not open it again")
        fresh = self.open(app, scene="yard", fresh=True)
        self.assertFalse(fresh.get("rejoined"))
        self.assertEqual(len(app.live.opened), 3, "fresh did not open the room again")

    def test_another_room_is_opened_not_rejoined(self):
        app = self.start()
        self.open(app, scene="yard")
        other = next(s for s in sorted(world_room.SCENES) if s != "yard")
        opened = self.open(app, scene=other)
        self.assertFalse(opened.get("rejoined"))
        self.assertEqual(len(app.live.opened), 2)
        self.assertEqual(app.live.rejoined, 0)


class ARoomOutlivesItsServer(KeptRoomsTestCase):
    def test_what_the_chat_built_is_there_after_a_restart(self):
        first = self.start()
        self.assertFalse(self.open(first, scene="yard")["kept"])
        self.ask(first, "an oak crate, please")
        again = self.start()          # the server started again, on the same folder
        opened = self.open(again, scene="yard")
        self.assertTrue(opened["kept"])
        self.assertIsInstance(opened["kept_since_unix_s"], float)
        self.assertIn("oak crate", names(again.live.opened[-1]), "the restart lost the crate")
        # And what was said, so "confirmed" still answers what the room asked.
        self.assertEqual([turn["asked"] for turn in again.room.chat], ["an oak crate, please"])
        # And the page is handed it, to show the conversation again.
        self.assertEqual([turn["asked"] for turn in opened["chat"]], ["an oak crate, please"])

    def test_a_pit_dug_by_hand_is_there_after_a_restart(self):
        first = self.start()
        self.open(first, scene="clearing")
        dig = {"op": "dig", "from": [0.5, 1.0], "to": [0.5, 1.0], "width_m": 0.4, "depth_m": 0.2}
        playground_server.remember_ground(first, dig)      # as /api/live/act does
        again = self.start()
        self.open(again, scene="clearing")
        self.assertEqual(again.live.opened[-1]["terrain"]["edits"],
                         [{"dig": {"from_m": [0.5, 1.0], "to_m": [0.5, 1.0],
                                   "width_m": 0.4, "depth_m": 0.2}}])

    def test_fresh_is_the_room_as_first_made_and_is_kept_as_that(self):
        first = self.start()
        self.open(first, scene="yard")
        self.ask(first, "an oak crate, please")
        self.open(first, scene="yard", fresh=True)
        self.assertNotIn("oak crate", names(first.live.opened[-1]))
        again = self.start()
        self.open(again, scene="yard")
        self.assertEqual(again.live.opened[-1], world_room.yard())
        self.assertEqual(again.room.chat, [])

    def test_starting_the_room_again_replays_the_room_this_server_holds(self):
        """Start the room again -- the page's button -- replays the room as it is
        held, as it always did: nothing is read back from disk under it. (A
        reload rejoins the running room instead: APageOpeningItsRoomAgain.)"""
        app = self.start()
        self.open(app, scene="yard")
        self.ask(app, "an oak crate, please")
        held = app.room
        opened = self.open(app, scene="yard", again=True)
        self.assertFalse(opened["kept"])
        self.assertFalse(opened.get("rejoined"))
        self.assertIs(app.room, held)
        self.assertIn("oak crate", names(app.live.opened[-1]))

    def test_each_server_keeps_its_own_rooms(self):
        """The three sims share one checkout: one person's world is not another
        port's test room."""
        mine = self.start(self.base / "rooms-8765")
        theirs = self.start(self.base / "rooms-8768")
        self.open(mine, scene="yard")
        self.ask(mine, "an oak crate, please")
        self.open(theirs, scene="yard")
        again = self.start(self.base / "rooms-8768")
        self.open(again, scene="yard")
        self.assertNotIn("oak crate", names(again.live.opened[-1]))


class WhatCannotBeKeptOrRead(KeptRoomsTestCase):
    def test_a_file_that_cannot_be_read_is_set_aside_not_lost(self):
        self.folder.mkdir(parents=True)
        (self.folder / "yard.json").write_text("{ half a room", encoding="utf-8")
        app = self.start()
        opened = self.open(app, scene="yard")
        self.assertFalse(opened["kept"])
        self.assertEqual(app.live.opened[-1], world_room.yard())
        aside = list(self.folder.glob("yard.set-aside-*.json"))
        self.assertEqual(len(aside), 1)
        self.assertEqual(aside[0].read_text(encoding="utf-8"), "{ half a room")

    def test_a_kept_room_that_will_not_open_is_set_aside_and_the_room_opens_as_made(self):
        first = self.start()
        self.open(first, scene="yard")

        def the_chat_builds_what_will_not_open(api_key, model, room, *_, **__):
            room.spec = dict(room.spec, bodies=room.spec["bodies"] + [
                dict(CRATE, name="will not open")])
            return {"reply": "Built.", "did": [], "changed": False, "usage": {}, "rounds": 1}
        self.ask(first, "something odd", chat=the_chat_builds_what_will_not_open)
        again = self.start()
        opened = self.open(again, scene="yard")
        self.assertFalse(opened["kept"])
        self.assertIn("set aside", opened["kept_problem"])
        self.assertEqual(again.live.opened[-1], world_room.yard())
        self.assertEqual(len(list(self.folder.glob("yard.set-aside-*.json"))), 1)

    def test_a_disk_that_will_not_take_it_does_not_break_the_room(self):
        app = self.start()
        self.open(app, scene="yard")
        with mock.patch.object(app.store, "save", side_effect=OSError("the disk is full")):
            answer = self.ask(app, "an oak crate, please")
        self.assertEqual(answer["reply"], "I built an oak crate.")
        self.assertIn("oak crate", names(app.room.spec))

    def test_a_room_is_written_whole(self):
        app = self.start()
        self.open(app, scene="yard")
        self.ask(app, "an oak crate, please")
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ["yard.json"])
        record = json.loads((self.folder / "yard.json").read_text(encoding="utf-8"))
        self.assertEqual((record["format"], record["scene"]), ("banjo.room.v2", "yard"))
        # With the world as it stood when last saved: the chat's room, opened.
        self.assertEqual(record["world"], app.live.snapshots[-1])

    def test_a_world_the_engine_will_not_open_at_all_is_set_aside_and_the_room_opens_from_its_spec(self):
        first = self.start()
        self.open(first, scene="yard")
        path = self.folder / "yard.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["world"]["crash"] = True
        path.write_text(json.dumps(record), encoding="utf-8")
        again = self.start()
        opened = self.open(again, scene="yard")
        self.assertIn("set aside", opened["kept_problem"])
        self.assertIsNone(again.live.given[-1], "the room was not opened from its spec in the end")
        aside = list(self.folder.glob("yard.world-set-aside-*.json"))
        self.assertEqual(len(aside), 1)
        self.assertTrue(json.loads(aside[0].read_text(encoding="utf-8"))["world"]["crash"])
        # The room itself was not set aside: only its world.
        self.assertEqual(list(self.folder.glob("yard.set-aside-*.json")), [])

    def test_only_the_rooms_on_the_menu_are_kept(self):
        store = room_store.RoomStore(self.folder)
        room = world_room.Room("yard")
        room.scene = "qa:20260912-101201/hinged-gate-1"
        self.assertFalse(store.save(room))
        self.assertFalse(self.folder.exists())
        self.assertIsNone(store.load("../yard"))


class ARoomComesBackAsItStood(KeptRoomsTestCase):
    """A restart gives back the running world, not only the authored room: the
    world is saved with the room (room_store v2's `world`, server.keep_world),
    and the first open after a restart opens the room into it -- as it stood --
    when it was saved from the spec the room has now. What the engine will not
    put back whole is set aside, and the room opens from its spec."""

    def test_the_world_kept_with_a_room_is_what_it_opens_into_after_a_restart(self):
        first = self.start()
        self.open(first, scene="yard")
        record = json.loads((self.folder / "yard.json").read_text(encoding="utf-8"))
        self.assertEqual(record["format"], "banjo.room.v2")
        self.assertEqual(record["world"], first.live.snapshots[-1], "the world was not kept as it opened")
        self.assertIsNone(first.live.given[-1], "a room opened for the first time was opened into a world")
        again = self.start()
        opened = self.open(again, scene="yard")
        self.assertEqual(again.live.given[-1], first.live.snapshots[-1],
                         "the room was not opened into the world kept with it")
        self.assertTrue(opened["kept"])
        self.assertEqual(opened["restored"]["tier"], "whole")
        self.assertNotIn("kept_problem", opened)
        # A reload after that rejoins it; "Start the room again" opens it from
        # its spec, and the world kept from then on is that one.
        self.assertTrue(self.open(again, scene="yard").get("rejoined"))
        self.open(again, scene="yard", again=True)
        self.assertIsNone(again.live.given[-1])
        self.assertEqual(json.loads((self.folder / "yard.json").read_text(encoding="utf-8"))["world"],
                         again.live.snapshots[-1])

    def test_the_world_is_kept_as_the_page_steps_it_and_after_a_break(self):
        app = self.start()
        opened = self.open(app, scene="yard")
        saved = len(app.live.snapshots)
        body = {"session": opened["session"], "op": "step"}
        playground_server.keep_world_after(app, body, {"t": 1.0})
        self.assertEqual(len(app.live.snapshots), saved, "saved a second into the world")
        playground_server.keep_world_after(app, body, {"t": playground_server.KEEP_WORLD_EVERY_S + 0.5})
        self.assertEqual(len(app.live.snapshots), saved + 1, "not saved after five seconds of the world")
        playground_server.keep_world_after(app, {"op": "step"}, {"t": 6.0, "finished": "pane"})
        self.assertEqual(len(app.live.snapshots), saved + 2, "not saved once a break was worked out")

    def test_a_refused_world_keeps_the_last_one(self):
        app = self.start()
        self.open(app, scene="yard")
        kept = json.loads((self.folder / "yard.json").read_text(encoding="utf-8"))["world"]
        with mock.patch.object(app.live, "snapshot", return_value=(None, "a break is being worked out")):
            self.assertFalse(playground_server.keep_world(app, "a test"))
        self.assertEqual(json.loads((self.folder / "yard.json").read_text(encoding="utf-8"))["world"], kept)

    def test_a_room_kept_before_its_world_was_opens_from_its_spec(self):
        self.folder.mkdir(parents=True)
        (self.folder / "yard.json").write_text(json.dumps(
            {"format": "banjo.room.v1", "scene": "yard", "saved_unix_s": 1.0,
             "spec": world_room.yard(), "chat": [{"asked": "hello", "replied": "hi"}]}), encoding="utf-8")
        app = self.start()
        opened = self.open(app, scene="yard")
        self.assertTrue(opened["kept"])
        self.assertIsNone(app.live.given[-1])
        self.assertNotIn("restored", opened)
        self.assertEqual([turn["asked"] for turn in opened["chat"]], ["hello"])

    def test_a_world_saved_before_the_chat_changed_the_room_is_not_opened_into_it(self):
        first = self.start()
        self.open(first, scene="yard")

        def the_chat_builds_without_opening_again(api_key, model, room, *_, **__):
            room.spec = dict(room.spec, bodies=room.spec["bodies"] + [dict(CRATE)])
            return {"reply": "Built.", "did": [], "changed": False, "usage": {}, "rounds": 1}
        self.ask(first, "an oak crate, please", chat=the_chat_builds_without_opening_again)
        again = self.start()
        opened = self.open(again, scene="yard")
        self.assertIsNone(again.live.given[-1], "a world saved before the chat's change was opened into its room")
        self.assertIn("oak crate", names(again.live.opened[-1]))
        self.assertNotIn("kept_problem", opened)

    def test_a_world_the_engine_will_not_put_back_whole_is_set_aside(self):
        first = self.start()
        self.open(first, scene="yard")
        path = self.folder / "yard.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["world"]["refuse"] = "its cells are not this room's"
        path.write_text(json.dumps(record), encoding="utf-8")
        again = self.start()
        opened = self.open(again, scene="yard")
        self.assertIn("could not be put back", opened["kept_problem"])
        self.assertIn("its cells are not this room's", opened["kept_problem"])
        aside = list(self.folder.glob("yard.world-set-aside-*.json"))
        self.assertEqual(len(aside), 1)
        self.assertEqual(json.loads(aside[0].read_text(encoding="utf-8"))["why"], "its cells are not this room's")
        # The world kept from then on is the one the room opened as.
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["world"], again.live.snapshots[-1])


class TheSpecAWorldIsSavedFrom(unittest.TestCase):
    """live_session.spec_digest, the room's word for the spec a world was opened
    from: a saved world is opened only into a room whose spec says the same.
    What changes without changing what the world is made of leaves it as it was
    -- a dig written into the room's ground, the water carried into a world the
    chat opened again (server.with_water, which gives a room with no water block
    one holding only its state) -- and what the chat builds does not."""

    SPEC = {"bodies": [dict(CRATE)], "terrain": {"generate": "flat"}}

    def test_what_does_not_change_the_world_does_not_change_it(self):
        digest = live_session.spec_digest(self.SPEC)
        self.assertTrue(digest)
        dug = dict(self.SPEC, terrain=dict(self.SPEC["terrain"], edits=[
            {"dig": {"from_m": [0.5, 1.0], "to_m": [0.5, 1.0], "width_m": 0.4, "depth_m": 0.2}}]))
        self.assertEqual(live_session.spec_digest(dug), digest, "a dig changed the spec's word")
        carried = dict(self.SPEC, water={"state": {"nx": 2, "nz": 2, "depth_b64": "AAAA"}})
        self.assertEqual(live_session.spec_digest(carried), digest,
                         "water carried into a room with no water block changed the spec's word")
        declared = dict(self.SPEC, water={"discharge_m3_s": 0.3})
        self.assertEqual(live_session.spec_digest(dict(declared, water=dict(declared["water"], state={"nx": 2}))),
                         live_session.spec_digest(declared), "carried water changed a watered room's word")
        self.assertNotEqual(live_session.spec_digest(declared), digest, "a river declared is not a change")

    def test_what_the_chat_builds_changes_it(self):
        built = dict(self.SPEC, bodies=self.SPEC["bodies"] + [dict(CRATE, name="another crate")])
        self.assertNotEqual(live_session.spec_digest(built), live_session.spec_digest(self.SPEC))

    def test_a_room_that_declares_nothing_new_has_the_word_it_always_had(self):
        """A pinned value, because what it guards is every saved world there is.

        The word is taken from the spec as the ROOM holds it: authored, kept
        verbatim (room_store), written back field by field
        (room_world.export_spec). It is not taken from what
        fracture_lab.validate returns, which invents fields of its own -- an id,
        the size actually built, a cell count, and since #20 which part of a
        joined object a body is. Digesting the validated spec instead would be a
        new word for every room that had not changed, and each would open from
        its spec with its saved world set aside. So if this value moves, check
        that it moved because a room really is made of something different --
        not because the spec grew a field on the way to the engine."""
        self.assertEqual("cf591eb8f10962fccb565da5c058757491ac0323e420aee8da4bdc3ed4c1a2a5",
                         live_session.spec_digest(self.SPEC))
        # A room that does declare a part is a different thing, and says so.
        declared = dict(self.SPEC, bodies=[dict(CRATE, join="t", part="side")])
        self.assertNotEqual(live_session.spec_digest(declared), live_session.spec_digest(self.SPEC))


class WhatThePersonHoldsThroughARestart(unittest.TestCase):
    """inventory_room.after_open on a room opened again whole: a thing in the
    hand the engine still holds stays in the hand. From the spec, it goes back
    into the bag, as before."""

    SPEC = {"bodies": [{"id": "b-floor00001", "name": "floor", "shape": "box", "material": "oak",
                        "size_mm": [600, 40, 400], "center_mm": [0, 20, 0], "anchored": True},
                       {"id": "b-ball000001", "name": "ball", "shape": "sphere", "material": "iron",
                        "size_mm": [100, 100, 100], "center_mm": [0, 600, 0]}]}

    def app(self, holding):
        asked = []
        session = SimpleNamespace(id="s1", state={"hand": {"holding": holding}, "bodies": [{"name": "ball"}]})
        live = SimpleNamespace(session=session, act=lambda body: asked.append(body) or {"ok": True})
        room = SimpleNamespace(spec=self.SPEC, inventory=None,
                               inventory_record={"revision": 3, "dominant": "right",
                                                 "hands": {"right": "b-ball000001", "left": None},
                                                 "stowed": [], "home": {}, "facing": {}})
        return SimpleNamespace(room=room, live=live), asked

    def test_a_held_thing_stays_in_the_hand_when_the_engine_still_holds_it(self):
        app, asked = self.app("ball")
        shown = inventory_room.after_open(app, {"restored": {"tier": "whole", "parked": []}})
        self.assertEqual(shown["hands"]["right"]["name"], "ball")
        self.assertEqual(shown["stowed"], [])
        self.assertEqual(asked, [], "the engine was asked to change something it already had right")

    def test_from_its_spec_it_goes_back_into_the_bag(self):
        app, asked = self.app("")
        shown = inventory_room.after_open(app, {"bodies": [{"name": "ball"}]})
        self.assertIsNone(shown["hands"]["right"])
        self.assertEqual([t["name"] for t in shown["stowed"]], ["ball"])
        self.assertEqual([a["op"] for a in asked], ["park"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
