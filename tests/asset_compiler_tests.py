"""The asset compiler (tools/asset_compiler.py) against fixtures built by code.

What these pin down is mostly what the compiler must NOT do. Converting a mesh
into cells is easy to do plausibly and wrongly: a cup comes back solid, a plate
too thin to resolve comes back three times its own volume, a slot comes back
welded shut, and every one of those looks right in a picture. So the cases here
are the ones with an answer known in advance -- an analytic volume, a cavity of
512 cells that must stay empty, a gap of exactly 36 bonds -- and the assertions
are on the numbers rather than on the shape looking sensible.

Nothing here runs the engine. The grid convention and the bond rule are
reproduced in the compiler from src/matter/Lattice.cpp, and these tests pin the
reproduction to the numbers that file states.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import asset_compiler as ac  # noqa: E402
import asset_fixtures as af  # noqa: E402

CELL_M = af.CELL_MM / 1000.0


class FixtureTestCase(unittest.TestCase):
    """The fixtures are written once, into a directory nothing else touches."""

    @classmethod
    def setUpClass(cls):
        cls._temp = tempfile.TemporaryDirectory()
        cls.fixtures = Path(cls._temp.name)
        af.build(cls.fixtures)

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()

    def document(self, name: str) -> dict:
        return json.loads((self.fixtures / f"{name}.assembly.json").read_text(encoding="utf-8"))

    def compile(self, name: str, **changes) -> dict:
        document = self.document(name)
        document.update(changes)
        return ac.compile_assembly(document, self.fixtures)

    def categories(self, blueprint: dict) -> list[str]:
        return sorted(failure["category"] for failure in blueprint["validation"]["failures"])

    def mesh(self, name: str) -> dict:
        return ac.scaled(ac.read_obj(self.fixtures / f"{name}.obj"), af.UNIT)


class APartIsConvertedOnceAndPlacedManyTimes(FixtureTestCase):

    def test_the_repeated_tread_is_converted_once_and_instanced_twelve_times(self):
        blueprint = self.compile("stair")
        validation = blueprint["validation"]
        self.assertEqual(validation["conversions_run"], 1,
                         "one tread shape converted more than once")
        self.assertEqual(validation["instances"], af.TREAD_COUNT)
        self.assertEqual(len(blueprint["conversions"]), 1)
        stored = blueprint["conversions"][blueprint["parts"]["tread"]["conversion"]]
        # 2,400 cells held once against 28,800 placed: the saving is the whole
        # point of keeping the occupancy in the part's own frame.
        self.assertEqual(stored["occupancy"]["count"], 2400)
        self.assertEqual(validation["cells_total"], 2400 * af.TREAD_COUNT)

    def test_two_names_for_one_shape_share_a_single_conversion(self):
        document = self.document("stair")
        document["parts"]["second_tread"] = dict(document["parts"]["tread"])
        document["instances"].append({"id": "other", "part": "second_tread",
                                      "translation_mm": [0.0, 0.0, -400.0]})
        blueprint = ac.compile_assembly(document, self.fixtures)
        self.assertEqual(blueprint["validation"]["conversions_run"], 1,
                         "the same geometry under a second name was converted twice")
        self.assertEqual(blueprint["parts"]["tread"]["conversion"],
                         blueprint["parts"]["second_tread"]["conversion"])

    def test_occupancy_is_the_same_cells_whatever_the_instance_transform(self):
        """Placing is a re-index of the one conversion, not a second voxelisation."""
        part = [tuple(cell) for cell in ac.occupancy(self.mesh("tread"), CELL_M)["cells"]]
        for translation, rotation in (((0, 0, 0), (0, 0, 0)), ((17, 3, -40), (0, 0, 0)),
                                      ((0, 0, 0), (0, 90, 0)), ((5, -2, 9), (90, 180, 270))):
            with self.subTest(translation=translation, rotation=rotation):
                placed = ac.place_instance(part, translation, rotation)
                # The same tread, turned and voxelised again from its mesh: a
                # quarter turn maps cell centres onto cell centres, so this is
                # an equality and not a tolerance.
                turned = ac.scaled(af.rotated(af.stair_tread(), rotation), af.UNIT)
                direct = ac.occupancy(turned, CELL_M)["cells"]
                shifted = sorted(tuple(cell[axis] + translation[axis] for axis in range(3))
                                 for cell in direct)
                self.assertEqual(placed, shifted)
                self.assertEqual(len(placed), len(part))

    def test_an_instance_turned_by_anything_but_a_quarter_turn_is_refused(self):
        """Measured: the same tread at 45 degrees is 2,484 cells against 2,400.

        A part re-indexed onto the shared grid keeps its cell count exactly; a
        part voxelised again in world space does not, so the two are different
        assets and saying so beats returning either one quietly.
        """
        with self.assertRaises(ValueError) as refused:
            ac.place_instance([(0, 0, 0)], (0, 0, 0), (0.0, 37.0, 0.0))
        self.assertIn("quarter turn", str(refused.exception))


class WhatTheOccupancyMustKeep(FixtureTestCase):

    def test_the_cup_keeps_its_cavity(self):
        blueprint = self.compile("cup")
        conversion = blueprint["conversions"][blueprint["parts"]["cup"]["conversion"]]
        cells = {tuple(cell) for cell in conversion["occupancy"]["cells"]}
        # The cup is 12 x 10 x 12 cells outside and its cavity is 8 x 8 x 8, so
        # a solid conversion would be 1,440 cells and a correct one is 928.
        self.assertEqual(len(cells), 928)
        cavity = {(i, j, k) for i in range(2, 10) for j in range(2, 10) for k in range(2, 10)}
        self.assertEqual(cavity & cells, set(),
                         "the cup came back filled in, which is what a fill from the outside does")
        self.assertEqual({cell for cell in cells if cell[1] == 10}, set(),
                         "something closed the open top")
        self.assertEqual(self.categories(blueprint), [])

    def test_the_solid_block_converts_to_its_analytic_volume_exactly(self):
        blueprint = self.compile("block")
        conversion = blueprint["conversions"][blueprint["parts"]["block"]["conversion"]]
        occupancy = conversion["occupancy"]
        self.assertEqual(occupancy["count"], 20 * 12 * 8)
        self.assertAlmostEqual(conversion["geometry"]["volume_m3"] * 1e9,
                               af.ANALYTIC_VOLUME_MM3["block"], places=6)
        # Every face lies on a cell boundary, so there is no sampling error at
        # all: the residue measured here is 1.1e-16, which is the last bit of
        # 0.01 cubed against the divergence-theorem sum, not a lost cell.
        self.assertLess(abs(occupancy["volume_error"]), 1.0e-15)

    def test_the_volume_error_stays_well_inside_the_surface_bound(self):
        """Centre sampling can be wrong by one cell for every cell the surface
        crosses, which is |dV| <= A h. Measured on the block at four cell sizes,
        the worst was 3.475% at 6 mm, or 0.113 of that bound; the budget below
        is 0.15 of it. Where the faces lie on cell boundaries nothing is
        sampled wrongly and all that is left is float rounding, 1.1e-16.
        """
        mesh = self.mesh("block")
        report = ac.mesh_report(mesh)
        for cell_mm, aligned in ((10.0, True), (7.0, False), (6.0, False), (3.0, False)):
            with self.subTest(cell_mm=cell_mm):
                cell_m = cell_mm / 1000.0
                found = ac.occupancy(mesh, cell_m)
                error = (found["volume_m3"] - report["volume_m3"]) / report["volume_m3"]
                bound = report["surface_area_m2"] * cell_m / report["volume_m3"]
                self.assertLessEqual(abs(error), 0.15 * bound)
                if aligned:
                    self.assertLess(abs(error), 1.0e-15)

    def test_the_block_mass_properties_match_the_analytic_solid(self):
        """The generator's cell term m h^2 / 6 makes a box of whole cells exact.

        Measured: 1.344 kg and Ixx 2.3296e-3 kg m2 against m (b^2 + c^2) / 12,
        which agree to the last place a double carries.
        """
        blueprint = self.compile("block")
        properties = blueprint["conversions"][blueprint["parts"]["block"]["conversion"]]["mass_properties"]
        a, b, c = (value / 1000.0 for value in af.BLOCK_MM)
        mass = a * b * c * ac.MATERIAL_DENSITY_KG_M3["oak"]
        self.assertAlmostEqual(properties["mass_kg"], mass, places=12)
        self.assertAlmostEqual(properties["center_of_mass_m"][0], 0.5 * a, places=12)
        for axis, (first, second) in enumerate(((b, c), (a, c), (a, b))):
            self.assertAlmostEqual(properties["inertia_kg_m2"][axis][axis],
                                   mass * (first ** 2 + second ** 2) / 12.0, places=12)

    def test_a_face_on_a_cell_centre_plane_is_a_tie_and_not_a_defect(self):
        """The tread is 300 mm long, so at a 40 mm cell its far face lies exactly
        on the centre plane of cell 7, since 300 mm is seven and a half cells.

        Measured: 5 of the 40 cells are inside on one scan axis and outside on
        another, with no unclosed row anywhere. The mesh is closed and its
        volume is right, so this is a tie on the surface rather than a defect,
        and calling it invalid_solid would condemn a sound part for the cell
        size it was asked about.
        """
        found = ac.occupancy(self.mesh("tread"), 0.04)
        self.assertEqual(found["axis_disagreements"], 5)
        self.assertEqual(found["unclosed_rows"], 0)
        blueprint = self.compile("stair", cell_size_m=0.04)
        self.assertEqual(self.categories(blueprint), [])
        self.assertIn("editable_voxels", blueprint["validation"]["capabilities"])

    def test_the_box_decomposition_covers_every_cell_exactly_once(self):
        """Five boxes for a cup of 928 cells: what a part that need only be
        collided with can be instead of 928 nodes."""
        cells = {tuple(cell) for cell in ac.occupancy(self.mesh("cup"), CELL_M)["cells"]}
        boxes = ac.box_decomposition(cells)
        self.assertEqual(len(boxes), 5)
        covered: list[tuple[int, int, int]] = []
        for i, j, k, width, height, depth in boxes:
            covered.extend((i + x, j + y, k + z) for x in range(width)
                           for y in range(height) for z in range(depth))
        self.assertEqual(len(covered), len(cells), "the boxes overlap")
        self.assertEqual(set(covered), cells)


class WhatIsRefusedRatherThanRepaired(FixtureTestCase):

    def test_a_plate_thinner_than_a_cell_is_refused_and_never_thickened(self):
        blueprint = self.compile("plate")
        self.assertIn("feature_below_resolution", self.categories(blueprint))
        conversion = blueprint["conversions"][blueprint["parts"]["plate"]["conversion"]]
        # The plate is 3 mm through and sits across the cell centre plane, so
        # centre sampling reports a full 10 mm slab: 400 cells of 1,000 mm3
        # against 120,000 mm3 of solid, which is 3.33 times the matter. The
        # compiler must say so rather than hand back the slab.
        self.assertEqual(conversion["occupancy"]["count"], 400)
        self.assertAlmostEqual(conversion["occupancy"]["volume_error"], 10.0 / 3.0 - 1.0, places=9)
        self.assertAlmostEqual(conversion["occupancy"]["thickness_m"], af.PLATE_MM[1] / 1000.0, places=9)
        self.assertNotIn("editable_voxels", blueprint["validation"]["capabilities"])
        detail = next(f["detail"] for f in blueprint["validation"]["failures"]
                      if f["category"] == "feature_below_resolution")
        self.assertIn("3 mm", detail)

    def test_a_slot_inside_the_bond_horizon_is_reported_as_a_lost_gap(self):
        """Two 60 mm blocks with a 10 mm slot, fused into one body.

        buildBonds filters by grid distance alone (src/matter/Lattice.cpp:113),
        so the columns either side of the slot -- exactly 2 cells apart, inside
        the horizon of 2 -- are bonded through the empty cell between them. The
        6 x 6 face gives exactly 36 such bonds, and the slot is welded shut.
        """
        blueprint = self.compile("slot")
        self.assertIn("required_gap_lost", self.categories(blueprint))
        self.assertEqual([group["void_crossing_bonds"] for group in blueprint["bond_groups"]], [36])
        self.assertNotIn("editable_voxels", blueprint["validation"]["capabilities"])
        # The two parts are one fused group, which is the set a single
        # generateVoxelLattice call would be handed.
        self.assertEqual(len(blueprint["bond_groups"]), 1)
        self.assertEqual(blueprint["bond_groups"][0]["cells"], 2 * 216)

    def test_a_gap_wider_than_the_horizon_keeps_its_gap(self):
        """The same two blocks 30 mm apart: three cells, outside the horizon."""
        document = self.document("slot")
        document["instances"][1]["translation_mm"] = [af.SLOT_BLOCK_MM + 30.0, 0.0, 0.0]
        blueprint = ac.compile_assembly(document, self.fixtures)
        self.assertEqual([group["void_crossing_bonds"] for group in blueprint["bond_groups"]], [0])
        # Nothing bonds them and they do not touch, so declaring them one body
        # is the ambiguity now, rather than a lost gap.
        self.assertEqual(self.categories(blueprint), ["connection_ambiguous"])

    def test_a_staircase_that_will_not_fit_the_room_says_so_in_cells(self):
        """Twelve treads of 2,400 cells is 28,800 against the lane's 16,000."""
        blueprint = self.compile("stair")
        self.assertIn("physics_budget_exceeded", self.categories(blueprint))
        self.assertEqual(blueprint["validation"]["cells_total"], 28800)
        self.assertEqual(blueprint["cell_budget"], ac.ROOM_CELL_BUDGET)
        self.assertNotIn("editable_voxels", blueprint["validation"]["capabilities"])

    def test_an_undeclared_unit_is_refused_rather_than_guessed(self):
        document = self.document("block")
        document["parts"]["block"].pop("unit")
        blueprint = ac.compile_assembly(document, self.fixtures)
        self.assertEqual(self.categories(blueprint), ["units_ambiguous"])
        self.assertIsNone(blueprint["parts"]["block"]["conversion"])
        self.assertEqual(blueprint["validation"]["capabilities"], [],
                         "a part that was never converted still claimed capabilities")

    def test_an_assembly_without_a_rights_record_is_not_publishable(self):
        document = self.document("block")
        document.pop("rights")
        blueprint = ac.compile_assembly(document, self.fixtures)
        self.assertIn("rights_unverified", self.categories(blueprint))
        self.assertFalse(blueprint["validation"]["publishable"])

    def test_a_material_outside_the_catalogue_keeps_collision_and_loses_the_rest(self):
        document = self.document("block")
        document["parts"]["block"]["material"] = "unobtainium"
        blueprint = ac.compile_assembly(document, self.fixtures)
        self.assertIn("material_unknown", self.categories(blueprint))
        capabilities = blueprint["validation"]["capabilities"]
        self.assertIn("static_collision", capabilities)
        self.assertNotIn("movable_rigid", capabilities)
        self.assertNotIn("editable_voxels", capabilities)
        conversion = blueprint["conversions"][blueprint["parts"]["block"]["conversion"]]
        self.assertIsNone(conversion["mass_properties"])

    def test_nothing_this_slice_produces_claims_to_have_been_tested_or_powered(self):
        """No engine runs here, so two flags can never be earned."""
        for name in ("block", "cup", "slot", "stair"):
            with self.subTest(name=name):
                capabilities = self.compile(name)["validation"]["capabilities"]
                self.assertNotIn("functionally_tested", capabilities)
                self.assertNotIn("powered", capabilities)


