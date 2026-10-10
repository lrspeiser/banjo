"""The machine's newer physics, each in a small machine run by the real engine:
gears, a block and tackle, a motor on a battery, the sun charging a battery
through a solar panel, a steam engine and a cannon whose ball dents what it
hits. docs/machine-physics-roadmap.md lists them.

    python tests/machine_physics_tests.py [--engine path/to/banjo_live_world_run]

Without an engine the declaration checks still run; the engine tests are
skipped, never passed. Set BANJO_MACHINE_ENGINE=required to fail instead.

Each test asks for what makes the thing that thing -- the big wheel turns the
other way at the ratio of the teeth, the load rises by the ratio of the
tackle, the steam lifts the piston, the ball leaves the barrel and the gas
after it -- with tolerances for a world that has contact and settling in it,
not for exact repeats.
"""
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


def box(name, size, at, **kw):
    return dict({'name': name, 'shape': 'box', 'material': 'oak', 'size_m': size, 'at_m': at}, **kw)


def wheel(name, x, radius):
    return {'name': name, 'shape': 'compound', 'material': 'aluminum', 'at_m': [x, 0.3, 0],
            'parts': [{'shape': 'cylinder', 'size_m': [2 * radius, 0.04, 2 * radius], 'at_m': [0, 0, 0],
                       'turn_deg': [90, 0, 0]}]}


GEARS = {'schema': mw.SCHEMA, 'title': 'Motor, gears and sun',
         'parts': [box('post a', [0.1, 0.28, 0.1], [0, 0.14, -0.1], material='concrete', fixed=True),
                   box('post b', [0.1, 0.28, 0.1], [0.4, 0.14, -0.1], material='concrete', fixed=True),
                   wheel('wheel a', 0.0, 0.1), wheel('wheel b', 0.4, 0.2),
                   box('battery box', [0.1, 0.1, 0.1], [-0.4, 0.05, 0], material='iron', fixed=True),
                   box('panel', [0.5, 0.02, 0.5], [-1.2, 0.01, 0], material='glass', fixed=True),
                   box('solar box', [0.1, 0.1, 0.1], [-1.2, 0.05, 0.5], material='iron', fixed=True)],
         'joints': [{'name': 'hinge a', 'kind': 'hinge', 'a': 'post a', 'b': 'wheel a', 'at_m': [0, 0.3, 0],
                     'axis': [0, 0, 1], 'friction_n_m': 0.02},
                    {'name': 'hinge b', 'kind': 'hinge', 'a': 'post b', 'b': 'wheel b', 'at_m': [0.4, 0.3, 0],
                     'axis': [0, 0, 1], 'friction_n_m': 0.02},
                    {'name': 'gears', 'kind': 'gear', 'a': 'hinge a', 'b': 'hinge b', 'teeth_a': 12, 'teeth_b': 24}],
         'batteries': [{'name': 'battery', 'in': 'battery box', 'capacity_j': 50000, 'voltage_v': 24},
                       {'name': 'solar battery', 'in': 'solar box', 'capacity_j': 20000, 'voltage_v': 12,
                        'charge_j': 0}],
         'circuits': [{'name': 'drive', 'battery': 'battery',
                       'motor': {'hinge': 'hinge a', 'stall_torque_n_m': 2, 'no_load_rad_s': 6}}],
         'sun': {'elevation_deg': 50, 'azimuth_deg': 180, 'irradiance_w_m2': 1000},
         'solar_panels': [{'name': 'panel', 'part': 'panel', 'battery': 'solar battery', 'normal': [0, 1, 0],
                           'area_m2': 0.25, 'efficiency': 0.2}],
         'stations': [{'title': 'Gears', 'done_when': {'turned_deg': {'joint': 'hinge b', 'deg': 180}},
                       'focus': ['wheel a', 'wheel b']}]}

