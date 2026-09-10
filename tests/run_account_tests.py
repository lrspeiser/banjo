"""The run account: what a scene did, measured, in the names the request used.

These use synthetic recordings rather than real ones so each case states exactly
one fact. The contract being pinned is that the account is arithmetic -- the same
recording always produces the same sentences, it never claims a contact it did not
measure, and a scene that did nothing reads differently from one that did what was
asked. That difference is the whole point: the chat used to say "0 bonds broken"
either way.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))
import run_account


def playback(paths, *, phases=None, fracture_at=None, cell_m=0.02, ground_y=0.0):
    """paths: {"name (material)": [(t, [x,y,z]), ...]} -> a banjo.playback.v1 doc."""
    bodies, frames = [], []
    times = sorted({t for path in paths.values() for t, _ in path})
    for index, name in enumerate(paths):
        bodies.append({"id": f"cell:{index}", "material_id": name, "object_id": 100 + index,
                       "shape": "box", "dimensions_m": [cell_m] * 3})
    for step, t in enumerate(times):
        poses = []
        for index, (name, path) in enumerate(paths.items()):
            at = dict(path).get(t)
            if at is None:
                continue
            poses.append({"id": f"cell:{index}", "position_m": list(at),
                          "orientation_wxyz": [1, 0, 0, 0], "component_id": 0})
        frames.append({"time_s": t, "phase": (phases or {}).get(t, "rigid"), "poses": poses,
                       "bonds": [], "fracture_count": 1 if t == fracture_at else 0})
    return {"schema": "banjo.playback.v1", "bodies": bodies, "frames": frames,
            "supports": [[[-1, ground_y, -1], [1, ground_y, -1], [1, ground_y, 1]]]}


def report(broken=0, max_damage=0.0, components=1, ratio=0.5, cell_m=0.02):
    return {"measurements": {"cell_size_m": cell_m, "realtime_ratio": ratio,
                             "handoff": {"components": components},
                             "lattice": {"broken_bonds": broken, "max_damage": max_damage}}}


def lines(doc, rep, spec=None):
    return run_account.account(doc, rep, spec)["lines"]


class Account(unittest.TestCase):
    def test_a_body_that_never_moves_says_so(self):
        doc = playback({"ramp (oak)": [(0.0, [0, 1, 0]), (1.0, [0, 1, 0])]})
        self.assertIn("ramp (oak): did not move", lines(doc, report())[0])

    def test_anchored_is_named_when_the_spec_says_so(self):
        doc = playback({"ramp (oak)": [(0.0, [0, 1, 0]), (1.0, [0, 1, 0])]})
        spec = {"bodies": [{"name": "ramp", "material": "oak", "anchored": True,
                            "velocity_m_s": [0, 0, 0]}]}
        self.assertIn("(anchored)", lines(doc, report(), spec)[0])

    def test_a_ball_that_rolls_and_stops_reports_both(self):
        path = [(0.0, [0, 1, 0]), (0.5, [1.0, 1, 0]), (1.0, [2.0, 1, 0]),
                (1.5, [2.0, 1, 0]), (2.0, [2.0, 1, 0])]
        doc = playback({"ball (iron)": path})
        line = lines(doc, report())[0]
        self.assertIn("moved 2.00 m (+x)", line)
        self.assertIn("came to rest", line)

    def test_a_ball_still_going_is_not_called_at_rest(self):
        path = [(0.0, [0, 1, 0]), (0.5, [1, 1, 0]), (1.0, [2, 1, 0]), (1.5, [3, 1, 0])]
        line = lines(playback({"ball (iron)": path}), report())[0]
        self.assertIn("still moving at 2.0 m/s", line)
        self.assertNotIn("came to rest", line)

    def test_a_body_that_leaves_the_world_is_reported_as_gone(self):
        path = [(0.0, [0, 1, 0]), (0.5, [1, -0.5, 0]), (1.0, [2, -6.0, 0])]
        line = lines(playback({"ball (iron)": path}), report())[0]
        self.assertIn("fell out of the scene at t=1.00 s", line)

    def test_ten_pins_become_one_line(self):
        paths = {"lane (oak)": [(0.0, [0, 0, 0]), (1.0, [0, 0, 0])]}
        for n in range(1, 11):
            paths[f"pin{n} (glass)"] = [(0.0, [n * 0.1, 1, 0]), (1.0, [n * 0.1 + 0.5, 1, 0])]
        out = lines(playback(paths), report())
        pin_lines = [line for line in out if line.startswith("pin")]
        self.assertEqual(len(pin_lines), 1, out)
        self.assertIn("x10", pin_lines[0])

    def test_breaking_is_reported_with_when(self):
        doc = playback({"plate (glass)": [(0.0, [0, 1, 0]), (0.01, [0, 1, 0])]},
                       phases={0.0: "lattice", 0.01: "lattice"}, fracture_at=0.01)
        out = lines(doc, report(broken=416, components=33))
        self.assertTrue(any(line.startswith("BROKE: 416 bonds into 33 pieces") for line in out), out)
        self.assertFalse(any("NOTHING BROKE" in line for line in out), out)

    def test_nothing_broke_explains_the_window_when_the_action_came_later(self):
        doc = playback({"lane (oak)": [(0.0, [0, 0, 0]), (0.5, [0, 0, 0])],
                        "pin1 (glass)": [(0.0, [1, 1, 0]), (0.5, [2, 1, 0])]},
                       phases={0.0: "lattice"})
        out = lines(doc, report())
        self.assertTrue(any("NOTHING BROKE" in line for line in out), out)
        self.assertTrue(any("lattice window" in line for line in out), out)

    def test_a_contact_is_only_claimed_when_the_recording_has_one(self):
        """Contacts are read from Jolt's callbacks, never inferred. A recording
        with no contact list must produce no impact claim, however suggestive
        the trajectories are -- inferring hits from centre distance gets
        visibly wrong answers and this channel exists to be trusted."""
        doc = playback({"lane (oak)": [(0.0, [0, 0, 0]), (0.5, [0, 0, 0])],
                        "ball (iron)": [(0.0, [0, 0.05, 0]), (0.5, [1, 0.05, 0])]})
        joined = " ".join(lines(doc, report())).lower()
        for verb in ("hit ", "struck", "collided", "reached "):
            self.assertNotIn(verb, joined)

    def test_recorded_impacts_are_reported_hardest_first(self):
        doc = playback({"ball (iron)": [(0.0, [0, 1, 0]), (1.0, [2, 1, 0])]})
        doc["contacts"] = [
            {"a": "ball (iron)", "b": "pin1 (glass)", "first_time_s": 0.20,
             "peak_closing_speed_m_s": 6.97, "peak_impulse_n_s": 3.75,
             "peak_energy_j": 1.0, "events": 2},
            {"a": "pin1 (glass)", "b": "pin5 (glass)", "first_time_s": 0.22,
             "peak_closing_speed_m_s": 8.22, "peak_impulse_n_s": 2.82,
             "peak_energy_j": 1.0, "events": 2},
        ]
        out = lines(doc, report())
        impacts = [line for line in out if " hit " in line]
        self.assertEqual(len(impacts), 2, out)
        self.assertIn("pin1 (glass) hit pin5 (glass)", impacts[0])
        self.assertIn("8.2 m/s", impacts[0])

    def test_things_resting_on_each_other_are_not_impacts(self):
        doc = playback({"ball (iron)": [(0.0, [0, 1, 0]), (1.0, [0, 1, 0])]})
        doc["contacts"] = [
            {"a": "ball (iron)", "b": "lane (oak)", "first_time_s": 0.004,
             "peak_closing_speed_m_s": 0.05, "peak_impulse_n_s": 0.1,
             "peak_energy_j": 0.0, "events": 1},
        ]
        out = lines(doc, report())
        self.assertFalse(any(" hit " in line for line in out), out)
        self.assertTrue(any("nothing struck anything" in line for line in out), out)

    def test_the_cost_is_reported_against_the_gate(self):
        doc = playback({"ball (iron)": [(0.0, [0, 1, 0]), (1.0, [0, 1, 0])]})
        self.assertIn("inside the 1.1x limit", " ".join(lines(doc, report(ratio=0.5))))
        self.assertIn("OVER the 1.1x limit", " ".join(lines(doc, report(ratio=2.8))))

    def test_the_same_recording_always_gives_the_same_account(self):
        doc = playback({"ball (iron)": [(0.0, [0, 1, 0]), (0.5, [1, 1, 0]), (1.0, [2, 1, 0])],
                        "ramp (oak)": [(0.0, [0, 0, 0]), (0.5, [0, 0, 0]), (1.0, [0, 0, 0])]})
        first = lines(doc, report())
        for _ in range(3):
            self.assertEqual(lines(doc, report()), first)

    def test_an_empty_recording_does_not_raise(self):
        run_account.account({"bodies": [], "frames": []}, report())


if __name__ == "__main__":
    unittest.main(verbosity=2)
