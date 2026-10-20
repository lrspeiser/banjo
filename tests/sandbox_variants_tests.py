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
NATIVE_FAMILY_BATCH = None
if '--engine' in sys.argv:
    index = sys.argv.index('--engine')
    ENGINE = Path(sys.argv[index + 1]).resolve()
    del sys.argv[index:index + 2]


def families():
    return [level for level in game.load_levels() if level['id'] in variants.POLICIES]


def native_family_batches():
    # Heat's four presets took 370 s by themselves on the hosted runner.
    # Keep them together in their own batch, rather than timing out the
    # adjacent electrical families. Every family still runs every preset.
    rows=families()
    return [[f for f in rows[index::3] if f['id']!='easy-heat'] for index in range(3)]+[
        [f for f in rows if f['id']=='easy-heat']]


def recipe_test_batches():
    tests=list(unittest.defaultTestLoader.loadTestsFromTestCase(Recipes))
    native='test_native_all_twenty_seeded_challenges'
    heat='test_heat_v2_clips_and_wires_while_v1_retains_the_original_attachment'
    others=[test for test in tests if test._testMethodName not in (native,heat)]
    native_case=lambda:[test for test in tests if test._testMethodName==native]
    return [native_case(),native_case(),native_case(),
            [test for test in tests if test._testMethodName==heat],
            others[::2],others[1::2],native_case()]


def receipt(valid):
    return {'valid': valid, 'mean_energy_j': 1234.1, 'engine_sha256': 'test-engine',
            'scenarios': {name: {'runs': 3, 'worked': 3 if name == 'solution' and valid else 0}
                          for name in ('solution', 'empty', 'wrong')}}


