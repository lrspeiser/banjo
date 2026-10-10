"""Ordinary browser tool discovery, native primary/F strokes, piles and collection.

The observer is placed on surveyed ground for repeatability. This verifies input
and native tool/carry/deposit behavior, not physical-avatar locomotion or private
per-player ground ownership.

Since 5af65746 (docs/automatic-excavation-piles-checkpoint.md) a named world
exports every stroke's measured output to a nearby material pile, so the hand
never fills and digging never stops at "Load full"; the pile is collected by
an ordinary click into private Inventory. The capacity refusal itself is held
by tests/tool_use_tests.py for worlds without automatic piles.
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
    personal=flow.GoodsJourney.personal

    def test_find_equip_dig_to_pile_collect_and_resume_use_native_operations(self):
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
        # Find tool is offered over the room once digging is refused for want
        # of a tool. It sat in the Details rail, which eaf9e306 removed, and
        # could not be pressed: it must be on screen and under the pointer.
        wait('(b=>{if(!b||!b.checkVisibility())return false;const r=b.getBoundingClientRect(),'
             'e=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return !!e && b.contains(e)})'
             '(document.querySelector("[data-find-tool]"))')
        click('[data-find-tool]')
        wait('document.querySelector("#picked").textContent.includes("Field Pick")')
        self.assertEqual(before,p.evaluate('banjoRoom.camera.position.toArray()'),'Find turns the view without teleporting')
        shot('found')
        p.evaluate('''(()=>{const a=banjoRoom.world.bodies.get("field pick").mesh.position;
            banjoRoom.standAt(a.x-.8,banjoRoom.groundAt(a.x,a.z)+1.62,a.z);
            banjoRoom.lookAt(a.x,a.y,a.z);document.activeElement.blur();banjoRoom.resume();})()''')
        time.sleep(.6);key('KeyE')
        wait('banjoRoom.world.held?.pick && banjoRoom.world.use.mode==="tool-ready"')
        wait('document.querySelector("[data-tool-guide]").hidden')   # wanted no more
        # The held tool's skill progress and its Skills link ride on the tool's
        # hand card. They were in the right rail until it became chat only
        # (eaf9e306), where no player could see them: on screen and pressable.
        skill='document.querySelector("#hand-slots [data-hand] .hand-skill")'
        wait('(l=>!!l && l.checkVisibility() && l.querySelector("b").textContent.length>0'
             ' && l.querySelector("a").href.includes("tab=skills"))('+skill+')')
        aim(.3,.025)
        wait('document.querySelector("#details-actions").textContent.includes("dig here")')
        self.assertNotIn('Study tool',p.evaluate('document.querySelector("#details-actions").textContent'))
        def carried_ground():
            c=p.evaluate('banjoRoom.world.carriedGround')
            return c['sand_kg']+c['soil_kg']+c.get('rock_kg',0)
        def excavated():   # the server's own ledger, not the page's rounded copy
            return {q['name']:dict(q['holds']) for q in app.brains.goods.stockpiles if q.get('excavated')}
        strokes=[]
        for i in range(4):
            answer=stroke('KeyJ' if i==0 else 'KeyF');strokes.append(answer)
            self.assertNotIn('refused',answer)
            self.assertTrue(answer['result']['supported'],answer)
            self.assertGreater(answer['result']['work_j'],0)
            self.assertGreater(answer['result']['loosened_kg'],0,'F must run the actual tool too' if i else answer)
            self.assertIn('nearby pile',answer['said'],answer)
            # Every stroke's measured output leaves the hand: nothing builds up
            # towards a load limit, so no stroke is ever refused as full.
            self.assertAlmostEqual(0,carried_ground(),places=6)
        piles=excavated()
        self.assertTrue(piles,'the measured output went to a pile')
        dug=sum(s['result']['loosened_kg'] for s in strokes)
        held=sum(sum(h.values()) for h in piles.values())
        self.assertAlmostEqual(dug,held,delta=1e-4*len(strokes),msg=f'piles hold what was dug: {piles}')
        self.assertNotEqual('true',p.evaluate('document.querySelector("#world-load-meter").dataset.full'))
        self.assertIn('No weight limit',p.evaluate('document.querySelector("#world-load-meter").textContent'))
        self.assertTrue(p.evaluate('document.querySelector("#world-load-meter a").href.includes("tab=inventory")'))
        shot('piled')
        # The page joins as its own guest; whoever it is, exactly that one
        # player's private ledger gains the whole pile and nobody else's moves.
        def ledgers():return {pid:self.personal(app,{'id':pid}) for pid in app.room.player_records}
        before=ledgers()
        wait('!document.querySelector("#collect-output").hidden')
        click('#collect-output')
        wait('document.querySelector("#details-last-text").textContent.includes("Inventory")')
        emptied=excavated()
        self.assertTrue(all(not h for h in emptied.values()),f'a click takes the whole pile: {emptied}')
        after=ledgers()
        gained=[pid for pid in after if after[pid]!=before.get(pid,{})]
        self.assertEqual(1,len(gained),f'one collector is credited: {before} -> {after}')
        self.assertNotEqual(owner['id'],gained[0],'the page collected for itself, not the fixture owner')
        for name,holds in piles.items():
            for substance,kg in holds.items():
                self.assertAlmostEqual(before.get(gained[0],{}).get(substance,0)+kg,
                                       after[gained[0]].get(substance,0),delta=5e-5)
        shot('collected')
        aim(.3,.65);answer=stroke('KeyF')
        self.assertNotIn('refused',answer)
        self.assertGreater(answer['result']['loosened_kg'],0,'Collecting leaves digging free to go on')
        self.assertAlmostEqual(0,carried_ground(),places=6)
        # Successful saved digging earned the pick's skill; its hand card says
        # so, and its link opens Skills on that technique.
        wait(skill+'?.querySelector("output").textContent==="1 / 1"')
        link=p.evaluate(skill+'.querySelector("a").href')
        self.assertIn('technique=',link)
        wait('(a=>{const r=a.getBoundingClientRect(),e=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);'
             'return r.width>0 && !!e && a.contains(e)})('+skill+'.querySelector("a"))')
        shot('skill-on-hand')
        self.assertEqual([],[e for e in p.events if e.get('method')=='Runtime.exceptionThrown'])
        click('#hand-slots [data-hand] .hand-skill a')
        wait('location.search.includes("tab=skills") && document.querySelector("#ws-tree")?.textContent.includes("Gathering by hand")')
        (out/'gathering-journey.json').write_text(json.dumps({'strokes':strokes,'piles':piles,
            'collected':{'before':before,'after':after},'resumed':answer},indent=2))


if __name__=='__main__':unittest.main()
