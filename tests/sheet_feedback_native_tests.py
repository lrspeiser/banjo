"""Actual native inputs for viewer diagnostics; not material qualification."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
binary = Path(sys.argv[1]).resolve(strict=True)
child = subprocess.Popen([str(binary), '--serve'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
def send(value):
    child.stdin.write(json.dumps(value)+'\n'); child.stdin.flush()
    return json.loads(child.stdout.readline())
try:
    cases=[]
    for material in ('glass','ice','oak','iron'):
        initial=send(dict(op='create',material=material,pick='iron',point_m=[0,0,0]))
        assert initial['ok'] and initial['state']['broken_bonds']==0
        # Compare a common physical interval, to within one accepted native step,
        # rather than pretending equal step counts imply equal elapsed time.
        dt=initial['state']['dt_s']
        remaining=int(2e-5/dt)
        while remaining:
            steps=min(remaining,1000)
            result=send(dict(op='advance',steps=steps))
            assert result['ok'],result.get('error')
            remaining-=steps
        state=result['state']
        assert len(state['positions'])==800
        assert len(state['broken_interfaces'])==state['broken_bonds']
        assert all(0<=i<800 for pair in state['broken_interfaces'] for i in pair)
        assert 0<=2e-5-state['time_s']<dt*1.001 and abs(state['energy_residual_j'])<1e-9
        cases.append(dict(material=material,initial=initial['state'],after=state))
    send(dict(op='create',material='ice',pick='iron',point_m=[0,0,0]))
    for _ in range(3):
        refusal=send(dict(op='advance',steps=1000))
        if not refusal['ok']:break
    assert not refusal['ok'] and refusal.get('error'),'known ice continuation refusal was hidden'
    assert send(dict(op='snapshot'))['state']==refusal['state'],'refusal lost the accepted state'
    output=root/'build/sheet-feedback-results.json'
    output.write_text(json.dumps(dict(native_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),observation_s=2e-5,cases=cases,ice_continuation=refusal)),encoding='utf-8')
    print('PASS: actual glass/ice/oak/iron native snapshots, bond endpoints and retained states. Physical qualification remains open.')
finally:
    child.stdin.close(); child.wait(timeout=3); child.stdout.close()
