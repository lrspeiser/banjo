#!/usr/bin/env python3
"""The joint screen against cases worked out by hand, in glass, oak and iron.

Every expected number here is plain statics or Newton's second law, written out
in the test, never read back from the code under test.
"""
from __future__ import annotations

from math import pi
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mcp  # noqa: E402,F401
from mcp import engine_materials, product_breakscreen as screen, product_joints  # noqa: E402
from mcp import workshop_components, workshop_construction as con  # noqa: E402

KEY = con.CONSTRUCTION_KEY
G = 9.80665
MATERIALS = ("glass", "oak", "iron")


def part(name, size, centre, *, material="oak", role="beam", shape="box", rotation=(0, 0, 0)):
    return {"name": name, "role": role, "shape": shape, "size_m": list(size), "center_m": list(centre),
            "rotation_deg": list(rotation), "material": material}


def built(parts, joints):
    rows = [{"id": f"j{i + 1}", "kind": kind, "a": a, "b": b} for i, (a, b, kind) in enumerate(joints)]
    spec = {"kind": "custom", "design_id": "case", "parameters": {},
            "component_overrides": {KEY: {"added": parts, "joints": rows, "joints_authored": True}}}
    return workshop_components.design_from_spec(spec)[0]


def joint(answer, name):
    return next(row for row in answer["joints"] if row["joint"] == name)


class FreeBody(unittest.TestCase):
    """Struck in mid-air: a joint carries the share of the blow that accelerates what is beyond it."""

    def two_blocks(self, material):
        return built([part("a", (0.2, 0.1, 0.1), (0.0, 1.0, 0.0), material=material),
                      part("b", (0.1, 0.1, 0.1), (0.15, 1.0, 0.0), material=material)],
                     [("a", "b", "fixed")])

    def test_a_push_through_the_centre_is_shared_by_mass_and_weight_loads_nothing_in_free_fall(self):
        for material in MATERIALS:
            answer = screen.screen(self.two_blocks(material), component_name="a", point_m=(-0.1, 1.0, 0.0),
                                   direction=(1, 0, 0), force_n=300.0, resting=False)
            load = joint(answer, "j1")["load"]
            # b is a third of the mass, so a third of the push goes through the joint, pressing it.
            self.assertAlmostEqual(-100.0, load["axial_n"], places=3, msg=material)
            self.assertAlmostEqual(0.0, load["shear_n"], places=3, msg=material)
            self.assertEqual("free", answer["standing"])
            density = engine_materials.density(material)
            self.assertAlmostEqual(300.0 / (density * 0.003), answer["acceleration_m_s2"][0], places=3, msg=material)
            self.assertAlmostEqual(-G, answer["acceleration_m_s2"][1], places=3, msg=material)

    def test_a_pull_loads_it_in_tension_and_the_answer_is_the_strength_over_the_contact(self):
        for material in MATERIALS:
            design = self.two_blocks(material)
            answer = screen.screen(design, component_name="a", point_m=(-0.1, 1.0, 0.0),
                                   direction=(-1, 0, 0), force_n=300.0, resting=False)
            row = joint(answer, "j1")
            self.assertAlmostEqual(100.0, row["load"]["axial_n"], places=3, msg=material)
            tensile = engine_materials.mechanics(material)["tensile_strength_pa"]
            self.assertAlmostEqual(100.0 / (tensile * 0.01), row["utilisation"], places=9, msg=material)
            self.assertEqual("pulled apart", row["would_be"])
            # A third of the pull reaches the joint, so it parts at three times its tensile capacity.
            self.assertAlmostEqual(3.0 * tensile * 0.01, answer["first_to_give"]["force_n"],
                                   delta=3.0 * tensile * 0.01 * 1e-6, msg=material)

    def test_a_push_off_the_centre_line_spins_it_and_the_joint_carries_the_shear_of_that(self):
        design = self.two_blocks("oak")
        answer = screen.screen(design, component_name="a", point_m=(-0.1, 1.0, 0.0),
                               direction=(0, 0, 1), force_n=90.0, resting=False)
        # A free bar struck across one end: a = F/m at the centre and alpha = F d / I about it.
        rho = 700.0
        m = rho * 0.003
        centre = (rho * 0.002 * 0.0 + rho * 0.001 * 0.15) / m                       # x of the centre of mass
        self.assertAlmostEqual(90.0 / m, answer["acceleration_m_s2"][2], places=3)
        ia = rho * 0.002 * (0.2 ** 2 + 0.1 ** 2) / 12 + rho * 0.002 * (0.0 - centre) ** 2
        ib = rho * 0.001 * (0.1 ** 2 + 0.1 ** 2) / 12 + rho * 0.001 * (0.15 - centre) ** 2
        alpha = 90.0 * (-0.1 - centre) / (ia + ib)      # about +y for a +z force at x < centre: tau_y = z*Fx - x*Fz
        # b's centre accelerates at a_z - alpha*(x_b - centre)... written for +y rotation: a_z = -alpha_y * x.
        tau_y = -(-0.1 - centre) * 90.0
        alpha_y = tau_y / (ia + ib)
        a_b = 90.0 / m - alpha_y * (0.15 - centre)
        self.assertAlmostEqual(abs(rho * 0.001 * a_b), joint(answer, "j1")["load"]["shear_n"], places=3)
        self.assertNotEqual(0.0, alpha)


