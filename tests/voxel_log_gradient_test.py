"""Experimental finite-rotation runs: bound state and expose, never hide, refusals.

This is qualification evidence, not a passing realism/realtime gate. The default
native-motor regression remains separate and must still pass unchanged.
"""
import json, math, subprocess, sys, time
from pathlib import Path

native = Path(sys.argv[1]).resolve()
for material, ball in [('glass', 'iron'), ('oak', 'iron'), ('iron', 'iron'), ('ice', 'iron'), ('glass', 'glass')]:
    proc = subprocess.Popen([str(native), '--serve'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    def request(command):
        proc.stdin.write(json.dumps(command) + '\n'); proc.stdin.flush()
        return json.loads(proc.stdout.readline())
    try:
        declaration = {'sheet': material, 'ball': ball, 'face_law': 'log-gradient'}
        reply = request({'op': 'create', 'declaration': declaration}); assert reply['ok'], reply.get('error')
        initial = reply['state']; masses = {c['id']: c['mass_kg'] for c in initial['cells']}
        assert initial['qualification']['face_law'] == 'log-gradient'
        assert initial['qualification']['calibrated'] is False
        started = time.monotonic()
        while reply['ok'] and reply['state']['time_s'] < 2 - 1e-9:
            reply = request({'op': 'advance', 'steps': min(16, round((2 - reply['state']['time_s']) / initial['dt_s']))})
            state = reply['state']
            assert {c['id']: c['mass_kg'] for c in state['cells']} == masses
            assert state['diagnostics']['unclosed_energy_j'] <= .10001
            assert all(math.isfinite(x) for c in state['cells'] for k in ['position_m', 'velocity_m_s', 'spin_rad_s'] for x in c[k])
        state = reply['state']
        if reply['ok']:
            assert abs(state['time_s'] - 2) < 1e-8
        else:
            assert 'energy gate refused' in reply['error'], reply['error']
            assert 1.4 < state['time_s'] < 2, 'unexpected refusal before impact'
            assert request({'op': 'snapshot'})['state'] == state, 'failed trial changed the last accepted state'
        if material in ['oak', 'iron']:
            assert reply['ok'], 'elastic comparison regressed'
            assert state['objects'][0]['pieces'] == 1 and state['objects'][0]['broken_faces'] == 0
        elapsed = time.monotonic() - started
        print(json.dumps({'declaration': declaration, 'completed': reply['ok'], 'calibrated': False,
            'time_s': state['time_s'], 'wall_s': elapsed, 'realtime_ratio': state['time_s'] / elapsed,
            'error': reply.get('error'), 'substeps': state['substeps'], 'rejected_trials': state['rejected_trials'],
            'sheet': state['objects'][0], 'ball': state['objects'][1], 'diagnostics': state['diagnostics'],
            'contact_audit': state['contact_audit']}), flush=True)
    finally:
        proc.terminate(); proc.wait(timeout=5)
print('BOUNDED EXPERIMENT: finite-rotation states/refusals measured; full energy, realism and realtime gates remain OPEN', flush=True)
