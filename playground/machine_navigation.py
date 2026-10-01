"""Bounded local routes over observed native geometry, driven by native motors.

The routine asks for one waypoint at a time. Planning neither moves bodies nor
edits the ground. The stopping margin is a controller allowance, not traction.
"""
from __future__ import annotations

import heapq
import math
from itertools import product

from machine_ports import _turn

CELL_M = .5
LOOK_M = 6.
STOP_MARGIN_M = .65
# Turning clear of a worked area can require an outward loop before any
# distance progress. A 1,024-query search stopped before the measured return
# loop on generated map 0; retain the 6 m horizon and bound the expanded search.
MAX_SURVEYS = 4096
WAYPOINT_NEAR_M = .4


def shape_points(body, cell_m):
    """World corners of occupied parts, retaining each part's rotation."""
    q=body.get('orientation_wxyz') or [1,0,0,0]
    at=body.get('position_m') or [0,0,0]
    points=[]
    parts=body.get('rigid_parts_local')
    if parts:
        for p in parts:
            center=p['center_local_m'];size=p['dimensions_m']
            turn=p.get('rotation_wxyz') or [1,0,0,0]
            for signs in product((-1,1),repeat=3):
                local=_turn(turn,[signs[a]*size[a]/2 for a in range(3)])
                points.append([center[a]+local[a] for a in range(3)])
    else:
        cells=body.get('cells_local_m') or []
        if cells:
            lo=[min(p[a] for p in cells)-cell_m/2 for a in range(3)]
            hi=[max(p[a] for p in cells)+cell_m/2 for a in range(3)]
        else:
            size=body.get('dimensions_m') or [0,0,0]
            lo=[-s/2 for s in size];hi=[s/2 for s in size]
        points=list(product(*[(lo[a],hi[a]) for a in range(3)]))
    return [[v+at[a] for a,v in enumerate(_turn(q,p))] for p in points]


def bounds(body, cell_m):
    points=shape_points(body,cell_m)
    return ([min(p[a] for p in points) for a in range(3)],
            [max(p[a] for p in points) for a in range(3)])


