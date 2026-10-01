"""Generated native layout, hauling, processing and durable personal pickup."""
from copy import deepcopy
import json
import unittest
from unittest import mock

import world_goods_tests as flow

ROOT=flow.ROOT
server=flow.server
workshop_library=flow.workshop_library


class GeneratedRovers(unittest.TestCase):
    setUp=flow.GoodsJourney.setUp
    tearDown=flow.GoodsJourney.tearDown
    start=flow.GoodsJourney.start
    stop=flow.GoodsJourney.stop
    get=flow.GoodsJourney.get
    post=flow.GoodsJourney.post
    join=flow.GoodsJourney.join
    setup_world=flow.GoodsJourney.setup_world
    personal=flow.GoodsJourney.personal

    def test_generated_precise_assemblies_are_separate_and_processors_reach_their_stockpiles(self):
        import math
        import precise_rigid
        import machine_goods
        for seed in (0,1):
            with self.subTest(seed=seed),mock.patch.object(server.secrets,'randbelow',side_effect=[seed,851269740+seed]):
                world,owner,app=self.setup_world()
                app.live.act({'session':app.live.session.id,'op':'poses'})
                state=app.live.session.state;parts=[]
                for b in state['bodies']:
                    for p in b.get('rigid_parts_local') or []:
                        lo,hi=precise_rigid.bounds([p],b['position_m'],b['orientation_wxyz'])
                        parts.append((b['name'].split(':')[0],lo,hi))
                self.assertTrue(parts)
                for i,(name,lo,hi) in enumerate(parts):
                    for other,low,high in parts[i+1:]:
                        if name==other:continue
                        self.assertFalse(lo[0]<high[0]+.3499 and hi[0]>low[0]-.3499 and
                                         lo[2]<high[2]+.3499 and hi[2]>low[2]-.3499,
                                         (seed,name,other,lo,hi,low,high))
                rover_program=next(p for p in state['machines']['programs'] if p['kind']=='roam')
                self.assertFalse(any(s['sees'] for s in rover_program['sensors']),
                                 'Initial native ground/water probes must have clearance')
                route=app.brains.of(rover_program['name']).routine.places
                start,end=route['smelter intake'],route['vein']
                length=math.dist(start,end)
                for k in range(math.ceil((length-4.)/.25)+1):
                    distance=min(length-1.5,2.5+k*.25)
                    x=start[0]+(end[0]-start[0])*distance/length
                    z=start[1]+(end[1]-start[1])*distance/length
                    for name,lo,hi in parts:
                        if name=='rover':continue
                        self.assertGreaterEqual(math.hypot(max(lo[0]-x,0,x-hi[0]),
                                                           max(lo[2]-z,0,z-hi[2])),1.325-.001,
                                                (seed,name,'hauling corridor',x,z))
                bodies={b['name']:b for b in state['bodies']}
                for program in state['machines']['programs']:
                    routine=app.brains.of(program['name']).routine
                    if routine.kind!='process':continue
                    at=bodies[program['body']]['position_m']
                    for pile_name in (routine.intake,routine.output):
                        pile=app.brains.goods.by_name(pile_name)
                        self.assertLessEqual(math.hypot(at[0]-pile['at_m'][0],at[2]-pile['at_m'][1]),
                                             machine_goods.REACH_M+pile['radius_m']-.1999)

    def test_generated_rovers_deliver_mined_ore_process_it_and_owner_collects_after_restart(self):
        def credited_copper(app,owner):
            with workshop_library._connect(app) as db:
                row=db.execute("SELECT mass_kg FROM workshop_goods_rack "
                               "WHERE owner_id=? AND substance='copper'",(owner['id'],)).fetchone()
            return row['mass_kg'] if row else 0.
        reports=[]
        for seed in (0,1):
            with self.subTest(seed=seed),mock.patch.object(server.secrets,'randbelow',side_effect=[seed,851269740+seed]):
                world,owner,app=self.setup_world()
                program=next(p for p in app.live.session.state['machines']['programs'] if p['kind']=='roam')
                self.assertIsNotNone(app.brains.of(program['name']).before,
                                     'Ordinary startup must observe native state without a poses request')
                rover=app.brains.of(program['name']).routine
                processor=next(b.routine for b in app.brains.brains.values()
                               if b.routine and b.routine.recipe=='smelt copper')
                intake=app.brains.goods.by_name(processor.intake)
                output=app.brains.goods.by_name(processor.output)
                starter_ore=intake['holds']['copper ore']
                before_personal=self.personal(app,owner)
                for step in range(1500):
                    app.clock._tick(.2)
                    if rover.trips:break
                self.assertGreater(rover.trips,0,(seed,rover.summary()))
                self.assertTrue(rover.load_reading()['empty'])
                delivered=next(e for e in app.brains.goods.activities
                               if e['kind']=='dump' and e['machine']==program['name'])
                self.assertEqual({'pile':processor.intake},delivered['to'])
                mined_ore=delivered['goods_kg']['copper ore']
                self.assertGreater(mined_ore,0.)
                self.assertAlmostEqual(rover.delivered_kg,sum(delivered['goods_kg'].values()),places=8)
                self.assertTrue(any(e['kind']=='dig' and e['machine']==program['name']
                                    for e in app.brains.goods.activities))
                # A normal player power-off isolates this actual first load
                # from later loads while the receiving processor finishes.
                app.live.act({'session':app.live.session.id,'op':'run','program':program['id'],
                              'sender':'delivery-verification','seq':1,'power':False})
                expected=(starter_ore+mined_ore)*.3
                for _ in range(400):
                    app.clock._tick(.2)
                    if abs(output['holds'].get('copper',0.)-expected)<1e-6:break
                # Goods.put/convert retain six decimal places in kg. Bound
                # the existing input/output quantization; durable credit below
                # must match the actual output exactly, without new rounding.
                copper=output['holds'].get('copper',0.)
                self.assertAlmostEqual(expected,copper,delta=1e-6)
                self.assertLess(intake['holds'].get('copper ore',0.),1e-8)
                self.assertEqual(before_personal,self.personal(app,owner),'Output waits for personal pickup')
                x,z=output['at_m']
                floor=app.live.act({'session':app.live.session.id,'op':'survey','at':[x,z]})['survey']['ground_m']
                request={'session':app.live.session.id,'pile':output['name'],'automatic':True,
                         'request_id':f'generated-haul-{seed}',
                         'person':{'eyes_m':[x,floor+1.62,z],'facing':[0,0,-1]}}
                answer=self.post('/api/world/goods/collect',request,world)
                self.assertEqual(copper,answer['collected']['copper'])
                self.assertEqual(copper,credited_copper(app,owner))
                self.assertEqual(round(copper,4),self.personal(app,owner)['copper'])
                saved_routine=deepcopy(rover.record())
                self.stop();self.start();self.post('/api/world/open',{},world)
                restored=self.app.hub.get(world);request['session']=restored.live.session.id
                self.post('/api/world/goods/collect',request,world)
                self.assertEqual(saved_routine,restored.brains.of(program['name']).routine.record())
                self.assertEqual(copper,credited_copper(restored,owner))
                self.assertEqual(round(copper,4),self.personal(restored,owner)['copper'])
                self.assertEqual({},restored.brains.goods.by_name(output['name'])['holds'])
                reports.append({'seed_choice':seed,'delivery_by_s':(step+1)*.2,
                                'delivered_kg':rover.delivered_kg,'mined_ore_kg':mined_ore,
                                'starter_ore_kg':starter_ore,'collected_copper_kg':copper,
                                'conversion_residual_kg':copper-expected,
                                'restart_retry_no_duplicate':True})
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/'generated-first-haul.json').write_text(json.dumps(reports,indent=2))


if __name__ == "__main__":
    unittest.main(verbosity=2)
