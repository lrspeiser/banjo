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
EMPTY_START_LEVELS = ('easy-solar', 'easy-tackle', 'easy-spring', 'easy-gears',
                      'easy-water-wheel', 'easy-water-receiver')


class Tray(unittest.TestCase):
    def test_catalogue_bases_have_no_unrelated_reference_boxes(self):
        for row in mg.load_levels():
            self.assertFalse({'reference marker', 'channel marker'} &
                             {p['name'] for p in row['machine'].get('parts', [])}, row['id'])
        for row in mg.sandbox_templates():
            self.assertFalse({'reference marker', 'channel marker'} &
                             {p['name'] for p in (row['base'] or {}).get('parts', [])}, row['name'])
        gears = mg.level_by_id('easy-gears')
        self.assertEqual(mw.compile_spec(mg.compose(gears, [], leave_out_goal=True)[0])['parts'], [])
        compiled = mw.compile_spec(mg.compose(gears, gears['solution'])[0])
        self.assertIn('your gears 1 battery box', {p['name'] for p in compiled['parts']})
        self.assertEqual(compiled['batteries'][0]['in'], 'your gears 1 battery box')

    def test_edit_guides_follow_compiled_geometry_and_do_not_change_the_setup(self):
        free = mg.free_build()
        placement = [{'piece': 'plank', 'x_m': 0, 'z_m': 0, 'length_m': .6}]
        kept = copy.deepcopy(placement)
        ordinary = mg.ghost(free, placement, 0)
        annotated = mg.ghost(free, placement, 0, edit_key='length_m')
        guide = annotated.pop('edit_guide')
        self.assertEqual(annotated, ordinary)
        self.assertEqual(placement, kept)
        self.assertEqual(len(guide['arrows']), 2)
        self.assertEqual(sorted(a['direction'][0] for a in guide['arrows']), [-1, 1])
        self.assertEqual(sorted(round(a['at'][0], 6) for a in guide['arrows']), [-.3, .3])
        for yaw, pitch in ((90, 0), (37, 25), (-65, -35)):
            turned = [dict(placement[0], yaw_deg=yaw, pitch_deg=pitch)]
            guide = mg.ghost(free, turned, 0, edit_key='length_m')['edit_guide']
            axis = mw._mat_apply(mw.heading(yaw, pitch, 0), [1, 0, 0])
            self.assertEqual(len(guide['arrows']), 2)
            for a in guide['arrows']:
                self.assertAlmostEqual(abs(sum(v * w for v, w in zip(a['direction'], axis))), 1, places=5)
        track = [{'piece': 'track', 'x_m': 0, 'z_m': 0, 'yaw_deg': 90}]
        drop = mg.ghost(free, track, 0, edit_key='drop_m')['edit_guide']
        self.assertEqual(len(drop['arrows']), 1)
        self.assertLess(drop['arrows'][0]['direction'][1], -.9)
        self.assertLess(drop['arrows'][0]['at'][2], -.5, 'the lower end follows the turned board')
        end = mg.ghost(free, track, 0, edit_key='end')['edit_guide']
        self.assertLess(end['marker'][2], -.5)
        self.assertEqual(end['arrows'], [])
        for item in free['tray']:
            if item.get('attach'):
                continue
            for key, rule in item['knobs'].items():
                if key in ('x_m', 'z_m'):
                    continue
                values = rule.get('choices', [rule.get('default', rule.get('min')), rule.get('min'), rule.get('max')])
                for value in values:
                    if value is None:
                        continue
                    with self.subTest(piece=item['piece'], key=key, value=value):
                        context = copy.deepcopy(free)
                        if item['piece'] in ('water_wheel', 'water_tank'):
                            context['machine'] = copy.deepcopy(mg.sandbox_water_launch.CHANNEL_BASE)
                            context['custom_base'] = True
                        p = [{'piece': item['piece'], **{k: 0 for k in ('x_m', 'z_m') if k in item['knobs']}, key: value}]
                        before = mg.ghost(context, p, 0)
                        after = mg.ghost(context, p, 0, edit_key=key)
                        guide = after.pop('edit_guide')
                        self.assertEqual(after, before)
                        if rule.get('part') or rule.get('hinge') or rule.get('terminal') or rule.get('power_port') or not after['parts']:
                            self.assertIsNone(guide)
                            continue
                        self.assertEqual(guide['key'], key)
                        for arrow in guide['arrows']:
                            self.assertAlmostEqual(sum(v * v for v in arrow['direction']), 1, places=6)
        self.assertIsNone(mg.ghost(free, placement, 0, edit_key='unrecognised')['edit_guide'])

    def test_sandbox_templates_keep_the_base_and_readings_and_cannot_replace_a_level(self):
        for template in mg.sandbox_templates():
            level = mg.requested_level({'level': 'free', 'base': template['base']})
            spec, _, _ = mg.compose(level, template['placements'])
            compiled = mw.compile_spec(spec)
            self.assertTrue(compiled['parts'])
            if template['base']:
                self.assertEqual(spec['stations'], template['base'].get('stations', []))
                for part in template['base'].get('parts', []):
                    self.assertIn(part, spec['parts'], 'the base supports are preserved')
                for kit in template['base'].get('kits', []):
                    self.assertIn(kit, spec['kits'])
                g = mg.ghost(level, [{'piece': 'marble', 'x_m': -1.8, 'z_m': -1.8}], 0)
                self.assertTrue(g['fits'], g['problems'])
        base = mg.sandbox_templates()[1]['base']
        with self.assertRaisesRegex(ValueError, 'not a level'):
            mg.requested_level({'level': 'gap', 'base': base})
        bad = copy.deepcopy(mg.free_build()['machine'])
        bad['parts'].append({'name': 'your block 1', 'shape': 'box', 'material': 'oak', 'size_m': [.1, .1, .1], 'at_m': [0, .05, 0], 'fixed': True})
        with self.assertRaisesRegex(ValueError, 'reserved'):
            mg.requested_level({'level': 'free', 'base': bad})

    def test_every_level_is_well_formed_and_its_solution_fits_its_tray(self):
        self.assertEqual([l['id'] for l in LEVELS[:8]], ['gap', 'cut', 'fire', 'steam', 'chain', 'laser', 'sun', 'tackle'])
        self.assertEqual(len({l['id'] for l in LEVELS}), len(LEVELS))
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
                # A mirror turns about the vertical by its own angle_deg; a
                # counterweight on a rope is not something to turn.
                self.assertEqual(turning, ['angle_deg', 'pitch_deg', 'roll_deg'] if t['piece'] == 'mirror'
                                 else sorted(t['turns']) if 'turns' in t
                                 else [] if t.get('turning') is False or level.get('turning') is False
                                 else ['pitch_deg', 'roll_deg', 'yaw_deg'], level['id'])
                # Moved across too, but for a counterweight, which hangs in
                # line with the beam its rope runs along.
                if t.get('across') is False:
                    self.assertNotIn('z_m', t['knobs'])
                else:
                    self.assertIn('z_m', t['knobs'])
            # Unturned, a level's own solution is built exactly as before.
            spec, _, cost = mg.compose(level, level['solution'])
            self.assertFalse(any('turned' in k for k in spec['kits']), level['id'])
            knobs = {t['piece']: t['knobs'] for t in level['tray']}
            turned = [dict(p, **{k: v for k, v in (('pitch_deg', 10), ('roll_deg', -20)) if k in knobs[p['piece']]})
                      for p in level['solution']]
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
        self.assertEqual((g['fits'], [p['name'] for p in g['parts']]), (True, ['your mirror 2', 'your mirror 2 stand']))
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

    def test_nothing_floats(self):
        # Every fixed part stands on the ground or is bolted to one that does,
        # by a chain of them: the level's own (level 6's laser sits on its
        # post) and the player's wherever its knobs put it (a mirror on a
        # stand, a cannon's barrel, a ramp on two legs) -- as the solution has
        # it and with every knob at either end of its range.
        for level in LEVELS:
            tries = [level['solution']]
            for t in level['tray']:
                for end in ('min', 'max'):
                    p = {'piece': t['piece']}
                    for key, rule in t['knobs'].items():
                        p[key] = rule['choices'][-1 if end == 'max' else 0] if 'choices' in rule else (
                            knob_default(rule) if rule.get('turning') or any(rule.get(k) for k in ('part', 'terminal', 'hinge', 'power_port')) else rule[end])
                    tries.append([p])
            for placements in tries:
                parts = mg._assemble(level, placements, lenient=True)[3]['parts']
                held = mg.held_up(parts)
                with self.subTest(level=level['id'], placements=placements):
                    self.assertEqual([p['name'] for p in parts if p.get('fixed') and p['name'] not in held], [])
        # The stand is the piece's: shown with its ghost, standing on the ground.
        laser = mg.level_by_id('laser')
        stand = next(p for p in mg.ghost(laser, laser['solution'], 0)['parts'] if p['name'] == 'your mirror 1 stand')
        self.assertAlmostEqual(stand['at_m'][1] - 0.5 * stand['size_m'][1], 0.0, places=6)
        # Level 8's rope turns over pulley blocks hung from the beam, in line with it.
        tackle = mg.level_by_id('tackle')
        parts = {p['name']: p for p in mg._assemble(tackle, tackle['solution'])[3]['parts']}
        for name in ('your tackle 1 pulley 1', 'your tackle 1 pulley 2'):
            block, beam = parts[name], parts['gantry beam']
            self.assertAlmostEqual(block['at_m'][1] + 0.5 * block['size_m'][1], beam['at_m'][1] - 0.5 * beam['size_m'][1])
            self.assertEqual(block['at_m'][2], beam['at_m'][2])
        self.assertNotIn('z_m', tackle['tray'][0]['knobs'], 'a counterweight hangs in line with its beam')

    def test_every_level_opens_before_any_piece_is_placed(self):
        # Shown, not run: a goal about a piece not placed yet is left out and
        # what it needs is said. An empty learning field is also valid; its
        # native opening is checked separately below.
        for level in LEVELS:
            spec, _, _ = mg.compose(level, [], leave_out_goal=True)
            parts = mw.compile_spec(spec)['parts']
            if level['id'] in EMPTY_START_LEVELS:
                self.assertEqual(parts, [], level['id'])
            else:
                self.assertTrue(parts, level['id'])
        steam = mg.level_by_id('steam')
        spec, _, _ = mg.compose(steam, [], leave_out_goal=True)
        self.assertEqual((spec['_needs'], spec['stations']), ('Place a steam engine: the goal is its piston', []))
        spec, _, _ = mg.compose(steam, steam['solution'], leave_out_goal=True)
        self.assertNotIn('_needs', spec)
        self.assertEqual(spec['stations'][0]['title'], steam['goal']['title'])

    def test_a_win_is_scored_by_the_energy_it_took(self):
        # Making the pieces: mass (the engine's densities) times the material's
        # embodied energy. Level 1's 0.7 m oak plank is 2.94 kg, 30.6 MJ.
        gap = mg.level_by_id('gap')
        compiled = mw.compile_spec(mg.compose(gap, gap['solution'])[0])
        plank = mg.pieces_energy(compiled)['your plank 1']
        self.assertAlmostEqual(plank['kg'], 0.7 * 0.02 * 0.3 * 700.0, places=3)
        self.assertAlmostEqual(plank['j'], plank['kg'] * 10.4e6, delta=1.0)
        # Aluminium costs six times iron's energy a kilogram: on level 8 the
        # heavier iron counterweight takes less energy to make.
        tackle = mg.level_by_id('tackle')
        def made(kg, ratio, h):
            c = mw.compile_spec(mg.compose(tackle, [dict(tackle['solution'][0], counterweight_kg=kg, ratio=ratio,
                                                         drop_from_m=h)])[0])
            return mg.pieces_energy(c)['your tackle 1']['j']
        self.assertLess(made(7.9, 2, 1.2), made(4.7, 3, 1.75) / 3)
        # The run, each once: what the batteries gave, fuel burned in heaters
        # (level 4's 12 kW firebox, 2 s: 24 kJ), and the powder in the charges
        # (level 3's 1 g: 2.8 kJ). A coil's heat came out of a battery: the
        # engine's heat ledger counts it again, and it is not taken from there.
        steam = mg.level_by_id('steam')
        compiled = mw.compile_spec(mg.compose(steam, steam['solution'])[0])
        self.assertEqual(mg.run_energy(compiled, {}, 2.0)['heat_j'], 24000)
        fire = mg.level_by_id('fire')
        compiled = mw.compile_spec(mg.compose(fire, fire['solution'])[0])
        run = mg.run_energy(compiled, {'heat_ledger': {'heater_in_j': 2000.0}}, 1.0)
        # Millijoule receipts retain the compiled charge geometry's precision.
        self.assertEqual((run['heat_j'], run['powder_j'], run['electric_j']), (0, 2799.993, 0))
        # A person's test pull: the work it did counts; what pulled back does not.
        pulled = mg.run_energy(compiled, {'pulls': [{'body': 'x', 'work_j': 15.0}, {'body': 'y', 'work_j': -4.0}]}, 1.0)
        self.assertEqual((pulled['pull_j'], pulled['j']), (15, 2814.993))
        battery = {'batteries': [{'name': 'b', 'capacity_j': 1000.0, 'charge_j': 600.0}]}
        self.assertEqual(mg.run_energy(battery | {'parts': []},
                                       {'machines': {'batteries': [{'name': 'b', 'charge_j': 450.0}]}})['electric_j'], 150)
        # Stars: the goal, within a quarter of par, at or under par.
        par = gap['par_energy_j']
        checked = mg.check_placements(gap, gap['solution'])[0]
        self.assertEqual([mg.stars(gap, checked, 21, 1.9, energy_j=e)['stars'] for e in (par, 1.2 * par, 1.3 * par)],
                         [3, 2, 1])
        self.assertEqual(mg.stars(gap, checked, 21, None, energy_j=par)['stars'], 0)
        self.assertEqual(mg.stars(gap, checked, 21, 1.9, helped=True, energy_j=par)['stars'], 1)
        self.assertTrue(all(level.get('par_energy_j') for level in LEVELS), 'every level has an energy par')

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


