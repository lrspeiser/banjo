"""Tools that dig, through the MCP: a found oak pick in a clearing.

A one-piece oak pick -- a haft and an arm, joined -- lying on the soil of the
engine's clearing, given its point with `tool_point`, declared a swing-and-lever
with `interaction` and tried: swung into the soil, levered out, and swung onto
the bare rock. Then struck by hand in the world itself, where what the pry
broke out is kept as the ground's own dig edit and carried through the world
being opened again; and handed to the playground's room and back. All of it
through the MCP's own handlers, in the real engine. docs/ground-work.md.

Needs the library (BANJO_LIBRARY). No model and no network.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))

import room_world   # noqa: E402  (puts mcp/ on the path)
import banjo_mcp    # noqa: E402
import world_room   # noqa: E402

# The pick: an oak haft along x and an arm lying along -z from its +x end,
# touching it, both on the 0.04 m grid, lying on the clearing's soil (y = 0).
PICK = [
    {"name": "pick haft", "shape": "box", "material": "oak", "size_m": [0.8, 0.04, 0.04],
     "position_m": [0.0, 0.02, 1.22], "join": "pick"},
    {"name": "pick arm", "shape": "box", "material": "oak", "size_m": [0.04, 0.04, 0.28],
     "position_m": [0.38, 0.02, 1.06], "join": "pick"},
]
POINT = {"tip_m": [0.38, 0.02, 0.92], "pointing": [0, 0, -1], "grip_m": [-0.36, 0.02, 1.22],
         "width_m": 0.04, "thickness_m": 0.04, "angle_deg": 30, "length_m": 0.2}


def call(handler: str, /, **args):
    return banjo_mcp.HANDLERS[handler](args)


def clearing_with_pick() -> str:
    """The playground's clearing room, held as an MCP world, with the pick in it."""
    world_id = room_world.open_room(world_room.clearing())
    for part in PICK:
        call("add_object", world_id=world_id, object=dict(part))
    return world_id


def pointed(world_id: str) -> dict:
    return call("tool_point", world_id=world_id, body="pick arm", **POINT)


def trial_of(world_id: str, name: str) -> dict:
    return call("interaction", world_id=world_id, object=name, template="swing-and-lever",
                parts=["pick haft", "pick arm"], tool="pick haft")["trial"]


