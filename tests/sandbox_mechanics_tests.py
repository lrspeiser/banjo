"""Engine-backed reusable piece checks; no displayed property counts as a law."""
import copy
import json
import math
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import machine_world as mw
import machine_game as mg
import sandbox_mechanics as sm

ENGINE = Path(os.environ.get('BANJO_LIVE_ENGINE', ROOT / 'build/rube/Release/banjo_live_world_run.exe'))
if '--engine' in sys.argv:
    i = sys.argv.index('--engine')
    ENGINE = Path(sys.argv[i + 1]).resolve()
    del sys.argv[i:i + 2]


def assembled(template, changes=None, station=None):
    """Exercise real builders and compiler before game dispatch is integrated."""
    spec = copy.deepcopy(template['base'])
    placements = copy.deepcopy(template['placements'])
    if changes:
        placements[0].update(changes)
    for i, p in enumerate(placements):
        row = next(t for t in sm.TRAY if t['piece'] == p['piece'])
        knobs = {key: value.get('default') for key, value in row['knobs'].items()}
        knobs.update({key: value.get('default') for key, value in mg.FREE_KNOBS.items()
                      if row.get('turning') is not False})
        knobs.update(p)
        fragment = sm.PIECES[p['piece']](f'your {p["piece"]} {i + 1}', knobs,
                                       {'spec': spec, 'tray': row, 'parts': mw.compile_spec(spec, lenient=True)['parts']})
        for key, value in fragment.items():
            if key == 'mirrors':
                spec.setdefault('light', {}).setdefault('mirrors', []).extend(value)
            elif isinstance(value, list):
                spec.setdefault(key, []).extend(value)
            elif isinstance(value, dict):
                spec.setdefault(key, {}).update(value)
            else:
                spec[key] = value
    spec['parts'] += mg.hold_up(mw.compile_spec(dict(spec, stations=[]))['parts'], only_player=True)
    if station:
        spec['stations'] = [station]
    return spec


def template(piece):
    return next(t for t in sm.templates() if t['placements'][0]['piece'] == piece)


def measured(spec, seconds=2, sample=None):
    compiled = mw.compile_spec(spec)
    with tempfile.TemporaryDirectory() as logs:
        session = mw.MachineSession(compiled, ENGINE, Path(logs), paced=False)
        try:
            session.play(True)
            started = time.perf_counter()
            while time.perf_counter() - started < 120:
                with session.lock:
                    if sample:
                        sample(session)
                    if session.t >= seconds or session.error:
                        break
                    session.lock.wait(.01)
            with session.lock:
                result = {'t': session.t, 'error': session.error, 'readouts': copy.deepcopy(session.readouts),
                          'bodies': {b['name']: copy.deepcopy(b) for b in session.bodies.values()},
                          'wall_s': time.perf_counter() - started}
            if result['t'] < seconds and not result['error']:
                raise RuntimeError(f'Rehearsal timed out at {result["t"]} s')
            return result
        finally:
            session.close()


def engine_test(test):
    def call(self):
        if not ENGINE.is_file():
            if os.environ.get('BANJO_MACHINE_ENGINE') == 'required':
                self.fail('BANJO_LIVE_ENGINE is required')
            self.skipTest('native engine unavailable')
        return test(self)
    call.__name__ = test.__name__
    return call


def spring_audit(material, dt):
    spec = assembled(template('spring'), {'material': material, 'stiffness_n_m': 1000, 'damping_n_s_m': 30})
    with tempfile.TemporaryDirectory() as logs:
        engine, _, _ = mw.build_engine(ENGINE, mw.compile_spec(spec), Path(logs))
        try:
            body = next(b for b in engine.first['bodies'] if b['name'].endswith(' load'))
            mass, y, speed = body['mass_kg'], body['position_m'][1], 0
            initial = mass * 9.81 * y + .5 * 1000 * (y - .58) ** 2
            damping, impulse = 0, 0
            for _ in range(round(.25 / dt)):
                impulse += (-mass * 9.81 - 1000 * (y - .58) - 30 * speed) * dt
                damping += 30 * speed * speed * dt
                reply = engine.op(op='step', dt=dt, n=1, moved=False)
                body = next(b for b in reply['bodies'] if b['name'].endswith(' load'))
                y, speed = body['position_m'][1], body['velocity_m_s'][1]
            final = mass * 9.81 * y + .5 * mass * speed ** 2 + .5 * 1000 * (y - .58) ** 2
            return {'material': material, 'dt': dt, 'mass_kg': mass, 'initial_j': initial,
                    'final_j': final, 'damping_quadrature_j': damping,
                    'energy_correction_j': final + damping - initial,
                    'impulse_correction_n_s': mass * speed - impulse}
        finally:
            engine.close()


