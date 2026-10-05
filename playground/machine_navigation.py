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
# A close destination needs a smaller motor arrival allowance than a through
# waypoint. This is a request to the native brakes, never a pose correction.
FINAL_NEAR_M = .1
# Water under its own footprint it may drive out of: a dig's puddle, not a lake.
OWN_WET_M = .1
# How deep water counts as wet, for a machine with no water sensor to say.
WET_M = .003
# A wet cell's step costs this many dry ones: it wades only where that saves
# going round.
WADE_COST = 2.


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


def part_bounds(body, cell_m):
    """One box per rigid part, or the whole body's for anything else.

    A solar farm is a deck on four legs: as one box it filled the open space
    under its deck, and a rover stopped beside it could never plan a route
    away. Its parts are its legs, its deck and its panels, each where it is."""
    parts=body.get('rigid_parts_local')
    if not parts:return [bounds(body,cell_m)]
    out=[]
    for part in parts:
        points=shape_points({**body,'rigid_parts_local':[part]},cell_m)
        out.append(([min(p[a] for p in points) for a in range(3)],[max(p[a] for p in points) for a in range(3)]))
    return out


def waypoint(ctx, target, arrival=(0.,0.), avoid_workings=True):
    """One safe visible waypoint, or an explicit blocked result. No global map."""
    at=ctx.at();mine=set(ctx.program.get('parts') or [])|{ctx.program.get('body')}
    close_arrival=0 < arrival[1] <= 1. and arrival[0] == 0.
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
    # The water it may go through is the water its own sensors let it: a
    # route its reflexes would refuse is no route. The mine's rover, held to
    # 3 mm, was boxed in at a 50 mm shore margin; its sensors now let it wade
    # to its caster's axle, and so does this.
    wade=min((float(s['depth_m']) for s in ctx.program.get('sensors') or []
              if s.get('kind')=='water' and s.get('depth_m') is not None),default=WET_M)
    obstacles=[]
    top=max(p[1] for p in own)
    for b in ctx.bodies or []:
        if b.get('name') in mine:continue
        for lo,hi in part_bounds(b,ctx.cell_m):
            if hi[1]<floor-.1:continue  # buried geometry does not obstruct this route
            if lo[1]>top+.1:continue    # a deck it passes under does not either
            if math.hypot((lo[0]+hi[0])/2-at[0],(lo[2]+hi[2])/2-at[1])>LOOK_M+max(hi[0]-lo[0],hi[2]-lo[2]):continue
            obstacles.append((lo,hi,b.get('name')))
    # Its own scoops, where its routine remembers them: holes its wheels keep
    # out of. Heights cannot show them on a hillside (a scoop on the high side
    # stands above the low side's untouched ground), and the mine's rover,
    # sent home across ground it had worked, stuck in a scoop with its wheels
    # turning and gave the trip up.
    # Only preferred: where they leave no route that makes progress, it
    # crosses them (one scoop is crossable, docs/machine-world.md) rather
    # than stand boxed in between its workings and a slope for good.
    workings=[(d[0],d[1],d[2]/2) for d in (getattr(ctx.routine,'dug_spots',None) or [])
              if avoid_workings and math.hypot(d[0]-at[0],d[1]-at[1])<=LOOK_M+radius]
    queries=0;surveyed={};valid={};rejections={};start_grade=[0.]
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
        depth=float((s.get('water') or {}).get('depth_m') or 0)
        # Water is a bound on where it may GO, not on the ground it already
        # stands on: a rover's own dig fills with water under it, and refusing
        # its own wet cells left it parked in the hole for good. Only the
        # cells it occupies now, and only shallow water.
        own=math.hypot(x-at[0],z-at[1])<=radius+1e-6 and depth<OWN_WET_M
        if not s.get('on_the_ground') or (depth>wade and not own):
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
            if close_arrival:
                # A transit stopping margin must not exclude the receiving
                # region itself. Taper that allowance at a close destination;
                # the actual occupied radius and native hazard guards remain.
                pad=min(pad,STOP_MARGIN_M*max(0.,math.hypot(x-target[0],z-target[1])-arrival[1])/1.5)
            for lo,hi,name in obstacles:
                dx=max(lo[0]-x,0,x-hi[0]);dz=max(lo[2]-z,0,z-hi[2])
                # Already within a part's margin where it stands (beside a leg
                # of the solar farm), it may still move AWAY from that part:
                # refusing every node left it parked there for good.
                ox=max(lo[0]-at[0],0,at[0]-hi[0]);oz=max(lo[2]-at[1],0,at[1]-hi[2])
                if math.hypot(ox,oz)<radius and (node==(0,0) or math.hypot(dx,dz)>math.hypot(ox,oz)+1e-6):continue
                if math.hypot(dx,dz)<radius+pad:
                    rejected('geometry',(x,z),{'bounds_m':[lo,hi],'body':name});ok=False;break
        if ok:
            # No stopping margin: a scoop is ground to keep its wheels out of,
            # not a solid to brake short of. Standing over one, it may still
            # move away from it, as from a part it stands beside.
            for px,pz,half in workings:
                d=math.hypot(x-px,z-pz);now=math.hypot(at[0]-px,at[1]-pz)
                if now<radius+half and (node==(0,0) or d>now+1e-6):continue
                if d<radius+half:
                    rejected('working',(x,z),{'scoop_m':[px,pz]});ok=False;break
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
                # The bound is on where it may GO, not on the ground it already
                # stands on. A final arrival is not graded, so a rover sent to
                # dig on a hillside a little over its bound (the mine's vein,
                # 8.15 deg against 8) stopped there and then refused every
                # route away, its own cell failing first. Every other node is
                # still graded, and the native probes still veto the drive.
                # Nor may the cells round it be: on a working's pitted
                # hillside at 9.1 deg every cell beside the mine's rover was
                # 9.08 deg, and no route away was admitted for the rest of
                # the run. Standing over the bound, it may cross ground no
                # steeper than it already stands on, and nothing steeper.
                if node==(0,0):start_grade[0]=grade
                bound=max(float(ctx.program.get('climb_deg',8)),start_grade[0])
                if grade>bound and node!=(0,0):
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
    # Reserve a checked short retreat before a failed search consumes its
    # observation budget. No blind reverse: require actual rear probes and
    # sample a metre including braking room; request only half that distance.
    # Stopped where its own footprint is not clear (at a river's margin, say),
    # only the cells it would back into are asked: requiring its present cell
    # too left it there for good, refusing every route, even after 'go on'.
    start_clear=clear(start)
    retreat=None
    if len(rear)>=2 and not any(s.get('sees') for s in rear):
        dx,dz=-math.sin(initial_heading),-math.cos(initial_heading)
        if all(clear((dx*k*.25/CELL_M,dz*k*.25/CELL_M)) and
               clear_pose((dx*k*.25/CELL_M,dz*k*.25/CELL_M),initial_heading,reverse=True)
               for k in range(0 if start_clear else 1,5)):
            retreat={'target':[at[0]+dx*.5,at[1]+dz*.5],'from_m':list(at),
                     'reverse':True,'travel_m':.5,'heading_deg':ctx.heading(),
                     'final':False,'radius_m':radius}
    if not start_clear:
        if retreat:return dict(retreat,surveys=queries,escaping=True)
        if workings:return waypoint(ctx,target,arrival,avoid_workings=False)
        return {'blocked':'there is no clearance around its current assembled footprint'+(' ('+', '.join(sorted(k+(': '+str((v.get('details') or {}).get('body')) if (v.get('details') or {}).get('body') else '') for k,v in rejections.items()))+')' if rejections else ''),
                'rejections':rejections,'radius_m':radius,'surveys':queries}
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
            if float(((terrain(nxt) or {}).get('water') or {}).get('depth_m') or 0)>WET_M:step*=WADE_COST
            score=cost+step+.1*abs(angle_change(heading(state),yaw))
            next_state=(*nxt,i)
            if score>=costs.get(next_state,math.inf):continue
            costs[next_state]=score;parents[next_state]=state
            heapq.heappush(queue,(score+remaining(nxt),score,next_state))
    if best==begin:
        if retreat:
            return dict(retreat,surveys=queries)
        if workings:return waypoint(ctx,target,arrival,avoid_workings=False)
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
    near=WAYPOINT_NEAR_M
    if final and close_arrival:
        # Grid acceptance is not arrival. Stopping .4 m before a grid point
        # already .25 m outside the receiving region caused endless replans.
        # Survey the extended leg to a point inside the region with enough
        # room for the native motor's arrival radius. If it cannot fit, retain
        # the surveyed frontier and do not report final arrival.
        dx,dz=destination[0]-target[0],destination[1]-target[1]
        distance=math.hypot(dx,dz)
        reach=max(0.,arrival[1]-FINAL_NEAR_M)
        endpoint=[target[0]+dx*reach/distance,target[1]+dz*reach/distance] if distance>reach else destination
        node=((endpoint[0]-at[0])/CELL_M,(endpoint[1]-at[1])/CELL_M)
        if leg_clear(start,node,initial_heading,math.atan2(node[0],node[1])):
            destination=endpoint;near=FINAL_NEAR_M
        else:final=False
    if final and arrival==(0.,0.):destination=list(target)
    return {'target':destination,'final':final,'near_m':near,'radius_m':radius,'surveys':queries,
            'path':[list(point(n)) for n in path[:64]]}


