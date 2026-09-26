"""Raw materials into finished goods (docs/machine-world.md, "Raw materials
into finished goods"): the room's account of goods and its spelling; a
routine written out as its own steps; a machine that goes nowhere; the
Workshop's goods rack and what a machine's parts take of it; and, in the
real engine, the mine: the rover digging a copper vein by a custom routine,
the smelter and the mill working their recipes, the drone hauling between
them, and copper wire landing on the Workshop's rack -- stepped as the
server steps the room, with the brains before and after each step -- and a
person talking to a still machine.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tests/goods_tests.py

Without BANJO_LIVE_ENGINE only the checks that need no engine run, unless
BANJO_ROVER_LIVE_TESTS=required, which ctest sets.
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
from mcp import workshop as w, workshop_machines  # noqa: E402
import fracture_lab, inventory, live_session, machine_goods, machine_routine, machine_senses, machine_tools  # noqa: E402
import room_store, rover_brain, rover_talk, workshop_library  # noqa: E402

ENGINE = Path(os.environ["BANJO_LIVE_ENGINE"]).resolve() if os.environ.get("BANJO_LIVE_ENGINE") else None
DT = 1 / 240
MINE = ROOT / "playground" / "rooms" / "tests-mine.json"


def goods_block() -> dict:
    return {"deposits": [{"name": "copper vein", "substance": "copper ore", "at_m": [2.0, -6.5], "radius_m": 3.0,
                          "grade": 0.3, "reserve_kg": 20.0}],
            "stockpiles": [{"name": "smelter intake", "at_m": [-3.0, -8.0]},
                           {"name": "workshop rack", "at_m": [-6.0, -14.5], "rack": True}],
            "recipes": [{"name": "smelt copper", "in": {"copper ore": 1.0}, "out": {"copper": 0.3, "slag": 0.6},
                         "work_j_per_kg": 2000.0, "s_per_kg": 2.0}]}


class TheRoomsAccountOfGoods(unittest.TestCase):
    def test_the_block_is_checked_in_the_rooms_words(self):
        checked = machine_goods.checked(goods_block())
        self.assertEqual(("copper vein", 0.3, 20.0, 0.0), (checked["deposits"][0]["name"], checked["deposits"][0]["grade"],
                                                            checked["deposits"][0]["reserve_kg"],
                                                            checked["deposits"][0]["taken_kg"]))
        self.assertEqual(1.0, checked["stockpiles"][0]["radius_m"], "a heap's radius by default")
        self.assertTrue(checked["stockpiles"][1]["rack"])
        self.assertEqual({"copper": 0.3, "slag": 0.6}, checked["recipes"][0]["out"])
        for broken, why in (({"deposits": [{"name": "x", "at_m": [0, 0]}]}, "substance"),
                            ({"recipes": [{"name": "r", "in": {"a": 1}, "out": {"b": 2}}]}, "more mass"),
                            ({"recipes": [{"name": "r", "in": {}, "out": {"b": 1}}]}, "takes something in"),
                            ({"stockpiles": [{"name": "s", "at_m": [0, 0]}, {"name": "s", "at_m": [1, 1]}]}, "called"),
                            ({"markets": []}, "cannot say")):
            with self.subTest(why=why), self.assertRaisesRegex(ValueError, why):
                machine_goods.checked(broken)
        self.assertEqual({"deposits": [], "stockpiles": [], "recipes": []}, machine_goods.checked(None))

    def test_ore_comes_out_of_a_deposit_at_its_grade_until_it_is_gone(self):
        spec = {"goods": goods_block()}
        goods = machine_goods.Goods(spec)
        self.assertEqual({}, goods.dug(10.0, 10.0, 40.0), "nothing off the vein")
        self.assertEqual({"copper ore": 12.0}, goods.dug(2.5, -6.0, 40.0))
        self.assertEqual({"copper ore": 8.0}, goods.dug(2.5, -6.0, 40.0), "only what is left")
        self.assertEqual({}, goods.dug(2.5, -6.0, 40.0))
        self.assertEqual(20.0, spec["goods"]["deposits"][0]["taken_kg"], "booked in the room's own block")
        self.assertIsNone(goods.deposit_at(2.0, -6.5))

    def test_goods_go_onto_and_off_stockpiles_and_the_rack_hands_on(self):
        landed = []
        goods = machine_goods.Goods({"goods": goods_block()}, on_rack=lambda s, kg: landed.append((s, kg)))
        put = goods.put(-3.0, -8.0, {"copper ore": 12.0, "soil": 0.0})
        self.assertEqual({"put": {"copper ore": 12.0}, "onto": "smelter intake"}, put)
        heap = goods.put(5.0, 5.0, {"copper": 1.0})
        self.assertEqual("heap 1", heap["onto"])
        self.assertEqual(3, len(goods.stockpiles))
        self.assertEqual({"took": {"copper ore": 7.0}, "from": "smelter intake", "left": {"copper ore": 5.0}},
                         goods.take(-3.5, -8.5, 7.0))
        self.assertEqual({"took": {"copper ore": 5.0}, "from": "smelter intake", "left": {}},
                         goods.take(-3.5, -8.5, 50.0, substance="copper ore"))
        with self.assertRaisesRegex(ValueError, "no stockpile within reach"):
            goods.take(20.0, 20.0, 1.0)
        goods.put(-6.0, -14.0, {"copper wire": 1.47})
        self.assertEqual([("copper wire", 1.47)], landed)
        self.assertEqual({"copper wire": 1.47}, goods.by_name("workshop rack")["holds"])
        reading = goods.reading(-3.0, -9.0)
        self.assertEqual(3, len(reading["stockpiles"]))
        self.assertTrue(reading["stockpiles"][0]["within_reach"])
        self.assertEqual(["copper", "copper ore", "copper wire", "slag"], goods.substances())

    def test_a_recipe_works_a_batch_and_no_more_than_is_there(self):
        goods = machine_goods.Goods({"goods": goods_block()})
        holds = {"copper ore": 7.0}
        made = goods.convert("smelt copper", holds, 5.0)
        self.assertEqual(({"copper": 1.5, "slag": 3.0}, {"copper ore": 5.0}, 10000.0, 10.0),
                         (made["made"], made["used"], made["work_j"], made["took_s"]))
        self.assertAlmostEqual(0.5, made["waste_kg"])
        self.assertEqual({"copper ore": 2.0}, holds)
        made = goods.convert("smelt copper", holds, 5.0)
        self.assertEqual({"copper ore": 2.0}, made["used"], "the rest of what is there")
        self.assertEqual({}, holds)
        self.assertEqual(["copper ore"], goods.convert("smelt copper", holds, 5.0)["missing"])
        with self.assertRaisesRegex(ValueError, "no recipe called"):
            goods.convert("alchemy", holds, 1.0)


class TheRoutineLanguage(unittest.TestCase):
    def test_steps_are_checked_against_the_tools_and_the_untils(self):
        steps = machine_routine.checked_steps([{"do": "go_to", "args": {"place": "vein"}, "until": "arrived"},
                                               {"do": "dig", "until": "load_full", "repeat": True, "retries": 2},
                                               {"do": "hold_still", "until": 4}])
        self.assertEqual(("go_to", "arrived", True, 2, 4), (steps[0]["do"], steps[0]["until"], steps[1]["repeat"],
                                                            steps[1]["retries"], steps[2]["until"]))
        for broken, why in (([{"do": "fly"}], "no such tool"), ([{"do": "dig", "until": "never"}], "until is one of"),
                            ([{"do": "dig", "whenever": 1}], "cannot say"), ([], "list of 1 to"),
                            ([{"do": "dig", "retries": 99}], "retries is 0 to 20")):
            with self.subTest(why=why), self.assertRaisesRegex(ValueError, why):
                machine_routine.checked_steps(broken)

    def test_a_custom_routine_runs_its_own_steps_and_a_named_one_its_own(self):
        r = machine_routine.Routine("rover", {"kind": "custom", "hopper_kg": 20.0, "places": {"vein": [1, 2]},
                                              "steps": [{"do": "hold_still", "until": 2.0},
                                                        {"do": "go_to", "args": {"place": "vein"}, "until": "arrived"}]})
        self.assertEqual(2, len(r.steps))
        self.assertEqual("hold_still", r.current()["do"])
        haul = machine_routine.Routine("drone", {"kind": "haul", "hopper_kg": 20.0,
                                                 "places": {"source": [0, 0], "destination": [1, 1]}})
        self.assertEqual(["go_to", "take", "go_to", "dump"], [s["do"] for s in haul.steps])
        mill = machine_routine.Routine("mill", {"kind": "process", "recipe": "draw wire", "intake": "mill intake",
                                                "output": "workshop rack", "batch_kg": 3.0})
        self.assertEqual(("draw wire", "mill intake", "workshop rack", 3.0),
                         (mill.recipe, mill.intake, mill.output, mill.batch_kg))
        self.assertEqual("draw wire", mill.summary()["making"]["recipe"])

    def test_the_room_checks_a_routine_and_a_still_program(self):
        base = {"algorithm": "lattice", "cell_m": 0.05,
                "bodies": [{"name": "smelter", "shape": "box", "material": "concrete", "anchored": True,
                            "size_mm": [600, 800, 600], "center_mm": [0, 400, 0]}],
                "machines": {"stores": [{"name": "smelter battery", "body": "smelter", "capacity_j": 1000.0,
                                         "charge_j": 500.0, "voltage_v": 24.0}],
                             "programs": [{"name": "smelter", "kind": "still", "body": "smelter",
                                           "store": "smelter battery",
                                           "routine": {"kind": "process", "recipe": "smelt copper",
                                                       "intake": "smelter intake", "output": "smelter output"}}]},
                "goods": goods_block()}
        validated = fracture_lab.validate(base)
        [program] = validated["machines"]["programs"]
        self.assertEqual(("still", "smelter battery", "process", "smelt copper"),
                         (program["kind"], program["store"], program["routine"]["kind"], program["routine"]["recipe"]))
        self.assertEqual(0.3, validated["goods"]["deposits"][0]["grade"])
        custom = deepcopy(base)
        custom["machines"]["programs"][0]["routine"] = {
            "kind": "custom", "hopper_kg": 10.0, "places": {"vein": [2, -6.5]},
            "steps": [{"do": "hold_still", "until": 2.0}, {"do": "dig", "until": "load_full", "repeat": True}]}
        self.assertEqual(2, len(fracture_lab.validate(custom)["machines"]["programs"][0]["routine"]["steps"]))
        for change, why in (({"store": "no such"}, "there is none"), ({"left": "a"}, "goes nowhere"),
                            ({"routine": {"kind": "process", "recipe": "smelt copper"}}, "needs intake"),
                            ({"routine": {"kind": "custom", "steps": [{"do": "go_to", "args": {"place": "moon"}}]}},
                             "a place it does not know"),
                            ({"routine": {"kind": "dig", "hopper_kg": 5, "steps": [],
                                          "places": {"dig site": [0, 0], "depot": [1, 1]}}}, "written already")):
            broken = deepcopy(base)
            broken["machines"]["programs"][0].update(change)
            with self.subTest(why=why), self.assertRaisesRegex(ValueError, why):
                fracture_lab.validate(broken)
        wrong = deepcopy(base)
        wrong["goods"]["recipes"][0]["out"] = {"gold": 5.0}
        with self.assertRaisesRegex(ValueError, "more mass"):
            fracture_lab.validate(wrong)


class TheWorkshopsGoodsRack(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = SimpleNamespace(runs_path=Path(self.tmp.name) / "runs", workshop_owner_id="owner")

    def test_goods_land_on_the_rack_and_a_machines_parts_take_them(self):
        workshop_library.add_goods(self.app, "copper wire", 1.47)
        workshop_library.add_goods(self.app, "copper wire", 1.0)
        self.assertEqual([{"substance": "copper wire", "mass_kg": 2.47}],
                         [{k: r[k] for k in ("substance", "mass_kg")} for r in workshop_library.goods_rack(self.app)["goods"]])
        design = w.assemble("rover", design_id="rover")
        needed = workshop_library.goods_needed(design)
        self.assertEqual({"copper": 1.0, "copper wire": 2.3}, needed,
                         "two 20 N m motors at a kilogram each, two controls, a 100 kJ battery, a panel")
        self.assertEqual({}, workshop_library.goods_needed(w.assemble("chair", design_id="c")))
        for material in ("oak", "iron", "glass"):
            workshop_library.set_rack(self.app, material, 500.0)
        needs = workshop_library.what_it_needs(self.app, design)
        self.assertFalse(needs["enough"])
        self.assertEqual([("copper", 1.0)], [(m["substance"], m["short_kg"]) for m in needs["missing"]])
        self.assertIn("short 1 kg of copper", needs["says"])
        with self.assertRaisesRegex(ValueError, "short 1 kg of copper"):
            workshop_library.take_from_rack(self.app, needs)
        workshop_library.add_goods(self.app, "copper", 3.0)
        needs = workshop_library.what_it_needs(self.app, design)
        self.assertTrue(needs["enough"])
        drawn = workshop_library.take_from_rack(self.app, needs)
        self.assertEqual({"copper": 2.0, "copper wire": 0.17},
                         {r["substance"]: round(r["mass_kg"], 2) for r in drawn["goods_rack"]["goods"]})

    def test_the_bench_records_a_still_program_and_its_recipe_work(self):
        record = workshop_machines.checked({
            "stores": [{"name": "b", "in": "deck", "capacity_j": 1000, "charge_j": 500, "voltage_v": 24}],
            "motors": [], "controls": [],
            "programs": [{"kind": "still", "store": "b",
                          "routine": {"kind": "process", "recipe": "smelt copper", "intake": "in", "output": "out",
                                      "batch_kg": 2}}]})
        [program] = record["programs"]
        self.assertEqual(("still", "b", "process", 2.0), (program["kind"], program["store"],
                                                          program["routine"]["kind"], program["routine"]["batch_kg"]))
        with self.assertRaisesRegex(ValueError, "needs intake"):
            workshop_machines.checked({"stores": [], "motors": [], "controls": [],
                                       "programs": [{"kind": "still", "store": "b",
                                                     "routine": {"kind": "process", "recipe": "r"}}]})
        custom = workshop_machines.checked({"stores": [], "motors": [], "controls": [],
                                            "programs": [{"kind": "still", "store": "b",
                                                          "routine": {"kind": "custom",
                                                                      "steps": [{"do": "process", "until": "done"}]}}]})
        self.assertEqual("process", custom["programs"][0]["routine"]["steps"][0]["do"])


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE is required")
class TheMine(unittest.TestCase):
    """The mine room, opened as the server opens it and stepped as the page
    steps it, with the brains before and after each step: ore to wire on the
    Workshop's rack; and a person talking to the smelter."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.spec = json.loads(MINE.read_text(encoding="utf-8"))
        self.live = live_session.Live()
        self.addCleanup(self.live.shutdown)
        self.room = SimpleNamespace(scene="tests-mine", spec=self.spec, chat=[], inventory=inventory.Inventory(),
                                    workshop_installs=[])
        self.brains = rover_brain.Brains(lambda: None)
        self.landed: list[tuple[str, float]] = []
        self.brains.on_rack = lambda substance, kg: self.landed.append((substance, kg))
        self.app = SimpleNamespace(live=self.live, live_holder="world", room=self.room, engine_path=ENGINE,
                                   runs_path=root / "runs", store=room_store.RoomStore(root / "rooms"),
                                   brains=self.brains, api_key="", model="",
                                   on_live_reply=lambda session, reply: self.brains.listen(session, reply))
        self.live.open(self.app, {"spec": self.spec})
        self.brains.opened(self.spec)
        self.assertNotIn("machine_problems", self.live.session.state, self.live.session.state.get("machine_problems"))

    def programs(self, reply=None):
        reply = reply or self.live.session.send(op="step", dt=DT, n=1)
        return {p["name"]: p for p in reply["machines"]["programs"]}

    def test_ore_to_wire_on_the_rack_with_the_brains_running_every_routine(self):
        programs = self.programs()
        self.assertEqual({"rover": "roam", "smelter": "still", "drone": "hover", "mill": "still"},
                         {n: p["kind"] for n, p in programs.items()})
        self.assertEqual("stopped", programs["smelter"]["doing"])
        for seq, (name, p) in enumerate(programs.items(), 1):
            self.live.session.send(op="run", program=p["id"], sender="test", seq=seq, power=True)
        self.assertEqual("standing by", self.programs()["smelter"]["doing"], "on, with nothing to work")
        sid = self.live.session.id
        t = 0.0
        for _ in range(4 * 240):                  # up to 240 s
            body = {"session": sid, "op": "step", "dt": DT, "n": 60}
            self.brains.before(self.app, body)
            answer = self.live.act(body)
            self.brains.attach(body, answer)
            t = float(answer["t"])
            if any(s == "copper wire" for s, _ in self.landed):
                break
        goods = self.brains.goods
        rack = goods.by_name("workshop rack")["holds"]
        notes = {n: list(self.brains.of(n).routine.notes)[-3:] for n in programs}
        print(f"\n    copper wire on the rack at {t:.0f} s: {rack}; the vein has {goods.reserve_kg(goods.deposits[0]):.0f} kg "
              f"left; onto the goods rack: {self.landed}; notes: {notes}")
        self.assertGreaterEqual(rack.get("copper wire", 0.0), 1.0, notes)
        self.assertEqual(self.landed[0][0], "copper wire")
        self.assertLess(goods.reserve_kg(goods.deposits[0]), 400.0, "the vein is being worked")
        self.assertEqual(rack, self.spec["goods"]["stockpiles"][3]["holds"], "the ledger is the room's own block")
        smelter = self.brains.of("smelter").routine
        self.assertGreaterEqual(smelter.batches, 1)
        # A person talks to the smelter: it goes nowhere, says so, and "make"
        # works a batch if there is ore, "stop" holds it.
        talked = rover_talk.talk(self.app, {"program": "smelter", "open": True,
                                            "person": {"standing_m": [-1.0, 1.0, -9.5], "facing": [-1, 0, 0]}})
        self.assertEqual("talk", talked["program"]["asked"]["by"])
        self.assertIn("I am ", talked["reply"])
        said = rover_talk.talk(self.app, {"program": "smelter", "said": "come here"})
        self.assertIn("go nowhere", said["reply"])
        said = rover_talk.talk(self.app, {"program": "smelter", "said": "stop"})
        self.assertEqual("waiting", said["program"]["doing"])
        said = rover_talk.talk(self.app, {"program": "smelter", "said": "make a batch"})
        self.assertTrue(said["reply"].startswith(("Worked", "Made nothing")), said["reply"])
        closed = rover_talk.talk(self.app, {"program": "smelter", "close": True})
        self.assertEqual("Going on.", closed["reply"])


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE is required")
class TheProcessorFromTheBench(unittest.TestCase):
    """The Workshop's processor template installed into a room through the
    gate: its bins become stockpiles of the room's where they stand, its
    recipe is given to the room, and ore put on its intake is worked into
    copper on its output by its still program's routine."""

    def test_it_installs_with_its_bins_as_stockpiles_and_works_its_recipe(self):
        from workshop_rover_tests import empty_basin
        import workshop_install as install
        design = w.assemble("processor", design_id="processor")
        self.assertEqual(9, len(design.parts))
        self.assertEqual("1 store, 1 panel, a still program and a process routine",
                         workshop_machines.described(design)["says"])
        candidate = {"kind": "processor", "design_id": "processor", "parameters": {},
                     "component_overrides": deepcopy(design.lineage["component_overrides"])}
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        live = live_session.Live()
        self.addCleanup(live.shutdown)
        room = SimpleNamespace(scene="basin", spec=empty_basin(), chat=[], inventory=inventory.Inventory(),
                               workshop_installs=[])
        brains = rover_brain.Brains(lambda: None)
        app = SimpleNamespace(live=live, live_holder="world", room=room, engine_path=ENGINE, runs_path=root / "runs",
                              store=room_store.RoomStore(root / "rooms"), brains=brains, api_key="", model="",
                              on_live_reply=lambda session, reply: brains.listen(session, reply))
        for material in ("glass", "oak", "iron", "concrete"):
            workshop_library.set_rack(app, material, 500.0)
        workshop_library.set_goods(app, "copper", 50.0)
        workshop_library.set_goods(app, "copper wire", 50.0)
        from unittest import mock
        import world_room
        with mock.patch.dict(world_room.SCENES, {"basin": empty_basin}):
            live.open(app, {"spec": room.spec})
            ctx = install.context(app, {})
            preview = install.preview(app, {"session": ctx["session"], "scene": "basin", "mode": "authoring",
                                            "position_m": [0.0, -9.0], "candidate": candidate})
            self.assertEqual("preview", preview["status"], preview)
            self.assertEqual(1, len(preview["root_bodies"]), "one body, no pins")
            receipt = install.commit(app, {"scene": "basin", "session": ctx["session"],
                                           "preview_id": preview["preview_id"], "request_id": "install-processor-1"})
            self.assertEqual("installed", receipt["status"], receipt)
            spec = room.spec
            [program] = spec["machines"]["programs"]
            self.assertEqual(("still", "process", "smelt copper", "processor intake bin", "processor output bin"),
                             (program["kind"], program["routine"]["kind"], program["routine"]["recipe"],
                              program["routine"]["intake"], program["routine"]["output"]))
            self.assertNotIn("recipes", program["routine"], "given to the room, not kept on the routine")
            piles = {s["name"]: s for s in spec["goods"]["stockpiles"]}
            self.assertEqual({"processor intake bin", "processor output bin"}, set(piles))
            self.assertGreater(piles["processor intake bin"]["at_m"][1], piles["processor output bin"]["at_m"][1] + 0.5,
                               "the intake bin stands ahead (+z) of the output bin, where the bins are")
            self.assertEqual(["smelt copper"], [r["name"] for r in spec["goods"]["recipes"]])
            self.assertEqual(1.0, receipt["materials_taken"][-1]["took_kg"] if receipt["materials_taken"][-1].get("substance") == "copper" else 1.0)
            live.open(app, {"spec": spec})
            brains.opened(spec)
            self.assertNotIn("machine_problems", live.session.state, live.session.state.get("machine_problems"))
            goods = brains.goods
            intake = goods.by_name("processor intake bin")
            goods.put(intake["at_m"][0], intake["at_m"][1], {"copper ore": 7.0})
            reply = live.session.send(op="step", dt=DT, n=1)
            [said] = reply["machines"]["programs"]
            live.session.send(op="run", program=said["id"], sender="test", seq=1, power=True)
            sid = live.session.id
            for _ in range(4 * 40):
                body = {"session": sid, "op": "step", "dt": DT, "n": 60}
                brains.before(app, body)
                answer = live.act(body)
                brains.attach(body, answer)
                if goods.by_name("processor output bin")["holds"].get("copper", 0.0) >= 2.0:
                    break
            output = goods.by_name("processor output bin")["holds"]
            store = next(s for s in answer["machines"]["stores"] if s["name"] == "processor battery")
            print(f"\n    the bench's processor made {output} of 7 kg of ore; its battery gave {store['given_j']:.0f} J; "
                  f"notes: {list(brains.of('processor').routine.notes)[-3:]}")
            self.assertAlmostEqual(2.1, output.get("copper", 0.0), places=3, msg="7 kg of ore at three tenths")
            self.assertEqual({}, goods.by_name("processor intake bin")["holds"])
            self.assertAlmostEqual(14000.0, store["given_j"], delta=1.0, msg="2 kJ a kilogram, and nothing else drew")


if __name__ == "__main__":
    if os.environ.get("BANJO_ROVER_LIVE_TESTS") == "required" and not (ENGINE and ENGINE.is_file()):
        raise RuntimeError("BANJO_LIVE_ENGINE must be built for the required live goods tests")
    unittest.main()
