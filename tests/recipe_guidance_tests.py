"""Personal/shared recipe shortages -> actual world supply -> paid fabrication."""
import base64
import json
from pathlib import Path
import time
import unittest
from unittest import mock
import world_goods_tests as flow

ROOT=Path(__file__).resolve().parents[1]


class RecipeGuidance(unittest.TestCase):
    setUp=flow.GoodsJourney.setUp
    tearDown=flow.GoodsJourney.tearDown
    start=flow.GoodsJourney.start
    stop=flow.GoodsJourney.stop
    get=flow.GoodsJourney.get
    post=flow.GoodsJourney.post
    join=flow.GoodsJourney.join
    setup_world=flow.GoodsJourney.setup_world

    def test_routes_use_actual_pile_stock_personal_shortage_and_machine_inputs(self):
        world,owner,app=self.setup_world()
        other=self.join(world,'Other crafter')
        def recipes(token=None):return self.post('/api/workshop/recipes',{},world,token)
        def rover(token=None):return next(t for t in recipes(token)['templates'] if t.get('kind')=='rover')
        initial=rover();oak=next(l for l in initial['materials'] if l['material']=='oak')
        self.assertEqual(0,oak['personal_kg']);self.assertEqual(12.4,oak['shared_kg'])
        self.assertAlmostEqual(oak['kg']-12.4,oak['short_kg'])
        pile=next(p for p in app.brains.goods.stockpiles if p.get('holds',{}).get('oak',0)>25)
        route=next(r for r in oak['acquisition'] if r['kind']=='pile')
        self.assertEqual(pile['name'],route['name']);self.assertEqual(pile['holds']['oak'],route['available_kg'])
        self.assertEqual([],route['input_to'])
        sid=app.live.session.id;at=pile['at_m']
        floor=app.live.act({'session':sid,'op':'survey','at':at})['survey']['ground_m']
        # A collect takes the whole pile into private stock (bulk pickup).
        got=self.post('/api/world/goods/collect',{'session':sid,'pile':pile['name'],'request_id':'recipe-oak',
            'person':{'eyes_m':[at[0],floor+1.62,at[1]],'facing':[0,0,-1]}},world)['collected']['oak']
        self.assertGreater(got,0)
        updated=next(l for l in rover()['materials'] if l['material']=='oak')
        self.assertAlmostEqual(got,updated['personal_kg']);self.assertEqual(12.4,updated['shared_kg'])
        self.assertAlmostEqual(max(0.,updated['kg']-12.4-got),updated['short_kg'])
        left=pile['holds'].get('oak',0)
        routes=[r for r in updated.get('acquisition',[]) if r['kind']=='pile' and r['name']==pile['name']]
        if left>0:self.assertEqual(left,routes[0]['available_kg'])
        else:self.assertEqual([],routes,'an emptied pile is not offered as a supply')
        other_oak=next(l for l in rover(other['token'])['materials'] if l['material']=='oak')
        self.assertEqual(0,other_oak['personal_kg']);self.assertEqual(oak['short_kg'],other_oak['short_kg'])
        copper=next(l for l in initial['goods'] if l['substance']=='copper')
        process=next(r for r in copper['acquisition'] if r['kind']=='process')
        machine=process['machines'][0]
        program=next(p for p in app.room.spec['machines']['programs'] if p['name']==machine['name'])
        self.assertEqual(program['body'],machine['body'])
        intake=app.brains.goods.by_name(machine['intake'])
        self.assertEqual(intake['holds']['copper ore'],machine['inputs'][0]['held_kg'])
        all_lines=[l for t in recipes()['templates'] for l in [*t.get('materials',[]),*t.get('goods',[])]]
        deposits=[r for l in all_lines for r in l['acquisition'] if r['kind']=='deposit']
        if deposits:self.assertTrue(any('rover' in r['equipment'] for r in deposits))
        # An exhausted source must disappear rather than remain a suggested
        # supply. The timber lies in several piles; empty every one.
        for loose in [p for p in app.brains.goods.stockpiles if p.get('holds',{}).get('oak',0)>0 and not p.get('rack')]:
            lx,lz=loose['at_m'];lfloor=app.live.act({'session':sid,'op':'survey','at':[lx,lz]})['survey']['ground_m']
            while loose['holds'].get('oak',0)>0:
                self.post('/api/world/goods/collect',{'session':sid,'pile':loose['name'],
                    'request_id':'empty-oak-'+str(len(app.room.goods_claims)),
                    'person':{'eyes_m':[lx,lfloor+1.62,lz],'facing':[0,0,-1]}},world)
        after=next(l for l in rover(other['token'])['materials'] if l['material']=='oak')
        self.assertFalse(any(r['kind']=='pile' for r in after['acquisition']))
        self.assertTrue(any(r['kind']=='market' and r['offer_id']=='oak-stock' for r in after['acquisition']))

    def test_browser_shortage_locate_collect_make_and_targeted_market(self):
        if not flow.qa_browser.CHROME.is_file():self.skipTest('Chrome not installed')
        with mock.patch.object(flow.server.secrets,'randbelow',side_effect=[0,851269740]):
            # This test covers the legacy recipe-supply authoring route. Fresh
            # finite-workbench Make/funding is covered by fabrication_remake_tests.
            world,owner,app=self.setup_world(legacy_process=True)
        chrome=flow.qa_browser.Chrome(1440,900);self.addCleanup(chrome.close)
        p=chrome.page;p.send('Page.enable');p.send('Runtime.enable')
        def wait(expr):
            deadline=time.monotonic()+40
            while time.monotonic()<deadline:
                if p.evaluate('Boolean('+expr+')'):return
                time.sleep(.1)
            self.fail(expr+'; '+str(p.evaluate('document.body.innerText.slice(-2000)')))
        def click(selector):
            point=p.evaluate('''(()=>{const e=document.querySelector(%s);e.scrollIntoView({block:'center'});
                const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()'''%json.dumps(selector))
            for kind in ('mousePressed','mouseReleased'):
                p.send('Input.dispatchMouseEvent',{'type':kind,'button':'left','clickCount':1,**point})
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        def shot(tag):
            (out/f'recipe-guidance-{tag}.png').write_bytes(base64.b64decode(p.send('Page.captureScreenshot',{'format':'png'})['data']))
        recipes_url=self.base+f'/world?world={world}&workshop=1&tab=recipes'
        p.send('Page.navigate',{'url':recipes_url})
        card='[data-recipe="table:table"]'
        wait(f'document.querySelector({json.dumps(card)})')
        self.assertTrue(p.evaluate(f'document.querySelector({json.dumps(card+" .ws-recipe-acts button")}).disabled'))
        # The catalog Table is listed under the recommended Work table's
        # "Other versions"; a player opens that first.
        p.evaluate(f'document.querySelector({json.dumps(card)}).closest(".ws-variants")?.setAttribute("open","")')
        # The canvas selects the item into Lab. Supply routes belong to the
        # separate materials disclosure in the consolidated Build card.
        click(card+' .ws-recipe-details > summary');wait(f'document.querySelector({json.dumps(card+" .ws-recipe-details")}).open')
        text=p.evaluate(f'document.querySelector({json.dumps(card)}).textContent')
        self.assertIn('Yours 0',text);self.assertIn('Shared 12.4',text);self.assertIn('None required',text)
        self.assertIn('oak pile',text);self.assertIn('Missing',text);shot('shortage')
        click(card+' [data-supply-route="oak pile"]')
        wait('window.banjoRoom?.ready() && location.search.includes("resource=")')
        p.evaluate('banjoRoom.hold()')
        wait('document.querySelector("#picked").textContent.includes("Material pile")')
        self.assertIn('Walk within 2 m',p.evaluate('document.querySelector("#picked").textContent'))
        browser_owner=p.evaluate('banjoRoom.status().player_id')
        initial_pose=p.evaluate('banjoRoom.camera.position.toArray()')
        # Locate turns the view, never teleports the player. For collection the
        # test observer stands beside the actual pile on its native ground.
        pile=next(s for s in app.brains.goods.stockpiles if s['name']=='oak pile');x,z=pile['at_m']
        self.assertGreater(((initial_pose[0]-x)**2+(initial_pose[2]-z)**2)**.5,2)
        p.evaluate(f'banjoRoom.standAt({x+1},banjoRoom.groundAt({x},{z})+1.6,{z});banjoRoom.lookAt({x},banjoRoom.groundAt({x},{z})+.2,{z})')
        wait('!document.querySelector("#collect-output").hidden && document.querySelector("#collect-output").dataset.pile==="oak pile"')
        in_pile=pile['holds']['oak']
        click('#collect-output')
        wait('document.querySelector("#details-last-text").textContent.includes("Inventory")')
        token=flow.workshop_library.REQUEST_OWNER.set(browser_owner)
        try:
            # Collect takes the whole pile into private stock.
            before=next(r for r in flow.workshop_library.rack(app)['materials'] if r['material']=='oak')
            self.assertAlmostEqual(in_pile,before['personal_kg']);self.assertEqual(12.4,before['shared_kg'])
        finally:flow.workshop_library.REQUEST_OWNER.reset(token)
        p.send('Page.navigate',{'url':recipes_url})
        wait(f'document.querySelector({json.dumps(card+" .ws-recipe-acts button")}) && !document.querySelector({json.dumps(card+" .ws-recipe-acts button")}).disabled')
        # Back on Recipes the Table is under Work table's "Other versions" again.
        p.evaluate(f'document.querySelector({json.dumps(card)}).closest(".ws-variants")?.setAttribute("open","")')
        click(card+' .ws-recipe-details > summary');shot('supplied')
        installed=len(app.room.workshop_installs)        # new worlds start with their own
        click(card+' .ws-recipe-acts button')
        wait(f'document.querySelector({json.dumps(card+" .ws-recipe-result")}).textContent.includes("Made ✓")')
        self.assertEqual(installed+1,len(app.room.workshop_installs))
        token=flow.workshop_library.REQUEST_OWNER.set(browser_owner)
        try:after=next(r for r in flow.workshop_library.rack(app)['materials'] if r['material']=='oak')
        finally:flow.workshop_library.REQUEST_OWNER.reset(token)
        # Make draws on your own stock first; the shared stock is untouched.
        table_kg=37.4-6.6224
        self.assertAlmostEqual(in_pile-table_kg,after['personal_kg'],places=4)
        self.assertAlmostEqual(12.4,after['shared_kg'],places=4)
        rover='[data-recipe="rover:rover"]'
        # Make's final refresh must replace the previous stock values before
        # the next recipe's guidance is read or acted on.
        wait(f'document.querySelector({json.dumps(rover)}).textContent.includes("Yours "+(({after["personal_kg"]}).toLocaleString(undefined,{{maximumFractionDigits:2}}))+" kg")')
        shot('made')
        click(rover+' .ws-recipe-details > summary');wait(f'document.querySelector({json.dumps(rover+" .ws-recipe-details")}).open')
        text=p.evaluate(f'document.querySelector({json.dumps(rover)}).textContent')
        # Whichever is true here: no machine smelts copper, a furnace can be
        # switched to it, or (in a starter world) the furnace already does.
        self.assertTrue(any(w in text for w in ('Processing machine required','Select Smelt Copper','Turn on in World')),text[:300])
        self.assertIn('hopper',text)
        supplies=rover+' [data-supply="copper"] .ws-input-supplies summary'
        click(supplies)
        nested=rover+' [data-supply="copper"] [data-supply="copper ore"]'
        wait(f'document.querySelector({json.dumps(nested)})')
        ore_text=p.evaluate(f'document.querySelector({json.dumps(nested)}).textContent')
        self.assertIn('Hopper',ore_text);self.assertIn('Recipe yield estimate',text)
        self.assertIn('Rover → dig → intake',ore_text)
        self.assertTrue(p.evaluate(f'!!document.querySelector({json.dumps(nested+" [data-supply-route]")})'))
        click(nested+' [data-supply-kind="deposit"] [data-supply-route]')
        wait('window.banjoRoom?.ready() && location.search.includes("resource=")')
        wait('document.querySelector("#picked").textContent.includes("Extraction area")')
        shot('ore-source')
        p.send('Page.navigate',{'url':recipes_url})
        wait(f'document.querySelector({json.dumps(rover)})')
        click(rover+' .ws-recipe-details > summary');wait(f'document.querySelector({json.dumps(rover+" .ws-recipe-details")}).open')
        click(rover+' [data-supply-offer="wire-coil"]')
        wait('document.querySelector("[data-market-item=wire-coil].ws-goal-target") && !document.querySelector("#ws-pane-market").hidden')
        shot('market')
        self.assertEqual([],[e for e in p.events if e.get('method')=='Runtime.exceptionThrown'])
        (out/'recipe-guidance.json').write_text(json.dumps({'owner':browser_owner,'before':before,'after':after,
            'shortage_text':text,'receipt_count':len(app.room.workshop_installs)},indent=2))

    def test_empty_hopper_targets_actual_yield_and_cycles_are_bounded(self):
        world,owner,app=self.setup_world()
        source=next(m for m in flow.machine_witness.machines(app) if m['recipe']=='smelt copper')
        program=app.brains.of(source['machine'])
        output=app.brains.goods.by_name(program.routine.output)
        flow.GoodsJourney.process_batch(self,app,output)
        intake=app.brains.goods.by_name(program.routine.intake)
        # Empty the remaining hopper through its ordinary manual collection
        # action. Automatic nearby pickup still excludes machine inputs.
        at=intake['at_m'];sid=app.live.session.id
        floor=app.live.act({'session':sid,'op':'survey','at':at})['survey']['ground_m']
        self.post('/api/world/goods/collect',{'session':sid,'pile':intake['name'],
            'request_id':'empty-guidance-hopper','person':{'eyes_m':[at[0],floor+1.62,at[1]],
                                                        'facing':[0,0,-1]}},world)
        self.assertEqual(0,intake['holds'].get('copper ore',0))
        def line():
            recipes=self.post('/api/workshop/recipes',{},world)
            rover=next(t for t in recipes['templates'] if t.get('kind')=='rover')
            return next(l for l in rover['goods'] if l['substance']=='copper')
        copper=line();self.assertGreater(copper['short_kg'],0)
        route=next(r for r in copper['acquisition'] if r['kind']=='process' and r['name']=='smelt copper')
        ore=route['machines'][0]['inputs'][0]
        self.assertEqual(0,ore['held_kg'])
        self.assertAlmostEqual(copper['short_kg']/0.3,ore['kg'])
        self.assertEqual(ore['kg'],ore['short_kg'])
        deposit=next(r for r in ore['acquisition'] if r['kind']=='deposit')
        actual=next(d for d in app.brains.goods.holders()['deposits'] if d['name']==deposit['name'])
        self.assertEqual(actual['left_kg'],deposit['left_kg']);self.assertTrue(deposit['equipment'])
        # Declarative authoring guidance must terminate for a circular process.
        # This changes recipe descriptions only, not the running native world.
        app.room.spec['goods']['recipes'].append({'name':'circular-copper','in':{'copper':1},'out':{'copper':1}})
        circular=next(r for r in line()['acquisition'] if r.get('name')=='circular-copper')
        inputs=circular['machines'][0]['inputs'] if circular['machines'] else circular['input_supplies']
        blocked=inputs[0]['acquisition']
        self.assertEqual('blocked',blocked[0]['kind']);self.assertIn('Supply cycle',blocked[0]['reason'])


if __name__=='__main__':unittest.main()
