"""Shared short ground-tool gestures. These are bounded hand targets, never
prescribed poses, forces, excavation yields or elapsed-time shortcuts."""
from __future__ import annotations
import math

CLEARANCE_M = .06
BITE_M = .08
DRAG_M = .04
ACCEL_M_S2 = 80.0
LEAD_M = .025


def lift_path(grip, tip, pointing, at):
    """Lift a grounded horizontal tool before asking the wrist to turn it.
    Established point-down taps need no lift or recovery animation."""
    if pointing[1]<-.98 or tip[1]>at[1]+.45:
        return None
    return [list(grip),[grip[0],grip[1]+.6,grip[2]]]


def _cross(a,b):
    return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]


def _unit(v):
    n=math.sqrt(sum(x*x for x in v))
    if n<1e-9: raise ValueError('Tool point and grip need independent axes')
    return [x/n for x in v]


def local_frame(tip, grip, pointing, centre, orientation):
    """Recover the native point's body frame, shared by the in-process trial."""
    w,x,y,z=orientation
    inverse=[w,-x,-y,-z]
    def rotate(v):
        a,b,c,d=inverse
        uv=_cross([b,c,d],v);uuv=_cross([b,c,d],uv)
        return [v[i]+2*(a*uv[i]+uuv[i]) for i in range(3)]
    return {'tip_local':rotate([t-c for t,c in zip(tip,centre)]),
            'grip_local':rotate([g-c for g,c in zip(grip,centre)]),
            'pointing_local':rotate(pointing)}


def _quaternion(m):
    trace=sum(m[i][i] for i in range(3))
    if trace>0:
        s=2*math.sqrt(trace+1)
        return [s/4,(m[2][1]-m[1][2])/s,(m[0][2]-m[2][0])/s,(m[1][0]-m[0][1])/s]
    i=max(range(3),key=lambda i:m[i][i]);j=(i+1)%3;k=(i+2)%3
    s=2*math.sqrt(1+m[i][i]-m[j][j]-m[k][k]);q=[0.0]*4
    q[0]=(m[k][j]-m[j][k])/s;q[i+1]=s/4
    q[j+1]=(m[j][i]+m[i][j])/s;q[k+1]=(m[k][i]+m[i][k])/s
    return q


def ready_pose(point, at, eyes, direction=None):
    """Point above the actual surveyed contact, handle towards its user. The
    native wrist/hand must achieve this wish; selecting it grants no work."""
    tip,grip=point['tip_local'],point['grip_local']
    y=_unit(point['pointing_local'])
    z=_unit(_cross(y,[g-t for g,t in zip(grip,tip)]));x=_cross(y,z)
    horizontal=[at[0]-eyes[0],0,at[2]-eyes[2]]
    forward=_unit(horizontal) if sum(v*v for v in horizontal)>1e-12 else [0,0,-1]
    into=_unit(direction) if direction is not None else [0,-1,0]
    side=_cross([0,1,0],into) if direction is not None else _cross([0,1,0],forward)
    if sum(v*v for v in side)<1e-12: side=_cross([0,1,0],forward)
    side=_unit(side);across=_cross(into,side)
    local=[x,y,z];world=[across,into,side]
    matrix=[[sum(world[k][i]*local[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    offset=[sum(matrix[i][j]*(grip[j]-tip[j]) for j in range(3)) for i in range(3)]
    return {'hand':[at[i]+offset[i]-CLEARANCE_M*into[i] for i in range(3)],
            'hand_q':_quaternion(matrix)}


def contact_path(grip, use, eyes, at):
    """Down, a short lateral working motion, then withdraw to clearance.
    No wrist turn; native resistance decides whether any part succeeds."""
    forward=_unit([at[0]-eyes[0],0,at[2]-eyes[2]])
    down=[grip[0],grip[1]-CLEARANCE_M-BITE_M,grip[2]]
    path=[list(grip),down]
    if use['lever'] is not None:
        down=[down[i]-DRAG_M*forward[i] for i in range(3)];path.append(down)
    path.append([down[0],down[1]+CLEARANCE_M+BITE_M,down[2]])
    return path
