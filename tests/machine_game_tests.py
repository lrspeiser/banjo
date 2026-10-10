"""The puzzles (/play, scripts/machine_game.py, client/voxel-lab/levels.json):
every level can be solved, cannot be solved without pieces, keeps to its tray,
and scores what the engine measured.

    python tests/machine_game_tests.py [--engine path/to/banjo_live_world_run]

Without an engine the tray and scoring tests still run; the engine tests are
skipped, never passed. Set BANJO_MACHINE_ENGINE=required to fail instead.
"""
import copy
import json
import os
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
        self.assertEqual([l['id'] for l in LEVELS], ['gap', 'cut', 'fire', 'steam', 'chain', 'laser'])
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
        wild = [dict(gap['solution'][0], top_m=9.0)]
        with self.assertRaises(mg.LevelRefused) as caught:
            mg.compose(gap, wild)
        self.assertIn('top_m is 0.1 to 0.5', ' '.join(caught.exception.problems))
        sneaky = [dict(gap['solution'][0], material='glass')]
        with self.assertRaises(mg.LevelRefused):
            mg.compose(gap, sneaky)
        fire = mg.level_by_id('fire')
        costly = [dict(fire['solution'][0], powder_g=3.0, x_m=1.4)]
        _, _, cost = mg.compose(fire, costly)
        self.assertEqual(cost, 34.0)   # 10 + 8 per gram

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
        self.assertEqual(r['placements'][0]['x_to_m'], 0.64)
        self.assertTrue(r['helped'])
        self.assertNotIn(json.dumps(level['solution']), json.dumps(seen[0]), 'the model is never shown the answer')
        # A knob past its range is brought to the end of the range, as the
        # slider would; a knob the piece does not have is left out.
        pulled = mc.respond_level('Place it', level, [], mode='build', call=lambda m: (
            {'reply': 'A long plank.', 'placements': [{'piece': 'plank', 'x_from_m': -0.1, 'x_to_m': 9.0,
                                                       'top_m': 0.3, 'colour': 'red'}]}, {}))
        self.assertEqual((pulled['placements'][0]['x_to_m'], 'colour' in pulled['placements'][0]), (0.7, False))
        # Several options: the first that is built is used.
        opts = mc.respond_level('Place it', level, [], mode='build', call=lambda m: (
            {'reply': 'Two ways.', 'options': [[{'piece': 'cannon'}], level['solution']]}, {}))
        self.assertEqual(opts['placements'][0]['x_from_m'], -0.04)
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
    def test_a_misplaced_piece_fails_for_a_physical_reason(self):
        # The knife set too high swings over the rope and into the weight's arm.
        level = mg.level_by_id('cut')
        high = [dict(level['solution'][0], pivot_height_m=level['solution'][0]['pivot_height_m'] + 0.2)]
        # The cannon too weak: its ball falls short of the block.
        fire = mg.level_by_id('fire')
        weak = [dict(fire['solution'][0], powder_g=0.5)]
        # One mirror where two are needed: the beam goes into the wall.
        laser = mg.level_by_id('laser')
        with tempfile.TemporaryDirectory() as logs:
            for lv, placed in ((level, high), (fire, weak), (laser, laser['solution'][:1])):
                t = mg.trial(lv, placed, ENGINE, Path(logs), runs=1)
                self.assertEqual(t['worked'], 0, lv['id'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
