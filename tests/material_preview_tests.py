"""Material candidates and actual player collection agree; inspection grants nothing."""
from copy import deepcopy
from contextlib import contextmanager, nullcontext
import base64
import json
import math
import os
from pathlib import Path
import sys
import struct
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'playground'),str(ROOT/'mcp'),str(ROOT/'tests'),str(ROOT)]
import ai_player_tests as fixture
import interaction_profiles
import resource_previews
import qa_browser
import tool_use
import tool_use_tests as controls
import world_goods_tests as goods
import player_world


class TerrainDelivery(unittest.TestCase):
    def test_independent_acknowledgements_retry_and_private_accounts(self):
        view=player_world.TerrainView();reads=[]
        live=SimpleNamespace(session=SimpleNamespace(id='native-1'),checkpoint=nullcontext)
        def read(request):
            reads.append(request)
            reply={'terrain':{'grid':{'nx':2},'runs_b64':'native runs','carried':{'sand_kg':12}}}
            view.observe(live.session,reply)
            return reply
        live.act=read
        first={};view.attach(live,None,first)
        self.assertNotIn('carried',first['terrain']);self.assertEqual(1,len(reads))
        first['terrain']['grid']['nx']=999
        retry={};view.attach(live,None,retry)
        self.assertEqual(2,retry['terrain']['grid']['nx']);self.assertEqual(1,len(reads))
        quiet={};view.attach(live,retry['terrain_version'],quiet)
        self.assertNotIn('terrain',quiet)
        view.observe(live.session,{'terrain':{**view.geometry,'carried':{'soil_kg':99}}})
        still_quiet={};view.attach(live,retry['terrain_version'],still_quiet)
        self.assertNotIn('terrain',still_quiet,'An unchanged full read or private load must not repaint terrain')
        # Another caller/clock consumed the changed rectangle. Both viewers
        # must independently catch up, without a growing history or user map.
        view.observe(live.session,{'terrain_changed':{'box':[0,0,1,1]}})
        a={};view.attach(live,retry['terrain_version'],a)
        b={};view.attach(live,retry['terrain_version'],b)
        self.assertEqual(a,b);self.assertEqual(2,len(reads))
        self.assertNotIn('carried',b['terrain'])
        live.session=SimpleNamespace(id='native-2')
        changed={};view.attach(live,b['terrain_version'],changed)
        self.assertEqual('native-2',changed['terrain_version']['session']);self.assertEqual(3,len(reads))

    def test_pose_replies_do_not_invalidate_and_client_cursors_have_no_state_authority(self):
        view=player_world.TerrainView();session=SimpleNamespace(id='s')
        view.observe(session,{'terrain_changed':{'box':[0,0,1,1]}})
        stamp=(view.session,view.revision)
        view.observe(session,{'bodies':[],'carried':{'sand_kg':4}})
        self.assertEqual(stamp,(view.session,view.revision))
        for bad in ({'session':'s','revision':True},{'session':'s','revision':-1},
                    {'session':'s','revision':2**53},{'session':'s','revision':0,'stock':5},'s'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):view.validate(bad)
        view.validate(None);view.validate({'session':'s','revision':0})

    def test_capture_and_native_reply_keep_the_same_lock_order(self):
        view=player_world.TerrainView();native=threading.RLock()
        held=threading.Event();attempt=threading.Event();listen=threading.Event()
        replied=threading.Event();captured=threading.Event();errors=[]
        session=SimpleNamespace(id='concurrent-native')
        @contextmanager
        def checkpoint():
            attempt.set()
            with native:yield
        def read(request):
            attempt.set()
            with native:
                reply={'terrain':{'grid':{'nx':2},'runs_b64':'latest'}}
                view.observe(session,reply)
                return reply
        live=SimpleNamespace(session=session,checkpoint=checkpoint,act=read)
        def native_reply():
            with native:
                held.set();listen.wait(2)
                view.observe(session,{'terrain_changed':{'box':[0,0,1,1]}})
                replied.set()
        answer={}
        def capture():
            try:view.attach(live,None,answer);captured.set()
            except Exception as exc:errors.append(exc)
        sender=threading.Thread(target=native_reply,daemon=True)
        viewer=threading.Thread(target=capture,daemon=True)
        sender.start();self.assertTrue(held.wait(2));viewer.start()
        self.assertTrue(attempt.wait(2));listen.set()
        self.assertTrue(replied.wait(2),'A native listener must not wait behind a blocked capture')
        self.assertTrue(captured.wait(2));sender.join(1);viewer.join(1)
        self.assertEqual([],errors);self.assertEqual('latest',answer['terrain']['runs_b64'])


