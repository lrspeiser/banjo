"""Composed personal goals exercised through player HTTP/native controls."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'playground'),str(ROOT)]
import ai_player_tests as agents
import goal_chains
import server
import starter_goals_tests as camp
import world_hub_tests as hub


class Predicates(unittest.TestCase):
    def test_own_tool_requires_paid_owner_admission_and_positive_use_of_that_body(self):
        from types import SimpleNamespace
        tool={'status':'installed','owner_id':'alice','resources_charged':True,
              'engine_grid_verified':True,'root_body':'made-tool','request_id':'paid','matter_physics_hash':'hash'}
        saved={'spec':{'bodies':[{'name':'made-tool'}],
                      'interactions':[{'template':'swing-and-lever','tool':'made-tool','parts':['made-tool']}]},
               'world':{'bodies':[{'name':'made-tool'}]},'workshop_installs':[tool]}
        e={'id':'ev','run':'world:alice:actual','passes':True,'source':'found-example','test':'loosens-soil',
           'tool':'made-tool','result':{'loosened_m3':.001},'tool_condition':{'after':{'whole':True}}}
        journal=lambda event:SimpleNamespace(copy=lambda:{'evidence':{'ev':event}})
        predicate={'kind':'own-tool-test'}
        result=goal_chains.evaluate(predicate,journal(e),saved,'alice','world',None)
        self.assertEqual('paid',result['request_id'])
        for edit in ({'tool':'field pick'},{'run':'world:bob:actual'},{'passes':False},
                     {'result':{'loosened_m3':0}},{'tool_condition':{'after':{'whole':False}}}):
            self.assertIsNone(goal_chains.evaluate(predicate,journal({**e,**edit}),saved,'alice','world',None))
        for edit in ({'owner_id':'bob'},{'resources_charged':False},{'engine_grid_verified':False}):
            bad=deepcopy(saved);bad['workshop_installs'][0].update(edit)
            self.assertIsNone(goal_chains.evaluate(predicate,journal(e),bad,'alice','world',None))

    def test_surface_annotation_without_actual_matching_box_face_is_not_evidence(self):
        saved={'spec':{'precise_rigid_bodies':[{'name':'built','parts':[{
            'dimensions_m':[.5,.04,.4],'center_local_m':[0,0,0]}]}],
            'interaction_points':[{'body':'built','points':[{'kind':'surface','id':'top',
                'position_m':[0,.02,0],'size_m':[.5,2,.4]}]}]},
            'world':{'t_s':1,'bodies':[{'name':'built','orientation_wxyz':[1,0,0,0]}]},
            'workshop_installs':[{'root_body':'built','status':'installed','owner_id':'alice',
                'resources_charged':True,'native_precise_geometry_verified':True,
                'request_id':'paid','matter_physics_hash':'engine-hash'}]}
        self.assertEqual(.2,goal_chains._surface(saved,'alice',.1)['area_m2'])
        self.assertIsNone(goal_chains._surface(saved,'bob',.1))
        for change in ('oversized','floating','rotated','point-yaw','parked','unfunded','unadmitted'):
            bad=deepcopy(saved)
            if change=='oversized':bad['spec']['interaction_points'][0]['points'][0]['size_m'][0]=2
            if change=='floating':bad['spec']['interaction_points'][0]['points'][0]['position_m'][1]=1
            if change=='rotated':bad['spec']['precise_rigid_bodies'][0]['parts'][0]['rotation_wxyz']=[.70710678,.70710678,0,0]
            if change=='point-yaw':bad['spec']['interaction_points'][0]['points'][0]['yaw_deg']=45
            if change=='parked':bad['world']['bodies'][0]['parked']=True
            if change=='unfunded':bad['workshop_installs'][0]['resources_charged']=False
            if change=='unadmitted':bad['workshop_installs'][0]['native_precise_geometry_verified']=False
            self.assertIsNone(goal_chains._surface(bad,'alice',.1),change)

    def test_catalog_refuses_unimplemented_predicate_and_navigation_only(self):
        data=json.loads((ROOT/'progression/goals.json').read_text())
        read_text=Path.read_text
        goal_chains.definitions.cache_clear()
        try:
            for predicate in ({'kind':'shaping'},{'kind':'personal-test','test':'study-example',
                'source':'found-example','positive':'invented_work'}):
                bad=deepcopy(data);bad['chains'][0]['steps'][0]['predicate']=predicate
                with mock.patch.object(Path,'read_text',autospec=True,
                    side_effect=lambda path,*a,**kw:json.dumps(bad) if path.name=='goals.json' else read_text(path,*a,**kw)):
                    with self.assertRaises(ValueError):goal_chains.definitions()
                goal_chains.definitions.cache_clear()
        finally:goal_chains.definitions.cache_clear()
        self.assertEqual(4,len(goal_chains.definitions()['first-workshop-v1']['steps']))
        self.assertEqual(3,len(goal_chains.definitions()['first-tool-v1']['steps']))


@unittest.skipUnless(hub.RUNNER.is_file() and hub.ENGINE.is_file(),'native engine required')
class PlayerJourney(unittest.TestCase):
    setUp=agents.AutonomousGuests.setUp
    start=agents.AutonomousGuests.start
    stop=agents.AutonomousGuests.stop
    tearDown=agents.AutonomousGuests.tearDown
    get=hub.NamedWorlds.get
    post=hub.NamedWorlds.post
    join=hub.NamedWorlds.join

    def test_personal_tool_opening_collects_builds_uses_and_restarts_for_two_players(self):
        reports=[]
        for terrain_choice,goods_seed in ((1,851269742),(0,1)):
            with mock.patch.object(server.secrets,'randbelow',side_effect=[terrain_choice,goods_seed-1]):
                world=self.post('/api/worlds',{'name':'Gather and make'})['id']
            alice=self.join(world,'Alice');bob=self.join(world,'Bob');self.players={world:alice}
            self.post('/api/world/open',{},world);app=self.app.hub.get(world)
            wood_before=sum(p.get('holds',{}).get('oak',0) for p in app.brains.goods.stockpiles)
            results=[]
            for index,player in enumerate((alice,bob)):
                token=player['token']
                def goals():return self.post('/api/workshop/goals',{},world,token)
                first=goals();self.assertEqual('first-tool-v1',first['chain_id'])
                self.assertEqual('get-tool-wood',first['next_goal'])
                sid=first['session'];guide=first['goals'][0]['guide']
                pile=app.brains.goods.by_name(guide['resource']);at=pile['at_m']
                floor=self.post('/api/live/act',{'session':sid,'op':'survey','at':at},world,token)['survey']['ground_m']
                collected=self.post('/api/world/goods/collect',{'session':sid,'pile':pile['name'],
                    'request_id':f'collect-{index}','person':{'eyes_m':[at[0],floor+1.62,at[1]],'facing':[1,0,0]}},world,token)
                self.assertGreaterEqual(collected['collected']['oak'],2)
                ready=goals();self.assertEqual('make-own-tool',ready['next_goal'])
                built=camp.make_paid(self,world,token,ready['recipe'],[-1.4,-.6+index*1.2],f'opening-made-{index}')
                self.assertTrue(built['engine_grid_verified']);self.assertTrue(built['resources_charged'])
                ready=goals();self.assertEqual('use-own-tool',ready['next_goal'])
                sid=ready['session'];root=ready['product_body']
                native=next(b for b in app.live.session.state['bodies'] if b['name']==root)
                x,z=-.9,.025
                floor=self.post('/api/live/act',{'session':sid,'op':'survey','at':[x,z]},world,token)['survey']['ground_m']
                target=self.post('/api/live/act',{'session':sid,'op':'survey','at':[x+1.2,z]},world,token)['survey']['ground_m']
                person={'standing_m':[x,floor,z],'eyes_m':[x,floor+1.62,z],'facing':[1,0,0],
                    'look_direction':[1.2,target-floor-1.62,0]}
                picked=self.post('/api/world/inventory',{'session':sid,'op':'take_up','item':root,
                    'request':f'equip-{index}','person':person},world,token)
                self.assertTrue(picked['ok'],picked)
                # Native work runs through the same request/clock as the page.
                replies=[];errors=[]
                def use():
                    try:replies.append(self.post('/api/world/tool/use',{'session':sid,'person':person,
                        'at_m':[x+1.2,target,z]},world,token))
                    except Exception as exc:errors.append(exc)
                worker=threading.Thread(target=use,daemon=True);worker.start();deadline=time.monotonic()+25
                while worker.is_alive() and time.monotonic()<deadline:
                    app.clock._tick(.05);time.sleep(.015)
                worker.join(1);self.assertFalse(worker.is_alive());self.assertEqual([],errors)
                self.assertNotIn('refused',replies[0],replies[0])
                self.assertGreater(replies[0]['result']['loosened_kg'],0,replies[0])
                finished=self.post('/api/workshop/goals',{'chain':'first-tool-v1'},world,token)
                self.assertTrue(finished['complete'],finished)
                self.assertEqual(root,finished['goals'][2]['evidence']['body'])
                # The active checklist moves on; the old purchase checklist does not gate it.
                self.assertEqual('first-workshop-v1',goals()['chain_id'])
                legacy=self.post('/api/workshop/goals',{'chain':'first-camp-v1'},world,token)
                self.assertFalse(any(g['complete'] for g in legacy['goals']))
                self.post('/api/world/inventory',{'session':sid,'op':'stow','item':root,
                    'request':f'pack-{index}','person':person},world,token)
                results.append((player,finished))
            self.assertNotEqual(results[0][1]['product_body'],results[1][1]['product_body'])
            self.stop();self.start()
            self.post('/api/world/open',{},world)
            for player,finished in results:
                restored=self.post('/api/workshop/goals',{'chain':'first-tool-v1'},world,player['token'])
                self.assertEqual([(g['id'],g['complete'],g['evidence']) for g in finished['goals']],
                    [(g['id'],g['complete'],g['evidence']) for g in restored['goals']])
                inv=self.post('/api/workshop/inventory',{},world,player['token'])
                self.assertTrue(any(i['name']==finished['product_body'] and i['label']=='Personal field pick' for i in inv['carried']))
                self.assertAlmostEqual(23.075,next(m['personal_kg'] for m in inv['materials'] if m['material']=='oak'))
            app=self.app.hub.get(world)
            self.assertAlmostEqual(50,wood_before-sum(p.get('holds',{}).get('oak',0) for p in app.brains.goods.stockpiles))
            with server.workshop_library._connect(app) as db:
                self.assertEqual(0,db.execute('SELECT COUNT(*) FROM market_orders').fetchone()[0])
                self.assertEqual(0,db.execute('SELECT COUNT(*) FROM market_deposits').fetchone()[0])
            reports.append({'terrain_seed':7 if terrain_choice else 4,'goods_seed':goods_seed,
                'players':2,'cell_m':.05,'dt_s':1/240,'provider_calls':0,
                'market_orders':0,'wallet_deposits':0,'results':[r[1] for r in results],
                'restart_retained':True})
        output=ROOT/'build/opening-tools';output.mkdir(parents=True,exist_ok=True)
        (output/'acceptance.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')

    def test_empty_loose_wood_and_market_produce_a_real_blocker_without_awards(self):
        world=self.post('/api/worlds',{'name':'Finite exhausted wood'})['id']
        owner=self.join(world,'Late arrival');self.players={world:owner}
        self.post('/api/world/open',{},world);app=self.app.hub.get(world)
        # Explicit depleted-source fixture: removes supply, grants no material.
        for pile in app.brains.goods.stockpiles: pile.get('holds',{}).pop('oak',None)
        self.post('/api/workshop/market',{},world)
        with server.workshop_library._connect(app) as db:
            db.execute("UPDATE market_stock SET remaining=0 WHERE item_id='oak-stock'")
        goals=self.post('/api/workshop/goals',{},world)
        self.assertEqual('get-tool-wood',goals['next_goal'])
        self.assertFalse(any(g['complete'] for g in goals['goals']))
        self.assertEqual('market',goals['goals'][0]['guide']['screen'])
        self.assertNotIn('resource',goals['goals'][0]['guide'])
        import ai_actions
        market=self.post('/api/workshop/market',{},world)
        book=self.post('/api/workshop/recipes',{},world)
        offered=ai_actions.catalog({'goals':goals,'market':market,'stockpiles':book['stockpiles']}, {})
        self.assertEqual(['wait'],[a['verb'] for a in offered])
        self.assertIn('no oak lot in stock',offered[0]['blockers'][0])

    def test_camp_tool_surface_and_supported_batch_on_two_seeds_without_grants(self):
        reports=[]
        for terrain_choice,goods_seed in ((1,851269742),(0,1)):
            with mock.patch.object(server.secrets,'randbelow',side_effect=[terrain_choice,goods_seed-1]):
                world=self.post('/api/worlds',{'name':'Composed player journey'})['id']
            owner=self.join(world,'Builder');self.players={world:owner}
            other=self.join(world,'Distant guest')
            self.post('/api/world/open',{},world)
            app=self.app.hub.get(world)
            first=camp.play_first_camp(self,world,owner['token'])
            self.assertTrue(first['complete'])
            def goals(player=None):return self.post('/api/workshop/goals',{'chain':'first-workshop-v1'},world,player)
            before=goals();self.assertEqual('study-tool',before['next_goal'])
            self.assertEqual(before['goals'],goals()['goals'],'viewing cannot award progress')
            self.assertTrue(before['unlocked'])
            session=before['session']
            floor=self.post('/api/live/act',{'session':session,'op':'survey','at':[-.9,.025]},world)['survey']['ground_m']
            ground=self.post('/api/live/act',{'session':session,'op':'survey','at':[.3,.025]},world)['survey']['ground_m']
            person={'standing_m':[-.9,floor,.025],'eyes_m':[-.9,floor+1.62,.025],
                'facing':[1,0,0],'look_direction':[1.2,ground-floor-1.62,0]}
            def inventory(op,item):
                shown=self.post('/api/world/inventory/shown',{'session':session},world)
                reply=self.post('/api/world/inventory',{'session':session,'op':op,'item':item,
                    'request':f'{op}-{item}-{terrain_choice}','revision':shown['record']['revision'],'person':person},world)
                self.assertTrue(reply['ok'],reply)
            inventory('take_up','field pick')
            studied=self.post('/api/world/action',{'session':session,'object':'field pick','primary':True,'person':person},world)
            self.assertNotIn('refused',studied,studied)
            self.assertEqual('gather-ground',goals()['next_goal'])
            replies=[];errors=[]
            def use():
                try:replies.append(self.post('/api/world/tool/use',{'session':session,'person':person,'at_m':[.3,ground,.025]},world))
                except Exception as exc:errors.append(exc)
            worker=threading.Thread(target=use,daemon=True);worker.start();deadline=time.monotonic()+25
            while worker.is_alive() and time.monotonic()<deadline:
                app.clock._tick(.05);time.sleep(.015)
            worker.join(1);self.assertFalse(worker.is_alive());self.assertEqual([],errors)
            self.assertGreater(replies[0]['result']['loosened_kg'],0,replies[0])
            gathered=goals();self.assertEqual('build-surface',gathered['next_goal'])
            self.assertIn('using-ground-tools',server.journal_of(app,owner['id']).knows())
            inventory('stow','field pick')
            candidate=deepcopy(gathered['recipe'])
            # A different id and shape still works: match admitted support,
            # not a hardcoded tutorial name or exact sample recipe hash.
            if not terrain_choice:
                candidate['design_id']='another-useful-surface'
                candidate['parameters'].update(width_m=.50,depth_m=.35)
            context=self.post('/api/world/workshop/context',{},world)
            preview=self.post('/api/world/workshop/preview',{'session':context['session'],'scene':context['scene'],
                'mode':'authoring','candidate':candidate,'position_m':[4.5,0]},world)
            self.assertTrue(preview['needs']['enough'],preview)
            made=self.post('/api/world/workshop/commit',{'session':preview['session'],'scene':preview['scene'],
                'preview_id':preview['preview_id'],'request_id':f'surface-{terrain_choice}'},world)
            session=made['session']
            self.assertTrue(made['resources_charged']);self.assertTrue(made['native_precise_geometry_verified'])
            self.assertEqual('observe-process',goals()['next_goal'])
            # Exercise the advertised next use on the actual admitted table.
            # The normal native resolver must promise supported placement.
            root=made['root_body'];stool=first['goals']['camp_body']
            native=next(b for b in app.live.session.state['bodies'] if b['name']==root)
            surface=next(p for r in app.room.spec['interaction_points'] if r['body']==root
                for p in r['points'] if p['kind']=='surface')
            import placement
            delta=placement.rotate(native['orientation_wxyz'],surface['position_m'])
            top=[native['position_m'][k]+delta[k] for k in range(3)]
            floor=self.post('/api/live/act',{'session':session,'op':'survey','at':[top[0],top[2]+1.2]},world)['survey']['ground_m']
            person={'standing_m':[top[0],floor,top[2]+1.2],'eyes_m':[top[0],floor+1.62,top[2]+1.2],
                'facing':[0,0,-1],'look_direction':[0,top[1]-floor-1.62,-1.2],'looking_at':root}
            inventory('equip',stool)
            target=self.post('/api/world/placement',{'session':session,'name':stool,'person':person},world)
            self.assertTrue(target['fits'],target)
            self.assertEqual(root,target['onto'],target)
            placed=[];place_errors=[]
            def putdown():
                try:placed.append(self.post('/api/world/putdown',{'session':session,'object':stool,'person':person,
                    'placement_target':target['target']},world))
                except Exception as exc:place_errors.append(exc)
            worker=threading.Thread(target=putdown,daemon=True);worker.start();deadline=time.monotonic()+25
            while worker.is_alive() and time.monotonic()<deadline:
                app.clock._tick(.05);time.sleep(.015)
            worker.join(1);self.assertFalse(worker.is_alive());self.assertEqual([],place_errors)
            dropped=placed[0]
            self.assertTrue(dropped['ok'],dropped)
            # Only native supported batches watched personally can finish.
            import machine_witness
            source=next(m for m in machine_witness.machines(app) if m['recipe']=='smelt copper')
            at=source['at_m'];person={'eyes_m':[at[0],at[1]+1.2,at[2]+2],
                'facing':[0,0,-1],'look_direction':[0,-1.2,-2]}
            request={'session':session,'machine':source['machine'],'person':person}
            self.post('/api/world/watch-machine',request,world)
            self.assertFalse(goals()['complete'],'watch registration is not a batch')
            for tick in range(220):
                if tick%30==0:self.post('/api/world/watch-machine',request,world)
                app.clock._tick(.2)
                if any(e.get('source')=='watched' for e in server.journal_of(app,owner['id']).copy()['evidence'].values()):break
            final=goals();self.assertTrue(final['complete'],final)
            self.assertTrue(all(g['evidence'] for g in final['goals']))
            self.assertFalse(any(g['complete'] for g in goals(other['token'])['goals']))
            self.assertNotIn('rough-shaping-wood',server.journal_of(app,owner['id']).knows())
            self.stop();self.start();self.post('/api/world/open',{},world)
            restored=goals();self.assertEqual(final['goals'],restored['goals'])
            self.assertTrue(restored['complete'])
            self.assertEqual('first-workshop-v1',self.post('/api/workshop/goals',{'chain':'active'},world)['chain_id'])
            reports.append({'terrain_seed':7 if terrain_choice else 4,'goods_seed':goods_seed,
                'camp_actions':len(first['trace']),'chain':final,'native_dt_s':1/240,'cell_m':.05,
                'provider_calls':0,'mode':'scripted HTTP player; accelerated ordinary clock',
                'other_guest_completed':0,'restart_preserved':True,'stool_placed_on_table':True})
        output=ROOT/'build/goal-chains';output.mkdir(parents=True,exist_ok=True)
        (output/'acceptance.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')

    def test_browser_chapters_and_guides_navigate_without_earning_actions(self):
        import qa_browser
        if not qa_browser.CHROME.is_file():
            if os.environ.get('BANJO_BROWSER_TESTS')=='required':self.fail('Chrome required')
            self.skipTest('Chrome unavailable')
        world=self.post('/api/worlds',{'name':'Goal chapters'})['id']
        owner=self.join(world,'Guide reader');self.players={world:owner}
        self.post('/api/world/open',{},world)
        camp.play_first_camp(self,world,owner['token'])
        chrome=qa_browser.Chrome(1280,800);self.addCleanup(chrome.close)
        page=chrome.page;page.send('Page.enable');page.send('Runtime.enable')
        def wait(expression):
            deadline=time.monotonic()+25
            while time.monotonic()<deadline:
                try:
                    if page.evaluate(expression):return
                except (RuntimeError,TimeoutError):pass
                time.sleep(.15)
            self.fail('Browser did not reach '+expression)
        page.send('Page.navigate',{'url':self.base+'/world'})
        wait('document.readyState === "complete"')
        page.evaluate(f'localStorage.setItem("banjo.player.{world}",{json.dumps(owner["token"])})')
        url=self.base+f'/world?world={world}&workshop=1&tab=goals&goal-chain=first-workshop-v1'
        page.send('Page.navigate',{'url':url})
        wait('!!document.querySelector("[data-goal-go=study-tool]")')
        before=self.post('/api/workshop/goals',{'chain':'first-workshop-v1'},world)
        self.assertEqual(0,page.evaluate('document.querySelectorAll("[data-goal-action],[data-goal-bank]").length'))
        page.evaluate('document.querySelector("[data-goal-go=build-surface]").click()')
        wait('!!document.querySelector(".ws-goal-target[data-recipe]")')
        self.assertEqual('Work table',page.evaluate('document.querySelector(".ws-goal-target strong").textContent'))
        after=self.post('/api/workshop/goals',{'chain':'first-workshop-v1'},world)
        self.assertEqual(before['goals'],after['goals'])
        self.assertEqual(before['balance_j'],after['balance_j'])
        page.send('Page.navigate',{'url':url});wait('!!document.querySelector("[data-goal-go=study-tool]")')
        page.evaluate('document.querySelector("[data-goal-go=study-tool]").click()')
        wait('location.search.includes("tab=skills") && !!document.querySelector("#ws-pane-skills .ws-link")')
        self.assertEqual(before['goals'],self.post('/api/workshop/goals',{'chain':'first-workshop-v1'},world)['goals'])
        page.send('Page.navigate',{'url':url});wait('!!document.querySelector("[data-goal-go=study-tool]")')
        import base64
        output=ROOT/'build/goal-chains';output.mkdir(parents=True,exist_ok=True)
        (output/'checklist.png').write_bytes(base64.b64decode(page.send('Page.captureScreenshot')['data']))


if __name__=='__main__':unittest.main()
