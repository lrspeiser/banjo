"""Solar-to-shaft-to-raised-load regression with the full mechanical ledger."""
import copy
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import machine_world as mw
import machine_game as mg
import sandbox_combinations as combinations

ENGINE = Path(os.environ.get('BANJO_LIVE_ENGINE', ROOT / 'build/rube/Release/banjo_live_world_run.exe'))
if '--engine' in sys.argv:
    i = sys.argv.index('--engine'); ENGINE = Path(sys.argv[i + 1]).resolve(); del sys.argv[i:i + 2]


def audit(spec, dt, material='oak', seconds=.75):
    spec = copy.deepcopy(spec)
    next(p for p in spec['parts'] if p['name'] == 'flag')['material'] = material
    compiled = mw.compile_spec(spec)
    with tempfile.TemporaryDirectory() as logs:
        engine, _, _ = mw.build_engine(ENGINE, compiled, Path(logs))
        try:
            initial = next(b for b in engine.first['bodies'] if b['name'] == 'flag')
            mass = initial['mass_kg']
            start_y = initial['position_m'][1]
            theta, bearing_heat = 0, 0
            for _ in range(round(seconds / dt)):
                reply = engine.op(op='step', dt=dt, n=1, moved=False)
                body = next(b for b in reply['bodies'] if b['name'] == 'flag')
                next_theta = 2 * math.atan2(body['orientation_wxyz'][3], body['orientation_wxyz'][0])
                bearing_heat += .001 * abs(next_theta - theta)
                theta = next_theta
            p, v = body['position_m'], body['velocity_m_s']
            # A fixed-axis rigid box; translational+rotational kinetic energy
            # equals one half its inertia about that axis times omega squared.
            omega = (p[0] * v[1] - (p[1] - .8) * v[0]) / (p[0] ** 2 + (p[1] - .8) ** 2)
            inertia = mass * ((.5 ** 2 + .06 ** 2) / 12 + .15 ** 2)
            kinetic = .5 * inertia * omega ** 2
            potential = mass * 9.81 * (p[1] - start_y)
            ledger = engine.op(op='circuits')['circuits'][0]['ledger']
            stores = reply['machines']['stores']
            supply = next(s for s in stores if s['name'] == 'supply battery')
            cables=[{key:c[key] for key in ('name','connected','retention_n','peak_terminal_force_n')}
                    for c in engine.op(op='mechanical_cables')['cables']]
            return {'dt': dt, 'material': material, 'mass_kg': mass,
                    'kinetic_j': kinetic, 'potential_j': potential, 'bearing_heat_j': bearing_heat,
                    'mechanical_residual_j': potential + kinetic + bearing_heat - ledger['shaft_j'],
                    'ledger': ledger, 'supply': supply, 'lift_m': p[1] - start_y,'cables':cables}
        finally:
            engine.close()


