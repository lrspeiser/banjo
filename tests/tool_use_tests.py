"""Using a tool, the same way for every tool (playground/tool_use.py), and how a
tool's profile may shape it (mcp/interaction_profiles.py, `use`).

    python tests/tool_use_tests.py -v

The server says what the tool in the person's hand does where they look -- its
action, whether it can be done there and why not, and the ring the page draws
-- and does it with the bounded hand. These hold a stand-in for the running
room that plays the engine's part: a stroke goes, the ground's record of the
meeting comes over in the replies while it does -- and once the point is out,
in exactly ONE reply, as the engine sends it before forgetting it -- and the
stroke ends. No engine and no model.

Measured with the pick in the page before this: E took it up only with the
crosshair exactly on its 4 cm haft, a second click with the point in the ground
dropped it, and a use that read the room's list after the pry said "it is still
in" when the pry had broken out 5 L.
"""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))
sys.path.insert(0, str(ROOT / "mcp"))

import interaction_profiles  # noqa: E402
import tool_use  # noqa: E402

PICK = {"object": "the pick", "template": "swing-and-lever", "parts": ["pick haft", "pick arm"],
        "tool": "pick haft"}
BODIES = {"pick haft", "pick arm"}
PERSON = {"standing_m": [13.0, 0.6, -4.38], "facing": [0.0, 0.0, -1.0],
          "eyes_m": [13.0, 2.22, -4.38]}
IN_REACH = [12.7, 0.9, -5.58]            # 1.24 m ahead, given 0.3 m above the ground
SOIL = {"on_the_ground": True, "ground_m": 0.6, "rock_top_m": -0.5, "surface": "sand",
        "water": None}


class StandInRoom:
    """The running room, as far as a tool's use goes: a stroke is under way for a
    moment and then ends; while it goes the replies carry the ground's record of
    the point meeting the ground to whoever listens (app.reply_listeners) -- open
    while the point is in, and closed in exactly ONE reply once it is out. Asked
    for its list afterwards, it has only what is still open, as the engine does."""

    def __init__(self, app, survey=None, point_in=False, loosened_m3=0.005, meets=True,
                 holding="pick haft"):
        self.app = app
        self.survey = dict(SOIL, **(survey or {}))
        self.point_in = point_in
        self.loosened_m3 = loosened_m3
        self.meets = meets
        self.asked: list[str] = []
        self.t = 10.0
        self.record = None
        self.session = SimpleNamespace(
            id="s1", tool_busy=False,
            state={"hand": {"holding": holding, "grip_m": [13.1, 1.7, -4.9]},
                   "bodies": [{"name": "pick haft", "velocity_m_s": [0.0, 0.0, 0.0]}],
                   "carried": {"sand_kg": 0.0, "soil_kg": 0.0}})

    def act(self, body):
        op = body["op"]
        self.asked.append(("lever" if body.get("lever") else "strike") if op == "strike" else op)
        if op == "survey":
            return {"ok": True, "survey": dict(self.survey)}
        if op == "tool_points":
            return {"tool_points": [{"body": "pick haft", "in": "sand" if self.point_in else "",
                                     "depth_m": 0.1 if self.point_in else 0.0}]}
        if op == "ground_work":
            return {"ground_work": [dict(self.record)] if self.record else [],
                    "carried": self.session.state["carried"]}
        if op == "strike" and not body.get("lever"):
            self.t += 0.1
            if self.meets:
                self.record = {"tool": "pick haft", "point": 1, "at_s": self.t + 0.2,
                               "kind": "in the ground", "open": True, "ground": "sand",
                               "depth_m": 0.12, "closing_speed_m_s": 9.2, "work_j": 15.9,
                               "peak_force_n": 166.0}
            self._goes([dict(self.record)] if self.record else [])
            return {"ok": True, "striking": True, "t": self.t}
        if op == "strike":          # the pry: still in, broken out sideways
            self.record = dict(self.record, kind="broke out", sideways_m=0.05)
            self._goes([dict(self.record)])
            return {"ok": True, "striking": True, "t": self.t}
        if op == "stroke":          # drawn out: over, said in one reply, then forgotten
            closed = dict(self.record or {"tool": "pick haft", "point": 1, "at_s": self.t,
                                          "kind": "broke out", "ground": "sand", "depth_m": 0.1},
                          open=False, loosened={"sand_m3": self.loosened_m3},
                          loosened_kg=1600.0 * self.loosened_m3)
            self.record = None
            self.point_in = False
            self.session.state["carried"] = {"sand_kg": 1600.0 * self.loosened_m3, "soil_kg": 0.0}
            self._goes([closed])
            return {"ok": True, "stroking": True, "t": self.t}
        raise AssertionError(f"not an op a tool's use asks for: {op}")

    def _goes(self, records):
        hand = self.session.state["hand"]
        hand.update(stroking=True, stroke_ended=None)

        def later():
            time.sleep(0.1)
            for listener in list(self.app.reply_listeners):
                listener(self.session, {"ground_work": records})
            hand.update(stroking=False, stroke_ended="reached")
        threading.Thread(target=later, daemon=True).start()