class WhatTheGeneratorWouldBeHanded(FixtureTestCase):

    def test_the_neighbour_rule_is_the_one_the_generator_uses(self):
        """Grid distance alone, in the positive half, so each pair appears once.

        At a horizon of 2 that is 16 offsets: 3 at distance 1, 6 at root two,
        4 at root three and 3 at distance 2.
        """
        offsets = ac.horizon_offsets(2)
        self.assertEqual(len(offsets), 16)
        self.assertEqual(len(set(offsets)), 16)
        for dx, dy, dz in offsets:
            self.assertLessEqual((dx * dx + dy * dy + dz * dz) ** 0.5, 2.0 + 1e-9)
            self.assertNotIn((-dx, -dy, -dz), offsets, "a pair would be bonded twice")

    def test_only_a_two_cell_step_can_cross_a_void_at_this_horizon(self):
        """A diagonal step grazes a corner; it does not pass through a cell."""
        spanning = [offset for offset in ac.horizon_offsets(2) if ac.interior_offsets(offset)]
        self.assertEqual(sorted(spanning), [(0, 0, 2), (0, 2, 0), (2, 0, 0)])
        self.assertEqual(ac.interior_offsets((2, 0, 0)), ((1, 0, 0),))
        self.assertEqual(ac.interior_offsets((1, 1, 0)), ())


if __name__ == "__main__":
    unittest.main()
