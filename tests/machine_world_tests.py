"""The machine world: declaration checks, kits, the live engine run and the
chat's refusal and rehearsal loops (with a stand-in model).

    python tests/machine_world_tests.py [--engine path/to/banjo_live_world_run]

Without an engine the declaration and chat tests still run; the engine tests
are skipped, never passed. Set BANJO_MACHINE_ENGINE=required to fail instead.
"""
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
import machine_world as mw  # noqa: E402
import machine_chat as mc   # noqa: E402

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


def engine_turn(v, degrees):
    """A body's turn as the engine makes it (TileImpactScene
    rotationQuaternion, R = Rx Ry Rz: about the world's z first), written out
    again independently: v turned about z, then y, then x."""
    x, y, z = v
    a = [math.radians(d) for d in degrees]
    x, y = x * math.cos(a[2]) - y * math.sin(a[2]), x * math.sin(a[2]) + y * math.cos(a[2])
    x, z = x * math.cos(a[1]) + z * math.sin(a[1]), -x * math.sin(a[1]) + z * math.cos(a[1])
    y, z = y * math.cos(a[0]) - z * math.sin(a[0]), y * math.sin(a[0]) + z * math.cos(a[0])
    return [x, y, z]


def quaternion_turn(q, v):
    """v turned by the unit quaternion q = [w, x, y, z]."""
    w, qv = q[0], q[1:]
    t = [2 * (qv[1] * v[2] - qv[2] * v[1]), 2 * (qv[2] * v[0] - qv[0] * v[2]), 2 * (qv[0] * v[1] - qv[1] * v[0])]
    c = [qv[1] * t[2] - qv[2] * t[1], qv[2] * t[0] - qv[0] * t[2], qv[0] * t[1] - qv[1] * t[0]]
    return [v[i] + w * t[i] + c[i] for i in range(3)]


def part(name, size, at, **kw):
    return dict({'name': name, 'shape': 'box', 'material': 'oak', 'size_m': size, 'at_m': at}, **kw)


