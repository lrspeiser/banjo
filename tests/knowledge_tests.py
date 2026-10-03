"""A person's notebook: what they know is kept apart from what the world is.

docs/knowledge-and-progression.md, increment 2. The notebook grows only from
what the engine measured the person's own tool doing, read from their live
room's replies (server.hear). A scratch-world trial, the chat, or a result the
engine marked "not supported" adds nothing, and the same result never counts
twice. These pin that, the graph's checks when it loads, which design a built
thing is, and that the room's chat reads the notebook and cannot write it.

No engine runs here, only the library, for the chat's copy of the room.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from copy import deepcopy
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))

import room_world   # noqa: E402,F401  (puts mcp/ on the path, finds the library)
import progression  # noqa: E402
import room_store   # noqa: E402
import server       # noqa: E402
import world_chat   # noqa: E402
import world_room   # noqa: E402

LIBRARY = os.environ.get("BANJO_LIBRARY")

# The chat's own recipe for the pick (world_chat.py, TOOLS THAT DIG), in the
# room document's millimetres.
PICK_ROOM = {
    "bodies": [
        {"name": "pick haft", "shape": "box", "material": "oak", "size_mm": [800, 40, 40],
         "center_mm": [0, 20, 1220], "join": "pick"},
        {"name": "pick arm", "shape": "box", "material": "oak", "size_mm": [40, 40, 280],
         "center_mm": [380, 20, 1060], "join": "pick"},
        {"name": "stone", "shape": "box", "material": "concrete", "size_mm": [200, 200, 200],
         "center_mm": [1000, 100, 0]}],
    "tool_points": [{"body": "pick haft", "tip_mm": [380, 20, 920], "pointing": [0, 0, -1],
                     "grip_mm": [-360, 20, 1220], "width_mm": 40, "thickness_mm": 40,
                     "angle_deg": 30, "length_mm": 200}],
    "interactions": [{"object": "the pick", "template": "swing-and-lever",
                      "parts": ["pick haft", "pick arm"], "tool": "pick haft"}]}


def closed(kind: str, **fields) -> dict:
    """A closed ground-work record as the live runner sends it (the numbers are
    the MCP's measured ones in the clearing: docs/ground-work.md)."""
    record = {"point": 1, "tool": "pick haft", "ground": "soil", "supported": True, "why": "",
              "model": "ground-work-v1", "kind": kind, "at_s": 3.14159, "at_m": [0.0, 0.0, 0.0],
              "closing_speed_m_s": 9.17, "depth_m": 0.1203, "sideways_m": 0.19, "work_j": 15.85,
              "loosened": {"sand_m3": 0.0, "soil_m3": 0.00561}, "loosened_kg": 8.97,
              "tool_whole": True, "tool_dent_mm": 0.0, "open": False}
    record.update(fields)
    return record


def definitions_in(folder: Path) -> Path:
    """A copy of the shipped graph to change."""
    copy = folder / "progression"
    shutil.copytree(ROOT / "progression", copy)
    return copy


def edit(folder: Path, name: str, change) -> None:
    path = folder / name
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document), encoding="utf-8")


class TheGraphIsCheckedWhenItLoads(unittest.TestCase):
    def test_the_shipped_graph_loads_with_a_route_open_from_the_start(self):
        registry = progression.Registry()
        pick = registry.designs["one-piece-wooden-pick"]
        start = registry.start
        open_routes = [r["id"] for r in pick["routes"]["any_of"]
                       if not registry.blockers(pick, r, start["holds"], set(start["teaches"]))]
        self.assertEqual(open_routes, ["found-whole"])

    def test_a_process_nobody_registered_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = definitions_in(Path(tmp))
            edit(folder, "techniques.json",
                 lambda d: d["techniques"][0].update(processes=["carve-v9"]))
            with self.assertRaisesRegex(progression.DefinitionError, "carve-v9"):
                progression.Registry(folder)

    def test_a_requirement_cycle_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = definitions_in(Path(tmp))

            def loop(document):
                document["techniques"] += [
                    {"id": "a", "version": 1, "name": "A", "prerequisites": {"all_of": ["b"]}},
                    {"id": "b", "version": 1, "name": "B", "prerequisites": {"all_of": ["a"]}}]
            edit(folder, "techniques.json", loop)
            with self.assertRaisesRegex(progression.DefinitionError, "cycle"):
                progression.Registry(folder)

    def test_a_start_that_would_strand_a_player_is_refused(self):
        # "A player must not need a pickaxe to obtain the only material capable
        # of making their first pickaxe."
        with tempfile.TemporaryDirectory() as tmp:
            folder = definitions_in(Path(tmp))
            edit(folder, "start.json", lambda d: d.update(holds=[]))
            with self.assertRaisesRegex(progression.DefinitionError, "stranded"):
                progression.Registry(folder)


class WhichDesignAThingIs(unittest.TestCase):
    def setUp(self):
        self.registry = progression.Registry()
        self.profile = PICK_ROOM["interactions"][0]

    def test_the_chats_pick_is_the_registered_design(self):
        built = progression.construction_of(PICK_ROOM, self.profile)
        self.assertEqual(progression.design_of(self.registry, built), "one-piece-wooden-pick@1")

    def test_a_changed_construction_is_a_design_of_its_own(self):
        for change in (lambda room: room["bodies"][0].update(size_mm=[1000, 40, 40]),   # longer haft
                       lambda room: room["bodies"][1].update(material="iron"),          # iron arm
                       lambda room: room["bodies"][1].update(join="other")):            # two pieces
            room = json.loads(json.dumps(PICK_ROOM))
            change(room)
            built = progression.construction_of(room, room["interactions"][0])
            self.assertIsNone(progression.design_of(self.registry, built))
            self.assertTrue(progression.own_design_key(built).startswith("own:"))

    def test_what_it_is_called_changes_nothing(self):
        room = json.loads(json.dumps(PICK_ROOM).replace("pick haft", "stick one")
                          .replace("pick arm", "stick two").replace("the pick", "a stick"))
        built = progression.construction_of(room, room["interactions"][0])
        self.assertEqual(built, progression.construction_of(PICK_ROOM, self.profile))
        self.assertEqual(progression.design_of(self.registry, built), "one-piece-wooden-pick@1")


