"""Native differentials and continuous correlated geometry, not modal execution."""
import argparse,math,os,sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from coupled_modes import ModeBasis,contact_envelope
from cpu_coupled_world import CpuCoupledEvaluator,CpuCoupledWorld
p=argparse.ArgumentParser();p.add_argument('--library',type=Path,required=True);args=p.parse_args()
os.environ['BANJO_COUPLED_CPU_LIBRARY']=str(args.library.resolve())

def refuses(fn):
    try:fn()
    except (ValueError,RuntimeError):return
    raise AssertionError('Invalid observation admitted')

def cayley(t):
    x,y,z=t;s=np.array([[0,-z,y],[z,0,-x],[-y,x,0.]])
    return np.linalg.solve(np.eye(3)-s/2,np.eye(3)+s/2)

def quaternion(t):
    q=np.r_[1.,np.asarray(t)/2];return q/np.linalg.norm(q)

def rotation(q):
    w,x,y,z=q
    return np.column_stack([np.array(v)+2*np.cross([x,y,z],w*np.array(v)+np.cross([x,y,z],v)) for v in np.eye(3)])

def oracle(row,bodies):
    owner=int(row[3]);target=int(row[1] if owner==row[0] else row[0]);site=int(row[2])%24
    normal=site//8;face=site//4;u=(normal+1)%3;v=(normal+2)%3
    local=np.zeros(3);local[normal]=(-1 if face%2==0 else 1)*bodies[owner,4+normal]
    local[u]=(-1 if site%2==0 else 1)*bodies[owner,4+u]/math.sqrt(3)
    local[v]=(-1 if (site//2)%2==0 else 1)*bodies[owner,4+v]/math.sqrt(3)
    r=bodies[owner,20:23]-bodies[target,20:23]+bodies[owner,23:26]-bodies[target,23:26]+rotation(bodies[owner,10:14])@local
    z=rotation(bodies[target,10:14]).T@r
    if bodies[target,0]==0:return z[1]
    q=abs(z)-bodies[target,4:7]
    return np.linalg.norm(np.maximum(q,0))+min(max(q),0)

# Identical eigenvalues share functions; arbitrary eigenspace coordinates must
# not destroy equal-motion cancellation. Near eigenvalues stay distinct.
for eigen in (0.,16.,-4.,1e12):
    b=ModeBasis([1.,1.],np.eye(2)*eigen,[.3,.3],[.4,.4])
    r=b.envelope(.2,np.array([[1.,-1.],[2.,-2.],[1.,1.]]))
    assert max(abs(r['displacement_lower'][:2]))<1e-12 and max(abs(r['displacement_upper'][:2]))<1e-12
    for t in np.linspace(0,.2,103):
        x=b.advance(float(t))['displacement'];observed=np.array([x[0]-x[1],2*(x[0]-x[1]),x.sum()])
        assert np.all(observed>=r['displacement_lower']) and np.all(observed<=r['displacement_upper'])
    refuses(lambda:b.envelope(.1,[[float('nan'),0]]));refuses(lambda:b.envelope(.1,[[1]]))
near=ModeBasis([1.,1.],np.diag([16.,16.+1e-10]),[0.,0.],[1.,1.])
assert len(np.unique(near.eigenvalues))==2
bound=near.envelope(1.5,np.array([[1.,-1.]]))
for t in np.linspace(0,1.5,401):
    x=near.advance(float(t))['displacement'];assert bound['displacement_lower'][0]<=x[0]-x[1]<=bound['displacement_upper'][0]
assert bound['displacement_upper'][0]-bound['displacement_lower'][0]>.1,'near frequencies must not be silently merged'

w=CpuCoupledWorld(dict(height_m=10));template=w.eval.bodies[3].copy()
def body(position,shape=1,mass=.01,turn=(0,0,0)):
    b=template.copy();b[0]=shape;b[1]=mass;b[2]=mass*.01**2/6 if mass else 0
    b[4:7]=.008 if mass else [.005,.008,.011];b[7:10]=b[20:23]=position;b[23:26]=0
    b[10:14]=b[26:30]=quaternion(turn);b[14:20]=0;return b

rng=np.random.default_rng(91573);checks=0
for target_shape in (0,1):
    for reverse in (False,True):
        for case in range(4):
            a=body([.014,.027,-.01],turn=rng.uniform(-.6,.6,3))
            b=body([-.006,-.009,.005],target_shape,0,turn=rng.uniform(-.6,.6,3))
            e=CpuCoupledEvaluator(np.array([b,a] if reverse else [a,b]),[])
            before=e.bodies.copy();rows=e.contact_differential()
            for row in rows:
                assert abs(oracle(row,e.bodies)-row[4])<2e-16
                ga,ta,gb,tb=row[19:31].reshape(4,3)
                assert np.linalg.norm(ga+gb)<1e-13
                assert np.linalg.norm(np.cross(e.bodies[0,7:10],ga)+ta+np.cross(e.bodies[1,7:10],gb)+tb)<1e-12
                for index in range(12):
                    obj=index//6;axis=index%3;rot=index%6>=3;delta=1e-6 if rot else 1e-7
                    states=[]
                    for sign in (1,-1):
                        candidate=before.copy()
                        if rot:
                            t=np.zeros(3);t[axis]=sign*delta
                            # Independent exponential increment, not native Cayley.
                            q=np.r_[math.cos(delta/2),t*math.sin(delta/2)/delta]
                            old=candidate[obj,10:14];v=np.array(q[1:]);ov=old[1:]
                            candidate[obj,10:14]=np.r_[q[0]*old[0]-v@ov,q[0]*ov+old[0]*v+np.cross(v,ov)]
                        else:candidate[obj,23+axis]+=sign*delta;candidate[obj,7+axis]+=sign*delta
                        states.append(oracle(row,candidate))
                    derivative=(states[0]-states[1])/(2*delta)
                    assert abs(derivative-row[19+index])<3e-7,(target_shape,reverse,index,derivative,row[19+index])
                    checks+=1
            assert np.array_equal(e.bodies,before)
            protected=np.full((48,34),123.)
            assert e.lib.banjo_coupled_cpu_contact_differential(e.bodies,e.n,0,protected)==-1 and np.all(protected==123)
            bad=e.bodies.copy();bad[0,23]=float('nan')
            assert e.lib.banjo_coupled_cpu_contact_differential(bad,e.n,48,protected)==-1 and np.all(protected==123)

# Continuous full-cycle, close/reopen, feature crossing and large-turn paths.
# The native law is not evolved; independent geometry checks conditional bounds.
for frequency in (0.,16.,1e6):
    for target_shape in (0,1):
        for common in (False,True):
            e=CpuCoupledEvaluator(np.array([body([0,.019,0]),body([0,0,0],target_shape,.01 if target_shape else 0)]),[])
            d=len(e.dynamic);v=rng.uniform(-.2,.2,d);f=rng.uniform(-.4,.4,d)
            if common and d==12:v[6:]=v[:6];f[6:]=f[:6]
            basis=ModeBasis(np.ones(d),np.eye(d)*frequency,f,v)
            basis.dynamic_dofs=e.dynamic;basis.native_bodies=e.bodies.copy();basis.native_edges=e.edges.copy();basis.world_body_ids=list(range(e.n))
            h=.5;guard=contact_envelope(basis,e,h);original=e.bodies.copy()
            for t in np.linspace(0,h,129):
                move=np.zeros((e.n,6));move.ravel()[e.dynamic]=basis.advance(float(t))['displacement']
                candidate=original.copy();candidate[:,23:26]+=move[:,:3];candidate[:,7:10]=candidate[:,20:23]+candidate[:,23:26]
                for j in range(e.n):candidate[j,10:14]=quaternion(move[j,3:])
                actual=np.array([oracle(row,candidate) for row in guard['native_differential']])
                assert np.all(actual>=guard['lower_gap_m']) and np.all(actual<=guard['upper_gap_m'])
            if common and frequency==0 and target_shape==1:
                assert guard['summary']['maximum_rotation_remainder_m']>0,'common affine COM motion is not exact rigid rotation'
# Explicit large Cayley parameters, opposite turns and both moving frames.
e=CpuCoupledEvaluator(np.array([body([0,.019,0]),body([0,0,0])]),[]);d=len(e.dynamic)
basis=ModeBasis(np.ones(d),np.zeros((d,d)),np.zeros(d),[.2,-.1,.3,3.,-2.,4.,-.2,.1,-.3,-4.,3.,-2.])
basis.dynamic_dofs=e.dynamic;basis.native_bodies=e.bodies.copy();basis.native_edges=e.edges.copy();basis.world_body_ids=[0,1]
guard=contact_envelope(basis,e,1.)
for t in np.linspace(0,1.,257):
    move=basis.advance(float(t))['displacement'].reshape(2,6);candidate=e.bodies.copy()
    candidate[:,23:26]+=move[:,:3];candidate[:,7:10]=candidate[:,20:23]+candidate[:,23:26]
    for j in range(2):
        candidate[j,10:14]=quaternion(move[j,3:])
        assert np.allclose(rotation(candidate[j,10:14]),cayley(move[j,3:]),rtol=0,atol=1e-15)
    actual=np.array([oracle(row,candidate) for row in guard['native_differential']])
    assert np.all(actual>=guard['lower_gap_m']) and np.all(actual<=guard['upper_gap_m'])
# Independent equal free translations cancel before bounding. This was false
# for body-wise envelopes, even though no geometry could change.
e=CpuCoupledEvaluator(np.array([body([0,.019,0]),body([0,0,0])]),[]);d=len(e.dynamic)
basis=ModeBasis(np.ones(d),np.zeros((d,d)),np.zeros(d),np.tile([2.,3.,4.,0.,0.,0.],2))
basis.dynamic_dofs=e.dynamic;basis.native_bodies=e.bodies.copy();basis.native_edges=e.edges.copy();basis.world_body_ids=[0,1]
guard=contact_envelope(basis,e,2.)
assert max(guard['upper_gap_m']-guard['lower_gap_m'])<1e-11
assert guard['summary']['mean_gap_width_ratio']<1e-12
assert guard['summary']['possible_contact_changes']<guard['summary']['legacy_possible_contact_changes']
# A support/geometry edit cannot keep an old observation recipe alive.
e.bodies[0,23]+=1e-15;e.bodies[0,7]=e.bodies[0,20]+e.bodies[0,23]
refuses(lambda:contact_envelope(basis,e,2.))
print('PASS',checks,'independent native derivatives; degeneracy/correlation and continuous Cayley/SDF bounds')