class Declaration(unittest.TestCase):
    def test_default_machine_compiles_from_general_parts(self):
        c = mw.compile_spec(mw.default_spec())
        names = {p['name'] for p in c['parts']}
        for n in ('water wheel', 'water wheel spout', 'ramp gate', 'marble', 'domino 1', 'domino 8', 'lever',
                  'lever pivot', 'weight', 'weight rope', 'weight arm', 'glass plate'):
            self.assertIn(n, names)
        self.assertEqual({j['kind'] for j in c['joints']}, {'hinge', 'fix', 'slide', 'drum'})
        self.assertEqual(c['circuits'][0]['switch'], {'hinge': 'lever hinge', 'closed_at_or_above_deg': 8.0})
        self.assertEqual(c['ground']['kind'], 'flume')
        self.assertLess(c['cells'], mw.MAX_CELLS)
        for p in c['parts']:
            if p['shape'] == 'compound':
                continue   # exact bodies, not built from cells
            for s in p['size_m']:
                self.assertAlmostEqual(s / c['cell_m'], round(s / c['cell_m']), places=6, msg=p['name'])
            self.assertGreaterEqual(mw.lowest_point(p), -1e-9, p['name'])
        wheel = next(p for p in c['parts'] if p['name'] == 'water wheel')
        bed = mw.ground_height(c['ground'], wheel['at_m'][0], wheel['at_m'][2])
        self.assertAlmostEqual(wheel['at_m'][1], bed + 0.065 + 0.4, places=9)
        rope = next(j for j in c['joints'] if j['kind'] == 'drum')
        gate = next(p for p in c['parts'] if p['name'] == 'ramp gate')
        self.assertAlmostEqual(rope['load_point_m'][2], gate['at_m'][2] - 0.25, places=3,
                               msg='the rope is tied to the gate end that moves toward the drum')

    def test_the_flume_ground_is_checked_like_any_other_part(self):
        flume = {'kind': 'flume', 'trench_z_m': 1.0, 'trench_width_m': 0.5, 'trench_depth_m': 0.35}
        ground = mw.compile_ground(flume, [])
        self.assertEqual(mw.ground_height(ground, 0.0, 0.0), 0.0)
        self.assertAlmostEqual(mw.ground_height(ground, 0.0, 1.0), -0.35 - 0.005 * (0.0 - ground['x0_m']), places=12)
        base = {'schema': mw.SCHEMA, 'ground': flume}
        cases = [
            ({'ground': dict(flume, trench_z_m=2.9)}, 'inside the ground'),
            ({'ground': dict(flume, kind='lake')}, 'flume'),
            ({'parts': [part('a', [.1, .1, .1], [0, -0.1, 1.0])]}, None),     # down in the trench: allowed
            ({'parts': [part('a', [.1, .1, .6], [0, -0.1, 0.8])]}, 'into the ground'),   # across the bank
            ({'parts': [part('a', [.1, .1, .1], [6, .05, 0])]}, 'off the edge of the ground'),
            ({'kits': [{'kit': 'water_wheel', 'name': 'w', 'at_m': [0, 0, 1]}], 'ground': None}, 'flume'),
            ({'kits': [{'kit': 'water_wheel', 'name': 'w', 'at_m': [0, 0, 1], 'paddle_width_m': 0.45}]}, 'at most'),
        ]
        for extra, words in cases:
            with self.subTest(words=words, extra=extra):
                spec = dict(base, **extra)
                if words is None:
                    mw.compile_spec(spec)
                    continue
                with self.assertRaises(mw.MachineRefused) as refused:
                    mw.compile_spec(spec)
                self.assertTrue(any(words in q for q in refused.exception.problems), refused.exception.problems)

    def test_poured_water_is_declared_over_the_ground_it_lands_on(self):
        flume = {'kind': 'flume', 'trench_z_m': 1.0, 'trench_width_m': 0.5, 'trench_depth_m': 0.35}
        c = mw.compile_spec({'schema': mw.SCHEMA, 'ground': flume, 'kits': [
            {'kit': 'water_wheel', 'name': 'w', 'at_m': [0, 0, 1], 'pour': {'side': '+x', 'discharge_l_s': 3}}]})
        spout = c['spouts'][0]
        wheel = next(q for q in c['parts'] if q['name'] == 'w')
        self.assertEqual(spout['name'], 'w spout')
        self.assertAlmostEqual(spout['at_m'][0], 0.2, places=9)        # half the radius, on the +x side
        self.assertAlmostEqual(spout['at_m'][1], wheel['at_m'][1] + 0.4 + 0.5, places=9)
        self.assertIn('w spout', {q['name'] for q in c['parts']})      # the pipe it pours from
        scene = mw.scene_of(c)
        self.assertEqual(scene['spouts'][0]['discharge_m3_s'], 0.003)
        base = {'schema': mw.SCHEMA, 'ground': flume}
        cases = [
            ({'ground': None, 'spouts': [{'name': 's', 'at_m': [0, 1, 1]}]}, 'to land in'),
            ({'spouts': [{'name': 's', 'at_m': [9, 1, 1]}]}, 'off the edge of the ground'),
            ({'spouts': [{'name': 's', 'at_m': [0, -0.1, 0]}]}, 'at or below the ground'),
            ({'spouts': [{'name': 's', 'at_m': [0, 1, 1], 'direction': [0, 0, 0]}]}, 'point somewhere'),
            ({'spouts': [{'name': 's', 'at_m': [0, 1, 1], 'discharge_l_s': 50}]}, 'discharge_l_s'),
            ({'kits': [{'kit': 'water_wheel', 'name': 'w', 'at_m': [0, 0, 1], 'pour': {'side': 'up'}}]}, 'pour side'),
        ]
        for extra, words in cases:
            with self.subTest(words=words):
                with self.assertRaises(mw.MachineRefused) as refused:
                    mw.compile_spec(dict(base, **extra))
                self.assertTrue(any(words in q for q in refused.exception.problems), refused.exception.problems)

    def test_compound_parts_become_exact_bodies_in_the_scene(self):
        c = mw.compile_spec({'schema': mw.SCHEMA, 'ground': {'kind': 'flume'},
                             'kits': [{'kit': 'water_wheel', 'name': 'w', 'at_m': [0, 0, 1], 'paddles': 6}]})
        scene = mw.scene_of(c)
        self.assertEqual([b['name'] for b in scene['precise_rigid_bodies']], ['w'])
        self.assertEqual(len(scene['precise_rigid_bodies'][0]['parts']), 2 + 6)
        self.assertNotIn('w', [b['name'] for b in scene['bodies']])
        self.assertEqual(scene['terrain']['generate']['kind'], 'flume')
        q = mw.quaternion_of_turn([0, 0, 90])
        self.assertAlmostEqual(q[0], math.cos(math.pi / 4), places=12)
        self.assertAlmostEqual(q[3], math.sin(math.pi / 4), places=12)

    def test_rotation_matches_the_engine(self):
        # The matrix the checks use, the quaternion the scene is built with
        # (which the engine reports back as the body's orientation:
        # test_a_two_axis_turn_is_the_one_the_engine_reports), and the turn
        # written out by hand all agree.
        for degrees in ([30, 0, 45], [20, 35, -50], [-60, 25, 10], [0, 90, 0], [0, 0, -20]):
            r = mw.rotation(degrees)
            q = mw.quaternion_of_turn(degrees)
            for v in ([1, 0, 0], [0, 1, 0], [0.3, -0.2, 0.9]):
                mine = [sum(r[i][j] * v[j] for j in range(3)) for i in range(3)]
                for a, b, c in zip(mine, engine_turn(v, degrees), quaternion_turn(q, v)):
                    self.assertAlmostEqual(a, b, places=12)
                    self.assertAlmostEqual(a, c, places=12)

    def test_refuses_what_cannot_be_built_honestly(self):
        base = {'schema': mw.SCHEMA, 'cell_m': 0.02}
        cases = [
            ({'parts': [part('a', [.1, .1, .1], [0, .02, 0])]}, 'into the ground'),
            ({'parts': [part('a', [.1, .1, .1], [0, .05, 0]), part('b', [.1, .1, .1], [.05, .05, 0])]}, 'overlap'),
            ({'parts': [part('a', [.1, .1, .1], [0, .05, 0], material='unobtainium')]}, 'material'),
            ({'parts': [part('a', [.1, .1, .1], [0, .05, 0])],
              'joints': [{'kind': 'hinge', 'a': 'a', 'b': 'ghost', 'at_m': [0, .1, 0]}]}, 'ghost'),
            ({'parts': [part('a', [.1, .1, .1], [0, .05, 0])], 'batteries': [{'name': 'b', 'in': 'a'}],
              'circuits': [{'name': 'c', 'battery': 'b', 'switch': {'hinge': 'none', 'closed_at_or_above_deg': 5},
                            'coil': {'heats': 'a', 'resistance_ohm': 1}}]}, 'hinge joint'),
            ({'parts': [part('a', [.01, .1, .1], [0, .05, 0])]}, 'at least one cell'),
            ({'kits': [{'kit': 'pendulum', 'name': 'p', 'pivot_m': [0, .5, 0], 'rope_m': .6}]}, 'hit the ground'),
            ({'kits': [{'kit': 'ramp', 'name': 'r', 'top_m': [0, .5, 0], 'bottom_m': [1, .2, .5]}]}, 'along x or z'),
            ({'parts': [part(f'p{i}', [.04, .04, .04], [i * .1, .02, 0]) for i in range(mw.MAX_PARTS + 1)]}, 'at most'),
        ]
        for extra, words in cases:
            with self.subTest(words=words):
                with self.assertRaises(mw.MachineRefused) as refused:
                    mw.compile_spec(dict(base, **extra))
                self.assertTrue(any(words in p for p in refused.exception.problems), refused.exception.problems)

    def test_two_fixed_parts_may_meet_and_snapped_sizes_are_said(self):
        spec = {'schema': mw.SCHEMA, 'cell_m': 0.02, 'parts': [
            part('a', [.5, .1, .1], [0, .05, 0], fixed=True), part('b', [.1, .5, .1], [0, .25, 0], fixed=True),
            part('c', [.105, .1, .1], [1, .05, 0])]}
        c = mw.compile_spec(spec)
        snapped = next(p for p in c['parts'] if p['name'] == 'c')
        self.assertAlmostEqual(snapped['size_m'][0], .1, places=9)
        self.assertTrue(any(n.startswith('c: sized to whole 20 mm cells') for n in c['notes']))

    def test_kits_lay_out_what_they_say(self):
        c = mw.compile_spec({'schema': mw.SCHEMA, 'kits': [
            {'kit': 'domino_row', 'name': 'd', 'start_m': [0, 0, 1], 'direction': '-z', 'count': 3, 'spacing_m': .2},
            {'kit': 'block_tower', 'name': 't', 'at_m': [2, 0, 0], 'count': 3, 'size_m': [.1, .1, .1], 'gap_m': .002},
            {'kit': 'pendulum', 'name': 'p', 'pivot_m': [-2, 1, 0], 'rope_m': .6, 'pull_back_deg': 30,
             'swing_toward': '+x'}]})
        by = {p['name']: p for p in c['parts']}
        self.assertEqual([round(by[f'd {i}']['at_m'][2], 9) for i in (1, 2, 3)], [1.0, .8, .6])
        self.assertEqual([round(by[f't {i}']['at_m'][1], 9) for i in (1, 2, 3)], [.05, .152, .254])
        ball = by['p ball']['at_m']
        self.assertAlmostEqual(math.dist(ball, [-2, 1, 0]), .6, places=9)
        self.assertLess(ball[0], -2)   # pulled back against its swing
        rope = next(j for j in c['joints'] if j['name'] == 'p rope')
        self.assertEqual((rope['kind'], rope['a'], rope['b'], rope['length_m']), ('tie', 'p beam', 'p ball', .6))


