"""Opening a saved QA build by id: POST /api/world/open {"qa": "<run>/<case>-<trial>"}.

    python tests/qa_open_tests.py -v

The id is the only thing a request can say about which file is read, so what is
refused matters as much as what opens: anything that is not exactly
<run>/<case>-<trial> never becomes part of a path, and a build that is not
there says so. The opening tests hold a stand-in for the live world, so they
need no engine; one more opens a saved build in the real live engine when that
is built (BANJO_LIVE_ENGINE, or build/integration). The framing helpers of
tests/qa_browser.py, which photographs these builds, are checked here too.
"""
from __future__ import annotations

import http.client
from http.server import ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "playground"))

from playground_tests import PlaygroundTestCase, plan_for, playground_server  # noqa: E402
import qa_browser   # noqa: E402
import world_room   # noqa: E402

ENGINE = next((p for p in [
    *([Path(os.environ["BANJO_LIVE_ENGINE"])] if os.environ.get("BANJO_LIVE_ENGINE") else []),
    ROOT / "build/integration/Release/banjo_live_world_run.exe",
    ROOT / "build/integration/banjo_live_world_run",
] if p.is_file()), None)

RUN = "20260912-101201"
BUILD = f"{RUN}/hinged-gate-1"


def small_room():
    """A yard with one thing built in it: a room that opens in a moment."""
    spec = world_room.yard()
    spec["bodies"].append({"name": "oak crate", "shape": "box", "material": "oak",
                           "size_mm": [320, 320, 320], "center_mm": [0, 160, 0]})
    return spec


def names(spec):
    return {body["name"] for body in spec["bodies"]}


class StandInLive:
    """The live world, as far as opening one goes: it keeps what it was asked to open."""

    def __init__(self):
        self.opened = []
        self.session = None

    def open(self, app, body):
        self.opened.append(json.loads(json.dumps(body["spec"])))
        return {"session": f"session-{len(self.opened)}",
                "bodies": [{"name": b["name"]} for b in body["spec"]["bodies"]]}

    def shutdown(self):
        pass


class QaOpenTestCase(PlaygroundTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.make_app(mock.Mock(return_value=(plan_for("unsupported"),
                                                         {"model": "fake-model"})))
        self.saved = self.base / "agent-regression"
        patcher = mock.patch.object(playground_server, "QA_ROOT", self.saved)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), playground_server.Handler)
        self.httpd.app = self.app
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.port = self.httpd.server_port

    def stop_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)

    def save(self, build_id, spec_or_text):
        path = self.saved / f"{build_id}.spec.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        text = spec_or_text if isinstance(spec_or_text, str) else json.dumps(spec_or_text)
        path.write_text(text, encoding="utf-8")
        return path

    def open(self, body):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        try:
            connection.request("POST", "/api/world/open", body=json.dumps(body),
                               headers={"Content-Type": "application/json",
                                        "X-Banjo-Token": self.app.csrf_token})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()


class OpeningASavedBuild(QaOpenTestCase):
    def setUp(self):
        super().setUp()
        self.live = self.app.live = StandInLive()

    def test_a_saved_build_opens_as_a_room(self):
        spec = small_room()
        self.save(BUILD, spec)
        status, body = self.open({"qa": BUILD})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["scene"], f"qa:{BUILD}")
        self.assertEqual(self.live.opened, [spec], "the world was not opened from the saved room")
        # Held as the room the chat would change, under its own key.
        self.assertIs(self.app.room, self.app.rooms[f"qa:{BUILD}"])
        self.assertEqual(self.app.room.spec, spec)
        self.assertEqual(self.app.room.scene, f"qa:{BUILD}")

    def test_a_reload_keeps_what_the_chat_did_to_it_and_fresh_reads_the_file_again(self):
        self.save(BUILD, small_room())
        self.open({"qa": BUILD})
        # What the chat does to a room: change its spec in place.
        self.app.room.spec["bodies"].append({
            "name": "iron ball", "shape": "sphere", "material": "iron",
            "size_mm": [120, 120, 120], "center_mm": [600, 60, 0]})
        status, _ = self.open({"qa": BUILD})
        self.assertEqual(status, 200)
        self.assertIn("iron ball", names(self.live.opened[-1]), "a reload lost the chat's change")
        status, _ = self.open({"qa": BUILD, "fresh": True})
        self.assertEqual(status, 200)
        self.assertNotIn("iron ball", names(self.live.opened[-1]),
                         "fresh did not go back to the saved room")

    def test_traversal_and_anything_else_that_is_not_an_id_is_refused(self):
        # Real rooms just outside the folder, so that a refusal cannot be a
        # missing file in disguise.
        self.save("../x", small_room())
        self.save(f"{RUN}/../../outside-1", small_room())
        before = self.app.room
        for bad in ["../x", f"{RUN}/../../outside-1", f"{RUN}/hinged-gate-1/../../x-1",
                    "..\\x", f"{RUN}\\hinged-gate-1", f"/{RUN}/hinged-gate-1",
                    f"C:/{RUN}/hinged-gate-1", f"{RUN}/Hinged-Gate-1", f"{RUN}/hinged-gate",
                    f"{RUN}/hinged_gate-1", f"{RUN}/hinged-gate-1.spec.json",
                    f"{RUN}/hinged-gate-1\n", "20260912/hinged-gate-1",
                    # Digits, but not ASCII ones.
                    "\u0662\u0660\u0662\u0666\u0660\u0669\u0661\u0662-"
                    "\u0661\u0660\u0661\u0662\u0660\u0661/hinged-gate-1",
                    "", 12, None, [BUILD], {"id": BUILD}]:
            with self.subTest(qa=bad):
                status, body = self.open({"qa": bad})
                self.assertEqual(status, 400, body)
                self.assertIn("<run>/<case>-<trial>", body["error"])
        self.assertEqual(self.live.opened, [], "a refused id still opened a world")
        self.assertIs(self.app.room, before, "a refused id replaced the room")

    def test_a_build_that_is_not_there_says_so(self):
        before = self.app.room
        status, body = self.open({"qa": BUILD})
        self.assertEqual(status, 404, body)
        self.assertIn(f"no saved QA build {BUILD}", body["error"])
        self.assertIn(f"build/agent-regression/{BUILD}.spec.json", body["error"])
        self.assertEqual(self.live.opened, [])
        self.assertIs(self.app.room, before)

    def test_a_file_that_is_not_a_room_is_refused(self):
        for text in ["[1, 2]", '{"bodies": 3}', "not json", '{"bodies": [], "bodies": []}',
                     '{"bodies": [], "cell_m": NaN}']:
            with self.subTest(text=text):
                self.save(BUILD, text)
                status, body = self.open({"qa": BUILD})
                self.assertEqual(status, 400, body)
        self.assertEqual(self.live.opened, [])

    def test_the_rooms_on_the_menu_still_open_by_name(self):
        status, body = self.open({"scene": "yard"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["scene"], "yard")
        self.assertEqual(self.live.opened, [world_room.yard()])


@unittest.skipUnless(ENGINE, "the live engine is not built")
class OpeningASavedBuildInTheEngine(QaOpenTestCase):
    def test_the_live_world_opens_with_what_was_saved(self):
        # The live engine is found next to the engine the server was given.
        self.app.engine_path = ENGINE.with_name("banjo_platform_cli" + ENGINE.suffix)
        self.addCleanup(self.app.live.shutdown)
        spec = small_room()
        self.save(BUILD, spec)
        status, body = self.open({"qa": BUILD})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["scene"], f"qa:{BUILD}")
        self.assertEqual({b["name"] for b in body["bodies"]}, names(spec))
        self.assertIsNotNone(self.app.live.session)


