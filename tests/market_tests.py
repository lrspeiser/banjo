"""Market stock, personal ownership and world-time supply without a native build."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "playground"))
sys.path.insert(0, str(ROOT / "mcp"))
import market  # noqa: E402
import workshop_library  # noqa: E402
import room_store  # noqa: E402


class MarketLedger(unittest.TestCase):
    def test_bank_claim_requires_matching_native_meter_in_room_save(self):
        with tempfile.TemporaryDirectory() as temp:
            store = room_store.RoomStore(Path(temp))
            room = SimpleNamespace(scene="new-game", spec={"bodies": []}, chat=[],
                                   world_record={"energy_stores": [{"id": 3, "given_j": 99}]},
                                   market_pending=[{"request_id": "deposit-one", "owner_id": "alice",
                                                    "joules": 100, "store_name": "array battery",
                                                    "store_id": 3, "given_after_j": 100}])
            with self.assertRaisesRegex(ValueError, "matching native snapshot"):
                store.save(room)
            room.world_record["energy_stores"][0]["given_j"] = 100
            self.assertTrue(store.save(room))
            loaded = store.load("new-game")
            self.assertEqual({"deposit-one"}, loaded.market_durable_pending)
            app = SimpleNamespace(store=store, room=loaded, world_lock=threading.Lock(),
                                  runs_path=Path(temp) / "runs")
            market._settle(app)
            market._settle(app)
            with workshop_library._connect(app) as db:
                market._schema(db)
                self.assertEqual(100, market._balance(db, "alice"))
            self.assertEqual([], store.load("new-game").market_pending)

    def test_purchase_spends_personal_then_shared_stock_and_replenishes(self):
        with tempfile.TemporaryDirectory() as temp:
            app = SimpleNamespace(world_id="world", runs_path=Path(temp) / "runs",
                                  room=SimpleNamespace(world_record={"t_s": 0}), live=SimpleNamespace(session=None))
            scope = workshop_library.REQUEST_OWNER.set("alice")
            try:
                with workshop_library._connect(app) as db:
                    market._schema(db)
                    db.execute("UPDATE workshop_material_rack SET mass_kg=0.1 "
                               "WHERE owner_id='owner' AND material='oak'")
                    db.execute("INSERT INTO market_wallet(owner_id,balance_j) VALUES ('alice',500)")
                before = market._price(120, 60, 60)
                order = {"item_id": "oak-stock", "quoted_price_j": before,
                         "request_id": "one-oak-lot"}
                market._buy(app, "alice", order)
                market._buy(app, "alice", order)
                with workshop_library._connect(app) as db:
                    market._schema(db)
                    self.assertEqual(500 - before, market._balance(db, "alice"))
                    self.assertEqual(59, next(o for o in market._offers(db)
                                              if o["id"] == "oak-stock")["remaining"])
                self.assertAlmostEqual(0.6, next(r["mass_kg"] for r in workshop_library.rack(app)["materials"]
                                                if r["material"] == "oak"))
                workshop_library.take_from_rack(app, {"materials": [{"material": "oak", "needed_kg": 0.55}],
                                                       "goods": []})
                alice_oak = next(r for r in workshop_library.rack(app)["materials"]
                                 if r["material"] == "oak")
                self.assertAlmostEqual(0, alice_oak["personal_kg"])
                self.assertAlmostEqual(0.05, alice_oak["shared_kg"])
                with self.assertRaisesRegex(ValueError, "comes from the world and Market"):
                    workshop_library.set_rack(app, "oak", 100)
                app.room.world_record["t_s"] = 120
                with workshop_library._connect(app) as db:
                    market._schema(db)
                    market._restock(app, db)
                    restored = next(o for o in market._offers(db) if o["id"] == "oak-stock")
                self.assertEqual(60, restored["remaining"])
                self.assertEqual(before, restored["price_j"])
            finally:
                workshop_library.REQUEST_OWNER.reset(scope)


if __name__ == "__main__":
    unittest.main()
