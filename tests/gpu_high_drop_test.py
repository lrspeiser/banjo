"""Ten metre primitive control, independent collision oracle and origin mapping.

This does not admit connected-sheet fracture or sphere internal deformation.
"""
import argparse, json, math, sys, time
from pathlib import Path
import cupy as cp
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from gpu_coupled_world import GpuCoupledWorld, source_hash
from gpu_contact_timing_test import oracle_state

def main(output):
    profiles = json.loads((ROOT/'client/voxel-lab/material-laws.json').read_text())['profiles']
    report = dict(source_sha256=source_hash(), scope='10 m primitive / fixed plane, frictionless linear compliance; no fracture admission', runs=[])
    for p in profiles:
        errors={}
        for hz,phase in ((240,.25),(240,.0625),(960,.25),(960,.0625)):
            w=GpuCoupledWorld(dict(experiment='freefall',ball_material=p['material'],ball_mass_kg=.1,height_m=10,dt_s=1/hz,contact_resolution=f'phase-{phase}',representation_policy='partitioned-flight'))
            radius=w.snapshot()['cells'][-1]['radius_m']
            omega=math.sqrt(2/(1/p['young_pa']+1/211e9)*min(.01,2*radius)/.1)
            start=time.perf_counter();max_x=max_v=max_P=max_L=0.;contacts=rebases=0;resumed=False
            while w.time<2-1e-12:
                count=min(round((2-w.time)*hz),w.snapshot()['render_schedule']['safe_rigid_flight_steps'])
                previous=w.time;s=w.advance(count);t=previous
                for a in s['substep_accounts']:
                    t+=a['dt_s'];gap=a['poses_wxyz'][-1][1]-radius;v=a['velocities'][-1][1]
                    x,exact_v=oracle_state(t,10,omega)
                    max_x=max(max_x,abs(gap-x));max_v=max(max_v,abs(v-exact_v))
                    max_P=max(max_P,float(np.linalg.norm(a['P_residual_n_s'])));max_L=max(max_L,float(np.linalg.norm(a['L_residual_n_m_s'])))
                    assert abs(a['energy_residual_j'])<=a['energy_tolerance_j']
                    contacts+=gap<0;rebases+=len(a['coordinate_rebases'])
                # Reopen after a real coupled contact step, including the new
                # numerical origin and its unchanged physical state/history.
                if contacts and not resumed:
                    r=GpuCoupledWorld.from_checkpoint(w.export_checkpoint())
                    assert np.array_equal(cp.asnumpy(r.eval.bodies),cp.asnumpy(w.eval.bodies))
                    assert r.export_checkpoint()==w.export_checkpoint()
                    w=r;resumed=True
            assert contacts>0 and rebases>0 and resumed
            assert max_P<1e-9 and max_L<1e-9
            assert abs(s['diagnostics']['global_energy_residual_j'])<1e-8
            # Declared isolated-control accuracy bounds against the exact
            # compliance oracle, independently of conservation closure.
            assert max_x<(6e-6 if phase==.25 else 4e-7)
            assert max_v<(.14 if phase==.25 else .01)
            errors[hz,phase]=(max_x,max_v)
            row=dict(material=p['material'],conditions=w.d,physical_s=w.time,wall_s=time.perf_counter()-start,contacts=contacts,coordinate_rebases=rebases,max_position_error_m=max_x,max_velocity_error_m_s=max_v,max_P_residual_n_s=max_P,max_L_residual_n_m_s=max_L,diagnostics=s['diagnostics'],resume_exact=True)
            report['runs'].append(row);print(p['material'],hz,phase,max_x,max_v,row['wall_s'],flush=True)
        for hz in (240,960):
            assert all(errors[hz,.0625][i]<errors[hz,.25][i]/2 for i in (0,1)),errors
        # Exact basis-only map: physical columns, mechanical observables and
        # all native edge history are byte-identical; only columns 20:26 move.
        b=cp.asnumpy(w.eval.bodies);e=cp.asnumpy(w.eval.edges);mechanics=w.mechanics(b)
        receipts=w.local_primitive_origins(b)
        after=cp.asnumpy(w.eval.bodies)
        assert np.array_equal(after[:,:20],b[:,:20]) and np.array_equal(cp.asnumpy(w.eval.edges),e)
        assert all(np.array_equal(x,y) for x,y in zip(mechanics,w.mechanics(after)))
        # Publication failure after rebasing restores the entire private basis.
        w=GpuCoupledWorld(dict(experiment='freefall',ball_material=p['material'],height_m=10,dt_s=1/240,representation_policy='partitioned-flight'))
        w.advance(16);saved_b=cp.asnumpy(w.eval.bodies).copy();bindings=w.registry.binding_state();w.representations=None
        rebased=[];original=w.local_primitive_origins
        def checked(bodies):
            receipts=original(bodies);rebased.extend(receipts);return receipts
        w.local_primitive_origins=checked
        def fail(*args):raise RuntimeError('Injected publication failure after numerical-origin update')
        w._snapshot=fail
        try:w.advance(1);raise AssertionError('Injected failure admitted')
        except RuntimeError:pass
        assert rebased and np.array_equal(cp.asnumpy(w.eval.bodies),saved_b) and w.registry.binding_state()==bindings
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n')
    print('PASS meaningful primitive collision/refinement, exact resume and numerical-origin rollback; full sheet gate remains open',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);main(parser.parse_args().output)
