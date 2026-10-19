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
        lifted=compose(wall.lift_assembly()[0])
        self.assertFalse(any(' stand' in p['name'] for p in lifted['parts']))
        self.assertTrue(any(j.get('a')=='your wall_lift 1 outlet bracket' and
            j.get('b')=='your wall_lift 1 outlet' and j['kind']=='fix' for j in lifted['joints']))

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
        # Replace the rejected proposal explicitly; repairs may now edit a
        # staged candidate instead of always starting from the original.
        good=dict(reply='Added a physical lift.',clear=True,assemblies=[dict(kind='marble_lift')])
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
        answer=dict(reply='Lift.',clear=True,assemblies=[dict(kind='marble_lift')]);calls=[]
        def call(messages):calls.append(copy.deepcopy(messages));return answer,{}
        def engine(compiled,**kwargs):return dict(error='test-only failed native trial',events=[])
        with self.assertRaisesRegex(mg.LevelRefused,'failed native trial'):
            machine_chat.respond_free('Lift',level,before,call=call,rehearse=engine)
        self.assertEqual(len(calls),machine_chat.BUILD_ATTEMPTS)
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


class WallWorld(unittest.TestCase):
    def setUp(self):
        self.template=wall.world_template(mg.free_build()['tray'])
        self.level=mg.requested_level(dict(level='free',base=self.template['base']))

    def test_world_library_has_explicit_wall_mounts_and_every_ordinary_piece(self):
        rows={row['piece']:row for row in self.level['tray']}
        self.assertTrue({r['piece'] for r in mg.free_build()['tray']}<=set(rows))
        self.assertEqual(len([r for r in rows.values() if r.get('wall_mounted')]),14)
        self.assertFalse(any(p['name']==wall.FOUNDATION[1] for p in self.template['base']['parts']))
        self.assertNotIn('z_m',rows['wall_battery']['knobs'])
        self.assertIn('z_m',rows['battery']['knobs'])
        spec=mg.compose(self.level,[dict(piece='loose_block',x_m=4,z_m=3),dict(piece='wall_track',x_m=-1,height_m=2)])[0]
        block=next(p for p in spec['parts'] if p['name']=='your loose_block 1')
        self.assertEqual(block['at_m'][2],3)
        self.assertFalse(any('wall_track 2 stand' in p['name'] for p in spec['parts']))
        with self.assertRaises(mg.LevelRefused):mg.compose(self.level,[dict(piece='wall_track',x_m=2.8)])

    def test_explicit_conversion_preserves_original_and_rewrites_wiring(self):
        with self.assertRaises(ValueError):wall.world_draft({},[])
        old=wall.base();placements=wall.lift_assembly()[0];original=copy.deepcopy((old,placements))
        draft=wall.world_draft(old,placements)
        self.assertEqual((old,placements),original)
        self.assertEqual(draft['placements'][1]['piece'],'wall_marble')
        self.assertEqual(draft['placements'][3]['a_terminal'],'your wall_battery 3:plus')
        self.assertEqual(draft['placements'][3]['b_terminal'],'your wall_lift 1:plus')
        level=mg.requested_level(dict(level='free',base=draft['base']))
        mg.compose(level,draft['placements'])
        self.assertEqual(wall.world_draft(draft['base'],draft['placements']),draft)
        roundtrip=json.loads(json.dumps(draft))
        self.assertEqual(mg.compose(level,roundtrip['placements'])[0],mg.compose(level,draft['placements'])[0])

    def test_native_route_leaves_wall_plane_for_glass_oak_iron_and_nudges(self):
        results=[]
        for material in ('glass','oak','iron'):
            for nudge in (-.002,0,.002):
                with self.subTest(material=material,nudge=nudge),tempfile.TemporaryDirectory() as logs:
                    ps=copy.deepcopy(self.template['placements']);ps[0].update(material=material,x_m=ps[0]['x_m']+nudge)
                    spec=mg.compose(self.level,ps)[0]
                    r=mw.rehearse(mw.compile_spec(spec),ENGINE,logs,seconds=12,track=['your wall_marble 1'])
                    self.assertIsNone(r['error'])
                    points=r['paths']['your wall_marble 1']['points']
                    names={h['other'] for h in r['hits']}
                    self.assertTrue(all('your wall_track '+str(i)+' track' in names for i in (2,3,4)),names)
                    self.assertIn('your track 5 stop',names)
                    self.assertGreater(max(p[3] for p in points),1.5)
                    self.assertGreater(points[-1][2],.45)
                    self.assertLess(abs(points[-1][3]-1.71),.03)
                    results.append(dict(material=material,nudge_m=nudge,dt_s=1/240,cell_m=.02,
                        final=points[-1],max_depth_m=max(p[3] for p in points),wall_s=r['wall_s']))
        print('WALL INTO WORLD',json.dumps(results),flush=True)

    def test_missed_world_track_fails_to_carry_marble_outward(self):
        ps=copy.deepcopy(self.template['placements']);ps[4]['x_m']=-1.4
        with tempfile.TemporaryDirectory() as logs:
            r=mw.rehearse(mw.compile_spec(mg.compose(self.level,ps)[0]),ENGINE,logs,seconds=9,track=['your wall_marble 1'])
        self.assertIsNone(r['error'])
        self.assertLess(max(p[3] for p in r['paths']['your wall_marble 1']['points']),.4)
        self.assertFalse(any(h['other'].startswith('your track 5') for h in r['hits']))

    def test_lift_works_without_a_global_front_sheet_and_reports_ledgers(self):
        records=[]
        for material in ('glass','oak','iron'):
            ps,check=wall.world_lift_assembly();ps[1]['material']=material
            with tempfile.TemporaryDirectory() as logs:
                r=mw.rehearse(mw.compile_spec(mg.compose(self.level,ps)[0]),ENGINE,logs,seconds=12,track=[check['marble']])
            self.assertIsNone(r['error']);measured=machine_chat.lift_checks([check],r)[0]
            self.assertTrue(measured['happened'],measured)
            ledger=r['readouts']['electrical']['networks'][0]['ledger']
            self.assertLess(abs(ledger['electrical_residual_j']),1e-8)
            records.append(dict(material=material,dt_s=1/240,cell_m=.02,check=measured,ledger=ledger,wall_s=r['wall_s']))
        print('OPEN WALL LIFT',json.dumps(records),flush=True)

    def test_builder_distinguishes_wall_and_world_and_uses_correct_terminals(self):
        prompt=machine_chat.free_prompt(self.level)
        self.assertIn('ordinary 3D world',prompt);self.assertIn('Never flatten',prompt)
        rows,check=wall.world_lift_assembly(offset=5)
        self.assertEqual(rows[3]['a_terminal'],'your wall_battery 8:plus')
        self.assertEqual(check['marble'],'your wall_marble 7')
        result=machine_chat.respond_free('A lift',self.level,[],call=lambda messages:(dict(reply='Lift',assemblies=[dict(kind='marble_lift')]),{}))
        self.assertEqual(result['placements'][1]['piece'],'wall_marble')