def app_with(profile=PICK, **room):
    app = SimpleNamespace(reply_listeners=[],
                          room=SimpleNamespace(spec={"interactions": [dict(profile)]}))
    app.live = StandInRoom(app, **room)
    return app


class AToolsUseIsShapedByItsProfile(unittest.TestCase):
    def checked(self, use, profile=PICK):
        return interaction_profiles.check(dict(profile, use=use), BODIES, [], points=["pick haft"])

    def test_what_is_left_unsaid_is_the_default(self):
        self.assertEqual(interaction_profiles.tool_use(PICK),
                         {"label": "Dig here", "past": "dug",
                          "swing": {"speed_m_s": 4.0, "raise_deg": 110.0},
                          "lever": {"speed_m_s": 1.2, "lever_deg": 40.0},
                          "reach_m": [1.15, 2.0], "repeat": True})

    def test_only_what_was_said_is_kept(self):
        out = self.checked({"label": "Break up the soil", "swing": {"raise_deg": 140}})
        self.assertEqual(out["use"], {"label": "Break up the soil", "swing": {"raise_deg": 140.0}})
        use = interaction_profiles.tool_use(out)
        self.assertEqual(use["swing"], {"speed_m_s": 4.0, "raise_deg": 140.0})
        self.assertEqual(use["label"], "Break up the soil")

    def test_the_hands_bounds_are_held(self):
        # 6 m/s: in the live room the tool lagged the swing and stopped short.
        for use, said in (({"swing": {"speed_m_s": 6}}, "1 to 5"),
                          ({"lever": {"lever_deg": 90}}, "5 to 80"),
                          ({"reach_m": [0.2, 2.5]}, "0.3 and 2"),
                          ({"label": ""}, "a few words"),
                          ({"colour": "red"}, "may say"),
                          ({"pry": "no"}, "true or false"),
                          ({"swing": {"force_n": 800}}, "raise_deg, speed_m_s")):
            with self.subTest(use=use), self.assertRaisesRegex(ValueError, said):
                self.checked(use)

    def test_a_tool_only_swung_is_never_pried(self):
        self.assertIsNone(interaction_profiles.tool_use(self.checked({"pry": False}))["lever"])

    def test_a_bow_has_no_use(self):
        bow = {"object": "the bow", "template": "draw-and-release", "parts": ["pick haft"]}
        with self.assertRaisesRegex(ValueError, "not part of a draw-and-release"):
            interaction_profiles.check(dict(bow, use={"label": "Shoot"}), BODIES, [])


class WhatAToolDoesWhereYouLook(unittest.TestCase):
    def resolve(self, at, **room):
        return tool_use.resolve(app_with(**room), {"person": PERSON, "at_m": at})

    def test_with_no_tool_in_hand_it_says_to_take_one_up(self):
        said = self.resolve(IN_REACH, holding=None)
        self.assertFalse(said["enabled"])
        self.assertIn("Take up a tool first", said["reason"])

    def test_with_the_crosshair_off_the_ground_it_says_where_to_point(self):
        said = self.resolve(None)
        self.assertFalse(said["enabled"])
        self.assertIn("Point the crosshair at the ground", said["reason"])
        self.assertEqual(said["label"], "Dig here")

    def test_too_far_and_too_near_say_so_and_the_ring_says_which(self):
        far = self.resolve([13.0, 0.6, -7.38])
        self.assertEqual((far["enabled"], far["ring"]["state"]), (False, "far"))
        self.assertIn("3.0 m away: step closer", far["reason"])
        near = self.resolve([13.0, 0.6, -4.7])
        self.assertEqual((near["enabled"], near["ring"]["state"]), (False, "near"))
        self.assertIn("at your feet", near["reason"])
        # A metre in front is in reach of the arm, and a swing there came down
        # short one time in several: step back.
        close = self.resolve([13.0, 0.6, -5.38])
        self.assertEqual((close["enabled"], close["ring"]["state"]), (False, "near"))
        self.assertIn("1.0 m in front of you, too close", close["reason"])

    def test_in_reach_it_can_be_done_on_the_ground_as_it_is(self):
        said = self.resolve(IN_REACH)
        self.assertTrue(said["enabled"])
        self.assertEqual(said["ring"]["state"], "ok")
        self.assertIsNone(said["reason"])
        self.assertEqual(said["target"]["at_m"], [12.7, 0.6, -5.58], "set on the surveyed ground")
        self.assertEqual(said["target"]["ground"], "sand")

    def test_bare_rock_and_wet_ground_may_be_tried_and_the_ring_warns(self):
        for survey, why in (({"surface": "rock"}, "Bare rock"),
                            ({"rock_top_m": 0.595}, "Bare rock"),
                            ({"water": {"depth_m": 0.1}}, "Under water")):
            with self.subTest(survey=survey):
                said = self.resolve(IN_REACH, survey=survey)
                self.assertTrue(said["enabled"], "the engine says what happens there")
                self.assertEqual(said["ring"]["state"], "warn")
                self.assertIn(why, said["reason"])

    def test_off_the_ground_there_is_nothing_to_work(self):
        said = self.resolve(IN_REACH, survey={"on_the_ground": False})
        self.assertEqual((said["enabled"], said["ring"]["state"]), (False, "no"))

    def test_the_label_and_the_reach_are_the_profiles(self):
        mattock = dict(PICK, use={"label": "Break up the soil", "reach_m": [0.5, 1.0]})
        said = self.resolve(IN_REACH, profile=mattock)
        self.assertEqual(said["label"], "Break up the soil")
        self.assertEqual(said["ring"]["state"], "far", "1.24 m is past this one's 1 m")


