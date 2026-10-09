"""Actual four-material CPU admission, analytical dynamics and atomic rollback."""
import argparse,json,os,sys,time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from cpu_coupled_world import CpuCoupledWorld,implementation_hash
from coupled_solver import TrialFailure

def main(args):
    os.environ['BANJO_COUPLED_CPU_LIBRARY']=str(args.library.resolve());runs=[]
    for material in ('glass','oak','iron','ice'):
        w=CpuCoupledWorld(dict(material=material,height_m=.001,dt_s=1/240,representation_policy='partitioned-flight'))
        initial=w.snapshot();start=time.perf_counter();contact=False
        for _ in range(10):
            s=w.advance(1)
            assert not s['qualification']['gpu'] and s['qualification']['device']=='cpu'
            assert abs(s['diagnostics']['global_energy_residual_j'])<5e-9
            for a in s['substep_accounts']:
                assert abs(a['energy_residual_j'])<=a['energy_tolerance_j']
                assert np.linalg.norm(a['P_residual_n_s'])<1e-9 and np.linalg.norm(a['L_residual_n_m_s'])<1e-9
                contact|=a['ledger'][8]>0
        ballistic=initial['cells'][-1]['position_m'][1]-.5*9.81*w.time**2
        assert contact and s['cells'][-1]['position_m'][1]>ballistic+1e-4
        r=CpuCoupledWorld.from_checkpoint(w.export_checkpoint());assert r.export_checkpoint()==w.export_checkpoint()
        assert np.array_equal(r.eval.bodies,w.eval.bodies) and np.array_equal(r.eval.edges,w.eval.edges)
        a=w.advance(1);b=r.advance(1)
        for field in ('cells','history_arrays','diagnostics','substep_accounts'):assert a[field]==b[field],field
        runs.append(dict(material=material,conditions=w.d,physical_s=w.time,wall_s=time.perf_counter()-start,diagnostics=a['diagnostics'],resume_exact=True))
        print(material,'CPU sheet control accepted',flush=True)
        # Malformed candidates refuse without modifying authoritative matter.
        original=w.eval.bodies.copy();v=original[:,14:20].copy();v[0,0]=np.nan
        try:w.eval.evaluate(v,1/240);raise AssertionError('Nonfinite candidate admitted')
        except ValueError:pass
        assert np.array_equal(w.eval.bodies,original)
        for raw in (dict(device='cuda:0'),dict(pipeline='parallel'),dict(linear_backend='cupy-reference')):
            try:CpuCoupledWorld(raw);raise AssertionError('Silent backend fallback')
            except ValueError:pass
    w=CpuCoupledWorld({});initial=w.snapshot();b=w.eval.bodies.copy();e=w.eval.edges.copy();solve=w.eval.solve;calls=0
    def fail(*a,**kw):
        nonlocal calls
        calls+=1
        if calls>1:raise TrialFailure('Injected CPU convergence refusal')
        return solve(*a,**kw)
    w.eval.solve=fail
    try:w.advance(2);raise AssertionError('Failed interval admitted')
    except RuntimeError:pass
    refused=w.snapshot();failure=refused.pop('rejected_candidate')
    assert refused==initial and failure['interval_rolled_back'] and failure['failed_interval_substeps']==1
    assert np.array_equal(w.eval.bodies,b) and np.array_equal(w.eval.edges,e)
    report=dict(schema='banjo.cpu-coupled-evidence.v1',implementation_sha256=implementation_hash(),numpy_version=np.__version__,runs=runs,atomic_rollback=True,full_fracture_qualified=False)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('PASS four-material CPU contacts / resume / refusal / rollback',flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--library',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())
