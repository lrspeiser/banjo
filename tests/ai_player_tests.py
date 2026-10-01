"""Autonomous guest isolation, model decisions, restart and read-only watching."""
from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "playground"), str(ROOT / "tests"), str(ROOT)]
import server
import room_store
import ai_player
import ai_actions
import world_hub_tests as hub
import qa_browser
import knowledge_tests


class ControllerBoundaries(unittest.TestCase):
    def test_provider_view_omits_render_geometry_but_keeps_current_choices(self):
        state={'goals':{'chain_id':'new','title':'Goal','next_goal':'need','complete':False,
            'goals':[{'id':'need','requirement':{'kind':'energy-deposit'}}]},
            'native':{'session':'actual','t':2,'terrain':{'large mesh':'not planning input'},
                      'bodies':[{'mesh':['not planning input']}],'spec':{'not':'planning input'}},
            'market':{'balance_j':12,'offers':[],'bankable':True},'balance_j':12,
            'inventory':{'hands':{'right':None},'record':{'stowed':[]}},'skills':[]}
        actions=ai_actions.catalog(state,{})
        view=ai_actions.model_view(state,actions,[])
        self.assertEqual({'session':'actual','t':2},view['native'])
        self.assertEqual(actions,view['action_catalog'])
        self.assertNotIn('not planning input',json.dumps(view))
        self.assertEqual({'kind':'energy-deposit'},view['goals']['goals'][0]['requirement'])

    def test_dry_route_avoids_water_and_reports_an_unreachable_target(self):
        seen=[]
        def survey(x,z):
            seen.append((x,z))
            return {'on_the_ground':True,'ground_m':.25,
                    'water':{'depth_m':1 if .3<x<1.3 and abs(z)<.5 else 0}}
        path=ai_actions.walking_route([0,1.87,0],[3,0,0],1.2,survey)
        self.assertTrue(any(abs(p[2])>=.5 for p in path))
        self.assertTrue(all(not (.3<x<1.3 and abs(z)<.5) for x,y,z in path))
        self.assertAlmostEqual(1.2,((path[-1][0]-3)**2+path[-1][2]**2)**.5,delta=.24)
        with self.assertRaisesRegex(ValueError,'No surveyed dry route'):
            ai_actions.walking_route([0,1.87,0],[3,0,0],1.2,
                lambda x,z:{'on_the_ground':abs(x)<.1 and abs(z)<.1,'ground_m':0})
        self.assertLess(len(seen),1200)

    def test_catalog_uses_requirements_and_observed_targets_not_tutorial_names(self):
        state={'goals':{'chain_id':'unrelated-chain','next_goal':'renamed-task','goals':[
            {'id':'renamed-task','requirement':{'kind':'personal-test','test':'study-example'}}]},
            'pose':{'eyes_m':[0,1.62,0]},'recipes':[],'market':{},'skills':[
            {'id':'renamed-skill','name':'A technique','known':False,'unmet':[],
             'earned_by':[{'locations':[{'action':'inspect','body':'my new tool',
                 'where':'stowed','at_m':[8,0,8]}]}]}]}
        offered=ai_actions.catalog(state,{})
        target=next(a['target'] for a in offered if a['verb']=='select-target')
        offered=ai_actions.catalog(state,{'selected_target':target})
        self.assertEqual('acquire',next(a['verb'] for a in offered if a['verb']!='wait'))
        target['where']='right';state['skills'][0]['earned_by'][0]['locations'][0]=target
        offered=ai_actions.catalog(state,{'selected_target':target})
        self.assertEqual('inspect',next(a['verb'] for a in offered if a['verb']!='wait'))
        state['skills'][0]['unmet']=['a missing prerequisite']
        offered=ai_actions.catalog(state,{})
        self.assertFalse(any(a['verb']=='select-target' for a in offered))
        self.assertTrue(any('first needs' in b for a in offered if a['verb']=='wait' for b in a['blockers']))

    def test_reference_controller_stops_at_the_decision_budget(self):
        manager = ai_player.Manager.__new__(ai_player.Manager)
        manager.app = SimpleNamespace()
        manager.cadence_s = 0
        profile = {"pose": {}, "ai": {"mode": "reference", "history": [], "decisions": 0}}
        goals = {"complete":False,"chain_id":"unit","next_goal":"any-energy-goal",
            "goals":[{"id":"any-energy-goal","requirement":{"kind":"energy-deposit"}}]}
        manager._observe=lambda p,c:{'goals':goals,'market':{'bankable':True}}
        manager._post = lambda p, path, body, cookie: goals if path.endswith("goals") else {}
        manager._save = lambda p, **updates: p["ai"].update(updates)
        actions = []
        def execute(*args):
            actions.append(args[3]); return {"unit_fixture": True}
        manager._execute = execute
        manager._run(profile, threading.Event(), "")
        self.assertEqual(ai_player.MAX_DECISIONS, len(actions))
        self.assertEqual("blocked", profile["ai"]["status"])
        self.assertIn("budget", profile["ai"]["message"])

    def test_named_ground_work_is_attributed_to_the_striking_player_and_tool(self):
        with tempfile.TemporaryDirectory() as temp:
            alice, bob = "a" * 32, "b" * 32
            session = SimpleNamespace(id="fixture", room_spec=knowledge_tests.PICK_ROOM,
                state={"t":4,"player_hands": {alice: {"holding": "pick haft"}, bob: {"holding": "other tool"}}})
            app = SimpleNamespace(world_id="c" * 32, journal_lock=threading.RLock(), player_journals={},
                store=room_store.RoomStore(temp), room=SimpleNamespace(spec=knowledge_tests.PICK_ROOM,
                    player_records={alice:{},bob:{}}),
                live=SimpleNamespace(session=session))
            for owner in (alice, bob):
                scope = server.workshop_library.REQUEST_OWNER.set(owner)
                try: server.note_strike(app, {"t": 3.1})
                finally: server.workshop_library.REQUEST_OWNER.reset(scope)
            server.hear(app, session, {"ground_work": [knowledge_tests.closed("broke out")]})
            self.assertEqual({},server.journal_of(app,alice).data['evidence'])
            self.assertEqual([alice],[r['owner'] for r in app.room.player_evidence_pending])
            # This unit boundary uses an explicit source-save fixture. The
            # actual native/restart path is tested in AutonomousGuests.
            app.room.world_record={'t_s':4}
            app.room.player_learning_durable_ids={r['evidence']['id'] for r in app.room.player_evidence_pending}
            server.player_learning.saved(app,server.journal_of,server.registry())
            self.assertEqual(1, len(server.journal_of(app, alice).data["evidence"]))
            self.assertEqual({}, server.journal_of(app, bob).data["evidence"])
            scope = server.workshop_library.REQUEST_OWNER.set(bob)
            try:
                self.assertIs(server.journal_of(app), server.journal_of(app, bob))
                self.assertIsNot(server.journal_of(app), server.journal_of(app, shared=True))
            finally: server.workshop_library.REQUEST_OWNER.reset(scope)
            server.hear(app, session, {"ground_work": [knowledge_tests.closed("broke out")]})
            server.player_learning.saved(app,server.journal_of,server.registry())
            self.assertEqual(1, len(server.journal_of(app, alice).data["evidence"]))
            server.hear(app, session, {"ground_work": [knowledge_tests.closed("broke out", at_s=20)]})
            self.assertEqual(1, len(server.journal_of(app, alice).data["evidence"]))


