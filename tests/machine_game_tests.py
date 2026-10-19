"""The puzzles (/play, scripts/machine_game.py, client/voxel-lab/levels.json):
every level can be solved, cannot be solved without pieces, keeps to its tray,
and scores what the engine measured.

    python tests/machine_game_tests.py [--engine path/to/banjo_live_world_run]

Without an engine the tray and scoring tests still run; the engine tests are
skipped, never passed. Set BANJO_MACHINE_ENGINE=required to fail instead.
"""
import copy
import json
import math
import os
import time
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import machine_world as mw     # noqa: E402
import machine_game as mg      # noqa: E402
import machine_chat as mc      # noqa: E402
import sandbox_mechanics as sm  # noqa: E402

ENGINE = None
if '--engine' in sys.argv:
    i = sys.argv.index('--engine')
    ENGINE = Path(sys.argv[i + 1]).resolve()
    del sys.argv[i:i + 2]
elif os.environ.get('BANJO_LIVE_ENGINE'):
    ENGINE = Path(os.environ['BANJO_LIVE_ENGINE']).resolve()


def need_engine(test):
    def wrapped(self):
        if ENGINE is None or not ENGINE.is_file():
            if os.environ.get('BANJO_MACHINE_ENGINE') == 'required':
                self.fail('banjo_live_world_run is required')
            self.skipTest('no banjo_live_world_run given')
        return test(self)
    wrapped.__name__ = test.__name__
    return wrapped


LEVELS = mg.load_levels()
EMPTY_START_LEVELS = ('easy-river-wheel',)


