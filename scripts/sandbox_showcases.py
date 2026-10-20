"""Editable marble journeys assembled from the existing machine laws.

Stations observe contacts and destinations; they never operate a mechanism.
"""
import copy
import math
from functools import lru_cache

import machine_world as mw
from sandbox_mechanics import box


def empty(title):
    return dict(schema=mw.SCHEMA, title=title, cell_m=.02, parts=[], joints=[], kits=[], stations=[])


def merge(spec, fragment):
    for key in ('parts', 'joints', 'kits', 'batteries', 'spouts', 'airflows','strands','pulleys','solar_panels'):
        spec.setdefault(key, []).extend(copy.deepcopy(fragment.get(key, [])))
    for section in ('electrical','light','thermo'):
        for key,rows in fragment.get(section,{}).items():
            if isinstance(rows,list):spec.setdefault(section,{}).setdefault(key,[]).extend(copy.deepcopy(rows))


def translated(fragment, delta):
    fragment=copy.deepcopy(fragment)
    for key,rows in fragment.items():
        if isinstance(rows,list) and key!='kits':mw.shift_rows(delta,rows)
    for section in ('electrical','light','thermo'):
        for rows in fragment.get(section,{}).values():
            if isinstance(rows,list):mw.shift_rows(delta,rows)
    for row in fragment.get('stations',[]):
        for rule in row.get('done_when',{}).values():
            if isinstance(rule,dict):mw.shift_rows(delta,[rule])
    for device in fragment.get('electrical',{}).get('devices',[]):
        if device.get('terminals'):
            device['terminals']={key:[at[i]+delta[i] for i in range(3)] for key,at in device['terminals'].items()}
        if device.get('handle'):mw.shift_rows(delta,[device['handle']])
    for kit in fragment.get('kits',[]):
        kit['translated_m']=[at+d for at,d in zip(kit.get('translated_m',[0,0,0]),delta)]
    return fragment


def raised(fragment, height):
    return translated(fragment,[0,height,0])


def namespace(fragment, prefix):
    names=set()
    def collect(value):
        if isinstance(value,dict):
            if isinstance(value.get('name'),str):names.add(value['name'])
            for v in value.values():collect(v)
        elif isinstance(value,list):
            for v in value:collect(v)
    collect(fragment);names.discard('traveller')
    def renamed(value):
        if isinstance(value,dict):return {k:renamed(v) for k,v in value.items()}
        if isinstance(value,list):return [renamed(v) for v in value]
        if isinstance(value,str):
            head,sep,tail=value.partition(':')
            if head in names:return prefix+head+(sep+tail if sep else '')
        return value
    return renamed(fragment)


def prepared(value):
    if isinstance(value,dict):return {key:prepared(item) for key,item in value.items()}
    if isinstance(value,list):return [prepared(item) for item in value]
    if isinstance(value,str) and value.startswith('your '):return 'prepared '+value[5:]
    return value


def marble(spec, at, name='traveller', material='glass', diameter=.08):
    spec['parts'].append(dict(name=name, shape='sphere', material=material, size_m=[diameter]*3,
                              at_m=list(at), fixed=False))
    return name


def station(spec, title, rule, focus=()):
    spec['stations'].append(dict(title=title, done_when=rule, focus=list(focus)))


def checkpoint(spec, title, ball, at, size=(.38, .35, .38)):
    station(spec, title, {'in_zone':dict(part=ball, at_m=list(at), size_m=list(size))}, [ball])


class Course:
    def __init__(self, spec, start, heading=0, width=.22, prefix='track', rail_height=.20):
        self.spec, self.at, self.heading, self.width = spec, list(start), heading, width
        self.prefix, self.count, self.rail_height = prefix, 0, rail_height

    def _add(self, parts):
        self.count += 1
        name = f'{self.prefix} {self.count}'
        for i,part in enumerate(parts):
            part['name']=name if not i else name+f' panel {i}'
            if i%3:
                part['size_m'][1]+=self.rail_height-.06
                part['at_m'][1]+=(self.rail_height-.06)/2
            self.spec['parts'].append(part)
        # Uprights terminate at the track's underside, below the marble lane.
        for side in (0,):
            p = parts[0]['at_m']; angle=math.radians(self.heading)
            x,z=p[0]+side*(self.width/2+.06)*math.sin(angle),p[2]+side*(self.width/2+.06)*math.cos(angle)
            height=max(.04,p[1]-.018)
            self.spec['parts'].append(box(name+f' support {side}', [.04,height,.04], [x,height/2,z], 'iron'))
        return name

    def straight(self, length, drop, **more):
        angle=math.radians(self.heading)
        end=[self.at[0]+length*math.cos(angle),self.at[1]-drop,self.at[2]-length*math.sin(angle)]
        kit=dict(top_m=self.at,bottom_m=end,width_m=self.width,material='oak',**more)
        errors=[];parts,joints=mw._kit_ramp(kit,errors,f'{self.prefix} segment')
        if errors or joints:raise ValueError(errors or 'A course segment has no moving joints')
        name=self._add(parts);self.at=end
        return name

    def bend(self, radius=.45, turn=180, drop=.22):
        errors=[]
        parts,_=mw._kit_bend(dict(start_m=self.at,heading_deg=self.heading,turn_deg=turn,
            radius_m=radius,drop_m=drop,width_m=self.width,material='oak'),errors,self.prefix+' corner')
        if errors:raise ValueError(errors)
        name=self._add(parts)
        _,self.at,self.heading=mw.bend_path(self.at,self.heading,turn,radius,drop)
        return name


