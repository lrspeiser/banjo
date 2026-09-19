from __future__ import annotations

from math import radians, sin, sqrt
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mcp.workshop import (
    ComponentLibrary,
    WorkshopSession,
    _axis_of,
    assemble,
    assemblies,
    feedback,
    materialize,
    measure,
    rectangular_four_leg_frame,
    rotation_onto,
    strut,
    variants,
)


class WorkshopIsolation(unittest.TestCase):
    def test_a_workshop_session_requires_the_outside_world_to_be_paused(self):
        session = WorkshopSession("w1", "room-rev-44", "chair")
        self.assertTrue(session.outside_paused)
        with self.assertRaises(ValueError):
            WorkshopSession("w2", "room-rev-44", "chair", outside_paused=False)


class Geometry(unittest.TestCase):
    def test_a_rotation_really_aims_the_member_it_describes(self):
        for direction in [(1, 0, 0), (0, 1, 0), (-1, 2, 0), (0, 2, -1),
                          (0.3, 1, -0.7), (-0.5, 1, 0.5), (0, -1, 0)]:
            length = sqrt(sum(v * v for v in direction))
            want = tuple(v / length for v in direction)
            got = _axis_of(rotation_onto(direction))
            for a, b in zip(got, want):
                self.assertAlmostEqual(a, b, places=9, msg=str(direction))

    def test_a_strut_spans_the_two_points_it_was_given(self):
        member = strut(name="m", role="beam", from_m=(0.5, 0.0, -0.2),
                       to_m=(0.4, 0.7, 0.1), section_m=(0.05, 0.05))
        low, high = member.ends_m()
        for got, want in zip(low, (0.5, 0.0, -0.2)):
            self.assertAlmostEqual(got, want, places=9)
        for got, want in zip(high, (0.4, 0.7, 0.1)):
            self.assertAlmostEqual(got, want, places=9)

    def test_a_standing_panel_touches_the_ground_over_a_rectangle(self):
        # Measuring one point per member reported a cabinet side as a line and
        # called the whole unit unstable.
        unit = assemble("shelf-unit")
        width, depth = unit.measure()["support_footprint_m"]
        self.assertGreater(depth, 0.2)
        self.assertTrue(unit.measure()["stands_up"])


class Components(unittest.TestCase):
    def test_one_leg_family_serves_a_table_and_a_chair(self):
        lib = ComponentLibrary()
        table = rectangular_four_leg_frame(
            design_id="table", purpose="hold objects",
            top_size_m=(1.2, 0.04, 0.7), top_height_m=0.76, library=lib)
        chair = assemble("chair", design_id="chair", library=lib)
        for design in (table, chair):
            self.assertIn({"family": "leg", "count": 4}, design.lineage["components"])
            self.assertEqual(4, sum(p.role == "leg" for p in design.parts))
        self.assertGreater(table.parts[1].size_m[1], chair.parts[1].size_m[1])

    def test_leg_styles_are_semantic_and_bounded(self):
        lib = ComponentLibrary()
        leg = lib.make("leg", name="front-left", at_m=(0, 0, 0),
                       parameters={"height_m": 0.7, "style": "splayed",
                                   "splay_deg": 8}).parts[0]
        self.assertEqual("leg", leg.role)
        self.assertAlmostEqual(8.0, leg.rotation_deg[2], places=6)
        with self.assertRaises(ValueError):
            lib.make("leg", name="bad", at_m=(0, 0, 0),
                     parameters={"style": "splayed", "splay_deg": 45})
        with self.assertRaises(KeyError):
            lib.make("leg", name="bad", at_m=(0, 0, 0), parameters={"heigth_m": 0.7})

    def test_the_library_describes_every_family_it_offers(self):
        lib = ComponentLibrary()
        self.assertIn("leg", lib.families())
        self.assertIn("stretcher", lib.families())
        for described in lib.described():
            self.assertTrue(described["about"])
            self.assertTrue(described["parameters"])
            for parameter in described["parameters"]:
                self.assertIn("unit", parameter)

    def test_an_assembly_adds_the_parts_its_options_ask_for(self):
        plain = assemble("table")
        railed = assemble("table", parameters={"aprons": 1, "stretchers": 1})
        self.assertEqual(5, len(plain.parts))
        self.assertEqual(13, len(railed.parts))
        self.assertIn({"family": "apron", "count": 4}, railed.lineage["components"])


