"""Actual native-world navigation and cursor transitions in Chrome."""
import json
import base64
import math
import os
from pathlib import Path
import time
import unittest
from unittest import mock
import ai_player_tests as ai
import qa_browser

OUT=Path(__file__).resolve().parents[1]/'build/resource-flow'

class Navigation(unittest.TestCase):
    get,post,join=ai.AutonomousGuests.get,ai.AutonomousGuests.post,ai.AutonomousGuests.join
    setUp,start,stop,tearDown,setup_world=(ai.AutonomousGuests.setUp,ai.AutonomousGuests.start,
        ai.AutonomousGuests.stop,ai.AutonomousGuests.tearDown,ai.AutonomousGuests.setup_world)

    def test_faster_walk_edge_look_and_safe_cursor_for_panels(self):
        if not qa_browser.CHROME.is_file():
            if os.environ.get('BANJO_BROWSER_TESTS')=='required':self.fail('Chrome required')
            self.skipTest('Chrome unavailable')
        with mock.patch.object(ai.server.secrets,'randbelow',side_effect=[0,1]):
            ident,owner,app=self.setup_world()
        chrome=qa_browser.Chrome(1280,800);self.addCleanup(chrome.close)
        page=chrome.page;page.send('Page.enable');page.send('Runtime.enable')
        def wait(expr,seconds=25):
            until=time.monotonic()+seconds
            while time.monotonic()<until:
                if page.evaluate('Boolean('+expr+')'):return
                time.sleep(.04)
            self.fail(expr)
        def key(code,down):
            page.send('Input.dispatchKeyEvent',{'type':'keyDown' if down else 'keyUp',
                'key':{'KeyW':'w','Escape':'Escape','ShiftLeft':'Shift'}.get(code,code),
                'code':code,'windowsVirtualKeyCode':{'KeyW':87,'Escape':27,'ShiftLeft':16}[code]})
        def click(x,y):
            for kind in ('mousePressed','mouseReleased'):
                page.send('Input.dispatchMouseEvent',{'type':kind,'x':x,'y':y,'button':'left','clickCount':1})
        page.send('Page.navigate',{'url':self.base+f'/world?world={ident}&hold=1'})
        wait('window.banjoRoom?.ready()')
        page.evaluate('window.dispatchEvent(new CustomEvent("banjo-movement-mode",{detail:"gravity"}))')
        spot=page.evaluate("""(()=>{const r=banjoRoom;for(let z=-12;z<12;z+=.5)
          for(let x=-14;x<10;x+=.5){let ok=true,prev=r.groundAt(x,z);
            for(let t=0;t<=5;t+=.1){const h=r.groundAt(x+t,z),w=r.waterAt(x+t,z);
              if(w&&w.level-h>.02 || Math.abs(h-prev)>.065)ok=false;prev=h}
            if(ok)return [x,z];}return null})()""")
        self.assertIsNotNone(spot)
        x,z=spot
        def stand():
            page.evaluate(f'banjoRoom.standAt({x},banjoRoom.groundAt({x},{z})+1.6,{z});banjoRoom.lookAt({x+5},banjoRoom.camera.position.y,{z})')
        rates=[]
        for sprint in (False,True):
            stand()
            if sprint:key('ShiftLeft',True)
            before=page.evaluate('({t:performance.now(),p:banjoRoom.camera.position.toArray()})')
            key('KeyW',True);time.sleep(.65);key('KeyW',False)
            after=page.evaluate('({t:performance.now(),p:banjoRoom.camera.position.toArray()})')
            if sprint:key('ShiftLeft',False)
            rate=math.hypot(after['p'][0]-before['p'][0],after['p'][2]-before['p'][2])/((after['t']-before['t'])/1000)
            self.assertAlmostEqual(6.8 if sprint else 4.2,rate,delta=.65)
            rates.append(rate)
        stand()
        edge=page.evaluate('document.querySelector("#panel").getBoundingClientRect().left-3')
        yaw=page.evaluate('banjoRoom.controls().yaw')
        page.send('Input.dispatchMouseEvent',{'type':'mouseMoved','x':edge,'y':400})
        time.sleep(.55)
        turned=abs(page.evaluate('banjoRoom.controls().yaw')-yaw)
        self.assertGreater(turned,.65)
        key('KeyW',True);key('Escape',True);key('Escape',False)
        self.assertTrue(page.evaluate('banjoRoom.controls().cursorFree'))
        self.assertEqual([],page.evaluate('banjoRoom.keysDown()'))
        yaw=page.evaluate('banjoRoom.controls().yaw')
        pose=page.evaluate('banjoRoom.camera.position.toArray()')
        page.send('Input.dispatchMouseEvent',{'type':'mouseMoved','x':edge,'y':60})
        time.sleep(.5)
        self.assertEqual(yaw,page.evaluate('banjoRoom.controls().yaw'))
        key('KeyW',False);key('KeyW',True);time.sleep(.2);key('KeyW',False)
        after=page.evaluate('banjoRoom.camera.position.toArray()')
        self.assertLess(math.hypot(after[0]-pose[0],after[2]-pose[2]),.001)
        page.evaluate('document.querySelector("[data-game-menu]").click()')
        wait('document.querySelector("#game-menu").open')
        page.evaluate('document.querySelector("#game-menu-close").click()')
        self.assertTrue(page.evaluate('banjoRoom.controls().cursorFree'))
        held=page.evaluate('banjoRoom.held()?.name || null')
        click(400,400)
        self.assertFalse(page.evaluate('banjoRoom.controls().cursorFree'))
        self.assertEqual(held,page.evaluate('banjoRoom.held()?.name || null'))
        page.evaluate('banjoRoom.pick("field pick")')
        key('Escape',True);key('Escape',False)
        self.assertEqual('field pick',page.evaluate('banjoRoom.picked().name'))
        key('Escape',True);key('Escape',False)
        self.assertFalse(page.evaluate('banjoRoom.controls().cursorFree'))
        # Focusing chat also freezes mouse/keyboard navigation.
        page.evaluate('document.querySelector("#ask-text").focus()')
        self.assertTrue(page.evaluate('banjoRoom.controls().cursorFree'))
        yaw=page.evaluate('banjoRoom.controls().yaw')
        page.send('Input.dispatchMouseEvent',{'type':'mouseMoved','x':edge,'y':400})
        time.sleep(.25)
        self.assertEqual(yaw,page.evaluate('banjoRoom.controls().yaw'))
        self.assertFalse([e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])
        page.evaluate('localStorage.setItem("banjo.movement","old-walk");location.reload()')
        wait('window.banjoRoom?.ready()')
        self.assertEqual('gravity',page.evaluate('banjoRoom.controls().movementMode'))
        OUT.mkdir(parents=True,exist_ok=True)
        (OUT/'world-navigation.json').write_text(json.dumps({'walk_m_s':rates[0],
            'run_m_s':rates[1],'edge_turn_rad_in_055_s':turned,'cursor_stops_look_and_keys':True,
            'resume_click_preserves_hand':True,'escape_preserves_selection':True,
            'legacy_movement_preference_uses_gravity':True,
            'native_terrain_seed':app.room.spec['terrain']['generate']['seed']},indent=2)+'\n',encoding='utf-8')
        (OUT/'world-navigation.png').write_bytes(base64.b64decode(
            page.send('Page.captureScreenshot',{'format':'png'})['data']))

if __name__=='__main__':unittest.main(verbosity=2)
