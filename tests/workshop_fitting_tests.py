#!/usr/bin/env python3
"""Check Validity: the concepts it insists on, and the redraws it makes.

The cart is what the rules were written against. The door is the test that
matters: it is built from components here, nothing about it was tuned for, and
it has to come out as a frame and a leaf on one hinge without anybody saying so.
"""
from __future__ import annotations
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "playground"))

from mcp.workshop import WorkshopDesign, WirePart, assemble  # noqa: E402
from mcp import workshop_components  # noqa: E402
from mcp import workshop_construction as construction  # noqa: E402
from mcp import workshop_machines  # noqa: E402
import workshop_articulation  # noqa: E402
import workshop_fitting  # noqa: E402

CELL = 0.04


def block(name, role, size, at, material="oak"):
    return WirePart(name=name, role=role, size_m=tuple(size), center_m=tuple(at),
                    material=material, rotation_deg=(0.0, 0.0, 0.0), shape="box", family=role)


def door_and_frame():
    """Two posts, a lintel across them, and a leaf hung on the left post."""
    base = WorkshopDesign(design_id="door", purpose="a door that swings in its frame",
                          parts=[block("post-left", "post", (0.09, 2.03, 0.09), (-0.52, 1.015, 0.0))],
                          kind="custom", parameters={
                              "primary_use_component": "door",
                              "interaction_point_components": {"grip": "door", "use": "door"}})
    overrides = construction.add_part(
        base, {}, part=block("post-right", "post", (0.09, 2.03, 0.09), (0.52, 1.015, 0.0)))
    built = workshop_components.apply_overrides(base, overrides)
    overrides = construction.add_part(
        built, overrides, part=block("lintel", "beam", (1.13, 0.09, 0.09), (0.0, 2.075, 0.0)),
        joint={"to": "post-left", "kind": "fixed"})
    built = workshop_components.apply_overrides(base, overrides)
    overrides = construction.set_joint(built, overrides, a="lintel", b="post-right", kind="fixed")
    built = workshop_components.apply_overrides(base, overrides)
    overrides = construction.add_part(
        built, overrides, part=block("door", "panel", (0.90, 1.97, 0.045), (-0.025, 1.0, 0.0)),
        joint={"to": "post-left", "kind": "bearing"})
    return base, overrides


def compiled(base, answer, root):
    fitted = workshop_components.apply_overrides(base, answer["overrides"])
    return workshop_articulation.compile_design(fitted, answer["overrides"], cell_m=CELL, root=root)


class TheCart(unittest.TestCase):
    def setUp(self):
        # A cart is worked by its handle, and every place you touch it names a
        # part: the world hands you a component, not an assembly.
        self.design = assemble("cart", design_id="c", parameters={
            "primary_use_component": "handle",
            "interaction_point_components": {"deck": "deck", "grip": "handle", "use": "handle"}})

    def test_it_will_not_compile_as_the_template_draws_it(self):
        overrides = workshop_fitting._readopt(self.design, {})
        built = workshop_components.apply_overrides(self.design, overrides)
        with self.assertRaises(ValueError):
            workshop_articulation.compile_design(built, overrides, cell_m=CELL, root="cart")

    def test_check_validity_redraws_it_until_it_does(self):
        answer = workshop_fitting.check_validity(self.design, {}, cell_m=CELL, root="cart")
        self.assertTrue(answer["ok"], answer.get("why"))
        self.assertEqual("ready", answer["stage"])
        self.assertTrue(answer["changes"])

    def test_it_comes_out_as_four_wheels_turning_on_a_frame(self):
        answer = workshop_fitting.check_validity(self.design, {}, cell_m=CELL, root="cart")
        made = compiled(self.design, answer, "cart")
        self.assertEqual(5, len(made["groups"]))
        self.assertEqual(4, len(made["joints"]))
        self.assertEqual({"hinge"}, {j["kind"] for j in made["joints"]})
        masses = sorted(round(g["mass_kg"], 1) for g in made["groups"])
        self.assertEqual(1, len(set(masses[:4])), "the four wheels should weigh the same")
        self.assertGreater(masses[-1], masses[0], "the frame is heavier than a wheel")

    def test_the_through_axle_is_drawn_as_stubs(self):
        answer = workshop_fitting.check_validity(self.design, {}, cell_m=CELL, root="cart")
        rules = {c["rule"] for c in answer["changes"]}
        self.assertIn("a shaft through its mounts becomes stubs", rules)
        fitted = workshop_components.apply_overrides(self.design, answer["overrides"])
        names = {p.name for p in fitted.parts}
        self.assertNotIn("axle-1", names, "the through-axle is gone")
        self.assertTrue([n for n in names if n.startswith("axle-1-stub")])

    def test_every_change_says_what_it_did_and_why(self):
        answer = workshop_fitting.check_validity(self.design, {}, cell_m=CELL, root="cart")
        for change in answer["changes"]:
            self.assertTrue(change["says"].strip())
            self.assertIn(change["part"].split(",")[0].strip(), change["says"])
            self.assertTrue(change["rule"].strip())