def waypoint(ctx, target, arrival=(0.,0.)):
    """One safe visible waypoint, or an explicit blocked result. No global map."""
    at=ctx.at();mine=set(ctx.program.get('parts') or [])|{ctx.program.get('body')}
    own=[p for b in ctx.bodies or [] if b.get('name') in mine for p in shape_points(b,ctx.cell_m)]
    if not own:return None
    radius=max(math.hypot(p[0]-at[0],p[2]-at[1]) for p in own)
    if not 0<radius<LOOK_M/2:
        return {'blocked':'its assembly is too large for the local route window'}
    floor=float(ctx.program['at_m'][1])-float(ctx.program.get('height_m') or 0)
    # A go_to leg drives forward, including its initial facing turn. Match the
    # native forward guard; rear probes remain active for actual reversing.
    probes=[s for s in ctx.program.get('sensors') or []
            if s.get('kind')=='ground' and s.get('stops',1)>=0]
    probe_radius=max((math.hypot(s['at_m'][0]-at[0],s['at_m'][2]-at[1]) for s in probes),default=0.)
    probe_offsets=[(s['at_m'][0]-at[0],s['at_m'][2]-at[1],float(s['depth_m'])) for s in probes]
    rear=[s for s in ctx.program.get('sensors') or []
          if s.get('kind')=='ground' and s.get('stops',1)<0]
    rear_offsets=[(s['at_m'][0]-at[0],s['at_m'][2]-at[1],float(s['depth_m'])) for s in rear]
    initial_heading=math.radians(ctx.heading())
    obstacles=[]
    for b in ctx.bodies or []:
        if b.get('name') in mine:continue
        lo,hi=bounds(b,ctx.cell_m)
        if hi[1]<floor-.1:continue  # buried geometry does not obstruct this route
        if math.hypot(float(b['position_m'][0])-at[0],float(b['position_m'][2])-at[1])>LOOK_M+max(hi[0]-lo[0],hi[2]-lo[2]):continue
        obstacles.append((lo,hi))
    queries=0;surveyed={};valid={};rejections={}
    def rejected(kind,point,details=None):
        info=rejections.setdefault(kind,{'count':0,'nearest':None,'distance':math.inf})
        info['count']+=1;d=math.hypot(point[0]-at[0],point[1]-at[1])
        if d<info['distance']:info.update(nearest=list(point),distance=d,details=details)
    def point(node):return (at[0]+node[0]*CELL_M,at[1]+node[1]*CELL_M)
    def terrain(node):
        nonlocal queries
        x,z=point(node)
        key=(round(x,2),round(z,2))  # same observation key as Context.survey
        if key in surveyed:return surveyed[key]
        if queries>=MAX_SURVEYS or math.hypot(x-at[0],z-at[1])>LOOK_M:
            surveyed[key]=None;return None
        if not ctx.terrain_declared:
            surveyed[key]={'ground_m':0.};return surveyed[key]
        queries+=1;s=ctx.survey(x,z)
        if not s.get('on_the_ground') or float((s.get('water') or {}).get('depth_m') or 0)>.003:
            rejected('terrain',(x,z),{k:s.get(k) for k in ('on_the_ground','slope_deg','water')});s=None
        surveyed[key]=s;return s
    def clear(node):
        if node in valid:return valid[node]
        x,z=point(node)
        ok=math.hypot(x-at[0],z-at[1])<=LOOK_M-max(radius,probe_radius)
        if ok:
            # Native arrival stops up to 1 m before a waypoint. A current
            # pose can therefore be inside the planning margin while the
            # actual assembled footprint is clear. Let the first leg leave
            # that margin; do not ignore the physical radius or an obstacle.
            pad=STOP_MARGIN_M*min(1.,math.hypot(x-at[0],z-at[1])/1.5)
            for lo,hi in obstacles:
                dx=max(lo[0]-x,0,x-hi[0]);dz=max(lo[2]-z,0,z-hi[2])
                if math.hypot(dx,dz)<radius+pad:
                    rejected('geometry',(x,z),{'bounds_m':[lo,hi]});ok=False;break
        if ok:
            reach=radius/CELL_M
            footprint=((0,0),(-reach,0),(reach,0),(0,-reach),(0,reach))
            samples=[terrain((node[0]+dx,node[1]+dz)) for dx,dz in footprint]
            ok=all(s is not None for s in samples)
            if ok:
                # The declared climb bound governs the supported assembly,
                # not a point gradient on a smaller terrain triangle. Fit a
                # secant plane across its occupied radius; native pitch and
                # drop probes still veto the actual drive on sharp curvature.
                heights=[float(s['ground_m']) for s in samples]
                grade=math.degrees(math.atan(math.hypot(heights[2]-heights[1],
                                                        heights[4]-heights[3])/(2*radius)))
                if grade>float(ctx.program.get('climb_deg',8)):
                    rejected('supported_grade',(x,z),{'grade_deg':grade});ok=False
        valid[node]=ok;return ok
    poses={}
    def clear_pose(node,heading,reverse=False):
        """Predict the declared probes at this heading, using native heights.

        A hazard beside a route does not prohibit driving parallel to it. The
        native controller still measures the actual tilted assembly each step.
        """
        key=(*node,round(heading,8),reverse)
        if key in poses:return poses[key]
        center=terrain(node);gradient=(center or {}).get('ground_gradient_xz')
        ok=center is not None
        if ok and gradient:
            delta=heading-initial_heading;c=math.cos(delta);s=math.sin(delta)
            for ox,oz,limit in rear_offsets if reverse else probe_offsets:
                dx=ox*c+oz*s;dz=-ox*s+oz*c
                observed=terrain((node[0]+dx/CELL_M,node[1]+dz/CELL_M))
                reading=(float(center['ground_m'])+gradient[0]*dx+gradient[1]*dz-
                         float(observed['ground_m'])) if observed else math.inf
                if abs(reading)>limit:
                    rejected('ground_probe',point(node),{'reading_m':reading if math.isfinite(reading) else None,
                                                        'limit_m':limit,'heading_deg':math.degrees(heading)})
                    ok=False;break
        poses[key]=ok;return ok
    def angle_change(before,after):return (after-before+math.pi)%math.tau-math.pi
    def turn_clear(node,before,after):
        change=angle_change(before,after)
        steps=max(1,math.ceil(abs(change)/math.radians(22.5)))
        return all(clear_pose(node,before+change*k/steps) for k in range(steps+1))
    def leg_clear(node,nxt,before,after):
        if not turn_clear(node,before,after):return False
        steps=max(1,math.ceil(math.hypot(nxt[0]-node[0],nxt[1]-node[1])*CELL_M/(CELL_M/2)))
        return all(clear(p) and clear_pose(p,after) for p in
                   ((node[0]+(nxt[0]-node[0])*k/steps,node[1]+(nxt[1]-node[1])*k/steps)
                    for k in range(1,steps+1)))
    def distance(node):
        x,z=point(node);return math.hypot(x-target[0],z-target[1])
    def remaining(node):
        d=distance(node)
        return max(arrival[0]-d,0.,d-arrival[1])
    start=(0,0)
    if remaining(start)<=CELL_M/2:
        # Already in the receiving/work region: only ask its brakes to hold.
        # Do not require a new route over terrain it need not traverse.
        return {'target':list(at),'final':True,'radius_m':radius,'surveys':queries,'path':[list(at)]}
    if not clear(start):return {'blocked':'there is no clearance around its current assembled footprint',
                               'rejections':rejections,'radius_m':radius,'surveys':queries}
    # Reserve a checked short retreat before a failed search consumes its
    # observation budget. No blind reverse: require actual rear probes and
    # sample a metre including braking room; request only half that distance.
    retreat=None
    if len(rear)>=2 and not any(s.get('sees') for s in rear):
        dx,dz=-math.sin(initial_heading),-math.cos(initial_heading)
        if all(clear((dx*k*.25/CELL_M,dz*k*.25/CELL_M)) and
               clear_pose((dx*k*.25/CELL_M,dz*k*.25/CELL_M),initial_heading,reverse=True)
               for k in range(5)):
            retreat={'target':[at[0]+dx*.5,at[1]+dz*.5],'from_m':list(at),
                     'reverse':True,'travel_m':.5,'heading_deg':ctx.heading(),
                     'final':False,'radius_m':radius}
    # Heading is part of a route state: arrival from one direction can be safe
    # while a turn at the same location would sweep a probe over a drop.
    directions=[(dx,dz,math.atan2(dx,dz)) for dx,dz in product((-1,0,1),repeat=2) if dx or dz]
    begin=(*start,-1)
    def heading(state):return initial_heading if state[2]==-1 else directions[state[2]][2]
    costs={begin:0.};parents={};queue=[(remaining(start),0.,begin)];best=begin
    while queue:
        _,cost,state=heapq.heappop(queue);node=state[:2]
        if cost!=costs.get(state):continue
        if remaining(node)<remaining(best[:2]):best=state
        if remaining(node)<=CELL_M/2:best=state;break
        for i,(dx,dz,yaw) in enumerate(directions):
            nxt=(node[0]+dx,node[1]+dz)
            if not clear(nxt):continue
            if dx and dz and (not clear((node[0]+dx,node[1])) or not clear((node[0],node[1]+dz))):continue
            if not leg_clear(node,nxt,heading(state),yaw):continue
            step=CELL_M*math.hypot(dx,dz)
            score=cost+step+.1*abs(angle_change(heading(state),yaw))
            next_state=(*nxt,i)
            if score>=costs.get(next_state,math.inf):continue
            costs[next_state]=score;parents[next_state]=state
            heapq.heappush(queue,(score+remaining(nxt),score,next_state))
    if best==begin:
        if retreat:
            return dict(retreat,surveys=queries)
        return {'blocked':'no visible dry route makes progress toward that place','rejections':rejections,
                'radius_m':radius,'surveys':queries,'reachable_nodes':len(costs)}
    path=[best]
    while path[-1]!=begin:path.append(parents[path[-1]])
    path=[state[:2] for state in reversed(path)]
    # Smooth grid zigzags only where the whole straight leg has clearance.
    # This avoids asking the caster to turn at each half-metre grid corner.
    chosen=path[1]
    for candidate in reversed(path[1:]):
        # A heading-state route may loop back through the same position.
        # An approach ask inside its arrival radius would brake immediately,
        # erasing that required loop/turn and replanning forever at the origin.
        if math.hypot(*candidate)*CELL_M<=WAYPOINT_NEAR_M+.05:continue
        if leg_clear(start,candidate,initial_heading,math.atan2(*candidate)):
            chosen=candidate;break
    destination=list(point(chosen))
    final=remaining(chosen)<=CELL_M/2
    if final and arrival==(0.,0.):destination=list(target)
    return {'target':destination,'final':final,'radius_m':radius,'surveys':queries,
            'path':[list(point(n)) for n in path[:64]]}
