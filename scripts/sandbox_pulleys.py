"""Individual wheels and routed, massive native strands; no ratio constraint."""
import copy
import math
import machine_world as mw


def number(label, low, high, default, step=.01):
    return dict(label=label,min=low,max=high,default=default,step=step)


def oriented(fragment,k):
    yaw=k.get('yaw_deg',0);matrix=mw.rotation([0,yaw,0]);origin=[k.get('x_m',0),0,k.get('z_m',0)]
    def point(p):return [origin[i]+sum(matrix[i][j]*(p[j]-origin[j]) for j in range(3)) for i in range(3)]
    for part in fragment.get('parts',[]):
        part['at_m']=point(part['at_m']);part['turn_deg']=mw.turn_of(mw._mat_mul(matrix,mw.rotation(part.get('turn_deg',[0,0,0]))))
    for joint in fragment.get('joints',[]):
        joint['at_m']=point(joint['at_m'])
        if 'axis' in joint:joint['axis']=[sum(matrix[i][j]*joint['axis'][j] for j in range(3)) for i in range(3)]
    for guide in fragment.get('pulleys',[]):guide['heading']=[matrix[i][0] for i in range(3)]
    return fragment


def anchor(name,k,ctx):
    x,z,y=k.get('x_m',0),k.get('z_m',0),k.get('height_m',1.45)
    return oriented({'parts':[dict(name=name,shape='box',material='iron',size_m=[.08,.08,.08],at_m=[x,y,z],fixed=True),
                     dict(name=name+' bracket',shape='box',material='iron',size_m=[.08,.04,.28],at_m=[x,y,z+.12],fixed=True),
                     dict(name=name+' post',shape='box',material='concrete',size_m=[.08,y+.02,.08],at_m=[x,(y+.02)/2,z+.24],fixed=True)]},k)


def pulley(name,k,ctx):
    x,z,y=k.get('x_m',0),k.get('z_m',0),k.get('height_m',1.45)
    r=k.get('radius_m',.12);moving=k.get('mount','fixed')=='moving'
    rotor=name+' wheel'
    # Disjoint cylinders: a hub and its two flanges. The precise compound
    # compiler derives union mass/centroid/inertia from this occupied matter.
    wheel=dict(name=rotor,shape='compound',material='oak',at_m=[x,y,z],fixed=False,parts=[
        dict(shape='cylinder',size_m=[2*r,.04,2*r],at_m=[0,0,0],turn_deg=[90,0,0]),
        dict(shape='cylinder',size_m=[2*(r+.03),.008,2*(r+.03)],at_m=[0,0,-.024],turn_deg=[90,0,0]),
        dict(shape='cylinder',size_m=[2*(r+.03),.008,2*(r+.03)],at_m=[0,0,.024],turn_deg=[90,0,0])])
    if moving:
        carrier=dict(name=name,shape='compound',material='aluminum',at_m=[x,y,z+.10],fixed=False,parts=[
            dict(shape='box',size_m=[.08,2*r+.06,.04],at_m=[0,-.04,0]),
            dict(shape='box',size_m=[.12,.04,.12],at_m=[0,-r-.06,-.04])])
        parts=[carrier,wheel]
    else:
        carrier=dict(name=name,shape='box',material='iron',size_m=[.08,.16,.04],at_m=[x,y,z+.10],fixed=True)
        parts=[carrier,wheel,dict(name=name+' post',shape='box',material='concrete',size_m=[.08,y-.08,.08],at_m=[x,(y-.08)/2,z+.10],fixed=True)]
    joints=[dict(name=name+' axle',kind='hinge',a=name,b=rotor,at_m=[x,y,z],axis=[0,0,1],friction_n_m=.0001)]
    load=k.get('load','')
    if load:
        target=next((p for p in ctx['parts'] if p['name']==load),None)
        if not moving or not target or target['fixed'] or target['shape']=='compound':
            raise ValueError('Choose a moving box for the pulley load')
        top=target['at_m'][1]+target['size_m'][1]/2
        yaw=math.radians(k.get('yaw_deg',0));mount=[x+.04*math.sin(yaw),y-r-.08,z+.04*math.cos(yaw)]
        if abs(mount[1]-top)>.015 or abs(mount[0]-target['at_m'][0])>target['size_m'][0]/2-.02 or abs(mount[2]-target['at_m'][2])>target['size_m'][2]/2:
            raise ValueError('Line up the bottom of the pulley block with the top of the load')
        joints.append(dict(name=name+' load bolt',kind='fix',a=name,b=load,at_m=[x,y-r-.08,z+.04]))
    return oriented(dict(parts=parts,joints=joints,pulleys=[dict(name=rotor,carrier=name,at_m=[x,y,z],radius_m=r,moving=moving)]),k)