class ToolsByRecipe(unittest.TestCase):
    """A tool by name, laid out exactly and tried. Asked in the page for a
    mattock, the room's chat twice laid one by hand that was not a tool (317,000
    and 691,000 tokens): its head off the cells, its tip past its head."""

    def tearDown(self):
        for world_id in [w for w in banjo_mcp.WORLDS if w.startswith("room-")]:
            room_world.close_room(world_id)

    def profile(self, world_id: str, name: str) -> dict:
        return next(p for p in banjo_mcp.WORLDS[world_id]["interactions"] if p["object"] == name)

    def test_a_mattock_and_a_hoe_are_built_and_dig_when_tried(self):
        world_id = room_world.open_room(world_room.clearing())
        for which, at, label in (("mattock", [0.0, 1.2], "Break up the soil"),
                                 ("hoe", [-1.6, 2.4], "Hoe the soil")):
            said = call("build_recipe", world_id=world_id, recipe=which, at_m=at)
            trial = said["and"]["interaction"]["trial"]
            point = said["and"]["tool_point"]
            soil = trial.get("into_soil") or {}
            print(f"\n  {which}: {point.get('mass_kg')} kg, {point.get('its_weight_about_the_grip_n_m')} N m "
                  f"about the grip; into the soil {soil.get('swung')}; then {soil.get('levered')}")
            self.assertTrue(trial.get("tried"), trial)
            self.assertEqual(self.profile(world_id, f"the {which}")["use"]["label"], label)
            broke = [w for w in (soil.get("levered") or []) if w.get("loosened_litres", 0) > 0]
            self.assertTrue(broke, f"the {which} broke nothing out: {soil}")

    def test_a_tool_is_made_the_one_the_person_asked_for(self):
        world_id = room_world.open_room(world_room.clearing())
        said = call("build_recipe", world_id=world_id, recipe="hoe", at_m=[0.0, 1.2],
                    tool={"call_it": "the grub hoe", "head": {"width_m": 0.08},
                          "use": {"label": "Grub it out", "past": "grubbed out"}})
        self.assertEqual(said["parts"], ["grub hoe haft", "grub hoe blade"])
        profile = self.profile(world_id, "the grub hoe")
        self.assertEqual((profile["tool"], profile["use"]["label"], profile["use"]["past"]),
                         ("grub hoe haft", "Grub it out", "grubbed out"))
        self.assertIn("0.08 m by 0.12 m blade", said["built"])

    def test_a_broader_head_gets_a_point_as_broad_and_is_still_pried(self):
        """The chat's mattock: a 0.12 m head on the recipe's 0.08 m point met
        the ground with its edges first, and it had filled in pry false."""
        world_id = room_world.open_room(world_room.clearing())
        said = call("build_recipe", world_id=world_id, recipe="mattock", at_m=[0.0, 1.2],
                    tool={"head": {"width_m": 0.12}, "use": {"label": "Break up the soil", "pry": False}})
        self.assertEqual(said["and"]["tool_point"]["width_mm"], 120.0)
        self.assertNotIn("pry", self.profile(world_id, "the mattock")["use"])

    def test_a_tool_is_one_material(self):
        """A joined piece is all one material: an "iron" head on an oak haft was
        built all of oak, 1.344 kg."""
        world_id = room_world.open_room(world_room.clearing())
        with self.assertRaisesRegex(banjo_mcp.Refused, "one material"):
            call("build_recipe", world_id=world_id, recipe="mattock", at_m=[0.0, 1.2],
                 tool={"head": {"material": "iron"}})

    def test_a_head_the_wrist_cannot_hold_level_is_refused_whole(self):
        world_id = room_world.open_room(world_room.clearing())
        before = len(banjo_mcp.WORLDS[world_id]["scene"]["bodies"])
        with self.assertRaisesRegex(banjo_mcp.Refused, "wrist"):
            call("build_recipe", world_id=world_id, recipe="mattock", at_m=[0.0, 1.2],
                 tool={"material": "iron"})
        self.assertEqual(len(banjo_mcp.WORLDS[world_id]["scene"]["bodies"]), before, "nothing built")
        self.assertEqual(banjo_mcp.WORLDS[world_id].get("interactions") or [], [])

    def test_the_blanks_a_model_fills_are_dropped(self):
        world_id = room_world.open_room(world_room.clearing())
        said = call("build_recipe", world_id=world_id, recipe="pick", at_m=[0.0, 1.2],
                    tool={"call_it": "", "head": {"material": "", "length_m": 0, "width_m": 0},
                          "point": {}, "use": {"label": ""}})
        self.assertEqual(said["parts"], ["pick haft", "pick arm"])
        self.assertNotIn("use", self.profile(world_id, "the pick"))

    def test_the_pick_is_laid_out_as_the_guide_has_it(self):
        recipe = banjo_mcp.RECIPES["pick"]
        self.assertEqual([(p["name"], p["size_m"], p["position_m"]) for p in recipe["parts"]],
                         [("pick haft", [0.8, 0.04, 0.04], (0.0, 0.02, 0.02)),
                          ("pick arm", [0.04, 0.04, 0.28], (0.38, 0.02, -0.14))])
        point = recipe["then"][0][1]
        self.assertEqual((point["tip_m"], point["grip_m"], point["width_m"], point["length_m"]),
                         ((0.38, 0.02, -0.28), (-0.36, 0.02, 0.02), 0.04, 0.2))