def catcher(spec, at, name='finish', width=.65, length=.9, heading=0):
    x,y,z=at
    parts=[box(name+' floor',[length,.04,width],[x,y-.02,z]),
        box(name+' far wall',[.04,.30,width+.08],[x+length/2,y+.15,z]),
        *[box(name+f' side {side}',[length,.30,.04],[x,y+.15,z+side*(width/2+.02)]) for side in (-1,1)]]
    if heading:mw.turn_rows(mw.heading(heading,0,0),at,parts)
    spec['parts']+=parts


def switchback():
    import sandbox_motion as motion
    spec=empty('Marble skyscraper')
    course=Course(spec,[-1.5,3.2,.9])
    marble(spec,[-1.38,3.24,.9])
    for i in range(3):
        course.straight(3,.42)
        checkpoint(spec,f'Cross floor {i+1}','traveller',[course.at[0]-.2*math.cos(math.radians(course.heading)),course.at[1]+.06,course.at[2]])
        course.bend(turn=180 if i%2==0 else -180,drop=.24)
    course.width=.45
    course.straight(2.8,.55)
    end=course.at
    door=motion.door('swing door',dict(x_m=.3,z_m=-1.98,width_m=.39,height_m=.25,friction_n_m=.01),{})
    mw.turn_rows(mw.heading(-90,0,0),[.3,0,-1.98],door['parts'],door['joints'])
    merge(spec,raised(door,.99))
    station(spec,'Push through the swinging door',{'turned_deg':{'joint':'swing door hinge','deg':20}},['swing door leaf'])
    catcher(spec,[-1.98,end[1]-.1,end[2]],heading=180,length=1.7)
    for i in range(5):
        spec['parts'].append(box(f'finish domino {i+1}',[.02,.14,.45],[-1.5-i*.1,end[1]-.03,end[2]],'oak',False))
    checkpoint(spec,'Land in the domino tray','traveller',[-1.98,end[1],end[2]],(1.7,.4,.65))
    station(spec,'Topple the last domino',{'hits':['finish domino 4','finish domino 5']},['finish domino 5'])
    return spec


def coaster(spec, start, ball='traveller', heading=0, length=2.4, prefix='coaster', drops=(.30,.17,.32,.15,.12),width=.22,rail_height=.20):
    course=Course(spec,start,heading=heading,prefix=prefix,width=width,rail_height=rail_height)
    course.straight(length,drops[0])
    checkpoint(spec,'Across the upper bridge',ball,[*course.at[:1],course.at[1]+.06,course.at[2]])
    course.bend(radius=.45,turn=180,drop=drops[1])
    course.straight(length-.2,drops[2])
    checkpoint(spec,'Back along the lower bridge',ball,[course.at[0],course.at[1]+.06,course.at[2]])
    course.bend(radius=.45,turn=-90,drop=drops[3])
    course.straight(1.5,drops[4])
    angle=math.radians(course.heading)
    finish=[course.at[0]+.36*math.cos(angle),course.at[1]-.10,course.at[2]-.36*math.sin(angle)]
    catcher(spec,finish,heading=course.heading)
    checkpoint(spec,'Into the finish tray',ball,[finish[0],finish[1]+.12,finish[2]],(.6,.4,.6))
    return course


