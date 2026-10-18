"""Planar editing, native mounting and gravity routes for the wall workshop."""
import copy
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import machine_game as mg
import machine_world as mw
import sandbox_wall as wall
import machine_chat

ENGINE=Path(os.environ.get('BANJO_LIVE_ENGINE',ROOT/'build/feedback-test/Release/banjo_live_world_run.exe'))
if '--engine' in sys.argv:
    i=sys.argv.index('--engine');ENGINE=Path(sys.argv[i+1]).resolve();del sys.argv[i:i+2]


def compose(placements,base=None):
    return mg.compose(mg.requested_level(dict(level='free',base=base or wall.base())),placements)[0]


class Wall(unittest.TestCase):
    def rehearse(self,spec,seconds=10,track=None):
        with tempfile.TemporaryDirectory() as logs:
            return mw.rehearse(mw.compile_spec(spec),ENGINE,logs,seconds=seconds,track=track or ['your marble 1'])

    def test_wall_is_a_saved_surface_with_a_separate_tray(self):
        t=wall.template();before=copy.deepcopy(t)
        restored=json.loads(json.dumps(t))
        self.assertEqual(compose(t['placements'],t['base']),compose(restored['placements'],restored['base']))
        self.assertEqual(t,before)
        rows=mg.requested_level(dict(level='free',base=t['base']))['tray']
        self.assertEqual(len(rows),15)
        self.assertTrue(all('z_m' not in t['knobs'] for t in rows))
        self.assertFalse(any('wall_' in t['piece'] for t in mg.free_build()['tray']))
        self.assertEqual(len(mg.sandbox_templates()),5)
        for name in wall.FOUNDATION:
            bad=wall.base();bad['parts']=[p for p in bad['parts'] if p['name']!=name]
            with self.assertRaises(ValueError):mg.requested_level(dict(level='free',base=bad))
        with self.assertRaises(mg.LevelRefused):compose([dict(piece='wall_track',x_m=2.8)])

    def test_wall_builder_uses_height_and_keeps_the_board(self):
        level=mg.requested_level(dict(level='free',base=wall.base()))
        prompt=machine_chat.free_prompt(level)
        self.assertIn('vertical wall',prompt)
        self.assertNotIn('table runs from',prompt)
        ps=[dict(piece='wall_track',x_m=-1,height_m=2.2)]
        def call(messages):return dict(reply='Added a wall track.',clear=True,add=ps),{}
        result=machine_chat.respond_free('Add a track',level,[],call=call)
        self.assertEqual(result['placements'][0]['x_m'],-1)
        self.assertEqual(result['placements'][0]['height_m'],2.2)
        self.assertEqual(level['machine']['build_surface'],wall.surface())

    def test_builder_expands_a_lift_and_preserves_existing_pieces(self):
        level=mg.requested_level(dict(level='free',base=wall.base()))
        before=wall.template()['placements'];saved=copy.deepcopy(before)
        answer=dict(reply='Added a wired marble lift.',assemblies=[dict(kind='marble_lift')])
        result=machine_chat.respond_free('A wheel catches a marble and lifts it higher',level,before,
            call=lambda messages:(answer,{}))
        self.assertEqual(result['placements'][:5],
            [{k:v for k,v in p.items() if k!='cost'} for p in mg.check_placements(level,before)[0]])
        self.assertEqual(before,saved)
        added=result['placements'][5:]
        self.assertEqual([p['piece'] for p in added],['wall_lift','marble','battery','wire','wire'])
        self.assertEqual(added[3]['a_terminal'],'your battery 8:plus')
        self.assertEqual(added[3]['b_terminal'],'your wall_lift 6:plus')
        context=machine_chat.free_context(level,result['placements'])
        self.assertEqual([t['id'] for t in context[5]['terminals']],['your wall_lift 6:plus','your wall_lift 6:minus'])
        self.assertIn('bounds_m',context[5])

    def test_builder_resolves_numbered_and_named_wire_ends_and_edits(self):
        level=mg.requested_level(dict(level='free',base=wall.base()))
        before=[dict(piece='battery',x_m=-.8,height_m=2)]
        answer=dict(reply='Connected both leads.',edit=[dict(number=1,set=dict(x_m=-1))],add=[
            dict(piece='motor',id='drive',x_m=.4,height_m=2),
            dict(piece='wire',a_terminal=dict(piece=1,terminal='plus'),b_terminal='drive:plus',length_m=2),
            dict(piece='wire',a_terminal=dict(piece=1,terminal='minus'),b_terminal='drive:minus',length_m=2)])
        result=machine_chat.respond_free('Wire the motor',level,before,call=lambda m:(answer,{}))
        self.assertEqual(result['placements'][0]['x_m'],-1)
        self.assertEqual(before[0]['x_m'],-.8)
        self.assertEqual(result['placements'][2]['b_terminal'],'your motor 2:plus')
        self.assertEqual(result['placements'][3]['a_terminal'],'your battery 1:minus')

    def test_builder_repairs_overlap_and_bad_terminals_using_actual_context(self):
        level=mg.requested_level(dict(level='free',base=wall.base()))
        bad=dict(reply='Lift.',add=[dict(piece='wall_track'),dict(piece='motor'),
            dict(piece='wire',a_terminal='battery:plus',b_terminal='motor:plus')])
        good=dict(reply='Added a physical lift.',assemblies=[dict(kind='marble_lift')])
        asked=[]
        def call(messages):
            asked.append(copy.deepcopy(messages))
            return (bad if len(asked)==1 else good),{}
        result=machine_chat.respond_free('A marble lift',level,[],call=call)
        self.assertEqual(len(asked),2)
        repair=json.loads(asked[1][-1]['content'])
        self.assertTrue(any('overlap' in p for p in repair['refused']))
        self.assertIn('existing_connections',repair)
        self.assertEqual(repair['existing_connections'][1]['terminals'][0]['id'],'your motor 2:plus')
        self.assertEqual(result['placements'][0]['piece'],'wall_lift')

    def test_engine_failure_is_repaired_and_never_applied_after_exhaustion(self):
        level=mg.requested_level(dict(level='free',base=wall.base()));before=[]
        answer=dict(reply='Lift.',assemblies=[dict(kind='marble_lift')]);calls=[]
        def call(messages):calls.append(copy.deepcopy(messages));return answer,{}
        def engine(compiled,**kwargs):return dict(error='test-only failed native trial',events=[])
        with self.assertRaisesRegex(mg.LevelRefused,'failed native trial'):
            machine_chat.respond_free('Lift',level,before,call=call,rehearse=engine)
        self.assertEqual(len(calls),3)
        self.assertEqual(before,[])

    def test_lift_catches_raises_and_unloads_glass_oak_iron_with_nudges(self):
        results=[]
        for material in ('glass','oak','iron'):
            for offset in (-.002,0,.002):
                with self.subTest(material=material,offset=offset):
                    ps,check=wall.lift_assembly();ps[1].update(material=material,x_m=ps[1]['x_m']+offset)
                    r=self.rehearse(compose(ps),seconds=12,track=[check['marble']])
                    self.assertIsNone(r['error'])
                    measured=machine_chat.lift_checks([check],r)[0]
                    self.assertTrue(measured['happened'],measured)
                    ledger=r['readouts']['electrical']['networks'][0]['ledger']
                    self.assertGreater(ledger['source_j'],0)
                    self.assertLess(abs(ledger['electrical_residual_j']),1e-8)
                    self.assertTrue(all(c['connected'] for c in r['readouts']['mechanical_cables']))
                    results.append(dict(material=material,offset=offset,dt_s=1/240,cell_m=.02,
                        check=measured,ledger=ledger,wall_s=r['wall_s']))
        print('WALL LIFT',json.dumps(results),flush=True)

    def test_lift_without_a_return_or_with_a_missed_cradle_does_not_lift(self):
        for missing in ('return','cradle'):
            ps,check=wall.lift_assembly()
            if missing=='return':ps.pop()
            else:ps[1]['x_m']=-.65
            r=self.rehearse(compose(ps),seconds=12,track=[check['marble']])
            self.assertIsNone(r['error'])
            self.assertFalse(machine_chat.lift_checks([check],r)[0]['happened'])
            if missing=='return':
                self.assertLess(abs(r['readouts']['machines']['motors'][0]['turned_rad']),.01)

    def test_builder_rehearses_the_added_lift_in_the_existing_wall(self):
        level=mg.requested_level(dict(level='free',base=wall.base()))
        def run(compiled,**more):
            with tempfile.TemporaryDirectory() as logs:return mw.rehearse(compiled,ENGINE,logs,**more)
        result=machine_chat.respond_free('I want a wheel that a marble falls in and carries it up and drops it higher',
            level,wall.template()['placements'],call=lambda m:(dict(reply='Added the lift.',
                assemblies=[dict(kind='marble_lift')]),{}),rehearse=run)
        self.assertTrue(result['rehearsal']['checks'][0]['happened'])
        self.assertEqual(result['placements'][5]['x_m'],-1.2)

    def test_each_mount_stays_put_and_native_shapes_open(self):
        level=mg.requested_level(dict(level='free',base=wall.base()))
        for row in level['tray']:
            if row['piece']=='wire':continue
            with self.subTest(piece=row['piece']),tempfile.TemporaryDirectory() as logs:
                spec=compose([dict(piece=row['piece'])])
                engine,_,_=mw.build_engine(ENGINE,mw.compile_spec(spec),Path(logs))
                try:
                    before={p['name']:p for p in engine.first['bodies']}
                    after=engine.op(op='step',dt=1/240,n=240,moved=False)
                    for p in after['bodies']:
                        if 'mounting' in p['name'] or p['name'] not in before:continue
                        # Freely rotating and falling parts have their own tests.
                        if p['name'].endswith((' track',' funnel',' cup',' peg',' bracket',' post','wall bolts')) or p['name'] in wall.FOUNDATION:
                            self.assertLess(math.dist(p['position_m'],before[p['name']]['position_m']),.001,p['name'])
                finally:engine.close()

    def test_gravity_route_for_glass_oak_iron_and_nudged_starts(self):
        for material in ('glass','oak','iron'):
            for offset in (-.002,0,.002):
                with self.subTest(material=material,offset=offset):
                    t=wall.template();t['placements'][0].update(material=material,x_m=-1.9+offset)
                    result=self.rehearse(compose(t['placements']))
                    self.assertIsNone(result['error'])
                    hits=[h['other'] for h in result['hits']]
                    for name in ('your wall_track 2 track','your wall_track 3 track','your wall_track 4 track','your wall_cup 5 cup'):
                        self.assertIn(name,hits,(material,offset,hits))
                    points=result['paths']['your marble 1']['points']
                    final=points[-1]
                    self.assertTrue(.49<final[1]<1.21 and .78<final[2]<1.13,final)
                    self.assertTrue(all(.03<p[3]<.59 for p in points))
                    print('WALL ROUTE',material,offset,'dt',1/240,'cell',.02,'final',final,'wall_s',result['wall_s'],flush=True)

    def test_misplaced_start_track_fails_for_contact_and_gravity(self):
        t=wall.template();t['placements'][1]['x_m']=1.8
        result=self.rehearse(compose(t['placements']))
        self.assertIsNone(result['error'])
        self.assertFalse(any(h['other']=='your wall_cup 5 cup' for h in result['hits']))
        self.assertLess(result['paths']['your marble 1']['points'][-1][2],.1)

    def test_marble_tips_the_wall_seesaw(self):
        for add_ball in (False,True):
            ps=[dict(piece='wall_lever',x_m=0,height_m=2)]
            if add_ball:ps.append(dict(piece='marble',x_m=.22,height_m=2.25))
            result=self.rehearse(compose(ps),seconds=2,track=['your wall_lever 1 lever'])
            self.assertIsNone(result['error'])
            q=result['paths']['your wall_lever 1 lever']['turn_wxyz']
            angle=abs(2*math.atan2(q[3],q[0]))
            # Observe a visible > 10-degree tip, not a prescribed final angle:
            # the marble can rebound and leave a freely swinging seesaw.
            self.assertGreater(angle,math.radians(10)) if add_ball else self.assertLess(angle,.01)

    def test_funnel_has_a_real_opening_and_releases_into_a_cup(self):
        ps=[dict(piece='marble',x_m=.2,height_m=2.6),dict(piece='wall_funnel',x_m=0,height_m=2),
            dict(piece='wall_cup',x_m=0,height_m=1,width_m=.8)]
        result=self.rehearse(compose(ps),seconds=5)
        self.assertIsNone(result['error'])
        self.assertTrue(any(h['other']=='your wall_funnel 2 funnel' for h in result['hits']))
        self.assertTrue(any(h['other']=='your wall_cup 3 cup' for h in result['hits']))

    def test_two_physical_leads_power_the_motor_and_missing_return_does_not(self):
        ps=[dict(piece='battery',x_m=-.8,height_m=2),dict(piece='motor',x_m=.4,height_m=2),
            dict(piece='wire',a_terminal='your battery 1:plus',b_terminal='your motor 2:plus',length_m=2),
            dict(piece='wire',a_terminal='your battery 1:minus',b_terminal='your motor 2:minus',length_m=2)]
        for closed in (False,True):
            spec=compose(ps if closed else ps[:3])
            result=self.rehearse(spec,seconds=2,track=['your motor 2 wheel'])
            self.assertIsNone(result['error'])
            motor=result['readouts']['machines']['motors'][0]
            if closed:
                self.assertGreater(motor['turned_rad'],1)
                ledger=result['readouts']['electrical']['networks'][0]['ledger']
                self.assertGreater(ledger['source_j'],0)
                self.assertLess(abs(ledger['electrical_residual_j']),1e-8)
                self.assertLess(abs(ledger['coupling_residual_j']),.001)
                for cable in result['readouts']['mechanical_cables']:
                    self.assertTrue(cable['connected'])
                    self.assertGreater(cable['mass_kg'],0)
                    self.assertLess(cable['max_joint_gap_m'],.002)
                    self.assertAlmostEqual(cable['length_m'],2,places=5)
                    ys=[p[1] for segment in cable['segments_m'] for p in segment]
                    self.assertLess(min(ys),1.99,'The stock must sag under gravity')
                print('WALL DC MOTOR',motor,'ledger',ledger,flush=True)
            else:self.assertLess(abs(motor['turned_rad']),.01)

    def test_wall_gear_contact_transmits_torque_and_separated_gears_do_not(self):
        for separation in (.30,.60):
            ps=[dict(piece='battery',x_m=-.8,height_m=2),dict(piece='motor',x_m=.4,height_m=2),
                dict(piece='wire',a_terminal='your battery 1:plus',b_terminal='your motor 2:plus',length_m=2),
                dict(piece='wire',a_terminal='your battery 1:minus',b_terminal='your motor 2:minus',length_m=2),
                dict(piece='gear',x_m=.4+separation,height_m=2,phase_deg=15)]
            spec=compose(ps)
            self.assertFalse(any(j['kind']=='gear' for j in spec['joints']))
            result=self.rehearse(spec,seconds=2,track=['your gear 5 wheel'])
            self.assertIsNone(result['error'])
            q=result['paths']['your gear 5 wheel']['turn_wxyz']
            # Phase rotates the tooth geometry, not the body's reference pose.
            delta=2*math.atan2(q[3],q[0])
            if separation==.30:self.assertLess(delta,-.8)
            else:self.assertLess(abs(delta),.01)


if __name__=='__main__':unittest.main(verbosity=2)
