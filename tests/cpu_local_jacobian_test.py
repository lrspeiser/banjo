"""Full CPU reference parity, request boundaries and measured local Jacobians."""
import argparse,json,os,sys,time,statistics
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from cpu_coupled_world import CpuCoupledWorld,CpuCoupledEvaluator,implementation_hash
PUBLIC=('poses','residual','history','forces','ledger','faults')

def exact(a,b):
    for key in PUBLIC:
        assert a[key].shape==b[key].shape and a[key].dtype==b[key].dtype
        assert a[key].tobytes()==b[key].tobytes(),(key,np.nanmax(abs(a[key]-b[key])))

def candidates(e,base):
    original=base.ravel();d=len(e.dynamic);v=np.broadcast_to(original,(2*d,len(original))).copy()
    ids=np.arange(d);delta=1e-12*np.maximum(1,abs(original[e.dynamic]))
    v[ids,e.dynamic]+=delta;v[d+ids,e.dynamic]-=delta
    return v

def physical(state):
    return {k:state[k] for k in ('time_s','dt_s','ticks','cells','history_arrays','diagnostics','substep_accounts')}

def main(args):
    os.environ['BANJO_COUPLED_CPU_LIBRARY']=str(args.library.resolve());runs=[];rng=np.random.default_rng(875)
    for material in ('glass','oak','iron','ice'):
        w=CpuCoupledWorld(dict(material=material,pipeline='local-jacobian',height_m=.001,dt_s=1/240));e=w.eval
        bodies=e.bodies.copy();edges=e.edges.copy();count=0;faults=set();timing={}
        for scale in (1e-6,.01,1e5):
            base=rng.normal(size=(e.n,6))*scale;base[e.bodies[:,1]==0]=0
            v=candidates(e,base);out=e.evaluate(base,1/960)
            local=e.evaluate(v,1/960,_jacobian_base=out);full=e.evaluate(v,1/960);exact(local,full)
            count+=len(v);faults.update(local['faults'].tolist())
        # A zero-contact graph, support contacts, contact activation changes,
        # and a single body near the finite-frame rotation branch.
        for rotation in (1e14,1e200):
            base=np.zeros((e.n,6));base[3,3]=rotation;v=candidates(e,base);out=e.evaluate(base,1/960)
            with np.errstate(invalid='ignore',over='ignore'):
                local=e.evaluate(v,1/960,_jacobian_base=out);full=e.evaluate(v,1/960)
            exact(local,full);count+=len(v);faults.update(local['faults'].tolist())
            # Native callers need not zero their buffers. Early faults must
            # preserve the same unwritten suffixes as the full reference.
            def filled():return {k:np.full_like(local[k],123) for k in PUBLIC}
            a=filled();b=filled();changed=np.tile(e.dynamic//6,2).astype(np.int32)
            assert e.lib.banjo_coupled_cpu_trials(e.bodies,e.n,e.edges,e.m,v,len(v),1/960,-9.81,*(a[k] for k in PUBLIC))==0
            assert e.lib.banjo_coupled_cpu_local_trials(e.bodies,e.n,e.edges,e.m,base,v,changed,len(v),1/960,-9.81,*(b[k] for k in PUBLIC))==0
            exact(a,b)
        base=np.zeros((e.n,6));v=candidates(e,base);out=e.evaluate(base,1/960)
        for label,kw in (('full',{}),('local',{'_jacobian_base':out})):
            e.evaluate(v,1/960,**kw);times=[]
            for _ in range(7):
                start=time.perf_counter();e.evaluate(v,1/960,**kw);times.append(time.perf_counter()-start)
            timing[label]=dict(median_ms=statistics.median(times)*1000,max_ms=max(times)*1000)
        # Extra changes, including signed zero, are refused, not silently
        # treated as a single-body trial or routed to an approximate fallback.
        bad=v.copy();claimed=e.dynamic[0]//6;other=next(i for i in range(e.n) if i!=claimed)
        for value in (1.,-0.):
            bad[:]=v;bad[0,6*other]=value
            try:e.evaluate(bad,1/960,_jacobian_base=out);raise AssertionError('Undeclared body change accepted')
            except ValueError:pass
        buffers={k:np.full_like(out[k],123.) for k in PUBLIC}
        # Native declaration refusal must leave every caller buffer untouched.
        invalid=np.repeat(base[None],2,axis=0);invalid[0,other,0]=1.
        changed=np.full(2,claimed,dtype=np.int32)
        code=e.lib.banjo_coupled_cpu_local_trials(e.bodies,e.n,e.edges,e.m,base,invalid,changed,2,1/960,-9.81,
            *(buffers[k] for k in PUBLIC))
        assert code==-1 and all(np.all(a==123) for a in buffers.values())
        assert np.array_equal(e.bodies,bodies) and np.array_equal(e.edges,edges)
        # Real accepted material trajectories, full reactions/work, restart,
        # and next-step histories must match the unoptimized reference exactly.
        reference=CpuCoupledWorld(dict(material=material,pipeline='serial-reference',height_m=.001,dt_s=1/240))
        wall={'full':0.,'local':0.}
        for _ in range(10):
            start=time.perf_counter();a=w.advance(1);wall['local']+=time.perf_counter()-start
            start=time.perf_counter();b=reference.advance(1);wall['full']+=time.perf_counter()-start
            assert physical(a)==physical(b)
        restored=CpuCoupledWorld.from_checkpoint(w.export_checkpoint())
        assert restored.export_checkpoint()==w.export_checkpoint()
        assert physical(restored.advance(1))==physical(w.advance(1))==physical(reference.advance(1))
        runs.append(dict(material=material,conditions=w.d,sheet_young_pa=float(bodies[3,3]),sheet_mass_kg=float(bodies[3:12,1].sum()),candidate_comparisons=count,fault_codes=sorted(faults),
            jacobian_candidates=len(v),trial_timing=timing,ten_ticks_wall_s=wall,
            physical_s=a['time_s'],diagnostics=a['diagnostics'],resume_exact=True))
        print(material,'exact local/full candidates, histories and restart',flush=True)
    # m=0 and one dynamic body exercise the empty-contribution path.
    ball=CpuCoupledWorld(dict(experiment='freefall',pipeline='local-jacobian')).eval.bodies[-1:]
    e=CpuCoupledEvaluator(ball,[],pipeline='local-jacobian');base=np.zeros((1,6));v=candidates(e,base)
    exact(e.evaluate(v,1/240,_jacobian_base=e.evaluate(base,1/240)),e.evaluate(v,1/240))
    # The bounded native ABI accepts signed-zero prescribed mass. Preserve
    # reference gravity component signs even when no contact can erase them.
    plane=CpuCoupledWorld(dict(experiment='freefall')).eval
    b=plane.bodies.copy();b[:,1]=0.;b[0,1]=-0.;base=np.zeros((plane.n,6));v=base[None].copy()
    template=plane.evaluate(v,1/240);a={k:np.zeros_like(template[k]) for k in PUBLIC};z={k:np.zeros_like(template[k]) for k in PUBLIC}
    changed=np.array([1],dtype=np.int32)
    assert plane.lib.banjo_coupled_cpu_trials(b,plane.n,plane.edges,plane.m,v,1,1/240,-9.81,*(a[k] for k in PUBLIC))==0
    assert plane.lib.banjo_coupled_cpu_local_trials(b,plane.n,plane.edges,plane.m,base,v,changed,1,1/240,-9.81,*(z[k] for k in PUBLIC))==0
    exact(a,z)
    # Maximum body and candidate capacity, with entirely separated contacts.
    bodies=np.repeat(ball,32,axis=0);bodies[:,7]=bodies[:,20]=np.arange(32)*.1
    e=CpuCoupledEvaluator(bodies,[],pipeline='local-jacobian');base=np.zeros((32,6));v=candidates(e,base)
    exact(e.evaluate(v,1/240,_jacobian_base=e.evaluate(base,1/240)),e.evaluate(v,1/240))
    assert len(v)==384
    # Maximum interface capacity. This is numerical request parity, not a
    # manufacturing claim about duplicating a physical material connection.
    w=CpuCoupledWorld(dict(pipeline='local-jacobian'));e=CpuCoupledEvaluator(w.eval.bodies,np.repeat(w.eval.edges[:1],128,axis=0),pipeline='local-jacobian')
    base=np.zeros((e.n,6));v=candidates(e,base)
    exact(e.evaluate(v,1/240,_jacobian_base=e.evaluate(base,1/240)),e.evaluate(v,1/240))
    # Retain the actual difficult glass root, with the exact same iterate and
    # unchanged iteration/equation limits rather than a manufactured oracle.
    archive=json.loads((ROOT/'docs/evidence/gpu-representations/backend-performance.json').read_text())
    d=archive['glass_drop']['state']['rejected_candidate']['last_solver_failure'];roots=[]
    for pipeline in ('serial-reference','local-jacobian'):
        e=CpuCoupledEvaluator(d['initial_bodies'],d['initial_edges'],pipeline=pipeline)
        start=time.perf_counter();out,v,iterations,residual=e.solve(d['dt_s'],d['gravity_m_s2']);elapsed=time.perf_counter()-start
        roots.append((out,v,iterations,residual,elapsed))
    for key in PUBLIC:assert roots[0][0][key].tobytes()==roots[1][0][key].tobytes(),key
    assert roots[0][1].tobytes()==roots[1][1].tobytes() and roots[0][2:4]==roots[1][2:4]
    report=dict(schema='banjo.cpu-local-jacobian.v1',implementation_sha256=implementation_hash(),numpy_version=np.__version__,
        runs=runs,retained_glass_root=dict(iterations=roots[0][2],residual=roots[0][3],full_wall_s=roots[0][4],local_wall_s=roots[1][4]),
        exact_private_and_history_parity=True,full_fracture_qualified=False)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print('PASS local CPU Jacobian/reference and actual root parity',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--library',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())
