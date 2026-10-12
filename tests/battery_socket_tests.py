"""Real two-contact battery holder, finite supply and removal regressions."""
import copy
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import machine_world as mw
import machine_game as mg
import sandbox_electrics as e
import sandbox_battery_socket as socket

ENGINE = Path(os.environ.get('BANJO_LIVE_ENGINE', ROOT / 'build/agent-integration/empty-native/banjo_live_world_run.exe'))
if '--engine' in sys.argv:
    i = sys.argv.index('--engine'); ENGINE = Path(sys.argv[i + 1]).resolve(); del sys.argv[i:i + 2]


def merge(spec, fragment):
    for key in ('parts', 'joints', 'batteries'):
        spec.setdefault(key, []).extend(copy.deepcopy(fragment.get(key, [])))
    for key, rows in fragment.get('electrical', {}).items():
        spec.setdefault('electrical', {}).setdefault(key, []).extend(copy.deepcopy(rows))


def fixture(**knobs):
    spec = e.empty('Physical battery holder')
    merge(spec, socket.holder())
    merge(spec, e.bulb('lamp', {'x_m': .6}, {}))
    e.link(spec, 'holder feed', 'battery holder:plus', 'lamp:plus')
    e.link(spec, 'holder return', 'lamp:minus', 'battery holder:minus')
    merge(spec, socket.battery('your battery 1', dict(x_m=-.5, **knobs),
                              {'tray': {'contact_holder': socket.holder_metadata()}}))
    spec['stations'] = [dict(title='Lamp stays lit', focus=['lamp bulb'], done_when={
        'load_power_w': dict(device='lamp', at_least_w=2, for_s=.5)})]
    return spec


@contextmanager
def opened(spec):
    compiled = mw.compile_spec(spec)
    with tempfile.TemporaryDirectory(prefix='banjo-battery-socket-') as logs:
        engine, joints, circuits = mw.build_engine(ENGINE, compiled, Path(logs))
        try: yield engine, compiled, Path(logs)
        finally: engine.close()


def advance(engine, seconds=2, dt=1/240):
    reply = None
    for _ in range(round(seconds/dt)):
        reply = engine.op(op='step', dt=dt, n=1, moved=False)
        if reply.get('stepped_back'):
            raise AssertionError('battery fixture unexpectedly entered a fracture trial')
    return reply


def electrical(engine):
    circuit = engine.op(op='circuits')['circuits'][0]
    lamp = next(b for b in circuit['branches'] if b['id'] == 'lamp')
    contacts = [b for b in circuit['branches'] if 'follows_contact' in b]
    return circuit, lamp, contacts


def physical_state(engine):
    poses = engine.op(op='poses')['bodies']
    saved = {p['name']: p for p in engine.op(op='snapshot')['snapshot']['bodies']}
    for p in poses:
        row = saved[p['name']]
        p.update(position_m=row['pose']['com_m'], velocity_m_s=row['pose']['v_m_s'],
                 orientation_wxyz=row['pose']['q_wxyz'], spin_rad_s=row['pose']['w_rad_s'],
                 awake=row['awake'])
    return poses


