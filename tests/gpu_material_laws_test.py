"""Actual shared-source CPU/CUDA histories, constitutive work and gateway tests."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import numpy as np
import cupy as cp
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from gpu_material_laws import ResidentLaws, GpuMaterialWorld, source_hash


class Oracle:
    def __init__(self,path):
        self.proc=subprocess.Popen([str(path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,encoding='utf8')
    def call(self,command):
        self.proc.stdin.write(json.dumps(command)+'\n');self.proc.stdin.flush()
        result=json.loads(self.proc.stdout.readline());assert result['ok'],result
        return result
    def close(self):
        self.proc.stdin.close();self.proc.wait(timeout=10);assert self.proc.returncode==0


def main(args):
    oracle=Oracle(args.oracle);baseline=Oracle(args.baseline_oracle) if args.baseline_oracle else None
    controls=[];max_scaled_error=0.;max_residual=0.;compared_rows=0;cpu_parity_rows=0
    try:
        profiles=oracle.call({'op':'catalog'})['profiles']
        assert json.loads((ROOT/'client/voxel-lab/material-laws.json').read_text(encoding='utf8'))['profiles']==profiles,'stale generated catalog'
        if baseline:assert baseline.call({'op':'catalog'})['profiles']==profiles
        def compare(lanes,models,steps):
            nonlocal max_scaled_error,max_residual,compared_rows,cpu_parity_rows
            gpu=ResidentLaws(lanes,models);cpu=np.zeros((len(lanes),32));old=cpu.copy()
            for q in steps:
                command={'op':'advance','lanes':[dict(material=p['material'],model=model,state=s.tolist(),coordinates=coordinates.tolist()) for p,model,s,coordinates in zip(lanes,models,cpu,q)]}
                cpu=np.array(oracle.call(command)['states']);actual=gpu.update(q)
                error=np.max(np.abs(cpu-actual)/np.maximum(1.,np.abs(cpu)));max_scaled_error=max(max_scaled_error,float(error))
                assert np.allclose(cpu,actual,rtol=2e-13,atol=2e-12),(models,error)
                if baseline:
                    prior=dict(command);prior['lanes']=[row|{'state':s.tolist()} for row,s in zip(command['lanes'],old)]
                    old=np.array(baseline.call(prior)['states']);assert np.array_equal(cpu,old),'shared-header refactor changed checked CPU results'
                    cpu_parity_rows+=len(lanes)
                residual=np.asarray([s[18] if m=='connector-plastic' else s[10] for s,m in zip(actual,models)])
                max_residual=max(max_residual,float(np.max(np.abs(residual))));compared_rows+=len(lanes)
            return gpu
        # Same declared normal opening for the website's four lanes; early
        # damage, unloading/reloading, separation and retained iron rest.
        q=np.zeros((4,6));steps=[]
        for opening in [0,5e-8,2e-7,2e-6,0,1e-6,12e-6,30e-6,0,30e-6]:
            current=q.copy();current[:,0]=opening;steps.append(current)
        gpu=compare(profiles,[p['display_model'] for p in profiles],steps)
        for p,m,s in zip(profiles,gpu.models,gpu.host):
            plastic=m=='connector-plastic'
            controls.append(dict(material=p['material'],model=m,density_kg_m3=p['density_kg_m3'],young_pa=p['young_pa'],
                stored_energy_j=float(s[15] if plastic else s[3]),physical_dissipation_j=float(s[12] if plastic else s[4]),
                numerical_return_excess_j=float(s[13] if plastic else 0),permanent_rest_m=float(s[0]) if plastic else 0,
                separated=bool(not plastic and s[6]),work_residual_j=float(s[18] if plastic else s[10])))
        # Exact normal cohesive law across all four materials, including iron
        # as an explicit property coupon, not iron's displayed plastic law.
        qs=[]
        for opening_fraction in [.1,.6,0,.3,.8,-.1,.5,1.1,0,.5]:
            current=q.copy()
            for i,p in enumerate(profiles):current[i,0]=opening_fraction*2*p['cohesive_law'][2]/p['cohesive_law'][1]
            qs.append(current)
        compare(profiles,['normal-cohesive']*4,qs)
        # Persistent 4096 independent histories and all six modes under load
        # reversal. This is a material kernel scalability check, not a world.
        rng=np.random.default_rng(864113)
        lanes=[copy.deepcopy(profiles[2]) for _ in range(4096)]
        qs=[]
        for _ in range(8):
            coordinates=rng.uniform(-1,1,(4096,6));coordinates[:,:3]*=5e-5;coordinates[:,3:]*=.03;qs.append(coordinates)
        compare(lanes,['connector-plastic']*4096,qs)
        lanes=[copy.deepcopy(profiles[i%4]) for i in range(4096)]
        qs=[]
        for fraction in [.1,.6,0,.5,.9,1.1,0]:
            coordinates=np.zeros((4096,6));coordinates[:,0]=[fraction*2*p['cohesive_law'][2]/p['cohesive_law'][1] for p in lanes];qs.append(coordinates)
        compare(lanes,['normal-cohesive']*4096,qs)
        # Rename invariance: only coefficients/history can drive outcomes.
        renamed=copy.deepcopy(profiles);[p.update(material='unrelated-label') for p in renamed]
        a,b=ResidentLaws(profiles),ResidentLaws(renamed)
        assert np.array_equal(a.update(steps[7]),b.update(steps[7]))
        # Prescribed opening fracture work scales with physical area, not the
        # count of interfaces. No mass/conservation claim follows from this.
        for p in profiles:
            parts=[copy.deepcopy(p) for _ in range(16)]
            for part in parts:part['cohesive_law'][3]/=16
            split=ResidentLaws(parts,['normal-cohesive']*16)
            opening=1.1*2*p['cohesive_law'][2]/p['cohesive_law'][1]
            coordinates=np.zeros((16,6));coordinates[:,0]=opening
            out=split.update(coordinates)
            assert abs(out[:,4].sum()-p['cohesive_law'][2]*p['cohesive_law'][3])<1e-12
        # Fault injection refuses the candidate, including actual CUDA state.
        guarded=ResidentLaws(profiles);before=guarded.host.copy();launch=guarded._launch
        def fault(unload):launch(unload);guarded.candidate[0,3]=np.nan
        guarded._launch=fault
        try:guarded.update(steps[7]);assert False,'nonfinite update accepted'
        except RuntimeError:pass
        assert np.array_equal(before,guarded.host) and np.array_equal(before,cp.asnumpy(guarded.state)) and guarded.updates==0 and guarded.total_s==0
        guarded._launch=launch;guarded.update(steps[7]);assert guarded.updates==1,'refused candidate poisoned later update'
        world=GpuMaterialWorld({});world.strain(30e-6);before=world.snapshot()
        for bad in [True,-1,0.001,float('nan'),'30',None]:
            try:world.strain(bad);assert False,'invalid opening accepted'
            except ValueError:pass
            assert world.snapshot()==before
        unloaded=world.strain(unload=True)
        assert unloaded['coupons'][2]['permanent_rest_m']>0
        assert all(abs(c['force_n'])<1e-9 and abs(c['stored_energy_j'])<1e-12 for c in unloaded['coupons'])
        assert all(c['separated'] for c in unloaded['coupons'] if c['model']=='normal-cohesive')
        refined=[]
        for increments in [64,128]:
            loading=ResidentLaws([profiles[2]]);coordinates=np.zeros((1,6))
            for i in range(1,increments+1):coordinates[0,0]=30e-6*i/increments;loading.update(coordinates)
            refined.append(loading.host[0].copy())
        assert abs(refined[0][0]-refined[1][0])<1e-16 and abs(refined[0][12]-refined[1][12])<1e-12
        assert refined[1][13]<.52*refined[0][13],'projection loss did not reduce under finer loading'
        # Warm actual controls include upload/readback/audit, not just launch.
        benchmark=[]
        for count in [4,4096,65536]:
            lanes=[copy.deepcopy(profiles[i%4]) for i in range(count)];resident=ResidentLaws(lanes)
            coordinates=np.zeros((count,6));coordinates[:,0]=2e-6
            rows=[]
            for _ in range(9):resident.update(coordinates);rows.append((resident.last_ms,resident.gpu_ms,resident.readback_ms,resident.audit_ms))
            benchmark.append(dict(interfaces=count,control_median_ms=statistics.median(r[0] for r in rows),kernel_median_ms=statistics.median(r[1] for r in rows),readback_median_ms=statistics.median(r[2] for r in rows),audit_median_ms=statistics.median(r[3] for r in rows)))
        # Actual production HTTP -> bounded worker -> CUDA -> record -> UI.
        spec=importlib.util.spec_from_file_location('material_gateway',ROOT/'scripts/voxel-lab.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            server=module.Server(('127.0.0.1',0),args.native,Path(folder),gpu_python=Path(sys.executable));threading.Thread(target=server.serve_forever,daemon=True).start();base='http://127.0.0.1:'+str(server.server_port)
            def req(command):
                try:
                    with urllib.request.urlopen(urllib.request.Request(base+'/api/gpu',json.dumps(command).encode(),{'Content-Type':'application/json'}),timeout=30) as response:return response.status,json.load(response)
                except urllib.error.HTTPError as error:return error.code,json.load(error)
            try:
                with urllib.request.urlopen(base+'/materials') as response:assert b'Pull' in response.read()
                status,created=req({'op':'create','declaration':{'solver_backend':'cupy-material-laws'}});assert status==200 and created['ok'],created
                key=created['session'];assert created['state']['controlled_loading'] and created['state']['qualification']['source_sha256']==source_hash()
                _,loaded=req({'op':'strain','session':key,'opening_m':30e-6});assert loaded['ok'] and loaded['state']['coupons'][2]['permanent_rest_m']>0
                _,released=req({'op':'unload','session':key});assert released['ok'] and all(c['force_n']==0 for c in released['state']['coupons'])
                assert req({'op':'play','session':key,'running':True,'target_time_s':2})[0]==400
                assert not req({'op':'advance','session':key,'steps':1})[1]['ok']
                for bad in [True,-1,.001]:assert not req({'op':'strain','session':key,'opening_m':bad})[1]['ok']
                _,retained=req({'op':'snapshot','session':key});assert retained['state']==released['state']
                assert server.sessions[key].proc.poll() is None,'invalid request killed protocol'
                with urllib.request.urlopen(base+'/api/log/'+key) as response:record=response.read();assert b'"op":"strain"' in record or b'"op": "strain"' in record
                assert req({'op':'close','session':key})[1]['ok']
            finally:
                for session in server.sessions.values():session.close()
                server.shutdown();server.server_close()
        result=dict(scope='Controlled interface laws only; no dynamic world or realtime qualification',source_sha256=source_hash(),
            revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),gpu=world.laws.device_name,cupy=cp.__version__,numpy=np.__version__,
            cpu_gpu_compared_updates=compared_rows,prior_checked_cpu_exact_updates=cpu_parity_rows,max_scaled_cpu_gpu_error=max_scaled_error,
            max_increment_work_residual_j=max_residual,controls=controls,benchmark=benchmark,
            plastic_loading_refinement=[dict(increments=n,permanent_rest_m=float(s[0]),physical_dissipation_j=float(s[12]),numerical_return_excess_j=float(s[13])) for n,s in zip([64,128],refined)],
            dt_s=None,physical_clock=False,full_world_gpu=False,realtime_qualified=False,
            tests=['catalog parity','history/reversal/six modes','shared CPU CUDA comparison','old checked CPU exact parity' if baseline else 'baseline not supplied',
                   'rename invariance','area partition','finite rollback','invalid input retention','unloading','actual HTTP worker CUDA journal','warm measured controls'])
        args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
        print(f'PASS: {compared_rows} CPU/CUDA law updates; {cpu_parity_rows} exact prior-CPU updates; actual gateway and retained failures')
    finally:
        oracle.close()
        if baseline:baseline.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--oracle',type=Path,required=True);parser.add_argument('--baseline-oracle',type=Path);parser.add_argument('--native',type=Path,required=True);parser.add_argument('--report',type=Path,required=True);main(parser.parse_args())