class Engine(unittest.TestCase):
    @need_engine
    def test_a_two_axis_turn_is_the_one_the_engine_reports(self):
        """The turn the declaration's checks use is the engine's own: a plank
        turned about two axes faces where the engine says it does."""
        turn = [30, 0, 45]
        spec = {'schema': mw.SCHEMA, 'parts': [part('plank', [0.4, 0.02, 0.2], [0, 1, 0], turn_deg=turn, fixed=True)]}
        with tempfile.TemporaryDirectory() as logs:
            session = mw.MachineSession(mw.compile_spec(spec), ENGINE, Path(logs), paced=False)
            try:
                q = session.bodies['plank']['orientation_wxyz']
            finally:
                session.close()
        r = mw.rotation(turn)
        for v in ([1, 0, 0], [0, 1, 0], [0, 0, 1]):
            mine = [sum(r[i][j] * v[j] for j in range(3)) for i in range(3)]
            for a, b in zip(mine, quaternion_turn(q, v)):
                self.assertAlmostEqual(a, b, places=4)   # the engine's reply is rounded to 1e-5


    @need_engine
    def test_default_machine_runs_every_built_station_in_order_and_hands_heat_over_exactly(self):
        with tempfile.TemporaryDirectory() as logs:
            compiled = mw.compile_spec(mw.default_spec())
            r = mw.rehearse(compiled, ENGINE, Path(logs), seconds=40, wall_limit_s=200)
            self.assertIsNone(r['error'])
            built = [(s, row) for s, row in zip(compiled['stations'], r['stations']) if s.get('done_when')]
            self.assertTrue(all(row['done'] for _, row in built), r['stations'])
            times = [row['at_s'] for _, row in built]
            self.assertEqual(times, sorted(times), 'stations happened out of order')
            texts = ' | '.join(e['text'] for e in r['events'])
            self.assertIn('marble hits domino 1', texts)
            self.assertIn('glass plate broke into', texts)

    @need_engine
    def test_an_aimed_pendulum_is_placed_not_scripted_and_the_engine_finds_the_hit(self):
        spec = {'schema': mw.SCHEMA, 'kits': [
            {'kit': 'block_tower', 'name': 'tower', 'at_m': [1, 0, 2], 'count': 3, 'size_m': [.1, .1, .1]},
            {'kit': 'pendulum', 'name': 'p', 'aim_at': 'tower 2', 'rope_m': .7, 'pull_back_deg': 50, 'swing_toward': '-z',
             'ball': {'material': 'iron', 'diameter_m': .12}}],
            'stations': [{'title': 'Swing', 'done_when': {'hits': ['p ball', 'tower 2']}, 'focus': ['p ball']}]}
        compiled = mw.compile_spec(spec)
        ball = next(p for p in compiled['parts'] if p['name'] == 'p ball')
        self.assertGreater(ball['at_m'][2], 2.0)   # pulled back on the far side, swinging toward -z
        self.assertEqual(ball['velocity_m_s'], [0.0, 0.0, 0.0])
        with tempfile.TemporaryDirectory() as logs:
            r = mw.rehearse(compiled, ENGINE, Path(logs), seconds=3)
        self.assertTrue(r['stations'][0]['done'], r['events'])
        self.assertEqual(r['closest_approach'], [])

    @need_engine
    def test_live_session_streams_only_changes_and_measures_the_circuit(self):
        with tempfile.TemporaryDirectory() as logs:
            host = mw.MachineHost(ENGINE, logs)
            try:
                opened = host.open(mw.default_spec())
                self.assertTrue(opened['full'])
                self.assertEqual(len(opened['bodies']), len(opened['machine']['parts']))
                session = host.get(opened['session'])
                session.play(True, 4.0)
                deadline = time.time() + 60
                seq = opened['seq']
                while time.time() < deadline:
                    frame = session.frame(seq, 250)
                    self.assertLessEqual(len(frame['bodies']), len(session.bodies))
                    seq = frame['seq']
                    circuits = frame['readouts'].get('circuits') or []
                    if circuits and circuits[0]['closed'] and frame['t'] > 4:
                        break
                circuit = frame['readouts']['circuits'][0]
                self.assertTrue(circuit['closed'])
                self.assertAlmostEqual(circuit['current_a'], 48 / (0.05 + 0.001 + 0.8), places=3)
                self.assertAlmostEqual(frame['readouts']['heat_ledger']['heater_in_j'], circuit['into_body_j'],
                                       delta=1e-6 * max(1.0, circuit['into_body_j']) + 0.02)
                self.assertLess(abs(circuit['electrical_residual_j']), 1e-6)
                # The pour: every parcel the engine carries, where it is, and a
                # ledger that closes (poured = landed + ran off + in the air).
                pour = frame['readouts']['pour']
                self.assertGreater(pour['poured_l'], 5.0)
                self.assertGreater(pour['landed_l'], 0.5 * pour['poured_l'])
                self.assertLess(abs(pour['residual_m3']), 1e-12)
                xyz = frame['parcels']['xyz_mm']
                self.assertEqual(len(xyz) % 3, 0)
                self.assertEqual(len(xyz) // 3, pour['parcels'])
                # Over the flume's ground (x within 4.95 m, z within 2.95 m),
                # no higher than the spout's mouth and no lower than the bed:
                # water splashes off the paddles onto the banks as well.
                for k in range(0, len(xyz), 3):
                    self.assertTrue(-4950 <= xyz[k] <= 4950 and -600 <= xyz[k + 1] <= 1100 and -2950 <= xyz[k + 2] <= 2950,
                                    xyz[k:k + 3])
                quiet = session.frame(session.seq, 0)
                self.assertEqual(quiet['bodies'], [])
                self.assertTrue(host.close(opened['session'])['closed'])
                with self.assertRaises(LookupError):
                    host.get(opened['session'])
            finally:
                host.close_all()


# ---- light (docs/optics-checkpoint.md) ---------------------------------------------

def lens_machine(lens=True):
    """A glass ball rolls along two rails to a stop; there the overhead sun,
    focused through it, lands on a light sensor 4 mm across under the rails.
    The sensor's switch closes a coil on a rope, which burns, and a weight
    falls. Without the ball the open sun on the sensor (0.05 W) is a sixth of
    what closes the switch."""
    tilt, rail_top, x_rest, x0 = -1.5, 0.30, 0.30, -0.30
    t = math.tan(math.radians(tilt))
    lift = math.sqrt(0.05 ** 2 - 0.02 ** 2)           # a 100 mm ball on rails 40 mm apart
    centre_rest = rail_top + x_rest * t + lift
    focus = centre_rest - 0.0675                       # its focus, 17.5 mm beyond its far side
    parts = [
        part('rail north', [0.8, 0.02, 0.02], [0.0, rail_top - 0.01, -0.03], turn_deg=[0, 0, tilt], fixed=True),
        part('rail south', [0.8, 0.02, 0.02], [0.0, rail_top - 0.01, 0.03], turn_deg=[0, 0, tilt], fixed=True),
        part('stop', [0.04, 0.06, 0.12], [x_rest + 0.07, centre_rest, 0.0], fixed=True),
        part('sensor plate', [0.12, 0.02, 0.12], [x_rest, focus - 0.01, 0.0], material='concrete', fixed=True),
        part('battery box', [0.2, 0.1, 0.2], [0.6, 0.05, 0.6], material='concrete', fixed=True)]
    if lens:
        parts.append({'name': 'lens', 'shape': 'sphere', 'material': 'glass', 'size_m': [0.1, 0.1, 0.1],
                      'at_m': [x0, rail_top + x0 * t + lift + 0.001, 0.0], 'velocity_m_s': [0.25, 0, 0]})
    return {
        'schema': mw.SCHEMA, 'title': 'A burning glass', 'cell_m': 0.02,
        'sun': {'elevation_deg': 90, 'azimuth_deg': 180, 'irradiance_w_m2': 1000},
        'parts': parts,
        'kits': [{'kit': 'hanging_weight', 'name': 'weight', 'post_m': [1.2, 0, 0], 'drop_m': 0.5, 'peg_size_m': 0.02,
                  'peg_length_m': 0.3, 'weight_size_m': 0.16, 'weight_material': 'iron', 'side': '+z',
                  'holds_shear_n': 800, 'hang': 'rope', 'rope_m': 0.3}],
        'batteries': [{'name': 'battery', 'in': 'battery box', 'capacity_j': 200000, 'voltage_v': 48,
                       'max_power_w': 3000}],
        'light': {'sunlight': {'through': [{'center_m': [x_rest, centre_rest - 0.03, 0.0], 'size_m': [0.14, 0.14, 0.14]}],
                               'spacing_m': 0.003},
                  'photocells': [{'name': 'eye', 'on': 'sensor plate', 'at_m': [x_rest, focus, 0.0], 'normal': [0, 1, 0],
                                  'area_m2': math.pi * 0.004 ** 2}]},
        'circuits': [{'name': 'heater', 'battery': 'battery', 'switch': {'photocell': 'eye', 'closed_at_or_above_w': 0.3},
                      'coil': {'heats': 'weight rope', 'resistance_ohm': 0.8}}],
        'stations': [
            {'title': 'Sunlight through the glass ball lights the sensor', 'done_when': {'lit_w': {'photocell': 'eye', 'w': 0.3}},
             'focus': ['sensor plate']},
            {'title': 'The switch closes', 'done_when': {'switch_closed': 'heater'}, 'focus': ['battery box']},
            {'title': 'The coil burns the rope', 'done_when': {'parted': 'weight rope'}, 'focus': ['weight rope']},
            {'title': 'The weight falls', 'done_when': {'hits': ['weight', 'the ground']}, 'focus': ['weight']}]}


class Light(unittest.TestCase):
    def test_light_is_declared_and_what_cannot_be_built_is_refused(self):
        c = mw.compile_spec(lens_machine())
        self.assertEqual(c['light']['sun']['irradiance_w_m2'], 1000.0)
        self.assertEqual([p['name'] for p in c['light']['photocells']], ['eye'])
        self.assertEqual(c['circuits'][0]['switch'], {'photocell': 'eye', 'closed_at_or_above_w': 0.3})
        self.assertIsNone(mw.compile_spec(mw.default_spec())['light'], 'a machine with no light has none')

        def refused(change, words):
            spec = lens_machine()
            change(spec)
            with self.assertRaises(mw.MachineRefused) as caught:
                mw.compile_spec(spec)
            self.assertIn(words, str(caught.exception))
        refused(lambda s: s.pop('sun'), 'sunlight needs a sun')
        refused(lambda s: s['light'].update(mirrors=['stop']), 'only a metal')
        refused(lambda s: s['circuits'][0]['switch'].update(photocell='nobody'), 'switch.photocell must name a photocell')
        refused(lambda s: s['light']['sunlight'].update(spacing_m=0.002, through=[{'center_m': [0, 1, 0],
                                                                                     'size_m': [1, 1, 1]}]), 'at most 8,192')
        refused(lambda s: s['stations'][0]['done_when']['lit_w'].update(photocell='nobody'), 'lit_w needs a photocell')

    def test_a_mirror_kit_turns_its_face_to_send_the_sun_to_its_target(self):
        spec = {'schema': mw.SCHEMA, 'sun': {'elevation_deg': 55, 'azimuth_deg': 200, 'irradiance_w_m2': 1000},
                'parts': [part('target', [0.1, 0.1, 0.1], [2.0, 0.6, -1.0], fixed=True)],
                'kits': [{'kit': 'mirror', 'name': 'heliostat', 'at_m': [0.0, 0.5, 0.0], 'size_m': [0.3, 0.3],
                          'aim_at': 'target'}]}
        # The kit's part is declared before the plain parts, so aim at a point
        # the target stands on instead; and at the target by name after it.
        spec['kits'][0].pop('aim_at')
        spec['kits'][0]['aim_m'] = [2.0, 0.6, -1.0]
        c = mw.compile_spec(spec)
        plate = next(p for p in c['parts'] if p['name'] == 'heliostat')
        self.assertEqual(c['light']['mirrors'], ['heliostat'])
        normal = mw.rotation(plate['turn_deg'])
        n = [normal[i][1] for i in range(3)]                       # the plate's own +y, turned
        el, az = math.radians(55), math.radians(200)
        down = [-math.cos(el) * math.sin(az), -math.sin(el), -math.cos(el) * math.cos(az)]
        d = sum(a * b for a, b in zip(down, n))
        out = [down[i] - 2 * d * n[i] for i in range(3)]
        want = [2.0, 0.1, -1.0]
        cos = sum(a * b for a, b in zip(out, want)) / math.sqrt(sum(a * a for a in want))
        self.assertGreater(cos, 1 - 1e-9, 'the sun off the mirror goes to its target')
        refused = dict(spec, sun=None)
        refused.pop('sun')
        with self.assertRaises(mw.MachineRefused):
            mw.compile_spec(refused)

    def test_a_light_gate_kit_makes_a_beam_and_a_sensor(self):
        spec = {'schema': mw.SCHEMA,
                'parts': [part('battery box', [0.2, 0.1, 0.2], [0, 0.05, 1], material='concrete', fixed=True)],
                'batteries': [{'name': 'battery', 'in': 'battery box', 'capacity_j': 1e4, 'voltage_v': 12}],
                'kits': [{'kit': 'light_gate', 'name': 'gate', 'from_m': [-0.5, 0, 0], 'to_m': [0.5, 0, 0],
                          'height_m': 0.3, 'battery': 'battery'}]}
        c = mw.compile_spec(spec)
        self.assertEqual([lp['name'] for lp in c['light']['lamps']], ['gate lamp'])
        self.assertEqual([p['name'] for p in c['light']['photocells']], ['gate eye'])
        self.assertEqual(c['light']['lamps'][0]['axis'], [1.0, 0.0, 0.0])

    @need_engine
    def test_sunlight_through_a_glass_ball_works_the_switch_that_burns_the_rope(self):
        with tempfile.TemporaryDirectory() as logs:
            r = mw.rehearse(mw.compile_spec(lens_machine()), ENGINE, Path(logs), seconds=30, wall_limit_s=200)
            self.assertIsNone(r['error'])
            self.assertTrue(all(row['done'] for row in r['stations']), r['stations'])
            times = [row['at_s'] for row in r['stations']]
            self.assertEqual(times, sorted(times), 'stations happened out of order')
            # Lit only once the ball has rolled over the sensor, not by the
            # open sun at the start.
            self.assertGreater(times[0], 1.0)
            texts = ' | '.join(e['text'] for e in r['events'])
            self.assertIn('heater: switch closed', texts)
            self.assertIn('weight rope came off', texts)
        # Without the ball the same sun on the same sensor is not enough.
        with tempfile.TemporaryDirectory() as logs:
            bare = mw.MachineSession(mw.compile_spec(lens_machine(lens=False)), ENGINE, Path(logs), paced=False)
            try:
                bare.play(True)
                with bare.lock:
                    while bare.t < 3.0 and not bare.error:
                        bare.lock.wait(0.1)
                    eye = bare.readouts['light']['photocells'][0]
                    closed = bare.readouts['circuits'][0]['closed']
            finally:
                bare.close()
            self.assertFalse(closed, 'the open sun closed the switch')
            # The rays it catches, 3 mm apart, each carrying 1000 W/m2 x 9 mm2:
            # about 0.05 W on its 50 mm2, and at most a third of the 0.3 W that
            # closes the switch.
            self.assertGreater(eye['peak_w'], 0.0)
            self.assertLess(eye['peak_w'], 0.1)

    @need_engine
    def test_a_ball_through_a_light_gate_darkens_its_sensor(self):
        spec = {'schema': mw.SCHEMA, 'cell_m': 0.02,
                'parts': [part('battery box', [0.2, 0.1, 0.2], [0, 0.05, 1], material='concrete', fixed=True),
                          part('block', [0.1, 0.24, 0.1], [0.0, 0.12, 0.0], material='concrete', fixed=True),
                          {'name': 'ball', 'shape': 'sphere', 'material': 'oak', 'size_m': [0.1, 0.1, 0.1],
                           'at_m': [0.0, 1.0, 0.0]}],
                'batteries': [{'name': 'battery', 'in': 'battery box', 'capacity_j': 1e5, 'voltage_v': 12}],
                'kits': [{'kit': 'light_gate', 'name': 'gate', 'from_m': [-0.5, 0, 0], 'to_m': [0.5, 0, 0],
                          'height_m': 0.3, 'battery': 'battery'}],
                'circuits': [{'name': 'alarm', 'battery': 'battery',
                              'switch': {'photocell': 'gate eye', 'closed_at_or_below_w': 1.0},
                              'coil': {'heats': 'battery box', 'resistance_ohm': 10}}],
                'stations': [{'title': 'The beam reaches the eye', 'done_when': {'lit_w': {'photocell': 'gate eye', 'w': 2}}},
                             {'title': 'The ball breaks the beam', 'done_when': {'shaded_w': {'photocell': 'gate eye', 'w': 1}}},
                             {'title': 'The alarm closes', 'done_when': {'switch_closed': 'alarm'}}]}
        with tempfile.TemporaryDirectory() as logs:
            r = mw.rehearse(mw.compile_spec(spec), ENGINE, Path(logs), seconds=2, wall_limit_s=60)
        self.assertIsNone(r['error'])
        self.assertTrue(all(row['done'] for row in r['stations']), r['stations'])
        # Its underside falls 0.65 m to the beam's 0.3 m: 0.36 s, seen within a
        # trace (four steps) and a reply.
        self.assertAlmostEqual(r['stations'][1]['at_s'], math.sqrt(2 * 0.65 / 9.81), delta=0.04)
        # It comes to rest on the block in the beam, and the alarm stays on.
        self.assertGreaterEqual(r['stations'][2]['at_s'], r['stations'][1]['at_s'])

    @need_engine
    def test_mirrors_aimed_at_a_part_add_their_light_on_it(self):
        """A dark target in the sun, and 0, 1 or 3 mirror kits aimed at it: each
        mirror adds, on the target, about what falls on the mirror times its
        reflectance, and the target absorbs half (it is oak)."""
        def absorbed(count):
            spec = {'schema': mw.SCHEMA, 'cell_m': 0.02,
                    'sun': {'elevation_deg': 60, 'azimuth_deg': 0, 'irradiance_w_m2': 1000},
                    'parts': [part('target', [0.4, 0.4, 0.04], [0, 0.5, 1.5], fixed=True)],
                    'kits': [{'kit': 'mirror', 'name': f'mirror {k}', 'at_m': [-0.6 + 0.6 * k, 0.5, 0.0],
                              'size_m': [0.2, 0.2], 'aim_m': [0, 0.5, 1.5]} for k in range(count)],
                    'light': {'sunlight': {'through': ['target'] + [f'mirror {k}' for k in range(count)],
                                           'spacing_m': 0.01}}}
            with tempfile.TemporaryDirectory() as logs:
                session = mw.MachineSession(mw.compile_spec(spec), ENGINE, Path(logs), paced=False)
                try:
                    light = session.readouts['light']
                finally:
                    session.close()
            return next((b['absorbed_w'] for b in light['lit'] if b['name'] == 'target'), 0.0), light
        alone, _ = absorbed(0)
        one, _ = absorbed(1)
        three, light = absorbed(3)
        # The sun stands 60 degrees up over +z, behind the target, so the face
        # the mirrors see is in its own shadow. Each mirror, 0.2 m square, is
        # turned square to the bisector of the sun and the target, so it takes
        # 1000 W/m2 x 0.04 m2 x cos(half the angle between them) and reflects
        # 0.925 of it (0.92 visible, 0.93 infrared); the whole beam lands on the
        # target's face and the oak absorbs half.
        sun = [0.0, math.sin(math.radians(60)), math.cos(math.radians(60))]

        def landed(k):
            to = [0.6 - 0.6 * k, 0.0, 1.5]
            n = math.sqrt(sum(c * c for c in to))
            cos_half = math.sqrt(0.5 * (1 + sum(a * b / n for a, b in zip(sun, to))))
            return 0.5 * 1000 * 0.04 * cos_half * (0.46 * 0.92 + 0.54 * 0.93)
        self.assertAlmostEqual(one - alone, landed(0), delta=0.08 * landed(0))
        self.assertAlmostEqual(three - alone, sum(landed(k) for k in range(3)), delta=0.08 * sum(landed(k) for k in range(3)))
        self.assertLess(abs(light['residual_w']), 1e-9 * light['sent_w'])

    @need_engine
    def test_light_goes_on_through_the_pieces_of_a_broken_pane(self):
        spec = {'schema': mw.SCHEMA, 'cell_m': 0.02,
                'sun': {'elevation_deg': 70, 'azimuth_deg': 90, 'irradiance_w_m2': 1000},
                'kits': [{'kit': 'plate_on_supports', 'name': 'pane', 'at_m': [0, 0.3, 0], 'size_m': [0.48, 0.02, 0.28],
                          'material': 'glass', 'span': 'z'}],
                'parts': [{'name': 'ball', 'shape': 'sphere', 'material': 'iron', 'size_m': [0.1, 0.1, 0.1],
                           'at_m': [0, 1.2, 0], 'velocity_m_s': [0, -3, 0]}],
                'light': {'sunlight': {'through': [{'center_m': [0, 0.31, 0], 'size_m': [0.5, 0.06, 0.3]}],
                                       'spacing_m': 0.01}},
                'stations': [{'title': 'The pane breaks', 'done_when': {'broke': 'pane'}}]}
        with tempfile.TemporaryDirectory() as logs:
            session = mw.MachineSession(mw.compile_spec(spec), ENGINE, Path(logs), paced=False)
            try:
                session.play(True)
                with session.lock:
                    while session.t < 1.5 and not session.error:
                        session.lock.wait(0.1)
                    light = session.readouts['light']
                    broke = session.readouts['stations'][0]['done']
            finally:
                session.close()
        self.assertTrue(broke, 'the ball broke the pane')
        pieces = [b for b in light['lit'] if b['name'].startswith('pane piece')]
        self.assertTrue(pieces, light['lit'])
        self.assertLess(abs(light['residual_w']), 1e-9 * light['sent_w'])
        self.assertLess(abs(light['joules']['residual']), 1e-9 * light['joules']['sent'])

    @need_engine
    def test_a_live_machine_sends_its_rays_to_draw(self):
        with tempfile.TemporaryDirectory() as logs:
            host = mw.MachineHost(ENGINE, logs)
            try:
                opened = host.open(lens_machine())
                light = opened['readouts']['light']
                self.assertGreater(light['sent_w'], 10.0)
                self.assertTrue(light['paths'] and all(len(p['mm']) % 3 == 0 for p in light['paths']))
                self.assertLess(abs(light['residual_w']), 1e-9 * light['sent_w'])
            finally:
                host.close_all()


def fake_model(answers):
    calls = []

    def call(messages):
        calls.append(messages)
        return copy.deepcopy(answers[len(calls) - 1]), {'input_tokens': 10, 'output_tokens': 5}
    return call, calls


class Chat(unittest.TestCase):
    def setUp(self):
        self.base = {'schema': mw.SCHEMA, 'cell_m': 0.02, 'parts': [part('floor block', [.4, .1, .4], [0, .05, 0], fixed=True)],
                     'stations': []}

    def test_refused_declaration_goes_back_once_with_its_reasons(self):
        bad = copy.deepcopy(self.base)
        bad['parts'].append(part('box', [.1, .1, .1], [0, .02, 0]))
        good = copy.deepcopy(self.base)
        good['parts'].append(part('box', [.1, .1, .1], [0, .151, 0]))
        call, calls = fake_model([{'reply': 'first', 'spec': bad}, {'reply': 'second', 'spec': good}])
        r = mc.respond('put a box on the block', self.base, call=call)
        self.assertTrue(r['buildable'])
        self.assertEqual((r['attempts'], r['reply']), (2, 'second'))
        refused = json.loads(calls[1][-1]['content'])['refused']
        self.assertTrue(any('below the ground' in p or 'overlap' in p for p in refused))

    def test_still_refused_builds_nothing_and_says_why(self):
        bad = copy.deepcopy(self.base)
        bad['parts'].append(part('box', [.1, .1, .1], [0, .02, 0]))
        call, _ = fake_model([{'reply': 'a', 'spec': bad}, {'reply': 'b', 'spec': bad}])
        r = mc.respond('put a box on the block', self.base, call=call)
        self.assertFalse(r['buildable'])
        self.assertTrue(r['problems'])

    def test_rehearsal_sends_measured_events_back_when_a_new_station_did_not_happen(self):
        first = copy.deepcopy(self.base)
        first['parts'].append(part('box', [.1, .1, .1], [1, .05, 0]))
        first['stations'] = [{'title': 'Box falls', 'done_when': {'hits': ['box', 'floor block']}}]
        second = copy.deepcopy(first)
        second['parts'][1]['at_m'] = [0, .4, 0]
        call, calls = fake_model([{'reply': 'one', 'spec': first}, {'reply': 'two', 'spec': second}])
        runs = []

        def rehearse(compiled):
            on_block = any(p['name'] == 'box' and abs(p['at_m'][0]) < .2 for p in compiled['parts'])
            runs.append(on_block)
            return {'world_time_s': 2.0, 'wall_s': .1, 'error': None,
                    'stations': [{'title': 'Box falls', 'done': on_block, 'at_s': .3 if on_block else None}],
                    'events': [{'t': .3, 'text': 'box hits floor block at 2.4 m/s'}] if on_block else []}
        r = mc.respond('drop a box on the block', self.base, call=call, rehearse=rehearse)
        self.assertEqual(runs, [False, True])
        self.assertIn('rehearsal', json.loads(calls[1][-1]['content']))
        self.assertEqual(r['rehearsal']['new_stations'], [{'title': 'Box falls', 'happened': True, 'at_s': .3}])
        self.assertEqual(r['reply'], 'two')

    def test_no_model_configured_is_said_plainly(self):
        saved = mc.configuration
        mc.configuration = lambda: ('', 'none')
        try:
            with self.assertRaises(mc.ChatUnavailable):
                mc.respond('anything', self.base)
        finally:
            mc.configuration = saved

    def test_prompt_lists_every_kit_and_material(self):
        prompt = mc.system_prompt()
        for name in list(mw.KITS) + list(mw.MATERIALS):
            self.assertIn(name, prompt)


if __name__ == '__main__':
    unittest.main()