class TheEvaluatorReadsOnlyWhatTheEngineMeasured(unittest.TestCase):
    def setUp(self):
        self.registry = progression.Registry()

    def evidence(self, record, session="s1"):
        return progression.evidence_from(record, session_id=session, spec=PICK_ROOM,
                                         registry=self.registry, at="2026-09-14T00:00:00Z")

    def test_a_pry_that_broke_soil_out_demonstrates_loosening(self):
        e = self.evidence(closed("broke out"))
        self.assertTrue(e["passes"])
        self.assertEqual((e["test"], e["design"]), ("loosens-soil", "one-piece-wooden-pick@1"))
        self.assertEqual(e["claim"], "demonstrated: loosens the tested soil")
        self.assertIn("broke out 5.6 L (9.0 kg)", e["said"])
        self.assertIn("this design revision (one-piece-wooden-pick@1), this soil", e["scope"])
        self.assertEqual(e["models"], ["ground-work-v1"])
        self.assertIn("no wet ground", e["limitations"])

    def test_nothing_loose_or_a_broken_tool_is_recorded_not_claimed(self):
        nothing = self.evidence(closed("pulled out", loosened={"sand_m3": 0.0, "soil_m3": 0.0},
                                       loosened_kg=0.0))
        self.assertFalse(nothing["passes"])
        self.assertEqual(nothing["claim"], "recorded: did not loosen the soil")
        broke = self.evidence(closed("broke out", tool_whole=False))
        self.assertFalse(broke["passes"])
        self.assertIn("did not stay whole", broke["said"])

    def test_rock_that_stopped_it_is_recorded(self):
        e = self.evidence(closed("stopped", ground="rock", loosened={"sand_m3": 0.0, "soil_m3": 0.0},
                                 loosened_kg=0.0, closing_speed_m_s=8.22))
        self.assertEqual((e["test"], e["passes"]), ("on-rock", False))
        self.assertEqual(e["claim"], "recorded: rock stops it")
        self.assertEqual(e["said"], "the rock stopped the pick at 8.2 m/s; it stayed whole")
        soil = self.evidence(closed("broke out"))
        self.assertTrue(soil["said"].startswith("the pick went 120 mm into the soil at 9.2 m/s"),
                        soil["said"])

    def test_open_glancing_and_unmodelled_are_not_evidence(self):
        self.assertIsNone(self.evidence(closed("in the ground", open=True)))
        self.assertIsNone(self.evidence(closed("glanced")))
        wet = closed("not supported", supported=False, why="12 mm of water stands on it")
        self.assertIsNone(self.evidence(wet))
        self.assertEqual(progression.not_modelled(wet), "12 mm of water stands on it")

    def test_a_thing_that_is_not_a_swung_tool_is_not_evidence(self):
        self.assertIsNone(self.evidence(closed("broke out", tool="stone")))


