"""The room on /world, and the tools that change it.

The model's side is not tested here -- that needs a key and a paid round trip.
What is tested is everything underneath it: that the room opens, that the tools
do what they say, and above all that a change the engine would refuse is refused
HERE, where the thing that made it can be told about it.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "playground"))

import fracture_lab      # noqa: E402
import live_session      # noqa: E402
import world_room        # noqa: E402

ENGINE = next((p for p in [
    ROOT / "build/integration/Release/banjo_live_world_run.exe",
    ROOT / "build/integration/banjo_live_world_run",
] if p.is_file()), None)


class TheRoomAsAuthored(unittest.TestCase):
    def test_every_material_in_the_catalogue_is_in_it(self):
        """The room is there to be experimented on, so it has to carry the whole
        catalogue: a room of three materials cannot show that what a thing is
        made of is what decides how it behaves."""
        used = {b["material"] for b in world_room.room()["bodies"]}
        self.assertEqual(used, set(world_room.MATERIALS),
                         f"missing from the room: {set(world_room.MATERIALS) - used}")

    def test_every_side_is_a_whole_number_of_cells(self):
        spec = world_room.room()
        cell_mm = spec["cell_m"] * 1000.0
        for body in spec["bodies"]:
            for axis, side in zip("xyz", body["size_mm"]):
                self.assertAlmostEqual(
                    side / cell_mm, round(side / cell_mm), places=6,
                    msg=f"{body['name']} is {side} mm on {axis}, which is not a whole "
                        f"number of {cell_mm:g} mm cells")

    def test_nothing_loose_is_buried_in_the_floor(self):
        """A body's centre is its middle, so an object on the floor sits at half
        its own height. Authoring one at y = 0 buries half of it, and the engine
        will push it out on the first step -- which looks like the room
        exploding for no reason."""
        for body in world_room.room()["bodies"]:
            if body.get("anchored"):
                continue
            bottom = body["center_mm"][1] - body["size_mm"][1] / 2.0
            self.assertGreaterEqual(bottom, -1e-6,
                                    f"{body['name']} starts {-bottom:.0f} mm into the floor")

    def test_it_fits_in_the_lane(self):
        spec = fracture_lab.validate(world_room.room())
        cells = sum(fracture_lab.body_cells(b, spec["cell_m"]) for b in spec["bodies"])
        self.assertLess(cells, 16000,
                        f"the room is {cells} cells and the lane holds about 16,000")

    def test_the_scene_the_engine_gets_asks_for_plasticity(self):
        """Without it nothing can hold a shape it was pushed into, so nothing
        can dent. It was set on the room, validated, and then dropped on the way
        to the engine, because the scene document only ever carried bodies."""
        document = fracture_lab.scene_document(fracture_lab.validate(world_room.room()))
        self.assertTrue(document["plasticity"],
                        "the engine is not being told to allow a permanent set")


    def test_there_is_something_of_every_material_to_drop_things_on(self):
        """Targets, not just things to throw.

        A room where the only thing that breaks is one glass pane teaches one
        fact. Every material has its own threshold and its own way of failing,
        and the only way to see that is to have one of each to aim at."""
        plates = [b for b in world_room.room()["bodies"] if "plate" in b["name"]]
        self.assertEqual({b["material"] for b in plates}, set(world_room.MATERIALS),
                         "not every material has something to drop things on")
        for material in world_room.MATERIALS:
            thicknesses = {b["size_mm"][1] for b in plates if b["material"] == material}
            self.assertGreater(len(thicknesses), 1,
                               f"{material} comes in only one thickness, so nothing "
                               f"there can show that thickness matters")

    def test_every_plate_is_bridged_rather_than_lying_on_the_floor(self):
        """What breaks a plate is a span under it.

        The same plate flat on the ground is held everywhere and will not break
        however hard it is hit, so a room of plates lying on the floor would
        have nothing to show."""
        room = world_room.room()["bodies"]
        for plate in [b for b in room if "plate" in b["name"]]:
            bottom = plate["center_mm"][1] - plate["size_mm"][1] / 2.0
            self.assertGreater(bottom, 50.0,
                               f"{plate['name']} sits {bottom:.0f} mm up, which is on "
                               f"the floor rather than on piers")


class TheToolsThatChangeIt(unittest.TestCase):
    def setUp(self):
        self.room = world_room.Room()

    def test_adding_something_puts_it_there(self):
        note = self.room.add_object(
            {"name": "test ball", "shape": "sphere", "material": "glass",
             "size_mm": [100, 100, 100], "position_mm": [0, 3000, -2500],
             "velocity_m_s": [0, 0, 0], "anchored": False})
        self.assertIn("glass", note)
        self.assertIsNotNone(self.room.find("test ball"))

    def test_a_change_the_engine_would_refuse_is_refused_here(self):
        """And the room is left exactly as it was.

        This is the whole point of checking inside the tool. A complaint raised
        when the room is rebuilt arrives after the model's turn has ended: the
        person reads a validator message about overlapping cells and the model,
        which is the only thing that can move the object, never hears about it.
        """
        before = [dict(b) for b in self.room.bodies()]
        with self.assertRaises(ValueError) as caught:
            # Right on top of a plate that is already there. Found rather than
            # written down, so the test does not quietly stop testing anything
            # when the room is laid out differently.
            plate = next(b for b in self.room.bodies() if "plate" in b["name"])
            self.room.add_object(
                {"name": "overlapping tile", "shape": "box", "material": "ceramic",
                 "size_mm": list(plate["size_mm"]),
                 "position_mm": list(plate["center_mm"]),
                 "velocity_m_s": [0, 0, 0], "anchored": False})
        self.assertIn("same cells", str(caught.exception))
        self.assertEqual(self.room.bodies(), before, "the refused change was left behind")

    def test_a_bad_material_or_shape_is_refused_by_name(self):
        for bad in ({"material": "cheese"}, {"shape": "dodecahedron"}):
            args = {"name": "x", "shape": "box", "material": "glass",
                    "size_mm": [100, 100, 100], "position_mm": [0, 2000, -3000],
                    "velocity_m_s": [0, 0, 0], "anchored": False}
            args.update(bad)
            with self.assertRaises(ValueError):
                self.room.add_object(args)

    def test_clearing_and_rebuilding_works(self):
        self.assertIn("emptied", self.room.clear_room({}))
        self.assertEqual(self.room.bodies(), [])
        # An empty room is not a broken one: emptying is the first half of
        # "clear this and build me ...", and checking an empty scene asks the
        # validator about a single-tile lane nobody mentioned.
        self.room.add_object(
            {"name": "lone plate", "shape": "box", "material": "glass",
             "size_mm": [600, 20, 200], "position_mm": [0, 410, 900],
             "velocity_m_s": [0, 0, 0], "anchored": False})
        self.assertEqual(len(self.room.bodies()), 1)

    def test_moving_and_removing_name_what_they_touched(self):
        self.assertIn("iron ball", self.room.move_object(
            {"name": "iron ball", "position_mm": [0, 2000, -3000]}))
        self.assertIn("iron ball", self.room.remove_object({"name": "iron ball"}))
        self.assertIsNone(self.room.find("iron ball"))
        with self.assertRaises(ValueError):
            self.room.remove_object({"name": "iron ball"})


@unittest.skipUnless(ENGINE, "the live engine is not built")
class TheRoomActuallyOpens(unittest.TestCase):
    def test_it_opens_and_every_body_says_what_it_is_made_of(self):
        runs = ROOT / "build" / "playground-runs"
        runs.mkdir(parents=True, exist_ok=True)
        spec = fracture_lab.validate(world_room.room())
        session = live_session.Session(ENGINE, spec, runs)
        try:
            bodies = session.state["bodies"]
            self.assertEqual(len(bodies), len(spec["bodies"]))
            for body in bodies:
                self.assertTrue(body.get("material"),
                                f"{body['name']} came back with no material, so nothing "
                                f"can label it")
            # The label needs the material, and the pointer needs the ray.
            found = session.send(op="pick", **{"from": [-0.9, 3.0, 0.0], "dir": [0, -1, 0]})
            self.assertTrue(found["hit"])
            self.assertEqual(found["name"], "iron ball")
            # And it runs far faster than real time, which is the rule this
            # whole engine is built to.
            import time
            began = time.perf_counter()
            for _ in range(60):
                state = session.send(op="step", dt=1 / 120.0, n=4)
                while state.get("breakable"):
                    state = session.send(op="fracture", name=state["breakable"][0])
            wall = time.perf_counter() - began
            self.assertLess(wall, 2.0 * 1.1,
                            f"2 s of room took {wall:.2f} s, which is past the rule")
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
