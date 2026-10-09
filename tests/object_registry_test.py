"""Actual CUDA continuation plus independently compiled prior material loading.

Preloaded specimens test retained constitutive history, not free-world impact
accuracy. The 10 m realtime gate is measured separately and remains open.
"""
import argparse,copy,importlib.util,json,math,subprocess,sys,tempfile,threading,time,urllib.request,urllib.error
from pathlib import Path
import cupy as cp
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from gpu_coupled_world import GpuCoupledWorld,TrialFailure,source_hash
from object_registry import properties,canonical,seal,digest,CHECKPOINT_LIMIT,open_checkpoint,CHECKPOINT_SCHEMA

def browser_roundtrip(value):
    script="let s='';process.stdin.setEncoding('utf8');process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s))));"
    r=subprocess.run(['node','-e',script],input=canonical(value),text=True,capture_output=True,check=True,timeout=5)
    return json.loads(r.stdout)

def primitive(shape,half,pos,density=10.,q=None):
    return dict(shape=shape,half_size_m=half,reference_position_m=pos,reference_quaternion_wxyz=q or [1,0,0,0],density_kg_m3=density)

def oracles():
    # Two cubes separated by empty space: full parallel-axis inertia, not a
    # filled bounding box. Rotation permutes the independent expected tensor.
    a=primitive('cube',[.5]*3,[-2,0,0]);b=primitive('cube',[.5]*3,[2,0,0]);p=properties([a,b])
    assert p['volume_m3']==2 and p['mass_kg']==20 and p['center_of_mass_m']==[0,0,0]
    assert np.allclose(p['inertia_kg_m2'],np.diag([20/6,20/6+80,20/6+80]),rtol=1e-15,atol=1e-14)
    box=primitive('cube',[.5,1,1.5],[0,0,0],q=[math.sqrt(.5),0,0,math.sqrt(.5)])
    m=60.;assert np.allclose(properties([box])['inertia_kg_m2'],np.diag([m*(.25+2.25)/3,m*(1+2.25)/3,m*(.25+1)/3]),atol=1e-13)
    radius=.2;p=properties([primitive('sphere',[radius]*3,[3,2,1])]);m=10*4*math.pi*radius**3/3
    assert abs(p['mass_kg']-m)<1e-15 and np.allclose(p['inertia_kg_m2'],np.eye(3)*.4*m*radius**2,atol=1e-16)
    return dict(occupied_gap_preserved=True,full_parallel_axis_inertia=True,rotated_box_oracle=True,sphere_oracle=True)

def exact_state(a,b):
    assert bool(cp.array_equal(a.eval.bodies,b.eval.bodies)) and bool(cp.array_equal(a.eval.edges,b.eval.edges))
    assert a.snapshot()['diagnostics']==b.snapshot()['diagnostics']
    assert a.registry.document()==b.registry.document()

def refuse(checkpoint,mutator):
    changed=open_checkpoint(checkpoint);mutator(changed);changed=seal(changed)
    try:GpuCoupledWorld.from_checkpoint(changed);raise AssertionError('Invalid checkpoint admitted')
    except (ValueError,TypeError,KeyError):pass

