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

ENGINE = Path(os.environ.get('BANJO_LIVE_ENGINE', ROOT / 'build/agent-circuits/Release/banjo_live_world_run.exe'))
if '--engine' in sys.argv:
    i = sys.argv.index('--engine'); ENGINE = Path(sys.argv[i + 1]); del sys.argv[i:i + 2]


class Graph(unittest.TestCase):
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
