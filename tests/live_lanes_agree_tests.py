"""Two ways to hold a world, asked to prove they are the same world.

The playground can drive a live scene through a subprocess speaking the line
protocol, or through the C library loaded into the server. Claiming they are
interchangeable is easy; the only honest way to say it is to run both against
the same scene, step for step, and compare what comes back.

Measured, rather than assumed: each lane on its own is exactly reproducible --
two runs of the same lane put a dropped ball in the same place to the last bit
printed -- and the two lanes agree with each other to about two micrometres,
which is a hundredth of a cell. The residue is the parallel lattice backend
summing contributions in whatever order its threads happen to finish, and two
processes do not thread identically.

Two micrometres does not stay two micrometres. A ball that bounces off the edge
of a pane is a chaotic sequence of contacts, and it will amplify that into
millimetres within a second -- which is a property of bouncing, not of the
boundary. So the comparisons below are made where the answer is stable: at rest,
or while motion is smooth. Comparing two worlds in the middle of a bounce
measures chaos and calls it a bug, which is what the first version of this file
did.

One real difference did turn up here, and it is about batching rather than
physics. Asking the subprocess for four steps gets fewer when one of them is
taken back: the line protocol stops the batch so the host can decide about the
break before time moves again. `banjo_advance` answers the break itself and
finishes the batch. Both are right for what they are, but it means the two lanes
are NOT at the same clock after the same number of calls -- so everything below
drives each lane to a target time and compares there, rather than counting
calls and assuming the clocks match.
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))

import fracture_lab          # noqa: E402
import live_inprocess        # noqa: E402
import live_session          # noqa: E402

ENGINE = next((p for p in [
    ROOT / "build/integration/Release/banjo_live_world_run.exe",
    ROOT / "build/integration/banjo_live_world_run",
    ROOT / "build/Release/banjo_live_world_run.exe",
] if p.is_file()), None)

# How far apart two descriptions of the same world may be. A tenth of a
# millimetre -- fifty times the measured difference between the lanes, and a
# two-hundredth of a cell, so a real divergence has room to be caught while the
# threading residue does not trip it.
TOLERANCE_M = 1.0e-4


def scene() -> dict:
    """The playground's own default, which is measured to break.

    Reaching for a bigger drop does not help: a 40 mm pane lying flat on a
    concrete floor is so well supported that a 4 m drop arrives at 8.7 m/s
    against a 4.5 m/s threshold and still holds. What breaks glass is a thin
    plate with a span under it, which is exactly what the default scene is --
    a 10 mm plate bridged between two piers, struck at 6.26 m/s, measured at
    eight pieces. It also brings anchored scenery with it, so the comparison
    covers a body that must not move as well as ones that must.
    """
    return fracture_lab.validate(dict(fracture_lab.DEFAULT))


def places(state: dict) -> dict[str, tuple[float, float, float]]:
    return {b["name"]: tuple(b["position_m"]) for b in state["bodies"]}


def speeds(state: dict) -> dict[str, float]:
    return {b["name"]: max(abs(v) for v in b["velocity_m_s"]) for b in state["bodies"]}


def run_to(lane, target_s: float, dt: float = 1 / 120.0) -> dict:
    """Drive one lane until its clock reaches `target_s`, answering any break.

    Counting calls would not do: a batch that meets a break comes back short
    from one lane and complete from the other. The clock is the only thing both
    lanes agree to mean the same by.
    """
    state = lane.send(op="poses")
    guard = 0
    while state["t"] < target_s - 1e-12:
        guard += 1
        if guard > 100000:
            raise AssertionError(f"a lane stopped advancing at t={state['t']:.4f}")
        state = lane.send(op="step", dt=dt, n=1)
        while state.get("breakable"):
            state = lane.send(op="fracture", name=state["breakable"][0], window_s=0.003)
    return state


def compare(case, left: dict, right: dict, when: str) -> None:
    case.assertAlmostEqual(left["t"], right["t"], places=9,
                           msg=f"the clocks differ at {when}")
    a, b = places(left), places(right)
    case.assertEqual(sorted(a), sorted(b), f"the lanes hold different bodies at {when}")
    for name in a:
        for axis, (p, q) in enumerate(zip(a[name], b[name])):
            case.assertAlmostEqual(
                p, q, delta=TOLERANCE_M,
                msg=f"{name} axis {axis} differs by {abs(p - q):.2e} m at {when}")


@unittest.skipUnless(ENGINE, "the subprocess engine is not built")
@unittest.skipUnless(live_inprocess.available()[0],
                     f"the C library is not available: {live_inprocess.available()[1]}")
class TheTwoLanesDescribeTheSameWorld(unittest.TestCase):
    def setUp(self):
        self.spec = scene()
        self.runs = ROOT / "build" / "playground-runs"
        self.runs.mkdir(parents=True, exist_ok=True)

    def lanes(self):
        return (live_session.Session(ENGINE, dict(self.spec), self.runs),
                live_inprocess.InProcessSession(dict(self.spec)))

    def test_they_open_on_the_same_scene(self):
        out, here = self.lanes()
        try:
            self.assertEqual(sorted(places(out.state)), sorted(places(here.state)),
                             "the two lanes opened with different bodies")
            for name, at in places(out.state).items():
                for axis, (a, b) in enumerate(zip(at, places(here.state)[name])):
                    self.assertAlmostEqual(a, b, delta=TOLERANCE_M,
                                           msg=f"{name} axis {axis} differs at t=0")
            self.assertEqual(out.state["cell_size_m"], here.state["cell_size_m"])
        finally:
            out.close(); here.close()

    def test_they_stay_together_through_a_fall_and_a_break(self):
        out, here = self.lanes()
        try:
            # The striker in this scene arrives already moving, 20 mm clear of
            # the plate, so the break is in the first step: there is no quiet
            # fall to compare before it. The opening state is the baseline.
            before = len(places(out.state))
            compare(self, out.state, here.state, "t=0, before anything moves")

            # Through the break and out the far side, to rest.
            for when in (0.5, 1.0):
                compare(self, run_to(out, when), run_to(here, when), f"t={when:.2f} s")
            a, b = run_to(out, 3.0), run_to(here, 3.0)
            self.assertGreater(len(places(a)), before,
                               "nothing broke in the subprocess lane, so this proves nothing")
            self.assertEqual(sorted(places(a)), sorted(places(b)),
                             "the lanes broke the pane into differently named pieces")
            self.assertLess(max(speeds(a).values()), 0.1,
                            "the world is still moving, so this compares trajectories")
            compare(self, a, b, "t=3.00 s, at rest")
        finally:
            out.close(); here.close()

    def test_a_ray_gets_the_same_answer_from_both(self):
        out, here = self.lanes()
        try:
            for frm, direction in ([[0, 3, 0], [0, -1, 0]],
                                   [[0.35, 3, 0], [0, -1, 0]],
                                   [[0, 3, 0], [0, 1, 0]],
                                   [[0, 0.9, 0.6], [0, -0.4, -1]]):
                a = out.send(op="pick", **{"from": frm, "dir": direction})
                b = here.send(op="pick", **{"from": frm, "dir": direction})
                self.assertEqual(a["hit"], b["hit"], f"ray {frm}->{direction}: hit differs")
                self.assertEqual(a["name"], b["name"], f"ray {frm}->{direction}: name differs")
                if a["hit"]:
                    self.assertAlmostEqual(a["distance_m"], b["distance_m"], delta=TOLERANCE_M,
                                           msg=f"ray {frm}->{direction}: distance differs")
        finally:
            out.close(); here.close()

    def test_the_hand_behaves_the_same_in_both(self):
        out, here = self.lanes()
        try:
            for lane in (out, here):
                run_to(lane, 0.4)

            # Whatever can be picked up, asked of the world rather than
            # assumed. Not the sphere by shape: once the plate breaks, the
            # striker is in the island too and comes back as a hull, so looking
            # for a sphere finds nothing. The hand is what is being tested here,
            # not which object is in it.
            ball = next(b["name"] for b in out.state["bodies"] if not b["anchored"])
            for lane in (out, here):
                lane.send(op="grab", name=ball)
                self.assertEqual(lane.state["held"], ball)
                lane.send(op="move", to=[0.1, 1.4, 0.0])
                state = lane.send(op="step", dt=1 / 120.0, n=1)
                at = {b["name"]: b["position_m"] for b in state["bodies"]}[ball]
                self.assertAlmostEqual(at[1], 1.4, places=3, msg="a held ball drifted")
                lane.send(op="release")
                self.assertEqual(lane.state["held"], "")

            # Long enough to be lying still. Stopping while it was still
            # bouncing compared two chaotic trajectories, which differed by
            # 9 mm and said nothing about either lane.
            a, b = run_to(out, 4.0), run_to(here, 4.0)
            fell_out = places(a)[ball][1]
            self.assertLess(fell_out, 1.3, "the ball did not fall after being let go")
            self.assertLess(speeds(a)[ball], 0.05,
                            "the ball is still moving, so this is comparing a "
                            "trajectory rather than a resting place")
            self.assertAlmostEqual(fell_out, places(b)[ball][1], delta=TOLERANCE_M,
                                   msg="the two lanes put it to rest in different places")
        finally:
            out.close(); here.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