@unittest.skipUnless(hub.RUNNER.is_file() and hub.ENGINE.is_file(), "native world engine not built")
class AutonomousGuests(unittest.TestCase):
    get, post, join = hub.NamedWorlds.get, hub.NamedWorlds.post, hub.NamedWorlds.join

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.port = hub.free_port(); self.base = f"http://127.0.0.1:{self.port}"
        self.config = mock.patch.object(server, "local_configuration", return_value=("", "gpt-5-mini"))
        self.config.start(); self.addCleanup(self.config.stop)
        self.environment = mock.patch.dict(os.environ, {"BANJO_WORLD_CLOCK": "0", "BANJO_LIVE_ENGINE": str(hub.RUNNER)})
        self.environment.start(); self.addCleanup(self.environment.stop)
        self.start()

    def start(self):
        self.app = server.Playground(hub.ENGINE, hub.ENGINE, Path(self.temp.name) / "runs")
        self.app.store = room_store.RoomStore(Path(self.temp.name) / "rooms")
        self.app.hub = server.WorldHub(self.app)
        self.app.password = None; self.app.public_host = None
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), server.Handler)
        self.httpd.app = self.app
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True); self.thread.start()
        self.token = self.get("/api/status")["csrf_token"]

    def stop(self):
        for app in list(self.app.hub.apps.values()):
            if getattr(app, "ai_players", None):
                app.ai_players.shutdown()
                for worker, _ in app.ai_players.workers.values(): worker.join(timeout=8)
        self.httpd.shutdown(); self.httpd.server_close(); self.thread.join(timeout=3)
        self.app.hub.shutdown(); self.app.live.shutdown(); self.app.pool.shutdown(wait=False)

    def tearDown(self):
        self.stop(); self.temp.cleanup()

    def setup_world(self):
        world = self.post("/api/worlds", {"name": "AI camp"})["id"]
        owner = self.join(world, "Human"); self.players = {world: owner}
        self.post("/api/world/open", {}, world)
        self.post("/api/world/ai", {"action": "list"}, world)
        app = self.app.hub.get(world)
        app.ai_players.cadence_s = .02
        return world, owner, app

    def test_waiting_action_allows_world_clock_and_other_guest_to_run(self):
        world, owner, app = self.setup_world()
        guest = self.join(world, "Other guest")
        session = app.live.session.id
        target = app.room.spec["precise_rigid_bodies"][0]["name"]
        # An ordinary server-authored wait step exercises the real action
        # route. No tool outcome or physical result is mocked here.
        app.room.spec.setdefault("actions", []).append({"body": target,
            "label": "Observe briefly", "steps": [{"do": "wait", "seconds": .8}]})
        started = threading.Event()
        original = server.run_action
        def run(*args, **kwargs):
            started.set()
            return original(*args, **kwargs)
        result = []
        with mock.patch.object(server, "run_action", side_effect=run):
            worker = threading.Thread(target=lambda: result.append(self.post("/api/world/action",
                {"session": session, "object": target, "action": 0}, world)))
            worker.start()
            self.assertTrue(started.wait(3))
            before = app.live.session.state["t"]
            began = time.monotonic()
            self.assertTrue(app.clock._tick(.05))
            other = self.post("/api/live/act", {"session": session, "op": "poses"}, world, guest["token"])
            self.assertGreater(other["t"], before)
            self.assertLess(time.monotonic() - began, .6, "world waited for the action's sleep")
            worker.join(timeout=4)
        self.assertFalse(worker.is_alive())
        self.assertEqual(["Observe briefly"], result[0]["did"])

    def test_generated_starter_tool_can_be_taken_re_equipped_and_used_through_player_routes(self):
        reports=[]
        for terrain_choice, goods_seed in ((1,851269742),(0,1)):
            # Only map selection is pinned. No inventory, geometry, hand
            # outcome, terrain transfer or journal is supplied by this test.
            with mock.patch.object(server.secrets,'randbelow',side_effect=[terrain_choice,goods_seed-1]):
                world,owner,app=self.setup_world()
            other=self.join(world,'Other guest')
            session=app.live.session.id
            surveyed=self.post('/api/live/act',{'session':session,'op':'survey','at':[-.9,.025]},world)
            floor=surveyed['survey']['ground_m']
            target=self.post('/api/live/act',{'session':session,'op':'survey','at':[.3,.025]},world)['survey']['ground_m']
            person={'standing_m':[-.9,floor,.025],'eyes_m':[-.9,floor+1.62,.025],
                    'facing':[1,0,0],'look_direction':[1.2,target-floor-1.62,0]}
            def inventory(op):
                shown=self.post('/api/world/inventory/shown',{'session':session},world)
                answer=self.post('/api/world/inventory',{'session':session,'request':f'{op}-{terrain_choice}',
                    'revision':shown['record']['revision'],'op':op,'item':'field pick','person':person},world)
                self.assertTrue(answer['ok'],answer)
                return answer
            inventory('take_up'); inventory('stow'); inventory('equip')
            owned=self.post('/api/world/inventory/shown',{'session':session},world)
            self.assertTrue(any((h or {}).get('name')=='field pick' for h in owned['hands'].values()))
            with mock.patch.object(app.store,'save',return_value=False):
                studied=self.post('/api/world/action',{'session':session,'object':'field pick',
                    'primary':True,'person':person},world)
            self.assertNotIn('refused',studied,studied)
            journal=server.journal_of(app,owner['id'])
            self.assertEqual({},journal.data['evidence'],'failed physical save must not publish study')
            self.assertEqual(1,len(app.room.player_evidence_pending))
            self.assertTrue(server.keep_world(app,'retry tool study physical save'))
            self.assertTrue(journal.standing_of('field-pick').get('demonstrated',{}).get('study-example'),studied)
            self.assertNotIn('using-ground-tools',journal.knows(),'inspection alone is not functional success')
            # The normal player API starts the stroke; the world's normal
            # clock advances it. This does not mutate the source snapshot.
            results=[];errors=[]
            def use():
                try:results.append(self.post('/api/world/tool/use',{'session':session,
                        'person':person,'at_m':[.3,target,.025]},world))
                except Exception as exc:errors.append(exc)
            with self.assertLogs('banjo',level='ERROR'), mock.patch.object(journal,'_save',side_effect=OSError('injected personal journal failure')):
                worker=threading.Thread(target=use,daemon=True);worker.start()
                deadline=time.monotonic()+22
                while worker.is_alive() and time.monotonic()<deadline:
                    app.clock._tick(.05)
                    time.sleep(.015)
                worker.join(timeout=1)
            self.assertFalse(worker.is_alive(),'normal player tool use did not finish')
            self.assertEqual([],errors)
            self.assertEqual(1,len(results))
            record=results[0].get('result') or {}
            self.assertFalse(record.get('open',True),results)
            self.assertTrue(record.get('supported'),results)
            self.assertGreater(record.get('loosened_kg',0),0,results)
            self.assertGreater(record.get('work_j',0),0)
            self.assertTrue(results[0].get('learning_pending'))
            self.assertIn('Journal update pending',results[0]['said'])
            self.assertNotIn('using-ground-tools',journal.knows())
            self.assertEqual(1,len(app.room.player_evidence_pending),'journal failure retains source outbox')
            # Close with the journal still unavailable: restart must recover
            # the durably saved source, rather than an in-memory retry.
            with self.assertLogs('banjo',level='ERROR'), mock.patch.object(journal,'_save',side_effect=OSError('injected personal journal failure')):
                self.stop()
            self.start()
            reopened=self.post('/api/world/open',{},world)
            app=self.app.hub.get(world); session=reopened['session']
            journal=server.journal_of(app,owner['id'])
            self.assertIn('using-ground-tools',journal.knows())
            self.assertNotIn('rough-shaping-wood',journal.knows(),'gathering cannot certify unsupported shaping')
            self.assertTrue(journal.standing_of('field-pick').get('demonstrated',{}).get('loosens-soil'))
            self.assertEqual({},server.journal_of(app,other['id']).data['evidence'])
            studied_again=self.post('/api/world/action',{'session':session,'object':'field pick',
                'primary':True,'person':person},world)
            self.assertNotIn('refused',studied_again,studied_again)
            kept=journal.copy()
            self.assertTrue(server.keep_world(app,'starter tool player check'))
            self.assertEqual(kept,journal.copy(),'outbox replay cannot duplicate evidence or rewards')
            before=app.live.snapshot()[0]
            reopened=self.post('/api/world/open',{},world)
            self.assertEqual(session,reopened['session'])
            self.assertEqual(before['tool_points'],app.live.snapshot()[0]['tool_points'])
            report={'terrain_seed':app.room.spec['terrain']['generate']['seed'],
                'goods_seed':goods_seed,'ground':record['ground'],'work_j':record['work_j'],
                'loosened':record['loosened'],'other_guest_evidence':0,'provider_calls':0,
                'learned':sorted(journal.knows()),'evidence_count':len(journal.data['evidence']),
                'source_save_failure_awarded_nothing':True,'journal_failure_recovered_on_restart':True,
                'repeated_save_awarded_nothing_twice':True,'native_dt_s':1/240,'cell_m':.05,
                'saved_t_s':before['t_s'],'evidence':list(journal.data['evidence'].values())}
            reports.append(report)
            print('generated player tool use:',{k:v for k,v in report.items() if k!='evidence'})
        output=ROOT/'build/player-learning';output.mkdir(parents=True,exist_ok=True)
        (output/'tool-acceptance.json').write_text(json.dumps({'schema':'banjo.player-tool-acceptance.v1',
            'mode':'scripted authenticated player controls; no provider calls','runs':reports},indent=2),encoding='utf-8')

    def test_actual_machine_batch_is_personal_and_learning_outbox_recovers_after_restart(self):
        import machine_witness
        world, owner, app = self.setup_world()
        other = self.join(world, "Distant observer")
        session = app.live.session.id
        source = next(m for m in machine_witness.machines(app) if m["recipe"] == "smelt copper")
        at = source["at_m"]
        person = {"eyes_m": [at[0], at[1]+1.2, at[2]+2], "facing": [0,0,-1],
                  "look_direction": [0,-1.2,-2]}
        request = {"session": session, "machine": source["machine"], "person": person}
        self.post("/api/world/watch-machine", request, world)
        self.post("/api/world/watch-machine", request, world, other["token"])
        # Watching is not a remote subscription: this guest walks away before
        # the real source batch. The normal pose route supplies the position.
        self.post("/api/live/act", {"session":session,"op":"step","dt":1/60,"n":1,
            "person":{"eyes_m":[70,2,70],"facing":[1,0,0]}}, world, other["token"])
        journal = server.journal_of(app,owner["id"])
        with mock.patch.object(journal,"add_evidence",side_effect=OSError("journal write unavailable")):
            for i in range(200):
                if i % 30 == 0:
                    self.post("/api/world/watch-machine", request, world)
                app.clock._tick(.2)  # accelerated wall time, unchanged native dt
                if machine_witness.pending_of(app):
                    break
            self.assertTrue(machine_witness.pending_of(app), "No actual processing receipt")
            self.assertEqual(set(),journal.knows())
            saved = json.loads(app.store.path_of(app.room.scene).read_text(encoding="utf-8"))
            receipt = saved["machine_evidence_pending"][0]
            from copy import deepcopy
            for change in ("batch", "observer", "id", "quantities"):
                corrupt = deepcopy(receipt)
                if change == "batch": corrupt["batch"] += 100
                elif change == "observer": corrupt["evidence"]["observer"]["player"] = other["id"]
                elif change == "id": corrupt["evidence"]["id"] = "ev-0000000000"
                else: corrupt["evidence"]["result"]["made"] = {"copper":-1}
                with self.assertRaises(ValueError):
                    machine_witness.validate_pending([corrupt],saved["machine_runtime"],saved["players"])
            self.assertEqual(owner["id"],receipt["owner"])
            self.assertGreater(receipt["evidence"]["result"]["made_kg"],0)
            self.assertGreater(receipt["evidence"]["result"]["drawn_j"],0)
            self.assertEqual(set(),server.journal_of(app,other["id"]).knows())
            self.stop()
        self.start()
        self.post("/api/world/player/join", {"token":owner["token"]}, world)
        self.post("/api/world/open", {}, world)
        restored = self.app.hub.get(world)
        recovered = server.journal_of(restored,owner["id"])
        self.assertEqual({"smelting-copper"},recovered.knows())
        self.assertEqual({receipt["evidence"]["id"]},set(recovered.data["evidence"]))
        self.assertEqual(set(),server.journal_of(restored,other["id"]).knows())
        revision = recovered.data["revision"]
        server.keep_world(restored,"repeat observation checkpoint")
        self.assertEqual(revision,recovered.data["revision"])
        report = {"schema":"banjo.player-learning-acceptance.v1",
            "native_dt_s":1/240,"scene_cell_m":.05,"accelerated_clock_slice_s":.2,
            "source_machine":receipt["machine"],"source_batch":receipt["batch"],
            "observed_t_s":receipt["evidence"]["observer"]["t_s"],
            "saved_t_s":saved["world"]["t_s"],"result":receipt["evidence"]["result"],
            "learned":sorted(recovered.knows()),"other_guest_learned":[],
            "evidence_count":len(recovered.data["evidence"]),"restart_outbox_replayed_once":True,
            "provider_calls":0,"limits":receipt["evidence"]["limitations"]}
        output = ROOT/"build/player-learning"; output.mkdir(parents=True,exist_ok=True)
        (output/"acceptance.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        print("\n    personal machine witness: "+json.dumps(report))

    def test_skill_and_market_guidance_resolve_world_equipment_and_input_shortages(self):
        world, owner, app = self.setup_world()
        skills = self.post("/api/workshop/skills",{},world)
        tree = {t["id"]:t for t in skills["techniques"]}
        self.assertFalse(tree["rough-shaping-wood"]["within_reach"])
        self.assertIn("Missing example",tree["rough-shaping-wood"]["earned_by"][0]["says"])
        self.assertFalse(tree["burning-lime"]["within_reach"])
        self.assertIn("Missing equipment",tree["burning-lime"]["earned_by"][0]["says"])
        copper = tree["smelting-copper"]
        self.assertTrue(copper["within_reach"])
        location = copper["earned_by"][0]["locations"][0]
        self.assertEqual("watch-machine",location["action"])
        self.assertEqual(3,len(location["at_m"]))
        self.assertTrue(tree['using-ground-tools']['within_reach'])
        tool_route=tree['using-ground-tools']['earned_by'][0]
        self.assertEqual({'inspect','tool/use'},{l['action'] for l in tool_route['locations']})
        self.assertTrue(all(l['body']=='field pick' for l in tool_route['locations']))
        self.assertEqual("using-ground-tools",self.post("/api/workshop/market",{},world)["guidance"]["skill"]["id"])
        # A shortage fixture removes input; it grants no stock or skill.
        intake = next(p for p in app.room.spec["goods"]["stockpiles"] if p["name"] == location["intake"])
        intake["holds"].clear()
        changed = next(t for t in self.post("/api/workshop/skills",{},world)["techniques"] if t["id"] == "smelting-copper")
        self.assertFalse(changed["within_reach"])
        self.assertTrue(any("intake needs" in m for m in changed["world_missing"]))

    def wait_character(self, world, ident, states=("complete", "blocked"), seconds=120):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            view = self.post("/api/world/ai", {"action": "watch", "id": ident}, world)
            if view["character"]["status"] in states: return view
            time.sleep(.15)
        self.fail("Character never reached a terminal state: "+json.dumps(view['character']))

    def test_reference_explorer_completes_goal_chains_on_both_generated_terrains(self):
        reports=[]
        for terrain_choice,goods_seed in ((1,851269742),(0,1)):
            with mock.patch.object(server.secrets,'randbelow',side_effect=[terrain_choice,goods_seed-1]):
                world,owner,app=self.setup_world()
            began=time.monotonic()
            bot=self.post('/api/world/ai',{'action':'start','mode':'reference','name':'Seed explorer'},world)
            final=self.wait_character(world,bot['id'])
            self.assertEqual('complete',final['character']['status'],final['character'])
            goals=final['goals']; journal=server.journal_of(app,bot['id'])
            known=journal.knows()
            self.assertIn('using-ground-tools',known)
            self.assertIn('smelting-copper',known)
            self.assertEqual(set(),server.journal_of(app,owner['id']).knows())
            self.assertTrue(all(e['mode']=='reference' and not e['model'] for e in final['character']['history']))
            actions={e['action'] for e in app.room.player_records[bot['id']]['ai']['history']}
            self.assertTrue({'move','select-target','inspect','acquire','use-tool','watch-batch',
                             'compare-recipes','build','pack'}<=actions,actions)
            self.assertEqual('saved',app.room.persistence['state'])
            evidence=list(journal.data['evidence'].values())
            reports.append({'terrain_seed':(4,7)[terrain_choice],'goods_seed':goods_seed,
                'controller':'reference','provider_calls':0,'world':world,'character':bot['id'],
                'wall_s':round(time.monotonic()-began,3),'native_t_s':app.live.session.state['t'],
                'decisions':final['character']['decisions'],'goal_chain':goals['chain_id'],
                'goals_complete':goals['complete'],'known':sorted(known),'tech_tree_total':len(final['skills']),
                'evidence':evidence,'goals':goals['goals'],'actions':sorted(actions)})
            # Actual runtime and learning must load unchanged, not just public summaries.
            self.assertTrue(server.keep_world(app,'reference journey exact reload boundary'))
            stored=app.store.load(app.room.scene)
            self.assertEqual(app.brains.runtime(),stored.machine_runtime)
            self.assertEqual([],stored.player_evidence_pending)
            self.assertEqual([],stored.machine_evidence_pending)
        output=ROOT/'build/ai-player';output.mkdir(parents=True,exist_ok=True)
        (output/'explorer-acceptance.json').write_text(json.dumps(reports,indent=2,allow_nan=False),encoding='utf-8')
        print('\n    reference explorer: '+json.dumps([{k:r[k] for k in ('terrain_seed','goods_seed','decisions','wall_s','native_t_s','known')} for r in reports]))

    def test_reference_explorer_reports_empty_market_shelves_on_both_terrains(self):
        for terrain_choice,goods_seed in ((1,851269742),(0,1)):
            with mock.patch.object(server.secrets,'randbelow',side_effect=[terrain_choice,goods_seed-1]):
                world,owner,app=self.setup_world()
            # Explicit scarcity fixture: removes trader stock only. No player
            # supplies, knowledge, goals or native outcomes are granted.
            self.post('/api/workshop/market',{},world)
            with server.workshop_library._connect(app) as db:
                db.execute("UPDATE market_stock SET remaining=0 WHERE item_id='oak-stock'")
            bot=self.post('/api/world/ai',{'action':'start','mode':'reference'},world)
            final=self.wait_character(world,bot['id'])
            self.assertEqual('blocked',final['character']['status'])
            self.assertIn('no oak lot in stock',final['character']['message'])
            self.assertFalse(final['goals']['complete'])
            self.assertEqual(set(),server.journal_of(app,bot['id']).knows())
            self.assertEqual(['bank','wait'],[e['action'] for e in final['character']['history']])


    def test_model_selected_actions_complete_real_goals_with_separate_bag_and_tech_tree(self):
        world, owner, app = self.setup_world()
        calls = []
        class FakeModel:
            def ask(self, state, questions):
                offered = list(questions["next"]["criteria"])
                pick = ai_actions.reference_pick(state,state['action_catalog'])
                self_offered = pick in offered
                if not self_offered:raise AssertionError('Mock provider selected outside the observed catalog')
                calls.append(state)
                return {"next": {"choice": pick, "confidence": .9}}
        app.api_key = "test-only-key"
        app.ai_players.decider_factory = FakeModel
        bot = self.post("/api/world/ai", {"action": "start", "mode": "openai", "name": "AI explorer"}, world)
        final = self.wait_character(world, bot["id"])
        self.assertEqual("complete", final["character"]["status"], final["character"])
        self.assertTrue(final["goals"]["complete"])
        self.assertGreater(len(calls),10)
        self.assertEqual({'first-camp-v1','first-workshop-v1'},{s['goals']['chain_id'] for s in calls})
        self.assertIn("inventory", calls[0])
        self.assertIn("tech_tree", calls[0])
        self.assertTrue(all(e["mode"] == "openai" and e["result"] == "committed" for e in final["character"]["history"]))
        self.assertTrue(all(isinstance(v,(float,int)) for v in final['character']['pose']['eyes_m']))
        self.assertIn('using-ground-tools',{s['id'] for s in final['skills'] if s['known']})
        self.assertGreaterEqual(sum(s['known'] for s in final['skills']),2)
        self.assertIn(final["goals"]["camp_body"], final["state"]["inventory"]["record"]["stowed"])
        human = self.post("/api/world/inventory/shown", {"session": final["state"]["session"]}, world)
        self.assertEqual([], human["record"]["stowed"])
        self.assertEqual(0, self.post("/api/workshop/market", {}, world)["balance_j"])
        self.assertFalse(self.post("/api/workshop/goals", {}, world)["complete"])
        bot_profile = app.room.player_records[bot["id"]]
        self.assertNotIn(bot_profile["token"], json.dumps(final))
        # Controlled journal fixture checks ownership/routing, not earned physics.
        server.journal_of(app, bot["id"]).learn("rough-shaping-wood", {"kind": "unit-fixture"}, "test")
        bot_tree = self.post("/api/world/ai", {"action": "watch", "id": bot["id"]}, world)["skills"]
        self.assertTrue(next(s for s in bot_tree if s["id"] == "rough-shaping-wood")["known"])
        self.assertFalse(next(s for s in self.post("/api/workshop/skills", {}, world)["techniques"]
                              if s["id"] == "rough-shaping-wood")["known"])
        headers = {"X-Banjo-World": world, "X-Banjo-Player": owner["token"]}
        with urllib.request.urlopen(urllib.request.Request(self.base + "/api/knowledge", headers=headers)) as response:
            self.assertEqual([], json.load(response)["techniques"])
        self.stop(); self.start()
        self.post("/api/world/player/join", {"token": owner["token"]}, world)
        self.post("/api/world/open", {}, world)
        restored = self.post("/api/world/ai", {"action": "watch", "id": bot["id"]}, world)
        self.assertTrue(restored["goals"]["complete"])
        self.assertIn(restored["goals"]["camp_body"], restored["state"]["inventory"]["record"]["stowed"])
        self.assertTrue(next(s for s in restored["skills"] if s["id"] == "rough-shaping-wood")["known"])

    def test_pause_during_model_call_executes_no_choice_and_foreign_guest_cannot_control(self):
        world, owner, app = self.setup_world()
        entered, release = threading.Event(), threading.Event()
        class WaitingModel:
            def ask(self, state, questions):
                entered.set(); release.wait(5)
                return {"next": {"choice": "bank", "confidence": .9}}
        app.api_key = "test-only-key"; app.ai_players.decider_factory = WaitingModel
        bot = self.post("/api/world/ai", {"action": "start", "mode": "openai"}, world)
        self.assertTrue(entered.wait(15))
        other = self.join(world, "Other")
        with self.assertRaises(urllib.error.HTTPError):
            self.post("/api/world/ai", {"action": "pause", "id": bot["id"]}, world, other["token"])
        self.post("/api/world/ai", {"action": "pause", "id": bot["id"]}, world)
        release.set(); app.ai_players.workers[bot["id"]][0].join(timeout=8)
        view = self.post("/api/world/ai", {"action": "watch", "id": bot["id"]}, world)
        self.assertEqual("paused", view["character"]["status"])
        self.assertEqual(0, view["goals"]["balance_j"])
        self.assertEqual(0, view["character"]["decisions"])
        self.stop(); self.start()
        self.post("/api/world/open", {}, world)
        self.assertEqual("paused", self.post("/api/world/ai", {"action": "list"}, world)["characters"][0]["status"])

    def test_unsupported_model_choice_is_refused_without_a_game_action(self):
        world, owner, app = self.setup_world()
        class InvalidModel:
            def ask(self, state, questions):
                return {"next": {"choice": "invent_money", "confidence": 1}}
        app.api_key = "test-only-key"; app.ai_players.decider_factory = InvalidModel
        bot = self.post("/api/world/ai", {"action": "start", "mode": "openai"}, world)
        view = self.wait_character(world, bot["id"])
        self.assertEqual("blocked", view["character"]["status"])
        self.assertEqual(0, view["character"]["decisions"])
        self.assertEqual(0, view["goals"]["balance_j"])
        self.assertFalse(view["goals"]["complete"])

    def test_stepping_guest_does_not_inherit_an_unowned_machine_batch(self):
        world, owner, app = self.setup_world()
        scope = server.workshop_library.REQUEST_OWNER.set(owner["id"])
        try: app.brains.on_made("smelt copper", {"copper": 1.5}, {"copper ore": 5.0})
        finally: server.workshop_library.REQUEST_OWNER.reset(scope)
        # An unsourced compatibility callback is not a named-world batch.
        self.assertNotIn("smelting-copper", server.journal_of(app, shared=True).knows())
        self.assertNotIn("smelting-copper", server.journal_of(app, owner["id"]).knows())

    def test_realtime_rover_returns_bank_retries_reload_and_restart_agree(self):
        from mcp import ground_transfers, fabrication
        import world_access
        # A persistence experiment needs a reproducible source route. These
        # select ordinary generator seeds from the published playthrough;
        # they do not grant stock, change terrain or steer the native rover.
        # Random route viability is a separate, still-open navigation gate.
        with mock.patch.object(server.secrets,"randbelow",side_effect=[1,851269741]):
            world,owner,app=self.setup_world()
        app.clock.start()
        self.addCleanup(app.clock.stop)
        began=time.monotonic(); returned=False; requests=[]
        while time.monotonic()-began<150:
            receipt="realtime-bank-"+str(len(requests))
            bank=self.post("/api/workshop/market",{"action":"bank","joules":100,"request_id":receipt},world)
            requests.append(receipt)
            again=self.post("/api/workshop/market",{"action":"bank","joules":100,"request_id":receipt},world)
            self.assertEqual(bank["balance_j"],again["balance_j"])
            with world_access.state_lock(app):
                totals=ground_transfers.totals(getattr(app.room,"ground_transfers",None))
                returned=sum(totals["returned"].values())>.001
            if returned: break
            time.sleep(3)
        if not returned:
            output = ROOT/"build/player-learning"; output.mkdir(parents=True,exist_ok=True)
            diagnostic = {"terrain":app.room.spec.get("terrain"),
                "machines":app.live.session.state.get("machines"),
                "routines":{n:b.routine.summary() for n,b in app.brains.brains.items()},
                "ground_totals":totals,"t":app.live.session.state.get("t"),
                "elapsed_s":time.monotonic()-began,"clock":{"ticks":app.clock.ticks,
                    "world_s":app.clock.world_s,"trouble":app.clock.trouble}}
            (output/"rover-timeout.json").write_text(json.dumps(diagnostic,indent=2),encoding="utf-8")
        self.assertTrue(returned,"Generated realtime rover never returned a measurable load; see build/player-learning/rover-timeout.json")
        self.assertGreater(app.live.session.state["t"],.5*(time.monotonic()-began))
        # A disk refusal must not credit the attempted draw or hide the error.
        balance=again["balance_j"]
        with mock.patch.object(app.store,"_save",side_effect=OSError("test disk unavailable")):
            with self.assertRaises(urllib.error.HTTPError) as failed:
                self.post("/api/workshop/market",{"action":"bank","joules":100,"request_id":"recover-bank"},world)
            failure=json.load(failed.exception)
            self.assertEqual("failed",failure["persistence"]["state"])
            self.assertEqual(balance,self.post("/api/workshop/market",{},world)["balance_j"])
        recovered=self.post("/api/workshop/market",{"action":"bank","joules":100,"request_id":"recover-bank"},world)
        self.assertEqual(balance+100,recovered["balance_j"])
        for _ in range(2):
            self.assertEqual(balance+100,self.post("/api/workshop/market",{"action":"bank","joules":100,"request_id":"recover-bank"},world)["balance_j"])
        rejoined=self.post("/api/world/player/join",{"token":owner["token"]},world)
        self.assertEqual(owner["id"],rejoined["id"])
        self.post("/api/world/open",{},world)
        app.clock.stop()
        with world_access.state_lock(app):
            self.assertTrue(server.keep_world(app,"realtime acceptance checkpoint"))
            book=json.loads(json.dumps(app.room.ground_transfers))
            runtime=app.brains.runtime()
            fabrication.validate_ground_stock({},app.room.world_record,book)
        duration=time.monotonic()-began; native_t=app.room.world_record["t_s"]
        self.stop(); self.start()
        self.post("/api/world/player/join",{"token":owner["token"]},world)
        restored=self.post("/api/world/open",{},world)
        restarted=self.app.hub.get(world)
        self.assertEqual("whole",restored["restored"]["tier"])
        self.assertEqual(book,restarted.room.ground_transfers)
        self.assertEqual(runtime,restarted.brains.runtime())
        self.assertEqual(balance+100,self.post("/api/workshop/market",{},world)["balance_j"])
        fabrication.validate_ground_stock({},restarted.room.world_record,book)
        print(f"\n    generated realtime: {native_t:.3f} native s / {duration:.3f} wall s; "
              f"{len(book['receipts'])} ground receipts; returned {totals['returned']}; "
              f"wallet {balance+100} J, duplicate/failure/rejoin/restart checked")

    def test_market_shows_complete_plan_and_refreshes_after_real_purchase(self):
        if not qa_browser.CHROME.is_file():
            if os.environ.get('BANJO_BROWSER_TESTS')=='required':self.fail('Chrome is required')
            self.skipTest('Chrome not installed')
        world,owner,app=self.setup_world()
        chrome=qa_browser.Chrome(1280,800);self.addCleanup(chrome.close)
        page=chrome.page;page.send('Page.enable');page.send('Runtime.enable')
        def wait(expression):
            until=time.monotonic()+35
            while time.monotonic()<until:
                try:
                    if page.evaluate(expression):return
                except (RuntimeError,TimeoutError):pass
                time.sleep(.15)
            self.fail('Browser did not reach '+expression)
        page.send('Page.navigate',{'url':self.base+f'/world?world={world}&workshop=1&tab=market&guide=stock-oak'})
        wait('document.querySelector("#ws-market-recipe h3")?.textContent === "Camp stool" && document.querySelectorAll("#ws-market-offers li").length === 6')
        self.assertIn('Build stock estimate',page.evaluate('document.querySelector("#ws-market-recipe").textContent'))
        self.assertIn('Covered',page.evaluate('document.querySelector("[data-market-gap=oak]").textContent'))
        self.assertIn('6/6 lots',page.evaluate('document.querySelector("[data-market-supply-goal]").textContent'))
        self.assertFalse(page.evaluate('document.querySelector("#ws-market-recipe details").open'))
        visitor_token=page.evaluate('localStorage.getItem("banjo.player.'+world+'")')
        visitor=next(p['id'] for p in server.player_world.records(app).values() if p['token']==visitor_token)
        self.assertEqual(set(),server.journal_of(app,visitor).knows())
        wait('!document.querySelector("#ws-market-bank").disabled')
        page.evaluate('document.querySelector("#ws-market-bank").click()')
        wait('document.querySelector("#ws-market-balance").textContent === "500 J"')
        page.evaluate('document.querySelector("[data-market-item=oak-stock] button").click()')
        wait('document.querySelector("#ws-market-balance").textContent === "380 J" && document.querySelector("[data-market-supply-goal]").textContent.includes("5/5 lots")')
        guidance=self.post('/api/workshop/market',{},world,visitor_token)['guidance']
        plan=guidance['plan']
        self.assertAlmostEqual(.5,plan['lines'][0]['personal_kg'])
        self.assertEqual(0,self.post('/api/workshop/market',{},world,owner['token'])['balance_j'])
        output=ROOT/'build/market-guidance';output.mkdir(parents=True,exist_ok=True)
        import base64
        (output/'market.png').write_bytes(base64.b64decode(page.send('Page.captureScreenshot')['data']))
        page.evaluate('[...document.querySelectorAll("#ws-market-recipe button")].find(b=>b.textContent==="Open recipe").click()')
        wait('new URLSearchParams(location.search).get("tab")==="recipes" && [...document.querySelectorAll("[data-recipe]")].some(c=>c.dataset.recipe === "stool:Camp stool" && c.classList.contains("ws-goal-target"))')
        self.assertEqual(set(),server.journal_of(app,visitor).knows())
        self.assertFalse([e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])
        (output/'receipt.json').write_text(json.dumps({'world_seed':self.app.hub.metadata(world)['terrain_seed'],
            'plan_after_purchase':plan,'supply_goal_after_purchase':guidance['supply_goal'],
            'wallet_j':380,'other_guest_wallet_j':0,
            'learned_by_navigation':[],'provider_calls':0},indent=2),encoding='utf-8')

    def test_skills_links_to_the_tool_without_awarding_progress_for_navigation(self):
        if not qa_browser.CHROME.is_file(): self.skipTest('Chrome not installed')
        world,owner,app=self.setup_world()
        chrome=qa_browser.Chrome(1280,800);self.addCleanup(chrome.close)
        page=chrome.page;page.send('Page.enable');page.send('Runtime.enable')
        def wait(expression):
            until=time.monotonic()+35
            while time.monotonic()<until:
                try:
                    if page.evaluate(expression):return
                except (RuntimeError,TimeoutError):pass
                time.sleep(.15)
            self.fail('Browser did not reach '+expression)
        page.send('Page.navigate',{'url':self.base+f'/world?world={world}&workshop=1&tab=skills&technique=using-ground-tools'})
        wait('!!document.querySelector("[data-technique=using-ground-tools]") && [...document.querySelectorAll(".ws-tree-todo a")].some(a=>a.textContent==="Go to tool")')
        viewer=page.evaluate('localStorage.getItem("banjo.player.'+world+'")')
        # Viewer identity can differ from the HTTP fixture's creator.
        ident=next(p['id'] for p in server.player_world.records(app).values() if p['token']==viewer)
        self.assertEqual(set(),server.journal_of(app,ident).knows())
        output=ROOT/'build/player-learning';output.mkdir(parents=True,exist_ok=True)
        import base64
        (output/'tool-skills.png').write_bytes(base64.b64decode(page.send('Page.captureScreenshot')['data']))
        page.evaluate('[...document.querySelectorAll(".ws-tree-todo a")].find(a=>a.textContent==="Go to tool").click()')
        wait('new URLSearchParams(location.search).get("focus")==="field pick" && !!window.banjoRoom?.status().ready')
        self.assertEqual(set(),server.journal_of(app,ident).knows())
        self.assertEqual({},server.journal_of(app,ident).data['evidence'])
        self.assertFalse([e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])

    def test_menu_starts_reference_bot_and_camera_watches_without_control(self):
        if not qa_browser.CHROME.is_file():
            if os.environ.get("BANJO_BROWSER_TESTS") == "required": self.fail("Chrome is required")
            self.skipTest("Chrome not installed")
        world, owner, app = self.setup_world()
        chrome = qa_browser.Chrome(1280, 800); self.addCleanup(chrome.close)
        page = chrome.page; page.send("Page.enable"); page.send("Runtime.enable"); page.send("Network.enable")
        def wait_for(expression, seconds=45):
            until = time.monotonic() + seconds
            while time.monotonic() < until:
                try:
                    if page.evaluate(expression): return
                except (RuntimeError, TimeoutError): pass
                time.sleep(.15)
            self.fail(f"Browser did not reach {expression}; " + str(page.evaluate('document.querySelector("#panel-state")?.textContent')))
        page.send("Page.navigate", {"url": self.base + f"/world?world={world}"})
        wait_for('!!window.banjoRoom?.status().ready')
        viewer_id = page.evaluate('window.banjoRoom.status().player_id')
        viewer_token = page.evaluate(f'localStorage.getItem("banjo.player.{world}")')
        before = self.post("/api/world/inventory/shown", {"session": page.evaluate('window.banjoRoom.status().session')}, world, viewer_token)
        page.evaluate('document.querySelector("[data-game-menu]").click()')
        wait_for('document.querySelector("#game-menu-ai-start select").value === "reference"')
        page.evaluate('document.querySelector("#game-menu-ai-start").requestSubmit()')
        wait_for('location.search.includes("watch=") && !!window.banjoRoom?.status().ready && !!document.querySelector("#watch-status")')
        bot_id = page.evaluate('new URLSearchParams(location.search).get("watch")')
        wait_for('document.querySelector("#watch-status").textContent.includes("complete")',seconds=100)
        view = self.post("/api/world/ai", {"action": "watch", "id": bot_id}, world)
        self.assertEqual(viewer_id, page.evaluate('window.banjoRoom.status().player_id'))
        camera = page.evaluate('window.banjoRoom.camera.position.toArray()')
        for a, b in zip(camera, view["character"]["pose"]["eyes_m"]): self.assertAlmostEqual(a, b, places=2)
        after = self.post("/api/world/inventory/shown", {"session": view["state"]["session"]}, world, viewer_token)
        self.assertEqual(before["record"], after["record"])
        self.assertGreaterEqual(sum(s['known'] for s in view['skills']),2)
        self.assertTrue(page.evaluate('document.querySelector("#watch-tech").textContent.includes("Gathering by hand")'))
        self.assertEqual("4 / 4 goals", page.evaluate('document.querySelector("#watch-progress").textContent').split(' · ')[0])
        # Inspection may read native geometry while watching, but does not
        # permit controls or change either character's physical state.
        session_id = view["state"]["session"]
        native_before = self.post("/api/live/act", {"session":session_id, "op":"poses"}, world)
        page.evaluate('(()=>{const r=banjoRoom,n=[...r.world.bodies].find(([n,e])=>e.mechanicalModel!=="precise-rigid-v1")?.[0];r.pick(n)})()')
        wait_for('banjoRoom.reveal()?.kind === "cells"')
        native_after = self.post("/api/live/act", {"session":session_id, "op":"poses"}, world)
        for key in ("t", "bodies", "machines"):
            self.assertEqual(native_before[key], native_after[key], "watch inspection changed " + key)
        page.evaluate('banjoRoom.pick(null)')
        # Clear navigation/agent startup events. Watching renders and polls;
        # it never sends live controls, human pose updates or inventory writes.
        self.assertFalse([e for e in page.events if e.get("method") == "Runtime.exceptionThrown"])
        page.events.clear(); page.send("Input.dispatchKeyEvent", {"type":"keyDown", "key":"w", "code":"KeyW"})
        time.sleep(.6); page.send("Input.dispatchKeyEvent", {"type":"keyUp", "key":"w", "code":"KeyW"})
        urls = [e["params"]["request"]["url"] for e in page.events if e.get("method") == "Network.requestWillBeSent"]
        self.assertFalse([u for u in urls if "/api/live/act" in u or "/api/world/inventory" in u])
        self.assertFalse([e for e in page.events if e.get("method") == "Runtime.exceptionThrown"])
        out = ROOT / "build/ai-player"; out.mkdir(parents=True, exist_ok=True)
        import base64
        (out / "watching.png").write_bytes(base64.b64decode(page.send("Page.captureScreenshot")["data"]))
        page.evaluate('document.querySelector("#watch-return").click()')
        wait_for('!location.search.includes("watch=") && !!window.banjoRoom?.status().ready')
        self.assertEqual(viewer_id, page.evaluate('window.banjoRoom.status().player_id'))


if __name__ == "__main__": unittest.main()