def knob_default(rule):
    return rule['default'] if 'default' in rule else rule['choices'][0] if 'choices' in rule else rule['min']


class FreeBuild(unittest.TestCase):
    FREE = mg.level_by_id('free')

    def test_named_connections_keep_identity_and_can_target_later_placements(self):
        free = mg.requested_level({'level': 'free', 'base': mg.sandbox_water_launch.CHANNEL_BASE})
        placed = [{'piece':'water_wheel','side':'off','load_part':'your weight 2'},
                  {'piece':'weight','x_m':1,'z_m':.7,'height_m':.5,'mount':'guided'}]
        spec = mg.compose(free, placed)[0]
        compiled = mw.compile_spec(spec)
        self.assertTrue(any(j.get('load') == 'your weight 2' and j['kind'] == 'drum' for j in compiled['joints']))
        with self.assertRaisesRegex(mg.LevelRefused, 'not present'):
            mg.compose(free, [dict(placed[0], load_part='your weight 99')])

    def test_attach_spring_preserves_real_picked_points_and_parameters(self):
        placed = [{'piece':'block','x_m':-.5,'z_m':0,'tall_m':.2},
                  {'piece':'plank','x_m':.5,'z_m':0,'length_m':.2},
                  {'piece':'link','kind':'spring','a':'your block 1','b':'your plank 2',
                   'at_m':[-.5,.2,0],'at_b_m':[.5,.05,0],'rest_m':.9,'stiffness_n_m':80,'damping_n_s_m':2}]
        compiled = mw.compile_spec(mg.compose(self.FREE, placed)[0])
        joint = next(j for j in compiled['joints'] if j['name'] == 'your link 3')
        self.assertEqual(joint['kind'], 'spring')
        self.assertEqual(joint['at_m'], placed[-1]['at_m'])
        for key in ('rest_m','stiffness_n_m','damping_n_s_m'):
            self.assertEqual(joint[key], placed[-1][key])

    def test_the_free_build_has_no_goal_and_every_piece(self):
        free = self.FREE
        self.assertIsNone(free['goal'])
        pieces = [t['piece'] for t in free['tray']]
        for p in ('marble', 'track', 'shelf', 'flipflop', 'block', 'dominoes', 'lever', 'plank', 'ramp', 'cannon', 'steam'):
            self.assertIn(p, pieces)
        self.assertNotIn('free', [l['id'] for l in LEVELS], 'it is not one of the numbered levels')
        spec, checked, cost = mg.compose(free, [])
        self.assertEqual(spec['stations'], [], 'nothing to do but watch')
        shown = mg.public(free)
        self.assertTrue(shown['free'])
        self.assertEqual(shown['example'], free['example'])
        # A track turns only about the upright; a marble does not turn at all.
        knobs = {t['piece']: t['knobs'] for t in free['tray']}
        self.assertIn('yaw_deg', knobs['track'])
        self.assertNotIn('pitch_deg', knobs['track'])
        self.assertFalse({'yaw_deg', 'pitch_deg', 'roll_deg'} & set(knobs['marble']))

    def test_every_free_piece_fits_as_it_comes(self):
        for t in self.FREE['tray']:
            if t.get('attach'):
                continue      # a link is made by joining two parts, not from the tray
            placed = dict({k: knob_default(r) for k, r in t['knobs'].items()}, piece=t['piece'])
            context = copy.deepcopy(self.FREE)
            if t['piece'] in ('water_wheel', 'water_tank'):
                context['machine'] = copy.deepcopy(mg.sandbox_water_launch.CHANNEL_BASE)
                context['custom_base'] = True
            g = mg.ghost(context, [placed], 0)
            with self.subTest(piece=t['piece']):
                if t['piece'] in ('wire', 'power_cable'):
                    self.assertFalse(g['fits'], 'a wire needs two real terminals')
                    self.assertIn('terminal' if t['piece'] == 'wire' else 'power input', ' '.join(g['problems']))
                    continue
                self.assertTrue(g['fits'], g['problems'])
                self.assertTrue(g['parts'])

    def test_a_marble_is_set_down_on_what_is_under_it(self):
        # On a shelf it rests on the shelf; on a sloping track it rests on the
        # slope, touching it and in none of it.
        free = self.FREE
        shelf = {'piece': 'shelf', 'x_m': 0.0, 'z_m': 0.0, 'top_height_m': 0.8, 'run_m': 0.4, 'drop_m': 0.015, 'end': 'gate'}
        g = mg.ghost(free, [shelf, {'piece': 'marble', 'x_m': 0.1, 'z_m': 0.0}], 1)
        self.assertTrue(g['fits'], g['problems'])
        surface = 0.8 - 0.015 * 0.1 / 0.4
        self.assertAlmostEqual(g['parts'][0]['at_m'][1], surface + 0.02, delta=0.004)
        track = {'piece': 'track', 'x_m': 0.0, 'z_m': 0.0, 'top_height_m': 0.6, 'run_m': 0.6, 'drop_m': 0.3, 'end': 'open'}
        spec, _, _ = mg.compose(free, [track, {'piece': 'marble', 'x_m': 0.3, 'z_m': 0.0}])
        c = mw.compile_spec(spec)
        marble = next(p for p in c['parts'] if p['name'] == 'your marble 2')
        board = next(p for p in c['parts'] if p['name'] == 'your track 1')
        gap = -mw.overlap_depth(marble, board)
        self.assertGreaterEqual(gap, 0.0)
        self.assertLess(gap, 0.004, 'it rests on the slope, not on top of the slope\'s box')

    def test_a_piece_moved_near_another_snaps_where_they_connect(self):
        free = self.FREE
        first = {'piece': 'track', 'x_m': 0.0, 'z_m': 0.0, 'top_height_m': 0.8, 'run_m': 0.6, 'drop_m': 0.1, 'end': 'open'}
        # A track's top end near the first's far end (0.6, 0.7, 0): just under
        # it and a little past it, turned however it was turned.
        second = {'piece': 'track', 'x_m': 0.65, 'z_m': 0.05, 'top_height_m': 0.3, 'run_m': 0.6, 'drop_m': 0.1,
                  'end': 'open', 'yaw_deg': 90}
        g = mg.ghost(free, [first, second], 1, snapping=True)
        self.assertEqual(g['snap']['to'], 'your track 1')
        self.assertEqual(g['snap']['port'], 'far end')
        self.assertEqual(g['snap']['knobs'], {'x_m': 0.63, 'z_m': 0.0, 'top_height_m': 0.66})
        # Only a piece moved by hand is snapped; one already there says what it is joined to.
        self.assertNotIn('snap', mg.ghost(free, [first, second], 1))
        there = dict(second, **g['snap']['knobs'])
        self.assertFalse(mg.ghost(free, [first, there], 1)['snap']['moved'])
        # A flip-flop under the far end: its middle under it, its board behind
        # it the way the marbles come.
        ff = {'piece': 'flipflop', 'x_m': 0.62, 'z_m': 0.03, 'height_m': 0.3, 'tipped': 'left'}
        snapped = mg.ghost(free, [first, ff], 1, snapping=True)['snap']['knobs']
        self.assertEqual(snapped, {'x_m': 0.64, 'z_m': 0.0, 'height_m': 0.59, 'yaw_deg': -90})
        # A track's far end over a gate's paddle, short of it the way it runs.
        shelf = {'piece': 'shelf', 'x_m': -0.6, 'z_m': 0.0, 'top_height_m': 0.8, 'run_m': 0.4, 'drop_m': 0.015,
                 'end': 'gate that stays open'}
        trigger = {'piece': 'track', 'x_m': -0.6, 'z_m': 0.12, 'top_height_m': 1.0, 'run_m': 0.36, 'drop_m': 0.03, 'end': 'open'}
        g = mg.ghost(free, [shelf, trigger], 1, snapping=True)
        paddle = next(q for q in g['ports'] if q['kind'] == 'trigger')
        self.assertEqual(g['snap']['port'], 'gate paddle')
        far = [g['snap']['knobs']['x_m'] + 0.36, g['snap']['knobs']['top_height_m'] - 0.03]
        self.assertAlmostEqual(far[0], paddle['at'][0] - 0.05, places=3)
        self.assertAlmostEqual(far[1], paddle['at'][1] + 0.065, places=3)
        # A marble near a track's top end sits just in from it.
        g = mg.ghost(free, [first, {'piece': 'marble', 'x_m': 0.04, 'z_m': 0.02}], 1, snapping=True)
        self.assertEqual(g['snap']['knobs'], {'x_m': 0.05, 'z_m': 0.0})
        # Nothing near: nothing snaps.
        far_away = dict(second, x_m=1.5, z_m=1.5)
        self.assertNotIn('snap', mg.ghost(free, [first, far_away], 1, snapping=True))

    def test_two_parts_are_joined_by_glue_a_pin_or_a_string(self):
        free = self.FREE
        block = {'piece': 'block', 'x_m': 0.0, 'z_m': 0.0, 'tall_m': 0.2}
        plank = {'piece': 'plank', 'x_m': 0.0, 'z_m': 0.0, 'length_m': 0.6}
        for kind, extra, joint in (('glue', {}, 'fix'), ('pin', {'axis': 'along z'}, 'hinge'),
                                   ('string', {'at_b_m': [0.2, 0.25, 0.0]}, 'tie')):
            link = dict({'piece': 'link', 'kind': kind, 'a': 'your block 1', 'b': 'your plank 2', 'at_m': [0.0, 0.2, 0.0]}, **extra)
            spec, _, _ = mg.compose(free, [block, plank, link])
            made = next(j for j in mw.compile_spec(spec)['joints'] if j['name'] == 'your link 3')
            self.assertEqual(made['kind'], joint)
            if kind == 'pin':
                self.assertEqual(made['axis'], [0.0, 0.0, 1.0])
            if kind == 'string':
                self.assertAlmostEqual(made['length_m'], math.dist([0.0, 0.2, 0.0], [0.2, 0.25, 0.0]), places=4)
        with self.assertRaises(mg.LevelRefused):
            mg.compose(free, [block, dict(link, b='your block 1')])
        with self.assertRaisesRegex(mg.LevelRefused, 'not present'):
            mg.compose(free, [block, plank, dict(link, b='your plank 9')])

    def test_the_chat_builds_by_joining_pieces_and_the_server_lays_them_out(self):
        # The model says which pieces and what each joins to; the server puts
        # them there: marbles lined up on a shelf behind its gate, a trigger
        # track's far end over the gate's paddle, a flip-flop under the shelf's
        # end, a track running on from each of its ends -- then the whole build
        # in the middle of the table.
        free = self.FREE
        answer = {'reply': 'A shelf of marbles, a trigger, and a flip-flop.', 'clear': True, 'add': [
            {'piece': 'shelf', 'x_m': 1.5, 'z_m': 1.5, 'top_height_m': 0.8, 'run_m': 0.4, 'drop_m': 0.015,
             'end': 'gate that stays open'},
            {'piece': 'marble', 'join': {'to': 1, 'port': 'top end'}},
            {'piece': 'marble', 'join': {'to': 1, 'port': 'top end'}},
            {'piece': 'marble', 'join': {'to': 1, 'port': 'top end'}},
            {'piece': 'track', 'run_m': 0.36, 'drop_m': 0.03, 'join': {'to': 1, 'port': 'gate paddle'}},
            {'piece': 'marble', 'join': {'to': 5, 'port': 'top end'}},
            {'piece': 'flipflop', 'join': {'to': 1, 'port': 'far end'}},
            {'piece': 'track', 'run_m': 0.6, 'drop_m': 0.08, 'end': 'stop', 'join': {'to': 7, 'port': 'left end'}},
            {'piece': 'track', 'run_m': 0.6, 'drop_m': 0.08, 'end': 'stop', 'join': {'to': 7, 'port': 'right end'}}]}
        asked = []

        def call(messages):
            asked.append(messages)
            return (answer if len(asked) > 1 else dict(answer, add=answer['add'] + [{'piece': 'spaceship'}])), {}
        r = mc.respond_free('Hold three marbles up high, then split them two ways.', free, [], call=call)
        self.assertEqual(len(asked), 2, 'a refused build is sent back once with why')
        self.assertIn('spaceship is not a piece', asked[1][-1]['content'])
        placed = r['placements']
        self.assertEqual([p['piece'] for p in placed],
                         ['shelf', 'marble', 'marble', 'marble', 'track', 'marble', 'flipflop', 'track', 'track'])
        spec, checked, _ = mg.compose(free, placed)
        compiled = mw.compile_spec(spec)
        found = mg.ports(checked, compiled)
        port = lambda i, name: next(q for q in found if q['piece'] == i and q['port'] == name)
        # Marbles lined up from the shelf's top end, 4.5 cm apart.
        xs = [placed[i]['x_m'] for i in (1, 2, 3)]
        self.assertAlmostEqual(xs[0], port(0, 'top end')['at'][0] + 0.05, places=3)
        self.assertAlmostEqual(xs[1] - xs[0], 0.045, places=3)
        self.assertAlmostEqual(xs[2] - xs[1], 0.045, places=3)
        # The trigger track's far end 5 cm short of the paddle and 6.5 cm over it.
        paddle, far = port(0, 'gate paddle')['at'], port(4, 'far end')['at']
        self.assertAlmostEqual(far[0], paddle[0] - 0.05, places=3)
        self.assertAlmostEqual(far[1], paddle[1] + 0.065, places=3)
        # The flip-flop's middle 4 cm past the shelf's far end, 11 cm under it; its
        # tracks run on from its ends, away from it.
        shelf_far, middle = port(0, 'far end')['at'], port(6, 'middle')['at']
        self.assertAlmostEqual(middle[0], shelf_far[0] + 0.04, places=3)
        self.assertAlmostEqual(middle[1], shelf_far[1], places=3)
        for i, end in ((7, 'left end'), (8, 'right end')):
            self.assertEqual(port(i, 'top end')['dir'], port(6, end)['dir'])
        # And the whole build moved to the middle of the table.
        boxes = [(sd['at_m'], mg._reach(sd)) for p in compiled['parts'] if mg.owner(p) for sd in mw.solids_of(p)]
        for i in (0, 2):
            middle_of = 0.5 * (min(c[i] - r[i] for c, r in boxes) + max(c[i] + r[i] for c, r in boxes))
            self.assertLess(abs(middle_of), 0.011)

    def test_a_bend_turns_a_track_and_its_ends_connect(self):
        free = self.FREE
        entry = {'piece': 'track', 'x_m': -0.6, 'z_m': 0.0, 'top_height_m': 0.6, 'run_m': 0.6, 'drop_m': 0.06, 'end': 'open'}
        bend = {'piece': 'bend', 'x_m': 0.05, 'z_m': 0.05, 'top_height_m': 0.3, 'turn_deg': 90, 'radius_m': 0.3, 'drop_m': 0.04}
        g = mg.ghost(free, [entry, bend], 1, snapping=True)
        self.assertEqual((g['snap']['to'], g['snap']['port']), ('your track 1', 'far end'))
        bend = dict(bend, **g['snap']['knobs'])
        spec, checked, _ = mg.compose(free, [entry, bend])
        compiled = mw.compile_spec(spec)
        boards = [p for p in compiled['parts'] if p['name'].startswith('your bend 2 ') and 'rail' not in p['name']]
        self.assertEqual(len(boards), 4, 'a section for every 22.5 degrees')
        far = next(q for q in mg.ports(checked, compiled) if q['piece'] == 1 and q['port'] == 'far end')
        # Turned 90 degrees to the left: it leaves toward -z, 0.3 m across and 0.3 m along from where it began.
        self.assertAlmostEqual(far['dir'][2], -1.0, places=6)
        self.assertAlmostEqual(far['at'][0] - bend['x_m'], 0.3, places=3)
        self.assertAlmostEqual(far['at'][2] - bend['z_m'], -0.3, places=3)

    def test_the_example_is_built_as_it_is_written(self):
        spec, checked, cost = mg.compose(self.FREE, self.FREE['example'])
        c = mw.compile_spec(spec)
        names = {p['name'] for p in c['parts']}
        self.assertIn('your flipflop 8', names)
        self.assertIn('your dominoes 11 6', names)
        gate = next(j for j in c['joints'] if j['name'] == 'your shelf 1 barrier pin')
        self.assertIn('ratchet', gate, 'its shelf\'s gate stays open')


