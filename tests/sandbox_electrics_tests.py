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
    def test_wire_watts_use_the_native_voltage_reference_and_are_not_wire_heat(self):
        graph={'wires':[dict(name='feed',a='battery:plus',b='motor:plus')]}
        def sample(offset):
            network=dict(id='electrical probe',nodes=['battery:plus','battery:minus','motor:plus'],
                source={'negative':'battery:minus'},last={'voltage_v':[12+offset,offset,11.99+offset]},
                branches=[dict(id='feed',kind='wire',a='battery:plus',b='motor:plus',current_a=1,power_w=.01)])
            return e.readouts(graph,[network])['wires'][0]
        for offset in (0,-12,100):
            row=sample(offset)
            self.assertAlmostEqual(row['through_w'],12)
            self.assertAlmostEqual(row['loss_w'],.01)
            self.assertFalse(row['return_path'])

    def test_legacy_manual_saved_graph_migrates_without_rewriting_state_or_material(self):
        import json
        for material in ('glass', 'oak', 'iron'):
            for initial in (False, True, None):
                with self.subTest(material=material, initial=initial):
                    spec = e.manual_loop(initial is True)
                    legacy = e.legacy_manual_switch('control', {'state': 'closed' if initial else 'open'}, {})
                    next(p for p in legacy['parts'] if p['name'] == 'control handle')['material'] = material
                    if initial is None: legacy['electrical']['devices'][0].pop('closed')
                    spec['parts'] = [p for p in spec['parts'] if not p['name'].startswith('control ')] + legacy['parts']
                    spec['joints'] = [j for j in spec['joints'] if not j['name'].startswith('control ')]
                    spec['electrical']['devices'] = [d for d in spec['electrical']['devices'] if d['name'] != 'control'] + legacy['electrical']['devices']
                    saved_json = json.dumps(spec, sort_keys=True)
                    names = [d['name'] for d in spec['electrical']['devices']]
                    wires = copy.deepcopy(spec['electrical']['wires'])
                    compiled = mw.compile_spec(spec)
                    self.assertEqual(json.dumps(spec, sort_keys=True), saved_json)
                    self.assertEqual([d['name'] for d in compiled['electrical']['devices']], names)
                    self.assertEqual(compiled['electrical']['wires'], wires)
                    control = next(d for d in compiled['electrical']['devices'] if d['name'] == 'control')
                    self.assertEqual(control.get('closed', False), initial is True)
                    self.assertEqual(control['terminals'], legacy['electrical']['devices'][0]['terminals'])
                    handle = next(p for p in compiled['parts'] if p['name'] == control['handle']['part'])
                    self.assertEqual(handle['name'], 'control handle')
                    self.assertEqual(handle['material'], material)
                    self.assertFalse(handle['fixed'])
                    hinge = next(j for j in compiled['joints'] if j['name'] == control['hinge'])
                    self.assertEqual(hinge['kind'], 'hinge')
                    self.assertEqual(hinge['b'], handle['name'])

    def test_subjoule_external_input_and_store_draw_are_counted_once(self):
        compiled = mw.compile_spec(e.manual_loop(False))
        readouts = {'machines': {'batteries': [{'name': 'supply battery', 'given_j': .004}]},
                    'pulls': [{'body': 'control handle', 'work_j': .125},
                              {'body': 'other body', 'work_j': -.045}],
                    'pour': {'sources': [{'source_energy_j': .003}]}}
        receipt = mg.run_energy(compiled, readouts, 1)
        self.assertEqual(receipt['electric_j'], .004)
        self.assertEqual(receipt['pull_j'], .125)
        self.assertEqual(receipt['water_j'], .003)
        self.assertEqual(receipt['j'], .132)
        self.assertAlmostEqual(receipt['j'], sum(receipt[key] for key in
            ('heat_j', 'powder_j', 'electric_j', 'pull_j', 'water_j')), places=9)
        whole = mg.energy_of(compiled, readouts, 1)
        self.assertAlmostEqual(whole['j'] - whole['pieces_j'], .132, delta=1e-6)

    def test_contact_holder_template_preserves_editable_physical_pack(self):
        template = next(t for t in e.TEMPLATES if t['name']=='Drop a battery into its holder')
        before = copy.deepcopy(template)
        level = mg.requested_level({'level':'free','base':template['base']})
        compiled = mw.compile_spec(mg.compose(level,template['placements'])[0])
        self.assertEqual(len(compiled['electrical']['contacts']),4)
        self.assertTrue(all(not p['fixed'] for p in compiled['parts'] if p['name'].startswith('your battery')))
        self.assertEqual(level['tray'][next(i for i,t in enumerate(level['tray']) if t['piece']=='battery')]['knobs']['mount']['default'],'contact pack')
        self.assertEqual(template,before)
        # Dry saved designs retain the old fixed battery default and wire graph.
        dry = mg.requested_level({'level':'free','base':e.empty('dry')})
        old = mw.compile_spec(mg.compose(dry,[{'piece':'battery'}])[0])
        self.assertTrue(next(p for p in old['parts'] if p['name']=='your battery 1 housing')['fixed'])
        self.assertEqual(old['electrical']['contacts'],[])
        empty_graph = e.empty('dry without an electrical graph')
        empty_graph['electrical'] = None
        self.assertTrue(mg.requested_level({'level':'free','base':empty_graph})['custom_base'])

    def test_source_free_socket_has_no_branch_shorting_its_pads(self):
        level = next(t for t in e.easy_levels() if t['id']=='easy-power')
        ready = mw.compile_spec(level['machine'])
        self.assertEqual(ready['electrical']['networks'],[])
        placed = mw.compile_spec(mg.compose(level,level['solution'])[0])
        self.assertEqual(len(placed['electrical']['networks']),1)
        self.assertEqual(len(placed['electrical']['networks'][0]['contacts']),4)
        self.assertEqual(level['goal']['station']['done_when'],
                         {'load_power_w':{'device':'lamp','at_least_w':2,'for_s':.5}})
        self.assertEqual(level['time_s'],4)

    def test_contact_graph_rejects_nonconducting_or_unbound_bodies(self):
        level = next(t for t in e.easy_levels() if t['id']=='easy-power')
        valid = mg.compose(level,level['solution'])[0]
        for mutation in ('unhashable','missing','same','insulator','mismatched','bad-resistance','bad-binding'):
            bad = copy.deepcopy(valid)
            contact = bad['electrical']['contacts'][0]
            if mutation=='unhashable': contact['a']=[]
            elif mutation=='missing': contact['touch'][0]='missing body'
            elif mutation=='same': contact['touch'][1]=contact['touch'][0]
            elif mutation=='insulator':
                next(p for p in bad['parts'] if p['name']==contact['touch'][0])['material']='glass'
            elif mutation=='mismatched': contact['touch'][0]='your battery 1 housing'
            elif mutation=='bad-resistance': contact['resistance_ohm']=-1
            else: next(d for d in bad['electrical']['devices'] if d['kind']=='battery')['terminal_parts']=[]
            with self.subTest(mutation=mutation), self.assertRaises(mw.MachineRefused):
                mw.compile_spec(bad)

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
    def test_both_solar_challenges_need_sunlight_and_a_player_drawn_power_lead(self):
        for identity in ('sun','easy-solar'):
            level=mg.level_by_id(identity)
            with self.subTest(level=identity), tempfile.TemporaryDirectory() as logs:
                wall=next(p for p in level['machine']['parts'] if p['name']=='shade wall')
                self.assertGreaterEqual(wall['size_m'][0],2)
                self.assertGreaterEqual(wall['size_m'][1],1.6)
                self.assertEqual(wall['at_m'][1],wall['size_m'][1]/2)
                good=mg.trial(level,level['solution'],ENGINE,Path(logs),runs=3)
                self.assertEqual(good['worked'],3,good)
                for condition in ('disconnected','shaded','flat'):
                    placed=copy.deepcopy(level['solution'])
                    if condition=='disconnected':placed.pop()
                    elif condition=='shaded':placed[0].update(x_m=-.8 if identity=='sun' else 0,z_m=.6 if identity=='sun' else 0)
                    else:placed[0].update(yaw_deg=0,pitch_deg=0)
                    bad=mg.trial(level,placed,ENGINE,Path(logs),runs=3)
                    self.assertEqual(bad['worked'],0,(condition,bad))
                    result=self.run_spec(mg.compose(level,placed)[0],level['time_s'])
                    panel=result['readouts']['machines']['solar_panels'][0]
                    stores={b['name']:b for b in result['readouts']['machines']['batteries']}
                    if condition=='shaded':
                        self.assertTrue(panel['shaded'])
                        self.assertEqual(panel['shaded_by'],'shade wall')
                        self.assertEqual(panel['power_w'],0)
                    if condition=='disconnected':
                        self.assertEqual(stores['solar battery']['charge_j'],0)
                        self.assertGreater(stores['your solar 1 local battery']['charge_j'],20)
                    self.assertAlmostEqual(panel['sunlight_j'],panel['collected_j']+panel['spilled_j']+panel['heat_j'],delta=.003)
                    print('SOLAR_WALL_AND_LEAD',identity,condition,bad['worked'],'power_w',panel['power_w'],
                          'energy_residual_j',panel['sunlight_j']-panel['collected_j']-panel['spilled_j']-panel['heat_j'])

    def run_spec(self, spec, seconds=1, *, handle_inputs=None):
        with tempfile.TemporaryDirectory(prefix='banjo-electrical-') as logs:
            result = mw.rehearse(mw.compile_spec(spec), ENGINE, Path(logs), seconds=seconds, wall_limit_s=40,
                                 handle_inputs=handle_inputs)
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
                result = self.run_spec(spec, level['time_s'], handle_inputs=level.get('solution_inputs'))
                self.assertTrue(result['stations'][0]['done'], result)
                with tempfile.TemporaryDirectory(prefix='banjo-electrical-nudged-') as logs:
                    trial = mg.trial(level, level['solution'], ENGINE, Path(logs), runs=3,
                                     handle_inputs=level.get('solution_inputs'))
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
        saved = copy.deepcopy(spec)
        compiled = mw.compile_spec(spec)
        with tempfile.TemporaryDirectory(prefix='banjo-live-switch-') as logs:
            session = mw.MachineSession(compiled, ENGINE, Path(logs), paced=True)
            def grip():
                body = session.frame(0, 0)['bodies']
                body = next(b for b in body if b['name'] == 'control handle')
                w, x, y, z = body['orientation_wxyz']
                return [body['position_m'][i] + .08 * v for i, v in enumerate(
                    (1 - 2 * (y*y + z*z), 2 * (x*y + w*z), 2 * (x*z - w*y)))]
            def wait_lamp(on):
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    lamp = next(d for d in session.frame(0, 10)['readouts']['electrical']['devices'] if d['name'] == 'lamp')
                    if (lamp['power_w'] > 2) if on else (lamp['power_w'] < 1e-10):
                        return lamp
                self.fail(f'The physical rocker did not turn the lamp {"on" if on else "off"}: {lamp}')
            try:
                with self.assertRaises(ValueError): session.electrical_switch('control', True)
                session.mechanical_switch_pull('control', 'control handle', grip(), [0, -8, 0])
                self.assertFalse(session.playing, 'queued physical input cannot move a paused world')
                session.play(True)
                self.assertGreater(wait_lamp(True)['power_w'], 2)
                session.mechanical_switch_pull('control', 'control handle', grip(), [0, 0, 0])
                session.mechanical_switch_pull('control', 'control handle', grip(), [0, 8, 0])
                self.assertLess(wait_lamp(False)['power_w'], 1e-10)
                session.mechanical_switch_pull('control', 'control handle', grip(), [0, 0, 0])
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    frame = session.frame(0, 20)
                    pulls = frame['readouts'].get('pulls', [])
                    if pulls and all(p['force_n'] == [0, 0, 0] for p in pulls): break
                self.assertTrue(pulls)
                self.assertTrue(all(p['force_n'] == [0, 0, 0] for p in pulls))
                self.assertGreater(sum(p['work_j'] for p in pulls), 0)
                self.assertGreater(mg.run_energy(compiled, frame['readouts'], frame['t'])['pull_j'], 0)
                self.assertFalse(frame['readouts']['test_pulled'], 'operating a declared handle is legitimate input')
                self.assertFalse(session._test_pulled)
                self.assertFalse(compiled['electrical']['devices'][1]['closed'])
                self.assertEqual(spec, saved, 'runtime movement must not change the saved initial pose')
            finally: session.close()
            reset = mw.MachineSession(mw.compile_spec(saved), ENGINE, Path(logs), paced=True)
            try:
                self.assertFalse(reset._test_pulled)
                reset.play(True)
                deadline = time.monotonic() + 3
                while reset.t < .2 and not reset.error and time.monotonic() < deadline:
                    reset.frame(0, 20)
                self.assertIsNone(reset.error)
                lamp = next(d for d in reset.readouts['electrical']['devices'] if d['name'] == 'lamp')
                self.assertLess(lamp['power_w'], 1e-10, 'reset restores the originally open switch')
                self.assertFalse(reset.readouts.get('pulls'))
            finally: reset.close()

    def test_handle_host_refuses_spoofing_and_general_test_pull_stays_sticky(self):
        with tempfile.TemporaryDirectory(prefix='banjo-handle-boundaries-') as logs:
            host = mw.MachineHost(ENGINE, logs)
            try:
                session = host.get(host.open(e.manual_loop(False))['session'])
                body = session.bodies['control handle']
                point = list(body['position_m'])
                for name, handle, at, force in (
                    ('lamp', 'control handle', point, [0, -8, 0]),
                    ('control', 'control housing', point, [0, -8, 0]),
                    ('control', 'control handle', point, [0, -21, 0]),
                    ('control', 'control handle', [10, 10, 10], [0, -8, 0]),
                    ('control', 'control handle', [float('nan'), .22, 0], [0, -8, 0]),
                    ('control', 'control handle', point, [0, float('nan'), 0]),
                    ('control', 'control handle', point, [0, float('inf'), 0]),
                    ('control', 'control handle', point, [0, True, 0]),
                    ('control', 'control handle', point, [0, -8])):
                    with self.subTest(name=name, body=handle, at=at, force=force):
                        with self.assertRaises(ValueError):
                            session.mechanical_switch_pull(name, handle, at, force)
                self.assertFalse(session._pull_queue)
                self.assertFalse(session._test_pulled)
                session.pull('control handle', point, [0, -1, 0])
                self.assertTrue(session._test_pulled, 'generic Pull is a test even before it is applied')
                session.mechanical_switch_pull('control', 'control handle', point, [0, 0, 0])
                self.assertTrue(session._test_pulled, 'a legitimate release cannot erase a generic test')
                session.play(True)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    frame = session.frame(0, 20)
                    if frame['readouts'].get('test_pulled'): break
                self.assertTrue(frame['readouts']['test_pulled'])
            finally: host.close_all()

    def test_abandoned_mechanical_handle_force_expires_without_becoming_a_test_pull(self):
        with tempfile.TemporaryDirectory(prefix='banjo-abandoned-handle-') as logs:
            session = mw.MachineSession(mw.compile_spec(e.manual_loop(False)), ENGINE, Path(logs), paced=True)
            try:
                session.play(True)
                body = session.bodies['control handle']
                w, x, y, z = body['orientation_wxyz']
                grip = [body['position_m'][i] + .08 * v for i, v in enumerate(
                    (1 - 2 * (y*y + z*z), 2 * (x*y + w*z), 2 * (x*z - w*y)))]
                started = time.monotonic()
                session.mechanical_switch_pull('control', 'control handle', grip, [0, -8, 0])
                # No refresh or zero-force request follows. Both observations
                # below come from the native pull ledger sampled by the host.
                active = None
                while time.monotonic() - started < .75:
                    frame = session.frame(0, 20)
                    self.assertIsNone(frame['error'])
                    self.assertFalse(frame['readouts']['test_pulled'])
                    active = next((p for p in frame['readouts'].get('pulls', [])
                                   if p['body'] == 'control handle'), None)
                    if active and active['force_n'] == [0, -8, 0]: break
                self.assertIsNotNone(active, 'the engine must receive the force before its lease expires')
                self.assertEqual(active['force_n'], [0, -8, 0])
                active_at_s = frame['t']
                released = None
                while time.monotonic() - started < 2:
                    frame = session.frame(0, 20)
                    self.assertIsNone(frame['error'])
                    self.assertFalse(frame['readouts']['test_pulled'])
                    released = next((p for p in frame['readouts'].get('pulls', [])
                                     if p['body'] == 'control handle'), None)
                    if released and released['force_n'] == [0, 0, 0]: break
                elapsed_s = time.monotonic() - started
                self.assertIsNotNone(released)
                self.assertEqual(released['force_n'], [0, 0, 0], 'abandoning the pointer must release native force')
                self.assertGreaterEqual(elapsed_s, 1, 'the one-second lease must not expire prematurely')
                self.assertLess(elapsed_s, 2)
                self.assertGreater(frame['t'], active_at_s)
                self.assertTrue(frame['playing'], 'lease expiry releases the force without stopping the world')
                self.assertGreater(released['work_j'], 0, 'input work remains in the receipt after automatic release')
                self.assertFalse(session._test_pulled)
                with session.lock:
                    self.assertNotIn('control handle', session._switch_force_until)
                lamp = next(d for d in frame['readouts']['electrical']['devices'] if d['name'] == 'lamp')
                self.assertGreater(lamp['power_w'], 2, 'the abandoned drag must actually operate the physical rocker')
                print('ABANDONED_HANDLE_LEASE', dict(elapsed_s=round(elapsed_s, 4),
                    world_s=frame['t'], force_n=released['force_n'], input_work_j=released['work_j'],
                    test_pulled=frame['readouts']['test_pulled']))
            finally: session.close()


if __name__ == '__main__': unittest.main()
