"""Actual native impact controls for read-only global-step driver reporting."""
import json, subprocess, sys
from pathlib import Path

native=Path(sys.argv[1]).resolve()
for material in ['glass','oak','iron','ice']:
    proc=subprocess.Popen([str(native),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    def call(command):
        proc.stdin.write(json.dumps(command)+'\n');proc.stdin.flush()
        reply=json.loads(proc.stdout.readline());assert reply['ok'],reply.get('error')
        return reply['state']
    try:
        first=call({'op':'create','declaration':{'sheet':material,'height_m':.1}})
        assert first['diagnostics']['profile']['motion']['split_proposals']==0
        for _ in range(9):state=call({'op':'advance','steps':16})
        assert abs(state['time_s']-.15)<1e-9
        motion=state['diagnostics']['profile']['motion']
        assert motion['split_proposals']>0 and motion['max_depth']>0
        assert sum(x['split_proposals'] for x in motion['drivers'])==motion['split_proposals']
        bodies={x['id']:x for x in state['cells']}
        for driver in motion['drivers']:
            cell=bodies[driver['body']]
            assert not cell['fixed'] and driver['object']==cell['object']
        assert {x['id']:x['mass_kg'] for x in state['cells']}=={x['id']:x['mass_kg'] for x in first['cells']}
        print(material+': actual impact, retained source mass, valid dynamic driver IDs and recursive counters',flush=True)
    finally:
        proc.terminate();proc.wait(timeout=3)
print('PASS glass/oak/iron/ice motion reporting; physical accuracy is qualified separately')
