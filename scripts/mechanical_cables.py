"""Construction paths only. Runtime cable shapes/forces belong to native Jolt.

Conservative authoring bounds keep a newly manufactured lead outside solids.
The path's arc length determines its copper resistance and mass. It is never
recomputed while the machine runs: moving objects must push the native cable.
"""
import heapq
import math


def length(a, b):
    return math.dist(a, b)


def segment_distance(a,b,c,d):
    def sub(x,y):return [u-v for u,v in zip(x,y)]
    def dot(x,y):return sum(u*v for u,v in zip(x,y))
    def point(p,x,y):
        u=sub(y,x);t=max(0,min(1,dot(sub(p,x),u)/(dot(u,u) or 1)))
        return math.dist(p,[x[i]+t*u[i] for i in range(3)])
    u,v,w=sub(b,a),sub(d,c),sub(a,c)
    aa,bb,ab,aw,bw=dot(u,u),dot(v,v),dot(u,v),dot(u,w),dot(v,w)
    gap=min(point(a,c,d),point(b,c,d),point(c,a,b),point(d,a,b));den=aa*bb-ab*ab
    if den>1e-18:
        s,t=(ab*bw-bb*aw)/den,(aa*bw-ab*aw)/den
        if 0<=s<=1 and 0<=t<=1:gap=min(gap,math.dist([a[i]+s*u[i] for i in range(3)],[c[i]+t*v[i] for i in range(3)]))
    return gap


def clear_stock(path,radius,occupied=()):
    legs=list(zip(path,path[1:]));lengths=[length(a,b) for a,b in legs]
    for i,(a,b) in enumerate(legs):
        gap=0
        for j in range(i+1,len(legs)):
            if gap>2*radius+.001 and segment_distance(a,b,*legs[j])<2*radius+.001:return False
            gap+=lengths[j]
        for old in occupied:
            if any(segment_distance(a,b,c,d)<radius+old['radius_m']+.002 for c,d in zip(old['path_m'],old['path_m'][1:])):return False
    return True


def shape_points(part):
    """World corners using the engine's Rx Ry Rz convention, including kits."""
    def rotate(point,turn):
        x,y,z=point;rx,ry,rz=map(math.radians,turn)
        x,y=math.cos(rz)*x-math.sin(rz)*y,math.sin(rz)*x+math.cos(rz)*y
        x,z=math.cos(ry)*x+math.sin(ry)*z,-math.sin(ry)*x+math.cos(ry)*z
        y,z=math.cos(rx)*y-math.sin(rx)*z,math.sin(rx)*y+math.cos(rx)*z
        return [x,y,z]
    if part.get('parts'):
        local=[point for child in part['parts'] for point in shape_points(child)]
    else:
        size=part['size_m']
        local=[[(1 if mask&(1<<i) else -1)*size[i]/2 for i in range(3)] for mask in range(8)]
    at=part.get('at_m',[0,0,0]);turn=part.get('turn_deg',[0,0,0])
    return [[at[i]+v for i,v in enumerate(rotate(point,turn))] for point in local]


