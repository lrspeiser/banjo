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
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground"), str(ROOT / "tests")]
import live_session, room_store, rover_brain, rover_talk, world_room   # noqa: E402
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


def sees(program: dict, side: int, mm: float = 12.0) -> dict:
    program = deepcopy(program)
    for s in program["sensors"]:
        if s["side"] == side:
            s.update(sees=True, reading_m=mm / 1000.0)
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
                "stuck": {"type": "noul", "noul": 0.1},
                "battery": {"type": "score", "score": 0.0, "legend": {"0": "fine", "1": "low", "2": "urgent"}}}
    ask.asked = asked
    return ask


class WhatHappensToIt(unittest.TestCase):
    """What is noticed between two readings of the program (situations)."""

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
        self.assertEqual({"doing": "backing off", "for_s": 1.5,
                          "why": "Jev said back off (81% sure) when water ahead on its left"}, sure["ask"])
        self.assertEqual(("back_off", 0.81, 0.1, "fine"), (sure["pick"], sure["confidence"], sure["stuck"], sure["battery"]))
        unsure = rover_brain.decide(jev_says("wait", 0.4)(None, rover_brain.QUESTIONS), "x")
        self.assertIsNone(unsure["ask"])
        self.assertIn("too unsure", unsure["said"])
        odd = rover_brain.decide({"next": {"choice": "fly", "confidence": 0.99}}, "x")
        self.assertIsNone(odd["ask"])
        self.assertIn("no pick it knows", odd["said"])

    def test_the_questions_are_made_from_the_kind_of_program(self):
        questions = rover_brain.questions_for("roam")
        self.assertEqual(["go_on", "back_off", "turn_left", "turn_right", "wait"], list(questions["next"]["criteria"]))
        self.assertEqual({"next", "stuck", "battery"}, set(questions))
        self.assertIn("rover", questions["next"]["instructions"])
        # An unknown kind is asked as a rover is, rather than nothing.
        self.assertEqual(questions, rover_brain.questions_for("hunt"))

    def test_the_state_jev_reads_is_the_machine_and_what_struck_it(self):
        machines = {"controls": [{"id": 1, "condition": "", "speed_rpm": 40.0, "power": True, "direction": 1,
                                  "setting": 1.0}, {"id": 2, "condition": ""}]}
        state = rover_brain.state_of(sees(a_program(), -1), machines,
                                     [{"struck": "rover: left wheel", "by": "stone", "closing_speed_m_s": 0.5},
                                      {"struck": "pane", "by": "ball", "closing_speed_m_s": 9.0}], "stone struck it", [])
        self.assertEqual("stone struck it", state["event"])
        self.assertEqual(("roam", "going forward"), (state["machine"]["kind"], state["machine"]["doing"]))
        self.assertEqual([{"side": "left", "water_under_it_mm": 0, "sees_water": False},
                          {"side": "right", "water_under_it_mm": 12, "sees_water": True}], state["machine"]["water_sensors"])
        self.assertEqual(40.0, state["machine"]["wheels"][0]["speed_rpm"])
        self.assertEqual(["stone"], [s["by"] for s in state["struck"]])


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
        app = SimpleNamespace(live=SimpleNamespace(act=lambda body: (sent.append(body), {"asked": "applied"})[1]))
        brains = rover_brain.Brains(lambda: None)
        brains.brains["rover"] = brain
        brains.before(app, {"op": "poses"})
        self.assertEqual([], sent, "only a step applies what was decided")
        brains.before(app, {"session": "s", "op": "step"})
        self.assertEqual([{"session": "s", "op": "behave", "program": 1, "sender": "jev", "seq": 1,
                           "doing": "turning right", "for_s": 2.5,
                           "why": "Jev said turn right (70% sure) when water ahead on its left"}], sent)
        [decision] = brain.decisions
        self.assertEqual(("applied", "turn_right"), (decision["applied"], decision["pick"]))
        answer = {}
        brains.attach({"op": "step"}, answer)
        self.assertEqual("rover", answer["brains"][0]["name"])
        self.assertEqual(1, len(answer["brains"][0]["decisions"]))
        brains.attach({"op": "step"}, again := {})
        self.assertNotIn("brains", again, "the page hears of a brain once per change")
        brains.before(app, {"session": "s", "op": "step"})
        self.assertEqual(1, len(sent), "a decision is applied once")

    def test_a_jev_that_fails_leaves_the_reflexes_in_charge(self):
        def broken(state, questions):
            raise ValueError("Jev answered HTTP 529")
        brain = rover_brain.Brain("rover", rover_brain.JevClient("unused"), "jev")
        brain.observe(a_program(), None, [], 0.0, ask=broken)
        brain.observe(sees(a_program(), -1), None, [], 0.1, ask=broken)
        self.wait_for(brain)
        decision = brain.take()
        self.assertIsNone(decision["ask"])
        self.assertIn("HTTP 529", decision["said"])

    def test_without_a_key_the_mode_is_reflex_and_jev_cannot_be_pressed(self):
        brains = rover_brain.Brains(lambda: None)
        self.assertEqual("reflex", brains.of("rover").mode)
        with self.assertRaisesRegex(ValueError, "TYPESAFE_API_KEY"):
            brains.request({"program": "rover", "mode": "jev"})
        with self.assertRaisesRegex(ValueError, "reflex"):
            brains.request({"program": "rover", "mode": "sideways"})
        self.assertEqual("reflex", brains.request({"program": "rover"})["mode"])
        # With one, Jev is the default, and a mode set is kept for the next room.
        keyed = rover_brain.Brains(lambda: rover_brain.JevClient("k"))
        self.assertEqual("jev", keyed.of("rover")["mode"] if isinstance(keyed.of("rover"), dict) else keyed.of("rover").mode)
        keyed.request({"program": "rover", "mode": "reflex"})
        keyed.opened()
        self.assertEqual("reflex", keyed.of("rover").mode)


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
            if any(d.get("applied") == "applied" for d in brain.decisions):
                break
        self.assertTrue(self.ask.asked, "something happened to it in a minute of roaming")
        events = [d["event"] for d in brain.decisions]
        print(f"\n    Jev was asked {len(self.ask.asked)} times: {events}")
        applied = [d for d in brain.decisions if d.get("applied") == "applied"]
        self.assertTrue(applied, f"a pick was done: {list(brain.decisions)}")
        self.assertTrue(all(d["pick"] == "back_off" for d in applied))
        # What Jev read was the rover, with the event named.
        state, questions = self.ask.asked[0]
        self.assertEqual("roam", state["machine"]["kind"])
        self.assertIn(state["event"], events)
        self.assertEqual({"next", "stuck", "battery"}, set(questions))
        # The program said Jev asked it, and, the while up, its reflexes had it
        # back: no ask stands two seconds on.
        program = self.program()
        seen_jev = any("Jev said back off" in d["ask"]["why"] for d in applied)
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
        self.assertIn(opened["program"]["doing"], ("turning left", "turning right"))
        self.assertTrue(opened["reply"].startswith("I am turning"), opened["reply"])
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


class TheScriptedServer(unittest.TestCase):
    """The stand-in speaks the API the client speaks."""

    def test_the_client_reads_its_answers(self):
        httpd = scripted_jev_server.serve(0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        client = rover_brain.JevClient("scripted", url=f"http://127.0.0.1:{httpd.server_port}/v1/systemone")
        answers = client.ask(rover_brain.state_of(sees(a_program(), 1), None, [], "water ahead on its left", []),
                             rover_brain.questions_for("roam"))
        decision = rover_brain.decide(answers, "water ahead on its left")
        self.assertEqual("backing off", decision["ask"]["doing"])
        self.assertEqual(("come_here", 0.9, "jev"), rover_talk.classify(client, "come over here"))


if __name__ == "__main__":
    if os.environ.get("BANJO_ROVER_LIVE_TESTS") == "required" and not (ENGINE and ENGINE.is_file()):
        raise RuntimeError("BANJO_LIVE_ENGINE must be built for the required live rover tests")
    unittest.main()