PULLEY = {'schema': mw.SCHEMA, 'title': 'Block and tackle',
          'parts': [box('counterweight', [0.12, 0.12, 0.12], [-0.3, 1.0, 0], material='aluminum'),
                    box('load', [0.1, 0.1, 0.1], [0.3, 0.4, 0]),
                    box('bell', [0.1, 0.04, 0.1], [0.3, 0.75, 0], material='iron', fixed=True)],
          'joints': [{'name': 'tackle', 'kind': 'pulley', 'a': 'counterweight', 'b': 'load', 'at_m': [-0.3, 1.06, 0],
                      'at_b_m': [0.3, 0.45, 0], 'over_a_m': [-0.3, 1.6, 0], 'over_b_m': [0.3, 1.6, 0], 'ratio': 2}],
          'stations': [{'title': 'Block and tackle', 'done_when': {'hits': ['load', 'bell']}, 'focus': ['load']}]}

STEAM_AND_POWDER = {'schema': mw.SCHEMA, 'title': 'Steam and powder', 'plasticity': True,
                    'kits': [{'kit': 'steam_engine', 'name': 'steam', 'at_m': [-1.0, 0, 0], 'heat_w': 10000},
                             {'kit': 'cannon', 'name': 'cannon', 'at_m': [0.2, 0.1, 0.6], 'toward': '+x',
                              'powder_g': 2.0, 'ball': {'diameter_m': 0.08}, 'fire_at_s': 0.5}],
                    'parts': [box('anvil', [0.1, 0.3, 0.3], [1.2, 0.15, 0.6], material='iron', fixed=True)],
                    'stations': [
                        {'title': 'Steam lifts the piston', 'done_when': {'rose_m': {'part': 'steam piston', 'm': 0.1}},
                         'focus': ['steam piston']},
                        {'title': 'Cannon fires', 'done_when': {'moved_m': {'part': 'cannon ball', 'm': 0.3}},
                         'focus': ['cannon ball']},
                        {'title': 'Ball hits the anvil', 'done_when': {'hits': ['cannon ball', 'anvil']},
                         'focus': ['anvil']},
                        {'title': 'Ball dented', 'done_when': {'dented': 'cannon ball'}, 'focus': ['anvil']}]}


KNIFE = {'schema': mw.SCHEMA, 'title': 'Knife pendulum',
         'kits': [{'kit': 'hanging_weight', 'name': 'weight', 'post_m': [0.5, 0, 0], 'drop_m': 0.3, 'side': '-z',
                   'hang': 'rope', 'rope_m': 0.3, 'weight_material': 'iron'},
                  {'kit': 'knife_pendulum', 'name': 'knife', 'aim_at': 'weight rope', 'arm_m': 0.6,
                   'swing_toward': '+x'}],
         'stations': [{'title': 'Knife cuts the rope', 'done_when': {'cut': 'weight rope'}, 'focus': ['weight rope']},
                      {'title': 'Weight falls', 'done_when': {'hits': ['weight', 'the ground']}, 'focus': ['weight']}]}


# The same, with the rope's post on the other side of it: a knife turned 30
# degrees about the vertical swings in past where the post of KNIFE stands.
KNIFE_TURNED = dict(KNIFE, kits=[dict(KNIFE['kits'][0], side='+z'), KNIFE['kits'][1]])


def run(spec, seconds, sample=None, wall_s=240.0):
    """Run a machine unpaced in the real engine; `sample(session)` is called
    under the session's lock about every 0.05 s of world time."""
    compiled = mw.compile_spec(spec)
    with tempfile.TemporaryDirectory() as logs:
        s = mw.MachineSession(compiled, ENGINE, Path(logs), paced=False)
        try:
            s.play(True)
            started, last = time.perf_counter(), -1.0
            while time.perf_counter() - started < wall_s:
                with s.lock:
                    if sample and s.t - last >= 0.05:
                        last = s.t
                        sample(s)
                    if s.t >= seconds or s.error:
                        break
                    s.lock.wait(0.02)
            with s.lock:
                return {'t': s.t, 'error': s.error, 'events': [e['text'] for e in s.events],
                        'stations': list((s.readouts or {}).get('stations', [])),
                        'readouts': dict(s.readouts or {}),
                        'bodies': {b['name']: dict(b) for b in s.bodies.values()}}
        finally:
            s.close()


