"""Opt-in actual PhysX CUDA control and retained refusal tests, not realism."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from physx_contact_world import PhysXContactWorld, SOURCE_SHA256, np, wp
from gpu_contact_world import GpuContactWorld


class ShadowObservedPhysX(PhysXContactWorld):
    """Compare every real GPU substep with the independent column read path."""
    def _observe(self, slot, contacts=True):
        super()._observe(slot, contacts)
        if not hasattr(self, 'shadow_trace'):
            self.shadow_trace = wp.zeros(self.trace.shape,dtype=wp.float32,device=self.device)
        primary = self.trace
        self.trace = self.shadow_trace
        self.observation_mode = 'columns'
        try:
            super()._observe(slot, contacts=False)
        finally:
            self.trace = primary
            self.observation_mode = 'bindings'


def scene(raw, check_read_parity=False):
    start=time.perf_counter()
    w=(ShadowObservedPhysX if check_read_parity else PhysXContactWorld)(raw)
    startup=time.perf_counter()-start
    initial=w.snapshot()
    start=time.perf_counter()
    error=None
    peak=0.
    try:
        while w.ticks<round(2/w.d['dt_s']):
            accepted=w.snapshot()
            try:
                s=w.advance(min(32,round(2/w.d['dt_s'])-w.ticks))
                performance=s['performance']
                assert all(math.isfinite(t) and t>=0 for t in performance['phase_s'].values())
                assert math.isclose(sum(performance['phase_s'].values()),performance['step_s'],rel_tol=1e-12,abs_tol=1e-12)
                assert math.isclose(sum(performance['last_phase_ms'].values()),performance['last_batch_ms'],rel_tol=1e-12,abs_tol=1e-9)
                assert len(s['substep_trace']['normal_accounts'])==w.last_steps
                if check_read_parity:
                    assert np.array_equal(w.trace.numpy()[:w.last_steps],w.shadow_trace.numpy()[:w.last_steps]), 'Resident/column substep states differ'
                peak=max(peak,max(row['mechanical_change_j'] for row in s['substep_trace']['normal_accounts']))
            except ValueError as fault:
                error=str(fault)
                s=w.snapshot()
                assert s['cells']==accepted['cells'] and s['ticks']==accepted['ticks']
                try:w.advance(1)
                except ValueError:pass
                else:raise AssertionError('Rejected hidden history resumed')
                break
        s=w.snapshot()
        return dict(declaration=w.d,initial=initial['diagnostics'],final=s['diagnostics'],final_cells=s['cells'],
            final_time_s=s['time_s'],startup_s=startup,wall_s=time.perf_counter()-start,max_accepted_gain_j=peak,
            error=error,rejected_candidate=s.get('rejected_candidate'),qualification=s['qualification'],performance=s['performance'],
            all_substeps_match_column_reference=check_read_parity,
            timing_includes_shadow_reads=check_read_parity)
    finally:w.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    rows=[]
    for material in ('glass','oak','iron','ice'):
        # Same declared experiment for every substance. Refined zero-bounce,
        # friction-free control qualifies only the current rigid contact gate.
        result=scene(dict(experiment='yard',material=material,restitution=0.,friction=0.,dt_s=1/1920),check_read_parity=True)
        assert result['error'] is None,result
        assert result['final_time_s']==2.
        assert result['qualification']['gpu'] and result['qualification']['direct_gpu']
        expected=27*.12**3*{'glass':2500,'oak':700,'iron':7870,'ice':917}[material]+1
        assert math.isclose(result['final']['dynamic_mass_kg'],expected,rel_tol=2e-6)
        assert result['final']['max_normal_only_P_residual_n_s']<1e-5
        assert result['final']['mechanical_change_j']<-90
        assert result['final']['max_contacts']>30
        assert 0.25<result['final_cells'][-1]['position_m'][1]<.6
        rows.append(result)
        print(material,'refined stack',result['wall_s'],flush=True)
    bouncing=scene(dict(experiment='yard',material='glass',restitution=.5,friction=.3))
    # Initialization/contact history and ordering affect the bouncing stack.
    # Observe its actual outcome; do not require a prechosen failure time.
    if bouncing['error']:
        assert bouncing['rejected_candidate']['solver_stopped']
        assert bouncing['rejected_candidate']['max_gain_j']>0
    else:
        assert bouncing['final_time_s']==2. and bouncing['final']['mechanical_change_j']<0
    rows.append(bouncing)
    for mat in ('glass','oak','iron','ice'):
        result=scene(dict(experiment='pair',material=mat,friction=0.,restitution=.5,dt_s=1/1920))
        assert result['error'] is None
        assert abs(result['final_cells'][0]['velocity_m_s'][0]-.5)<2e-4
        assert abs(result['final_cells'][1]['velocity_m_s'][0]-1.5)<2e-4
        assert abs(result['final']['mechanical_change_j']+.75)<2e-4
        assert result['final']['max_normal_only_P_residual_n_s']<2e-5
        rows.append(result)
    # A missing entry in the logged normal ledger must not masquerade as full
    # conservation; both engines explicitly retain incomplete qualification.
    assert all(not r['final']['reaction_account_complete'] for r in rows)
    native=GpuContactWorld(dict(experiment='yard',restitution=0.,friction=0.))
    while native.ticks<1920:
        accepted=native.snapshot()
        try:native.advance(min(32,1920-native.ticks))
        except ValueError:
            assert native.snapshot()['cells']==accepted['cells']
            break
    else:raise AssertionError('Retained Newton coupled counterexample disappeared; investigate ordering')
    commands=[{'op':'create','declaration':{'solver_backend':'physx-tgs','experiment':'pair','dt_s':1/1920}},
        {'op':'advance','steps':1},{'op':'accelerate_object'}, {'op':'snapshot'}]
    worker=subprocess.run([sys.executable,str(ROOT/'scripts/gpu-contact-worker.py')],input=''.join(json.dumps(c)+'\n' for c in commands),text=True,capture_output=True,timeout=40)
    replies=[json.loads(line) for line in worker.stdout.splitlines()]
    assert worker.returncode==0 and len(replies)==len(commands)
    assert [r['ok'] for r in replies]==[True,True,False,True]
    assert replies[1]['state']['ticks']==1 and replies[3]['state']['ticks']==1
    assert 'omni_physx_sdk' not in worker.stdout
    # Finite/capacity diagnostics must stop and preserve exact displayed state.
    try:PhysXContactWorld(dict(experiment='pair',dt_s=1/960))
    except ValueError as error:assert 'analytical bounce' in str(error)
    else:raise AssertionError('Withdrawn coarse pair admitted')
    w=PhysXContactWorld(dict(experiment='pair',dt_s=1/1920))
    initial=w.snapshot();w.sdk_faults.append('injected capacity diagnostic')
    try:w.advance(1)
    except ValueError:assert w.snapshot()['cells']==initial['cells'] and w.snapshot()['ticks']==0
    else:raise AssertionError('SDK capacity fault admitted')
    assert w.snapshot()['performance']==initial['performance'], 'Rejected time reported as accepted throughput'
    w.close()
    report=dict(scope='Experimental rigid GPU contact/control, not bonded material qualification',
        source_sha256=SOURCE_SHA256,worker_sha256=hashlib.sha256((ROOT/'scripts/gpu-contact-worker.py').read_bytes()).hexdigest(),
        tests_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),base_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),results=rows,
        checks=['actual CUDA columns, actual mass/inertia','four-material refined stack control',
            'four analytical isolated pair controls','bouncing stack actual gated outcome and exact refusal retention when applicable',
            'Newton zero-bounce/friction retained failure','JSON-only worker and unsupported command preservation',
            'SDK diagnostic stops and retains accepted scene'])
    report['checks'].append('disjoint finite phase timings sum to accepted batch time; every substep retained')
    report['checks'].append('all 3840 substep transforms/velocities match column reads exactly for each material; binding resources closed before stage teardown')
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf8')
    print('PhysX scoped checks passed; full laws and near realtime remain open')


if __name__=='__main__':main()