class Resting(unittest.TestCase):
    """Standing on the floor: the floor carries the weight and holds against sliding."""

    def column(self, material, *, base="iron"):
        return built([part("base", (1.0, 0.1, 1.0), (0, 0.05, 0), material=base, role="top"),
                      part("post", (0.1, 0.5, 0.1), (0, 0.35, 0), material=material, role="post"),
                      part("cap", (0.3, 0.1, 0.3), (0, 0.65, 0), material=material, role="top")],
                     [("base", "post", "fixed"), ("post", "cap", "fixed")])

    def test_each_joint_carries_the_weight_above_it_and_a_load_set_on_top(self):
        for material in MATERIALS:
            answer = screen.screen(self.column(material), component_name="cap", point_m=(0, 0.7, 0),
                                   direction=(0, -1, 0), force_n=500.0)
            rho = engine_materials.density(material)
            cap, post = rho * 0.3 * 0.1 * 0.3 * G, rho * 0.1 * 0.5 * 0.1 * G
            self.assertEqual("resting on the floor", answer["standing"])
            self.assertAlmostEqual(-(cap + 500.0), joint(answer, "j2")["load"]["axial_n"], places=2, msg=material)
            self.assertAlmostEqual(-(cap + post + 500.0), joint(answer, "j1")["load"]["axial_n"], places=2, msg=material)
            self.assertEqual("crushed", joint(answer, "j1")["would_be"])
            for row in answer["joints"]:
                self.assertAlmostEqual(0.0, row["load"]["shear_n"], places=2)
            self.assertEqual([0.0, 0.0, 0.0], [abs(v) for v in answer["acceleration_m_s2"]])

    def test_a_sideways_push_held_by_the_floor_bends_the_joint_by_force_times_height(self):
        for material in MATERIALS:
            answer = screen.screen(self.column(material), component_name="cap", point_m=(-0.15, 0.65, 0),
                                   direction=(1, 0, 0), force_n=200.0)
            self.assertEqual("resting on the floor", answer["standing"])
            foot = joint(answer, "j1")["load"]            # base-to-post, at y = 0.10
            self.assertAlmostEqual(200.0, foot["shear_n"], places=2, msg=material)
            bending = max(abs(foot["moment_u_n_m"]), abs(foot["moment_v_n_m"]))
            self.assertAlmostEqual(200.0 * (0.65 - 0.10), bending, places=2, msg=material)
            head = joint(answer, "j2")["load"]            # post-to-cap, at y = 0.60
            self.assertAlmostEqual(200.0 * (0.65 - 0.60), max(abs(head["moment_u_n_m"]), abs(head["moment_v_n_m"])),
                                   places=2, msg=material)

    def test_what_gives_first_is_the_far_fibre_reaching_the_materials_strength(self):
        for material in MATERIALS:
            answer = screen.screen(self.column(material), component_name="cap", point_m=(-0.15, 0.65, 0),
                                   direction=(1, 0, 0), force_n=200.0)
            m = engine_materials.mechanics(material)
            rho = engine_materials.density(material)
            section, area, arm = 0.1 * 0.1 ** 2 / 6.0, 0.01, 0.55
            weight = (rho * 0.3 * 0.1 * 0.3 + rho * 0.1 * 0.5 * 0.1) * G
            # Foot joint, bending about one axis with the weight pressing it. Three ways to go:
            #   the far fibre in tension   F*arm/(st*Z)                     = 1  (the weight is not credited)
            #   the near fibre crushing    W/(sc*A) + F*arm/(sc*Z)          = 1
            #   shear                      F/(tau*A)                        = 1
            tension = m["tensile_strength_pa"] * section / arm
            crushing = (1.0 - weight / (m["compressive_strength_pa"] * area)) * m["compressive_strength_pa"] * section / arm
            shear = m["shear_strength_pa"] * area
            expected = min(tension, crushing, shear)
            first = answer["first_to_give"]
            self.assertEqual("j1", first["joint"], material)
            self.assertAlmostEqual(expected, first["force_n"], delta=expected * 2e-5, msg=material)
            # Oak crushes before it tears (52 against 90 MPa); glass and iron tear first.
            self.assertEqual("crushed" if material == "oak" else "pulled apart", first["would_be"], material)

    def test_a_table_shares_a_central_load_equally_between_its_four_legs(self):
        legs = [(0.35, 0.2), (-0.35, 0.2), (0.35, -0.2), (-0.35, -0.2)]
        for material in MATERIALS:
            parts = [part("top", (0.8, 0.04, 0.5), (0, 0.72, 0), material=material, role="top")]
            parts += [part(f"leg-{i + 1}", (0.05, 0.7, 0.05), (x, 0.35, z), material=material, role="leg")
                      for i, (x, z) in enumerate(legs)]
            design = built(parts, [("top", f"leg-{i + 1}", "fixed") for i in range(4)])
            answer = screen.screen(design, component_name="top", point_m=(0, 0.74, 0),
                                   direction=(0, -1, 0), force_n=1000.0)
            top = engine_materials.density(material) * 0.8 * 0.04 * 0.5 * G
            for i in range(4):
                self.assertAlmostEqual(-(top + 1000.0) / 4.0, joint(answer, f"j{i + 1}")["load"]["axial_n"],
                                       places=2, msg=material)

    def test_a_push_the_floor_cannot_hold_slides_it_and_says_so(self):
        answer = screen.screen(self.column("oak", base="oak"), component_name="cap", point_m=(-0.15, 0.65, 0),
                               direction=(1, 0, 0), force_n=600.0, floor_friction=0.2)
        self.assertIn("sliding", answer["standing"])
        self.assertGreater(answer["acceleration_m_s2"][0], 0.0)

    def test_a_push_that_would_tip_it_over_is_screened_as_free_and_the_reason_is_given(self):
        tall = built([part("post", (0.1, 1.0, 0.1), (0, 0.5, 0)), part("cap", (0.3, 0.1, 0.3), (0, 1.05, 0))],
                     [("post", "cap", "fixed")])
        answer = screen.screen(tall, component_name="cap", point_m=(-0.15, 1.05, 0),
                               direction=(1, 0, 0), force_n=400.0)
        self.assertEqual("free", answer["standing"])
        self.assertIn("Not held by the floor", answer["limitations"][0])


