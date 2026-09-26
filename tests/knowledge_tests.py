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
        self.app = types.SimpleNamespace(store=room_store.RoomStore(self.tmp.name), journal=None)

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


if __name__ == "__main__":
    unittest.main()


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
        rungs = progression.what_is_next(self.journal, self.registry)
        self.assertEqual(1, len(rungs))
        rung = rungs[0]
        self.assertEqual("rough-shaping-wood", rung["technique"])
        self.assertTrue(rung["within_reach"], rung)
        self.assertEqual([], rung["first_learn"])
        self.assertEqual(["one-piece-wooden-pick"], rung["would_open"])
        self.assertEqual(1, len(rung["earned_by"]))
        self.assertFalse(rung["earned_by"][0]["done"])
        self.assertIn("Study", rung["earned_by"][0]["says"])
        # And once it is taken it is not still being offered.
        self.found_a_pick()
        progression.earn(self.journal, self.registry, self.now)
        self.assertEqual([], progression.what_is_next(self.journal, self.registry))

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
        self.assertEqual(["rough-shaping-wood"], [r["technique"] for r in book["next"]])
        self.found_a_pick()
        progression.earn(self.journal, self.registry, self.now)
        book = progression.notebook(self.journal, self.registry)
        self.assertEqual(["rough-shaping-wood"], [t["id"] for t in book["techniques"]])
        self.assertEqual("experiment", book["techniques"][0]["learned_from"])
        self.assertEqual([], book["next"])

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
