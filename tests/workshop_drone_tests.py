"""A rover that flies (docs/machine-world.md, "A rover that flies"): the
drone assembled from the same library as the rover -- the deck, battery,
panel, hopper and water eyes on four rotors -- with every joint authored and
its machines declared; and installed into a room through the same gate as
exact bodies on pins, where its hover program lifts it to its height, its
routine has its places, its senses read as any machine's do, and a person can
talk to it.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tests/workshop_drone_tests.py

Without BANJO_LIVE_ENGINE only the checks that need no engine run, unless
BANJO_ROVER_LIVE_TESTS=required, which ctest sets.
"""
from __future__ import annotations

from copy import deepcopy
import math
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground")]
import mcp  # noqa: E402,F401  (installs the products into the catalogue)
from mcp import workshop as w, workshop_components, workshop_construction, workshop_machines  # noqa: E402
import fracture_lab, inventory, live_session, machine_senses, rigid_assembly, room_store, rover_brain, rover_talk  # noqa: E402
import workshop_install as install  # noqa: E402
import workshop_library  # noqa: E402
from workshop_rover_tests import DT, empty_basin  # noqa: E402

ENGINE = Path(os.environ["BANJO_LIVE_ENGINE"]).resolve() if os.environ.get("BANJO_LIVE_ENGINE") else None
DRONE_AT = (0.0, -9.0)


def drone_candidate() -> dict:
    design = w.assemble("drone", design_id="drone")
    return {"kind": "drone", "design_id": "drone", "parameters": {},
            "component_overrides": deepcopy(design.lineage["component_overrides"])}