class HowAToolIsUsed(unittest.TestCase):
    """A tool's profile may shape how the person uses it (`use`): what the click
    is called, how the hand swings and pries it -- within the hand's bounds --
    and its trial swings it that way (playground/tool_use.py uses the same)."""

    def tearDown(self):
        for world_id in [w for w in banjo_mcp.WORLDS if w.startswith("room-")]:
            room_world.close_room(world_id)

    def declared(self, world_id: str, use: dict, trial: bool = False, name: str = "the mattock"):
        return call("interaction", world_id=world_id, object=name, template="swing-and-lever",
                    parts=["pick haft", "pick arm"], tool="pick haft", trial=trial, use=use)

    def test_what_is_said_is_kept_and_the_blanks_a_model_fills_are_dropped(self):
        world_id = clearing_with_pick()
        pointed(world_id)
        said = self.declared(world_id, {"label": "Break up the soil", "past": "",
                                        "swing": {"speed_m_s": 0, "raise_deg": 140},
                                        "reach_m": [0, 0], "repeat": True})
        self.assertEqual(said["use"], {"label": "Break up the soil", "swing": {"raise_deg": 140.0},
                                       "repeat": True})
        self.assertIn("'Break up the soil'", said["how_a_person_uses_it"])
        kept = banjo_mcp.WORLDS[world_id]["interactions"][0]
        self.assertEqual(kept["use"]["label"], "Break up the soil")

    def test_a_swing_past_the_hands_bounds_is_refused(self):
        world_id = clearing_with_pick()
        pointed(world_id)
        # The room's chat gave a mattock its trial's 9.8 m/s point speed as the
        # hand's: live, the swing glanced.
        with self.assertRaisesRegex(banjo_mcp.Refused, "1 to 5"):
            self.declared(world_id, {"swing": {"speed_m_s": 9.8}})

    def test_a_tool_that_is_never_pried_is_tried_that_way(self):
        world_id = clearing_with_pick()
        pointed(world_id)
        said = self.declared(world_id, {"label": "Drive it in", "pry": False}, trial=True,
                             name="the stake")
        self.assertIn("never pried", said["how_a_person_uses_it"])
        soil = said["trial"]["into_soil"]
        print(f"\n  never pried: {soil}")
        self.assertIsInstance(soil, dict, soil)
        self.assertNotIn("levered", soil)
        self.assertIn("drawn_out", soil)

    def test_said_again_under_a_new_name_the_tool_has_one_profile(self):
        """A pick built by recipe, then declared again as "the mattock": left
        with both, the page took the tool up as the first."""
        world_id = clearing_with_pick()
        pointed(world_id)
        self.declared(world_id, {}, name="the pick")
        self.declared(world_id, {"label": "Break up the soil", "past": "broke up"})
        profiles = banjo_mcp.WORLDS[world_id]["interactions"]
        self.assertEqual([p["object"] for p in profiles], ["the mattock"])
        self.assertEqual(profiles[0]["use"]["past"], "broke up")

    def test_a_copy_of_a_pick_is_a_pick_used_the_same_way(self):
        world_id = clearing_with_pick()
        pointed(world_id)
        self.declared(world_id, {"label": "Dig here", "swing": {"raise_deg": 120}}, name="the pick")
        call("duplicate", world_id=world_id, names=["pick haft", "pick arm"], prefix="second",
             offset_m=[1.2, 0.0, 0.0], trial=False)
        copy = next(p for p in banjo_mcp.WORLDS[world_id]["interactions"] if p["object"] != "the pick")
        self.assertEqual((copy["template"], copy["tool"]), ("swing-and-lever", "second pick haft"))
        self.assertEqual(copy["use"], {"label": "Dig here", "swing": {"raise_deg": 120.0}})


