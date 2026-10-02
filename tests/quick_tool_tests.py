"""Shared authoring, native material comparison and actual rapid player input."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import time
import threading
import unittest
from unittest import mock
import ai_player_tests as ai
import ground_work_mcp_tests as ground
import qa_browser
import interaction_profiles as profiles
from mcp import workshop_tools

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/player-learning'


class Authoring(unittest.TestCase):
    def test_overlapping_requests_refuse_instead_of_interrupting_the_current_hand(self):
        import tool_use_tests as controls
        import tool_use
        app=controls.app_with()
        entered=threading.Event();finish=threading.Event();answers=[]
        def contact(*args):
            entered.set();finish.wait(3)
            return {'gesture':'contact'}
        request={'person':controls.PERSON,'at_m':controls.IN_REACH}
        with mock.patch.object(tool_use,'_contact',side_effect=contact) as run:
            worker=threading.Thread(target=lambda:answers.append(tool_use.run(app,request)))
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                self.assertIn('busy',tool_use.run(app,request)['refused'])
                self.assertEqual(1,run.call_count)
            finally:finish.set();worker.join(3)
        self.assertFalse(app.live.session.tool_busy)

    def test_old_and_custom_tools_inherit_contact_and_shared_schema(self):
        for name in ('Field pick','LLM moon spade'):
            profile=profiles.check({'object':name,'template':'swing-and-lever',
                'parts':['handle'],'tool':'handle'},bodies={'handle'},joints=[],points=['handle'])
            self.assertEqual('contact',profiles.tool_use(profile)['gesture'])
            self.assertEqual(4,profiles.tool_use(profile)['cadence_hz'])
        self.assertEqual(ground.banjo_mcp.TOOL_USE_SCHEMA,workshop_tools.AUTHORING_SCHEMA['properties']['use'])

    def test_invalid_gestures_rates_and_outcome_fields_are_refused(self):
        for use in ({'gesture':'spin'},{'cadence_hz':float('nan')},{'cadence_hz':True},
                    {'cadence_hz':9},{'loosened_kg':100},{'force_n':10000}):
            with self.subTest(use=use),self.assertRaises(ValueError):
                profiles.check({'object':'custom','template':'swing-and-lever',
                    'parts':['handle'],'tool':'handle','use':use},bodies={'handle'},joints=[],points=['handle'])


class MaterialContact(unittest.TestCase):
    def tearDown(self):
        for ident in list(ground.banjo_mcp.WORLDS):
            if ident.startswith('room-'):ground.room_world.close_room(ident)

    def test_same_short_path_in_glass_oak_and_iron_retains_native_mass_and_ground_account(self):
        results=[]
        for material in ('glass','oak','iron'):
            ident=ground.room_world.open_room(ground.world_room.clearing())
            for part in ground.PICK:
                ground.call('add_object',world_id=ident,object={**part,'material':material})
            ground.pointed(ident)
            world=ground.banjo_mcp.WORLDS[ident]['world']
            mass=world.body('pick haft').mass_kg
            trial=ground.banjo_mcp._swing_and_pry(world,'pick haft')
            self.assertEqual('contact',trial['gesture'])
            self.assertTrue(trial['tool_whole'])
            work=world.ground_work()
            # The trial ends on rock. The carried/terrain edit ledger retains
            # the preceding actual soil removal without a scripted yield.
            carried=world.environment_report()['ground']['carried']
            removed=world.terrain().dug_m3
            carried_volume=carried['soil_m3']+carried['sand_m3']
            self.assertAlmostEqual(removed,carried_volume,delta=1e-10)
            self.assertGreater(removed,0,'the audit must measure actual removal, not an untouched trial copy')
            self.assertAlmostEqual(mass,world.body('pick haft').mass_kg,delta=1e-10)
            results.append({'material':material,'mass_kg':mass,'trial':trial,
                'removed_m3':removed,'carried_m3':carried_volume,
                'local_volume_residual_m3':removed-carried_volume})
            ground.room_world.close_room(ident)
        self.assertGreater(results[2]['mass_kg'],results[0]['mass_kg'])
        self.assertGreater(results[0]['mass_kg'],results[1]['mass_kg'])
        OUT.mkdir(parents=True,exist_ok=True)
        (OUT/'quick-tool-materials.json').write_text(json.dumps({'dt_s':1/240,
            'cell_m':.04,'results':results,'limits':'Native point/ground model; no calibrated fracture, '
            'wood grain/plasticity or full-world energy/momentum certification.'},indent=2)+'\n',encoding='utf-8')


@unittest.skipUnless(ai.hub.RUNNER.is_file() and ai.hub.ENGINE.is_file(),'native engines required')
class RapidPlayer(unittest.TestCase):
    get,post,join=ai.AutonomousGuests.get,ai.AutonomousGuests.post,ai.AutonomousGuests.join
    setUp,start,stop,tearDown,setup_world=(ai.AutonomousGuests.setUp,ai.AutonomousGuests.start,
        ai.AutonomousGuests.stop,ai.AutonomousGuests.tearDown,ai.AutonomousGuests.setup_world)

    def test_actual_hold_and_rapid_taps_complete_multiple_native_uses_per_second(self):
        if not qa_browser.CHROME.is_file():
            if os.environ.get('BANJO_BROWSER_TESTS')=='required':self.fail('Chrome required')
            self.skipTest('Chrome not installed')
        with mock.patch.object(ai.server.secrets,'randbelow',side_effect=[0,1]):
            ident,owner,app=self.setup_world()
        save_events=[]
        keep=ai.server.keep_world
        def observed_keep(target,*args,**kwargs):
            result=keep(target,*args,**kwargs)
            if target is app:
                save_events.append(dict(app.room.persistence))
            return result
        saving=mock.patch.object(ai.server,'keep_world',side_effect=observed_keep)
        saving.start();self.addCleanup(saving.stop)
        chrome=qa_browser.Chrome(1280,800);self.addCleanup(chrome.close)
        page=chrome.page;page.send('Page.enable');page.send('Runtime.enable')
        def wait(expression,seconds=25):
            until=time.monotonic()+seconds
            while time.monotonic()<until:
                if page.evaluate('Boolean('+expression+')'):return
                time.sleep(.025)
            self.fail('did not reach '+expression+'; '+str(page.evaluate('banjoRoom.use()')))
        def key(kind,code,letter):
            page.send('Input.dispatchKeyEvent',{'type':kind,'code':code,'key':letter,
                'windowsVirtualKeyCode':ord(letter.upper())})
        page.send('Page.navigate',{'url':self.base+f'/world?world={ident}'})
        wait('window.banjoRoom?.ready() && document.querySelector("#panel-state").textContent==="Live."')
        page.evaluate('(()=>{const r=banjoRoom,p=r.world.bodies.get("field pick").mesh.position;'
            'r.standAt(p.x,p.y+1.62,p.z+1.1);r.lookAt(p.x,p.y,p.z)})()')
        wait('banjoRoom.world.aim?.name==="field pick"')
        key('keyDown','KeyE','e');key('keyUp','KeyE','e')
        wait('banjoRoom.held()?.name==="field pick" && banjoRoom.use().mode==="tool-ready"')
        page.evaluate('banjoRoom.standAt(-.9,banjoRoom.groundAt(-.9,.025)+1.62,.025)')
        page.evaluate('banjoRoom.lookAt(.3,banjoRoom.groundAt(.3,.025),.025)')
        wait('banjoRoom.use().target?.enabled')
        before=page.evaluate('banjoRoom.use().target.carried || {}')
        self.assertEqual(0,sum(before.get(k,0) for k in ('soil_kg','sand_kg')),
            'pickup and idle positioning must not excavate before Use')
        # Observe real HTTP replies, including refusals. Never synthesize work.
        page.evaluate('''(()=>{window.quickUses=[];window.quickActive=0;window.quickMax=0;
          window.saveWarnings=[];
          new MutationObserver(()=>{const b=document.querySelector('#world-save-status');
            if(b && !b.hidden)saveWarnings.push(b.textContent)
          }).observe(document.body,{subtree:true,childList:true,attributes:true});
          const original=window.fetch;window.fetch=async function(url,options){
            if(!String(url).includes('/api/world/tool/use'))return original.apply(this,arguments);
            const start=performance.now();quickMax=Math.max(quickMax,++quickActive);
            try{const r=await original.apply(this,arguments);const answer=await r.clone().json();
              quickUses.push({start,end:performance.now(),answer});return r;
            }finally{quickActive--}}
        })()''')
        key('keyDown','KeyJ','j');key('keyUp','KeyJ','j')
        wait('quickActive===1')
        # Ask for a real native snapshot during the real tool movement. This
        # must keep the previous disk checkpoint and queue a quiet retry.
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            if not ai.server.keep_world(app,'browser stroke boundary'):
                break
            time.sleep(.005)
        self.assertEqual('pending',app.room.persistence['state'],save_events)
        wait('quickUses.length===1 && banjoRoom.use().mode==="tool-ready"')
        self.assertGreater(page.evaluate('quickUses[0].answer.result?.loosened_kg || 0'),0)
        first=page.evaluate('quickUses[0].answer')
        delta=sum(first['carried'].get(k,0)-before.get(k,0) for k in ('soil_kg','sand_kg'))
        self.assertAlmostEqual(delta,first['result']['loosened_kg'],delta=5e-6)
        page.evaluate('window.quickUses=[];window.quickRotation=[]')
        key('keyDown','KeyJ','j')
        began=time.monotonic()
        while time.monotonic()-began<3:
            page.evaluate('quickRotation.push(banjoRoom.world.bodies.get("field pick").mesh.quaternion.toArray())')
            time.sleep(.03)
        key('keyUp','KeyJ','j')
        wait('quickActive===0 && banjoRoom.use().mode==="tool-ready"')
        held=page.evaluate('quickUses')
        OUT.mkdir(parents=True,exist_ok=True)
        (OUT/'quick-tool-timing.json').write_text(json.dumps([{'ms':r['end']-r['start'],'start':r['start'],'done':r['answer'].get('done'),'refused':r['answer'].get('refused'),'result':r['answer'].get('result')} for r in held],indent=2)+'\n')
        self.assertGreaterEqual(len(held),6,'See quick-tool-timing.json')
        self.assertFalse([r for r in held if r['answer'].get('refused')],held)
        elapsed=(held[-1]['end']-held[0]['start'])/1000
        rate=len(held)/elapsed
        self.assertGreaterEqual(rate,2.0,held)
        self.assertTrue(all(r['answer']['gesture']=='contact' for r in held))
        self.assertTrue(all(r['answer'].get('result') and not r['answer']['result']['open'] for r in held),held)
        rotations=page.evaluate('quickRotation');reference=rotations[0]
        angles=[2*math.acos(min(1,abs(sum(a*b for a,b in zip(reference,q)))))*180/math.pi for q in rotations]
        self.assertLess(max(angles),30,'native tool should not wind up or revolve during short uses')
        page.evaluate('window.quickUses=[]')
        for _ in range(5):
            key('keyDown','KeyJ','j');key('keyUp','KeyJ','j');time.sleep(.12)
        wait('quickActive===0 && !banjoRoom.use().queued && !banjoRoom.use().timer')
        taps=page.evaluate('quickUses')
        self.assertEqual(5,len(taps),'rapid explicit taps should not be lost')
        self.assertEqual(1,page.evaluate('quickMax'),'requests must be sequential')
        # Stop ends held repeat after the currently executing native use.
        page.evaluate('window.quickUses=[]')
        key('keyDown','KeyJ','j');wait('quickActive===1')
        page.send('Input.dispatchMouseEvent',{'type':'mousePressed','x':300,'y':300,
            'button':'right','clickCount':1})
        page.send('Input.dispatchMouseEvent',{'type':'mouseReleased','x':300,'y':300,
            'button':'right','clickCount':1})
        key('keyUp','KeyJ','j');wait('quickActive===0')
        stopped=page.evaluate('quickUses.length');time.sleep(.6)
        self.assertEqual(stopped,page.evaluate('quickUses.length'))
        wait('document.querySelector("#world-save-status")?.hidden')
        self.assertEqual([],page.evaluate('saveWarnings'))
        self.assertTrue(any(s['state']=='pending' for s in save_events),save_events)
        self.assertFalse(any(s['state']=='failed' for s in save_events),save_events)
        self.assertEqual('saved',app.room.persistence['state'])
        self.assertFalse([e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])
        # A genuine disk failure still reaches the same visible warning, then
        # clears only when a complete paired checkpoint succeeds.
        with mock.patch.object(app.store,'_save',side_effect=OSError('injected disk full')):
            self.assertFalse(ai.server.keep_world(app,'browser storage failure'))
            wait('document.querySelector("#world-save-status") && !document.querySelector("#world-save-status").hidden')
            self.assertIn('injected disk full',page.evaluate('document.querySelector("#world-save-status").textContent'))
        self.assertTrue(ai.server.keep_world(app,'browser storage recovery'))
        wait('document.querySelector("#world-save-status").hidden')
        chrome.close()
        self.assertTrue(ai.server.keep_world(app,'rapid tool restart boundary'))
        saved=app.store.read_record(app.room.scene)['world']
        carried=saved['ground']['carriers']
        self.assertGreater(sum(c.get('soil_m3',0)+c.get('sand_m3',0) for c in carried.values()),0)
        self.stop();self.start()
        reopened=self.post('/api/world/open',{},ident)
        restored=self.app.hub.get(ident)
        again=restored.live.snapshot()[0]['ground']['carriers']
        self.assertEqual(carried,again,'actual excavated stock must survive server restart')
        self.assertEqual(saved['tool_points'],restored.live.snapshot()[0]['tool_points'])
        OUT.mkdir(parents=True,exist_ok=True)
        (OUT/'quick-tool-browser.json').write_text(json.dumps({'held':held,'rapid_taps':taps,
            'completed_uses_per_s':rate,'max_rotation_deg':max(angles),'max_concurrent_requests':1,
            'terrain_seed':app.room.spec['terrain']['generate']['seed'],
            'save_events':save_events,'tool_use_save_warnings':[],
            'disk_failure_warning_verified':True,'restart_carried':again},indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':unittest.main(verbosity=2)
