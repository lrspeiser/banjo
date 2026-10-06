"""Finite energy escrow, durable native evidence and exact request recovery."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'playground'),str(ROOT/'mcp'),str(ROOT)]
import physical_matter as matter
import workshop_library as library


class CutEscrow(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.calls=[];self.receipts={};self.used=199.25;self.fail=False
        self.app=SimpleNamespace(workshop_db=Path(self.temp.name)/'private.db',world_id='a'*32)
        self.app.live=SimpleNamespace(session=SimpleNamespace(send=self.send),snapshot=self.snapshot)
        with library._connect(self.app) as db:
            matter._schema(db)
            db.execute('INSERT INTO market_wallet VALUES (?,?)',('alice',1000))
            db.commit()
        self.at=[.125,.375,.125];self.ident='cut-request-0001'

    def snapshot(self):
        return {'ground':{'debris':{'receipts':deepcopy(self.receipts)}}},None

    def send(self,**command):
        self.calls.append(command)
        if self.fail:raise OSError('native response unavailable')
        receipt={'consumed_work_j':self.used,'supported':True,'body_id':800000001,'model':'work-cut-v2'}
        self.receipts[command['work_source']]={'answer':receipt}
        return {'ground_cut':receipt}

    def cut(self,persist=lambda *_:True,owner='alice',at=None):
        return matter.cut(self.app,at or self.at,self.ident,owner,persist)

    def test_finite_work_unused_refund_and_replay(self):
        result=self.cut()
        self.assertEqual(200,result['charged_j']);self.assertEqual(800,matter.balance(self.app,'alice'))
        self.assertEqual(result,self.cut());self.assertEqual(1,len(self.calls))
        self.assertEqual(1000,self.calls[0]['work_j'])

    def test_failed_save_recovers_existing_native_work_without_another_tool_action(self):
        with self.assertRaisesRegex(ValueError,'save pending'):self.cut(lambda *_:False)
        self.assertEqual(0,matter.balance(self.app,'alice'))
        recovered=matter.recover_cut(self.app,self.ident,'alice',lambda *_:True)
        self.assertEqual(200,recovered['charged_j']);self.assertEqual(800,matter.balance(self.app,'alice'))
        self.assertEqual(1,len(self.calls))
        self.assertEqual(recovered,matter.recover_cut(self.app,self.ident,'alice',lambda *_:True))

    def test_unknown_execution_keeps_reservation_and_reuses_the_same_source(self):
        self.fail=True
        with self.assertRaises(OSError):self.cut()
        self.assertEqual(0,matter.balance(self.app,'alice'))
        self.assertIsNone(matter.recover_cut(self.app,self.ident,'alice',lambda *_:True))
        self.fail=False;self.used=400
        self.cut();self.assertEqual(600,matter.balance(self.app,'alice'))
        self.assertEqual(self.calls[0]['work_source'],self.calls[1]['work_source'])

    def test_peer_and_changed_target_cannot_reuse_reservations(self):
        self.cut()
        with self.assertRaisesRegex(ValueError,'another player'):self.cut(owner='bob')
        with self.assertRaisesRegex(ValueError,'another player'):self.cut(at=[1.,.375,.125])
        with self.assertRaisesRegex(ValueError,'another player'):matter.recover_cut(self.app,self.ident,'bob',lambda *_:True)
        self.assertEqual(1,len(self.calls))

    def test_empty_energy_does_not_call_native_or_create_a_debit(self):
        with library._connect(self.app) as db:
            db.execute("UPDATE market_wallet SET balance_j=0 WHERE owner_id='alice'");db.commit()
        self.assertEqual('no energy',self.cut()['kind']);self.assertEqual([],self.calls)

    def test_unsupported_cut_refunds_every_reserved_joule(self):
        self.used=0.;self.cut();self.assertEqual(1000,matter.balance(self.app,'alice'))

    def test_out_of_budget_native_receipt_cannot_be_settled(self):
        self.used=1001
        with self.assertRaisesRegex(ValueError,'exceeded'):self.cut()
        self.assertEqual(0,matter.balance(self.app,'alice'))


ENGINE=Path(os.environ['BANJO_LIVE_ENGINE']).resolve() if os.environ.get('BANJO_LIVE_ENGINE') else None


class PlayerMatterBoundary(unittest.TestCase):
    def test_named_matter_routes_preserve_funded_authoring_boundary(self):
        import fabrication_room
        for path in ('/api/world/matter/collect','/api/world/matter/shown'):
            fabrication_room.check_player_request(path,{'request_id':'route-fixture-0001'})
        for path in ('/api/world/matter/native','/api/world/raw','/api/world/add'):
            with self.subTest(path=path),self.assertRaises(ValueError):
                fabrication_room.check_player_request(path,{})
        for op in ('strike-cell','collect-ground-debris','ground_withdraw','add','restore'):
            with self.subTest(op=op),self.assertRaises(ValueError):
                fabrication_room.check_player_request('/api/live/act',{'op':op})


@unittest.skipUnless(ENGINE and ENGINE.is_file(),'BANJO_LIVE_ENGINE required')
class NativeCutEscrow(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0,str(ROOT/'tests'))
        import fabrication_room as api
        import live_session,room_store,world_room
        from fabrication_tests import settings
        self.api=api
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.live=live_session.Live();self.addCleanup(self.live.shutdown)
        self.room=world_room.Room('fabrication')
        self.app=SimpleNamespace(live=self.live,live_holder='world',room=self.room,engine_path=ENGINE,
            runs_path=root/'runs',store=room_store.RoomStore(root/'rooms'),workshop_db=root/'private.db')
        self.live.open(self.app,{'spec':self.room.spec})
        self.call('configure',settings=settings(stock_kg={},energy_j=0),request_id='escrow-config-0001')
        self.app.world_id='native-cut-escrow-fixture'
        person={'standing_m':[0.,0.,0.],'eyes_m':[0.,1.62,0.],'facing':[0.,0.,-1.]}
        self.room.player_records={who:{'id':who,'token':letter*64,'name':who,
            'inventory':{},'pose':deepcopy(person)} for who,letter in (('alice','a'),('bob','b'))}
        self.room.spec['terrain']={'surface':'columns','generate':{'kind':'flat','nx':24,'nz':24,
            'cell_m':.25,'soil_m':0.,'sand_m':0.,'discharge_m3_s':0.}}
        self.room.spec['bodies'].append({'name':'escrow fixture cutter','shape':'box','material':'iron',
            'size_mm':[800,80,80],'center_mm':[0,1000,0]})
        self.room.spec.setdefault('tool_points',[]).append({'body':'escrow fixture cutter',
            'tip_mm':[400,1000,0],'pointing':[0,-1,0],'grip_mm':[-300,1000,0],
            'width_mm':80,'thickness_mm':80,'angle_deg':30.,'length_mm':200})
        self.live.open(self.app,{'spec':self.room.spec})
        self.live.session._actor_local.actor='alice'
        self.live.session.send(op='wield',name='escrow fixture cutter',grip=[-.3,1.,0.])
        with library._connect(self.app) as db:
            matter._schema(db)
            db.execute('INSERT INTO market_wallet VALUES (?,?)',('alice',600000))
            db.commit()
        self.persist(self.app,'fixture baseline')

    def context(self):return {'scene':self.room.scene,'session':self.live.session.id}
    def call(self,op,**body):return self.api.request(self.app,op,{**self.context(),**body})
    def snapshot(self):
        import workshop_install
        return workshop_install._snapshot(self.live)
    def persist(self,_app,_message):
        from mcp import fabrication
        saved=self.snapshot();state=deepcopy(self.room.fabrication_record)
        fabrication.advance(state,saved['t_s'])
        self.api._persist(self.app,self.room,saved,state)
        return True

    def test_real_cut_save_recovery_private_escrow_debris_audit_and_whole_restart(self):
        from mcp import fabrication
        ident='native-cut-escrow-0001';source='bank:alice:'+ident;at=[0.,-.01,0.]
        baseline=deepcopy(self.app.store.load(self.room.scene).world_record)
        session=self.live.session
        with mock.patch.object(session,'send',wraps=session.send) as sent:
            with mock.patch.object(self.app.store,'save',side_effect=OSError('fixture durable save failure')):
                with self.assertRaisesRegex(OSError,'durable save failure'):
                    matter.cut(self.app,at,ident,'alice',self.persist)
            self.assertEqual(100000,matter.balance(self.app,'alice'))
            self.assertEqual(baseline,self.app.store.load(self.room.scene).world_record)
            pending=self.snapshot()
            native=pending['ground']['debris']['receipts'][source]['answer']
            self.assertTrue(native['supported'],native)
            self.assertAlmostEqual(468750.,native['consumed_work_j'])
            self.assertAlmostEqual(37.5,native['mass_kg'])
            self.assertIsNotNone(native['body_id'])
            with library._connect(self.app) as db:
                row=db.execute('SELECT * FROM ground_work_orders WHERE request_id=?',(ident,)).fetchone()
                self.assertEqual('reserved',row['status']);self.assertEqual(500000,row['reserved_j'])
                self.assertIsNone(row['consumed_j'])
            recovered=matter.recover_cut(self.app,ident,'alice',self.persist)
            self.assertEqual(468750,recovered['charged_j'])
            self.assertEqual(131250,matter.balance(self.app,'alice'))
            self.assertEqual(pending,self.snapshot())
            self.assertEqual(pending,self.app.store.load(self.room.scene).world_record)
            self.assertEqual(recovered,matter.cut(self.app,at,ident,'alice',self.persist))
            self.assertEqual(recovered,matter.recover_cut(self.app,ident,'alice',self.persist))
            for operation in (lambda:matter.cut(self.app,at,ident,'bob',self.persist),
                              lambda:matter.recover_cut(self.app,ident,'bob',self.persist),
                              lambda:matter.cut(self.app,[1.,-.01,0.],ident,'alice',self.persist)):
                with self.assertRaisesRegex(ValueError,'another player'):operation()
            empty=matter.cut(self.app,at,'native-empty-escrow-0001','bob',self.persist)
            self.assertEqual('no energy',empty['kind'])
            commands=[c.kwargs for c in sent.call_args_list if c.kwargs.get('op')=='strike-cell']
            self.assertEqual(1,len(commands));self.assertEqual(500000,commands[0]['work_j'])
            self.assertEqual(source,commands[0]['work_source'])
            ground=session.send(op='environment')['environment']['ground']
        audit=fabrication.ground_audit(self.room.fabrication_record,ground)
        rock=audit['substances']['rock']
        self.assertEqual('matched',audit['status']);self.assertEqual('balanced',rock['collection_status'])
        self.assertAlmostEqual(.015625,rock['physical_debris_m3'])
        self.assertAlmostEqual(.015625,rock['excavated_m3'])
        self.assertAlmostEqual(0.,rock['carried_m3']);self.assertAlmostEqual(0.,rock['exported_m3'])
        self.assertAlmostEqual(0.,rock['net_external_or_untracked_m3'])
        saved=self.app.store.load(self.room.scene)
        opened=self.live.open(self.app,{'spec':saved.spec,'snapshot':saved.world_record})
        self.assertEqual('whole',opened['restored']['tier'])
        self.app.room=self.room=saved;self.live.session._actor_local.actor='alice'
        self.assertEqual(pending,self.snapshot())
        with mock.patch.object(self.live.session,'send',wraps=self.live.session.send) as sent:
            self.assertEqual(recovered,matter.recover_cut(self.app,ident,'alice',self.persist))
            self.assertEqual(recovered,matter.cut(self.app,at,ident,'alice',self.persist))
            self.assertFalse(any(c.kwargs.get('op')=='strike-cell' for c in sent.call_args_list))
        self.assertEqual(131250,matter.balance(self.app,'alice'))
        with library._connect(self.app) as db:
            orders=db.execute('SELECT request_id,status,consumed_j FROM ground_work_orders').fetchall()
            self.assertEqual([(ident,'applied',468750)],[tuple(row) for row in orders])
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/'native-cut-escrow.json').write_text(json.dumps({'runner':str(ENGINE),
            'finite_external_bank_initial_j':600000,'reserved_j':500000,'consumed_native_j':468750.,
            'charged_j':468750,'unused_refund_j':31250,'final_bank_j':131250,
            'cut_commands':1,'save_failure_recovery_and_whole_restart':True,'native_receipt':native,
            'ground_audit':audit,'terrain_cell_m':.25,'source_cell_m':.05,'dt_s':1/240,
            'limits':'Explicit supplied iron cutter and finite economic external work reservoir; no solar generation, simulated wiring, calibrated natural stone fracture or fresh-player opening claim.'},indent=2),encoding='utf-8')


if __name__=='__main__':unittest.main()