class Tray(unittest.TestCase):
    def test_game_batches_are_disjoint_and_cover_every_case(self):
        batches=game_test_batches()
        ids=[{test.id() for test in batch} for batch in batches]
        full=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
        expected={test.id() for group in full for test in group}
        self.assertEqual(len(batches),3)
        self.assertEqual(sum(map(len,ids)),len(set().union(*ids)))
        self.assertEqual(set().union(*ids),expected)
        self.assertTrue(all(type(test) is Engine for batch in batches[:2] for test in batch))
        self.assertTrue(all(type(test) is not Engine for test in batches[2]))

    def test_setup_requirements_expose_only_piece_counts(self):
        self.assertEqual(mg.public(mg.level_by_id('easy-power'))['required_pieces'],{'battery':1,'wire':2})
        self.assertEqual(mg.public(mg.level_by_id('laser'))['required_pieces'],{'mirror':2})
        self.assertNotIn('required_pieces',mg.public(mg.free_build()))
        for level in LEVELS:
            shown=mg.public(level)
            self.assertNotIn('solution',shown)
            self.assertTrue(all(isinstance(n,int) and n>0 for n in shown['required_pieces'].values()))

    def test_sandbox_has_five_curated_multi_component_examples(self):
        examples=mg.sandbox_templates()
        self.assertEqual(len(examples),5)
        self.assertEqual(len({r['name'] for r in examples}),5)
        self.assertEqual([row['name'] for row in examples],['Marble skyscraper','Waterworks express',
            'Solar pinball factory','Light the fuse','Electric marble relay'])
        self.assertTrue(set(p for row in examples for p in row['pieces'])<=
                        {t['piece'] for t in mg.free_build()['tray']})
        for row in examples:
            level=mg.requested_level(dict(level='free',base=row['base']))
            compiled=mw.compile_spec(mg.compose(level,row['placements'])[0])
            self.assertGreater(len(compiled['parts']),3,row['name'])
            self.assertFalse(any(any(p['velocity_m_s']) for p in compiled['parts']))
        pristine=copy.deepcopy(examples[0])
        examples[0]['base']['parts'].clear()
        self.assertEqual(mg.sandbox_templates()[0],pristine,'A player edit cannot mutate cached examples')

    def test_every_authored_tray_has_a_reviewed_lesson_control_set(self):
        for level in LEVELS:
            for tray in level['tray']:
                with self.subTest(level=level['id'],piece=tray['piece']):
                    keys=tray['lesson_knobs']
                    self.assertTrue(keys)
                    self.assertEqual(len(keys),len(set(keys)))
                    self.assertTrue(set(keys)<=tray['knobs'].keys())
                    self.assertTrue(set(tray['primary_knobs'])<=set(keys))
        self.assertTrue(all('lesson_knobs' not in t for t in mg.free_build()['tray']))

    def test_lesson_controls_keep_every_reference_machine_physically_identical(self):
        for level in LEVELS:
            trays={t['piece']:t for t in level['tray']}
            # Start with the same declared defaults and change only the values
            # offered in this lesson. Hidden construction versions stay default.
            reachable=[]
            for p in level['solution']:
                tray=trays[p['piece']]
                defaults={k:r.get('default',r.get('choices',[r.get('min','')])[0]) for k,r in tray['knobs'].items()}
                defaults.update({k:v for k,v in p.items() if k=='piece' or k in tray['lesson_knobs']})
                reachable.append(defaults)
            with self.subTest(level=level['id']):
                original=mg.compose(level,level['solution'])[0]
                simplified=mg.compose(level,reachable)[0]
                self.assertEqual(mw.compile_spec(original),mw.compile_spec(simplified))

    def test_level_hint_lists_only_player_editable_properties(self):
        for ident,kept,omitted in [('easy-spring','rest_m','damping_n_s_m'),
                                  ('advanced-capacitor','capacitance_f','leakage_ohm'),
                                  ('easy-gears','teeth','friction_n_m')]:
            text=mc.level_prompt(mg.level_by_id(ident),'hint')
            self.assertIn(kept+' (',text)
            self.assertNotIn(omitted+' (',text)

    def test_shared_recipe_controls_retain_current_and_legacy_reference_machines(self):
        import sandbox_variants as variants
        for family in mg.EASY_ORDER:
            for version in range(1,variants.FAMILY_VERSIONS.get(family,1)+1):
                level=variants.construct(mg.level_by_id(family),42,version=version)
                trays={t['piece']:t for t in level['tray']};reachable=[]
                for p in level['solution']:
                    tray=trays[p['piece']]
                    defaults={k:r.get('default',r.get('choices',[r.get('min','')])[0]) for k,r in tray['knobs'].items()}
                    defaults.update({k:v for k,v in p.items() if k=='piece' or k in tray['lesson_knobs']})
                    reachable.append(defaults)
                with self.subTest(family=family,version=version):
                    self.assertTrue(all(t['lesson_knobs'] for t in level['tray']))
                    self.assertEqual(mw.compile_spec(mg.compose(level,level['solution'])[0]),
                                     mw.compile_spec(mg.compose(level,reachable)[0]))

    def test_divert_water_hides_only_its_optional_source_controls(self):
        level=mg.level_by_id('easy-divert-water')
        self.assertFalse(mg.public(level)['water_controls'])
        source=level['machine']['spouts'][0]
        self.assertEqual(source['discharge_l_s'],1)
        self.assertEqual(source['initial_volume_l'],4)
        self.assertTrue(source.get('valve_open',True))
        self.assertFalse(source.get('reservoir_area_m2',0))
        self.assertEqual(level['time_s'],8)
        self.assertEqual(level['goal']['station']['done_when']['water_in_zone_l']['l'],3)
        self.assertNotIn('water_controls',mg.public(mg.free_build()))
        self.assertNotIn('water_controls',mg.public(mg.level_by_id('easy-water-receiver')))

    def test_spring_relaxed_length_guide_uses_joint_ends_without_releasing_latch(self):
        free=mg.free_build()
        for yaw,pitch,roll in ((0,0,0),(35,25,15),(-45,-20,90)):
            placements=[dict(piece='spring',mechanism_version=3,rest_m=.6,compressed_m=.2,
                             yaw_deg=yaw,pitch_deg=pitch,roll_deg=roll,x_m=0,z_m=0)]
            kept=copy.deepcopy(placements)
            ordinary=mg.ghost(free,placements,0)
            annotated=mg.ghost(free,placements,0,edit_key='rest_m')
            guide=annotated.pop('edit_guide')
            self.assertEqual(ordinary,annotated)
            self.assertEqual(placements,kept)
            joint=ordinary['spring_setup'][0]
            a,b=joint['at_m'],joint['at_b_m'];axis=[(b[i]-a[i])/math.dist(a,b) for i in range(3)]
            self.assertAlmostEqual(math.dist(*guide['rest_span']),joint['rest_m'])
            self.assertEqual(guide['rest_span'][0],a)
            for i in range(3):
                self.assertAlmostEqual(guide['marker'][i],a[i]+joint['rest_m']*axis[i])
                self.assertAlmostEqual(guide['arrows'][0]['direction'][i],axis[i])
            # Each compiled endpoint is rounded to micrometres; their
            # distance can differ by at most sqrt(3) micrometres.
            self.assertAlmostEqual(math.dist(a,b),.2,delta=math.sqrt(3)*1e-6)

    def test_chain_ramp_placement_is_not_limited_to_the_switch_strip(self):
        level=mg.level_by_id('chain')
        for x,z in ((-3,2),(1.2,-1.1),(4,3)):
            p=dict(level['solution'][0],x_m=x,z_m=z)
            spec,checked,_=mg.compose(level,[p])
            self.assertEqual((checked[0]['x_m'],checked[0]['z_m']),(x,z))
            self.assertTrue(mg.ghost(level,[p],0)['fits'])
        self.assertEqual(level['goal']['station']['done_when']['in_zone']['size_m'],[1,.2,.8])
        self.assertEqual(level['time_s'],6)

    def test_contact_search_uses_public_geometry_without_changing_placement_ranges(self):
        level=mg.level_by_id('chain');before=copy.deepcopy(level)
        placed=copy.deepcopy(level['solution'])
        compiled=mw.compile_spec(mg.compose(level,placed)[0])
        knobs=mg.refinement_knobs(level,placed,compiled)
        focused={key:rule for _,key,rule in knobs}
        self.assertLess(focused['z_m']['max']-focused['z_m']['min'],1)
        for key in ('x_m','z_m'):
            self.assertEqual((level['tray'][0]['knobs'][key]['min'],level['tray'][0]['knobs'][key]['max']),(-10,10))
        level['solution']=[{'secret':'never consult this'}]
        self.assertEqual(mg.refinement_knobs(level,placed,compiled),knobs)
        level['solution']=before['solution'];self.assertEqual(level,before)

    def test_knife_plane_snaps_to_the_compiled_member_span_and_releases(self):
        for identity in ('easy-cut', 'cut'):
            with self.subTest(level=identity):
                level = mg.level_by_id(identity)
                proposed = copy.deepcopy(level['solution'])
                proposed[0]['z_m'] += .04
                before = copy.deepcopy(proposed)
                reply = mg.ghost(level, proposed, 0, snapping=True, nearby=True)
                self.assertEqual(proposed, before, 'only an editor suggestion is returned')
                self.assertIn('snap', reply)
                self.assertEqual(reply['snap']['port'], 'cutting plane')
                self.assertAlmostEqual(reply['snap']['knobs']['z_m'], .235)
                self.assertEqual(reply['snap']['knobs']['x_m'], proposed[0]['x_m'])
                spans = [q for q in reply['alignment']['targets'] if q.get('span')]
                self.assertTrue(spans)
                self.assertTrue(any(q['span'][0][1] <= reply['alignment']['primary']['at'][1] <= q['span'][1][1] for q in spans))
                held = reply['snap']['to'] + '|' + reply['snap']['port']
                proposed[0]['z_m'] = .235 + .09
                self.assertNotIn('snap', mg.ghost(level, proposed, 0, snapping=True, nearby=True))
                self.assertIn('snap', mg.ghost(level, proposed, 0, snapping=True, nearby=True, snap_hold=held))
                proposed[0]['z_m'] = .235 + .12
                self.assertNotIn('snap', mg.ghost(level, proposed, 0, snapping=True, nearby=True, snap_hold=held))
                proposed[0].update(z_m=.235, x_m=-1)
                self.assertNotIn('snap', mg.ghost(level, proposed, 0, snapping=True, nearby=True), 'distant collinear guides do not pull pieces')
                proposed[0].update(x_m=-.08, pivot_height_m=2)
                self.assertNotIn('snap', mg.ghost(level, proposed, 0, snapping=True, nearby=True), 'a tangent above the cord is not a cutting alignment')

    def test_prepared_sphere_object_can_snap_without_moving_a_group_or_clipping(self):
        import sandbox_edit
        base={'schema':mw.SCHEMA,'cell_m':.02,'parts':[
            {'name':'board','shape':'box','material':'oak','size_m':[.6,.02,.12],'at_m':[0,.3,0],'fixed':True},
            {'name':'ball','shape':'sphere','material':'glass','size_m':[.04]*3,'at_m':[.1,.34,.045],'fixed':False}]}
        before=copy.deepcopy(base)
        reply=sandbox_edit.ghost(base,'part:ball',[0,0,0],snapping=True,nearby=True)
        self.assertEqual(base,before);self.assertIn('snap',reply)
        self.assertAlmostEqual(reply['snap']['knobs']['z_m'],0)
        self.assertNotIn('snap',sandbox_edit.ghost(base,'part:board',[0,0,0],snapping=True,nearby=True))
        self.assertNotIn('snap',sandbox_edit.ghost(base,'part:ball',[0,.5,0],snapping=True,nearby=True))
        # Seating on an inclined plane is stable, not a creeping translation
        # from repeatedly adding the sphere's normal offset to its x position.
        import machine_alignment as ma
        board=copy.deepcopy(base['parts'][0]);board['turn_deg']=[0,0,-30]
        compiled=mw.compile_spec(dict(base,parts=[board,base['parts'][1]]))
        ball=compiled['parts'][1]
        choices=ma.seat_candidates(dict(diameter_m=.04),ball,compiled)
        self.assertTrue(choices)
        at=min(choices,key=lambda q:q['distance'])['at']
        ball=dict(ball,at_m=at)
        again=ma.seat_candidates(dict(diameter_m=.04),ball,compiled)
        self.assertAlmostEqual(min(again,key=lambda q:q['distance'])['distance'],0,places=8)

    def test_wheel_guides_use_cylinder_centres_and_hinge_axes_without_piece_names(self):
        import machine_alignment as ma
        level=mg.level_by_id('easy-gears')
        proposed=copy.deepcopy(level['solution'])
        _,_,_,compiled=mg._assemble(level,proposed,lenient=True)
        before=copy.deepcopy(compiled)
        row=mg.ghost(level,proposed,0,nearby=True)['alignment']['primary']
        self.assertEqual(row['label'],'wheel axle')
        self.assertEqual(row['at'],[0,.65,0])
        self.assertEqual(row['dir'],[0,0,1])
        self.assertAlmostEqual(row['wheel']['radius_m'],.1608)
        self.assertAlmostEqual(row['wheel']['root_m'],.1272)
        self.assertEqual(compiled,before)
        renamed=copy.deepcopy(compiled)
        names={p['name']:'body '+str(i) for i,p in enumerate(renamed['parts'])}
        for part in renamed['parts']:part['name']=names[part['name']]
        for joint in renamed['joints']:
            for key in ('a','b'):
                if joint.get(key) in names:joint[key]=names[joint[key]]
        renamed.pop('electrical',None)
        wheels=[f for f in ma.features(renamed) if f.get('wheel')]
        self.assertEqual(len(wheels),3)
        self.assertTrue(all(f['at'][1]==.65 and f['dir']==[0,0,1] for f in wheels))

    def test_working_guides_use_compiled_optics_and_the_knifes_edge_circle(self):
        import machine_alignment as ma
        for id,piece in [('easy-mirror','mirror'),('easy-lens','lens'),('easy-cut','knife')]:
            level=mg.level_by_id(id)
            placed=copy.deepcopy(level['solution'])
            index=next(i for i,p in enumerate(placed) if p['piece']==piece)
            before=copy.deepcopy(placed)
            _,_,_,compiled=mg._assemble(level,placed,lenient=True)
            row=mg.ghost(level,placed,index,nearby=True)['alignment']['primary']
            self.assertEqual(placed,before,'guides never mutate declarations')
            if piece=='mirror':
                part=next(p for p in compiled['parts'] if p['name']==row['part'])
                for a,b in zip(row['at'],part['at_m']):self.assertAlmostEqual(a,b,places=6)
                self.assertEqual(row['dir'],mw._axes(part)[0])
            elif piece=='lens':
                lens=next(p for p in compiled['light']['lenses'] if p['on']==row['part'])
                for a,b in zip(row['at'],lens['at_m']):self.assertAlmostEqual(a,b,places=6)
            else:
                blade=next(b for b in compiled['blades'] if b['part']==row['part'])
                joint=next(j for j in compiled['joints'] if j['kind']=='hinge' and j['name'].startswith('your knife'))
                edge=[(a+b)/2 for a,b in zip(blade['heel_m'],blade['tip_m'])]
                self.assertTrue(row['kinematic']);self.assertLess(row['at'][1],edge[1])
                self.assertAlmostEqual(math.dist(row['at'],joint['at_m']),math.dist(edge,joint['at_m']),places=5)

    def test_nearby_marble_snap_centers_on_a_prepared_track_and_releases_in_3d(self):
        free=mg.free_build()
        free['machine']={'schema':mw.SCHEMA,'cell_m':.02,'ground':None,
            'kits':[{'kit':'ramp','name':'prepared path','top_m':[0,.6,0],
                'bottom_m':[.6,.5,0],'width_m':.12,'thickness_m':.02}]}
        marble={'piece':'marble','x_m':.3,'z_m':.045,'placement':'on surface','diameter_m':.04}
        before=copy.deepcopy(marble)
        suggestion=mg.ghost(free,[marble],0,snapping=True,nearby=True)['snap']
        self.assertEqual(marble,before)
        self.assertAlmostEqual(suggestion['knobs']['z_m'],0,places=5)
        self.assertIn('prepared path',suggestion['to'])
        self.assertNotIn('snap',mg.ghost(free,[dict(marble,z_m=.16)],0,snapping=True,nearby=True))
        airborne=dict(marble,placement='at height',height_m=1.8)
        self.assertNotIn('snap',mg.ghost(free,[airborne],0,snapping=True,nearby=True),'same screen line is not proximity in 3D')
        self.assertNotIn('snap',mg.ghost(free,[marble],0,snapping=False,nearby=True),'exact controls do not snap')
        seated=dict(marble,**suggestion['knobs'])
        self.assertFalse(mg.ghost(free,[seated],0,nearby=True)['snap']['moved'])
        near_release=dict(marble,z_m=.085)
        self.assertNotIn('snap',mg.ghost(free,[near_release],0,snapping=True,nearby=True))
        hold=suggestion['to']+'|'+suggestion['port']
        self.assertIn('snap',mg.ghost(free,[near_release],0,snapping=True,nearby=True,snap_hold=hold))
        # A different solid over the landing surface must never be bypassed.
        blocked=copy.deepcopy(free)
        blocked['machine']['parts']=[{'name':'obstacle','shape':'box','material':'oak',
            'at_m':[.3,.75,0],'size_m':[.12,.4,.08],'fixed':True}]
        self.assertNotIn('snap',mg.ghost(blocked,[marble],0,snapping=True,nearby=True))

    def test_sandbox_ghost_refuses_moving_a_prepared_body_into_another(self):
        import sandbox_edit
        base={'schema':mw.SCHEMA,'parts':[{'name':name,'shape':'box','material':'oak',
            'at_m':[x,.1,0],'size_m':[.2,.2,.2],'fixed':True} for name,x in [('one',0),('two',.3)]]}
        self.assertTrue(sandbox_edit.ghost(base,'part:one',[0,0,0])['fits'])
        bad=sandbox_edit.ghost(base,'part:one',[.2,0,0])
        self.assertFalse(bad['fits']);self.assertIn('into two',bad['problems'][0])
        self.assertEqual(base['parts'][0]['at_m'],[0,.1,0])

    def test_sandbox_apparatus_batches_cover_every_prepared_group(self):
        import sandbox_apparatus_tests as apparatus
        batches=apparatus.partitions()
        keys=lambda rows:{(base['title'],obj['id']) for base,_,obj in rows}
        self.assertEqual(set.union(*(keys(batch) for batch in batches)),keys(apparatus.cases()))
        self.assertEqual(sum(map(len,batches)),len(apparatus.cases()))

    def test_sandbox_kit_translation_preserves_glass_oak_iron_mass_geometry_and_pivots(self):
        import sandbox_edit
        for material in ('glass','oak','iron'):
            base={'schema':mw.SCHEMA,'kits':[{'kit':'lever','name':'lever','pivot_m':[0,.3,0],
                'length_m':.8,'width_m':.2,'material':material}],'parts':[]}
            original=mw.compile_spec(base)
            moved,_,compiled=sandbox_edit.edit(base,'kit:lever',[.2,.1,-.15])
            self.assertEqual([mg._volume(p) for p in original['parts']],[mg._volume(p) for p in compiled['parts']])
            for old,new in zip(original['joints'],compiled['joints']):
                for a,b,d in zip(old['at_m'],new['at_m'],[.2,.1,-.15]):self.assertAlmostEqual(a+d,b)
            for old,new in zip(original['parts'],compiled['parts']):
                self.assertEqual(old['size_m'],new['size_m']);self.assertEqual(old['turn_deg'],new['turn_deg'])

    def test_prepared_native_rope_endpoint_follows_only_its_moved_body(self):
        import sandbox_edit,sandbox_showcases
        base=sandbox_showcases.optical_launch();before=copy.deepcopy(base)
        moved,_,compiled=sandbox_edit.edit(base,'part:release ramp gate',[0,0,.06])
        old=base['strands'][0]['path_m'];new=moved['strands'][0]['path_m']
        self.assertEqual(new[0],old[0],'The hanging weight has not moved')
        for i in range(3):self.assertAlmostEqual(new[-1][i],old[-1][i]+(.06 if i==2 else 0))
        self.assertEqual(compiled['strands'][0]['path_m'],new)
        self.assertEqual(base,before,'A refused or accepted edit cannot mutate the shared base')

    def test_every_level_starts_with_an_object_or_visible_goal_area(self):
        for level in LEVELS:
            initial=mw.compile_spec(mg.compose(level,[],leave_out_goal=True)[0])
            self.assertTrue(initial['parts'] or level['goal'].get('area') or level['goal']['station']['done_when'].get('in_zone'),level['id'])
        for ident,target in [('easy-spring','spring load'),('easy-tackle','crate'),('easy-gears','target gear wheel'),('easy-water-wheel','wheel target')]:
            row=mg.level_by_id(ident);initial=mw.compile_spec(mg.compose(row,[],leave_out_goal=True)[0])
            names={p['name'] for p in initial['parts']}
            self.assertIn(target,names)
            compiled=mw.compile_spec(mg.compose(row,row['solution'])[0])
            self.assertEqual(sum(p['name']==target for p in compiled['parts']),1,'The added device must act on the existing target')
        for ident,target in [('easy-spring','spring load'),('easy-tackle','crate')]:
            row=mg.level_by_id(ident);body=next(p for p in row['machine']['parts'] if p['name']==target)
            self.assertAlmostEqual(row['goal']['area']['at_m'][1],body['at_m'][1]+body['size_m'][1]/2+row['goal']['station']['done_when']['rose_m']['m'])

    def test_catalogue_bases_have_no_unrelated_reference_boxes(self):
        for row in mg.load_levels():
            self.assertFalse({'reference marker', 'channel marker'} &
                             {p['name'] for p in row['machine'].get('parts', [])}, row['id'])
        for row in mg.sandbox_templates():
            self.assertFalse({'reference marker', 'channel marker'} &
                             {p['name'] for p in (row['base'] or {}).get('parts', [])}, row['name'])
        gears = mg.level_by_id('easy-gears')
        self.assertIn('target gear wheel',{p['name'] for p in mw.compile_spec(mg.compose(gears, [], leave_out_goal=True)[0])['parts']})
        compiled = mw.compile_spec(mg.compose(gears, gears['solution'])[0])
        self.assertIn('supply housing', {p['name'] for p in compiled['parts']})
        self.assertEqual(compiled['electrical']['devices'][-1]['hinge'],'drive gear axle')
        self.assertFalse(any(j['kind']=='gear' for j in compiled['joints']), 'Teeth contacts must carry the torque')

    def test_edit_guides_follow_compiled_geometry_and_do_not_change_the_setup(self):
        free = mg.free_build()
        placement = [{'piece': 'plank', 'x_m': 0, 'z_m': 0, 'length_m': .6}]
        kept = copy.deepcopy(placement)
        ordinary = mg.ghost(free, placement, 0)
        annotated = mg.ghost(free, placement, 0, edit_key='length_m')
        guide = annotated.pop('edit_guide')
        self.assertEqual(annotated, ordinary)
        self.assertEqual(placement, kept)
        self.assertEqual(len(guide['arrows']), 2)
        self.assertEqual(sorted(a['direction'][0] for a in guide['arrows']), [-1, 1])
        self.assertEqual(sorted(round(a['at'][0], 6) for a in guide['arrows']), [-.3, .3])
        self.assertTrue(guide['resizes'])
        for piece, key, resizes in (('loose_block', 'width_m', True),
                                    ('scaffold', 'height_m', True),
                                    ('wall_marble', 'height_m', False),
                                    ('mirror', 'angle_deg', False),
                                    ('plank', 'x_m', False)):
            with self.subTest(piece=piece, key=key):
                context = mg.level_by_id('easy-wall-drop') if piece == 'wall_marble' else free
                probe_placement = {'piece': piece, 'x_m': 0}
                if context is free:
                    probe_placement['z_m'] = 0
                annotation = mg.ghost(context, [probe_placement], 0, edit_key=key)['edit_guide']
                self.assertEqual(annotation['resizes'], resizes)
        for yaw, pitch in ((90, 0), (37, 25), (-65, -35)):
            turned = [dict(placement[0], yaw_deg=yaw, pitch_deg=pitch)]
            guide = mg.ghost(free, turned, 0, edit_key='length_m')['edit_guide']
            axis = mw._mat_apply(mw.heading(yaw, pitch, 0), [1, 0, 0])
            self.assertEqual(len(guide['arrows']), 2)
            for a in guide['arrows']:
                self.assertAlmostEqual(abs(sum(v * w for v, w in zip(a['direction'], axis))), 1, places=5)
        track = [{'piece': 'track', 'x_m': 0, 'z_m': 0, 'yaw_deg': 90}]
        drop = mg.ghost(free, track, 0, edit_key='drop_m')['edit_guide']
        self.assertEqual(len(drop['arrows']), 1)
        self.assertLess(drop['arrows'][0]['direction'][1], -.9)
        self.assertLess(drop['arrows'][0]['at'][2], -.5, 'the lower end follows the turned board')
        end = mg.ghost(free, track, 0, edit_key='end')['edit_guide']
        self.assertLess(end['marker'][2], -.5)
        self.assertEqual(end['arrows'], [])
        for item in free['tray']:
            if item.get('attach'):
                continue
            for key, rule in item['knobs'].items():
                if key in ('x_m', 'z_m'):
                    continue
                values = rule.get('choices', [rule.get('default', rule.get('min')), rule.get('min'), rule.get('max')])
                for value in values:
                    if value is None:
                        continue
                    with self.subTest(piece=item['piece'], key=key, value=value):
                        context = copy.deepcopy(free)
                        if item['piece'] in ('water_wheel', 'water_tank', 'water_chute', 'water_collector'):
                            context['machine'] = copy.deepcopy(mg.sandbox_water_launch.CHANNEL_BASE)
                            context['custom_base'] = True
                        p = [{'piece': item['piece'], **{k: 0 for k in ('x_m', 'z_m') if k in item['knobs']}, key: value}]
                        before = mg.ghost(context, p, 0)
                        after = mg.ghost(context, p, 0, edit_key=key)
                        guide = after.pop('edit_guide')
                        self.assertEqual(after, before)
                        if rule.get('part') or rule.get('hinge') or rule.get('terminal') or rule.get('power_port') or not after['parts']:
                            self.assertIsNone(guide)
                            continue
                        self.assertEqual(guide['key'], key)
                        for arrow in guide['arrows']:
                            self.assertAlmostEqual(sum(v * v for v in arrow['direction']), 1, places=6)
        self.assertIsNone(mg.ghost(free, placement, 0, edit_key='unrecognised')['edit_guide'])

    def test_sandbox_templates_keep_the_base_and_readings_and_cannot_replace_a_level(self):
        for template in mg.sandbox_templates():
            level = mg.requested_level({'level': 'free', 'base': template['base']})
            spec, _, _ = mg.compose(level, template['placements'])
            compiled = mw.compile_spec(spec)
            self.assertTrue(compiled['parts'])
            if template['base']:
                self.assertEqual(spec['stations'], template['base'].get('stations', []))
                for part in template['base'].get('parts', []):
                    self.assertIn(part, spec['parts'], 'the base supports are preserved')
                for kit in template['base'].get('kits', []):
                    self.assertIn(kit, spec['kits'])
                g = mg.ghost(level, [{'piece': 'marble', 'x_m': -1.8, 'z_m': -1.8}], 0)
                self.assertTrue(g['fits'], g['problems'])
        base = mg.sandbox_templates()[1]['base']
        with self.assertRaisesRegex(ValueError, 'not a level'):
            mg.requested_level({'level': 'gap', 'base': base})
        bad = copy.deepcopy(mg.free_build()['machine'])
        bad['parts'].append({'name': 'your block 1', 'shape': 'box', 'material': 'oak', 'size_m': [.1, .1, .1], 'at_m': [0, .05, 0], 'fixed': True})
        with self.assertRaisesRegex(ValueError, 'reserved'):
            mg.requested_level({'level': 'free', 'base': bad})

    def test_every_level_is_well_formed_and_its_solution_fits_its_tray(self):
        ids=[l['id'] for l in LEVELS]
        self.assertEqual(ids[0],'easy-wall-drop','start with gravity and a cup, without depth alignment')
        self.assertLess(ids.index('easy-loop'),ids.index('easy-power'))
        self.assertLess(ids.index('easy-power'),ids.index('advanced-parallel'))
        self.assertLess(ids.index('easy-mirror'),ids.index('laser'))
        self.assertLess(ids.index('easy-river-wheel'),ids.index('easy-river-lift'))
        chapters=[l['onboarding']['chapter'] for l in LEVELS]
        self.assertEqual(chapters,sorted(chapters),'mechanics precedes electricity, water and mixed heat tasks')
        self.assertEqual(mg.level_by_id('easy-gears')['onboarding']['chapter'],'Level 2: 3D Mechanics')
        self.assertEqual(mg.level_by_id('easy-power')['onboarding']['chapter'],'Level 3: Electricity')
        self.assertEqual([l['onboarding']['rank'] for l in LEVELS],list(range(1,len(LEVELS)+1)))
        self.assertEqual(len({l['id'] for l in LEVELS}), len(LEVELS))
        for level in LEVELS:
            spec, checked, cost = mg.compose(level, level['solution'])
            mw.compile_spec(spec)
            self.assertLessEqual(cost, level['par'], f'{level["id"]}: its own solution is over par')
            self.assertNotIn('solution', mg.public(level), 'the page is never sent the answer')

    def test_wall_lessons_are_early_planar_lessons_without_expanding_the_level_inventory(self):
        ids = [level['id'] for level in LEVELS]
        wall_ids = ['easy-wall-drop', 'easy-wall-track', 'easy-wall-funnel', 'easy-wall-peg', 'easy-wall-seesaw', 'easy-wall-wheel']
        new_ids=['easy-wall-loop','easy-wall-switch','easy-wall-fill','easy-wall-current']
        self.assertEqual(ids[:10], wall_ids+new_ids)
        self.assertEqual(ids[10], 'easy-weight', 'Introduce depth with a familiar falling weight')
        self.assertEqual([l['id'] for l in LEVELS if l['onboarding']['chapter']=='Level 1: Wall Basics'], wall_ids+new_ids)
        builders = dict(mg.PIECES)
        for ident in wall_ids:
            level = mg.level_by_id(ident)
            self.assertEqual(level['onboarding']['chapter'], 'Level 1: Wall Basics')
            self.assertEqual(level['wall_mode'], level['machine']['build_surface'])
            self.assertEqual(level['wall_mode']['version'], 2)
            self.assertNotIn('workshop clear guard', {p['name'] for p in level['machine']['parts']})
            self.assertEqual(len(level['tray']), 1)
            row = level['tray'][0]
            self.assertEqual(row['count'], 1)
            self.assertEqual(row['lesson_knobs'], ['x_m', 'height_m'])
            self.assertNotIn('z_m', row['knobs'])
            self.assertFalse(any(key in row['knobs'] for key in ('yaw_deg', 'pitch_deg', 'roll_deg')))
            self.assertFalse(level.get('free'))
            mg.compose(level, level['solution'])
            mg.compose(level, [], leave_out_goal=True)
        self.assertEqual(mg.PIECES, builders, 'Wall construction must not leak its builders into other levels')

    def test_catalog_task_counts_describe_player_work_without_changing_a_machine(self):
        self.assertEqual(set(mg.PLAYER_TASK_COUNTS), {l['id'] for l in LEVELS})
        before = copy.deepcopy(LEVELS)
        for level in LEVELS:
            shown = mg.public(level)
            self.assertIs(type(shown['task_count']), int)
            self.assertGreater(shown['task_count'], 0)
            self.assertNotIn('solution', shown)
        self.assertEqual(mg.public(mg.level_by_id('gap'))['task_count'], 1)
        self.assertEqual(mg.public(mg.level_by_id('laser'))['task_count'], 2)
        self.assertEqual(mg.public(mg.level_by_id('sun'))['task_count'], 2)
        self.assertEqual(mg.public(mg.level_by_id('easy-solar'))['task_count'], 2)
        self.assertEqual(mg.public(mg.level_by_id('fire'))['task_count'], 4)
        self.assertEqual(mg.public(mg.level_by_id('easy-switch'))['task_count'], 2)
        variant = copy.deepcopy(mg.level_by_id('easy-switch'))
        variant['id'] = 'easy-switch--v2--12345678--0'
        variant['variant'] = {'family':'easy-switch'}
        self.assertEqual(mg.public(variant)['task_count'], 2)
        self.assertNotIn('task_count', mg.public(mg.free_build()))
        self.assertEqual(LEVELS, before, 'menu metadata cannot mutate physical levels')

    def test_onboarding_assessments_are_complete_and_blind_packets_hide_answers(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('onboarding_audit',ROOT/'scripts/audit-level-onboarding.py')
        audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
        receipt=json.loads((ROOT/'docs/level-onboarding-audit.json').read_text(encoding='utf-8'))
        self.assertFalse(receipt['human_times_measured'])
        # Lessons added after the blind probe are not in its receipt; each
        # must say so in its own estimate basis rather than borrow the probe's.
        unprobed={l['id'] for l in LEVELS if 'not yet probed' in l['onboarding']['estimate_basis']}
        self.assertEqual(unprobed,{'easy-roll','easy-block','easy-rope','easy-thread',
                                  'easy-wall-drop','easy-wall-track','easy-wall-funnel','easy-wall-peg','easy-wall-seesaw','easy-wall-wheel',
                                  'easy-wall-loop','easy-wall-switch','easy-wall-fill','easy-wall-current'})
        self.assertEqual({r['id'] for r in receipt['levels']},{l['id'] for l in LEVELS}-unprobed)
        for level in LEVELS:
            exported=audit.packet(level)
            self.assertFalse({'solution','wrong','hints','solution_inputs'} & set(exported['player']))
            self.assertNotIn('solution',exported['scene'])
            lo,hi=mg.public(level)['onboarding']['estimated_minutes']
            self.assertTrue(0<lo<=hi)
            self.assertIn('not measured human',mg.public(level)['onboarding']['estimate_basis'])

    def test_the_tray_is_enforced(self):
        gap = mg.level_by_id('gap')
        with self.assertRaises(mg.LevelRefused) as caught:
            mg.compose(gap, [{'piece': 'cannon'}])
        self.assertIn('piece is one of plank', caught.exception.problems[0])
        two = [dict(gap['solution'][0]), dict(gap['solution'][0])]
        with self.assertRaises(mg.LevelRefused):
            mg.compose(gap, two)
        wild = [dict(gap['solution'][0], length_m=9.0)]
        with self.assertRaises(mg.LevelRefused) as caught:
            mg.compose(gap, wild)
        self.assertIn('length_m is 0.2 to 1.2', ' '.join(caught.exception.problems))
        sneaky = [dict(gap['solution'][0], material='glass')]
        with self.assertRaises(mg.LevelRefused):
            mg.compose(gap, sneaky)
        fire = mg.level_by_id('fire')
        costly = [dict(fire['solution'][0], powder_g=3.0, x_m=1.4)]
        _, _, cost = mg.compose(fire, costly)
        self.assertEqual(cost, 34.0)   # 10 + 8 per gram

    def test_pieces_are_set_down_on_what_is_there_and_never_go_into_anything(self):
        gap = mg.level_by_id('gap')

        def plank(length, x):
            spec, _, _ = mg.compose(gap, [{'piece': 'plank', 'length_m': length, 'x_m': x}])
            return next(p for p in mw.compile_spec(dict(spec, stations=[]))['parts'] if p['name'] == 'your plank 1')

        # Across the gap onto the ledges (2 cm below the tables): level with them.
        self.assertAlmostEqual(plank(0.7, 0.3)['at_m'][1] + 0.01, 0.302, places=6)
        # Too long for the ledges: on the tables' tops, a step up.
        self.assertAlmostEqual(plank(0.9, 0.3)['at_m'][1] + 0.01, 0.322, places=6)
        # Too short to reach either: down on the floor of the gap.
        self.assertAlmostEqual(plank(0.55, 0.3)['at_m'][1] + 0.01, 0.022, places=6)
        self.assertFalse(plank(0.7, 0.3)['fixed'], 'a plank is held by gravity, not bolted')
        # A bolted piece stood inside something solid is refused, and says where.
        laser = mg.level_by_id('laser')
        with self.assertRaises(mg.LevelRefused) as caught:
            mg.compose(laser, [{'piece': 'mirror', 'x_m': -0.35, 'z_m': 0.5, 'angle_deg': 0}])
        self.assertIn('your mirror 1 goes 120 mm into wall', caught.exception.problems[0])
        with self.assertRaises(mg.LevelRefused) as caught:
            mg.compose(laser, [{'piece': 'mirror', 'x_m': 0.6, 'z_m': 0.0, 'angle_deg': 45},
                               {'piece': 'mirror', 'x_m': 0.6, 'z_m': 0.0, 'angle_deg': -45}])
        self.assertIn('into your mirror', caught.exception.problems[0])

    def test_every_piece_can_be_moved_across_and_turned_any_way_for_nothing(self):
        for level in LEVELS:
            for t in level['tray']:
                turning = sorted(k for k, r in t['knobs'].items() if r.get('turning'))
                # A mirror turns about the vertical by its own angle_deg; a
                # counterweight on a rope is not something to turn.
                self.assertEqual(turning, ['angle_deg', 'pitch_deg', 'roll_deg'] if t['piece'] == 'mirror'
                                 else sorted(t['turns']) if 'turns' in t
                                 else [] if t.get('turning') is False or level.get('turning') is False
                                 else ['pitch_deg', 'roll_deg', 'yaw_deg'], level['id'])
                # Moved across too, but for a counterweight, which hangs in
                # line with the beam its rope runs along.
                if t.get('across') is False:
                    self.assertNotIn('z_m', t['knobs'])
                else:
                    self.assertIn('z_m', t['knobs'])
            # Unturned, a level's own solution is built exactly as before.
            spec, _, cost = mg.compose(level, level['solution'])
            self.assertFalse(any('turned' in k for k in spec['kits']), level['id'])
            knobs = {t['piece']: t['knobs'] for t in level['tray']}
            turned = [dict(p, **{k: v for k, v in (('pitch_deg', 10), ('roll_deg', -20)) if k in knobs[p['piece']]})
                      for p in level['solution']]
            self.assertEqual(mg.check_placements(level, turned)[1], cost, 'turning costs nothing')

    def test_turn_of_and_heading_are_the_engines_turn(self):
        import random
        rng = random.Random(4)
        for i in range(500):
            t = [rng.uniform(-180, 180) for _ in range(3)]
            if i % 5 == 0:
                t[1] = rng.choice([90.0, -90.0])     # straight up or down
            m = mw.rotation(t)
            back = mw.rotation(mw.turn_of(m))
            self.assertLess(max(abs(m[r][c] - back[r][c]) for r in range(3) for c in range(3)), 1e-6, t)
        # Yaw takes +x toward -z; pitch lifts the +x end; roll turns about x.
        self.assertEqual([round(v, 9) + 0 for v in mw._mat_apply(mw.heading(90, 0, 0), [1, 0, 0])], [0, 0, -1])
        self.assertEqual([round(v, 9) + 0 for v in mw._mat_apply(mw.heading(0, 90, 0), [1, 0, 0])], [0, 1, 0])
        self.assertEqual([round(v, 9) + 0 for v in mw._mat_apply(mw.heading(0, 0, 90), [0, 1, 0])], [0, 0, 1])

    def test_a_turned_piece_turns_everything_it_made_and_stands_on_the_ground(self):
        fire = mg.level_by_id('fire')
        aimed = [dict(fire['solution'][0], yaw_deg=20)]
        c = mw.compile_spec(mg.compose(fire, aimed)[0])
        way = [math.cos(math.radians(20)), 0.0, -math.sin(math.radians(20))]
        breech = c['thermo']['gas_regions'][0]
        wad = next(j for j in c['joints'] if j['name'] == 'your cannon 1 wad')
        for got in (breech['axis'], wad['axis']):
            self.assertLess(math.dist(got, way), 1e-6, 'the push and the wad turn with the barrel')
        parts = {p['name']: p for p in c['parts']}
        ball, barrel = parts['your cannon 1 ball']['at_m'], parts['your cannon 1 barrel']['at_m']
        out = [ball[i] - barrel[i] for i in range(3)]
        # (to the micrometre its positions are given to)
        self.assertLess(math.dist([v / math.hypot(*out) for v in out], way), 1e-5, 'the ball is out along the barrel')
        # Tipped so far its breech would go into the ground, it is lifted to
        # stand on it, not refused and not buried.
        tipped = mw.compile_spec(mg.compose(fire, [dict(fire['solution'][0], bore_height_m=0.05, pitch_deg=40)])[0])
        low = min(mw.lowest_point(s) for p in tipped['parts'] for s in mw.solids_of(p))
        self.assertGreaterEqual(low, 0.0)
        self.assertLess(low, 0.01)
        for setup in (c,tipped):
            barrel=next(p for p in setup['parts'] if p['name']=='your cannon 1 barrel')
            coil=next(d for d in setup['electrical']['devices'] if d['name']=='your cannon 1')
            for key,offset in (('plus',[0,.075,-.045]),('minus',[0,.075,.045])):
                expected=[barrel['at_m'][i]+v for i,v in enumerate(mw._mat_apply(mw.rotation(barrel['turn_deg']),offset))]
                self.assertLess(math.dist(coil['terminals'][key],expected),1e-8,'pins turn and lift with the actual barrel')
        # A tipped plank is set down clear of what is under it.
        gap = mg.level_by_id('gap')
        spec, _, _ = mg.compose(gap, [dict(gap['solution'][0], pitch_deg=12, yaw_deg=25)])
        plank = next(p for p in mw.compile_spec(spec)['parts'] if p['name'] == 'your plank 1')
        self.assertEqual(plank['turn_deg'], mw.turn_of(mw.heading(25, 12, 0)))

    def test_a_ghost_says_where_a_piece_would_be_and_why_it_cannot_go_there(self):
        # Before it is set down: compiled, never run (no engine here).
        gap = mg.level_by_id('gap')
        g = mg.ghost(gap, [dict(gap['solution'][0])], 0)
        self.assertTrue(g['fits'], g['problems'])
        self.assertEqual([p['name'] for p in g['parts']], ['your plank 1'])
        self.assertAlmostEqual(g['parts'][0]['at_m'][1], 0.292, places=6)     # down on the ledges
        laser = mg.level_by_id('laser')
        g = mg.ghost(laser, [{'piece': 'mirror', 'x_m': -0.35, 'z_m': 0.5, 'angle_deg': 0}], 0)
        self.assertFalse(g['fits'])
        self.assertEqual(g['problems'], ['your mirror 1 goes 120 mm into wall; move it'])
        self.assertEqual(len(g['parts']), 1, 'a ghost that does not fit is still shown where it is')
        # The second of two: only its own parts, and only its own problems.
        two = laser['solution'] + [{'piece': 'mirror', 'x_m': -0.35, 'z_m': 0.5, 'angle_deg': 0}]
        with self.assertRaises(mg.LevelRefused):
            mg.ghost(laser, two, 2)          # the tray holds two mirrors
        g = mg.ghost(laser, laser['solution'], 1)
        self.assertEqual((g['fits'], [p['name'] for p in g['parts']]), (True, ['your mirror 2', 'your mirror 2 stand']))
        tight = dict(mg.level_by_id('fire'), budget=20)
        g = mg.ghost(tight, [dict(tight['solution'][0], powder_g=3.0)], 0)
        self.assertEqual(g['problems'], ['the pieces would cost 34; the budget is 20'])
        self.assertTrue(g['parts'])
        # A panel's ghost says how squarely it faces the sun, for aiming it:
        # 0.25 m2 under 1000 W/m2, less by the slant the sun meets it at.
        sun = mg.level_by_id('sun')
        faced = mg.ghost(sun, sun['solution'], 0)['sun'][0]
        self.assertEqual((faced['off_sun_deg'], faced['sunlight_w']), (0.0, 250.0))
        flat = mg.ghost(sun, [{k: v for k, v in sun['solution'][0].items() if k not in ('yaw_deg', 'pitch_deg')}], 0)
        self.assertEqual((flat['sun'][0]['off_sun_deg'], flat['sun'][0]['sunlight_w']), (75.0, 64.7))

    def test_nothing_floats(self):
        # Every fixed part stands on the ground or is bolted to one that does,
        # by a chain of them: the level's own (level 6's laser sits on its
        # post) and the player's wherever its knobs put it (a mirror on a
        # stand, a cannon's barrel, a ramp on two legs) -- as the solution has
        # it and with every knob at either end of its range.
        for level in LEVELS:
            tries = [level['solution']]
            for t in level['tray']:
                if t.get('attach'):
                    continue      # a join adds a joint between two parts, never a part that could float
                for end in ('min', 'max'):
                    p = {'piece': t['piece']}
                    for key, rule in t['knobs'].items():
                        p[key] = rule['choices'][-1 if end == 'max' else 0] if 'choices' in rule else (
                            knob_default(rule) if rule.get('turning') or any(rule.get(k) for k in ('part', 'terminal', 'hinge', 'power_port')) else rule[end])
                    tries.append([p])
            for placements in tries:
                parts = mg._assemble(level, placements, lenient=True)[3]['parts']
                held = mg.held_up(parts)
                with self.subTest(level=level['id'], placements=placements):
                    self.assertEqual([p['name'] for p in parts if p.get('fixed') and p['name'] not in held], [])
        # The stand is the piece's: shown with its ghost, standing on the ground.
        laser = mg.level_by_id('laser')
        stand = next(p for p in mg.ghost(laser, laser['solution'], 0)['parts'] if p['name'] == 'your mirror 1 stand')
        self.assertAlmostEqual(stand['at_m'][1] - 0.5 * stand['size_m'][1], 0.0, places=6)
        # Level 8's rope turns over pulley blocks hung from the beam, in line with it.
        tackle = mg._with_free_knobs(next(l for l in json.loads(mg.LEVELS_PATH.read_text())['levels'] if l['id']=='tackle'))
        parts = {p['name']: p for p in mg._assemble(tackle, tackle['solution'])[3]['parts']}
        for name in ('your tackle 1 pulley 1', 'your tackle 1 pulley 2'):
            block, beam = parts[name], parts['gantry beam']
            self.assertAlmostEqual(block['at_m'][1] + 0.5 * block['size_m'][1], beam['at_m'][1] - 0.5 * beam['size_m'][1])
            self.assertEqual(block['at_m'][2], beam['at_m'][2])
        self.assertNotIn('z_m', tackle['tray'][0]['knobs'], 'a counterweight hangs in line with its beam')

    def test_every_level_opens_before_any_piece_is_placed(self):
        # Shown, not run: a goal about a piece not placed yet is left out and
        # what it needs is said. An empty learning field is also valid; its
        # native opening is checked separately below.
        for level in LEVELS:
            spec, _, _ = mg.compose(level, [], leave_out_goal=True)
            parts = mw.compile_spec(spec)['parts']
            if level['id'] in EMPTY_START_LEVELS:
                self.assertEqual(parts, [], level['id'])
            else:
                self.assertTrue(parts, level['id'])
        steam = mg.level_by_id('steam')
        spec, _, _ = mg.compose(steam, [], leave_out_goal=True)
        self.assertEqual((spec['_needs'], spec['stations']), ('Place a steam engine: the goal is its piston', []))
        spec, _, _ = mg.compose(steam, steam['solution'], leave_out_goal=True)
        self.assertNotIn('_needs', spec)
        self.assertEqual(spec['stations'][0]['title'], steam['goal']['title'])

    def test_a_win_is_scored_by_the_energy_it_took(self):
        # Making the pieces: mass (the engine's densities) times the material's
        # embodied energy. Level 1's 0.7 m oak plank is 2.94 kg, 30.6 MJ.
        gap = mg.level_by_id('gap')
        compiled = mw.compile_spec(mg.compose(gap, gap['solution'])[0])
        plank = mg.pieces_energy(compiled)['your plank 1']
        self.assertAlmostEqual(plank['kg'], 0.7 * 0.02 * 0.3 * 700.0, places=3)
        self.assertAlmostEqual(plank['j'], plank['kg'] * 10.4e6, delta=1.0)
        # Aluminium costs six times iron's energy a kilogram: on level 8 the
        # heavier iron counterweight takes less energy to make.
        tackle = mg._with_free_knobs(next(l for l in json.loads(mg.LEVELS_PATH.read_text())['levels'] if l['id']=='tackle'))
        def made(kg, ratio, h):
            c = mw.compile_spec(mg.compose(tackle, [dict(tackle['solution'][0], counterweight_kg=kg, ratio=ratio,
                                                         drop_from_m=h)])[0])
            return mg.pieces_energy(c)['your tackle 1']['j']
        self.assertLess(made(7.9, 2, 1.2), made(4.7, 3, 1.75) / 3)
        # The run, each once: what the batteries gave, fuel burned in heaters
        # (level 4's 12 kW firebox, 2 s: 24 kJ), and the powder in the charges
        # (level 3's 1 g: 2.8 kJ). A coil's heat came out of a battery: the
        # engine's heat ledger counts it again, and it is not taken from there.
        steam = mg.level_by_id('steam')
        compiled = mw.compile_spec(mg.compose(steam, steam['solution'])[0])
        self.assertEqual(mg.run_energy(compiled, {}, 2.0)['heat_j'], 24000)
        fire = mg.level_by_id('fire')
        compiled = mw.compile_spec(mg.compose(fire, fire['solution'])[0])
        run = mg.run_energy(compiled, {'heat_ledger': {'heater_in_j': 2000.0}}, 1.0)
        # Millijoule receipts retain the compiled charge geometry's precision.
        self.assertEqual((run['heat_j'], run['powder_j'], run['electric_j']), (0, 2799.993, 0))
        # A person's test pull: the work it did counts; what pulled back does not.
        pulled = mg.run_energy(compiled, {'pulls': [{'body': 'x', 'work_j': 15.0}, {'body': 'y', 'work_j': -4.0}]}, 1.0)
        self.assertEqual((pulled['pull_j'], pulled['j']), (15, 2814.993))
        battery = {'batteries': [{'name': 'b', 'capacity_j': 1000.0, 'charge_j': 600.0}]}
        self.assertEqual(mg.run_energy(battery | {'parts': []},
                                       {'machines': {'batteries': [{'name': 'b', 'charge_j': 450.0}]}})['electric_j'], 150)
        # Stars: the goal, within a quarter of par, at or under par.
        par = gap['par_energy_j']
        checked = mg.check_placements(gap, gap['solution'])[0]
        self.assertEqual([mg.stars(gap, checked, 21, 1.9, energy_j=e)['stars'] for e in (par, 1.2 * par, 1.3 * par)],
                         [3, 2, 1])
        self.assertEqual(mg.stars(gap, checked, 21, None, energy_j=par)['stars'], 0)
        self.assertEqual(mg.stars(gap, checked, 21, 1.9, helped=True, energy_j=par)['stars'], 1)
        self.assertTrue(all(level.get('par_energy_j') for level in LEVELS), 'every level has an energy par')

    def test_a_goal_about_a_piece_needs_that_piece(self):
        with self.assertRaises(mg.LevelRefused) as caught:
            mg.compose(mg.level_by_id('steam'), [])
        self.assertIn('Place a steam engine', caught.exception.problems[0])

    def test_stars_come_from_the_goal_the_budget_and_the_pieces(self):
        level = mg.level_by_id('cut')
        _, checked, cost = mg.compose(level, level['solution'])
        self.assertEqual(mg.stars(level, checked, cost, 0.7)['stars'], 3)
        self.assertEqual(mg.stars(level, checked, cost, None)['stars'], 0)
        self.assertEqual(mg.stars(level, checked, cost, level['time_s'] + 1)['stars'], 0)
        self.assertEqual(mg.stars(level, checked, 30.0, 0.7)['stars'], 2)    # over par
        self.assertEqual(mg.stars(level, checked, cost, 0.7, helped=True)['stars'], 1)

    def test_the_chat_places_only_tray_pieces_and_is_held_to_the_level(self):
        level = mg.level_by_id('gap')
        answers = iter([
            ({'reply': 'A cannon.', 'placements': [{'piece': 'cannon', 'x_m': 0.0}]}, {}),
            ({'reply': 'A plank over the gap.', 'placements': level['solution']}, {}),
        ])
        seen = []

        def call(messages):
            seen.append(messages)
            return next(answers)

        r = mc.respond_level('Place it for me', level, [], mode='build', call=call)
        self.assertEqual(len(seen), 2, 'a piece not on the tray goes back to the model once')
        self.assertIn('piece is one of plank', json.dumps(seen[1][-1]))
        self.assertEqual(r['placements'][0]['length_m'], 0.7)
        self.assertTrue(r['helped'])
        self.assertNotIn(json.dumps(level['solution']), json.dumps(seen[0]), 'the model is never shown the answer')
        # A knob past its range is brought to the end of the range, as the
        # slider would; a knob the piece does not have is left out.
        pulled = mc.respond_level('Place it', level, [], mode='build', call=lambda m: (
            {'reply': 'A long plank.', 'placements': [{'piece': 'plank', 'length_m': 9.0, 'x_m': 0.3,
                                                       'colour': 'red'}]}, {}))
        self.assertEqual((pulled['placements'][0]['length_m'], 'colour' in pulled['placements'][0]), (1.2, False))
        # Several options: the first that is built is used.
        opts = mc.respond_level('Place it', level, [], mode='build', call=lambda m: (
            {'reply': 'Two ways.', 'options': [[{'piece': 'cannon'}], level['solution']]}, {}))
        self.assertEqual(opts['placements'][0]['x_m'], 0.3)
        hint = mc.respond_level('Help', level, [], mode='hint', call=lambda m: ({'reply': 'Bridge the gap.'}, {}))
        self.assertEqual(hint['reply'], 'Bridge the gap.')
        self.assertNotIn('placements', hint)

    def test_failed_gear_hint_uses_visible_controls_and_one_action_without_a_private_solution(self):
        level=mg.level_by_id('easy-gears');before=copy.deepcopy(level);seen=[]
        last={'goal_at_s':None,'world_t':2.35,'measurements':{'stations':[{'done':False}]}}
        def call(messages):
            seen.extend(messages);return {'reply':'Add a gear from the tray first.','placements':level['solution']},{}
        result=mc.respond_level('Help with my failed attempt',level,[],mode='hint',last_run=last,call=call)
        self.assertEqual(result['reply'],'Add a gear from the tray first.')
        self.assertNotIn('placements',result)
        self.assertEqual(json.loads(seen[1]['content'])['last_run'],last)
        self.assertIn('ONE next action',seen[0]['content'])
        self.assertIn('Teeth, Radius and Axle height',seen[0]['content'])
        self.assertIn('bigger is not automatically a better fit',seen[0]['content'])
        self.assertNotIn(json.dumps(level['solution']),json.dumps(seen))
        self.assertEqual(level,before)

    def test_coaching_is_read_only_names_current_targets_and_never_sees_the_solution(self):
        level=mg.level_by_id('gap');placed=[];seen=[]
        ui={'targets':[{'id':'tray:plank','label':'Add plank'},{'id':'piece:0','label':'Plank','at_m':[0,.1,0]}]}
        def call(messages):
            seen.append(messages)
            return {'reply':'Add the plank to bridge the gap.','guide':{'target_id':'tray:plank','gesture':'click'},
                    'placements':level['solution'],'spec':level['machine'],'helped':True},{}
        result=mc.respond_coach(level,placed,ui,call=call)
        self.assertEqual(result['guide'],{'target_id':'tray:plank','gesture':'click'})
        self.assertEqual(placed,[])
        for key in ['placements','spec','helped','rehearsal']:
            self.assertNotIn(key,result)
        self.assertNotIn(json.dumps(level['solution']),json.dumps(seen))

        for target in ['javascript:alert(1)',{'bad':'selector'},None]:
            r=mc.respond_coach(level,[],ui,call=lambda m: ({'reply':'Try it.','guide':{'target_id':target}},{}))
            self.assertIsNone(r['guide'])
        for at in [[999,0,0],[float('nan'),0,0],[True,0,0],[0,0],'<script>']:
            r=mc.respond_coach(level,[],ui,call=lambda m: ({'reply':'Drag it.','guide':{'target_id':'piece:0','gesture':'drag','to_m':at}},{}))
            self.assertNotIn('to_m',r['guide'])
        r=mc.respond_coach(level,[],ui,call=lambda m: ({'reply':'Drag toward the gap.','guide':{'target_id':'piece:0','gesture':'drag','to_m':[.3,.1,0]}},{}))
        self.assertEqual(r['guide']['to_m'],[.3,.1,0])
        self.assertIn('Explore the Sandbox design',mc.level_prompt(mg.free_build(),'coach'))

    def test_specific_heater_question_still_reaches_the_model(self):
        level=mg.level_by_id('easy-heat');seen=[]
        ui={'editing':{'p':{'piece':'ignition','attachment_version':2,'target':'','preset':'warm'}},
            'targets':[{'id':'control:heater-attach'}]}
        def call(messages):
            seen.extend(messages);return {'reply':'At fixed voltage, lower resistance allows greater current.'},{}
        answer=mc.respond_level('Why does lower resistance produce more heat?',level,[],ui=ui,call=call)
        self.assertTrue(seen)
        self.assertIn('lower resistance',answer['reply'])

    def test_heater_help_knows_editor_attachment_choices_and_circuit_without_a_model(self):
        level=copy.deepcopy(mg.level_by_id('easy-heat'))
        level.pop('solution');level.pop('wrong')
        def unavailable(messages):
            self.fail('Basic heater assembly help must work without calling a model')
        p={'piece':'ignition','attachment_version':2,'target':'','preset':'warm'}
        ui={'editing':{'p':p},'targets':[{'id':'control:heater-attach','label':'Clip to cord'}]}
        reply=mc.respond_coach(level,[],ui,call=unavailable)
        self.assertEqual(reply['guide']['target_id'],'control:heater-attach')
        self.assertIn('Clip to cord',mc.respond_level('What do I do?',level,[],ui=ui,call=unavailable)['reply'])
        p['target']='weight rope';ui['targets']=[{'id':'control:piece-choice-toggle','label':'Warm'}]
        reply=mc.respond_coach(level,[],ui,call=unavailable)
        self.assertEqual(reply['guide']['target_id'],'control:piece-choice-toggle')
        p['preset']='hot';ui['targets']=[{'id':'control:place','label':'Place'}]
        self.assertEqual(mc.respond_coach(level,[],ui,call=unavailable)['guide']['target_id'],'control:place')
        placed=[copy.deepcopy(p)]
        self.assertEqual(mc.respond_coach(level,placed,{'targets':[{'id':'control:view-out'}]},call=unavailable)['guide']['target_id'],'control:view-out')
        for terminal in ('plus','minus'):
            a,b='supply:'+terminal,'your ignition 1:'+terminal
            ui={'targets':[{'id':'socket:'+a},{'id':'socket:'+b}]}
            guide=mc.respond_coach(level,placed,ui,call=unavailable)['guide']
            self.assertEqual((guide['target_id'],guide['end_target_id']),('socket:'+a,'socket:'+b))
            placed.append({'piece':'wire','a_terminal':a,'b_terminal':b})
        ui={'targets':[{'id':'control:start'}]}
        self.assertEqual(mc.respond_coach(level,placed,ui,call=unavailable)['guide']['target_id'],'control:start')

    def test_typed_hint_receives_the_unplaced_editor_state(self):
        level=mg.level_by_id('easy-heat');seen=[]
        editing={'p':{'piece':'ignition','attachment_version':2,'target':'','preset':'warm'}}
        def call(messages):
            seen.extend(messages);return {'reply':'Clip the heater onto the cord.'},{}
        mc.respond_level('How do I attach this?',level,[],ui={'editing':editing},call=call)
        context=json.loads(seen[1]['content'])
        self.assertEqual(context['editing'],editing)
        self.assertIn('Clip to cord',seen[0]['content'])
        self.assertNotIn(json.dumps(level['solution']),json.dumps(seen))

    def test_chat_delivers_manual_setup_without_searching_for_an_automatic_win(self):
        level=mg.level_by_id('fire')
        seen=[]
        def rehearse(compiled):
            seen.append(compiled)
            return dict(stations=[dict(done=False)],events=[],error=None)
        result=mc.respond_level('Place it',level,[],mode='build',rehearse=rehearse,
            call=lambda messages: (dict(reply='Aim and connect the cannon.',placements=level['solution']),{}))
        self.assertEqual(len(seen),1)
        self.assertTrue(result['rehearsal']['manual_input_required'])
        self.assertIsNone(result['rehearsal']['goal_at_s'])
        self.assertTrue(result['helped'])
        self.assertEqual(len(result['placements']),3)
        self.assertIn('Drag the field handle',result['reply'])


def knob_default(rule):
    return rule['default'] if 'default' in rule else rule['choices'][0] if 'choices' in rule else rule['min']


class FreeBuild(unittest.TestCase):
    FREE = mg.level_by_id('free')

    @staticmethod
    def course_proposal():
        return dict(reply='A marble takes a ramp, a turn and a stopped catch.',clear=True,
            add=[dict(piece='track',id='entry',x_m=-.8,z_m=0,top_height_m=1,run_m=.8,drop_m=.12),
                 dict(piece='bend',id='turn',turn_deg=90,radius_m=.3,drop_m=.06,join=dict(to=1,port='far end')),
                 dict(piece='track',id='finish',run_m=.7,drop_m=.08,end='stop',join=dict(to=2,port='far end')),
                 dict(piece='marble',id='ball',join=dict(to=1,port='top end'))],
            verify=[dict(marble='ball',via=['entry','turn','finish'],finish='finish',seconds=10)])

    def test_word_builder_has_one_existing_tool_contract_in_3d_and_wall_spaces(self):
        import sandbox_wall
        for level in (self.FREE,mg.requested_level(dict(level='free',base=sandbox_wall.world_base())),
                mg.requested_level(dict(level='free',base=sandbox_wall.base()))):
            prompt=mc.free_prompt(level)
            for text in ('EXISTING Sandbox tools','Never invent a device','Include every required object',
                    'verify','SAME marble','id (not name)','earlier final piece number'):
                self.assertIn(text.lower(),prompt.lower())
            self.assertIn('marble',prompt)

    def test_structured_builder_schema_and_knob_translation_use_the_actual_catalog(self):
        schema=mc.free_response_schema(self.FREE)
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(set(schema['required']),set(schema['properties']))
        options=schema['properties']['add']['items']['anyOf']
        allowed=[row['properties']['piece']['enum'][0] for row in options]
        self.assertIn('rope',allowed);self.assertNotIn('imaginary_teleporter',allowed)
        bend=next(row for row in options if row['properties']['piece']['enum']==['bend'])
        self.assertNotIn('run_m',bend['properties']['knobs']['items']['properties']['name']['enum'])
        original=dict(reply='Proposal',add=[dict(piece='track',id='entry',join=None,
            knobs=[dict(name='run_m',value=.8),dict(name='drop_m',value=.12)])],
            edit=[dict(number=1,knobs=[dict(name='run_m',value=1)])],
            assemblies=[dict(kind='marble_lift',x_m=None,height_m=None)])
        normalized=mc.normalize_build_answer(original)
        self.assertEqual(normalized['add'],[dict(piece='track',id='entry',run_m=.8,drop_m=.12)])
        self.assertEqual(normalized['edit'],[dict(number=1,set=dict(run_m=1))])
        self.assertEqual(normalized['assemblies'],[dict(kind='marble_lift')])
        self.assertIn('knobs',original['add'][0],'translation must not mutate a recorded model answer')
        for knobs in ([dict(name='run_m',value=.8),dict(name='run_m',value=.9)],
                [dict(name='piece',value='imaginary_teleporter')]):
            with self.assertRaises(mg.LevelRefused):mc.normalize_build_answer(dict(add=[dict(piece='track',knobs=knobs)]))

    def test_course_verification_resolves_ids_and_rejects_fake_or_duplicate_targets(self):
        answer=self.course_proposal()
        result=mc.respond_free('Build a marble course',self.FREE,[],call=lambda messages:(answer,{}))
        compiled=mw.compile_spec(mg.compose(self.FREE,result['placements'])[0])
        aliases={p['id']:f'your {p["piece"]} {i+1}' for i,p in enumerate(answer['add'])}
        checks=mc.course_checks(answer['verify'],result['placements'],compiled,aliases)
        self.assertEqual(checks[0]['via'],['your track 1','your bend 2','your track 3'])
        for change in (dict(marble='entry'),dict(via=['entry','entry']),dict(via=['entry','invented']),
                dict(seconds=float('inf')),dict(seconds=0),dict(script='move the marble')):
            with self.subTest(change=change),self.assertRaises(mg.LevelRefused):
                mc.course_checks([dict(answer['verify'][0],**change)],result['placements'],compiled,aliases)
        with self.assertRaisesRegex(mg.LevelRefused,'shared rehearsal duration'):
            mc.course_checks([answer['verify'][0],dict(answer['verify'][0],seconds=5)],result['placements'],compiled,aliases)

    def test_word_builder_rejects_unavailable_controls_and_forward_joins(self):
        for bad in (dict(piece='track',teleport=True),dict(piece='track',join=dict(to=2,port='far end')),
                dict(piece='imaginary_teleporter')):
            with self.subTest(bad=bad):
                count=[]
                def call(messages):count.append(1);return dict(reply='Proposal',add=[bad]),{}
                with self.assertRaises(mg.LevelRefused):mc.respond_free('Build it',self.FREE,[],call=call)
                self.assertEqual(len(count),mc.BUILD_ATTEMPTS)

    def test_a_failed_course_cannot_pass_by_removing_its_route_checks(self):
        answer=self.course_proposal();calls=[]
        def call(messages):
            calls.append(copy.deepcopy(messages))
            return (answer if len(calls)==1 else dict(answer,verify=[])),{}
        def run(compiled,**kw):return dict(paths={},hits=[],events=[],error=None)
        with self.assertRaisesRegex(mg.LevelRefused,'could not verify'):
            mc.respond_free('Build a marble course',self.FREE,[],call=call,rehearse=run)
        self.assertEqual(len(calls),mc.BUILD_ATTEMPTS)
        self.assertIn('could not verify',calls[1][-1]['content'])
        self.assertTrue(json.loads(calls[1][-1]['content'])['required_verify'],
            'the server retains the checks, so omission cannot bypass physical failure')

    def test_repair_can_omit_its_route_json_but_still_has_to_pass_the_same_physics_checks(self):
        answer=self.course_proposal();calls=[];observed=[]
        def call(messages):
            calls.append(copy.deepcopy(messages))
            return (answer if len(calls)==1 else dict(reply='Repair settings',edit=[],verify=[])),{}
        def run(compiled,**kw):
            observed.append(kw)
            return dict(paths={},hits=[],events=[],error=None)
        with self.assertRaisesRegex(mg.LevelRefused,'could not verify'):
            mc.respond_free('Build a marble course',self.FREE,[],call=call,rehearse=run)
        self.assertEqual(len(observed),mc.BUILD_ATTEMPTS)
        contracts=[json.loads(rows[-1]['content'])['required_verify'] for rows in calls[1:]]
        self.assertTrue(all(c==contracts[0] for c in contracts))

    def test_builder_check_identity_deduplicates_unordered_sets_without_changing_ordered_routes(self):
        check=dict(kind='course',marble='ball',via=['a','b','c'],finish=['left','right'],seconds=15,
            order='any',minimum_contacts=3,radius_m=.04)
        echo=dict(check,via=['c','b','a'],finish=['right','left'],radius_m=.05)
        self.assertEqual(mc.merge_builder_checks([check],[echo]),[check])
        subset=dict(check,via=['a','b','c'],finish='left')
        self.assertEqual(mc.merge_builder_checks([check],[subset]),[check])
        for change in (dict(seconds=25),dict(minimum_contacts=2),dict(finish='other'),dict(order='ordered')):
            self.assertEqual(len(mc.merge_builder_checks([check],[dict(check,**change)])),2)
        ordered=dict(check,order='ordered')
        self.assertEqual(len(mc.merge_builder_checks([ordered],[dict(ordered,via=['c','b','a'])])),2)

    def test_bad_route_metadata_can_be_corrected_without_preserving_invalid_stages(self):
        answer=self.course_proposal();calls=[]
        bad=copy.deepcopy(answer);bad['verify'][0]['via'].insert(0,'ball')
        def call(messages):calls.append(1);return (bad if len(calls)==1 else answer),{}
        result=mc.respond_free('Build a marble course',self.FREE,[],call=call)
        self.assertEqual(len(calls),2)
        self.assertEqual(len(result['placements']),4)

    def test_geometry_repair_retains_valid_direct_route_metadata(self):
        first=self.course_proposal();duplicate=copy.deepcopy(first['add'][0]);duplicate.pop('id');first['add'].append(duplicate)
        calls=[]
        def call(messages):
            calls.append(copy.deepcopy(messages))
            if len(calls)==1:return first,{}
            return dict(reply='Move the overlapping block',edit=[dict(number=5,set=dict(x_m=1.5,z_m=1.5))],verify=[]),{}
        result=mc.respond_free('Build a marble course',self.FREE,[],call=call)
        self.assertEqual(len(calls),2)
        contract=json.loads(calls[1][-1]['content'])['required_verify']
        self.assertEqual(len(contract),1)
        self.assertEqual(contract[0]['via'],['your track 1','your bend 2','your track 3'])
        self.assertEqual(len(result['placements']),5)

    def test_a_physical_failure_cannot_be_fixed_by_retargeting_the_goal(self):
        answer=self.course_proposal();calls=[]
        changed=copy.deepcopy(answer);changed['verify'][0]['finish']='entry'
        def call(messages):calls.append(1);return (answer if len(calls)==1 else changed),{}
        with self.assertRaisesRegex(mg.LevelRefused,'original route targets'):
            mc.respond_free('Build a course',self.FREE,[],call=call,
                rehearse=lambda compiled,**kw:dict(error='test-only physical failure',paths={},hits=[],events=[]))
        self.assertEqual(len(calls),mc.BUILD_ATTEMPTS)

    def test_builder_returns_unavailable_feature_explanations_with_its_answer(self):
        answer=dict(self.course_proposal(),limitations=['Continuous bucket rotation is not available in the single-pass lift.'])
        result=mc.respond_free('Build a course',self.FREE,[],call=lambda messages:(answer,{}))
        self.assertEqual(result['limitations'],answer['limitations'])

    # Like pieces snapping flush: plank end to end, block side to side and on top.
    def _flush(self, placed, index, **extra):
        before = copy.deepcopy(placed)
        reply = mg.ghost(self.FREE, placed, index, snapping=True, nearby=True, **extra)
        self.assertEqual(placed, before, 'a snap is only a suggestion')
        return reply.get('snap')

    def _built(self, placed, index):
        reply = mg.ghost(self.FREE, placed, index, nearby=True)
        self.assertTrue(reply['fits'], reply['problems'])
        _, _, _, compiled = mg._assemble(self.FREE, placed, lenient=True)
        return {p['name']: p for p in compiled['parts']}, reply

    def assertFlush(self, a, b, collinear=False):
        gap = mg._gap(a, b)
        self.assertGreaterEqual(gap, -1e-9, 'no overlap')
        self.assertLessEqual(gap, mg.FLUSH_TOUCH_M, 'no gap')
        self.assertEqual(mw.overlap_depth(a, b) > 0.001, False)
        if collinear:
            self.assertAlmostEqual(a['at_m'][1], b['at_m'][1], places=4)

    def test_plank_ends_snap_flush_and_collinear(self):
        for yaw in (0, 30, -90):
            with self.subTest(yaw=yaw):
                r = math.radians(yaw)
                fwd = [math.cos(r), -math.sin(r)]
                first = {'piece': 'plank', 'x_m': 0.0, 'z_m': 0.0, 'length_m': 0.4, 'yaw_deg': yaw}
                # 4 cm past the end and 2 cm off the line, turned 4 degrees off it.
                near = {'piece': 'plank', 'length_m': 0.6, 'yaw_deg': yaw + 4,
                        'x_m': round(0.54 * fwd[0] + 0.02 * fwd[1], 4), 'z_m': round(0.54 * fwd[1] - 0.02 * fwd[0], 4)}
                snap = self._flush([first, near], 1)
                self.assertIsNotNone(snap)
                self.assertEqual((snap['to'], snap['port']), ('your plank 1', 'one end'))
                self.assertTrue(snap['moved'] and snap['exact'])
                placed = [first, dict(near, **snap['knobs'])]
                self.assertAlmostEqual(placed[1]['yaw_deg'], yaw, places=4)
                parts, reply = self._built(placed, 1)
                self.assertFalse(reply['snap']['moved'], 'once snapped it stays put')
                self.assertFlush(parts['your plank 1'], parts['your plank 2'], collinear=True)
                # Along the same line: the second's middle is on the first's axis.
                at = parts['your plank 2']['at_m']
                self.assertAlmostEqual(at[0] * fwd[1] - at[2] * fwd[0], 0.0, places=3)
                self.assertFalse(any(j for j in mg.compose(self.FREE, placed)[0].get('joints', [])),
                                 'snapping adds no glue')
        # Other end too, and a plank across the line (60 degrees off) is not pulled round.
        first = {'piece': 'plank', 'x_m': 0.0, 'z_m': 0.0, 'length_m': 0.4}
        snap = self._flush([first, {'piece': 'plank', 'x_m': -0.43, 'z_m': 0.0, 'length_m': 0.4}], 1)
        self.assertEqual(snap['port'], 'other end')
        self.assertAlmostEqual(snap['knobs']['x_m'], -0.4001, places=4)
        self.assertIsNone(self._flush([first, {'piece': 'plank', 'x_m': 0.42, 'z_m': 0.0, 'length_m': 0.4, 'yaw_deg': 60}], 1))

    def test_block_sides_and_top_snap_flush(self):
        first = {'piece': 'block', 'x_m': 0.0, 'z_m': 0.0}
        for near, port in (({'x_m': 0.13, 'z_m': 0.01}, 'right side'), ({'x_m': -0.12, 'z_m': -0.02}, 'left side'),
                           ({'x_m': 0.01, 'z_m': 0.12}, 'front side'), ({'x_m': 0.02, 'z_m': -0.13}, 'back side')):
            with self.subTest(port=port):
                snap = self._flush([first, dict(piece='block', **near)], 1)
                self.assertEqual((snap['to'], snap['port']), ('your block 1', port))
                placed = [first, dict(dict(piece='block', **near), **snap['knobs'])]
                parts, _ = self._built(placed, 1)
                a, b = parts['your block 1'], parts['your block 2']
                self.assertFlush(a, b)
                self.assertAlmostEqual(a['at_m'][1], b['at_m'][1], places=4, msg='standing on the same floor')
        # A turned block: the snap follows its sides, and a quarter turn off still matches.
        turned = {'piece': 'block', 'x_m': 0.0, 'z_m': 0.0, 'yaw_deg': 30}
        snap = self._flush([turned, {'piece': 'block', 'x_m': 0.11, 'z_m': -0.04, 'yaw_deg': 118}], 1)
        self.assertEqual(snap['port'], 'right side')
        parts, _ = self._built([turned, dict(dict(piece='block', x_m=0.11, z_m=-0.04, yaw_deg=118), **snap['knobs'])], 1)
        self.assertFlush(parts['your block 1'], parts['your block 2'])

    def test_blocks_stack_centred_on_top(self):
        # Fixed blocks are set down, so a smaller one near the middle stands centred on the top.
        first = {'piece': 'block', 'x_m': 0.0, 'z_m': 0.0, 'tall_m': 0.2}
        near = {'piece': 'block', 'x_m': 0.02, 'z_m': 0.01, 'tall_m': 0.1}
        snap = self._flush([first, near], 1)
        self.assertEqual(snap['port'], 'top')
        parts, _ = self._built([first, dict(near, **snap['knobs'])], 1)
        a, b = parts['your block 1'], parts['your block 2']
        self.assertFlush(a, b)
        self.assertAlmostEqual(b['at_m'][1] - mw._half(b)[1], a['at_m'][1] + mw._half(a)[1], places=4)
        self.assertEqual((b['at_m'][0], b['at_m'][2]), (a['at_m'][0], a['at_m'][2]))
        # Loose blocks say their height: held over another, they go onto its top.
        low = {'piece': 'loose_block', 'x_m': 0.0, 'z_m': 0.0, 'center_height_m': 0.1}
        high = {'piece': 'loose_block', 'x_m': 0.03, 'z_m': 0.0, 'center_height_m': 0.33}
        snap = self._flush([low, high], 1)
        self.assertEqual(snap['port'], 'top')
        self.assertEqual(snap['knobs'], {'x_m': 0.0, 'z_m': 0.0, 'center_height_m': 0.3})
        parts, _ = self._built([low, dict(high, **snap['knobs'])], 1)
        self.assertFlush(parts['your loose_block 1'], parts['your loose_block 2'])
        self.assertFalse(mg.compose(self.FREE, [low, dict(high, **snap['knobs'])])[0].get('joints'),
                         'stacked loose blocks only touch; nothing glues them')

    def test_flush_snap_releases_beyond_capture_and_respects_its_hold(self):
        import machine_alignment as ma
        first = {'piece': 'block', 'x_m': 0.0, 'z_m': 0.0}
        captured = self._flush([first, {'piece': 'block', 'x_m': 0.17, 'z_m': 0.0}], 1)
        self.assertAlmostEqual(captured['distance'], 0.17 - 0.1001, places=4)
        held = captured['to'] + '|' + captured['port']
        # 9 cm from the flush spot: past capture (8 cm) but within release (11 cm).
        between = [first, {'piece': 'block', 'x_m': 0.1901, 'z_m': 0.0}]
        self.assertGreater(0.09, ma.CAPTURE_M)
        self.assertIsNone(self._flush(between, 1))
        self.assertIsNotNone(self._flush(between, 1, snap_hold=held))
        beyond = [first, {'piece': 'block', 'x_m': 0.2201, 'z_m': 0.0}]
        self.assertIsNone(self._flush(beyond, 1, snap_hold=held))
        # Exact controls do not snap, and planks never snap to blocks.
        self.assertNotIn('snap', mg.ghost(self.FREE, [first, {'piece': 'block', 'x_m': 0.13, 'z_m': 0.0}], 1, nearby=True))
        self.assertIsNone(self._flush([first, {'piece': 'plank', 'x_m': 0.25, 'z_m': 0.0, 'length_m': 0.4}], 1))

    def test_flush_snap_is_refused_where_it_would_overlap_something(self):
        # Something of the level's stands where the snapped block would go.
        free = copy.deepcopy(self.FREE)
        free['machine'].setdefault('parts', []).append(
            {'name': 'post', 'shape': 'box', 'material': 'oak', 'size_m': [0.04, 0.3, 0.04], 'at_m': [0.13, 0.15, 0.0], 'fixed': True})
        first = {'piece': 'block', 'x_m': 0.0, 'z_m': 0.0}
        self.assertIsNotNone(self._flush([first, {'piece': 'block', 'x_m': 0.16, 'z_m': 0.03}], 1), 'clear spot, for contrast')
        self.assertNotIn('snap', mg.ghost(free, [first, {'piece': 'block', 'x_m': 0.16, 'z_m': 0.03}], 1, snapping=True, nearby=True))
        # A plank's flush spot blocked by a post: refused, not lifted onto it.
        free['machine']['parts'][-1]['at_m'] = [0.5, 0.15, 0.0]
        placed = [{'piece': 'plank', 'x_m': 0.0, 'z_m': 0.0, 'length_m': 0.4},
                  {'piece': 'plank', 'x_m': 0.43, 'z_m': 0.0, 'length_m': 0.4}]
        self.assertIsNotNone(self._flush(placed, 1), 'clear spot, for contrast')
        self.assertNotIn('snap', mg.ghost(free, placed, 1, snapping=True, nearby=True))

    def test_flush_snapping_stays_out_of_lessons(self):
        # The one lesson with a plank ('gap') has one plank; none of them gets faces.
        self.assertIn('gap', [l['id'] for l in LEVELS if any(t['piece'] == 'plank' for t in l['tray'])])
        for level in LEVELS:
            with self.subTest(level=level['id']):
                solution = copy.deepcopy(level['solution'])
                _, checked, _, compiled = mg._assemble(level, solution, lenient=True)
                for i in range(len(solution)):
                    self.assertEqual(mg.flush_candidates(level, checked, i, compiled), [])

    def test_named_connections_keep_identity_and_can_target_later_placements(self):
        free = mg.requested_level({'level': 'free', 'base': mg.sandbox_water_launch.CHANNEL_BASE})
        placed = [{'piece':'water_wheel','side':'off','load_part':'your weight 2'},
                  {'piece':'weight','x_m':1,'z_m':.7,'height_m':.5,'mount':'guided'}]
        spec = mg.compose(free, placed)[0]
        compiled = mw.compile_spec(spec)
        self.assertTrue(any(j.get('load') == 'your weight 2' and j['kind'] == 'drum' for j in compiled['joints']))
        with self.assertRaisesRegex(mg.LevelRefused, 'not present'):
            mg.compose(free, [dict(placed[0], load_part='your weight 99')])

    def test_attach_spring_preserves_real_picked_points_and_parameters(self):
        placed = [{'piece':'block','x_m':-.5,'z_m':0,'tall_m':.2},
                  {'piece':'plank','x_m':.5,'z_m':0,'length_m':.2},
                  {'piece':'link','kind':'spring','a':'your block 1','b':'your plank 2',
                   'at_m':[-.5,.2,0],'at_b_m':[.5,.05,0],'rest_m':.9,'stiffness_n_m':80,'damping_n_s_m':2}]
        compiled = mw.compile_spec(mg.compose(self.FREE, placed)[0])
        joint = next(j for j in compiled['joints'] if j['name'] == 'your link 3')
        self.assertEqual(joint['kind'], 'spring')
        self.assertEqual(joint['at_m'], placed[-1]['at_m'])
        for key in ('rest_m','stiffness_n_m','damping_n_s_m'):
            self.assertEqual(joint[key], placed[-1][key])

    def test_the_free_build_has_no_goal_and_every_piece(self):
        free = self.FREE
        self.assertIsNone(free['goal'])
        pieces = [t['piece'] for t in free['tray']]
        for p in ('marble', 'track', 'shelf', 'flipflop', 'block', 'dominoes', 'lever', 'plank', 'ramp', 'cannon', 'steam'):
            self.assertIn(p, pieces)
        self.assertNotIn('free', [l['id'] for l in LEVELS], 'it is not one of the numbered levels')
        spec, checked, cost = mg.compose(free, [])
        self.assertEqual(spec['stations'], [], 'nothing to do but watch')
        shown = mg.public(free)
        self.assertTrue(shown['free'])
        self.assertEqual(shown['example'], free['example'])
        # A track turns only about the upright; a marble does not turn at all.
        knobs = {t['piece']: t['knobs'] for t in free['tray']}
        self.assertIn('yaw_deg', knobs['track'])
        self.assertNotIn('pitch_deg', knobs['track'])
        self.assertFalse({'yaw_deg', 'pitch_deg', 'roll_deg'} & set(knobs['marble']))

    def test_every_free_piece_fits_as_it_comes(self):
        for t in self.FREE['tray']:
            if t.get('attach'):
                continue      # a link is made by joining two parts, not from the tray
            placed = dict({k: knob_default(r) for k, r in t['knobs'].items()}, piece=t['piece'])
            context = copy.deepcopy(self.FREE)
            if t['piece'] in ('water_wheel', 'water_tank', 'water_chute', 'water_collector'):
                context['machine'] = copy.deepcopy(mg.sandbox_water_launch.CHANNEL_BASE)
                context['custom_base'] = True
            g = mg.ghost(context, [placed], 0)
            with self.subTest(piece=t['piece']):
                if t['piece'] in ('wire', 'power_cable'):
                    self.assertFalse(g['fits'], 'a wire needs two real terminals')
                    self.assertIn('terminal' if t['piece'] == 'wire' else 'power input', ' '.join(g['problems']))
                    continue
                self.assertTrue(g['fits'], g['problems'])
                self.assertTrue(g['parts'])

    def test_a_marble_is_set_down_on_what_is_under_it(self):
        # On a shelf it rests on the shelf; on a sloping track it rests on the
        # slope, touching it and in none of it.
        free = self.FREE
        shelf = {'piece': 'shelf', 'x_m': 0.0, 'z_m': 0.0, 'top_height_m': 0.8, 'run_m': 0.4, 'drop_m': 0.015, 'end': 'gate'}
        g = mg.ghost(free, [shelf, {'piece': 'marble', 'x_m': 0.1, 'z_m': 0.0}], 1)
        self.assertTrue(g['fits'], g['problems'])
        surface = 0.8 - 0.015 * 0.1 / 0.4
        self.assertAlmostEqual(g['parts'][0]['at_m'][1], surface + 0.02, delta=0.004)
        track = {'piece': 'track', 'x_m': 0.0, 'z_m': 0.0, 'top_height_m': 0.6, 'run_m': 0.6, 'drop_m': 0.3, 'end': 'open'}
        spec, _, _ = mg.compose(free, [track, {'piece': 'marble', 'x_m': 0.3, 'z_m': 0.0}])
        c = mw.compile_spec(spec)
        marble = next(p for p in c['parts'] if p['name'] == 'your marble 2')
        board = next(p for p in c['parts'] if p['name'] == 'your track 1')
        gap = -mw.overlap_depth(marble, board)
        self.assertGreaterEqual(gap, 0.0)
        self.assertLess(gap, 0.004, 'it rests on the slope, not on top of the slope\'s box')

    def test_a_piece_moved_near_another_snaps_where_they_connect(self):
        free = self.FREE
        first = {'piece': 'track', 'x_m': 0.0, 'z_m': 0.0, 'top_height_m': 0.8, 'run_m': 0.6, 'drop_m': 0.1, 'end': 'open'}
        # A track's top end near the first's far end (0.6, 0.7, 0): just under
        # it and a little past it, turned however it was turned.
        second = {'piece': 'track', 'x_m': 0.65, 'z_m': 0.05, 'top_height_m': 0.3, 'run_m': 0.6, 'drop_m': 0.1,
                  'end': 'open', 'yaw_deg': 90}
        g = mg.ghost(free, [first, second], 1, snapping=True)
        self.assertEqual(g['snap']['to'], 'your track 1')
        self.assertEqual(g['snap']['port'], 'far end')
        self.assertEqual(g['snap']['knobs'], {'x_m': 0.63, 'z_m': 0.0, 'top_height_m': 0.66})
        # Only a piece moved by hand is snapped; one already there says what it is joined to.
        self.assertNotIn('snap', mg.ghost(free, [first, second], 1))
        there = dict(second, **g['snap']['knobs'])
        self.assertFalse(mg.ghost(free, [first, there], 1)['snap']['moved'])
        # A flip-flop under the far end: its middle under it, its board behind
        # it the way the marbles come.
        ff = {'piece': 'flipflop', 'x_m': 0.62, 'z_m': 0.03, 'height_m': 0.3, 'tipped': 'left'}
        snapped = mg.ghost(free, [first, ff], 1, snapping=True)['snap']['knobs']
        self.assertEqual(snapped, {'x_m': 0.64, 'z_m': 0.0, 'height_m': 0.59, 'yaw_deg': -90})
        # A track's far end over a gate's paddle, short of it the way it runs.
        shelf = {'piece': 'shelf', 'x_m': -0.6, 'z_m': 0.0, 'top_height_m': 0.8, 'run_m': 0.4, 'drop_m': 0.015,
                 'end': 'gate that stays open'}
        trigger = {'piece': 'track', 'x_m': -0.6, 'z_m': 0.12, 'top_height_m': 1.0, 'run_m': 0.36, 'drop_m': 0.03, 'end': 'open'}
        g = mg.ghost(free, [shelf, trigger], 1, snapping=True)
        paddle = next(q for q in g['ports'] if q['kind'] == 'trigger')
        self.assertEqual(g['snap']['port'], 'gate paddle')
        far = [g['snap']['knobs']['x_m'] + 0.36, g['snap']['knobs']['top_height_m'] - 0.03]
        self.assertAlmostEqual(far[0], paddle['at'][0] - 0.05, places=3)
        self.assertAlmostEqual(far[1], paddle['at'][1] + 0.065, places=3)
        # A marble near a track's top end sits just in from it.
        g = mg.ghost(free, [first, {'piece': 'marble', 'x_m': 0.04, 'z_m': 0.02}], 1, snapping=True)
        self.assertEqual(g['snap']['knobs'], {'x_m': 0.05, 'z_m': 0.0})
        # Nothing near: nothing snaps.
        far_away = dict(second, x_m=1.5, z_m=1.5)
        self.assertNotIn('snap', mg.ghost(free, [first, far_away], 1, snapping=True))

    def test_two_parts_are_joined_by_glue_a_pin_or_a_string(self):
        free = self.FREE
        block = {'piece': 'block', 'x_m': 0.0, 'z_m': 0.0, 'tall_m': 0.2}
        plank = {'piece': 'plank', 'x_m': 0.0, 'z_m': 0.0, 'length_m': 0.6}
        for kind, extra, joint in (('glue', {}, 'fix'), ('pin', {'axis': 'along z'}, 'hinge'),
                                   ('string', {'at_b_m': [0.2, 0.25, 0.0]}, 'tie')):
            link = dict({'piece': 'link', 'kind': kind, 'a': 'your block 1', 'b': 'your plank 2', 'at_m': [0.0, 0.2, 0.0]}, **extra)
            spec, _, _ = mg.compose(free, [block, plank, link])
            made = next(j for j in mw.compile_spec(spec)['joints'] if j['name'] == 'your link 3')
            self.assertEqual(made['kind'], joint)
            if kind == 'pin':
                self.assertEqual(made['axis'], [0.0, 0.0, 1.0])
            if kind == 'string':
                self.assertAlmostEqual(made['length_m'], math.dist([0.0, 0.2, 0.0], [0.2, 0.25, 0.0]), places=4)
        with self.assertRaises(mg.LevelRefused):
            mg.compose(free, [block, dict(link, b='your block 1')])
        with self.assertRaisesRegex(mg.LevelRefused, 'not present'):
            mg.compose(free, [block, plank, dict(link, b='your plank 9')])

    def test_the_chat_builds_by_joining_pieces_and_the_server_lays_them_out(self):
        # The model says which pieces and what each joins to; the server puts
        # them there: marbles lined up on a shelf behind its gate, a trigger
        # track's far end over the gate's paddle, a flip-flop under the shelf's
        # end, a track running on from each of its ends -- then the whole build
        # in the middle of the table.
        free = self.FREE
        answer = {'reply': 'A shelf of marbles, a trigger, and a flip-flop.', 'clear': True, 'add': [
            {'piece': 'shelf', 'x_m': 1.5, 'z_m': 1.5, 'top_height_m': 0.8, 'run_m': 0.4, 'drop_m': 0.015,
             'end': 'gate that stays open'},
            {'piece': 'marble', 'join': {'to': 1, 'port': 'top end'}},
            {'piece': 'marble', 'join': {'to': 1, 'port': 'top end'}},
            {'piece': 'marble', 'join': {'to': 1, 'port': 'top end'}},
            {'piece': 'track', 'run_m': 0.36, 'drop_m': 0.03, 'join': {'to': 1, 'port': 'gate paddle'}},
            {'piece': 'marble', 'join': {'to': 5, 'port': 'top end'}},
            {'piece': 'flipflop', 'join': {'to': 1, 'port': 'far end'}},
            {'piece': 'track', 'run_m': 0.6, 'drop_m': 0.08, 'end': 'stop', 'join': {'to': 7, 'port': 'left end'}},
            {'piece': 'track', 'run_m': 0.6, 'drop_m': 0.08, 'end': 'stop', 'join': {'to': 7, 'port': 'right end'}}]}
        asked = []

        def call(messages):
            asked.append(messages)
            return (answer if len(asked) > 1 else dict(answer, add=answer['add'] + [{'piece': 'spaceship'}])), {}
        r = mc.respond_free('Hold three marbles up high, then split them two ways.', free, [], call=call)
        self.assertEqual(len(asked), 2, 'a refused build is sent back once with why')
        self.assertIn('spaceship is not a piece', asked[1][-1]['content'])
        placed = r['placements']
        self.assertEqual([p['piece'] for p in placed],
                         ['shelf', 'marble', 'marble', 'marble', 'track', 'marble', 'flipflop', 'track', 'track'])
        spec, checked, _ = mg.compose(free, placed)
        compiled = mw.compile_spec(spec)
        found = mg.ports(checked, compiled)
        port = lambda i, name: next(q for q in found if q['piece'] == i and q['port'] == name)
        # Marbles lined up from the shelf's top end, 4.5 cm apart.
        xs = [placed[i]['x_m'] for i in (1, 2, 3)]
        self.assertAlmostEqual(xs[0], port(0, 'top end')['at'][0] + 0.05, places=3)
        self.assertAlmostEqual(xs[1] - xs[0], 0.045, places=3)
        self.assertAlmostEqual(xs[2] - xs[1], 0.045, places=3)
        # The trigger track's far end 5 cm short of the paddle and 6.5 cm over it.
        paddle, far = port(0, 'gate paddle')['at'], port(4, 'far end')['at']
        self.assertAlmostEqual(far[0], paddle[0] - 0.05, places=3)
        self.assertAlmostEqual(far[1], paddle[1] + 0.065, places=3)
        # The flip-flop's middle 4 cm past the shelf's far end, 11 cm under it; its
        # tracks run on from its ends, away from it.
        shelf_far, middle = port(0, 'far end')['at'], port(6, 'middle')['at']
        self.assertAlmostEqual(middle[0], shelf_far[0] + 0.04, places=3)
        self.assertAlmostEqual(middle[1], shelf_far[1], places=3)
        for i, end in ((7, 'left end'), (8, 'right end')):
            self.assertEqual(port(i, 'top end')['dir'], port(6, end)['dir'])
        # And the whole build moved to the middle of the table.
        boxes = [(sd['at_m'], mg._reach(sd)) for p in compiled['parts'] if mg.owner(p) for sd in mw.solids_of(p)]
        for i in (0, 2):
            middle_of = 0.5 * (min(c[i] - r[i] for c, r in boxes) + max(c[i] + r[i] for c, r in boxes))
            self.assertLess(abs(middle_of), 0.011)

    def test_a_bend_turns_a_track_and_its_ends_connect(self):
        free = self.FREE
        entry = {'piece': 'track', 'x_m': -0.6, 'z_m': 0.0, 'top_height_m': 0.6, 'run_m': 0.6, 'drop_m': 0.06, 'end': 'open'}
        bend = {'piece': 'bend', 'x_m': 0.05, 'z_m': 0.05, 'top_height_m': 0.3, 'turn_deg': 90, 'radius_m': 0.3, 'drop_m': 0.04}
        g = mg.ghost(free, [entry, bend], 1, snapping=True)
        self.assertEqual((g['snap']['to'], g['snap']['port']), ('your track 1', 'far end'))
        bend = dict(bend, **g['snap']['knobs'])
        spec, checked, _ = mg.compose(free, [entry, bend])
        compiled = mw.compile_spec(spec)
        boards = [p for p in compiled['parts'] if p['name'].startswith('your bend 2 ') and 'rail' not in p['name']]
        self.assertEqual(len(boards), 4, 'a section for every 22.5 degrees')
        far = next(q for q in mg.ports(checked, compiled) if q['piece'] == 1 and q['port'] == 'far end')
        # Turned 90 degrees to the left: it leaves toward -z, 0.3 m across and 0.3 m along from where it began.
        self.assertAlmostEqual(far['dir'][2], -1.0, places=6)
        self.assertAlmostEqual(far['at'][0] - bend['x_m'], 0.3, places=3)
        self.assertAlmostEqual(far['at'][2] - bend['z_m'], -0.3, places=3)

    def test_the_example_is_built_as_it_is_written(self):
        spec, checked, cost = mg.compose(self.FREE, self.FREE['example'])
        c = mw.compile_spec(spec)
        names = {p['name'] for p in c['parts']}
        self.assertIn('your flipflop 8', names)
        self.assertIn('your dominoes 11 6', names)
        gate = next(j for j in c['joints'] if j['name'] == 'your shelf 1 barrier pin')
        self.assertIn('ratchet', gate, 'its shelf\'s gate stays open')


class SandboxGoal(unittest.TestCase):
    GOAL = {'title': 'Into the box', 'done_when': {'in_zone': {'part': 'your marble 1', 'at_m': [0, .05, 0], 'size_m': [.4, .3, .4]}}}

    def test_a_player_goal_is_validated_and_measured_first_without_scoring(self):
        free = mg.requested_level({'level': 'free', 'goal': self.GOAL})
        spec = mg.compose(free, [{'piece': 'marble', 'x_m': 0, 'z_m': 0}])[0]
        self.assertEqual(spec['stations'][0]['done_when'], self.GOAL['done_when'])
        self.assertTrue(spec['stations'][0]['player_goal'])
        mw.compile_spec(spec)          # the engine declaration accepts it
        # Until the body exists the goal is left out (or refused).
        self.assertIn('not here yet', mg.compose(free, [], leave_out_goal=True)[0]['_needs'])
        with self.assertRaises(mg.LevelRefused):
            mg.compose(free, [])
        for bad in ({'done_when': {'hits': ['a', 'b']}}, {'done_when': {'in_zone': {'part': 'x', 'at_m': [0, 0], 'size_m': [1, 1, 1]}}},
                    {'done_when': {'in_zone': {'part': 'x', 'at_m': [0, 0, 0], 'size_m': [0, 1, 1]}}},
                    {'done_when': {'in_zone': {'part': 'x', 'at_m': [0, 999, 0], 'size_m': [1, 1, 1]}}},
                    {'done_when': {'in_zone': {'part': 'x', 'at_m': [0, float('nan'), 0], 'size_m': [1, 1, 1]}}}, 'zone'):
            with self.assertRaises(ValueError, msg=bad):
                mg.requested_level({'level': 'free', 'goal': bad})
        with self.assertRaisesRegex(ValueError, 'Sandbox design'):
            mg.requested_level({'level': 'gap', 'goal': self.GOAL})
        # A shared challenge: "the first marble you place".
        kind = {'title': 'Marble in', 'done_when': {'in_zone': {'piece': 'marble', 'at_m': [0, .05, 0], 'size_m': [.4, .3, .4]}}}
        free = mg.requested_level({'level': 'free', 'goal': kind})
        spec = mg.compose(free, [{'piece': 'plank', 'x_m': 1, 'z_m': 0}, {'piece': 'marble', 'x_m': 0, 'z_m': 0}])[0]
        self.assertEqual(spec['stations'][0]['done_when']['in_zone']['part'], 'your marble 2')
        self.assertEqual(mg.compose(free, [{'piece': 'plank', 'x_m': 1, 'z_m': 0}], leave_out_goal=True)[0]['_needs'],
                         'the goal is about a marble, which is not here yet')
        for bad in ({'piece': 'Marble!'}, {'piece': 'marble', 'part': 'x'}):
            with self.assertRaises(ValueError):
                mg.requested_level({'level': 'free', 'goal': {'done_when': {'in_zone': {**bad, 'at_m': [0, 0, 0], 'size_m': [1, 1, 1]}}}})

    @need_engine
    def test_a_marble_dropped_over_the_zone_reaches_it_and_one_dropped_beside_it_does_not(self):
        free = mg.requested_level({'level': 'free', 'goal': self.GOAL})
        results = {}
        with tempfile.TemporaryDirectory() as logs:
            for name, x in (('over', 0), ('beside', 1.5)):
                spec = mg.compose(free, [{'piece': 'marble', 'x_m': x, 'z_m': 0, 'height_m': .4}])[0]
                run = mw.rehearse(mw.compile_spec(spec), ENGINE, Path(logs), seconds=2)
                self.assertIsNone(run['error'])
                results[name] = next(s for s in run['stations'] if s['title'] == 'Into the box')
        self.assertTrue(results['over'].get('done'), results)
        self.assertFalse(results['beside'].get('done'), results)


    def test_a_light_goal_puts_a_target_with_a_sensor_where_it_is_set(self):
        focus = next(t for t in sm.templates() if t['name'] == 'Find the focus')
        goal = {'title': 'Light here', 'done_when': {'lit_at': {'at_m': [-.3, .575, 0], 'facing': '-x'}}}
        free = mg.requested_level({'level': 'free', 'base': focus['base'], 'goal': goal})
        spec = mg.compose(free, focus['placements'])[0]
        self.assertEqual(spec['stations'][0]['done_when'], {'lit_w': {'photocell': mg.LIGHT_GOAL_CELL, 'w': mg.LIGHT_GOAL_W}})
        self.assertTrue(spec['stations'][0]['player_goal'])
        plate = next(p for p in spec['parts'] if p['name'] == mg.LIGHT_GOAL_PLATE)
        self.assertEqual(plate['size_m'], [.02, .12, .12])
        self.assertTrue(any(p['name'] == mg.LIGHT_GOAL_PLATE + ' post' for p in spec['parts']), 'held up on a post')
        cell = next(c for c in spec['light']['photocells'] if c['name'] == mg.LIGHT_GOAL_CELL)
        self.assertEqual((cell['at_m'], cell['normal']), ([-.3, .575, 0], [-1, 0, 0]))
        mw.compile_spec(spec)
        # Set inside a piece, it says so rather than building it.
        inside = mg.requested_level({'level': 'free', 'base': focus['base'],
                                     'goal': {'done_when': {'lit_at': {'at_m': [focus['placements'][0]['x_m'], .575, 0], 'facing': '-x'}}}})
        self.assertIn('set it in open space', mg.compose(inside, focus['placements'], leave_out_goal=True)[0]['_needs'])
        for bad in ({'lit_at': {'at_m': [0, .5, 0], 'facing': 'down'}}, {'lit_at': {'at_m': [0, .02, 0], 'facing': 'up'}},
                    {'lit_at': {'at_m': [0, .5], 'facing': '+x'}}, {'lit_at': {'at_m': [0, .5, 0], 'facing': '+x'}, 'in_zone': {}}):
            with self.assertRaises(ValueError, msg=bad):
                mg.requested_level({'level': 'free', 'goal': {'done_when': bad}})

    @need_engine
    def test_a_light_goal_is_reached_in_the_beam_facing_it_and_not_beside_it_or_facing_away(self):
        focus = next(t for t in sm.templates() if t['name'] == 'Find the focus')
        results = {}
        with tempfile.TemporaryDirectory() as logs:
            for name, at, facing in (('in the beam', [-.3, .575, 0], '-x'), ('beside it', [-.3, .575, .5], '-x'),
                                     ('facing away', [-.3, .575, 0], '+x')):
                free = mg.requested_level({'level': 'free', 'base': focus['base'],
                                           'goal': {'title': 'Light here', 'done_when': {'lit_at': {'at_m': at, 'facing': facing}}}})
                run = mw.rehearse(mw.compile_spec(mg.compose(free, focus['placements'])[0]), ENGINE, Path(logs), seconds=1.5)
                self.assertIsNone(run['error'])
                results[name] = next(s for s in run['stations'] if s['title'] == 'Light here').get('done', False)
        self.assertEqual(results, {'in the beam': True, 'beside it': False, 'facing away': False})

class Engine(unittest.TestCase):
    @need_engine
    def test_fixed_stage_probe_requires_native_intact_geometry(self):
        level=mg.level_by_id('free');answer=FreeBuild.course_proposal()
        result=mc.respond_free('Build a course',level,[],call=lambda messages:(answer,{}))
        compiled=mw.compile_spec(mg.compose(level,result['placements'])[0])
        checks=mc.course_checks([dict(marble=4,via=[1,2,3],finish=3,seconds=10)],result['placements'],compiled,{})
        with tempfile.TemporaryDirectory() as logs:
            measured=mw.rehearse(compiled,ENGINE,Path(logs),seconds=10,track=['your marble 4'])
        measured['hits']=[]
        self.assertTrue(mc.measure_courses(checks,measured,compiled)[0]['happened'],'native path may prove rolling contact with intact fixed surfaces')
        intact=list(measured['intact_fixed'])
        measured['intact_fixed']=[n for n in intact if n!='your track 3' and not n.startswith('your track 3 ')]
        self.assertFalse(mc.measure_courses(checks,measured,compiled)[0]['happened'],'a changed catcher cannot be checked against its old shape')
        measured['intact_fixed']=[]
        self.assertFalse(mc.measure_courses(checks,measured,compiled)[0]['happened'],'initial geometry cannot substitute for missing native contact evidence after a surface changes')

    @need_engine
    def test_flaky_live_gate_proposal_is_repaired_by_an_existing_control_before_apply(self):
        draft=json.loads((ROOT/'tests/fixtures/chat-built-gate-proposal.json').read_text())
        before=copy.deepcopy(draft);original=[];calls=[]
        verify=[dict(marble=4,via=[1,6,7,8],finish=8,seconds=15),dict(marble=5,via=[1,6,7,9],finish=9,seconds=15)]
        def call(messages):
            calls.append(copy.deepcopy(messages))
            if len(calls)==1:return dict(reply='Gate proposal',add=draft['placements'],verify=verify),{}
            return dict(reply='Increased the trigger marble to open the gate reliably.',edit=[dict(number=3,set=dict(diameter_m=.1))],verify=verify),{}
        with tempfile.TemporaryDirectory() as logs:
            result=mc.respond_free('Build a Rube Goldberg course',mg.level_by_id('free'),original,call=call,
                rehearse=lambda compiled,**kw:mw.rehearse(compiled,ENGINE,Path(logs),wall_limit_s=60,**kw))
        self.assertEqual(len(calls),2)
        self.assertIn('small placement variation',calls[1][-1]['content'])
        self.assertEqual(result['placements'][2]['diameter_m'],.1)
        self.assertEqual(result['rehearsal']['verified_runs'],3)
        self.assertEqual(len(result['rehearsal']['checks']),2)
        self.assertTrue(all(c['happened'] for r in result['rehearsal']['variations'] for c in r['checks']))
        self.assertEqual(original,[]);self.assertEqual(draft,before)

    @need_engine
    def test_course_checks_can_target_a_real_subpart_contact(self):
        level=mg.level_by_id('free');answer=FreeBuild.course_proposal()
        answer['verify'][0]['via']=[1,'your bend 2 1',3]
        with tempfile.TemporaryDirectory() as logs:
            result=mc.respond_free('Build a course',level,[],call=lambda messages:(answer,{}),
                rehearse=lambda compiled,**kw:mw.rehearse(compiled,ENGINE,Path(logs),wall_limit_s=60,**kw))
        self.assertTrue(result['rehearsal']['checks'][0]['happened'])
        self.assertEqual(result['rehearsal']['checks'][0]['stages'][1]['piece'],'your bend 2 1')

    @need_engine
    def test_recorded_live_chat_course_reaches_every_stage_with_nudges(self):
        draft=json.loads((ROOT/'tests/fixtures/chat-built-marble-course.json').read_text())
        level=mg.requested_level(dict(level='free',base=draft['base']))
        for material in ('glass','oak','iron'):
            ps=copy.deepcopy(draft['placements']);ps[-1]['material']=material
            compiled=mw.compile_spec(mg.compose(level,ps)[0])
            checks=mc.course_checks([dict(marble=6,via=[1,2,3,4,5],finish=5,seconds=15)],ps,compiled,{})
            for seed in (0,1,2):
                with self.subTest(material=material,seed=seed),tempfile.TemporaryDirectory() as logs:
                    scene=mg.nudged(compiled,seed) if seed else compiled
                    r=mw.rehearse(scene,ENGINE,Path(logs),seconds=15,wall_limit_s=60,track=['your marble 6'])
                    check=mc.measure_courses(checks,r,scene)[0]
                    self.assertIsNone(r['error']);self.assertTrue(check['happened'],check)
                    print('LIVE_CHAT_COURSE',material,seed,check['distance_m'],check['finished_on'],flush=True)

    @need_engine
    def test_word_builder_can_repair_a_staged_course_without_applying_the_failed_draft(self):
        level=mg.requested_level(dict(level='free',base=dict(schema=mw.SCHEMA,parts=[],stations=[])))
        original=[];proposal=FreeBuild.course_proposal();proposal['clear']=False
        proposal['add'][2]['end']='open'
        calls=[]
        def call(messages):
            calls.append(copy.deepcopy(messages))
            if len(calls)==1:return proposal,{}
            return dict(reply='Added a physical end stop to catch the marble.',edit=[dict(number=3,set=dict(end='stop'))],
                verify=proposal['verify']),{}
        with tempfile.TemporaryDirectory() as logs:
            result=mc.respond_free('Build a complete marble course',level,original,call=call,
                rehearse=lambda compiled,**kw:mw.rehearse(compiled,ENGINE,Path(logs),wall_limit_s=60,**kw))
        self.assertEqual(len(calls),2)
        feedback=json.loads(calls[1][-1]['content'])
        self.assertEqual(len(feedback['on_the_table']),4)
        self.assertEqual(original,[])
        self.assertEqual(len(result['placements']),4)
        self.assertEqual(result['placements'][2]['end'],'stop')
        self.assertTrue(result['rehearsal']['checks'][0]['happened'])

    @need_engine
    def test_word_built_course_has_ordered_native_contacts_and_a_catch_for_three_materials(self):
        base=dict(schema=mw.SCHEMA,title='Blank course qualification',parts=[],kits=[],stations=[])
        level=mg.requested_level(dict(level='free',base=base))
        for material in ('glass','oak','iron'):
            with self.subTest(material=material),tempfile.TemporaryDirectory() as logs:
                answer=FreeBuild.course_proposal();answer['add'][-1]['material']=material
                def run(compiled,**kw):return mw.rehearse(compiled,ENGINE,Path(logs),wall_limit_s=60,**kw)
                result=mc.respond_free('Build a course with a marble',level,[],call=lambda messages:(answer,{}),rehearse=run)
                check=result['rehearsal']['checks'][0]
                self.assertTrue(check['happened'],check)
                self.assertEqual([s['piece'] for s in check['stages']],['your track 1','your bend 2','your track 3'])
                self.assertEqual(check['finished_on'],'your track 3')
                print('WORD_BUILT_COURSE',material,json.dumps(check),flush=True)

    @need_engine
    def test_gear_motion_replay_observes_native_contact_without_changing_the_setup(self):
        level=mg.level_by_id('easy-gears')
        compiled=mw.compile_spec(mg.compose(level,level['solution'])[0])
        before=copy.deepcopy(compiled)
        with tempfile.TemporaryDirectory() as logs:
            replay=mw.rehearse(compiled,ENGINE,Path(logs),seconds=2,flows=True)
            ordinary=mw.rehearse(compiled,ENGINE,Path(logs),seconds=2)
            self.assertEqual(compiled,before)
            self.assertIsNone(replay['error']);self.assertTrue(replay['complete'])
            self.assertEqual(replay['stations'],ordinary['stations'])
            self.assertEqual(replay['readouts'],ordinary['readouts'])
            shapes={b['name']:b for b in replay['mechanism_shapes']}
            self.assertTrue({'drive gear wheel','target gear wheel','your gear 1 wheel'} <= shapes.keys())
            frames=replay['flow_frames']
            self.assertEqual(frames[0]['t'],0)
            target=[next(b for b in f['mechanisms'] if b['name']=='target gear wheel') for f in frames]
            self.assertEqual(target[0]['orientation_wxyz'],shapes['target gear wheel']['orientation_wxyz'])
            self.assertNotEqual(target[0]['orientation_wxyz'],target[-1]['orientation_wxyz'])
            self.assertTrue(any(abs(j.get('turned_deg',0))>=180 for f in frames
                for j in f.get('mechanism_joints',[]) if j['name']=='target gear axle'))
            success=mg.trial(level,level['solution'],ENGINE,logs,runs=3)
            self.assertEqual(success['worked'],3,success)
            for placements in ([],level['wrong']):
                self.assertEqual(mg.trial(level,placements,ENGINE,logs,runs=1)['worked'],0)
        print('Gear replay / ordinary wall seconds:',replay['wall_s'],ordinary['wall_s'])
        print('Gear native nudged goal seconds:',[r['goal_at_s'] for r in success['results']])

    @need_engine
    def test_divert_water_auto_source_keeps_nudged_wins_and_physical_misses(self):
        level=mg.level_by_id('easy-divert-water')
        with tempfile.TemporaryDirectory() as logs:
            success=mg.trial(level,level['solution'],ENGINE,logs,runs=3)
            self.assertEqual(success['worked'],3,success)
            for placed in ([],level['wrong']):
                miss=mg.trial(level,placed,ENGINE,logs,runs=1)
                self.assertEqual(miss['worked'],0,miss)
        print('Divert water automatic-source goal times:',[r['goal_at_s'] for r in success['results']])

    @need_engine
    def test_sandbox_translation_preserves_native_mass_and_free_dynamics_for_three_materials(self):
        import sandbox_edit
        delta=[.2,.1,-.15]
        for material in ('glass','oak','iron'):
            base={'schema':mw.SCHEMA,'parts':[{'name':'block','shape':'box','material':material,
                'at_m':[0,.6,0],'size_m':[.12,.12,.12],'fixed':False}]}
            moved,_,compiled=sandbox_edit.edit(base,'part:block',delta)
            with tempfile.TemporaryDirectory() as logs:
                records=[]
                for i,spec in enumerate((base,moved)):
                    folder=Path(logs)/str(i);folder.mkdir()
                    engine,_,_=mw.build_engine(ENGINE,mw.compile_spec(spec),folder)
                    try:
                        initial=engine.first['bodies'][0]
                        final=engine.op(op='step',dt=1/240,n=24,moved=False)['bodies'][0]
                        records.append((initial,final))
                    finally:engine.close()
                a,b=records
                self.assertEqual(a[0]['mass_kg'],b[0]['mass_kg'])
                self.assertEqual(a[1]['velocity_m_s'],b[1]['velocity_m_s'])
                for x,y,d in zip(a[1]['position_m'],b[1]['position_m'],delta):self.assertAlmostEqual(x+d,y,places=6)

    @need_engine
    def test_laser_exposes_real_hot_cell_energy_then_removes_the_cell_and_releases_the_load(self):
        level=mg.level_by_id('laser')
        with tempfile.TemporaryDirectory() as logs:
            compiled=mw.compile_spec(mg.compose(level,level['solution'])[0])
            engine,_,_=mw.build_engine(ENGINE,compiled,Path(logs))
            try:
                samples=[]
                for _ in range(20):
                    frame=engine.op(op='step',dt=1/240,n=48,moved=False)
                    optics=engine.op(op='optics')['optics']
                    for cell in optics.get('hot_cells',[]):
                        if cell['cut_w']>0:
                            samples.append(cell)
                            self.assertEqual(cell['how'],'chars')
                            self.assertGreater(cell['needed_j'],0)
                            self.assertGreaterEqual(cell['held_j'],0)
                            body=next(b for b in frame['bodies'] if b['name']==cell['body'])
                            if body.get('cells_local_m'):
                                self.assertIn(cell['local_m'],body['cells_local_m'])
                            else:
                                self.assertTrue(all(abs(v)<=d/2+1e-6 for v,d in zip(cell['local_m'],body['dimensions_m'])),
                                    'A boxed body omits redundant voxel geometry; its reported cell must be inside it')
                    if optics['taken_count']:
                        taken=optics['taken'][-1]
                        self.assertGreater(taken['j'],0);self.assertEqual(taken['how'],'chars')
                        self.assertFalse(any(c['body']==taken['body'] for c in optics['hot_cells']),
                            'A consumed one-cell rope segment must stop drawing as heated material')
                        break
                self.assertGreater(len(samples),2,'A sustained burn must be visible before the cell disappears')
                self.assertGreater(max(c['held_j']/c['needed_j'] for c in samples),.5)
            finally:engine.close()

    @need_engine
    def test_audit_lessons_require_direction_current_connection_and_solar_lead(self):
        with tempfile.TemporaryDirectory() as logs:
            motor=mg.level_by_id('easy-motor')
            row=motor['tray'][0]
            defaults=dict(piece='motor',**{k:v['default'] for k,v in row['knobs'].items()})
            self.assertEqual(defaults['direction'],'reverse')
            river=mg.level_by_id('easy-river-lift')
            row=river['tray'][0]
            bank=dict(piece='water_wheel',**{k:v['default'] for k,v in row['knobs'].items()})
            self.assertEqual(bank['z_m'],1)
            self.assertEqual(bank['load_part'],'')
            solar=mg.level_by_id('easy-charge-lift')
            controls=[('motor defaults',motor,[defaults]),('river defaults',river,[bank]),
                      ('river connected on bank',river,[dict(river['solution'][0],z_m=1)]),
                      ('river immersed unconnected',river,[dict(river['solution'][0],load_part='')]),
                      ('solar no lead',solar,solar['solution'][:1])]
            for label,level,placements in controls:
                with self.subTest(control=label):
                    result=mg.trial(level,placements,ENGINE,Path(logs),runs=3)
                    self.assertEqual(result['worked'],0,result)
                    self.assertTrue(all(r['error'] is None for r in result['results']),result)

    @need_engine
    def test_chain_pressure_switch_preview_uses_measured_contacts_and_complete_power_loop(self):
        level=mg.level_by_id('chain')
        with tempfile.TemporaryDirectory() as logs:
            logs=Path(logs)
            good=mg.trial(level,level['solution'],ENGINE,logs,runs=3)
            self.assertEqual(good['worked'],3,good)
            for label,placed in [('empty',[]),('off the seesaw',[dict(level['solution'][0],z_m=.3)])]:
                bad=mg.trial(level,placed,ENGINE,logs,runs=3)
                self.assertEqual(bad['worked'],0,(label,bad))
            result=mg.preview(level,level['solution'],ENGINE,logs)
            frames=result['flow_frames'];self.assertIsNotNone(result['goal_at_s'])
            states=[f['contact_circuits'][0] for f in frames]
            self.assertFalse(states[0]['closed']);self.assertEqual(states[0]['current_a'],0)
            self.assertTrue(any(s['closed'] and s['coil_w']>0 for s in states))
            self.assertNotEqual(states[0]['bodies'],states[-1]['bodies'],'transport follows measured lever motion')
            for f,s in zip(frames,states):
                self.assertEqual({w['legacy_leg'] for w in f['wires']},{'supply','switched','return'})
                self.assertTrue(all(w['value']==s['current_a'] for w in f['wires']))
                self.assertTrue({'lever','lever contact','contact plate'} <= {b['name'] for b in s['bodies']})
            print('CHAIN_CONTACT_DIAGRAM',good,'preview goal',result['goal_at_s'])

    @need_engine
    def test_chain_charge_keeps_the_iron_box_inside_the_original_target_after_landing(self):
        level=mg.level_by_id('chain')
        compiled=mw.compile_spec(mg.compose(level,level['solution'])[0])
        zone=level['goal']['station']['done_when']['in_zone']
        with tempfile.TemporaryDirectory() as logs:
            for seed in (0,2,3):
                run=mw.rehearse(mg.nudged(compiled,seed) if seed else compiled,ENGINE,Path(logs),seconds=6.5,
                               after_s=7,track=['block','cannon ball'])
                self.assertIsNone(run['error'])
                self.assertGreaterEqual(run['world_time_s'],6.5)
                self.assertTrue(run['stations'][0]['done'])
                self.assertLessEqual(run['stations'][0]['at_s'],level['time_s'])
                points=run['paths']['block']['points'];end=points[-1][1:4]
                self.assertTrue(all(abs(end[i]-zone['at_m'][i])<=zone['size_m'][i]/2 for i in range(3)),(seed,end))
                self.assertLessEqual(max(p[1] for p in points),zone['at_m'][0]+zone['size_m'][0]/2)
                self.assertTrue(any({h['body'],h['other']}=={'block','cannon ball'} for h in run['hits']))
                for c in run['readouts']['circuits']:
                    self.assertLess(abs(c['electrical_residual_j']),1e-6)
                print('CHAIN_LANDING',dict(seed=seed,end=end,goal_s=run['stations'][0]['at_s'],wall_s=run['wall_s'],circuits=run['readouts']['circuits']))

    @need_engine
    def test_chain_charge_material_comparison_preserves_declared_masses_and_reports_receipts(self):
        level=mg.level_by_id('chain')
        with tempfile.TemporaryDirectory() as logs:
            for material in ('glass','oak','iron'):
                spec=mg.compose(level,level['solution'])[0]
                next(p for p in spec['parts'] if p['name']=='block')['material']=material
                compiled=mw.compile_spec(spec)
                session=mw.MachineSession(compiled,ENGINE,Path(logs),paced=False)
                try:
                    mass=session.bodies['block']['mass_kg']
                    self.assertAlmostEqual(mass,mg.DENSITY[material]*.001,places=8)
                finally:session.close()
                run=mw.rehearse(compiled,ENGINE,Path(logs),seconds=6.5,after_s=7,track=['block','cannon ball'])
                self.assertIsNone(run['error'])
                self.assertTrue(any({h['body'],h['other']}=={'block','cannon ball'} for h in run['hits']))
                for c in run['readouts']['circuits']:
                    self.assertLess(abs(c['electrical_residual_j']),1e-6)
                print('CHAIN_MATERIAL',dict(material=material,mass_kg=mass,
                    cell_m=compiled['cell_m'],dt_s=mw.DT_S,end=run['paths']['block']['points'][-1],
                    wall_s=run['wall_s'],circuits=run['readouts']['circuits'],heat_ledger=run['readouts'].get('heat_ledger')))

    @need_engine
    def test_cannon_latch_keeps_heat_on_after_a_short_pull_for_glass_oak_and_iron(self):
        level=mg.level_by_id('fire')
        with tempfile.TemporaryDirectory() as logs:
            for material in ('glass','oak','iron'):
                with self.subTest(material=material):
                    spec=mg.compose(level,level['solution'])[0]
                    next(p for p in spec['parts'] if p['name']=='trigger handle')['material']=material
                    session=mw.MachineSession(mw.compile_spec(spec),ENGINE,Path(logs),paced=True)
                    try:
                        grip=next(d for d in session.compiled['electrical']['devices'] if d['name']=='trigger')['handle']['at_m']
                        session.mechanical_switch_pull('trigger','trigger handle',grip,[0,-8,0])
                        session.play(True)
                        deadline=time.monotonic()+15
                        while session.t<.25 and not session.error and time.monotonic()<deadline:
                            session.frame(session.seq,20)
                        session.mechanical_switch_pull('trigger','trigger handle',session.bodies['trigger handle']['position_m'],[0,0,0])
                        while session.t<1.3 and not session.error and time.monotonic()<deadline:
                            session.frame(session.seq,20)
                        frame=session.frame(0,0)
                        self.assertIsNone(frame['error'])
                        self.assertTrue(frame['readouts']['stations'][0]['done'],frame['readouts'])
                        hinge=next(j for j in frame['readouts']['joints'] if j['name']=='trigger rocker hinge')
                        self.assertLessEqual(hinge['degrees'],-30+1e-3)
                        self.assertTrue(next(d for d in frame['readouts']['electrical']['devices'] if d['name']=='trigger')['closed'])
                        self.assertTrue(all(p['force_n']==[0,0,0] for p in frame['readouts']['pulls']))
                        self.assertFalse(frame['readouts']['test_pulled'])
                        ledger=frame['readouts']['electrical']['networks'][0]['ledger']
                        self.assertLess(abs(ledger['electrical_residual_j']),1e-6)
                        print('CANNON_LATCH_MATERIAL',material,'dt',mw.DT_S,'goal',frame['readouts']['stations'][0]['at_s'],
                              'hinge',hinge['degrees'],'pulls',frame['readouts']['pulls'],'ledger',ledger)
                    finally:session.close()

    @need_engine
    def test_cannon_requires_both_leads_and_player_force_then_real_aim_and_charge(self):
        fire = mg.level_by_id('fire')
        before = copy.deepcopy(fire)
        placements = fire['solution']
        inputs = fire['solution_inputs']
        with tempfile.TemporaryDirectory() as logs:
            logs = Path(logs)
            good = mg.trial(fire, placements, ENGINE, logs, runs=3, handle_inputs=inputs)
            self.assertEqual(good['worked'], 3, good)
            scenarios = [
                ('no player input', placements, None),
                ('no leads', placements[:1], inputs),
                ('no feed', [placements[0], placements[2]], inputs),
                ('no return', placements[:2], inputs),
                ('wrong aim', [dict(placements[0], yaw_deg=35), *placements[1:]], inputs),
                ('weak charge', [dict(placements[0], powder_g=.5), *placements[1:]], inputs),
                ('too low', [dict(placements[0], bore_height_m=.2), *placements[1:]], inputs),
            ]
            for label, placed, forces in scenarios:
                with self.subTest(scenario=label):
                    result = mg.trial(fire, placed, ENGINE, logs, runs=3, handle_inputs=forces)
                    self.assertEqual(result['worked'], 0, result)
                    self.assertTrue(all(r['error'] is None for r in result['results']), result)
            compiled = mw.compile_spec(mg.compose(fire, placements)[0])
            self.assertFalse(compiled['circuits'], 'no invisible legacy firing circuit')
            self.assertFalse(compiled['thermo'].get('heaters'), 'no timer primer')
            self.assertEqual(len(compiled['electrical']['wires']), 3)
            dry = mg.preview(fire, placements, ENGINE, logs)
            self.assertIsNone(dry['goal_at_s'])
            self.assertTrue(dry['manual_input_required'])
            self.assertFalse(any(p['name']=='your cannon 1 ball' for p in dry['paths']))
            run = mw.rehearse(compiled, ENGINE, logs, seconds=4, flows=True, track=['your cannon 1 ball','block'],
                              handle_inputs=inputs)
            self.assertFalse(run['readouts']['test_pulled'])
            self.assertGreater(mg.run_energy(compiled, run['readouts'], run['world_time_s'])['pull_j'], 0)
            self.assertTrue(any(h['body']=='your cannon 1 ball' and h['other']=='block' for h in run['hits']))
            for network in run['readouts']['electrical']['networks']:
                self.assertLess(abs(network['ledger']['electrical_residual_j']), 1e-6)
            print('cannon force oracle:', good, 'electrical ledger:', run['readouts']['electrical']['networks'][0]['ledger'])
        self.assertEqual(fire, before, 'reference inputs never alter the saved setup')
        self.assertNotIn('solution_inputs', mg.public(fire))
    @need_engine
    def test_empty_learning_fields_open_and_step_without_dummy_bodies(self):
        for identity in EMPTY_START_LEVELS:
            with self.subTest(level=identity), tempfile.TemporaryDirectory() as logs:
                spec = mg.compose(mg.level_by_id(identity), [], leave_out_goal=True)[0]
                compiled = mw.compile_spec(spec)
                self.assertEqual(compiled['parts'], [])
                engine, _, _ = mw.build_engine(ENGINE, compiled, logs)
                try:
                    self.assertEqual(engine.first['bodies'], [])
                    reply = engine.op(op='step', dt=.002, n=1, moved=False)
                    self.assertTrue(reply['ok'])
                    self.assertEqual(reply['bodies'], [])
                finally:
                    engine.close()

    @need_engine
    def test_generated_recipe_reopens_after_cache_loss_without_exposing_answers(self):
        with tempfile.TemporaryDirectory() as logs:
            generated = mg.fresh_easy('easy-loop', 42, ENGINE, logs)
            public = mg.public(generated)
            self.assertTrue(public['variant']['validated'])
            self.assertNotIn('solution', public)
            self.assertNotIn('wrong', public)
            self.assertNotIn('validation', public['variant'])
            self.assertNotIn('attempts', public['variant'])
            kept = copy.deepcopy(generated)
            retrieved = mg.level_by_id(generated['id'])
            retrieved['machine']['title'] = 'changed outside the cache'
            self.assertEqual(mg.level_by_id(generated['id']), kept)
            mg._variants.clear(); mg._variant_requests.clear()
            with self.assertRaises(ValueError): mg.level_by_id(generated['id'])
            recreated = mg.fresh_easy('easy-loop', 42, ENGINE, logs, recipe_id=generated['id'])
            self.assertEqual(recreated['machine'], generated['machine'])
            self.assertEqual(recreated['goal'], generated['goal'])
            self.assertEqual(recreated['par_energy_j'], generated['par_energy_j'])
            with self.assertRaises(ValueError):
                mg.fresh_easy('easy-loop', 43, ENGINE, logs, recipe_id=generated['id'])

    @need_engine
    def test_rehearsed_water_energy_keeps_the_measured_source_work(self):
        level = mg.level_by_id('easy-water-receiver')
        spec, _, _ = mg.compose(level, level['solution'])
        compiled = mw.compile_spec(spec)
        with tempfile.TemporaryDirectory() as logs:
            result = mw.rehearse(compiled, ENGINE, logs, seconds=3)
        self.assertIn('pour', result['readouts'])
        energy = mg.energy_of(compiled, result['readouts'], result['world_time_s'])
        self.assertGreater(energy['run']['water_j'], 1)
        supplied = sum(source['source_energy_j'] for source in result['readouts']['pour']['sources'])
        # Preserve millijoules so small mechanical input is not rounded away.
        self.assertEqual(energy['run']['water_j'], round(supplied,3))

    @need_engine
    def test_sandbox_chain_runs_the_same_declaration_with_live_readings(self):
        template = next(t for t in mg.archived_sandbox_templates() if t['name']=='Chain reaction')
        spec, _, _ = mg.compose(mg.requested_level({'level': 'free', 'base': template['base']}), [])
        compiled = mw.compile_spec(spec)
        with tempfile.TemporaryDirectory() as logs:
            r = mw.rehearse(compiled, ENGINE, Path(logs), seconds=40.0, wall_limit_s=200,
                            track=['water wheel', 'marble'], after_s=0.25)
        self.assertTrue(r['stations'], 'readings were not discarded by composition')
        self.assertIsNone(r['error'])
        self.assertTrue(all(s['done'] for s in r['stations']), r['stations'])
        times = [s['at_s'] for s in r['stations']]
        self.assertEqual(times, sorted(times), 'the base chain happened in order')
        self.assertNotEqual(r['paths']['water wheel']['turn_wxyz'], [1, 0, 0, 0], 'the wheel turned in the engine')
        print(f'\n  Sandbox chain: all {len(times)} stations in order at {times}; wall {r["wall_s"]} s')

    @need_engine
    def test_the_free_builds_example_works_and_its_preview_follows_the_marbles(self):
        # A marble rolls onto the gate's paddle; the gate opens and its catch
        # holds it. The marbles waiting on the shelf roll down to the
        # flip-flop, which sends them to the stop and to the dominoes, and
        # every domino falls -- in the run as written and nudged a little.
        free = mg.level_by_id('free')
        spec, _, _ = mg.compose(free, free['example'])
        compiled = mw.compile_spec(spec)
        waiting = ('your marble 2', 'your marble 3', 'your marble 4')
        with tempfile.TemporaryDirectory() as logs:
            for seed in (0, 1, 2):
                s = mw.MachineSession(mg.nudged(compiled, seed) if seed else compiled, ENGINE, Path(logs), paced=False)
                try:
                    s.play(True)
                    began = time.perf_counter()
                    while time.perf_counter() - began < 120:
                        with s.lock:
                            if s.t >= 8.0 or s.error:
                                break
                            s.lock.wait(0.05)
                    with s.lock:
                        self.assertIsNone(s.error)
                        ends = {n: s.bodies[n]['position_m'] for n in waiting}
                        down = sum(1 for n, b in s.bodies.items() if 'dominoes' in n and b['position_m'][1] < 0.045)
                        events = [e['text'] for e in s.events]
                finally:
                    s.close()
                stopped = sum(1 for p in ends.values() if p[2] < -0.5 and p[1] > 0.1)
                beyond = sum(1 for p in ends.values() if p[2] > 0.3)
                print(f'\n  example, nudge {seed}: {stopped} at the stop, {beyond} to the dominoes, {down} dominoes down')
                self.assertTrue(any('caught on its ratchet' in e for e in events))
                self.assertGreaterEqual(stopped, 1)
                self.assertGreaterEqual(beyond, 1)
                self.assertEqual(down, 6)
            shown = mg.preview(free, free['example'], ENGINE, Path(logs))
        self.assertIsNone(shown['goal_at_s'])
        self.assertTrue(shown['paths'][0]['name'].startswith('your marble'), 'the marbles are followed first')

    @need_engine
    def test_a_marble_goes_from_a_track_onto_the_one_snapped_to_it_and_a_pin_makes_a_seesaw(self):
        free = mg.level_by_id('free')
        first = {'piece': 'track', 'x_m': 0.0, 'z_m': 0.0, 'top_height_m': 0.8, 'run_m': 0.6, 'drop_m': 0.1, 'end': 'open'}
        second = {'piece': 'track', 'x_m': 0.65, 'z_m': 0.05, 'top_height_m': 0.4, 'run_m': 0.6, 'drop_m': 0.1, 'end': 'stop'}
        second = dict(second, **mg.ghost(free, [first, second], 1, snapping=True)['snap']['knobs'])
        marble = dict({'piece': 'marble', 'x_m': 0.04, 'z_m': 0.02})
        placed = [first, second, marble]
        marble = dict(marble, **mg.ghost(free, placed, 2, snapping=True)['snap']['knobs'])
        spec, _, _ = mg.compose(free, [first, second, marble])

        def ran(spec, seconds):
            with tempfile.TemporaryDirectory() as logs:
                s = mw.MachineSession(mw.compile_spec(spec), ENGINE, Path(logs), paced=False)
                try:
                    s.play(True)
                    began = time.perf_counter()
                    while time.perf_counter() - began < 120:
                        with s.lock:
                            if s.t >= seconds or s.error:
                                break
                            s.lock.wait(0.05)
                    with s.lock:
                        return s.error, {n: dict(b) for n, b in s.bodies.items()}, [e['text'] for e in s.events]
                finally:
                    s.close()
        error, bodies, events = ran(spec, 3.0)
        self.assertIsNone(error)
        end = bodies['your marble 3']['position_m']
        print(f'\n  snapped tracks: the marble ended at {[round(v, 3) for v in end]}')
        # At the second track's stop, 1.2 m along, on the track.
        self.assertAlmostEqual(end[0], second['x_m'] + 0.6 - 0.02 - 0.02, delta=0.02)
        self.assertGreater(end[1], 0.25)
        # A plank on a block, pinned at its middle: a marble dropped on one end
        # tips it about the pin, and it stays on the pin; glued, it does not tip.
        block = {'piece': 'block', 'x_m': 0.0, 'z_m': 0.0, 'tall_m': 0.2, 'length_m': 0.02, 'depth_m': 0.1}
        plank = {'piece': 'plank', 'x_m': 0.0, 'z_m': 0.0, 'length_m': 0.6}
        built = mg.compose(free, [block, plank])[0]
        top = next(p for p in mw.compile_spec(built)['parts'] if p['name'] == 'your plank 2')['at_m']
        for kind, tips in (('pin', True), ('glue', False)):
            link = {'piece': 'link', 'kind': kind, 'a': 'your block 1', 'b': 'your plank 2', 'at_m': [0.0, top[1], 0.0],
                    'axis': 'along z'}
            spec = mg.compose(free, [block, plank, link])[0]
            spec['parts'].append({'name': 'dropped', 'shape': 'sphere', 'material': 'iron', 'size_m': [0.06] * 3,
                                  'at_m': [0.25, 0.8, 0.0]})
            error, bodies, events = ran(spec, 1.5)
            self.assertIsNone(error)
            q = bodies['your plank 2']['orientation_wxyz']
            tipped = 2 * math.degrees(math.acos(min(1.0, abs(q[0]))))
            print(f'  {kind}: the plank turned {tipped:.1f} degrees, its middle at {[round(v, 3) for v in bodies["your plank 2"]["position_m"]]}')
            self.assertLess(math.dist(bodies['your plank 2']['position_m'], top), 0.02, 'it stays on its pin')
            if tips:
                self.assertGreater(tipped, 5.0)
            else:
                self.assertLess(tipped, 1.0)

    @need_engine
    def test_marbles_held_on_a_shelf_are_split_three_ways_by_joined_pieces(self):
        # Built from joins alone, as the chat builds: a shelf whose gate stays
        # open, four marbles lined up on it, a trigger track over its paddle
        # with a marble on it, a long track from the shelf, a flip-flop, and a
        # second flip-flop on its right end; a track with a stop on each of the
        # three ends left. Every marble let go ends on one of the three tracks.
        free = mg.level_by_id('free')
        add = [{'piece': 'shelf', 'top_height_m': 0.9, 'run_m': 0.4, 'drop_m': 0.015, 'end': 'gate that stays open'}]
        add += [{'piece': 'marble', 'join': {'to': 1, 'port': 'top end'}}] * 3
        add += [{'piece': 'track', 'run_m': 0.36, 'drop_m': 0.03, 'join': {'to': 1, 'port': 'gate paddle'}},
                {'piece': 'marble', 'join': {'to': 5, 'port': 'top end'}},
                {'piece': 'marble', 'join': {'to': 1, 'port': 'top end'}},
                {'piece': 'track', 'run_m': 0.9, 'drop_m': 0.08, 'join': {'to': 1, 'port': 'far end'}},
                {'piece': 'flipflop', 'join': {'to': 8, 'port': 'far end'}},
                {'piece': 'track', 'run_m': 0.6, 'drop_m': 0.08, 'end': 'stop', 'join': {'to': 9, 'port': 'left end'}},
                {'piece': 'flipflop', 'join': {'to': 9, 'port': 'right end'}},
                {'piece': 'track', 'run_m': 0.6, 'drop_m': 0.08, 'end': 'stop', 'join': {'to': 11, 'port': 'left end'}},
                {'piece': 'track', 'run_m': 0.6, 'drop_m': 0.08, 'end': 'stop', 'join': {'to': 11, 'port': 'right end'}}]
        answer = {'reply': '', 'clear': True, 'add': add}
        placed = mc.respond_free('Split them three ways.', free, [], call=lambda messages: (answer, {}))['placements']
        spec, _, _ = mg.compose(free, placed)
        compiled = mw.compile_spec(spec)
        with tempfile.TemporaryDirectory() as logs:
            s = mw.MachineSession(compiled, ENGINE, Path(logs), paced=False)
            try:
                s.play(True)
                began = time.perf_counter()
                while time.perf_counter() - began < 120:
                    with s.lock:
                        if s.t >= 10.0 or s.error:
                            break
                        s.lock.wait(0.05)
                with s.lock:
                    self.assertIsNone(s.error)
                    ends = {n: mg.resting_on(compiled, s.bodies[n]['position_m'], 0.02)
                            for n in ('your marble 2', 'your marble 3', 'your marble 4', 'your marble 7')}
            finally:
                s.close()
        print(f'\n  three ways: {ends}')
        self.assertTrue(set(ends.values()) <= {'your track 10', 'your track 12', 'your track 13'}, ends)
        self.assertGreaterEqual(len(set(ends.values())), 2, 'they went more than one way')

    @need_engine
    def test_a_funnel_gathers_what_lands_anywhere_on_it_into_its_hole(self):
        # Marbles dropped on its corners, its edges and near its middle all go
        # down through its hole, near its middle; and a funnel moved near a
        # track's far end goes under it.
        free = mg.level_by_id('free')
        funnel = {'piece': 'funnel', 'x_m': 0.0, 'z_m': 0.0, 'height_m': 0.5, 'size_m': 0.4}
        base = mg.compose(free, [funnel])[0]
        hole = 0.5 - 0.12
        for x, z in ((0.15, 0.15), (-0.15, -0.15), (0.17, 0.0), (0.0, -0.17), (-0.08, 0.02)):
            spec = copy.deepcopy(base)
            spec['parts'].append({'name': 'm', 'shape': 'sphere', 'material': 'iron', 'size_m': [0.04] * 3, 'at_m': [x, 0.75, z]})
            with tempfile.TemporaryDirectory() as logs:
                s = mw.MachineSession(mw.compile_spec(spec), ENGINE, Path(logs), paced=False)
                try:
                    s.play(True)
                    began, last, crossed = time.perf_counter(), None, None
                    while time.perf_counter() - began < 60 and crossed is None:
                        with s.lock:
                            if s.t >= 2.0 or s.error:
                                break
                            at = list(s.bodies['m']['position_m'])
                            if last is not None and last[1] >= hole > at[1]:
                                crossed = at
                            last = at
                            s.lock.wait(0.005)
                finally:
                    s.close()
            with self.subTest(dropped_at=(x, z)):
                self.assertIsNotNone(crossed, 'it went down past the hole')
                self.assertLess(math.hypot(crossed[0], crossed[2]), 0.03, f'through the hole: {crossed}')
        track = {'piece': 'track', 'x_m': -0.6, 'z_m': 0.0, 'top_height_m': 0.9, 'run_m': 0.6, 'drop_m': 0.1, 'end': 'open'}
        g = mg.ghost(free, [track, dict(funnel, x_m=0.05, z_m=0.03)], 1, snapping=True)
        self.assertEqual(g['snap']['port'], 'far end')
        self.assertEqual(g['snap']['knobs'], {'x_m': 0.06, 'z_m': 0.0, 'height_m': 0.72})

    @need_engine
    def test_a_marble_goes_round_a_bend(self):
        # Down a track, round a bend 90 degrees either way and onto the track
        # snapped to its far end, to that track's stop.
        free = mg.level_by_id('free')
        for turn in (90, -90):
            entry = {'piece': 'track', 'x_m': -0.6, 'z_m': 0.0, 'top_height_m': 0.6, 'run_m': 0.6, 'drop_m': 0.06,
                     'end': 'open'}
            bend = {'piece': 'bend', 'x_m': 0.05, 'z_m': 0.05, 'top_height_m': 0.3, 'turn_deg': turn, 'radius_m': 0.3,
                    'drop_m': 0.04}
            bend = dict(bend, **mg.ghost(free, [entry, bend], 1, snapping=True)['snap']['knobs'])
            out = next(q for q in mg.ports(*[mg.check_placements(free, [entry, bend])[0],
                                              mw.compile_spec(mg.compose(free, [entry, bend])[0])])
                       if q['piece'] == 1 and q['port'] == 'far end')
            leave = {'piece': 'track', 'x_m': out['at'][0] + 0.05, 'z_m': out['at'][2] + 0.05, 'top_height_m': 0.1,
                     'run_m': 0.6, 'drop_m': 0.05, 'end': 'stop',
                     'yaw_deg': round(math.degrees(math.atan2(-out['dir'][2], out['dir'][0])))}
            leave = dict(leave, **mg.ghost(free, [entry, bend, leave], 2, snapping=True)['snap']['knobs'])
            spec, _, _ = mg.compose(free, [entry, bend, leave, {'piece': 'marble', 'x_m': -0.55, 'z_m': 0.0}])
            with tempfile.TemporaryDirectory() as logs:
                s = mw.MachineSession(mw.compile_spec(spec), ENGINE, Path(logs), paced=False)
                try:
                    s.play(True)
                    began = time.perf_counter()
                    while time.perf_counter() - began < 120:
                        with s.lock:
                            if s.t >= 4.0 or s.error:
                                break
                            s.lock.wait(0.05)
                    with s.lock:
                        self.assertIsNone(s.error)
                        end = s.bodies['your marble 4']['position_m']
                finally:
                    s.close()
            stop = [leave['x_m'] + 0.56 * out['dir'][0], leave['z_m'] + 0.56 * out['dir'][2]]
            print(f'\n  bend {turn}: the marble ended at {[round(v, 3) for v in end]}, the stop is at {[round(v, 3) for v in stop]}')
            self.assertLess(math.hypot(end[0] - stop[0], end[2] - stop[1]), 0.05, 'at the stop of the track after the bend')
            self.assertGreater(end[1], 0.05, 'on the track, not the ground')

    @need_engine
    def test_every_level_is_solved_by_its_solution_every_time_and_not_without_pieces(self):
        with tempfile.TemporaryDirectory() as logs:
            for level in LEVELS:
                with self.subTest(level=level['id']):
                    t = mg.trial(level, level['solution'], ENGINE, Path(logs), runs=3,
                                 handle_inputs=level.get('solution_inputs'), release_inputs=level.get('solution_releases'))
                    print(f"\n  {level['id']}: works {t['worked']} of 3, goal at {[r['goal_at_s'] for r in t['results']]}")
                    self.assertEqual(t['worked'], 3, t['results'])
                    try:
                        empty = mg.trial(level, [], ENGINE, Path(logs), runs=1)
                    except mg.LevelRefused:
                        continue      # the goal is about a piece not placed yet
                    self.assertEqual(empty['worked'], 0, f"{level['id']} is solved with no pieces at all")

    @need_engine
    def test_the_engines_search_finds_the_chain_from_a_ramp_in_the_wrong_place(self):
        # The model's own first try, a ramp over the lever: the ball flies past
        # it. Scattered starts, then one knob at a time, every step a real run.
        level = mg.level_by_id('chain')
        start = [{'piece': 'ramp', 'x_m': 0.5, 'top_height_m': 1.0, 'run_m': 1.0, 'foot_height_m': 0.05, 'z_m': 0.0}]
        with tempfile.TemporaryDirectory() as logs:
            reh = lambda c: mw.rehearse(c, ENGINE, Path(logs), seconds=level['time_s'] + 0.5, wall_limit_s=60)
            self.assertGreater(mg.miss_m(level, reh(mw.compile_spec(mg.compose(level, start)[0]))), 3.0,
                               'the start misses the lever and every step after it')
            placed, run, runs = mg.refine(level, start, reh, budget=48, scatter=16, seed=3)
        print(f'\n  chain found in {runs} runs: {placed}')
        self.assertEqual(mg.miss_m(level, run), 0.0)
        self.assertTrue(all(row['done'] for row in run['stations']), 'every step of the chain happened')

    @need_engine
    def test_turned_pieces_work_as_turned_in_the_engine(self):
        # A cannon turned 20 degrees fires 20 degrees off its old line.
        fire = mg.level_by_id('fire')
        spec, _, _ = mg.compose(fire, [dict(fire['solution'][0], yaw_deg=20), *fire['solution'][1:]])
        with tempfile.TemporaryDirectory() as logs:
            s = mw.MachineSession(mw.compile_spec(spec), ENGINE, Path(logs), paced=False)
            try:
                start, flown, began = None, None, time.perf_counter()
                trigger = next(d for d in s.compiled['electrical']['devices'] if d['name']=='trigger')
                s.mechanical_switch_pull('trigger', trigger['handle']['part'], trigger['handle']['at_m'], [0,-8,0])
                s.play(True)
                while time.perf_counter() - began < 120:
                    with s.lock:
                        s.lock.wait(0.05)
                        t, err = s.t, s.error
                    self.assertIsNone(err)
                    ball = next(b for b in s.frame(0, 0)['bodies'] if b['name'] == 'your cannon 1 ball')['position_m']
                    start = start or ball
                    if math.dist(ball, start) > 0.4 or t > 3.0:
                        flown = ball
                        break
            finally:
                s.close()
        out = [flown[i] - start[i] for i in range(3)]
        self.assertGreater(math.hypot(out[0], out[2]), 0.4, 'it fired')
        self.assertAlmostEqual(math.degrees(math.atan2(-out[2], out[0])), 20.0, delta=3.0)
        # A knife turned 30 degrees about the vertical still cuts the rope.
        cut = mg.level_by_id('cut')
        with tempfile.TemporaryDirectory() as logs:
            t = mg.trial(cut, [dict(cut['solution'][0], yaw_deg=30)], ENGINE, Path(logs), runs=1)
        self.assertEqual(t['worked'], 1, t['results'])

    @need_engine
    def test_each_levels_par_is_what_its_own_solution_takes(self):
        # Measured, rounded up to three figures: the level's own answer wins
        # on par, and a better one (level 1's plank a little shorter) beats it.
        with tempfile.TemporaryDirectory() as logs:
            for level in LEVELS:
                m = mg.measure_energy(level, level['solution'], ENGINE, Path(logs),
                                      handle_inputs=level.get('solution_inputs'), release_inputs=level.get('solution_releases'))
                with self.subTest(level=level['id']):
                    self.assertIsNotNone(m['goal_at_s'])
                    self.assertLessEqual(m['j'], level['par_energy_j'])
                    self.assertGreater(m['j'], 0.99 * level['par_energy_j'])
            gap = mg.level_by_id('gap')
            shorter = mg.measure_energy(gap, [dict(gap['solution'][0], length_m=0.66)], ENGINE, Path(logs))
        self.assertIsNotNone(shorter['goal_at_s'])
        self.assertLess(shorter['j'], gap['par_energy_j'])

    @need_engine
    def test_the_preview_is_the_engines_rehearsal_of_where_things_go(self):
        # Level 1 as it stands, then with the plank over the gap: the ball's
        # path, what it hits on the way, and when the goal happens -- the
        # same time the run itself gives.
        gap = mg.level_by_id('gap')
        with tempfile.TemporaryDirectory() as logs:
            bare = mg.preview(gap, [], ENGINE, Path(logs))
            done = mg.preview(gap, gap['solution'], ENGINE, Path(logs))
        self.assertIsNone(bare['goal_at_s'])
        self.assertIn('the ground', [h['other'] for h in bare['hits']], 'without the plank it falls in the gap')
        self.assertEqual(done['goal_at_s'], 1.9)
        ball = next(p for p in done['paths'] if p['goal'])
        self.assertEqual(ball['name'], 'ball')
        self.assertIn('your plank 1', [h['other'] for h in done['hits']])
        zone = gap['goal']['station']['done_when']['in_zone']
        end = ball['points'][-1][1:4]
        self.assertTrue(all(abs(end[i] - zone['at_m'][i]) <= zone['size_m'][i] / 2 for i in range(3)), end)

    @need_engine
    def test_short_optical_preview_follows_native_lens_focus_without_mutating_the_design(self):
        level = mg.level_by_id('easy-lens')
        before = copy.deepcopy(level)
        with tempfile.TemporaryDirectory() as work:
            logs = Path(work)
            good = mg.optical_preview(level, level['solution'], ENGINE, logs)
            misplaced = [dict(level['solution'][0], z_m=.3)]
            miss = mg.optical_preview(level, misplaced, ENGINE, logs)
            bare = mg.optical_preview(level, [], ENGINE, logs)
            for result in (good, miss, bare):
                self.assertTrue(result['paths'])
                self.assertAlmostEqual(result['world_time_s'], 1/60, places=12)
                self.assertLess(abs(result['watts']['residual']), 1e-10)
                self.assertLess(abs(result['joules']['residual']), 1e-10)
                self.assertTrue(all(math.isfinite(v) for p in result['paths'] for v in p['mm']))
                self.assertNotIn('goal_at_s', result, 'a setup trace is not a win prediction')
            self.assertGreater(good['photocells'][0]['power_w'], 2)
            self.assertLess(miss['photocells'][0]['power_w'], 2)
            self.assertLess(bare['photocells'][0]['power_w'], 2)
            self.assertEqual(list(logs.iterdir()), [], 'short previews remove their temporary engine files')
            dark = mg.optical_preview(mg.level_by_id('gap'), [], ENGINE, logs)
            self.assertEqual(dark['paths'], [])
        self.assertEqual(level, before)

    @need_engine
    def test_editable_lenses_mount_at_all_tray_diameters_shapes_and_orientations(self):
        import itertools
        level = mg.level_by_id('easy-lens')
        with tempfile.TemporaryDirectory() as logs:
            for diameter, shape, turn in itertools.product((.04,.06,.08,.10,.12), ('convex','concave'),
                    ((0,0,0),(37,0,0),(90,0,0),(0,45,0),(17,23,-35))):
                with self.subTest(diameter=diameter, shape=shape, turn=turn):
                    placement = [dict(level['solution'][0], diameter_m=diameter, shape=shape,
                        x_m=-.18, z_m=-.58, yaw_deg=turn[0], pitch_deg=turn[1], roll_deg=turn[2])]
                    r = mg.optical_preview(level, placement, ENGINE, Path(logs))
                    self.assertTrue(r['paths'])
                    self.assertLess(abs(r['watts']['residual']),1e-10)

    @need_engine
    def test_optical_lessons_keep_their_nudged_solutions_and_energy_par(self):
        with tempfile.TemporaryDirectory() as logs:
            for name in ('easy-lens','easy-mirror','laser'):
                level=mg.level_by_id(name)
                with self.subTest(level=name):
                    result=mg.trial(level,level['solution'],ENGINE,Path(logs),runs=3)
                    self.assertEqual(result['worked'],3,result['results'])
                    energy=mg.measure_energy(level,level['solution'],ENGINE,Path(logs))
                    self.assertIsNotNone(energy['goal_at_s'])
                    self.assertLessEqual(energy['j'],level['par_energy_j'])
                    self.assertGreater(energy['j'],.99*level['par_energy_j'])

    @need_engine
    def test_flow_preview_reports_native_light_water_and_signed_current_without_changing_the_setup(self):
        import sandbox_electrics as electrical
        import sandbox_water_launch as water
        with tempfile.TemporaryDirectory() as logs:
            logs = Path(logs)
            runs = []
            for closed in (True, False):
                spec = electrical.manual_loop(closed=closed)
                before = copy.deepcopy(spec)
                result = mw.rehearse(mw.compile_spec(spec), ENGINE, logs, seconds=1, flows=True)
                self.assertIsNone(result['error']); self.assertTrue(result['complete'])
                self.assertEqual(spec, before)
                rows = result['flow_frames']
                self.assertEqual(rows[0]['t'], 0)
                self.assertTrue(all(a['t'] < b['t'] for a,b in zip(rows, rows[1:])))
                self.assertLessEqual(len(rows), 182)
                last = {w['name']: w for w in rows[-1]['wires']}
                native = {w['name']: w['current_a'] for w in result['readouts']['electrical']['wires']}
                self.assertEqual({name:w['value'] for name,w in last.items()}, native)
                self.assertEqual(last['supply wire']['points_m'],
                                 [p for segment in last['supply wire']['mechanical']['segments_m'] for p in segment])
                # Frame zero uses the manufactured native terminal. Later
                # frames carry actual rod poses, including socket reaction.
                start=next(w for w in rows[0]['wires'] if w['name']=='supply wire')['points_m'][0]
                self.assertLess(math.dist(start,[-.68,.18,.07]),1e-6)
                runs.append(max(abs(w['value']) for w in last.values()))
            self.assertGreater(runs[0], .24)
            self.assertLess(runs[1], 1e-8, 'an open circuit must not predict flowing current')
            # Swapping a wire's declared endpoints changes only the sign and
            # arrow direction, not the physical magnitude.
            spec = electrical.manual_loop()
            w = spec['electrical']['wires'][0]; w['a'],w['b']=w['b'],w['a']
            reverse = mw.rehearse(mw.compile_spec(spec), ENGINE, logs, seconds=1, flows=True)
            self.assertLess(reverse['flow_frames'][-1]['wires'][0]['value'], -.24)
            template = water.TEMPLATES[1]
            level = mg.requested_level(dict(level='free',base=template['base']))
            compiled = mw.compile_spec(mg.compose(level,template['placements'])[0])
            poured = mw.rehearse(compiled, ENGINE, logs, seconds=5, flows=True)
            frames = poured['flow_frames']
            self.assertTrue(any(f.get('water',{}).get('xyz_mm') for f in frames))
            self.assertEqual(frames[-1]['water']['xyz_mm'], [], 'finite source stops pouring')
            self.assertGreater(frames[-1]['surface']['wet_cells'], 0)
            self.assertLessEqual(max(len(f.get('water',{}).get('xyz_mm',[]))//3 for f in frames),128)
            self.assertLessEqual(max(len(f.get('surface',{}).get('xyz_mm',[]))//3 for f in frames),512)
            self.assertAlmostEqual(frames[-1]['water']['poured_l'], poured['readouts']['pour']['poured_l'], places=2)
            self.assertLess(abs(poured['readouts']['pour']['residual_m3']),1e-8)
            blocked = mg.preview(mg.level_by_id('laser'),[],ENGINE,logs)
            laser = mg.level_by_id('laser')
            bounced = mg.preview(laser,laser['solution'],ENGINE,logs)
            self.assertIsNone(blocked['goal_at_s']); self.assertIsNotNone(bounced['goal_at_s'])
            self.assertTrue(any(len(p['w'])>=3 for f in bounced['flow_frames'] for p in f['light']))
            self.assertTrue(all(len(f['light'])<=32 for f in bounced['flow_frames']))

    @need_engine
    def test_gentle_first_launch_starts_beyond_the_bin_and_keeps_nudged_wins(self):
        level=mg.level_by_id('easy-catapult')
        tray=level['tray'][0]
        self.assertTrue(tray['start_at_defaults'])
        placed=[dict(piece='catapult',**{k:v['default'] for k,v in tray['knobs'].items() if 'default' in v})]
        self.assertEqual(placed[0]['x_m'],0)
        self.assertGreater(placed[0]['x_m'],-1,'outside the open end, not over the receiving floor')
        self.assertEqual(mw.compile_spec(mg.compose(level,placed)[0]),
                         mw.compile_spec(mg.compose(level,level['solution'])[0]))
        self.assertEqual(mg.public(level)['camera_area'],level['camera_area'])
        with self.assertRaises(mg.LevelRefused):
            mg.compose(level,[])
        with tempfile.TemporaryDirectory() as logs:
            for rows,wins in ((placed,3),([dict(placed[0],yaw_deg=90)],0)):
                result=mg.trial(level,rows,ENGINE,Path(logs),runs=3)
                print('Gentle first launch:',wins,'expected wins;',result['results'],flush=True)
                self.assertEqual(result['worked'],wins,result)
                self.assertTrue(all(r['error'] is None for r in result['results']))

    @need_engine
    def test_a_misplaced_piece_fails_for_a_physical_reason(self):
        # The knife set too high swings over the rope and into the weight's arm.
        level = mg.level_by_id('cut')
        high = [dict(level['solution'][0], pivot_height_m=level['solution'][0]['pivot_height_m'] + 0.2)]
        # The cannon too weak: its ball falls short of the block.
        fire = mg.level_by_id('fire')
        weak = [dict(fire['solution'][0], powder_g=0.5), *fire['solution'][1:]]
        # One mirror where two are needed: the beam goes into the wall.
        laser = mg.level_by_id('laser')
        # A panel lying flat in the sun, and one facing the sun in the shed's
        # shadow: too little sunlight for the winch to lift the weight.
        sun = mg.level_by_id('sun')
        flat = [{k: v for k, v in sun['solution'][0].items() if k not in ('yaw_deg', 'pitch_deg')}, *sun['solution'][1:]]
        shaded = [dict(sun['solution'][0], x_m=-0.8, z_m=0.6), *sun['solution'][1:]]
        # The counterweight hung too low: it reaches the ground before the
        # crate, supported by two rope spans, reaches the shelf.
        tackle = mg.level_by_id('tackle')
        low = copy.deepcopy(tackle['solution'])
        next(p for p in low if p['piece']=='counterweight')['height_m']=.45
        with tempfile.TemporaryDirectory() as logs:
            for lv, placed in ((level, high), (fire, weak), (laser, laser['solution'][:1]), (sun, flat), (sun, shaded),
                               (tackle, low)):
                t = mg.trial(lv, placed, ENGINE, Path(logs), runs=1,
                             handle_inputs=lv.get('solution_inputs'), release_inputs=lv.get('solution_releases'))
                self.assertEqual(t['worked'], 0, lv['id'])

    @need_engine
    def test_wall_lessons_have_material_comparisons_and_physical_failure_cases(self):
        # Same 80 mm marble, 20 mm cells and 1/240 s native steps. The wall
        # constrains authoring only; a miss is free fall and the wheel is passive.
        with tempfile.TemporaryDirectory() as logs:
            logs = Path(logs)
            for ident in ('easy-wall-drop', 'easy-wall-track', 'easy-wall-funnel', 'easy-wall-peg', 'easy-wall-seesaw', 'easy-wall-wheel'):
                level = mg.level_by_id(ident)
                for material in ('glass', 'oak', 'iron'):
                    changed = copy.deepcopy(level)
                    marble = next((p for p in changed['machine']['parts'] if p['name']=='marble'), None)
                    if marble:
                        marble['material'] = material
                    else:
                        changed['tray'][0]['knobs']['material'].update(choices=[material], default=material)
                    result = mg.trial(changed, changed['solution'], ENGINE, logs, runs=3)
                    print('WALL_LESSON', ident, material, result['results'])
                    self.assertEqual(result['worked'], 3, result)
                    self.assertTrue(all(r['error'] is None for r in result['results']))
                wrong = mg.trial(level, level['wrong'], ENGINE, logs, runs=3)
                self.assertEqual(wrong['worked'], 0, wrong)
                self.assertTrue(all(r['error'] is None for r in wrong['results']))
                if ident in ('easy-wall-wheel', 'easy-wall-seesaw'):
                    with self.assertRaises(mg.LevelRefused):
                        mg.compose(level, [])
                    spec = mg.compose(level, level['solution'])[0]
                    spec['parts'] = [p for p in spec['parts'] if p['name'] != 'marble']
                    held = 'your wall_water_wheel 1' if ident=='easy-wall-wheel' else 'your wall_lever 1'
                    spec['stations'][0]['focus'] = [held+(' wheel' if ident=='easy-wall-wheel' else ' lever')]
                    idle = mw.rehearse(mw.compile_spec(spec), ENGINE, logs, seconds=6, wall_limit_s=30)
                    self.assertFalse(idle['stations'][0]['done'], 'An unpowered wheel must not turn on its own')
                    joint = next(j for j in idle['readouts']['joints'] if j['name'] == held+' axle')
                    self.assertAlmostEqual(joint['turned_deg'], 0, delta=.01)
                else:
                    if ident=='easy-wall-drop':
                        with self.assertRaises(mg.LevelRefused):mg.compose(level, [])
                    else:
                        empty = mg.trial(level, [], ENGINE, logs, runs=3)
                        self.assertEqual(empty['worked'], 0, empty)
                    spec = mg.compose(level, level['solution'])[0]
                    body = 'your wall_marble 1' if ident=='easy-wall-drop' else 'marble'
                    run = mw.rehearse(mw.compile_spec(spec), ENGINE, logs, seconds=6, after_s=6, wall_limit_s=30, track=[body])
                    at = run['paths'][body]['points'][-1][1:4]
                    cup = next(p for p in spec['parts'] if p['name']=='catching cup cup')
                    floor = cup['parts'][0]['size_m']
                    # After continuing past the win, a ball may rest beside a
                    # cup wall outside the smaller central scoring zone. Test
                    # actual containment and its floor, not that central zone.
                    # 2 mm covers native contact slop and rounded trail output.
                    self.assertLessEqual(abs(at[0]-cup['at_m'][0]), floor[0]/2-.04-.04+.002)
                    self.assertLessEqual(abs(at[2]-cup['at_m'][2]), floor[2]/2-.04+.002)
                    self.assertAlmostEqual(at[1],cup['at_m'][1]+floor[1]/2+.04,delta=.002)
                    self.assertGreaterEqual(run['world_time_s'], 6)
                    self.assertTrue(any(hit['other'].startswith('your ') if ident!='easy-wall-drop' else hit['other']=='catching cup cup' for hit in run['hits']))
                energy = mg.measure_energy(level, level['solution'], ENGINE, logs)
                self.assertLessEqual(energy['j'], level['par_energy_j'])
                self.assertGreater(energy['j'], .99*level['par_energy_j'])

    @need_engine
    def test_wall_electricity_and_water_need_real_connections_contacts_and_flow(self):
        with tempfile.TemporaryDirectory() as folder:
            logs=Path(folder)
            for ident in ('easy-wall-loop','easy-wall-switch','easy-wall-fill','easy-wall-current'):
                level=mg.level_by_id(ident)
                with self.subTest(level=ident):
                    failed=mg.trial(level,level['wrong'],ENGINE,logs,runs=3)
                    self.assertEqual(failed['worked'],0,failed)
                    self.assertTrue(all(r['error'] is None for r in failed['results']))
                    compiled=mw.compile_spec(mg.compose(level,level['solution'])[0])
                    run=mw.rehearse(compiled,ENGINE,logs,seconds=level['time_s']+.3,flows=True)
                    self.assertIsNone(run['error'])
                    self.assertTrue(run['stations'][0]['done'])
                    if ident in ('easy-wall-loop','easy-wall-switch'):
                        wires=run['readouts']['electrical']['wires']
                        self.assertTrue(all(w['mechanical']['connected'] for w in wires))
                        for network in run['readouts']['electrical']['networks']:
                            self.assertLess(abs(network['ledger']['electrical_residual_j']),1e-8)
                    else:
                        for source in run['readouts']['pour']['sources']:
                            self.assertAlmostEqual(source['emitted_m3']+source['remaining_m3'],source['initial_m3'],places=10)
                        self.assertLess(abs(run['readouts']['pour']['residual_m3']),1e-10)
            fill=mg.level_by_id('easy-wall-fill')
            slow=copy.deepcopy(fill['solution']);slow[0]['opening_percent']=10
            self.assertEqual(mg.trial(fill,slow,ENGINE,logs,runs=3)['worked'],0,'Being aligned is insufficient when flow misses the deadline')
            wheel=mg.level_by_id('easy-wall-current')
            dry=mg.compose(wheel,wheel['solution'])[0]
            dry['spouts'][0]['opening_fraction']=0
            idle=mw.rehearse(mw.compile_spec(dry),ENGINE,logs,seconds=6)
            self.assertFalse(idle['stations'][0]['done'])
            axle=next(j for j in idle['readouts']['joints'] if j['name']=='your wall_water_wheel 1 axle')
            self.assertAlmostEqual(axle['turned_deg'],0,delta=.01)
            # The 100 mm marble's material changes its actual mass and contact
            # response; it never selects a scripted lamp event. Oak can miss
            # the contact dwell under a nudge, so the lesson stocks iron.
            measured=[]
            for material in ('glass','oak','iron'):
                level=mg.level_by_id('easy-wall-switch')
                level['tray'][0]['knobs']['material']['choices']=['glass','oak','iron']
                placed=copy.deepcopy(level['solution']);placed[0]['material']=material
                result=mg.trial(level,placed,ENGINE,logs,runs=3)
                self.assertTrue(all(r['error'] is None for r in result['results']))
                if material in ('glass','iron'):self.assertEqual(result['worked'],3,result)
                measured.append(dict(material=material,result=result))
            print('WALL CONTACT MATERIALS',json.dumps(measured))

    @need_engine
    def test_starter_ball_block_and_string_lessons_fail_when_the_primitive_is_misused(self):
        # A marble on flat floor stays put; a block too low leaves a hole and
        # one too high is a wall; a string tied low goes slack. Nudged, as
        # the solutions are, and each without an engine error.
        leaf = [-.5, .855, 0]
        cases = {'easy-roll': [[dict(piece='marble')], [dict(piece='marble', x_m=-.7, z_m=.3)]],
                 'easy-block': [[], [dict(piece='block', x_m=.05, tall_m=.4)]],
                 'easy-rope': [[dict(piece='ring_marble', x_m=-.5)],
                               [dict(piece='ring_marble', x_m=-.5), dict(piece='link', kind='string', a='frame beam',
                                    b='your ring_marble 1 ring', at_m=[-.1, 1.4, 0], at_b_m=leaf)]]}
        with tempfile.TemporaryDirectory() as logs:
            for ident, setups in cases.items():
                level = mg.level_by_id(ident)
                for placed in [level['wrong'], *setups]:
                    with self.subTest(level=ident, placed=placed):
                        t = mg.trial(level, placed, ENGINE, Path(logs), runs=3)
                        self.assertEqual(t['worked'], 0, t['results'])
                        self.assertTrue(all(r['error'] is None for r in t['results']), t['results'])
        self.assertEqual(sum(t['piece'] == 'link' for t in mg.level_by_id('easy-rope')['tray']), 1)
        self.assertEqual(mg.level_by_id('easy-rope')['tray'][1]['knobs']['kind']['choices'], ['string'],
                         'the rope lesson offers only a tension-only string')

    @need_engine
    def test_a_ring_marble_does_not_roll_true_where_a_marble_does(self):
        # On the roll lesson's slope a marble set down near the top rolls into
        # the cup; a ring marble set down at the same place does not. Its ring
        # is wider than the ball, so it reaches the floor whichever way the
        # ball rolls. Nudged, as the solutions are.
        roll = mg.level_by_id('easy-roll')
        ring = copy.deepcopy(roll)
        row = copy.deepcopy(next(t for t in mg.free_build()['tray'] if t['piece'] == 'ring_marble'))
        row.update(count=1, cost=0)
        ring['tray'] = [row]
        ring['goal']['station']['done_when']['in_zone']['part'] = 'your ring_marble 1'
        with tempfile.TemporaryDirectory() as logs:
            for x in (-.7, -.5):
                with self.subTest(x_m=x):
                    t = mg.trial(roll, [dict(piece='marble', x_m=x)], ENGINE, Path(logs), runs=3)
                    self.assertEqual(t['worked'], 3, t['results'])
                    t = mg.trial(ring, [dict(piece='ring_marble', x_m=x)], ENGINE, Path(logs), runs=3)
                    self.assertEqual(t['worked'], 0, t['results'])
                    self.assertTrue(all(r['error'] is None for r in t['results']), t['results'])


def game_test_batches():
    cases=[test for cls in list(globals().values())
           if isinstance(cls,type) and issubclass(cls,unittest.TestCase)
           for test in unittest.defaultTestLoader.loadTestsFromTestCase(cls)]
    engine=[test for test in cases if type(test) is Engine]
    return [engine[::2],engine[1::2],
            [test for test in cases if type(test) is not Engine]]


if __name__ == '__main__':
    shard=next((arg for arg in sys.argv[1:] if arg.startswith('--shard=')),None)
    if shard:
        index,count=map(int,shard.split('=',1)[1].split('/'))
        if count!=3 or not 0<=index<count:raise SystemExit('game batches use INDEX/3')
        sys.argv.remove(shard)
        batches=game_test_batches()
        print(f'Game batch {index+1}/3: {len(batches[index])} of {sum(map(len,batches))} cases',flush=True)
        result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(batches[index]))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    unittest.main(verbosity=2)
