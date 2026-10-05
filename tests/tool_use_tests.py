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

from copy import deepcopy

import sys
import threading
import time
import unittest
from unittest import mock
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
    def test_transient_native_outcomes_are_private_and_only_visible_during_use(self):
        a={'tool':'alice-tool','point':1,'at_s':2,'open':False}
        b={'tool':'bob-tool','point':2,'at_s':2,'open':False}
        session=SimpleNamespace(tool_busy_players={'alice','bob'},tool_feedback={
            'alice':{(1,2):a},'bob':{(2,2):b}})
        app=SimpleNamespace(live=SimpleNamespace(session=session))
        self.assertEqual([a],tool_use.feedback(app,'alice'))
        self.assertEqual([b],tool_use.feedback(app,'bob'))
        self.assertEqual([],tool_use.feedback(app,'third'))
        session.tool_busy_players.remove('alice')
        self.assertEqual([],tool_use.feedback(app,'alice'))

    def checked(self, use, profile=PICK):
        return interaction_profiles.check(dict(profile, use=use), BODIES, [], points=["pick haft"])

    def test_what_is_left_unsaid_is_the_default(self):
        self.assertEqual(interaction_profiles.tool_use(PICK),
                         {"label": "Dig here", "past": "dug",
                          "gesture":"contact", "cadence_hz":4.0,
                          "swing": {"speed_m_s": 4.0, "raise_deg": 110.0},
                          "lever": {"speed_m_s": 1.2, "lever_deg": 40.0},
                          "reach_m": [0.3, 2.0], "repeat": True})

    def test_contact_reach_defaults_preserve_explicit_limits_and_legacy_swing(self):
        self.assertEqual([.3,2.],interaction_profiles.tool_use(PICK)['reach_m'])
        self.assertEqual([1.15,2.],interaction_profiles.tool_use(dict(PICK,use={'gesture':'swing'}))['reach_m'])
        self.assertEqual([.5,1.],interaction_profiles.tool_use(dict(PICK,use={'reach_m':[.5,1.]}))['reach_m'])

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
    def test_wet_cube_readiness_matches_existing_cell_strike_without_relaxing_smooth_ground(self):
        for surface,materials in [('sand',['sand']),('soil',['soil']),('rock',['rock'])]:
            with self.subTest(surface=surface):
                app=app_with(survey={'surface':surface,'water':{'depth_m':.1}})
                app.live.session.room_spec={'terrain':{'surface':'columns'}}
                answer=tool_use.resolve(app,{'person':PERSON,'at_m':IN_REACH})
                self.assertTrue(answer['feedback']['ready'])
                self.assertEqual(materials,answer['feedback']['materials'])
                self.assertEqual('ok',answer['ring']['state'])
                self.assertFalse(set(app.live.asked)&{'strike-cell','stroke','dig'})
        app=app_with(survey={'water':{'depth_m':.1}})
        app.live.session.room_spec={'terrain':{'surface':'smooth'}}
        self.assertFalse(tool_use.resolve(app,{'person':PERSON,'at_m':IN_REACH})['feedback']['ready'])

    def test_cube_preview_uses_native_cell_depth_for_layers_not_the_point_length(self):
        app=app_with(survey={'surface':'sand','sand_m':.22,'soil_m':.8,'water':{'depth_m':.1}})
        app.live.session.room_spec={'terrain':{'surface':'columns','generate':{'cell_m':.25}}}
        answer=tool_use.resolve(app,{'person':PERSON,'at_m':IN_REACH})
        self.assertEqual(['sand','soil'],answer['feedback']['materials'])
        app.live.session.state['terrain']={'grid':{'cell_m':.125}}
        answer=tool_use.resolve(app,{'person':PERSON,'at_m':IN_REACH})
        self.assertEqual(['sand'],answer['feedback']['materials'])

    def test_compact_feedback_uses_actual_readiness_without_promising_yield(self):
        cases=[(IN_REACH,{},'ready',True,'Dig here',['sand']),
               ([13, .6, -7.38],{},'blocked',False,'Move closer',[]),
               ([13, .6, -4.48],{},'blocked',False,'Step back',[]),
               (IN_REACH,{'holding':None},'tool-needed',False,'Hold a digging tool',[]),
               (IN_REACH,{'survey':{'water':{'depth_m':.1}}},'no-yield',False,'Find loose ground',[]),
               (IN_REACH,{'survey':{'surface':'rock'}},'no-yield',False,'Find loose ground',[])]
        for at,room,state,ready,action,materials in cases:
            with self.subTest(action=action,room=room):
                app=app_with(**room);before=deepcopy(app.live.session.state)
                answer=tool_use.resolve(app,{'person':PERSON,'at_m':at})
                feedback=answer['feedback']
                self.assertEqual((state,ready,action,materials),
                    (feedback['state'],feedback['ready'],feedback['action'],feedback['materials']))
                self.assertEqual(before,app.live.session.state)
                self.assertFalse(set(app.live.asked)&{'stroke','strike','dig'})

    def test_compact_feedback_covers_full_load_detached_and_authored_tools(self):
        from unittest import mock
        app=app_with();app.live.session.state['carried']={'limit_kg':80,'available_kg':0}
        answer=tool_use.resolve(app,{'person':PERSON,'at_m':IN_REACH})['feedback']
        self.assertEqual(('Free load space','inventory',False),(answer['action'],answer['screen'],answer['ready']))
        app=app_with()
        with mock.patch.object(tool_use,'_native_point',return_value=None):
            answer=tool_use.resolve(app,{'person':PERSON,'at_m':IN_REACH})['feedback']
        self.assertEqual(('Inspect tool','inventory',[]),(answer['action'],answer['screen'],answer['materials']))
        app.room.spec['interactions'][0]['object']='Authored spade'
        answer=tool_use.resolve(app,{'person':PERSON,'at_m':IN_REACH})
        self.assertEqual('Authored spade',answer['feedback']['tool'])
        self.assertEqual(['sand'],answer['feedback']['materials'])
        self.assertEqual('sand',answer['target']['material'])

    def test_small_real_yields_are_not_displayed_as_zero_litres(self):
        said=tool_use._said({'kind':'broke out','ground':'soil','depth_m':.02,
            'loosened':{'soil_m3':.00005},'loosened_kg':.08},
            interaction_profiles.tool_use(PICK),.08)
        self.assertIn('50 mL',said)
        self.assertIn('80 g',said)
        self.assertNotIn('0.0 L',said)

    def resolve(self, at, **room):
        return tool_use.resolve(app_with(**room), {"person": PERSON, "at_m": at})

    def test_with_no_tool_in_hand_it_says_to_take_one_up(self):
        said = self.resolve(IN_REACH, holding=None)
        self.assertFalse(said["enabled"])
        self.assertIn("Take up a tool first", said["reason"])

    def test_full_load_refuses_without_starting_a_stroke(self):
        app=app_with()
        app.live.session.state['carried']={'limit_kg':80,'total_kg':80,'available_kg':0,
                                          'sand_kg':78,'objects_kg':2}
        said=tool_use.run(app,{'person':PERSON,'at_m':IN_REACH})
        self.assertIn('Load full',said['refused'])
        self.assertIn('H to heap',said['refused'])
        self.assertEqual([],said['done'])
        self.assertEqual(80,said['carried']['total_kg'])
        self.assertEqual([],app.live.asked)
        app.live.session.state['carried']['available_kg']=1
        self.assertTrue(tool_use.resolve(app,{'person':PERSON,'at_m':IN_REACH})['enabled'])

    def test_with_the_crosshair_off_the_ground_it_says_where_to_point(self):
        said = self.resolve(None)
        self.assertFalse(said["enabled"])
        self.assertIn("Point the crosshair at the ground", said["reason"])
        self.assertEqual(said["label"], "Dig here")

    def test_too_far_and_too_near_say_so_and_the_ring_says_which(self):
        far = self.resolve([13.0, 0.6, -7.38])
        self.assertEqual((far["enabled"], far["ring"]["state"]), (False, "far"))
        self.assertIn("3.0 m away: step closer", far["reason"])
        near = self.resolve([13.0, 0.6, -4.48])
        self.assertEqual((near["enabled"], near["ring"]["state"]), (False, "near"))
        self.assertIn("at your feet", near["reason"])
        # Short-contact handling can work within the old full-swing dead zone.
        close = self.resolve([13.0, 0.6, -5.38])
        self.assertEqual((close["enabled"], close["ring"]["state"]), (True, "ok"))

    def test_in_reach_it_can_be_done_on_the_ground_as_it_is(self):
        said = self.resolve(IN_REACH)
        self.assertTrue(said["enabled"])
        self.assertEqual(said["ring"]["state"], "ok")
        self.assertIsNone(said["reason"])
        self.assertEqual(said["target"]["at_m"], [12.7, 0.6, -5.58], "set on the surveyed ground")
        self.assertEqual(said["target"]["ground"], "sand")

    def test_detached_head_refuses_in_the_target_preview(self):
        from unittest import mock
        app=app_with()
        with mock.patch.object(tool_use,'_native_point',return_value=None):
            said=tool_use.resolve(app,{'person':PERSON,'at_m':IN_REACH})
        self.assertFalse(said['enabled'])
        self.assertEqual(said['ring']['state'],'no')
        self.assertIn('no connected working point',said['reason'])
        self.assertIn('Lab',said['reason'])

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
        profile=room.pop('profile',PICK)
        room['profile']=dict(profile,use={'gesture':'swing',**(profile.get('use') or {})})
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
        app = app_with(meets=False,profile=dict(PICK,use={'gesture':'swing'}))
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