class Candidates(unittest.TestCase):
    def test_only_native_loose_layers_are_candidates(self):
        use=interaction_profiles.tool_use(controls.PICK)
        for surface in ('soil','sand','rock','copper ore','concrete'):
            with self.subTest(surface=surface):
                answer=resource_previews.ground_tool({'on_the_ground':True,'surface':surface},use)
                self.assertEqual([surface] if surface in ('soil','sand') else [],answer['materials'])
                self.assertNotIn('kg',answer)

    def test_wet_ground_absent_ground_and_no_pry_do_not_promise_material(self):
        use=interaction_profiles.tool_use(controls.PICK)
        for survey,profile in (({'on_the_ground':True,'surface':'soil','water':{'depth_m':.2}},use),
                               ({'on_the_ground':False,'surface':'soil'},use),
                               ({'on_the_ground':True,'surface':'soil'},{**use,'lever':None})):
            self.assertEqual([],resource_previews.ground_tool(survey,profile)['materials'])

    def test_thin_sand_can_reveal_soil_but_never_ledger_ore(self):
        use=interaction_profiles.tool_use(controls.PICK)
        survey={'on_the_ground':True,'surface':'sand','sand_m':.04,'soil_m':.8}
        self.assertEqual(['sand','soil'],resource_previews.ground_tool(survey,use,.2)['materials'])
        self.assertEqual(['sand'],resource_previews.ground_tool({**survey,'sand_m':.5},use,.2)['materials'])

    def test_thin_film_and_loose_mixture_follow_actual_runs_not_coarse_contact_kind(self):
        use=interaction_profiles.tool_use(controls.PICK)
        film={'on_the_ground':True,'surface':'soil','sand_m':.005,'soil_m':1,
              'runs':[{'material':'soil'},{'material':'sand'}]}
        self.assertEqual(['sand','soil'],resource_previews.ground_tool(film,use)['materials'])
        # Loose sand/soil is one proportional native mixture, not ordered beds.
        mixed={**film,'surface':'sand','sand_m':.15,'loose_soil_m':.25,
               'runs':[{'material':'soil'},{'material':'loose soil'}]}
        self.assertEqual(['soil','sand'],resource_previews.ground_tool(mixed,use)['materials'])
        for material in ('rock','clay','ore','oxidised ore'):
            buried={**film,'runs':[{'material':'soil'},{'material':material}]}
            self.assertEqual([],resource_previews.ground_tool(buried,use)['materials'])

    def test_custom_tools_share_readonly_preview_without_receipts_or_inventory_changes(self):
        app=controls.app_with()
        app.room.spec['interactions'][0]['object']='LLM custom spade'
        before=deepcopy(app.live.session.state)
        for _ in range(3):
            answer=tool_use.resolve(app,{'person':controls.PERSON,'at_m':controls.IN_REACH})
            self.assertEqual(['sand'],answer['gather']['materials'])
        self.assertEqual(before,app.live.session.state)
        self.assertFalse(set(app.live.asked)&{'stroke','strike','dig'})


