"""Native object-strike host/HTTP qualification using explicit authored fixtures.

These are connection tests, not paid manufacture, wear or internal fracture.
"""
from copy import deepcopy
import json
from pathlib import Path
import threading
import time
import unittest
import urllib.error
from unittest import mock
import ai_player_tests as ai

ROOT=Path(__file__).resolve().parents[1]


def fixture(material='glass',tool_capacity=0):
    return {**deepcopy(ai.server.fracture_lab.DEFAULT),'cell_m':.02,
        'bodies':[
            {'name':'head','shape':'sphere','material':'iron','size_mm':[100,100,100],'center_mm':[80,1500,0]},
            {'name':'field pick','shape':'box','material':'oak','size_mm':[40,240,40],'center_mm':[0,1380,0]},
            {'name':'target','shape':'box','material':material,'size_mm':[100,100,100],'center_mm':[240,1500,0]},
            {'name':'anchor','shape':'box','material':'iron','size_mm':[80,80,80],'center_mm':[400,1500,0],'anchored':True}],
        'joints':[
            {'kind':'fixing','a':'field pick','b':'head','at_mm':[20,1490,0],'axis':[0,1,0],
             'holds_tension_n':tool_capacity,'holds_shear_n':tool_capacity},
            {'kind':'fixing','a':'anchor','b':'target','at_mm':[300,1500,0],'axis':[1,0,0],
             'holds_tension_n':200,'holds_shear_n':200}],
        'tool_points':[{'body':'head','grip_body':'field pick','tip_mm':[120,1500,0],
            'grip_mm':[0,1300,0],'pointing':[1,0,0],'width_mm':40,'thickness_mm':40,
            'angle_deg':30,'length_mm':100}],
        'interactions':[{'object':'Fixture pick','template':'swing-and-lever',
                         'parts':['field pick','head'],'tool':'field pick'}]}


