"""Independent native coordinate/branch/preload tests; no reduced execution."""
import argparse,json,os,sys,time
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from cpu_coupled_world import CpuCoupledWorld,CpuCoupledEvaluator
from material_modes import material_branch_model,attachment_hessian

p=argparse.ArgumentParser();p.add_argument('--library',type=Path,required=True);p.add_argument('--output',type=Path);args=p.parse_args()
os.environ['BANJO_COUPLED_CPU_LIBRARY']=str(args.library.resolve())
def refuses(fn):
    try:fn()
    except (ValueError,RuntimeError):return
    raise AssertionError('Unsupported elastic branch admitted')
def quaternion(t):
    q=np.r_[1.,np.asarray(t)/2];return q/np.linalg.norm(q)
def multiply(q,r):return np.r_[q[0]*r[0]-q[1:]@r[1:],q[0]*r[1:]+r[0]*q[1:]+np.cross(q[1:],r[1:])]
def shifted(bodies,d):
    out=bodies.copy();out[:,23:26]+=d[:,:3];out[:,7:10]=out[:,20:23]+out[:,23:26]
    for i in range(len(out)):out[i,10:14]=multiply(quaternion(d[i,3:]),out[i,10:14])
    return out
def endpoint(e,move):
    before=e.bodies.copy();edges=e.edges.copy()
    path=e.evaluate_material(2*move/1e-6-before[:,14:20],1e-6,gravity=0)
    assert path['faults'][0]==0
    e.bodies[:]=shifted(before,move);e.bodies[:,14:20]=0;e.edges[:,35:67]=path['history'][0]
    response=e.evaluate_material(np.zeros((e.n,6)),1e-6,gravity=0)
    return response

