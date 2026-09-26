"""The Workshop's robot parts (docs/machine-world.md, "The Workshop's robot
parts"): the rover assembled from the library's own components with every
joint authored and its machines declared; the bench chat adding a sensor and
a routine; and the rover installed into a room as exact bodies on pins, where
its program roams, its routine has its places, and a person can talk to it.

    BANJO_LIVE_ENGINE=.../banjo_live_world_run.exe python tests/workshop_rover_tests.py

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
import fracture_lab, inventory, live_session, rigid_assembly, room_store, rover_brain, rover_talk  # noqa: E402
import workshop_install as install  # noqa: E402
import workshop_library  # noqa: E402

ENGINE = Path(os.environ["BANJO_LIVE_ENGINE"]).resolve() if os.environ.get("BANJO_LIVE_ENGINE") else None
DT = 1 / 240
# The rover room's ground and sun (tools/build_rover_room.py), with no rover in it.
TERRAIN = {"generate": {"kind": "basin", "nx": 128, "nz": 128, "cell_m": 0.25, "lake_level_m": 0.35, "sand_m": 0.0}}
SUN = {"elevation_deg": 50.0, "azimuth_deg": 200.0, "irradiance_w_m2": 1000.0}
ROVER_AT = (0.0, -9.0)


def rover_candidate() -> dict:
    design = w.assemble("rover", design_id="rover")
    return {"kind": "rover", "design_id": "rover", "parameters": {},
            "component_overrides": deepcopy(design.lineage["component_overrides"])}


def empty_basin() -> dict:
    return {"algorithm": "lattice", "cell_m": 0.05, "plasticity": "on", "terrain": TERRAIN, "sun": dict(SUN),
            "bodies": [{"name": "post", "shape": "box", "material": "concrete", "anchored": True,
                        "size_mm": [150.0, 900.0, 150.0], "center_mm": [13000.0, 3300.0, 13000.0]}]}


class TheRoverIsInTheCatalogue(unittest.TestCase):
    def test_the_robot_parts_are_families_the_chat_can_search(self):
        library = w.ComponentLibrary()
        names = {f.name for f in w.LIBRARY_FAMILIES}
        for family in ("mount", "drive-wheel", "caster", "battery", "solar-panel", "hopper"):
            self.assertIn(family, names)
            self.assertTrue(library.family(family).about)
        caster = library.make("caster", name="c", material="iron", at_m=(0.0, 0.31, 0.38), parameters={})
        self.assertEqual(["c swivel", "c plate", "c left cheek", "c right cheek", "c pin", "c wheel"],
                         [p.name for p in caster.parts])
        wheel = library.make("drive-wheel", name="left wheel", material="oak", at_m=(0.38, 0.16, -0.32),
                             parameters={"side": 1.0})
        self.assertEqual(["left wheel stub", "left wheel"], [p.name for p in wheel.parts])
        self.assertLess(wheel.parts[0].center_m[0], 0.38, "the stub reaches inward from the left wheel")

    def test_the_rover_template_authors_every_joint_and_declares_its_machines(self):
        design = w.assemble("rover", design_id="rover")
        self.assertEqual(17, len(design.parts))
        overrides = design.lineage["component_overrides"]
        construction = overrides[workshop_construction.CONSTRUCTION_KEY]
        self.assertTrue(construction["joints_authored"])
        kinds = [j["kind"] for j in construction["joints"]]
        self.assertEqual((13, 4), (kinds.count("fixed"), kinds.count("bearing")))
        machines = overrides[workshop_machines.MACHINES_KEY]
        self.assertEqual(["left motor", "right motor"], [m["name"] for m in machines["motors"]])
        self.assertEqual(["left wheel", "right wheel"], [c["name"] for c in machines["controls"]])
        [program] = machines["programs"]
        self.assertEqual(("roam", 2, "dig", 40.0), (program["kind"], len(program["sensors"]),
                                                   program["routine"]["kind"], program["routine"]["hopper_kg"]))
        self.assertEqual([0.55, 0.36, 1.0], program["sensors"][0]["at_m"])
        self.assertTrue(all(overrides[p.name] == {"mechanics": {"model": "rigid"}} for p in design.parts))
        # It opens on the bench with those overrides, whoever opens it.
        import workshop_api_core
        wire = workshop_api_core._candidate(SimpleNamespace(runs_path=Path(tempfile.gettempdir())), design,
                                            w.assembly("rover"))
        self.assertIn(workshop_machines.MACHINES_KEY, wire["component_overrides"])

    def test_it_compiles_to_the_rooms_rover_five_bodies_on_four_pins(self):
        design, overrides = workshop_components.design_from_spec(rover_candidate())
        self.assertEqual([], [j for j in workshop_construction.joints(design) if j.get("open")], "every joint closes")
        artifact = rigid_assembly.compile_design(design, overrides, root="rover")
        groups = {b["name"]: sorted(b["_components"]) for b in artifact["bodies"]}
        self.assertEqual(5, len(groups))
        self.assertEqual(sorted(["deck", "left mount", "right mount", "caster mount", "solar panel", "battery", "hopper"]),
                         groups["rover"], "the chassis is the heaviest group and carries the name")
        axes = sorted((j["a"], j["b"], tuple(round(v, 3) for v in j["axis"])) for j in artifact["joints"])
        self.assertEqual(4, len(axes))
        self.assertEqual(1, sum(1 for a in axes if a[2] == (0.0, 1.0, 0.0)), "one vertical swivel")
        self.assertEqual(3, sum(1 for a in axes if a[2] == (1.0, 0.0, 0.0)), "three wheels across x")

    def test_installed_machines_are_the_rooms_own_and_validate(self):
        design, overrides = workshop_components.design_from_spec(rover_candidate())
        artifact = rigid_assembly.compile_design(design, overrides, root="rover")
        origin = [1.0, 0.2, -3.0]
        frame = (lambda p: [float(p[k]) + origin[k] for k in range(3)], lambda d: list(d))
        made = workshop_machines.installed(design, artifact["component_to_body"], frame,
                                           {"dig site": [1.0, 0.0], "depot": [1.0, -6.0]})
        [program] = made["programs"]
        self.assertEqual("rover", program["body"], "the chassis is the body both wheels' pins turn on")
        self.assertEqual([1550.0, 560.0, -2000.0], program["sensors"][0]["at_mm"])
        self.assertEqual(3.0, program["sensors"][0]["depth_mm"])
        self.assertEqual({"kind": "dig", "hopper_kg": 40.0, "places": {"dig site": [1.0, 0.0], "depot": [1.0, -6.0]}},
                         program["routine"])
        [panel] = made["panels"]
        self.assertEqual([0.0, 1.0, 0.0], panel["normal"])
        self.assertAlmostEqual(0.39 + origin[1], panel["at_mm"][1] / 1000.0, places=3, msg="the panel's top")
        self.assertEqual("rover", made["stores"][0]["body"])
        self.assertTrue(all(c["on"][0] == "rover" for c in made["controls"]))
        # The room takes it as it is.
        placed = rigid_assembly.placed(artifact, origin, 0.0, 0.0)
        spec = {**empty_basin(), "precise_rigid_bodies": rigid_assembly.scene_bodies(placed),
                "joints": rigid_assembly.scene_joints(placed), "machines": made}
        validated = fracture_lab.validate(spec)
        self.assertEqual(2, len(validated["machines"]["programs"][0]["sensors"]))
        self.assertEqual("dig", validated["machines"]["programs"][0]["routine"]["kind"])


class TheBenchChatMakesItARobot(unittest.TestCase):
    def setUp(self):
        import workshop_chat
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        runs = Path(self.tmp.name) / "runs"
        runs.mkdir(parents=True)
        app = SimpleNamespace(runs_path=runs, workshop_owner_id="owner")
        # A cart with no program, as a person builds one up.
        design = w.assemble("cart", design_id="c")
        candidate = design.wireframe()
        candidate["component_overrides"] = {}
        self.state = workshop_chat._State(app, candidate, None, ["oak", "iron"], [])
        self.state.execute("add_power_part", {"kind": "store", "name": "battery", "in": "deck",
                                              "capacity_j": 5000, "charge_j": 1400, "voltage_v": 24})
        for side, mount in (("left", "bearing-mount-11"), ("right", "bearing-mount-12")):
            self.state.execute("add_power_part", {"kind": "control", "name": f"{side} wheel", "turns": [mount, "axle-1"]})

    def test_a_sensor_and_a_routine_need_a_program_and_ride_with_it(self):
        with self.assertRaisesRegex(ValueError, "set the program first"):
            self.state.execute("add_sensor", {"on": "deck", "at_m": [0.5, 0.36, 1.0]})
        self.state.execute("set_program", {"kind": "roam", "left": "left wheel", "right": "right wheel"})
        out = self.state.execute("add_sensor", {"on": "deck", "at_m": [0.5, 0.36, 1.0], "depth_m": 0.003})
        self.assertIn("water sensor on deck", out["summary"])
        out = self.state.execute("set_routine", {"kind": "dig", "hopper_kg": 30})
        self.assertIn("routine is to dig", out["summary"])
        record = workshop_machines.of_overrides(self.state.overrides)
        [program] = record["programs"]
        self.assertEqual(1, len(program["sensors"]))
        self.assertEqual({"kind": "dig", "hopper_kg": 30.0}, program["routine"])
        # Setting the program again keeps them.
        self.state.execute("set_program", {"kind": "roam", "left": "left wheel", "right": "right wheel", "climb_deg": 10})
        [program] = workshop_machines.of_overrides(self.state.overrides)["programs"]
        self.assertEqual((1, "dig", 10.0), (len(program["sensors"]), program["routine"]["kind"], program["climb_deg"]))
        with self.assertRaisesRegex(ValueError, "needs a hopper"):
            self.state.execute("set_routine", {"kind": "dig"})
        with self.assertRaises(ValueError):
            self.state.execute("set_program", {"kind": "drive", "left": "left wheel", "right": "right wheel"})

    def test_the_rover_template_opens_on_the_bench_as_a_machine(self):
        import workshop_chat
        candidate = rover_candidate()
        state = workshop_chat._State(SimpleNamespace(runs_path=Path(self.tmp.name), workshop_owner_id="owner"),
                                     candidate, None, ["oak", "iron", "glass"], [])
        described = workshop_machines.described(state.design)
        self.assertEqual("1 store, 2 motors, 1 panel, 2 controls, a roam program with 2 water eyes and a dig routine (40 kg hopper)",
                         described["says"])
        out = state.execute("inspect_design", {})
        self.assertEqual(17, len(state.design.parts))
        self.assertTrue(out)


@unittest.skipUnless(ENGINE and ENGINE.is_file(), "BANJO_LIVE_ENGINE is required")
class InstalledIntoTheRoom(unittest.TestCase):
    """The rover from the bench, set down in the basin by the lake as exact
    bodies on pins, powered as the room opens, roaming dry, with a routine
    that knows its places and a person who can talk to it."""

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
        from unittest import mock
        import world_room
        patcher = mock.patch.dict(world_room.SCENES, {"basin": empty_basin})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.live.open(self.app, {"spec": self.room.spec})
        self.ctx = install.context(self.app, {})

    def program(self, reply=None):
        reply = reply or self.live.session.send(op="step", dt=DT, n=1)
        return next(p for p in reply["machines"]["programs"] if p["name"] == "rover")

    def pose(self, name):
        return next(b for b in self.live.session.send(op="poses")["bodies"] if b["name"] == name)

    def test_it_installs_as_the_rooms_rover_and_roams_dry(self):
        preview = install.preview(self.app, {"session": self.ctx["session"], "scene": "basin", "mode": "authoring",
                                             "position_m": list(ROVER_AT), "candidate": rover_candidate()})
        self.assertEqual("preview", preview["status"])
        self.assertEqual(5, len(preview["root_bodies"]))
        self.assertEqual({"dig site": [0.0, -6.0], "depot": [0.0, -12.0]}, preview["places"],
                         "its places, three metres ahead and behind where it is set down")
        self.assertEqual(2, len(preview["machines"]["programs"][0]["sensors"]))
        receipt = install.commit(self.app, {"scene": "basin", "session": self.ctx["session"],
                                            "preview_id": preview["preview_id"], "request_id": "install-rover-1"})
        self.assertEqual("installed", receipt["status"])
        # The room's spec now declares it, and the room opened from that spec
        # powers it (live_session.Live._power runs at open).
        spec = self.room.spec
        self.assertEqual(5, len(spec["precise_rigid_bodies"]))
        [program] = spec["machines"]["programs"]
        self.assertEqual(("roam", 2, "dig"), (program["kind"], len(program["sensors"]), program["routine"]["kind"]))
        self.live.open(self.app, {"spec": spec})
        self.brains.opened(spec)
        opened = self.live.session.state
        self.assertNotIn("machine_problems", opened, opened.get("machine_problems"))
        self.live.session.send(op="step", dt=DT, n=240)
        program = self.program()
        self.assertEqual(("stopped", False, 2), (program["doing"], program["power"], len(program["sensors"])))
        self.assertFalse(any(s["sees"] for s in program["sensors"]), "dry where it stands")
        said = self.live.session.send(op="run", program=program["id"], sender="test", seq=1, power=True)
        self.assertEqual("going forward", said["program"]["doing"])
        chassis = preview["root_body"]
        was = self.pose(chassis)["position_m"]
        path, wet = 0.0, 0.0
        for _ in range(80):                       # 20 s
            self.live.session.send(op="step", dt=DT, n=60)
            at = self.pose(chassis)["position_m"]
            path += math.dist(at, was)
            was = at
            for body in [b for b in self.live.session.send(op="poses")["bodies"] if b["name"] != chassis]:
                p = body["position_m"]
                water = (self.live.session.send(op="survey", at=[p[0], p[2]]).get("survey") or {}).get("water")
                wet = max(wet, (water or {}).get("depth_m", 0.0))
        program = self.program()
        print(f"\n    the Workshop's rover roamed {path:.1f} m in 20 s, {program['turns']} turns away, at most "
              f"{wet * 1000:.0f} mm of water under a wheel; now {program['doing']}: {program['why']}")
        self.assertGreater(path, 3.0, "it went somewhere")
        self.assertLessEqual(wet, 0.003, "and stayed dry")
        # Its routine knows its places, and a person can talk to it.
        brain = self.brains.of("rover")
        self.assertEqual({"dig site", "depot"}, set(brain.routine.places))
        self.assertEqual(40.0, brain.routine.hopper_kg)
        p = self.pose(chassis)["position_m"]
        talked = rover_talk.talk(self.app, {"program": "rover", "open": True,
                                            "person": {"standing_m": [p[0] + 3.0, p[1], p[2]], "facing": [-1, 0, 0]}})
        self.assertEqual("talk", talked["program"]["asked"]["by"])
        self.assertTrue(talked["reply"].startswith("I am "), talked["reply"])
        said = rover_talk.talk(self.app, {"program": "rover", "said": "stop"})
        self.assertEqual("waiting", said["program"]["doing"])


if __name__ == "__main__":
    if os.environ.get("BANJO_ROVER_LIVE_TESTS") == "required" and not (ENGINE and ENGINE.is_file()):
        raise RuntimeError("BANJO_LIVE_ENGINE must be built for the required live rover tests")
    unittest.main()