class TheCart(unittest.TestCase):
    def setUp(self):
        design, _ = workshop_components.design_from_spec({"kind": "cart", "design_id": "cart", "parameters": {}})
        overrides = {KEY: con.adopted(design)}
        # All oak, so that every part has the same declared strengths to reason with.
        for name in ("axle-1", "axle-2"):
            overrides[name] = {"material": "oak"}
        self.design = workshop_components.design_from_spec(
            {"kind": "cart", "design_id": "cart", "parameters": {}, "component_overrides": overrides})[0]

    def test_it_is_free_to_roll_its_two_wheelsets_and_a_load_on_the_deck_goes_out_through_the_bearings(self):
        model = screen._Model(self.design)
        self.assertEqual(8, len(model.modes))            # six of the whole cart, and each wheelset's spin
        self.assertEqual([8, 3, 3], [len(body) for body in model.bodies()])
        answer = screen.screen(self.design, component_name="deck", point_m=(0, 0.38, 0),
                               direction=(0, -1, 0), force_n=1500.0)
        self.assertEqual("resting on the floor", answer["standing"])
        chassis = sum(model.mass[model.index[name]] for name in model.bodies()[0]) * G
        bearings = [row for row in answer["joints"] if row["kind"] == "bearing"]
        self.assertEqual(4, len(bearings))
        self.assertAlmostEqual(chassis + 1500.0, sum(row["load"]["shear_n"] for row in bearings), delta=0.05)
        mounts = [row for row in answer["joints"] if row["a"] == "deck" and row["b"].startswith("bearing-mount")]
        above = sum(model.mass[model.index[n]] for n in model.bodies()[0] if not n.startswith("bearing-mount")) * G
        self.assertAlmostEqual(-(above + 1500.0), sum(row["load"]["axial_n"] for row in mounts), delta=0.05)

    def test_a_blow_on_the_handle_finds_the_handles_own_joints_first_and_says_what_comes_off(self):
        handle = next(p for p in self.design.parts if p.name == "handle")
        answer = screen.screen(self.design, component_name="handle", point_m=handle.center_m,
                               direction=(0, -1, 0), force_n=3000.0)
        first = answer["first_to_give"]
        self.assertIn("handle", first["a"] + first["b"])
        self.assertLess(first["force_n"], 3000.0)
        self.assertTrue(answer["gives_way"])
        pieces = answer["comes_apart_into"]
        self.assertGreater(len(pieces), 1)
        self.assertIn("deck", pieces[0])
        self.assertIn("handle", [name for piece in pieces[1:] for name in piece])