class Recipes(unittest.TestCase):
    def test_recipe_batches_cover_every_case_and_native_family_once(self):
        from collections import Counter
        all_cases=Counter(t._testMethodName for t in unittest.defaultTestLoader.loadTestsFromTestCase(Recipes))
        all_cases['test_native_all_twenty_seeded_challenges']=4
        self.assertEqual(Counter(t._testMethodName for group in recipe_test_batches() for t in group),all_cases)
        self.assertEqual(Counter(f['id'] for group in native_family_batches() for f in group),
                         Counter(f['id'] for f in families()))
        self.assertEqual([f['id'] for f in native_family_batches()[3]],['easy-heat'])
        self.assertTrue(all(recipe_test_batches()))

    def test_contact_spring_v3_presets_require_a_release_and_preserve_private_inputs(self):
        family=game.level_by_id('easy-spring');seen={}
        for seed in range(32):
            candidate=variants.construct(family,seed);seen[candidate['variant']['value']]=candidate
        self.assertEqual(set(seen),{180,200,220,240})
        with tempfile.TemporaryDirectory() as td:
            for candidate in seen.values():
                self.assertEqual(candidate['variant']['version'],3)
                self.assertNotIn('solution_releases',game.public(candidate))
                self.assertEqual(variants.reconstruct(family,candidate['variant']['seed'],0,version=3),candidate)
                if ENGINE.is_file():self.assertTrue(variants.validate(candidate,ENGINE,Path(td))['valid'])
    def test_heat_v2_clips_and_wires_while_v1_retains_the_original_attachment(self):
        family=game.level_by_id('easy-heat')
        self.assertEqual(variants.family_version(family['id']),2)
        legacy=variants.construct(family,42,version=1)
        self.assertEqual(game.public(legacy)['task_count'],1)
        self.assertEqual(len(legacy['solution']),1)
        self.assertIn('connect_to',legacy['tray'][0])
        old_spec=game.compose(legacy,legacy['solution'])[0]
        self.assertTrue(next(p for p in old_spec['parts'] if p['name']=='your ignition 1 housing')['fixed'])
        seen={variants.construct(family,seed)['variant']['value']:variants.construct(family,seed) for seed in range(32)}
        self.assertEqual(set(seen),set(variants.POLICIES[family['id']][-1]))
        for candidate in [legacy,*seen.values()]:
            self.assertEqual(candidate['goal'],family['goal']);self.assertEqual(candidate['time_s'],12)
            with tempfile.TemporaryDirectory() as logs:
                if ENGINE.is_file():self.assertTrue(variants.validate(candidate,ENGINE,Path(logs))['valid'],candidate)

    def test_marble_v3_press_deck_retains_both_earlier_switch_recipes(self):
        family=game.level_by_id('easy-marble-light')
        self.assertEqual(variants.family_version(family['id']),3)
        old=variants.construct(family,42,version=1)
        self.assertTrue(old['tray'][0]['legacy_contacts'])
        self.assertEqual(old,variants.reconstruct(family,42,0,version=1))
        old_spec=game.compose(old,old['solution'])[0]
        self.assertNotIn('touch',next(d for d in old_spec['electrical']['devices'] if d['kind']=='switch'))
        v2=variants.construct(family,42,version=2)
        v2_spec=game.compose(v2,v2['solution'])[0]
        self.assertEqual(next(p for p in v2_spec['parts'] if p['name']=='your switch 1 paddle')['shape'],'box')
        new_spec=game.compose(family,family['solution'])[0]
        self.assertEqual(next(p for p in new_spec['parts'] if p['name']=='your switch 1 paddle')['shape'],'compound')
        seen={variants.construct(family,seed)['variant']['value']:variants.construct(family,seed) for seed in range(32)}
        self.assertEqual(set(seen),set(variants.POLICIES[family['id']][-1]))
        for candidate in [old,v2,*seen.values()]:
            self.assertEqual(candidate['goal'],family['goal'])
            self.assertEqual(candidate['time_s'],family['time_s'])
            with tempfile.TemporaryDirectory() as logs:
                if ENGINE.is_file():self.assertTrue(variants.validate(candidate,ENGINE,Path(logs))['valid'],candidate)

    def test_timed_receiver_v3_preserves_old_receipts_and_validates_all_fills(self):
        import sandbox_water_launch as water
        family=game.level_by_id('easy-water-receiver')
        self.assertEqual(variants.family_version(family['id']),3)
        for version,legacy in ((1,water.LEGACY_LEVELS[family['id']]),(2,water.LEGACY_RECEIVER_LEVEL)):
            old=variants.construct(family,42,version=version)
            self.assertEqual(old['goal'],legacy['goal'])
            self.assertEqual(old['time_s'],legacy['time_s'])
            self.assertIn('water_received_l',old['goal']['station']['done_when'])
            self.assertEqual(old,variants.reconstruct(family,42,0,version=version))
        seen={variants.construct(family,seed)['variant']['value']:variants.construct(family,seed) for seed in range(32)}
        self.assertEqual(set(seen),set(variants.POLICIES[family['id']][-1]))
        for candidate in seen.values():
            self.assertEqual(candidate['goal'],family['goal'])
            self.assertEqual(candidate['time_s'],5)
            with tempfile.TemporaryDirectory() as logs:
                if ENGINE.is_file():self.assertTrue(variants.validate(candidate,ENGINE,Path(logs))['valid'],candidate)

    def test_audit_lessons_preserve_their_v1_recipes_and_validate_v2_presets(self):
        with tempfile.TemporaryDirectory() as logs:
            for family in ('easy-motor','easy-river-lift','easy-charge-lift'):
                level=game.level_by_id(family)
                seen={}
                for seed in range(32):
                    candidate=variants.construct(level,seed)
                    seen[candidate['variant']['value']]=candidate
                self.assertEqual(set(seen),set(variants.POLICIES[family][-1]))
                for candidate in seen.values():
                    self.assertEqual(candidate['variant']['version'],2)
                    self.assertEqual(candidate['goal'],level['goal'])
                    if ENGINE.is_file():self.assertTrue(variants.validate(candidate,ENGINE,Path(logs))['valid'],candidate['id'])
                old=variants.construct(level,42,version=1)
                self.assertEqual(variants.reconstruct(level,42,0,version=1),old)
                if family=='easy-motor':self.assertEqual(old['tray'][0]['knobs']['direction']['default'],'forward')
                elif family=='easy-river-lift':self.assertEqual(old['tray'][0]['knobs']['load_part']['default'],'river gate')
                else:
                    self.assertEqual(len(old['solution']),1)
                    self.assertEqual(game.public(old)['task_count'],1)
                if ENGINE.is_file():self.assertTrue(variants.validate(old,ENGINE,Path(logs))['valid'])

    def test_bulb_v3_shrinks_the_load_and_preserves_both_earlier_apparatus_versions(self):
        family=game.level_by_id('easy-bulb')
        self.assertEqual(variants.family_version('easy-bulb'),3)
        seen={}
        for seed in range(32):
            candidate=variants.construct(family,seed)
            seen[candidate['variant']['value']]=candidate
        self.assertEqual(set(seen),{2.5,2.6,2.7,2.8})
        with tempfile.TemporaryDirectory() as logs:
            for value,candidate in seen.items():
                self.assertEqual(candidate['tray'][0]['knobs']['size']['default'],'large')
                self.assertEqual(candidate['machine']['batteries'][0]['max_power_w'],value)
                self.assertEqual(candidate['goal'],family['goal'])
                if ENGINE.is_file():
                    report=variants.validate(candidate,ENGINE,Path(logs))
                    self.assertTrue(report['valid'],report)
            for version in (1,2):
                old=variants.construct(family,42,version=version)
                self.assertEqual(old['machine']['batteries'][0]['max_power_w'],200)
                self.assertNotIn('size',old['tray'][0]['knobs'])
                self.assertEqual(old['wrong'],[])
                self.assertEqual(old['solution'],[dict(piece='bulb',x_m=.6)])
                self.assertEqual(variants.reconstruct(family,42,0,version=version),old)
                if ENGINE.is_file():self.assertTrue(variants.validate(old,ENGINE,Path(logs))['valid'])

    def test_target_lessons_preserve_the_earlier_native_apparatus(self):
        if not ENGINE.is_file():
            if os.environ.get('BANJO_MACHINE_ENGINE')=='required':self.fail('Native engine required')
            self.skipTest('Native engine unavailable')
        with tempfile.TemporaryDirectory() as td:
            for family,version in [('easy-spring',1),('easy-spring',2),('easy-tackle',1),('easy-gears',1),('easy-gears',2),('easy-water-wheel',1),('easy-water-wheel',2)]:
                with self.subTest(family=family,version=version):
                    old=variants.construct(game.level_by_id(family),42,version=version)
                    self.assertEqual(variants.reconstruct(game.level_by_id(family),42,0,version=version),old)
                    report=variants.validate(old,ENGINE,Path(td))
                    self.assertTrue(report['valid'],report)
                    if family=='easy-water-wheel':self.assertEqual(game.public(old)['task_count'],version)
                    if family=='easy-gears':self.assertEqual(game.public(old)['task_count'],1)

    def test_water_v2_uses_independent_tanks_and_keeps_the_v1_feed_recipe(self):
        for name in ('easy-water-wheel','easy-water-gate','easy-water-receiver'):
            family=game.level_by_id(name)
            current=variants.construct(family,42,version=2)
            self.assertEqual(current['variant']['version'],2)
            self.assertTrue(any(p.get('outlet_model')=='gravity' for p in current['solution']))
            old=variants.construct(family,42,version=1)
            self.assertEqual(old['variant']['version'],1)
            self.assertEqual(len(old['solution']),1)
            self.assertNotIn('outlet_model',old['tray'][0]['knobs'])
            self.assertEqual(variants.reconstruct(family,42,0,version=1),old)
            c=world.compile_spec(game.compose(old,old['solution'])[0])
            self.assertTrue(c['spouts'])
            self.assertFalse(any(s.get('reservoir_area_m2') for s in c['spouts']))

    def test_solar_v2_has_a_wall_and_lead_and_preserves_the_original_v1_recipe(self):
        family=next(f for f in families() if f['id']=='easy-solar')
        new=variants.construct(family,42)
        self.assertEqual(new['variant']['version'],2)
        self.assertEqual(game.public(new)['task_count'],2)
        self.assertEqual(new['goal']['station']['done_when'],{'charged_j':{'battery':'solar battery','at_least_j':20}})
        self.assertEqual(new['time_s'],1)
        self.assertEqual([p['piece'] for p in new['solution']],['solar','power_cable'])
        self.assertTrue(new['tray'][0]['explicit_power'])
        for seed in (0,42):
            old=variants.construct(family,seed,version=1)
            self.assertEqual(old['variant']['version'],1)
            self.assertEqual(game.public(old)['task_count'],1)
            self.assertEqual(old['machine']['parts'],[])
            self.assertEqual(old['goal']['station']['done_when'],{'charged_j':{'battery':'your solar 1 battery','at_least_j':20}})
            self.assertEqual(len(old['solution']),1)
            self.assertNotIn('explicit_power',old['tray'][0])
            self.assertEqual(old['par_energy_j'],532000000)
            self.assertEqual(variants.parse(old['id'])['version'],1)
            world.compile_spec(game.compose(old,old['solution'])[0])

    def test_all_authored_families_are_physical_reproducible_deep_copies(self):
        self.assertEqual(len(families()), 23)
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
                         'easy-power--v4--0000002a--0', 'easy-power--v02--0000002a--0'):
            with self.assertRaises(ValueError):
                variants.parse(identity)

    def test_power_versions_preserve_legacy_seed_policy_and_physical_identity(self):
        family = next(row for row in families() if row['id'] == 'easy-power')
        before = copy.deepcopy(family)
        current = variants.construct(family, 42)
        self.assertEqual(current['id'], 'easy-power--v3--0000002a--0')
        self.assertEqual(current['variant']['version'], 3)
        physical = world.compile_spec(game.compose(current, current['solution'])[0])
        self.assertFalse(physical['electrical']['contacts'])
        self.assertEqual(len(physical['electrical']['wires']),2)
        self.assertEqual(set(current['tray'][0]['knobs']),{'voltage_v'})
        self.assertTrue(all(p['fixed'] for p in physical['parts']))
        self.assertEqual(game.public(current)['task_count'],3)
        contact = variants.construct(family,42,version=2)
        old = world.compile_spec(game.compose(contact,contact['solution'])[0])
        self.assertEqual(len(old['electrical']['contacts']),4)
        self.assertEqual(game.public(contact)['task_count'],1)
        self.assertEqual(variants.reconstruct(family,42,0,version=2),contact)
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
        self.assertEqual(variants.identity('easy-motor', 42,version=1), 'easy-motor--v1--0000002a--0')
        self.assertEqual(variants.identity('easy-motor', 42), 'easy-motor--v2--0000002a--0')
        for version in (0, 4, True, '1'):
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
            self.assertEqual(current['id'], f'{family["id"]}--v{variants.family_version(family["id"])}--0000002a--0')
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
                    self.assertEqual(legacy['solution'], [{'piece':'switch','state':'closed'}]
                                     if family['id']=='easy-switch' else
                                     [{'piece':'bulb','x_m':.6}] if family['id']=='easy-bulb' else family['solution'])
                    self.assertEqual(legacy['wrong'], [] if family['id']=='easy-bulb' else family['wrong'])
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

    def test_switch_v3_requires_player_input_and_v2_keeps_its_original_pose_choice(self):
        family=next(f for f in families() if f['id']=='easy-switch')
        new=variants.construct(family,42)
        self.assertEqual(new['variant']['version'],3)
        self.assertEqual(new['tray'][0]['knobs']['state']['choices'],['open'])
        self.assertEqual(new['tray'][0]['knobs']['mode']['choices'],['manual'])
        self.assertEqual(new['solution'],[dict(piece='switch',state='open')])
        self.assertTrue(new['solution_inputs'])
        with self.assertRaises(game.LevelRefused):
            game.compose(new,[dict(piece='switch',state='closed')])
        old=variants.construct(family,42,version=2)
        self.assertEqual(old['variant']['version'],2)
        self.assertEqual(old['solution'],[dict(piece='switch',state='closed')])
        self.assertEqual(old['tray'][0]['knobs']['state']['choices'],['open','closed'])
        self.assertNotIn('solution_inputs',old)
        self.assertEqual(variants.parse(old['id'])['version'],2)

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
        selected=families()
        if NATIVE_FAMILY_BATCH is not None:
            selected=native_family_batches()[NATIVE_FAMILY_BATCH]
        with tempfile.TemporaryDirectory() as logs:
            for family in selected:
                print('NATIVE_RECIPE_FAMILY '+family['id'],flush=True)
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
    shard=next((arg for arg in sys.argv[1:] if arg.startswith('--shard=')),None)
    if shard:
        index,count=map(int,shard.split('=',1)[1].split('/'))
        if count!=7 or not 0<=index<count:raise SystemExit('recipe batches use INDEX/7')
        sys.argv.remove(shard)
        if index<3 or index==6:NATIVE_FAMILY_BATCH=3 if index==6 else index
        chosen=recipe_test_batches()[index]
        print(f'Recipe batch {index+1}/7: {len(chosen)} cases'+
              (f', native families: {[f["id"] for f in native_family_batches()[NATIVE_FAMILY_BATCH]]}'
               if NATIVE_FAMILY_BATCH is not None else ''),flush=True)
        result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(chosen))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    unittest.main()