def routed_rope(name,k,ctx):
    a,b=k['a'],k['b'];start=list(k['at_m']);end=list(k['at_b_m'])
    bodies={p['name']:p for p in ctx['parts']}
    def attachment(body,key,fallback):
        anchor=k.get(key)
        if anchor is None:return fallback
        if body not in bodies or any(abs(v)>.5001 for v in anchor):raise ValueError('Choose a surface attachment on the body')
        part=bodies[body];axes=mw._axes(part)
        return [part['at_m'][i]+sum(axes[j][i]*anchor[j]*part['size_m'][j] for j in range(3)) for i in range(3)]
    start=attachment(a,'anchor_a',start);end=attachment(b,'anchor_b',end)
    guides={p['name']:p for p in ctx.get('spec',{}).get('pulleys',[])}
    route=[]
    for ref in k.get('via',[]):
        target,_,side=ref.partition(':')
        guide=guides.get(target)
        if not guide:raise ValueError('Route the rope over a pulley wheel')
        route.append((guide,side or ('under' if guide['moving'] else 'over')))
    path=[start]
    for i,(guide,side) in enumerate(route):
        if side not in ('over','under'):raise ValueError('A pulley route passes over or under its wheel')
        center=guide['at_m'];radius=guide['radius_m']+.008
        before=start if i==0 else route[i-1][0]['at_m']
        after=end if i+1==len(route) else route[i+1][0]['at_m']
        heading=guide.get('heading',[1,0,0]);normal=[-heading[2],0,heading[0]]
        left_to_right=sum((after[j]-before[j])*heading[j] for j in range(3))>=0
        begin,finish=(math.pi,0) if left_to_right else (0,math.pi)
        if side=='under':begin,finish=(-math.pi,0) if left_to_right else (0,-math.pi)
        if any(abs(sum((p[j]-center[j])*normal[j] for j in range(3)))>.025 for p in (start,end)):
            raise ValueError('Line up rope ends and pulley wheels on the same plane')
        for step in range(25):
            angle=begin+(finish-begin)*step/24
            point=[center[0]+heading[0]*radius*math.cos(angle),center[1]+radius*math.sin(angle),center[2]+heading[2]*radius*math.cos(angle)]
            if math.dist(path[-1],point)>1e-6:path.append(point)
    if math.dist(path[-1],end)>1e-6:path.append(end)
    if len(path)>64:raise ValueError('Use at most two pulleys in one rope route')
    return dict(strands=[dict(name=name,kind='rope',circuit=0,a_body=a,b_body=b,path_m=path,
        radius_m=.006,density_kg_m3=700,segment_m=.04,retention_n=1000,
        bend_rigidity_n_m2=1e-7,loss_time_s=.002,friction=.5)])


def counterweight(name,k,ctx):
    side=(k.get('mass_kg',8)/7870)**(1/3)
    return oriented({'parts':[dict(name=name,shape='compound',material='iron',parts=[dict(shape='box',size_m=[side]*3,at_m=[0,0,0])],
        at_m=[k.get('x_m',0),k.get('height_m',1),k.get('z_m',0)],fixed=False)]},k)


PIECES={'anchor':anchor,'pulley':pulley,'rope':routed_rope,'counterweight':counterweight}
TRAY=[
    dict(piece='anchor',title='Rope anchor',count=99,cost=0,sandbox_builder=True,turning=False,knobs={
        'x_m':number('Position along (m)',-10,10,0),'z_m':number('Position across (m)',-10,10,0),
        'height_m':number('Anchor height (m)',.3,3,1.45)},primary_knobs=['height_m']),
    dict(piece='pulley',title='Pulley wheel',count=99,cost=0,sandbox_builder=True,turning=False,knobs={
        'x_m':number('Position along (m)',-10,10,0),'z_m':number('Position across (m)',-10,10,0),
        'height_m':number('Axle height (m)',.25,3,1.45),'radius_m':number('Wheel radius (m)',.10,.20,.12),
        'mount':dict(label='Mounting',choices=['fixed','moving'],default='fixed'),
        'load':dict(label='Load',part=True,default='')},primary_knobs=['radius_m','height_m','mount']),
    dict(piece='counterweight',title='Counterweight',count=99,cost=0,sandbox_builder=True,turning=False,knobs={
        'x_m':number('Position along (m)',-10,10,0),'z_m':number('Position across (m)',-10,10,0),
        'height_m':number('Centre height (m)',.1,3,1),'mass_kg':number('Mass (kg)',1,16,8,.5)},primary_knobs=['mass_kg','height_m']),
    dict(piece='rope',title='Rope through pulleys',count=99,cost=0,sandbox_builder=True,attach='rope',turning=False,across=False,knobs={
        'a':dict(part=True,default='',label='First attachment'),'b':dict(part=True,default='',label='Last attachment'),
        'at_m':dict(point=True,default=[0,1,0]),'at_b_m':dict(point=True,default=[1,1,0]),
        'anchor_a':dict(point=True,needed=False,default=None,hidden=True),
        'anchor_b':dict(point=True,needed=False,default=None,hidden=True),
        'via':dict(part_list=True,default=[],label='Pulley route')},primary_knobs=['via'])]
