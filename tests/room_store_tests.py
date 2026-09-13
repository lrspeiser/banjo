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
import room_store   # noqa: E402
import world_chat   # noqa: E402
import world_room   # noqa: E402

CRATE = {"name": "oak crate", "shape": "box", "material": "oak",
         "size_mm": [320, 320, 320], "center_mm": [0, 160, 0]}


def names(spec):
    return {body["name"] for body in spec["bodies"]}


class StandInLive:
    """The live world, as far as opening one goes: it keeps what it was asked to
    open, and refuses a room with a body called "will not open" in it."""

    def __init__(self):
        self.opened = []
        self.session = None

    def open(self, app, body):
        spec = json.loads(json.dumps(body["spec"]))
        if "will not open" in names(spec):
            raise ValueError("the engine refused it")
        self.opened.append(spec)
        self.session = SimpleNamespace(id=f"session-{len(self.opened)}", state={"bodies": []},
                                       send=lambda **_: {})
        return {"session": self.session.id, "bodies": [{"name": n} for n in sorted(names(spec))]}

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
            status, answer = self.post(app, "/api/world/ask", {"message": message})
        self.assertEqual(status, 200, answer)
        return answer


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

    def test_a_reload_opens_the_room_this_server_holds(self):
        """Start the room again -- the page's button -- replays the room as it is
        held, as it always did: nothing is read back from disk under it."""
        app = self.start()
        self.open(app, scene="yard")
        self.ask(app, "an oak crate, please")
        held = app.room
        opened = self.open(app, scene="yard")
        self.assertFalse(opened["kept"])
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
        self.assertEqual((record["format"], record["scene"]), ("banjo.room.v1", "yard"))

    def test_only_the_rooms_on_the_menu_are_kept(self):
        store = room_store.RoomStore(self.folder)
        room = world_room.Room("yard")
        room.scene = "qa:20260912-101201/hinged-gate-1"
        self.assertFalse(store.save(room))
        self.assertFalse(self.folder.exists())
        self.assertIsNone(store.load("../yard"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
