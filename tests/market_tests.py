"""Market stock, personal ownership and world-time supply without a native build."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "playground"))
sys.path.insert(0, str(ROOT / "mcp"))
import market  # noqa: E402
import workshop_library  # noqa: E402
import room_store  # noqa: E402


class MarketLedger(unittest.TestCase):
    def test_complete_gap_cost_matches_actual_sequential_purchases(self):
        with tempfile.TemporaryDirectory() as temp:
            app=SimpleNamespace(world_id='world',runs_path=Path(temp)/'runs')
            with workshop_library._connect(app) as db:
                market._schema(db)
                db.execute("INSERT INTO market_wallet VALUES ('alice',10000)")
                offers=market._offers(db)
            recipe={'name':'Composite','materials':[
                {'material':'oak','kg':1.1,'held_kg':.1,'personal_kg':.05,'shared_kg':.05},
                {'material':'glass','kg':.5,'held_kg':0}],
                'goods':[{'substance':'copper wire','kg':.5,'held_kg':.5,'personal_kg':.5},
                         {'substance':'copper','kg':.7,'held_kg':0}]}
            plan=market._build_plan(recipe,offers,10000)
            self.assertEqual(4,len(plan['lines']))
            self.assertEqual('covered',next(l for l in plan['lines'] if l['substance']=='copper wire')['status'])
            oak=plan['lines'][0]
            self.assertEqual((.05,.05),(oak['debit_personal_kg'],oak['debit_shared_kg']))
            self.assertEqual(242,oak['cost_j']) # 120 then 122, not two stale 120 quotes.
            for line in plan['lines']:
                for index in range(line['lots']):
                    with workshop_library._connect(app) as db: current=market._offers(db)
                    offer=next(o for o in current if o['id']==line['offer_id'])
                    market._buy(app,'alice',{'item_id':offer['id'],'quoted_price_j':offer['price_j'],
                                           'request_id':f"{offer['id']}-{index}"})
            with workshop_library._connect(app) as db:
                self.assertEqual(plan['estimated_total_j'],10000-market._balance(db,'alice'))

    def test_shortage_and_absent_supplier_do_not_quote_a_partial_total(self):
        with tempfile.TemporaryDirectory() as temp:
            app=SimpleNamespace(runs_path=Path(temp)/'runs')
            with workshop_library._connect(app) as db:
                market._schema(db)
                db.execute("UPDATE market_stock SET remaining=1 WHERE item_id='oak-stock'")
                offers=market._offers(db)
            plan=market._build_plan({'name':'Needs sources','materials':[
                {'material':'oak','kg':1,'held_kg':0}, {'material':'unobtainium','kg':2,'held_kg':0}]},offers,10000)
            self.assertEqual(['stock-short','no-offer'],[l['status'] for l in plan['lines']])
            self.assertIsNone(plan['estimated_total_j'])
            self.assertFalse(plan['affordable'])
            self.assertEqual(1,plan['lines'][0]['lots_available'])
            self.assertEqual(.5,plan['lines'][0]['unavailable_kg'])

    def test_goal_compatible_affordable_saved_design_beats_tiny_gap_in_large_build(self):
        import goal_chains
        candidate=goal_chains.work_table_recipe()
        def recipe(name,kg,source='built-in'):
            return {**candidate,'name':name,'source':source,'readiness':{'ready_as_drawn':True},
                    'materials':[{'material':'oak','kg':kg,'held_kg':0}],
                    'goods':[{'substance':'copper wire','kg':.5,'held_kg':0}]}
        with tempfile.TemporaryDirectory() as temp:
            app=SimpleNamespace(runs_path=Path(temp)/'runs')
            with workshop_library._connect(app) as db:
                market._schema(db);offers=market._offers(db)
            large=recipe('Huge machine',20)
            small=recipe('My useful surface',.5,'saved');small['saved_design_id']='saved-surface'
            unrelated=recipe('Unrelated cheap part',.1);unrelated['kind']='not-a-surface'
            unrelated['goods']=[]
            goals={'chain_id':'renamed-chain','unlocked':True,'goals':[
                {'id':'first','title':'Study equipment','complete':False,'requirement':{'kind':'personal-test'}},
                {'id':'custom-surface','title':'Receive materials','complete':False,
                 'requirement':{'kind':'funded-box-surface','minimum_area_m2':.15}}]}
            chosen=market._recommend([large,unrelated,small],offers,500,goals)
            self.assertEqual(small['name'],chosen['name'])
            self.assertTrue(chosen['affordable'])
            self.assertEqual('custom-surface',chosen['goal']['id'])
            self.assertEqual(['Study equipment'],chosen['goal']['before'])
            self.assertEqual(450,chosen['estimated_total_j'])

    def test_subgram_shortfall_is_not_hidden_by_display_rounding(self):
        offer={'id':'small-stock','substance':'oak','base_j':1,'initial':2,'remaining':2,'mass_kg':.001}
        plan=market._build_plan({'name':'Fine part','materials':[{'material':'oak','kg':.00208,'held_kg':.002}]},[offer],1)
        self.assertAlmostEqual(.00008,plan['lines'][0]['gap_kg'])
        self.assertEqual(1,plan['estimated_total_j'])

    def test_guidance_uses_authenticated_guest_and_reports_missing_skill(self):
        app=SimpleNamespace(world_id='world')
        scope=workshop_library.REQUEST_OWNER.set('alice')
        try:
            with mock.patch('workshop_tabs.skills',return_value={'techniques':[
                {'id':'next','name':'Next technique','known':False,'within_reach':False,
                 'needs':[{'name':'First technique','known':False}], 'world_missing':['Equipment missing']}]}), \
                 mock.patch('workshop_tabs.recipes',return_value={'templates':[]}), \
                 mock.patch('starter_goals.view',return_value={'chain_id':'new','goals':[]}) as goals:
                guidance=market._guidance(app,[],0)
            goals.assert_called_once_with(app,'alice',{'chain':'active'})
            self.assertEqual(['First technique'],guidance['skill_blocked']['prerequisites'])
            self.assertEqual(['Equipment missing'],guidance['skill_blocked']['world_missing'])
        finally:workshop_library.REQUEST_OWNER.reset(scope)

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
                drawn = workshop_library.take_from_rack(app, {"materials": [{"material": "oak", "needed_kg": 0.55}],
                                                             "goods": []})
                alice_oak = next(r for r in workshop_library.rack(app)["materials"]
                                 if r["material"] == "oak")
                self.assertAlmostEqual(0, alice_oak["personal_kg"])
                self.assertAlmostEqual(0.05, alice_oak["shared_kg"])
                # A concurrent purchase followed by an installation failure
                # must restore the original owners without erasing that order.
                with workshop_library._connect(app) as db:
                    market._buy(app, "alice", {"item_id": "oak-stock", "quoted_price_j": 122,
                                              "request_id": "concurrent-oak-lot"})
                workshop_library.refund_rack(app, drawn)
                refunded = next(r for r in workshop_library.rack(app)["materials"] if r["material"] == "oak")
                self.assertAlmostEqual(1.0, refunded["personal_kg"])
                self.assertAlmostEqual(.1, refunded["shared_kg"])
                with self.assertRaisesRegex(ValueError, "comes from the world and Market"):
                    workshop_library.set_rack(app, "oak", 100)
                app.room.world_record["t_s"] = 120
                with workshop_library._connect(app) as db:
                    market._schema(db)
                    market._restock(app, db)
                    restored = next(o for o in market._offers(db) if o["id"] == "oak-stock")
                self.assertEqual(59, restored["remaining"])
                self.assertEqual(122, restored["price_j"])
            finally:
                workshop_library.REQUEST_OWNER.reset(scope)


if __name__ == "__main__":
    unittest.main()
