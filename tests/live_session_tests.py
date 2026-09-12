"""The live session layer: what the panel can ask of a running world.

These drive the real engine through the real line protocol -- there is no stub
world here, because the thing worth pinning is that the process on the other end
answers the way the panel assumes it does. What they assert is the contract the
browser depends on: a world opens with the objects that were asked for, stepping
is gravity, a hold is honoured, and a request the engine cannot satisfy comes back
as something a person can read rather than a stack trace.
"""
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))
import fracture_lab  # noqa: E402
import live_session  # noqa: E402

ENGINE = ROOT / "build" / "integration" / "Release" / "banjo_platform_cli.exe"


def scene(**changes):
    spec = {
        "algorithm": "lattice",
        "cell_m": 0.02,
        "duration_s": 1.0,
        "bodies": [
            {"name": "floor", "shape": "box", "material": "oak",
             "size_mm": [600, 40, 400], "center_mm": [0, 20, 0], "anchored": True},
            {"name": "ball", "shape": "sphere", "material": "iron",
             "size_mm": [100, 100, 100], "center_mm": [0, 600, 0]},
        ],
    }
    spec.update(changes)
    return spec


class LiveSession(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ENGINE.is_file():
            raise unittest.SkipTest(f"{ENGINE.name} is not built")
        cls._temp = tempfile.TemporaryDirectory()
        cls.app = types.SimpleNamespace(engine_path=ENGINE,
                                        runs_path=Path(cls._temp.name))

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()

    def setUp(self):
        self.live = live_session.Live()
        self.addCleanup(self.live.shutdown)

    def body(self, state, name):
        for b in state["bodies"]:
            if b["name"] == name:
                return b
        return None

    def test_a_world_opens_with_the_objects_that_were_asked_for(self):
        state = self.live.open(self.app, {"spec": scene()})
        self.assertEqual(len(state["bodies"]), 2, state["bodies"])
        self.assertEqual(self.body(state, "floor")["shape"], "box")
        self.assertEqual(self.body(state, "ball")["shape"], "sphere")
        self.assertTrue(self.body(state, "floor")["anchored"])
        self.assertTrue(state["session"])

    def test_stepping_is_gravity(self):
        state = self.live.open(self.app, {"spec": scene()})
        # open() answers with the session id; act() answers with the world, which
        # does not repeat it.
        session = state["session"]
        started = self.body(state, "ball")["position_m"][1]
        for _ in range(20):
            state = self.live.act({"session": session, "op": "step",
                                   "dt": 1 / 120.0, "n": 12})
        landed = self.body(state, "ball")["position_m"][1]
        self.assertLess(landed, started - 0.2, "the ball did not fall")
        self.assertGreater(landed, 0.04, "the ball fell through the floor")

    def test_a_held_object_goes_where_it_is_put(self):
        state = self.live.open(self.app, {"spec": scene()})
        session = state["session"]
        self.live.act({"session": session, "op": "grab", "name": "ball"})
        state = self.live.act({"session": session, "op": "move", "to": [0.1, 1.4, 0.0]})
        self.assertEqual(state["held"], "ball")
        for _ in range(10):
            state = self.live.act({"session": session, "op": "step",
                                   "dt": 1 / 120.0, "n": 12})
        at = self.body(state, "ball")["position_m"]
        self.assertAlmostEqual(at[1], 1.4, places=2, msg="a held ball drifted")
        self.assertAlmostEqual(at[0], 0.1, places=2, msg="a held ball did not go where it was put")
        state = self.live.act({"session": session, "op": "release"})
        self.assertEqual(state["held"], "")

    def test_anchored_scenery_cannot_be_picked_up(self):
        state = self.live.open(self.app, {"spec": scene()})
        with self.assertRaises(live_session.LiveError) as caught:
            self.live.act({"session": state["session"], "op": "grab", "name": "floor"})
        self.assertIn("cannot be picked up", str(caught.exception))

    def test_the_single_tile_scene_runs_live_too(self):
        """A plate and a ball is a scene of objects, so it opens like any other.

        It used to be refused -- "a live world needs a many-object scene" -- and
        that refusal was the playground's default scene, so the first thing
        anyone saw was a message telling them to go and pick a different one.
        The same physics written in different words is still the same physics:
        the plate is a panel, the striker is a ball above it, and ledges are two
        anchored piers.
        """
        spec = dict(fracture_lab.DEFAULT)
        self.assertFalse(spec.get("bodies"), "this test needs the single-tile form")
        state = self.live.open(self.app, {"spec": spec})
        names = [b["name"] for b in state["bodies"]]
        self.assertIn("glass plate", names)
        self.assertIn("iron ball", names)
        self.assertEqual(sum(1 for n in names if n.startswith("pier")), 2,
                         f"the ledges did not become piers: {names}")
        # The striker arrives already moving, because the lane resolves its drop
        # height into a speed rather than simulating the fall.
        ball = self.body(state, "iron ball")
        self.assertLess(ball["velocity_m_s"][1], -6.0,
                        "the striker was parked in mid air instead of being dropped")

    def test_an_empty_request_still_opens_a_world(self):
        """There is no request left that cannot be run.

        A spec is validated before it is opened, and validation fills in every
        default, so a caller who sends nothing gets the default scene rather
        than an error. That is the point of the change: the panel has no state
        it can be in that the live lane will not accept, so it never has to
        explain to the reader why their scene is the wrong kind.
        """
        state = self.live.open(self.app, {"spec": {}})
        self.assertTrue(state["bodies"], "an empty request opened an empty world")
        self.assertIn("glass plate", [b["name"] for b in state["bodies"]])

    def test_a_stale_session_is_refused_clearly(self):
        first = self.live.open(self.app, {"spec": scene()})
        # Opening another closes the first: one physics engine at a time.
        self.live.open(self.app, {"spec": scene()})
        with self.assertRaises(live_session.LiveError) as caught:
            self.live.act({"session": first["session"], "op": "poses"})
        self.assertIn("no longer open", str(caught.exception))

    def test_a_step_is_bounded_however_much_is_asked_for(self):
        state = self.live.open(self.app, {"spec": scene()})
        # A client asking for an hour of simulated time in one call gets the cap,
        # not an hour: the world has to stay answerable between steps.
        state = self.live.act({"session": state["session"], "op": "step",
                               "dt": 1.0, "n": 100000})
        self.assertLessEqual(
            state["t"], live_session.MAX_DT_S * live_session.MAX_STEPS_PER_CALL + 1e-9,
            "a step call ran past its own cap")

    def test_an_unknown_operation_is_named(self):
        state = self.live.open(self.app, {"spec": scene()})
        with self.assertRaises(live_session.LiveError) as caught:
            self.live.act({"session": state["session"], "op": "explode"})
        self.assertIn("explode", str(caught.exception))


# The engine a session actually runs, found next to the one the panel is given.
WORLD = ENGINE.with_name("banjo_live_world_run" + ENGINE.suffix)


def freeze(process):
    """Stop a process where it stands: a hung engine, as far as anyone talking
    to it can tell -- alive, holding its pipes, answering nothing. It is never
    thawed; whatever froze it is killed afterwards."""
    if sys.platform == "win32":
        import ctypes
        status = ctypes.WinDLL("ntdll").NtSuspendProcess(
            ctypes.c_void_p(int(process._handle)))
        if status != 0:
            raise OSError(f"could not suspend the engine (NTSTATUS {status:#x})")
    else:
        os.kill(process.pid, signal.SIGSTOP)


class AWorldClosedUnderACall(unittest.TestCase):
    """Closing a world while a call is inside it.

    The server answers on many threads, so a pick for the old room can be in
    flight at the moment the page opens a new one -- and opening a room closes
    the last. Closing the pipes under that pick turned its answer into
    "OSError: [Errno 22] Invalid argument" from the write, which nothing
    handles: the request died with a traceback in the server's log and the page
    got no answer at all. Whatever the moment, a call has to come back as its
    reply or as a LiveError, which every caller already handles.
    """

    @classmethod
    def setUpClass(cls):
        if not WORLD.is_file():
            raise unittest.SkipTest(f"{WORLD.name} is not built")
        cls._temp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()

    def open(self):
        session = live_session.Session(ENGINE, fracture_lab.validate(scene()),
                                       Path(self._temp.name))
        self.addCleanup(self.bury, session)
        return session

    @staticmethod
    def bury(session):
        """No engine outlives its test, whatever the test did to it."""
        if session._process.poll() is None:
            session._process.kill()
        session._process.wait(timeout=10)
        session._shut()

    @staticmethod
    def pick(session, outcome):
        """The call the page was making when this was found."""
        try:
            outcome["reply"] = session.send(op="pick", **{"from": [0.0, 1.2, 0.0],
                                                         "dir": [0.0, -1.0, 0.0]})
        except BaseException as error:      # anything, so the test can say what
            outcome["error"] = error

    def assertAnsweredOrClosed(self, outcome):
        error = outcome.get("error")
        if error is not None and not isinstance(error, live_session.LiveError):
            self.fail(f"a call to a world being closed came back as "
                      f"{type(error).__name__}: {error}")

    def test_a_call_past_its_check_is_answered_before_the_pipes_close(self):
        """The interleaving in the log, pinned rather than hoped for.

        The pick had checked that the world was up; then the world was closed
        and the engine quit; then the pick wrote its command into a pipe with
        nobody on the other end. The pick is held exactly there -- between the
        check and the write -- and the pipes are kept open until it is done
        with them, so a close that does not wait its turn fails this with the
        very error that was logged, every time.
        """
        session = self.open()
        checked, go, done = threading.Event(), threading.Event(), threading.Event()
        poll, shut = session._process.poll, session._shut

        def held_at_the_check():
            answer = poll()
            if threading.current_thread() is asker and not checked.is_set():
                checked.set()
                go.wait(10)
            return answer

        def shut_once_the_pick_is_done():
            done.wait(10)
            shut()

        session._process.poll = held_at_the_check
        session._shut = shut_once_the_pick_is_done
        outcome: dict = {}

        def ask():
            try:
                self.pick(session, outcome)
            finally:
                done.set()

        asker = threading.Thread(target=ask)
        asker.start()
        self.assertTrue(checked.wait(10), "the pick never reached its check")
        closer = threading.Thread(target=session.close)
        closer.start()
        # Long enough for a close that does not wait its turn to have quit the
        # engine. One that does is still waiting for the pick, and the engine is
        # still up when the pick goes on.
        deadline = time.monotonic() + 1.0
        while session._process.returncode is None and time.monotonic() < deadline:
            time.sleep(0.005)
        go.set()
        asker.join(timeout=20)
        closer.join(timeout=20)
        self.assertFalse(asker.is_alive(), "the pick never came back")
        self.assertFalse(closer.is_alive(), "close() never came back")
        self.assertAnsweredOrClosed(outcome)
        # It was inside before the close began, so it is owed its answer.
        self.assertIn("reply", outcome, f"a pick already under way was cut off: {outcome}")
        self.assertTrue(outcome["reply"].get("ok"), outcome["reply"])
        # And the world is shut behind it.
        with self.assertRaises(live_session.LiveError) as caught:
            session.send(op="poses")
        self.assertIn("has closed", str(caught.exception))
        self.assertIsNotNone(session._process.poll(), "the engine outlived its close")

    def test_a_call_into_a_hung_engine_comes_back_closed(self):
        """The slowest op there is: an engine that will never answer.

        close() waits CLOSE_WAIT_S for the call inside, then kills the engine,
        and the call's read comes back empty. The call must come back as a
        LiveError -- and close() must come back at all, because Live.open holds
        its own lock across it: a close that waited forever on a hung engine
        would take every room with it.
        """
        session = self.open()
        freeze(session._process)
        outcome: dict = {}
        asker = threading.Thread(target=self.pick, args=(session, outcome), daemon=True)
        asker.start()
        # In once it holds the world's lock; from then on it is waiting on an
        # engine that will not answer.
        deadline = time.monotonic() + 10
        while not session._lock.locked() and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertTrue(session._lock.locked(), "the pick never went in")
        with mock.patch.object(live_session, "CLOSE_WAIT_S", 0.5):
            began = time.monotonic()
            closer = threading.Thread(target=session.close, daemon=True)
            closer.start()
            closer.join(timeout=20)
            took = time.monotonic() - began
        asker.join(timeout=20)
        self.assertFalse(closer.is_alive(), "close() never came back from a hung engine")
        self.assertFalse(asker.is_alive(), "the pick stuck in a hung engine never came back")
        self.assertLess(took, 4.0, f"close() took {took:.1f} s to give up on a hung "
                                   f"engine, against a wait of 0.5 s")
        self.assertIn("error", outcome, f"a frozen engine answered: {outcome}")
        self.assertAnsweredOrClosed(outcome)
        self.assertIn("has closed", str(outcome["error"]))

    def test_the_server_answers_a_closed_world_as_a_400_with_the_reason(self):
        """What the page gets.

        LiveError is a ValueError, and the server answers every ValueError as a
        400 carrying the reason, which the page's catch reads. The OSError this
        used to be was answered by nothing: the connection was dropped and the
        traceback went to the log.
        """
        import http.client
        from http.server import ThreadingHTTPServer
        import json
        import server as playground_server

        app = types.SimpleNamespace(csrf_token="token", live=live_session.Live(),
                                    engine_path=ENGINE, runs_path=Path(self._temp.name),
                                    live_inprocess=False)
        self.addCleanup(app.live.shutdown)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), playground_server.Handler)
        httpd.app = app
        serving = threading.Thread(target=httpd.serve_forever, daemon=True)
        serving.start()
        self.addCleanup(serving.join, 3)
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)

        def post(path, body):
            connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port,
                                                    timeout=20)
            try:
                connection.request("POST", path, body=json.dumps(body),
                                   headers={"Content-Type": "application/json",
                                            "X-Banjo-Token": app.csrf_token})
                response = connection.getresponse()
                return response.status, json.loads(response.read() or b"{}")
            finally:
                connection.close()

        status, opened = post("/api/live/open", {"spec": scene()})
        self.assertEqual(status, 200, opened)
        # The close that won the race: the world goes while it is still the
        # current one, so the act gets past the session check and into send().
        app.live.session.close()
        status, answer = post("/api/live/act", {"session": opened["session"], "op": "pick",
                                               "from": [0, 1.2, 0], "dir": [0, -1, 0]})
        self.assertEqual(status, 400, answer)
        self.assertIn("has closed", answer.get("error", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