def waterworks():
    import json
    from pathlib import Path
    import sandbox_water_launch as water
    import sandbox_plumbing as plumbing
    original=json.loads((Path(__file__).resolve().parents[1]/'client/voxel-lab/machine-default.json').read_text())
    spec=empty('Waterworks express')
    spec['ground']=copy.deepcopy(original['ground'])
    spec['ground']['nz']=80
    spec['kits']=copy.deepcopy(original['kits'][:2])
    spec['kits'][0].pop('pour')
    spec['kits'][1]['ball']['name']='traveller'
    for kit in spec['kits']:kit['translated_m']=[0,1.1,0]
    spec['joints']=copy.deepcopy(original['joints'])
    mw.shift_rows([0,1.1,0],spec['joints'])
    tank=water.water_tank('header tank',dict(x_m=-1.7,height_m=2.10,fill_l=8,
        outlet_model='gravity',opening_percent=100),dict(spec=spec))
    merge(spec,tank)
    # The raised wheel's fixed post is bolted to this open scaffold platform.
    spec['parts'].append(box('wheel scaffold',[.65,1.1,.10],[-1.5,.55,.44],'iron'))
    station(spec,'Water turns the wheel',{'turned_deg':dict(joint='water wheel hinge',deg=90)},['water wheel'])
    station(spec,'The drum draws the starting gate',{'slid_m':dict(joint='ramp gate slide',m=.12)},['ramp gate'])
    merge(spec,plumbing.pipe('glass transit tube',dict(x_m=-.35,z_m=0,height_m=1.56,length_m=1.2,
        drop_deg=15,radius_m=.12),dict(spec=spec,parts=spec['parts'])))
    pipe_end=[-.35+1.2*math.cos(math.radians(15)),1.44-1.2*math.sin(math.radians(15)),0]
    checkpoint(spec,'Through the glass transit tube','traveller',[pipe_end[0],pipe_end[1]+.06,0])
    coaster(spec,[pipe_end[0]+.08,pipe_end[1]-.04,0],length=2.2,drops=(.23,.13,.25,.10,.10))
    return spec


def solar_factory():
    import machine_game as mg
    import sandbox_plumbing as plumbing
    import sandbox_mechanics as mechanics
    lesson=mg.level_by_id('easy-charge-lift')
    spec=prepared(mg.compose(lesson,lesson['solution'])[0])
    spec=raised(spec,1.4)
    spec['title']='Solar pinball factory'
    spec['stations']=[]
    spec['parts']=[p for p in spec['parts'] if not p['name'].startswith('charge light')]
    spec['electrical']['devices']=[d for d in spec['electrical']['devices'] if d['name']!='charge light']
    spec['electrical']['wires']=[w for w in spec['electrical']['wires'] if not w['name'].startswith('light ')]
    drive=next(d for d in spec['electrical']['devices'] if d['name']=='drive')
    drive.update(command=1,hinge='carrier gear axle')
    merge(spec,plumbing.scaffold('factory workbench',dict(height_m=1.4,width_m=3,depth_m=1.6),dict(spec=spec,parts=[])))
    marble(spec,[.05,2.275,0])
    spec['parts']=[p for p in spec['parts'] if p['name'] not in ('flag','drive frame')]
    spec['joints']=[j for j in spec['joints'] if j['name']!='drive axle']
    merge(spec,mechanics.gear('carrier gear',dict(height_m=2.2,z_m=.18,material='oak'),{}))
    merge(spec,mechanics.gear('idler gear',dict(height_m=2.2,x_m=.31,z_m=.18,phase_deg=15),{}))
    for post in spec['parts']:
        if post['name'] in ('carrier gear post','idler gear post'):post['at_m'][2]=.32
    carrier=next(p for p in spec['parts'] if p['name']=='carrier gear wheel')
    carrier['parts'] += [dict(shape='box',size_m=[.5,.06,.12],at_m=[.15,0,-.18]),
        dict(shape='box',size_m=[.025,.025,.106],at_m=[0,0,-.07])]
    next(j for j in spec['joints'] if j['name']=='carrier gear axle').update(lower_deg=0,upper_deg=100)
    housing=next(p for p in spec['parts'] if p['name']==drive['part'])
    delta=[0,2.2-housing['at_m'][1],.4-housing['at_m'][2]]
    mw.shift_rows(delta,[housing,drive])
    drive['terminals']={key:[at[i]+delta[i] for i in range(3)] for key,at in drive['terminals'].items()}
    station(spec,'Sun-powered carrier rises',{'turned_deg':{'joint':'carrier gear axle','deg':20}},['carrier gear wheel'])
    station(spec,'The gear teeth pass the turn',{'turned_deg':{'joint':'idler gear axle','deg':30}},['idler gear wheel'])
    start=Course(spec,[-.15,1.8,0],heading=180,width=.4,prefix='factory slide')
    start.straight(1.8,.4)
    checkpoint(spec,'Slide off the powered carrier','traveller',[-1.8,1.52,0],(.6,.4,.45))
    # The powered carrier can feed the first bend at different speeds after
    # cords settle. Real taller sidewalls contain that higher-energy arrival.
    coaster(spec,start.at,heading=180,length=2.1,width=.4,rail_height=.50)
    return spec