class OneUseIsTheWholeOfIt(unittest.TestCase):
    def run_it(self, at=IN_REACH, **room):
        app = app_with(**room)
        noted = []
        said = tool_use.run(app, {"person": PERSON, "at_m": at}, note=lambda _app, a: noted.append(a))
        return app, said, noted

    def test_swung_pried_drawn_out_and_said_from_the_record_that_closed(self):
        app, said, noted = self.run_it()
        self.assertEqual([op for op in app.live.asked if op in ("strike", "lever", "stroke")],
                         ["strike", "lever", "stroke"])
        # The record closed in one reply, after which the room's own list is
        # empty: read from that list, this said "it is still in".
        self.assertEqual(said["said"], "Dug: 5.0 L of sand (8.0 kg) came loose; the point went 12 cm "
                                       "in. You carry 8.0 kg of ground; H heaps it.")
        self.assertIn("It arrived at 9.2 m/s", said["detail"])
        self.assertEqual(said["did"], ["Dig here"])
        self.assertEqual(len(noted), 1, "the swing is credited to the notebook once")
        self.assertEqual(app.reply_listeners, [], "it stops listening when it is done")
        self.assertFalse(app.live.session.tool_busy)

    def test_a_tool_only_swung_is_drawn_out_without_a_pry(self):
        stake = dict(PICK, use={"label": "Drive it in", "pry": False})
        app, said, _ = self.run_it(profile=stake, loosened_m3=0.0)
        self.assertNotIn("lever", app.live.asked)
        self.assertEqual(said["said"], "The point went 12 cm into the sand, and came out without "
                                       "breaking any loose.")
        self.assertEqual(said["did"], ["Drive it in"])

    def test_out_of_reach_nothing_is_swung(self):
        app, said, noted = self.run_it(at=[13.0, 0.6, -7.38])
        self.assertIn("step closer", said["refused"])
        self.assertNotIn("strike", app.live.asked)
        self.assertEqual(noted, [])

    def test_a_hand_still_busy_refuses_another(self):
        app = app_with()
        app.live.session.tool_busy = True
        said = tool_use.run(app, {"person": PERSON, "at_m": IN_REACH})
        self.assertIn("busy", said["refused"])
        self.assertNotIn("strike", app.live.asked)

    def test_a_point_left_in_the_ground_is_drawn_out_first(self):
        app, said, _ = self.run_it(point_in=True)
        moves = [op for op in app.live.asked if op in ("strike", "lever", "stroke")]
        self.assertEqual(moves[:2], ["stroke", "strike"], "drawn out, then swung")
        self.assertTrue(said["done"][0].startswith("drew it out of the ground first"), said["done"])

    def test_a_swing_that_meets_no_ground_says_so(self):
        _, said, _ = self.run_it(meets=False)
        self.assertEqual(said["said"], "The swing met no ground.")

    def test_a_swing_that_stops_short_says_where_its_point_ended(self):
        # Measured in the page: from 1.1 m, a point that ended 7 mm above the
        # ground and 4 cm before the aim was said to have "met no ground".
        app = app_with(meets=False)
        room = app.live
        asked = room.act

        def act(body):
            if body["op"] == "tool_points":
                return {"tool_points": [{"body": "pick haft", "in": "", "depth_m": 0.0,
                                         "tip": [12.74, 0.607, -5.58]}]}
            return asked(body)
        room.act = act
        said = tool_use.run(app, {"person": PERSON, "at_m": IN_REACH})
        self.assertEqual(said["said"], "The swing stopped short: its point ended 7 mm above the "
                                       "ground, 4 cm from where you aimed. Step back a little and "
                                       "swing again.")


if __name__ == "__main__":
    unittest.main()