class ADoorNobodyTunedFor(unittest.TestCase):
    def setUp(self):
        self.base, self.overrides = door_and_frame()

    def test_it_is_built_from_components_with_one_turning_joint(self):
        built = workshop_components.apply_overrides(self.base, self.overrides)
        self.assertEqual(4, len(built.parts))
        joints = construction.joints(built)
        self.assertEqual(3, len(joints))
        self.assertEqual(1, sum(1 for j in joints if j["kind"] == "bearing"))

    def test_it_will_not_compile_as_drawn(self):
        built = workshop_components.apply_overrides(self.base, self.overrides)
        with self.assertRaises(ValueError):
            workshop_articulation.compile_design(built, self.overrides, cell_m=CELL, root="door")

    def test_check_validity_makes_it_a_door_that_swings(self):
        answer = workshop_fitting.check_validity(self.base, self.overrides, cell_m=CELL, root="door")
        self.assertTrue(answer["ok"], answer.get("why"))
        made = compiled(self.base, answer, "door")
        self.assertEqual(2, len(made["groups"]), "a frame and a leaf")
        self.assertEqual(1, len(made["joints"]))
        self.assertEqual("hinge", made["joints"][0]["kind"])

    def test_the_leaf_is_lighter_than_the_frame_it_hangs_in(self):
        answer = workshop_fitting.check_validity(self.base, self.overrides, cell_m=CELL, root="door")
        made = compiled(self.base, answer, "door")
        masses = sorted(g["mass_kg"] for g in made["groups"])
        self.assertLess(masses[0], masses[1])

    def test_the_bearing_survives_the_redraw_as_a_bearing(self):
        answer = workshop_fitting.check_validity(self.base, self.overrides, cell_m=CELL, root="door")
        fitted = workshop_components.apply_overrides(self.base, answer["overrides"])
        kinds = {j["kind"] for j in construction.joints(fitted)}
        self.assertIn("bearing", kinds,
                      "re-adopting after a redraw must not turn the hinge back into a bond")