class TheNotebookKeepsOnePersonsResults(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = types.SimpleNamespace(store=room_store.RoomStore(self.tmp.name), journal=None,
                                        room=types.SimpleNamespace(spec=PICK_ROOM))

    def hear(self, records, session="s1", strikes=(3.1,)):
        # A strike began at 3.1 s of the world's clock; the records meet the
        # ground at 3.14159 s, within its stroke.
        server.hear(self.app, types.SimpleNamespace(id=session, room_spec=PICK_ROOM,
                                                    strikes=list(strikes)),
                    {"ok": True, "ground_work": records})

    def test_a_tool_that_met_the_ground_with_no_strike_is_not_evidence(self):
        # Measured: the pick put down onto the rock met it at 3.7 m/s, and was
        # credited as a swing the rock stopped.
        self.hear([closed("stopped", ground="rock")], strikes=())
        self.hear([closed("stopped", ground="rock")], strikes=(0.5,))    # long before it
        self.assertEqual(self.app.journal.data["evidence"], {})
        self.hear([closed("stopped", ground="rock")], strikes=(0.5, 3.1))
        self.assertEqual(len(self.app.journal.data["evidence"]), 1)

    def test_the_same_result_counts_once_and_outlives_a_restart(self):
        record = closed("broke out")
        self.hear([record])
        self.hear([record])            # the same reply read again
        self.hear([closed("in the ground", open=True)])
        self.assertEqual(len(self.app.journal.data["evidence"]), 1)
        again = progression.Journal(Path(self.tmp.name) / "journal.json")
        book = progression.notebook(again, server.registry())
        self.assertEqual([d["design"] for d in book["designs"]], ["one-piece-wooden-pick@1"])
        self.assertEqual(book["designs"][0]["standing"], ["demonstrated", "found"])

    def test_a_result_in_a_new_world_is_a_new_result(self):
        self.hear([closed("broke out")], session="s1")
        self.hear([closed("broke out")], session="s2")   # the room opened again: points renumbered
        self.assertEqual(len(self.app.journal.data["evidence"]), 2)

    def test_what_the_engine_does_not_model_is_a_note_and_not_evidence(self):
        self.hear([closed("not supported", supported=False, why="12 mm of water stands on it")])
        book = server.knowledge_view(self.app)
        self.assertEqual(book["not_modelled"], ["12 mm of water stands on it"])
        self.assertEqual(book["designs"], [])

    def test_an_answer_carries_the_notebook_only_when_it_is_newer(self):
        self.assertIn("notebook", server.with_notebook(self.app, {"ok": True}, -1))
        self.assertNotIn("notebook", server.with_notebook(self.app, {"ok": True}, 0))
        self.hear([closed("broke out")])
        self.assertIn("notebook", server.with_notebook(self.app, {"ok": True}, 0))
        self.assertNotIn("notebook", server.with_notebook(self.app, {"ok": True}, None))


class TheChatReadsItAndCannotWriteIt(unittest.TestCase):
    def test_failed_journal_write_does_not_publish_or_suppress_retry(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as folder:
            journal = progression.Journal(Path(folder)/"atomic-journal.json")
            evidence = progression.evidence_from_batch("smelt copper",{"copper":1.5},{"copper ore":5},
                session_id="source",at="test",batch=1)
            with mock.patch.object(progression.os,"replace",side_effect=OSError("disk failure")):
                with self.assertRaises(OSError): journal.add_evidence(evidence)
            self.assertEqual(0,journal.data["revision"])
            self.assertEqual({},journal.data["evidence"])
            self.assertTrue(journal.add_evidence(evidence))
            with mock.patch.object(progression.os,"replace",side_effect=OSError("disk failure")):
                with self.assertRaises(OSError): progression.earn(journal,progression.Registry(),"test")
            self.assertEqual(set(),journal.knows())
            self.assertEqual(["smelting-copper"],progression.earn(journal,progression.Registry(),"test"))
            restored = progression.Journal(journal.path)
            self.assertEqual({"smelting-copper"},restored.knows())
            self.assertEqual(1,len(restored.data["evidence"]))

    def test_no_tool_the_chat_has_writes_a_notebook(self):
        names = {t["name"] for t in room_world.chat_tools()}
        self.assertIn("read_knowledge", names)
        self.assertFalse({n for n in names if "evaluate" in n or "award" in n or "unlock" in n})
        self.assertIn("You cannot add to it", world_chat.GUIDE)

    @unittest.skipUnless(LIBRARY and Path(LIBRARY).is_file(), "the library is not built")
    def test_the_chat_is_given_the_notebook_as_it_stands(self):
        # Left to ask read_knowledge, the model answered "what does my notebook
        # say" from the conversation, and said it held a trial it never did.
        sent: list[list[dict]] = []

        def model(api_key, model_name, conversation):
            sent.append(list(conversation))
            return {"status": "completed", "usage": {},
                    "output": [{"type": "message",
                                "content": [{"type": "output_text", "text": "Noted."}]}]}

        journal = progression.Journal()
        real, world_chat._call = world_chat._call, model
        try:
            world_chat.ask("key", "a model", world_room.Room("yard"), {"bodies": []},
                           "what do I know?", [], history=[], journal=journal)
            journal.add_evidence(progression.evidence_from(
                closed("broke out"), session_id="s1", spec=PICK_ROOM,
                registry=progression.Registry(), at="2026-09-14T00:00:00Z"))
            world_chat.ask("key", "a model", world_room.Room("yard"), {"bodies": []},
                           "what do I know?", [], history=[], journal=journal)
        finally:
            world_chat._call = real
        empty = json.loads(sent[0][-1]["content"])["their_notebook"]
        self.assertTrue(str(empty["designs"]).startswith("nothing yet"))
        self.assertTrue(empty["blocked"][0].startswith("making one-piece wooden pick themselves"))
        told = json.loads(sent[1][-1]["content"])["their_notebook"]
        self.assertEqual(told["designs"][0]["design"], "One-piece wooden pick")
        self.assertIn("broke out 5.6 L", told["designs"][0]["claims"][0])
        self.assertIn("never", world_chat.GUIDE.split("WHAT THE PERSON KNOWS", 1)[1][:900].lower())

    @unittest.skipUnless(LIBRARY and Path(LIBRARY).is_file(), "the library is not built")
    def test_read_knowledge_in_the_chat_is_the_persons_notebook(self):
        journal = progression.Journal()
        journal.add_evidence(progression.evidence_from(
            closed("broke out"), session_id="s1", spec=PICK_ROOM, registry=progression.Registry(),
            at="2026-09-14T00:00:00Z"))
        sent: list[list[dict]] = []

        def model(api_key, model_name, conversation):
            sent.append(list(conversation))
            if len(sent) == 1:
                return {"status": "completed", "usage": {},
                        "output": [{"type": "function_call", "name": "read_knowledge",
                                    "arguments": "{}", "call_id": "c1"}]}
            return {"status": "completed", "usage": {},
                    "output": [{"type": "message",
                                "content": [{"type": "output_text", "text": "Your pick loosens soil."}]}]}

        real, world_chat._call = world_chat._call, model
        try:
            world_chat.ask("key", "a model", world_room.Room("yard"), {"bodies": []},
                           "what do I know?", [], history=[], journal=journal)
        finally:
            world_chat._call = real
        told = next(item for item in sent[1] if item.get("type") == "function_call_output")
        said = json.loads(told["output"])
        self.assertEqual([d["design"] for d in said["designs"]], ["one-piece-wooden-pick@1"])
        self.assertIn("broke out 5.6 L", said["designs"][0]["evidence"][0]["said"])
        self.assertEqual(len(journal.data["evidence"]), 1, "reading it changed nothing")


class TheWayToAThing(unittest.TestCase):
    """The owner: "ask the chat about an item and it will look at the tech
    tree, figure out all the skills you still need and build it out to get
    to the item."

    The walk is the part that must not be a guess. Which skills a thing
    needs, which you have, and what order the rest go in are answerable from
    the registry, and a model asked to work them out is wrong in ways nobody
    can see.
    """

    def setUp(self):
        self.registry = progression.Registry()
        self.journal = progression.Journal(None)

    def route(self, thing):
        return progression.route_to(self.journal, self.registry, thing)

    def test_it_lists_the_skills_in_the_order_they_go(self):
        out = self.route("aluminium-cell")
        self.assertTrue(out["known_design"])
        self.assertFalse(out["can_make_it"])
        # Deepest first: you cannot draw wire before you can smelt copper,
        # and you cannot win aluminium before you can draw wire.
        self.assertEqual(["smelting-copper", "drawing-wire", "smelting-aluminium"],
                         [s["technique"] for s in out["steps"]])

    def test_each_step_says_what_earns_it(self):
        out = self.route("lime-kiln")
        step = out["steps"][0]
        self.assertEqual("burning-lime", step["technique"])
        self.assertEqual("Watch a lime kiln burn limestone into cement, once.",
                         step["earned_by"][0]["says"])
        self.assertFalse(step["earned_by"][0]["done"])

    def test_it_prefers_a_way_that_MAKES_the_thing(self):
        """Every design can also be found whole, so "fewest skills" alone
        always answers "find one" -- true, and not what anybody asking how
        to make a thing wants."""
        out = self.route("copper-mill")
        self.assertEqual("built-on-the-bench", out["route"])
        self.assertTrue(out["or_find_one"], "being able to find one is not said at all")

    def test_what_you_know_drops_out_of_the_list(self):
        self.journal.learn("smelting-copper", {"kind": "lesson", "id": "a check"},
                           "2026-09-30T00:00:00Z")
        out = self.route("copper-mill")
        self.assertEqual(["drawing-wire"], [s["technique"] for s in out["steps"]])
        self.journal.learn("drawing-wire", {"kind": "lesson", "id": "a check"},
                           "2026-09-30T00:00:00Z")
        self.assertTrue(self.route("copper-mill")["can_make_it"])

    def test_a_thing_that_is_not_there_says_so(self):
        out = self.route("a spaceship")
        self.assertFalse(out["known_design"])
        self.assertIn("no design called", out["says"])
        self.assertTrue(out["routes"], "it does not say what there IS")

    def test_the_chat_tool_leads_with_one_sentence(self):
        """Written in the tool and not left to the model: it is the line most
        answers are built out of, and it should say the same thing every
        time."""
        import workshop_chat

        class Bare:
            pass

        said = workshop_chat._route_to_a_thing(Bare(), "copper mill")
        self.assertEqual("Copper mill needs 2 skills you have not got: "
                         "Smelting copper, then Drawing wire", said["summary"])
        self.assertEqual(["smelting-copper", "drawing-wire"],
                         [s["technique"] for s in said["steps"]])
        # One skill, not "1 skills".
        self.assertIn("needs 1 skill you", workshop_chat._route_to_a_thing(Bare(), "lime kiln")["summary"])
        # And a thing nobody has heard of does not pretend.
        self.assertIn("no design called",
                      workshop_chat._route_to_a_thing(Bare(), "a spaceship")["summary"])


class ThereIsAWayToLearnSomething(unittest.TestCase):
    """The knowledge layer kept a journal for a fortnight and nothing could
    write a technique into it.

    `Journal.knows()` read a dict that no code path filled, so the graph could
    not advance: a player could find a wooden pick and never, by any route,
    become able to make a second one -- the only non-found route is shut behind
    rough-shaping-wood, and rough-shaping-wood could not be learned.
    """

    def setUp(self):
        self.registry = progression.Registry()
        self.journal = progression.Journal()
        self.now = "2026-09-26T00:00:00Z"

    def found_a_pick(self):
        self.journal.data["designs"]["one-piece-wooden-pick@1"] = {
            "standing": {"found": {"since": self.now, "object": "wooden pick"}}}

    def test_a_technique_is_earned_by_studying_what_you_were_given(self):
        self.assertEqual(set(), self.journal.knows())
        self.assertEqual([], progression.earn(self.journal, self.registry, self.now),
                         "nothing is earned by a person who has done nothing")
        self.found_a_pick()
        self.assertEqual(["rough-shaping-wood"],
                         progression.earn(self.journal, self.registry, self.now))
        self.assertEqual({"rough-shaping-wood"}, self.journal.knows())
        source = self.journal.data["techniques"]["rough-shaping-wood"]["source"]
        self.assertEqual("experiment", source["kind"])
        self.assertEqual("studied-a-found-pick", source["route"])

    def test_it_is_learned_once_however_often_it_is_asked(self):
        self.found_a_pick()
        progression.earn(self.journal, self.registry, self.now)
        was = self.journal.data["revision"]
        self.assertEqual([], progression.earn(self.journal, self.registry, "2026-09-26T01:00:00Z"))
        self.assertEqual(was, self.journal.data["revision"], "nothing was written the second time")

    def test_what_is_one_step_away_is_said_before_it_is_taken(self):
        """The ladder. A person one demonstration short of a capability should
        be told so, which is the whole of what a technology tree is for."""
        rungs = {r["technique"]: r for r in progression.what_is_next(self.journal, self.registry)}
        rung = rungs["rough-shaping-wood"]
        self.assertTrue(rung["within_reach"], rung)
        self.assertEqual([], rung["first_learn"])
        self.assertEqual(["one-piece-wooden-pick"], rung["would_open"])
        self.assertEqual(1, len(rung["earned_by"]))
        self.assertFalse(rung["earned_by"][0]["done"])
        self.assertIn("Study", rung["earned_by"][0]["says"])
        # And once it is taken it is not still being offered.
        self.found_a_pick()
        progression.earn(self.journal, self.registry, self.now)
        self.assertNotIn("rough-shaping-wood",
                         [r["technique"] for r in progression.what_is_next(self.journal, self.registry)])

    def test_successful_dig_earns_gathering_without_a_separate_inspection(self):
        record = progression.evidence_from(closed("broke out"), session_id="s1",
            spec=PICK_ROOM, registry=self.registry, at=self.now)
        self.journal.add_evidence(record)
        self.assertIn("using-ground-tools", progression.earn(self.journal, self.registry, self.now))
        shown = self.journal.standing_of("one-piece-wooden-pick")["demonstrated"]
        self.assertNotIn("study-example", shown, "using a tool must not fabricate an inspection")
        before = self.journal.copy()
        self.assertEqual([], progression.earn(self.journal, self.registry, self.now))
        self.assertEqual(before, self.journal.copy())

    def test_no_progress_for_failed_unsupported_or_broken_digs(self):
        for fields in ({"kind":"stopped"}, {"supported":False}, {"tool_whole":False},
                       {"loosened":{"soil_m3":0,"sand_m3":0},"loosened_kg":0}):
            with self.subTest(fields=fields):
                journal = progression.Journal()
                source = closed("broke out"); source.update(fields)
                evidence = progression.evidence_from(source, session_id="s1", spec=PICK_ROOM,
                    registry=self.registry, at=self.now)
                if evidence: journal.add_evidence(evidence)
                progression.earn(journal, self.registry, self.now)
                self.assertNotIn("using-ground-tools", journal.knows())
                skill = next(s for s in progression.skills_for_design(journal, self.registry,
                    "one-piece-wooden-pick@1") if s["id"] == "using-ground-tools")
                self.assertFalse(skill["earned_by"][0]["all_of"][0]["done"])

    def test_contextual_progress_keeps_alternate_designs_and_next_skills_separate(self):
        self.registry.techniques["next-pick-skill"] = {"id":"next-pick-skill","name":"Next pick skill",
            "version":1,"prerequisites":{"all_of":["using-ground-tools"]},
            "earned_by":{"any_of":[{"id":"two-steps","says":"Dig and study the tool",
                "all_of":[{"design":"one-piece-wooden-pick","demonstrated":True,"test":"loosens-soil"},
                          {"design":"one-piece-wooden-pick","demonstrated":True,"test":"study-example"}]}]}}
        self.registry.check()
        self.journal.add_evidence(progression.evidence_from(closed("broke out"), session_id="s1",
            spec=PICK_ROOM, registry=self.registry, at=self.now))
        progression.earn(self.journal, self.registry, self.now)
        skills = progression.skills_for_design(self.journal, self.registry,"one-piece-wooden-pick@1")
        gathering = next(s for s in skills if s["id"] == "using-ground-tools")
        self.assertTrue(gathering["known"])
        self.assertEqual(["used-found-pick"],[r["id"] for r in gathering["earned_by"]])
        next_skill = next(s for s in skills if s["id"] == "next-pick-skill")
        self.assertTrue(next_skill["within_reach"])
        self.assertEqual([True,False],[n["done"] for n in next_skill["earned_by"][0]["all_of"]])

    def test_a_technique_whose_groundwork_is_missing_is_not_within_reach(self):
        """The graph is walked, not skipped: prerequisites first, however much
        has been shown."""
        self.registry.techniques["casting-iron"] = {
            "id": "casting-iron", "version": 1, "name": "Casting iron",
            "describes": "pouring iron into a mould",
            "prerequisites": {"all_of": ["rough-shaping-wood"]},
            "earned_by": {"any_of": [{"id": "x", "says": "s", "all_of": [
                {"design": "one-piece-wooden-pick", "found": True}]}]}}
        self.found_a_pick()
        rungs = {r["technique"]: r for r in progression.what_is_next(self.journal, self.registry)}
        self.assertFalse(rungs["casting-iron"]["within_reach"])
        self.assertEqual(["rough-shaping-wood"], rungs["casting-iron"]["first_learn"])
        # Both, in the order the graph allows, from the one thing they found.
        self.assertEqual(["rough-shaping-wood", "casting-iron"],
                         progression.earn(self.journal, self.registry, self.now))

    def test_the_starting_area_can_teach(self):
        """start.json has carried a `teaches` list all along with no reader."""
        self.registry.start["teaches"] = ["rough-shaping-wood"]
        self.assertEqual(["rough-shaping-wood"],
                         progression.teach_the_start(self.journal, self.registry, self.now))
        self.assertEqual("lesson",
                         self.journal.data["techniques"]["rough-shaping-wood"]["source"]["kind"])
        # Only to a notebook that holds nothing: a lesson does not overwrite
        # what somebody worked out for themselves.
        self.assertEqual([], progression.teach_the_start(self.journal, self.registry, self.now))

    def test_the_notebook_says_what_is_known_and_what_is_next(self):
        book = progression.notebook(self.journal, self.registry)
        self.assertEqual([], book["techniques"])
        self.assertIn("rough-shaping-wood", [r["technique"] for r in book["next"]])
        self.found_a_pick()
        progression.earn(self.journal, self.registry, self.now)
        book = progression.notebook(self.journal, self.registry)
        self.assertEqual(["rough-shaping-wood"], [t["id"] for t in book["techniques"]])
        self.assertEqual("experiment", book["techniques"][0]["learned_from"])
        self.assertNotIn("rough-shaping-wood", [r["technique"] for r in book["next"]])

    def test_a_dead_rung_is_refused_when_the_graph_is_loaded(self):
        """The point of checking at load is that a rung nobody can reach is
        found here rather than by a player."""
        for broken, because in (
                ({"any_of": [{"id": "x", "says": "s", "all_of": [
                    {"design": "no-such-design", "found": True}]}]}, "not a design"),
                ({"any_of": [{"id": "x", "says": "s", "all_of": [
                    {"design": "one-piece-wooden-pick"}]}]}, "finding a design"),
                ({"any_of": [{"id": "x", "says": "s", "all_of": [
                    {"design": "one-piece-wooden-pick", "demonstrated": True,
                     "test": "no-such-test"}]}]}, "no test called"),
                ({"any_of": [{"id": "x", "says": "s"}]}, "asks for nothing")):
            with self.subTest(because=because):
                registry = progression.Registry()
                registry.techniques["rough-shaping-wood"]["earned_by"] = broken
                with self.assertRaises(progression.DefinitionError) as caught:
                    registry.check()
                self.assertIn(because, str(caught.exception))


class ARecipeYouWatchedIsARecipeYouKnow(unittest.TestCase):
    """The goods chain arrived whole and taught nobody anything.

    A vein, a rover that digs it, a smelter that makes copper of the ore, a
    mill that draws it into wire, the wire landing on the Workshop's rack --
    and every step of it simply available. The ledger already told the server
    when goods reached the rack; this is its sibling, and it is the difference
    between equipment you were handed and progress you made.
    """

    def setUp(self):
        self.registry = progression.Registry()
        self.journal = progression.Journal()
        self.now = "2026-09-26T00:00:00Z"

    def watched(self, recipe, made, used, batch=1):
        record = progression.evidence_from_batch(
            recipe, made, used, session_id="s1", at=self.now, batch=batch)
        self.assertIsNotNone(record, f"{recipe} made no evidence")
        self.journal.add_evidence(record)
        return progression.earn(self.journal, self.registry, self.now)

    def test_watching_a_smelt_teaches_smelting(self):
        self.assertEqual(set(), self.journal.knows())
        learned = self.watched("smelt copper", {"copper": 1.5}, {"copper ore": 5.0})
        self.assertEqual(["smelting-copper"], learned)
        book = progression.notebook(self.journal, self.registry)
        said = [e["said"] for d in book["designs"] for e in d["evidence"]]
        self.assertIn("Copper smelter worked 5.00 kg of copper ore into 1.50 kg of copper", said)

    def test_glass_experiment_earns_its_own_branch_and_recovers_older_evidence_once(self):
        self.assertEqual([], progression.earn(self.journal, self.registry, self.now))
        self.assertEqual([], self.registry.techniques['melting-glass']['prerequisites']['all_of'])
        evidence = progression.evidence_from_batch('melt glass', {'glass':.85}, {'sand':1.},
            session_id='older-glass', at=self.now, batch=1)
        self.assertIsNotNone(evidence)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'journal.json'
            older=progression.Journal(path)
            older.add_evidence(evidence)
            self.assertEqual(set(),older.knows())
            restored=progression.Journal(path)
            self.assertEqual(['melting-glass'],progression.earn(restored,self.registry,self.now))
            self.assertNotIn('smelting-copper',restored.knows())
            learned=restored.copy()
            reopened=progression.Journal(path)
            self.assertEqual([],progression.earn(reopened,self.registry,self.now))
            self.assertEqual(learned,reopened.copy())
            self.assertEqual([],progression.earn(progression.Journal(),self.registry,self.now))

    def test_the_mill_is_a_rung_above_the_smelter(self):
        """You cannot draw wire out of copper you cannot make, so the graph is
        walked: watching a mill first teaches nothing until smelting is in."""
        rungs = {r["technique"]: r for r in progression.what_is_next(self.journal, self.registry)}
        self.assertTrue(rungs["smelting-copper"]["within_reach"])
        self.assertFalse(rungs["drawing-wire"]["within_reach"])
        self.assertEqual(["smelting-copper"], rungs["drawing-wire"]["first_learn"])
        self.assertEqual(["copper-mill"], rungs["drawing-wire"]["would_open"])
        # Watched out of order, both land the moment the first one does.
        self.watched("draw wire", {"copper wire": 0.98}, {"copper": 1.0}, batch=1)
        self.assertEqual(set(), self.journal.knows(), "the mill alone teaches nothing yet")
        learned = self.watched("smelt copper", {"copper": 1.5}, {"copper ore": 5.0}, batch=2)
        self.assertEqual(["smelting-copper", "drawing-wire"], learned)

    def test_a_recipe_no_machine_is_registered_for_teaches_nothing(self):
        """A room may carry any chemistry a person writes. The graph only knows
        the recipes it has designs for, and says nothing about the rest rather
        than inventing a technique for them."""
        self.assertIsNone(progression.evidence_from_batch(
            "bake a cake", {"cake": 1.0}, {"flour": 1.0},
            session_id="s1", at=self.now, batch=1))

    def test_the_same_batch_read_twice_awards_nothing_twice(self):
        self.watched("smelt copper", {"copper": 1.5}, {"copper ore": 5.0}, batch=1)
        was = self.journal.data["revision"]
        record = progression.evidence_from_batch(
            "smelt copper", {"copper": 1.5}, {"copper ore": 5.0},
            session_id="s1", at=self.now, batch=1)
        self.assertFalse(self.journal.add_evidence(record))
        self.assertEqual(was, self.journal.data["revision"])

    def test_a_batch_that_made_nothing_is_not_evidence(self):
        self.assertIsNone(progression.evidence_from_batch(
            "smelt copper", {}, {"copper ore": 5.0}, session_id="s1", at=self.now, batch=1))


class GeneralBatchPredicates(unittest.TestCase):
    def test_small_positive_source_amounts_are_preserved_in_evidence(self):
        evidence = progression.evidence_from_batch("fire ceramic",{"ceramic":1e-7},{"clay":1e-6},
            session_id="source",at="test",batch=1)
        self.assertEqual(1e-7,evidence["result"]["made_kg"])
        self.assertEqual({"ceramic":1e-7},evidence["result"]["made"])

    def test_ceramic_batch_uses_curated_test_and_rejects_wrong_input_and_nonfinite_amount(self):
        registry, journal = progression.Registry(), progression.Journal()
        evidence = progression.evidence_from_batch("fire ceramic",{"ceramic":.9},{"clay":1},
            session_id="source",at="test",batch=1)
        journal.add_evidence(evidence)
        self.assertEqual(["firing-ceramic"],progression.earn(journal,registry,"test"))
        for made, used in (({"ceramic":1},{"sand":1}),({"ceramic":float("nan")},{"clay":1}),
                           ({"ceramic":1},{"clay":-1})):
            self.assertIsNone(progression.evidence_from_batch("fire ceramic",made,used,
                session_id="s",at="test",batch=1))


class PersonalToolSourceReceipts(unittest.TestCase):
    def setUp(self):
        import player_learning
        self.learning=player_learning
        self.owner='a'*32
        self.registry=progression.Registry()
        self.app=types.SimpleNamespace(world_id='c'*32,
            room=types.SimpleNamespace(player_records={self.owner:{}}))
        self.session=types.SimpleNamespace(id='unit-native-source',state={'t':4},room_spec=PICK_ROOM)

    def test_ground_outbox_preserves_tiny_source_amounts_and_requires_later_snapshot(self):
        source=closed('broke out',loosened={'soil_m3':1e-12,'sand_m3':0},loosened_kg=1.6e-9)
        self.learning.ground(self.app,self.owner,self.session,source,self.registry)
        pending=self.learning.pending_of(self.app)
        self.assertEqual(1e-12,pending[0]['evidence']['result']['loosened_m3'])
        self.learning.validate_pending(pending,{'t_s':4},self.app.room.player_records,self.registry)
        with self.assertRaises(ValueError):
            self.learning.validate_pending(pending,{'t_s':3},self.app.room.player_records,self.registry)
        for change in ('owner','id','passes','result','nan','open','supported','timestamp'):
            bad=deepcopy(pending)
            if change=='owner':bad[0]['owner']='b'*32
            elif change=='id':bad[0]['evidence']['id']='ev-'+('0'*10)
            elif change=='passes':bad[0]['evidence']['passes']=False
            elif change=='result':bad[0]['evidence']['result']['loosened_m3']=1
            elif change=='nan':bad[0]['source']['record']['work_j']=float('nan')
            elif change=='open':bad[0]['source']['record']['open']=True
            elif change=='supported':bad[0]['source']['record']['supported']=False
            elif change=='timestamp':bad[0]['source']['record']['at_s']=5
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.learning.validate_pending(bad,{'t_s':4},self.app.room.player_records,self.registry)

    def test_unsaved_receipt_cannot_publish_and_saved_retry_is_idempotent(self):
        self.learning.ground(self.app,self.owner,self.session,closed('broke out'),self.registry)
        journal=progression.Journal()
        self.app.room.world_record={'t_s':4}
        self.learning.saved(self.app,lambda app,owner:journal,self.registry)
        self.assertEqual({},journal.data['evidence'])
        self.app.room.player_learning_durable_ids={r['evidence']['id'] for r in self.learning.pending_of(self.app)}
        self.learning.saved(self.app,lambda app,owner:journal,self.registry)
        kept=journal.copy()
        self.learning.ground(self.app,self.owner,self.session,closed('broke out'),self.registry)
        self.learning.saved(self.app,lambda app,owner:journal,self.registry)
        self.assertEqual(kept,journal.copy())

    def test_malformed_study_and_unknown_actor_are_rejected(self):
        source={'construction':progression.construction_of(PICK_ROOM,PICK_ROOM['interactions'][0]),
            'object':'Pick','tool':'pick haft','body_id':1,'point_id':1,'matter_sha256':'d'*64}
        self.learning.queue(self.app,self.owner,'study',source,session=self.session.id,t_s=4,registry=self.registry)
        for field,value in (('body_id',True),('point_id',0),('matter_sha256','invented'),('construction',None)):
            bad=deepcopy(self.learning.pending_of(self.app));bad[0]['source'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.learning.validate_pending(bad,{'t_s':4},self.app.room.player_records,self.registry)
        with self.assertRaises(ValueError):
            self.learning.queue(self.app,'b'*32,'study',source,session=self.session.id,t_s=4,registry=self.registry)


class WorldLearningRouteBoundaries(unittest.TestCase):
    def test_held_ground_target_uses_player_pose_and_declared_reach(self):
        import learning_routes
        queried=[]
        def survey(request):
            queried.append(request)
            x,z=request['at']
            return {'survey':{'on_the_ground':True,'x_m':x,'z_m':z,'ground_m':3,
                'surface':'sand','sand_m':.4,'soil_m':1,'water':{'depth_m':0}}}
        app=types.SimpleNamespace(live=types.SimpleNamespace(
            session=types.SimpleNamespace(id='native'),act=survey))
        for reach in ([1.15,2.0],[.4,.8]):
            with self.subTest(reach=reach):
                target=learning_routes._dry_ground(app,[99,0,99],
                    {'reach_m':reach,'lever':{}},
                    {'eyes_m':[4,4.62,7],'facing':[1,0,0]})
                self.assertAlmostEqual(4+sum(reach)/2,target[0])
                self.assertEqual(3,target[1]);self.assertAlmostEqual(7,target[2])
        self.assertEqual(2,len(queried))
        self.assertTrue(all(r['op']=='survey' and r['session']=='native' for r in queried))

    def test_ground_guidance_skips_inaccessible_surfaces_and_is_bounded(self):
        import learning_routes
        queried=[]
        def survey(request):
            queried.append(request)
            x,z=request['at']
            # The first reachable ring is unavailable: buried soil under rock,
            # wet sand, and off-grid columns do not authorize gathering.
            n=len(queried)
            return {'survey':{'on_the_ground':n%3!=0,'x_m':x,'z_m':z,'ground_m':0,
                'surface':'sand' if n%3 else 'soil','sand_m':.2,'soil_m':1,
                'water':{'depth_m':.1 if n%3==1 else 0}}} if n!=2 else {
                'survey':{'on_the_ground':True,'x_m':x,'z_m':z,'ground_m':0,
                    'surface':'rock','soil_m':1,'water':{'depth_m':0}}}
        app=types.SimpleNamespace(live=types.SimpleNamespace(
            session=types.SimpleNamespace(id='native'),act=survey))
        use={'reach_m':[1.15,2.0],'lever':{}}
        pose={'eyes_m':[0,1.62,0],'facing':[0,0,1]}
        target=learning_routes._dry_ground(app,[0,0,0],use,pose)
        self.assertEqual(5,len(queried));self.assertIsNotNone(target)
        self.assertAlmostEqual(1.575,(target[0]**2+target[2]**2)**.5)
        for surface in ('rock','clay'):
            queried.clear()
            def unavailable(request):
                queried.append(request)
                x,z=request['at']
                return {'survey':{'on_the_ground':True,'x_m':x,'z_m':z,'ground_m':0,
                    'surface':surface,'soil_m':1,'water':{'depth_m':0}}}
            app.live.act=unavailable
            self.assertIsNone(learning_routes._dry_ground(app,[0,0,0],use,pose))
            self.assertEqual(24,len(queried))

    def test_ground_guidance_retains_approach_when_only_far_column_is_available(self):
        import learning_routes
        queried=[]
        def survey(request):
            queried.append(request)
            x,z=request['at']
            return {'survey':{'on_the_ground':True,'x_m':x,'z_m':z,'ground_m':0,
                'surface':'sand' if len(queried)>16 else 'clay','sand_m':.2,'soil_m':1}}
        app=types.SimpleNamespace(live=types.SimpleNamespace(
            session=types.SimpleNamespace(id='native'),act=survey))
        target=learning_routes._dry_ground(app,[0,0,0],
            {'reach_m':[1.15,2.0],'lever':{}},{'eyes_m':[0,1.62,0],'facing':[0,0,1]})
        self.assertEqual(17,len(queried));self.assertEqual([0,0,3.],target)

    def test_learned_skill_is_not_blocked_by_a_missing_alternative_after_tool_is_gone(self):
        import learning_routes
        registry=progression.Registry()
        app=types.SimpleNamespace(room=types.SimpleNamespace(spec={}),
            live=types.SimpleNamespace(session=types.SimpleNamespace(state={'bodies':[]})))
        tree=[{'id':'using-ground-tools','known':True,'within_reach':False,'earned_by':[
            {'done':True,'says':'Dig soil or sand with your Field pick once.','all_of':[
                {'design':'field-pick','test':'loosens-soil','done':True}]},
            {'done':False,'all_of':[{'design':'one-piece-wooden-pick','test':'loosens-soil','done':False}]}]}]
        with mock.patch.object(learning_routes.machine_witness,'machines',return_value=[]):
            learning_routes.resolve(app,registry,tree)
        self.assertTrue(tree[0]['known'])
        self.assertEqual([],tree[0]['world_missing'])
        self.assertEqual('Dig soil or sand with your Field pick once.',tree[0]['earned_by'][0]['says'])
        self.assertTrue(tree[0]['earned_by'][0]['world_ready'])
        self.assertIn('Making One-piece wooden pick is not available yet',tree[0]['earned_by'][1]['says'])

    def test_one_ready_machine_is_enough_and_completed_conditions_do_not_require_new_gifts(self):
        import learning_routes
        registry=progression.Registry()
        app=types.SimpleNamespace(room=types.SimpleNamespace(spec={
            'machines':{'programs':[{'name':name,'body':name,'routine':{'intake':name+' intake'}} for name in ('empty','ready')]},
            'goods':{'recipes':[{'name':'smelt copper','in':{'copper ore':1}}],
                'stockpiles':[{'name':'empty intake','holds':{}},{'name':'ready intake','holds':{'copper ore':5}}]}}),
            live=types.SimpleNamespace(session=types.SimpleNamespace(state={'bodies':[]})))
        sources=[{'machine':name,'recipe':'smelt copper','program':'processor','at_m':[i,0,0]}
                 for i,name in enumerate(('empty','ready'))]
        # Explicit resolver fixtures test alternatives, not native processing.
        sources=[dict(s,program=registry.designs['copper-smelter']['machine']['program']) for s in sources]
        tree=[{'id':'unit-chain','within_reach':True,'earned_by':[{'all_of':[
            {'design':'one-piece-wooden-pick','found':True,'done':True},
            {'design':'copper-smelter','demonstrated':True,'test':'smelts-ore','done':False}]}]}]
        with mock.patch.object(learning_routes.machine_witness,'machines',return_value=sources):
            learning_routes.resolve(app,registry,tree)
        self.assertTrue(tree[0]['within_reach'])
        self.assertEqual([],tree[0]['world_missing'])
        self.assertEqual(['ready'],[l['machine'] for l in tree[0]['earned_by'][0]['locations']])


if __name__ == "__main__":
    unittest.main()