class Declarations(unittest.TestCase):
    def refused(self, spec, words):
        with self.assertRaises(mw.MachineRefused) as caught:
            mw.compile_spec(spec)
        self.assertIn(words, ' | '.join(caught.exception.problems))

    def test_new_pieces_are_checked_before_anything_is_built(self):
        bad = dict(GEARS, joints=GEARS['joints'][:2] + [dict(GEARS['joints'][2], b='post b')])
        self.refused(bad, 'gear')
        self.refused(dict(GEARS, circuits=[{'name': 'drive', 'battery': 'battery'}]), 'a circuit needs a load')
        self.refused(dict(GEARS, sun=None), 'a solar panel needs a sun')
        no_plastic = dict(STEAM_AND_POWDER)
        no_plastic.pop('plasticity')
        self.refused(no_plastic, 'a dent needs "plasticity": true')
        weak = dict(STEAM_AND_POWDER, kits=[STEAM_AND_POWDER['kits'][0],
                                            dict(STEAM_AND_POWDER['kits'][1], powder_g=0.05)])
        self.refused(weak, 'only smoulders')
        # An iron edge on the iron weight itself: as hard as the edge, so it
        # cannot be cut, and the declaration says how to drop a weight instead.
        at_iron = dict(KNIFE, kits=[KNIFE['kits'][0], dict(KNIFE['kits'][1], aim_at='weight')])
        self.refused(at_iron, '"hang": "rope"')

    def test_kits_declare_their_steam_and_powder_to_the_engine(self):
        c = mw.compile_spec(STEAM_AND_POWDER)
        regions = {r['name']: r for r in c['thermo']['gas_regions']}
        self.assertEqual((regions['steam steam']['piston'], regions['steam steam']['balance']), ('steam piston', True))
        breech = regions['cannon breech']
        self.assertEqual((breech['piston'], breech['vent_open'], breech['opens_at_stroke_m']), ('cannon ball', False, 0.3))
        contents = {r['body']: r for r in c['thermo']['contents']}
        self.assertEqual(contents['steam boiler']['temperature_k'], mw.BOILING_K)
        self.assertGreater(contents['cannon charge']['contents']['propellant'], 0.05)
        self.assertIn('thermo', mw.scene_of(c))
        wad = next(j for j in c['joints'] if j['name'] == 'cannon wad')
        self.assertEqual((wad['kind'], wad['b']), ('fix', 'cannon ball'))

    def test_a_knife_pendulum_is_held_out_level_away_from_its_swing_with_its_edge_leading(self):
        c = mw.compile_spec(KNIFE)
        by = {p['name']: p for p in c['parts']}
        rope = by['weight rope']['at_m']
        self.assertLess(by['knife blade']['at_m'][0], rope[0] - 0.5, 'held out against a swing toward +x')
        self.assertAlmostEqual(by['knife blade']['at_m'][1], by['knife beam']['at_m'][1] - 0.06, places=6)
        # Square to the world, so the engine builds it exactly to its faces.
        self.assertEqual((by['knife blade']['turn_deg'], by['knife arm']['turn_deg']), ([0, 0, 0], [0, 0, 0]))
        edge = c['blades'][0]
        self.assertEqual(edge['part'], 'knife blade')
        # The edge runs across the swing (along z) on the blade's underside:
        # the way it moves first when it is let go.
        self.assertAlmostEqual(edge['heel_m'][0], edge['tip_m'][0], places=9)
        self.assertGreater(abs(edge['tip_m'][2] - edge['heel_m'][2]), 0.15)
        self.assertEqual(edge['facing'], [0.0, -1.0, 0.0])
        self.assertAlmostEqual(edge['heel_m'][1], by['knife blade']['at_m'][1] - 0.06, places=9)
        # Pulled back 60 degrees: the arm and the blade turned down 30 degrees
        # about the hinge (toward +x, so about +z), and the edge still on the
        # blade's leading face, facing the way the blade first moves.
        tilted = mw.compile_spec(dict(KNIFE, kits=[KNIFE['kits'][0], dict(KNIFE['kits'][1], pull_back_deg=60)]))
        at60 = {p['name']: p for p in tilted['parts']}
        self.assertEqual(at60['knife blade']['turn_deg'], [0.0, 0.0, 30.0])
        self.assertEqual(at60['knife arm']['turn_deg'], [0.0, 0.0, 30.0])
        pivot = next(j for j in tilted['joints'] if j['name'] == 'knife hinge')['at_m']
        level, low = by['knife blade']['at_m'], at60['knife blade']['at_m']
        self.assertAlmostEqual(math.dist(level[:2], pivot[:2]), math.dist(low[:2], pivot[:2]), places=9)
        self.assertAlmostEqual(math.degrees(math.atan2(pivot[1] - low[1], pivot[0] - low[0])), 30.0, places=6)
        cut60 = tilted['blades'][0]
        self.assertAlmostEqual(cut60['facing'][0], 0.5, places=9)
        self.assertAlmostEqual(cut60['facing'][1], -math.sqrt(3) / 2, places=9)
        c30, s30 = math.cos(math.radians(30)), math.sin(math.radians(30))
        for key in ('heel_m', 'tip_m'):
            # Into the blade's own frame: on its leading face, inside its thickness.
            rel = [cut60[key][i] - low[i] for i in range(3)]
            local = [c30 * rel[0] + s30 * rel[1], -s30 * rel[0] + c30 * rel[1], rel[2]]
            self.assertAlmostEqual(local[1], -0.06, places=9)
            self.assertAlmostEqual(local[0], 0.0, places=9)
        # Heavier: an iron weight of whole cells fixed on the arm near its end.
        heavy = mw.compile_spec(dict(KNIFE, kits=[KNIFE['kits'][0], dict(KNIFE['kits'][1], weight_kg=10)]))
        weight = next(p for p in heavy['parts'] if p['name'] == 'knife weight')
        self.assertEqual(weight['size_m'], [0.1, 0.1, 0.1])
        fixing = next(j for j in heavy['joints'] if j['name'] == 'knife weight fixing')
        self.assertEqual((fixing['a'], fixing['b']), ('knife arm', 'knife weight'))
        # Its arm hangs beside the rope's own arm, not through it.
        self.assertLess(by['knife arm']['at_m'][2], by['weight arm']['at_m'][2] - 0.1)

    def test_a_knife_turned_about_the_vertical_is_the_same_knife_turned(self):
        # turn_deg 30: every part, pin and the edge is where the unturned
        # knife has it, turned 30 degrees about the vertical through its pin,
        # and every part is turned [0, 30, z] -- the heading about y on top of
        # the pull back about z, which is the order the engine turns a body in.
        for pull in (90, 60):
            def knife(turn):
                return mw.compile_spec(dict(KNIFE_TURNED, kits=[
                    KNIFE_TURNED['kits'][0],
                    dict(KNIFE_TURNED['kits'][1], pull_back_deg=pull, turn_deg=turn, arm_side='+')]))
            square, turned = knife(0), knife(30)
            c, s = math.cos(math.radians(30)), math.sin(math.radians(30))

            def about_up(v):
                return [v[0] * c + v[2] * s, v[1], -v[0] * s + v[2] * c]

            def hinge(compiled):
                return next(j for j in compiled['joints'] if j['name'] == 'knife hinge')['at_m']

            was, now = {p['name']: p for p in square['parts']}, {p['name']: p for p in turned['parts']}
            h0, h1 = hinge(square), hinge(turned)
            for name in ('knife beam', 'knife post A', 'knife post B', 'knife arm', 'knife blade'):
                want = about_up([was[name]['at_m'][i] - h0[i] for i in range(3)])
                got = [now[name]['at_m'][i] - h1[i] for i in range(3)]
                for i in range(3):
                    self.assertAlmostEqual(got[i], want[i], places=9, msg=(pull, name))
                self.assertEqual(now[name]['turn_deg'], [0.0, 30.0, float(was[name]['turn_deg'][2])], (pull, name))
                self.assertEqual(now[name]['size_m'], was[name]['size_m'])
            e0, e1 = square['blades'][0], turned['blades'][0]
            for key in ('heel_m', 'tip_m'):
                want = about_up([e0[key][i] - h0[i] for i in range(3)])
                for i in range(3):
                    self.assertAlmostEqual(e1[key][i] - h1[i], want[i], places=9)
            for i, v in enumerate(about_up(e0['facing'])):
                self.assertAlmostEqual(e1['facing'][i], v, places=9)
            # And it swings 30 degrees round: the hinge's axis is turned too.
            axis = next(j for j in turned['joints'] if j['name'] == 'knife hinge')['axis']
            for i, v in enumerate(about_up([0.0, 0.0, 1.0])):
                self.assertAlmostEqual(axis[i], v, places=9)