# ---- the shared map ----------------------------------------------------------
# The local planner sees a 6 m window and nothing else, so it heads greedily at
# a place and a river between them is a wall: the mine's rover, sent home round
# a bend of water, met the bank and stood there. Beyond that window it follows
# a route over the room's record of what has been SEEN (machine_sight), the one
# every machine and the person fill in, so a drone that has flown ahead gives a
# rover its way round. Unseen ground is never routed through: what nobody has
# seen nobody can know is passable (the owner, 2026-10-04).
# Where the local window takes over: a route point this far along is handed to
# it as the next place to reach, well inside LOOK_M so it can plan right to it.
SUBGOAL_M = 4.
# How long a cell's survey stands in the shared map, in room seconds. Ground
# changes by digging and water moves; neither is quick at a metre a cell.
MAP_FRESH_S = 20.
# A step over one of its own scoops costs this many dry ones: crossed when
# going round costs more, as in the local window.
WORKING_COST = 4.
# The most map cells one plan opens: a 60 m room is 3,600.
MAP_MOST_CELLS = 6000


def _map_cells(ctx, sight):
    """The shared survey cache, on the room's own sight record, so every
    machine reads what any one of them surveyed."""
    cache=getattr(sight,'route_cells',None)
    if cache is None:
        cache={};sight.route_cells=cache
    t=float(ctx.t)
    def cell(i,j):
        if not (0<=i<sight.nx and 0<=j<sight.nz) or not sight.seen[j*sight.nx+i]:return None
        got=cache.get((i,j))
        if got is None or not 0.<=t-got[0]<MAP_FRESH_S:
            x=sight.x0_m+(i+.5)*sight.cell_m;z=sight.z0_m+(j+.5)*sight.cell_m
            got=(t,ctx.survey(x,z) or {});cache[(i,j)]=got
        return got[1]
    return cell