class FramingASavedBuild(unittest.TestCase):
    """tests/qa_browser.py stands back from what was built and looks at it."""

    def test_the_marker_stone_is_not_part_of_the_build(self):
        focus, extent = qa_browser.frame_of(small_room())
        self.assertEqual(focus, [0.0, 0.16, 0.0])
        self.assertAlmostEqual(extent, 0.5 * math.sqrt(3 * 0.32 ** 2), places=4)

    def test_the_eye_stands_back_and_above_and_looks_at_the_build(self):
        eye, look = qa_browser.framing([0.0, 1.0, 0.0], 2.0)
        # 1.3 extents and 0.6 m back (it was 2.5 and a metre, which left builds
        # filling 1.4 to 3.2% of the picture).
        self.assertAlmostEqual(math.hypot(eye[0], eye[2]), 1.3 * 2.0 + 0.6, places=2)
        self.assertGreater(eye[2], 0.0, "not on the side the room's camera faces from")
        self.assertGreater(eye[1], 1.0, "the eye is not above the focus")
        self.assertEqual(look, [0.0, 1.0, 0.0])

    def test_the_frame_takes_in_where_loose_things_will_go(self):
        # A ball two metres up and a block sent sliding at 3 m/s: the frame has
        # to reach the floor under the ball and a second of the block's slide,
        # and must not take in the marker stone five metres off.
        room = {"bodies": [
            {"name": "marker stone", "shape": "box", "material": "concrete",
             "size_mm": [80, 80, 80], "center_mm": [-5000, 40, -5000], "anchored": True},
            {"name": "ball", "shape": "sphere", "material": "rubber",
             "size_mm": [200, 200, 200], "center_mm": [0, 2100, 0]},
            {"name": "block", "shape": "box", "material": "ice", "size_mm": [240, 240, 240],
             "center_mm": [0, 120, 400], "velocity_m_s": [3.0, 0.0, 0.0]}]}
        focus, extent = qa_browser.motion_frame(room, [0.0, 2.1, 0.0], 0.3)
        self.assertLessEqual(focus[1] - extent, 1e-6, "the floor under the ball is out of frame")
        self.assertGreaterEqual(focus[0] + extent, 0.12 + 3.0 - 1e-6,
                                "the block's slide is out of frame")
        self.assertLess(extent, 5.0, "the marker stone was framed as part of the build")

    def test_a_run_is_one_build_for_each_saved_room(self):
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(qa_browser, "QA_ROOT", Path(folder)):
            run = Path(folder) / RUN
            run.mkdir()
            for name in ("hinged-gate-1", "hearth-2"):
                (run / f"{name}.spec.json").write_text(json.dumps(small_room()), encoding="utf-8")
            # What else a run folder holds, none of it a room.
            (run / "hinged-gate-1.json").write_text("{}", encoding="utf-8")
            (run / "report.json").write_text("[]", encoding="utf-8")
            builds = qa_browser.builds_in(RUN, show_s=4.0, show_for={"hearth": 80.0})
        self.assertEqual([b["id"] for b in builds], [f"{RUN}/hearth-2", f"{RUN}/hinged-gate-1"])
        self.assertEqual([b["show_s"] for b in builds], [80.0, 4.0])
        self.assertEqual(builds[0]["focus_m"], [0.0, 0.16, 0.0])


if __name__ == "__main__":
    unittest.main()