EASY_LEVELS=[]
TEMPLATES=[]
for row in TRAY:
    if row['piece']!='rope':
        row['turns']=['yaw_deg']
        row['knobs']['yaw_deg']=dict(number('Turn (°)',-180,180,0,1),turning=True)


def configure_levels(levels):
    """Keep the published goal/deadline, replace only the apparatus and kit."""
    global LEGACY_TACKLE
    lesson=next(l for l in levels if l['id']=='easy-tackle')
    LEGACY_TACKLE=copy.deepcopy(lesson)
    machine=dict(schema='banjo.machine.v1',cell_m=.02,parts=[
        dict(name='crate',shape='box',material='glass',size_m=[.1]*3,at_m=[-.128,.8,0],fixed=False),
        dict(name='counterweight',shape='box',material='iron',size_m=[.08]*3,at_m=[.128,.8,0],fixed=False)])
    fragment=pulley('guide',dict(height_m=1.6),{})
    for key,value in fragment.items():machine.setdefault(key,[]).extend(value)
    rope=copy.deepcopy(next(t for t in TRAY if t['piece']=='rope'));rope.update(count=1,cost=1)
    levels.append(dict(id='easy-thread',title='Thread a pulley',difficulty='easy',teaches='routing a rope over a wheel',
        brief='Connect the gold ring on the glass crate to the iron counterweight, taking the rope over the pulley wheel. The falling weight pulls the crate up.',
        time_s=2,budget=10,par=2,style_pieces=1,par_energy_j=3030000,machine=machine,tray=[rope],
        goal=dict(title='The crate rises',focus=['crate'],area=dict(at_m=[-.128,1.02,0],size_m=[.2,.02,.2]),
            station=dict(done_when=dict(rose_m=dict(part='crate',m=.15)))),
        solution=[dict(piece='rope',a='crate',b='counterweight',at_m=[-.128,.85,0],at_b_m=[.128,.84,0],via=['guide wheel:over'])],
        wrong=[dict(piece='rope',a='crate',b='counterweight',at_m=[-.128,.85,0],at_b_m=[.128,.84,0],via=['guide wheel:under'])],
        hints=['Start on the crate’s gold ring, tap the wheel, then finish on the counterweight.','An unthreaded rope pulls the boxes together; it cannot redirect the weight upward.']))
    for identity in ('easy-tackle','tackle'):
        level=next(l for l in levels if l['id']==identity)
        crate=next(p for p in level['machine']['parts'] if p['name']=='crate')
        x,y,z=crate['at_m'];top=y+crate['size_m'][1]/2;r=.12;c=r+.008;plane=z-.04
        level['machine']['parts']=[crate]+[p for p in level['machine']['parts'] if p['name']=='crate pedestal']
        height=1.6 if identity=='easy-tackle' else 1.95
        moving_y=top+r+.08;mass=8 if identity=='easy-tackle' else 12
        counter_y=.95 if identity=='easy-tackle' else 1.65
        kit=[copy.deepcopy(t) for t in TRAY]
        for row in kit:
            row.update(count=2 if row['piece']=='pulley' else 1,start_at_defaults=True)
            row['cost']=1 if row['piece'] in ('pulley','rope') else .5
        # Distinct wheels share a tray card; both remain independently editable.
        next(t for t in kit if t['piece']=='pulley')['knobs']['load'].update(default='')
        level['tray']=kit
        if identity=='easy-tackle':level['par_energy_j']=1320000000  # Rebuilt kit, including strand fabrication estimate, rounded up.
        else:level['par_energy_j']=1430000000
        level['solution']=[dict(piece='anchor',x_m=x-c,z_m=plane,height_m=height),
            dict(piece='pulley',x_m=x,z_m=plane,height_m=moving_y,mount='moving',load='crate'),
            dict(piece='pulley',x_m=x+2*c,z_m=plane,height_m=height,radius_m=r,mount='fixed'),
            dict(piece='counterweight',x_m=x+3*c,z_m=plane,height_m=counter_y,mass_kg=mass),
            dict(piece='rope',a='your anchor 1',b='your counterweight 4',at_m=[x-c,height-.04,plane],
                at_b_m=[x+3*c,counter_y+(mass/7870)**(1/3)/2,plane],
                via=['your pulley 2 wheel:under','your pulley 3 wheel:over'])]
        level['wrong']=copy.deepcopy(level['solution'])
        level['wrong'][3]['mass_kg']=2
        level['wrong'][4]['at_b_m'][1]=counter_y+(2/7870)**(1/3)/2
        level['brief']='Build a lift: attach the moving pulley to the crate, place a fixed wheel above it, and route the rope from the anchor under the moving wheel and over the fixed wheel to the counterweight.'
        level['hints']=[level['brief'],'Two lengths of rope support the moving wheel. Its load rises about half as far as the counterweight falls. A heavier counterweight must supply enough gravitational energy.']
        level['goal']['focus']=['crate'];level['goal']['needs']='Place the wheels and counterweight, then thread the rope.'