rng=np.random.default_rng(140763);results={};maximum_j_error=0.;maximum_h_error=0.
for name in ('glass','oak','iron','ice'):
    w=CpuCoupledWorld(dict(material=name,height_m=10.));edge=w.eval.edges[0].copy();ids=edge[:2].astype(int)
    bodies=w.eval.bodies[ids].copy();edge[:2]=[0,1]
    e=CpuCoupledEvaluator(bodies,[edge]);row=e.material_geometry()[0]
    before_b=e.bodies.copy();before_e=e.edges.copy()
    assert np.array_equal(row[:4],[0,0,1,edge[2]])
    # Every derivative uses the native scalar coordinates at independent poses,
    # not a force derivative or a symmetrized finite matrix.
    for turn in (np.zeros((2,3)),rng.uniform(-.2,.2,(2,3))):
        d=np.zeros((2,6));d[:,3:]=turn;e.bodies[:]=shifted(before_b,d)
        original=e.bodies.copy();row=e.material_geometry()[0];jac=row[10:82].reshape(6,12)
        for i in range(12):
            direction=np.zeros((2,6));direction.ravel()[i]=1e-7 if i%6<3 else 1e-6;step=direction.ravel()[i]
            samples=[]
            for sign in (1,-1):e.bodies[:]=shifted(original,sign*direction);samples.append(e.material_geometry()[0,4:10])
            derivative=(samples[0]-samples[1])/(2*step);error=float(np.max(abs(derivative-jac[:,i])))
            assert error<2e-8,(name,i,error);maximum_j_error=max(maximum_j_error,error)
        e.bodies[:]=original
        for axis in range(3):
            hessian=attachment_hessian(row,axis,e.bodies)
            for _ in range(6):
                direction=rng.normal(size=(2,6));direction[:,:3]*=.01;step=5e-5
                scalars=[]
                for sign in (1,-1):e.bodies[:]=shifted(original,sign*step*direction);scalars.append(e.material_geometry()[0,4+axis])
                actual=(sum(scalars)-2*row[4+axis])/step**2;expected=direction.ravel()@hessian@direction.ravel()
                error=abs(actual-expected);assert error<3e-8,(name,axis,error);maximum_h_error=max(maximum_h_error,error)
        e.bodies[:]=before_b
    e.edges[:]=before_e;row=e.material_geometry()[0];normal=row[82:85]
    models={};started=time.perf_counter()
    for choice in ('opening','compression'):
        model=material_branch_model(e,normal_at_zero=choice);models[choice]=model
        np.testing.assert_allclose(model['stiffness'],model['stiffness'].T,rtol=0,atol=1e-9)
        assert model['execution_admitted'] is False
        mixed=material_branch_model(e,normal_at_zero=[choice]);np.testing.assert_array_equal(mixed['stiffness'],model['stiffness'])
    refuses(lambda:material_branch_model(e,normal_at_zero=[]))
    # Pristine branch K matches the native one-sided endpoint force response
    # in each allowed normal direction, including shear on compression.
    branch_errors={}
    for choice,sign in [('opening',1),('compression',-1)]:
        errors=[]
        for amplitude in (1e-10,5e-11):
            for shear in (0.,.2):
                e.bodies[:]=before_b;e.edges[:]=before_e
                d=np.zeros((2,6));d[1,:3]=amplitude*(sign*normal+shear*row[85:88])
                response=endpoint(e,d);actual=response['forces'][0].ravel()
                predicted=models[choice]['force']-models[choice]['stiffness']@d.ravel()
                relative=float(np.linalg.norm(actual-predicted)/max(np.linalg.norm(actual),1e-30))
                assert relative<5e-7,(name,choice,amplitude,shear,relative);errors.append(relative)
                loaded=material_branch_model(e,normal_at_zero=choice)
                np.testing.assert_allclose(loaded['force'],actual,rtol=5e-12,atol=1e-12)
                expected_energy=response['ledger'][0,0]
                assert abs(loaded['energy_j']-expected_energy)<1e-12*max(expected_energy,1e-20)
        branch_errors[choice]=max(errors)
    e.bodies[:]=before_b;e.edges[:]=before_e
    index=38 if int(edge[2])!=1 else 50
    e.edges[0,index]=1e-8
    refuses(lambda:material_branch_model(e,normal_at_zero='opening'));e.edges[:]=before_e
    # Both normal-only cohesive branches retain their original declared
    # compression coefficient; kind2's normal clamp must not erase kind0.
    if int(edge[2])==2:
        e.edges[0,2]=0
        for sign,choice in [(1,'opening'),(-1,'compression')]:
            e.bodies[:]=before_b;e.edges[:,35:67]=0
            model=material_branch_model(e,normal_at_zero=choice)
            d=np.zeros((2,6));d[1,:3]=sign*1e-10*normal
            response=endpoint(e,d)
            np.testing.assert_allclose(response['forces'][0].ravel(),-model['stiffness']@d.ravel(),rtol=1e-9,atol=1e-10)
            loaded=material_branch_model(e,normal_at_zero=choice)
            assert abs(loaded['energy_j']-response['ledger'][0,0])<1e-12*max(loaded['energy_j'],1e-20)
        e.bodies[:]=before_b;e.edges[:]=before_e
    if int(edge[2])==2:
        assert np.linalg.norm(models['opening']['stiffness']-models['compression']['stiffness'])>0
        # No normal response under compression, while shear is retained.
        d=np.zeros((2,6));d[1,:3]=-normal
        assert np.linalg.norm(models['compression']['stiffness']@d.ravel())<1e-8
        d[1,:3]=row[85:88];assert np.linalg.norm(models['compression']['stiffness']@d.ravel())>0
        e.edges[0,36]=2*edge[19]/edge[18];refuses(lambda:material_branch_model(e,normal_at_zero='opening'));e.edges[:]=before_e
    else:
        np.testing.assert_array_equal(models['opening']['stiffness'],models['compression']['stiffness'])
        e.edges[0,35]=1.;refuses(lambda:material_branch_model(e,normal_at_zero='opening'));e.edges[:]=before_e
    protected=np.full((1,100),123.)
    assert e.lib.banjo_coupled_cpu_material_geometry(e.bodies,e.n,e.edges,e.m,0,protected)==-1 and np.all(protected==123)
    bad=e.bodies.copy();bad[0,23]=float('nan')
    assert e.lib.banjo_coupled_cpu_material_geometry(bad,e.n,e.edges,e.m,1,protected)==-1 and np.all(protected==123)
    assert np.array_equal(e.bodies,before_b) and np.array_equal(e.edges,before_e)
    results[name]=dict(native_one_sided_force_relative_errors=branch_errors,build_and_checks_wall_s=time.perf_counter()-started,
        conditional_branches_distinct=int(edge[2])==2,full_force_rows=e.n*6,execution_admitted=False)
record=dict(schema='banjo.native-material-branch-verification.v1',materials=results,
    maximum_native_coordinate_gradient_error=maximum_j_error,maximum_attachment_curvature_error=maximum_h_error,
    scope='Native scalar coordinates/elastic one-sided potentials, private preparation; no reduced execution')
if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record,indent=2))
