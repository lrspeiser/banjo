"""Guide latency/isolation, stale advice, private persistence and real HTTP."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'playground'),str(ROOT/'tests'),str(ROOT)]
import proactive_guidance as guide
import workshop_chat
import ai_player_tests as fixture

STEP={'chain_id':'first','goal':{'id':'tool','title':'Make a tool'},
    'observed_native_t_s':1,'next_action':{'verb':'build','label':'Make your pick',
        'destination':{'screen':'lab','recipe':'field-pick'},'status':'Available','blockers':[]},
    'limits':'Snapshot only; actions recheck supplies.'}


class Guide(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=SimpleNamespace(world_id='world',workshop_store=Path(self.temp.name),api_key='test')
        self.release=threading.Event();self.entered=threading.Event();self.finished=threading.Event()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.release.set)

    def slow(self,app,context):
        self.entered.set();self.release.wait(3)
        return {'text':'Use the Lab to make your pick.','model':'fixture','usage':{}}

    def wait_done(self,manager):
        for _ in range(100):
            with manager.lock:
                if not manager.running:return
            time.sleep(.01)
        self.fail('guide worker did not finish')

    def test_slow_provider_returns_immediately_deduplicates_and_invalidates_stale_advice(self):
        manager=guide.Manager(self.app,self.slow);self.addCleanup(manager.shutdown)
        began=time.monotonic();first=manager.handle('alice',{},STEP)
        self.assertLess(time.monotonic()-began,.25);self.assertEqual('pending',first['status'])
        self.assertTrue(self.entered.wait(1))
        self.assertEqual(first,manager.handle('alice',{},STEP))
        newer=deepcopy(STEP);newer['next_action']['verb']='collect';newer['next_action']['label']='Collect wood'
        update=manager.handle('alice',{'action':'status','key':first['key']},newer)
        self.assertNotEqual(first['key'],update['key']);self.assertEqual('fallback',update['status'])
        self.release.set();self.wait_done(manager)
        self.assertNotIn('alice',manager.jobs);self.assertEqual(1,len(manager.measurements))
        same=deepcopy(STEP);same['observed_native_t_s']=400
        self.assertEqual(guide.signature(guide.observation(STEP)),guide.signature(guide.observation(same)))

    def test_dismissal_and_quiet_survive_restart_without_affecting_peer_or_other_world(self):
        manager=guide.Manager(self.app)
        key=guide.signature(guide.observation(STEP))
        self.assertEqual('dismissed',manager.handle('alice',{'action':'dismiss','key':key},STEP)['status'])
        manager.shutdown();restarted=guide.Manager(self.app);self.addCleanup(restarted.shutdown)
        self.assertEqual('dismissed',restarted.handle('alice',{},STEP)['status'])
        self.app.api_key=''
        self.assertEqual('fallback',restarted.handle('bob',{},STEP)['status'])
        self.assertEqual('quiet',restarted.handle('bob',{'action':'settings','enabled':False},STEP)['status'])
        second=guide.Manager(self.app);self.addCleanup(second.shutdown)
        self.assertEqual('quiet',second.handle('bob',{},STEP)['status'])
        other=guide.Manager(SimpleNamespace(**{**vars(self.app),'world_id':'other'}));self.addCleanup(other.shutdown)
        self.assertEqual('fallback',other.handle('bob',{},STEP)['status'])

    def test_failures_remain_fallback_and_provider_concurrency_is_bounded(self):
        manager=guide.Manager(self.app,self.slow);self.addCleanup(manager.shutdown)
        self.assertEqual('pending',manager.handle('alice',{},STEP)['status'])
        self.assertEqual('pending',manager.handle('bob',{},STEP)['status'])
        self.assertEqual('busy',manager.handle('carol',{},STEP)['status'])
        self.release.set();self.wait_done(manager)
        self.assertEqual('ready',manager.handle('bob',{},STEP)['status'])
        def fail(*args):raise TimeoutError('private provider information')
        failed=guide.Manager(self.app,fail);self.addCleanup(failed.shutdown)
        failed.handle('alice',{},STEP);self.wait_done(failed)
        reply=failed.handle('alice',{},STEP)
        self.assertEqual('fallback',reply['status']);self.assertNotIn('private',json.dumps(reply))

    def test_model_has_bounded_read_only_schema_timeout_and_actual_observation(self):
        context=guide.observation(STEP)
        def respond(app,payload,**kwargs):
            self.assertEqual(6,kwargs['timeout_s']);self.assertEqual([],payload['tools'])
            self.assertFalse(payload['store']);self.assertEqual(160,payload['max_output_tokens'])
            self.assertEqual('none',payload['reasoning']['effort'])
            self.assertEqual(context,json.loads(payload['input'][-1]['content']))
            return {'status':'completed','output':[{'content':[{'type':'output_text',
                'text':json.dumps({'explanation':'Use the Lab to make your pick.'})}]}]}
        self.app.guidance_model='gpt-5.6-luna'
        with mock.patch.object(workshop_chat,'_call_model',side_effect=respond):
            self.assertEqual('Use the Lab to make your pick.',guide.explain(self.app,context)['text'])
        for forged in ({'owner':'alice'},{'state':STEP},{'action':'settings','enabled':1},{'event':'grant-skill'}):
            with self.assertRaises(ValueError):guide.validate(forged)

    def test_focused_foundation_excludes_unrelated_tool_goal_from_model_context(self):
        current=deepcopy(STEP)
        current['project']={'focused':True,'name':'Foundation pad','candidate':{'kind':'foundation-pad','parameters':{}}}
        current['next_action']={'verb':'review-project','label':'Prepare supplies · Foundation pad',
            'destination':{'screen':'lab'},'status':'Available'}
        sent=guide.observation(current)
        self.assertIsNone(sent['goal']);self.assertIsNone(sent['chain_id'])
        self.assertEqual('Foundation pad',sent['project']['name']);self.assertTrue(sent['project']['focused'])


@unittest.skipUnless(fixture.hub.RUNNER.is_file() and fixture.hub.ENGINE.is_file(),'native world engine not built')
class SharedHTTP(unittest.TestCase):
    setUp=fixture.AutonomousGuests.setUp
    tearDown=fixture.AutonomousGuests.tearDown
    start=fixture.AutonomousGuests.start
    stop=fixture.AutonomousGuests.stop
    get=fixture.AutonomousGuests.get
    post=fixture.AutonomousGuests.post
    join=fixture.AutonomousGuests.join
    setup_world=fixture.AutonomousGuests.setup_world

    def test_generated_foundation_keeps_exact_editable_source_on_both_maps_and_restart(self):
        from mcp import workshop_components
        reports=[]
        for surface in ('smooth','columns'):
            world,owner,app=self.setup_world(surface=surface)
            receipt=next(r for r in app.room.workshop_installs if r['recipe']['kind']=='foundation-pad')
            source=self.post('/api/world/workshop/what_made',{'body':receipt['root_body']},world)
            self.assertEqual(receipt['recipe'],source['recipe'])
            catalog=self.post('/api/workshop/recipes',{},world)
            pad=next(t for t in catalog['templates'] if t['kind']=='foundation-pad' and t['source']!='saved')
            concrete=next(r for r in pad['materials'] if r['material']=='concrete')
            self.assertAlmostEqual(24.,concrete['kg'],places=6)
            self.assertTrue(concrete['enough']);self.assertTrue(pad['readiness']['ready_as_drawn'])
            human=self.post('/api/world/guidance',{},world)
            observed=app.ai_players._observe({**owner,'ai':{'memory':{}}},'')
            self.assertEqual(human['build_readiness'],observed['construction_readiness'])
            design,_=workshop_components.design_from_spec(source['recipe'])
            self.assertEqual(5,len(design.parts))
            authored={p.name:p for p in design.parts}
            physical=next(b for b in app.room.spec['precise_rigid_bodies'] if b['name']==receipt['root_body'])
            for p in physical['parts']:
                # Compiler names source parts as root/component, retaining
                # their exact independently sized feet in the Lab recipe.
                name=p['name'].split('/')[-1]
                self.assertEqual(list(authored[name].size_m),p['dimensions_m'])
            reports.append((world,owner,source))
        self.stop();self.start()
        self.players={world:owner for world,owner,_ in reports}
        for world,owner,source in reports:
            self.post('/api/world/player/join',{'token':owner['token']},world)
            restored=self.post('/api/world/workshop/what_made',{'body':source['body']},world)
            self.assertEqual(source['recipe'],restored['recipe'])

    def test_slow_guide_allows_peer_native_steps_and_private_restart_preferences(self):
        world,owner,app=self.setup_world();peer=self.join(world,'Peer');app.api_key='mock-only'
        entered=threading.Event();release=threading.Event()
        def provider(app,context):
            entered.set();release.wait(5)
            return {'text':'Collect the nearby wood.','model':'fixture','usage':{}}
        manager=app.proactive_guide=guide.Manager(app,provider)
        try:
            pending=self.post('/api/world/assist',{},world)
            self.assertEqual('pending',pending['status']);self.assertTrue(entered.wait(1))
            gate=fixture.server.world_access.gate(app)
            with gate.condition:self.assertEqual(0,gate.readers)
            sid=app.live.session.id
            before=self.post('/api/live/act',{'session':sid,'op':'poses'},world,peer['token'])['t']
            stepped=self.post('/api/live/act',{'session':sid,'op':'step','dt':1/240,'n':12},world,peer['token'])
            self.assertGreater(stepped['t'],before)
            quiet=self.post('/api/world/assist',{'action':'settings','enabled':False},world)
            self.assertEqual('quiet',quiet['status'])
            app.api_key=''
            self.assertEqual('fallback',self.post('/api/world/assist',{},world,peer['token'])['status'])
            with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/assist',{'owner':peer['id']},world)
        finally:
            release.set()
            for _ in range(100):
                if not manager.running:break
                time.sleep(.01)
        self.stop();self.start();self.players={world:owner}
        self.post('/api/world/player/join',{'token':owner['token']},world)
        self.assertEqual('quiet',self.post('/api/world/assist',{},world)['status'])


if __name__=='__main__':unittest.main()