class AWellPulleyBuiltThroughTheChatsTools(unittest.TestCase):
    """Every step here is a tool call the model could make, with its arguments.

    Nothing touches the fitter or the construction library directly, so this
    covers the hooks as well as the redraws: if the pulley comes out as a drum
    turning on a headstock, a model with these tools can build a machine.
    """

    CALLS = [
        ("add_part", {"name": "post-right", "role": "post", "size_m": [0.11, 2.2, 0.11],
                      "center_m": [0.45, 1.1, 0.0], "material": "oak"}),
        ("add_part", {"name": "headstock", "role": "beam", "size_m": [1.01, 0.11, 0.11],
                      "center_m": [0.0, 2.255, 0.0], "material": "oak",
                      "fasten_to": "post-left", "kind": "fixed"}),
        ("set_joint", {"a": "headstock", "b": "post-right", "kind": "fixed"}),
        ("add_part", {"name": "drum", "role": "drum", "size_m": [0.18, 0.26, 0.26],
                      "center_m": [0.0, 2.07, 0.0], "material": "oak",
                      "fasten_to": "headstock", "kind": "bearing"}),
        ("add_part", {"name": "rope", "role": "rope", "size_m": [0.05, 1.2, 0.05],
                      "center_m": [0.0, 1.34, 0.13], "material": "oak",
                      "fasten_to": "drum", "kind": "fixed"}),
        ("add_part", {"name": "bucket", "role": "panel", "size_m": [0.28, 0.3, 0.28],
                      "center_m": [0.0, 0.59, 0.13], "material": "oak",
                      "fasten_to": "rope", "kind": "fixed"}),
    ]

    def setUp(self):
        import tempfile, types
        import workshop_chat
        self.tmp = tempfile.TemporaryDirectory()
        runs = Path(self.tmp.name) / "runs"
        runs.mkdir(parents=True)
        app = types.SimpleNamespace(runs_path=runs, workshop_owner_id="owner")
        first = {"name": "post-left", "role": "post", "shape": "box", "family": "post",
                 "size_m": [0.11, 2.2, 0.11], "center_m": [-0.45, 1.1, 0.0],
                 "rotation_deg": [0.0, 0.0, 0.0], "material": "oak"}
        overrides = {construction.CONSTRUCTION_KEY:
                     construction.checked({"added": [first], "joints_authored": True})}
        base = assemble("custom", design_id="well-pulley", purpose="draw water from a well",
                        parameters={"primary_use_component": "drum",
                                    "interaction_point_components": {"grip": "drum", "use": "drum"}})
        candidate = workshop_components.apply_overrides(base, overrides).wireframe()
        candidate["component_overrides"] = overrides
        self.state = workshop_chat._State(app, candidate, None, ["oak", "iron"], [])

    def tearDown(self):
        self.tmp.cleanup()

    def build(self):
        for tool, args in self.CALLS:
            self.state.execute(tool, args)
        return self.state

    def test_the_tools_build_it_one_part_at_a_time(self):
        state = self.build()
        self.assertEqual(6, len(state.design.parts))
        joints = construction.joints(state.design)
        self.assertEqual(5, len(joints))
        self.assertEqual(1, sum(1 for j in joints if j["kind"] == "bearing"))

    def test_a_part_that_does_not_touch_is_refused_with_the_reason(self):
        import workshop_chat  # noqa: F401
        with self.assertRaises(ValueError) as caught:
            self.state.execute("add_part", {"name": "floating", "role": "beam",
                                            "size_m": [0.1, 0.1, 0.1], "center_m": [5.0, 5.0, 5.0],
                                            "fasten_to": "post-left", "kind": "fixed"})
        self.assertIn("does not touch", str(caught.exception))

    def test_check_validity_through_the_tool_makes_it_turn(self):
        state = self.build()
        answer = state.execute("check_validity", {})
        self.assertTrue(answer["ok"], answer.get("why"))
        self.assertTrue(answer["changes"])
        made = workshop_articulation.compile_design(
            state.design, state.overrides, cell_m=CELL, root="well-pulley")
        self.assertEqual(2, len(made["groups"]), "a headstock, and a drum that turns on it")
        self.assertEqual(1, len(made["joints"]))
        self.assertEqual("hinge", made["joints"][0]["kind"])

    def test_the_bucket_hangs_on_the_turning_side(self):
        state = self.build()
        state.execute("check_validity", {})
        made = workshop_articulation.compile_design(
            state.design, state.overrides, cell_m=CELL, root="well-pulley")
        self.assertEqual(2, len(made["groups"]))
        # Drum, rope and bucket move together; the two posts and the headstock do not.
        self.assertTrue(all(g["mass_kg"] > 0 for g in made["groups"]))


