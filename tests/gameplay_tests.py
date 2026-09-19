"""Focused expedition law, inventory and persistence tests (no general material claim)."""
from copy import deepcopy
import base64
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"mcp"), str(ROOT/"playground")]
import gameplay as g
import gameplay_room
import room_store
import world_room


def terrain(height=1.0):
    return {"grid": {"nx": 41, "nz": 41, "cell_m": .25, "x0_m": -5, "z0_m": -5},
            "heights_b64": base64.b64encode(struct.pack("<1681f", *([height]*1681))).decode(),
            "view": {"eye_m": [0, 2.7, 0]}}


class Expedition(unittest.TestCase):
    def act(self, s, op, **extra):
        return g.action(s, {"action": op, "request_id": str(s["revision"]),
                            "at_m": s["spawn_m"], **extra})

    def ready(self):
        s = g.new(terrain())
        for kind, kg in (("stone", 2), ("dry_wood", 1), ("wet_wood", 1)):
            n = next(n for n in s["nodes"] if n["kind"] == kind)
            s = self.act(s, "gather", node=n["id"], kg=kg, at_m=n["at_m"])
            g.advance(s, s["time_s"]+1)
        s = self.act(s, "build")
        s = self.act(s, "load")
        s = self.act(s, "fuel", kg=.2)
        return self.act(s, "light")

    def audit(self, s):
        a = g.report(s)["audit"]
        self.assertLess(abs(a["material_residual_kg"]), 1e-9)
        self.assertLess(abs(a["energy_residual_j"]), 1e-5)

    def test_seed_and_invalid_spawn(self):
        self.assertEqual(g.new(terrain()), g.new(terrain()))
        self.assertNotEqual(g.new(terrain(), seed=8)["nodes"], g.new(terrain())["nodes"])
        with self.assertRaisesRegex(ValueError, "terrace"):
            g.new(terrain(.1))

    def test_full_batch_conserves_and_preserves_output_heat(self):
        s = self.ready()
        initial = deepcopy(s)
        g.advance(s, 500)
        self.assertAlmostEqual(s["dryer"]["water_kg"], 0)
        self.assertGreater(s["dryer"]["fuel_kg"], 0)
        self.assertFalse(s["dryer"]["lit"])
        self.assertEqual(s["dryer"]["wood_kg"], .8)
        self.audit(s)
        g.advance(s, 1300)
        s = self.act(s, "collect")
        self.assertAlmostEqual(s["inventory_kg"]["dry_wood"], 1.1)
        self.assertGreater(s["inventory_heat_j"]["dry_wood"], 0)
        self.audit(s)
        # Batching time must not award additional production.
        split = deepcopy(initial)
        for t in range(4, 1301):
            g.advance(split, t)
        split = self.act(split, "collect")
        self.assertAlmostEqual(split["ledger"]["burned_kg"], s["ledger"]["burned_kg"], places=10)
        self.audit(split)

    def test_stall_and_recharge_are_finite(self):
        s = self.ready()
        # Remove fuel by an accounted return to inventory, then load a tiny charge.
        d = s["dryer"]
        s["inventory_kg"]["dry_wood"] += d["fuel_kg"]-.001
        d["fuel_kg"] = .001
        g.advance(s, 900)
        self.assertGreater(d["water_kg"], .19)
        self.assertFalse(d["lit"])
        self.assertAlmostEqual(d["fuel_kg"], 0)
        with self.assertRaises(ValueError): self.act(s, "collect")
        self.audit(s)

    def test_roundtrip_preserves_partial_work_and_no_offline_credit(self):
        s = self.ready()
        g.advance(s, 73)
        self.assertGreater(s["dryer"]["water_kg"], 0)
        resumed = json.loads(json.dumps(s))
        g.advance(resumed, resumed["time_s"])
        self.assertEqual(resumed, s)
        g.advance(s, 600)
        g.advance(resumed, 600)
        self.assertEqual(resumed, s)
        with self.assertRaisesRegex(ValueError, "rewind"): g.advance(resumed, 1)
        self.audit(s)

    def test_atomic_validation_idempotency_and_reach(self):
        s = g.new(terrain())
        old = deepcopy(s)
        with self.assertRaises(ValueError): self.act(s, "build")
        self.assertEqual(s, old)
        n = s["nodes"][0]
        req = {"action": "gather", "request_id": "retry", "node": n["id"], "kg": 1, "at_m": n["at_m"]}
        after = g.action(s, req)
        self.assertEqual(g.action(after, req), after)
        with self.assertRaises(ValueError): g.action(after, {**req, "kg": 2})
        with self.assertRaises(ValueError): g.action(s, {**req, "at_m": [999,0,999]})
        for kg in (float("nan"), True, -1, 0, 3):
            with self.assertRaises(ValueError): g.action(s, {**req, "kg": kg})
        self.assertEqual(s, old)

    def test_failed_dryer_cannot_burn_or_repair_on_load(self):
        s = self.ready()
        s["dryer"]["damage"] = 1.0
        fuel = s["dryer"]["fuel_kg"]
        g.advance(s, 100)
        self.assertEqual(s["dryer"]["fuel_kg"], fuel)
        self.assertEqual(s["dryer"]["damage"], 1)
        with self.assertRaises(ValueError): self.act(s, "light")
        self.audit(s)

    def test_room_store_roundtrip_and_missing_half_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            store = room_store.RoomStore(Path(directory))
            room = world_room.Room("expedition")
            room.gameplay_record = self.ready()
            room.world_record = {"t_s": room.gameplay_record["time_s"], "opaque": "native snapshot"}
            store.save(room)
            loaded = store.load("expedition")
            self.assertEqual(loaded.gameplay_record, room.gameplay_record)
            self.assertEqual(loaded.world_record, room.world_record)
            path = store.path_of("expedition")
            record = json.loads(path.read_text())
            del record["gameplay"]
            path.write_text(json.dumps(record))
            with self.assertRaises(ValueError): store.load("expedition")

    def test_adapter_rolls_back_a_failed_save(self):
        s = g.new(terrain())
        n = s["nodes"][0]
        app = SimpleNamespace(room=SimpleNamespace(scene="expedition", gameplay_record=s, world_record={"old": 1}),
                              live_holder="world", live=SimpleNamespace(session=SimpleNamespace(id="s", state={"t":0})))
        req = {"session":"s", "op":"action", "action":{"action":"gather", "request_id":"x", "node":n["id"], "at_m":n["at_m"]}}
        with self.assertRaises(ValueError):
            gameplay_room.request(app, req, lambda *_: False)
        self.assertEqual(app.room.gameplay_record, s)
        self.assertEqual(n["kg"], 6)


if __name__ == "__main__":
    unittest.main()