def map_route(ctx, target, arrival=(0.,0.)):
    """Cell middles from where it stands to the place, over seen ground it may
    cross; None when the seen ground holds no such route."""
    sight=getattr(ctx,'sight',None)
    if sight is None or not getattr(sight,'nx',0) or not ctx.terrain_declared:return None
    at=ctx.at();mine=set(ctx.program.get('parts') or [])|{ctx.program.get('body')}
    own=[p for b in ctx.bodies or [] if b.get('name') in mine for p in shape_points(b,ctx.cell_m)]
    if not own:return None
    radius=max(math.hypot(p[0]-at[0],p[2]-at[1]) for p in own)
    floor=float(ctx.program['at_m'][1])-float(ctx.program.get('height_m') or 0)
    top=max(p[1] for p in own)
    climb=float(ctx.program.get('climb_deg',8))
    wade=min((float(s['depth_m']) for s in ctx.program.get('sensors') or []
              if s.get('kind')=='water' and s.get('depth_m') is not None),default=WET_M)
    solids=[(lo,hi) for b in ctx.bodies or [] if b.get('name') not in mine
            for lo,hi in part_bounds(b,ctx.cell_m) if hi[1]>=floor-.1 and lo[1]<=top+.1]
    workings=[(d[0],d[1],d[2]/2) for d in (getattr(ctx.routine,'dug_spots',None) or [])]
    survey=_map_cells(ctx,sight);c=sight.cell_m
    def middle(i,j):return (sight.x0_m+(i+.5)*c,sight.z0_m+(j+.5)*c)
    def index(x,z):return (int(math.floor((x-sight.x0_m)/c)),int(math.floor((z-sight.z0_m)/c)))
    start=index(*at);goal_at=index(*target)
    def remaining(i,j):
        x,z=middle(i,j);d=math.hypot(x-target[0],z-target[1])
        return max(arrival[0]-d,0.,d-arrival[1])
    passable={}
    def ok(i,j):
        if (i,j)==start:return True
        if (i,j) in passable:return passable[(i,j)]
        s=survey(i,j);good=s is not None and bool(s.get('on_the_ground'))
        if good:good=float((s.get('water') or {}).get('depth_m') or 0)<=wade
        if good:
            # The same secant over its occupied width as the local window,
            # from the cells either side; a missing neighbour is not graded.
            h=[survey(i+di,j+dj) for di,dj in ((1,0),(-1,0),(0,1),(0,-1))]
            if all(n is not None and 'ground_m' in n for n in h):
                grade=math.degrees(math.atan(math.hypot(float(h[0]['ground_m'])-float(h[1]['ground_m']),
                                                        float(h[2]['ground_m'])-float(h[3]['ground_m']))/(2*c)))
                good=grade<=climb
        if good:
            x,z=middle(i,j)
            for lo,hi in solids:
                if math.hypot(max(lo[0]-x,0,x-hi[0]),max(lo[2]-z,0,z-hi[2]))<radius:good=False;break
        passable[(i,j)]=good;return good
    def cost(i,j):
        s=survey(i,j) or {};k=1.
        if float((s.get('water') or {}).get('depth_m') or 0)>WET_M:k=WADE_COST
        x,z=middle(i,j)
        if any(math.hypot(x-px,z-pz)<radius+half for px,pz,half in workings):k=max(k,WORKING_COST)
        return k
    moves=[(di,dj) for di in (-1,0,1) for dj in (-1,0,1) if di or dj]
    costs={start:0.};parents={};queue=[(remaining(*start),0.,start)];done=None;opened=0
    while queue and opened<MAP_MOST_CELLS:
        _,g,node=heapq.heappop(queue)
        if g!=costs.get(node):continue
        opened+=1
        if remaining(*node)<=c/2 or node==goal_at:done=node;break
        for di,dj in moves:
            nxt=(node[0]+di,node[1]+dj)
            if not ok(*nxt):continue
            if di and dj and (not ok(node[0]+di,node[1]) or not ok(node[0],node[1]+dj)):continue
            score=g+c*math.hypot(di,dj)*cost(*nxt)
            if score>=costs.get(nxt,math.inf):continue
            costs[nxt]=score;parents[nxt]=node
            heapq.heappush(queue,(score+remaining(*nxt),score,nxt))
    if done is None:return None
    cells=[done]
    while cells[-1]!=start:cells.append(parents[cells[-1]])
    return [list(at)]+[list(middle(*n)) for n in reversed(cells[:-1])]


def plan(ctx, target, arrival=(0.,0.)):
    """The next leg toward a place: straight from the local window when the
    place is within it, and otherwise toward the point SUBGOAL_M along a route
    over the shared map, which the local window then plans to."""
    at=ctx.at()
    if math.hypot(target[0]-at[0],target[1]-at[1])-arrival[1]>SUBGOAL_M:
        route=map_route(ctx,target,arrival)
        if route and len(route)>2:
            along=0.;subgoal=None
            for a,b in zip(route,route[1:]):
                along+=math.hypot(b[0]-a[0],b[1]-a[1])
                if along>SUBGOAL_M:break
                subgoal=b
            if subgoal is not None and math.hypot(subgoal[0]-at[0],subgoal[1]-at[1])>WAYPOINT_NEAR_M+.05:
                leg=waypoint(ctx,subgoal,(0.,CELL_M))
                if leg and not leg.get('blocked'):
                    # A point on the way, never the arrival: the routine plans
                    # the next leg from wherever this one ends.
                    leg.update(final=False,near_m=WAYPOINT_NEAR_M,map_route=route[:64])
                    return leg
    return waypoint(ctx,target,arrival)