class WallPatterns(unittest.TestCase):
    def setUp(self):
        added=wall.edit_panel(wall.world_base(),[],None,add=True)
        self.base=wall.edit_panel(added['base'],[],added['wall']['id'],dict(yaw_deg=90,z_m=2))['base']
        self.level=mg.requested_level(dict(level='free',base=self.base))
        self.panel=wall.panels(self.base)[1]

    def pattern(self,**changes):
        return dict(id='pins',piece='wall_peg',set=dict(wall=self.panel['id'],
            x_m=self.panel['x_m']-.7,height_m=2.4,diameter_m=.16),
            rows=3,columns=3,step_x_m=.5,step_y_m=-.5,stagger_m=.25,
            avoid_occupied=True,**changes)

    def test_repeated_tools_are_individual_mounted_pieces_and_skip_real_obstructions(self):
        before=[dict(piece='wall_peg',x_m=self.panel['x_m']-.7,height_m=2.4,wall=self.panel['id'])]
        kept=copy.deepcopy(before)
        answer=dict(reply='Added staggered pegs',patterns=[self.pattern()])
        result=machine_chat.respond_free('Add rows of pegs',self.level,before,
            active_wall=self.panel['id'],call=lambda messages:(answer,{}))
        self.assertEqual(before,kept)
        self.assertEqual(result['placements'][0]['x_m'],before[0]['x_m'])
        self.assertEqual(len(result['placements']),9)
        self.assertEqual(result['patterns'][0]['added'],8)
        self.assertEqual(len(result['patterns'][0]['omitted']),1)
        self.assertTrue(all(p['piece']=='wall_peg' and p['wall']==self.panel['id'] for p in result['placements']))
        compiled=mw.compile_spec(mg.compose(self.level,result['placements'])[0])
        self.assertEqual(mg.clashes_of(compiled),[])
        self.assertAlmostEqual(next(p for p in compiled['parts'] if p['name']=='your wall_peg 2 peg')['at_m'][0],
            self.panel['x_m']+.3,places=6,msg='the complete grid uses the rotated mounting plane')

    def test_existing_collisions_and_selected_wall_reach_the_model_before_it_plans(self):
        bad=[dict(piece='track',x_m=0,z_m=0,top_height_m=1,run_m=1,drop_m=.2,yaw_deg=-90)]
        seen=[]
        def call(messages):
            seen.append(json.loads(messages[1]['content']))
            return dict(reply='Moved the intersecting track in front',edit=[dict(number=1,set=dict(z_m=1))]),{}
        result=machine_chat.respond_free('Repair the track',self.level,bad,
            active_wall=self.panel['id'],call=call)
        env=seen[0]['environment']
        self.assertTrue(any('workshop backing' in p for p in env['existing_problems']))
        self.assertEqual(env['active_wall']['id'],self.panel['id'])
        self.assertEqual(len(result['placements']),1)
        self.assertEqual(result['placements'][0]['z_m'],1)
        with self.assertRaises(mg.LevelRefused):machine_chat.free_environment(self.level,[],'unknown wall')

    def test_pattern_validates_controls_and_spacing_instead_of_omitting_bad_settings(self):
        for changes in (dict(rows=0),dict(rows=9,columns=9),dict(step_x_m=0),dict(step_y_m=float('nan'))):
            pattern=self.pattern();pattern.update(changes)
            with self.subTest(changes=changes),self.assertRaises(mg.LevelRefused):
                machine_chat.respond_free('Repeat pegs',self.level,[],active_wall=self.panel['id'],
                    call=lambda messages:(dict(reply='Grid',patterns=[pattern]),{}))

    def test_repetition_is_not_specific_to_pegs_and_never_clears_unrelated_work(self):
        pattern=self.pattern();pattern.update(piece='wall_cup',rows=1,columns=3,step_x_m=.8)
        pattern['set']=dict(wall=self.panel['id'],x_m=self.panel['x_m']-.8,height_m=.3,width_m=.6)
        result=machine_chat.respond_free('Add a row of cups',self.level,[],
            active_wall=self.panel['id'],call=lambda messages:(dict(reply='Cups',patterns=[pattern]),{}))
        self.assertEqual([p['piece'] for p in result['placements']],['wall_cup']*3)
        before=[dict(piece='wall_peg',x_m=0,height_m=2)]
        with self.assertRaisesRegex(mg.LevelRefused,'Keep the original pieces'):
            machine_chat.respond_free('Cover this wall with pegs',self.level,before,
                call=lambda messages:(dict(reply='Cleared',clear=True),{}))

    def test_region_fits_the_selected_moved_wall_and_keeps_each_axis_independent(self):
        pattern=self.pattern();pattern.update(region=[.1,.9,.35,.85],stagger_m=.2)
        pattern['set']=dict(wall=self.panel['id'],diameter_m=.12)
        result=machine_chat.respond_free('Fill this wall',self.level,[],active_wall=self.panel['id'],
            call=lambda messages:(dict(reply='Grid',patterns=[pattern]),{}))
        ps=result['placements'];self.assertEqual(len(ps),9)
        self.assertAlmostEqual(min(p['x_m'] for p in ps),self.panel['x_m']-1.2)
        self.assertAlmostEqual(max(p['x_m'] for p in ps),self.panel['x_m']+1.2)
        self.assertAlmostEqual(max(p['height_m'] for p in ps),2.55)
        self.assertAlmostEqual(min(p['height_m'] for p in ps),1.05)
        for region in ([0,1,0],[-.1,1,0,1],[1,0,0,1],[0,1,float('nan'),1]):
            bad=dict(pattern,region=region)
            with self.subTest(region=region),self.assertRaises(mg.LevelRefused):
                machine_chat.respond_free('Fill wall',self.level,[],call=lambda messages:(dict(reply='Grid',patterns=[bad]),{}))

    def test_any_order_observes_distinct_contacts_and_real_final_catcher_pose(self):
        ps=[dict(piece='wall_marble',x_m=0,height_m=2),
            *[dict(piece='wall_peg',x_m=x,height_m=1.5) for x in (-.5,0,.5)],
            *[dict(piece='wall_cup',x_m=x,height_m=.3,width_m=.6) for x in (-.7,.7)]]
        compiled=mw.compile_spec(mg.compose(self.level,ps)[0])
        check=machine_chat.course_checks([dict(marble=1,via=[2,3,4],finish=[5,6],seconds=4,
            order='any',minimum_contacts=3)],ps,compiled,{})
        # A unit-level native receipt exercises observation logic only.
        # The separate native qualification verifies physical peg impacts.
        ball='your wall_marble 1';cup=next(p for p in compiled['parts'] if p['name']=='your wall_cup 6 cup')
        at=[cup['at_m'][0],.36,.3]
        receipt=dict(paths={ball:dict(points=[[0,0,2,.3],[3,*at],[4,*at]])},
            supports_final=[cup],hits=[dict(body=ball,other=f'your wall_peg {n} peg',t=t)
                for n,t in ((4,.2),(2,.4),(3,.6))])
        measured=machine_chat.measure_courses(check,receipt,compiled)[0]
        self.assertTrue(measured['happened'],measured)
        self.assertEqual(measured['finished_on'],'your wall_cup 6')
        receipt['hits']=[dict(body=ball,other='your wall_peg 2 peg',t=t) for t in (.2,.4,.6)]
        self.assertFalse(machine_chat.measure_courses(check,receipt,compiled)[0]['happened'])
        receipt['supports_final']=[]
        self.assertIsNone(machine_chat.measure_courses(check,receipt,compiled)[0]['finished_on'])

    def test_recorded_model_peg_field_keeps_the_original_design_and_passes_native_nudges(self):
        fixture=json.loads((ROOT/'tests/fixtures/chat-built-plinko-wall.json').read_text(encoding='utf-8'))
        level=mg.requested_level(dict(level='free',base=fixture['base']))
        answers=iter(fixture['proposals']);kept=copy.deepcopy(fixture['before'])
        def run(compiled,**kw):
            with tempfile.TemporaryDirectory() as logs:return mw.rehearse(compiled,ENGINE,Path(logs),**kw)
        result=machine_chat.respond_free(fixture['request'],level,fixture['before'],active_wall=fixture['active_wall'],
            call=lambda messages:(next(answers),{}),rehearse=run)
        self.assertEqual(fixture['before'],kept)
        self.assertEqual(result['placements'],fixture['placements'])
        self.assertEqual(result['rehearsal']['verified_runs'],3)
        self.assertTrue(all(c['happened'] for c in result['rehearsal']['checks']))
        original=mw.compile_spec(mg.compose(level,fixture['before'])[0])
        final=mw.compile_spec(mg.compose(level,result['placements'])[0])
        names={p['name'] for p in original['parts']}
        self.assertEqual([p for p in final['parts'] if p['name'] in names],original['parts'])
        self.assertEqual(result['patterns'][0]['added'],18)
        self.assertEqual(len(result['patterns'][0]['omitted']),2)

    def test_peg_field_material_comparison_and_rotated_wall_use_actual_contacts(self):
        fixture=json.loads((ROOT/'tests/fixtures/chat-built-plinko-wall.json').read_text(encoding='utf-8'))
        board=fixture['active_wall'];base=fixture['base'];before=fixture['before']
        added,check,_=wall.peg_field_assembly(base,before,board)
        records=[]
        for material in ('glass','oak','iron'):
            ps=copy.deepcopy(before+added);ps[-1]['material']=material
            compiled=mw.compile_spec(mg.compose(mg.requested_level(dict(level='free',base=base)),ps)[0])
            for seed in (0,1,2):
                scene=mg.nudged(compiled,seed) if seed else compiled
                with tempfile.TemporaryDirectory() as logs:r=mw.rehearse(scene,ENGINE,Path(logs),seconds=15,track=[check['marble']])
                measured=machine_chat.measure_courses([check],r,scene)[0]
                self.assertIsNone(r['error']);self.assertTrue(measured['happened'],(material,seed,measured))
                records.append(dict(material=material,seed=seed,dt_s=1/240,cell_m=.02,check=measured,wall_s=r['wall_s']))
        turned=wall.edit_panel(base,before,board,dict(yaw_deg=90))
        self.assertTrue(turned['fits'],turned['problems'])
        new,rotated_check,_=wall.peg_field_assembly(turned['base'],turned['placements'],board)
        scene=mw.compile_spec(mg.compose(mg.requested_level(dict(level='free',base=turned['base'])),turned['placements']+new)[0])
        with tempfile.TemporaryDirectory() as logs:r=mw.rehearse(scene,ENGINE,Path(logs),seconds=15,track=[rotated_check['marble']])
        self.assertTrue(machine_chat.measure_courses([rotated_check],r,scene)[0]['happened'])
        print('PLINKO FIELD',json.dumps(records),flush=True)


