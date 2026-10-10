"""Native endpoint branches and independent Cayley scalar-gap curvature.

This verifies private preparation, not accepted reduced motion or fracture.
"""
import argparse, json, os, sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from cpu_coupled_world import CpuCoupledWorld,CpuCoupledEvaluator
from coupled_modes import contact_gap_hessian,contact_branch_model,prepare_contact_branches

p=argparse.ArgumentParser();p.add_argument('--library',type=Path,required=True)
p.add_argument('--output',type=Path);args=p.parse_args()
os.environ['BANJO_COUPLED_CPU_LIBRARY']=str(args.library.resolve())

def refuses(fn):
    try:fn()
    except (ValueError,RuntimeError):return
    raise AssertionError('Unsupported preparation admitted')

def quaternion(t):
    q=np.r_[1.,np.asarray(t)/2];return q/np.linalg.norm(q)

def multiply(q,r):
    return np.r_[q[0]*r[0]-q[1:]@r[1:],q[0]*r[1:]+r[0]*q[1:]+np.cross(q[1:],r[1:])]

template=CpuCoupledWorld(dict(height_m=10)).eval.bodies[3].copy()
def body(position,shape=1,mass=.01,turn=(0,0,0)):
    b=template.copy();b[0]=shape;b[1]=mass;b[2]=mass*.016**2/6 if mass else 0
    b[4:7]=.008 if mass else [.04,.03,.05]
    b[7:10]=b[20:23]=position;b[23:26]=0
    b[10:14]=b[26:30]=quaternion(turn);b[14:20]=0;return b

rng=np.random.default_rng(66253);maximum_error=0.;checked=0
for shape in (0,1):
    for reverse in (False,True):
        source=body([.009,-.002,.006],turn=(.2,-.3,.1))
        target=body([0,0,0],shape,0,turn=(-.12,.08,.16))
        e=CpuCoupledEvaluator(np.array([target,source] if reverse else [source,target]),[])
        original=e.bodies.copy();rows=e.contact_differential()
        for index,row in enumerate(rows):
            try:hessian=contact_gap_hessian(row,original)
            except ValueError:continue
            assert np.array_equal(hessian,hessian.T)
            # Independent native scalar gap at poses reached by a Cayley
            # increment. Test mixed coordinates, not differentiated torques.
            for _ in range(3):
                direction=rng.normal(size=12);direction.reshape(2,6)[:,:3]*=.01
                predicted=float(direction@hessian@direction)
                errors=[]
                for step in (1e-4,5e-5):
                    gaps=[]
                    for sign in (1,-1):
                        candidate=original.copy();move=(sign*step*direction).reshape(2,6)
                        candidate[:,23:26]+=move[:,:3];candidate[:,7:10]=candidate[:,20:23]+candidate[:,23:26]
                        for i in range(2):candidate[i,10:14]=multiply(quaternion(move[i,3:]),original[i,10:14])
                        e.bodies[:]=candidate;gaps.append(e.contact_differential()[index,4])
                    measured=(sum(gaps)-2*row[4])/step**2
                    errors.append(abs(measured-predicted))
                e.bodies[:]=original
                assert errors[-1]<3e-6*max(abs(predicted),.01),(shape,reverse,index,predicted,errors)
                maximum_error=max(maximum_error,errors[-1]);checked+=1
        assert np.array_equal(original,e.bodies)

