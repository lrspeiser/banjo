"""Real Codex selected-object trials; not a fixture provider or a CTest test.

Requires an already configured Codex CLI login. Each case uses a fresh world
and records all inputs, provider exchanges, accepted state and lifecycle replay.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--build-dir', default='build/win-integration')
parser.add_argument('--out', required=True)
parser.add_argument('--cases', nargs='+', choices=('glass', 'oak', 'iron', 'door', 'energy'), default=['glass', 'oak', 'iron', 'door', 'energy'])
args = parser.parse_args()
repo = Path(__file__).resolve().parent.parent
build = (repo / args.build_dir / 'Release').resolve()
output = (repo / args.out).resolve()
output.mkdir(parents=True, exist_ok=False)
creator = build / 'banjo_creator_cli.exe'
probe = build / 'banjo_assistant_probe.exe'

def write(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def command(folder, label, commands, load=None, save=None):
    path = folder / (label + '-commands.json')
    write(path, commands)
    argv = [str(creator), '--commands', str(path)]
    if load: argv += ['--load', str(load)]
    if save: argv += ['--save', str(save)]
    result = subprocess.run(argv, capture_output=True, text=True, check=True)
    (folder / (label + '-results.json')).write_text(result.stdout, encoding='utf-8')
    values = json.loads(result.stdout)
    assert all(item['ok'] for item in values), values
    return values

rows = []
for case in args.cases:
    material = case if case in ('glass', 'oak', 'iron') else 'oak'
    folder = output / case
    folder.mkdir()
    stock = folder / 'stock.json'
    inventory = command(folder, 'collect', [{'type': 'collect', 'lot_id': material + '-pile'}, {'type': 'inspect'}], save=stock)[-1]['result']
    density = next(p['density_kg_m3'] for p in inventory['physics_signature']['profiles'] if p['id'] == material)
    radius = (9.9 / (density * 4 * math.pi / 3)) ** (1 / 3)
    recipe = {
        'schema_version': 2, 'name': material + ' collected sphere',
        'shape': {'type': 'sphere', 'radius_m': radius}, 'physics': 'rigid-v1', 'material': material,
        'placement': {'tangent_m': -2, 'bitangent_m': 0, 'clearance_m': .002, 'orientation_wxyz': [1, 0, 0, 0]},
        'motion': {'linear_velocity_m_s': [0, 0, 0], 'angular_velocity_rad_s': [0, 0, 0]},
    }
    initial = folder / 'before.json'
    first_id = case + '-original'
    seed = command(folder, 'seed', [
        {'type': 'create', 'request_id': first_id, 'recipe': recipe},
        {'type': 'step', 'ticks': 120}, {'type': 'inspect'},
    ], load=stock, save=initial)[-1]['result']
    assert seed['objects'][0]['kinetic_energy_j'] > 0
    assert abs(seed['inventory'][0]['mass_kg'] - .1) < 1e-12
    before_bytes = initial.read_bytes()
    prompt = f'Rebuild the selected {material} sphere into a solid {material} block with full local X/Y/Z lengths 8 cm, 6 cm, 10 cm. Reuse its intact material. Start at rest, align its bottom face with the 10-degree ramp, tangent -2 m, lane 0 m, with 2 mm clearance below its lowest point.'
    if case == 'door':
        prompt = 'Rebuild the selected oak sphere into a functioning hinged door with an attached metal hinge. If the required mechanics or resources are unavailable, return clarification without a substitute object.'
    if case == 'energy':
        prompt = 'Rebuild the selected oak sphere as a block only if a workbench can supply and account for its fabrication energy within 10 joules. If energy-limited fabrication is unavailable, return clarification without a substitute object.'
    prompt_file = folder / 'prompt.txt'
    prompt_file.write_text(prompt, encoding='utf-8')
    request_id = case + '-revision'
    started = time.perf_counter()
    with (folder / 'probe.log').open('w', encoding='utf-8') as log:
        result = subprocess.run([str(probe), '--world', str(initial), '--prompt-file', str(prompt_file), '--workspace', str(folder), '--request-id', request_id, '--edit-object', '1', '--apply'], stdout=log, stderr=subprocess.STDOUT)
    elapsed = time.perf_counter() - started
    write(folder / 'timing.json', {'seconds': elapsed, 'exit_code': result.returncode})
    assert result.returncode == 0, f'{case}: see {folder / "probe.log"}'
    assert initial.read_bytes() == before_bytes, 'Input world changed in place'
    request = read(folder / ('assistant-' + request_id) / 'request.json')
    response = read(folder / ('assistant-' + request_id) / 'response.json')
    assert request['editing']['object_id'] == 1 and request['editing']['expected_revision'] == 1
    assert abs(request['editing']['recoverable_mass_kg'] - 9.9) < 1e-12
    assert len(request['editing']['available_after_recovery']) == 1
    assert abs(request['editing']['available_after_recovery'][0]['mass_kg'] - 10) < 1e-12
    assert 'history' not in request['world']
    assert request['world']['capabilities']['energy']['fabrication_supported'] is False
    events = [json.loads(line) for line in (folder / ('assistant-' + request_id) / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
    assert not any(e.get('item', {}).get('type') in ('command_execution', 'mcp_tool_call', 'web_search', 'file_change') for e in events)
    usage = next(e['usage'] for e in events if e['type'] == 'turn.completed')
    row = {'case': case, 'seconds': elapsed, 'status': response['status'], 'usage': usage}
    applied = folder / (request_id + '-world.json')
    if case in ('door', 'energy'):
        assert response['status'] == 'clarification' and response['recipe'] is None
        assert not applied.exists(), 'Clarification must not publish a world'
    else:
        assert response['status'] == 'proposal'
        candidate = response['recipe']
        assert candidate['material'] == material and candidate['shape'] == {'type': 'box', 'dimensions_m': [.08, .06, .1]}
        assert candidate['motion'] == {'linear_velocity_m_s': [0, 0, 0], 'angular_velocity_rad_s': [0, 0, 0]}
        state = read(applied)
        inspect = read(folder / (request_id + '-inspect.json'))
        assert state['world_version'] == 3 and state['ticks'] == 360
        assert len(state['objects']) == 1 and len(state['history']) == 2
        obj = state['objects'][0]
        assert obj['id'] == 1 and obj['revision'] == 2 and obj['request_id'] == first_id and obj['recipe'] == candidate
        change = state['history'][-1]
        assert change['operation'] == 'rebuild' and change['request_id'] == request_id and change['expected_revision'] == 1 and change['tick'] == 120
        expected_mass = density * .08 * .06 * .1
        assert expected_mass > .1
        assert abs(inspect['objects'][0]['mass_kg'] - expected_mass) < 1e-12
        assert change['mechanics_before']['kinetic_energy_j'] > 0 and change['mechanics_after']['kinetic_energy_j'] == 0
        lot = next(lot for lot in state['lots'] if lot['material'] == material)
        assert abs(lot['remaining_mass_kg'] + expected_mass - 10) < 1e-12
        receipt = {'type': 'reclaim', 'request_id': case + '-reclaim', 'object_id': 1, 'expected_revision': 2}
        replay = command(folder, 'reclaim-replay', [
            receipt,
            {'type': 'rebuild', 'request_id': request_id, 'object_id': 1, 'expected_revision': 1, 'recipe': candidate},
            receipt,
            {'type': 'create', 'request_id': first_id, 'recipe': recipe},
            {'type': 'inspect'},
        ], load=applied, save=folder / 'reclaimed.json')[-1]['result']
        assert not replay['objects'] and replay['history_count'] == 3 and replay['ticks'] == 360
        assert abs(next(lot for lot in replay['lots'] if lot['material'] == material)['remaining_mass_kg'] - 10) < 1e-12
        row.update({'mass_kg': expected_mass, 'reused_kg': expected_mass, 'returned_kg': 9.9 - expected_mass, 'free_stock_before_kg': .1, 'free_stock_after_kg': lot['remaining_mass_kg'], 'authoring_kinetic_before_j': change['mechanics_before']['kinetic_energy_j'], 'authoring_kinetic_after_j': 0, 'reclaimed_stock_kg': 10})
    rows.append(row)
    write(output / 'results.json', rows)
    print(f'{case}: {response["status"]}, {elapsed:.3f}s', flush=True)

write(output / 'manifest.json', {
    'base_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip(),
    'source_sha256': {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in ('src/creator/CreatorWorld.cpp', 'src/creator/CodexAssistant.cpp', 'src/app/assistant_probe_main.cpp', 'scripts/run-revision-check.py')},
    'scope': 'Real default-provider Codex calls. Three-material selected rebuild/reclaim and unsupported door/energy cases when included. No fabrication energy, material calibration or native UI claim.',
})
