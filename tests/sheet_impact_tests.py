"""Actual native regression plus a separate fail-closed free-form qualification.

Regression passing is NOT a claim that the qualification gate passes. The
qualification emits every failure and exits nonzero on missing user outcomes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

MATERIALS=('iron','aluminum','glass','ceramic','oak','rubber','ice','concrete')

class Native:
    def __init__(self,binary):
        self.child=subprocess.Popen([str(binary),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    def send(self,**value):
        self.child.stdin.write(json.dumps(value)+'\n');self.child.stdin.flush()
        result=json.loads(self.child.stdout.readline())
        if 'state' in result:
            state=result['state']
            assert len(state['positions'])==800,'matter disappeared'
            assert abs(state['energy_residual_j'])<1e-9,'unaccounted pipeline energy'
            assert state['momentum_residual_n_s']<1e-9,'unaccounted linear momentum'
            assert state['angular_residual_kg_m2_s']<1e-9,'unaccounted angular momentum'
        return result
    def close(self):
        self.child.stdin.close();self.child.wait(timeout=3);self.child.stdout.close()

def run(binary,qualify=False):
    native=Native(binary);rows=[];start=time.monotonic()
    try:
        for material in MATERIALS:
            for pick in MATERIALS:
                r=native.send(op='create',material=material,pick=pick)
                assert r['ok'] and r['state']['broken_bonds']==0 and r['state']['open_columns']==0
                assert r['state']['max_displacement_m']==0
                initial=r['state']
                r=native.send(op='advance',steps=1000);s=r['state']
                rows.append(dict(material=material,pick=pick,ok=r['ok'],error=r.get('error'),
                                 steps=s['steps'],broken_bonds=s['broken_bonds'],
                                 dt_s=s['dt_s'],time_s=s['time_s'],
                                 displacement_m=s['max_displacement_m'],plastic_extension_m=s['max_plastic_extension_m'],
                                 initial_energy_j=s['initial_energy_j'],numerical_energy_j=s['numerical_energy_j'],
                                 energy_residual_j=s['energy_residual_j']))
                if r['ok']:
                    assert s['max_displacement_m']>0,f'{material}/{pick}: no actual response'
                    assert s['source']!=initial['source'],'tool motion did not change'
                else:
                    assert r.get('error'),'refusal was silently accepted'
                    assert native.send(op='snapshot')['state']==s,'refusal changed accepted state'
        # Same zero-velocity experiment is not allowed to fracture itself.
        for material in ('glass','oak','iron'):
            native.send(op='create',material=material,pick='iron',speed_m_s=0)
            s=native.send(op='advance',steps=1000)['state']
            assert s['broken_bonds']==0 and s['max_displacement_m']==0 and s['max_plastic_extension_m']==0
        # Long reference strike: actual topology AND absence of matter along
        # through-sheet probes; a hidden crack counter cannot satisfy this.
        native.send(op='create',material='glass',pick='iron')
        for _ in range(60):
            r=native.send(op='advance',steps=1000)
            assert r['ok'],r.get('error')
        glass=r['state'];assert glass['broken_bonds']>0 and glass['detached_cells']>0 and glass['open_columns']>0
        assert glass['max_displacement_m']>.004,'cells never visibly leave the sheet'
        assert abs(glass['numerical_energy_j'])<.001*glass['initial_energy_j'],'numerical correction dominates result'
        # Reproduce the actual browser click. Refusal must retain the last
        # accepted state and all its ledgers, never half-commit a failed step.
        native.send(op='create',material='glass',pick='iron',point_m=[.0007808484689576858,0,.0004226478800741229])
        off=native.send(op='advance',steps=1000)
        if not off['ok']:
            after=native.send(op='snapshot');assert after['state']==off['state'],'refusal changed accepted state'
        result=dict(schema='banjo.sheet-verification.v1',native_sha256=hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
                    matrix=rows,glass_reference={k:v for k,v in glass.items() if k not in ('positions','broken_interfaces')},
                    off_centre={k:v for k,v in off.items() if k!='state'},wall_s=time.monotonic()-start,
                    release_ready=False,remaining_gates=['off-centre free-form contact','calibrated unloaded metal dent',
                      'tool fracture','finite-cell debris contact and settling','timestep/resolution refinement','posts contact'])
        output=Path('build/material-lab/sheet-verification.json');output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k not in ('matrix','glass_reference')}),flush=True)
        print('64 native diagnostics checked; '+str(sum(not row['ok'] for row in rows))+' contact refusals; glass reference opening verified. Free-form release gate: BLOCKED.',flush=True)
        return 1 if qualify else 0
    finally:native.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('binary',type=Path);p.add_argument('--qualify',action='store_true')
    args=p.parse_args();raise SystemExit(run(args.binary,args.qualify))