def loading(w,oracle):
    b=cp.asnumpy(w.eval.bodies);e=cp.asnumpy(w.eval.edges);v=np.zeros((len(b),6));h=.001
    # Unit-bearing imposed separation follows the actual registered law scale.
    opening=2*e[0,29]/e[0,23] if e[0,2]==1 else 4*e[0,20]/e[0,19]
    indices=np.flatnonzero((b[:,1]>0)&(b[:,0]==1)&(b[:,20]>.009));v[indices,0]=2*opening/h
    command=dict(op='coupled',bodies=b.tolist(),edges=e.tolist(),velocity=v.tolist(),dt_s=h,gravity=[0,0,0])
    oracle.stdin.write(json.dumps(command)+'\n');oracle.stdin.flush();cpu=json.loads(oracle.stdout.readline());assert cpu['ok'],cpu
    trial=w.eval.evaluate(cp.asarray(v),h,gravity=0);assert int(trial['faults'][0])==0
    for field in ('history','ledger','poses'):
        actual=cp.asnumpy(trial[field])[0];expected=np.asarray(cpu['trial'][field]).reshape(actual.shape)
        assert np.allclose(actual,expected,rtol=2e-10,atol=1e-12),field
    history=cp.asnumpy(trial['history'])[0];ledger=cp.asnumpy(trial['ledger'])[0]
    # The external loading apparatus holds the final poses and removes the
    # imposed motion. Its prior work is part of this specimen's initial energy;
    # this fixture bypasses free-world dynamics admission deliberately.
    ending=cp.asnumpy(trial['poses'])[0];b[:,23:26]+=h*v[:,:3]/2;b[:,7:14]=ending;b[:,14:20]=0
    cp.copyto(w.eval.bodies,cp.asarray(b));w.eval.edges[:,35:67]=cp.asarray(history);w.histories=history
    w.stored_j=float(ledger[1]);w.contact_j=float(ledger[5]);w.return_excess=float(ledger[3])
    if e[0,2]==1:w.plastic=float(ledger[2]);assert np.any(history[:,14]>0) and np.any(history[:,:6]!=0)
    else:w.fracture=float(ledger[2]);assert np.any(history[:,6]>0) and np.any(history[:,5]>0)
    w.initial_energy=w.mechanics(b)[0]+w.stored_j+w.contact_j+w.fracture+w.plastic+w.return_excess;w.accepted=w._snapshot(b)
    return dict(imposed_opening_m=opening,dt_s=h,scope='Compiled CPU/CUDA constitutive prior-loading comparison; externally held specimen, not free impact admission',
        separated=int(np.count_nonzero(history[:,6])) if e[0,2]!=1 else 0,yielded=int(np.count_nonzero(history[:,14])) if e[0,2]==1 else 0,
        stored_j=w.stored_j,fracture_j=w.fracture,plastic_j=w.plastic,return_excess_j=w.return_excess)