class Engine(unittest.TestCase):
    @need_engine
    def test_a_motor_turns_one_wheel_and_the_gears_turn_the_other_back_at_half_speed(self):
        r = run(GEARS, 4.0)
        self.assertIsNone(r['error'])
        joints = {j['name']: j for j in r['readouts']['joints']}
        a, b = joints['hinge a']['turned_deg'], joints['hinge b']['turned_deg']
        print(f'\n  motor wheel turned {a:.0f} deg, geared wheel {b:.0f} deg')
        self.assertGreater(a, 360.0, 'the motor did not turn its wheel')
        self.assertAlmostEqual(b / a, -0.5, delta=0.02, msg='12 teeth to 24 turn the big wheel back at half speed')
        self.assertTrue(r['stations'][0]['done'])
        machines = r['readouts']['machines']
        battery = next(x for x in machines['batteries'] if x['name'] == 'battery')
        self.assertLess(battery['charge_j'], 50000.0, 'the motor ran on nothing')

    @need_engine
    def test_the_sun_charges_an_empty_battery_through_a_panel_nothing_shades(self):
        r = run(GEARS, 3.0)
        machines = r['readouts']['machines']
        panel = machines['solar_panels'][0]
        print(f"\n  panel: {panel['sunlight_w']:.1f} W of sunlight, {panel['power_w']:.1f} W in")
        self.assertFalse(panel['shaded'], f"shaded by {panel['shaded_by']}")
        # 0.25 m2 facing up under a sun 50 deg high: sunlight times sin(50),
        # thinned by the air, and a fifth of it stored.
        self.assertGreater(panel['sunlight_w'], 0.25 * 1000 * math.sin(math.radians(50)) * 0.85)
        self.assertLess(panel['sunlight_w'], 0.25 * 1000 * math.sin(math.radians(50)) * 1.05)
        self.assertAlmostEqual(panel['power_w'], 0.2 * panel['sunlight_w'], delta=0.01 * panel['sunlight_w'])
        stored = next(x for x in machines['batteries'] if x['name'] == 'solar battery')['charge_j']
        self.assertGreater(stored, 0.5 * panel['power_w'] * r['t'])

    @need_engine
    def test_a_block_and_tackle_lifts_its_load_half_as_far_as_the_counterweight_falls(self):
        start = {p['name']: p['at_m'][1] for p in PULLEY['parts']}
        seen = []

        def sample(s):
            heights = {b['name']: b['position_m'][1] for b in s.bodies.values()}
            if 'load' in heights and heights['load'] < 0.68:
                seen.append((start['counterweight'] - heights['counterweight'], heights['load'] - start['load']))

        r = run(PULLEY, 1.0, sample)
        self.assertTrue(r['stations'][0]['done'], r['events'])
        fall, rise = seen[-1]
        print(f'\n  counterweight fell {fall:.3f} m, load rose {rise:.3f} m')
        self.assertGreater(rise, 0.1)
        self.assertAlmostEqual(rise / fall, 0.5, delta=0.05)

    @need_engine
    def test_steam_lifts_a_piston_and_a_cannon_throws_its_ball_hard_enough_to_dent_it(self):
        speeds = []

        def sample(s):
            ball = next((b for b in s.bodies.values() if b['name'] == 'cannon ball'), None)
            if ball:
                speeds.append(math.hypot(*ball.get('velocity_m_s', [0, 0, 0])))

        r = run(STEAM_AND_POWDER, 3.0, sample)
        self.assertIsNone(r['error'])
        done = {s['title']: s for s in r['stations']}
        print('\n  ' + ' | '.join(r['events'][:8]))
        self.assertTrue(done['Steam lifts the piston']['done'], r['events'])
        self.assertTrue(done['Cannon fires']['done'], r['events'])
        self.assertTrue(done['Ball hits the anvil']['done'], r['events'])
        self.assertGreater(max(speeds), 10.0, 'the ball was pushed, not fired')
        gas = {g['name']: g for g in r['readouts']['gas']}
        # Out of the muzzle, the breech is open to the air again.
        self.assertLess(gas['cannon breech']['pressure_kpa'], 110.0)
        self.assertGreater(gas['steam steam']['stroke_m'], 0.1)
        self.assertTrue(done['Ball dented']['done'], r['events'])
        self.assertLessEqual(done['Cannon fires']['at_s'], done['Ball hits the anvil']['at_s'],
                             'the ball was timed hitting before it was timed leaving')

    @need_engine
    def test_a_knife_pendulum_cuts_the_rope_edge_first_and_the_weight_falls(self):
        r = run(KNIFE, 1.5)
        self.assertIsNone(r['error'])
        print('\n  ' + ' | '.join(r['events'][:6]))
        done = {s['title']: s for s in r['stations']}
        self.assertTrue(done['Knife cuts the rope']['done'], r['events'])
        self.assertTrue(done['Weight falls']['done'], r['events'])
        self.assertLess(done['Knife cuts the rope']['at_s'], done['Weight falls']['at_s'])
        cut = next(c for c in r['readouts']['cuts'] if c['target'] == 'weight rope')
        self.assertEqual(cut['kind'], 'edge')
        # A 20 mm oak cord is 400 mm2; through it at the swing's slant costs at
        # least that much area, each square metre at oak's R for this edge.
        self.assertGreater(cut['area_mm2'], 400.0)
        self.assertGreater(cut['work_j'], 0.9 * 400e-6 * 15000.0)

    @need_engine
    def test_a_knife_pulled_back_60_degrees_cuts_the_rope_edge_first_wherever_it_stands(self):
        # Pulled back 60 degrees, the blade starts tilted 30 degrees off level.
        # A tilted box was built of a staircase of the world's cells, so its
        # face had matter where the edge was declared in some places and not in
        # others: with the rope's post at x 0.513 or 0.527 the engine refused
        # the edge, and where it took it the cut came to 442-514 mm2 by place.
        # Built in its own frame, it is the same knife wherever it stands.
        places = [[0.5, 0, 0], [0.513, 0, 0], [0.527, 0, 0.004], [0.5371, 0, -0.0113], [0.4437, 0, 0.0071]]
        seen = []
        for post in places:
            spec = dict(KNIFE, kits=[dict(KNIFE['kits'][0], post_m=post),
                                     dict(KNIFE['kits'][1], pull_back_deg=60)])
            r = run(spec, 1.5)
            self.assertIsNone(r['error'], f'post at {post}')
            done = {s['title']: s for s in r['stations']}
            self.assertTrue(done['Knife cuts the rope']['done'], (post, r['events']))
            self.assertTrue(done['Weight falls']['done'], (post, r['events']))
            self.assertLess(done['Knife cuts the rope']['at_s'], done['Weight falls']['at_s'])
            cuts = [c for c in r['readouts']['cuts'] if c['target'].startswith('weight rope')]
            self.assertTrue(cuts, (post, r['events']))
            self.assertEqual(cuts[0]['kind'], 'edge', (post, r['events']))
            self.assertTrue(any('cut weight rope through' in t for t in r['events']), (post, r['events']))
            area = sum(c['area_mm2'] for c in cuts)
            self.assertGreater(area, 400.0)
            seen.append(area)
        print(f'\n  pulled back 60 degrees, the rope cut edge first in {len(places)} places: '
              + ', '.join(f'{a:.0f}' for a in seen) + ' mm2')
        # The same blade meets the same rope the same way wherever it stands.
        self.assertLess(max(seen) - min(seen), 0.01 * max(seen))

    @need_engine
    def test_a_knife_turned_30_degrees_about_the_vertical_takes_its_edge_and_cuts_wherever_it_stands(self):
        # Turned 30 degrees about the vertical, held out level its blade is a
        # plate turned about y; pulled back 60 it is turned about y and z both.
        # Before the engine built a tilted box in its own frame, it refused
        # this knife its edge in 5 of these 8 runs -- "the edge does not lie
        # on its matter", every time it was pulled back 60 -- and where it took
        # it the cut came to 398-424 mm2 by place. Now every one takes its
        # edge, cuts the rope edge first and
        # through, and the weight falls; and a knife meets the rope the same
        # way wherever it stands.
        places = [[0.5, 0, 0], [0.513, 0, 0.0037], [0.527, 0, 0.004], [0.5371, 0, -0.0113]]
        said = []
        for pull in (90, 60):
            areas = []
            for post in places:
                spec = dict(KNIFE_TURNED, kits=[dict(KNIFE_TURNED['kits'][0], post_m=post),
                                                dict(KNIFE_TURNED['kits'][1], pull_back_deg=pull, turn_deg=30)])
                r = run(spec, 1.5)
                self.assertIsNone(r['error'], (pull, post))
                done = {s['title']: s for s in r['stations']}
                self.assertTrue(done['Knife cuts the rope']['done'], (pull, post, r['events']))
                self.assertTrue(done['Weight falls']['done'], (pull, post, r['events']))
                cuts = [c for c in r['readouts']['cuts'] if c['target'].startswith('weight rope')]
                self.assertTrue(cuts, (pull, post, r['events']))
                self.assertEqual(cuts[0]['kind'], 'edge', (pull, post, r['events']))
                self.assertTrue(any('cut weight rope through' in t for t in r['events']), (pull, post, r['events']))
                areas.append(sum(c['area_mm2'] for c in cuts))
            self.assertLess(max(areas) - min(areas), 0.01 * max(areas), (pull, areas))
            said.append(f'pulled back {pull}: ' + ', '.join(f'{a:.0f}' for a in areas) + ' mm2')
        print('\n  turned 30 degrees about the vertical, the rope cut edge first everywhere; ' + '; '.join(said))

    @need_engine
    def test_the_flat_of_the_knife_does_not_cut(self):
        flat = dict(KNIFE, kits=[KNIFE['kits'][0], dict(KNIFE['kits'][1])])
        compiled = mw.compile_spec(flat)
        # Put the same edge on the plate's top face, facing up: as it comes
        # through the bottom the plate's flat leads and the edge trails.
        for key in ('heel_m', 'tip_m'):
            compiled['blades'][0][key][1] += 0.12
        compiled['blades'][0]['facing'] = [0.0, 1.0, 0.0]
        with tempfile.TemporaryDirectory() as logs:
            s = mw.MachineSession(compiled, ENGINE, Path(logs), paced=False)
            try:
                s.play(True)
                started = time.perf_counter()
                with s.lock:
                    while s.t < 1.0 and not s.error and time.perf_counter() - started < 120:
                        s.lock.wait(0.05)
                    texts = [e['text'] for e in s.events]
                    pieces = [b for b in s.bodies if b.startswith('weight rope piece')]
            finally:
                s.close()
        print('\n  ' + ' | '.join(texts[:4]))
        self.assertFalse(pieces, 'the flat cut the rope')
        self.assertFalse(any('cut weight rope through' in t for t in texts))


if __name__ == '__main__':
    unittest.main(verbosity=2)