class Splay(unittest.TestCase):
    """The defects docs/workshop-next.md stage 0 records, kept fixed."""

    def test_a_splayed_leg_stands_outside_the_head_it_hangs_from(self):
        splayed = assemble("table", parameters={"leg_style": "splayed", "splay_deg": 10})
        leg = next(p for p in splayed.parts if p.name == "leg-2")  # the +x, -z corner
        foot, head = leg.ends_m()
        self.assertGreater(abs(foot[0]), abs(head[0]))
        self.assertGreater(abs(foot[2]), abs(head[2]))

    def test_splaying_widens_the_base_and_the_tip_angle(self):
        upright = assemble("table", parameters={"leg_style": "straight"}).measure()
        splayed = assemble("table", parameters={"leg_style": "splayed",
                                                "splay_deg": 10}).measure()
        self.assertGreater(splayed["support_footprint_m"][0],
                           upright["support_footprint_m"][0])
        self.assertGreater(splayed["tip_angle_deg"], upright["tip_angle_deg"])

    def test_the_footprint_is_measured_where_the_design_touches_the_ground(self):
        # Reporting the leg CENTRE inset as the support footprint overstated a
        # splayed candidate's base by 13%.
        section = 0.058
        design = assemble("table", parameters={"leg_style": "splayed", "splay_deg": 10,
                                               "leg_section_m": section})
        reported = design.measure()["support_footprint_m"][0]
        legs = [p for p in design.parts if p.role == "leg"]
        feet = [p.ends_m()[0][0] for p in legs]
        heads = [p.highest_end_m()[0] for p in legs]
        # Wider than the foot centres, because a cut foot has width; and wider
        # than the heads, which is the number the old check reported as the
        # "support footprint" whatever the splay.
        self.assertGreater(reported, max(feet) - min(feet))
        self.assertGreater(reported, max(heads) - min(heads) + section)
        # A foot square is at most its diagonal across, however it is yawed.
        self.assertLess(reported, max(feet) - min(feet) + section * 1.45)

    def test_a_leg_whose_head_misses_the_top_is_reported(self):
        good = assemble("table", parameters={"leg_style": "splayed", "splay_deg": 15})
        self.assertEqual([], good.measure()["legs_not_under_the_top"])


class CheapVariants(unittest.TestCase):
    def setUp(self):
        self.base = assemble("table", design_id="table", purpose="a workshop table",
                             parameters={"width_m": 1.0, "depth_m": 0.6, "height_m": 0.74})

    def test_agent_can_fork_many_designs_without_materializing_them(self):
        made = variants(self.base, {
            "leg_style": ["straight", "splayed", "tapered"],
            "top_profile": ["square", "round"],
        })
        self.assertEqual(6, len(made))
        self.assertTrue(all(d.lineage["parent"] == "table" for d in made))
        self.assertEqual("table", self.base.design_id)

    def test_every_forked_candidate_really_differs(self):
        # An earlier variants() only wrote the change into a parameters dict and
        # copied the parent's parts, so all six materialized identically.
        made = variants(self.base, {"leg_section_m": [0.04, 0.06, 0.08]})
        sections = {round(d.parts[1].size_m[0], 4) for d in made}
        self.assertEqual({0.04, 0.06, 0.08}, sections)

    def test_forking_on_a_parameter_the_assembly_does_not_have_is_refused(self):
        with self.assertRaises(KeyError):
            variants(self.base, {"leg_colour": ["red", "blue"]})

    def test_feedback_is_about_the_design_and_its_lineage(self):
        candidate = variants(self.base, {"leg_style": ["straight", "splayed"]})[1]
        record = feedback(candidate, rating=5, selected=True, note="looks sturdier")
        self.assertEqual(candidate.design_id, record["design_id"])
        self.assertEqual(5, record["rating"])
        self.assertTrue(record["selected"])
        self.assertEqual("splayed", record["parameters"]["leg_style"])