def gateway(native):
    spec=importlib.util.spec_from_file_location('registry_gateway',ROOT/'scripts/voxel-lab.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as tmp:
        server=module.Server(('127.0.0.1',0),native,Path(tmp),gpu_python=Path(sys.executable));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        url='http://127.0.0.1:'+str(server.server_port)+'/api/gpu';sessions=[]
        def request(d):
            data=json.dumps(d).encode();req=urllib.request.Request(url,data=data,headers={'Content-Type':'application/json'})
            try:
                with urllib.request.urlopen(req,timeout=60) as response:return json.load(response)
            except urllib.error.HTTPError as e:return json.load(e)
        try:
            created=request(dict(op='create',declaration=dict(solver_backend='cupy-implicit-body',height_m=10,experiment='freefall',representation_policy='partitioned-flight',dt_s=1/240)));assert created['ok'],created
            key=created['session'];sessions.append(key);moved=request(dict(op='advance',session=key,steps=16));assert moved['ok']
            exported=request(dict(op='export',session=key));assert exported['ok'] and 'checkpoint' in exported
            unchanged=request(dict(op='snapshot',session=key));assert unchanged['state']==moved['state'],'Export replaced accepted delivery'
            restored=request(dict(op='restore',checkpoint=browser_roundtrip(exported['checkpoint'])));assert restored['ok'],restored;sessions.append(restored['session'])
            for k in ('cells','history_arrays','diagnostics','objects','time_s'):assert restored['state'][k]==moved['state'][k]
            corrupted=copy.deepcopy(exported['checkpoint']);corrupted['native']['bodies'][-1][1]={'$f64':(.2).hex()}
            bad=request(dict(op='restore',checkpoint=corrupted));assert not bad['ok']
            original=request(dict(op='snapshot',session=key));assert original['state']==moved['state'],'Failed restore touched original session'
            a=request(dict(op='advance',session=key,steps=16));b=request(dict(op='advance',session=restored['session'],steps=16))
            assert a['state']['cells']==b['state']['cells'] and a['state']['diagnostics']==b['state']['diagnostics']
            return dict(save_reopen_exact=True,next_16_steps_exact=True,export_keeps_delivery=True,failed_restore_keeps_original=True,checkpoint_bytes=len(canonical(exported['checkpoint']).encode()))
        finally:
            for s in sessions:request(dict(op='close',session=s))
            server.shutdown();server.server_close();thread.join()

def main(args):
    values=[1.,-0.,1e-300,1e300,float(np.nextafter(1.,2.)),1e-7]
    decoded=open_checkpoint(browser_roundtrip(seal(dict(schema=CHECKPOINT_SCHEMA,values=values))))
    assert [v.hex() for v in decoded['values']]==[v.hex() for v in values]
    report=dict(schema='banjo.object-registry-evidence.v1',source_sha256=source_hash(),oracles=oracles(),materials=[],realtime_qualified=False,full_representation_architecture_complete=False)
    oracle=subprocess.Popen([str(args.oracle)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,encoding='utf8')
    try:
        for material in ('glass','oak','iron','ice'):
            w=GpuCoupledWorld(dict(material=material,height_m=.001,dt_s=1/240,representation_policy='partitioned-flight'));w.advance(5)
            checkpoint=w.export_checkpoint();start=time.perf_counter();r=GpuCoupledWorld.from_checkpoint(browser_roundtrip(checkpoint));reopen=time.perf_counter()-start
            assert checkpoint==r.export_checkpoint();exact_state(w,r)
            for _ in range(3):w.advance(1);r.advance(1);exact_state(w,r)
            for account in r.last_accounts:
                assert abs(account['energy_residual_j'])<=account['energy_tolerance_j'] and np.linalg.norm(account['P_residual_n_s'])<=1e-9 and np.linalg.norm(account['L_residual_n_m_s'])<=1e-9
            assert abs(r.snapshot()['diagnostics']['global_energy_residual_j'])<5e-9
            objects=w.snapshot()['objects']['objects'];assert objects[1]['definition_sha256']==objects[2]['definition_sha256'] and objects[1]['instance_id']!=objects[2]['instance_id']
            document=w.registry.document();list(document['definitions'].values())[0]['version']=999;assert document!=w.registry.document(),'Definition getter shares mutable data'
            prior=GpuCoupledWorld(dict(material=material,height_m=10,dt_s=1/240,representation_policy='partitioned-flight'));load=loading(prior,oracle)
            loaded=GpuCoupledWorld.from_checkpoint(prior.export_checkpoint());exact_state(prior,loaded)
            report['materials'].append(dict(material=material,conditions=w.d,diagnostics=w.snapshot()['diagnostics'],checkpoint_bytes=len(canonical(checkpoint).encode()),reopen_wall_s=reopen,next_accepted_steps_exact=3,prior_loading=load,damaged_or_plastic_history_exact=True))
            print(material,'exact continuation; prior state',load['separated'],load['yielded'],flush=True)
    finally:oracle.stdin.close();oracle.wait(timeout=5)
    w=GpuCoupledWorld(dict(experiment='freefall',height_m=10,dt_s=1/240,representation_policy='partitioned-flight'));w.advance(16);p=w.export_checkpoint();r=GpuCoupledWorld.from_checkpoint(p);exact_state(w,r)
    assert r.registry.summary()['objects'][-1]['solver_binding']=='isolated-rigid-flight'
    checks=[lambda d:d.update(source_sha256='old'),lambda d:d['native']['bodies'][-1].__setitem__(1,.5),lambda d:d['continuation'].update(time=.3),
        lambda d:d['registry']['continuation']['instances'][-1].update(solver_binding='unknown'),lambda d:d['registry']['continuation']['instances'][0].update(solver_binding='isolated-rigid-flight'),
        lambda d:d['continuation'].update(histories=[[0]*32]),lambda d:d['continuation'].update(stored_j=1),lambda d:d['native']['bodies'][-1].__setitem__(10,2),lambda d:d['native']['bodies'][-1].__setitem__(8,1)]
    for mutate in checks:refuse(p,mutate)
    # Even a rehashed custom law definition is refused against the compiler's
    # exact installed geometry/laws, rather than trusting a cache key alone.
    def law(d):
        key=next(iter(d['registry']['definitions']));d['registry']['definitions'][key]['recipes']=['pretend-fire']
    refuse(p,law)
    initial=w.snapshot();bindings=w.registry.binding_state()
    def broken(*a):raise RuntimeError('Injected snapshot publication failure')
    w._snapshot=broken
    try:w.advance(1);raise AssertionError('Publication failure admitted')
    except RuntimeError:pass
    assert w.registry.binding_state()==bindings and w.snapshot()['objects']==initial['objects']
    stopped=GpuCoupledWorld.from_checkpoint(w.export_checkpoint())
    try:stopped.advance(1);raise AssertionError('Reopen healed a refused world')
    except ValueError:pass
    report.update(rejected_mutations=len(checks)+1,publication_ownership_rollback=True,stopped_state_stays_stopped=True,gateway=gateway(args.native))
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print('PASS registry oracles, four-material accepted/constitutive state, atomic refusal, actual gateway save/reopen; full realtime/impact remain unqualified',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--oracle',type=Path,required=True);parser.add_argument('--native',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);main(parser.parse_args())
