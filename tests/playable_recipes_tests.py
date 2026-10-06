"""Inorganic player catalog and a real paid compact-tool browser journey."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'playground'),str(ROOT/'mcp'),str(ROOT)]
import game_materials
import goal_chains
import playable_recipes
import product_labels
from mcp import engine_materials, progression, workshop, workshop_components
import workshop_navigation_tests as navigation


class Sources(unittest.TestCase):
    def test_tool_family_geometry_and_clearance_share_the_capability_contract(self):
        from mcp import workshop_tools,workshop_recipe_contract
        cases=[(playable_recipes.recipe('field-pick'),[0,0,-1],.15),
               (playable_recipes.metal_shovel_recipe(),[1,0,0],.2),
               (playable_recipes.metal_hoe_recipe(),[0,-1,0],.09)]
        hashes=set()
        for source,direction,clearance in cases:
            with self.subTest(source=source['design_id']):
                design,patches=workshop_components.design_from_spec(source)
                report=workshop_recipe_contract.derive(design,patches)
                contract=report['tool_authoring']
                hashes.add(report['source']['hash'])
                self.assertEqual(direction,contract['ground_work']['declaration']['pointing'])
                self.assertEqual('swing-and-lever',contract['ground_work']['adapter'])
                self.assertEqual('configured-unqualified',contract['ground_work']['status'])
                measured=contract['ground_work']['working_clearance']
                self.assertAlmostEqual(clearance,measured['minimum_m'])
                self.assertGreater(measured['minimum_m'],measured['contact_travel_m'])
                # A name can change without changing functional anchors.
                design.purpose='Uncatalogued implement'
                self.assertEqual(measured,workshop_tools.authoring_contract(design)['ground_work']['working_clearance'])
        self.assertEqual(3,len(hashes))

        bad=playable_recipes.metal_hoe_recipe()
        bad['component_overrides']['@construction']['added'][0]['center_m'][1]=.015
        design,_=workshop_components.design_from_spec(bad)
        measured=workshop_tools.authoring_contract(design)['ground_work']['working_clearance']
        self.assertAlmostEqual(0.,measured['minimum_m'])
        self.assertIn('geometry estimate only',measured['qualification'])

        # The same clearance survives a quarter-turn of the whole product
        # and arbitrary component names; neither is a tool-family switch.
        rotated,_=workshop_components.design_from_spec(playable_recipes.metal_hoe_recipe())
        parts=[]
        for part in rotated.parts:
            x,y,z=part.center_m
            parts.append(replace(part,center_m=(-y,x,z),rotation_deg=(0,0,90),
                                 name={'handle':'member-q','blade':'edge-r'}[part.name]))
        rotated.parts=parts
        rotated.parameters['ground_tool']['point']['component']='edge-r'
        rotated.parameters['ground_tool']['grip']['component']='member-q'
        report=workshop_tools.authoring_contract(rotated)
        self.assertAlmostEqual(.09,report['ground_work']['working_clearance']['minimum_m'])
        for actual,expected in zip(report['ground_work']['declaration']['pointing'],[1,0,0]):
            self.assertAlmostEqual(expected,actual)
        self.assertEqual('configured-unqualified',report['ground_work']['status'])

    def test_machine_parameters_bind_before_lineage_and_fixed_geometry_overrides_are_retained(self):
        source=playable_recipes.recipe('solar-array',parameters={'max_power_w':10000.,'capacity_j':50000.,'charge_j':10000.})
        machine=source['component_overrides']['@machines']['stores'][0]
        self.assertEqual(10000.,machine['max_power_w'])
        self.assertEqual(50000.,machine['capacity_j'])
        self.assertEqual(10000.,machine['charge_j'])
        self.assertEqual(.0035,source['component_overrides']['frame']['size_m'][1])
        self.assertEqual(.01,source['component_overrides']['battery']['size_m'][1])

    def test_every_playable_source_uses_real_catalog_materials_and_named_sources_are_inorganic(self):
        sources=[playable_recipes.recipe(a.name) for a in workshop.ASSEMBLIES]
        sources.extend(source for _,source in product_labels.named_sources())
        for source in sources:
            design,_=workshop_components.design_from_spec(source)
            with self.subTest(kind=design.kind):
                self.assertTrue(design.parts)
                for part in design.parts:
                    self.assertIn(engine_materials.canonical(part.material),game_materials.body_materials())
                    self.assertAlmostEqual(part.volume_m3()*engine_materials.density(part.material),part.mass_kg(),places=9)
        design,_=workshop_components.design_from_spec(goal_chains.first_tool_recipe())
        self.assertAlmostEqual(5.65125,sum(p.mass_kg() for p in design.parts),places=9)
        self.assertEqual({'iron','aluminum'},{p.material for p in design.parts})

    def test_game_graph_checks_and_does_not_mutate_historical_organic_experiments(self):
        historical=progression.Registry();before=deepcopy(historical.designs)
        game=playable_recipes.registry();game.check()
        self.assertNotIn('rough-shaping-wood',game.techniques)
        self.assertNotIn('one-piece-wooden-pick',game.designs)
        self.assertNotIn('shape-wood-v1',game.processes)
        self.assertEqual(before,progression.Registry().designs)
        self.assertEqual('oak',workshop.assemble('field-pick').parts[0].material)
        construction={'template':'swing-and-lever','one_piece':False,'parts':[
            {'size_m':[.05,.05,.4],'material':'aluminum','shape':'box'},
            {'size_m':[.05,.05,.15],'material':'iron','shape':'box'}],
            'point':{'width_m':.05,'thickness_m':.05,'angle_deg':30.,'length_m':.2}}
        self.assertEqual('field-pick@2',progression.design_of(game,construction))
        bad=deepcopy(construction);bad['parts'][0]['material']='oak'
        self.assertIsNone(progression.design_of(game,bad))
        bad=deepcopy(construction);bad['parts'][0]['size_m'][2]=.8
        self.assertIsNone(progression.design_of(game,bad))


class Game(navigation.GameScreens):
    def tearDown(self):
        if getattr(self,'page',None):
            out=ROOT/'build/playable-recipes';out.mkdir(parents=True,exist_ok=True)
            try:
                state=self.page.evaluate('({remake:document.querySelector("#ws-remake")?.textContent,notice:document.querySelector("#ws-notice")?.textContent})')
                (out/'last-ui-state.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
            except Exception:pass
        super().tearDown()

    def test_catalog_paid_mixed_metal_tool_and_browser_materials(self):
        world,owner,app=self.setup_world(surface='columns')
        before={material:sum(p.get('holds',{}).get(material,0.) for p in app.brains.goods.stockpiles)
                for material in ('iron','aluminum')}
        for material in ('iron','aluminum'):
            pile=next(p for p in app.brains.goods.stockpiles if p.get('holds',{}).get(material,0.)>=3.)
            at=pile['at_m'];sid=app.live.session.id
            floor=self.post('/api/live/act',{'session':sid,'op':'survey','at':at},world)['survey']['ground_m']
            got=self.post('/api/world/goods/collect',{'session':sid,'pile':pile['name'],
                'request_id':'collect-'+material,'person':{'eyes_m':[at[0],floor+1.62,at[1]],
                                                        'facing':[0,0,-1]}},world)
            self.assertGreater(got['collected'][material],0.)
        goals=self.post('/api/workshop/goals',{},world)
        self.assertEqual('make-own-tool',goals['next_goal'])
        offers=self.post('/api/workshop/market',{'guidance':False},world)['offers']
        self.assertFalse({'oak-stock','rubber-stock'} & {o['id'] for o in offers})
        self.assertIn('aluminum-stock',{o['id'] for o in offers})
        recipes=self.post('/api/workshop/recipes',{},world)['templates']
        for source in recipes:
            for line in source.get('materials',[]): self.assertTrue(game_materials.allowed(line['material']))
        skills=self.post('/api/workshop/skills',{},world)['techniques']
        self.assertNotIn('rough-shaping-wood',{s['id'] for s in skills})
        self.browser(world,owner);self.navigate(world,'workshop=1&tab=recipes')
        selector='[data-recipe="field-pick:Personal field pick"]'
        self.wait(f'!!document.querySelector({json.dumps(selector)})')
        self.click(selector+' .ws-recipe-details > summary')
        self.assertIn('aluminum',self.page.evaluate(f'document.querySelector({json.dumps(selector)}).textContent'))
        self.screenshot('inorganic-compact-tool-source.png')
        self.click(selector+' .ws-recipe-acts button:first-child')
        self.wait('!!document.querySelector("#ws-remake-prepare")')
        for _ in range(12):
            self.click('#ws-remake-prepare')
            self.wait('!document.querySelector("#ws-remake-start").disabled || !!document.querySelector("#ws-remake-prepare:not(:disabled)")')
            if self.page.evaluate('!document.querySelector("#ws-remake-start").disabled'):break
        self.wait('!document.querySelector("#ws-remake-start").disabled')
        self.click('#ws-remake-start');self.wait('!!document.querySelector("#ws-remake-step")')
        for _ in range(5):
            self.click('#ws-remake-step')
            self.wait('!!document.querySelector("#ws-remake-collect") || !!document.querySelector("#ws-remake-step:not(:disabled)")')
            if self.page.evaluate('!!document.querySelector("#ws-remake-collect")'):break
        self.wait('!!document.querySelector("#ws-remake-collect")')
        self.click('#ws-remake-collect')
        self.wait('document.querySelector("#ws-remake").textContent.includes("In your Inventory")')
        receipt=next(r for r in reversed(app.room.workshop_installs) if r.get('owner_id')==owner['id'])
        self.assertTrue(receipt['resources_charged']);self.assertTrue(receipt['engine_grid_verified'])
        job=app.room.fabrication_record['jobs'][receipt['fabrication_job_id']]
        self.assertEqual({'iron','aluminum'},set(job['product_materials_kg']))
        self.assertAlmostEqual(5.65125,sum(job['product_materials_kg'].values()),places=6)
        self.assertGreater(job['required_j'],0.)
        self.assertGreaterEqual(job['work_j'],job['required_j'])
        self.assertEqual(goal_chains.first_tool_recipe()['component_overrides'],receipt['recipe']['component_overrides'])
        self.assertTrue(app.room.fabrication_record['jobs'])
        self.assertFalse({'oak','rubber','pine'} & set(self.page.evaluate(
            '[...document.querySelectorAll("#ws-build-material option")].map(o=>o.value)')))
        if self.page.evaluate('document.querySelector("#ws-pane-inventory").hidden'):
            self.click('#ws-remake-inventory')
        self.wait('document.querySelector("#ws-pane-inventory").hidden === false && document.querySelector("#ws-inv-grid").textContent.includes("Personal field pick")')
        carried=self.post('/api/workshop/inventory',{},world)['carried']
        own=next(item for item in carried if item['label']=='Personal field pick')
        self.assertTrue(own['where'].startswith('bag '))
        self.assertAlmostEqual(5.65125,own['kg'],places=5)
        self.screenshot('inorganic-paid-tool-inventory.png')
        # Functional evidence comes from the actual owned native tool, not
        # matching its label or merely opening the recipe. This bounded path
        # performs ordinary hand work, then separately spends metered bank work.
        sid=app.live.session.id;x,z=-.9,.025
        floor=self.post('/api/live/act',{'session':sid,'op':'survey','at':[x,z]},world)['survey']['ground_m']
        person={'standing_m':[x,floor,z],'eyes_m':[x,floor+1.62,z],'facing':[1,0,0]}
        equipped=self.post('/api/world/inventory',{'session':sid,'op':'equip','item':own['id'],
            'request':'equip-paid-metal-tool','person':person},world)
        self.assertTrue(equipped['ok'],equipped)
        sid=app.live.session.id
        studied=self.post('/api/world/action',{'session':sid,'object':receipt['root_body'],
            'primary':True,'person':person},world)
        self.assertNotIn('refused',studied,studied)
        prior=self.post('/api/workshop/skills',{},world)
        self.assertFalse(next(s for s in prior['techniques'] if s['id']=='using-ground-tools')['known'])
        # This trial drives the real clock below. Stop the browser observer
        # from concurrently refreshing the hand/camera during the stroke.
        self.page.send('Page.navigate',{'url':'about:blank'})
        target=self.post('/api/workshop/goals',{},world)['goals'][2]['target']['ground_at_m']
        grid=app.live.session.state['terrain']['grid'];cell=float(grid['cell_m'])
        for axis,key in ((0,'x0_m'),(2,'z0_m')):
            index=(target[axis]-float(grid[key]))/cell
            self.assertAlmostEqual(round(index),index)
        person['look_direction']=[target[0]-x,target[1]-floor-1.62,target[2]-z]
        replies=[];errors=[]
        def use_hand():
            try:replies.append(self.post('/api/world/tool/use',{'session':app.live.session.id,
                'person':person,'at_m':target},world))
            except Exception as exc:errors.append(exc)
        # Keep each actual receipt: an initial lowering/contact can do work
        # without release. Require useful ordinary work within three strokes,
        # never replace a failed attempt with funded cutting.
        for _ in range(3):
            worker=threading.Thread(target=use_hand,daemon=True);worker.start();deadline=time.monotonic()+25
            while worker.is_alive() and time.monotonic()<deadline:
                app.clock._tick(.05);time.sleep(.015)
            worker.join(1);self.assertFalse(worker.is_alive());self.assertEqual([],errors)
            hand_used=replies[-1]
            self.assertNotIn('refused',hand_used,hand_used)
            if hand_used['result']['loosened_kg']>0:break
        self.assertNotIn('refused',hand_used,hand_used)
        self.assertGreater(hand_used['result']['loosened_kg'],0.,hand_used)
        finished=self.post('/api/workshop/goals',{'chain':'first-tool-v1'},world)
        self.assertTrue(finished['complete'],finished)
        # Assisted cuts have their own bank receipt; they do not substitute
        # for the ordinary strike's functional learning evidence.
        target[1]=self.post('/api/live/act',{'session':app.live.session.id,'op':'survey',
            'at':[target[0],target[2]]},world)['survey']['ground_m']
        for i in range(2):
            self.post('/api/workshop/market',{'action':'bank','joules':500,
                'request_id':f'fund-metal-soil-cut-{i}'},world)
        person['look_direction']=[target[0]-x,target[1]-floor-1.62,target[2]-z]
        used=self.post('/api/world/tool/use',{'session':app.live.session.id,'person':person,
            'at_m':target,'energy_assist':True,'request_id':'paid-metal-functional-cut'},world)
        self.assertNotIn('refused',used,used)
        self.assertGreater(used['cut']['mass_kg'],0.,used)
        self.assertGreater(used['cut']['charged_j'],0.,used)
        self.assertTrue(self.post('/api/workshop/goals',{'chain':'first-tool-v1'},world)['complete'])
        learned=self.post('/api/workshop/skills',{},world)
        self.assertTrue(next(s for s in learned['techniques'] if s['id']=='using-ground-tools')['known'])
        self.navigate(world,'workshop=1&tab=skills')
        self.wait('document.querySelector("#ws-tree").textContent.includes("Gathering by hand")')
        self.screenshot('inorganic-tool-gathering-earned.png')
        self.assertFalse([e for e in self.page.events if e.get('method')=='Runtime.exceptionThrown'])
        for material in before:
            after=sum(p.get('holds',{}).get(material,0.) for p in app.brains.goods.stockpiles)
            self.assertLess(after,before[material])
        out=ROOT/'build/playable-recipes';out.mkdir(parents=True,exist_ok=True)
        (out/'paid-metal-tool-use.json').write_text(json.dumps({'cut':used['cut'],
            'result':hand_used['result'],'ordinary_attempts':[r['result'] for r in replies],
            'known':next(s for s in learned['techniques'] if s['id']=='using-ground-tools')},indent=2),encoding='utf-8')


# Reuse browser infrastructure, not its unrelated historical journeys.
for name in dir(navigation.GameScreens):
    if name.startswith('test_'):setattr(Game,name,None)

if __name__=='__main__':unittest.main()