class NativeObjectStrikes(unittest.TestCase):
    setUp,start,stop,tearDown,setup_world,get,post,join=(
        ai.AutonomousGuests.setUp,ai.AutonomousGuests.start,ai.AutonomousGuests.stop,
        ai.AutonomousGuests.tearDown,ai.AutonomousGuests.setup_world,
        ai.AutonomousGuests.get,ai.AutonomousGuests.post,ai.AutonomousGuests.join)

    def open_fixture(self,material,take_up=True,tool_capacity=0):
        with mock.patch.object(ai.server.secrets,'randbelow',side_effect=[0,1]):
            world=self.post('/api/worlds',{'name':f'{material} connection fixture'})['id']
        owner=self.join(world,'Fixture player');self.players={world:owner}
        app=self.app.hub.get(world)
        players=app.room.player_records
        app.room=ai.server.world_room.Room('yard');app.room.scene='new-game'
        app.room.player_records=players
        app.rooms={'new-game':app.room};app.room.spec=fixture(material,tool_capacity)
        opened=app.live.open(app,{'spec':app.room.spec});app.live_holder='world'
        ai.server.inventory_room.after_open(app,opened,owner['id'])
        sid=opened['session']
        person={'standing_m':[-1.25,-.12,0],'eyes_m':[-1.25,1.5,0],
                'facing':[1,0,0],'look_direction':[1,0,0]}
        if take_up:
            shown=self.post('/api/world/inventory/shown',{'session':sid},world)
            self.post('/api/world/inventory',{'session':sid,'op':'take_up','item':'field pick',
                'revision':shown['record']['revision'],'request':'fixture-take','person':person},world)
        return world,owner,app,sid,person

    def test_failed_tool_connection_invalidates_review_and_survives_private_restart(self):
        import fabrication_tests as paid
        evidence=[]
        for material in ('glass','oak','iron'):
            world,owner,app,sid,person=self.open_fixture(material,tool_capacity=60)
            context={'scene':app.room.scene,'session':sid}
            self.post('/api/world/fabrication/configure',{**context,
                'settings':paid.settings(stock_kg={},energy_j=0),'request_id':'connection-config-0001'},world)
            shown=self.post('/api/world/inventory/shown',{'session':sid},world)
            held=next(e for e in shown['hands'].values() if e)
            # Give the original assembly a remembered bag slot before damage.
            for op, extra in (('stow',{}),('slot',{'slot':4}),('equip',{})):
                shown=self.post('/api/world/inventory/shown',{'session':sid},world)
                self.assertTrue(self.post('/api/world/inventory',{'session':sid,'op':op,
                    'item':'field pick' if op=='equip' else held['id'],'revision':shown['record']['revision'],
                    'request':'connection-'+op,'person':person,**extra},world)['ok'])
            request={**context,'source_item':held['id'],'candidate':paid.candidate()}
            try:reviewed=self.post('/api/world/fabrication/plan_remake',request,world)
            except urllib.error.HTTPError as error:self.fail(error.read().decode())
            self.assertTrue(all(j['attached'] for r in reviewed['source']['condition'] for j in r['joints']))
            hand=self.post('/api/live/act',{'session':sid,'op':'poses'},world)['hand']
            grip=hand['grip_m'];end=grip[:];end[0]+=.14
            self.post('/api/live/act',{'session':sid,'op':'stroke','path':[grip,end],
                'speed_m_s':4,'accel_m_s2':80,'lead_m':.025,'give_up_s':.125},world)
            self.post('/api/live/act',{'session':sid,'op':'step','dt':1/240,'n':120},world)
            shown=self.post('/api/world/inventory/shown',{'session':sid},world)
            retained=next(e for e in shown['hands'].values() if e)
            self.assertEqual('field pick',retained['name'])
            self.assertEqual(4,retained['slot'])
            self.assertNotEqual(held['id'],retained['id'])
            before_retry=app.live.snapshot()[0]
            replay=self.post('/api/world/inventory',{'session':sid,'op':'take_up','item':'field pick',
                'revision':0,'request':'fixture-take','person':person},world)
            self.assertTrue(replay['ok'])
            self.assertEqual(before_retry,app.live.snapshot()[0])
            self.assertEqual(shown['record'],replay['shown']['record'])
            self.assertEqual(.2688,round(ai.server.inventory_room.whole_kg(
                app,ai.server.inventory_room.item_holding(app,'field pick')),4))
            import placement
            self.assertEqual({'field pick'},placement.own_parts(app,'field pick'))
            self.assertEqual(['field pick'],[b['name'] for b in placement.carried_shape(app,'field pick')])
            damaged_request={**request,'source_item':retained['id']}
            damaged=self.post('/api/world/fabrication/plan_remake',damaged_request,world)
            self.assertNotEqual(reviewed['source']['source_hash'],damaged['source']['source_hash'])
            self.assertNotEqual(reviewed['source']['native_hash'],damaged['source']['native_hash'])
            rows=damaged['source']['condition']
            self.assertEqual([1],[r['fraction'] for r in rows])
            failure=rows[0]['joints'][0]
            self.assertFalse(failure['attached']);self.assertGreater(failure['parted_load_n'],60)
            self.assertEqual(60,failure['parted_capacity_n']);self.assertTrue(failure['parted_because'])
            before=deepcopy(app.room.fabrication_record)
            with self.assertRaises(urllib.error.HTTPError) as stale:
                self.post('/api/world/fabrication/start_remake',{**context,'plan_id':reviewed['plan_id'],
                    'revision':before['revision'],'request_id':'stale-connection-remake'},world)
            self.assertIn('Selected item changed',stale.exception.read().decode())
            self.assertEqual(before,app.room.fabrication_record)
            carried=self.post('/api/workshop/inventory',{},world)['carried']
            self.assertEqual({r['name']:r for r in rows},{r['name']:r for r in carried[0]['condition']})
            self.assertEqual(['field pick'],carried[0]['parts'])
            self.assertEqual(.2688,round(carried[0]['kg'],4))
            self.assertNotIn('Study / gather in World',carried[0]['next_use'])
            peer=self.join(world,'Connection peer')
            self.assertEqual([],self.post('/api/workshop/inventory',{},world,peer['token'])['carried'])
            with self.assertRaises(urllib.error.HTTPError):
                self.post('/api/world/fabrication/plan_remake',damaged_request,world,peer['token'])
            peer_shown=self.post('/api/world/inventory/shown',{'session':sid},world,peer['token'])
            refused=self.post('/api/world/inventory',{'session':sid,'op':'take','item':'field pick',
                'revision':peer_shown['record']['revision'],'request':'peer-no-handle','person':person},world,peer['token'])
            self.assertFalse(refused['ok'])
            collected=self.post('/api/world/inventory',{'session':sid,'op':'take','item':'head',
                'revision':peer_shown['record']['revision'],'request':'peer-takes-free-head','person':person},world,peer['token'])
            self.assertTrue(collected['ok'],collected)
            stowed=self.post('/api/world/inventory',{'session':sid,'op':'stow','item':retained['id'],
                'revision':shown['record']['revision'],'request':'owner-stows-handle','person':person},world)
            self.assertTrue(stowed['ok'],stowed)
            self.assertEqual(retained['id'],stowed['record']['stowed'][4])
            stored_rows=self.post('/api/workshop/inventory',{},world)['carried'][0]['condition']
            self.assertEqual(rows[0]['joints'],stored_rows[0]['joints'])
            native=app.live.snapshot()[0]
            parked={b['name']:b['parked']['actor'] for b in native['bodies'] if b.get('parked')}
            self.assertEqual({'head':peer['id'],'field pick':owner['id']},parked)
            self.assertTrue(ai.server.keep_world(app,'failed tool connection review checkpoint'))
            self.stop();self.start();self.post('/api/world/player/join',{'token':owner['token']},world)
            self.post('/api/world/open',{},world)
            reopened=self.post('/api/workshop/inventory',{},world)['carried']
            self.assertEqual({r['name']:r for r in stored_rows},{r['name']:r for r in reopened[0]['condition']})
            self.assertEqual('bag 5',reopened[0]['where'])
            self.assertEqual(['field pick'],reopened[0]['parts'])
            peer_carried=self.post('/api/workshop/inventory',{},world,peer['token'])['carried']
            self.assertEqual(['head'],peer_carried[0]['parts'])
            evidence.append({'material':material,'failure':failure,'source_review_invalidated':True,
                'private_restart_retained':True,'constituent_fractions':[r['fraction'] for r in rows]})
        if ai.qa_browser.CHROME.is_file():
            chrome=ai.qa_browser.Chrome(1280,800);self.addCleanup(chrome.close)
            page=chrome.page;page.send('Page.enable');page.send('Runtime.enable')
            page.send('Page.addScriptToEvaluateOnNewDocument',{'source':
                f'localStorage.setItem("banjo.player.{world}",{json.dumps(owner["token"])});'})
            page.send('Page.navigate',{'url':self.base+f'/world?world={world}&workshop=1&tab=inventory'})
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                if page.evaluate('Boolean(document.querySelector("#ws-inv-grid .body-condition[data-condition-state=disconnected]"))'):break
                time.sleep(.05)
            self.assertEqual('Disconnected',page.evaluate('document.querySelector("#ws-inv-grid .condition-value strong")?.textContent'))
            self.assertFalse(page.evaluate('Boolean(document.querySelector("#ws-inv-grid .body-condition meter"))'))
            self.assertEqual([],[e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])
            chrome.close()
        (ROOT/'build/resource-flow/connection-review-http.json').write_text(json.dumps({
            'dt_s':1/240,'cell_m':.02,'gravity_m_s2':[0,-9.81,0],'results':evidence,
            'limits':'Authored weak tool connection; separated-part slots/mass/ownership/restart qualify, not wear, material fracture or paid manufacture.'},indent=2)+'\n',encoding='utf-8')

    def test_native_http_strike_separates_declared_target_and_reopens(self):
        results=[]
        for material in ('glass','oak','iron'):
            world,owner,app,sid,person=self.open_fixture(material)
            preview=self.post('/api/world/tool',{'session':sid,'person':person,'target_name':'target'},world)
            self.assertTrue(preview['enabled'],preview)
            stop=threading.Event();errors=[]
            def clock():
                try:
                    while not stop.is_set():
                        with app.live.as_actor(owner['id']):
                            app.live.act({'session':sid,'op':'step','dt':1/240,'n':1})
                        time.sleep(1/240)
                except Exception as exc:errors.append(str(exc))
            pump=threading.Thread(target=clock,daemon=True);pump.start()
            try:
                answer=self.post('/api/world/tool/use',{'session':sid,'person':person,
                    'target_name':'target','at_m':[900,900,900]},world)
            finally:stop.set();pump.join(5)
            self.assertEqual([],errors)
            self.assertNotIn('refused',answer,answer)
            result=answer['result']
            self.assertEqual('banjo.object-strike.v1',result['schema'])
            self.assertTrue(result['impacts'],answer)
            self.assertTrue(result['parted_joints'],answer)
            self.assertFalse(result['internal_fracture_supported'])
            self.assertFalse(result['wear_supported'])
            self.assertTrue(result['working_point_connected'])
            with app.live.as_actor(owner['id']):
                before,why=app.live.snapshot()
            self.assertIsNotNone(before,why)
            self.assertTrue(ai.server.keep_world(app,'object-strike fixture closed'))
            saved=deepcopy(app.store.read_record(app.room.scene)['world'])
            again=app.live.open(app,{'spec':app.room.spec,'snapshot':saved})
            self.assertEqual('whole',again['restored']['tier'])
            with app.live.as_actor(owner['id']):
                after,why=app.live.snapshot()
            self.assertEqual(before['joints'],after['joints'])
            self.assertEqual(before.get('player_hands'),after.get('player_hands'))
            results.append({'material':material,'result':result})
        out=ROOT/'build/resource-flow/object-strike-http.json'
        out.write_text(json.dumps({'dt_s':1/240,'cell_m':.02,'gravity_m_s2':[0,-9.81,0],
            'results':results,'limits':'Authored native fixture; no paid build, internal damage, wear or global conservation qualification.'},indent=2)+'\n',encoding='utf-8')

    def test_browser_targets_an_object_and_uses_the_same_native_connections(self):
        if not ai.qa_browser.CHROME.is_file():self.skipTest('Chrome required')
        world,owner,app,sid,person=self.open_fixture('glass')
        chrome=ai.qa_browser.Chrome(1280,800);self.addCleanup(chrome.close)
        page=chrome.page;page.send('Page.enable');page.send('Runtime.enable')
        page.send('Page.addScriptToEvaluateOnNewDocument',{'source':
            f'localStorage.setItem("banjo.player.{world}",{json.dumps(owner["token"])});'})
        def wait(expression,seconds=15):
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline:
                if page.evaluate('Boolean('+expression+')'):return
                time.sleep(.025)
            self.fail('did not reach '+expression+'; '+str(page.evaluate(
                '({use:banjoRoom.use(),tools:banjoRoom.world.tools,aim:banjoRoom.world.aim,'
                'camera:banjoRoom.camera.position.toArray(),target:banjoRoom.world.bodies.get("target").mesh.position.toArray()})')))
        page.send('Page.navigate',{'url':self.base+f'/world?world={world}'})
        wait('window.banjoRoom?.ready() && banjoRoom.use().mode==="tool-ready"')
        page.evaluate('banjoRoom.standAt(-1.25,1.62,0);banjoRoom.lookAt(.24,1.5,0)')
        wait('banjoRoom.use().target?.enabled && banjoRoom.use().target?.target?.name==="target"')
        page.evaluate('''(()=>{window.strikes=[];const original=window.fetch;
          window.fetch=async function(url,options){const response=await original.apply(this,arguments);
            if(String(url).includes('/api/world/tool/use'))strikes.push(await response.clone().json());
            return response;}})()''')
        for kind in ('keyDown','keyUp'):
            page.send('Input.dispatchKeyEvent',{'type':kind,'code':'KeyJ','key':'j','windowsVirtualKeyCode':74})
        wait('strikes.length===1 && banjoRoom.use().mode==="tool-ready"')
        answer=page.evaluate('strikes[0]')
        self.assertNotIn('refused',answer,{'reason':answer.get('refused'),
            'native':self.post('/api/live/act',{'session':sid,'op':'tool_points'},world),
            'view':page.evaluate('({camera:banjoRoom.camera.position.toArray(),target:banjoRoom.use().target})')})
        self.assertEqual('object-contact',answer['gesture'])
        self.assertEqual(answer['inventory']['record']['revision'],
                         page.evaluate('banjoRoom.world.inventory.record.revision'))
        self.assertTrue(answer['result']['parted_joints'],answer)
        # A browser can begin Use in sustained native contact after its carry
        # clock has already reported the impact. Require the target's actual
        # overload receipt; a fresh impact event is not a continuous load.
        failure=next(j for j in answer['result']['parted_joints'] if 'target' in (j['a'],j['b']))
        self.assertFalse(failure['attached']);self.assertEqual(200,failure['parted_capacity_n'])
        self.assertGreater(failure['parted_load_n'],200)
        self.assertEqual('field pick',page.evaluate('banjoRoom.held().name'))
        (ROOT/'build/resource-flow/object-strike-browser.json').write_text(
            json.dumps(answer,indent=2)+'\n',encoding='utf-8')
        chrome.close()


NativeObjectStrikes=unittest.skipUnless(ai.hub.RUNNER.is_file() and ai.hub.ENGINE.is_file(),
                                      'native engine required')(NativeObjectStrikes)

if __name__=='__main__':unittest.main(verbosity=2)
