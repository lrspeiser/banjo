"""Electrical graph, saved device and native energy transfer regressions."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import sandbox_electrics as e
import machine_world as mw
import machine_game as mg
import machine_chat as mc

ENGINE = Path(os.environ.get('BANJO_LIVE_ENGINE', ROOT / 'build/agent-circuits/Release/banjo_live_world_run.exe'))
if '--engine' in sys.argv:
    i = sys.argv.index('--engine'); ENGINE = Path(sys.argv[i + 1]); del sys.argv[i:i + 2]


class Graph(unittest.TestCase):
    def test_ghost_shows_prepared_terminal_graph_without_changing_the_level(self):
        level = next(row for row in e.easy_levels() if row['id'] == 'easy-marble-light')
        before = copy.deepcopy(level)
        reply = mg.ghost(level, [copy.deepcopy(level['solution'][0])], 0)
        electrical = reply['electrical_preview']
        self.assertEqual(len(electrical['wires']), 3)
        pins = {d['name'] + ':' + key: at for d in electrical['devices'] for key, at in d['terminals'].items()}
        self.assertIn('your switch 1:in', pins)
        self.assertIn('your switch 1:out', pins)
        self.assertTrue(all(w['a'] in pins and w['b'] in pins for w in electrical['wires']))
        self.assertEqual(level, before, 'showing prepared leads must not alter the scenario')
        loop = next(row for row in e.easy_levels() if row['id'] == 'easy-loop')
        reply = mg.ghost(loop, [copy.deepcopy(loop['solution'][0])], 0)
        self.assertEqual(reply['wire_preview'], [
            next(d['terminals']['minus'] for d in reply['electrical_preview']['devices'] if d['name'] == 'lamp'),
            next(d['terminals']['minus'] for d in reply['electrical_preview']['devices'] if d['name'] == 'supply')])

    def test_saved_power_lead_and_generic_ports(self):
        level = mg.level_by_id('sun')
        saved = copy.deepcopy(level['solution'])
        spec = mg.compose(level, saved)[0]
        before = copy.deepcopy(spec)
        compiled = mw.compile_spec(spec)
        self.assertEqual(spec, before)
        self.assertEqual(saved, level['solution'])
        ports = {p['name']: p for p in compiled['electrical']['power_ports']}
        self.assertEqual(ports['your solar 1:power']['solar_panel'], 'your solar 1')
        self.assertEqual(ports['winch:power']['battery'], 'solar battery')
        self.assertEqual(compiled['solar_panels'][0]['battery'], 'solar battery')
        disconnected = mw.compile_spec(mg.compose(level, saved[:1])[0])
        self.assertEqual(disconnected['solar_panels'][0]['battery'], 'your solar 1 local battery')
        # Place the cable before its panel to exercise dependency staging.
        reordered = [dict(saved[1], a_port='your solar 2:power'), saved[0]]
        self.assertEqual(mw.compile_spec(mg.compose(level, reordered)[0])['solar_panels'][0]['battery'], 'solar battery')
        free = copy.deepcopy(mg.free_build())
        free['machine']['sun'] = {'elevation_deg': 90, 'azimuth_deg': 0}
        placements = [{'piece': 'solar', 'x_m': -.7}, {'piece': 'battery', 'x_m': .7, 'charge_percent': 0},
                      {'piece': 'power_cable', 'a_port': 'your solar 1:power', 'b_port': 'your battery 2:power'}]
        c = mw.compile_spec(mg.compose(free, placements)[0])
        self.assertEqual(c['solar_panels'][0]['battery'], 'your battery 2 battery')
        self.assertEqual(len(c['electrical']['power_cables']), 1)
        self.assertTrue(mg.ghost(level, saved, 1)['wire_preview'])
        assisted = mc.respond_level('Place it', level, [], mode='build',
                                    call=lambda messages: ({'reply': 'Connect the panel to the winch.', 'placements': saved}, {}))
        self.assertEqual(assisted['placements'][1]['b_port'], 'winch:power')
        self.assertIn('winch:power', mc.level_prompt(level, 'build'))
        # Search geometry while retaining the actual string connection.
        refined, _, runs = mg.refine(level, saved,
            lambda compiled: {'stations': [{'done': False}], 'zone_nearest_m': {level['goal']['title']: 1}},
            budget=2, scatter=1)
        self.assertEqual(refined[1]['b_port'], 'winch:power')
        self.assertEqual(runs, 2)
        for bad in (dict(saved[1], a_port='absent:power'),
                    dict(saved[1], a_port='winch:power', b_port='your solar 1:power')):
            with self.assertRaises(mw.MachineRefused): mg.compose(level, [saved[0], bad])
        duplicate = copy.deepcopy(spec)
        duplicate['electrical']['power_cables'].append(dict(duplicate['electrical']['power_cables'][0], name='second lead'))
        with self.assertRaises(mw.MachineRefused): mw.compile_spec(duplicate)
        # An already declared solar destination cannot sneak around the
        # explicit one-source-per-store restriction.
        parallel = copy.deepcopy(spec)
        parallel['solar_panels'].append(dict(parallel['solar_panels'][0], name='other solar', battery='solar battery'))
        with self.assertRaises(mw.MachineRefused): mw.compile_spec(parallel)

    def test_saved_graph_keeps_terminals_crossings_and_shared_supply(self):
        spec = e.manual_loop(second_bulb=True)
        before = copy.deepcopy(spec)
        c = mw.compile_spec(spec)
        self.assertEqual(spec, before)
        self.assertEqual(len(c['electrical']['networks']), 1)
        self.assertEqual(len(c['electrical']['networks'][0]['devices']), 4)
        self.assertEqual(c['electrical']['wires'], spec['electrical']['wires'])
        spec['electrical']['wires'][0]['a'] = 'missing:plus'
        with self.assertRaises(mw.MachineRefused): mw.compile_spec(spec)

    def test_multi_source_and_insulating_shortcuts_are_refused(self):
        spec = e.manual_loop()
        e.merge(spec, e.battery('other supply', {'z_m': .6}, {}))
        e.link(spec, 'extra supply', 'other supply:plus', 'supply:plus')
        with self.assertRaises(mw.MachineRefused): mw.compile_spec(spec)
        spec = e.manual_loop(); spec['electrical']['devices'][2]['efficiency'] = 1.1
        with self.assertRaises(mw.MachineRefused): mw.compile_spec(spec)
        spec = e.manual_loop(); spec['electrical']['devices'][0]['battery'] = 'absent'
        with self.assertRaises(mw.MachineRefused): mw.compile_spec(spec)


@unittest.skipUnless(ENGINE.is_file(), 'requires native engine')
class Native(unittest.TestCase):
    def run_spec(self, spec, seconds=1):
        with tempfile.TemporaryDirectory(prefix='banjo-electrical-') as logs:
            result = mw.rehearse(mw.compile_spec(spec), ENGINE, Path(logs), seconds=seconds, wall_limit_s=40)
        self.assertIsNone(result.get('error'), result)
        return result

    def test_explicit_solar_lead_disconnect_shade_and_nudged_solution(self):
        level = mg.level_by_id('sun')
        with tempfile.TemporaryDirectory(prefix='banjo-sun-lead-') as logs:
            trial = mg.trial(level, level['solution'], ENGINE, Path(logs), runs=3)
        self.assertEqual(trial['worked'], 3, trial)
        for mode in ('disconnected', 'flat', 'shaded'):
            placements = copy.deepcopy(level['solution'])
            if mode == 'disconnected': placements.pop()
            if mode == 'flat':
                placements[0]['yaw_deg'] = 0; placements[0]['pitch_deg'] = 0
            if mode == 'shaded':
                placements[0]['x_m'] = -.8; placements[0]['z_m'] = .6
            result = self.run_spec(mg.compose(level, placements)[0], level['time_s'])
            self.assertFalse(result['stations'][0]['done'], mode)
            batteries = {b['name']: b for b in result['readouts']['machines']['batteries']}
            panel = result['readouts']['machines']['solar_panels'][0]
            if mode == 'disconnected':
                self.assertEqual(batteries['solar battery']['charge_j'], 0)
                self.assertEqual(batteries['solar battery']['given_j'], 0)
                self.assertGreater(batteries['your solar 1 local battery']['charge_j'], 390)
                self.assertAlmostEqual(batteries['your solar 1 local battery']['charge_j'], panel['charged_j'], delta=.001)
                self.assertAlmostEqual(panel['sunlight_j'], panel['collected_j'] + panel['spilled_j'] + panel['heat_j'], delta=.003)
            if mode == 'shaded': self.assertEqual(panel['sunlight_w'], 0)
        print('sun explicit lead: 3/3 nudged wins; disconnected, flat and shaded fail')

    def test_ready_solar_geometry_and_no_energy_before_running(self):
        level = mg.level_by_id('sun')
        for shaded in (False, True):
            placements = copy.deepcopy(level['solution'])
            if shaded: placements[0].update(x_m=-.8, z_m=.6)
            compiled = mw.compile_spec(mg.compose(level, placements)[0])
            with tempfile.TemporaryDirectory(prefix='banjo-sun-ready-') as logs:
                session = mw.MachineSession(compiled, ENGINE, Path(logs), paced=True)
                try:
                    deadline = time.monotonic() + 5
                    frame = session.frame(0, 10)
                    while 'machines' not in frame.get('readouts', {}) and time.monotonic() < deadline:
                        time.sleep(.01)
                        frame = session.frame(0, 10)
                    panel = frame['readouts']['machines']['solar_panels'][0]
                    self.assertEqual(session.t, 0)
                    self.assertTrue(panel['valid'])
                    self.assertEqual(panel['battery'], 'solar battery')
                    self.assertEqual(panel['occlusion_model'], 'center_ray')
                    self.assertAlmostEqual(panel['off_sun_deg'], 0, delta=.001)
                    self.assertEqual(len(panel['at_m']), 3)
                    self.assertEqual(len(panel['normal']), 3)
                    self.assertEqual(len(panel['toward_sun']), 3)
                    self.assertEqual(len(panel['ray_from_m']), 3)
                    if shaded:
                        self.assertEqual(panel['sunlight_w'], 0)
                        self.assertIsNotNone(panel['shadow_hit_m'])
                        self.assertGreater(panel['shadow_distance_m'], 0)
                    else:
                        self.assertAlmostEqual(panel['sunlight_w'], 250, delta=.001)
                        self.assertIsNone(panel['shadow_hit_m'])
                    for key in ('charged_j', 'sunlight_j', 'collected_j', 'spilled_j', 'heat_j'):
                        self.assertEqual(panel[key], 0, key)
                    for b in frame['readouts']['machines']['batteries']:
                        self.assertEqual(b['given_j'], 0)
                        self.assertEqual(b['taken_j'], 0)
                finally: session.close()

    def test_power_lead_routes_one_finite_store_and_accounts_for_overflow(self):
        free = copy.deepcopy(mg.free_build())
        free['machine']['sun'] = {'elevation_deg': 90, 'azimuth_deg': 0}
        for charge in (0, 100):
            placements = [{'piece': 'solar', 'x_m': -.7},
                          {'piece': 'battery', 'x_m': .7, 'capacity_j': 100, 'charge_percent': charge},
                          {'piece': 'power_cable', 'a_port': 'your solar 1:power', 'b_port': 'your battery 2:power'}]
            result = self.run_spec(mg.compose(free, placements)[0], 1)
            machines = result['readouts']['machines']
            batteries = {b['name']: b for b in machines['batteries']}
            panel = machines['solar_panels'][0]
            self.assertEqual(batteries['your solar 1 battery']['charge_j'], 0)
            self.assertEqual(panel['battery'], 'your battery 2 battery')
            self.assertAlmostEqual(panel['sunlight_j'], panel['collected_j'] + panel['spilled_j'] + panel['heat_j'], delta=.003)
            if charge:
                self.assertEqual(batteries['your battery 2 battery']['charge_j'], 100)
                self.assertEqual(panel['collected_j'], 0)
                self.assertEqual(panel['charged_j'], 100)
                self.assertGreater(panel['spilled_j'], 45)
            else:
                self.assertGreater(panel['charged_j'], 45)
                self.assertEqual(panel['spilled_j'], 0)
                # Public charge readout is rounded to 0.1 J; taken_j retains
                # millijoules for the conservation comparison.
                self.assertEqual(batteries['your battery 2 battery']['charge_j'], round(panel['charged_j'], 1))
                self.assertAlmostEqual(batteries['your battery 2 battery']['taken_j'], panel['charged_j'], delta=.001)

    def test_closed_open_missing_return_and_empty_battery(self):
        closed = self.run_spec(e.manual_loop())
        ds = closed['readouts']['electrical']['devices']
        lamp = next(d for d in ds if d['name'] == 'lamp')
        self.assertGreater(lamp['power_w'], 2.9)
        self.assertGreater(lamp['current_a'], .24)
        self.assertEqual(closed['readouts']['circuits'], [], 'graph circuits must not become legacy zero-current rows')
        self.assertEqual(len(closed['readouts']['electrical']['networks']), 1)
        self.assertAlmostEqual(lamp['emitted_w'], .2 * lamp['power_w'], places=9)
        for spec in (e.manual_loop(False), e.manual_loop(charge_j=0)):
            result = self.run_spec(spec)
            self.assertLess(abs(next(d for d in result['readouts']['electrical']['devices'] if d['name'] == 'lamp')['power_w']), 1e-10)
        spec = e.manual_loop(); spec['electrical']['wires'].pop()
        result = self.run_spec(spec)
        self.assertLess(abs(next(d for d in result['readouts']['electrical']['devices'] if d['name'] == 'lamp')['power_w']), 1e-10)

    def test_two_loads_share_charge_and_regulation_heat(self):
        spec = e.manual_loop(second_bulb=True)
        spec['batteries'][0]['max_power_w'] = 3
        result = self.run_spec(spec, 2)
        native = result['readouts']['electrical']['networks'][0]
        ledger = native['ledger']
        self.assertLessEqual(ledger['source_j'], 6.3)
        self.assertGreater(ledger['heat_j'], 0)
        self.assertGreater(ledger['emitted_j'], 0)
        self.assertAlmostEqual(ledger['source_j'], ledger['heat_j'] + ledger['emitted_j'], places=8)
        self.assertLess(abs(ledger['electrical_residual_j']), 1e-8)
        self.assertLess(abs(ledger['thermal_residual_j']), 1e-6)
        bulbs = [d['power_w'] for d in result['readouts']['electrical']['devices'] if d['kind'] == 'bulb']
        self.assertAlmostEqual(*bulbs, places=9)
        print('shared bulbs:', ledger)

    def test_material_heating_glass_oak_iron_same_coil_energy(self):
        results = {}
        for material in ('glass', 'oak', 'iron'):
            spec = e.empty('Comparative heater')
            e.merge(spec, e.battery('supply', {'x_m': -.6}, {}))
            spec['parts'].append(e.box('sample', [.5, .15, 0], [.04, .3, .04], material))
            e.merge(spec, e.ignition('heater', {'target': 'sample', 'preset': 'warm'}, {}))
            e.link(spec, 'feed', 'supply:plus', 'heater:plus'); e.link(spec, 'return', 'heater:minus', 'supply:minus')
            result = self.run_spec(spec, 2)
            circuit = result['readouts']['electrical']['networks'][0]['ledger']
            self.assertGreater(circuit['exported_j'], 20)
            self.assertLess(abs(circuit['electrical_residual_j']), 1e-8)
            self.assertAlmostEqual(circuit['exported_j'], result['readouts']['heat_ledger']['heater_in_j'], delta=.011)
            results[material] = circuit['exported_j']
            with tempfile.TemporaryDirectory(prefix='banjo-material-heater-') as logs:
                engine, _, _ = mw.build_engine(ENGINE, mw.compile_spec(spec), Path(logs))
                try:
                    engine.op(op='step', dt=1 / 240, n=480)
                    sample = next(b for b in engine.op(op='thermo')['thermo']['bodies'] if b['name'] == 'sample')
                    self.assertGreater(sample['temperature_k'], 293.15)
                    print(material, 'surface K', sample['temperature_k'], 'core K', sample['core_temperature_k'])
                finally: engine.close()
        self.assertAlmostEqual(max(results.values()), min(results.values()), places=6)
        print('same declared box .04 x .3 x .04 m / 12 ohm / 12 V / dt 1/240:', results)

    def test_all_examples_and_easy_solutions_wrong_controls(self):
        for template in e.TEMPLATES:
            spec = copy.deepcopy(template['base'])
            if template['name'] == 'Marble turns on a light':
                spec['stations'] = [{'title': 'Light', 'done_when': {'load_power_w': {'device': 'lamp', 'at_least_w': 2, 'for_s': .1}}}]
            result = self.run_spec(spec, 6 if template['name'] == 'Burn the cord' else 2)
            if template['name'] == 'Marble turns on a light': self.assertTrue(result['stations'][0]['done'], result)
        for level in e.EASY_LEVELS:
            with self.subTest(level=level['id']):
                spec = mg.compose(level, level['solution'])[0]
                result = self.run_spec(spec, level['time_s'])
                self.assertTrue(result['stations'][0]['done'], result)
                with tempfile.TemporaryDirectory(prefix='banjo-electrical-nudged-') as logs:
                    trial = mg.trial(level, level['solution'], ENGINE, Path(logs), runs=3)
                    self.assertEqual(trial['worked'], 3, trial)
                if level.get('wrong'):
                    wrong = mg.compose(level, level['wrong'])[0]
                    result = self.run_spec(wrong, level['time_s'])
                    self.assertFalse(result['stations'][0]['done'], result)
                print(level['id'], 'verified')

    def test_series_bulbs_manual_switch_runtime_and_saved_initial_state(self):
        spec = e.manual_loop(second_bulb=True)
        spec['electrical']['wires'] = spec['electrical']['wires'][:2]
        e.link(spec, 'series link', 'lamp:minus', 'second lamp:plus')
        e.link(spec, 'series return', 'second lamp:minus', 'supply:minus')
        result = self.run_spec(spec)
        bulbs = [d['power_w'] for d in result['readouts']['electrical']['devices'] if d['kind'] == 'bulb']
        self.assertAlmostEqual(*bulbs, places=9)
        self.assertLess(max(bulbs), .8)
        spec = e.manual_loop(False)
        compiled = mw.compile_spec(spec)
        with tempfile.TemporaryDirectory(prefix='banjo-live-switch-') as logs:
            session = mw.MachineSession(compiled, ENGINE, Path(logs), paced=True)
            try:
                session.electrical_switch('control', True); session.play(True)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    lamp = next(d for d in session.frame(0, 10)['readouts']['electrical']['devices'] if d['name'] == 'lamp')
                    if lamp['power_w'] > 2: break
                self.assertGreater(lamp['power_w'], 2)
                session.electrical_switch('control', False)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    lamp = next(d for d in session.frame(0, 10)['readouts']['electrical']['devices'] if d['name'] == 'lamp')
                    if lamp['power_w'] < 1e-10: break
                self.assertLess(lamp['power_w'], 1e-10)
                self.assertFalse(compiled['electrical']['devices'][1]['closed'])
                with self.assertRaises(ValueError): session.electrical_switch('lamp', True)
            finally: session.close()


if __name__ == '__main__': unittest.main()
