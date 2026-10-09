"""CPU/CUDA trials, analytical motion, coupled admission and whole-interval rollback.

Passing these controls does not admit general collision geometry or realtime.
"""
import argparse,copy,json,subprocess,sys,time
from pathlib import Path
import cupy as cp
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from gpu_coupled_world import GpuCoupledWorld,TrialFailure,source_hash

def main(args):
    process=subprocess.Popen([str(args.oracle)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    def oracle(command):
        process.stdin.write(json.dumps(command)+'\n');process.stdin.flush();reply=json.loads(process.stdout.readline());assert reply['ok'],reply;return reply['trial']
    results=[];rng=np.random.default_rng(4367);max_relative=0.
    try:
        for material in ('glass','oak','iron','ice'):
            w=GpuCoupledWorld(dict(material=material,height_m=.001,dt_s=1/240));e=w.eval
            bodies=cp.asnumpy(e.bodies);edges=cp.asnumpy(e.edges)
            # Arbitrary trial kinematics include all angular/translation DOFs.
            for index in range(3):
                velocity=rng.normal(size=(e.n,6))*1e-6;velocity[bodies[:,1]==0]=0
                reference=oracle(dict(op='coupled',bodies=bodies.tolist(),edges=edges.tolist(),velocity=velocity.tolist(),dt_s=1/960,gravity=[0,-9.81,0]))
                out=e.evaluate(cp.asarray(velocity),1/960);assert int(out['faults'][0])==reference['fault']==0
                for name in ('poses','residual','history','forces','ledger'):
                    actual=cp.asnumpy(out[name])[0];expected=np.array(reference[name]);difference=abs(actual-expected)
                    scale=np.maximum(1.,abs(expected));relative=float(np.max(difference/scale,initial=0));max_relative=max(max_relative,relative)
                    assert np.allclose(actual,expected,rtol=2e-10,atol=2e-10),(material,index,name,relative)
            # The same 1 mm, 10 gram drop on the same finite nine-cell sheet.
            before=w.snapshot();started=time.perf_counter();contact_seen=False
            for tick in range(10):
                state=w.advance(1);assert state['time_s']>before['time_s'];assert len(state['cells'])==13
                assert abs(state['diagnostics']['global_energy_residual_j'])<5e-9
                for a in state['substep_accounts']:
                    assert abs(a['energy_residual_j'])<=a['energy_tolerance_j']
                    assert np.linalg.norm(a['P_residual_n_s'])<=1e-9 and np.linalg.norm(a['L_residual_n_m_s'])<=1e-9
                    assert len(a['poses_wxyz'])==13 and len(a['material_history'])==e.m
                    contact_seen|=a['ledger'][8]>0
            # The ball must differ from unimpeded gravity after crossing the sheet.
            ball=state['cells'][-1];initial=before['cells'][-1]
            ballistic=initial['position_m'][1]-.5*9.81*state['time_s']**2
            assert ball['position_m'][1]>ballistic+1e-4 and contact_seen,(material,'no resolved collision')
            results.append(dict(material=material,conditions=state['declaration'],time_s=state['time_s'],wall_s=time.perf_counter()-started,
                ball_y_m=ball['position_m'][1],ball_vy_m_s=ball['velocity_m_s'][1],diagnostics=state['diagnostics'],performance=state['performance']))
            print(material,'coupled drop accepted',results[-1]['wall_s'],'wall seconds',flush=True)
        # Independent analytical freefall includes rotation and changing inertia
        # through ball material/density. Contact starts only after the oracle interval.
        for material in ('glass','oak','iron','ice'):
            w=GpuCoupledWorld(dict(experiment='freefall',ball_material=material,height_m=.1,dt_s=1/240))
            start=w.snapshot()['cells'][-1]['position_m'][1]
            for _ in range(8):state=w.advance(1)
            ball=state['cells'][-1];t=state['time_s']
            assert abs(ball['position_m'][1]-(start-.5*9.81*t*t))<1e-12
            assert abs(ball['velocity_m_s'][1]+9.81*t)<1e-10
        # A failure after a privately accepted microstep must restore the WHOLE
        # requested interval, including geometry, velocity and material history.
        w=GpuCoupledWorld({});initial=w.snapshot();b=w.eval.bodies.copy();e=w.eval.edges.copy();solve=w.eval.solve;calls=0
        def fail_after_first(*a,**kw):
            nonlocal calls
            calls+=1
            if calls>1:raise TrialFailure('Deliberate convergence refusal witness')
            return solve(*a,**kw)
        w.eval.solve=fail_after_first
        try:w.advance(2);raise AssertionError('Failure was admitted')
        except RuntimeError:pass
        assert w.time==0 and bool(cp.array_equal(w.eval.bodies,b)) and bool(cp.array_equal(w.eval.edges,e))
        refused=w.snapshot();witness=refused.pop('rejected_candidate');assert refused==initial and witness['interval_rolled_back'] and witness['failed_interval_substeps']==1
        assert witness['trial_attempts']>1 and witness['subdivision_refusals'][-1]['depth']==10
        assert all(a['error']=='Deliberate convergence refusal witness' for a in witness['subdivision_refusals'])
        result=dict(schema='banjo.gpu-coupled-evidence.v1',source_sha256=source_hash(),device=cp.cuda.runtime.getDeviceProperties(0)['name'].decode(),
            cuda_driver=cp.cuda.runtime.driverGetVersion(),cpu_cuda_trials=12,max_scaled_trial_difference=max_relative,comparisons=results,
            analytical_freefall_materials=4,whole_interval_rollback=True,realtime_qualified=False)
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
        print('GPU coupled controls passed; realtime and general geometry remain open',flush=True)
    finally:process.stdin.close();process.wait(timeout=10)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--oracle',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())
