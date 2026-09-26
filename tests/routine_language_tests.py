"""A routine that responds, and standing requests (docs/machine-world.md):
the conditions a routine can watch for, read off the senses; steps with
`when` and `unless`; a `watch` whose steps interrupt the routine the moment
its condition comes to hold; orders a person gives, written as steps of the
routine language, run before the machine's own round, queued, cancelled and
reported when done; and, in the real engine, the mine's rover told to go
somewhere and its drone told to bring copper, both reporting back.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tests/routine_language_tests.py
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground")]
import mcp  # noqa: E402,F401
from mcp import workshop_machines  # noqa: E402
import fracture_lab, inventory, live_session, machine_conditions as conditions, machine_goods  # noqa: E402
import machine_routine, machine_senses as senses, room_store, rover_brain, rover_talk  # noqa: E402

ENGINE = Path(os.environ["BANJO_LIVE_ENGINE"]).resolve() if os.environ.get("BANJO_LIVE_ENGINE") else None
DT = 1 / 240
MINE = ROOT / "playground" / "rooms" / "tests-mine.json"


class FakeEngine:
    """An engine that answers an ask with a waiting program, and remembers
    what it was asked."""

    def __init__(self):
        self.sent = []

    def __call__(self, **command):
        self.sent.append(command)
        if command.get("op") == "behave":
            return {"program": {"doing": "waiting" if command.get("doing") != "approaching" else "going forward",
                                "why": command.get("why", "")}}
        return {}


def context(routine, program=None, t=0.0, goods=None, person=None, engine=None):
    program = {"id": 1, "power": True, "charge_share": 0.9, "at_m": [0.0, 0.5, 0.0], "heading_deg": 0.0,
               "sensors": [], **(program or {})}
    return senses.Context(program=program, ask=engine or FakeEngine(), routine=routine, t=t, goods=goods,
                          person=person, machines={"controls": []})


class Conditions(unittest.TestCase):
    def test_conditions_are_checked_and_read_off_the_senses(self):
        self.assertEqual("hopper_full", conditions.checked("hopper_full"))
        self.assertEqual({"is": "battery_below", "share": 0.3}, conditions.checked({"is": "battery_below", "share": "0.3"}))
        self.assertEqual({"all": ["hopper_full", {"not": "person_near"}]},
                         conditions.checked({"all": ["hopper_full", {"not": "person_near"}]}))
        for broken, why in (("hungry", "no condition called"), ({"is": "battery_below", "kg": 1}, "takes"),
                            ({"not": "a", "is": "b"}, "nothing else"), ({"all": []}, "1 to 8"),
                            ({"is": "battery_below", "share": 3}, "out of range")):
            with self.subTest(why=why), self.assertRaisesRegex(ValueError, why):
                conditions.checked(broken)
        r = machine_routine.Routine("m", {"kind": "custom", "hopper_kg": 10.0, "places": {"depot": [3.0, 0.0]},
                                          "steps": [{"do": "hold_still", "until": 1}]})
        goods = machine_goods.Goods({"goods": {"stockpiles": [{"name": "d", "at_m": [3.0, 0.0], "holds": {"copper": 2.0}}]}})
        ctx = context(r, goods=goods, person={"standing_m": [1.0, 0.0, 0.0]})
        self.assertTrue(conditions.holds(ctx, "hopper_empty"))
        self.assertFalse(conditions.holds(ctx, "hopper_full"))
        r.load_in(0.0, 0.0, 9.6, {"copper ore": 9.6})
        self.assertTrue(conditions.holds(ctx, "hopper_full"))
        self.assertTrue(conditions.holds(ctx, {"is": "hopper_has", "substance": "copper ore", "kg": 5}))
        self.assertTrue(conditions.holds(ctx, {"is": "pile_has", "place": "depot", "substance": "copper", "kg": 2}))
        self.assertFalse(conditions.holds(ctx, {"is": "pile_has", "place": "depot", "kg": 3}))
        self.assertFalse(conditions.holds(ctx, {"is": "pile_empty", "place": "depot"}))
        self.assertTrue(conditions.holds(ctx, "person_near"))
        self.assertFalse(conditions.holds(ctx, {"is": "person_near", "m": 0.5}))
        self.assertFalse(conditions.holds(ctx, {"is": "at_place", "place": "depot"}))
        self.assertTrue(conditions.holds(ctx, {"is": "at_place", "place": "depot", "within_m": 4}))
        self.assertTrue(conditions.holds(ctx, {"is": "battery_above", "share": 0.5}))
        self.assertTrue(conditions.holds(ctx, {"any": ["night", {"not": "water_ahead"}]}))
        self.assertFalse(conditions.holds(ctx, {"is": "at_place", "place": "moon"}), "a place it does not know is false")
        self.assertEqual("pile has (place depot, kg 3)", conditions.described({"is": "pile_has", "place": "depot", "kg": 3}))
        self.assertTrue(all(c["description"] for c in conditions.catalogue()))


class TheRunner(unittest.TestCase):
    def test_when_and_unless_skip_a_step_as_it_is_issued(self):
        r = machine_routine.Routine("m", {"kind": "custom", "hopper_kg": 10.0, "places": {},
                                          "steps": [{"do": "hold_still", "args": {"for_s": 1.0}, "until": "asked_done",
                                                     "when": "hopper_full"},
                                                    {"do": "back_off", "until": "asked_done", "unless": "hopper_empty"},
                                                    {"do": "hold_still", "until": 2}]})
        engine = FakeEngine()
        ctx = context(r, engine=engine)
        self.assertIsNone(r.tick(ctx))
        self.assertIsNone(r.tick(ctx))
        self.assertEqual(["step 1 done: skipped: hopper full does not hold",
                          "step 2 done: skipped: hopper empty holds"], list(r.notes)[:2])
        did = r.tick(ctx)
        self.assertEqual("asked to be waiting for 3 s", did["did"])
        self.assertEqual(1, len([c for c in engine.sent if c.get("op") == "behave"]))

    def test_a_watch_interrupts_on_the_rising_edge_and_the_routine_resumes(self):
        r = machine_routine.Routine("m", {
            "kind": "custom", "hopper_kg": 10.0, "places": {"depot": [3.0, 0.0]},
            "steps": [{"do": "go_to", "args": {"place": "depot"}, "until": "arrived"}],
            "watch": [{"when": {"is": "battery_below", "share": 0.3},
                       "do": [{"do": "hold_still", "args": {"for_s": 5.0}, "until": "asked_done"}]}]})
        engine = FakeEngine()
        program = {"charge_share": 0.9}
        ctx = context(r, program=program, engine=engine)
        did = r.tick(ctx)
        self.assertEqual("go_to", engine.sent[-1].get("op") and "go_to" if engine.sent[-1].get("doing") == "approaching" else "no")
        # The battery drops: the watch fires once, its step goes first.
        ctx.program["charge_share"] = 0.2
        ctx.program["asked"] = {"by": "routine", "doing": "approaching"}
        did = r.tick(ctx)
        self.assertEqual("asked to be waiting for 5 s", did["did"])
        self.assertEqual("watch 1", r.summary()["on"])
        # Still low: it does not fire again while its steps run, nor after
        # them until it has gone false and come back.
        ctx.program["asked"] = {"by": "routine", "doing": "waiting"}
        self.assertIsNone(r.tick(ctx))
        ctx.program["asked"] = None
        self.assertIsNone(r.tick(ctx))              # its step done; back to the routine
        self.assertIsNone(r.summary()["on"])
        self.assertIn("watch 1 done; back to routine", list(r.notes))
        did = r.tick(ctx)
        self.assertEqual("asked to go to depot, and stop a metre off", did["did"], "the interrupted step, again")
        ctx.program["asked"] = {"by": "routine", "doing": "approaching"}
        self.assertIsNone(r.tick(ctx), "still low, no second firing")
        ctx.program["charge_share"] = 0.8
        self.assertIsNone(r.tick(ctx))
        ctx.program["charge_share"] = 0.1
        did = r.tick(ctx)
        self.assertEqual("asked to be waiting for 5 s", did["did"], "fires again on a new rising edge")
        restart = machine_routine.Routine("m", {
            "kind": "custom", "hopper_kg": 10.0, "places": {},
            "steps": [{"do": "hold_still", "until": 1}, {"do": "back_off", "until": "asked_done"}],
            "watch": [{"when": "person_near", "do": [{"do": "hold_still", "until": 1}], "then": "restart"}]})
        ctx = context(restart, engine=FakeEngine())
        restart.tick(ctx)
        ctx.t = 2.0
        restart.tick(ctx)                              # step 1 done
        self.assertEqual(2, restart.summary()["step"])
        ctx.person = {"standing_m": [0.5, 0.0, 0.5]}
        restart.tick(ctx)
        ctx.t = 4.0
        restart.tick(ctx)                              # the watch's step is up; restart from the top
        self.assertEqual(1, restart.summary()["step"])

    def test_orders_queue_run_first_cancel_and_are_reported(self):
        r = machine_routine.Routine("m", {"kind": "custom", "hopper_kg": 10.0, "places": {"depot": [3.0, 0.0]},
                                          "steps": [{"do": "hold_still", "until": 1}]})
        engine = FakeEngine()
        ctx = context(r, engine=engine)
        first = r.order("go to the depot", [{"do": "go_to", "args": {"place": "depot"}, "until": "arrived"}])
        second = r.order("wait", [{"do": "hold_still", "args": {"for_s": 2.0}, "until": "asked_done"}])
        self.assertEqual((1, 2, 1), (first["order"], second["order"], second["queued_behind"]))
        self.assertEqual([2, 1], [o["order"] for o in r.orders()])
        self.assertTrue(r.orders()[1]["running"])
        did = r.tick(ctx)
        self.assertEqual("asked to go to depot, and stop a metre off", did["did"], "the first order first")
        ctx.program["asked"] = {"by": "routine", "doing": "approaching"}
        ctx.program["doing"] = "waiting"
        self.assertIsNone(r.tick(ctx))                 # arrived: order 1 done
        self.assertEqual([{"name": "order 1", "order": 1, "at_step": 1}], list(r.finished))
        ctx.program["asked"] = None
        did = r.tick(ctx)
        self.assertEqual("asked to be waiting for 2 s", did["did"], "then the second")
        self.assertEqual(1, r.cancel_orders())
        self.assertEqual([], r.orders())
        self.assertEqual("routine", r.frame.name)
        # The brain says so in the chat, once.
        brain = rover_brain.Brain("m", None, "reflex", {"kind": "custom", "hopper_kg": 10.0,
                                                          "steps": [{"do": "hold_still", "until": 1}]})
        brain.routine = r
        brain.orders_given[1] = "go to the depot"
        brain.report_finished()
        brain.report_finished()
        self.assertEqual(["Done: go to the depot. Back to my rounds."], [t["said"] for t in brain.talk])

    def test_the_room_checks_a_watch_and_the_bench_keeps_one(self):
        spec = {"algorithm": "lattice", "cell_m": 0.05,
                "bodies": [{"name": "smelter", "shape": "box", "material": "concrete", "anchored": True,
                            "size_mm": [600, 800, 600], "center_mm": [0, 400, 0]}],
                "machines": {"stores": [{"name": "b", "body": "smelter", "capacity_j": 1000.0, "charge_j": 500.0,
                                         "voltage_v": 24.0}],
                             "programs": [{"name": "smelter", "kind": "still", "body": "smelter", "store": "b",
                                           "routine": {"kind": "custom", "places": {"here": [0, 0]},
                                                       "steps": [{"do": "hold_still", "until": 2, "when": "day"}],
                                                       "watch": [{"when": {"is": "battery_below", "share": 0.2},
                                                                  "do": [{"do": "hold_still", "until": 5}]}]}}]}}
        made = fracture_lab.validate(spec)["machines"]["programs"][0]["routine"]
        self.assertEqual("day", made["steps"][0]["when"])
        self.assertEqual(({"is": "battery_below", "share": 0.2}, "resume"), (made["watch"][0]["when"], made["watch"][0]["then"]))
        wrong = deepcopy(spec)
        wrong["machines"]["programs"][0]["routine"]["watch"] = [{"when": "day", "do": [{"do": "go_to", "args": {"place": "moon"}}]}]
        with self.assertRaisesRegex(ValueError, "a place it does not know"):
            fracture_lab.validate(wrong)
        record = workshop_machines.checked({"stores": [{"name": "b", "in": "deck", "capacity_j": 1000, "charge_j": 500,
                                                         "voltage_v": 24}], "motors": [], "controls": [],
                                            "programs": [{"kind": "still", "store": "b",
                                                          "routine": {"kind": "custom", "steps": [{"do": "hold_still", "until": 1}],
                                                                      "watch": [{"when": "night", "do": [{"do": "hold_still", "until": 1}]}]}}]})
        self.assertEqual("night", record["programs"][0]["routine"]["watch"][0]["when"])


class PlainWordOrders(unittest.TestCase):
    def test_plain_words_become_steps_over_the_places_it_knows(self):
        places, subs = {"source": [0, 0], "destination": [1, 1], "vein": [2, 2]}, ["copper", "copper ore"]
        steps = rover_talk.plain_order("bring copper from the source to the destination", places, subs)
        self.assertEqual(["go_to", "take", "go_to", "dump"], [s["do"] for s in steps])
        self.assertEqual({"place": "source", "substance": "copper"}, steps[1]["args"])
        self.assertEqual(["go_to"], [s["do"] for s in rover_talk.plain_order("go to the vein and wait", places, subs)])
        self.assertEqual(3, len(rover_talk.plain_order("make 3 batches", places, subs)))
        self.assertIsNone(rover_talk.plain_order("bring gold from the source to the destination", places, subs))
        self.assertIsNone(rover_talk.plain_order("bring copper from the moon to the destination", places, subs))
        self.assertIsNone(rover_talk.plain_order("sing me a song", places, subs))
        self.assertEqual("order", rover_talk.classify(None, "dig at the vein and dump it at the smelter intake")[0])
        self.assertEqual("cancel", rover_talk.classify(None, "never mind that")[0])
        self.assertEqual("take", rover_talk.classify(None, "take some copper")[0], "a take here and now is a tool, not an order")


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE is required")
class InTheMine(unittest.TestCase):
    """The mine's machines told things: the rover ordered to the smelter's
    intake, the drone ordered to bring copper, both reporting back; and a
    watch put on the rover that makes it hold still when a person comes near."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.spec = json.loads(MINE.read_text(encoding="utf-8"))
        rover = self.spec["machines"]["programs"][0]
        rover["routine"]["watch"] = [{"when": {"is": "person_near", "m": 3.0},
                                      "do": [{"do": "hold_still", "args": {"for_s": 4.0}, "until": "asked_done"}]}]
        self.live = live_session.Live()
        self.addCleanup(self.live.shutdown)
        self.room = SimpleNamespace(scene="tests-mine", spec=self.spec, chat=[], inventory=inventory.Inventory(),
                                    workshop_installs=[])
        self.brains = rover_brain.Brains(lambda: None)
        self.app = SimpleNamespace(live=self.live, live_holder="world", room=self.room, engine_path=ENGINE,
                                   runs_path=root / "runs", store=room_store.RoomStore(root / "rooms"),
                                   brains=self.brains, api_key="", model="",
                                   on_live_reply=lambda session, reply: self.brains.listen(session, reply))
        self.live.open(self.app, {"spec": self.spec})
        self.brains.opened(self.spec)

    def step(self, seconds, person=None, until=None):
        sid = self.live.session.id
        answer = None
        for _ in range(int(seconds * 4)):
            body = {"session": sid, "op": "step", "dt": DT, "n": 60, **({"person": person} if person else {})}
            self.brains.before(self.app, body)
            answer = self.live.act(body)
            self.brains.attach(body, answer)
            if until is not None and until():
                break
        return answer

    def test_orders_run_before_the_round_and_are_reported_and_a_watch_holds_it(self):
        programs = {p["name"]: p for p in self.live.session.send(op="step", dt=DT, n=1)["machines"]["programs"]}
        for seq, (name, p) in enumerate(programs.items(), 1):
            self.live.session.send(op="run", program=p["id"], sender="test", seq=seq, power=True)
        rover = self.brains.of("rover")
        person = {"standing_m": [8.0, 1.0, -9.0], "facing": [-1, 0, 0]}
        said = rover_talk.talk(self.app, {"program": "rover", "said": "go to the smelter intake", "person": person})
        self.assertTrue(said["reply"].startswith("Will do: go to smelter intake"), said["reply"])
        self.assertEqual(1, len(rover.routine.orders()))
        self.step(60, person=person, until=lambda: any(t.get("order_done") for t in rover.talk))
        done = [t["said"] for t in rover.talk if t.get("order_done")]
        print(f"\n    the rover: {done}; notes: {list(rover.routine.notes)[-4:]}")
        self.assertEqual(["Done: go to the smelter intake. Back to my rounds."], done)
        self.assertEqual([], rover.routine.orders())
        at = rover.before["at_m"]
        self.assertLess(((at[0] + 3.0) ** 2 + (at[2] + 8.0) ** 2) ** 0.5, 2.0, "it went there")
        # The person walks up to it: the watch holds it for four seconds.
        near = {"standing_m": [at[0] + 1.5, at[1], at[2]], "facing": [-1, 0, 0]}
        self.step(3, person=near, until=lambda: rover.routine.summary()["on"] == "watch 1")
        self.assertEqual("watch 1", rover.routine.summary()["on"], list(rover.routine.notes)[-4:])
        self.assertEqual("waiting", rover.before["doing"])
        # And the drone: an order in plain words over its places and the room's substances.
        drone = self.brains.of("drone")
        said = rover_talk.talk(self.app, {"program": "drone", "said": "bring copper from the source to the destination"})
        self.assertTrue(said["reply"].startswith("Will do: go to source; take source, copper"), said["reply"])
        said = rover_talk.talk(self.app, {"program": "drone", "said": "what are you doing?"})
        self.assertIn("1 order to do: bring copper", said["reply"])
        said = rover_talk.talk(self.app, {"program": "drone", "said": "never mind"})
        self.assertEqual("Dropped 1 order. Back to my rounds.", said["reply"])
        self.assertEqual([], drone.routine.orders())
        still = rover_talk.talk(self.app, {"program": "smelter", "said": "go to the vein"})
        self.assertIn("go nowhere", still["reply"])


if __name__ == "__main__":
    if os.environ.get("BANJO_ROVER_LIVE_TESTS") == "required" and not (ENGINE and ENGINE.is_file()):
        raise RuntimeError("BANJO_LIVE_ENGINE must be built for the required live routine tests")
    unittest.main()
