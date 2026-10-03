"""Authenticated native ground accounts, independent budgets and durable restore.

API excavation here is the bounded terrain-edit lane. Actual tool work and
owner attribution during shared stepping are tested by banjo_ground_work_tests.
"""
from copy import deepcopy
import base64
import json
from pathlib import Path
import time
import unittest
from unittest import mock
import urllib.error
import world_goods_tests as flow

ROOT=Path(__file__).resolve().parents[1]


class PrivateGround(unittest.TestCase):
    setUp=flow.GoodsJourney.setUp
    tearDown=flow.GoodsJourney.tearDown
    start=flow.GoodsJourney.start
    stop=flow.GoodsJourney.stop
    get=flow.GoodsJourney.get
    post=flow.GoodsJourney.post
    join=flow.GoodsJourney.join
    setup_world=flow.GoodsJourney.setup_world

    def storage_fixture(self):
        with mock.patch.object(flow.server.secrets,'randbelow',side_effect=[0,851269740]):
            world,alice,app=self.setup_world()
        bob=self.join(world,'Other gatherer')
        def dig(x,z,player=None):
            return self.post('/api/live/act',{'session':app.live.session.id,'op':'dig',
                'from':[x,z],'to':[x,z],'width_m':.4,'depth_m':.1},world,player)['carried']
        a=dig(-1,0);b=dig(2,-1,bob['token'])
        legacy=app.live.act({'session':app.live.session.id,'op':'dig',
            'from':[3,1],'to':[3,1],'width_m':.4,'depth_m':.1})['carried']
        self.assertGreater(a['total_kg'],0);self.assertGreater(b['total_kg'],0);self.assertGreater(legacy['total_kg'],0)
        self.assertTrue(flow.server.keep_world(app,'save raw storage source fixture'))
        return world,alice,bob,app,a,b,legacy

    def raw_request(self,app,ident,account,**extra):
        return {'scene':app.room.scene,'session':app.live.session.id,'request_id':ident,
            'revision':app.room.fabrication_record['revision'],
            **{s+'_m3':account.get(s+'_m3',0) for s in ('sand','soil','rock')},**extra}

    def test_authenticated_storage_recovery_ownership_failures_and_full_restart(self):
        world,alice,bob,app,a,b,legacy=self.storage_fixture()
        def inv(token=None):return self.post('/api/workshop/inventory',{},world,token)
        def call(op,request,token=None):
            try:return self.post('/api/world/fabrication/'+op,request,world,token)
            except urllib.error.HTTPError as exc:
                exc.add_note(exc.read().decode());raise
        request=self.raw_request(app,'owned-raw-store-0001',a)
        before=deepcopy(app.room.world_record['ground'])
        with mock.patch.object(app.store,'save',side_effect=OSError('disk full')):
            with self.assertRaises(urllib.error.HTTPError) as refused:call('store_ground',request)
            self.assertEqual(503,refused.exception.code)
        self.assertEqual(before,flow.server.workshop_install._snapshot(app.live)['ground'])
        self.assertEqual([],inv()['stored_ground'])
        result=call('store_ground',request)
        self.assertEqual(alice['id'],result['state']['raw_lot_ownership'][request['request_id']]['owner'])
        self.assertTrue(call('store_ground',request)['replayed'])
        self.assertEqual(0,inv()['ground_load']['total_kg'])
        self.assertAlmostEqual(b['total_kg'],inv(bob['token'])['ground_load']['total_kg'],places=5)

        self.assertAlmostEqual(legacy['total_kg'],inv()['unassigned_ground']['total_kg'],places=5)
        self.assertEqual([],inv(bob['token'])['stored_ground'])
        with self.assertRaises(urllib.error.HTTPError):call('store_ground',request,bob['token'])
        returned=self.raw_request(app,'owned-raw-return-0001',a,lot_id=request['request_id'])
        with self.assertRaises(urllib.error.HTTPError):call('retrieve_ground',returned,bob['token'])
        with mock.patch.object(app.store,'save',side_effect=OSError('disk full')):
            with self.assertRaises(urllib.error.HTTPError):call('retrieve_ground',returned)
        self.assertEqual(0,inv()['ground_load']['total_kg'])
        call('retrieve_ground',returned)
        self.assertTrue(call('retrieve_ground',returned)['replayed'])
        with self.assertRaises(urllib.error.HTTPError):call('retrieve_ground',returned,bob['token'])
        self.assertAlmostEqual(a['total_kg'],inv()['ground_load']['total_kg'],places=5)
        # Recovery names its unknown source explicitly and never changes a
        # private native account. A lost durable-save acknowledgement restarts
        # into the one already received lot, then replays without duplication.
        recovery=self.raw_request(app,'legacy-raw-recovery-0001',legacy)
        save=app.store.save
        def lost_ack(record):
            self.assertTrue(save(record));raise OSError('save acknowledgement lost')
        with mock.patch.object(app.store,'save',side_effect=lost_ack):
            with self.assertRaises(urllib.error.HTTPError):call('recover_ground',recovery)
        self.stop();self.start()
        for guest in (alice,bob):self.post('/api/world/player/join',{'token':guest['token']},world)
        self.post('/api/world/open',{},world);app=self.app.hub.get(world)
        self.assertTrue(call('recover_ground',recovery)['replayed'])
        with self.assertRaises(urllib.error.HTTPError):call('recover_ground',recovery,bob['token'])
        own=inv();peer=inv(bob['token'])
        self.assertEqual(0,own['unassigned_ground']['total_kg'])
        self.assertAlmostEqual(a['total_kg'],own['ground_load']['total_kg'],places=5)
        self.assertAlmostEqual(b['total_kg'],peer['ground_load']['total_kg'],places=5)
        self.assertEqual([],peer['stored_ground'])
        self.assertAlmostEqual(legacy['total_kg'],sum(v['mass_kg'] for v in own['stored_ground']),places=5)
        self.assertTrue(all(v['recovered'] for v in own['stored_ground']))
        provenance=app.room.fabrication_record['raw_lot_ownership'][recovery['request_id']]
        self.assertEqual({'owner':alice['id'],'source_actor':''},provenance)
        # Capacity refusal cannot spend the lot; use an actual fresh private
        # dig to fill the bag, not a fabricated balance or weakened limit.
        self.post('/api/live/act',{'session':app.live.session.id,'op':'dig',
            'from':[-2,-1],'to':[-2,-1],'width_m':.8,'depth_m':.4},world)
        full=self.raw_request(app,'recovered-return-full-0001',legacy,lot_id=recovery['request_id'])
        with self.assertRaises(urllib.error.HTTPError):call('retrieve_ground',full)
        self.assertAlmostEqual(legacy['total_kg'],sum(v['mass_kg'] for v in inv()['stored_ground']),places=5)
        load=inv()['ground_load']
        store_again=self.raw_request(app,'owned-raw-store-0002',load)
        call('store_ground',store_again)
        full['revision']=app.room.fabrication_record['revision'];full['session']=app.live.session.id
        call('retrieve_ground',full)
        final=inv()
        self.assertAlmostEqual(legacy['total_kg'],final['ground_load']['total_kg'],places=5)
        self.assertAlmostEqual(load['total_kg'],sum(v['mass_kg'] for v in final['stored_ground']),places=5)
        self.assertEqual('',getattr(app.live.session._actor_local,'actor',''))
        self.assertTrue(flow.server.keep_world(app,'save completed raw storage journey'))
        self.stop();self.start()
        self.post('/api/world/open',{},world);app=self.app.hub.get(world)
        self.assertTrue(call('retrieve_ground',full)['replayed'])
        self.assertEqual(final['stored_ground'],inv()['stored_ground'])
        self.assertAlmostEqual(legacy['total_kg'],inv()['ground_load']['total_kg'],places=5)
        self.assertAlmostEqual(b['total_kg'],inv(bob['token'])['ground_load']['total_kg'],places=5)

    def glass_input_fixture(self):
        world,alice,bob,app,a,b,legacy=self.storage_fixture()
        request=self.raw_request(app,'glass-input-source-0001',a)
        self.post('/api/world/fabrication/store_ground',request,world)
        sid=app.live.session.id
        program=next(p for p in app.live.session.state['machines']['programs']
            if app.brains.of(p['name']).routine and app.brains.of(p['name']).routine.recipe=='smelt copper')
        for p in app.live.session.state['machines']['programs']:
            self.post('/api/world/machine',{'session':sid,'program':p['id'],'power':False,
                'sender':'glass-input-fixture','seq':1},world)
        routine=app.brains.of(program['name']).routine
        intake=app.brains.goods.by_name(routine.intake)
        floor=app.live.act({'session':sid,'op':'survey','at':intake['at_m']})['survey']['ground_m']
        person={'eyes_m':[intake['at_m'][0],floor+1.62,intake['at_m'][1]],'facing':[0,0,-1]}
        selection={'session':sid,'program':program['id'],'action':'select','recipe':'melt glass',
            'expected_recipe':routine.recipe,'person':person}
        return world,alice,bob,app,request,program,intake,person,selection

    def test_stored_sand_glass_input_native_energy_private_output_and_restart(self):
        import machine_witness
        world,alice,bob,app,stored,program,intake,person,selection=self.glass_input_fixture()
        def call(path,body,token=None):
            try:return self.post(path,body,world,token)
            except urllib.error.HTTPError as exc:
                exc.add_note(exc.read().decode());raise
        def delivery(ident,mass=5):return {'session':app.live.session.id,'pile':intake['name'],
            'substance':'sand','mass_kg':mass,'request_id':ident,'lot_id':stored['request_id'],
            'revision':app.room.fabrication_record['revision'],'person':person}
        original=app.brains.of(program['name']).routine.recipe
        with mock.patch.object(app.store,'save',side_effect=OSError('disk full')):
            with self.assertRaises(urllib.error.HTTPError):call('/api/world/process',selection)
        self.assertEqual(original,app.brains.of(program['name']).routine.recipe)
        selected=call('/api/world/process',selection)
        self.assertEqual('melt glass',selected['recipe'])
        self.assertTrue(call('/api/world/process',selection)['repeated'])
        menu=call('/api/world/goods/deliver',{'session':app.live.session.id,'action':'view','pile':intake['name']})
        sand=next(r for r in menu['stored'] if r['substance']=='sand')
        self.assertGreaterEqual(sand['mass_kg'],7)
        initial=sand['mass_kg'];before=deepcopy(intake['holds'])
        request=delivery('sand-delivery-paid-0001')
        with self.assertRaises(urllib.error.HTTPError):call('/api/world/goods/deliver',request,bob['token'])
        with mock.patch.object(app.store,'save',side_effect=OSError('disk full')):
            with self.assertRaises(urllib.error.HTTPError) as failed:call('/api/world/goods/deliver',request)
            self.assertEqual(503,failed.exception.code)
        self.assertEqual(before,intake['holds'])
        self.assertNotIn(request['request_id'],app.room.fabrication_record.get('raw_input_deliveries',{}))
        call('/api/world/goods/deliver',request)
        self.assertTrue(call('/api/world/goods/deliver',request)['repeated'])
        self.assertEqual(5,intake['holds']['sand'])
        with self.assertRaises(urllib.error.HTTPError):call('/api/world/goods/deliver',request,bob['token'])
        # Lost acknowledgement preserves the receiving world through a normal
        # shutdown; its retry cannot debit another 2 kg from the raw lot.
        extra=delivery('sand-delivery-lost-ack-0001',2)
        save=app.store.save
        def lost(record):self.assertTrue(save(record));raise OSError('acknowledgement lost')
        with mock.patch.object(app.store,'save',side_effect=lost):
            with self.assertRaises(urllib.error.HTTPError):call('/api/world/goods/deliver',extra)
        self.assertEqual(7,intake['holds']['sand'])
        self.stop();self.start();call('/api/world/open',{})
        app=self.app.hub.get(world);intake=app.brains.goods.by_name(intake['name'])
        self.assertEqual('melt glass',app.brains.of(program['name']).routine.recipe)
        source=next(m for m in machine_witness.machines(app) if m['machine']==program['name'])
        self.assertEqual('melt glass',source['recipe'])
        extra['session']=app.live.session.id
        self.assertTrue(call('/api/world/goods/deliver',extra)['repeated'])
        self.assertEqual(7,intake['holds']['sand'])
        from mcp import fabrication
        remaining=next(v for v in fabrication.raw_inventory(app.room.fabrication_record)[stored['request_id']] if v['substance']=='sand')
        self.assertAlmostEqual(initial-7,remaining['mass_kg'],places=6)
        output=app.brains.goods.by_name(app.brains.of(program['name']).routine.output)
        meters=deepcopy(app.live.session.state['machines']['stores'])
        call('/api/world/machine',{'session':app.live.session.id,'program':program['id'],'power':True,
            'sender':'glass-input-fixture','seq':2})
        at=source['at_m'];view={'eyes_m':[at[0],at[1]+1.2,at[2]+2],
            'facing':[0,0,-1],'look_direction':[0,-1.2,-2]}
        watched=call('/api/world/watch-machine',{'session':app.live.session.id,
            'machine':source['machine'],'person':view})
        self.assertEqual('melt glass',watched['recipe'])
        for tick in range(600):
            if tick%30==0:
                call('/api/live/act',{'session':app.live.session.id,'op':'step','dt':1/240,'n':1,'person':view})
            app.clock._tick(.2)
            output=app.brains.goods.by_name(output['name'])
            if output.get('holds',{}).get('glass',0)>=7*.85-1e-6:break
        self.assertAlmostEqual(5.95,output.get('holds',{}).get('glass',0),places=5)
        journal=flow.server.journal_of(app,alice['id'])
        evidence=[v for v in journal.data['evidence'].values() if v.get('source')=='watched']
        self.assertEqual(1,len(evidence))
        self.assertEqual('glass-furnace',evidence[0]['design'].split('@')[0])
        self.assertGreater(evidence[0]['result']['made_kg'],0)
        self.assertGreater(evidence[0]['result']['drawn_j'],0)
        self.assertNotIn('smelting-copper',journal.knows())
        self.assertNotIn('melting-glass',journal.knows(),'Existing prerequisite still requires copper; observation is distinct from mastery')
        self.assertEqual({},flow.server.journal_of(app,bob['id']).data['evidence'])
        self.assertNotIn('sand',intake['holds'])
        self.assertEqual(before,intake['holds'],'Unselected copper remains in the same hopper')
        app.live.act({'session':app.live.session.id,'op':'poses'})
        drawn=sum(s['given_j'] for s in app.live.session.state['machines']['stores'])-sum(s['given_j'] for s in meters)
        self.assertGreater(drawn,7*800,'The native battery pays for heating as well as process work')
        call('/api/world/machine',{'session':app.live.session.id,'program':program['id'],'power':False,
            'sender':'glass-input-fixture','seq':3})
        at=output['at_m'];floor=app.live.act({'session':app.live.session.id,'op':'survey','at':at})['survey']['ground_m']
        pickup={'session':app.live.session.id,'pile':output['name'],'request_id':'glass-private-output-0001',
            'person':{'eyes_m':[at[0],floor+1.62,at[1]],'facing':[0,0,-1]}}
        call('/api/world/goods/collect',pickup)
        self.assertTrue(call('/api/world/goods/collect',pickup)['repeated'])
        def glass(token=None):
            inventory=call('/api/workshop/inventory',{},token)
            return next(r['personal_kg'] for r in inventory['materials'] if r['material']=='glass')
        self.assertAlmostEqual(5.95,glass(),places=5);self.assertEqual(0,glass(bob['token']))
        self.stop();self.start();call('/api/world/open',{})
        app=self.app.hub.get(world)
        extra['session']=pickup['session']=app.live.session.id
        self.assertTrue(call('/api/world/goods/deliver',extra)['repeated'])
        self.assertTrue(call('/api/world/goods/collect',pickup)['repeated'])
        self.assertAlmostEqual(5.95,glass(),places=5);self.assertEqual(0,glass(bob['token']))
        (ROOT/'build/resource-flow/stored-sand-glass.json').write_text(json.dumps({
            'stored_sand_kg':initial,'delivered_sand_kg':7,'remaining_sand_kg':initial-7,
            'glass_kg':5.95,'declared_process_j':5600,'native_store_draw_j':drawn,
            'restart':'whole','build_use':'not yet qualified'},indent=2))

        recovered=flow.server.journal_of(app,alice['id'])
        self.assertEqual({v['id'] for v in evidence},set(recovered.data['evidence']))
        self.assertEqual({},flow.server.journal_of(app,bob['id']).data['evidence'])
        self.assertEqual('melt glass',next(m for m in machine_witness.machines(app)
            if m['machine']==program['name'])['recipe'])

    def test_processing_guidance_selects_owned_sand_and_shares_current_input_facts(self):
        import starter_goals
        world,alice,bob,app,stored,program,intake,person,selection=self.glass_input_fixture()
        # Remove the initially supplied copper to exercise the actual empty-
        # intake boundary. No material or completion evidence is granted.
        intake['holds'].clear()
        empty=self.join(world,'Empty observer')
        goals={'chain_id':'observed-process-guidance','complete':False,'next_goal':'batch',
            'goals':[{'id':'batch','title':'Learn from a working machine',
                      'requirement':{'kind':'personal-batch'}}]}
        with mock.patch.object(starter_goals,'view',return_value=goals):
            own=self.post('/api/world/guidance',{},world)
            other=self.post('/api/world/guidance',{},world,empty['token'])
            self.assertEqual('melt glass',own['processing_readiness']['recipe'])
            self.assertGreater(own['processing_readiness']['available_batch_kg'],0)
            # Analytical preview boundary: a sub-batch input is completely
            # consumed by convert(copy), but its source facts must stay intact.
            # This mock supplies observations only; it grants no game material.
            import world_goods
            original=world_goods.input_readiness
            before=deepcopy(app.room.fabrication_record)
            def partial(*args,**kwargs):
                facts=original(*args,**kwargs)
                for line in facts['inputs']:
                    line.update(hopper_kg=0,mass_kg=0,carried_kg=0,
                        stored_personal_kg=.5 if line['substance']=='sand' else 0)
                return facts
            with mock.patch.object(world_goods,'input_readiness',side_effect=partial):
                small=self.post('/api/world/guidance',{},world)
            self.assertEqual(.5,small['processing_readiness']['available_batch_kg'])
            self.assertEqual([],small['processing_readiness']['missing'])
            self.assertEqual(before,app.room.fabrication_record)
            self.assertEqual('select-process',own['next_action']['verb'])
            self.assertEqual('Choose melt glass',own['next_action']['label'])
            self.assertEqual(0,other['processing_readiness']['available_batch_kg'])
            self.assertFalse(any(r['stored_personal_kg'] for r in other['processing_readiness']['inputs']))
            self.post('/api/world/process',selection,world)
            current=self.post('/api/world/guidance',{},world)
            self.assertEqual('Load sand into '+intake['name'],current['next_action']['label'])
            delivered=self.post('/api/world/goods/deliver',{'session':app.live.session.id,
                'action':'view','pile':intake['name']},world)
            menu=self.post('/api/world/process',{'session':app.live.session.id,
                'program':program['id'],'action':'view'},world)
            self.assertEqual(delivered['inputs'],current['processing_readiness']['inputs'])
            self.assertEqual({k:v for k,v in delivered.items() if k!='persistence'},menu['input_readiness'])
            market=self.post('/api/workshop/market',{},world)
            self.assertEqual(current['next_action'],market['guidance']['player']['next_action'])
            self.assertEqual(current['processing_readiness'],market['guidance']['player']['processing_readiness'])
            self.assertEqual({},flow.server.journal_of(app,alice['id']).data['evidence'])

    def test_browser_selects_glass_and_retries_stored_input_after_reload(self):
        if not flow.qa_browser.CHROME.is_file():self.skipTest('Chrome not installed')
        world,alice,bob,app,stored,program,intake,person,selection=self.glass_input_fixture()
        chrome=flow.qa_browser.Chrome(1280,900);self.addCleanup(chrome.close)
        p=chrome.page;p.send('Page.enable');p.send('Runtime.enable')
        p.send('Page.addScriptToEvaluateOnNewDocument',{'source':
            'localStorage.setItem('+json.dumps('banjo.player.'+world)+','+json.dumps(alice['token'])+');'})
        def wait(expr):
            deadline=time.monotonic()+35
            while time.monotonic()<deadline:
                if p.evaluate('Boolean('+expr+')'):return
                time.sleep(.1)
            self.fail(expr+'; '+str(p.evaluate('document.querySelector("#picked")?.textContent')))
        def click(selector):
            spot=p.evaluate('(()=>{const b=document.querySelector('+json.dumps(selector)+');b.scrollIntoView({block:"center"});const r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()')
            for kind in ('mousePressed','mouseReleased'):
                p.send('Input.dispatchMouseEvent',{'type':kind,'button':'left','clickCount':1,**spot})
        def select_machine():
            wait('window.banjoRoom?.ready()')
            p.evaluate('banjoRoom.standAt('+','.join(map(str,person['eyes_m']))+');banjoRoom.pick('+json.dumps(program['body'])+');')
            wait('document.querySelector("[data-process-recipe] button")')
        p.send('Page.navigate',{'url':self.base+f'/world?world={world}&hold=1'})
        select_machine();click('[data-process-recipe] button')
        wait('document.querySelector("[data-process-recipe] select")')
        p.evaluate('(()=>{const s=document.querySelector("[data-process-recipe] select");s.value="melt glass";s.dispatchEvent(new Event("change"));})()')
        click('[data-select-process-recipe]')
        wait('document.querySelector("#details-last-text")?.textContent.includes("Recipe →")')
        self.assertEqual('melt glass',app.brains.of(program['name']).routine.recipe)
        click('[data-input-delivery] button')
        wait('document.querySelector("[data-deliver-raw-lot]")')
        before=deepcopy(intake['holds'])
        with mock.patch.object(app.store,'save',side_effect=OSError('disk full')):
            click('[data-deliver-raw-lot]')
            wait('document.querySelector("[data-retry-raw-input]")')
        self.assertEqual(before,intake['holds'])
        p.send('Page.reload',{});select_machine();click('[data-input-delivery] button')
        wait('document.querySelector("[data-retry-raw-input]")')
        click('[data-retry-raw-input]')
        wait('!document.querySelector("[data-retry-raw-input]") && document.querySelector("#details-last-text")?.textContent.includes("→ Input")')
        self.assertEqual(5,app.brains.goods.by_name(intake['name'])['holds']['sand'])
        self.assertEqual([],[e for e in p.events if e.get('method')=='Runtime.exceptionThrown'])
        (ROOT/'build/resource-flow/stored-sand-input.png').write_bytes(
            base64.b64decode(p.send('Page.captureScreenshot',{'format':'png'})['data']))
        p.send('Page.addScriptToEvaluateOnNewDocument',{'source':
            'localStorage.setItem('+json.dumps('banjo.player.'+world)+','+json.dumps(bob['token'])+');'})
        # Finish the loaded batch before looking at the empty input as a
        # peer. Collection remains separately covered by the native journey.
        self.post('/api/world/machine',{'session':app.live.session.id,'program':program['id'],
            'power':True,'sender':'browser-guidance','seq':1},world)
        output=app.brains.goods.by_name(app.brains.of(program['name']).routine.output)
        for _ in range(600):
            app.clock._tick(.2)
            if output.get('holds',{}).get('glass',0)>=4.25-1e-6:break
        self.assertAlmostEqual(4.25,output.get('holds',{}).get('glass',0),places=5)
        p.send('Page.reload',{});select_machine();click('[data-input-delivery] button')
        wait('document.querySelector("[data-input-guidance=sand]")')
        self.assertIn('Inventory · Store → Load here',p.evaluate('document.querySelector("[data-input-guidance=sand]").textContent'))
        self.assertFalse(p.evaluate('Boolean(document.querySelector("[data-deliver-raw-lot]"))'))
        (ROOT/'build/resource-flow/empty-sand-input.png').write_bytes(
            base64.b64decode(p.send('Page.captureScreenshot',{'format':'png'})['data']))

    def test_empty_input_exhausted_source_and_current_recipe_guidance(self):
        world,alice,bob,app,stored,program,intake,person,selection=self.glass_input_fixture()
        def view(token=None):return self.post('/api/world/goods/deliver',
            {'session':app.live.session.id,'action':'view','pile':intake['name']},world,token)
        self.assertEqual('processing',view(bob['token'])['inputs'][0]['next'])
        self.post('/api/world/goods/collect',{'session':app.live.session.id,'pile':intake['name'],
            'request_id':'guidance-input-withdraw','person':person},world)
        self.assertEqual('load_inventory',view()['inputs'][0]['next'])
        self.assertEqual('mine_source',view(bob['token'])['inputs'][0]['next'])
        # Explicit exhausted-ledger fixture; no additional ore or yield is granted.
        for d in app.brains.goods.deposits:
            if d['substance']=='copper ore':d['taken_kg']=d['reserve_kg']
        exhausted=view(bob['token'])['inputs'][0]
        self.assertEqual('source_exhausted',exhausted['next'])
        self.assertTrue(all(d['left_kg']==0 for d in exhausted['sources']))
        self.post('/api/world/process',selection,world)
        self.assertEqual('load_stored',view()['inputs'][0]['next'])
        row=view(bob['token'])['inputs'][0]
        self.assertEqual('store_ground',row['next']);self.assertGreater(row['carried_kg'],0)
        # An authenticated new gatherer has no carried or stored material.
        newcomer=self.join(world,'New gatherer')
        self.assertEqual('gather_ground',view(newcomer['token'])['inputs'][0]['next'])
        catalog=self.post('/api/workshop/recipes',{},world)
        glass=next(r for r in catalog['room_recipes'] if r['name']=='melt glass')
        copper=next(r for r in catalog['room_recipes'] if r['name']=='smelt copper')
        self.assertIn(program['name'],glass['worked_by']);self.assertNotIn(program['name'],copper['worked_by'])
        self.assertEqual('smelt copper',next(p for p in app.room.spec['machines']['programs']
            if p['name']==program['name'])['routine']['recipe'])
        from copy import deepcopy
        import machine_routine, world_goods
        record=deepcopy(app.brains.runtime())
        original=machine_routine.Routine(program['name'],machine_routine.declared_for(app.room.spec,program['name'])).record()
        original.pop('process_recipe')
        record[program['name']]=original
        machine_routine.validate_runtime(app.room.spec,record) # Old v1 retains the original recipe.
        record[program['name']]['process_recipe']='invented free output'
        with self.assertRaises(ValueError):machine_routine.validate_runtime(app.room.spec,record)
        # A saved source debit cannot survive without its paired receiving claim.
        state=deepcopy(app.room.fabrication_record)
        state['raw_input_deliveries']={'orphan':{}}
        with self.assertRaises(ValueError):world_goods.validate_raw_deliveries(state,app.room.goods_deliveries)
    def test_browser_store_retrieve_recovery_and_pending_retry(self):
        if not flow.qa_browser.CHROME.is_file():self.skipTest('Chrome not installed')
        world,alice,bob,app,a,b,legacy=self.storage_fixture()
        chrome=flow.qa_browser.Chrome(1280,900);self.addCleanup(chrome.close)
        p=chrome.page;p.send('Page.enable');p.send('Runtime.enable')
        p.send('Page.addScriptToEvaluateOnNewDocument',{'source':
            'localStorage.setItem('+json.dumps('banjo.player.'+world)+','+json.dumps(alice['token'])+');'})
        def wait(expr):
            deadline=time.monotonic()+35
            while time.monotonic()<deadline:
                if p.evaluate('Boolean('+expr+')'):return
                time.sleep(.1)
            self.fail(expr+'; '+str(p.evaluate('document.querySelector("#ws-notice")?.textContent')))
        def click(selector):
            spot=p.evaluate('(()=>{const b=document.querySelector('+json.dumps(selector)+');b.scrollIntoView({block:"center"});const r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()')
            for kind in ('mousePressed','mouseReleased'):
                p.send('Input.dispatchMouseEvent',{'type':kind,'button':'left','clickCount':1,**spot})
        p.send('Page.navigate',{'url':self.base+f'/world?world={world}&workshop=1&tab=inventory&hold=1'})
        wait('document.querySelector("[data-ground-action=store_ground]")')
        material=p.evaluate('document.querySelector("[data-ground-action=store_ground]").closest("article").dataset.groundLoad')
        source_kg=a[material+'_kg']
        self.assertTrue(p.evaluate('Boolean(document.querySelector("[data-ground-load] canvas"))'))
        with mock.patch.object(app.store,'save',side_effect=OSError('disk full')):
            click('[data-ground-action=store_ground]')
            wait('document.querySelector("[data-ground-retry]")')
        self.assertAlmostEqual(a['total_kg'],self.post('/api/workshop/inventory',{},world)['ground_load']['total_kg'],places=5)
        p.send('Page.reload',{})
        wait('document.querySelector("[data-ground-retry]")')
        self.assertTrue(p.evaluate('document.querySelector("[data-ground-action=store_ground]").disabled'))
        click('[data-ground-retry]')
        wait('document.querySelector("#ws-inv-stored-ground [data-ground-lot]") && !document.querySelector("[data-ground-retry]")')
        own=self.post('/api/workshop/inventory',{},world)
        self.assertAlmostEqual(source_kg,sum(v['mass_kg'] for v in own['stored_ground']),places=5)
        click('[data-ground-action=retrieve_ground]')
        wait('!document.querySelector("[data-ground-action=retrieve_ground]:disabled") && document.querySelector("#ws-inv-ground").textContent.includes("5 kg")')
        retrieved=self.post('/api/workshop/inventory',{},world)
        self.assertAlmostEqual(min(5,source_kg),retrieved['ground_load'][material+'_kg'],places=5)
        for substance in ('sand','soil','rock'):
            if legacy.get(substance+'_kg',0)<=.0005:continue
            selector=f'#ws-inv-unassigned [data-ground-load="{substance}"] [data-ground-action=recover_ground]'
            click(selector)
            wait('!document.querySelector('+json.dumps(selector)+')')
        recovered=self.post('/api/workshop/inventory',{},world)
        self.assertAlmostEqual(legacy['total_kg'],sum(v['mass_kg'] for v in recovered['stored_ground'] if v['recovered']),places=5)
        self.assertEqual(0,recovered['unassigned_ground']['total_kg'])
        peer=self.post('/api/workshop/inventory',{},world,bob['token'])
        self.assertEqual([],peer['stored_ground']);self.assertAlmostEqual(b['total_kg'],peer['ground_load']['total_kg'],places=5)
        self.assertEqual(0,p.evaluate('document.querySelectorAll("button button").length'))
        self.assertEqual([],[e for e in p.events if e.get('method')=='Runtime.exceptionThrown'])
        p.evaluate('document.querySelector("#ws-inv-stored-ground").scrollIntoView({block:"center"})')
        (ROOT/'build/resource-flow/raw-storage-inventory.png').write_bytes(
            base64.b64decode(p.send('Page.captureScreenshot',{'format':'png'})['data']))

    def test_independent_capacity_deposit_spoof_refusal_and_restart(self):
        with mock.patch.object(flow.server.secrets,'randbelow',side_effect=[0,851269740]):
            world,alice,app=self.setup_world()
        bob=self.join(world,'Other gatherer');sid=app.live.session.id
        def act(op,token=None,**more):
            return self.post('/api/live/act',{'session':sid,'op':op,**more},world,token)
        def carrying(token=None):
            return self.post('/api/world/inventory/shown',{'session':sid},world,token)['carried']
        a=act('dig',**{'from':[-1,0],'to':[-1,0],'width_m':.8,'depth_m':.4})
        self.assertAlmostEqual(80,a['carried']['total_kg'],places=5)
        self.assertEqual(0,carrying(bob['token'])['total_kg'])
        # The server derives actor identity from the authenticated token.
        with self.assertRaises(urllib.error.HTTPError) as refusal:
            act('ground_withdraw',bob['token'],actor=alice['id'],
                sand_m3=a['carried']['sand_m3'],soil_m3=a['carried']['soil_m3'])
        self.assertEqual(400,refusal.exception.code)
        b=act('dig',bob['token'],actor=alice['id'],**{'from':[2,-1],'to':[2,-1],'width_m':.8,'depth_m':.4})
        self.assertAlmostEqual(80,b['carried']['total_kg'],places=5)
        self.assertAlmostEqual(80,carrying()['total_kg'],places=5)
        # An actual rover scoop uses its server-owned machine account even
        # when invoked inside a full player's request context.
        import machine_tools
        program=next(p for p in app.live.session.state['machines']['programs'] if p['kind']=='roam')
        brain=app.brains.of(program['name'])
        with app.live.as_actor(alice['id']):
            machine_tools.run(brain.context(app.brains._ask(app,sid)),machine_tools.Call('dig',{},'routine'))
        self.assertGreater(brain.routine.kg,0)
        self.assertAlmostEqual(80,carrying()['total_kg'],places=5)
        self.assertAlmostEqual(80,carrying(bob['token'])['total_kg'],places=5)
        self.assertEqual(0,app.live.session.state['player_carried']['machine:'+program['name']]['total_kg'])
        app.clock._tick(.05) # unattended stepping must not select another player's stock
        self.assertAlmostEqual(80,carrying()['total_kg'],places=5)
        self.assertAlmostEqual(80,carrying(bob['token'])['total_kg'],places=5)
        self.assertTrue(flow.server.keep_world(app,'save independent ground accounts'))
        saved=deepcopy(app.room.world_record)
        self.assertEqual('banjo.ground-state.v5',saved['ground']['schema'])
        self.assertGreater(saved['ground']['carriers'][alice['id']]['sand_m3'],0)
        self.assertGreater(sum(saved['ground']['carriers'][bob['id']].values()),0)
        self.stop();self.start()
        for guest in (alice,bob):
            rejoined=self.post('/api/world/player/join',{'token':guest['token']},world)
            self.assertEqual(guest['id'],rejoined['id'])
        opened=self.post('/api/world/open',{},world);sid=opened['session']
        self.assertEqual('whole',opened['restored']['tier'])
        self.assertAlmostEqual(80,opened['terrain']['carried']['total_kg'],places=5)
        self.assertAlmostEqual(80,carrying(bob['token'])['total_kg'],places=5)
        emptied=act('deposit',at=[-2,-1],radius_m=.8,
            sand_m3=a['carried']['sand_m3'],soil_m3=a['carried']['soil_m3'])
        self.assertAlmostEqual(0,emptied['carried']['total_kg'],places=6)
        self.assertAlmostEqual(80,carrying(bob['token'])['total_kg'],places=5)
        # Global native export counters cannot fund a raw player return.
        # Server-owned machine/storage receipts authorize those operations.
        with self.assertRaises(urllib.error.HTTPError) as unfunded:
            act('ground_return',sand_m3=0,soil_m3=.001)
        self.assertEqual(400,unfunded.exception.code)
        self.assertEqual(0,carrying()['total_kg'])
        with self.assertRaises(urllib.error.HTTPError):
            act('deposit',actor=bob['id'],at=[-2,-1],radius_m=.8,
                sand_m3=b['carried']['sand_m3'],soil_m3=b['carried']['soil_m3'])
        report=act('environment')['environment']['ground']
        self.assertAlmostEqual(80,sum(report['carried_all'][k+'_kg'] for k in ('sand','soil','rock')),places=5)
        for substance in ('sand','soil'):
            key=substance+'_m3'
            self.assertAlmostEqual(0,report['residual'][key],places=9)
            self.assertAlmostEqual(report['ledger']['dug'][key],
                report['ledger']['deposited'][key]+report['carried_all'][key]
                +report['exported'][key]-report['returned'][key],places=9)
        (ROOT/'build/resource-flow/private-ground-api.json').write_text(json.dumps(
            {'alice':a['carried'],'bob':b['carried'],'after_alice_heap':report},indent=2))

    def test_browser_reads_its_own_load_after_another_player_digs(self):
        if not flow.qa_browser.CHROME.is_file():self.skipTest('Chrome not installed')
        world,alice,app=self.setup_world();sid=app.live.session.id
        chrome=flow.qa_browser.Chrome(1280,800);self.addCleanup(chrome.close)
        p=chrome.page;p.send('Page.enable');p.send('Runtime.enable')
        p.send('Page.navigate',{'url':self.base+f'/world?world={world}'})
        def wait(expr):
            deadline=time.monotonic()+40
            while time.monotonic()<deadline:
                if p.evaluate('Boolean('+expr+')'):return
                time.sleep(.1)
            self.fail(expr)
        wait('window.banjoRoom?.ready()')
        browser_id=p.evaluate('banjoRoom.status().player_id')
        self.assertNotEqual(alice['id'],browser_id)
        self.post('/api/live/act',{'session':sid,'op':'dig','from':[-1,0],'to':[-1,0],
            'width_m':.8,'depth_m':.4},world)
        wait('banjoRoom.world.carriedGround && banjoRoom.world.carriedGround.total_kg===0')
        self.assertIn('0.0 / 80 kg',p.evaluate('document.querySelector("#world-load-meter").textContent'))
        self.assertEqual('false',p.evaluate('document.querySelector("#world-load-meter").dataset.full'))
        peer=next(g for g in app.room.player_records.values() if g['id']==browser_id)
        self.post('/api/live/act',{'session':sid,'op':'dig','from':[2,-1],'to':[2,-1],
            'width_m':.8,'depth_m':.4},world,peer['token'])
        wait('document.querySelector("#world-load-meter").dataset.full==="true"')
        self.assertAlmostEqual(80,p.evaluate('banjoRoom.world.carriedGround.total_kg'),places=5)
        # Earlier saves may carry an anonymous world load. It stays separate
        # and visible rather than becoming the next joining player's property.
        legacy=app.live.act({'session':sid,'op':'dig','from':[3,1],'to':[3,1],
            'width_m':.4,'depth_m':.1})['carried']
        self.assertGreater(legacy['total_kg'],0)
        p.send('Page.navigate',{'url':self.base+f'/world?world={world}&workshop=1&tab=inventory'})
        wait('document.querySelector("#ws-inv-ground [data-ground-load]")')
        wait('document.querySelector("#ws-inv-unassigned [data-ground-load]")')
        wait('document.querySelector("#ws-inv-energy .ws-energy-card")')
        self.assertIn('80 kg',p.evaluate('document.querySelector("#ws-inv-ground").textContent'))
        self.assertIn('Unassigned',p.evaluate('document.querySelector("#ws-inv-unassigned").textContent'))
        self.assertIn('Heap → World',p.evaluate('document.querySelector("#ws-inv-ground").textContent'))
        loaded=self.post('/api/workshop/inventory',{},world,peer['token'])
        self.assertAlmostEqual(80,loaded['ground_load']['total_kg'],places=5)
        self.assertAlmostEqual(legacy['total_kg'],loaded['unassigned_ground']['total_kg'],places=5)
        p.evaluate('document.querySelector("#ws-inv-unassigned").scrollIntoView({block:"end"})')
        (ROOT/'build/resource-flow/private-ground-inventory.png').write_bytes(
            base64.b64decode(p.send('Page.captureScreenshot',{'format':'png'})['data']))
        self.assertEqual([],[e for e in p.events if e.get('method')=='Runtime.exceptionThrown'])


if __name__=='__main__':unittest.main()