class TheDroneIsInTheCatalogue(unittest.TestCase):
    def test_a_rotor_is_a_family_the_chat_can_search(self):
        library = w.ComponentLibrary()
        self.assertIn("rotor", {f.name for f in w.LIBRARY_FAMILIES})
        rotor = library.make("rotor", name="front rotor", material="oak", at_m=(0.0, 0.2, 0.6), parameters={})
        self.assertEqual(["front rotor stub", "front rotor"] +
                         [f"front rotor blade {i}" for i in (1, 2, 3, 4)],
                         [p.name for p in rotor.parts])
        stub, hub = rotor.parts[:2]
        self.assertEqual("iron", stub.material)
        self.assertGreater(hub.center_m[1], stub.center_m[1], "the hub sits on top of the stub")
        self.assertEqual((0.0, 0.2, 0.6), rotor.anchors["mount"])

    def test_four_blades_round_a_hub_instead_of_a_disc_that_never_looks_like_it_turns(self):
        """A solid disc has one thing wrong with it that nothing else does: a
        turning one looks exactly like a stopped one, so the drone gave no sign
        of whether it was running.

        Nothing ever stopped it being blades -- a rotor is exact parts, collided
        as they are drawn, at whatever size. It was a disc because the family
        made a disc."""
        library = w.ComponentLibrary()
        at, span = (0.0, 0.2, 0.6), 0.4
        rotor = library.make("rotor", name="r", material="oak", at_m=at,
                             parameters={"diameter_m": span})
        blades = [p for p in rotor.parts if "blade" in p.name]
        hub = next(p for p in rotor.parts if p.name == "r")
        self.assertEqual(4, len(blades))
        # Spaced evenly round the hub, all the same, and all at one radius.
        out = sorted(round(math.hypot(b.center_m[0] - at[0], b.center_m[2] - at[2]), 6)
                     for b in blades)
        self.assertEqual(1, len(set(out)), "every blade the same distance out")
        self.assertEqual([0.0, 90.0, 180.0, 270.0], sorted(b.rotation_deg[1] for b in blades))
        self.assertEqual(1, len({b.size_m for b in blades}), "every blade the same blade")
        # Reaching the rim and no further, and rooted on the hub rather than
        # floating off it.
        self.assertAlmostEqual(max(out) + blades[0].size_m[0] / 2, span / 2, places=6)
        self.assertAlmostEqual(min(out) - blades[0].size_m[0] / 2, hub.size_m[0] / 2, places=6)
        # The hub is SQUARE, and that is not a drawing choice: a design is held
        # together by what its parts touch face to face, and a square blade end
        # on a round hub meets it along one line and comes away loose.
        self.assertEqual("box", hub.shape)
        # And far lighter than the disc it replaces, because most of a disc is
        # the part between the blades.
        disc = library.make("rotor", name="d", material="oak", at_m=at,
                            parameters={"diameter_m": span, "blades": 0})
        self.assertLess(sum(p.mass_kg() for p in rotor.parts),
                        0.5 * sum(p.mass_kg() for p in disc.parts))

    def test_a_blade_count_that_cannot_butt_onto_the_hub_gets_the_disc(self):
        # Two or four butt square onto a four-sided hub. Three would meet it on
        # a corner and come away, so it is given the disc rather than a rotor
        # that falls apart.
        library = w.ComponentLibrary()
        for blades, want in ((0, 0), (1, 0), (2, 2), (3, 0), (4, 4)):
            with self.subTest(blades=blades):
                made = library.make("rotor", name="r", material="oak", at_m=(0.0, 0.2, 0.6),
                                    parameters={"blades": float(blades)})
                self.assertEqual(want, len([p for p in made.parts if "blade" in p.name]))

    def test_the_drone_template_authors_every_joint_and_declares_its_machines(self):
        design = w.assemble("drone", design_id="drone")
        # Sixteen on the chassis and six to a rotor: a stub, a hub and its four
        # blades.
        self.assertEqual(40, len(design.parts))
        overrides = design.lineage["component_overrides"]
        construction = overrides[workshop_construction.CONSTRUCTION_KEY]
        self.assertTrue(construction["joints_authored"])
        kinds = [j["kind"] for j in construction["joints"]]
        # Nineteen as it was, and sixteen more: every blade fastened to its
        # hub by name, because this template writes its own joints down and
        # nothing is worked out from what touches what afterwards.
        self.assertEqual((35, 4), (kinds.count("fixed"), kinds.count("bearing")))
        machines = overrides[workshop_machines.MACHINES_KEY]
        self.assertEqual(["front motor", "right motor", "back motor", "left motor"], [m["name"] for m in machines["motors"]])
        self.assertTrue(all(m["rotor"]["thrust_n_per_rad2"] > 0 for m in machines["motors"]), "every motor spins a rotor")
        [program] = machines["programs"]
        self.assertEqual(("hover", 1.5, ["front rotor", "right rotor", "back rotor", "left rotor"], 2, "dig", 20.0),
                         (program["kind"], program["hover_m"], program["rotors"], len(program["sensors"]),
                          program["routine"]["kind"], program["routine"]["hopper_kg"]))
        self.assertNotIn("left", program, "a hover program has rotors, not wheels")
        self.assertEqual("1 store, 4 motors, 1 panel, 4 controls, a hover program with 2 water eyes and a dig routine (20 kg hopper)",
                         workshop_machines.described(design)["says"])

    def test_the_record_refuses_a_hover_program_that_is_not_on_four_rotors(self):
        with self.assertRaisesRegex(ValueError, "four rotor controls"):
            workshop_machines.checked({"stores": [], "motors": [], "panels": [],
                                       "controls": [{"name": "a", "turns": ["x", "y"]}],
                                       "programs": [{"kind": "hover", "rotors": ["a", "a"]}]})

    def test_it_compiles_to_five_bodies_on_four_vertical_pins(self):
        design, overrides = workshop_components.design_from_spec(drone_candidate())
        self.assertEqual([], [j for j in workshop_construction.joints(design) if j.get("open")], "every joint closes")
        artifact = rigid_assembly.compile_design(design, overrides, root="drone")
        groups = {b["name"]: sorted(b["_components"]) for b in artifact["bodies"]}
        self.assertEqual(5, len(groups))
        self.assertIn("deck", groups["drone"], "the chassis carries the name")
        self.assertTrue(all(len(g) == 6 for n, g in groups.items() if n != "drone"),
                        "each rotor is its stub, its hub and four blades")
        self.assertEqual(4, len(artifact["joints"]))
        self.assertTrue(all(tuple(round(v, 3) for v in j["axis"]) == (0.0, 1.0, 0.0) for j in artifact["joints"]),
                        "every pin stands up")
        mass = sum(p.mass_kg() for p in design.parts)
        self.assertLess(mass, 4 * 0.011 * 70.0 ** 2 / 9.81, "four rotors at 70 rad/s lift it with room to spare")
        made = workshop_machines.installed(design, artifact["component_to_body"], None,
                                           {"dig site": [0.0, 3.0], "depot": [0.0, -3.0]})
        [program] = made["programs"]
        self.assertEqual(("drone", "hover", 1.5), (program["body"], program["kind"], program["hover_m"]))
        self.assertEqual(4, len(program["rotors"]))
        self.assertEqual({"thrust_n_per_rad2": 0.011, "drag_n_m_per_rad2": 0.0021}, made["motors"][0]["rotor"])
        placed = rigid_assembly.placed(artifact, [0.0, 0.2, 0.0], 0.0, 0.0)
        spec = {**empty_basin(), "precise_rigid_bodies": rigid_assembly.scene_bodies(placed),
                "joints": rigid_assembly.scene_joints(placed), "machines": made}
        validated = fracture_lab.validate(spec)
        [program] = validated["machines"]["programs"]
        self.assertEqual(("hover", 4, 1.5, 2, "dig"), (program["kind"], len(program["rotors"]), program["hover_m"],
                                                       len(program["sensors"]), program["routine"]["kind"]))
        self.assertEqual(0.011, validated["machines"]["motors"][0]["rotor"]["thrust_n_per_rad2"])

    def test_the_senses_read_a_flying_machine_as_any_other(self):
        program = {"kind": "hover", "at_m": [1.0, 1.7, 2.0], "heading_deg": 0.0, "height_m": 1.48, "climb_m_s": 0.02,
                   "hover_m": 1.5, "doing": "waiting", "rotors": [11, 12, 13, 14], "body": "drone"}
        machines = {"controls": [{"id": i, "condition": "on", "speed_rpm": 570.0, "power": True} for i in (11, 12, 13, 14)]}
        ctx = machine_senses.Context(program=program, machines=machines, bodies=[])
        position = machine_senses.sense_position(ctx)
        self.assertEqual((1.48, 0.02, 1.5), (position["height_above_ground_m"], position["climb_m_s"],
                                              position["holds_height_m"]))
        drives = machine_senses.sense_wheels(ctx)
        self.assertEqual(["rotor 1", "rotor 2", "rotor 3", "rotor 4"], [d["side"] for d in drives["wheels"]])
        self.assertIn("hover", rover_brain.KINDS)


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE is required")
class InstalledIntoTheRoom(unittest.TestCase):
    """The drone from the bench, set down in the basin as exact bodies on
    pins, powered as the room opens: it lifts to its height and holds it, its
    routine goes to its places in the air, and a person can talk to it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.live = live_session.Live()
        self.addCleanup(self.live.shutdown)
        self.room = SimpleNamespace(scene="basin", spec=empty_basin(), chat=[], inventory=inventory.Inventory(),
                                    workshop_installs=[])
        self.brains = rover_brain.Brains(lambda: None)
        self.app = SimpleNamespace(live=self.live, live_holder="world", room=self.room, engine_path=ENGINE,
                                   runs_path=root / "runs", store=room_store.RoomStore(root / "rooms"),
                                   brains=self.brains, api_key="", model="",
                                   on_live_reply=lambda session, reply: self.brains.listen(session, reply))
        for material in ("glass", "oak", "iron", "concrete"):
            workshop_library.set_rack(self.app, material, 500.0)
        # And the goods its machines take (workshop_library.GOODS_PER).
        for substance in ("copper", "copper wire"):
            workshop_library.set_goods(self.app, substance, 50.0)
        from unittest import mock
        import world_room
        patcher = mock.patch.dict(world_room.SCENES, {"basin": empty_basin})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.live.open(self.app, {"spec": self.room.spec})
        self.ctx = install.context(self.app, {})

    def program(self, reply=None):
        reply = reply or self.live.session.send(op="step", dt=DT, n=1)
        return next(p for p in reply["machines"]["programs"] if p["name"] == "drone")

    def pose(self, name):
        return next(b for b in self.live.session.send(op="poses")["bodies"] if b["name"] == name)

    def test_it_installs_as_the_rooms_drone_and_flies(self):
        preview = install.preview(self.app, {"session": self.ctx["session"], "scene": "basin", "mode": "authoring",
                                             "position_m": list(DRONE_AT), "candidate": drone_candidate()})
        self.assertEqual("preview", preview["status"], preview)
        self.assertEqual(5, len(preview["root_bodies"]))
        self.assertEqual({"dig site": [0.0, -6.0], "depot": [0.0, -12.0]}, preview["places"])
        receipt = install.commit(self.app, {"scene": "basin", "session": self.ctx["session"],
                                            "preview_id": preview["preview_id"], "request_id": "install-drone-1"})
        self.assertEqual("installed", receipt["status"], receipt)
        spec = self.room.spec
        [program] = spec["machines"]["programs"]
        self.assertEqual(("hover", 4, 2, "dig"), (program["kind"], len(program["rotors"]), len(program["sensors"]),
                                                  program["routine"]["kind"]))
        self.live.open(self.app, {"spec": spec})
        self.brains.opened(spec)
        opened = self.live.session.state
        self.assertNotIn("machine_problems", opened, opened.get("machine_problems"))
        self.live.session.send(op="step", dt=DT, n=240)
        program = self.program()
        self.assertEqual(("hover", "stopped", False), (program["kind"], program["doing"], program["power"]))
        chassis = preview["root_body"]
        ground_y = self.pose(chassis)["position_m"][1]
        said = self.live.session.send(op="run", program=program["id"], sender="test", seq=1, power=True)
        self.assertEqual("waiting", said["program"]["doing"], "on, with nowhere to go, it hovers")
        heights = []
        for _ in range(40):                       # 10 s
            self.live.session.send(op="step", dt=DT, n=60)
            heights.append(self.pose(chassis)["position_m"][1] - ground_y)
        program = self.program()
        print(f"\n    the Workshop's drone rose to {max(heights):.2f} m and holds {program['height_m']:.2f} m "
              f"(asked {program['hover_m']} m), {program['doing']}: {program['why']}")
        self.assertGreater(heights[-1], 1.0, "it took off")
        # ON STATION, which is `landed_height_m + hover_m` and not `hover_m`:
        # hover_m is asked ABOVE where the machine's centre stood when it was
        # made, and height_m is that centre above the ground. Comparing the two
        # directly measured how high the drone's centre sits, not whether it
        # holds anything -- it passed at 0.32 with a solid rotor disc and failed
        # at 0.36 when four blades replaced it, which moved the centre and
        # changed nothing about the flying.
        held = program["landed_height_m"] + program["hover_m"]
        self.assertLess(abs(program["height_m"] - held), 0.35, "and holds its height")
        # Its routine knows its places, and stepped as the page steps the
        # room -- the brains before and after each step -- it flies to its dig
        # site, digs a load, carries it to its depot in the air and dumps it.
        brain = self.brains.of("drone")
        self.assertEqual({"dig site", "depot"}, set(brain.routine.places))
        self.assertEqual(20.0, brain.routine.hopper_kg)
        sid = self.live.session.id
        t = 0.0
        for _ in range(4 * 90):                   # up to 90 s
            body = {"session": sid, "op": "step", "dt": DT, "n": 60}
            self.brains.before(self.app, body)
            answer = self.live.act(body)
            self.brains.attach(body, answer)
            t = float(answer["t"])
            if brain.routine.trips >= 1:
                break
        p = self.pose(chassis)["position_m"]
        print(f"    its routine delivered {brain.routine.trips} load ({brain.routine.delivered_kg:.0f} kg) in "
              f"{t:.0f} s; it is at {p[0]:.2f}, {p[2]:.2f}, {p[1] - ground_y:.2f} m up; notes: "
              + "; ".join(list(brain.routine.notes)[-4:]))
        self.assertEqual(1, brain.routine.trips, list(brain.routine.notes))
        self.assertLess(t, 60.0, "one load in under a minute")
        self.assertLess(math.hypot(p[0], p[2] + 12.0), 2.5, "it dumped near its depot")
        self.assertGreater(p[1] - ground_y, 0.8, "in the air")
        # And it keeps at it, trip after trip. One load was all this asked for
        # once, and a drone that could not stop flew 8 m past its dig site every
        # time and spent the best part of a minute coming back; one that drifted
        # out of reach of the site sat on the dig step for the rest of the run,
        # because the step that took it there is behind it.
        was, drifted_s = brain.routine.trips, 0.0
        for _ in range(4 * 240):                  # up to 240 s more
            body = {"session": sid, "op": "step", "dt": DT, "n": 60}
            self.brains.before(self.app, body)
            answer = self.live.act(body)
            self.brains.attach(body, answer)
            t = float(answer["t"])
            here = self.pose(chassis)["position_m"]
            if brain.routine.summary().get("step") == 2 and math.hypot(here[0], here[2] + 6.0) > 4.0:
                drifted_s += DT * 60
            if brain.routine.trips >= was + 2:
                break
        p2 = self.pose(chassis)["position_m"]
        print(f"    kept at it: {brain.routine.trips} loads ({brain.routine.delivered_kg:.0f} kg) by {t:.0f} s; "
              f"it was far from its dig site with digging to do for {drifted_s:.0f} s")
        self.assertGreaterEqual(brain.routine.trips, was + 2, list(brain.routine.notes))
        self.assertLess(drifted_s, 30.0, "it does not sit out of reach of the ground it is working")
        self.assertGreater(p2[1] - ground_y, 0.8, "and it is still flying")
        program = self.program()
        # A person can talk to it, and its senses know it flies.
        talked = rover_talk.talk(self.app, {"program": "drone", "open": True,
                                            "person": {"standing_m": [p[0] + 3.0, ground_y, p[2]], "facing": [-1, 0, 0]}})
        self.assertEqual("talk", talked["program"]["asked"]["by"])
        self.assertTrue(talked["reply"].startswith("I am "), talked["reply"])
        said = rover_talk.talk(self.app, {"program": "drone", "said": "stop"})
        self.assertEqual("waiting", said["program"]["doing"])


if __name__ == "__main__":
    if os.environ.get("BANJO_ROVER_LIVE_TESTS") == "required" and not (ENGINE and ENGINE.is_file()):
        raise RuntimeError("BANJO_LIVE_ENGINE must be built for the required live drone tests")
    unittest.main()