class SolarLift(unittest.TestCase):
    def test_display_requirements_use_native_mass_and_do_not_change_the_power_or_goals(self):
        import sandbox_electrics as electrics
        level=mg.level_by_id('easy-charge-lift')
        original=mg.compose(level,level['solution'])[0]
        for material,density in [('glass',2500),('oak',700),('iron',7870)]:
            for dt in (1/240,1/480):
                spec=copy.deepcopy(original)
                next(p for p in spec['parts'] if p['name']=='flag')['material']=material
                compiled=mw.compile_spec(spec)
                with tempfile.TemporaryDirectory() as td:
                    engine,_,_=mw.build_engine(ENGINE,compiled,Path(td))
                    try:
                        bodies={b['name']:b for b in engine.first['bodies']}
                        unchanged=copy.deepcopy(compiled)
                        rows=electrics.power_requirements(compiled,bodies,{},[],[])
                        row=next(r for r in rows if r['name']=='drive')
                        torque=.5*.06*.12*density*9.81*.15+.001
                        self.assertAlmostEqual(row['required_torque_n_m'],torque,delta=1e-5)
                        self.assertAlmostEqual(row['required_w'],torque**2*6/5,delta=1e-4)
                        self.assertEqual(row['exceeds_motor'],torque>5)
                        self.assertEqual(compiled,unchanged,'Display calculations cannot alter the physical declaration')
                        reply=engine.op(op='step',dt=dt,n=1,moved=False)
                        self.assertIsNone(reply.get('error'))
                        print('POWER REQUIREMENT',material,dt,row['required_w'],row['required_torque_n_m'])
                    finally:engine.close()

    def setUp(self):
        if not ENGINE.is_file():
            if os.environ.get('BANJO_MACHINE_ENGINE') == 'required': self.fail('native engine required')
            self.skipTest('native engine unavailable')

    def test_correct_panel_wins_nudged_flat_and_empty_fail(self):
        level = mg.level_by_id('easy-charge-lift')
        with tempfile.TemporaryDirectory() as logs:
            for label, placements, expected in [('aligned', level['solution'], 3),
                                                 ('flat', level['wrong'], 0), ('empty', [], 0)]:
                result = mg.trial(level, placements, ENGINE, Path(logs), runs=3)
                self.assertEqual(result['worked'], expected, result)
                self.assertTrue(all(r['error'] is None for r in result['results']))
                print('CHARGE LIFT', label, result)

    def test_solar_lift_needs_sunlight_and_preview_reports_native_source(self):
        level=mg.level_by_id('easy-charge-lift')
        spec=mg.compose(level,level['solution'])[0]
        spec['sun']['irradiance_w_m2']=0
        with tempfile.TemporaryDirectory() as logs:
            result=mw.rehearse(mw.compile_spec(spec),ENGINE,Path(logs),seconds=level['time_s'],flows=True)
            self.assertIsNone(result['error'])
            self.assertFalse(result['stations'][0]['done'],'The bulb is a load, not the solar light source')
            self.assertTrue(result['flow_frames'])
            for frame in result['flow_frames']:
                self.assertEqual(frame['solar_panels'][0]['power_w'],0)
                self.assertEqual(next(b for b in frame['batteries'] if b['name']=='supply battery')['charge_j'],0)

    def test_supply_light_motor_and_mechanics_ledger_closes_with_recorded_correction(self):
        level = mg.level_by_id('easy-charge-lift')
        spec, _, _ = mg.compose(level, level['solution'])
        for material, density in [('oak', 700), ('glass', 2500), ('iron', 7870)]:
            for dt in (1 / 240, 1 / 480, .001, .0005):
                with self.subTest(material=material, dt=dt):
                    result = audit(spec, dt, material)
                    ledger, supply = result['ledger'], result['supply']
                    self.assertAlmostEqual(result['mass_kg'], .5 * .06 * .12 * density, places=5)
                    self.assertLess(abs(ledger['electrical_residual_j']), 1e-8)
                    self.assertLess(abs(ledger['thermal_residual_j']), 1e-6)
                    self.assertAlmostEqual(supply['taken_j'] - supply['given_j'], supply['charge_j'], delta=1e-5)
                    # Correction is explicitly booked, rather than called a
                    # conservation proof or hidden inside a new heat term.
                    exported = ledger['shaft_j'] + ledger['heat_j'] + ledger['emitted_j'] + ledger['exported_j']
                    self.assertAlmostEqual(ledger['source_j'] + ledger['coupling_residual_j'], exported, delta=1e-7)
                    # This is the raised load/hinge ledger, not the cable
                    # assembly's full-pipeline conservation qualification.
                    # Its fixed mount does no work; pose rounding and native
                    # correction leave <0.01 J unaccounted for this load.
                    self.assertLess(abs(result['mechanical_residual_j']), .01)
                    self.assertTrue(all(c['connected'] for c in result['cables']),result['cables'])
                    if material == 'oak':
                        self.assertGreater(result['lift_m'], .05)
                        self.assertLess(abs(ledger['coupling_residual_j']), .02 * ledger['shaft_j'])
                    else:
                        self.assertLess(result['lift_m'], .05)
                    print('SOLAR LIFT AUDIT', {key: value for key, value in result.items()
                                               if key not in ('ledger', 'supply')},
                          'shaft_j', ledger['shaft_j'], 'coupling_j', ledger['coupling_residual_j'])


