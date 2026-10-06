"""Study requires the actual complete native fixed tool, including mixed matter."""
from copy import deepcopy
import base64
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'playground'),str(ROOT/'tools'),str(ROOT/'mcp')]
import fracture_lab, live_session, playable_recipes, player_learning, room_store, workshop_install
from mcp import progression, workshop_components

ENGINE=Path(os.environ.get('BANJO_LIVE_ENGINE',ROOT/'build/pickaxe-preview/Release/banjo_live_world_run.exe'))


@unittest.skipUnless(ENGINE.is_file(),'native live engine required')
class FixedToolStudy(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sessions=[]
        self.addCleanup(lambda:[session.close() for session in self.sessions])

    def fixture(self,material=None):
        source=playable_recipes.recipe('field-pick') if material is None else {
            'kind':'field-pick','design_id':'historical-comparison','parameters':{'material':material}}
        design,overrides=workshop_components.design_from_spec(source)
        plan=workshop_install.fixed_lattice_plan(design,overrides,root='pick',cell_m=.05,
            position_m=[0.,0.],floor_of=lambda _:1.)
        spec={'cell_m':.05,'bodies':plan['bodies'],'joints':plan['matter'].get('joints',[]),
              'tool_points':[plan['tool']['point']],'interactions':[plan['tool']['profile']]}
        session=live_session.Session(ENGINE,fracture_lab.validate(spec),Path(self.tmp.name)/'runs')
        self.sessions.append(session)
        session._actor_local.actor='alice'
        self.assertFalse(live_session.Live._hang(session,spec['joints']).get('joint_problems'))
        self.assertFalse(live_session.Live._point(session,spec['tool_points']).get('tool_point_problems'))
        session.send(op='wield',name='pick',grip=[v/1000 for v in plan['tool']['point']['grip_mm']])
        room=SimpleNamespace(scene='new-game',spec=spec,chat=[],player_records={
            'alice':{'id':'alice','name':'Alice','token':'a'*64,'inventory':{}},
            'bob':{'id':'bob','name':'Bob','token':'b'*64,'inventory':{}}},player_learning_durable_ids=set())
        live=SimpleNamespace(session=session,snapshot=lambda:(session.send(op='snapshot')['snapshot'],None))
        app=SimpleNamespace(world_id='a'*32,room=room,live=live)
        return app,plan,player_learning.registry_for_room(room)

    def test_actual_mixed_point_on_head_studies_complete_held_fixed_assembly(self):
        app,plan,registry=self.fixture()
        snapshot,_=app.live.snapshot()
        point=snapshot['tool_points'][0]
        self.assertNotEqual('pick',point['body'])
        self.assertEqual('pick',point['grip_body'])
        self.assertEqual(2,len(snapshot['bodies']))
        self.assertTrue(snapshot['joints'][0]['held'])
        self.assertTrue(player_learning.study(app,'alice','pick',registry))
        receipt=player_learning.pending_of(app)[0]
        self.assertIs(False,receipt['source']['construction']['one_piece'])
        self.assertEqual('field-pick@2',receipt['evidence']['design'])
        self.assertEqual('study-example',receipt['evidence']['test'])
        self.assertEqual(snapshot['tool_points'][0]['id'],receipt['source']['point_id'])
        self.assertTrue(player_learning.study(app,'alice','pick',registry))
        self.assertEqual(1,len(player_learning.pending_of(app)))
        app.live.session._actor_local.actor='bob'
        self.assertFalse(player_learning.study(app,'bob','pick',registry))
        self.assertEqual(1,len(player_learning.pending_of(app)))

    def test_missing_or_partial_matter_and_invalid_native_fixed_paths_never_award(self):
        app,_,registry=self.fixture()
        original,_=app.live.snapshot()
        variants=[]
        for group in ('pick','pick-g0'):
            bad=deepcopy(original);bad['bodies']=[b for b in bad['bodies'] if b['name']!=group]
            variants.append(('missing '+group,bad))
            bad=deepcopy(original);body=next(b for b in bad['bodies'] if b['name']==group)
            body['nodes_b64']=base64.b64encode(base64.b64decode(body['nodes_b64'])[:-4]).decode()
            if group==bad['tool_points'][0]['body']:
                bad['tool_points'][0]['frame_nodes_b64']=body['nodes_b64']
            variants.append(('partial '+group,bad))
            bad=deepcopy(original);next(b for b in bad['bodies'] if b['name']==group)['offsets_b64']=''
            variants.append(('missing offsets '+group,bad))
        for field,value in (('attached',False),('body_id',999999),('grip_body','absent'),
                            ('frame_nodes_b64',''),('frame_offsets_b64',''),('width_m',.06)):
            bad=deepcopy(original);bad['tool_points'][0][field]=value
            variants.append(('point '+field,bad))
        bad=deepcopy(original);bad['tool_points']=[];variants.append(('missing point',bad))
        for field,value in (('attached',False),('kind','hinge'),('comes_off_n',10.),
                            ('holds_tension_n',0.),('holds_shear_n',0.),('holds_tension_n',float('inf'))):
            bad=deepcopy(original);bad['joints'][0][field]=value
            variants.append(('joint '+field,bad))
        bad=deepcopy(original);bad['joints'][0].pop('held');variants.append(('missing native fixing',bad))
        bad=deepcopy(original);bad['joints']=[];variants.append(('missing fixing',bad))
        for reason,snapshot in variants:
            with self.subTest(reason=reason),mock.patch.object(app.live,'snapshot',return_value=(snapshot,None)):
                with self.assertRaises(ValueError):player_learning.study(app,'alice','pick',registry)
                self.assertEqual([],player_learning.pending_of(app))

    def test_study_failed_save_retry_whole_reopen_and_revision_binding(self):
        app,_,registry=self.fixture()
        self.assertTrue(player_learning.study(app,'alice','pick',registry))
        original=deepcopy(player_learning.pending_of(app))
        app.room.world_record=app.live.snapshot()[0]
        store=room_store.RoomStore(Path(self.tmp.name)/'room')
        journal=progression.Journal(Path(self.tmp.name)/'alice.json','alice')
        with mock.patch.object(room_store.os,'replace',side_effect=OSError('fixture atomic save refused')):
            with self.assertRaises(OSError):store.save(app.room)
        player_learning.saved(app,lambda *_:journal,registry)
        self.assertEqual({},journal.data['evidence'])
        self.assertEqual(original,player_learning.pending_of(app))
        self.assertTrue(player_learning.study(app,'alice','pick',registry))
        self.assertEqual(original,player_learning.pending_of(app))
        self.assertTrue(store.save(app.room))
        restored=store.load('new-game')
        self.assertEqual(original,restored.player_evidence_pending)
        self.assertEqual('field-pick@2',restored.player_evidence_pending[0]['evidence']['design'])
        session=live_session.Session(ENGINE,fracture_lab.validate(restored.spec),Path(self.tmp.name)/'reopen',
                                    snapshot=restored.world_record)
        self.sessions.append(session);session._actor_local.actor='alice'
        app.room=restored;app.live=SimpleNamespace(session=session,
            snapshot=lambda:(session.send(op='snapshot')['snapshot'],None))
        self.assertTrue(player_learning.study(app,'alice','pick',player_learning.registry_for_room(restored)))
        self.assertEqual(original,player_learning.pending_of(app))
        with mock.patch.object(journal,'add_evidence',side_effect=OSError('fixture journal save refused')):
            player_learning.saved(app,lambda *_:journal,registry)
        self.assertEqual(original,player_learning.pending_of(app))
        player_learning.saved(app,lambda *_:journal,registry)
        self.assertEqual([],player_learning.pending_of(app))
        self.assertEqual([original[0]['evidence']['id']],list(journal.data['evidence']))
        player_learning.saved(app,lambda *_:journal,registry)
        self.assertEqual(1,len(journal.data['evidence']))

    def test_historical_glass_oak_iron_whole_study_and_receipt_graph_remain(self):
        for material in ('glass','oak','iron'):
            with self.subTest(material=material):
                app,_,registry=self.fixture(material)
                # These are laboratory comparisons, not revision 2 game prototypes.
                app.room.scene='yard';registry=player_learning.registry_for_room(app.room)
                self.assertTrue(player_learning.study(app,'alice','pick',registry))
                receipt=player_learning.pending_of(app)[0]
                self.assertIs(True,receipt['source']['construction']['one_piece'])
                player_learning.validate_pending([receipt],app.live.snapshot()[0],app.room.player_records,registry)
                if material=='oak':
                    app.room.scene='new-game'
                    self.assertIsNotNone(player_learning.registry_for_room(app.room).designs.get('one-piece-wooden-pick'))


if __name__=='__main__':unittest.main(verbosity=2)
