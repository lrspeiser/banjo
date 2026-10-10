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
    """TileImpactScene rotateDegrees, written out again independently."""
    x, y, z = v
    a = [math.radians(d) for d in degrees]
    y, z = y * math.cos(a[0]) - z * math.sin(a[0]), y * math.sin(a[0]) + z * math.cos(a[0])
    x, z = x * math.cos(a[1]) + z * math.sin(a[1]), -x * math.sin(a[1]) + z * math.cos(a[1])
    x, y = x * math.cos(a[2]) - y * math.sin(a[2]), x * math.sin(a[2]) + y * math.cos(a[2])
    return [x, y, z]


def part(name, size, at, **kw):
    return dict({'name': name, 'shape': 'box', 'material': 'oak', 'size_m': size, 'at_m': at}, **kw)


class Declaration(unittest.TestCase):
    def test_default_machine_compiles_from_general_parts(self):
        c = mw.compile_spec(mw.default_spec())
        names = {p['name'] for p in c['parts']}
        for n in ('marble', 'domino 1', 'domino 8', 'lever', 'lever pivot', 'weight', 'weight peg', 'glass plate'):
            self.assertIn(n, names)
        self.assertEqual({j['kind'] for j in c['joints']}, {'hinge', 'fix'})
        self.assertEqual(c['circuits'][0]['switch'], {'hinge': 'lever hinge', 'closed_at_or_above_deg': 8.0})
        self.assertLess(c['cells'], mw.MAX_CELLS)
        for p in c['parts']:
            for s in p['size_m']:
                self.assertAlmostEqual(s / c['cell_m'], round(s / c['cell_m']), places=6, msg=p['name'])
            self.assertGreaterEqual(mw.lowest_point(p), -1e-9, p['name'])

    def test_rotation_matches_the_engine(self):
        for degrees in ([30, 0, 45], [20, 35, -50], [-60, 25, 10], [0, 90, 0], [0, 0, -20]):
            r = mw.rotation(degrees)
            for v in ([1, 0, 0], [0, 1, 0], [0.3, -0.2, 0.9]):
                mine = [sum(r[i][j] * v[j] for j in range(3)) for i in range(3)]
                for a, b in zip(mine, engine_turn(v, degrees)):
                    self.assertAlmostEqual(a, b, places=12)

    def test_refuses_what_cannot_be_built_honestly(self):
        base = {'schema': mw.SCHEMA, 'cell_m': 0.02}
        cases = [
            ({'parts': [part('a', [.1, .1, .1], [0, .02, 0])]}, 'below the ground'),
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
    def test_default_machine_runs_every_built_station_in_order_and_hands_heat_over_exactly(self):
        with tempfile.TemporaryDirectory() as logs:
            compiled = mw.compile_spec(mw.default_spec())
            r = mw.rehearse(compiled, ENGINE, Path(logs), seconds=30, wall_limit_s=120)
            self.assertIsNone(r['error'])
            built = [(s, row) for s, row in zip(compiled['stations'], r['stations']) if s.get('done_when')]
            self.assertTrue(all(row['done'] for _, row in built), r['stations'])
            times = [row['at_s'] for _, row in built]
            self.assertEqual(times, sorted(times), 'stations happened out of order')
            self.assertFalse(r['stations'][-1]['done'], 'the unbuilt water wheel cannot be done')
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
                quiet = session.frame(session.seq, 0)
                self.assertEqual(quiet['bodies'], [])
                self.assertTrue(host.close(opened['session'])['closed'])
                with self.assertRaises(LookupError):
                    host.get(opened['session'])
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