class MarbleShowcases(unittest.TestCase):
    def setUp(self):
        if not ENGINE.is_file():
            if os.environ.get('BANJO_MACHINE_ENGINE') == 'required':self.fail('native engine required')
            self.skipTest('native engine unavailable')

    def run_machine(self,spec,seconds=20):
        with tempfile.TemporaryDirectory() as logs:
            return mw.rehearse(spec,ENGINE,Path(logs),seconds=seconds,wall_limit_s=120,
                               track=['traveller'],after_s=.25)

    def test_five_marble_journeys_finish_in_order_with_native_nudges(self):
        for row in mg.sandbox_templates():
            compiled=mw.compile_spec(row['base'])
            self.assertLessEqual(len(compiled['parts']),mw.MAX_PARTS)
            for seed in (0,1,2):
                with self.subTest(machine=row['name'],seed=seed):
                    result=self.run_machine(mg.nudged(compiled,seed) if seed else compiled)
                    self.assertIsNone(result['error'],result)
                    self.assertTrue(result['complete'],result['world_time_s'])
                    self.assertTrue(all(s['done'] for s in result['stations']),result['stations'])
                    times=[s['at_s'] for s in result['stations']]
                    self.assertEqual(times,sorted(times),'Stations observe the causal sequence')
                    pts=result['paths']['traveller']['points']
                    length=sum(math.dist(a[1:],b[1:]) for a,b in zip(pts,pts[1:]))
                    self.assertGreater(length,8,'The marble must travel through the machine')
                    print('MARBLE JOURNEY',row['name'],seed,'stations',times,'path_m',round(length,2),
                          'sim_s',result['world_time_s'],'wall_s',result['wall_s'],flush=True)

    def test_removing_the_driving_input_stops_the_physical_handoff(self):
        for row in mg.sandbox_templates():
            spec=row['base']
            if row['name']=='Waterworks express':spec['spouts'][0]['valve_open']=False
            elif row['name']=='Solar pinball factory':spec['sun']['irradiance_w_m2']=0
            elif row['name']=='Light the fuse':spec['batteries'][0]['charge_j']=0
            else:
                ball=next(p for p in spec['parts'] if p['name']==('starter marble' if row['name']=='Electric marble relay' else 'traveller'))
                ball['at_m'][2]+=4
            with self.subTest(machine=row['name']):
                result=self.run_machine(mw.compile_spec(spec),seconds=16)
                self.assertIsNone(result['error'])
                self.assertFalse(result['stations'][-1]['done'],result['stations'])
                release=next(s for s in result['stations'] if any(word in s['title'] for word in
                    ('swinging door','starting gate','carrier rises','draws the gate','metal contact')))
                self.assertFalse(release['done'],result['stations'])
                print('MARBLE BLOCKED',row['name'],'wall_s',result['wall_s'],flush=True)

    def test_same_tower_geometry_for_glass_oak_and_iron(self):
        import sandbox_showcases
        for material in ('glass','oak','iron'):
            spec=sandbox_showcases.switchback()
            next(p for p in spec['parts'] if p['name']=='traveller')['material']=material
            result=self.run_machine(mw.compile_spec(spec))
            self.assertIsNone(result['error'])
            self.assertTrue(result['stations'][2]['done'],result['stations'])
            # Same size, route, timestep and gravity. Door/domino outcomes may
            # differ with material mass; do not relabel all three as glass.
            print('MARBLE MATERIAL',material,'dt_s',mw.DT_S,'stations',result['stations'],flush=True)


if __name__ == '__main__': unittest.main()
