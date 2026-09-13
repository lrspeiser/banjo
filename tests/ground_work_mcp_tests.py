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
