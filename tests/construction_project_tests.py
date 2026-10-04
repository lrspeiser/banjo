"""Ordinary owned Inventory/site/placement actions, peers, stale intent and restart."""
from copy import deepcopy
from contextlib import nullcontext
import json
import math
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest import mock
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'playground'),str(ROOT/'tests'),str(ROOT)]
import construction_projects as projects
import construction_prepare as prepare
import ai_player_tests as fixture
import placement_context_tests as preview_fixture
import placement


class Suggestions(unittest.TestCase):
    def test_bounded_read_only_search_skips_previous_and_never_promises_tipping_spots(self):
        live=preview_fixture.FakeLive()
        app=type('App',(),{})()
        app.live=live;app.room=type('Room',(),{'spec':{'interaction_points':[]}})()
        live.as_actor=lambda owner:nullcontext()
        before=deepcopy(live.session.state)
        first,_=projects.suggest(app,'owner','item',preview_fixture.PERSON)
        self.assertTrue(projects.usable(first))
        another,_=projects.suggest(app,'owner','item',preview_fixture.PERSON,first['target'])
        self.assertGreater(math.dist(first['target']['on'],another['target']['on']),.2)
        self.assertEqual(before,live.session.state)
        self.assertLessEqual(len(live.calls),20)
        for changed in ({'may_fall_over':True},{'supported_corners':2},{'fits':False}):
            self.assertFalse(projects.usable({**first,**changed}))
        with mock.patch.object(projects,'_native',return_value={'fits':False,'why':'Too steep'}):
            answer,reason=projects.suggest(app,'owner','item',preview_fixture.PERSON)
        self.assertIsNone(answer);self.assertEqual('Too steep',reason)


class Preparation(unittest.TestCase):
    """The patch is read from the ground as it is; nothing is invented."""
    def app(self,height,rock=-5.0,wet=0.0):
        app=type('App',(),{})()
        session=type('Session',(),{'id':'s','state':{'bodies':[]}})()
        def act(body):
            x,z=body['at']
            return {'survey':{'on_the_ground':True,'ground_m':height(x,z),'rock_top_m':rock,
                'surface':'soil','water':{'depth_m':wet}}}
        app.live=type('Live',(),{'session':session,'act':staticmethod(act)})()
        return app

    saved={'centre_m':[0.0,1.1],'ahead':[0.0,1.0],'size_m':[.7,.7]}

    def test_flat_ground_needs_nothing(self):
        got=prepare.read(self.app(lambda x,z:.8),self.saved)
        self.assertTrue(got['done']);self.assertEqual([],got['squares'])
        self.assertIn('level',prepare.instruction(got))

    def test_a_hump_marks_only_the_squares_above_the_lowest(self):
        got=prepare.read(self.app(lambda x,z:.8+(.12 if x>.1 else 0)),self.saved)
        self.assertFalse(got['done'])
        self.assertTrue(got['squares']);self.assertTrue(all(sq['at_m'][0]>.1 for sq in got['squares']))
        self.assertAlmostEqual(.12,max(sq['dig_m'] for sq in got['squares']),3)
        area=sum(sq['size_m'][0]*sq['size_m'][1] for sq in got['squares'])
        self.assertAlmostEqual(.12*area,got['dig_m3'],4)
        self.assertNotIn('why',got);self.assertIn('Dig the',prepare.instruction(got))

    def test_hillside_rock_and_water_are_said(self):
        steep=prepare.read(self.app(lambda x,z:.8+z),self.saved)
        self.assertIn('too much to level by hand',steep['why'])
        rocky=prepare.read(self.app(lambda x,z:.8+(.1 if x>0 else 0),rock=.85),self.saved)
        self.assertIn('pick',rocky['why']);self.assertTrue(any(sq['rock'] for sq in rocky['squares']))
        wet=prepare.read(self.app(lambda x,z:.8+(.1 if x>0 else 0),wet=.2),self.saved)
        self.assertIn('water',wet['why'])

    def test_the_patch_is_bounded_and_sized_to_the_thing(self):
        big={**self.saved,'size_m':[9.0,9.0]}
        self.assertLessEqual(len(list(prepare.squares(big))),prepare.MOST_SQUARES)