class ObjectControls(unittest.TestCase):
    """Host admission/receipts only; native fixing tests measure the physics."""
    person={**PERSON,'look_direction':[0,0,-1]}
    point={'tip_local':[.1,0,0],'grip_local':[0,-.2,0],'pointing_local':[1,0,0],
           'tip':[13,2.22,-5.82],'pointing':[0,0,-1]}
    hit={'hit':True,'name':'made item','point_m':[13,2.22,-5.88]}

    def app(self, hit=None):
        app=app_with();app.live.requests=[]
        app.live.session.state.update(t=10)
        # This stand-in point is already in the working pose. Give its hand
        # the matching grip; distant pickup readiness is a separate scenario.
        app.live.session.state['hand']['grip_m']=tool_use.tool_gestures.ready_pose(
            self.point,self.hit['point_m'],self.person['eyes_m'],self.person['look_direction'])['hand']
        native=app.live.act
        def act(body):
            app.live.requests.append(body)
            if body['op']=='pick': return self.hit if hit is None else hit
            return native(body)
        app.live.act=act
        return app

    def resolve(self,app,**body):
        return tool_use.resolve(app,{'person':self.person,'target_name':'made item',**body})

    def test_native_recast_ignores_client_point_and_allows_full_bag(self):
        app=self.app();app.live.session.state['carried']={'limit_kg':80,'available_kg':0}
        with mock.patch.object(tool_use,'_native_point',return_value=self.point):
            said=self.resolve(app,at_m=[900,900,900])
        self.assertTrue(said['enabled'])
        self.assertEqual(self.hit['point_m'],said['target']['at_m'])
        self.assertTrue(app.live.requests[0]['past_held'])
        self.assertFalse(said['internal_fracture_supported'])
        self.assertIsNone(said['ring'])

    def test_occluded_stale_malformed_and_out_of_reach_targets_refuse(self):
        for hit,body in [({'hit':False},{}),({**self.hit,'name':'occluder'},{}),
                         (self.hit,{'target_name':['made item']}),
                         ({**self.hit,'point_m':[13,2.22,-7.88]},{}),
                         ({**self.hit,'point_m':[13,2.22,-4.48]},{}),
                         ({**self.hit,'point_m':[13,float('nan'),-5.88]}, {})]:
            with self.subTest(hit=hit,body=body),mock.patch.object(tool_use,'_native_point',return_value=self.point):
                app=self.app(hit);self.assertFalse(self.resolve(app,**body)['enabled'])
                self.assertFalse(any(r['op']=='stroke' for r in app.live.requests))

    def test_disconnected_point_refuses_before_stroke(self):
        app=self.app()
        with mock.patch.object(tool_use,'_native_point',return_value=None):
            said=tool_use.run(app,{'person':self.person,'target_name':'made item'})
        self.assertIn('connected working point',said['refused'])
        self.assertFalse(any(r['op']=='stroke' for r in app.live.requests))

    def test_receipts_repeat_and_cleanup_follow_native_contact_and_connection(self):
        for contact,detach in [(False,False),(True,False),(True,True)]:
            with self.subTest(contact=contact,detach=detach):
                app=self.app();native=app.live.act;count=0
                joint={'id':7,'a':'pick arm','b':'pick haft','attached':True}
                def act(body):
                    nonlocal count
                    if body['op']=='joints':return {'joints':[joint]}
                    if body['op']=='step':return {'ok':True}
                    if body['op']=='stroke':
                        app.live.requests.append(body);count+=1
                        hand=app.live.session.state['hand']
                        hand.update(stroking=False,stroke_ended='reached',work_j=-.5)
                        reply={'t':10.125,'impacts':[{'struck':'made item','by':'pick arm'}] if contact else []}
                        if detach:
                            joint.update(attached=False,parted_because='shear exceeded declared capacity')
                            reply['joints']=[joint]
                        for listener in list(app.reply_listeners):listener(app.live.session,reply)
                        return {'ok':True,'stroking':True}
                    return native(body)
                app.live.act=act
                def point(*args):return None if detach and count else self.point
                with mock.patch.object(tool_use,'_native_point',side_effect=point):
                    said=tool_use.run(app,{'person':self.person,'target_name':'made item'})
                self.assertEqual(bool(contact and not detach),said['repeat'])
                # Draw back, strike, withdraw; a head that came off on the
                # first stroke stops the rest.
                self.assertEqual(1 if detach else 3,count,'a detached head stops further tool strokes')
                self.assertEqual(-.5,said['result']['hand_work_j'],'signed native work is retained')
                self.assertEqual(1 if detach else 0,len(said['result']['parted_joints']))
                self.assertEqual('tool-connection-failed' if detach else 'contact-only' if contact else 'no-contact',
                                 said['result']['outcome'])
                self.assertEqual([7] if detach else [],said['result']['tool_connections_failed'])
                self.assertEqual([],said['result']['target_connections_failed'])
                self.assertFalse(said['result']['wear_supported'])
                self.assertEqual([],app.reply_listeners)
                self.assertFalse(app.live.session.tool_busy)
                self.assertEqual(0,app.live.session.state['carried']['soil_kg'])
                self.assertEqual(0,app.live.session.state['carried']['sand_kg'])

    def test_exception_removes_both_listeners_and_busy_state(self):
        app=self.app();native=app.live.act
        def act(body):
            if body['op']=='joints':return {'joints':[]}
            if body['op']=='step':raise RuntimeError('native step refused')
            return native(body)
        app.live.act=act
        with mock.patch.object(tool_use,'_native_point',return_value=self.point),self.assertRaisesRegex(RuntimeError,'native step refused'):
            tool_use.run(app,{'person':self.person,'target_name':'made item'})
        self.assertEqual([],app.reply_listeners)
        self.assertFalse(app.live.session.tool_busy)

    def test_repeated_frame_reads_preserve_distinct_contacts_and_downstream_target_failure(self):
        app=self.app();native=app.live.act;count=0
        joints=[{'id':8,'a':'made item','b':'target mount','attached':True},
                {'id':9,'a':'target mount','b':'target foot','attached':True},
                {'id':10,'a':'unrelated','b':'other','attached':True}]
        event={'struck':'made item','by':'pick arm','energy_j':.25}
        def act(body):
            nonlocal count
            if body['op']=='joints':return {'joints':joints}
            if body['op']=='step':return {'ok':True}
            if body['op']=='stroke':
                count+=1
                app.live.session.state['hand'].update(stroking=False,stroke_ended='reached')
                if count==1:
                    joints[1].update(attached=False,parted_because='native downstream shear failure')
                    joints[2].update(attached=False,parted_because='unrelated failure')
                    reply={'t':10.125,'impacts':[event,event],'joints':joints}
                    for _ in range(3):
                        for listener in list(app.reply_listeners):listener(app.live.session,reply)
                    for listener in list(app.reply_listeners):
                        listener(app.live.session,{**reply,'t':10.25})
                return {'ok':True,'stroking':True}
            return native(body)
        app.live.act=act
        with mock.patch.object(tool_use,'_native_point',return_value=self.point):
            answer=tool_use.run(app,{'person':self.person,'target_name':'made item'})
        self.assertEqual(4,len(answer['result']['impacts']))
        self.assertEqual([9],answer['result']['target_connections_failed'])
        self.assertEqual([],answer['result']['tool_connections_failed'])
        self.assertEqual('target-connection-failed',answer['result']['outcome'])
        self.assertEqual([joints[1]],answer['result']['parted_joints'])
        self.assertEqual([],app.reply_listeners)

    def test_grounded_readiness_lifts_before_turning_and_keeps_failure_receipt(self):
        for mode in ('reached','parted','blocked'):
            with self.subTest(mode=mode):
                detach=mode=='parted'
                app=self.app();native=app.live.act;count=0
                app.live.session.state['hand']['grip_m']=[13,.65,-4.9]
                grounded={**self.point,'tip':[13,.62,-4.9]}
                joint={'id':7,'a':'pick arm','b':'pick haft','attached':True}
                def act(body):
                    nonlocal count
                    if body['op']=='joints':return {'joints':[joint]}
                    if body['op']=='step':
                        app.live.requests.append(body);return {'ok':True}
                    if body['op']=='stroke':
                        app.live.requests.append(body);count+=1
                        hand=app.live.session.state['hand']
                        hand.update(grip_m=body['path'][-1],stroking=False,stroke_ended='reached',work_j=-.25)
                        if detach and count==1:
                            joint.update(attached=False,parted_because='native mount load exceeded capacity')
                            for listener in list(app.reply_listeners):
                                listener(app.live.session,{'joints':[joint]})
                        return {'ok':True,'stroking':True}
                    return native(body)
                app.live.act=act
                def point(*args):
                    if detach and count:return None
                    return grounded if count==0 or mode=='blocked' else self.point
                with mock.patch.object(tool_use,'_native_point',side_effect=point):
                    answer=tool_use.run(app,{'person':self.person,'target_name':'made item'})
                actions=[r for r in app.live.requests if r['op'] in ('stroke','step')]
                self.assertEqual('stroke',actions[0]['op'],'do not turn the wrist against the floor')
                self.assertEqual([13,1.25,-4.9],actions[0]['path'][-1])
                if detach:
                    self.assertEqual(1,count)
                    self.assertEqual('lift',answer['result']['phase'])
                    self.assertEqual(-.25,answer['result']['hand_work_j'])
                    self.assertEqual([joint],answer['result']['parted_joints'])
                    self.assertEqual([],answer['result']['impacts'])
                    self.assertEqual([],answer['did'])
                    self.assertFalse(answer['repeat'])
                    self.assertIn('lifting',answer['refused'])
                elif mode=='blocked':
                    self.assertEqual(1,count)
                    self.assertEqual('lift',answer['result']['phase'])
                    self.assertIn('cannot lift clear',answer['refused'])
                    self.assertFalse(any(r['op']=='step' for r in actions))
                else:
                    self.assertNotIn('refused',answer)
                self.assertEqual([],app.reply_listeners)
                self.assertFalse(app.live.session.tool_busy)

    def test_object_ready_pose_points_at_contact_including_vertical_rays(self):
        import tool_gestures as gestures
        for direction in ([0,0,-1],[0,-1,0],[0,1,0],[1,0,0]):
            ready=gestures.ready_pose(self.point,[1,2,3],[1,4,3],direction)
            frame=gestures.local_frame([1-gestures.CLEARANCE_M*direction[0],
                2-gestures.CLEARANCE_M*direction[1],3-gestures.CLEARANCE_M*direction[2]],
                ready['hand'],direction,ready['hand'],ready['hand_q'])
            for got,want in zip(frame['pointing_local'],self.point['pointing_local']):
                self.assertAlmostEqual(got,want,places=10)
            for got,want in zip(frame['tip_local'],[a-b for a,b in zip(self.point['tip_local'],self.point['grip_local'])]):
                self.assertAlmostEqual(got,want,places=10)

    def test_native_frame_uses_actual_hand_grip_for_single_and_joined_tools(self):
        for body in ('pick haft','pick arm'):
            app=self.app();app.live.session.state['hand']['grip_m']=[1.2,2,3]
            point={'body':body,'grip_body':'pick haft','attached':True,'grip_connected':True,
                   'tip':[1.4,2,3],'grip':[1.1,2,3],'pointing':[0,0,-1]}
            def act(request):
                if request['op']=='tool_points':return {'tool_points':[point]}
                if request['op']=='poses':return {'bodies':[{'name':'pick haft',
                    'position_m':[1,2,3],'orientation_wxyz':[1,0,0,0]}]}
                self.fail('unexpected command '+request['op'])
            app.live.act=act
            actual=tool_use._native_point(app,'pick haft')
            for got,want in zip(actual['grip_local'],[.2,0,0]):self.assertAlmostEqual(got,want,places=12)
            for got,want in zip(actual['tip_local'],[.4,0,0]):self.assertAlmostEqual(got,want,places=12)
            self.assertEqual([0,0,-1],actual['pointing_local'])


if __name__ == "__main__":
    unittest.main()