def construction_path(a, b, parts, lane=0, radius=.003,stock_length=None,occupied=(),lift=0,side_shift=0,point_budget=64,route_cache=None):
    # Different leads must not be manufactured on the exact same obstacle
    # corner. The native simulation may bring them back together later.
    clearance=radius+.008+lane*.012
    boxes=[]
    for p in parts:
        points=shape_points(p)
        boxes.append(([min(q[i] for q in points)-clearance for i in range(3)],
                      [max(q[i] for q in points)+clearance for i in range(3)]))
    def inside(p,o):return all(o[0][i]+1e-8<p[i]<o[1][i]-1e-8 for i in range(3))
    def escape(p):
        hits=[o for o in boxes if inside(p,o)]
        if not hits:return list(p)
        options=[]
        for o in hits:
            for i in range(3):
                for side in (0,1):
                    q=list(p);q[i]=o[side][i]
                    blocked=any(segment_distance(p,q,c,d)<radius+old['radius_m']+.002
                        for old in occupied for c,d in zip(old['path_m'],old['path_m'][1:]))
                    if not any(inside(q,z) for z in boxes) and not blocked:options.append(q)
        if not options:raise ValueError('Cable terminal is buried inside overlapping solids')
        return min(options,key=lambda q:length(q,p))
    def intersects(p,q,o):
        lo,hi=0.,1.
        for i in range(3):
            d=q[i]-p[i]
            if abs(d)<1e-12:
                if p[i]<=o[0][i]+1e-8 or p[i]>=o[1][i]-1e-8:return False
            else:
                x,y=sorted(((o[0][i]-p[i])/d,(o[1][i]-p[i])/d))
                lo=max(lo,x);hi=min(hi,y)
                if hi-lo<1e-8:return False
        return hi>1e-8 and lo<1-1e-8
    start,end=escape(a),escape(b)
    def route():
        nodes=[start,end]
        # Separate initial lead lanes; gravity/contact subsequently decide routing.
        top=max(start[1],end[1])+.10+lane*.03+lift
        nodes.extend(([start[0],top,start[2]],[end[0],top,end[2]]))
        for low,high in boxes:
            for mask in range(8):
                q=[(high if mask&(1<<i) else low)[i] for i in range(3)]
                if q[1]>=radius and not any(inside(q,z) for z in boxes):nodes.append(q)
        costs=[math.inf]*len(nodes);costs[0]=0;parents={};heap=[(0,0)]
        while heap:
            cost,i=heapq.heappop(heap)
            if cost!=costs[i]:continue
            if i==1:break
            for j,q in enumerate(nodes):
                trial=cost+length(nodes[i],q)
                if j==i or trial>=costs[j] or any(intersects(nodes[i],q,o) for o in boxes):continue
                if any(segment_distance(nodes[i],q,c,d)<radius+old['radius_m']+.002
                       for old in occupied for c,d in zip(old['path_m'],old['path_m'][1:])):continue
                if trial<costs[j]:costs[j]=trial;parents[j]=i;heapq.heappush(heap,(trial,j))
        if not math.isfinite(costs[1]):raise ValueError('No clear construction route for cable')
        path=[end];i=1
        while i:i=parents[i];path.append(nodes[i])
        return list(reversed(path))
    # Side shifts only change the slack coil, not this visibility graph.
    # Reuse its identical answer within this one fitting operation. Never
    # cache across machines, endpoint edits, lanes or occupied-cord changes.
    if route_cache is None:path=route()
    else:
        if lift not in route_cache:
            try:route_cache[lift]=route()
            except ValueError as exc:route_cache[lift]=str(exc)
        cached=route_cache[lift]
        if isinstance(cached,str):raise ValueError(cached)
        path=cached
    # Add real manufactured slack on clear spans. This adds material, not force.
    roomy=[]
    for p,q in zip(path,path[1:]):
        roomy.append(p)
        if length(p,q)>.02:
            mid=[(p[k]+q[k])/2 for k in range(3)];mid[1]+=.10+lane*.025+lift
            dx,dz=q[0]-p[0],q[2]-p[2];horizontal=math.hypot(dx,dz) or 1
            mid[0]-=dz/horizontal*side_shift;mid[2]+=dx/horizontal*side_shift
            if not any(intersects(p,mid,o) or intersects(mid,q,o) for o in boxes):roomy.append(mid)
    roomy.extend((path[-1],list(b)))
    path=[list(a)]+[p for i,p in enumerate(roomy) if length(p,([list(a)]+roomy)[i])>1e-8]
    if stock_length is None:
        if not clear_stock(path,radius,occupied):raise ValueError('Initial cable route intersects another cord')
        return path
    current=sum(length(p,q) for p,q in zip(path,path[1:]))
    if stock_length<current-1e-6:raise ValueError(f'Cable needs at least {current:.2f} m to reach its terminals')
    if stock_length-current<.001:
        if clear_stock(path,radius,occupied):return path
        raise ValueError('Initial cable route intersects another cord')
    # Wind the chosen stock into a real, initially clear service coil. Its
    # rods, mass, self-contact and later unwinding all belong to Jolt.
    for index in sorted(range(len(path)-1),key=lambda i:-length(path[i],path[i+1])):
        p,q=path[index:index+2]
        for side in (1,-1):
            center=[(p[0]+q[0])/2+side_shift,.02+lift,
                    (p[2]+q[2])/2+side*min(.35+lane*.4,max(.12,(stock_length-current)*.3))]
            for turns in range(1,6):
                def wound(r):
                    coil=[[center[0]+r*math.cos(2*math.pi*k/12),center[1]+.014*k/12,
                           center[2]+r*math.sin(2*math.pi*k/12)] for k in range(12*turns+1)]
                    return path[:index+1]+coil+path[index+1:]
                def span(points):return sum(length(x,y) for x,y in zip(points,points[1:]))
                low,high=.025,.4
                if not span(wound(low))<=stock_length<=span(wound(high)):continue
                for _ in range(35):
                    mid=(low+high)/2
                    if span(wound(mid))<stock_length:low=mid
                    else:high=mid
                candidate=wound((low+high)/2)
                if len(candidate)>point_budget:continue
                inserted=candidate[index:index+12*turns+3]
                if any(intersects(x,y,o) for x,y in zip(inserted,inserted[1:]) for o in boxes):continue
                if not clear_stock(candidate,radius,occupied):continue
                return candidate
    raise ValueError('No clear space for the chosen cable stock; shorten it or separate the devices')


