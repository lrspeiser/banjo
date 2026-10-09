"""Opt-in actual CUDA tests. Stock rigid laws; no material-fracture claims."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from gpu_contact_world import GpuContactWorld, declaration, check_capacity, wp


def run_scene(raw, ticks, batch=32):
    start = time.perf_counter()
    world = GpuContactWorld(raw)
    startup = time.perf_counter()-start
    initial = world.snapshot()
    start = time.perf_counter()
    while world.ticks < ticks:
        world.advance(min(batch, ticks-world.ticks))
    final = world.snapshot()
    return world, dict(declaration=world.d, startup_s=startup, wall_s=time.perf_counter()-start,
                      initial=initial['diagnostics'], final=final['diagnostics'],
                      final_cells=final['cells'], performance=final['performance'],
                      max_substep_gain_j=world.max_candidate_gain_j,
                      source_sha256=final['qualification']['source_sha256'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--native', type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for material in ('glass', 'oak', 'iron', 'ice'):
        for hz in (960, 1920):
            world, row = run_scene(dict(experiment='floor', ball_material=material, dt_s=1/hz), 2*hz)
            final = world.snapshot()
            assert final['qualification']['gpu'] and final['qualification']['device'] == 'cuda:0'
            assert math.isclose(final['diagnostics']['dynamic_mass_kg'], 1., rel_tol=2e-6)
            assert final['diagnostics']['max_contacts'] == 1
            impact_time=math.sqrt(20/9.81)
            after_impact=2-impact_time
            expected_height=final['cells'][0]['radius_m']+.5*math.sqrt(20*9.81)*after_impact-.5*9.81*after_impact**2
            assert abs(final['cells'][0]['position_m'][1]-expected_height)<.012*(960/hz), '10 m / e=.5 analytical rebound'
            assert abs(final['diagnostics']['mechanical_change_j']+.75*9.81*10)<.1
            assert final['qualification']['complete_physics_validated'] is False
            rows.append(row)
        assert abs(rows[-1]['final_cells'][0]['position_m'][1]-rows[-2]['final_cells'][0]['position_m'][1]) < .03
    # Exact equal-mass central impact oracle. Both bodies are free: no support
    # reaction can hide missing momentum or incorrect contact dissipation.
    for material in ('glass', 'oak', 'iron', 'ice'):
        world, row = run_scene(dict(experiment='pair', material=material, friction=0., solver_relaxation=1.),384)
        final = world.snapshot()
        assert abs(final['cells'][0]['velocity_m_s'][0]-.5) < 2e-4
        assert abs(final['cells'][1]['velocity_m_s'][0]-1.5) < 2e-4
        assert abs(row['final']['momentum_n_s'][0]-row['initial']['momentum_n_s'][0]) < 2e-5
        assert abs(row['final']['mechanical_change_j']+.75) < 2e-4
        rows.append(row)
    # Off-center frictional contact: actual calculated spin and pair P/L.
    world, row = run_scene(dict(experiment='pair', material='glass', friction=.3,
                               offset_m=.03, solver_relaxation=1.),384)
    assert any(abs(x)>1e-3 for c in world.snapshot()['cells'] for x in c['angular_velocity_rad_s'])
    for key in ('momentum_n_s', 'angular_momentum_n_m_s'):
        assert max(abs(a-b) for a,b in zip(row['initial'][key],row['final'][key])) < 5e-4, key
    rows.append(row)
    # Symplectic Euler gravity control has known O(dt) position error.
    world,row=run_scene(dict(experiment='freefall'),480)
    cell=world.snapshot()['cells'][0]; initial=world.initial['cells'][0]
    assert abs(cell['velocity_m_s'][1]+9.81*.5)<2e-4
    assert abs(cell['position_m'][1]-(initial['position_m'][1]-.5*9.81*.5**2))<.003
    rows.append(row)
    # CPU is an explicitly selected reference for identical library operations;
    # it is never a fallback for a CUDA request. Compare graph and CPU schedules.
    gpu,gpu_row=run_scene(dict(experiment='pair',friction=0.,solver_relaxation=1.),384)
    cpu,cpu_row=run_scene(dict(experiment='pair',friction=0.,solver_relaxation=1.,device='cpu'),384)
    for a,b in zip(gpu.snapshot()['cells'],cpu.snapshot()['cells']):
        for key in ('position_m','velocity_m_s'):
            assert max(abs(x-y) for x,y in zip(a[key],b[key]))<3e-5
    rows.append(cpu_row)
    mixed=GpuContactWorld(dict(experiment='pair',friction=0.,solver_relaxation=1.))
    for count in [1,7,16,32]*6+[24,24]:mixed.advance(count)
    assert mixed.ticks==384
    for a,b in zip(gpu.snapshot()['cells'],mixed.snapshot()['cells']):
        assert a['position_m']==b['position_m'] and a['velocity_m_s']==b['velocity_m_s'], 'graph buffer parity'
    # Keep the full failed scene. It must fail visibly and retain accepted
    # transforms, time and trace, rather than render a rejected calculation.
    yard=GpuContactWorld(dict(experiment='yard'))
    while yard.ticks<1920:
        before=yard.snapshot()
        try:yard.advance(32)
        except ValueError:break
    else:raise AssertionError('Known stack failure not reproduced in bounded full experiment')
    after=yard.snapshot()
    for key in ('cells','ticks','time_s','substep_trace'):assert before[key]==after[key], key
    assert after['rejected_candidate']['max_gain_j']>0
    refined=GpuContactWorld(dict(experiment='yard',dt_s=1/1920))
    while refined.ticks<3840:
        try:refined.advance(32)
        except ValueError:break
    else:raise AssertionError('Refined stack failure not reproduced in bounded full experiment')
    try:yard.advance(1)
    except ValueError:pass
    else:raise AssertionError('Refused solver continued with unqualified internal history')
    capacity=GpuContactWorld(dict(experiment='freefall'))
    forced=wp.array([1],dtype=int,device=capacity.device)
    capacity.capacity_checks.append((forced,0))
    try:capacity.advance(1)
    except ValueError:pass
    else:raise AssertionError('Intermediate capacity overflow admitted')
    assert capacity.snapshot()['rejected_candidate']['faults']==2
    for bad in ({'bogus':1},{'device':'other'},{'height_m':True},{'height_m':float('nan')},{'dt_s':1/240}):
        try:declaration(bad)
        except ValueError:pass
        else:raise AssertionError(f'Invalid declaration admitted: {bad}')

    spec=importlib.util.spec_from_file_location('gateway',ROOT/'scripts/voxel-lab.py')
    gateway=importlib.util.module_from_spec(spec);spec.loader.exec_module(gateway)
    with tempfile.TemporaryDirectory() as folder:
        server=gateway.Server(('127.0.0.1',0),args.native.resolve(),Path(folder),gpu_python=Path(sys.executable))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{server.server_port}'
        def req(data,endpoint='/api/gpu'):
            try:
                with urllib.request.urlopen(urllib.request.Request(base+endpoint,json.dumps(data).encode(),{'Content-Type':'application/json'}),timeout=120) as r:return r.status,json.load(r)
            except urllib.error.HTTPError as e:return e.code,json.load(e)
        try:
            _,reply=req(dict(op='create',declaration=dict(experiment='floor')))
            assert reply['ok'];session=reply['session']
            assert req([])[0]==400
            assert req(dict(op='snapshot',session=session),'/api/world')[0]==400
            start=time.perf_counter()
            _,reply=req(dict(op='play',session=session,running=True,target_time_s=2))
            frame=reply['frame_id']
            while reply['pipeline']['running'] or reply['pipeline']['calculating']:
                _,reply=req(dict(op='frame',session=session,after=frame,wait_ms=250));frame=reply['frame_id']
            assert reply['ok'] and reply['state']['ticks']==1920
            assert reply['state']['qualification']['gpu']
            assert reply['pipeline']['buffered_frames']==1
            assert req(dict(op='accelerate_object',session=session,object=1,acceleration_m_s2=[1,0,0]))[0]==400
            log=list(server.session(session).iter_log())
            records=[json.loads(line) for line in log]
            assert any(r.get('response',{}).get('state',{}).get('substep_trace',{}).get('transforms') for r in records)
            ticks=[]
            for record in records:
                if record.get('request',{}).get('op')=='advance':
                    trace=record['response']['state']['substep_trace']
                    ticks.extend(range(trace['first_tick'],trace['first_tick']+len(trace['transforms'])))
            assert ticks==list(range(1,1921)), 'Journal omitted or duplicated calculated substeps'
            stream=dict(wall_s=time.perf_counter()-start,pipeline=reply['pipeline'],final_time_s=reply['state']['time_s'])
            req(dict(op='close',session=session))
            _,reply=req(dict(op='create',declaration=dict(experiment='yard')));session=reply['session']
            while reply['ok'] and reply['state']['ticks']<1920:
                previous=reply['state']
                _,reply=req(dict(op='advance',session=session,steps=16))
            assert not reply['ok'], 'Stack failure not reproduced through HTTP'
            for key in ('cells','ticks','time_s','substep_trace'):assert previous[key]==reply['state'][key]
            assert 'rejected_candidate' in reply['state']
            req(dict(op='close',session=session))
        finally:
            for s in server.sessions.values():s.close()
            server.shutdown();server.server_close()
    report=dict(schema='banjo.gpu-contact-evidence.v1',rows=rows,
                environment=gpu.snapshot()['qualification'],
                test_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                worker_sha256=hashlib.sha256((ROOT/'scripts/gpu-contact-worker.py').read_bytes()).hexdigest(),
                native_gateway_sha256=hashlib.sha256(args.native.read_bytes()).hexdigest(),
                known_stack_refusal=after['rejected_candidate'],refined_stack_refusal=refined.snapshot()['rejected_candidate'],stream=stream,
                qualification='Scoped rigid tests only; reaction/contact loss accounting incomplete; stack blocked')
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2)+'\n')
    print('CUDA contact analytical, material-density, graph/CPU, admission and HTTP pipeline checks passed')


if __name__=='__main__':main()