class AMaceHasNoFrameButYourHand(unittest.TestCase):
    """A head turning on a haft, and nothing else standing still.

    Every other machine here braces against a frame. A hand-held one braces
    against the person, so the part it says you take hold of IS the frame --
    without that, a mace is refused for being all moving parts.
    """

    def mace(self):
        base = WorkshopDesign(
            design_id="mace", purpose="a mace whose head turns on its haft",
            parts=[block("haft", "handle", (0.05, 0.62, 0.05), (0.0, 0.31, 0.0))],
            kind="custom",
            parameters={"primary_use_component": "haft",
                        "interaction_point_components": {"grip": "haft", "use": "head"}})
        overrides = construction.add_part(
            base, {}, part=block("head", "wheel", (0.11, 0.11, 0.11), (0.0, 0.675, 0.0), "iron"),
            joint={"to": "haft", "kind": "bearing"})
        return base, overrides

    def test_the_part_you_hold_counts_as_the_frame(self):
        base, overrides = self.mace()
        answer = workshop_fitting.check_validity(base, overrides, cell_m=CELL, root="mace")
        self.assertTrue(answer["ok"], answer.get("why"))
        frame = next(c for c in answer["concepts"]
                     if c["concept"].startswith("something stands still"))
        self.assertTrue(frame["ok"])
        self.assertIn("you hold the haft", frame["says"])

    def test_it_comes_out_as_a_head_turning_on_a_haft(self):
        base, overrides = self.mace()
        answer = workshop_fitting.check_validity(base, overrides, cell_m=CELL, root="mace")
        made = compiled(base, answer, "mace")
        self.assertEqual(2, len(made["groups"]))
        self.assertEqual(1, len(made["joints"]))
        self.assertEqual("hinge", made["joints"][0]["kind"])

    def test_without_saying_what_you_hold_it_is_all_moving_parts(self):
        base, overrides = self.mace()
        bare = WorkshopDesign(design_id=base.design_id, purpose=base.purpose,
                              parts=list(base.parts), kind="custom", parameters={})
        answer = workshop_fitting.check_validity(bare, overrides, cell_m=CELL, root="mace")
        self.assertFalse(answer["ok"])
        self.assertEqual("concepts", answer["stage"])
        self.assertIn("all moving parts", answer["says"])


class DressingAProductWithoutChangingIt(unittest.TestCase):
    """set_skin is how a thing looks. What it IS must not move underneath it."""

    def setUp(self):
        import tempfile, types
        import workshop_chat
        self.tmp = tempfile.TemporaryDirectory()
        runs = Path(self.tmp.name) / "runs"
        runs.mkdir(parents=True)
        app = types.SimpleNamespace(runs_path=runs, workshop_owner_id="owner")
        design = assemble("cart", design_id="c")
        candidate = design.wireframe()
        candidate["component_overrides"] = {}
        self.state = workshop_chat._State(app, candidate, None, ["oak", "iron"], [])

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_skin_changes_the_look_and_not_the_mass(self):
        before = self.state.design.measure()["mass_kg"]
        out = self.state.execute("set_skin", {"selector": {"roles": ["wheel"]},
                                              "profile": "round", "color": "#3b2d1f",
                                              "roughness": 0.35})
        self.assertEqual(4, len(out["components"]))
        self.assertIn("Appearance only", out["note"])
        self.assertAlmostEqual(before, self.state.design.measure()["mass_kg"], places=6)

    def test_it_is_kept_on_the_design_where_the_page_reads_it(self):
        self.state.execute("set_skin", {"selector": {"names": ["deck"]}, "color": "walnut"})
        skin = (self.state.overrides.get("deck") or {}).get("skin") or {}
        self.assertEqual("walnut", skin.get("color"))
        self.assertFalse(skin.get("physical"), "dressing a thing must not change its matter")

    def test_changing_the_shape_for_real_says_the_measurements_are_stale(self):
        out = self.state.execute("set_skin", {"selector": {"names": ["deck"]},
                                              "profile": "curve", "bend_m": 0.1,
                                              "physical": True})
        self.assertIn("stale", out["note"])

    def test_it_refuses_to_guess_what_to_change(self):
        with self.assertRaises(ValueError) as caught:
            self.state.execute("set_skin", {"selector": {"names": ["deck"]}})
        self.assertIn("say what to change", str(caught.exception))