@unittest.skipUnless(fixture.hub.RUNNER.is_file() and fixture.hub.ENGINE.is_file(),'native engines required')
class PlayerMaterials(unittest.TestCase):
    batch,process_batch,personal=goods.GoodsJourney.batch,goods.GoodsJourney.process_batch,goods.GoodsJourney.personal
    get,post,join=fixture.AutonomousGuests.get,fixture.AutonomousGuests.post,fixture.AutonomousGuests.join
    setUp,start,stop,tearDown,setup_world=(fixture.AutonomousGuests.setUp,fixture.AutonomousGuests.start,
        fixture.AutonomousGuests.stop,fixture.AutonomousGuests.tearDown,fixture.AutonomousGuests.setup_world)

    def test_column_surface_exposes_soil_and_private_storage_peer_restart_agree(self):
        self.surface='columns'
        self.test_actual_tool_exposes_soil_and_private_storage_peer_restart_agree()

    def test_cut_surface_exposes_soil_and_private_storage_peer_restart_agree(self):
        self.surface='cuts';self.contact_distance=.45
        self.test_actual_tool_exposes_soil_and_private_storage_peer_restart_agree()

    def test_close_contact_exposes_soil_and_private_storage_peer_restart_agree(self):
        self.contact_distance=.45
        self.test_actual_tool_exposes_soil_and_private_storage_peer_restart_agree()

    def test_close_column_contact_exposes_soil_and_private_storage_peer_restart_agree(self):
        self.surface='columns';self.contact_distance=.45
        self.test_actual_tool_exposes_soil_and_private_storage_peer_restart_agree()

    def test_actual_tool_exposes_soil_and_private_storage_peer_restart_agree(self):
        import starter_goals_tests as camp
        with mock.patch.object(fixture.server.secrets,'randbelow',side_effect=[1,851269741]):
            world,owner,app=self.setup_world(surface=getattr(self,'surface','smooth'))
        self.assertEqual(getattr(self,'surface','smooth'),app.room.spec['terrain'].get('surface','smooth'))
        peer=self.join(world,'Layer observer');token=owner['token']
        sid=app.live.session.id
        # Isolate pick extraction from the independently running ore rover.
        for program in app.live.session.state['machines']['programs']:
            self.post('/api/world/machine',{'session':sid,'program':program['id'],'power':False,
                'sender':'layer-comparison','seq':1},world)
        first=self.post('/api/workshop/goals',{},world)
        pile=app.brains.goods.by_name(first['goals'][0]['guide']['resource']);at=pile['at_m']
        floor=self.post('/api/live/act',{'session':sid,'op':'survey','at':at},world)['survey']['ground_m']
        self.post('/api/world/goods/collect',{'session':sid,'pile':pile['name'],'request_id':'layer-wood',
            'person':{'eyes_m':[at[0],floor+1.62,at[1]],'facing':[1,0,0]}},world)
        built=camp.make_paid(self,world,token,first['recipe'],[-1.4,-.6],'layer-pick')
        self.assertTrue(built['resources_charged']);root=built['root_body']
        sid=app.live.session.id;target=[.3,.025];x,z=target[0]-getattr(self,'contact_distance',1.2),.025
        floor=self.post('/api/live/act',{'session':sid,'op':'survey','at':[x,z]},world)['survey']['ground_m']
        person={'standing_m':[x,floor,z],'eyes_m':[x,floor+1.62,z],'facing':[1,0,0]}
        self.assertTrue(self.post('/api/world/inventory',{'session':sid,'op':'take_up','item':root,
            'request':'layer-equip','person':person},world)['ok'])
        def survey(player=None):
            return self.post('/api/live/act',{'session':sid,'op':'survey','at':target},world,player)['survey']
        def inventory(player=None):return self.post('/api/workshop/inventory',{},world,player)
        before=survey();self.assertEqual('sand',before['runs'][-1]['material'])
        frame=self.post('/api/live/act',{'session':sid,'op':'step','dt':1/240,'n':1},world,peer['token'])
        peer_version=frame.get('terrain_version')
        self.assertEqual(getattr(self,'surface','smooth'),frame['terrain']['surface'])
        reserves=deepcopy(app.brains.goods.holders()['deposits'])
        reports=[];stored=[];saw_film=False;totals={'sand':0.,'soil':0.}
        for n in range(40):
            current=survey();self.assertEqual(current,survey(peer['token']))
            point=[target[0],current['ground_m'],target[1]]
            person['look_direction']=[point[0]-x,point[1]-floor-1.62,point[2]-z]
            preview=self.post('/api/world/tool',{'session':sid,'person':person,'at_m':point},world)
            self.assertTrue(preview['enabled'],preview)
            candidates=preview['gather']['materials']
            self.assertTrue(preview['feedback']['ready'],preview['feedback'])
            self.assertEqual(candidates,preview['feedback']['materials'])
            self.assertEqual(current['runs'][-1]['material'],preview['target']['material'])
            if current['surface']=='soil' and current['runs'][-1]['material']=='sand':
                saw_film=True;self.assertIn('sand',candidates)
            if current['runs'][-1]['material']=='soil':
                self.assertEqual(['soil'],candidates)
            load=inventory()['ground_load'];replies=[];errors=[]
            def use():
                try:replies.append(self.post('/api/world/tool/use',{'session':sid,'person':person,'at_m':point},world))
                except Exception as exc:errors.append(exc)
            worker=threading.Thread(target=use,daemon=True);worker.start();deadline=time.monotonic()+25
            while worker.is_alive() and time.monotonic()<deadline:
                app.clock._tick(.05);time.sleep(.015)
            worker.join(1);self.assertFalse(worker.is_alive());self.assertEqual([],errors)
            result=replies[0]['result'];self.assertGreater(result['loosened_kg'],0,replies[0])
            after=inventory()['ground_load']
            self.assertEqual(0,sum(after[s+'_kg'] for s in totals),'Output goes to piles, not a filling hand load')
            delta={s:sum(p['kg'] for p in replies[0].get('excavation_piles',[]) if p['material']==s) for s in totals}
            for s,kg in delta.items():
                if kg>1e-6:self.assertIn(s,candidates)
                totals[s]+=kg
            self.assertAlmostEqual(result['loosened_kg'],sum(delta.values()),delta=5e-5)
            peer_frame=self.post('/api/live/act',{'session':sid,'op':'step','dt':1/240,'n':1,
                'terrain_seen':peer_version},world,peer['token'])
            self.assertTrue('terrain' in peer_frame,'A peer must receive ground changes consumed by tool/clock replies')
            peer_version=peer_frame['terrain_version']
            block=peer_frame['terrain'];grid=block['grid']
            column=(math.floor((target[1]-grid['z0_m'])/grid['cell_m']+.5)*grid['nx']
                    +math.floor((target[0]-grid['x0_m'])/grid['cell_m']+.5))
            raw=base64.b64decode(block['runs_b64']);cursor=0
            for _ in range(column):cursor+=1+3*raw[cursor]
            top_kind=raw[cursor+1+3*(raw[cursor]-1)]
            exposed=survey()['runs'][-1]['material']
            self.assertEqual({'sand':2,'soil':1,'loose soil':3}[exposed],top_kind)
            center=[grid['x0_m']+(column%grid['nx'])*grid['cell_m'],
                    grid['z0_m']+(column//grid['nx'])*grid['cell_m']]
            measured=self.post('/api/live/act',{'session':sid,'op':'survey','at':center},world)['survey']['ground_m']
            height=struct.unpack_from('<f',base64.b64decode(block['heights_b64']),4*column)[0]
            self.assertAlmostEqual(measured,height,delta=1e-6)
            self.assertEqual(0,block.get('carried',{}).get('total_kg',0),
                'The shared geometry response can include only this peer\'s own carried load')
            self.assertEqual(0,inventory(peer['token'])['ground_load']['total_kg'])
            reports.append({'before':current,'candidates':candidates,'result':result,'collected_kg':delta,
                'peer_top_kind':top_kind,'peer_column_height_m':height,
                'peer_geometry_bytes':len(json.dumps(block,separators=(',',':')).encode())})
            if sum(totals.values())>55 or current['runs'][-1]['material']=='soil':
                for pile in app.brains.goods.stockpiles:
                    if not pile.get('excavated') or not pile['holds']:continue
                    at=pile['at_m'];h=self.post('/api/live/act',{'session':sid,'op':'survey','at':at},world)['survey']['ground_m']
                    request={'session':sid,'pile':pile['name'],'request_id':f'layer-collect-{n}-{pile["excavated"]}',
                        'person':{'eyes_m':[at[0],h+1.62,at[1]],'facing':[1,0,0]}}
                    stored.append(self.post('/api/world/goods/collect',request,world))
                    repeated=self.post('/api/world/goods/collect',request,world)
                    self.assertTrue(repeated['repeated'])
            print(f'layer stroke {n+1}: {current["surface"]}, sand={current["sand_m"]:.6f} m, {delta}',flush=True)
            if current['runs'][-1]['material']=='soil':break
        else:self.fail('Actual repeated tool work did not expose soil within 40 strokes')
        # On cube ground a swing takes a whole cube, film and all, so the thin
        # film over soil is cut through in one stroke and never seen alone.
        if getattr(self,'surface','smooth')!='columns':
            self.assertTrue(saw_film,'The run/coarse-contact boundary must actually be crossed')
        final=survey();own=inventory();other=inventory(peer['token'])
        self.assertEqual('soil',final['runs'][-1]['material'])
        self.assertEqual([],other['stored_ground']);self.assertEqual(0,other['ground_load']['total_kg'])
        self.assertEqual(reserves,app.brains.goods.holders()['deposits'],'Pick work must not consume ledger ore')
        for s,total in totals.items():
            received=self.personal(app,owner).get(s,0)
            self.assertAlmostEqual(total,received,delta=5e-5)
        self.assertTrue(fixture.server.keep_world(app,'save real exposed-layer acceptance'))
        self.stop();self.start();self.post('/api/world/open',{},world);app=self.app.hub.get(world);sid=app.live.session.id
        self.assertEqual(getattr(self,'surface','smooth'),app.room.spec['terrain'].get('surface','smooth'))
        self.assertEqual(final,survey());self.assertEqual(final,survey(peer['token']))
        self.assertEqual(own['stored_ground'],inventory()['stored_ground'])
        for s,total in totals.items():self.assertAlmostEqual(total,self.personal(app,owner).get(s,0),delta=5e-5)
        self.assertEqual(other['stored_ground'],inventory(peer['token'])['stored_ground'])
        reopened=self.post('/api/live/act',{'session':sid,'op':'step','dt':1/240,'n':1,
            'terrain_seen':peer_version},world,peer['token'])
        for key in ('heights_b64','ground_b64','runs_b64'):
            self.assertTrue(peer_frame['terrain'][key]==reopened['terrain'][key],key+' changed across restart')
        output=ROOT/'build/material-readability';output.mkdir(parents=True,exist_ok=True)
        suffix='-columns' if getattr(self,'surface','smooth')=='columns' else ''
        (output/f'layer-acceptance{suffix}.json').write_text(json.dumps({'terrain_seed':7,'terrain_cell_m':.25,
            'surface':getattr(self,'surface','smooth'),
            'manufacture_cell_m':.05,'dt_s':1/240,'strokes':reports,'stored':own['stored_ground'],
            'final':final,'restart_retained':True,'peer_credited_kg':0,'ore_reserve_unchanged':True},indent=2),encoding='utf-8')

    def test_output_thumbnail_collect_button_credits_only_actual_personal_goods(self):
        if not qa_browser.CHROME.is_file():
            if os.environ.get('BANJO_BROWSER_TESTS')=='required':self.fail('Chrome required')
            self.skipTest('Chrome not installed')
        ident,owner,app,source,pile,person=self.batch()
        expected=deepcopy(pile['holds'])
        chrome=qa_browser.Chrome(1280,800);self.addCleanup(chrome.close)
        page=chrome.page;page.send('Page.enable');page.send('Runtime.enable')
        def wait(expression):
            until=time.monotonic()+25
            while time.monotonic()<until:
                if page.evaluate('Boolean('+expression+')'):return
                time.sleep(.04)
            self.fail(expression+'; '+str(page.evaluate('({card:document.querySelector("#material-preview")?.textContent,use:banjoRoom.use(),paused:banjoRoom.world.paused,acting:banjoRoom.world.acting,asking:banjoRoom.world.asking,focus:document.activeElement?.id})')))
        page.send('Page.navigate',{'url':self.base+f'/world?world={ident}'})
        wait('window.banjoRoom?.ready()')
        page.evaluate('window.dispatchEvent(new CustomEvent("banjo-movement-mode",{detail:"fly"}))')
        name=json.dumps(pile['name'])
        # Look at an actual material packet, rather than the empty space
        # between packets. These pictures carry ledger identity, not fake mass.
        page.evaluate(f'''(()=>{{const r=banjoRoom,g=r.scene.getObjectByName("resource-packets").children.find(c=>c.userData.resourcePile==={name});
          const m=g.children.find(c=>c.isInstancedMesh),T=m.instanceMatrix.array;
          const x=g.position.x+T[12],y=g.position.y+T[13],z=g.position.z+T[14];
          r.standAt(x,y+1.4,z+1.2);r.lookAt(x,y,z)}})()''')
        wait('document.querySelector("#material-preview [data-method=pile] button")?.textContent==="Collect"')
        self.assertEqual(expected,pile['holds'],'Preview must not collect in inspection flight')
        token=page.evaluate(f'localStorage.getItem("banjo.player.{ident}")')
        player=next(p for p in app.room.player_records.values() if p['token']==token)
        self.assertEqual({},self.personal(app,player))
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/'material-output-preview.png').write_bytes(base64.b64decode(page.send('Page.captureScreenshot',{'format':'png'})['data']))
        page.evaluate('document.querySelector("#material-preview [data-method=pile] button").click()')
        wait(f'!Object.keys(banjoRoom.world.goods.stockpiles.find(p=>p.name==={name}).holds_kg).length')
        self.assertEqual(expected,self.personal(app,player))
        self.assertEqual({},self.personal(app,owner),'Another player does not receive the collected goods')
        self.assertEqual({},pile['holds'])
        self.assertFalse([e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])

    def test_real_crosshair_thumbnails_pickup_and_native_soil_receipt_in_an_ore_area(self):
        if not qa_browser.CHROME.is_file():
            if os.environ.get('BANJO_BROWSER_TESTS')=='required':self.fail('Chrome required')
            self.skipTest('Chrome not installed')
        with mock.patch.object(fixture.server.secrets,'randbelow',side_effect=[0,1]):
            ident,owner,app=self.setup_world()
        # Explicit ledger-zone fixture at known native soil. A zone declares a
        # rover route; it does not change the native ground's material or law.
        deposit=next(d for d in app.brains.goods.deposits if d['substance']=='copper ore')
        deposit['at_m']=[.3,.025];deposit['radius_m']=1
        app.brains.of('rover').routine.places['vein']=[.3,.025]
        reserve=app.brains.goods.reserve_kg(deposit)
        chrome=qa_browser.Chrome(1280,800);self.addCleanup(chrome.close)
        page=chrome.page;page.send('Page.enable');page.send('Runtime.enable')
        def wait(expression):
            until=time.monotonic()+25
            while time.monotonic()<until:
                if page.evaluate('Boolean('+expression+')'):return
                time.sleep(.04)
            self.fail(expression+'; '+str(page.evaluate('document.querySelector("#material-preview")?.textContent')))
        def key(code,letter):
            for kind in ('keyDown','keyUp'):
                page.send('Input.dispatchKeyEvent',{'type':kind,'code':code,'key':letter,'windowsVirtualKeyCode':ord(letter.upper())})
        page.send('Page.navigate',{'url':self.base+f'/world?world={ident}'})
        wait('window.banjoRoom?.ready()')
        page.evaluate('(()=>{const r=banjoRoom,p=r.world.bodies.get("field pick").mesh.position;'
            'r.standAt(p.x,p.y+1.62,p.z+1.1);r.lookAt(p.x,p.y,p.z)})()')
        wait('document.querySelector("#material-preview [data-method=product] img")')
        self.assertIn('Whole item',page.evaluate('document.querySelector("#material-preview").textContent'))
        key('KeyE','e');wait('banjoRoom.held()?.name==="field pick" && banjoRoom.use().mode==="tool-ready"')
        page.evaluate('banjoRoom.standAt(-.9,banjoRoom.groundAt(-.9,.025)+1.62,.025);'
            'banjoRoom.lookAt(.3,banjoRoom.groundAt(.3,.025),.025)')
        wait('document.querySelector("#material-preview [data-method=dig] canvas") && document.querySelector("#material-preview [data-method=ore] canvas")')
        # The ground under the crosshair is listed once: as the surface row,
        # marked "Possible yield" when the native tool can loosen it, and any
        # deeper candidate the stroke may reach as a separate dig row.
        materials=page.evaluate('''[...document.querySelectorAll("#material-preview [data-method=dig],#material-preview [data-method=surface]")]
          .filter(e=>e.dataset.method==="dig" || e.textContent.includes("Possible yield")).map(e=>e.dataset.material)''')
        self.assertTrue(materials)
        self.assertTrue(set(materials)<= {'soil','sand'})
        self.assertEqual('Mining rover',page.evaluate('document.querySelector("#material-preview [data-method=ore] small").textContent'))
        self.assertTrue(page.evaluate('document.querySelector("#label").hidden'))
        self.assertEqual(0,page.evaluate('(()=>{let n=0;banjoRoom.scene.getObjectByName("resource-packets").traverse(o=>{if(o.isSprite||o.userData.resourceDeposit)n++});return n})()'))
        before=page.evaluate('banjoRoom.world.carriedGround || {}')
        self.assertEqual(0,sum(before.get(k,0) for k in ('soil_kg','sand_kg')))
        self.assertEqual(reserve,app.brains.goods.reserve_kg(deposit))
        position=page.evaluate('banjoRoom.camera.position.toArray()')
        page.evaluate('document.querySelector("#material-preview details button").click()')
        self.assertEqual(position,page.evaluate('banjoRoom.camera.position.toArray()'),'Look changes direction, not player location')
        page.evaluate('banjoRoom.lookAt(.3,banjoRoom.groundAt(.3,.025),.025)')
        wait('document.querySelector("#material-preview [data-method=ore] button")')
        page.evaluate('document.querySelector("#material-preview [data-method=ore] button").click()')
        wait('!document.querySelector("#machine-panel").hidden')
        page.evaluate('document.querySelector("#mp-close").click()')
        wait('banjoRoom.use().mode==="tool-ready" && banjoRoom.use().target?.enabled && !banjoRoom.world.acting && !banjoRoom.world.asking')
        key('KeyJ','j');wait('banjoRoom.use().last?.result && banjoRoom.use().mode==="tool-ready"')
        receipt=page.evaluate('banjoRoom.use().last.result')
        self.assertGreater(receipt['loosened_kg'],0)
        self.assertIn(receipt['ground'],materials)
        carried=page.evaluate('banjoRoom.use().last.carried')
        self.assertEqual(0,sum(carried.get(k,0) for k in ('soil_kg','sand_kg')))
        piles=page.evaluate('banjoRoom.use().last.excavation_piles')
        self.assertAlmostEqual(receipt['loosened_kg'],sum(p['kg'] for p in piles),delta=5e-6)
        self.assertEqual(reserve,app.brains.goods.reserve_kg(deposit),'A pick use must not award the rover ledger ore')
        self.assertFalse([e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/'material-preview.png').write_bytes(base64.b64decode(page.send('Page.captureScreenshot',{'format':'png'})['data']))
        (out/'material-preview.json').write_text(json.dumps({'native_seed':app.room.spec['terrain']['generate']['seed'],
            'preview':materials,'receipt':receipt,'carried':carried,
            'ore_reserve_before':reserve,'ore_reserve_after':app.brains.goods.reserve_kg(deposit),'exceptions':[]},indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':unittest.main()
