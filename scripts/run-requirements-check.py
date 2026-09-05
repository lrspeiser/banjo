"""Real Codex inventory/shortfall trials. Requires an existing Codex CLI login.

Uses fresh worlds and saves all provider exchanges. Not a fixture or CTest.
Every supplied design is independently assessed; no assistant text grants stock.
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
    if load:
        argv += ['--load', str(load)]
    if save:
        argv += ['--save', str(save)]
    result = subprocess.run(argv, capture_output=True, text=True, check=True)
    (folder / (label + '-results.json')).write_text(result.stdout, encoding='utf-8')
    values = json.loads(result.stdout)
    assert all(item['ok'] for item in values), values
    return values


rows = []
for mode, material in [('short', m) for m in ('glass', 'oak', 'iron')] + [('uncollected', m) for m in ('glass', 'oak', 'iron')] + [('alternative', 'oak')]:
    case = mode + '-' + material
    folder = output / case
    folder.mkdir()
    initial = folder / 'before.json'
    inventory = command(folder, 'initial', [{'type': 'inspect'}], save=initial)[-1]['result']
    densities = {p['id']: p['density_kg_m3'] for p in inventory['physics_signature']['profiles']}
    if mode in ('short', 'alternative'):
        source = material if mode == 'short' else 'iron'
        sphere = {
            'schema_version': 2, 'name': source + ' existing sphere',
            'shape': {'type': 'sphere', 'radius_m': (9.9 / (densities[source] * 4 * math.pi / 3)) ** (1 / 3)},
            'physics': 'rigid-v1', 'material': source,
            'placement': {'tangent_m': -2, 'bitangent_m': 0, 'clearance_m': .002, 'orientation_wxyz': [1, 0, 0, 0]},
            'motion': {'linear_velocity_m_s': [0, 0, 0], 'angular_velocity_rad_s': [0, 0, 0]},
        }
        commands = [{'type': 'collect', 'lot_id': source + '-pile'}, {'type': 'create', 'request_id': 'existing', 'recipe': sphere}, {'type': 'step', 'ticks': 120}]
        if mode == 'alternative':
            commands.append({'type': 'collect', 'lot_id': 'oak-pile'})
        command(folder, 'seed', commands, load=initial, save=initial)
    prompt = f'Design a NEW solid {material} block with full local X/Y/Z lengths 8 cm, 6 cm, 10 cm. Keep existing objects intact. Do not change the substance or size to fit inventory. Explain what I need to collect if short. Start at rest at tangent 2 m, lane 0 m, clearance 2 mm, world-aligned.'
    if mode == 'alternative':
        prompt = 'I cannot afford the new iron block. Explicitly change the design to an OAK solid block with full X/Y/Z lengths 8 cm, 6 cm, 10 cm using collected wood instead. Keep my iron sphere intact. Start at rest at tangent 2 m, lane 0 m, clearance 2 mm, world-aligned.'
    prompt_file = folder / 'prompt.txt'
    prompt_file.write_text(prompt, encoding='utf-8')
    before_bytes = initial.read_bytes()
    before = read(initial)
    started = time.perf_counter()
    with (folder / 'probe.log').open('w', encoding='utf-8') as log:
        run = subprocess.run([str(probe), '--world', str(initial), '--prompt-file', str(prompt_file), '--workspace', str(folder), '--request-id', case, '--apply'], stdout=log, stderr=subprocess.STDOUT)
    seconds = time.perf_counter() - started
    write(folder / 'timing.json', {'seconds': seconds, 'exit_code': run.returncode})
    assert run.returncode == 0, f'{case}: see probe.log'
    assert initial.read_bytes() == before_bytes, 'The source world was changed'
    request_dir = folder / ('assistant-' + case)
    request, reply = read(request_dir / 'request.json'), read(request_dir / 'response.json')
    assert request['editing'] is None, 'New creation must not implicitly select a source object'
    assert reply['status'] == 'proposal' and reply['recipe'] is not None, reply
    candidate = reply['recipe']
    assert candidate['material'] == material
    assert candidate['shape'] == {'type': 'box', 'dimensions_m': [.08, .06, .1]}, 'No silent shrinking'
    assert candidate['motion'] == {'linear_velocity_m_s': [0, 0, 0], 'angular_velocity_rad_s': [0, 0, 0]}
    assert candidate['placement'] == {'tangent_m': 2, 'bitangent_m': 0, 'clearance_m': .002, 'orientation_wxyz': [1, 0, 0, 0]}
    events = [json.loads(line) for line in (request_dir / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
    assert not any(e.get('item', {}).get('type') in ('command_execution', 'mcp_tool_call', 'web_search', 'file_change') for e in events)
    assessment = read(folder / (case + '-assessment.json'))
    required = densities[material] * .08 * .06 * .1
    held = .1 if mode == 'short' else 10 if mode == 'alternative' else 0
    missing = max(0, required - held)
    requirement = assessment['material_requirements'][0]
    for key, value in [('required_mass_kg', required), ('inventory_mass_kg', held), ('recoverable_mass_kg', 0), ('missing_mass_kg', missing), ('collectible_mass_kg', 10 if mode == 'uncollected' else 0), ('missing_after_collection_kg', missing if mode == 'short' else 0)]:
        assert abs(requirement[key] - value) < 1e-12, (key, requirement)
    assert assessment['fabrication_energy_j'] is None
    applied = folder / (case + '-world.json')
    if mode != 'alternative':
        assert assessment['status'] == 'needs_resources' and not assessment['buildable_with_inventory']
        assert assessment['buildable_after_collection'] == (mode == 'uncollected')
        assert not applied.exists(), 'A short design must not be built even with --apply'
    else:
        assert assessment['status'] == 'buildable' and applied.exists()
        state = read(applied)
        assert len(state['objects']) == 2 and state['objects'][0]['recipe'] == before['objects'][0]['recipe']
        assert state['objects'][0]['revision'] == 1 and state['history'][:1] == before['history']
        assert state['objects'][1]['recipe'] == candidate
        assert abs(next(lot for lot in state['lots'] if lot['material'] == 'iron')['remaining_mass_kg'] - .1) < 1e-12
        assert abs(next(lot for lot in state['lots'] if lot['material'] == 'oak')['remaining_mass_kg'] - (10 - required)) < 1e-12
    if mode == 'uncollected':
        # The exact retained recipe becomes affordable only after explicit collection.
        created = folder / 'collected-and-built.json'
        receipt = {'type': 'create', 'request_id': case, 'recipe': candidate}
        result = command(folder, 'collect-build-replay', [
            {'type': 'collect', 'lot_id': material + '-pile'},
            {'type': 'collect', 'lot_id': material + '-pile'},
            {'type': 'assess', 'recipe': candidate}, receipt, receipt,
            {'type': 'step', 'ticks': 240}, {'type': 'inspect'},
        ], load=initial, save=created)
        assert result[0]['result']['collected'] and not result[1]['result']['collected']
        assert result[2]['result']['buildable_with_inventory']
        state = read(created)
        assert len(state['objects']) == 1 and len(state['history']) == 1 and state['ticks'] == 240
        assert state['objects'][0]['recipe'] == candidate
        assert abs(next(lot for lot in state['lots'] if lot['material'] == material)['remaining_mass_kg'] + required - 10) < 1e-12
    rows.append({'case': case, 'seconds': seconds, 'status': assessment['status'], 'required_kg': required, 'inventory_kg': held, 'missing_kg': missing, 'explanation': reply['explanation'], 'usage': next(e['usage'] for e in events if e['type'] == 'turn.completed')})
    write(output / 'results.json', rows)
    print(json.dumps(rows[-1]), flush=True)

files = {str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(output.rglob('*')) if path.is_file()}
write(output / 'manifest.json', {'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip(), 'working_tree': subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo, text=True), 'sha256': files})
