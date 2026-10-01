"""Ordinary browser tool discovery, native primary/F strokes, capacity and H heap.

The observer is placed on surveyed ground for repeatability. This verifies input
and native tool/carry/deposit behavior, not physical-avatar locomotion or private
per-player ground ownership.
"""
import base64
import json
from pathlib import Path
import time
import unittest
from unittest import mock
import world_goods_tests as flow

ROOT=Path(__file__).resolve().parents[1]


class GatheringJourney(unittest.TestCase):
    setUp=flow.GoodsJourney.setUp
    tearDown=flow.GoodsJourney.tearDown
    start=flow.GoodsJourney.start
    stop=flow.GoodsJourney.stop
    get=flow.GoodsJourney.get
    post=flow.GoodsJourney.post
    join=flow.GoodsJourney.join
    setup_world=flow.GoodsJourney.setup_world

    def test_find_equip_dig_full_heap_and_resume_use_native_operations(self):
        if not flow.qa_browser.CHROME.is_file():self.skipTest('Chrome not installed')
        with mock.patch.object(flow.server.secrets,'randbelow',side_effect=[0,851269740]):
            world,owner,app=self.setup_world()
        chrome=flow.qa_browser.Chrome(1280,800);self.addCleanup(chrome.close)
        p=chrome.page;p.send('Page.enable');p.send('Runtime.enable')
        p.send('Page.navigate',{'url':self.base+f'/world?world={world}&hold=1'})
        def wait(expr,seconds=40):
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline:
                if p.evaluate('Boolean('+expr+')'):return
                time.sleep(.1)
            self.fail(expr+'; '+str(p.evaluate('document.querySelector("#details-last-text")?.textContent')))
        def key(code):
            for kind in ('keyDown','keyUp'):
                p.send('Input.dispatchKeyEvent',{'type':kind,'code':code,'key':code[-1].lower()})
        def click(selector):
            point=p.evaluate('''(()=>{const e=document.querySelector(%s);
                const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()'''%json.dumps(selector))
            for kind in ('mousePressed','mouseReleased'):
                p.send('Input.dispatchMouseEvent',{'type':kind,'button':'left','clickCount':1,**point})
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        def shot(tag):
            (out/f'gathering-{tag}.png').write_bytes(base64.b64decode(p.send('Page.captureScreenshot',{'format':'png'})['data']))
        def aim(x,z):
            p.evaluate(f'banjoRoom.standAt({x-1.2},banjoRoom.groundAt({x-1.2},{z})+1.62,{z});banjoRoom.lookAt({x},banjoRoom.groundAt({x},{z}),{z});document.activeElement.blur()')
            time.sleep(.4)
        def stroke(code):
            p.evaluate('banjoRoom.world.use.last=null')
            key(code);wait('banjoRoom.world.use.last && banjoRoom.world.use.mode==="tool-ready"')
            return p.evaluate('banjoRoom.world.use.last')
        wait('window.banjoRoom?.ready()')
        p.evaluate('document.activeElement.blur()');key('KeyF')
        wait('document.querySelector("#details-last-text").textContent.includes("Tool needed")')
        self.assertEqual(0,p.evaluate('banjoRoom.world.carriedGround.sand_kg+banjoRoom.world.carriedGround.soil_kg'))
        before=p.evaluate('banjoRoom.camera.position.toArray()')
        click('[data-find-tool]')
        wait('document.querySelector("#picked").textContent.includes("Field Pick")')
        self.assertEqual(before,p.evaluate('banjoRoom.camera.position.toArray()'),'Find turns the view without teleporting')
        shot('found')
        p.evaluate('''(()=>{const a=banjoRoom.world.bodies.get("field pick").mesh.position;
            banjoRoom.standAt(a.x-.8,banjoRoom.groundAt(a.x,a.z)+1.62,a.z);
            banjoRoom.lookAt(a.x,a.y,a.z);document.activeElement.blur();banjoRoom.resume();})()''')
        time.sleep(.6);key('KeyE')
        wait('banjoRoom.world.held?.pick && banjoRoom.world.use.mode==="tool-ready"')
        aim(.3,.025)
        wait('document.querySelector("#details-actions").textContent.includes("dig here")')
        self.assertNotIn('Study tool',p.evaluate('document.querySelector("#details-actions").textContent'))
        strokes=[]
        for i in range(6):
            answer=stroke('KeyJ' if i==0 else 'KeyF');strokes.append(answer)
            if answer.get('refused'):break
            self.assertTrue(answer['result']['supported'],answer)
            self.assertGreater(answer['result']['work_j'],0)
        self.assertIn('Load full',strokes[-1].get('refused',''))
        self.assertEqual([],strokes[-1]['done'],'A full load starts no stroke')
        self.assertGreater(strokes[0]['result']['loosened_kg'],0)
        self.assertGreater(strokes[1]['result']['loosened_kg'],0,'F must run the actual tool too')
        full=p.evaluate('banjoRoom.world.carriedGround')
        self.assertLessEqual(full['total_kg'],full['limit_kg']+.02) # native sampled mass reports round to .01 kg
        wait('document.querySelector("#world-load-meter").dataset.full==="true"')
        self.assertIn('H to heap',p.evaluate('document.querySelector("#world-load-meter").textContent'))
        self.assertTrue(p.evaluate('document.querySelector("#world-load-meter a").href.includes("tab=inventory")'))
        shot('full')
        aim(-1,-.8);key('KeyH')
        wait('document.querySelector("#details-last-text").textContent.startsWith("Heaped")')
        emptied=p.evaluate('banjoRoom.world.carriedGround')
        self.assertAlmostEqual(0,emptied['sand_kg']+emptied['soil_kg'],places=6)
        self.assertAlmostEqual(emptied['objects_kg'],emptied['total_kg'],places=6)
        wait('document.querySelector("#world-load-meter").dataset.full==="false"')
        shot('emptied')
        aim(.3,.65);answer=stroke('KeyF')
        self.assertNotIn('refused',answer)
        self.assertGreater(answer['result']['loosened_kg'],0,'Emptying allows another measured stroke')
        self.assertEqual([],[e for e in p.events if e.get('method')=='Runtime.exceptionThrown'])
        (out/'gathering-journey.json').write_text(json.dumps({'strokes':strokes,'full':full,
            'emptied':emptied,'resumed':answer},indent=2))


if __name__=='__main__':unittest.main()
