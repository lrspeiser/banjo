"""The live session layer: what the panel can ask of a running world.

These drive the real engine through the real line protocol -- there is no stub
world here, because the thing worth pinning is that the process on the other end
answers the way the panel assumes it does. What they assert is the contract the
browser depends on: a world opens with the objects that were asked for, stepping
is gravity, a hold is honoured, and a request the engine cannot satisfy comes back
as something a person can read rather than a stack trace.
"""
from pathlib import Path
import sys
import tempfile
import types
import unittest

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
