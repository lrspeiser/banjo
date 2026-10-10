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


class Tray(unittest.TestCase):
    def test_every_level_is_well_formed_and_its_solution_fits_its_tray(self):
        self.assertEqual([l['id'] for l in LEVELS], ['gap', 'cut', 'fire', 'steam', 'chain', 'laser', 'sun'])
        for level in LEVELS:
            spec, checked, cost = mg.compose(level, level['solution'])
            mw.compile_spec(spec)
            self.assertLessEqual(cost, level['par'], f'{level["id"]}: its own solution is over par')
            self.assertNotIn('solution', mg.public(level), 'the page is never sent the answer')

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
                # A mirror turns about the vertical by its own angle_deg.
                self.assertEqual(turning, ['angle_deg', 'pitch_deg', 'roll_deg'] if t['piece'] == 'mirror'
                                 else ['pitch_deg', 'roll_deg', 'yaw_deg'], level['id'])
                self.assertIn('z_m', t['knobs'])
            # Unturned, a level's own solution is built exactly as before.
            spec, _, cost = mg.compose(level, level['solution'])
            self.assertFalse(any('turned' in k for k in spec['kits']), level['id'])
            turned = [dict(p, pitch_deg=10, roll_deg=-20) for p in level['solution']]
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
        self.assertEqual((g['fits'], [p['name'] for p in g['parts']]), (True, ['your mirror 2']))
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


class Engine(unittest.TestCase):
    @need_engine
    def test_every_level_is_solved_by_its_solution_every_time_and_not_without_pieces(self):
        with tempfile.TemporaryDirectory() as logs:
            for level in LEVELS:
                with self.subTest(level=level['id']):
                    t = mg.trial(level, level['solution'], ENGINE, Path(logs), runs=3)
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
        spec, _, _ = mg.compose(fire, [dict(fire['solution'][0], yaw_deg=20)])
        with tempfile.TemporaryDirectory() as logs:
            s = mw.MachineSession(mw.compile_spec(spec), ENGINE, Path(logs), paced=False)
            try:
                start, flown, began = None, None, time.perf_counter()
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
    def test_a_misplaced_piece_fails_for_a_physical_reason(self):
        # The knife set too high swings over the rope and into the weight's arm.
        level = mg.level_by_id('cut')
        high = [dict(level['solution'][0], pivot_height_m=level['solution'][0]['pivot_height_m'] + 0.2)]
        # The cannon too weak: its ball falls short of the block.
        fire = mg.level_by_id('fire')
        weak = [dict(fire['solution'][0], powder_g=0.5)]
        # One mirror where two are needed: the beam goes into the wall.
        laser = mg.level_by_id('laser')
        # A panel lying flat in the sun, and one facing the sun in the shed's
        # shadow: too little sunlight for the winch to lift the weight.
        sun = mg.level_by_id('sun')
        flat = [{k: v for k, v in sun['solution'][0].items() if k not in ('yaw_deg', 'pitch_deg')}]
        shaded = [dict(sun['solution'][0], x_m=-0.8, z_m=0.6)]
        with tempfile.TemporaryDirectory() as logs:
            for lv, placed in ((level, high), (fire, weak), (laser, laser['solution'][:1]), (sun, flat), (sun, shaded)):
                t = mg.trial(lv, placed, ENGINE, Path(logs), runs=1)
                self.assertEqual(t['worked'], 0, lv['id'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
