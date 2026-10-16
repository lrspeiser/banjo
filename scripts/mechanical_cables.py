"""Construction paths only. Runtime cable shapes/forces belong to native Jolt.

Conservative authoring bounds keep a newly manufactured lead outside solids.
The path's arc length determines its copper resistance and mass. It is never
recomputed while the machine runs: moving objects must push the native cable.
"""
import heapq
import math


def length(a, b):
    return math.dist(a, b)


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


def construction_path(a, b, parts, lane=0, radius=.003):
    clearance=radius+.008
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
                    if not any(inside(q,z) for z in boxes):options.append(q)
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
    nodes=[start,end]
    # Separate initial lead lanes; gravity/contact subsequently decide routing.
    top=max(start[1],end[1])+.10+lane*.03
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
            if j==i or any(intersects(nodes[i],q,o) for o in boxes):continue
            trial=cost+length(nodes[i],q)
            if trial<costs[j]:costs[j]=trial;parents[j]=i;heapq.heappush(heap,(trial,j))
    if not math.isfinite(costs[1]):raise ValueError('No clear construction route for cable')
    path=[end];i=1
    while i:i=parents[i];path.append(nodes[i])
    path=list(reversed(path))
    # Add real manufactured slack on clear spans. This adds material, not force.
    roomy=[]
    for p,q in zip(path,path[1:]):
        roomy.append(p)
        if length(p,q)>.02:
            mid=[(p[k]+q[k])/2 for k in range(3)];mid[1]+=.10+lane*.025
            if not any(intersects(p,mid,o) or intersects(mid,q,o) for o in boxes):roomy.append(mid)
    roomy.extend((path[-1],list(b)))
    return [list(a)]+[p for i,p in enumerate(roomy) if length(p,([list(a)]+roomy)[i])>1e-8]


def prepare(w, devices, parts, lane=0):
    terminals={d['name']+':'+k:(d.get('terminal_parts',{}).get(k,d['part']),at)
               for d in devices for k,at in d['terminals'].items()}
    a,pa=terminals[w['a']];b,pb=terminals[w['b']]
    settings=w.get('mechanical',{})
    if settings is True:settings={}
    if not isinstance(settings,dict):raise ValueError('mechanical cable settings must be an object')
    radius=float(settings.get('radius_m',.003))
    path=settings.get('path_m') or construction_path(pa,pb,parts,lane,radius)
    if length(path[0],pa)>1e-6 or length(path[-1],pb)>1e-6:raise ValueError('Cable path must meet its terminals')
    span=sum(length(p,q) for p,q in zip(path,path[1:]))
    # The first physical pack upgrades motor leads. Old schematic saved wires
    # elsewhere retain their declared electrical law until separately migrated.
    area=float(w.get('area_mm2',2.5))
    return dict(settings,name=w['name'],a_body=a,b_body=b,path_m=path,area_mm2=area),span,area