class DeclarationChecks(unittest.TestCase):
    def test_each_piece_is_independent_and_saved_examples_compile(self):
        for row in sm.TRAY:
            example = {'base': sm.base(row['title']), 'placements': [{'piece': row['piece']}]}
            with self.subTest(piece=row['piece']):
                compiled = mw.compile_spec(assembled(example))
                self.assertTrue(compiled['parts'])
                self.assertFalse(mg.clashes_of(compiled))
                ghost = mg.ghost(mg.free_build(), [{'piece': row['piece']}], 0)
                self.assertTrue(ghost['fits'], ghost['problems'])
        for example in sm.templates():
            with self.subTest(example=example['name']):
                encoded = json.dumps(example)
                compiled = mw.compile_spec(assembled(json.loads(encoded)))
                self.assertFalse(mg.clashes_of(compiled), mg.clashes_of(compiled))
                self.assertTrue(compiled['parts'])
                level = mg.requested_level({'level': 'free', 'base': example['base']})
                native_spec, _, _ = mg.compose(level, example['placements'])
                self.assertTrue(mw.compile_spec(native_spec)['parts'])

    def test_dimensions_and_energy_sources_are_authoritative(self):
        panel = assembled(template('solar'), {'size_m': .4, 'battery': 'included battery'})
        self.assertAlmostEqual(mw.compile_spec(panel)['solar_panels'][0]['area_m2'], .16)
        dark = assembled({'base': sm.base('Dark'), 'placements': [{'piece': 'solar'}]})
        self.assertEqual(dark['sun']['irradiance_w_m2'], 0)
        self.assertEqual(dark['batteries'][0]['charge_j'], 0)
        lens = assembled(template('lens'), {'radius_m': .3, 'diameter_m': .08, 'height_m': .7})
        optic = mw.compile_spec(lens)['light']['lenses'][0]
        self.assertEqual(optic['at_m'][1], .7)
        self.assertEqual(optic['front_radius_m'], .3)
        self.assertEqual(optic['aperture_m'], .04)