class AProductThatDrivesItself(unittest.TestCase):
    """Stores, motors, panels and a program, declared on the bench.

    The world has carried all of this since the rover, but only a hand-written
    room file could declare it. A motor names the two components its pin joins,
    the way the room names a motor by the two things its pin joins.
    """

    def driven_cart(self, motor_on=("bearing-mount-11", "axle-1"), store="battery"):
        base = assemble("cart", design_id="c", parameters={
            "primary_use_component": "handle",
            "interaction_point_components": {"deck": "deck", "grip": "handle", "use": "handle"}})
        record = {
            "stores": [{"name": "battery", "in": "deck", "capacity_j": 5000,
                        "charge_j": 1400, "voltage_v": 24}],
            "motors": [{"name": "left motor", "turns": list(motor_on), "store": store,
                        "stall_torque_n_m": 20, "no_load_rpm": 60, "brake_torque_n_m": 40}],
        }
        return base, {workshop_machines.MACHINES_KEY: record}

    def test_a_motor_on_a_bearing_with_a_store_is_a_machine(self):
        base, overrides = self.driven_cart()
        answer = workshop_fitting.check_validity(base, overrides, cell_m=CELL, root="cart")
        self.assertTrue(answer["ok"], answer.get("why"))
        wired = next(c for c in answer["concepts"] if "drives it" in c["concept"])
        self.assertTrue(wired["ok"])
        self.assertIn("1 motor", wired["says"])

    def test_a_motor_on_a_bond_is_refused_by_name(self):
        base, overrides = self.driven_cart(motor_on=("deck", "handle"))
        answer = workshop_fitting.check_validity(base, overrides, cell_m=CELL, root="cart")
        self.assertFalse(answer["ok"])
        self.assertEqual("concepts", answer["stage"])
        self.assertIn("bonded solid", answer["says"])

    def test_a_motor_drawing_on_no_store_is_refused_by_name(self):
        base, overrides = self.driven_cart(store="flywheel")
        answer = workshop_fitting.check_validity(base, overrides, cell_m=CELL, root="cart")
        self.assertFalse(answer["ok"])
        self.assertIn("flywheel", answer["says"])

    def test_the_motor_follows_the_shaft_when_it_is_redrawn_as_stubs(self):
        base, overrides = self.driven_cart()
        answer = workshop_fitting.check_validity(base, overrides, cell_m=CELL, root="cart")
        after = workshop_machines.of_overrides(answer["overrides"])
        turns = after["motors"][0]["turns"]
        self.assertNotIn("axle-1", turns, "the through-axle is gone; the pin is the stub")
        self.assertTrue([t for t in turns if t.startswith("axle-1-stub")])
        fitted = workshop_components.apply_overrides(base, answer["overrides"])
        here = {p.name for p in fitted.parts}
        for component in turns:
            self.assertIn(component, here, "a motor must drive a part that exists")

    def test_it_comes_out_as_the_room_spells_a_machine(self):
        base, overrides = self.driven_cart()
        answer = workshop_fitting.check_validity(base, overrides, cell_m=CELL, root="cart")
        fitted = workshop_components.apply_overrides(base, answer["overrides"])
        made = compiled(base, answer, "cart")
        room = workshop_machines.installed(fitted, made["component_to_body"])
        bodies = {g["root_body"] for g in made["groups"]}
        self.assertEqual(1, len(room["stores"]))
        self.assertIn(room["stores"][0]["body"], bodies)
        self.assertEqual(1, len(room["motors"]))
        motor = room["motors"][0]
        # The room names a motor by the two things its pin joins.
        self.assertEqual(2, len(motor["on"]))
        self.assertTrue(set(motor["on"]) <= bodies)
        self.assertNotEqual(motor["on"][0], motor["on"][1], "a pin joins two different bodies")
        self.assertEqual("battery", motor["store"])
        self.assertEqual(20.0, motor["stall_torque_n_m"])

    def test_a_program_needs_controls_that_are_there(self):
        base, overrides = self.driven_cart()
        record = dict(workshop_machines.of_overrides(overrides))
        record["programs"] = [{"kind": "roam", "left": "left wheel", "right": "right wheel"}]
        answer = workshop_fitting.check_validity(
            base, {workshop_machines.MACHINES_KEY: record}, cell_m=CELL, root="cart")
        self.assertFalse(answer["ok"])
        self.assertIn("not a control here", answer["says"])

    def test_a_store_cannot_hold_more_than_it_can(self):
        with self.assertRaises(ValueError) as caught:
            workshop_machines.checked({"stores": [{"name": "battery", "in": "deck",
                                                   "capacity_j": 100, "charge_j": 500}]})
        self.assertIn("holds more than it can", str(caught.exception))