def optical_launch():
    import machine_game as mg
    import sandbox_mechanics as mechanics
    import sandbox_pulleys as pulleys
    lesson=mg.level_by_id('laser')
    spec=raised(prepared(mg.compose(lesson,lesson['solution'])[0]),1.4)
    spec['title']='Light the fuse'
    spec['stations']=[]
    spec['parts']=[p for p in spec['parts'] if not p['name'].startswith('bin ')]
    for p in spec['parts']:
        if p['shape']=='box' and p['fixed'] and p['at_m'][1]-p['size_m'][1]/2<=1.401:
            p['size_m'][1]+=1.4;p['at_m'][1]-=.7
    spec['parts'].append(box('weight gantry footing',[.16,1.4,.16],[-.4,.7,1.25]))
    merge(spec,mechanics.lens('focusing lens',dict(x_m=-.65,z_m=0,height_m=1.975,
        radius_m=.5,diameter_m=.12,shape='convex'),dict(spec=spec,tray={})))
    spec['parts'].append(box('lens stand',[.04,1.91,.04],[-.65,.955,0]))
    release=dict(kit='ramp',name='release ramp',top_m=[-1.09,1.65,1.8],
        bottom_m=[.01,1.45,1.8],width_m=.22,rails=False,gate=True,
        ball=dict(name='traveller',material='glass',diameter_m=.08))
    errors=[];parts,joints=mw._kit_ramp(release,errors,'release ramp')
    if errors:raise ValueError(errors)
    next(j for j in joints if j['name']=='release ramp gate slide').update(friction_n=4,axis=[0,0,-1])
    merge(spec,dict(parts=parts,joints=joints))
    spec['parts'].append(box('release ramp support',[.05,1.52,.05],[-.54,.76,1.8],'iron'))
    gate_x=next(p for p in parts if p['name']=='release ramp gate')['at_m'][0]
    for i,(left,right) in enumerate([(-1.09,gate_x-.065),(gate_x+.065,.01)]):
        middle=(left+right)/2;top=1.65-(middle+1.09)*.2/1.1
        for side in (-1,1):spec['parts'].append(box(f'release rail {i} {side}',
            [math.hypot(right-left,(right-left)*.2/1.1),.20,.04],[middle,top+.10,1.8+side*.13],
            'oak',turn_deg=parts[0]['turn_deg']))
    compiled=mw.compile_spec(spec)
    gate=next(p for p in compiled['parts'] if p['name']=='release ramp gate')
    load=next(p for p in compiled['parts'] if p['name']=='weight')
    route=pulleys.routed_rope('gate pull rope',dict(a='weight',b=gate['name'],
        at_m=[load['at_m'][0]-.06,load['at_m'][1],load['at_m'][2]+.06],
        at_b_m=[gate['at_m'][0],gate['at_m'][1],gate['at_m'][2]-gate['size_m'][2]/2]),
        dict(spec=compiled,parts=compiled['parts']))
    merge(spec,route)
    station(spec,'Light releases the hanging weight',{'moved_m':{'part':'weight','m':.12}},['weight'])
    station(spec,'The falling weight draws the gate',{'slid_m':dict(joint='release ramp gate slide',m=.12)},['release ramp gate'])
    bridge=Course(spec,[.01,1.43,1.8],prefix='optical bridge')
    bridge.straight(1.49,.10)
    coaster(spec,bridge.at,length=2.1)
    return spec


