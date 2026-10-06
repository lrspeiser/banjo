"""Market stock, personal ownership and world-time supply without a native build."""
from __future__ import annotations

from pathlib import Path
from copy import deepcopy
import os
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
import live_session
import world_room
import server
import world_clock

ENGINE = Path(os.environ['BANJO_LIVE_ENGINE']) if os.environ.get('BANJO_LIVE_ENGINE') else None


@unittest.skipUnless(ENGINE and ENGINE.is_file(), 'BANJO_LIVE_ENGINE is required')
class AutomaticSolarBank(unittest.TestCase):
    """Actual solar/storage/draw counters, with explicit owned source fixtures."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.live = live_session.Live(); self.addCleanup(self.live.shutdown)
        self.room = world_room.Room('tests-solar')
        machines = self.room.spec['machines']
        machines['motors'] = []; machines['controls'] = []; machines['programs'] = []
        machines['stores'] = [dict(machines['stores'][0], capacity_j=1000., charge_j=300.)]
        machines['stores'].append(dict(machines['stores'][0], name='second battery', charge_j=0.))
        machines['panels'].append(dict(machines['panels'][0], name='second panel', store='second battery'))
        root = Path(self.temp.name)
        self.app = SimpleNamespace(room=self.room, live=self.live, live_holder='world', engine_path=ENGINE,
            runs_path=root/'runs', store=room_store.RoomStore(root/'rooms'), world_lock=threading.Lock())
        self.live.open(self.app, {'spec':self.room.spec})
        stores = self.live.session.state['machines']['stores']
        self.room.workshop_installs = [
            {'owner_id':owner, 'resources_charged':True, 'component_to_body':{'battery':s['body']},
             'recipe':{'kind':'custom-energy-device', 'component_overrides':{'@machines':{
                'stores':[{'name':s['name'], 'in':'battery', 'bank_reserve_fraction':.05}]}}}}
            for owner, s in zip(('alice','bob'), stores)]
        self.assertTrue(server.keep_world(self.app, 'initial bank fixture'))

    def balance(self, owner):
        with workshop_library._connect(self.app) as db:
            market._schema(db)
            return market._balance(db, owner)

    def step(self, seconds=1):
        for _ in range(seconds*4):
            self.live.act({'session':self.live.session.id,'op':'step','dt':1/240,'n':60})

    def test_sunlight_auto_debit_private_credit_reserve_and_unattended_clock(self):
        self.assertEqual(0,self.balance('alice')) # initial 300 J cannot mint income
        self.assertEqual(0,self.balance('bob'))
        before = deepcopy(self.room.world_record)
        clock = world_clock.WorldClock(self.app, keep=server.keep_world)
        self.assertTrue(clock._tick(.25))
        self.assertGreater(self.balance('alice'),0)
        self.assertEqual(0,self.balance('bob')) # filling 5% reserve first
        for _ in range(10):self.assertTrue(clock._tick(.25))
        self.assertGreater(self.balance('bob'),0)
        saved = self.room.world_record
        for owner, store in zip(('alice','bob'),saved['energy_stores']):
            old = next(s for s in before['energy_stores'] if s['id']==store['id'])
            sunlight = sum(p['collected_j'] for p in saved['solar_panels'] if p['store']==store['id'])
            self.assertAlmostEqual(self.balance(owner),store['given_j']-old['given_j'],places=8)
            self.assertLessEqual(self.balance(owner),sunlight+1e-8)
            self.assertGreaterEqual(store['charge_j'],50.)
            self.assertAlmostEqual(old['charge_j']+sunlight,store['charge_j']+self.balance(owner),places=7)
        self.assertEqual(1,len(market.bank_sources(self.app,'alice')))
        self.assertEqual(1,len(market.bank_sources(self.app,'bob')))
        self.assertEqual([],market.bank_sources(self.app,'visitor'))
        totals = [self.balance(o) for o in ('alice','bob')]
        self.assertTrue(server.keep_world(self.app,'repeat without simulation'))
        self.assertEqual(totals,[self.balance(o) for o in ('alice','bob')])
        print('native solar bank:', {'wallets_j':totals, 'dt_s':1/240,
            'energy_residual_j':max(abs(s['charge_j']+self.balance(o)-b['charge_j']-
                sum(p['collected_j'] for p in saved['solar_panels'] if p['store']==s['id']))
                for o,s,b in zip(('alice','bob'),saved['energy_stores'],before['energy_stores']))})

    def test_failed_save_restart_discards_unsaved_debit_and_retry_credits_once(self):
        self.step(2)
        durable = self.app.store.load('tests-solar')
        with mock.patch.object(self.app.store,'save',side_effect=OSError('disk full')):
            self.assertFalse(server.keep_world(self.app,'failed bank save'))
        self.assertEqual(0,self.balance('alice'))
        self.assertTrue(self.room.market_pending)
        self.live.open(self.app,{'spec':durable.spec,'snapshot':durable.world_record})
        self.app.room=self.room=durable
        self.assertTrue(server.keep_world(self.app,'restore unsaved bank'))
        self.assertEqual(0,self.balance('alice'))
        self.step(2)
        with mock.patch.object(self.app.store,'save',side_effect=OSError('disk full')):
            self.assertFalse(server.keep_world(self.app,'fail again'))
        pending = deepcopy(self.room.market_pending)
        self.assertTrue(server.keep_world(self.app,'retry bank save'))
        self.assertEqual(sum(r['joules'] for r in pending if r['owner_id']=='alice'),self.balance('alice'))
        balance = self.balance('alice')
        self.assertTrue(server.keep_world(self.app,'retry unchanged'))
        self.assertEqual(balance,self.balance('alice'))
        durable=self.app.store.load('tests-solar')
        self.live.open(self.app,{'spec':durable.spec,'snapshot':durable.world_record})
        self.app.room=self.room=durable
        self.assertTrue(server.keep_world(self.app,'restart settled bank'))
        self.assertEqual(balance,self.balance('alice'))

    def test_saved_draw_crash_before_sql_settlement_recovers_once(self):
        self.step(2)
        with mock.patch.object(market,'_settle',side_effect=OSError('crash after native save')):
            with self.assertRaises(OSError):server.keep_world(self.app,'paired bank save')
        durable=self.app.store.load('tests-solar')
        self.assertTrue(durable.market_pending)
        self.live.open(self.app,{'spec':durable.spec,'snapshot':durable.world_record})
        self.app.room=self.room=durable
        market._settle(self.app)
        total=self.balance('alice');self.assertGreater(total,0)
        market._settle(self.app)
        self.assertEqual(total,self.balance('alice'))
        self.assertTrue(server.keep_world(self.app,'no duplicate sunlight'))
        self.assertEqual(total,self.balance('alice'))

    def test_night_stops_income_and_missing_source_never_redirects_to_another_owner(self):
        self.step(2);server.keep_world(self.app,'daytime')
        self.live.session.send(op='sun',elevation_deg=0.,azimuth_deg=0.,irradiance_w_m2=0.)
        self.step(1);server.keep_world(self.app,'night')
        totals=[self.balance(o) for o in ('alice','bob')]
        self.step(1);server.keep_world(self.app,'night again')
        self.assertEqual(totals,[self.balance(o) for o in ('alice','bob')])
        self.assertEqual(0,market.bank_sources(self.app,'alice')[0]['generation_w'])
        wrong=deepcopy(self.room.energy_banks[0]);wrong['body']='removed array'
        self.room.energy_banks=[wrong,self.room.energy_banks[1]]
        self.assertEqual([],market.bank_sources(self.app,'alice'))

    def test_older_paid_array_adopts_connector_but_unpaid_or_unassigned_source_does_not(self):
        self.room.energy_banks=[]
        legacy=self.room.workshop_installs[0]
        legacy['recipe']['kind']='solar-array'
        legacy['recipe']['component_overrides']['@machines']['stores'][0].pop('bank_reserve_fraction')
        self.room.workshop_installs[1]['resources_charged']=False
        market.connect_banks(self.room,self.room.world_record)
        self.assertEqual(1,len(self.room.energy_banks));self.assertEqual('alice',self.room.energy_banks[0]['owner_id'])
        self.assertEqual(.05,self.room.energy_banks[0]['reserve_fraction'])
        self.room.workshop_installs=[] # bounded receipts can expire, bank binding remains
        self.step(1);self.assertTrue(server.keep_world(self.app,'legacy array bank'))
        self.assertGreater(self.balance('alice'),0);self.assertEqual(0,self.balance('bob'))

    def test_corrupt_or_duplicate_bank_bindings_are_rejected(self):
        for bad in ([self.room.energy_banks[0]]*2, [dict(self.room.energy_banks[0],reserve_fraction=.01)],
                    [dict(self.room.energy_banks[0],exported_j=-1)], [dict(self.room.energy_banks[0],owner_id='')]):
            with self.subTest(bad=bad),self.assertRaises(ValueError):market.validate_banks(bad)

    def test_sunlight_spent_on_other_work_cannot_cash_out_initial_charge(self):
        self.step(1)
        snapshot,_=self.live.snapshot()
        bank=self.room.energy_banks[0]
        collected=sum(p['collected_j'] for p in snapshot['solar_panels'] if p['store']==bank['store_id'])
        self.live.act({'session':self.live.session.id,'op':'draw','store':bank['store_id'],'joules':collected})
        self.assertTrue(server.keep_world(self.app,'sunlight used for other work'))
        self.assertEqual(0,self.balance('alice'))
        self.step(1);self.assertTrue(server.keep_world(self.app,'new sunlight becomes income'))
        self.assertGreater(self.balance('alice'),0)
        self.assertLessEqual(self.balance('alice'),collected+1e-8)


class MarketLedger(unittest.TestCase):
    def test_complete_gap_cost_matches_actual_sequential_purchases(self):
        with tempfile.TemporaryDirectory() as temp:
            app=SimpleNamespace(world_id='world',runs_path=Path(temp)/'runs')
            with workshop_library._connect(app) as db:
                market._schema(db)
                db.execute("INSERT INTO market_wallet VALUES ('alice',10000)")
                offers=market._offers(db,playable=True)
            recipe={'name':'Composite','materials':[
                {'material':'iron','kg':2.1,'held_kg':.1,'personal_kg':.05,'shared_kg':.05},
                {'material':'glass','kg':.5,'held_kg':0}],
                'goods':[{'substance':'copper wire','kg':.5,'held_kg':.5,'personal_kg':.5},
                         {'substance':'copper','kg':.7,'held_kg':0}]}
            plan=market._build_plan(recipe,offers,10000)
            self.assertEqual(4,len(plan['lines']))
            self.assertEqual('covered',next(l for l in plan['lines'] if l['substance']=='copper wire')['status'])
            iron=plan['lines'][0]
            self.assertEqual((.05,.05),(iron['debit_personal_kg'],iron['debit_shared_kg']))
            self.assertEqual(1532,iron['cost_j']) # 760 then 772, not two stale quotes.
            for line in plan['lines']:
                for index in range(line['lots']):
                    with workshop_library._connect(app) as db: current=market._offers(db,playable=True)
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
                 mock.patch('starter_goals.view',return_value={'chain_id':'new','goals':[]}) as goals, \
                 mock.patch('player_guidance.resolve',return_value={'project':None}) as unified:
                # Since 0c18d185 the Market's guidance starts from the one
                # resolved next action (player_guidance.resolve, which reads
                # the live world); it too must be bound to the signed-in guest.
                guidance=market._guidance(app,[],0)
            unified.assert_called_once_with(app,'alice',offers=[],balance=0)
            self.assertEqual({'project':None},guidance['player'])
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
                               "WHERE owner_id='owner' AND material='iron'")
                    db.execute("INSERT INTO market_wallet(owner_id,balance_j) VALUES ('alice',3000)")
                before = market._price(760, 48, 48)
                order = {"item_id": "iron-stock", "quoted_price_j": before,
                         "request_id": "one-iron-lot"}
                market._buy(app, "alice", order)
                market._buy(app, "alice", order)
                with workshop_library._connect(app) as db:
                    market._schema(db)
                    self.assertEqual(3000 - before, market._balance(db, "alice"))
                    self.assertEqual(47, next(o for o in market._offers(db,playable=True)
                                              if o["id"] == "iron-stock")["remaining"])
                self.assertAlmostEqual(1.1, next(r["mass_kg"] for r in workshop_library.rack(app)["materials"]
                                                if r["material"] == "iron"))
                drawn = workshop_library.take_from_rack(app, {"materials": [{"material": "iron", "needed_kg": 1.05}],
                                                             "goods": []})
                alice_iron = next(r for r in workshop_library.rack(app)["materials"]
                                 if r["material"] == "iron")
                self.assertAlmostEqual(0, alice_iron["personal_kg"])
                self.assertAlmostEqual(0.05, alice_iron["shared_kg"])
                # A concurrent purchase followed by an installation failure
                # must restore the original owners without erasing that order.
                with workshop_library._connect(app) as db:
                    market._buy(app, "alice", {"item_id": "iron-stock", "quoted_price_j": 772,
                                              "request_id": "concurrent-iron-lot"})
                workshop_library.refund_rack(app, drawn)
                refunded = next(r for r in workshop_library.rack(app)["materials"] if r["material"] == "iron")
                self.assertAlmostEqual(2.0, refunded["personal_kg"])
                self.assertAlmostEqual(.1, refunded["shared_kg"])
                with self.assertRaisesRegex(ValueError, "comes from the world and Market"):
                    workshop_library.set_rack(app, "iron", 100)
                app.room.world_record["t_s"] = 120
                with workshop_library._connect(app) as db:
                    market._schema(db)
                    market._restock(app, db)
                    restored = next(o for o in market._offers(db,playable=True) if o["id"] == "iron-stock")
                self.assertEqual(47, restored["remaining"])
                self.assertEqual(772, restored["price_j"])
            finally:
                workshop_library.REQUEST_OWNER.reset(scope)


if __name__ == "__main__":
    unittest.main()