class EngineChecks(unittest.TestCase):
    @engine_test
    def test_easy_solutions_win_nudged_and_physically_wrong_setups_fail(self):
        for original in sm.EASY_LEVELS:
            level = mg.level_by_id(original['id'])
            with tempfile.TemporaryDirectory() as logs, self.subTest(level=level['id']):
                hit = mg.trial(level, level['solution'], ENGINE, Path(logs), runs=3)
                wrong = mg.trial(level, level['wrong'], ENGINE, Path(logs), runs=3)
                self.assertEqual(hit['worked'], 3, hit)
                self.assertEqual(wrong['worked'], 0, wrong)
                self.assertTrue(all(x['error'] is None for x in hit['results'] + wrong['results']))
                empty, _, _ = mg.compose(level, [], leave_out_goal=True)
                r = measured(empty, level['time_s'])
                self.assertIsNone(r['error'])
                self.assertFalse(any(s['done'] for s in r['readouts']['stations']))
                print('EASY', level['id'], [r['goal_at_s'] for r in hit['results']])

    @engine_test
    def test_knife_cut_work_and_miss_are_engine_measured(self):
        spec = assembled(template('knife'))
        spec['stations'] = [{'title': 'Cut cord', 'done_when': {'cut': 'weight rope'}}]
        hit = measured(spec, 1)
        cut = next(c for c in hit['readouts']['cuts'] if c['target'] == 'weight rope')
        self.assertEqual(cut['kind'], 'edge')
        self.assertGreater(cut['work_j'], 5)
        self.assertGreater(cut['area_mm2'], 400)
        self.assertTrue(hit['readouts']['stations'][0]['done'])
        print('KNIFE', cut)
        for material in ('glass', 'iron'):
            compare = copy.deepcopy(spec)
            next(k for k in compare['kits'] if k['kit'] == 'hanging_weight')['peg_material'] = material
            result = measured(compare, 1)
            self.assertIsNone(result['error'])
            self.assertFalse(result['readouts']['stations'][0]['done'])
            print('KNIFE MATERIAL', material, result['readouts']['cuts'])

    @engine_test
    def test_spring_full_gravity_motion_damping_and_numerical_correction_refine(self):
        for material in ('oak', 'glass', 'iron'):
            coarse = spring_audit(material, 1 / 240)
            fine = spring_audit(material, 1 / 480)
            # No floor or guide-stop contact occurs in this .25s window.
            # Fixed anchors perform zero work; their reactions account for
            # momentum. The implicit spring integration's residual is recorded
            # as numerical correction, separately from viscous damping.
            self.assertLessEqual(coarse['energy_correction_j'], 0)
            self.assertLess(abs(fine['energy_correction_j']), abs(coarse['energy_correction_j']))
            self.assertLess(abs(fine['impulse_correction_n_s']), abs(coarse['impulse_correction_n_s']))
            print('SPRING AUDIT', coarse, fine)

    @engine_test
    def test_low_power_mirror_hits_a_sensor_and_wrong_angle_misses(self):
        hit = measured(assembled(template('mirror')), .5)
        miss = measured(assembled(template('mirror'), {'angle_deg': 0}), .5)
        self.assertIsNone(hit['error'])
        self.assertTrue(hit['readouts']['stations'][0]['done'], hit['readouts'])
        self.assertFalse(miss['readouts']['stations'][0]['done'])
        print('MIRROR', hit['readouts']['light']['photocells'], hit['readouts']['light']['joules']['residual'])

    @engine_test
    def test_convex_lens_increases_received_power_and_a_sideways_miss_fails(self):
        hit = measured(assembled(template('lens')), .5)
        miss = measured(assembled(template('lens'), {'z_m': .3}), .5)
        sensor = lambda r: next(x for x in r['readouts']['light']['photocells'] if x['name'] == 'target')['power_w']
        self.assertGreater(sensor(hit), sensor(miss) * 2)
        print('LENS', sensor(hit), sensor(miss))

    @engine_test
    def test_solar_orientation_and_full_battery_limit_charge(self):
        facing = measured(assembled(template('solar')), 1)
        flat = measured(assembled(template('solar'), {'pitch_deg': 0}), 1)
        dark = assembled(template('solar'))
        dark['sun']['irradiance_w_m2'] = 0
        dark = measured(dark, 1)
        charge = lambda r: r['readouts']['machines']['batteries'][0]['charge_j']
        self.assertGreater(charge(facing), charge(flat) * 2)
        self.assertEqual(charge(dark), 0)
        full = assembled(template('solar'))
        full['batteries'][0]['charge_j'] = full['batteries'][0]['capacity_j']
        full = measured(full, 1)
        self.assertEqual(charge(full), 10000)
        print('SOLAR', charge(facing), charge(flat), charge(dark))

    @engine_test
    def test_tackle_rises_at_ratio_and_lighter_counterweight_cannot_raise_iron_load(self):
        moving = measured(assembled(template('tackle')), 1)
        a = moving['bodies']['your tackle 1']['position_m'][1]
        b = moving['bodies']['your tackle 1 load']['position_m'][1]
        self.assertGreater(b, .45)
        self.assertAlmostEqual(1 - a, 2 * (b - .25), delta=.008)
        heavy = assembled(template('tackle'))
        next(p for p in heavy['parts'] if p['name'] == 'your tackle 1 load')['material'] = 'iron'
        heavy = measured(heavy, .5)
        self.assertLess(heavy['bodies']['your tackle 1 load']['position_m'][1], .26)
        print('TACKLE', a, b, 'ratio residual m', 1 - a - 2 * (b - .25))

    @engine_test
    def test_gears_follow_ratio_with_a_finite_battery_and_off_stays_still(self):
        driven = measured(assembled(template('gears')), 2)
        hinges = {j['name']: j for j in driven['readouts']['joints']}
        a = hinges['your gears 1 input axle']['turned_deg']
        b = hinges['your gears 1 output axle']['turned_deg']
        self.assertGreater(abs(a), 180)
        self.assertAlmostEqual(a, -2 * b, delta=2)
        circuit = driven['readouts']['circuits'][0]
        self.assertGreater(circuit['source_j'], 0)
        self.assertLess(abs(circuit['electrical_residual_j']), 1e-6)
        stopped = measured(assembled(template('gears'), {'drive': 'off'}), 1)
        self.assertLess(abs(next(j for j in stopped['readouts']['joints'] if j['name'].endswith('input axle'))['turned_deg']), 1)
        print('GEARS', a, b, json.dumps(circuit))

    @engine_test
    def test_weight_tip_and_matched_material_spring_settling(self):
        tipped = measured(assembled(template('weight')), 1)
        self.assertTrue(tipped['readouts']['stations'][0]['done'])
        outcomes = {}
        for material in ('oak', 'glass', 'iron'):
            sample = measured(assembled(template('spring'), {'material': material, 'stiffness_n_m': 400,
                                                             'damping_n_s_m': 20}), 3)
            self.assertIsNone(sample['error'])
            y = sample['bodies']['your spring 1 load']['position_m'][1]
            self.assertGreater(y, .15)
            outcomes[material] = y
        self.assertGreater(outcomes['oak'], outcomes['glass'])
        self.assertGreater(outcomes['glass'], outcomes['iron'])
        print('SPRING MATERIALS', outcomes)


if __name__ == '__main__':
    unittest.main()