class Capacity(unittest.TestCase):
    def test_a_bonded_joint_is_the_weaker_materials_strength_over_the_contact(self):
        design = built([part("a", (0.2, 0.1, 0.1), (0, 1, 0), material="iron"),
                        part("b", (0.1, 0.1, 0.1), (0.15, 1, 0), material="glass")], [("a", "b", "fixed")])
        row = con.joints(design)[0]
        rated = product_joints.capacity(row, *design.parts)
        self.assertAlmostEqual(45.0e6 * 0.01, rated["tension_n"], places=3)
        self.assertAlmostEqual(35.0e6 * 0.01, rated["shear_n"], places=3)
        self.assertAlmostEqual(600.0e6 * 0.01, rated["compression_n"], places=3)      # iron crushes before glass
        self.assertAlmostEqual(45.0e6 * (0.1 * 0.1 ** 3 / 12) / 0.05, rated["bending_u_n_m"], places=6)
        self.assertEqual({"axis", "holds_tension_n", "holds_shear_n", "unchecked_by_the_engine"},
                         set(rated["engine_fixing"]))
        self.assertIn("b (glass)", rated["strength"]["tensile_governed_by"])
        self.assertIn("a (iron)", rated["strength"]["compressive_governed_by"])

    def test_a_shaft_is_rated_across_and_along_and_a_bearing_not_along(self):
        block = part("block", (0.0345, 0.18, 0.0345), (0.19, 0.25, 0.0))
        axle = part("axle", (0.03, 0.76, 0.03), (0, 0.16, 0), shape="cylinder", role="axle",
                    rotation=(0, 0, -90), material="iron")
        for kind in ("fixed", "bearing"):
            design = built([block, axle], [("block", "axle", kind)])
            rated = product_joints.capacity(con.joints(design)[0], *design.parts)
            crush = 52.0e6 * 0.03 * 0.0345                  # oak's bore under the projected area
            shear = 170.0e6 * pi * 0.03 ** 2 / 4            # the iron shaft across
            self.assertAlmostEqual(min(crush, shear), rated["radial_n"], delta=1e-6 * crush)
            self.assertEqual("the bore crushing under the shaft", rated["radial_governed_by"])
            if kind == "bearing":
                self.assertIsNone(rated["axial_n"])
                self.assertEqual(0.0, rated["torque_n_m"])
            else:
                self.assertAlmostEqual(11.0e6 * pi * 0.03 * 0.0345, rated["axial_n"], delta=1e-3)

    def test_a_material_the_engine_does_not_have_leaves_the_joint_unrated_and_says_why(self):
        design = built([part("a", (0.2, 0.1, 0.1), (0, 1, 0), material="pine"),
                        part("b", (0.1, 0.1, 0.1), (0.15, 1, 0))], [("a", "b", "fixed")])
        rated = product_joints.capacity(con.joints(design)[0], *design.parts)
        self.assertFalse(rated["rated"])
        self.assertIn("pine", rated["why"])

    def test_a_template_has_to_show_its_joints_before_they_can_be_screened(self):
        design, _ = workshop_components.design_from_spec({"kind": "table", "design_id": "t", "parameters": {}})
        with self.assertRaisesRegex(ValueError, "no joints of its own"):
            screen.screen(design, component_name="top", point_m=(0, 0.76, 0), direction=(0, -1, 0), force_n=10)


if __name__ == "__main__":
    unittest.main()