def terminal_layout(w, devices, parts, seats=None):
    terminals={d['name']+':'+k:((d.get('terminal_parts') if isinstance(d.get('terminal_parts'),dict) else {}).get(k,d['part']),at)
               for d in devices for k,at in d['terminals'].items()}
    a,pa=terminals[w['a']];b,pb=terminals[w['b']]
    def seat(key,body,point):
        offset=(seats or {}).get(key,0)
        if not offset or not parts:return point
        # Standard solder pads exit along Z. Space parallel plugs across X,
        # not along their outgoing cord: an inline seat would put the second
        # plug directly through the first cord's straight strain relief.
        axis=0
        return [v+(offset if i==axis else 0) for i,v in enumerate(point)]
    pa,pb=seat('a',a,pa),seat('b',b,pb)
    raw=w.get('mechanical')
    if raw is not None and raw is not True and not isinstance(raw,dict):raise ValueError('mechanical cable settings must be an object')
    settings=dict(raw) if isinstance(raw,dict) else {}
    directions={d['name']+':'+k:v for d in devices for k,v in d.get('terminal_normals',{}).items()}
    for key,point,field in ((w['a'],pa,'exit_a_m'),(w['b'],pb,'exit_b_m')):
        direction=directions.get(key)
        device=next(d for d in devices if d['name']==key.rsplit(':',1)[0])
        if direction is None and device['kind'] in ('battery','bulb','socket','resistor','capacitor','switch'):
            direction=[0,0,1]
        if direction is None and (seats or {}).get('a' if field=='exit_a_m' else 'b'):
            # Parallel plugs leave their shared solder pad in distinct lanes
            # before they bend. Otherwise the first lead can fence in the next
            # socket, despite the pad having enough physical room for both.
            direction=[0,0,1]
        if direction is not None:
            if not isinstance(direction,list) or len(direction)!=3 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in direction) or math.hypot(*direction)==0:
                raise ValueError('terminal normal must be a finite nonzero xyz direction')
            norm=math.hypot(*direction)
            settings.setdefault(field,[point[i]+.1*direction[i]/norm for i in range(3)])
    if any(d['kind']=='motor' and d['name'] in (w['a'].rsplit(':',1)[0],w['b'].rsplit(':',1)[0]) for d in devices):
        settings.setdefault('segment_m',.04)
    return a,pa,b,pb,settings


def prepare(w, devices, parts, lane=0,occupied=(),seats=None):
    a,pa,b,pb,settings=terminal_layout(w,devices,parts,seats)
    return connection(w['name'],a,pa,b,pb,parts,lane,settings,w.get('area_mm2',2.5),w.get('length_m'),occupied)


