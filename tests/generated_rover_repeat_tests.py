"""Repeated native receiving receipts on both ordinary generated starts."""
from copy import deepcopy
import json
import math
import time
import unittest
from unittest import mock

import generated_rover_tests as fixture
import machine_navigation


class RepeatedHauling(unittest.TestCase):
    setUp=fixture.GeneratedRovers.setUp
    tearDown=fixture.GeneratedRovers.tearDown
    start=fixture.GeneratedRovers.start
    stop=fixture.GeneratedRovers.stop
    get=fixture.GeneratedRovers.get
    post=fixture.GeneratedRovers.post
    join=fixture.GeneratedRovers.join
    setup_world=fixture.GeneratedRovers.setup_world

    def test_three_real_receiving_loads_on_both_maps_and_complete_routine_restore(self):
        reports=[]
        for seed in (0,1):
            with self.subTest(seed=seed),mock.patch.object(fixture.server.secrets,'randbelow',side_effect=[seed,851269740+seed]):
                world,owner,app=self.setup_world()
                program=next(p for p in app.live.session.state['machines']['programs'] if p['kind']=='roam')
                routine=app.brains.of(program['name']).routine
                processor=next(b.routine for b in app.brains.brains.values()
                               if b.routine and b.routine.recipe=='smelt copper')
                timings=[];plans=[];firsts=[];last_trips=0
                original=machine_navigation.waypoint
                def measured(*args,**kwargs):
                    began=time.perf_counter();result=original(*args,**kwargs)
                    timings.append(time.perf_counter()-began);plans.append(deepcopy(result))
                    return result
                with mock.patch.object(machine_navigation,'waypoint',side_effect=measured):
                    for step in range(1500):
                        app.clock._tick(.2)
                        if routine.trips>last_trips:
                            firsts.append((step+1)*.2);last_trips=routine.trips
                        if routine.trips>=3:break
                self.assertGreaterEqual(routine.trips,3,(seed,routine.summary()))
                dumps=[e for e in app.brains.goods.activities
                       if e['kind']=='dump' and e['machine']==program['name']]
                self.assertEqual(3,len(dumps))
                for receipt in dumps:
                    self.assertEqual({'pile':processor.intake},receipt['to'])
                    self.assertGreater(receipt['goods_kg'].get('copper ore',0.),0.)
                delivered=sum(sum(e['goods_kg'].values()) for e in dumps)
                self.assertAlmostEqual(delivered,routine.delivered_kg,places=8)
                self.assertTrue(routine.load_reading()['empty'])
                self.assertTrue(plans)
                for plan in plans:
                    if not plan:continue
                    self.assertLessEqual(plan['surveys'],machine_navigation.MAX_SURVEYS)
                    path=plan.get('path') or []
                    if len(path)>1:
                        self.assertGreater(math.dist(path[0],plan['target']),machine_navigation.WAYPOINT_NEAR_M)
                saved=deepcopy(routine.record())
                self.assertTrue(fixture.server.keep_world(app,'repeat hauling acceptance'))
                self.stop();self.start();self.post('/api/world/open',{},world)
                restored=self.app.hub.get(world).brains.of(program['name']).routine
                self.assertEqual(saved,restored.record())
                ordered=sorted(timings)
                reports.append({'seed_choice':seed,'delivery_times_s':firsts,'delivered_kg':delivered,
                                'mined_ore_kg':sum(e['goods_kg']['copper ore'] for e in dumps),
                                'plans':len(plans),'retreats':sum(bool(p and p.get('reverse')) for p in plans),
                                'max_surveys':max((p or {}).get('surveys',0) for p in plans),
                                'median_plan_s':ordered[len(ordered)//2],'max_plan_s':max(timings),
                                'routine_restart_exact':True})
        out=fixture.ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/'generated-repeat-hauling.json').write_text(json.dumps(reports,indent=2))


if __name__=='__main__':unittest.main(verbosity=2)