class Engine(unittest.TestCase):
    @need_engine
    def test_empty_learning_fields_open_and_step_without_dummy_bodies(self):
        for identity in EMPTY_START_LEVELS:
            with self.subTest(level=identity), tempfile.TemporaryDirectory() as logs:
                spec = mg.compose(mg.level_by_id(identity), [], leave_out_goal=True)[0]
                compiled = mw.compile_spec(spec)
                self.assertEqual(compiled['parts'], [])
                engine, _, _ = mw.build_engine(ENGINE, compiled, logs)
                try:
                    self.assertEqual(engine.first['bodies'], [])
                    reply = engine.op(op='step', dt=.002, n=1, moved=False)
                    self.assertTrue(reply['ok'])
                    self.assertEqual(reply['bodies'], [])
                finally:
                    engine.close()

    @need_engine
    def test_generated_recipe_reopens_after_cache_loss_without_exposing_answers(self):
        with tempfile.TemporaryDirectory() as logs:
            generated = mg.fresh_easy('easy-loop', 42, ENGINE, logs)
            public = mg.public(generated)
            self.assertTrue(public['variant']['validated'])
            self.assertNotIn('solution', public)
            self.assertNotIn('wrong', public)
            self.assertNotIn('validation', public['variant'])
            self.assertNotIn('attempts', public['variant'])
            kept = copy.deepcopy(generated)
            retrieved = mg.level_by_id(generated['id'])
            retrieved['machine']['title'] = 'changed outside the cache'
            self.assertEqual(mg.level_by_id(generated['id']), kept)
            mg._variants.clear(); mg._variant_requests.clear()
            with self.assertRaises(ValueError): mg.level_by_id(generated['id'])
            recreated = mg.fresh_easy('easy-loop', 42, ENGINE, logs, recipe_id=generated['id'])
            self.assertEqual(recreated['machine'], generated['machine'])
            self.assertEqual(recreated['goal'], generated['goal'])
            self.assertEqual(recreated['par_energy_j'], generated['par_energy_j'])
            with self.assertRaises(ValueError):
                mg.fresh_easy('easy-loop', 43, ENGINE, logs, recipe_id=generated['id'])

    @need_engine
    def test_rehearsed_water_energy_keeps_the_measured_source_work(self):
        level = mg.level_by_id('easy-water-receiver')
        spec, _, _ = mg.compose(level, level['solution'])
        compiled = mw.compile_spec(spec)
        with tempfile.TemporaryDirectory() as logs:
            result = mw.rehearse(compiled, ENGINE, logs, seconds=3)
        self.assertIn('pour', result['readouts'])
        energy = mg.energy_of(compiled, result['readouts'], result['world_time_s'])
        self.assertGreater(energy['run']['water_j'], 1)
        supplied = sum(source['source_energy_j'] for source in result['readouts']['pour']['sources'])
        # Preserve millijoules so small mechanical input is not rounded away.
        self.assertEqual(energy['run']['water_j'], round(supplied,3))

    @need_engine
    def test_sandbox_chain_runs_the_same_declaration_with_live_readings(self):
        template = mg.sandbox_templates()[1]
        spec, _, _ = mg.compose(mg.requested_level({'level': 'free', 'base': template['base']}), [])
        compiled = mw.compile_spec(spec)
        with tempfile.TemporaryDirectory() as logs:
            r = mw.rehearse(compiled, ENGINE, Path(logs), seconds=40.0, wall_limit_s=200,
                            track=['water wheel', 'marble'], after_s=0.25)
        self.assertTrue(r['stations'], 'readings were not discarded by composition')
        self.assertIsNone(r['error'])
        self.assertTrue(all(s['done'] for s in r['stations']), r['stations'])
        times = [s['at_s'] for s in r['stations']]
        self.assertEqual(times, sorted(times), 'the base chain happened in order')
        self.assertNotEqual(r['paths']['water wheel']['turn_wxyz'], [1, 0, 0, 0], 'the wheel turned in the engine')
        print(f'\n  Sandbox chain: all {len(times)} stations in order at {times}; wall {r["wall_s"]} s')

    @need_engine
    def test_the_free_builds_example_works_and_its_preview_follows_the_marbles(self):
        # A marble rolls onto the gate's paddle; the gate opens and its catch
        # holds it. The marbles waiting on the shelf roll down to the
        # flip-flop, which sends them to the stop and to the dominoes, and
        # every domino falls -- in the run as written and nudged a little.
        free = mg.level_by_id('free')
        spec, _, _ = mg.compose(free, free['example'])
        compiled = mw.compile_spec(spec)
        waiting = ('your marble 2', 'your marble 3', 'your marble 4')
        with tempfile.TemporaryDirectory() as logs:
            for seed in (0, 1, 2):
                s = mw.MachineSession(mg.nudged(compiled, seed) if seed else compiled, ENGINE, Path(logs), paced=False)
                try:
                    s.play(True)
                    began = time.perf_counter()
                    while time.perf_counter() - began < 120:
                        with s.lock:
                            if s.t >= 8.0 or s.error:
                                break
                            s.lock.wait(0.05)
                    with s.lock:
                        self.assertIsNone(s.error)
                        ends = {n: s.bodies[n]['position_m'] for n in waiting}
                        down = sum(1 for n, b in s.bodies.items() if 'dominoes' in n and b['position_m'][1] < 0.045)
                        events = [e['text'] for e in s.events]
                finally:
                    s.close()
                stopped = sum(1 for p in ends.values() if p[2] < -0.5 and p[1] > 0.1)
                beyond = sum(1 for p in ends.values() if p[2] > 0.3)
                print(f'\n  example, nudge {seed}: {stopped} at the stop, {beyond} to the dominoes, {down} dominoes down')
                self.assertTrue(any('caught on its ratchet' in e for e in events))
                self.assertGreaterEqual(stopped, 1)
                self.assertGreaterEqual(beyond, 1)
                self.assertEqual(down, 6)
            shown = mg.preview(free, free['example'], ENGINE, Path(logs))
        self.assertIsNone(shown['goal_at_s'])
        self.assertTrue(shown['paths'][0]['name'].startswith('your marble'), 'the marbles are followed first')

    @need_engine
    def test_a_marble_goes_from_a_track_onto_the_one_snapped_to_it_and_a_pin_makes_a_seesaw(self):
        free = mg.level_by_id('free')
        first = {'piece': 'track', 'x_m': 0.0, 'z_m': 0.0, 'top_height_m': 0.8, 'run_m': 0.6, 'drop_m': 0.1, 'end': 'open'}
        second = {'piece': 'track', 'x_m': 0.65, 'z_m': 0.05, 'top_height_m': 0.4, 'run_m': 0.6, 'drop_m': 0.1, 'end': 'stop'}
        second = dict(second, **mg.ghost(free, [first, second], 1, snapping=True)['snap']['knobs'])
        marble = dict({'piece': 'marble', 'x_m': 0.04, 'z_m': 0.02})
        placed = [first, second, marble]
        marble = dict(marble, **mg.ghost(free, placed, 2, snapping=True)['snap']['knobs'])
        spec, _, _ = mg.compose(free, [first, second, marble])

        def ran(spec, seconds):
            with tempfile.TemporaryDirectory() as logs:
                s = mw.MachineSession(mw.compile_spec(spec), ENGINE, Path(logs), paced=False)
                try:
                    s.play(True)
                    began = time.perf_counter()
                    while time.perf_counter() - began < 120:
                        with s.lock:
                            if s.t >= seconds or s.error:
                                break
                            s.lock.wait(0.05)
                    with s.lock:
                        return s.error, {n: dict(b) for n, b in s.bodies.items()}, [e['text'] for e in s.events]
                finally:
                    s.close()
        error, bodies, events = ran(spec, 3.0)
        self.assertIsNone(error)
        end = bodies['your marble 3']['position_m']
        print(f'\n  snapped tracks: the marble ended at {[round(v, 3) for v in end]}')
        # At the second track's stop, 1.2 m along, on the track.
        self.assertAlmostEqual(end[0], second['x_m'] + 0.6 - 0.02 - 0.02, delta=0.02)
        self.assertGreater(end[1], 0.25)
        # A plank on a block, pinned at its middle: a marble dropped on one end
        # tips it about the pin, and it stays on the pin; glued, it does not tip.
        block = {'piece': 'block', 'x_m': 0.0, 'z_m': 0.0, 'tall_m': 0.2, 'length_m': 0.02, 'depth_m': 0.1}
        plank = {'piece': 'plank', 'x_m': 0.0, 'z_m': 0.0, 'length_m': 0.6}
        built = mg.compose(free, [block, plank])[0]
        top = next(p for p in mw.compile_spec(built)['parts'] if p['name'] == 'your plank 2')['at_m']
        for kind, tips in (('pin', True), ('glue', False)):
            link = {'piece': 'link', 'kind': kind, 'a': 'your block 1', 'b': 'your plank 2', 'at_m': [0.0, top[1], 0.0],
                    'axis': 'along z'}
            spec = mg.compose(free, [block, plank, link])[0]
            spec['parts'].append({'name': 'dropped', 'shape': 'sphere', 'material': 'iron', 'size_m': [0.06] * 3,
                                  'at_m': [0.25, 0.8, 0.0]})
            error, bodies, events = ran(spec, 1.5)
            self.assertIsNone(error)
            q = bodies['your plank 2']['orientation_wxyz']
            tipped = 2 * math.degrees(math.acos(min(1.0, abs(q[0]))))
            print(f'  {kind}: the plank turned {tipped:.1f} degrees, its middle at {[round(v, 3) for v in bodies["your plank 2"]["position_m"]]}')
            self.assertLess(math.dist(bodies['your plank 2']['position_m'], top), 0.02, 'it stays on its pin')
            if tips:
                self.assertGreater(tipped, 5.0)
            else:
                self.assertLess(tipped, 1.0)

    @need_engine
    def test_marbles_held_on_a_shelf_are_split_three_ways_by_joined_pieces(self):
        # Built from joins alone, as the chat builds: a shelf whose gate stays
        # open, four marbles lined up on it, a trigger track over its paddle
        # with a marble on it, a long track from the shelf, a flip-flop, and a
        # second flip-flop on its right end; a track with a stop on each of the
        # three ends left. Every marble let go ends on one of the three tracks.
        free = mg.level_by_id('free')
        add = [{'piece': 'shelf', 'top_height_m': 0.9, 'run_m': 0.4, 'drop_m': 0.015, 'end': 'gate that stays open'}]
        add += [{'piece': 'marble', 'join': {'to': 1, 'port': 'top end'}}] * 3
        add += [{'piece': 'track', 'run_m': 0.36, 'drop_m': 0.03, 'join': {'to': 1, 'port': 'gate paddle'}},
                {'piece': 'marble', 'join': {'to': 5, 'port': 'top end'}},
                {'piece': 'marble', 'join': {'to': 1, 'port': 'top end'}},
                {'piece': 'track', 'run_m': 0.9, 'drop_m': 0.08, 'join': {'to': 1, 'port': 'far end'}},
                {'piece': 'flipflop', 'join': {'to': 8, 'port': 'far end'}},
                {'piece': 'track', 'run_m': 0.6, 'drop_m': 0.08, 'end': 'stop', 'join': {'to': 9, 'port': 'left end'}},
                {'piece': 'flipflop', 'join': {'to': 9, 'port': 'right end'}},
                {'piece': 'track', 'run_m': 0.6, 'drop_m': 0.08, 'end': 'stop', 'join': {'to': 11, 'port': 'left end'}},
                {'piece': 'track', 'run_m': 0.6, 'drop_m': 0.08, 'end': 'stop', 'join': {'to': 11, 'port': 'right end'}}]
        answer = {'reply': '', 'clear': True, 'add': add}
        placed = mc.respond_free('Split them three ways.', free, [], call=lambda messages: (answer, {}))['placements']
        spec, _, _ = mg.compose(free, placed)
        compiled = mw.compile_spec(spec)
        with tempfile.TemporaryDirectory() as logs:
            s = mw.MachineSession(compiled, ENGINE, Path(logs), paced=False)
            try:
                s.play(True)
                began = time.perf_counter()
                while time.perf_counter() - began < 120:
                    with s.lock:
                        if s.t >= 10.0 or s.error:
                            break
                        s.lock.wait(0.05)
                with s.lock:
                    self.assertIsNone(s.error)
                    ends = {n: mg.resting_on(compiled, s.bodies[n]['position_m'], 0.02)
                            for n in ('your marble 2', 'your marble 3', 'your marble 4', 'your marble 7')}
            finally:
                s.close()
        print(f'\n  three ways: {ends}')
        self.assertTrue(set(ends.values()) <= {'your track 10', 'your track 12', 'your track 13'}, ends)
        self.assertGreaterEqual(len(set(ends.values())), 2, 'they went more than one way')

    @need_engine
    def test_a_funnel_gathers_what_lands_anywhere_on_it_into_its_hole(self):
        # Marbles dropped on its corners, its edges and near its middle all go
        # down through its hole, near its middle; and a funnel moved near a
        # track's far end goes under it.
        free = mg.level_by_id('free')
        funnel = {'piece': 'funnel', 'x_m': 0.0, 'z_m': 0.0, 'height_m': 0.5, 'size_m': 0.4}
        base = mg.compose(free, [funnel])[0]
        hole = 0.5 - 0.12
        for x, z in ((0.15, 0.15), (-0.15, -0.15), (0.17, 0.0), (0.0, -0.17), (-0.08, 0.02)):
            spec = copy.deepcopy(base)
            spec['parts'].append({'name': 'm', 'shape': 'sphere', 'material': 'iron', 'size_m': [0.04] * 3, 'at_m': [x, 0.75, z]})
            with tempfile.TemporaryDirectory() as logs:
                s = mw.MachineSession(mw.compile_spec(spec), ENGINE, Path(logs), paced=False)
                try:
                    s.play(True)
                    began, last, crossed = time.perf_counter(), None, None
                    while time.perf_counter() - began < 60 and crossed is None:
                        with s.lock:
                            if s.t >= 2.0 or s.error:
                                break
                            at = list(s.bodies['m']['position_m'])
                            if last is not None and last[1] >= hole > at[1]:
                                crossed = at
                            last = at
                            s.lock.wait(0.005)
                finally:
                    s.close()
            with self.subTest(dropped_at=(x, z)):
                self.assertIsNotNone(crossed, 'it went down past the hole')
                self.assertLess(math.hypot(crossed[0], crossed[2]), 0.03, f'through the hole: {crossed}')
        track = {'piece': 'track', 'x_m': -0.6, 'z_m': 0.0, 'top_height_m': 0.9, 'run_m': 0.6, 'drop_m': 0.1, 'end': 'open'}
        g = mg.ghost(free, [track, dict(funnel, x_m=0.05, z_m=0.03)], 1, snapping=True)
        self.assertEqual(g['snap']['port'], 'far end')
        self.assertEqual(g['snap']['knobs'], {'x_m': 0.06, 'z_m': 0.0, 'height_m': 0.72})

    @need_engine
    def test_a_marble_goes_round_a_bend(self):
        # Down a track, round a bend 90 degrees either way and onto the track
        # snapped to its far end, to that track's stop.
        free = mg.level_by_id('free')
        for turn in (90, -90):
            entry = {'piece': 'track', 'x_m': -0.6, 'z_m': 0.0, 'top_height_m': 0.6, 'run_m': 0.6, 'drop_m': 0.06,
                     'end': 'open'}
            bend = {'piece': 'bend', 'x_m': 0.05, 'z_m': 0.05, 'top_height_m': 0.3, 'turn_deg': turn, 'radius_m': 0.3,
                    'drop_m': 0.04}
            bend = dict(bend, **mg.ghost(free, [entry, bend], 1, snapping=True)['snap']['knobs'])
            out = next(q for q in mg.ports(*[mg.check_placements(free, [entry, bend])[0],
                                              mw.compile_spec(mg.compose(free, [entry, bend])[0])])
                       if q['piece'] == 1 and q['port'] == 'far end')
            leave = {'piece': 'track', 'x_m': out['at'][0] + 0.05, 'z_m': out['at'][2] + 0.05, 'top_height_m': 0.1,
                     'run_m': 0.6, 'drop_m': 0.05, 'end': 'stop',
                     'yaw_deg': round(math.degrees(math.atan2(-out['dir'][2], out['dir'][0])))}
            leave = dict(leave, **mg.ghost(free, [entry, bend, leave], 2, snapping=True)['snap']['knobs'])
            spec, _, _ = mg.compose(free, [entry, bend, leave, {'piece': 'marble', 'x_m': -0.55, 'z_m': 0.0}])
            with tempfile.TemporaryDirectory() as logs:
                s = mw.MachineSession(mw.compile_spec(spec), ENGINE, Path(logs), paced=False)
                try:
                    s.play(True)
                    began = time.perf_counter()
                    while time.perf_counter() - began < 120:
                        with s.lock:
                            if s.t >= 4.0 or s.error:
                                break
                            s.lock.wait(0.05)
                    with s.lock:
                        self.assertIsNone(s.error)
                        end = s.bodies['your marble 4']['position_m']
                finally:
                    s.close()
            stop = [leave['x_m'] + 0.56 * out['dir'][0], leave['z_m'] + 0.56 * out['dir'][2]]
            print(f'\n  bend {turn}: the marble ended at {[round(v, 3) for v in end]}, the stop is at {[round(v, 3) for v in stop]}')
            self.assertLess(math.hypot(end[0] - stop[0], end[2] - stop[1]), 0.05, 'at the stop of the track after the bend')
            self.assertGreater(end[1], 0.05, 'on the track, not the ground')

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
    def test_each_levels_par_is_what_its_own_solution_takes(self):
        # Measured, rounded up to three figures: the level's own answer wins
        # on par, and a better one (level 1's plank a little shorter) beats it.
        with tempfile.TemporaryDirectory() as logs:
            for level in LEVELS:
                m = mg.measure_energy(level, level['solution'], ENGINE, Path(logs))
                with self.subTest(level=level['id']):
                    self.assertIsNotNone(m['goal_at_s'])
                    self.assertLessEqual(m['j'], level['par_energy_j'])
                    self.assertGreater(m['j'], 0.99 * level['par_energy_j'])
            gap = mg.level_by_id('gap')
            shorter = mg.measure_energy(gap, [dict(gap['solution'][0], length_m=0.66)], ENGINE, Path(logs))
        self.assertIsNotNone(shorter['goal_at_s'])
        self.assertLess(shorter['j'], gap['par_energy_j'])

    @need_engine
    def test_the_preview_is_the_engines_rehearsal_of_where_things_go(self):
        # Level 1 as it stands, then with the plank over the gap: the ball's
        # path, what it hits on the way, and when the goal happens -- the
        # same time the run itself gives.
        gap = mg.level_by_id('gap')
        with tempfile.TemporaryDirectory() as logs:
            bare = mg.preview(gap, [], ENGINE, Path(logs))
            done = mg.preview(gap, gap['solution'], ENGINE, Path(logs))
        self.assertIsNone(bare['goal_at_s'])
        self.assertIn('the ground', [h['other'] for h in bare['hits']], 'without the plank it falls in the gap')
        self.assertEqual(done['goal_at_s'], 1.9)
        ball = next(p for p in done['paths'] if p['goal'])
        self.assertEqual(ball['name'], 'ball')
        self.assertIn('your plank 1', [h['other'] for h in done['hits']])
        zone = gap['goal']['station']['done_when']['in_zone']
        end = ball['points'][-1][1:4]
        self.assertTrue(all(abs(end[i] - zone['at_m'][i]) <= zone['size_m'][i] / 2 for i in range(3)), end)

    @need_engine
    def test_flow_preview_reports_native_light_water_and_signed_current_without_changing_the_setup(self):
        import sandbox_electrics as electrical
        import sandbox_water_launch as water
        with tempfile.TemporaryDirectory() as logs:
            logs = Path(logs)
            runs = []
            for closed in (True, False):
                spec = electrical.manual_loop(closed=closed)
                before = copy.deepcopy(spec)
                result = mw.rehearse(mw.compile_spec(spec), ENGINE, logs, seconds=1, flows=True)
                self.assertIsNone(result['error']); self.assertTrue(result['complete'])
                self.assertEqual(spec, before)
                rows = result['flow_frames']
                self.assertEqual(rows[0]['t'], 0)
                self.assertTrue(all(a['t'] < b['t'] for a,b in zip(rows, rows[1:])))
                self.assertLessEqual(len(rows), 182)
                last = {w['name']: w for w in rows[-1]['wires']}
                native = {w['name']: w['current_a'] for w in result['readouts']['electrical']['wires']}
                self.assertEqual({name:w['value'] for name,w in last.items()}, native)
                self.assertEqual(last['supply wire']['points_m'][0], [-.68,.18,.07])
                runs.append(max(abs(w['value']) for w in last.values()))
            self.assertGreater(runs[0], .24)
            self.assertLess(runs[1], 1e-8, 'an open circuit must not predict flowing current')
            # Swapping a wire's declared endpoints changes only the sign and
            # arrow direction, not the physical magnitude.
            spec = electrical.manual_loop()
            w = spec['electrical']['wires'][0]; w['a'],w['b']=w['b'],w['a']
            reverse = mw.rehearse(mw.compile_spec(spec), ENGINE, logs, seconds=1, flows=True)
            self.assertLess(reverse['flow_frames'][-1]['wires'][0]['value'], -.24)
            template = water.TEMPLATES[1]
            level = mg.requested_level(dict(level='free',base=template['base']))
            compiled = mw.compile_spec(mg.compose(level,template['placements'])[0])
            poured = mw.rehearse(compiled, ENGINE, logs, seconds=3, flows=True)
            frames = poured['flow_frames']
            self.assertTrue(any(f.get('water',{}).get('xyz_mm') for f in frames))
            self.assertEqual(frames[-1]['water']['xyz_mm'], [], 'finite source stops pouring')
            self.assertGreater(frames[-1]['surface']['wet_cells'], 0)
            self.assertLessEqual(max(len(f.get('water',{}).get('xyz_mm',[]))//3 for f in frames),128)
            self.assertLessEqual(max(len(f.get('surface',{}).get('xyz_mm',[]))//3 for f in frames),512)
            self.assertAlmostEqual(frames[-1]['water']['poured_l'], poured['readouts']['pour']['poured_l'], places=2)
            self.assertLess(abs(poured['readouts']['pour']['residual_m3']),1e-8)
            blocked = mg.preview(mg.level_by_id('laser'),[],ENGINE,logs)
            laser = mg.level_by_id('laser')
            bounced = mg.preview(laser,laser['solution'],ENGINE,logs)
            self.assertIsNone(blocked['goal_at_s']); self.assertIsNotNone(bounced['goal_at_s'])
            self.assertTrue(any(len(p['w'])>=3 for f in bounced['flow_frames'] for p in f['light']))
            self.assertTrue(all(len(f['light'])<=32 for f in bounced['flow_frames']))

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
        flat = [{k: v for k, v in sun['solution'][0].items() if k not in ('yaw_deg', 'pitch_deg')}, *sun['solution'][1:]]
        shaded = [dict(sun['solution'][0], x_m=-0.8, z_m=0.6), *sun['solution'][1:]]
        # The counterweight hung too low: it reaches the ground before the
        # crate, rising a third as far, reaches the shelf.
        tackle = mg.level_by_id('tackle')
        low = [dict(tackle['solution'][0], drop_from_m=1.4)]
        with tempfile.TemporaryDirectory() as logs:
            for lv, placed in ((level, high), (fire, weak), (laser, laser['solution'][:1]), (sun, flat), (sun, shaded),
                               (tackle, low)):
                t = mg.trial(lv, placed, ENGINE, Path(logs), runs=1)
                self.assertEqual(t['worked'], 0, lv['id'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
