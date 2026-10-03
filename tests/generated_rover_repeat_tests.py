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

    def test_five_actual_loads_on_retained_world_seed_and_exact_restart(self):
        # The ordinary browser's seed/layout, without its later player edits.
        # This tests sustained mining/receiving, not the edited shore failure.
        with mock.patch.object(fixture.server.secrets,'randbelow',side_effect=[0,813489048]):
            world,owner,app=self.setup_world()
        # Explicit milestone checkpoints avoid measuring JSON disk writes as
        # solver cost. Native source/receiving transfers keep their paired saves.
        app.clock.keep=None
        program=next(p for p in app.live.session.state['machines']['programs'] if p['kind']=='roam')
        brain=app.brains.of(program['name']);routine=brain.routine
        processor=next(b.routine for b in app.brains.brains.values()
                       if b.routine and b.routine.recipe=='smelt copper')
        times=[];last=0
        for step in range(2200):
            app.clock._tick(.2)
            if routine.trips>last:
                times.append((step+1)*.2);last=routine.trips
            if routine.trips>=5:break
        self.assertEqual(5,routine.trips,routine.summary())
        receipts=[e for e in app.brains.goods.activities
                  if e['kind']=='dump' and e['machine']==program['name']]
        self.assertEqual(5,len(receipts))
        self.assertAlmostEqual(200.,routine.delivered_kg,places=8)
        self.assertTrue(routine.load_reading()['empty'])
        for receipt in receipts:
            self.assertEqual({'pile':processor.intake},receipt['to'])
            self.assertEqual(12.,receipt['goods_kg']['copper ore'])
        self.assertTrue(any(e['kind']=='output' and e['machine']!='rover'
                            and e['goods_kg'].get('copper',0)>0 for e in app.brains.goods.activities),
                        'Receiving must feed an actual paid native processing batch')
        self.assertTrue(fixture.server.keep_world(app,'five-load native acceptance'))
        saved=deepcopy(routine.record());goods=deepcopy(app.brains.goods.block)
        self.stop();self.start();self.post('/api/world/open',{},world)
        restored=self.app.hub.get(world)
        self.assertEqual(saved,restored.brains.of(program['name']).routine.record())
        self.assertEqual(goods,restored.brains.goods.block)
        out=fixture.ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/'retained-seed-five-loads.json').write_text(json.dumps({
            'terrain_seed':4,'goods_seed':813489049,'native_dt_s':1/240,
            'delivery_times_s':times,'delivered_kg':routine.delivered_kg,'copper_ore_kg':60.,
            'restart_exact':True,'automatic_tick_save':False},indent=2))

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