def pack_energy(bodies, initial, spec):
    sizes = {p['name']: p['size_m'] for p in spec['parts']}
    start = {p['name']: p for p in initial}
    energy = 0
    for p in bodies:
        if not p['name'].startswith('your battery 1'): continue
        mass = p['mass_kg']; v = p['velocity_m_s']; w = p['spin_rad_s']
        # Native poses report world angular velocity; this fixture settles
        # with axis-aligned boxes. Rotate omega into its actual box frame.
        q = p['orientation_wxyz']; qw, qx, qy, qz = q
        # Conjugate quaternion applied to the world angular velocity.
        u = [-qx, -qy, -qz]
        cross = lambda a,b: [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
        t = [2*x for x in cross(u,w)]; c = cross(u,t)
        local = [w[i]+qw*t[i]+c[i] for i in range(3)]
        d = sizes[p['name']]
        inertia = [mass*(d[(i+1)%3]**2+d[(i+2)%3]**2)/12 for i in range(3)]
        energy += .5*mass*sum(x*x for x in v)+.5*sum(inertia[i]*local[i]**2 for i in range(3))
        energy += mass*9.81*(p['position_m'][1]-start[p['name']]['position_m'][1])
    return energy


class BatterySocket(unittest.TestCase):
    def setUp(self):
        if not ENGINE.is_file():
            if os.environ.get('BANJO_MACHINE_ENGINE') == 'required': self.fail('native engine required')
            self.skipTest('native engine unavailable')

    def test_pack_has_separate_insulated_terminals_and_four_real_paths(self):
        spec = fixture(); compiled = mw.compile_spec(spec)
        pack = [p for p in compiled['parts'] if p['name'].startswith('your battery 1')]
        self.assertEqual(len(pack), 5)
        self.assertTrue(all(not p['fixed'] for p in pack))
        self.assertEqual(len(compiled['joints']), 4)
        contacts = compiled['electrical']['contacts']
        self.assertEqual(len(contacts), 4)
        self.assertEqual({tuple(c['touch']) for c in contacts}, {
            ('your battery 1 '+cap+' cap', 'battery holder '+pad+' pad')
            for cap in ('plus','minus') for pad in ('plus','minus')})
        self.assertFalse(any('socket' in w['name'] for w in compiled['electrical']['wires']))
        self.assertEqual(len(socket.battery('pack', {}, {})['electrical']['contacts']), 0)
        self.assertEqual(json.loads(json.dumps(spec)), spec)

    def test_correct_drop_wins_three_nudged_native_runs(self):
        with tempfile.TemporaryDirectory() as logs:
            for material in ('glass','oak','iron'):
                compiled = mw.compile_spec(fixture(housing_material=material))
                for seed in range(3):
                    result = mw.rehearse(mg.nudged(compiled, seed) if seed else compiled, ENGINE, Path(logs), seconds=2)
                    self.assertIsNone(result['error'], result)
                    self.assertTrue(result['stations'][0]['done'], result)
                    self.assertLessEqual(result['stations'][0]['at_s'], 2)
                    print('SOCKET NUDGE', material, seed, result['stations'][0]['at_s'])

    def test_both_one_neither_contacts_and_empty_supply(self):
        for label, knobs, expected_contacts, powered in [
            ('both', {}, 2, True), ('one metal pad', {'insulated_pad':True}, 1, False),
            ('misaligned pack', {'x_offset':.16}, 0, False),
            ('crosswise pack', {'yaw_deg':90}, 0, False),
            ('off holder', {'z_m':.5}, 0, False), ('empty', {'charge_percent':0}, 2, False)]:
            spec=fixture(**{k:v for k,v in knobs.items() if k not in ('x_offset','insulated_pad')})
            if knobs.get('insulated_pad'):
                pad=next(p for p in spec['parts'] if p['name']=='battery holder minus pad')
                spec['parts'].append(dict(copy.deepcopy(pad),name='insulating seat',material='glass'))
                pad['at_m'][2]=.4
                device=next(d for d in spec['electrical']['devices'] if d['kind']=='socket')
                device['terminals']['minus'][2]=.4
            if 'x_offset' in knobs:
                for p in spec['parts']:
                    if p['name'].startswith('your battery 1'): p['at_m'][0]+=knobs['x_offset']
                for j in spec['joints']: j['at_m'][0]+=knobs['x_offset']
            with self.subTest(label=label), opened(spec) as (engine, _, _):
                advance(engine); circuit, lamp, contacts=electrical(engine)
                self.assertEqual(sum(c['closed'] for c in contacts), expected_contacts)
                self.assertGreater(lamp['power_w'], 2) if powered else self.assertLess(abs(lamp['power_w']), 1e-8)
                print('SOCKET CONTROL', label, lamp['power_w'], [(c['id'],c['closed']) for c in contacts])

    def test_housing_brushing_holder_and_missing_cap_cannot_power(self):
        for label in ('housing brush', 'missing cap'):
            spec=fixture()
            if label=='missing cap':
                # Missing metal cannot be declared as a conductive endpoint.
                spec['parts']=[p for p in spec['parts'] if p['name']!='your battery 1 minus cap']
                with self.assertRaises(mw.MachineRefused): mw.compile_spec(spec)
                continue
            # Turn the whole pack upside down. Its iron housing then stands
            # on both pads while its insulated caps point safely upward.
            for p in spec['parts']:
                if p['name'].startswith('your battery 1'):
                    p['at_m'][1]=.8-p['at_m'][1]
                    p['at_m'][2]=-p['at_m'][2]
                    p['turn_deg']=[180,0,0]
            for j in spec['joints']:
                j['at_m'][1]=.8-j['at_m'][1]; j['axis']=[0,-1,0]
            with opened(spec) as (engine, _, _):
                advance(engine)
                _,lamp,contacts=electrical(engine)
                self.assertLess(abs(lamp['power_w']),1e-8)
                self.assertFalse(any(c['closed'] for c in contacts))
                housing=next(p for p in physical_state(engine) if p['name']=='your battery 1 housing')
                self.assertAlmostEqual(housing['position_m'][1]-.04,.12,delta=.001)

    def test_reversed_pack_uses_crossed_contacts_and_still_lights_resistive_bulb(self):
        spec=fixture(yaw_deg=180)
        with opened(spec) as (engine,_,_):
            advance(engine); _,lamp,contacts=electrical(engine)
            self.assertGreater(lamp['power_w'],2)
            self.assertLess(lamp['current_a'],0)
            closed=[c for c in contacts if c['closed']]
            self.assertEqual(len(closed),2)
            self.assertTrue(all(('plus cap' in c['follows_contact']['a']) != ('plus pad' in c['follows_contact']['b']) for c in closed))

    def test_real_upward_pull_removes_pack_and_opens_both_contacts(self):
        with opened(fixture()) as (engine,_,_):
            advance(engine); _,lamp,_=electrical(engine)
            self.assertGreater(lamp['power_w'],2)
            housing=next(b for b in engine.op(op='poses')['bodies'] if b['name']=='your battery 1 housing')
            engine.op(op='pull',body=housing['name'],at=housing['position_m'],force=[0,200,0])
            advance(engine,.5); _,lamp,contacts=electrical(engine)
            self.assertLess(abs(lamp['power_w']),1e-8)
            self.assertFalse(any(c['closed'] for c in contacts))
            receipt=engine.op(op='pulls')['pulls'][0]
            self.assertGreater(receipt['work_j'],0)
            print('SOCKET PULL',json.dumps(receipt))

    def test_a_cap_detached_and_removed_opens_the_live_loop(self):
        with opened(fixture()) as (engine,_,_):
            advance(engine)
            self.assertGreater(electrical(engine)[1]['power_w'],2)
            fixing=next(j for j in engine.op(op='joints')['joints'] if j['b']=='your battery 1 minus cap')
            engine.op(op='unhinge',joint=fixing['id'])
            engine.op(op='park',name='your battery 1 minus cap')
            advance(engine,.2)
            _,lamp,contacts=electrical(engine)
            self.assertLess(abs(lamp['power_w']),1e-8)
            self.assertFalse(any(c['closed'] for c in contacts if c['follows_contact']['a']=='your battery 1 minus cap'))

    def test_sleeping_contacts_and_native_snapshot_continue_with_same_charge(self):
        with opened(fixture()) as (engine,compiled,logs):
            advance(engine,4); before,lamp,contacts=electrical(engine)
            self.assertGreater(lamp['power_w'],2)
            poses=physical_state(engine)
            self.assertTrue(all(not p['awake'] for p in poses if p['name'].startswith('your battery 1')))
            snapshot=engine.op(op='snapshot')['snapshot']
            scene_path=logs/'restore-scene.json'; scene_path.write_text(json.dumps(mw.scene_of(compiled)))
            saved_path=logs/'restore-world.json'; saved_path.write_text(json.dumps(snapshot))
            commands='\n'.join(json.dumps(c) for c in [dict(op='step',dt=1/240,n=24),dict(op='circuits'),dict(op='quit')])+'\n'
            result=subprocess.run([str(ENGINE),'--scene',str(scene_path),'--snapshot',str(saved_path)],
                input=commands,text=True,capture_output=True,timeout=30,check=True)
            replies=[json.loads(s) for s in result.stdout.splitlines()]
            self.assertTrue(all(r.get('ok') for r in replies), replies)
            circuit=next(r['circuits'][0] for r in replies if 'circuits' in r)
            self.assertGreater(circuit['ledger']['source_j'],before['ledger']['source_j'])
            self.assertEqual(sum(c['closed'] for c in circuit['branches'] if 'follows_contact' in c),2)

    def test_material_mass_timestep_and_separate_electrical_mechanical_receipts(self):
        for material,density in [('glass',2500),('oak',700),('iron',7870)]:
            measurements=[]
            for dt in (1/240,1/480):
                spec=fixture(housing_material=material)
                with self.subTest(material=material,dt=dt),opened(spec) as (engine,compiled,_):
                    initial=physical_state(engine); advance(engine,2,dt)
                    circuit,lamp,contacts=electrical(engine)
                    poses=physical_state(engine); pack=[p for p in poses if p['name'].startswith('your battery 1')]
                    mass=sum(p['mass_kg'] for p in pack)
                    expected=math.prod(socket.HOUSING_SIZE)*density+2*math.prod(socket.SPACER_SIZE)*2500+2*math.prod(socket.CAP_SIZE)*7870
                    self.assertAlmostEqual(mass,expected,places=6)
                    self.assertGreater(lamp['power_w'],2)
                    ledger=circuit['ledger']; store=engine.op(op='overloaded')['machines']['stores'][0]
                    self.assertAlmostEqual(store['given_j'],ledger['source_j'],delta=1e-8)
                    self.assertAlmostEqual(store['charge_j']+store['given_j'],1000,delta=1e-8)
                    self.assertLess(abs(ledger['electrical_residual_j']),1e-8)
                    self.assertLess(abs(ledger['thermal_residual_j']),1e-6)
                    self.assertAlmostEqual(ledger['source_j'],ledger['heat_j']+ledger['emitted_j']+ledger['exported_j'],delta=1e-8)
                    delta=pack_energy(poses,initial,spec)
                    # The drop loses mechanical energy in ordinary contacts.
                    # No closed global contact/constraint ledger is exposed.
                    self.assertLess(delta,0)
                    measurement=dict(material=material,dt_s=dt,mass_kg=mass,power_w=lamp['power_w'],
                        rigid_delta_ke_pe_j=delta,ledger=ledger,store=store)
                    measurements.append(measurement); print('SOCKET AUDIT',json.dumps(measurement))
            self.assertAlmostEqual(measurements[0]['power_w'],measurements[1]['power_w'],delta=.005)


if __name__=='__main__': unittest.main()
