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

    def test_four_easy_solutions_win_in_three_nudged_runs(self):
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
        level=sw.EASY_LEVELS[3];p=copy.deepcopy(level['solution']);p[0]['side']='right'
        self.assertFalse(self.run_level(level,p)['stations'][0]['done'])

    def test_finite_source_receiver_air_runoff_and_energy_close(self):
        level=sw.EASY_LEVELS[1];c=mw.compile_spec(mg.compose(level,level['solution'])[0])
        with tempfile.TemporaryDirectory() as td:
            e,_,_=mw.build_engine(ENGINE,c,td)
            try:
                for _ in range(70):r=e.op(op='step',dt=.002,n=25,moved=False)
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
            p=copy.deepcopy(source['solution']);p[0].update(dict(valve='closed') if piece=='water_tank' else dict(release='held'))
            c=mw.compile_spec(mg.compose(source,p)[0])
            with tempfile.TemporaryDirectory() as td:
                session=mw.MachineSession(c,ENGINE,td,paced=False)
                try:
                    if piece=='water_tank':session.water_valve('your water_tank 1 outlet',True)
                    else:session.release_joint('your catapult 1 restraint')
                    session.play(True)
                    deadline=time.monotonic()+15
                    with session.lock:
                        while session.t<3 and not session.error and time.monotonic()<deadline:session.lock.wait(.1)
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

    def test_every_offered_wheel_radius_clears_bank_and_feed_support(self):
        for radius in (.25,.30,.35,.40):
            level=mg.requested_level(dict(level='free',base=sw.CHANNEL_BASE))
            c=mw.compile_spec(mg.compose(level,[dict(piece='water_wheel',radius_m=radius)])[0])
            with tempfile.TemporaryDirectory() as td:
                e,_,_=mw.build_engine(ENGINE,c,td)
                try:
                    peak=0
                    for _ in range(40):
                        e.op(op='step',dt=.002,n=25,moved=False)
                        peak=max(peak,abs(e.op(op='joints')['joints'][0]['degrees']))
                    self.assertGreater(peak,30,'The selected radius has a real usable axle and water contact')
                finally:e.close()


if __name__=='__main__':unittest.main()