class EditableWalls(unittest.TestCase):
    def test_turning_one_wall_rotates_its_geometry_joints_and_terminals_only(self):
        added=wall.edit_panel(wall.world_base(),[],None,add=True);second=added['wall']
        ps=[dict(piece='wall_gear',x_m=-1,height_m=2),
            dict(piece='wall_motor',x_m=second['x_m'],height_m=2,wall=second['id']),
            dict(piece='wall_battery',x_m=second['x_m']-1,height_m=2,wall=second['id']),
            dict(piece='loose_block',x_m=0,z_m=4)]
        original=mg.compose(mg.requested_level(dict(level='free',base=added['base'])),ps)[0]
        turned=wall.edit_panel(added['base'],ps,second['id'],dict(yaw_deg=90,z_m=2))
        self.assertTrue(turned['fits'],turned['problems']);self.assertEqual(turned['placements'],ps)
        after=mg.compose(mg.requested_level(dict(level='free',base=turned['base'])),ps)[0]
        for a,b in zip(original['parts'],after['parts']):
            if a['name'].startswith(('your wall_motor 2','your wall_battery 3')):
                self.assertEqual(a['size_m'] if 'size_m' in a else a.get('parts'),b['size_m'] if 'size_m' in b else b.get('parts'))
                dx=a['at_m'][0]-second['x_m'];self.assertAlmostEqual(b['at_m'][0],second['x_m']+a['at_m'][2],places=5)
                self.assertAlmostEqual(b['at_m'][2],2-dx,places=5)
            elif a['name']!=second['id']:self.assertEqual(a,b)
        hinge=next(j for j in after['joints'] if j['name'].startswith('your wall_motor 2') and j['kind']=='hinge')
        self.assertAlmostEqual(abs(hinge['axis'][0]),1)
        before=original['electrical']['devices'][0]['terminals'];now=after['electrical']['devices'][0]['terminals']
        for key,point in before.items():
            self.assertAlmostEqual(now[key][0],second['x_m']+point[2],places=5)
            self.assertAlmostEqual(now[key][2],2-(point[0]-second['x_m']),places=5)
        bad=copy.deepcopy(turned['base']);bad['build_surface']['panels'][1]['yaw_deg']=45
        with self.assertRaises(ValueError):wall.validate(bad)
        with self.assertRaises(ValueError):wall.edit_panel(added['base'],[],second['id'],dict(yaw_deg=90,x_m=0,z_m=0))
        for yaw in (float('nan'),True,181):
            with self.assertRaises(ValueError):wall.edit_panel(added['base'],[],second['id'],dict(yaw_deg=yaw))

    def test_turned_wall_lift_keeps_native_contacts_and_power_for_three_materials(self):
        added=wall.edit_panel(wall.world_base(),[],None,add=True);second=added['wall']
        moved=wall.edit_panel(added['base'],[],second['id'],dict(z_m=2,width_m=4,height_m=4,yaw_deg=90))
        rows,check=wall.world_lift_assembly(second['x_m'],1.6)
        for p in rows:
            if p['piece']!='wire':p['wall']=second['id']
        records=[]
        for material in ('glass','oak','iron'):
            ps=copy.deepcopy(rows);ps[1]['material']=material
            spec=mg.compose(mg.requested_level(dict(level='free',base=moved['base'])),ps)[0]
            with tempfile.TemporaryDirectory() as logs:
                result=mw.rehearse(mw.compile_spec(spec),ENGINE,logs,seconds=12,track=[check['marble']])
            self.assertIsNone(result['error']);measured=machine_chat.lift_checks([check],result)[0]
            self.assertTrue(measured['happened'],measured)
            ledger=result['readouts']['electrical']['networks'][0]['ledger']
            self.assertLess(abs(ledger['electrical_residual_j']),1e-8)
            records.append(dict(material=material,yaw_deg=90,dt_s=1/240,cell_m=.02,check=measured,ledger=ledger,wall_s=result['wall_s']))
        print('TURNED WALL LIFT',json.dumps(records),flush=True)

    def test_resize_has_real_dimensions_and_refuses_to_strand_fixtures(self):
        template=wall.world_template(mg.free_build()['tray']);saved=copy.deepcopy(template)
        r=wall.edit_panel(template['base'],template['placements'],wall.FOUNDATION[0],dict(width_m=8,height_m=5),edit_key='wall_height_m')
        self.assertTrue(r['fits'],r['problems'])
        backing=next(p for p in r['parts'] if p['name']==wall.FOUNDATION[0])
        self.assertEqual(backing['size_m'],[8,5,.02]);self.assertEqual(backing['at_m'],[0,2.5,-.01])
        self.assertEqual(r['edit_guide']['arrows'][0]['at'],[0,5,0])
        self.assertEqual(r['placements'],template['placements']);self.assertEqual(template,saved)
        smaller=wall.edit_panel(template['base'],template['placements'],wall.FOUNDATION[0],dict(height_m=2))
        self.assertFalse(smaller['fits']);self.assertIn('extends beyond the wall',' '.join(smaller['problems']))
        with self.assertRaises(ValueError):wall.edit_panel(template['base'],[],wall.FOUNDATION[0],dict(width_m=.1))
        tampered=copy.deepcopy(r['base']);tampered['parts'][-1]['size_m'][0]=7
        with self.assertRaises(ValueError):mg.requested_level(dict(level='free',base=tampered))

    def test_second_wall_owns_its_mounts_and_translates_only_its_own_pieces(self):
        base=wall.world_base();ps=[dict(piece='wall_battery',x_m=-1,height_m=2),dict(piece='loose_block',x_m=0,z_m=5)]
        added=wall.edit_panel(base,ps,None,add=True);self.assertTrue(added['fits'],added['problems'])
        second=added['wall'];ps += [dict(piece='wall_battery',wall=second['id'],x_m=second['x_m'],height_m=2)]
        changed=wall.edit_panel(added['base'],ps,second['id'],dict(z_m=2,x_m=second['x_m']+1))
        self.assertTrue(changed['fits'],changed['problems'])
        self.assertEqual(changed['placements'][:2],ps[:2])
        self.assertEqual(changed['placements'][2]['x_m'],second['x_m']+1)
        level=mg.requested_level(dict(level='free',base=changed['base']))
        spec=mg.compose(level,changed['placements'])[0]
        devices=spec['electrical']['devices']
        self.assertAlmostEqual(devices[1]['terminals']['plus'][2]-devices[0]['terminals']['plus'][2],2)
        restored=json.loads(json.dumps(dict(base=changed['base'],placements=changed['placements'])))
        self.assertEqual(mg.compose(mg.requested_level(dict(level='free',base=restored['base'])),restored['placements'])[0],spec)
        with self.assertRaises(ValueError):wall.edit_panel(added['base'],[],second['id'],dict(x_m=0,z_m=0))

    def test_relocated_second_wall_lift_has_native_contacts_and_power_for_three_materials(self):
        added=wall.edit_panel(wall.world_base(),[],None,add=True);second=added['wall']
        moved=wall.edit_panel(added['base'],[],second['id'],dict(z_m=2,width_m=4,height_m=4))
        rows,check=wall.world_lift_assembly(second['x_m'],1.6)
        for p in rows:
            if p['piece']!='wire':p['wall']=second['id']
        records=[]
        for material in ('glass','oak','iron'):
            ps=copy.deepcopy(rows);ps[1]['material']=material
            spec=mg.compose(mg.requested_level(dict(level='free',base=moved['base'])),ps)[0]
            with tempfile.TemporaryDirectory() as logs:
                result=mw.rehearse(mw.compile_spec(spec),ENGINE,logs,seconds=12,track=[check['marble']])
            self.assertIsNone(result['error']);measured=machine_chat.lift_checks([check],result)[0]
            self.assertTrue(measured['happened'],measured)
            self.assertTrue(all(p[3]>2 for p in result['paths'][check['marble']]['points']))
            ledger=result['readouts']['electrical']['networks'][0]['ledger']
            self.assertLess(abs(ledger['electrical_residual_j']),1e-8)
            records.append(dict(material=material,check=measured,ledger=ledger,wall_s=result['wall_s']))
        print('SECOND WALL LIFT',json.dumps(records),flush=True)


if __name__=='__main__':unittest.main(verbosity=2)
