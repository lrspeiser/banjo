import unittest

from mcp.workshop import (
    ComponentLibrary,
    WorkshopSession,
    feedback,
    materialize,
    rectangular_four_leg_frame,
    variants,
)


class WorkshopIsolation(unittest.TestCase):
    def test_a_workshop_session_requires_the_outside_world_to_be_paused(self):
        session = WorkshopSession("w1", "room-rev-44", "chair")
        self.assertTrue(session.outside_paused)
        with self.assertRaises(ValueError):
            WorkshopSession("w2", "room-rev-44", "chair", outside_paused=False)


class Components(unittest.TestCase):
    def test_one_leg_family_serves_a_table_and_a_chair(self):
        lib = ComponentLibrary()
        table = rectangular_four_leg_frame(
            design_id="table", purpose="hold objects",
            top_size_m=(1.2, 0.04, 0.7), top_height_m=0.76, library=lib)
        chair = rectangular_four_leg_frame(
            design_id="chair", purpose="support a seated person",
            top_size_m=(0.45, 0.04, 0.45), top_height_m=0.46, library=lib)
        self.assertEqual(table.lineage["components"], [{"family": "leg", "count": 4}])
        self.assertEqual(chair.lineage["components"], [{"family": "leg", "count": 4}])
        self.assertEqual(4, sum(p.role == "leg" for p in table.parts))
        self.assertEqual(4, sum(p.role == "leg" for p in chair.parts))
        self.assertGreater(table.parts[1].size_m[1], chair.parts[1].size_m[1])

    def test_leg_styles_are_semantic_and_bounded(self):
        lib = ComponentLibrary()
        leg = lib.make("leg", name="front-left", at_m=(0, 0, 0),
                       parameters={"height_m": 0.7, "style": "splayed", "splay_deg": 8})[0]
        self.assertEqual("leg", leg.role)
        self.assertEqual(8, leg.rotation_deg[2])
        with self.assertRaises(ValueError):
            lib.make("leg", name="bad", at_m=(0, 0, 0),
                     parameters={"style": "splayed", "splay_deg": 45})


class CheapVariants(unittest.TestCase):
    def setUp(self):
        self.base = rectangular_four_leg_frame(
            design_id="table", purpose="a workshop table",
            top_size_m=(1.0, 0.04, 0.6), top_height_m=0.74)

    def test_agent_can_fork_many_designs_without_materializing_them(self):
        made = variants(self.base, {
            "leg_style": ["straight", "splayed", "tapered"],
            "top_profile": ["square", "rounded"],
        })
        self.assertEqual(6, len(made))
        self.assertTrue(all(d.lineage["parent"] == "table" for d in made))
        self.assertEqual("table", self.base.design_id)

    def test_feedback_is_about_the_design_and_its_lineage(self):
        candidate = variants(self.base, {"leg_style": ["straight", "splayed"]})[1]
        record = feedback(candidate, rating=5, selected=True, note="looks sturdier")
        self.assertEqual(candidate.design_id, record["design_id"])
        self.assertEqual(5, record["rating"])
        self.assertTrue(record["selected"])
        self.assertEqual("splayed", record["parameters"]["leg_style"])


class WireframeToMatter(unittest.TestCase):
    def test_materialization_snaps_to_cells_and_does_not_claim_commit(self):
        design = rectangular_four_leg_frame(
            design_id="chair", purpose="support a seated person",
            top_size_m=(0.47, 0.037, 0.43), top_height_m=0.455)
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

    def test_wireframe_keeps_semantic_roles_for_the_renderer_and_agent(self):
        design = rectangular_four_leg_frame(
            design_id="table", purpose="work surface",
            top_size_m=(1.2, 0.05, 0.7), top_height_m=0.8)
        wire = design.wireframe()
        self.assertEqual("wireframe", wire["representation"])
        self.assertEqual("top", wire["parts"][0]["role"])
        self.assertEqual(["leg"] * 4, [p["role"] for p in wire["parts"][1:]])


if __name__ == "__main__":
    unittest.main()
