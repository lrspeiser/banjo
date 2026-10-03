"""Shared processing decisions, real private ground, bounded writes and recovery.

The native extraction fixture uses authenticated terrain edits. Ordinary paid
tool gathering and the complete opening are covered separately, not inferred
from this fixture. No provider or legacy browser driver is invoked here.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest import mock
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'playground'),str(ROOT)]
import ai_player_tests as fixture
import private_ground_tests as ground_fixture
import ai_actions
import process_guidance
import starter_goals


class SharedProcessing(unittest.TestCase):
    def setUp(self):
        decider=mock.patch.dict(os.environ,{'BANJO_DECIDER':'reflex'})
        decider.start();self.addCleanup(decider.stop)
        fixture.AutonomousGuests.setUp(self)
    tearDown=fixture.AutonomousGuests.tearDown
    start=fixture.AutonomousGuests.start
    stop=fixture.AutonomousGuests.stop
    get=fixture.AutonomousGuests.get
    post=fixture.AutonomousGuests.post
    join=fixture.AutonomousGuests.join
    setup_world=fixture.AutonomousGuests.setup_world
    storage_fixture=ground_fixture.PrivateGround.storage_fixture
    raw_request=ground_fixture.PrivateGround.raw_request

    def test_depleted_input_uses_own_ground_or_reports_actual_machine_port_refusal(self):
        reports=[]
        for surface in ('smooth','columns'):
            print('\n  Starting shared processing on '+surface,flush=True)
            world,owner,peer,app,account,peer_account,legacy=self.storage_fixture(surface=surface)
            began=time.monotonic()
            program=next(p for p in app.live.session.state['machines']['programs']
                if app.brains.of(p['name']).routine and app.brains.of(p['name']).routine.recipe=='smelt copper')
            routine=app.brains.of(program['name']).routine;intake=app.brains.goods.by_name(routine.intake)
            # A depletion fixture removes all initial processor input, without
            # granting supplies, products, skills or chapter completion.
            for brain in app.brains.brains.values():
                if brain.routine and brain.routine.kind=='process':app.brains.goods.by_name(brain.routine.intake)['holds'].clear()
            self.assertGreater(account['sand_m3'],0)
            profile=app.room.player_records[owner['id']]
            profile['ai']={'controller':peer['id'],'mode':'reference','status':'paused','decisions':0,'history':[],'memory':{}}
            self.assertTrue(fixture.server.keep_world(app,'depleted processor/extracted ground fixture'))
            goals={'chain_id':'processing-capability-fixture','complete':False,'next_goal':'batch',
                'goals':[{'id':'batch','title':'Learn from an actual working machine','requirement':{'kind':'personal-batch'}}]}
            # Named worlds share a wall-time step budget across callers;
            # retain the ordinary controller cadence and native time gate.
            stop=threading.Event();lost={'store_ground','deliver'};phases=[];retained=[];port_refusal=None
            with mock.patch.object(starter_goals,'view',return_value=goals):
                for decision in range(35):
                    state=app.ai_players._observe(profile,'')
                    guidance=self.post('/api/world/guidance',{},world)
                    action=next(a for a in ai_actions.catalog(state,profile['ai']['memory'])
                        if a['id']==ai_actions.reference_pick(state,ai_actions.catalog(state,profile['ai']['memory'])))
                    if action['verb']!='continue-process':
                        self.assertEqual(guidance['next_action'],{k:v for k,v in action.items() if k!='id'})
                    self.assertEqual('melt glass',state['processing_readiness']['recipe'])
                    if action['verb']=='wait' and not state['processing_readiness']['ports_in_reach']:
                        port_refusal=deepcopy(action);break
                    manager=app.ai_players;post=manager._post
                    phases.append(action['verb'])
                    if decision%5==0:
                        print('  '+surface+' decision '+str(decision)+' '+action['verb']+
                            ' native_t='+str(state['native']['t']),flush=True)
                    def observed(p,path,body,cookie):
                        reply=post(p,path,body,cookie);op=path.rsplit('/',1)[-1]
                        if op in lost:
                            lost.remove(op);raise ValueError('Injected lost processing acknowledgement')
                        return reply
                    try:
                        with mock.patch.object(manager,'_post',side_effect=observed):
                            receipt=manager._execute(profile,stop,'',action,state,'ai-input-'+surface+'-'+str(decision))
                    except ValueError as exc:
                        self.assertEqual('Injected lost processing acknowledgement',str(exc))
                        pending=deepcopy(profile['ai']['memory']['process_request']);retained.append(pending)
                        self.stop();self.start();self.post('/api/world/open',{},world)
                        self.post('/api/world/ai',{'action':'list'},world)
                        app=self.app.hub.get(world);profile=app.room.player_records[owner['id']]
                        self.assertEqual(pending,profile['ai']['memory']['process_request'])
                        peer_retry=deepcopy(pending['body'])
                        if pending['path']=='/api/world/goods/deliver':peer_retry['session']=app.live.session.id
                        with self.assertRaises(urllib.error.HTTPError) as refused:
                            self.post(pending['path'],peer_retry,world,peer['token'])
                        self.assertIn('belongs to another player',refused.exception.read().decode())
                        continue
                    if 'melting-glass' in fixture.server.journal_of(app,owner['id']).knows():break
                else:self.fail('Shared processing did not produce a saved glass experiment: '+str(phases))
            if surface=='smooth':
                self.assertIsNone(port_refusal);self.assertFalse(lost);self.assertEqual(2,len(retained))
                self.assertTrue({'power-off','select-process','store-ground','process-input','continue-process','watch-batch','observe'}<=set(phases),phases)
            else:
                self.assertIsNotNone(port_refusal,'This generated column-map processor loses its physical intake/output reach')
                self.assertEqual('Blocked',port_refusal['status'])
            self.assertNotIn('process_request',profile['ai']['memory'])
            process=app.room.fabrication_record
            self.assertLessEqual(len(process.get('raw_lots',{})),1);self.assertLessEqual(len(process.get('raw_input_deliveries',{})),1)
            deliveries=list(process.get('raw_input_deliveries',{}).values())
            delivered_kg=sum(c['mass_kg'] for d in deliveries for c in d['packet']['contents'])
            self.assertTrue(all(d['owner']==owner['id'] for d in deliveries));self.assertLessEqual(delivered_kg,routine.batch_kg)
            evidence=[e for e in fixture.server.journal_of(app,owner['id']).data['evidence'].values() if e.get('source')=='watched']
            if surface=='smooth':
                self.assertEqual(1,len(process['raw_lots']));self.assertEqual(1,len(deliveries))
                self.assertTrue(any(e['passes'] and e['result']['made'].get('glass',0)>0 for e in evidence))
            else:
                self.assertEqual([],evidence)
                own=self.post('/api/workshop/inventory',{},world)
                conserved=own['ground_load']['sand_kg']+sum(r['mass_kg'] for r in own['stored_ground'] if r['substance']=='sand')
                conserved+=app.brains.goods.by_name(routine.intake)['holds'].get('sand',0)
                self.assertAlmostEqual(account['sand_kg'],conserved,places=5)
            self.assertEqual(set(),fixture.server.journal_of(app,peer['id']).knows())
            other=self.post('/api/workshop/inventory',{},world,peer['token'])
            self.assertAlmostEqual(peer_account['total_kg'],other['ground_load']['total_kg'],places=5)
            self.assertEqual([],other['stored_ground'])
            self.assertTrue(fixture.server.keep_world(app,'saved AI processing result'))
            before=deepcopy(process);runtime=deepcopy(app.brains.runtime());journal=deepcopy(fixture.server.journal_of(app,owner['id']).copy())
            self.stop();self.start();self.post('/api/world/open',{},world);app=self.app.hub.get(world)
            self.assertEqual(before,app.room.fabrication_record);self.assertEqual(runtime,app.brains.runtime())
            self.assertEqual(journal,fixture.server.journal_of(app,owner['id']).copy())
            reports.append({'surface':surface,'wall_s':round(time.monotonic()-began,3),'phases':phases,
                'source_sand_m3':account['sand_m3'],'delivered_sand_kg':delivered_kg,
                'evidence':evidence,'port_refusal':port_refusal,'restarted_exact':True,
                'source_fixture':'authenticated bounded native terrain edit'})
        folder=ROOT/'build/resource-flow';folder.mkdir(parents=True,exist_ok=True)
        (folder/'ai-processing.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
        print('\n  AI processing: '+json.dumps([{k:r[k] for k in ('surface','wall_s','phases','delivered_sand_kg')} for r in reports]))

    def test_retained_processing_write_preempts_a_new_transfer_even_when_goal_changes(self):
        state={'goals':{'goals':[],'next_goal':None,'complete':True}}
        memory={'process_request':{'path':'/api/world/goods/deliver','body':{'request_id':'retained'}}}
        actions=ai_actions.catalog(state,memory)
        self.assertEqual(['continue-process'],[a['verb'] for a in actions])
        self.assertEqual(actions[0]['id'],ai_actions.reference_pick(state,actions))

    def test_fractional_raw_input_uses_bounded_micrograms_without_overdrawing(self):
        mass=.30848000000000003
        row={'machine':'furnace','body':'furnace-body','at_m':[0,0,0],
            'input_at_m':[0,0,0],'recipe':'melt glass','current_recipe':'melt glass',
            'input':'hopper','pending_inputs':[],'available_batch_kg':mass,
            'inputs':[{'substance':'sand','hopper_kg':0,'stored_personal_kg':mass,'mass_kg':0}],
            'stored':[{'substance':'sand','lot_id':'own-lot','mass_kg':mass}],
            'batch_kg':5,'raw_revision':7}
        action=process_guidance._next(row)
        self.assertEqual('deliver-input',action['operation'])
        self.assertEqual(.30848,action['transfer']['mass_kg'])
        self.assertLessEqual(action['transfer']['mass_kg'],mass)
        self.assertEqual('own-lot',action['transfer']['lot_id'])
        row['batch_kg']=100
        row['stored'][0]['mass_kg']=40
        row['inputs'][0]['stored_personal_kg']=40
        self.assertEqual(25,process_guidance._next(row)['transfer']['mass_kg'])


if __name__=='__main__':unittest.main()
