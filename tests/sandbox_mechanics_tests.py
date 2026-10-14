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


def contact_gear_audit(material,dt):
    level=mg.level_by_id('easy-gears')
    spec=mg.compose(level,level['solution'])[0]
    wheels=[p for p in spec['parts'] if p['shape']=='compound']
    density={'oak':700,'glass':2500,'iron':7870}[material]
    properties={}
    for p in wheels:
        p['material']=material
        mass=inertia=0
        for shape in p['parts']:
            a,b,c=shape['size_m'];x,y,z=shape['at_m']
            m=density*(math.pi*(a/2)**2*b if shape['shape']=='cylinder' else a*b*c)
            mass+=m
            inertia+=m*((a/2)**2/2 if shape['shape']=='cylinder' else (a*a+b*b)/12)+m*(x*x+y*y)
        properties[p['name']]=(mass,inertia)
    with tempfile.TemporaryDirectory() as td:
        engine,_,_=mw.build_engine(ENGINE,mw.compile_spec(spec),td)
        try:
            saved=lambda:{b['name']:b['pose'] for b in engine.op(op='snapshot')['snapshot']['bodies'] if b['name'] in properties}
            initial=saved();last=initial;bearing=0;elapsed=0;started=time.perf_counter()
            for _ in range(round(1/dt)):
                engine.op(op='step',dt=dt,n=1,moved=False)
                last=saved();elapsed+=dt
                bearing+=.001*sum(abs(p['w_rad_s'][2]) for p in last.values())*dt
            energy=momentum_z=potential_change=0
            linear=[0,0,0]
            for name,p in last.items():
                mass,inertia=properties[name]
                # Hinge holds the axle about z. Include COM offset in the axle
                # inertia; do not count its constrained COM translation twice.
                energy+=.5*inertia*p['w_rad_s'][2]**2
                momentum_z+=inertia*p['w_rad_s'][2]
                potential_change+=mass*9.81*(p['com_m'][1]-initial[name]['com_m'][1])
                for axis in range(3):linear[axis]+=mass*(p['v_m_s'][axis]-initial[name]['v_m_s'][axis])
            ledger=engine.op(op='circuits')['circuits'][0]['ledger']
            angles=engine.op(op='joints')['joints']
            native={b['name']:b['mass_kg'] for b in engine.first['bodies'] if b['name'] in properties}
            return dict(material=material,dt=dt,masses_kg=native,expected_masses_kg={n:v[0] for n,v in properties.items()},
                angles_deg_wrapped={j['id']:j['degrees'] for j in angles},source_j=ledger['source_j'],
                shaft_j=ledger['shaft_j'],electrical_residual_j=ledger['electrical_residual_j'],
                coupling_residual_j=ledger['coupling_residual_j'],kinetic_about_axles_j=energy,
                potential_change_j=potential_change,bearing_quadrature_j=bearing,
                contact_and_constraint_remainder_j=ledger['shaft_j']-energy-potential_change-bearing,
                required_fixed_support_impulse_n_s=[linear[0],linear[1]+sum(v[0] for v in properties.values())*9.81*elapsed,linear[2]],
                angular_momentum_about_axles_n_m_s=momentum_z,wall_s=time.perf_counter()-started)
        finally:engine.close()


