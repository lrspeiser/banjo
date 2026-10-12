"""Seeded recipe identity, bounded fallback, and native goal regressions."""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import machine_game as game
import machine_world as world
import sandbox_variants as variants

ENGINE = Path(os.environ.get('BANJO_LIVE_ENGINE', ROOT / 'build/rube/Release/banjo_live_world_run.exe'))
if '--engine' in sys.argv:
    index = sys.argv.index('--engine')
    ENGINE = Path(sys.argv[index + 1]).resolve()
    del sys.argv[index:index + 2]


def families():
    return [level for level in game.load_levels() if level['id'] in variants.POLICIES]


def receipt(valid):
    return {'valid': valid, 'mean_energy_j': 1234.1, 'engine_sha256': 'test-engine',
            'scenarios': {name: {'runs': 3, 'worked': 3 if name == 'solution' and valid else 0}
                          for name in ('solution', 'empty', 'wrong')}}


class Recipes(unittest.TestCase):
    def test_all_twenty_one_are_physical_reproducible_deep_copies(self):
        self.assertEqual(len(families()), 21)
        for family in families():
            with self.subTest(family=family['id']):
                original = copy.deepcopy(family)
                candidate = variants.construct(family, 42)
                self.assertEqual(candidate, variants.construct(family, 42))
                self.assertEqual(family, original)
                self.assertEqual(candidate['goal'], family['goal'])
                self.assertEqual(candidate['time_s'], family['time_s'])
                self.assertEqual(candidate['budget'], family['budget'])
                self.assertFalse(candidate['variant']['validated'])
                self.assertEqual(variants.parse(candidate['id']),
                                 dict(family=family['id'], seed=42, attempt=0,
                                      version=variants.family_version(family['id'])))
                old, _, _ = game.compose(family, family['solution'])
                new, _, _ = game.compose(candidate, candidate['solution'])
                self.assertNotEqual(world.compile_spec(old), world.compile_spec(new))
                self.assertNotIn('solution', game.public(candidate))
                self.assertNotIn('wrong', game.public(candidate))

    def test_seeds_and_retries_cover_bounded_inputs(self):
        for family in families():
            values = variants.POLICIES[family['id']][-1]
            seen = {variants.construct(family, seed)['variant']['value'] for seed in range(32)}
            self.assertEqual(seen, set(values))
            retry_values = [variants.construct(family, 42, attempt=i)['variant']['value']
                            for i in range(variants.MAX_ATTEMPTS)]
            self.assertEqual(len(set(retry_values)), variants.MAX_ATTEMPTS)

    def test_invalid_identifiers_and_seeds_are_refused(self):
        family = families()[0]
        for seed in (-1, 2**32, True, 1.5, '42', None):
            with self.assertRaises(ValueError):
                variants.construct(family, seed)
        for identity in ('easy-cut', 'easy-cut--v2--0000002a--0',
                         'easy-cut--v1--0000002a--9', 'free--v1--0000002a--0',
                         'easy-cut--v1--0000002A--0', 'easy-cut--v1--0000002a--00',
                         'easy-power--v3--0000002a--0', 'easy-power--v02--0000002a--0'):
            with self.assertRaises(ValueError):
                variants.parse(identity)

    def test_power_versions_preserve_legacy_seed_policy_and_physical_identity(self):
        family = next(row for row in families() if row['id'] == 'easy-power')
        before = copy.deepcopy(family)
        current = variants.construct(family, 42)
        self.assertEqual(current['id'], 'easy-power--v2--0000002a--0')
        self.assertEqual(current['variant']['version'], 2)
        physical = world.compile_spec(game.compose(current, current['solution'])[0])
        self.assertEqual(len(physical['electrical']['contacts']), 4)
        self.assertEqual(current['tray'][0]['knobs']['mount']['default'], 'contact pack')
        self.assertTrue(any(d['kind'] == 'socket' for d in physical['electrical']['devices']))
        self.assertTrue(any(not p['fixed'] for p in physical['parts'] if p['name'].startswith('your battery')))
        for seed, original_watts in ((0, 5), (1, 5), (42, 3.5), (0xffffffff, 3.5)):
            for attempt in (0, 1, 2, None):
                with self.subTest(seed=seed, attempt=attempt):
                    identifier = variants.identity('easy-power', seed, attempt, version=1)
                    decoded = variants.parse(identifier)
                    legacy = variants.reconstruct(family, decoded['seed'], decoded['attempt'], version=decoded['version'])
                    self.assertEqual(legacy['id'], identifier)
                    self.assertEqual(legacy['variant']['version'], 1)
                    self.assertEqual(legacy['goal'], family['goal'])
                    self.assertEqual(legacy['time_s'], family['time_s'])
                    self.assertEqual(legacy['budget'], family['budget'])
                    expected = 3 if attempt is None else (3.5, 4, 4.5, 5)[
                        ((3.5, 4, 4.5, 5).index(original_watts) + attempt) % 4]
                    lamp = next(d for d in legacy['machine']['electrical']['devices'] if d['name'] == 'lamp')
                    self.assertEqual(lamp['watts'], expected)
                    self.assertEqual(legacy['solution'], [{'piece': 'battery', 'x_m': -.5}])
                    self.assertEqual(legacy['wrong'], [{'piece': 'battery', 'x_m': -.5, 'charge_percent': 0}])
                    self.assertNotIn('contact_holder', legacy['tray'][0])
                    self.assertNotIn('mount', legacy['tray'][0]['knobs'])
                    compiled = world.compile_spec(game.compose(legacy, legacy['solution'])[0])
                    self.assertFalse(compiled['electrical'].get('contacts'))
                    self.assertEqual(len(compiled['electrical']['wires']), 2)
                    self.assertTrue(all(p['fixed'] for p in compiled['parts']))
        self.assertEqual(family, before)
        self.assertEqual(variants.identity('easy-motor', 42), 'easy-motor--v1--0000002a--0')
        for version in (0, 3, True, '1'):
            with self.assertRaises(ValueError):
                variants.construct(family, 42, version=version)

    def test_native_legacy_power_share_reopens_exact_apparatus_after_cache_loss(self):
        if not ENGINE.is_file():
            if os.environ.get('BANJO_MACHINE_ENGINE') == 'required':
                self.fail('A verified native engine is required.')
            self.skipTest('Native engine unavailable.')
        identifier = 'easy-power--v1--0000002a--0'
        with tempfile.TemporaryDirectory() as logs, patch.dict(game._variants, clear=True), \
                patch.dict(game._variant_requests, clear=True):
            first = game.fresh_easy('easy-power', 42, ENGINE, logs, recipe_id=identifier)
            game._variants.clear(); game._variant_requests.clear()
            reopened = game.fresh_easy('easy-power', 42, ENGINE, logs, recipe_id=identifier)
        for level in (first, reopened):
            self.assertEqual(level['id'], identifier)
            self.assertEqual(level['variant']['version'], 1)
            report = level['variant']['validation']
            self.assertTrue(report['valid'])
            self.assertEqual(report['scenarios']['solution']['worked'], 3)
            self.assertEqual(report['scenarios']['empty']['worked'], 0)
            self.assertEqual(report['scenarios']['wrong']['worked'], 0)
            self.assertEqual(level['machine'], first['machine'])
            self.assertNotIn('contact_holder', level['tray'][0])
        print('LEGACY_POWER_SHARE_MEASUREMENTS ' + json.dumps([
            level['variant']['validation'] for level in (first, reopened)], sort_keys=True))

    def test_switch_family_versions_preserve_raw_v1_graphs_and_migrate_handles(self):
        oracles = {'easy-switch': (11, 11.5, 12.5, 13),
                   'easy-bulb': (13, 12.5, 13, 11), 'easy-loop': (4, 5, 3.5, 4)}
        for family in [f for f in families() if f['id'] in oracles]:
            original = copy.deepcopy(family)
            current = variants.construct(family, 42)
            self.assertEqual(current['id'], f'{family["id"]}--v2--0000002a--0')
            raw = game.compose(current, current['solution'])[0]
            compiled = world.compile_spec(raw)
            switch = next(d for d in compiled['electrical']['devices'] if d['kind'] == 'switch')
            self.assertIn('handle', switch)
            self.assertFalse(next(p for p in compiled['parts'] if p['name'] == switch['handle']['part'])['fixed'])
            for (seed, attempt), expected in zip(((0, 0), (42, 0), (42, 1), (42, 2)), oracles[family['id']]):
                with self.subTest(family=family['id'], seed=seed, attempt=attempt):
                    legacy = variants.construct(family, seed, attempt=attempt, version=1)
                    self.assertEqual(variants.parse(legacy['id'])['version'], 1)
                    self.assertEqual(legacy['variant']['value'], expected)
                    self.assertEqual(legacy['goal'], family['goal'])
                    self.assertEqual(legacy['time_s'], family['time_s'])
                    self.assertEqual(legacy['solution'], family['solution'])
                    self.assertEqual(legacy['wrong'], family['wrong'])
                    if family['id'] == 'easy-switch':
                        self.assertTrue(legacy['tray'][0]['legacy_manual'])
                        self.assertEqual(set(legacy['tray'][0]['knobs']),
                            {'x_m', 'z_m', 'mode', 'state', 'threshold_deg'})
                        self.assertEqual(legacy['machine']['electrical']['wires'],
                            [{'name': 'return wire', 'a': 'lamp:minus', 'b': 'supply:minus'}])
                    else:
                        device = next(d for d in legacy['machine']['electrical']['devices'] if d['name'] == 'control')
                        self.assertTrue(device['closed'])
                        self.assertNotIn('hinge', device)
                        old_handle = next(p for p in legacy['machine']['parts'] if p['name'] == 'control handle')
                        self.assertTrue(old_handle['fixed'])
                        self.assertEqual(old_handle['size_m'], [.04, .1, .04])
                        self.assertEqual(old_handle['at_m'], [.04, .15, 0])
                        names = [w['name'] for w in legacy['machine']['electrical']['wires']]
                        self.assertEqual(names, ['supply wire'] + (['switched wire'] if family['id'] == 'easy-loop' else []))
                    before = copy.deepcopy(legacy)
                    migrated = world.compile_spec(game.compose(legacy, legacy['solution'])[0])
                    switched = next(d for d in migrated['electrical']['devices'] if d['kind'] == 'switch')
                    self.assertIn('handle', switched)
                    self.assertFalse(next(p for p in migrated['parts'] if p['name'] == switched['handle']['part'])['fixed'])
                    self.assertEqual(legacy, before, 'migration leaves the saved v1 declaration intact')
            fallback = variants.reconstruct(family, 42, None, version=1)
            self.assertEqual(fallback['id'], f'{family["id"]}--v1--0000002a--c')
            self.assertTrue(fallback['variant']['fallback'])
            if family['id'] == 'easy-switch':
                paddle = world.compile_spec(game.compose(fallback, [{'piece': 'switch', 'mode': 'paddle'}])[0])
                device = next(d for d in paddle['electrical']['devices'] if d['kind'] == 'switch')
                self.assertNotIn('handle', device, 'the old manual/paddle choice must retain actual paddle geometry')
                self.assertEqual(device['hinge'], 'your switch 1 paddle axle')
                self.assertEqual(device['closed_at_or_below_deg'], -8)
                body = next(p for p in paddle['parts'] if p['name'] == 'your switch 1 paddle')
                self.assertEqual(body['size_m'], [.36, .04, .16])
                self.assertFalse(body['fixed'])
            self.assertEqual(family, original)

    def test_native_legacy_switch_family_shares_reopen_with_physical_handles(self):
        if not ENGINE.is_file():
            if os.environ.get('BANJO_MACHINE_ENGINE') == 'required':
                self.fail('A verified native engine is required.')
            self.skipTest('Native engine unavailable.')
        measured = []
        with tempfile.TemporaryDirectory() as logs, patch.dict(game._variants, clear=True), \
                patch.dict(game._variant_requests, clear=True):
            for family in ('easy-switch', 'easy-bulb', 'easy-loop'):
                identifier = f'{family}--v1--0000002a--0'
                level = game.fresh_easy(family, 42, ENGINE, logs, recipe_id=identifier)
                self.assertEqual(level['id'], identifier)
                self.assertEqual(level['variant']['version'], 1)
                report = level['variant']['validation']
                self.assertTrue(report['valid'])
                self.assertEqual(report['scenarios']['solution']['worked'], 3)
                self.assertEqual(report['scenarios']['empty']['worked'], 0)
                self.assertEqual(report['scenarios']['wrong']['worked'], 0)
                measured.append(dict(family=family, **report))
        print('LEGACY_SWITCH_SHARE_MEASUREMENTS ' + json.dumps(measured, sort_keys=True))

    def test_retry_identity_and_three_run_energy_par(self):
        family = families()[0]
        with patch.object(variants, 'validate', side_effect=[receipt(False), receipt(True)]) as validate:
            chosen = variants.preflight(family, 42, 'unused-engine', 'unused-logs')
        self.assertEqual(validate.call_count, 2)
        self.assertEqual(chosen['variant']['attempt'], 1)
        self.assertFalse(chosen['variant']['fallback'])
        self.assertTrue(chosen['variant']['validated'])
        self.assertEqual(chosen['par_energy_j'], 1240)
        self.assertEqual(chosen['variant']['measured_energy_j'], 1234.1)
        self.assertEqual(chosen['id'], variants.reconstruct(family, 42, 1)['id'])

    def test_fallback_is_identifiable_and_must_itself_pass(self):
        family = families()[0]
        with patch.object(variants, 'validate', side_effect=[receipt(False)] * 3 + [receipt(True)]) as validate:
            chosen = variants.preflight(family, 42, 'unused-engine', 'unused-logs')
        self.assertEqual(validate.call_count, 4)
        self.assertTrue(chosen['variant']['fallback'])
        self.assertEqual(variants.parse(chosen['id'])['attempt'], None)
        self.assertEqual(chosen['machine'], family['machine'])
        self.assertEqual(chosen['goal'], family['goal'])
        with patch.object(variants, 'validate', return_value=receipt(False)) as validate:
            with self.assertRaises(variants.VariantRefused) as refused:
                variants.preflight(family, 42, 'unused-engine', 'unused-logs', max_attempts=1)
        self.assertEqual(validate.call_count, 2)
        self.assertEqual(len(refused.exception.receipts), 2)

    def test_engine_errors_do_not_count_as_physical_control_failures(self):
        family = variants.construct(families()[0], 42)
        clean = lambda worked: {'runs': 3, 'worked': worked,
            'results': [{'goal_at_s': .5 if worked else None, 'error': None, 'energy_j': 12}] * 3}
        broken = clean(0)
        broken['results'] = [{'goal_at_s': None, 'error': 'native failure', 'energy_j': 0}] * 3
        with tempfile.TemporaryDirectory() as logs:
            with patch.object(variants, '_trial', side_effect=[clean(3), broken, clean(0)]):
                result = variants.validate(family, Path(__file__), logs)
        self.assertFalse(result['valid'])
        self.assertNotIn('mean_energy_j', result)

    def test_incomplete_native_rehearsal_is_refused(self):
        family = variants.construct(families()[0], 42)
        with tempfile.TemporaryDirectory() as logs:
            with patch.object(world, 'rehearse', return_value={
                    'world_time_s': .01, 'stations': [], 'readouts': {}, 'error': None}):
                result = variants._trial(family, [], Path(__file__), logs)
        self.assertEqual(result['worked'], 0)
        self.assertTrue(all('before the challenge deadline' in row['error'] for row in result['results']))

    def test_native_all_twenty_seeded_challenges(self):
        if not ENGINE.is_file():
            if os.environ.get('BANJO_MACHINE_ENGINE') == 'required':
                self.fail('A verified native engine is required.')
            self.skipTest('Native engine unavailable.')
        measured = []
        with tempfile.TemporaryDirectory() as logs:
            for family in families():
                seeds = {}
                for seed in [42] + list(range(32)):
                    candidate = variants.construct(family, seed)
                    seeds.setdefault(candidate['variant']['value'], seed)
                self.assertEqual(set(seeds), set(variants.POLICIES[family['id']][-1]))
                times, energies, wall_s = [], [], 0
                for value, seed in seeds.items():
                    with self.subTest(family=family['id'], value=value, seed=seed):
                        chosen = variants.preflight(family, seed, ENGINE, logs)
                        report = chosen['variant']['validation']
                        self.assertTrue(report['valid'])
                        self.assertEqual(chosen['variant']['attempt'], 0)
                        self.assertFalse(chosen['variant']['fallback'])
                        self.assertEqual(report['scenarios']['solution']['worked'], 3)
                        self.assertEqual(report['scenarios']['empty']['worked'], 0)
                        self.assertEqual(report['scenarios']['wrong']['worked'], 0)
                        self.assertEqual(chosen['goal'], family['goal'])
                        self.assertGreaterEqual(chosen['par_energy_j'], report['mean_energy_j'])
                        times += [r['goal_at_s'] for r in report['scenarios']['solution']['results']]
                        energies.append(report['mean_energy_j'])
                        wall_s += report['wall_s']
                measured.append({'family': family['id'], 'values': sorted(seeds),
                                 'correct_nudges': len(times), 'wrong_wins': 0, 'empty_wins': 0,
                                 'goal_range_s': [min(times), max(times)],
                                 'mean_energy_range_j': [min(energies), max(energies)],
                                 'wall_s': round(wall_s, 3)})
        print('SEEDED_NATIVE_MEASUREMENTS ' + json.dumps(measured, sort_keys=True))


if __name__ == '__main__':
    unittest.main()