class Mass(unittest.TestCase):
    def test_the_material_decides_the_mass_and_the_balance(self):
        oak = assemble("table", parameters={"material": "oak"}).measure()
        iron = assemble("table", parameters={"material": "iron"}).measure()
        self.assertGreater(iron["mass_kg"], oak["mass_kg"] * 9)
        # Same shape, so the balance point is the same even though the mass is not.
        self.assertAlmostEqual(oak["centre_of_mass_m"][1],
                               iron["centre_of_mass_m"][1], places=6)

    def test_mass_is_the_arithmetic_anyone_would_do_by_hand(self):
        design = assemble("table", parameters={
            "width_m": 1.0, "depth_m": 1.0, "height_m": 1.0, "top_thickness_m": 0.1,
            "leg_section_m": 0.1, "material": "oak"})
        from mcp import engine_materials
        density = engine_materials.density("oak")
        top = 1.0 * 0.1 * 1.0 * density
        leg = 0.1 * 0.9 * 0.1 * density
        self.assertAlmostEqual(top + 4 * leg, design.measure()["mass_kg"], places=2)


class WireframeToMatter(unittest.TestCase):
    def test_materialization_snaps_to_cells_and_does_not_claim_commit(self):
        design = assemble("chair", design_id="chair")
        plan = materialize(design, cell_size_m=0.04)
        self.assertEqual("materialization-plan", plan["representation"])
        self.assertEqual("not-committed", plan["commit"]["status"])
        self.assertIn("functional trials", plan["commit"]["requires"])
        for obj in plan["objects"]:
            for d in obj["size_m"]:
                self.assertAlmostEqual(round(d / 0.04), d / 0.04)
                self.assertGreaterEqual(d, 0.04)
            for p in obj["center_m"]:
                self.assertAlmostEqual(round(p / 0.04), p / 0.04)

    def test_materialization_keeps_the_splay_that_was_chosen(self):
        # The page's own materializer dropped rotation, so the one feature that
        # distinguished the chosen candidate did not survive.
        plan = materialize(assemble("table", parameters={"leg_style": "splayed",
                                                         "splay_deg": 12}))
        legs = [o for o in plan["objects"] if o["role"] == "leg"]
        self.assertEqual(4, len(legs))
        self.assertTrue(any(any(abs(a) > 1 for a in o["rotation_deg"]) for o in legs))

    def test_two_candidates_that_snap_together_say_so(self):
        cell = 0.04
        base = assemble("table", design_id="t")
        near = variants(base, {"leg_section_m": [0.045, 0.048]})
        prints = {materialize(d, cell_size_m=cell)["fingerprint"] for d in near}
        self.assertEqual(1, len(prints), "45 and 48 mm legs both land on one 40 mm cell")
        apart = variants(base, {"leg_section_m": [0.04, 0.12]})
        self.assertEqual(2, len({materialize(d, cell_size_m=cell)["fingerprint"]
                                 for d in apart}))

    def test_snapping_reports_what_it_moved(self):
        plan = materialize(assemble("table", parameters={"leg_section_m": 0.058}),
                           cell_size_m=0.04)
        self.assertGreater(plan["snapping"]["members_changed"], 0)
        self.assertGreater(plan["snapping"]["largest_change_m"], 0)
        legs = [o for o in plan["objects"] if o["role"] == "leg"]
        self.assertIn("snapped_from_m", legs[0])

    def test_wireframe_keeps_semantic_roles_for_the_renderer_and_agent(self):
        design = assemble("table", design_id="table", purpose="work surface")
        wire = design.wireframe()
        self.assertEqual("wireframe", wire["representation"])
        self.assertEqual("top", wire["parts"][0]["role"])
        self.assertEqual(["leg"] * 4, [p["role"] for p in wire["parts"][1:]])
        self.assertIn("measured", wire)
        self.assertIn("mass_kg", wire["measured"])


class EveryAssembly(unittest.TestCase):
    def test_each_one_builds_stands_and_measures(self):
        for described in assemblies():
            with self.subTest(described["assembly"]):
                design = assemble(described["assembly"])
                reported = measure(design)
                self.assertTrue(design.parts)
                self.assertGreater(reported["mass_kg"], 0)
                self.assertTrue(reported["stands_up"])
                self.assertTrue(all(v > 0 for v in reported["bounding_box_m"]))

    def test_an_unknown_assembly_says_what_it_knows(self):
        with self.assertRaises(KeyError) as caught:
            assemble("spaceship")
        self.assertIn("table", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