def connection(name,a,pa,b,pb,parts,lane=0,settings=None,area=2.5,stock_length=None,occupied=()):
    settings=settings or {}
    if settings is True:settings={}
    if not isinstance(settings,dict):raise ValueError('mechanical cable settings must be an object')
    settings=dict(settings);settings.setdefault('segment_m',.08)
    # Locking power plugs have a declared 50 N retention rating. Native pullout
    # still uses the instantaneous solved terminal force; no grace interval.
    settings.setdefault('retention_n',50)
    area=float(area)
    radius=float(settings.get('radius_m',max(.003,math.sqrt(area*settings.get('conductor_count',1)*1e-6/math.pi)+.001)))
    settings['radius_m']=radius
    start,end=settings.get('exit_a_m',pa),settings.get('exit_b_m',pb)
    tails=length(pa,start)+length(pb,end)
    path=settings.get('path_m')
    if not path:
        problem=None
        route_cache={}
        for lift in (0,.03,.08,.15,.3,.5):
            for side_shift in (0,.04,-.04,.1,-.1,.2,-.2,.4,-.4,.7,-.7,1.1,-1.1):
                try:
                    path=construction_path(start,end,parts,lane,radius,
                        None if stock_length is None else stock_length-tails,occupied,lift,side_shift,
                        64-int(length(pa,start)>1e-8)-int(length(pb,end)>1e-8),route_cache)
                    break
                except ValueError as exc:problem=exc
            if path:break
        if not path:raise problem
    if length(pa,path[0])>1e-8:path=[list(pa)]+path
    if length(pb,path[-1])>1e-8:path=path+[list(pb)]
    if len(path)>64:raise ValueError('Cable fitting exceeds the native 64-point construction budget')
    if length(path[0],pa)>1e-6 or length(path[-1],pb)>1e-6:raise ValueError('Cable path must meet its terminals')
    span=sum(length(p,q) for p,q in zip(path,path[1:]))
    area=float(area)
    return dict(settings,name=name,a_body=a,b_body=b,path_m=path,area_mm2=area),span,area


def legacy_leads(circuit,parts,joints,batteries,occupied=()):
    """Explicit physical supply/load/return leads for old circuit declarations."""
    bodies={p['name']:p for p in parts}
    source=next(b['in'] for b in batteries if b['name']==circuit['battery'])
    load=(circuit.get('coil') or {}).get('heats')
    if not load:load=next(j['a'] for j in joints if j['name']==circuit['motor']['hinge'])
    def plug(name,side=0,exit_extra=0):
        p=bodies[name];size=p.get('size_m')
        if not size:
            points=shape_points(p);size=[max(q[i] for q in points)-min(q[i] for q in points) for i in range(3)]
        x,y,z=side*.3*size[0],0,size[2]/2+.004+exit_extra
        rx,ry,rz=map(math.radians,p.get('turn_deg',[0,0,0]))
        x,y=math.cos(rz)*x-math.sin(rz)*y,math.sin(rz)*x+math.cos(rz)*y
        x,z=math.cos(ry)*x+math.sin(ry)*z,-math.sin(ry)*x+math.cos(ry)*z
        y,z=math.cos(rx)*y-math.sin(rx)*z,math.sin(rx)*y+math.cos(rx)*z
        return [p['at_m'][i]+v for i,v in enumerate((x,y,z))]
    touch=(circuit.get('switch') or {}).get('touch')
    if touch:
        fixed=next((n for n in touch if bodies[n]['fixed']),touch[1]);moving=next(n for n in touch if n!=fixed)
        links=[('supply',source,-1,fixed,0,'plus','contact feed'),
               ('switched',moving,0,load,-1,'switched','load feed'),
               ('return',load,1,source,1,'load return','minus')]
    else:
        links=[('supply',source,-1,load,-1,'switched' if 'switch' in circuit else 'plus','load feed'),
               ('return',load,1,source,1,'load return','minus')]
    leads=[]
    for leg,a,sa,b,sb,na,nb in links:
        name=circuit['name']+'/'+leg
        exits=dict(exit_a_m=plug(a,sa,.15),exit_b_m=plug(b,sb,.15))
        physical,span,area=connection(name,a,plug(a,sa),b,plug(b,sb),parts,len(leads),exits)
        # A service loop allows a contact leaf to move without using its
        # supply lead as a mechanical restraint. It is real stock, not a
        # spring-free endpoint exemption or a runtime reroute.
        prior=list(occupied)+[w['mechanical'] for w in leads]
        for extra in (1.,.5,.25,0):
            try:
                physical,span,area=connection(name,a,plug(a,sa),b,plug(b,sb),parts,len(leads),exits,
                    stock_length=span+extra if extra else None,occupied=prior)
                break
            except ValueError:
                if not extra:raise
        leads.append(dict(name=name,leg=leg,a=na,b=nb,mechanical=physical,
                          length_m=span,area_mm2=area,resistance_ohm=.0172*span/area))
    return leads
