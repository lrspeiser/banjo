"""Engine-backed fixed water stores, physical wheel/gate and cradle launches."""
import copy
import math
import os
import random
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import machine_world as mw
import machine_game as mg
import sandbox_water_launch as sw

ENGINE=Path(os.environ.get('BANJO_LIVE_ENGINE',ROOT/'build/rube/Release/banjo_live_world_run.exe')).resolve()
if '--engine' in sys.argv:
    i=sys.argv.index('--engine');ENGINE=Path(sys.argv[i+1]).resolve();del sys.argv[i:i+2]


class WaterLaunchTests(unittest.TestCase):
    def test_diversion_requires_downhill_contact_and_actual_retention(self):
        level=mg.level_by_id('easy-divert-water')
        for placements in ([],[dict(piece='water_chute')],
                           [dict(piece='water_chute',drop_deg=20,yaw_deg=180)],
                           [dict(piece='water_chute',drop_deg=20,yaw_deg=90)],
                           [dict(piece='water_chute',drop_deg=20,yaw_deg=0,z_m=1.3)]):
            with self.subTest(placements=placements):
                result=self.run_level(level,placements)
                self.assertIsNone(result['error'])
                self.assertFalse(result['stations'][0]['done'])
                self.assertLess(result['readouts']['water_regions'][0]['litres'],3)

    def test_fixed_collector_compares_materials_timesteps_and_water_ledgers(self):
        level=mg.level_by_id('easy-divert-water')
        for material in ('glass','oak','iron'):
            for dt in (1/240,1/480):
                with self.subTest(material=material,dt=dt),tempfile.TemporaryDirectory() as td:
                    setup=mg.compose(level,[dict(level['solution'][0],material=material)])[0]
                    next(p for p in setup['parts'] if p['name']=='receiving container')['material']=material
                    compiled=mw.compile_spec(setup);region=level['goal']['station']['done_when']['water_in_zone_l']
                    engine,_,_=mw.build_engine(ENGINE,compiled,td)
                    try:
                        for _ in range(80):result=engine.op(op='step',dt=dt,n=round(.1/dt),moved=False)
                        water=result['parcels'];account=water['sources'][0]
                        retained=mw.water_in_region_l(water,region)
                        self.assertGreaterEqual(retained,3)
                        self.assertAlmostEqual(retained,3.968,delta=1e-8)
                        self.assertAlmostEqual(account['remaining_m3']+account['emitted_m3'],.004,delta=1e-12)
                        self.assertLess(abs(water['residual_m3']),1e-12)
                        self.assertLess(abs(water['energy_residual_j']),1e-6)
                        self.assertLess(math.hypot(*water['momentum_residual_n_s']),1e-8)
                        self.assertEqual(mw.water_in_region_l(water,dict(region,at_m=[-1,.42,.7])),0)
                        # Total output has rounded display precision; the region
                        # observation must retain the unrounded 64 mL parcel mass.
                        self.assertNotEqual(retained,water['in_air_m3']*1000)
                        print('\n diversion:',material,dt,'retained L',retained,'energy residual',water['energy_residual_j'],
                              'momentum residual',water['momentum_residual_n_s'],'numerical correction',water['numerical_correction_j'])
                    finally:engine.close()

    def setUp(self):
        if not ENGINE.is_file():
            if os.environ.get('BANJO_MACHINE_ENGINE')=='required':self.fail('Native engine required')
            self.skipTest('Native engine not supplied')

    def run_level(self,level,placements,seed=None):
        spec=mg.compose(level,placements)[0]
        if seed is not None:
            rng=random.Random(seed)
            for p in spec['parts']:
                if not p.get('fixed'):p['at_m']=[v+rng.uniform(-.0015,.0015) for v in p['at_m']]
        with tempfile.TemporaryDirectory() as td:
            return mw.rehearse(mw.compile_spec(spec),ENGINE,td,seconds=level['time_s'])

    def test_all_examples_build_through_the_actual_sandbox(self):
        for template in sw.TEMPLATES:
            level=mg.requested_level(dict(level='free',base=template['base']))
            c=mw.compile_spec(mg.compose(level,template['placements'])[0])
            self.assertFalse(c.get('problems', []),template['name'])
        for piece in ('water_wheel','water_tank'):
            with self.assertRaisesRegex(ValueError,'channel base'):
                sw.PIECES[piece]('dry',{},dict(spec=sw.DRY_BASE))

    def test_each_easy_solution_wins_in_three_nudged_runs(self):
        for level in sw.EASY_LEVELS:
            for seed in range(3):
                with self.subTest(level=level['id'],seed=seed):
                    r=self.run_level(level,level['solution'],seed)
                    self.assertIsNone(r['error'])
                    self.assertTrue(r['stations'][0]['done'],r)
                    print('\n',level['id'],seed,r['stations'][0]['at_s'],'s;',r['wall_s'],'s wall')

    def test_wrong_no_release_empty_and_closed_setups_fail_physically(self):
        for level in sw.EASY_LEVELS:
            r=self.run_level(level,level['wrong'])
            self.assertIsNone(r['error'])
            self.assertFalse(r['stations'][0]['done'],level['id'])
        for changes in (dict(fill_l=0),dict(fill_l=2),dict(valve='closed')):
            level=sw.EASY_LEVELS[1];p=copy.deepcopy(level['solution']);p[0].update(changes)
            self.assertFalse(self.run_level(level,p)['stations'][0]['done'])
        level=sw.EASY_LEVELS[2];p=copy.deepcopy(level['solution']);p[0]['release']='held'
        self.assertFalse(self.run_level(level,p)['stations'][0]['done'])
        p=copy.deepcopy(level['solution']);p[0]['counterweight_material']='oak'
        self.assertFalse(self.run_level(level,p)['stations'][0]['done'])
        p=copy.deepcopy(level['solution']);p[0]['loaded']='empty'
        spec,_,_=mg.compose(level,p,leave_out_goal=True)
        self.assertIn('_needs',spec)
        with tempfile.TemporaryDirectory() as td:
            e,j,_=mw.build_engine(ENGINE,mw.compile_spec(spec),td)
            try:
                result=e.op(op='step',dt=.002,n=300,moved=False)
                self.assertFalse(any(b['name']=='your catapult 1 marble' for b in result['bodies']))
                axle=next(row for row in e.op(op='joints')['joints'] if row['id']==j['your catapult 1 axle'])
                self.assertGreater(abs(axle['degrees']),30,'The unloaded physical arm still moves')
            finally:e.close()
        level=sw.EASY_LEVELS[3];p=copy.deepcopy(level['solution']);p[1]['x_m']=.3
        self.assertFalse(self.run_level(level,p)['stations'][0]['done'])

    def test_finite_source_receiver_air_runoff_and_energy_close(self):
        level=sw.EASY_LEVELS[1];c=mw.compile_spec(mg.compose(level,level['solution'])[0])
        with tempfile.TemporaryDirectory() as td:
            e,_,_=mw.build_engine(ENGINE,c,td)
            try:
                # The gravity head declines: let the final emitted parcel
                # finish falling before auditing its receiver receipt.
                for _ in range(140):r=e.op(op='step',dt=.002,n=25,moved=False)
                p=r['parcels'];s=p['sources'][0]
                self.assertAlmostEqual(s['emitted_m3']+s['remaining_m3'],s['initial_m3'],delta=1e-12)
                self.assertLess(s['remaining_m3'],.000064)
                self.assertAlmostEqual(s['received_m3'],s['emitted_m3'],delta=1e-12)
                self.assertLess(abs(p['residual_m3']),1e-12)
                self.assertLess(abs(p['energy_residual_j']),1e-6)
                self.assertLess(math.hypot(*p['momentum_residual_n_s']),1e-8)
                self.assertLess(p['numerical_correction_j'],0)
                final=e.op(op='step',dt=.002,n=500,moved=False)['parcels']['sources'][0]
                self.assertEqual(final['emitted_m3'],s['emitted_m3'])
                print('\n tank:',s,'falling residuals',p['energy_residual_j'],p['momentum_residual_n_s'])
            finally:e.close()

    def test_runtime_valve_and_joint_release_are_real_queued_engine_actions(self):
        for piece in ('water_tank','catapult'):
            source=sw.EASY_LEVELS[1 if piece=='water_tank' else 2]
            p=copy.deepcopy(source['solution']);p[0].update(dict(opening_percent=0) if piece=='water_tank' else dict(release='held'))
            c=mw.compile_spec(mg.compose(source,p)[0])
            with tempfile.TemporaryDirectory() as td:
                session=mw.MachineSession(c,ENGINE,td,paced=False)
                try:
                    if piece=='water_tank':session.water_opening('your water_tank 1 outlet',.75)
                    else:session.release_joint('your catapult 1 restraint')
                    session.play(True)
                    deadline=time.monotonic()+15
                    with session.lock:
                        while session.t<(6 if piece=='water_tank' else 3) and not session.error and time.monotonic()<deadline:session.lock.wait(.1)
                        self.assertIsNone(session.error)
                        self.assertTrue(session.readouts['stations'][0]['done'])
                    with self.assertRaises(ValueError):session.water_valve('not an outlet',True)
                    with self.assertRaises(ValueError):session.release_joint('water gate slide')
                finally:session.close()

    def test_catapult_material_mass_contact_launch_and_timestep_comparison(self):
        speeds={}
        for material in ('oak','glass','iron'):
            for dt in (.002,.001):
                raw=copy.deepcopy(sw.DRY_BASE)
                raw.update(sw.catapult('launcher',dict(projectile_material=material),dict(spec=raw)))
                with tempfile.TemporaryDirectory() as td:
                    e,_,_=mw.build_engine(ENGINE,mw.compile_spec(raw),td)
                    try:
                        initial=e.op(op='thermo')['thermo']['ledger']['mechanical_j'];peak=0;highest=0
                        for _ in range(round(.8/(dt*25))):
                            r=e.op(op='step',dt=dt,n=25,moved=False)
                            ball=next(b for b in r['bodies'] if b['name']=='launcher marble')
                            peak=max(peak,math.hypot(*ball['velocity_m_s']));highest=max(highest,ball['position_m'][1])
                            energy=e.op(op='thermo')['thermo']['ledger']['mechanical_j']
                            self.assertLessEqual(energy,initial+.01,'No unaccounted launch energy may appear')
                        self.assertGreater(highest,1.45)
                        self.assertGreater(peak,2.7)
                        densities=dict(oak=700,glass=2500,iron=7870)
                        # The 2 cm lattice sphere occupies 34 cells; no mass override.
                        self.assertAlmostEqual(ball['mass_kg'],34*.02**3*densities[material],delta=1e-5)
                        speeds[material,dt]=peak
                        print('\n launch',material,'dt',dt,'mass',ball['mass_kg'],'peak',peak,'mechanical change',energy-initial)
                    finally:e.close()
            self.assertLess(abs(speeds[material,.002]-speeds[material,.001]),.06)
        self.assertGreater(speeds['oak',.002],speeds['glass',.002])
        self.assertGreater(speeds['glass',.002],speeds['iron',.002])

    def test_glass_oak_and_iron_wheels_use_the_same_pour_and_keep_falling_ledgers(self):
        for material in ('glass','oak','iron'):
            raw=copy.deepcopy(sw.CHANNEL_BASE)
            fragment=sw.water_wheel('wheel',{},dict(spec=raw))
            fragment['kits'][0]['material']=material
            for key,value in fragment.items():raw.setdefault(key,[]).extend(value)
            with tempfile.TemporaryDirectory() as td:
                e,_,_=mw.build_engine(ENGINE,mw.compile_spec(raw),td)
                try:
                    for _ in range(60):r=e.op(op='step',dt=.002,n=25,moved=False)
                    p=r['parcels']
                    self.assertLess(abs(p['residual_m3']),1e-12)
                    self.assertLess(abs(p['energy_residual_j']),1e-6)
                    self.assertLess(math.hypot(*p['momentum_residual_n_s']),1e-8)
                    self.assertGreater(p['body_work_j'],0)
                    print('\n wheel',material,'body work',p['body_work_j'],'energy residual',p['energy_residual_j'],
                          'momentum residual',p['momentum_residual_n_s'],'numeric correction',p['numerical_correction_j'])
                finally:e.close()

    def test_separate_gravity_tank_compares_glass_oak_and_iron_and_two_timesteps(self):
        level=mg.level_by_id('easy-water-wheel')
        for material in ('glass','oak','iron'):
            for dt in (1/240,1/480):
                raw=mg.compose(level,level['solution'])[0]
                next(k for k in raw['kits'] if k['kit']=='water_wheel')['material']=material
                next(p for p in raw['parts'] if p['name']=='your water_tank 1 tank')['material']=material
                with tempfile.TemporaryDirectory() as td:
                    e,j,_=mw.build_engine(ENGINE,mw.compile_spec(raw),td)
                    started=time.perf_counter()
                    try:
                        for _ in range(round(4/(dt*24))):r=e.op(op='step',dt=dt,n=24,moved=False)
                        p=r['parcels'];s=p['sources'][0]
                        self.assertLess(abs(p['residual_m3']),1e-12)
                        self.assertLess(abs(p['energy_residual_j']),1e-6)
                        self.assertLess(math.hypot(*p['momentum_residual_n_s']),1e-8)
                        self.assertGreater(p['body_work_j'],0)
                        self.assertAlmostEqual(s['remaining_m3']+s['emitted_m3'],.004,delta=1e-12)
                        angle=next(x for x in e.op(op='joints')['joints'] if x['id']==j['wheel target hinge'])['degrees']
                        print('\n gravity',material,'dt',dt,'angle',angle,'volume',s['remaining_m3'],
                            'source J',s['source_energy_j'],'body J',p['body_work_j'],'energy residual',p['energy_residual_j'],
                            'momentum residual',p['momentum_residual_n_s'],'numerical correction',p['numerical_correction_j'],
                            'support impulse',s['reservoir_support_reaction_n_s'],'support moment',s['reservoir_support_moment_n_m_s'],
                            'wall',time.perf_counter()-started)
                    finally:e.close()

    def test_modular_pour_requires_opening_and_aim_and_accepts_either_piece_order(self):
        # Version-2 shared challenges keep the former two-piece lesson.
        level=mg._with_free_knobs(copy.deepcopy(sw.LEGACY_MODULAR_LEVELS['easy-water-wheel']))
        with tempfile.TemporaryDirectory() as td:
            for label,placements in [('closed',level['wrong']),('small opening',[level['solution'][0],dict(level['solution'][1],opening_percent=1)]),
                    ('misses across channel',[level['solution'][0],dict(level['solution'][1],z_m=1)]),('misses along channel',[level['solution'][0],dict(level['solution'][1],x_m=1)]),
                    ('wheel only',level['solution'][:1])]:
                result=mg.trial(level,placements,ENGINE,Path(td),runs=3)
                self.assertEqual(result['worked'],0,(label,result))
            self.assertEqual(mg.trial(level,list(reversed(level['solution'])),ENGINE,Path(td),runs=3)['worked'],3)
            for name in ('easy-water-wheel','easy-water-gate','easy-water-receiver','easy-river-wheel'):
                row=mg.level_by_id(name);energy=mg.measure_energy(row,row['solution'],ENGINE,Path(td))
                self.assertLessEqual(energy['j'],row['par_energy_j'])
                self.assertGreater(energy['j'],.99*row['par_energy_j'])
            river=mg.level_by_id('easy-river-wheel');dry=copy.deepcopy(river);dry['machine']['ground']['discharge_m3_s']=0
            self.assertEqual(mg.trial(dry,dry['solution'],ENGINE,Path(td),runs=3)['worked'],0)

    def test_every_offered_wheel_radius_clears_bank_and_feed_support(self):
        for radius in (.25,.30,.35,.40,.45,.50,.55,.60,.65):
            level=mg.requested_level(dict(level='free',base=sw.CHANNEL_BASE))
            c=mw.compile_spec(mg.compose(level,[dict(piece='water_wheel',radius_m=radius,side='left')])[0])
            with tempfile.TemporaryDirectory() as td:
                e,_,_=mw.build_engine(ENGINE,c,td)
                try:
                    peak=0
                    for _ in range(40):
                        e.op(op='step',dt=.002,n=25,moved=False)
                        peak=max(peak,abs(e.op(op='joints')['joints'][0]['degrees']))
                    self.assertGreater(peak,30,'The selected radius has a real usable axle and water contact')
                finally:e.close()

    def test_river_current_lifts_a_real_drum_load_without_a_pour(self):
        level=next(l for l in sw.EASY_LEVELS if l['id']=='easy-river-lift')
        compiled=mw.compile_spec(mg.compose(level,level['solution'])[0])
        self.assertEqual(compiled['spouts'],[],'The boundary current supplies this wheel, not a falling pour')
        drum=next(j for j in compiled['joints'] if j['kind']=='drum')
        self.assertEqual((drum['drum'],drum['load']),('your water_wheel 1','river gate'))
        self.assertGreater(drum['centre_m'][1],drum['load_point_m'][1]+.08)
        with tempfile.TemporaryDirectory() as td:
            e,j,_=mw.build_engine(ENGINE,compiled,td)
            started=time.perf_counter()
            try:
                initial=next(b for b in e.first['bodies'] if b['name']=='river gate')['position_m'][1]
                rise=angle=wound=tension=0
                for _ in range(200):
                    r=e.op(op='step',dt=.002,n=25,moved=False)
                    gate=next(b for b in r['bodies'] if b['name']=='river gate')
                    rise=max(rise,gate['position_m'][1]-initial)
                    joints=e.op(op='joints')['joints']
                    hinge=next(row for row in joints if row['id']==j['your water_wheel 1 hinge'])
                    angle=max(angle,hinge['degrees'])
                    rope=next(row for row in joints if row['id']==j['your water_wheel 1 load drum'])
                    wound=max(wound,rope['wound_m']);tension=max(tension,rope['tension_n'])
                    if r.get('water'):self.assertLess(abs(r['water']['residual_m3']),1e-8)
                self.assertGreaterEqual(rise,.08,'The river must do useful work on the real guided gate')
                self.assertGreater(angle,0,'The real axle must turn in its winding direction')
                self.assertGreater(wound,0,'The angled rope must actually wind onto the drum')
                self.assertGreater(tension,0,'The rope must apply measured tension to the load')
                print('\n river lift: rise',rise,'m; wheel',angle,'deg; wound',wound,'m; tension',tension,'N; 2ms rigid /10cm fluid; wall',time.perf_counter()-started,'s')
            finally:e.close()
        for label,changes in [('no rope',dict(load_part='')),('on bank',dict(z_m=1))]:
            p=copy.deepcopy(level['solution']);p[0].update(changes)
            r=self.run_level(level,p)
            self.assertIsNone(r['error'])
            self.assertFalse(r['stations'][0]['done'],label)
        dry=copy.deepcopy(level);dry['machine']['ground']['discharge_m3_s']=0
        r=self.run_level(dry,dry['solution'])
        self.assertIsNone(r['error'])
        self.assertFalse(r['stations'][0]['done'],'A dry channel has no source of lifting work')

    def test_river_lesson_discharge_presets_win_without_changing_goal(self):
        source=next(l for l in sw.EASY_LEVELS if l['id']=='easy-river-lift')
        for discharge in (.095,.105,.11,.12):
            level=copy.deepcopy(source);level['machine']['ground']['discharge_m3_s']=discharge
            for seed in range(3):
                with self.subTest(discharge=discharge,seed=seed):
                    r=self.run_level(level,level['solution'],seed)
                    self.assertIsNone(r['error'])
                    self.assertTrue(r['stations'][0]['done'],r)
                    print('\n river discharge',discharge,'seed',seed,'wins',r['stations'][0]['at_s'],'s; wall',r['wall_s'],'s')


if __name__=='__main__':unittest.main()
