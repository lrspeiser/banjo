"""Native object-strike host/HTTP qualification using explicit authored fixtures.

These are connection tests, not paid manufacture, wear or internal fracture.
"""
from copy import deepcopy
import json
from pathlib import Path
import threading
import time
import unittest
from unittest import mock
import ai_player_tests as ai

ROOT=Path(__file__).resolve().parents[1]


def fixture(material='glass'):
    return {**deepcopy(ai.server.fracture_lab.DEFAULT),'cell_m':.02,
        'bodies':[
            {'name':'head','shape':'sphere','material':'iron','size_mm':[100,100,100],'center_mm':[80,1500,0]},
            {'name':'field pick','shape':'box','material':'oak','size_mm':[40,240,40],'center_mm':[0,1380,0]},
            {'name':'target','shape':'box','material':material,'size_mm':[100,100,100],'center_mm':[240,1500,0]},
            {'name':'anchor','shape':'box','material':'iron','size_mm':[80,80,80],'center_mm':[400,1500,0],'anchored':True}],
        'joints':[
            {'kind':'fixing','a':'field pick','b':'head','at_mm':[20,1490,0],'axis':[0,1,0]},
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

    def open_fixture(self,material,take_up=True):
        with mock.patch.object(ai.server.secrets,'randbelow',side_effect=[0,1]):
            world=self.post('/api/worlds',{'name':f'{material} connection fixture'})['id']
        owner=self.join(world,'Fixture player');self.players={world:owner}
        app=self.app.hub.get(world)
        players=app.room.player_records
        app.room=ai.server.world_room.Room('yard');app.room.scene='new-game'
        app.room.player_records=players
        app.rooms={'new-game':app.room};app.room.spec=fixture(material)
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
        self.assertTrue(answer['result']['impacts'],answer)
        self.assertTrue(answer['result']['parted_joints'],answer)
        self.assertEqual('field pick',page.evaluate('banjoRoom.held().name'))
        (ROOT/'build/resource-flow/object-strike-browser.json').write_text(
            json.dumps(answer,indent=2)+'\n',encoding='utf-8')
        chrome.close()


NativeObjectStrikes=unittest.skipUnless(ai.hub.RUNNER.is_file() and ai.hub.ENGINE.is_file(),
                                      'native engine required')(NativeObjectStrikes)

if __name__=='__main__':unittest.main(verbosity=2)
