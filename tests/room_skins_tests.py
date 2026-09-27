"""The finish a product carries out of the Workshop and into the room.

A skin says what a thing LOOKS like -- its colour, and how polished or matt it
is. It is set on a component at the bench (set_skin), carried into the room with
the product when it is installed, saved with the room, and read back by the page
that draws it.

The whole reason it cannot touch anything physical is the list of fields it is
allowed to say, so that list is what these check first. The mass, the strength,
the matter, the temperature and every measurement the room reports are the
MATERIAL's and are not reachable from a finish. Shape is not reachable either:
changing a shape changes what the engine is colliding, and that is `physical` on
the bench, which recompiles the matter and says the measurements are stale.

They also check the thing the whitelist comment in fracture_lab warns about --
a field the middle does not know about is dropped in silence, which is how a cut
once arrived as a solid box with no error anywhere. So a skin is put through a
real saved room and looked for on the other side.

    python tests/room_skins_tests.py -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "playground"))

import fracture_lab  # noqa: E402
import workshop_install  # noqa: E402

BODIES = [{"name": "deck"}, {"name": "left wheel"}, {"name": "right wheel"}]


class WhatAFinishMaySay(unittest.TestCase):
    def test_a_finish_says_colour_and_polish_and_nothing_else(self):
        # The invariant, written where it can fail: if this list ever grows a
        # field that reaches the matter, everything else here is worthless.
        self.assertEqual(sorted(fracture_lab.SKIN_FIELDS),
                         ["body", "color", "metalness", "roughness"])

    def test_it_keeps_what_it_is_given(self):
        kept = fracture_lab.normalise_skins(
            [{"body": "deck", "color": "#3a2a18", "roughness": 0.55, "metalness": 0.0}], BODIES)
        self.assertEqual(kept, [{"body": "deck", "color": "#3a2a18",
                                 "roughness": 0.55, "metalness": 0.0}])

    def test_what_it_refuses(self):
        for skins, why in (
            ([{"body": "nobody", "color": "red"}], "a body that is not in the room"),
            ([{"body": "deck", "shape": "box"}], "a field that could change a shape"),
            ([{"body": "deck", "mass_kg": 4}], "a field that could change the matter"),
            ([{"body": "deck", "color": "red"}, {"body": "deck", "color": "blue"}],
             "two finishes for one surface"),
            ([{"body": "deck", "roughness": 1.4}], "a roughness that is not a roughness"),
            ([{"body": "deck", "metalness": "shiny"}], "a metalness that is not a number"),
            ([{"body": "deck"}], "a finish that says nothing"),
            ([{"body": "deck", "color": "x" * 33}], "a colour longer than a colour"),
            ("not a list", "something that is not a list"),
        ):
            with self.subTest(why):
                with self.assertRaises(ValueError):
                    fracture_lab.normalise_skins(skins, BODIES)

    def test_there_can_be_more_than_a_room_holds_but_not_unboundedly_many(self):
        with self.assertRaises(ValueError):
            fracture_lab.normalise_skins(
                [{"body": "deck", "color": "red"}] * (fracture_lab.MAX_SKINS + 1), BODIES)


class AFinishIsOfWhatTheThingIsBuiltOf(unittest.TestCase):
    """The owner, 2026-09-26: "a finish should be of the material it is built
    with."

    Colour and polish are things you do to a surface: stain oak, paint it, sand
    it, lacquer it, and it is still oak -- which is why its grain still runs
    through whatever you put on. How metallic a thing is, is not something you
    do to a surface. It is whether light leaves the stuff by reflecting off it
    or by scattering about inside it, and that is what the thing IS.

    So a finish may take it DOWN -- painting a steel bracket really does cover
    the metal with a paint that is not one -- and may never take it up. Without
    this the room could be made to draw a drone as anodised aluminium while
    saying "oak, 12.04 kg" about it, which is a room saying two things at once.
    """

    THINGS = [{"name": "drone", "material": "oak"},
              {"name": "bracket", "material": "iron"},
              {"name": "pot", "material": "alumina ceramic"}]

    def skins(self, *rows):
        return fracture_lab.normalise_skins(list(rows), self.THINGS)

    def test_wood_can_be_stained_and_polished(self):
        self.assertEqual(self.skins({"body": "drone", "color": "#4a2f1c", "roughness": 0.3}),
                         [{"body": "drone", "color": "#4a2f1c", "roughness": 0.3}])

    def test_wood_cannot_be_made_metal(self):
        with self.assertRaises(ValueError) as caught:
            self.skins({"body": "drone", "color": "#39414a", "metalness": 0.85})
        said = str(caught.exception)
        self.assertIn("made of oak", said)
        self.assertIn("will not become a metal", said)

    def test_a_glaze_on_clay_is_allowed_and_a_mirror_is_not(self):
        self.assertIn("metalness", self.skins({"body": "pot", "metalness": 0.05})[0])
        with self.assertRaises(ValueError):
            self.skins({"body": "pot", "metalness": 0.4})

    def test_metal_may_be_painted_over(self):
        # The paint is a dielectric, so the painted bracket really is not
        # metallic any more. Down is a finish; up is a different substance.
        self.assertEqual(self.skins({"body": "bracket", "color": "#2b4a7a", "metalness": 0.0}),
                         [{"body": "bracket", "color": "#2b4a7a", "metalness": 0.0}])

    def test_metal_may_be_left_metal(self):
        self.assertEqual(self.skins({"body": "bracket", "metalness": 0.9}),
                         [{"body": "bracket", "metalness": 0.9}])

    def test_which_materials_are_metals_lives_with_the_materials(self):
        from mcp import engine_materials
        self.assertTrue(engine_materials.conducts("iron"))
        self.assertTrue(engine_materials.conducts("aluminum"))
        self.assertFalse(engine_materials.conducts("oak"))
        # And it travels with the catalogue, so nothing has to keep its own copy.
        self.assertEqual({d["material"]: d["metal"] for d in engine_materials.described()
                          if d["material"] in ("iron", "oak")},
                         {"iron": True, "oak": False})


class AFinishSurvivesTheRoom(unittest.TestCase):
    """The whitelist in the middle: a field it has not heard of is dropped in
    silence, so the only way to know a skin arrives is to send one through."""

    def test_a_finish_put_into_a_real_room_comes_out_of_it(self):
        spec = json.loads((ROOT / "playground" / "rooms" / "explore.json")
                          .read_text(encoding="utf-8"))
        body = spec["bodies"][0]["name"]
        spec["skins"] = [{"body": body, "color": "#3a2a18", "roughness": 0.55}]
        out = fracture_lab.validate(spec)
        self.assertEqual(out.get("skins"),
                         [{"body": body, "color": "#3a2a18", "roughness": 0.55}])

    def test_a_room_with_no_finishes_says_nothing_about_them(self):
        spec = json.loads((ROOT / "playground" / "rooms" / "explore.json")
                          .read_text(encoding="utf-8"))
        spec["skins"] = []
        self.assertNotIn("skins", fracture_lab.validate(spec))

    def test_a_finish_for_something_that_is_not_there_is_refused_by_the_room(self):
        spec = json.loads((ROOT / "playground" / "rooms" / "explore.json")
                          .read_text(encoding="utf-8"))
        spec["skins"] = [{"body": "a thing nobody made", "color": "red"}]
        with self.assertRaises(ValueError):
            fracture_lab.validate(spec)


class WhichBodyWearsWhich(unittest.TestCase):
    """A skin is set on a COMPONENT and a body can be several components joined
    into one thing, so the install has to decide which body wears what."""

    TO_BODY = {"deck": "deck", "rail": "deck", "hub": "left wheel", "tyre": "left wheel"}

    class Design:
        """Just enough of a design to say what each component is made of."""

        class Part:
            def __init__(self, name, material):
                self.name, self.material = name, material

        def __init__(self, materials):
            self.parts = [self.Part(n, m) for n, m in materials.items()]

    OAK = Design({"deck": "oak", "rail": "oak", "hub": "iron", "tyre": "rubber"})

    def finishes(self, overrides, design=None):
        return workshop_install._finishes(design or self.OAK, overrides, self.TO_BODY)

    def test_components_that_agree_dress_the_body_they_became(self):
        skins, argued = self.finishes({
            "deck": {"skin": {"color": "#3a2a18", "roughness": 0.55}},
            "rail": {"skin": {"color": "#3a2a18", "roughness": 0.55}}})
        self.assertEqual(argued, [])
        self.assertEqual(skins, [{"body": "deck", "color": "#3a2a18",
                                  "roughness": 0.55, "metalness": 0.0}])

    def test_components_that_disagree_leave_the_body_as_it_was(self):
        # One body has one surface. Picking a winner would be inventing an
        # answer nobody gave, so it is said instead.
        skins, argued = self.finishes({
            "deck": {"skin": {"color": "#3a2a18"}},
            "rail": {"skin": {"color": "#bbbbbb"}}})
        self.assertEqual(skins, [])
        self.assertEqual(argued, ["deck"])

    def test_a_component_nobody_dressed_carries_nothing(self):
        # Every component has a roughness and a metalness whether anybody chose
        # them or not; carrying those in would quietly repaint every installed
        # thing and take the shine off iron for no reason anybody asked for.
        self.assertEqual(self.finishes({}), ([], []))
        self.assertEqual(self.finishes({"deck": {"parameters": {"length_m": 2}}}), ([], []))

    def test_one_dressed_part_of_a_joined_body_dresses_it(self):
        skins, argued = self.finishes({"tyre": {"skin": {"color": "black", "roughness": 0.95}}})
        self.assertEqual(argued, [])
        self.assertEqual([s["body"] for s in skins], ["left wheel"])

    def test_a_finish_the_material_will_not_carry_costs_the_finish_not_the_install(self):
        # The room refuses one outright, and rightly. Here it is dropped and
        # named instead, so that asking for a metallic oak deck costs you the
        # finish rather than the whole installation.
        skins, argued = self.finishes({"deck": {"skin": {"color": "#39414a", "metalness": 0.9}}})
        self.assertEqual(skins, [])
        self.assertEqual(argued, ["deck"])
        # The same finish on a thing actually made of metal is carried.
        metal = self.Design({"deck": "iron", "rail": "iron", "hub": "iron", "tyre": "iron"})
        skins, argued = self.finishes(
            {"deck": {"skin": {"color": "#39414a", "metalness": 0.9}}}, metal)
        self.assertEqual(argued, [])
        self.assertEqual(skins, [{"body": "deck", "color": "#39414a",
                                  "roughness": 0.72, "metalness": 0.9}])

    def test_a_component_that_became_no_body_is_passed_over(self):
        skins, argued = self.finishes({"a part that was fitted away": {"skin": {"color": "red"}}})
        self.assertEqual((skins, argued), ([], []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