@unittest.skipUnless(fixture.hub.RUNNER.is_file() and fixture.hub.ENGINE.is_file(),'native world engine not built')
class PlacementJourney(unittest.TestCase):
    setUp=fixture.AutonomousGuests.setUp
    tearDown=fixture.AutonomousGuests.tearDown
    start=fixture.AutonomousGuests.start
    stop=fixture.AutonomousGuests.stop
    get=fixture.AutonomousGuests.get
    def post(self,*args,**kwargs):
        try:return fixture.AutonomousGuests.post(self,*args,**kwargs)
        except urllib.error.HTTPError as error:
            error.msg+=': '+error.read().decode('utf-8')
            raise
    join=fixture.AutonomousGuests.join
    setup_world=fixture.AutonomousGuests.setup_world

    def write(self,world,action,**fields):
        view=self.post('/api/world/construction',{},world)
        return self.post('/api/world/construction',{'action':action,'revision':view['revision'],
            'request_id':action+'-'+str(view['revision']),**fields},world)

    def take_lamp(self,world,app,*,stow=False):
        import inventory_room
        sid=app.live.session.id
        body=next(b for b in app.live.session.state['bodies'] if b['name']=='camp light')
        x,_,z=body['position_m'];x-=.75
        y=self.post('/api/live/act',{'session':sid,'op':'survey','at':[x,z]},world)['survey']['ground_m']
        person={'standing_m':[x,y,z],'eyes_m':[x,y+1.62,z],'facing':[1,0,0]}
        thing=inventory_room.item_holding(app,'camp light')
        reply=self.post('/api/world/inventory',{'session':sid,'request':'take-light',
            'op':'take' if stow else 'take_up','item':thing['id'],'person':person},world)
        self.assertTrue(reply['ok'],reply)
        return thing['id'],person

    def test_private_selection_exact_retries_stale_revision_and_full_restart(self):
        world,owner,app=self.setup_world();peer=self.join(world,'Builder B')
        item,person=self.take_lamp(world,app,stow=True)
        before=self.post('/api/world/inventory/shown',{'session':app.live.session.id},world)
        select={'action':'select','item':item,'revision':0,'request_id':'lost-select'}
        accepted=self.post('/api/world/construction',select,world)
        self.assertEqual(accepted,self.post('/api/world/construction',{**select,'person':person},world))
        self.assertEqual(before,self.post('/api/world/inventory/shown',{'session':app.live.session.id},world))
        view=self.post('/api/world/construction',{},world)
        self.assertEqual('Equip',view['project']['status'])
        self.assertIsNone(self.post('/api/world/construction',{},world,peer['token'])['project'])
        for bad in ({**select,'request_id':'other','revision':0},
                    {**select,'item':'not-mine'},
                    {**select,'owner':owner['id']},
                    {**select,'target':{'on':[0,0,0]}}):
            with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/construction',bad,world)
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/world/construction',select,world,peer['token'])
        human=self.post('/api/world/guidance',{},world)
        observed=app.ai_players._observe({**owner,'ai':{'memory':{}}},'')
        self.assertEqual(human['construction_project'],observed['construction_project'])
        self.assertIsNone(human['goal']);self.assertEqual(item,human['next_action']['destination']['place'])
        with urllib.request.urlopen(self.base+'/construction_ui.js',timeout=5) as static:
            self.assertIn('export function constructionControls',static.read().decode())
        self.stop();self.start();self.players={world:owner}
        self.post('/api/world/player/join',{'token':owner['token']},world)
        self.post('/api/world/open',{},world)
        restored=self.post('/api/world/construction',{},world)
        self.assertEqual(view['project'],restored['project']);self.assertEqual(view['revision'],restored['revision'])
        self.assertEqual(accepted,self.post('/api/world/construction',select,world))
        cleared=self.write(world,'clear')
        self.assertIsNone(cleared['project']);self.assertIsNone(self.post('/api/world/construction',{},world)['project'])

    def test_native_site_another_location_movement_and_explicit_refusal_keep_the_item(self):
        world,owner,app=self.setup_world();item,person=self.take_lamp(world,app)
        self.write(world,'select',item=item)
        source=deepcopy(app.live.session.state)
        first=self.write(world,'suggest',person=person)
        self.assertTrue(first['project']['target'],first)
        # Preview reads do not step or reposition the world.
        self.assertEqual(source,app.live.session.state)
        project=self.post('/api/world/construction',{'person':person},world)['project']
        self.assertEqual('Place',project['status']);self.assertTrue(project['site']['fits'])
        another=self.write(world,'suggest',person=person)
        self.assertGreater(math.dist(first['project']['target']['on'],another['project']['target']['on']),.2)
        away=deepcopy(person);away['standing_m'][0]-=6;away['eyes_m'][0]-=6
        changed=self.post('/api/world/construction',{'person':away},world)
        self.assertEqual('Site changed',changed['project']['status'])
        self.assertIn('reach',changed['project']['blocker'])
        target=another['project']['target'];sid=app.live.session.id
        with mock.patch.object(placement,'execute',return_value=('', 'the destination became occupied')), \
             mock.patch.object(fixture.server,'run_action',side_effect=AssertionError('Must not silently drop elsewhere')):
            refused=self.post('/api/world/putdown',{'session':sid,'object':'camp light',
                'person':person,'placement_target':target},world)
        self.assertFalse(refused['ok']);self.assertIn('occupied',refused['why'])
        self.assertEqual('camp light',app.live.session.state['player_hands'][owner['id']]['holding'])

    def test_no_spot_marks_ground_to_dig_and_digging_it_clears_the_step(self):
        world,owner,app=self.setup_world();item,person=self.take_lamp(world,app)
        sid=app.live.session.id
        self.write(world,'select',item=item)
        # A hump of earth where the lamp would go, as a player's own heap of
        # earth dug from behind them: ground does not come from nowhere.
        bx,bz=person['standing_m'][0]-2.5,person['standing_m'][2]
        carried=self.post('/api/live/act',{'session':sid,'op':'dig','from':[bx,bz],'to':[bx,bz],'width_m':.6,'depth_m':.2},world)['carried']
        cx,cz=person['standing_m'][0]+prepare.AHEAD_M,person['standing_m'][2]
        self.post('/api/live/act',{'session':sid,'op':'deposit','at':[cx+.15,cz],'radius_m':.3,
            'soil_m3':carried.get('soil_m3',0),'sand_m3':carried.get('sand_m3',0),'from_carried':True},world)
        with mock.patch.object(projects,'suggest',return_value=(None,'No supported spot within reach. Move or prepare the ground.')):
            asked=self.write(world,'suggest',person=person)
        self.assertFalse(asked['site_found']);self.assertTrue(asked['preparing'])
        self.assertEqual([cx,cz],[round(v,4) for v in asked['project']['prepare']['centre_m']])
        view=self.post('/api/world/construction',{'person':person},world)['project']
        self.assertEqual('Prepare ground',view['status'],view.get('preparation'))
        self.assertEqual(['prepare','hold','site','place','inspect'],[s['id'] for s in view['steps']])
        self.assertEqual('current',view['steps'][0]['status'])
        # Each saved step says where it is done, to pick it up from there.
        self.assertEqual({'screen':'inventory','place':item},view['steps'][1]['destination'])
        self.assertEqual('world',view['steps'][0]['destination']['screen'])
        ground=view['preparation'];self.assertTrue(ground['squares']);self.assertIn('Dig the',ground['instruction'])
        guide=self.post('/api/world/guidance',{},world)
        self.assertEqual('Check the ground again',guide['next_action']['label'])
        # Reading changes nothing in the world.
        self.assertEqual(ground,self.post('/api/world/construction',{'person':person},world)['project']['preparation'])
        # Asking again while still digging keeps the same patch.
        with mock.patch.object(projects,'suggest',return_value=(None,'still no spot')):
            again=self.write(world,'suggest',person=person)
        self.assertEqual(asked['project']['prepare'],again['project']['prepare'])
        # Dig each marked square down by what it says, as a shovel would.
        dug=0.0
        for _ in range(4):
            marked=self.post('/api/world/construction',{'person':person},world)['project'].get('preparation')
            if not marked or marked['done']:break
            for sq in marked['squares']:
                at=[sq['at_m'][0],sq['at_m'][2]]
                got=self.post('/api/live/act',{'session':sid,'op':'dig','from':at,'to':at,
                    'width_m':sq['size_m'][0],'depth_m':sq['dig_m']},world)
                dug+=1
        done=self.post('/api/world/construction',{'person':person},world)['project']
        self.assertTrue(done['preparation']['done'],done['preparation'])
        self.assertEqual('Choose site',done['status'])
        self.assertEqual('done',done['steps'][0]['status'])
        # The native trial still decides the spot; the step is then kept done.
        found=self.write(world,'suggest',person=person)
        self.assertTrue(found['project']['target'],found)
        self.assertNotIn('prepare',found['project']);self.assertTrue(found['project']['prepared'])
        self.assertEqual('done',self.post('/api/world/construction',{'person':person},world)['project']['steps'][0]['status'])

    def test_a_thing_on_its_support_fastens_rated_by_its_contact_and_keeps_through_a_restart(self):
        import construction_mount
        from mcp import engine_materials
        world,owner,app=self.setup_world()
        # The smelter stands on its own foundation pad: a real support.
        rated=construction_mount.rating(app,'smelter','smelter foundation')
        self.assertGreater(rated['area_m2'],.1)
        # The weaker material's own strength over the contact, as a bonded joint.
        weaker=engine_materials.mechanics(rated['governed_by'])
        self.assertAlmostEqual(rated['area_m2']*weaker['tensile_strength_pa'],rated['holds_tension_n'],delta=1e-3)
        self.assertAlmostEqual(rated['area_m2']*weaker['shear_strength_pa'],rated['holds_shear_n'],delta=1e-3)
        self.assertGreater(rated['holds_shear_n'],0)
        # Not standing on it: refused, nothing joined.
        with self.assertRaisesRegex(ValueError,'not standing on'):construction_mount.rating(app,'camp light','smelter foundation')
        joints_before=len(app.live.session.state.get('joints') or [])
        fastened=construction_mount.fasten(app,'smelter','smelter foundation')
        self.post('/api/live/act',{'session':app.live.session.id,'op':'step','dt':1/240,'n':8},world)
        self.assertTrue(construction_mount.holding(app,fastened))
        self.assertEqual(joints_before+1,len(app.live.session.state.get('joints') or []))
        # Saved with the room and back after a restart, with its rating.
        self.assertTrue(fixture.server.keep_world(app,'fastening test'))
        self.stop();self.start();self.players={world:owner}
        self.post('/api/world/player/join',{'token':owner['token']},world)
        self.post('/api/world/open',{},world)
        app=self.app.hub.get(world)
        joint=next(j for j in app.live.session.state['joints'] if {j['a'],j['b']}=={'smelter','smelter foundation'})
        self.assertTrue(joint.get('attached',True))
        construction_mount.unfasten(app,{**fastened,'joint':joint['id']})
        self.post('/api/live/act',{'session':app.live.session.id,'op':'step','dt':1/240,'n':4},world)
        self.assertFalse(construction_mount.holding(app,{**fastened,'joint':joint['id']}))

    def test_an_item_on_bare_ground_has_nothing_to_fasten_to(self):
        world,owner,app=self.setup_world();item,person=self.take_lamp(world,app)
        self.write(world,'select',item=item)
        found=self.write(world,'suggest',person=person)
        project=self.post('/api/world/construction',{'person':person},world)['project']
        self.assertNotIn('fasten',[s['id'] for s in project['steps']])
        with self.assertRaises(urllib.error.HTTPError):self.write(world,'fasten',person=person)

    def test_native_place_and_resume_on_both_surfaces(self):
        reports=[]
        for surface in ('smooth','columns'):
            world,owner,app=self.setup_world(surface=surface);item,person=self.take_lamp(world,app)
            self.write(world,'select',item=item)
            found=self.write(world,'suggest',person=person)
            self.assertTrue(found['project']['target'],found)
            ready=self.post('/api/world/construction',{'person':person},world)['project']
            sid=app.live.session.id;stop=threading.Event();errors=[]
            def tick():
                try:
                    while not stop.is_set():
                        self.post('/api/live/act',{'session':sid,'op':'step','dt':1/240,'n':8},world)
                        stop.wait(.01)
                except Exception as error:errors.append(str(error))
            worker=threading.Thread(target=tick);worker.start()
            began=time.monotonic()
            try:
                done=self.post('/api/world/putdown',{'session':sid,'object':'camp light',
                    'person':person,'placement_target':ready['site']['target']},world)
            finally:stop.set();worker.join(5)
            self.assertFalse(errors);self.assertTrue(done['ok'],done)
            placed=self.post('/api/world/construction',{'person':person},world)
            self.assertEqual('Placed',placed['project']['status'])
            self.assertEqual(['done','done','done','current'],[s['status'] for s in placed['project']['steps']])
            self.assertEqual('View components and use',placed['project']['steps'][-1]['label'])
            use=placed['project']['operation']
            self.assertEqual('Automatic at night',use['mode'])
            self.assertIn('switches on at night',use['instruction'])
            with self.assertRaises(urllib.error.HTTPError):
                away=deepcopy(person);away['eyes_m'][0]-=20;away['standing_m'][0]-=20
                self.write(world,'inspect',person=away)
            journal=fixture.server.journal_of(app,owner['id'])
            self.assertNotIn('setting-out',journal.knows())
            inspected=self.write(world,'inspect',person=person)
            self.assertTrue(inspected['project']['inspected'])
            # The engine found it standing where it was set: that is the
            # evidence for Setting things down, and looking again adds none.
            self.assertEqual(['setting-out'],inspected['project'].get('learned'))
            self.assertIn('setting-out',fixture.server.journal_of(app,owner['id']).knows())
            shown=[e for e in fixture.server.journal_of(app,owner['id']).data['evidence'].values()
                   if e['test']=='stands-where-set']
            self.assertEqual(1,len(shown));self.assertTrue(shown[0]['passes'])
            self.assertLess(shown[0]['result']['tilt_deg'],10)
            placed=self.post('/api/world/construction',{'person':person},world)
            self.assertEqual('done',placed['project']['steps'][-1]['status'])
            self.assertFalse(app.live.session.state['player_hands'][owner['id']]['holding'])
            self.assertTrue(fixture.server.keep_world(app,'placement test checkpoint'))
            reports.append({'surface':surface,'world':world,'owner':owner,'project':placed,
                'native_body':deepcopy(next(b for b in app.live.session.state['bodies'] if b['name']=='camp light')),
                'wall_s':round(time.monotonic()-began,3)})
        self.stop();self.start();self.players={r['world']:r['owner'] for r in reports}
        for r in reports:
            self.post('/api/world/player/join',{'token':r['owner']['token']},r['world'])
            self.post('/api/world/open',{},r['world'])
            resumed=self.post('/api/world/construction',{},r['world'])
            self.assertEqual(r['project']['project'],resumed['project'])
            self.assertEqual(r['project']['revision'],resumed['revision'])
            app=self.app.hub.get(r['world'])
            native=next(b for b in app.live.session.state['bodies'] if b['name']=='camp light')
            self.assertEqual(r['native_body'],native)
        report=ROOT/'build'/'construction'/'placement-journey.json';report.parent.mkdir(parents=True,exist_ok=True)
        # Do not write private player tokens even to the ignored report.
        report.write_text(json.dumps([{k:v for k,v in r.items() if k!='owner'} for r in reports],indent=2),encoding='utf-8')

    def test_legacy_lamp_reopens_exact_components_without_inventing_source_for_a_changed_body(self):
        import workshop_install
        from mcp import workshop_components
        world,owner,app=self.setup_world()
        item,person=self.take_lamp(world,app,stow=True)
        # Simulate the owner's older world, created before lamp provenance was
        # retained. The physical declaration and native state are unchanged.
        app.room.workshop_installs=[r for r in app.room.workshop_installs if r.get('root_body')!='camp light']
        before=deepcopy(app.live.session.state)
        inv=self.post('/api/workshop/inventory',{},world)
        carried=next(t for t in inv['carried'] if t['id']==item)
        self.assertEqual('mine-lamp',carried['design_id'])
        source=self.post('/api/world/workshop/what_made',{'body':'camp light'},world)
        design,_=workshop_components.design_from_spec(source['recipe'])
        self.assertEqual(['foot','globe bracket','globe'],[p.name for p in design.parts])
        self.assertEqual(['iron','iron','glass'],[p.material for p in design.parts])
        reopened=self.post('/api/workshop/candidates',{**source['recipe'],'sweeps':{}},world)
        self.assertEqual('mine-lamp',reopened['kind'])
        self.assertEqual(before,app.live.session.state)
        # Renaming the body still recovers geometry; changing one dimension
        # cannot pass by retaining the old name.
        physical=next(b for b in app.room.spec['precise_rigid_bodies'] if b['name']=='camp light')
        original=deepcopy(physical)
        physical['name']='renamed fitting'
        self.assertTrue(any('renamed fitting' in r['bodies'] for r in workshop_install.made_here(app)))
        physical['name']='camp light';physical['parts'][0]['dimensions_m'][0]*=1.1
        self.assertFalse(any('camp light' in r['bodies'] for r in workshop_install.made_here(app)))
        physical.clear();physical.update(original)

    def test_generation_reseeds_declined_starter_sites_before_saving_a_world(self):
        sys.path.insert(0,str(ROOT/'tools'))
        import build_new_world
        original=build_new_world.compose
        attempts=[]
        def first_declined(*args,**kwargs):
            attempts.append(args[1]['proof']['seed'])
            if len(attempts)==1:raise ValueError('No dry placement keeps smelter clear')
            return original(*args,**kwargs)
        with mock.patch.object(build_new_world,'compose',side_effect=first_declined):
            created=self.post('/api/worlds',{'name':'Checked sites','surface':'columns'})
        self.assertGreaterEqual(len(attempts),2);self.assertLessEqual(len(attempts),6)
        self.assertNotEqual(attempts[0],created['goods_seed'])
        worlds_before=set(self.app.hub.folder.iterdir())
        with mock.patch.object(build_new_world,'compose',side_effect=ValueError('No dry placement')) as compose:
            with self.assertRaises(urllib.error.HTTPError):self.post('/api/worlds',{'name':'Must not be saved'})
        self.assertLessEqual(compose.call_count,6);self.assertGreater(compose.call_count,0)
        self.assertEqual(worlds_before,set(self.app.hub.folder.iterdir()))


if __name__=='__main__':unittest.main()
