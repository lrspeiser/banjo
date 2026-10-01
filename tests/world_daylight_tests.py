"""Native sun/store -> API -> rendered day, shadows, lamp and battery flow."""
import base64
import json
import math
from pathlib import Path
import time
import unittest
from unittest import mock

import world_goods_tests as flow

ROOT = Path(__file__).resolve().parents[1]

# Compare actual GPU pixels with the directional shadow on/off in one task.
# Restore before returning; this diagnoses rendering, never changes native state.
SHADOW_PIXELS = """(() => {
 const r=banjoRoom, light=r.scene.getObjectByName('sun-light');
 const gl=r.renderer.getContext(), w=gl.drawingBufferWidth,h=gl.drawingBufferHeight;
 const grab=()=>{r.renderer.render(r.scene,r.camera);const a=new Uint8Array(w*h*4);
   gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,a);return a;};
 const saved=light.castShadow, a=grab(); light.castShadow=false;const b=grab();
 light.castShadow=saved;r.renderer.render(r.scene,r.camera);
 let n=0,xsum=0,ysum=0;
 for(let y=0;y<h*.65;y++)for(let x=0;x<w*.65;x++){
   const i=(y*w+x)*4;
   if(b[i]+b[i+1]+b[i+2]-a[i]-a[i+1]-a[i+2]>6){n++;xsum+=x;ysum+=y;}}
 return {pixels:n,centre:n?[xsum/n,ysum/n]:null};
})()"""


