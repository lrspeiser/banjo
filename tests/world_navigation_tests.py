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
import workshop_navigation_tests as screens

OUT=Path(__file__).resolve().parents[1]/'build/resource-flow'

class Navigation(unittest.TestCase):
    wait = screens.GameScreens.wait
    get,post,join=ai.AutonomousGuests.get,ai.AutonomousGuests.post,ai.AutonomousGuests.join
    setUp,start,stop,tearDown,setup_world=(ai.AutonomousGuests.setUp,ai.AutonomousGuests.start,
        ai.AutonomousGuests.stop,ai.AutonomousGuests.tearDown,ai.AutonomousGuests.setup_world)

    def test_opening_pickup_stays_in_native_players_hand(self):
        self.native_pickup('field pick', False)

    def test_touch_pickup_stays_in_native_players_hand(self):
        self.native_pickup('field pick-g0', True)

    def native_pickup(self, part, touch):
        # Reproduce ordinary opening play: live clock, native body, no fly
        # camera, no paused simulation and no moved/spawned tool fixture.
        with mock.patch.dict(os.environ, {'BANJO_WORLD_CLOCK':'1'}), \
             mock.patch.object(ai.server.secrets,'randbelow',side_effect=[0,1]):
            ident,owner,app=self.setup_world(surface='columns')
        screens.GameScreens.browser(self,ident,owner)
        self.page.evaluate('localStorage.setItem("banjo.movement","native")')
        if touch:
            self.page.send('Emulation.setDeviceMetricsOverride',{'width':844,'height':390,
                'deviceScaleFactor':1,'mobile':True})
            self.page.send('Emulation.setTouchEmulationEnabled',{'enabled':True,'maxTouchPoints':5})
        self.page.send('Page.navigate',{'url':self.base+f'/world?world={ident}'})
        self.wait('banjoRoom?.ready() && document.querySelector("#panel-state").textContent==="Live."')
        self.wait('banjoRoom.controls().movementMode==="native" && !banjoRoom.status().paused')
        self.wait('!!banjoRoom.world.bodies.get("field pick")')
        time.sleep(.5)
        self.page.evaluate('''(()=>{const r=banjoRoom,p=r.world.bodies.get('field pick').mesh.position;
            r.lookAt(p.x,p.y,p.z);})()''')
        self.page.evaluate('''(()=>{window.pickupReplies=[];const original=window.fetch;
            window.fetch=async function(url,options){const response=await original.apply(this,arguments);
                if(String(url).includes('/api/world/inventory') && options?.body &&
                    JSON.parse(options.body).op==='take_up')pickupReplies.push(await response.clone().json());
                return response;};})()''')
        # Walk away normally, rather than relocating the eye independently of
        # its body. The old endpoint falsely accepted this grip, then the next
        # native step dropped it before the hand HUD could stay equipped.
        def key(code,down):
            self.page.send('Input.dispatchKeyEvent',{'type':'keyDown' if down else 'keyUp',
                'code':code,'key':code[-1].lower(),'windowsVirtualKeyCode':ord(code[-1])})
        def click_pick():
            self.page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            point=self.page.evaluate(f'''(()=>{{const r=banjoRoom;r.camera.updateMatrixWorld();const v=r.world.bodies.get({json.dumps(part)}).mesh
                .getWorldPosition(new r.THREE.Vector3()).project(r.camera);
                return {{x:(v.x+1)*innerWidth/2,y:(1-v.y)*innerHeight/2}};}})()''')
            self.assertTrue(0<point['x']<self.page.evaluate('innerWidth') and
                0<point['y']<self.page.evaluate('innerHeight'),point)
            hit=self.page.evaluate(f'document.elementFromPoint({point["x"]},{point["y"]})?.outerHTML?.slice(0,180)')
            self.assertIn('id="stage"',hit, {'point':point,'hit':hit})
            if touch:
                self.page.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[point]})
                # Real fingers move while tapping. This previously rotated
                # the camera and cancelled pickup at just 3 CSS pixels.
                self.page.send('Input.dispatchTouchEvent',{'type':'touchMove',
                    'touchPoints':[{**point,'x':point['x']+5,'y':point['y']+4}]})
                self.page.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
            else:
                for kind in ('mousePressed','mouseReleased'):
                    self.page.send('Input.dispatchMouseEvent',{'type':kind,**point,'button':'left','clickCount':1})
        key('KeyS',True);time.sleep(.8);key('KeyS',False);time.sleep(.4)
        click_pick();self.wait('pickupReplies.length>0')
        far=self.page.evaluate('pickupReplies.at(-1)')
        self.assertFalse(far['ok'],far)
        self.assertIn('Move closer',far['why'])
        pickup_log=app.runs_path/'interaction-events.jsonl'
        pickup_rows=[json.loads(s) for s in pickup_log.read_text(encoding='utf-8').splitlines()]
        pickup_result=next(r for r in reversed(pickup_rows) if r.get('event')=='inventory-result')
        self.assertFalse(pickup_result['ok'])
        self.assertIn('Move closer',pickup_result['why'])
        self.assertTrue(any(r.get('event')=='inventory-request' and r.get('id')==pickup_result['id']
            and r.get('op')=='take_up' and r.get('grip_m') for r in pickup_rows))
        self.assertIn('Move closer',self.page.evaluate('document.querySelector("#world-action-toast").textContent'))
        self.assertIsNone(self.page.evaluate('banjoRoom.held()'))
        self.assertEqual('',app.live.session.state.get('player_hands',{}).get(owner['id'],{}).get('holding',''))
        key('KeyW',True);time.sleep(.8);key('KeyW',False);time.sleep(.4)
        self.page.evaluate('''(()=>{const r=banjoRoom,p=r.world.bodies.get('field pick').mesh.position;
            r.lookAt(p.x,p.y,p.z);})()''')
        click_pick()
        time.sleep(2)
        observation=self.page.evaluate('({held:banjoRoom.held()?.name,mode:banjoRoom.use().mode,last:banjoRoom.world.last,camera:banjoRoom.camera.position.toArray()})')
        state=app.live.session.state
        observation['native']=state.get('native_players',{}).get(owner['id'])
        observation['hand']=state.get('player_hands',{}).get(owner['id'])
        observation['tool']=[b for b in state.get('bodies',[]) if b['name'] in ('field pick','field pick-g0')]
        observation['replies']=self.page.evaluate('pickupReplies.map(r=>({ok:r.ok,why:r.why,grip:r.room?.grip_m}))')
        self.assertEqual('field pick',observation.get('held'),observation)
        self.assertEqual('field pick',observation['hand']['holding'],observation)
        self.assertTrue(self.page.evaluate('document.body.classList.contains("panel-away")'))
        self.assertFalse(self.page.evaluate('document.body.classList.contains("chat-open")'))
        self.page.evaluate('window.beforePickupReload=true;location.reload()')
        self.wait('!window.beforePickupReload && window.banjoRoom?.ready() && banjoRoom.held()?.name==="field pick"')
        time.sleep(1)
        self.assertEqual('field pick',self.page.evaluate('banjoRoom.held()?.name'))
        self.assertEqual('field pick',app.live.session.state['player_hands'][owner['id']]['holding'])
        # Ordinary attempted use must leave linked intent/preflight/outcome
        # traces, even when refused. Keep the real native body and clock;
        # aim 6 m ahead, beyond shared reach, without modifying any tool pose.
        self.page.evaluate('''(()=>{const r=banjoRoom,p=r.camera.position;
            r.lookAt(p.x,r.groundAt(p.x,p.z-6),p.z-6);})()''')
        self.wait('banjoRoom.use().target?.enabled===false && !!banjoRoom.world.groundAim')
        x=self.page.evaluate('innerWidth/2');y=self.page.evaluate('innerHeight/2')
        if touch:
            self.page.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x,'y':y}]})
            self.page.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
        else:
            for kind in ('mousePressed','mouseReleased'):
                self.page.send('Input.dispatchMouseEvent',{'type':kind,'x':x,'y':y,'button':'left','clickCount':1})
        self.wait('!!banjoRoom.use().last?.refused')
        self.assertIn('step closer',self.page.evaluate('banjoRoom.use().last.refused').lower())
        until=time.monotonic()+10
        rows=[]
        while time.monotonic()<until:
            log=app.runs_path/'interaction-events.jsonl'
            rows=[json.loads(s) for s in log.read_text(encoding='utf-8').splitlines()] if log.exists() else []
            results=[r for r in rows if r.get('event')=='tool-result']
            if results and any(r.get('event')=='tool-reply' and r.get('id')==results[-1]['id'] for r in rows):break
            time.sleep(.1)
        self.assertTrue(results,rows)
        linked=[r for r in rows if r.get('id')==results[-1]['id']]
        self.assertEqual({r['event'] for r in linked},{'tool-press','tool-start','tool-request','tool-preflight','tool-result','tool-reply'})
        self.assertEqual({r['actor'] for r in linked},{linked[0]['actor']})
        self.assertEqual(next(r for r in linked if r['event']=='tool-press')['input'],'touch' if touch else 'mouse')
        self.assertIn('step closer',results[-1]['refused'].lower())
        self.assertEqual('field pick',results[-1]['hand']['holding'])
        observation['interaction_trace']={'linked_events':len(linked),'refused':results[-1]['refused']}
        observation['touch']=touch
        observation['far_refused']=far['why']
        observation['reload_keeps_native_hand']=True
        OUT.mkdir(parents=True,exist_ok=True)
        stem='native-body-pickup-touch' if touch else 'native-body-pickup'
        (OUT/(stem+'.json')).write_text(json.dumps(observation,indent=2),encoding='utf-8')
        (OUT/(stem+'.png')).write_bytes(base64.b64decode(self.page.send('Page.captureScreenshot')['data']))

    def test_mobile_controls_and_deliberate_panels_from_first_paint(self):
        if not qa_browser.CHROME.is_file():
            if os.environ.get('BANJO_BROWSER_TESTS') == 'required':self.fail('Chrome required')
            self.skipTest('Chrome unavailable')
        with mock.patch.object(ai.server.secrets,'randbelow',side_effect=[0,1]):
            ident,owner,app=self.setup_world(surface='columns')
        chrome=qa_browser.Chrome(390,844);self.addCleanup(chrome.close)
        page=chrome.page;page.send('Page.enable');page.send('Runtime.enable')
        def wait(expr,seconds=30):
            until=time.monotonic()+seconds
            while time.monotonic()<until:
                try:
                    if page.evaluate('Boolean('+expr+')'):return
                except (RuntimeError,TimeoutError):pass
                time.sleep(.04)
            self.fail(expr+' '+str(page.evaluate('({hit:document.elementFromPoint(innerWidth/2,80)?.outerHTML?.slice(0,250),size:[innerWidth,innerHeight],controls:window.banjoRoom?.controls()})')))
        url=self.base+f'/world?world={ident}&hold=1'
        page.send('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':1,'mobile':True})
        page.send('Emulation.setTouchEmulationEnabled',{'enabled':True,'maxTouchPoints':5})
        # A slow or failed module download must not paint an open sidebar.
        page.send('Emulation.setScriptExecutionDisabled',{'value':True})
        page.send('Page.navigate',{'url':url})
        wait('document.querySelector("#panel") && document.styleSheets.length >= 3')
        self.assertEqual('hidden',page.evaluate('getComputedStyle(document.querySelector("#panel")).visibility'))
        OUT.mkdir(parents=True,exist_ok=True)
        (OUT/'mobile-hud-before-javascript.png').write_bytes(base64.b64decode(
            page.send('Page.captureScreenshot',{'format':'png'})['data']))
        page.send('Emulation.setScriptExecutionDisabled',{'value':False})
        page.send('Page.addScriptToEvaluateOnNewDocument',{'source':"""
          window.unwantedPanelFrames=0;
          function observePaint(){const p=document.querySelector('#panel');
            if(p && getComputedStyle(p).visibility!=='hidden')window.unwantedPanelFrames++;
            requestAnimationFrame(observePaint)}requestAnimationFrame(observePaint);
        """})
        page.send('Page.navigate',{'url':url})
        wait('window.banjoRoom?.ready() && document.querySelector("#inventory-strip")')
        time.sleep(.3)
        self.assertEqual(0,page.evaluate('window.unwantedPanelFrames'))
        for width,height in ((390,844),(844,390),(360,640),(1280,800)):
            with self.subTest(viewport=(width,height)):
                page.send('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':width<1000})
                wait(f'innerWidth==={width} && innerHeight==={height}')
                page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                self.assertEqual('stage',page.evaluate('document.elementFromPoint(innerWidth/2,innerHeight/2)?.id'))
                page.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':width/2,'y':height/2}]})
                page.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
                wait('!document.querySelector("#stick").hidden',seconds=5)
                time.sleep(.15)
                layout=page.evaluate("""(()=>{const pad=document.querySelector('#stick'),r=pad.getBoundingClientRect();
                  const intersects=e=>{const b=e.getBoundingClientRect();return b.width && b.height &&
                    r.left<b.right && r.right>b.left && r.top<b.bottom && r.bottom>b.top};
                  const hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
                  return {onscreen:r.left>=0 && r.top>=0 && r.right<=innerWidth && r.bottom<=innerHeight,
                    reachable:!!hit?.closest('#stick') && [.2,.8].every(y=>!!document.elementFromPoint(r.left+r.width/2,r.top+r.height*y)?.closest('#stick')),
                    overlapsMenu:intersects(document.querySelector('#world-quickbar nav')),
                    overlapsInventory:intersects(document.querySelector('#inventory-strip')),
                    mapHidden:document.querySelector('#minimap').hidden,
                    previewHidden:document.querySelector('#material-preview').hidden,
                    panelHidden:getComputedStyle(document.querySelector('#panel')).visibility==='hidden'};})()""")
                self.assertEqual({'onscreen':True,'reachable':True,'overlapsMenu':False,
                    'overlapsInventory':False,'mapHidden':True,'previewHidden':True,'panelHidden':True},layout)
                (OUT/f'mobile-hud-{width}x{height}.png').write_bytes(base64.b64decode(
                    page.send('Page.captureScreenshot',{'format':'png'})['data']))
        # The pad receives real touch input and moves the player. Presentation
        # repair does not qualify native locomotion: use the existing walk mode.
        page.evaluate('window.dispatchEvent(new CustomEvent("banjo-movement-mode",{detail:"gravity"}))')
        before=page.evaluate('banjoRoom.camera.position.toArray()')
        center=page.evaluate('(()=>{const r=document.querySelector("#stick").getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()')
        page.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[center]})
        page.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':center['x'],'y':center['y']-35}]})
        wait('document.querySelector("#stick").dataset.held==="yes"')
        time.sleep(.35)
        page.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
        after=page.evaluate('banjoRoom.camera.position.toArray()')
        self.assertGreater(math.hypot(after[0]-before[0],after[2]-before[2]),.05)
        wait('document.querySelector("#stick").dataset.held==="no"')
        self.assertIsNone(page.evaluate('document.querySelector("#panel-details")'))
        page.evaluate('[...document.querySelectorAll("#world-quickbar button")].find(b=>b.textContent==="Chat /").click()')
        wait('document.body.classList.contains("chat-open") && getComputedStyle(document.querySelector("#talk")).display!=="none"')
        self.assertTrue(page.evaluate('getComputedStyle(document.querySelector("#details")).display==="none" && getComputedStyle(document.querySelector("#panel [data-game-menu]")).display==="none"'))
        page.evaluate('window.beforeReload=true;location.reload()')
        wait('!window.beforeReload && window.banjoRoom?.ready()')
        time.sleep(.3)
        self.assertEqual(0,page.evaluate('window.unwantedPanelFrames'))
        self.assertFalse(page.evaluate('document.body.classList.contains("chat-open")'))
        # The folded World state must not shrink the shared Workshop chat.
        page.send('Page.navigate',{'url':self.base+f'/world?world={ident}&workshop=1&tab=market'})
        wait('document.body.classList.contains("workshop-mode") && document.querySelector("#ws-component-chat-text") && !document.querySelector("#ws-component-chat-text").disabled')
        self.assertFalse(page.evaluate('document.body.classList.contains("ws-chat-open")'))
        page.evaluate('[...document.querySelectorAll(".game-bottom-tabs button")].find(b=>b.textContent==="Chat /").click()')
        wait('document.body.classList.contains("ws-chat-open")')
        self.assertGreater(page.evaluate('document.querySelector(".ws-left").getBoundingClientRect().width'),200)
        self.assertEqual('visible',page.evaluate('getComputedStyle(document.querySelector(".ws-left")).visibility'))
        page.send('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':1,'mobile':True})
        wait('!document.body.classList.contains("ws-chat-open")')
        page.evaluate('[...document.querySelectorAll(".game-bottom-tabs button")].find(b=>b.textContent==="Chat /").click()')
        self.assertGreater(page.evaluate('document.querySelector(".ws-left").getBoundingClientRect().width'),200)
        self.assertFalse([e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])

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
                try:
                    if page.evaluate('Boolean('+expr+')'):return
                except (RuntimeError,TimeoutError):pass   # mid-navigation
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
        # The chat box lives in the rail and is shown by the bottom bar's
        # Chat control (dcd94bae). Open it the way a player does, go back to
        # the world, then focus the visible box: focusing it alone must free
        # the cursor again.
        page.evaluate('[...document.querySelectorAll("button")].find(b=>b.textContent==="Chat /").click()')
        wait('document.querySelector("#ask-text").getBoundingClientRect().width>0')
        self.assertTrue(page.evaluate('banjoRoom.controls().cursorFree'))
        click(400,400)
        self.assertFalse(page.evaluate('banjoRoom.controls().cursorFree'))
        self.assertNotEqual('ask-text',page.evaluate('document.activeElement?.id'))
        page.evaluate('[...document.querySelectorAll("button")].find(b=>b.textContent==="Chat /").click()')
        self.assertEqual('ask-text',page.evaluate('document.activeElement?.id'))
        self.assertTrue(page.evaluate('banjoRoom.controls().cursorFree'))
        yaw=page.evaluate('banjoRoom.controls().yaw')
        page.send('Input.dispatchMouseEvent',{'type':'mouseMoved','x':edge,'y':400})
        time.sleep(.25)
        self.assertEqual(yaw,page.evaluate('banjoRoom.controls().yaw'))
        self.assertFalse([e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])
        # Mark this document so the wait below cannot pass on the old page
        # before the reload has replaced it.
        page.evaluate('window.beforeReload=true;localStorage.setItem("banjo.movement","old-walk");location.reload()')
        wait('!window.beforeReload && window.banjoRoom?.ready()')
        # An unknown stored choice falls back to the game's default: a body
        # (the owner's call, 2026-10-04).
        self.assertEqual('native',page.evaluate('banjoRoom.controls().movementMode'))
        OUT.mkdir(parents=True,exist_ok=True)
        (OUT/'world-navigation.json').write_text(json.dumps({'walk_m_s':rates[0],
            'run_m_s':rates[1],'edge_turn_rad_in_055_s':turned,'cursor_stops_look_and_keys':True,
            'resume_click_preserves_hand':True,'escape_preserves_selection':True,
            'legacy_movement_preference_uses_gravity':True,
            'native_terrain_seed':app.room.spec['terrain']['generate']['seed']},indent=2)+'\n',encoding='utf-8')
        (OUT/'world-navigation.png').write_bytes(base64.b64decode(
            page.send('Page.captureScreenshot',{'format':'png'})['data']))

    def test_click_joined_tool_parts_and_slash_opens_only_chat(self):
        # Native pickup of both constituents, including a first tap in cursor
        # mode. Use real pointer/touch events; no mocked hit or pickup result.
        for part,width,height,touch in [('field pick-g0',1280,800,False),
                                      ('field pick',844,390,True)]:
            with self.subTest(part=part,touch=touch):
                with mock.patch.object(ai.server.secrets,'randbelow',side_effect=[0,1]):
                    ident,owner,app=self.setup_world(surface='columns')
                screens.GameScreens.browser(self,ident,owner)
                # Hold a fixed observer before projecting a thin component's
                # click ray. Normal walking has its separate transition test.
                self.page.evaluate('localStorage.setItem("banjo.movement","fly")')
                self.page.send('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,
                    'deviceScaleFactor':1,'mobile':touch})
                if touch:self.page.send('Emulation.setTouchEmulationEnabled',{'enabled':True,'maxTouchPoints':5})
                self.page.send('Page.navigate',{'url':self.base+f'/world?world={ident}'})
                self.wait('banjoRoom?.ready() && document.querySelector("#panel-state").textContent==="Live."')
                self.assertTrue(self.page.evaluate('document.body.classList.contains("panel-away")'))
                self.assertIsNone(self.page.evaluate('document.querySelector("#panel-details")'))
                self.page.evaluate(f'''(()=>{{const r=banjoRoom,p=r.world.bodies.get({json.dumps(part)}).mesh.position;
                    r.standAt(p.x,r.groundAt(p.x,p.z+1)+1.62,p.z+1.0);r.lookAt(p.x,p.y,p.z);}})()''')
                self.wait('!banjoRoom.world.busy && !banjoRoom.world.acting')
                if touch:
                    # Slash opened chat, then the first world tap closes it
                    # and picks up the item rather than consuming the tap.
                    self.page.send('Input.dispatchKeyEvent',{'type':'keyDown','code':'Slash','key':'/','windowsVirtualKeyCode':191})
                    self.wait('document.body.classList.contains("chat-open")')
                point=self.page.evaluate(f'''(()=>{{const r=banjoRoom,
                    v=r.world.bodies.get({json.dumps(part)}).mesh.getWorldPosition(new r.THREE.Vector3()).project(r.camera);
                    return {{x:(v.x+1)*innerWidth/2,y:(1-v.y)*innerHeight/2}};}})()''')
                self.page.evaluate('''(()=>{window.pickupEvents=[];for(const type of ['pointerdown','pointerup'])
                    document.querySelector('#stage').addEventListener(type,e=>pickupEvents.push({type,x:e.clientX,y:e.clientY,button:e.button}));})()''')
                if touch:
                    self.page.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[point]})
                    self.page.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
                else:
                    for kind in ('mousePressed','mouseReleased'):
                        self.page.send('Input.dispatchMouseEvent',{'type':kind,**point,'button':'left','clickCount':1})
                try:self.wait('banjoRoom.held()?.name==="field pick" && banjoRoom.use().mode==="tool-ready"',seconds=12)
                except AssertionError:
                    self.fail(str(self.page.evaluate('({events:pickupEvents,hit:document.elementFromPoint(innerWidth/2,innerHeight/2)?.id,held:banjoRoom.held()?.name,use:banjoRoom.use().mode,aim:banjoRoom.world.aim,last:banjoRoom.world.last,controls:banjoRoom.controls(),camera:banjoRoom.camera.position.toArray()})')))
                self.assertEqual('field pick',app.live.session.state['hand']['holding'])
                self.assertTrue(self.page.evaluate('document.body.classList.contains("panel-away")'))
                self.assertFalse(self.page.evaluate('document.body.classList.contains("chat-open")'))
                # Selection alone cannot unfold the rail, including a machine.
                # Pickup success is not digging success. Use the actual starter
                # tool through ordinary mouse/touch input, with a fixed fly
                # camera to isolate targeting from walking-controller timing.
                self.page.evaluate('window.dispatchEvent(new CustomEvent("banjo-movement-mode",{detail:"fly"}))')
                self.page.evaluate('''(()=>{const r=banjoRoom;
                    r.standAt(-.9,r.groundAt(-.9,.025)+1.62,.025);
                    r.lookAt(.125,r.groundAt(.125,.025),.025);
                    window.digReplies=[];window.digRequests=[];
                    const original=window.fetch;window.fetch=async function(url,options){
                        const response=await original.apply(this,arguments);
                        if(String(url).includes('/api/world/tool/use')) {
                            digRequests.push(JSON.parse(options.body));
                            digReplies.push(await response.clone().json());
                        }return response;
                    };})()''')
                center={'x':width/2,'y':height/2}
                self.page.send('Input.dispatchMouseEvent',{'type':'mouseMoved',**center})
                self.wait('banjoRoom.use().target?.feedback?.ready && !banjoRoom.world.busy')
                self.wait('document.querySelector("#crosshair").dataset.readiness==="ready"')
                self.assertEqual('ready',self.page.evaluate('document.querySelector("#crosshair").dataset.readiness'))
                OUT.mkdir(parents=True,exist_ok=True)
                # Observe actual draw callbacks, rather than a stubbed renderer.
                self.page.evaluate('''(()=>{window.drawnBodies=new Set();window.drawnAttachments=new Set();const r=banjoRoom;
                    for(const [name,entry] of r.world.bodies)entry.mesh.traverse(mesh=>{
                        if(!mesh.isMesh)return;const original=mesh.onBeforeRender;
                        mesh.onBeforeRender=function(){drawnBodies.add(name);return original.apply(this,arguments);};
                    });r.scene.traverse(mesh=>{if(!mesh.userData.follows)return;
                        const original=mesh.onBeforeRender;mesh.onBeforeRender=function(){
                            drawnAttachments.add(mesh.userData.follows);return original.apply(this,arguments);};
                    });})()''')
                self.wait('drawnBodies.size>0')
                drawn=self.page.evaluate('({held:banjoRoom.world.held.pick.parts,drawn:[...drawnBodies],attachments:[...drawnAttachments]})')
                (OUT/f'dig-render-{width}x{height}.json').write_text(json.dumps(drawn,indent=2),encoding='utf-8')
                self.assertFalse(set(drawn['held']) & set(drawn['drawn']),drawn)
                self.assertFalse(set(drawn['held']) & set(drawn['attachments']),drawn)
                OUT.mkdir(parents=True,exist_ok=True)
                (OUT/f'dig-green-{width}x{height}.png').write_bytes(base64.b64decode(self.page.send('Page.captureScreenshot')['data']))
                press={**center,'x':width*.56} if touch else center
                if touch:
                    self.page.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[press]})
                    self.page.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
                else:
                    for kind in ('mousePressed','mouseReleased'):
                        self.page.send('Input.dispatchMouseEvent',{'type':kind,**press,'button':'left','clickCount':1})
                self.wait('digReplies.length===1 && banjoRoom.use().mode==="tool-ready"',seconds=20)
                response=self.page.evaluate('digReplies[0]');request=self.page.evaluate('digRequests[0]')
                self.assertNotIn('refused',response,response)
                self.assertGreater(response['result']['loosened_kg'],0,response)
                grid=self.page.evaluate('banjoRoom.groundDrawn()');q=grid['dx']
                def column(at):
                    return (math.floor((at[0]-grid['x0'])/q+.5),math.floor((at[2]-grid['z0'])/q+.5))
                target=column(request['at_m'])
                pieces=app.live.session.send(op='ground-debris')['ground_debris']['bodies']
                self.assertTrue(pieces,'successful digging must release native matter')
                for piece in pieces:
                    for cell in piece['cells']:
                        self.assertEqual(target,column(cell['source_center_m']),'an unselected column was removed')
                self.assertTrue(self.page.evaluate('document.body.classList.contains("panel-away")'))
                (OUT/f'dig-result-{width}x{height}.png').write_bytes(base64.b64decode(self.page.send('Page.captureScreenshot')['data']))
                (OUT/f'dig-input-{width}x{height}.json').write_text(json.dumps({
                    'touch':touch,'screen_press':press,'selected_column':target,'request_at_m':request['at_m'],
                    'timing':response.get('timing'),'result':response['result'],
                    'released_components':len(pieces)},indent=2),encoding='utf-8')
                self.page.evaluate('banjoRoom.pick("rover")')
                self.assertTrue(self.page.evaluate('document.body.classList.contains("panel-away")'))
                self.page.send('Input.dispatchKeyEvent',{'type':'keyDown','code':'Slash','key':'/','windowsVirtualKeyCode':191})
                self.wait('document.body.classList.contains("chat-open") && document.activeElement.id==="ask-text"')
                self.wait('Math.abs(document.querySelector("#panel").getBoundingClientRect().right-innerWidth)<1')
                visible=self.page.evaluate('''(()=>{const p=document.querySelector('#panel');return {
                    body:[...p.children].filter(e=>getComputedStyle(e).display!=='none').map(e=>e.id||e.tagName),
                    header:[...p.querySelector(':scope > header').children].filter(e=>getComputedStyle(e).display!=='none').map(e=>e.id||e.tagName)};})()''')
                self.assertEqual(['HEADER','talk'],visible['body'])
                self.assertEqual(['panel-fold','H1'],visible['header'])
                OUT.mkdir(parents=True,exist_ok=True)
                (OUT/f'chat-only-{width}x{height}.png').write_bytes(base64.b64decode(
                    self.page.send('Page.captureScreenshot')['data']))
                self.page.send('Input.dispatchKeyEvent',{'type':'keyDown','code':'Escape','key':'Escape','windowsVirtualKeyCode':27})
                self.wait('!document.body.classList.contains("chat-open") && document.body.classList.contains("panel-away")')
                self.assertEqual('field pick',self.page.evaluate('banjoRoom.held()?.name'))
                self.chrome.close()

if __name__=='__main__':unittest.main(verbosity=2)
