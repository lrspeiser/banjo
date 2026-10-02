"""Material candidates and actual player collection agree; inspection grants nothing."""
from copy import deepcopy
import base64
import json
import os
from pathlib import Path
import sys
import time
import unittest
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
        materials=page.evaluate('[...document.querySelectorAll("#material-preview [data-method=dig]")].map(e=>e.dataset.material)')
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
        self.assertAlmostEqual(receipt['loosened_kg'],sum(carried.get(k,0) for k in ('soil_kg','sand_kg')),delta=5e-6)
        self.assertEqual(reserve,app.brains.goods.reserve_kg(deposit),'A pick use must not award the rover ledger ore')
        self.assertFalse([e for e in page.events if e.get('method')=='Runtime.exceptionThrown'])
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/'material-preview.png').write_bytes(base64.b64decode(page.send('Page.captureScreenshot',{'format':'png'})['data']))
        (out/'material-preview.json').write_text(json.dumps({'native_seed':app.room.spec['terrain']['generate']['seed'],
            'preview':materials,'receipt':receipt,'carried':carried,
            'ore_reserve_before':reserve,'ore_reserve_after':app.brains.goods.reserve_kg(deposit),'exceptions':[]},indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':unittest.main()