# Exact touching is explicit: opening has no stiffness, closing has full
# native stiffness. A contact branch is not averaged at the boundary.
for depth in (0.,-.002,.002):
    e=CpuCoupledEvaluator(np.array([body([0,.008+depth,0]),body([0,0,0],0,0)]),[])
    a=contact_branch_model(e,touching='open');b=contact_branch_model(e,touching='closed')
    full=e.evaluate(np.zeros((2,6)),1e-6,gravity=0)
    assert not full['faults'][0]
    np.testing.assert_allclose(a['force'],full['forces'][0].ravel(),rtol=2e-13,atol=2e-12)
    assert abs(a['energy_j']-full['ledger'][0,4])<=1e-15
    if depth==0:
        assert a['touching_sites']==b['touching_sites']==4
        assert not np.any(a['stiffness']) and np.linalg.norm(b['stiffness'])>0
    else:np.testing.assert_array_equal(a['stiffness'],b['stiffness'])
    if depth<0:
        assert a['geometric_curvature_norm']>0
        assert np.linalg.norm(a['force'].reshape(2,6)[:,:3].sum(axis=0))<1e-12
        total=sum((np.cross(e.bodies[i,7:10],a['force'].reshape(2,6)[i,:3])+a['force'].reshape(2,6)[i,3:] for i in range(2)),np.zeros(3))
        assert np.linalg.norm(total)<1e-12
        original=e.bodies.copy()
        for _ in range(12):
            direction=rng.normal(size=12);direction.reshape(2,6)[:,:3]*=.01
            energies=[];step=1e-5
            for sign in (1,-1):
                candidate=original.copy();move=(sign*step*direction).reshape(2,6)
                candidate[:,23:26]+=move[:,:3];candidate[:,7:10]=candidate[:,20:23]+candidate[:,23:26]
                for i in range(2):candidate[i,10:14]=multiply(quaternion(move[i,3:]),original[i,10:14])
                e.bodies[:]=candidate;energies.append(e.evaluate(np.zeros((2,6)),1e-6,gravity=0)['ledger'][0,4])
            e.bodies[:]=original
            measured=(sum(energies)-2*a['energy_j'])/step**2;expected=direction@a['stiffness']@direction
            assert abs(measured-expected)<2e-5*max(abs(expected),1.),(measured,expected)
    sentinel=np.full(48,123.)
    assert e.lib.banjo_coupled_cpu_contact_stiffness(e.bodies,e.n,0,sentinel)==-1 and np.all(sentinel==123)
    refuses(lambda:contact_branch_model(e,touching='average'))

results={}
for name in ('glass','oak','iron','ice'):
    w=CpuCoupledWorld(dict(material=name,height_m=.001,ball_mass_kg=.01))
    # Remove the separated primitive only, keeping all installed sheet/support
    # rows and interfaces; use the world's normal private preparation mapping.
    ids=[i for i in range(w.eval.n) if w.eval.bodies[i,0]!=2]
    bodies=w.eval.bodies[ids].copy();edges=w.eval.edges.copy()
    mapping={old:new for new,old in enumerate(ids)}
    for edge in edges:edge[:2]=[mapping[int(i)] for i in edge[:2]]
    e=CpuCoupledEvaluator(bodies,edges)
    before_b=e.bodies.copy();before_e=e.edges.copy()
    delta=np.array([1e-13 if dof%6<3 else 1e-11 for dof in e.dynamic])
    candidates={};receipt=prepare_contact_branches(e,bodies.copy(),edges.copy(),delta,candidate_store=candidates)
    assert receipt['execution_admitted'] is False
    assert len(candidates)==4 and receipt['analytical_material_preparation']['full_reaction_maps_retained']
    for candidate in candidates.values():
        assert candidate.full_force.shape==(e.n*6,) and candidate.full_force_tangent.shape==(e.n*6,len(e.dynamic))
        assert np.array_equal(candidate.native_edges,edges) and np.array_equal(candidate.native_bodies,bodies)
        assert np.linalg.norm(candidate.advance(1/240)['affine_dynamic_impulse_residual'])<1e-12
    assert np.array_equal(before_b,e.bodies) and np.array_equal(before_e,e.edges)
    # Constitutive-only trials retain exact full-native history/poses, even
    # while the full native response includes contact independently.
    velocity=rng.normal(scale=1e-5,size=(e.n,6));velocity[e.bodies[:,1]==0]=0
    separated=e.evaluate_material(velocity,1e-6);full=e.evaluate(velocity,1e-6)
    np.testing.assert_array_equal(separated['faults'],full['faults'])
    np.testing.assert_array_equal(separated['history'],full['history'])
    np.testing.assert_array_equal(separated['poses'],full['poses'])
    assert separated['ledger'][0,4]==0
    refuses(lambda:e.evaluate_material(velocity,float('nan')))
    assert np.array_equal(before_b,e.bodies) and np.array_equal(before_e,e.edges)
    results[name]=receipt
record=dict(schema='banjo.contact-branch-verification.v1',curvature_directional_cases=checked,
    maximum_curvature_absolute_error=maximum_error,materials=results,
    scope='Native private endpoint curvature/material separation, no reduced execution or realtime claim')
if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record,indent=2))