class TheChatCanMakeItGo(unittest.TestCase):
    def setUp(self):
        import tempfile, types
        import workshop_chat
        self.tmp = tempfile.TemporaryDirectory()
        runs = Path(self.tmp.name) / "runs"
        runs.mkdir(parents=True)
        app = types.SimpleNamespace(runs_path=runs, workshop_owner_id="owner")
        design = assemble("cart", design_id="c")
        candidate = design.wireframe()
        candidate["component_overrides"] = {}
        self.state = workshop_chat._State(app, candidate, None, ["oak", "iron"], [])

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_tools_put_a_battery_and_a_motor_on_it(self):
        self.state.execute("add_power_part", {"kind": "store", "name": "battery", "in": "deck",
                                              "capacity_j": 5000, "charge_j": 1400, "voltage_v": 24})
        out = self.state.execute("add_power_part", {
            "kind": "motor", "name": "left motor", "turns": ["bearing-mount-11", "axle-1"],
            "store": "battery", "stall_torque_n_m": 20, "no_load_rpm": 60})
        self.assertIn("1 store", out["summary"])
        self.assertIn("1 motor", out["summary"])
        record = workshop_machines.of_overrides(self.state.overrides)
        self.assertEqual("battery", record["motors"][0]["store"])

    def test_a_program_is_one_and_says_what_it_does(self):
        self.state.execute("add_power_part", {"kind": "control", "name": "left wheel",
                                              "turns": ["bearing-mount-11", "axle-1"]})
        self.state.execute("add_power_part", {"kind": "control", "name": "right wheel",
                                              "turns": ["bearing-mount-12", "axle-1"]})
        out = self.state.execute("set_program", {"kind": "roam", "left": "left wheel",
                                                 "right": "right wheel", "rest_below": 0.25,
                                                 "rest_until": 0.6})
        self.assertIn("roam program", out["summary"])
        record = workshop_machines.of_overrides(self.state.overrides)
        self.assertEqual(1, len(record["programs"]))

    def test_it_refuses_a_machine_that_cannot_be_written_down(self):
        with self.assertRaises(ValueError):
            self.state.execute("add_power_part", {"kind": "motor", "turns": ["deck", "deck"],
                                                  "store": "battery", "stall_torque_n_m": 20,
                                                  "no_load_rpm": 60})


class WhatItRefusesToInvent(unittest.TestCase):
    def test_a_part_fastened_to_nothing_is_refused(self):
        base = WorkshopDesign(design_id="loose", purpose="two things near each other",
                              parts=[block("a", "post", (0.08, 0.8, 0.08), (0.0, 0.4, 0.0)),
                                     block("b", "post", (0.08, 0.8, 0.08), (2.0, 0.4, 0.0))],
                              kind="custom")
        answer = workshop_fitting.check_validity(base, {}, cell_m=CELL, root="loose")
        self.assertFalse(answer["ok"])
        self.assertEqual("concepts", answer["stage"])
        self.assertIn("nothing holds", answer["says"])

    def test_a_wheel_with_nothing_to_turn_on_is_said_not_guessed(self):
        base = WorkshopDesign(design_id="stuck", purpose="a wheel bonded to a post",
                              parts=[block("post", "post", (0.08, 0.8, 0.08), (0.0, 0.4, 0.0))],
                              kind="custom")
        overrides = construction.add_part(
            base, {}, part=block("wheel", "wheel", (0.32, 0.08, 0.32), (0.2, 0.4, 0.0)),
            joint={"to": "post", "kind": "fixed"})
        built = workshop_components.apply_overrides(base, overrides)
        said = {c["concept"]: c for c in workshop_fitting.concepts(built)}
        turning = said["every wheel has something to turn on"]
        self.assertFalse(turning["ok"])
        self.assertIn("turns on nothing", turning["says"])


if __name__ == "__main__":
    unittest.main()