class DaylightJourney(unittest.TestCase):
    setUp = flow.GoodsJourney.setUp
    tearDown = flow.GoodsJourney.tearDown
    start = flow.GoodsJourney.start
    stop = flow.GoodsJourney.stop
    get = flow.GoodsJourney.get
    post = flow.GoodsJourney.post
    join = flow.GoodsJourney.join
    setup_world = flow.GoodsJourney.setup_world
    batch = flow.GoodsJourney.batch
    test_native_day_cycle = flow.GoodsJourney.test_day_cycle_charges_real_store_and_night_lamp_consumes_it

    def test_native_daylight_reaches_visible_sun_shadows_and_energy_panel(self):
        if not flow.qa_browser.CHROME.is_file(): self.skipTest('Chrome not installed')
        with mock.patch.object(flow.server.secrets, 'randbelow', side_effect=[0,851269740]):
            world,owner,app = self.setup_world()
        chrome=flow.qa_browser.Chrome(1280,800);self.addCleanup(chrome.close)
        p=chrome.page;p.send('Page.enable');p.send('Runtime.enable')
        p.send('Page.navigate',{'url':self.base+f'/world?world={world}&hold=1'})
        def wait(expression):
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                if p.evaluate(expression):return
                time.sleep(.08)
            self.fail(expression)
        wait('window.banjoRoom?.ready()');p.evaluate('banjoRoom.hold()')
        lamp=app.live.session.state['machines']['lamps'][0]
        x,y,z=lamp['at_m']
        def ground_view():
            p.evaluate(f'banjoRoom.standAt({x+3},{y+1.8},{z+4});banjoRoom.lookAt({x+1.5},{y-.4},{z})')
        def advance(hour=None):
            if hour is not None:
                app.live.session.send(op='sun',day_s=600,noon_elevation_deg=60,hour=hour,irradiance_w_m2=1000)
            t=p.evaluate('banjoRoom.world.clock')
            p.evaluate('banjoRoom.resume()')
            wait(f'banjoRoom.world.clock>{t+.6}')
            p.evaluate('banjoRoom.hold()');time.sleep(.1)
        def battery(name='solar farm'):
            p.evaluate(f'banjoRoom.pick({json.dumps(name)})')
            wait('!!document.querySelector(".pk-battery")')
            return p.evaluate('''(()=>{const e=document.querySelector('.pk-battery');
                return {text:e.textContent,...e.dataset};})()''')
        outdir=ROOT/'build/resource-flow';outdir.mkdir(parents=True,exist_ok=True)
        evidence=[];shadows=[]
        for hour,tag in ((8,'morning'),(12,'noon'),(20,'night')):
            ground_view();advance(hour)
            state=p.evaluate('({sun:banjoRoom.world.sun, stores:banjoRoom.world.machines.stores, lamps:banjoRoom.world.machines.lamps})')
            native=app.live.session.state
            self.assertEqual(native['sun'],state['sun'])
            store=next(s for s in state['stores'] if s['id']==lamp['store'])
            row=battery();self.assertEqual(store['charge_j'],float(row['chargeJ']))
            self.assertEqual(store['capacity_j'],float(row['capacityJ']))
            self.assertIn('MJ /',row['text'])
            disc=p.evaluate('''(()=>{const r=banjoRoom,s=r.scene.getObjectByName('sun-disc');
                return {visible:s.visible,toward:s.position.clone().sub(r.camera.position).normalize().toArray()};})()''')
            self.assertEqual(hour!=20,disc['visible'])
            if hour!=20:
                for a,b in zip(disc['toward'],state['sun']['toward']):self.assertAlmostEqual(a,b,places=4)
                self.assertGreater(float(row['flowW']),0);self.assertGreater(store['taken_j'],0)
                self.assertFalse(state['lamps'][0]['lit'])
                shadow=p.evaluate(SHADOW_PIXELS);self.assertGreater(shadow['pixels'],100)
                shadows.append(shadow)
            else:
                self.assertTrue(state['lamps'][0]['lit']);self.assertEqual(20,state['lamps'][0]['drawn_w'])
                self.assertAlmostEqual(-20,float(row['flowW']),delta=.01)
                self.assertIn('out',battery('camp light')['text'])
            pixels=p.evaluate(flow.qa_browser.SEEN)
            evidence.append(dict(tag=tag,state=state,battery=row,pixels=pixels,disc=disc))
            (outdir/f'daylight-verified-{tag}.png').write_bytes(base64.b64decode(p.send('Page.captureScreenshot',{'format':'png'})['data']))
            if hour==8:
                p.evaluate('''(()=>{const r=banjoRoom,d=r.scene.getObjectByName('sun-disc').position;
                    const right=new r.THREE.Vector3(1,0,0).applyQuaternion(r.camera.quaternion);
                    const at=d.clone().addScaledVector(right,20);r.lookAt(at.x,at.y,at.z);})()''')
                time.sleep(.1)
                bright=p.evaluate('''(()=>{const r=banjoRoom,g=r.renderer.getContext();
                    r.renderer.render(r.scene,r.camera);const a=new Uint8Array(4);
                    const at=r.scene.getObjectByName('sun-disc').position.clone().project(r.camera);
                    g.readPixels((at.x+1)*g.drawingBufferWidth/2,(at.y+1)*g.drawingBufferHeight/2,1,1,g.RGBA,g.UNSIGNED_BYTE,a);
                    return [...a];})()''')
                self.assertGreater(min(bright[:3]),180)
                (outdir/'daylight-verified-sun.png').write_bytes(base64.b64decode(p.send('Page.captureScreenshot',{'format':'png'})['data']))
        self.assertGreater(math.dist(shadows[0]['centre'],shadows[1]['centre']),5)
        self.assertLess(evidence[2]['pixels']['mean_luma'],evidence[1]['pixels']['mean_luma']*.3)
        # Physically unwire the lamp, then observe the same night camera.
        app.live.session.send(op='lamp_wire',lamp=lamp['id'],store=0,cable=0)
        advance();self.assertFalse(p.evaluate('banjoRoom.world.machines.lamps[0].lit'))
        dark=p.evaluate(flow.qa_browser.SEEN)
        self.assertGreater(evidence[2]['pixels']['mean_luma']-dark['mean_luma'],1)
        (outdir/'daylight-verified-unwired.png').write_bytes(base64.b64decode(p.send('Page.captureScreenshot',{'format':'png'})['data']))
        app.live.session.send(op='lamp_wire',lamp=lamp['id'],store=lamp['store'],cable=lamp['cable'])
        advance(8);self.assertFalse(p.evaluate('banjoRoom.world.machines.lamps[0].lit'))
        self.assertGreater(float(battery()['flowW']),0)
        (outdir/'daylight-verified.json').write_text(json.dumps(dict(phases=evidence,shadows=shadows,unwired=dark),indent=2))
        self.assertEqual([],[e for e in p.events if e.get('method')=='Runtime.exceptionThrown'])


if __name__=='__main__':unittest.main()