def circuit_cascade():
    import sandbox_electrics as electric
    spec=copy.deepcopy(next(t['base'] for t in electric.TEMPLATES if t['name']=='Marble turns on a light'))
    spec['title']='Electric marble relay'
    spec['parts']=[p for p in spec['parts'] if p['name']!='trigger marble' and not p['name'].startswith('control ')]
    spec['joints']=[j for j in spec['joints'] if not j['name'].startswith('control ')]
    spec['electrical']['devices']=[d for d in spec['electrical']['devices'] if d['name']!='control']
    spec=translated(spec,[0,0,-1])
    merge(spec,electric.switch('control',dict(mode='paddle',x_m=-.28,threshold_deg=5,mechanism_version=3),{}))
    spec['stations']=[]
    approach=Course(spec,[-.08,2.5,.9],prefix='switch approach')
    marble(spec,[.04,2.55,.9],name='starter marble',material='iron',diameter=.1)
    approach.straight(2.5,.3)
    checkpoint(spec,'Starter marble crosses the high bridge','starter marble',[2.25,2.3,.9])
    approach.bend(radius=.45,drop=.2)
    approach.straight(2.3,1.25)
    spec['kits']=spec.get('kits',[])+[dict(kit='funnel',name='switch catcher',at_m=[-.18,.65,0],size_m=1.0,hole_m=.14,depth_m=.36)]
    spec['parts'].append(box('switch drop backboard',[.04,1.3,1.1],[-.72,.65,0],'oak'))
    for side in (-1,1):spec['parts'].append(box('funnel foot '+str(side),[.04,.65,.04],[.30,.325,side*.48],'iron'))
    station(spec,'The marble closes the metal contact',dict(load_power_w=dict(device='lamp',at_least_w=2,for_s=.1)),['control paddle','lamp bulb'])
    factory=namespace(translated(solar_factory(),[0,0,2]),'relay ')
    factory['parts']=[p for p in factory['parts'] if not p['name'].startswith('relay prepared solar 1') and p['name']!='relay supply housing']
    factory['batteries']=[];factory['solar_panels']=[];factory.pop('sun',None)
    factory['electrical']['power_cables']=[]
    factory['electrical']['devices']=[d for d in factory['electrical']['devices'] if d['kind']!='battery']
    for wire in factory['electrical']['wires']:
        if wire['a']=='relay supply:plus':wire['a']='buffer:a'
        if wire['b']=='relay supply:minus':wire['b']='supply:minus'
    carrier=next(p for p in factory['parts'] if p['name']=='relay carrier gear wheel')
    next(p for p in carrier['parts'] if p['size_m']==[.5,.06,.12])['size_m'][1]=.04
    # A real shallow cradle retains the waiting ball. The circuit's sharper
    # start needs a lower actuator command, rather than launching the ball
    # out of the course or relying on it to roll away before power arrives.
    carrier['parts'] += [dict(shape='box',size_m=[.5,.06,.015],at_m=[.15,.04,z])
                         for z in (-.24,-.12)]
    carrier['parts'].append(dict(shape='box',size_m=[.025,.025,.15],at_m=[-.10,.0275,-.18]))
    # Counterbalance most of the oak tray, leaving a slight downward preload
    # against its rest stop. This is real mass/inertia on the rotating body.
    carrier['parts'].append(dict(shape='box',size_m=[.12,.14,.15],at_m=[-.16,0,-.04]))
    next(d for d in factory['electrical']['devices'] if d['kind']=='motor')['command']=.6
    for row in factory['stations']:row['title']=row['title'].replace('Sun-powered','Circuit-powered')
    stations=factory.pop('stations')
    merge(spec,factory)
    merge(spec,electric.resistor('charging resistor',dict(x_m=-.7,z_m=-1.45,resistance_ohm=1),{}))
    merge(spec,electric.capacitor('buffer',dict(x_m=-.25,z_m=-1.45,capacitance_f=.2),{}))
    for name,a,b in [('buffer feed','control:out','charging resistor:a'),
                     ('buffer charge','charging resistor:b','buffer:a'),('buffer return','buffer:b','supply:minus')]:
        electric.link(spec,name,a,b)
    spec['stations']+=stations
    return spec


@lru_cache(maxsize=1)
def _templates():
    rows=[
        (switchback,'Four storeys, three hairpins, a swinging door and a domino finale. Follow the marble from the roof to the bottom.',
         ['track','bend','marble','door','dominoes']),
        (waterworks,'A header tank pours onto a water wheel. Its winding drum opens a gate and sends the marble through a glass tube and looping bridges.',
         ['water_tank','water_wheel','pipe','scaffold','track','bend']),
        (solar_factory,'Sunlight charges a battery, a motor turns meshing gears, and a wooden carrier tips the marble onto a long winding course.',
         ['solar','battery','motor','gear','scaffold','track','bend']),
        (optical_launch,'Two mirrors and a lens carry light to an oak cord. It burns, a weight pulls the gate, and the marble races through the bridges.',
         ['mirror','lens','weight','rope','track','bend']),
        (circuit_cascade,'A high marble run ends on a real metal switch. The circuit lights a bulb and charges a capacitor while a motor sends a second marble around the factory.',
         ['marble','switch','battery','bulb','resistor','capacitor','motor','gear','track','bend']),
    ]
    return [dict(name=(base:=build())['title'],description=description,base=base,
                 placements=[],pieces=pieces) for build,description,pieces in rows]


def templates():
    # Gallery requests and player edits must not share mutable declarations.
    rows=copy.deepcopy(_templates())
    for row in rows:row['base']['presentation']={'camera':'overview'}
    return rows