class APickInTheClearing(unittest.TestCase):
    def tearDown(self):
        for world_id in [w for w in banjo_mcp.WORLDS if w.startswith("room-")]:
            room_world.close_room(world_id)

    def test_a_joined_part_takes_the_point_as_its_whole_piece(self):
        world_id = clearing_with_pick()
        said = pointed(world_id)
        print(f"\n  point on {said['body']} ({said['material']}), {said['mass_kg']} kg; its weight "
              f"pulls {said['its_weight_about_the_grip_n_m']} N m about the grip")
        self.assertEqual(said["body"], "pick haft")
        self.assertIn("one_piece", said)
        self.assertNotIn("too_heavy_to_swing", said)
        self.assertLess(said["its_weight_about_the_grip_n_m"], banjo_mcp.HAND_TORQUE_N_M)
        scene = banjo_mcp.WORLDS[world_id]["scene"]
        self.assertEqual([p["body"] for p in scene["tool_points"]], ["pick haft"])
        # A point is not controls: the answer says the one step left, as the
        # call to make, with the whole piece's parts.
        self.assertIn("swing-and-lever", said["next"])
        self.assertIn('["pick haft", "pick arm"]', said["next"])
        call("interaction", world_id=world_id, object="the pick", template="swing-and-lever",
             parts=["pick haft", "pick arm"], tool="pick haft", trial=False)
        self.assertNotIn("next", pointed(world_id), "a pick with its controls was told to add them")

    def test_a_grip_off_the_tool_is_refused(self):
        """The room's chat once gave the pick's grip with its height and depth
        swapped -- 1.2 m above the haft -- and it was taken: the trial's hand held
        a point in the air, and the pick's point met no ground. The grip is where
        a hand closes on the tool, so it is on the tool, or refused."""
        world_id = clearing_with_pick()
        with self.assertRaises(banjo_mcp.Refused) as refused:
            call("tool_point", world_id=world_id, body="pick arm",
                 **dict(POINT, grip_m=[-0.36, 1.22, 0.02]))
        self.assertIn("the grip is not on the body's matter", str(refused.exception))
        self.assertEqual(banjo_mcp.WORLDS[world_id]["scene"].get("tool_points") or [], [])

    def test_it_is_tried_into_soil_levered_out_and_stopped_by_rock(self):
        world_id = clearing_with_pick()
        pointed(world_id)
        trial = trial_of(world_id, "the pick")
        print(f"\n  trial: {trial}")
        self.assertTrue(trial["tried"], trial.get("why"))
        soil = trial["into_soil"]["swung"][0]
        self.assertEqual(soil["ground"], "soil")
        self.assertIn(soil["what_happened"], ("in the ground", "broke out"))
        # In, and no further than the point is long and one step's travel.
        self.assertGreater(soil["went_in_mm"], 10.0)
        self.assertLessEqual(soil["went_in_mm"], 200.0 + 1000.0 * soil["arrived_m_s"] / 240.0)
        out = trial["into_soil"]["levered"][-1]
        self.assertFalse(out["still_in_the_ground"])
        self.assertIn(out["what_happened"], ("broke out", "pulled out"))
        rock = trial["into_rock"]["swung"][0]
        self.assertEqual((rock["ground"], rock["what_happened"]), ("rock", "stopped"))
        self.assertIn("cannot press", rock["why"])
        self.assertTrue(trial["tool_whole"])
        # The owner's gate: no job may take more than 10% longer than the
        # interaction it computes.
        self.assertLessEqual(trial["computing_took_s"], 1.1 * trial["simulated_s"])

    def test_what_it_is_called_does_not_reach_the_physics(self):
        """Nothing a profile says is physics: the same tool, tried under two names,
        is the same trial to the last digit."""
        world_id = clearing_with_pick()
        pointed(world_id)
        a = {k: v for k, v in trial_of(world_id, "the pick").items() if k != "computing_took_s"}
        b = {k: v for k, v in trial_of(world_id, "grandfather's old pick").items()
             if k != "computing_took_s"}
        self.assertEqual(a, b)

    def test_a_strike_breaks_ground_out_and_the_ground_keeps_it(self):
        world_id = clearing_with_pick()
        said = pointed(world_id)
        call("wield", world_id=world_id, name="pick haft", grip_m=said["grip_m"])
        # Held ready in front of a person standing at [0, 1.2] facing -z.
        banjo_mcp.WORLDS[world_id]["world"].move_held([0.0, 1.02, 0.66])
        for _ in range(240):
            banjo_mcp._step_answering(banjo_mcp.WORLDS[world_id]["world"], [])
        swung = call("strike", world_id=world_id, at_m=[0.0, 0.0], standing_m=[0.0, 1.2])
        print(f"\n  swung: {swung['ground_work']}")
        work = swung["ground_work"][0]
        self.assertEqual(work["ground"], "soil")
        self.assertTrue(work["still_in_the_ground"])
        levered = call("strike", world_id=world_id, lever=True, standing_m=[0.0, 1.2])
        print(f"  levered: {levered['ground_work']} then: {levered.get('then')}")
        out = levered["ground_work"][-1]
        self.assertFalse(out["still_in_the_ground"])
        self.assertEqual(out["what_happened"], "broke out")
        self.assertGreater(out["loosened_litres"], 0.0)
        entry = banjo_mcp.WORLDS[world_id]
        edits = entry["scene"]["terrain"]["edits"]
        self.assertEqual(len(edits), 1)
        self.assertIn("dig", edits[0])
        carried = banjo_mcp._ground_carried(entry)["soil"]["cubic_metres"]
        self.assertAlmostEqual(carried, out["loosened_litres"] / 1000.0, delta=1e-6)
        # Opened again -- any change does it -- the ground has kept the hole, and
        # what came out of it is still carried, to the bit.
        call("add_object", world_id=world_id,
             object={"name": "stone", "shape": "box", "material": "concrete",
                     "size_m": [0.08, 0.08, 0.08], "position_m": [-2.0, -2.0]})
        self.assertEqual(banjo_mcp._ground_carried(entry)["soil"]["cubic_metres"], carried)

    def test_a_caller_that_fills_every_field_is_not_refused_for_them(self):
        """The room's chat sends every property a tool has. Asked for a pick, it
        once sent this swing-and-lever with a blank draw, nock, limbs and
        projectile, and was refused twelve times; once it filled them with the
        pick's own parts, and was refused twelve times more, changing their
        numbers but never leaving them out. The template it said is what it
        meant: what a swing-and-lever has none of is set aside, and it is told."""
        world_id = clearing_with_pick()
        pointed(world_id)
        pick = {"object": "the pick", "template": "swing-and-lever",
                "parts": ["pick haft", "pick arm"], "tool": "pick haft", "trial": False}
        blanks = {"draw": {"part": "", "axis": [0, 0, 0], "max_m": 0.0, "speed_m_s": 0.0},
                  "nock": {"a": "", "b": ""}, "limbs": [], "projectile": ""}
        said = call("interaction", world_id=world_id, **pick, **blanks)
        self.assertEqual((said["template"], said["tool"]), ("swing-and-lever", "pick haft"))
        self.assertNotIn("not_read", said)
        # As the chat sent them, in its first round and its last.
        for axis, max_m, speed_m_s in (([0, 0, 0], 0.0, 0.0), ([0, 0, 1], 0.2, 1.0)):
            filled = {"draw": {"part": "pick haft", "axis": axis, "max_m": max_m,
                               "speed_m_s": speed_m_s},
                      "nock": {"a": "pick haft", "b": "pick arm"},
                      "limbs": [["pick haft", "pick arm"]], "projectile": "pick arm"}
            said = call("interaction", world_id=world_id, **pick, **filled)
            self.assertEqual((said["template"], said["tool"]), ("swing-and-lever", "pick haft"))
            self.assertTrue(said["not_read"].startswith("draw, limbs, nock, projectile:"),
                            said["not_read"])
        self.assertEqual(banjo_mcp.WORLDS[world_id]["interactions"],
                         [{"object": "the pick", "template": "swing-and-lever",
                           "parts": ["pick haft", "pick arm"], "tool": "pick haft"}])

    def test_a_bow_said_to_be_a_swing_is_refused_not_set_aside(self):
        """What is set aside is what would not work anyway. A whole working bow
        said to be a swing-and-lever says two things, and is refused."""
        world_id = room_world.open_room(world_room.courtyard())
        profile = room_world.mcp_profile(world_room.courtyard()["interactions"][0])
        with self.assertRaises(banjo_mcp.Refused) as refused:
            call("interaction", world_id=world_id, trial=False,
                 **dict(profile, template="swing-and-lever", tool=profile["parts"][0]))
        self.assertIn("make a working draw-and-release", str(refused.exception))

    def test_with_no_template_said_a_tool_is_still_refused(self):
        """With no template said a profile is a draw-and-release, and a tool sent
        with it may be the only sign that a pick was meant: refused, so the
        caller says which, not set aside."""
        world_id = clearing_with_pick()
        pointed(world_id)
        with self.assertRaises(banjo_mcp.Refused) as refused:
            call("interaction", world_id=world_id, object="the pick", template="",
                 parts=["pick haft", "pick arm"], tool="pick haft", trial=False)
        self.assertIn("['tool'] are not part of a draw-and-release", str(refused.exception))

    def test_a_bow_sent_with_a_tool_is_still_a_bow(self):
        world_id = room_world.open_room(world_room.courtyard())
        profile = room_world.mcp_profile(world_room.courtyard()["interactions"][0])
        said = call("interaction", world_id=world_id, trial=False, tool="", **profile)
        self.assertEqual(said["template"], "draw-and-release")
        self.assertNotIn("tool", said)
        self.assertNotIn("not_read", said)
        # Named, as a caller that fills every field names it: the string has no
        # point, so it is no swing-and-lever, and it is set aside.
        said = call("interaction", world_id=world_id, trial=False,
                    **dict(profile, template="draw-and-release", tool=profile["draw"]["part"]))
        self.assertEqual(said["template"], "draw-and-release")
        self.assertNotIn("tool", said)
        self.assertTrue(said["not_read"].startswith("tool:"), said["not_read"])

    def test_the_room_is_handed_the_point_and_the_profile(self):
        world_id = clearing_with_pick()
        pointed(world_id)
        call("interaction", world_id=world_id, object="the pick", template="swing-and-lever",
             parts=["pick haft", "pick arm"], tool="pick haft", trial=False)
        spec = room_world.export_spec(banjo_mcp.WORLDS[world_id])
        self.assertEqual(len(spec["tool_points"]), 1)
        point = spec["tool_points"][0]
        self.assertEqual(point["body"], "pick haft")
        for got, want in zip(point["tip_mm"], [380.0, 20.0, 920.0]):
            self.assertAlmostEqual(got, want, delta=0.01)
        self.assertEqual(spec["interactions"][0]["template"], "swing-and-lever")
        again = room_world.open_room(spec)
        entry = banjo_mcp.WORLDS[again]
        self.assertEqual([p.body for p in entry["world"].tool_points()], ["pick haft"])
        self.assertEqual([p["object"] for p in entry["interactions"]], ["the pick"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
