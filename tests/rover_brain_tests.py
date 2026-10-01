"""What thinks for the rover, and talking to it (docs/machine-world.md, "What
the rover decides by itself, and who it asks" and "Talking to the rover"):
what is made of Jev's answers, what happens to the rover is noticed, a
decision goes to its program before the next step, and the chat's open, say
and close each work the program -- in the real engine, with a scripted Jev.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tests/rover_brain_tests.py

Without BANJO_LIVE_ENGINE only the checks that need no engine run, unless
BANJO_ROVER_LIVE_TESTS=required, which ctest sets. Nothing here reaches the
network: Jev is a function, or the scripted server in tests/scripted_jev_server.py.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground"), str(ROOT / "tests")]
import live_session, machine_routine, machine_senses, machine_tools, room_store, rover_brain, rover_talk, world_room   # noqa: E402
import scripted_jev_server   # noqa: E402

ENGINE = Path(os.environ["BANJO_LIVE_ENGINE"]).resolve() if os.environ.get("BANJO_LIVE_ENGINE") else None
DT = 1 / 120


def a_program(**changes) -> dict:
    program = {"id": 1, "name": "rover", "kind": "roam", "left": 1, "right": 2, "body": "rover",
               "parts": ["rover", "rover: left wheel", "rover: right wheel"], "setting": 1.0, "climb_deg": 8.0,
               "sensors": [{"kind": "water", "body": "rover", "side": 1, "reading_m": 0.0, "sees": False},
                           {"kind": "water", "body": "rover", "side": -1, "reading_m": 0.0, "sees": False}],
               "power": True, "doing": "going forward", "why": "nothing in its way", "doing_s": 2.0,
               "turned_deg": 0.0, "turns": 0, "pitch_deg": 0.5, "roll_deg": 0.0, "rest_below": 0.25,
               "rest_until": 0.6, "charge_share": 0.8, "rests": 0, "asked": None}
    program.update(changes)
    return program


def sees(program: dict, side: int, mm: float = 12.0, seconds: float = 0.0) -> dict:
    program = deepcopy(program)
    for s in program["sensors"]:
        if s["side"] == side:
            s.update(sees=True, reading_m=mm / 1000.0, seeing_s=seconds)
    return program


def jev_says(pick: str, confidence: float = 0.9):
    """A Jev that always picks the same thing for the rover, sorts what a
    person says by plain words, and remembers what it was asked."""
    asked: list[tuple] = []

    def ask(state, questions):
        asked.append((state, questions))
        if "intent" in questions:
            answers = scripted_jev_server.sensible(state, questions)
            answers["intent"]["confidence"] = confidence
            return answers
        return {"next": {"type": "choice", "choice": pick, "confidence": confidence,
                         "probabilities": {pick: confidence}},
                "arg_for_s": {"type": "score", "score": 0.0},
                "stuck": {"type": "noul", "noul": 0.1},
                "battery": {"type": "score", "score": 0.0,
                            "legend": {"0": "fine: plenty", "1": "low: getting low", "2": "urgent: nearly flat"}}}
    ask.asked = asked
    return ask


class WhatHappensToIt(unittest.TestCase):
    """What is noticed between two readings of the program (situations)."""

    def test_ground_hazards_keep_kind_and_direction_separate_from_water(self):
        before=a_program()
        before['sensors'][0]['sees']=True
        now=deepcopy(before)
        now['sensors'].append({'kind':'ground','side':1,'stops':-1,'reading_m':.5,'depth_m':.12,'sees':True})
        self.assertIn('ground drop/step behind on its left',machine_senses.situations(before,now,None,[]))
        self.assertEqual([],machine_senses.situations(now,now,None,[]))
        now['sensors'][-1]['seeing_s']=machine_senses.STILL_IN_S+1
        self.assertIn('it still sees a ground drop/step and is not getting clear',
                      machine_senses.situations(now,now,None,[]))

    def test_water_seen_is_an_event_once(self):
        before, now = a_program(), sees(a_program(), 1)
        self.assertEqual(["water ahead on its left"], rover_brain.situations(before, now, None, []))
        self.assertEqual([], rover_brain.situations(now, now, None, []))

    def test_a_stalled_wheel_a_slope_a_low_battery_and_a_knock(self):
        machines = {"controls": [{"id": 1, "condition": "stalled: it made no progress, so it stopped"},
                                 {"id": 2, "condition": ""}]}
        self.assertEqual(["its left wheel stalled"], rover_brain.situations(a_program(), a_program(), machines, []))
        steep = a_program(why="the ground here is steeper than it climbs", doing="turning left")
        self.assertEqual(["the ground ahead is steeper than it climbs"],
                         rover_brain.situations(a_program(), steep, None, []))
        low = a_program(charge_share=0.33)
        self.assertEqual(["its battery is getting low: 33%"],
                         rover_brain.situations(a_program(charge_share=0.4), low, None, []))
        knocked = [{"struck": "rover", "by": "boulder", "closing_speed_m_s": 1.234}]
        self.assertEqual(["boulder struck it at 1.2 m/s"], rover_brain.situations(a_program(), a_program(), None, knocked))

    def test_being_still_in_it_is_its_own_event_and_reads_the_same_every_time(self):
        """The one reading that is not an edge.

        Everything else here fires on a change, so a machine that is still in
        the same trouble a minute later says nothing. Measured on the roaming
        rover: one "water ahead on its left", then thirty-nine seconds of
        sliding down the basin into the lake without another word. This is
        what says "and it still is", and it has to read the SAME every time --
        with the seconds in the words a brain would answer each reading as a
        fresh thing rather than as the thing it has not fixed yet.
        """
        still = "it is still in the water and not getting clear"
        under = sees(a_program(), 1, seconds=machine_senses.STILL_IN_S - 0.1)
        self.assertEqual(["water ahead on its left"], rover_brain.situations(a_program(), under, None, []))
        over = sees(a_program(), 1, seconds=machine_senses.STILL_IN_S)
        self.assertIn(still, rover_brain.situations(under, over, None, []))
        longer = sees(a_program(), 1, seconds=90.0)
        self.assertEqual([still], rover_brain.situations(over, longer, None, []))
        # Out of it: the engine zeroes the clock, and it stops being said.
        self.assertEqual([], rover_brain.situations(longer, a_program(), None, []))

    def test_being_still_in_it_is_heard_through_an_ask(self):
        """An ask silences the chatter, not the news that the ask is failing.

        Without this a brain cannot tell a plan that worked from one that did
        not: it is deaf from the moment it says anything until the ask lapses,
        so it gets exactly one try at every situation.
        """
        asked = sees(a_program(asked={"doing": "backing off", "by": "jev"}), 1, seconds=20.0)
        self.assertEqual(["it is still in the water and not getting clear"],
                         rover_brain.situations(a_program(), asked, None, []))

    def test_nothing_is_noticed_while_it_is_off_or_asked(self):
        self.assertEqual([], rover_brain.situations(a_program(), sees(a_program(power=False), 1), None, []))
        asked = sees(a_program(asked={"doing": "waiting", "by": "talk"}), 1)
        self.assertEqual([], rover_brain.situations(a_program(), asked, None, []))
        # A knock is noticed even then: it is not something the ask covers.
        knocked = [{"struck": "rover", "by": "boulder", "closing_speed_m_s": 2.0}]
        self.assertEqual(["boulder struck it at 2.0 m/s"], rover_brain.situations(a_program(), asked, None, knocked))


class WhatIsMadeOfJevsAnswer(unittest.TestCase):
    def test_a_confident_pick_is_an_ask_and_an_unsure_one_is_not(self):
        sure = rover_brain.decide(jev_says("back_off", 0.81)(None, rover_brain.QUESTIONS), "water ahead on its left")
        self.assertEqual({"tool": "back_off", "args": {"for_s": 1.5},
                          "why": "Jev said back off for 1.5 s (81% sure) when water ahead on its left"}, sure["call"])
        self.assertEqual(("back_off", 0.81, 0.1, "fine"), (sure["pick"], sure["confidence"], sure["stuck"], sure["battery"]))
        unsure = rover_brain.decide(jev_says("hold_still", 0.4)(None, rover_brain.QUESTIONS), "x")
        self.assertIsNone(unsure["call"])
        self.assertIn("too unsure", unsure["said"])
        odd = rover_brain.decide({"next": {"choice": "fly", "confidence": 0.99}}, "x")
        self.assertIsNone(odd["call"])
        self.assertIn("no tool it has", odd["said"])

    def test_the_questions_are_the_tools_whoever_answers(self):
        questions = rover_brain.questions_for("roam")
        self.assertEqual([t["name"] for t in machine_tools.catalogue()], list(questions["next"]["criteria"]))
        self.assertIn("dig", questions["next"]["criteria"])
        self.assertEqual({"next", "stuck", "battery", "arg_for_s", "arg_place", "arg_bearing_deg", "arg_distance_m",
                          "arg_depth_m"}, set(questions))
        self.assertIn("a lake", questions["next"]["instructions"])
        # An unknown kind is asked as a rover is, rather than nothing.
        self.assertEqual(questions, rover_brain.questions_for("hunt"))
        # Every argument a decider fills is a typed question in the same call:
        # a duration or a depth a score over its levels, a direction a choice,
        # a place a choice among what the machine knows and the person.
        self.assertEqual("score", questions["arg_for_s"]["type"])
        self.assertEqual(["a moment, a second and a half", "a few seconds, three", "a while, six seconds",
                          "a good while, twelve seconds"], questions["arg_for_s"]["criteria"])
        self.assertEqual("choice", questions["arg_bearing_deg"]["type"])
        self.assertIn("to its left", questions["arg_bearing_deg"]["criteria"])
        self.assertEqual(["person"], list(questions["arg_place"]["criteria"]))
        with_places = rover_brain.questions_for("roam", {"dig site": [1, 2], "depot": [3, 4]})
        self.assertEqual(["dig site", "depot", "person"], list(with_places["arg_place"]["criteria"]))

    def test_the_picked_tools_arguments_are_read_from_the_answers(self):
        answers = {"next": {"choice": "go_to", "confidence": 0.9},
                   "arg_place": {"choice": "depot", "confidence": 0.8},
                   "arg_bearing_deg": {"choice": "to its left", "confidence": 0.5},
                   "arg_distance_m": {"score": 1.2}, "arg_for_s": {"score": 2.6}, "arg_depth_m": {"score": 2.0}}
        places = {"dig site": [1, 2], "depot": [3, 4]}
        self.assertEqual({"place": "depot", "for_s": 12.0}, machine_tools.arguments_for("go_to", answers, places),
                         "a place makes the bearing and distance moot")
        answers["arg_place"] = {"choice": "moon"}
        self.assertEqual({"bearing_deg": 90.0, "distance_m": 3.0, "for_s": 12.0},
                         machine_tools.arguments_for("go_to", answers, places), "a place it does not know is no place")
        self.assertEqual({"depth_m": 0.3}, machine_tools.arguments_for("dig", answers, places))
        self.assertEqual({"for_s": 12.0}, machine_tools.arguments_for("turn_left", answers, places))
        self.assertEqual({}, machine_tools.arguments_for("dump", answers, places))
        self.assertEqual({}, machine_tools.arguments_for("go_to", {"next": {"choice": "go_to"}}, places),
                         "unanswered, the tool's own defaults stand")
        decision = rover_brain.decide(answers, "the person came near", "roam", "Jev", places)
        self.assertEqual({"tool": "go_to", "args": {"bearing_deg": 90.0, "distance_m": 3.0, "for_s": 12.0},
                          "why": "Jev said go to 3 m at +90 deg, for 12 s (90% sure) when the person came near"},
                         decision["call"])
        self.assertEqual("go to the person", machine_tools.described("go_to", {"place": "person"}))
        self.assertEqual("dig 0.3 m deep", machine_tools.described("dig", {"depth_m": 0.3}))

    def test_the_state_a_decider_reads_is_the_senses(self):
        machines = {"controls": [{"id": 1, "condition": "", "speed_rpm": 40.0, "power": True, "direction": 1,
                                  "setting": 1.0}, {"id": 2, "condition": ""}]}
        ctx = machine_senses.Context(program=sees(a_program(), -1), machines=machines,
                                     impacts=[{"struck": "rover: left wheel", "by": "stone", "closing_speed_m_s": 0.5},
                                              {"struck": "pane", "by": "ball", "closing_speed_m_s": 9.0}])
        state = rover_brain.state_of(ctx, "stone struck it", [])
        self.assertEqual("stone struck it", state["event"])
        s = state["senses"]
        self.assertEqual(set(machine_senses.SENSES), set(s), "every sense reads, engine or none")
        self.assertEqual("going forward", s["position"]["doing"])
        self.assertEqual([{"side": "left", "water_under_it_mm": 0, "sees_water": False},
                          {"side": "right", "water_under_it_mm": 12, "sees_water": True}], s["water"]["sensors"])
        self.assertIsNone(s["water"]["nearest_water"], "no engine to survey: nothing is invented")
        self.assertEqual(40.0, s["wheels"]["wheels"][0]["speed_rpm"])
        self.assertEqual(["stone"], [h["by"] for h in s["struck"]["hits"]])
        self.assertEqual({"declared": False}, s["sun"])
        self.assertEqual({"carries": False}, s["load"])


class TheBrainOffTheStep(unittest.TestCase):
    """A decision is asked for on a thread and applied before the next step."""

    def wait_for(self, brain, seconds=5.0):
        end = time.monotonic() + seconds
        while brain.thinking is not None and time.monotonic() < end:
            time.sleep(0.01)

    def test_an_event_asks_jev_once_and_the_answer_goes_to_the_program(self):
        ask = jev_says("turn_right", 0.7)
        brain = rover_brain.Brain("rover", rover_brain.JevClient("unused"), "jev")
        brain.observe(a_program(), None, [], 1.0, ask=ask)
        self.assertEqual([], ask.asked, "nothing happened yet")
        brain.observe(sees(a_program(), 1), None, [], 1.1, ask=ask)
        self.wait_for(brain)
        self.assertEqual(1, len(ask.asked))
        self.assertEqual("water ahead on its left", ask.asked[0][0]["event"])
        # The same water two seconds later is not asked about again; four
        # seconds later, out of the water and in again, it is.
        brain.observe(sees(a_program(), 1), None, [], 3.0, ask=ask)
        brain.observe(a_program(), None, [], 3.5, ask=ask)
        brain.observe(sees(a_program(), 1), None, [], 3.9, ask=ask)
        self.wait_for(brain)
        self.assertEqual(1, len(ask.asked))
        sent = []
        app = SimpleNamespace(live=SimpleNamespace(
            act=lambda body: (sent.append(body), {"program": {"doing": "turning right", "why": "x"}})[1]))
        brains = rover_brain.Brains(lambda: None)
        brains.brains["rover"] = brain
        brains.before(app, {"op": "poses"})
        self.assertEqual([], sent, "only a step applies what was decided")
        brains.before(app, {"session": "s", "op": "step"})
        self.assertEqual([{"session": "s", "op": "behave", "program": 1, "sender": "jev",
                           "doing": "turning right", "for_s": 1.5,
                           "why": "Jev said turn right for 1.5 s (70% sure) when water ahead on its left"}], sent)
        [decision] = brain.decisions
        self.assertEqual(("asked to be turning right for 1.5 s", "turn_right"), (decision["applied"], decision["pick"]))
        answer = {}
        brains.attach({"op": "step"}, answer)
        self.assertEqual("rover", answer["brains"][0]["name"])
        self.assertEqual(1, len(answer["brains"][0]["decisions"]))
        brains.attach({"op": "step"}, again := {})
        self.assertNotIn("brains", again, "the page hears of a brain once per change")
        brains.before(app, {"session": "s", "op": "step"})
        self.assertEqual(1, len(sent), "a decision is applied once")

    def test_while_it_is_still_in_it_the_brain_is_asked_again_and_knows_what_it_tried(self):
        """The point of the whole thing: more than one go at getting out.

        A machine that is stuck in something gets exactly one decision out of
        an edge-triggered event -- and if that decision does not work, nothing
        ever asks again. Measured on the roaming rover: one question at the
        shore, then thirty-nine seconds of sliding into the lake in silence.

        With "it is still in the water and not getting clear" the brain is
        asked afresh every AGAIN_S for as long as it is in, and each question
        carries what it just tried, so it can try something else. Nothing here
        knows what a rover is: any machine with a sensor that stops it gets
        this.
        """
        ask = jev_says("back_off", 0.9)
        brain = rover_brain.Brain("rover", rover_brain.JevClient("unused"), "jev")
        brains = rover_brain.Brains(lambda: None)
        brains.brains["rover"] = brain
        app = SimpleNamespace(live=SimpleNamespace(
            act=lambda body: {"program": {"doing": "backing off", "why": "x"}}))
        # What the page's own loop does: think on the reply, apply on the step.
        def observe_and_apply(program, at):
            brain.observe(program, None, [], at, ask=ask)
            self.wait_for(brain)
            brains.before(app, {"session": "s", "op": "step"})

        in_it = sees(a_program(), 1, seconds=20.0)
        observe_and_apply(a_program(), 0.0)
        for at in (1.0, 1.5, 2.0):          # inside AGAIN_S: asked once
            observe_and_apply(in_it, at)
        self.assertEqual(1, len(ask.asked))
        self.assertIn("it is still in the water and not getting clear", ask.asked[0][0]["event"])
        # Still in it, and long enough after: asked again, and this time the
        # question carries the answer it has already tried. By now the edge
        # has passed, so being still in it is the whole of what is wrong.
        for at in (1.0 + rover_brain.AGAIN_S, 1.0 + 2 * rover_brain.AGAIN_S):
            observe_and_apply(in_it, at)
        self.assertEqual(3, len(ask.asked), "it goes on being asked while it is still in it")
        self.assertEqual("it is still in the water and not getting clear", ask.asked[-1][0]["event"])
        tried = [d["tool"] for d in ask.asked[-1][0]["recent_decisions"]]
        self.assertEqual(["back_off", "back_off"], tried)
        # Out of it, and it stops being asked.
        observe_and_apply(a_program(), 100.0)
        self.assertEqual(3, len(ask.asked))

    def test_it_gets_a_few_goes_at_one_episode_and_then_stops_asking(self):
        """No timer, no surprise spend (docs/how-robots-think.md D3).

        "It is still in the water and not getting clear" repeats on purpose,
        so that a decider whose first answer did not work can try something
        else. Uncapped, that is a question every AGAIN_S for as long as
        somebody watches a stuck machine -- which on a real key is real
        money. It gets TRIES_MOST goes at one episode and then leaves it to
        its reflexes.
        """
        ask = jev_says("back_off", 0.9)
        brain = rover_brain.Brain("rover", rover_brain.JevClient("unused"), "jev")
        in_it = sees(a_program(), 1, seconds=20.0)
        at = 0.0
        for _ in range(12):                      # plenty of goes, well spaced
            at += rover_brain.AGAIN_S + 0.1
            brain.observe(in_it, None, [], at, ask=ask)
            self.wait_for(brain)
        self.assertEqual(rover_brain.TRIES_MOST, len(ask.asked),
                         "a machine in one long piece of trouble asks a few times, not for ever")
        # Out of it and into it again is a NEW episode, and it asks afresh.
        at += 1.0
        brain.observe(a_program(), None, [], at, ask=ask)
        self.wait_for(brain)
        at += 1.0
        brain.observe(in_it, None, [], at, ask=ask)
        self.wait_for(brain)
        self.assertEqual(rover_brain.TRIES_MOST + 1, len(ask.asked))

    def test_a_jev_that_fails_leaves_the_reflexes_in_charge(self):
        def broken(state, questions):
            raise ValueError("Jev answered HTTP 529")
        brain = rover_brain.Brain("rover", rover_brain.JevClient("unused"), "jev")
        brain.observe(a_program(), None, [], 0.0, ask=broken)
        brain.observe(sees(a_program(), -1), None, [], 0.1, ask=broken)
        self.wait_for(brain)
        decision = brain.take()
        self.assertIsNone(decision["call"])
        self.assertIn("HTTP 529", decision["said"])

    def test_without_a_key_the_mode_is_reflex_and_jev_cannot_be_pressed(self):
        brains = rover_brain.Brains(lambda: None)
        self.assertEqual("reflex", brains.of("rover").mode)
        with self.assertRaisesRegex(ValueError, "TYPESAFE_API_KEY"):
            brains.request({"program": "rover", "mode": "jev"})
        with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
            brains.request({"program": "rover", "mode": "openai"})
        with self.assertRaisesRegex(ValueError, "reflex"):
            brains.request({"program": "rover", "mode": "sideways"})
        summary = brains.request({"program": "rover"})
        self.assertEqual(("reflex", {"jev": False, "openai": False}), (summary["mode"], summary["configured"]))
        # With one, Jev is the default, and a mode set is kept for the next room.
        keyed = rover_brain.Brains(lambda: rover_brain.JevClient("k"))
        self.assertEqual("jev", keyed.of("rover").mode)
        keyed.request({"program": "rover", "mode": "reflex"})
        keyed.opened()
        self.assertEqual("reflex", keyed.of("rover").mode)

    def test_who_decides_comes_from_what_is_configured(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / ".env"
            for name in ("TYPESAFE_API_KEY", "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_DECIDER_MODEL",
                         "OPENAI_DECIDER_EFFORT", "BANJO_DECIDER", "JEV_API_URL"):
                os.environ.pop(name, None)
            env.write_text("OPENAI_API_KEY=k1\nOPENAI_MODEL=gpt-5-mini\n", encoding="utf-8")
            deciders, default = rover_brain.deciders_from([env])
            self.assertEqual((["openai"], "openai"), (sorted(deciders), default))
            self.assertEqual(("gpt-5-mini", "minimal", "OpenAI (gpt-5-mini)"),
                             (deciders["openai"].model, deciders["openai"].effort, deciders["openai"].label))
            env.write_text("OPENAI_API_KEY=k1\nOPENAI_DECIDER_MODEL=gpt-5-nano\nTYPESAFE_API_KEY=k2\n", encoding="utf-8")
            deciders, default = rover_brain.deciders_from([env])
            self.assertEqual((["jev", "openai"], "jev", "gpt-5-nano"),
                             (sorted(deciders), default, deciders["openai"].model))
            env.write_text("OPENAI_API_KEY=k1\nTYPESAFE_API_KEY=k2\nBANJO_DECIDER=openai\n", encoding="utf-8")
            self.assertEqual("openai", rover_brain.deciders_from([env])[1])
            env.write_text("TYPESAFE_API_KEY=k2\nBANJO_DECIDER=openai\n", encoding="utf-8")
            self.assertEqual("jev", rover_brain.deciders_from([env])[1], "a decider without a key is not the default")
        brains = rover_brain.Brains(lambda: ({"openai": rover_brain.OpenAIDecider("k", "gpt-5-mini")}, "openai"))
        brain = brains.of("rover")
        self.assertEqual(("openai", "OpenAI (gpt-5-mini)"), (brain.mode, brain.who))
        self.assertIs(brain.decider(), brain.deciders["openai"])
        brains.request({"program": "rover", "mode": "reflex"})
        self.assertEqual("its reflexes", brain.who)
        self.assertIs(brain.decider(), brain.deciders["openai"], "what a person says is still sorted by whoever is there")


class TheModelAsADecider(unittest.TestCase):
    """The chat's model asked the same typed questions, answering in Jev's shape."""

    def test_measured_usage_is_retained_without_response_text_or_credentials(self):
        import io
        client=rover_brain.OpenAIDecider('private-test-key','gpt-5-mini')
        questions={'next':{'type':'choice','criteria':{'inspect':'Inspect','wait':'Wait'}}}
        response={'status':'completed','usage':{'input_tokens':100,'output_tokens':40,'total_tokens':140,
            'input_tokens_details':{'cached_tokens':50},'output_tokens_details':{'reasoning_tokens':30}},
            'output':[{'type':'message','content':[{'type':'output_text',
                'text':json.dumps({'next':{'choice':'inspect','probabilities':{'inspect':1,'wait':0}}})}]}]}
        with mock.patch.object(rover_brain.request,'urlopen',return_value=io.BytesIO(json.dumps(response).encode())):
            result=client.ask({'private_prompt':'not metrics'},questions)
        self.assertEqual('inspect',result['next']['choice'])
        self.assertEqual(140,client.last_call['usage']['total_tokens'])
        self.assertEqual(50,client.last_call['usage']['cached_tokens'])
        self.assertEqual(30,client.last_call['usage']['reasoning_tokens'])
        self.assertEqual(200,client.last_call['http_status'])
        self.assertGreaterEqual(client.last_call['latency_s'],0)
        self.assertNotIn('private',json.dumps(client.last_call))

    def test_incomplete_response_retains_actual_usage_when_no_choice_was_returned(self):
        import io
        client=rover_brain.OpenAIDecider('private-test-key','gpt-5-mini')
        response={'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},'output':[],
                  'usage':{'input_tokens':10,'output_tokens':800,'total_tokens':810}}
        with mock.patch.object(rover_brain.request,'urlopen',return_value=io.BytesIO(json.dumps(response).encode())):
            with self.assertRaisesRegex(ValueError,'said nothing'):client.ask({},rover_brain.QUESTIONS)
        self.assertEqual('incomplete',client.last_call['response_status'])
        self.assertEqual(810,client.last_call['usage']['total_tokens'])
        self.assertIsNone(client.last_call['usage']['cached_tokens'])

    def test_failed_http_call_keeps_unknown_usage_and_safe_status(self):
        client=rover_brain.OpenAIDecider('private-test-key','gpt-5-mini')
        failure=rover_brain.error.HTTPError(client.url,401,'private diagnostic',{},None)
        with mock.patch.object(rover_brain.request,'urlopen',side_effect=failure):
            with self.assertRaisesRegex(ValueError,'HTTP 401'):client.ask({},rover_brain.QUESTIONS)
        self.assertEqual(401,client.last_call['http_status'])
        self.assertIsNone(client.last_call['usage'])
        self.assertNotIn('private',json.dumps(client.last_call))

    def test_invalid_usage_is_unknown_not_an_estimated_zero(self):
        for usage in ({},{'input_tokens':True,'output_tokens':1,'total_tokens':2},
                      {'input_tokens':3,'output_tokens':4,'total_tokens':99}):
            self.assertIsNone(rover_brain.response_usage({'usage':usage}))

    def test_the_schema_admits_only_the_answers_asked_for(self):
        schema = rover_brain.answer_schema(rover_brain.questions_for("roam"))
        self.assertEqual(["next", "arg_for_s", "arg_place", "arg_bearing_deg", "arg_distance_m", "arg_depth_m",
                          "stuck", "battery"], schema["required"])
        self.assertEqual([t["name"] for t in machine_tools.catalogue()],
                         schema["properties"]["next"]["properties"]["choice"]["enum"])
        self.assertEqual(["0", "1", "2"], schema["properties"]["battery"]["properties"]["probabilities"]["required"])
        self.assertFalse(schema["additionalProperties"])
        payload = rover_brain.OpenAIDecider("k", "gpt-5-mini").payload({"event": "x"}, rover_brain.QUESTIONS)
        self.assertEqual({"effort": "minimal"}, payload["reasoning"])
        self.assertEqual("json_schema", payload["text"]["format"]["type"])
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertNotIn("reasoning", rover_brain.OpenAIDecider("k", "gpt-4.1-mini").payload("s", rover_brain.QUESTIONS))

    def test_its_answers_come_back_in_jevs_shape(self):
        raw = {"next": {"choice": "go_forward", "probabilities": {"go_forward": 0.1, "back_off": 0.7, "turn_left": 0.1,
                                                                   "turn_right": 0.1, "hold_still": 0.0}},
               "stuck": {"noul": 0.2},
               "battery": {"probabilities": {"0": 0.2, "1": 0.8, "2": 0.0}}}
        answers = rover_brain.answers_from(raw, rover_brain.questions_for("roam"))
        # The choice is the most probable option, whatever the model named.
        self.assertEqual(("back_off", 0.7), (answers["next"]["choice"], answers["next"]["confidence"]))
        self.assertEqual(0.2, answers["stuck"]["noul"])
        self.assertEqual((0.8, 0.8), (answers["battery"]["score"], answers["battery"]["confidence"]))
        self.assertTrue(answers["battery"]["legend"]["1"].startswith("low"))
        decision = rover_brain.decide(answers, "water ahead on its left", "roam", "OpenAI (gpt-5-mini)")
        self.assertEqual("back_off", decision["call"]["tool"])
        self.assertEqual("OpenAI (gpt-5-mini): back off for 1.5 s (70% sure) when water ahead on its left", decision["said"],
                         "the model answers every question, so an unanswered score reads as its lowest level")
        self.assertEqual("low", decision["battery"])

    def test_the_model_is_called_and_read_through_the_responses_api(self):
        seen = {}

        class Reply:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n=-1):
                return json.dumps({"status": "completed", "output": [
                    {"type": "reasoning"},
                    {"type": "message", "content": [{"type": "output_text", "text": json.dumps(
                        {"intent": {"choice": "come_here", "probabilities": {"stop": 0.05, "come_here": 0.9}}})}]}]}).encode()

        def fake_urlopen(req, timeout=0):
            seen["url"], seen["auth"] = req.full_url, req.get_header("Authorization")
            seen["body"] = json.loads(req.data)
            return Reply()
        questions = {"intent": {"type": "choice", "instructions": "what do they mean",
                                "criteria": {"stop": "stop", "come_here": "come"}}}
        with patch.object(rover_brain.request, "urlopen", fake_urlopen):
            answers = rover_brain.OpenAIDecider("sk-test", "gpt-5-mini").ask({"said": "come over"}, questions)
        self.assertEqual("https://api.openai.com/v1/responses", seen["url"])
        self.assertEqual("Bearer sk-test", seen["auth"])
        self.assertIn("come over", seen["body"]["input"])
        self.assertEqual(("come_here", 0.9474), (answers["intent"]["choice"], answers["intent"]["confidence"]))
        # And the talk sorts what a person says through it the same way.
        with patch.object(rover_brain.request, "urlopen", fake_urlopen):
            sorted_as = rover_talk.classify(rover_brain.OpenAIDecider("sk-test", "gpt-5-mini"), "come over")
        self.assertEqual(("come_here", 0.9474, "openai"), sorted_as)


class TalkingToIt(unittest.TestCase):
    def test_plain_words_sort_what_the_person_means(self):
        for said, intent in (("stop right there", "stop"), ("come here", "come_here"), ("turn around", "turn_around"),
                             ("back off a bit", "back_off"), ("ok go on", "go_on"), ("why did you stop?", "why"),
                             ("how's your battery", "status"), ("what colour is the sky", "other")):
            with self.subTest(said=said):
                self.assertEqual((intent, "words"), rover_talk.classify(None, said)[::2])

    def test_jev_sorts_it_when_there_and_words_when_it_fails(self):
        client = SimpleNamespace(ask=jev_says("go_on", 0.8))
        self.assertEqual(("come_here", 0.8, "jev"), rover_talk.classify(client, "come over"))
        unsure = SimpleNamespace(ask=jev_says("go_on", 0.3))
        self.assertEqual(("other", 0.3, "jev"), rover_talk.classify(unsure, "stop"))

        def broken(state, questions):
            raise ValueError("down")
        self.assertEqual(("stop", 1.0, "words"), rover_talk.classify(SimpleNamespace(ask=broken), "stop!"))

    def test_it_describes_itself_from_its_program(self):
        said = rover_talk.describe(sees(a_program(turns=3), 1))
        self.assertEqual("I am going forward: nothing in its way. My battery is at 80%; I rest below 25%. "
                         "I see water ahead on my left. I have turned away from things 3 times.", said)
        self.assertTrue(rover_talk.describe(a_program(power=False)).startswith("I am switched off."))
        self.assertTrue(rover_talk.describe(a_program(doing="waiting", why="the person told it to stop"))
                        .startswith("I am holding still: the person told it to stop."))


class InTheRealEngine(unittest.TestCase):
    """The tests-rover room, with a Jev that always says back off, and a
    person who comes to talk to it."""

    def setUp(self):
        if ENGINE is None:
            self.skipTest("BANJO_LIVE_ENGINE is not set")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.live = live_session.Live()
        self.addCleanup(self.live.shutdown)
        self.room = world_room.Room("tests-rover")
        self.ask = jev_says("back_off", 0.9)
        self.brains = rover_brain.Brains(lambda: rover_brain.JevClient("scripted"))
        self.app = SimpleNamespace(live=self.live, live_holder="world", room=self.room, engine_path=ENGINE,
                                   runs_path=root / "runs", store=room_store.RoomStore(root / "rooms"),
                                   brains=self.brains, api_key="", model="",
                                   on_live_reply=lambda session, reply: self.brains.listen(session, reply))
        self.opened = self.live.open(self.app, {"spec": self.room.spec})
        self.brains.opened()
        # Jev is the function above, not the network.
        brain = self.brains.of("rover")
        brain.client.ask = self.ask
        self.session_id = self.live.session.id

    def program(self, reply=None):
        reply = reply or self.live.session.send(op="step", dt=DT, n=1)
        return next(p for p in reply["machines"]["programs"] if p["name"] == "rover")

    def step_as_the_page_does(self, seconds):
        """Steps through Live.act, with the brains before and after each, as
        the server does for the page; returns the last program reading."""
        program = None
        for _ in range(int(seconds * 4)):
            body = {"session": self.session_id, "op": "step", "dt": DT, "n": 30}
            self.brains.before(self.app, body)
            answer = self.live.act(body)
            self.brains.attach(body, answer)
            program = next(p for p in answer["machines"]["programs"] if p["name"] == "rover")
            brain = self.brains.of("rover")
            if brain.thinking is not None:
                end = time.monotonic() + 5.0
                while brain.thinking is not None and time.monotonic() < end:
                    time.sleep(0.005)
        return program

    def pose(self, name):
        return next(b for b in self.live.session.send(op="poses")["bodies"] if b["name"] == name)

    def test_jev_is_asked_at_the_waters_edge_and_its_pick_is_done(self):
        self.live.session.send(op="step", dt=DT, n=240)
        said = self.live.session.send(op="run", program=self.program()["id"], sender="test", seq=1, power=True)
        self.assertEqual("going forward", said["program"]["doing"])
        brain = self.brains.of("rover")
        asked_by_jev = None
        for _ in range(12):                       # up to a minute of roaming
            self.step_as_the_page_does(5.0)
            if any(d.get("applied", "").startswith("asked") for d in brain.decisions):
                break
        self.assertTrue(self.ask.asked, "something happened to it in a minute of roaming")
        events = [d["event"] for d in brain.decisions]
        print(f"\n    Jev was asked {len(self.ask.asked)} times: {events}")
        applied = [d for d in brain.decisions if d.get("applied", "").startswith("asked")]
        self.assertTrue(applied, f"a pick was done: {list(brain.decisions)}")
        self.assertTrue(all(d["pick"] == "back_off" for d in applied))
        # What Jev read was the rover, with the event named.
        state, questions = self.ask.asked[0]
        self.assertIn(state["event"], events)
        self.assertIn("nearest_water", state["senses"]["water"], "the senses were read with the engine at hand")
        self.assertIn("downhill_bearing_deg", state["senses"]["slope"])
        self.assertLessEqual({"next", "stuck", "battery", "arg_for_s", "arg_place"}, set(questions))
        # The program said Jev asked it, and, the while up, its reflexes had it
        # back: no ask stands two seconds on.
        program = self.program()
        seen_jev = any("Jev said back off" in d["call"]["why"] for d in applied)
        self.assertTrue(seen_jev)
        self.step_as_the_page_does(2.5)
        program = self.program()
        self.assertTrue(program["asked"] is None or program["asked"]["by"] != "jev" or program["asked"]["s"] < 1.6,
                        program["asked"])

    def test_talking_to_it_turns_it_to_the_person_and_lets_it_go_on(self):
        self.live.session.send(op="step", dt=DT, n=240)
        self.live.session.send(op="run", program=self.program()["id"], sender="test", seq=1, power=True)
        self.step_as_the_page_does(3.0)
        at = self.pose("rover")
        v = at["velocity_m_s"]
        speed = math.hypot(v[0], v[2])
        self.assertGreater(speed, 0.1, "it is going somewhere")
        behind = [at["position_m"][0] - 3.0 * v[0] / speed, at["position_m"][1], at["position_m"][2] - 3.0 * v[2] / speed]
        person = {"standing_m": behind, "facing": [v[0] / speed, 0, v[2] / speed]}
        opened = rover_talk.talk(self.app, {"program": "rover", "open": True, "person": person})
        self.assertEqual(("facing", "talk"), (opened["program"]["asked"]["doing"], opened["program"]["asked"]["by"]))
        # It was going somewhere when they spoke, so it stops before it turns:
        # turning with its wheels opposed has no braking, and one that turns
        # while still moving coasts off its way (LiveWorld, decideProgram).
        self.assertIn(opened["program"]["doing"], ("stopping", "turning left", "turning right"))
        self.assertTrue(opened["reply"].startswith(("I am stopping", "I am turning")), opened["reply"])
        self.assertEqual([("rover", True)], [(t["who"], t.get("opened", False)) for t in opened["talk"]])
        # While they talk, nothing that happens to it is asked about.
        self.step_as_the_page_does(14.0)
        program = self.program()
        self.assertEqual("waiting", program["doing"], program)
        self.assertEqual([], self.ask.asked, "Jev is not asked while the person has it")
        # Where it faces: going forward from here would go towards the person.
        faced = self.pose("rover")
        said = rover_talk.talk(self.app, {"program": "rover", "said": "stop", "person": person})
        self.assertEqual(("stop", "jev"), (said["talk"][-1]["intent"], said["talk"][-1]["sorted_by"]))
        self.assertEqual("waiting", said["program"]["doing"])
        self.assertEqual("Stopping. I will hold here until you say.", said["reply"])
        status = rover_talk.talk(self.app, {"program": "rover", "said": "what are you doing?", "person": person})
        self.assertTrue(status["reply"].startswith("I am holding still: the person told it to stop."), status["reply"])
        come = rover_talk.talk(self.app, {"program": "rover", "said": "come here", "person": person})
        self.assertEqual("approaching", come["program"]["asked"]["doing"])
        self.step_as_the_page_does(12.0)
        program = self.program()
        near = self.pose("rover")["position_m"]
        away = math.hypot(near[0] - behind[0], near[2] - behind[2])
        print(f"    asked to come, it is {away:.2f} m from the person 12 s on, {program['doing']}")
        self.assertLess(away, 1.6, "it came to the person")
        self.assertEqual("waiting", program["doing"])
        closed = rover_talk.talk(self.app, {"program": "rover", "close": True})
        self.assertIsNone(closed["program"]["asked"])
        self.assertEqual("going forward", closed["program"]["doing"])
        self.assertEqual("Going on.", closed["reply"])
        self.assertEqual({"you", "rover"}, {t["who"] for t in closed["talk"]})

    def test_a_person_talking_to_a_machine_that_is_off_is_told_so(self):
        self.live.session.send(op="step", dt=DT, n=120)
        opened = rover_talk.talk(self.app, {"program": "rover", "open": True,
                                            "person": {"standing_m": [0, 0, 0], "facing": [0, 0, 1]}})
        self.assertTrue(opened["reply"].startswith("I am switched off."), opened["reply"])
        self.assertIsNone(opened["program"]["asked"])
        said = rover_talk.talk(self.app, {"program": "rover", "said": "come here",
                                          "person": {"standing_m": [0, 0, 0], "facing": [0, 0, 1]}})
        self.assertEqual("I am switched off, so I cannot. Switch me on first.", said["reply"])
        with self.assertRaisesRegex(ValueError, "no machine with a program called"):
            rover_talk.talk(self.app, {"program": "toaster", "open": True})


class TheSensesAndTheTools(unittest.TestCase):
    """What a machine can sense and do, read and done through a stand-in
    engine that answers surveys and takes asks."""

    def engine(self, water_at=None, heights=None):
        sent = []

        def ask(**command):
            sent.append(command)
            op = command.get("op")
            if op == "survey":
                x, z = command["at"]
                h = (heights or (lambda x, z: 0.0))(x, z)
                wet = water_at is not None and math.hypot(x - water_at[0], z - water_at[1]) < 1.5
                return {"survey": {"on_the_ground": True, "ground_m": h, "surface": "soil", "sand_m": 0.0,
                                   "soil_m": 0.6, "slope_deg": 0.0,
                                   "water": {"depth_m": 0.2} if wet else None}}
            if op == "sun":
                return {"sun": {"elevation_deg": 50.0, "azimuth_deg": 200.0, "irradiance_w_m2": 1000.0}}
            if op == "behave":
                return {"asked": "applied", "program": {"doing": command["doing"] or "going forward", "why": command["why"]}}
            if op == "dig":
                return {"dug": {"kg": 12.0, "sand_m3": 0.0, "soil_m3": 0.0075}}
            if op in ("ground_withdraw", "ground_return", "deposit", "draw"):
                return {"ok": True, "drawn": command.get("joules")}
            return {}
        ask.sent = sent
        return ask

    def context(self, ask, **changes):
        program = a_program(at_m=[0.0, 0.3, 0.0], heading_deg=0.0, **changes)
        machines = {"controls": [{"id": 1, "motor": 11, "condition": ""}, {"id": 2, "motor": 12, "condition": ""}],
                    "motors": [{"id": 11, "store": 21}, {"id": 12, "store": 21}],
                    "stores": [{"id": 21, "capacity_j": 100000.0, "charge_j": 80000.0}],
                    "panels": [{"store": 21, "power_w": 12.5}]}
        return machine_senses.Context(program=program, machines=machines, ask=ask,
                                      bodies=[{"name": "boulder", "material": "granite", "position_m": [3.0, 0.5, 3.0],
                                               "velocity_m_s": [0, 0, 0]}])

    def test_directions_are_from_its_front_positive_to_its_left(self):
        self.assertEqual(90.0, machine_senses.relative_bearing(0.0, 1.0, 0.0), "+x is to the left of +z")
        self.assertEqual(-90.0, machine_senses.relative_bearing(0.0, -1.0, 0.0))
        self.assertEqual(180.0, machine_senses.relative_bearing(0.0, 0.0, -1.0))
        self.assertEqual(0.0, machine_senses.relative_bearing(90.0, 1.0, 0.0), "facing +x, +x is ahead")
        self.assertEqual([0.0, 3.0], machine_senses.point_ahead(self.context(self.engine()), 3.0))

    def test_it_senses_the_water_the_slope_the_sun_and_what_is_near(self):
        ctx = self.context(self.engine(water_at=(0.0, 3.0), heights=lambda x, z: -0.2 * z))
        s = machine_senses.read(ctx)
        self.assertEqual({"distance_m": 3.0, "bearing_deg": 0.0, "depth_m": 0.2}, s["water"]["nearest_water"])
        self.assertNotIn(0.0, s["water"]["dry_bearings_deg"], "ahead is wet three metres out")
        self.assertEqual(0.0, s["slope"]["downhill_bearing_deg"], "the ground falls towards +z: downhill is ahead")
        self.assertAlmostEqual(180.0, abs(s["slope"]["uphill_bearing_deg"]))
        self.assertLess(s["slope"]["ahead_rises_deg"], 0.0)
        self.assertEqual((True, -160.0, True), (s["sun"]["declared"], s["sun"]["bearing_deg"], s["sun"]["daylight"]))
        self.assertEqual((0.8, 12.5), (s["battery"]["share_of_full"], s["battery"]["charging_w"]))
        [near] = s["nearby"]["things"]
        self.assertEqual(("boulder", 4.24, 45.0), (near["name"], near["distance_m"], near["bearing_deg"]))
        self.assertEqual({"present": False}, s["person"])
        ctx.person = {"standing_m": [-2.0, 0.0, 0.0]}
        self.assertEqual({"present": True, "distance_m": 2.0, "bearing_deg": -90.0}, machine_senses.sense_person(ctx))
        # Every sense has words for whoever is told what a machine can sense.
        self.assertTrue(all(c["description"] for c in machine_senses.catalogue()))

    def test_the_tools_ask_the_program_and_say_what_they_did(self):
        ask = self.engine()
        ctx = self.context(ask)
        ctx.routine = machine_routine.Routine("rover", {"kind": "dig", "hopper_kg": 40.0,
                                                        "places": {"depot": [-3.0, 0.0], "dig site": [0.0, 4.0]}})
        did = machine_tools.run(ctx, machine_tools.Call("go_to", {"place": "dig site"}, "routine", "its routine"))
        # It stands off the site, because the site is the pit it digs
        # (machine_tools.DIG_STAND_M).
        self.assertEqual("asked to go to dig site, and stop a metre off", did["did"])
        self.assertEqual({"session": None, "op": "behave", "program": 1, "sender": "routine", "doing": "approaching",
                          "for_s": 60.0, "why": "its routine", "toward": [0.0, 0.3, 4.0]},
                         {**ask.sent[-1], "session": None})
        did = machine_tools.run(ctx, machine_tools.Call("face", {"bearing_deg": 90.0, "distance_m": 2.0}, "talk"))
        self.assertEqual([2.0, 0.3, 0.0], ask.sent[-1]["toward"])
        did = machine_tools.run(ctx, machine_tools.Call("go_to", {"place": "moon"}, "talk"))
        self.assertTrue(did["failed"])
        self.assertIn("knows no place called 'moon'", did["did"])
        did = machine_tools.run(ctx, machine_tools.Call("fly", {}, "talk"))
        self.assertTrue(did["failed"])
        # Every tool a decider may pick has words and a schema for its arguments.
        self.assertTrue(all(t["description"] and isinstance(t["params"], dict) for t in machine_tools.catalogue()))

    def test_a_scoop_goes_into_the_hopper_out_of_the_ground_and_costs_the_battery(self):
        ask = self.engine()
        ctx = self.context(ask)
        ctx.routine = machine_routine.Routine("rover", {"kind": "dig", "hopper_kg": 30.0, "work_j_per_kg": 50.0,
                                                        "places": {"depot": [-3.0, 0.0], "dig site": [0.0, 4.0]}})
        did = machine_tools.run(ctx, machine_tools.Call("dig", {}, "routine"))
        ops = [c["op"] for c in ask.sent]
        self.assertEqual(["dig_clearance", "survey", "dig", "ground_withdraw", "draw", "behave"], ops)
        dug = next(c for c in ask.sent if c["op"] == "dig")
        self.assertEqual(([0.0, 1.3], 0.5, 0.15), (dug["from"], dug["width_m"], dug["depth_m"]))
        self.assertEqual({"op": "ground_withdraw", "sand_m3": 0.0, "soil_m3": 0.0075},
                         next(c for c in ask.sent if c["op"] == "ground_withdraw"))
        self.assertEqual(600.0, next(c for c in ask.sent if c["op"] == "draw")["joules"], "12 kg at 50 J/kg")
        self.assertEqual(3.0, next(c for c in ask.sent if c["op"] == "behave")["for_s"], "a scoop takes its time")
        self.assertEqual((12.0, False), (ctx.routine.kg, ctx.routine.load_full()))
        self.assertEqual(600, did["drawn_j"])
        # Two more and it is full: the third scoop is cut to what fits, the
        # rest put back where it came from.
        machine_tools.run(ctx, machine_tools.Call("dig", {}, "routine"))
        machine_tools.run(ctx, machine_tools.Call("dig", {}, "routine"))
        self.assertEqual(30.0, ctx.routine.kg)
        self.assertTrue(ctx.routine.load_full())
        self.assertIn("deposit", [c["op"] for c in ask.sent[-6:]], "what did not fit went back")
        did = machine_tools.run(ctx, machine_tools.Call("dig", {}, "routine"))
        self.assertEqual("dug nothing: its hopper is full", did["did"])
        did = machine_tools.run(ctx, machine_tools.Call("dump", {}, "routine"))
        self.assertEqual("dumped 30.0 kg on the ground ahead", did["did"])
        self.assertEqual(["ground_return", "deposit", "behave"], [c["op"] for c in ask.sent[-3:]])
        self.assertEqual((0.0, 30.0, 1), (ctx.routine.kg, ctx.routine.delivered_kg, ctx.routine.trips))

    def test_rounded_scoop_cannot_overfill_an_exact_receiving_hopper(self):
        original = self.engine()
        received = []
        # Display values disagree: 30 kg reported but 0.01876 m3 = 30.016 kg.
        # The transfer returns its exact native packet, like the real host.
        def ask(**command):
            if command['op'] == 'dig':
                return {'dug': {'kg':30, 'sand_m3':0, 'soil_m3':.01876},
                        'carried': {'sand_m3':0, 'sand_kg':0,
                                    'soil_m3':.01876, 'soil_kg':30.016}}
            if command['op'] == 'ground_withdraw':
                volume = command['soil_m3']; received.append(volume)
                return {'material_packet': {'contents':[
                    {'substance':'soil','volume_m3':volume,'mass_kg':volume*1600}]}}
            return original(**command)
        ctx = self.context(ask)
        ctx.routine = machine_routine.Routine('renamed carrier', {'kind':'dig','hopper_kg':30})
        machine_tools.run(ctx, machine_tools.Call('dig',{},'routine'))
        self.assertAlmostEqual(30,ctx.routine.kg,places=12)
        self.assertAlmostEqual(.01875,received[0],places=15)
        returned = next(c for c in original.sent if c['op']=='deposit')
        self.assertAlmostEqual(.01876,received[0]+returned['soil_m3'],places=15)
        self.assertEqual(ctx.routine.record(),
                         self._restored_hopper(ctx.routine).record())

    def _restored_hopper(self, routine):
        restored = machine_routine.Routine('renamed carrier', {'kind':'dig','hopper_kg':30})
        restored.restore(routine.record())
        return restored

    def test_it_works_the_place_it_is_sent_to_and_never_digs_the_ground_under_itself(self):
        """A machine sent to work a place digs THAT place, off its high ground,
        and will not dig where it is standing or deepen a hole it has made
        (docs/machine-world.md, "When a machine cannot get out")."""
        # The ground is flat except for a hole 200 mm deep at the site's middle,
        # as a scoop would leave, and the machine stands 1.5 m south of the site.
        def heights(x, z):
            return -0.2 if math.hypot(x - 0.0, z - 1.5) < 0.2 else 0.0

        ask = self.engine(heights=heights)
        ctx = self.context(ask)
        ctx.routine = machine_routine.Routine("rover", {"kind": "dig", "hopper_kg": 30.0,
                                                        "places": {"depot": [-3.0, 0.0], "site": [0.0, 1.5]}})
        did = machine_tools.run(ctx, machine_tools.Call("dig", {"place": "site"}, "routine"))
        bite = next(c for c in ask.sent if c["op"] == "dig")["from"]
        self.assertTrue(did["did"].startswith("dug 12.0 kg"), did["did"])
        # Not the hole in the middle: somewhere else at the site, off the high
        # ground, and out at arm's length rather than under the machine.
        self.assertEqual(0.0, heights(bite[0], bite[1]), "into fresh ground, not the hole it already made")
        self.assertLessEqual(math.hypot(bite[0], bite[1] - 1.5), machine_tools.DIG_SPREAD_M + 1e-6,
                             "and still at the site")
        self.assertGreaterEqual(math.hypot(bite[0], bite[1]), machine_tools.DIG_CLEAR_M,
                                "never the ground under itself")
        # Standing on the place: it backs off instead of digging, and says so.
        near = self.context(self.engine(heights=heights))
        near.program["at_m"] = [0.0, 0.3, 1.2]
        near.routine = ctx.routine
        did = machine_tools.run(near, machine_tools.Call("dig", {"place": "site"}, "routine"))
        self.assertIn("will not dig the ground under itself", did["did"])
        self.assertIn("backs off", did["did"])
        self.assertEqual("backing off", next(c for c in near.ask.sent if c["op"] == "behave")["doing"])
        # Out of reach: it goes back to the place rather than digging where it
        # stands, and rather than refusing, which left a routine sat on a dig
        # step for the rest of a run because the step that took it there is
        # behind it.
        far = self.context(self.engine(heights=heights))
        far.routine = ctx.routine
        did = machine_tools.run(far, machine_tools.Call("dig", {"place": "depot"}, "routine"))
        self.assertNotIn("failed", did, did)
        self.assertIn("beyond the 2.0 m it can reach, so it goes back", did["did"])
        asked = next(c for c in far.ask.sent if c["op"] == "behave")
        self.assertEqual("approaching", asked["doing"])
        # It is sent to where it should STAND to work the place, not to the place.
        stand = math.hypot(asked["toward"][0] - (-3.0), asked["toward"][-1] - 0.0)
        self.assertLess(abs(stand - (machine_tools.DIG_STAND_M - machine_tools.NEAR_M)), 0.05,
                        f"aimed {stand:.2f} m short of the depot")
        # A machine that flies works the ground under it: it hovers over the
        # place and scoops down, so it keeps no stand-off and what it digs is
        # never under its wheels.
        flyer = self.context(self.engine(heights=heights))
        flyer.program["kind"] = "hover"
        flyer.program["at_m"] = [0.0, 1.8, 1.4]      # hovering right over the site
        flyer.routine = machine_routine.Routine("drone", {"kind": "dig", "hopper_kg": 20.0,
                                                          "places": {"site": [0.0, 1.5]}})
        did = machine_tools.run(flyer, machine_tools.Call("dig", {"place": "site"}, "routine"))
        self.assertTrue(did["did"].startswith("dug 12.0 kg"), did["did"])
        self.assertEqual(0.0, machine_tools.stands_off_m(flyer), "a flyer stands off nothing")
        self.assertGreater(machine_tools.stands_off_m(ctx), 1.0, "a machine on wheels does")
        # Worked out: every spot of the place already down past DIG_FRESH_M, so
        # it stops rather than deepening one, and its routine moves it on.
        # Down 200 mm across the whole working, but not out where the ground
        # around it is read (DIG_SPREAD_M + 0.5 m).
        dug_out = self.context(self.engine(heights=lambda x, z: -0.2 if math.hypot(x, z - 1.5) < 0.7 else 0.0))
        dug_out.routine = ctx.routine
        did = machine_tools.run(dug_out, machine_tools.Call("dig", {"place": "site"}, "routine"))
        self.assertTrue(did["idle"], did["did"])
        self.assertIn("worked out", did["did"])
        self.assertIn("will not dig one hole deeper", did["did"])
        self.assertNotIn("dig", [c["op"] for c in dug_out.ask.sent], "and it never touched the ground")

    def test_the_routine_runs_its_steps_and_waits_while_someone_else_has_it(self):
        ask = self.engine()
        # The site is within reach of where it stands: a machine digs the place
        # it was sent to, so it has to be able to reach it (DIG_REACH_M).
        routine = machine_routine.Routine("rover", {"kind": "dig", "hopper_kg": 24.0,
                                                    "places": {"dig site": [0.0, 1.8],
                                                               "depot": [-3.0, 0.0]}})
        ctx = self.context(ask)
        ctx.routine = routine
        self.assertEqual((1, "go_to dig site"), (routine.summary()["step"], routine.summary()["doing"]))
        did = routine.tick(ctx)
        self.assertEqual("asked to go to dig site, and stand 2.0 m off it", did["did"])
        # Still on its way: nothing more is asked.
        ctx.program["asked"] = {"doing": "approaching", "by": "routine"}
        self.assertIsNone(routine.tick(ctx))
        # Arrived: the next step, a scoop, and another when the first is done.
        ctx.program["doing"] = "waiting"
        self.assertIsNone(routine.tick(ctx))
        self.assertEqual(2, routine.summary()["step"])
        ctx.program["asked"] = None
        ctx.program["doing"] = "going forward"
        self.assertTrue(routine.tick(ctx)["did"].startswith("dug 12.0 kg"))
        ctx.program["asked"] = {"doing": "waiting", "by": "routine"}
        self.assertIsNone(routine.tick(ctx), "the scoop is still being taken")
        ctx.program["asked"] = None
        self.assertTrue(routine.tick(ctx)["did"].startswith("dug 12.0 kg"))
        self.assertTrue(routine.load_full())
        # Someone else has it: the routine waits, and takes its step up again after.
        ctx.program["asked"] = {"doing": "waiting", "by": "talk"}
        self.assertIsNone(routine.tick(ctx))
        self.assertEqual("talk", routine.summary()["paused_by"])
        ctx.program["asked"] = None
        self.assertIsNone(routine.tick(ctx), "full: the dig step ends")
        did = routine.tick(ctx)
        self.assertEqual("asked to be backing off for 1.5 s", did["did"], "away from its own hole first")
        self.assertIsNone(routine.summary()["paused_by"])
        ctx.program["asked"] = {"doing": "backing off", "by": "routine"}
        self.assertIsNone(routine.tick(ctx))
        ctx.program["asked"] = None
        self.assertIsNone(routine.tick(ctx), "backed off: the step ends")
        did = routine.tick(ctx)
        self.assertEqual("asked to go to depot, and stop a metre off", did["did"])
        # Off: nothing.
        ctx.program["power"] = False
        self.assertIsNone(routine.tick(ctx))

    def test_a_room_declares_a_routine_and_the_validator_keeps_it(self):
        import fracture_lab
        room = world_room.SCENES["tests-rover"]()
        program = room["machines"]["programs"][0]
        program["routine"] = {"kind": "dig", "places": {"dig site": [2, -6.5], "depot": [-2.5, -9.5]}, "hopper_kg": 40}
        kept = fracture_lab.validate(room)["machines"]["programs"][0]["routine"]
        self.assertEqual({"kind": "dig", "places": {"dig site": [2.0, -6.5], "depot": [-2.5, -9.5]}, "hopper_kg": 40.0}, kept)
        self.assertEqual(kept, machine_routine.declared_for(fracture_lab.validate(room), "rover"))
        for change, message in ((lambda r: r.update(kind="fly"), "kinds there are"),
                                (lambda r: r.pop("hopper_kg"), "needs a hopper"),
                                (lambda r: r["places"].pop("depot"), "lacks"),
                                (lambda r: r.update(speed=2), "cannot say")):
            routine = {"kind": "dig", "places": {"dig site": [2, -6.5], "depot": [-2.5, -9.5]}, "hopper_kg": 40}
            change(routine)
            program["routine"] = routine
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                fracture_lab.validate(room)


class InTheDigRoom(unittest.TestCase):
    """The tests-dig room: the rover's routine over its program, as the
    server runs it before each step the page takes -- it digs, carries and
    dumps, with the ground's account and its battery's both whole."""

    def setUp(self):
        if ENGINE is None:
            self.skipTest("BANJO_LIVE_ENGINE is not set")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.live = live_session.Live()
        self.addCleanup(self.live.shutdown)
        self.room = world_room.Room("tests-dig")
        self.brains = rover_brain.Brains(lambda: None)
        self.app = SimpleNamespace(live=self.live, live_holder="world", room=self.room, engine_path=ENGINE,
                                   runs_path=root / "runs", store=room_store.RoomStore(root / "rooms"),
                                   brains=self.brains, api_key="", model="",
                                   on_live_reply=lambda session, reply: self.brains.listen(session, reply))
        self.opened = self.live.open(self.app, {"spec": self.room.spec})
        self.brains.opened(self.room.spec)
        self.session_id = self.live.session.id

    def program(self, reply=None):
        reply = reply or self.live.session.send(op="step", dt=DT, n=1)
        return next(p for p in reply["machines"]["programs"] if p["name"] == "rover")

    def run_as_the_page_does(self, seconds, until=None):
        # At the page's own step, 1/240 s: at 1/120 the caster sinks and the
        # rover crawls (tools/build_rover_room.py).
        for _ in range(int(seconds * 4)):
            body = {"session": self.session_id, "op": "step", "dt": 1 / 240, "n": 60}
            self.brains.before(self.app, body)
            answer = self.live.act(body)
            self.brains.attach(body, answer)
            if until is not None and until():
                return True
        return False

    def test_it_digs_carries_and_dumps_by_its_routine(self):
        self.live.session.send(op="step", dt=DT, n=240)
        said = self.live.session.send(op="run", program=self.program()["id"], sender="test", seq=1, power=True)
        self.assertTrue(said["program"]["power"])
        brain = self.brains.of("rover")
        self.assertEqual(("dig", 40.0), (brain.routine.kind, brain.routine.hopper_kg))
        delivered = self.run_as_the_page_does(300.0, until=lambda: brain.routine.trips >= 1)
        summary = brain.routine.summary()
        print(f"\n    the dig routine: {summary['load']}; notes: {' | '.join(summary['notes'])}")
        self.assertTrue(delivered, f"in 300 s it did not deliver a load: {summary}")
        self.assertGreater(brain.routine.delivered_kg, 20.0)
        self.assertIn("step 4 done: it arrived", summary["notes"], "the load went to the depot, not just anywhere")
        carried = self.live.session.send(op="ground_work").get("carried") or {}
        self.assertLess(float(carried.get("total_kg") or 0.0), 0.5, "the ground's account is whole after the dump")
        store = self.live.session.send(op="step", dt=DT, n=1)["machines"]["stores"][0]
        self.assertGreater(store["given_j"], brain.routine.delivered_kg * 50.0, "the scoop's work was drawn")
        self.assertAlmostEqual(store["charge_j"], 100000.0 + store["taken_j"] - store["given_j"], places=2)
        # The page hears of the routine with the brain.
        self.assertEqual(1, summary["load"]["trips"])
        self.assertIn("step", summary)

    def test_restart_retains_exact_hopper_receipts_and_continues_to_return_it(self):
        import server
        from mcp import fabrication, ground_transfers
        self.live.session.send(op="step",dt=DT,n=240)
        self.live.session.send(op="run",program=self.program()["id"],sender="test",seq=1,power=True)
        brain=self.brains.of("rover")
        self.assertTrue(self.run_as_the_page_does(180,until=lambda:brain.routine.kg>20))
        self.assertTrue(server.keep_world(self.app,"loaded hopper"))
        exact=brain.routine.record(); book=deepcopy(self.room.ground_transfers)
        self.live.shutdown()
        self.room=self.app.room=self.app.store.load("tests-dig")
        self.brains=self.app.brains=rover_brain.Brains(lambda:None)
        self.opened=self.live.open(self.app,{"spec":self.room.spec,"snapshot":self.room.world_record})
        self.assertEqual("whole",self.opened["restored"]["tier"])
        self.brains.opened(self.room.spec,self.room.machine_runtime)
        self.brains.settle(self.opened); self.session_id=self.live.session.id
        brain=self.brains.of("rover")
        self.assertEqual(exact,brain.routine.record())
        self.assertEqual(book,self.room.ground_transfers)
        self.assertTrue(self.run_as_the_page_does(300,until=lambda:brain.routine.trips>=1))
        self.assertTrue(server.keep_world(self.app,"returned hopper"))
        fabrication.validate_ground_stock({},self.room.world_record,self.room.ground_transfers)
        totals=ground_transfers.totals(self.room.ground_transfers)
        self.assertGreater(totals["returned"]["soil_m3"],.01)
        self.assertLess(abs(totals["holders"]["machine:rover"]["soil_m3"]),1e-10)
        print("\n    loaded/restarted/returned: native source and exact receiving receipts agree; holder residual",
              totals["holders"]["machine:rover"])


class LocalNavigation(unittest.TestCase):
    def test_named_working_skips_a_refused_high_point_for_supported_fresh_ground(self):
        fixture=TheSensesAndTheTools();base=fixture.engine();checks=[]
        def ask(**command):
            if command['op']=='dig_clearance':
                checks.append(command['from'])
                return {'clear':abs(command['from'][0])>.1}
            return base(**command)
        ctx=fixture.context(ask)
        ctx.routine=machine_routine.Routine('rover',{'kind':'dig','places':{'site':[0.,1.8]}})
        bite=machine_tools._bite(ctx,{'place':'site'})
        self.assertGreater(abs(bite['point'][0]),.1)
        self.assertEqual([0.,1.8],checks[0]);self.assertGreater(len(checks),1)
        self.assertFalse(any(c['op'] in ('dig','draw','ground_withdraw') for c in base.sent))

    def test_named_working_uses_fresh_near_side_if_its_preferred_far_side_is_worked(self):
        fixture=TheSensesAndTheTools()
        ctx=fixture.context(fixture.engine(heights=lambda x,z:-.1 if math.hypot(x,z)>=1.75 and math.hypot(x,z-1.8)<=.55 else 0.))
        ctx.routine=machine_routine.Routine('rover',{'kind':'dig','places':{'site':[0.,1.8]}})
        bite=machine_tools._bite(ctx,{'place':'site'})
        self.assertIn('point',bite)
        self.assertLess(math.hypot(*bite['point']),1.8)
        self.assertEqual(0.,ctx.survey(*bite['point'])['ground_m'])

    def context(self, field=None, obstacles=()):
        self.commands=[]
        def ask(**command):
            self.commands.append(command)
            if command['op']=='survey':
                x,z=command['at']
                return {'survey':(field(x,z) if field else {'on_the_ground':True,'ground_m':0.,'slope_deg':0.,'water':None})}
            return {'program':{'doing':command.get('doing'),'why':command.get('why')}}
        body={'name':'rover','position_m':[0,.5,0],'dimensions_m':[.5,.5,.7],
              'orientation_wxyz':[1,0,0,0]}
        return machine_senses.Context(a_program(at_m=[0,.5,0],height_m=.5,power=True,climb_deg=12),
                                      bodies=[body,*obstacles],ask=ask,terrain_declared=True)

    def test_observed_geometry_routes_around_solid_without_mutation_or_remote_queries(self):
        import machine_navigation as nav
        box={'name':'wall','position_m':[2,.5,0],'dimensions_m':[1,1,1],'orientation_wxyz':[1,0,0,0]}
        ctx=self.context(obstacles=[box]);before=deepcopy(ctx.bodies)
        route=nav.waypoint(ctx,[5,0])
        self.assertNotIn('blocked',route)
        self.assertTrue(any(abs(p[1])>1 for p in route['path']),route)
        for p in route['path']:
            self.assertGreaterEqual(math.hypot(max(1.5-p[0],0,p[0]-2.5),max(-.5-p[1],0,p[1]-.5)),route['radius_m'])
        self.assertEqual(before,ctx.bodies)
        self.assertLessEqual(route['surveys'],nav.MAX_SURVEYS)
        self.assertTrue(all(c['op']=='survey' and math.hypot(*c['at'])<=nav.LOOK_M+1e-9 for c in self.commands))

    def test_actual_radius_does_not_inflate_when_the_assembly_rotates(self):
        import machine_navigation as nav
        ctx=self.context();original=nav.waypoint(ctx,[5,0])
        ctx.bodies[0]['orientation_wxyz']=[math.cos(math.pi/8),0,math.sin(math.pi/8),0]
        rotated=nav.waypoint(ctx,[5,0])
        self.assertAlmostEqual(original['radius_m'],rotated['radius_m'],places=12)
        self.assertAlmostEqual(math.hypot(.25,.35),rotated['radius_m'],places=12)

    def test_valid_short_final_leg_is_not_rejected_for_small_distance_improvement(self):
        import machine_navigation as nav
        ctx=self.context()
        route=nav.waypoint(ctx,[1.55,0],(0,1.))
        self.assertNotIn('blocked',route);self.assertTrue(route['final'])
        self.assertGreater(math.hypot(*route['target']),nav.WAYPOINT_NEAR_M)

    def test_dry_drop_within_probe_reach_is_predicted_before_the_occupied_footprint(self):
        import machine_navigation as nav
        def ground(x,z):
            return {'on_the_ground':True,'ground_m':-.3 if x>2 and abs(z)<1 else 0.,
                    'slope_deg':0.,'ground_gradient_xz':[0.,0.],'water':None}
        ctx=self.context(field=ground)
        ctx.program['sensors']=[{'kind':'ground','at_m':[1.5,.5,0.],'depth_m':.12}]
        route=nav.waypoint(ctx,[4,0])
        self.assertNotIn('blocked',route)
        self.assertTrue(any(abs(p[1])>=1 for p in route['path']),route)
        # This bounded plan may end at the visible frontier. Check the issued
        # leg and its turn directly, rather than requiring a complete map path.
        dx,dz=route['target'];yaw=math.atan2(dx,dz)
        for k in range(17):
            turn=yaw*k/16
            self.assertEqual(0.,ground(1.5*math.cos(turn),-1.5*math.sin(turn))['ground_m'])
            self.assertEqual(0.,ground(dx*k/16+1.5*math.cos(yaw),
                                      dz*k/16-1.5*math.sin(yaw))['ground_m'])
        self.assertLessEqual(route['surveys'],nav.MAX_SURVEYS)

    def retreat_context(self,wet=False):
        def field(x,z):
            return {'on_the_ground':True,'ground_m':-.3 if z>1.3 else 0.,
                    'ground_gradient_xz':[0.,0.],
                    'water':{'depth_m':.2} if wet and z<-.7 else None}
        ctx=self.context(field=field)
        ctx.program['sensors']=[{'kind':'ground','at_m':[0,.5,1.5],'depth_m':.12,'stops':1,'sees':True},
            *[{'kind':'ground','at_m':[x,.5,-1.],'depth_m':.12,'stops':-1,'sees':False} for x in (-.3,.3)]]
        return ctx

    def test_blocked_front_can_retreat_on_surveyed_dry_rear_ground_but_not_wet_or_blind(self):
        import machine_navigation as nav
        route=nav.waypoint(self.retreat_context(),[0,4])
        self.assertTrue(route['reverse']);self.assertEqual([0.,-.5],route['target'])
        self.assertLessEqual(route['surveys'],nav.MAX_SURVEYS)
        self.assertTrue(all(c['op']=='survey' for c in self.commands))
        wet=nav.waypoint(self.retreat_context(wet=True),[0,4])
        self.assertIn('blocked',wet);self.assertNotIn('reverse',wet)
        blind=self.retreat_context();blind.program['sensors']=blind.program['sensors'][:1]
        self.assertIn('blocked',nav.waypoint(blind,[0,4]))
        moving=self.retreat_context();moving.program['speed_m_s']=.3
        result=machine_tools.go_to(moving,machine_tools.Call('go_to',{'point':[0,4]},'routine'))
        self.assertTrue(result['blocked_route']);self.assertEqual('waiting',self.commands[-1]['doing'])

    def test_retreat_stops_on_actual_distance_waits_for_brakes_and_restores_step_and_load(self):
        ctx=self.retreat_context();declaration={'kind':'custom','hopper_kg':20,
            'steps':[{'do':'go_to','args':{'point':[0,4]},'until':'arrived'},
                     {'do':'dig','until':'load_full','repeat':True}]}
        r=machine_routine.Routine('rover',declaration);ctx.routine=r
        r.load_in(0,0,3,{'copper ore':3});before=deepcopy(r.load_reading())
        r.tick(ctx);self.assertEqual('backing off',self.commands[-1]['doing'])
        ctx.program.update(asked={'by':'routine','doing':'backing off'},at_m=[0,.5,-.6],speed_m_s=.3)
        r.tick(ctx);self.assertEqual('waiting',self.commands[-1]['doing'])
        self.assertTrue(r.frame.issued['reverse_stopping']);saved=deepcopy(r.record())
        restored=machine_routine.Routine('rover',declaration);restored.restore(saved)
        self.assertEqual(saved,restored.record());ctx.routine=restored
        ctx.program.update(asked={'by':'routine','doing':'waiting'})
        count=len(self.commands);ctx.t=3;restored.tick(ctx)
        self.assertEqual(count,len(self.commands));self.assertEqual(0,restored.frame.step)
        self.assertEqual(before,restored.load_reading())
        self.assertFalse(any(c['op'] in ('dig','draw','ground_withdraw') for c in self.commands))

    def test_actual_departure_from_surveyed_leg_brakes_before_replanning_without_digging(self):
        ctx=self.context();r=machine_routine.Routine('rover',{'kind':'custom','hopper_kg':20,
            'steps':[{'do':'go_to','args':{'point':[4,0]},'until':'arrived'},
                     {'do':'dig','until':'load_full','repeat':True}]})
        ctx.routine=r;r.load_in(0,0,3,{'copper ore':3})
        r.frame.issued={'navigation':{'path':[[0,0],[4,0]],'target':[4,0],'final':True}}
        ctx.program.update(at_m=[1,.5,1],speed_m_s=.4,asked={'by':'routine','doing':'approaching'})
        r.tick(ctx)
        self.assertEqual('waiting',self.commands[-1]['doing'])
        self.assertEqual(1.,r.frame.issued['navigation']['cross_track_m'])
        ctx.t=30;ctx.program['asked']={'by':'routine','doing':'waiting'}
        count=len(self.commands);r.tick(ctx)
        self.assertEqual(count,len(self.commands),'Moving rover cannot issue a fresh turn')
        self.assertEqual(0,r.frame.step);self.assertEqual(3.,r.kg)
        self.assertFalse(any(c['op']=='dig' for c in self.commands))

    def test_probe_heading_allows_a_parallel_route_but_rejects_a_hazardous_turn(self):
        import machine_navigation as nav
        def ground(x,z):
            return {'on_the_ground':True,'ground_m':-.3 if x>1 else 0.,
                    'ground_gradient_xz':[0.,0.],'water':None}
        ctx=self.context(field=ground)
        ctx.program['sensors']=[{'kind':'ground','at_m':[0.,.5,1.5],'depth_m':.12}]
        straight=nav.waypoint(ctx,[0,4])
        self.assertNotIn('blocked',straight)
        self.assertEqual(0.,straight['target'][0])
        self.assertGreater(straight['target'][1],1.)
        toward_drop=nav.waypoint(ctx,[4,0])
        if 'blocked' not in toward_drop:
            # Its probe must remain on the high side of the edge throughout
            # the issued straight leg, including the initial turn.
            dx,dz=toward_drop['target'];yaw=math.atan2(dx,dz)
            for k in range(9):
                self.assertLessEqual(1.5*math.sin(yaw*k/8),1.)
                self.assertLessEqual(dx*k/8+1.5*math.sin(yaw),1.)

    def test_arrival_waits_for_actual_braking_and_failed_drive_cannot_advance_to_dig(self):
        ctx=self.context();declaration={'kind':'custom','hopper_kg':20,
            'steps':[{'do':'go_to','args':{'point':[5,0]},'until':'arrived','retries':0},
                     {'do':'dig','until':'load_full','repeat':True}]}
        r=machine_routine.Routine('rover',declaration);ctx.routine=r
        r.frame.issued={'navigation':{'final':True}}
        ctx.program.update(doing='waiting',speed_m_s=.2,asked={'by':'routine','doing':'approaching'})
        self.assertIsNone(r.tick(ctx));self.assertEqual(0,r.frame.step)
        ctx.program.update(speed_m_s=0,asked=None)
        r.tick(ctx);self.assertTrue(r.frame.issued['drive_failed'])
        ctx.program.update(asked={'by':'routine','doing':'waiting'})
        for t in (1,3,30,300):ctx.t=t;r.tick(ctx)
        self.assertEqual(0,r.frame.step)
        self.assertFalse(any(c['op']=='dig' for c in self.commands))
        restored=machine_routine.Routine('rover',declaration);restored.restore(r.record())
        self.assertEqual(r.record(),restored.record())
        r.resume();self.assertIsNone(r.frame.issued)

    def test_wet_or_unreported_ground_is_not_a_route_and_loaded_machine_holds(self):
        ctx=self.context(field=lambda x,z:{'on_the_ground':False})
        declaration={'kind':'custom','hopper_kg':20,
            'steps':[{'do':'go_to','args':{'point':[5,0]},'until':'arrived'},
                     {'do':'dig','until':'load_full','repeat':True}]}
        r=machine_routine.Routine('rover',declaration)
        ctx.routine=r;r.load_in(0,0,3,{'copper ore':3});load=deepcopy(r.load_reading())
        did=r.tick(ctx);self.assertTrue(did['blocked_route'])
        self.assertEqual('waiting',self.commands[-1]['doing']);self.assertEqual(0,self.commands[-1]['for_s'])
        ctx.program.update(doing='waiting',asked={'by':'routine','doing':'waiting'})
        for t in (1,2,3,4,6,9,12):ctx.t=t;r.tick(ctx)
        self.assertEqual(0,r.frame.step);self.assertEqual(load,r.load_reading())
        self.assertTrue(all(c['op'] in ('survey','behave') for c in self.commands))
        restored=machine_routine.Routine('rover',declaration);restored.restore(r.record())
        self.assertEqual(r.record(),restored.record())

    def test_waypoint_waiting_replans_and_survives_restore_without_finishing_requested_place(self):
        ctx=self.context();declaration={'kind':'custom',
            'steps':[{'do':'go_to','args':{'point':[9,0]},'until':'arrived'}]}
        r=machine_routine.Routine('rover',declaration)
        ctx.routine=r;r.frame.issued={'navigation':{'final':False,'target':[2,0]}}
        ctx.program.update(doing='waiting',asked={'by':'routine','doing':'approaching'})
        ctx.t=4;r.tick(ctx)
        self.assertEqual(0,r.frame.step);self.assertFalse(r.frame.issued['navigation']['final'])
        self.assertEqual(.4,self.commands[-1]['near_m'])
        restored=machine_routine.Routine('rover',declaration);restored.restore(r.record())
        self.assertEqual(r.record(),restored.record())

    def test_partial_native_update_keeps_static_geometry_and_actual_removals(self):
        brains=rover_brain.Brains(lambda:None);brains.spec={'terrain':{'generate':'flat'}}
        static={'name':'wall','position_m':[2,.5,0],'dimensions_m':[1,1,1]}
        session=SimpleNamespace(state={'bodies':[static,{'name':'rover','position_m':[0,.5,0]}],'cell_size_m':.05})
        p=a_program(at_m=[0,.5,0],power=False)
        reply={'partial':True,'t':1,'bodies':[session.state['bodies'][-1]],'machines':{'programs':[p]}}
        brains.listen(session,reply)
        brain=brains.of('rover');self.assertIn(static,brain.bodies);self.assertTrue(brain.terrain_declared)
        session.state['bodies']=session.state['bodies'][1:];brains.listen(session,dict(reply,gone=['wall']))
        self.assertNotIn(static,brain.bodies)

    def test_open_replacement_brains_receive_native_observations_before_first_clock_step(self):
        brains=rover_brain.Brains(lambda:None)
        spec={'terrain':{'generate':'flat'},'machines':{'programs':[{'name':'rover'}]}}
        p=a_program(at_m=[3.,.5,4.],power=False)
        body={'name':'rover','position_m':p['at_m'],'dimensions_m':[.5,.5,.7]}
        opened={'t':0.,'bodies':[body],'machines':{'programs':[p]}}
        session=SimpleNamespace(state={'bodies':[body],'cell_size_m':.1})
        brains.opened(spec)
        self.assertIsNone(brains.of('rover').before)
        brains.settle(opened,session)
        brain=brains.of('rover')
        self.assertEqual(p,brain.before)
        self.assertEqual([body],brain.bodies)
        self.assertTrue(brain.terrain_declared)
        self.assertEqual(.1,brain.cell_m)


class TheScriptedServer(unittest.TestCase):
    """The stand-in speaks the API the client speaks."""

    def test_the_client_reads_its_answers(self):
        httpd = scripted_jev_server.serve(0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        client = rover_brain.JevClient("scripted", url=f"http://127.0.0.1:{httpd.server_port}/v1/systemone")
        ctx = machine_senses.Context(program=sees(a_program(), 1))
        answers = client.ask(rover_brain.state_of(ctx, "water ahead on its left", []), rover_brain.questions_for("roam"))
        decision = rover_brain.decide(answers, "water ahead on its left")
        self.assertEqual("back_off", decision["call"]["tool"])
        self.assertEqual(("come_here", 0.9, "jev"), rover_talk.classify(client, "come over here"))


if __name__ == "__main__":
    if os.environ.get("BANJO_ROVER_LIVE_TESTS") == "required" and not (ENGINE and ENGINE.is_file()):
        raise RuntimeError("BANJO_LIVE_ENGINE must be built for the required live rover tests")
    unittest.main()