def latched_spring_audit(material,dt):
    level=copy.deepcopy(mg.level_by_id('easy-spring'))
    next(p for p in level['machine']['parts'] if p['name']=='spring load')['material']=material
    compiled=mw.compile_spec(mg.compose(level,level['solution'])[0])
    with tempfile.TemporaryDirectory() as td:
        engine,ids,_=mw.build_engine(ENGINE,compiled,td)
        try:
            bodies={b['name']:b for b in engine.first['bodies'] if not b['anchored']}
            names=set(bodies)
            def poses():
                return {b['name']:b['pose'] for b in engine.op(op='snapshot')['snapshot']['bodies'] if b['name'] in names}
            def energy(p):
                total=0
                for name,state in p.items():
                    mass=bodies[name]['mass_kg'];size=bodies[name]['dimensions_m']
                    total+=mass*9.81*state['com_m'][1]+.5*mass*sum(v*v for v in state['v_m_s'])
                    # Uniform voxel boxes: rotate measured angular velocity
                    # into each body's principal frame before using inertia.
                    q=state['q_wxyz'];u=[-v for v in q[1:]];omega=state['w_rad_s']
                    cross=lambda a,b:[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
                    uv=cross(u,omega);uuv=cross(u,uv)
                    local=[omega[i]+2*q[0]*uv[i]+2*uuv[i] for i in range(3)]
                    total+=sum(mass*sum(size[j]**2 for j in range(3) if i!=j)/24*local[i]**2 for i in range(3))
                total+=engine.op(op='joints')['joints'][0]['stored_j']
                return total
            initial=poses();initial_j=energy(initial);previous=initial;damping=impulse=0;started=time.perf_counter()
            engine.op(op='unhinge',joint=ids['your spring 1 restraint'])
            for _ in range(round(.1/dt)):
                plate=previous['your spring 1 push plate'];velocity=plate['v_m_s'][1]
                length=plate['com_m'][1]-.10
                damping+=6*velocity**2*dt
                impulse+=(200*(.7-length)-6*velocity)*dt
                engine.op(op='step',dt=dt,n=1,moved=False);previous=poses()
            final_j=energy(previous);mass=sum(b['mass_kg'] for b in bodies.values())
            return dict(material=material,dt=dt,masses_kg={n:b['mass_kg'] for n,b in bodies.items()},
                load_y_m=previous['spring load']['com_m'][1],initial_j=initial_j,final_j=final_j,
                damping_quadrature_j=damping,contact_and_numerical_remainder_j=initial_j-final_j-damping,
                required_cradle_and_guide_impulse_n_s=sum(bodies[n]['mass_kg']*p['v_m_s'][1] for n,p in previous.items())+mass*9.81*.1-impulse,
                wall_s=time.perf_counter()-started)
        finally:engine.close()


class DeclarationChecks(unittest.TestCase):
    def test_spring_aim_rotates_the_physical_slide_and_old_saves_keep_the_original_builder(self):
        free=mg.free_build()
        old=mg.compose(free,[dict(piece='spring')])[0]
        self.assertFalse(any(j['name'].endswith(' restraint') for j in old['joints']))
        new=[dict(piece='spring',mechanism_version=3,load='included load',yaw_deg=25,pitch_deg=15,roll_deg=0)]
        ghost=mg.ghost(free,new,0,nearby=True)
        self.assertEqual(len(ghost['spring_setup']),1)
        axis=ghost['alignment']['primary']['dir']
        self.assertEqual(ghost['alignment']['primary']['label'],'spring push face')
        expected=mw._mat_apply(mw.heading(25,15,0),[0,1,0])
        for actual,wanted in zip(axis,expected):self.assertAlmostEqual(actual,wanted,places=6)
        self.assertLess(axis[1],1)
        self.assertNotEqual(ghost['spring_setup'][0]['at_b_m'][2],0)
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
    def test_latched_spring_pushes_by_contact_and_requires_release_alignment_and_preload(self):
        level=mg.level_by_id('easy-spring');release=level['solution_releases']
        spec=mg.compose(level,level['solution'])[0]
        self.assertFalse(any(j.get('a')=='spring load' or j.get('b')=='spring load' for j in spec['joints']))
        with tempfile.TemporaryDirectory() as td:
            for label,placed,inputs,wins in [('held',level['solution'],None,0),('released',level['solution'],release,3),
                    ('weak',level['wrong'],release,0),('miss',[dict(level['solution'][0],x_m=1)],release,0)]:
                result=mg.trial(level,placed,ENGINE,Path(td),runs=3,release_inputs=inputs)
                self.assertEqual(result['worked'],wins,(label,result))
                self.assertFalse(any(r['error'] for r in result['results']))
        for material in ('oak','glass','iron'):
            samples=[]
            for dt in (1/240,1/480):
                audit=latched_spring_audit(material,dt);samples.append(audit)
                self.assertLessEqual(audit['final_j'],audit['initial_j']+.01)
                if material=='iron':self.assertLess(audit['load_y_m'],.405)
                else:self.assertGreater(audit['load_y_m'],.41)
                print('LATCHED CONTACT SPRING',json.dumps(audit))
            self.assertLess(abs(samples[0]['load_y_m']-samples[1]['load_y_m']),.005)
    @engine_test
    def test_contact_gears_compare_material_mass_and_native_power_receipts_at_two_steps(self):
        for material in ('glass','oak','iron'):
            # Oak's low inertia requires <= 0.00356 s in the native circuit
            # coupling guard. Compare two finer explicit steps for all materials.
            for dt in (1/480,1/960):
                with self.subTest(material=material,dt=dt):
                    audit=contact_gear_audit(material,dt)
                    for name,mass in audit['masses_kg'].items():
                        self.assertAlmostEqual(mass,audit['expected_masses_kg'][name],delta=1e-5)
                    self.assertLess(abs(audit['electrical_residual_j']),1e-6)
                    self.assertGreater(audit['shaft_j'],0)
                    self.assertGreater(audit['kinetic_about_axles_j'],0)
                    print('CONTACT GEAR AUDIT',json.dumps(audit))

    @engine_test
    def test_individual_gear_teeth_need_contact_size_and_real_power(self):
        lone=sm.gear('single',{},{} )
        self.assertEqual(len(lone['joints']),1)
        self.assertEqual(sum(p['shape']=='compound' for p in lone['parts']),1)
        self.assertNotIn('batteries',lone)
        self.assertNotIn('circuits',lone)
        level=mg.level_by_id('easy-gears')
        spec=mg.compose(level,level['solution'])[0]
        self.assertFalse(any(j['kind']=='gear' for j in spec['joints']))
        driven=measured(spec,2)
        angles={j['name']:j['turned_deg'] for j in driven['readouts']['joints']}
        self.assertGreater(angles['target gear axle'],180)
        # Actual tooth contact has backlash; this is a measured travel check,
        # not an imposed ideal ratio or an assertion of involute accuracy.
        self.assertAlmostEqual(angles['drive gear axle'],-angles['your gear 1 axle'],delta=8)
        self.assertAlmostEqual(angles['your gear 1 axle'],-2*angles['target gear axle'],delta=8)
        for label,placement in [('off plane',dict(level['solution'][0],z_m=.2)),
                                ('too small',dict(level['solution'][0],module_m=.016))]:
            with tempfile.TemporaryDirectory() as td,self.subTest(condition=label):
                outcome=mg.trial(level,[placement],ENGINE,Path(td),runs=3)
                self.assertEqual(outcome['worked'],0,outcome)
        crowded=mg.ghost(level,[dict(level['solution'][0],teeth=18)],0)
        self.assertFalse(crowded['fits'],'Larger teeth cannot occupy the existing wheels')
        for label in ('empty battery','broken wire'):
            off=copy.deepcopy(spec)
            if label=='empty battery':off['batteries'][0]['charge_j']=0
            else:off['electrical']['wires'].pop()
            with self.subTest(condition=label):
                stopped=measured(off,2)
                self.assertLess(abs(next(j for j in stopped['readouts']['joints'] if j['name']=='target gear axle')['turned_deg']),1)
        print('CONTACT GEARS',angles)

    @engine_test
    def test_free_gears_use_a_separate_motor_battery_and_saved_wires(self):
        free=mg.free_build()
        placements=[dict(piece='gear',x_m=0),dict(piece='gear',x_m=.45,teeth=24,phase_deg=7.5),
            dict(piece='battery',x_m=-.6,z_m=-.4),
            dict(piece='motor',hinge='your gear 1 axle',x_m=0,z_m=-.3),
            dict(piece='wire',a_terminal='your battery 3:plus',b_terminal='your motor 4:plus'),
            dict(piece='wire',a_terminal='your battery 3:minus',b_terminal='your motor 4:minus')]
        # The ordinary saved JSON contains independent pieces and terminal
        # links; no paired-piece metadata or generated ratio joint is required.
        saved=json.loads(json.dumps(placements))
        spec=mg.compose(free,saved)[0]
        self.assertFalse(any(j['kind']=='gear' for j in spec['joints']))
        run=measured(spec,2)
        hinges={j['name']:j['turned_deg'] for j in run['readouts']['joints']}
        self.assertGreater(abs(hinges['your gear 2 axle']),180)
        self.assertGreater(run['readouts']['electrical']['networks'][0]['ledger']['source_j'],0)

    @engine_test
    def test_spring_acts_on_the_waiting_load_and_compares_materials_at_two_steps(self):
        for material,density in [('oak',700),('glass',2500),('iron',7870)]:
            for dt in (1/240,1/480):
                level=mg._with_free_knobs(copy.deepcopy(sm.LEGACY_SPRING_STARTER))
                next(p for p in level['machine']['parts'] if p['name']=='spring load')['material']=material
                spec=mg.compose(level,level['solution'])[0]
                with tempfile.TemporaryDirectory() as td:
                    engine,_,_=mw.build_engine(ENGINE,mw.compile_spec(spec),td)
                    try:
                        body=next(b for b in engine.first['bodies'] if b['name']=='spring load')
                        mass=body['mass_kg'];self.assertAlmostEqual(mass,.12**3*density,delta=1e-6)
                        y=body['position_m'][1];speed=0
                        initial=mass*9.81*y+.5*200*(y-.78)**2
                        damping=impulse=0
                        for _ in range(round(.1/dt)):
                            damping+=6*speed*speed*dt;impulse+=(-mass*9.81-200*(y-.78)-6*speed)*dt
                            r=engine.op(op='step',dt=dt,n=1,moved=False)
                            body=next(b for b in r['bodies'] if b['name']=='spring load')
                            y,speed=body['position_m'][1],body['velocity_m_s'][1]
                        final=mass*9.81*y+.5*mass*speed**2+.5*200*(y-.78)**2
                        self.assertLessEqual(final,initial+.01,'The fixed cradle cannot supply unaccounted lifting energy')
                        if material=='iron':self.assertLess(y,.405,'The same preload cannot lift the heavy iron load')
                        else:self.assertGreater(y,.41)
                        print('WAITING SPRING',dict(material=material,dt=dt,mass_kg=mass,y_m=y,
                            initial_j=initial,final_j=final,damping_j=damping,
                            energy_correction_and_contact_j=final+damping-initial,
                            unaccounted_support_and_numerical_impulse_n_s=mass*speed-impulse))
                    finally:engine.close()
        level=mg.level_by_id('easy-spring')
        with tempfile.TemporaryDirectory() as td:
            off=[dict(level['solution'][0],x_m=1)]
            self.assertEqual(mg.trial(level,off,ENGINE,Path(td),runs=3,release_inputs=level.get('solution_releases'))['worked'],0)
            self.assertEqual(mg.trial(level,[dict(piece='spring')],ENGINE,Path(td),runs=3)['worked'],0)

    @engine_test
    def test_easy_solutions_win_nudged_and_physically_wrong_setups_fail(self):
        for original in sm.EASY_LEVELS:
            level = mg.level_by_id(original['id'])
            with tempfile.TemporaryDirectory() as logs, self.subTest(level=level['id']):
                hit = mg.trial(level, level['solution'], ENGINE, Path(logs), runs=3,release_inputs=level.get('solution_releases'))
                wrong = mg.trial(level, level['wrong'], ENGINE, Path(logs), runs=3,release_inputs=level.get('solution_releases'))
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
        driven = measured(assembled(sm.LEGACY_GEAR_TEMPLATE), 2)
        hinges = {j['name']: j for j in driven['readouts']['joints']}
        a = hinges['your gears 1 input axle']['turned_deg']
        b = hinges['your gears 1 output axle']['turned_deg']
        self.assertGreater(abs(a), 180)
        self.assertAlmostEqual(a, -2 * b, delta=2)
        circuit = driven['readouts']['circuits'][0]
        self.assertGreater(circuit['source_j'], 0)
        self.assertLess(abs(circuit['electrical_residual_j']), 1e-6)
        stopped = measured(assembled(sm.LEGACY_GEAR_TEMPLATE, {'drive': 'off'}), 1)
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
