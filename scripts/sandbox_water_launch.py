"""Independent fixed gravity reservoirs, water wheels and a cradle launcher.

Water cards require the explicit channel base. No moving liquid containment
or scripted launches: the cradle pushes the projectile through rigid contact.
"""
import copy
import math
import machine_world as mw


def knob(lo, hi, step, default, label):
    return dict(min=lo, max=hi, step=step, default=default, label=label)


TRAY = [
    dict(piece='water_wheel', count=99, cost=0, turns=[], knobs={
        'x_m': knob(-1.5, 1.5, .02, 0, 'along channel (m)'),
        'z_m': knob(-1, 1, .02, 0, 'across river (m)'),
        'radius_m': knob(.25, .65, .05, .4, 'wheel radius (m)'),
        'side': dict(choices=['left', 'right', 'off'], default='left', label='pour onto'),
        'load_part': dict(default='',part=True,label='drum load (optional)'),
        'discharge_l_s': knob(.5, 3, .5, 2, 'external supply (L/s)')}),
    dict(piece='water_tank', count=99, cost=0, across=False, turns=[], knobs={
        'x_m': knob(-1.5, 1.5, .02, 0, 'outlet along channel (m)'),
        'height_m': knob(.5, 1.4, .1, 1.1, 'fixed outlet height (m)'),
        'fill_l': knob(0, 8, .5, 4, 'initial water (L)'),
        'discharge_l_s': knob(.5, 3, .5, 2, 'metered outlet (L/s)'),
        'valve': dict(choices=['closed', 'open'], default='open', label='valve')}),
    dict(piece='catapult', count=99, cost=0, turns=['yaw_deg'], knobs={
        'x_m': knob(-1.5, 1.5, .02, 0, 'position (m)'),
        'yaw_deg': dict(knob(-180,180,5,0,'aim'),turning=True,free=True),
        'cock_deg': knob(20, 40, 1, 30, 'cocked angle'),
        'counterweight_m': knob(.10, .16, .01, .14, 'iron counterweight side (m)'),
        'counterweight_material': dict(choices=['iron','glass','oak'],default='iron',label='counterweight material'),
        'projectile_material': dict(choices=['oak', 'glass', 'iron'], default='oak', label='marble material'),
        'diameter_m': knob(.06,.10,.01,.08,'marble diameter (m)'),
        'loaded': dict(choices=['loaded','empty'],default='loaded',label='cradle'),
        'release': dict(choices=['held', 'released'], default='released', label='arm restraint')})]


CHANNEL_BASE = dict(schema=mw.SCHEMA, title='Dry collection channel', ground=dict(
    kind='flume', nx=60, nz=40, cell_m=.1, trench_z_m=0, trench_width_m=.6,
    trench_depth_m=.35, trench_slope=.005, discharge_m3_s=0), parts=[])
DRY_BASE = dict(schema=mw.SCHEMA, title='Launcher workbench', parts=[])


def _box(name, at, size, material='oak', fixed=False, **extra):
    return dict(name=name, shape='box', material=material, at_m=at, size_m=size, fixed=fixed, **extra)


def water_wheel(name, k, ctx):
    if not (ctx.get('spec', {}).get('ground') or {}).get('kind') == 'flume':
        raise ValueError('A water wheel needs the collection channel base. Open its example to create one.')
    side = k.get('side', 'left')
    r = float(k.get('radius_m', .4))
    ground=mw.compile_ground(ctx['spec']['ground'],[])
    x,z=k.get('x_m',0),ground['trench_z_m']+k.get('z_m',0)
    bed=mw.ground_height(ground,x,z)
    # A smaller wheel needs a higher clearance over the bed to keep its axle
    # out of the solid bank. Derive it from geometry, never clip its collider.
    clearance=max(.065,.055-bed-r)
    hub=bed+clearance+r
    fragment = dict(kits=[dict(kit='water_wheel', name=name, at_m=[k.get('x_m',0),0,0],
        radius_m=r, across_m=k.get('z_m',0), clearance_m=clearance,paddle_width_m=.36, friction_n_m=.2,
        pour=dict(side='-x' if side == 'left' else '+x', offset_m=r*.5,
                  discharge_l_s=k.get('discharge_l_s',2), until_s=6))]) if side != 'off' else dict(kits=[dict(
        kit='water_wheel', name=name, at_m=[k.get('x_m',0),0,0], radius_m=r,
        across_m=k.get('z_m',0), clearance_m=clearance,paddle_width_m=.36, friction_n_m=.2)])
    if side != 'off':
        sx=x+(-1 if side=='left' else 1)*r*.5
        mouth=hub+r+.5
        bank=ground['trench_width_m']*.5+.45
        cell=ctx['spec'].get('cell_m',.02)
        support=math.ceil((mouth+.13-.004)/cell)*cell
        fragment['parts']=[_box(name+' feed support',[sx,support*.5,z+bank],[.06,support,.06],'concrete',True),
            _box(name+' feed bridge',[sx,mouth+.15,z+bank*.5],[.06,.04,bank+.06],'iron',True)]
    if k.get('load_part'):
        selected = next((p for p in ctx['parts'] if p['name']==k['load_part']),None)
        if not selected: raise ValueError('Choose an existing part as the drum load')
        point=list(selected['at_m'])
        if selected['shape']=='box':point[1] += selected['size_m'][1]*.5
        fragment['joints'] = [dict(name=name+' load drum',kind='drum',drum=name,load=k['load_part'],
            centre_m=[k.get('x_m',0),hub,z+.45],axis=[0,0,1],radius_m=.04,
            load_point_m=point,winds=1,spare_m=0)]
    return fragment


def water_tank(name, k, ctx):
    g = ctx.get('spec', {}).get('ground') or {}
    if g.get('kind') != 'flume':
        raise ValueError('A fixed water tank needs the collection channel base. Open its example to create one.')
    x, z, y = k.get('x_m',0), g.get('trench_z_m',0)+k.get('z_m',0), k.get('height_m',1.1)
    # The tank is above the bank. Its indicated fixed outlet lies over the
    # collection channel. Saved legacy tanks retain their metered outlet.
    channel_z=g.get('trench_z_m',0)
    bank = channel_z + .5*g.get('trench_width_m',.6) + .22
    # Keep the outlet clear of the vessel when moved across the channel.
    # A source too near its own wall catches newly emitted finite parcels.
    if abs(bank-z) < .32:bank=z+.4
    tank = dict(name=name+' tank',shape='compound',material='iron',at_m=[x,y+.12,bank],fixed=True,
        parts=[dict(shape='box',at_m=[0,-.11,0],size_m=[.28,.02,.28],turn_deg=[0,0,0]),
               dict(shape='box',at_m=[-.13,0,0],size_m=[.02,.24,.28],turn_deg=[0,0,0]),
               dict(shape='box',at_m=[.13,0,0],size_m=[.02,.24,.28],turn_deg=[0,0,0]),
               dict(shape='box',at_m=[0,0,-.13],size_m=[.24,.24,.02],turn_deg=[0,0,0]),
               dict(shape='box',at_m=[0,0,.13],size_m=[.24,.24,.02],turn_deg=[0,0,0])])
    parts = [_box(name+' frame',[x,y*.5,bank],[.08,y,.08],'concrete',True),
             tank,
             _box(name+' outlet',[x,y+.06,z],[.06,.10,.06],'iron',True),
             _box(name+' feed bridge',[x,y+.13,(z+bank)*.5],[.06,.04,abs(bank-z)+.12],'iron',True)]
    source=dict(name=name+' outlet', at_m=[x,y,z], direction=[0,-1,0],
        speed_m_s=0, discharge_l_s=k.get('discharge_l_s',2), initial_volume_l=k.get('fill_l',4),
        valve_open=k.get('valve','open')=='open',receiver_bounds_m=[
            -.5*(g.get('nx',60)-1)*g.get('cell_m',.1),.5*(g.get('nx',60)-1)*g.get('cell_m',.1),
            channel_z-.5*g.get('trench_width_m',.6),channel_z+.5*g.get('trench_width_m',.6)])
    if k.get('outlet_model','metered')=='gravity':
        # A thin, transparent fixed vessel lets the native remaining-volume
        # surface be seen. Precise compound parts keep their actual mass.
        tank['material']='glass'
        tank['parts']=[dict(shape='box',at_m=[0,-.1175,0],size_m=[.25,.005,.25],turn_deg=[0,0,0]),
            dict(shape='box',at_m=[-.1225,0,0],size_m=[.005,.24,.25],turn_deg=[0,0,0]),
            dict(shape='box',at_m=[.1225,0,0],size_m=[.005,.24,.25],turn_deg=[0,0,0]),
            dict(shape='box',at_m=[0,0,-.1225],size_m=[.24,.24,.005],turn_deg=[0,0,0]),
            dict(shape='box',at_m=[0,0,.1225],size_m=[.24,.24,.005],turn_deg=[0,0,0])]
        source.update(discharge_l_s=0,reservoir_area_m2=.24*.24,outlet_area_m2=math.pi*.025**2,
            head_offset_m=.005,contraction_coefficient=.62,opening_fraction=k.get('opening_percent',0)/100,
            reservoir_floor_m=[x,y+.005,bank])
        parts.append(dict(name=name+' tap',shape='compound',material='iron',fixed=True,at_m=[x,y+.19,z],
            turn_deg=[0,k.get('opening_percent',0)*.9,0],parts=[
                dict(shape='cylinder',at_m=[0,0,0],size_m=[.05,.02,.05],turn_deg=[0,0,0]),
                dict(shape='box',at_m=[0,.02,0],size_m=[.10,.02,.02],turn_deg=[0,0,0])]))
    return dict(parts=parts,spouts=[source])


def catapult(name, k, ctx):
    x, z, y = float(k.get('x_m',0)), float(k.get('z_m',0)), .85
    angle = -math.radians(float(k.get('cock_deg',30)))
    c,s = math.cos(angle),math.sin(angle)
    def world(u,v,w=0): return [x+c*u-s*v,y+s*u+c*v,z+w]
    def sub(at,size): return dict(shape='box',size_m=size,at_m=at,turn_deg=[0,0,0])
    weight = float(k.get('counterweight_m',.14))
    diameter = float(k.get('diameter_m',.08))
    # Joined wood and iron keep their own densities: weight is a separate
    # real body fixed to the arm, rather than an overridden arm mass.
    arm_parts=[sub([.25,0,0],[1.10,.04,.10]),
               sub([.79,.065,0],[.04,.09,.18]),
               sub([.68,.05,-.07],[.18,.08,.04]),
               sub([.68,.05,.07],[.18,.08,.04])]
    parts=[_box(name+' stand',[x,y*.5,z-.18],[.12,y,.12],'concrete',True),
           dict(name=name+' arm',shape='compound',material='oak',at_m=[x,y,z],
                turn_deg=[0,0,math.degrees(angle)],fixed=False,parts=arm_parts),
           _box(name+' counterweight',world(-.25,-.04-weight*.5),[weight]*3,k.get('counterweight_material','iron'),False,turn_deg=[0,0,math.degrees(angle)])]
    if k.get('loaded','loaded')=='loaded':
        parts.append(dict(name=name+' marble',shape='sphere',material=k.get('projectile_material','oak'),
                     at_m=world(.67,.026+diameter*.5),size_m=[diameter]*3,fixed=False))
    joints=[dict(name=name+' axle',kind='hinge',a=name+' stand',b=name+' arm',
                 at_m=[x,y,z],axis=[0,0,1],lower_deg=-180,upper_deg=110,friction_n_m=.04),
            dict(name=name+' weight fastening',kind='fix',a=name+' arm',b=name+' counterweight',
                 at_m=world(-.25,-.03),axis=[0,1,0])]
    if k.get('release','released') == 'held':
        joints.append(dict(name=name+' restraint',kind='fix',a=name+' stand',b=name+' arm',
                           at_m=[x,y,z],axis=[0,0,1]))
    if k.get('yaw_deg',0):
        mw.turn_rows(mw.heading(k['yaw_deg'],0,0),[x,y,z],parts,joints)
    return dict(parts=parts,joints=joints)


PIECES = dict(water_wheel=water_wheel, water_tank=water_tank, catapult=catapult)
TEMPLATES = [
    dict(id='water-wheel',name='Water turns a wheel',description='An external metered pour drives a supported wheel in a dry channel. Compare left, right and off.',
         base=copy.deepcopy(CHANNEL_BASE),placements=[dict(piece='water_wheel')]),
    dict(id='finite-water',name='A tank that runs dry',description='Four litres in a fixed metered source. Close its valve or change its starting fill; remaining water is measured.',
         base=copy.deepcopy(CHANNEL_BASE),placements=[dict(piece='water_tank')]),
    dict(id='cradle-catapult',name='Counterweight cradle launcher',description='A real raised iron weight turns the wooden arm. Compare held and released; the cradle contacts the marble.',
         base=copy.deepcopy(DRY_BASE),placements=[dict(piece='catapult')])]
def easy_level(ident,title,brief,base,piece,solution,rule,seconds=6):
    tray = copy.deepcopy(next(t for t in TRAY if t['piece']==piece))
    tray['count']=1
    tray['sandbox_builder']=True
    return dict(id=ident,title=title,teaches=piece,brief=brief,machine=copy.deepcopy(base),
        goal=dict(title=title,station=dict(title=title,done_when=rule)),tray=[tray],
        solution=[dict(piece=piece,**solution)],time_s=seconds,budget=1000000,par=1000000,
        style_pieces=1,difficulty='easy',hints=[brief],turning=False)


CATCH_BASE = copy.deepcopy(DRY_BASE)
CATCH_BASE['parts']=[
    _box('receiving bin floor',[-2,.03,0],[2,.06,.7],'concrete',True),
    _box('receiving bin back',[-3.04,.22,0],[.08,.44,.86],'concrete',True),
    _box('receiving bin left',[-2,.17,-.39],[2,.34,.08],'concrete',True),
    _box('receiving bin right',[-2,.17,.39],[2,.34,.08],'concrete',True)]
TEMPLATES[2]['base']=copy.deepcopy(CATCH_BASE)

GATE_BASE=copy.deepcopy(CHANNEL_BASE)
GATE_BASE['ground']['trench_depth_m']=.1
GATE_BASE['parts'] += [
    _box('water gate guide',[.16,.30,.45],[.08,.6,.08],'concrete',True),
    _box('water gate',[0,.12,.45],[.10,.16,.08],'oak'),
    _box('gate foot',[0,.02,.45],[.14,.04,.14],'concrete',True)]
GATE_BASE['joints']=[dict(name='water gate slide',kind='slide',a='water gate guide',b='water gate',
    at_m=[0,.12,.45],axis=[0,1,0],lower_m=0,upper_m=.14,friction_n=0)]
TEMPLATES.append(dict(id='water-opens-gate',name='Water opens a gate',description='The supported wheel winds a real drum rope and lifts a guided gate. No timed gate animation.',
    base=copy.deepcopy(GATE_BASE),placements=[dict(piece='water_wheel',load_part='water gate')]))

EASY_LEVELS = [
    easy_level('easy-water-wheel','6. Pour onto the paddles','Add a wheel in the channel and pour onto its left paddles. Water that misses cannot turn it.',
        CHANNEL_BASE,'water_wheel',dict(side='left'),{'turned_deg':{'joint':'your water_wheel 1 hinge','deg':30}}),
    easy_level('easy-water-receiver','15. Fill the receiver','Add a finite fixed tank with four litres and open its metered outlet. At least three litres must actually reach the channel.',
        CHANNEL_BASE,'water_tank',dict(fill_l=4,valve='open'),{'water_received_l':{'spout':'your water_tank 1 outlet','l':3}}),
    easy_level('easy-catapult','17. Gentle first launch','Release the raised counterweight so the cradle throws its oak marble into the wide receiving bin.',
        CATCH_BASE,'catapult',dict(counterweight_m=.14,release='released'),{'in_zone':{'part':'your catapult 1 marble','at_m':[-2,.23,0],'size_m':[1.9,.34,.65]}},3),
    easy_level('easy-water-gate','19. Water opens a gate','Pour on the wheel. Its drum rope must lift the guided gate eight centimetres.',
        GATE_BASE,'water_wheel',dict(side='left',load_part='water gate'),{'rose_m':{'part':'water gate','m':.08}},8)]

for level,par in zip(EASY_LEVELS,(768558050,1679769200,614548521,776455970)):
    level['par_energy_j']=par+1000
    level['wrong']=[dict(level['solution'][0], **(
        {'side':'off'} if level['tray'][0]['piece']=='water_wheel' else
        {'valve':'closed'} if level['tray'][0]['piece']=='water_tank' else {'yaw_deg':90}))]

TEMPLATES.append(dict(id='finite-tank-wheel',name='One tank, one wheel',
    description='A finite four-litre source drives the wheel and runs dry. This uses a metered outlet, with conserved parcel volume.',
    base=copy.deepcopy(CHANNEL_BASE),placements=[dict(piece='water_wheel',side='off'),
        dict(piece='water_tank',x_m=-.2,height_m=1.1,fill_l=4,valve='open')]))

# Boundary inflow supplies a real current along the channel; there is no
# falling spout. The larger wheel puts its axle above the load's attachment.
RIVER_BASE=copy.deepcopy(CHANNEL_BASE)
RIVER_BASE['title']='River workbench'
RIVER_BASE['ground']['discharge_m3_s']=.1
RIVER_BASE['parts'] += [
    _box('river gate guide',[-.09,.30,.45],[.08,.6,.08],'concrete',True),
    _box('river gate',[-.25,.12,.45],[.10,.16,.08],'oak'),
    _box('river gate foot',[-.25,.02,.45],[.14,.04,.14],'concrete',True)]
RIVER_BASE['joints']=[dict(name='river gate slide',kind='slide',a='river gate guide',b='river gate',
    at_m=[-.25,.12,.45],axis=[0,1,0],lower_m=0,upper_m=.14,friction_n=0)]
RIVER_SOLUTION=dict(piece='water_wheel',x_m=0,z_m=0,radius_m=.65,side='off',load_part='river gate')
TEMPLATES.append(dict(id='river-lift',name='River powers a lift',
    description='The river current pushes immersed paddles. Its axle winds a rope to lift the gate; no falling-water supply.',
    base=copy.deepcopy(RIVER_BASE),placements=[copy.deepcopy(RIVER_SOLUTION)]))
TEMPLATES.append(dict(id='river-workbench',name='Build beside a river',
    description='Add a water wheel in the current, then connect its drum load to the river gate. The flow enters upstream and leaves downstream.',
    base=copy.deepcopy(RIVER_BASE),placements=[]))
river_lesson=easy_level('easy-river-lift','21. River-powered lift',
    'Place a wheel in the river current. Its axle must wind the rope and raise the gate eight centimetres.',
    RIVER_BASE,'water_wheel',{k:v for k,v in RIVER_SOLUTION.items() if k!='piece'},
    {'rose_m':{'part':'river gate','m':.08}},10)
river_lesson['tray'][0]['knobs']['radius_m']['default']=.65
river_lesson['tray'][0]['knobs']['side']['default']='off'
river_lesson['tray'][0]['knobs']['load_part']['default']='river gate'
river_lesson['par_energy_j']=593992292  # Measured nominal piece construction plus 1 kJ margin.
river_lesson['wrong']=[dict(RIVER_SOLUTION,z_m=1)]
EASY_LEVELS.append(river_lesson)

# Keep the exact earlier recipes available for shared version-1 IDs.
LEGACY_LEVELS={level['id']:copy.deepcopy(level) for level in EASY_LEVELS}
_river_lift = next(row for row in EASY_LEVELS if row['id']=='easy-river-lift')
_river_lift['tray'][0].update(start_at_defaults=True, frame_on_add=True)
_river_lift['tray'][0]['knobs']['z_m']['default']=1
_river_lift['tray'][0]['knobs']['load_part']['default']=''
_river_lift['brief']='Move the wheel off the bank into the current, then connect its drum load to river gate. The current must raise the gate eight centimetres.'
_river_lift['hints'][0]=_river_lift['brief']
_river_lift['tray'][0]['knobs']['radius_m']['hidden']=True
_river_lift['tray'][0]['knobs']['load_part'].update(label='rope to gate',connection_target='river gate',connection_label='gate')
_river_lift['tray'][0]['focus_knob']='load_part'
_river_lift['goal']['title']='Lift the gate 8 cm'
_river_lift['goal']['area']=dict(at_m=[0,.002,0],size_m=[1.4,.02,.6],label='Put the lower paddles in this current')
LEGACY_TRAY=copy.deepcopy(TRAY)
TRAY[0]['knobs']['side']['default']='off'
TRAY[0]['knobs']['side']['label']='legacy attached feed'
TRAY[1]['across']=True
TRAY[1]['focus_knob']='opening_percent'
TRAY[1]['knobs'].update(z_m=knob(-1,1,.02,0,'outlet across channel (m)'),
    outlet_model=dict(choices=['gravity','metered'],default='gravity',label='outlet model'),
    opening_percent=knob(0,100,1,0,'tap opening (%)'))

def modular_pour_lesson(base,ident,title,brief,rule,seconds):
    wheel=copy.deepcopy(TRAY[0]);tank=copy.deepcopy(TRAY[1])
    for row in (wheel,tank):row.update(count=1,sandbox_builder=True,start_at_defaults=True)
    wheel['knobs']['side']['choices']=['off']
    wheel['knobs']['side']['default']='off'
    wheel['knobs']['z_m']['default']=0
    tank['knobs']['x_m']['default']=-.2
    tank['frame_on_add']=True
    solution=[dict(piece='water_wheel',side='off',load_part='water gate' if ident=='easy-water-gate' else ''),
              dict(piece='water_tank',x_m=-.2,z_m=0,height_m=1.1,fill_l=4,outlet_model='gravity',opening_percent=75)]
    return dict(id=ident,title=title,teaches='water flow and paddle contact',brief=brief,machine=copy.deepcopy(base),
        goal=dict(title=title,needs='Place a water wheel, then aim a separate tank at its paddles.',roles={'wheel':'water_wheel'},station=dict(done_when=rule)),
        tray=[wheel,tank],solution=solution,wrong=[solution[0],dict(solution[1],opening_percent=0)],
        time_s=seconds,budget=1000000,par=1000000,par_energy_j=771262154 if ident=='easy-water-wheel' else 777190154,style_pieces=2,difficulty='easy',
        hints=[brief,'The wheel has no built-in water supply. Water must hit its paddles.'],turning=False)

EASY_LEVELS[0]=modular_pour_lesson(CHANNEL_BASE,'easy-water-wheel','Pour onto the paddles',
    'Place a wheel and a separate tank. Increase the tap opening and aim its outlet onto the wheel’s left paddles.',
    {'turned_deg':{'joint':'@wheel hinge','deg':30}},6)
EASY_LEVELS[3]=modular_pour_lesson(GATE_BASE,'easy-water-gate','Water opens a gate',
    'Aim a separate tank at the wheel and open its tap. Connect the wheel’s drum load to water gate to lift it eight centimetres.',
    {'rose_m':{'part':'water gate','m':.08}},8)
EASY_LEVELS[3]['tray'][0]['knobs']['load_part']['default']=''

river_base=copy.deepcopy(CHANNEL_BASE);river_base['title']='Wheel in a river'
river_base['ground']['discharge_m3_s']=.1
river_wheel=easy_level('easy-river-wheel','Wheel in the river',
    'The wheel starts on the bank. Move its lower paddles into the river current to turn its axle thirty degrees.',
    river_base,'water_wheel',dict(radius_m=.65,side='off',x_m=0,z_m=0),
    {'turned_deg':{'joint':'your water_wheel 1 hinge','deg':30}},10)
river_wheel['tray'][0].update(start_at_defaults=True)
river_wheel['tray'][0]['frame_on_add']=True
river_wheel['tray'][0]['knobs']['radius_m']['default']=.65
river_wheel['tray'][0]['knobs']['z_m']['default']=1
river_wheel['tray'][0]['knobs']['side'].update(default='off',choices=['off'])
river_wheel['wrong']=[dict(river_wheel['solution'][0],z_m=1)]
river_wheel['par_energy_j']=593992292
EASY_LEVELS.append(river_wheel)
TEMPLATES.append(dict(id='river-wheel',name='Wheel in the river',
    description='Only river current drives this wheel. Move it onto the bank to compare; no tank or attached feed.',
    base=copy.deepcopy(river_base),placements=copy.deepcopy(river_wheel['solution'])))

receiver=easy_level('easy-water-receiver','Fill the receiver',
    'Place a separate tank over the collection channel and increase its tap opening. Three litres must actually reach the channel.',
    CHANNEL_BASE,'water_tank',dict(fill_l=4,outlet_model='gravity',opening_percent=75),
    {'water_received_l':{'spout':'your water_tank 1 outlet','l':3}})
receiver['tray'][0].update(start_at_defaults=True)
receiver['tray'][0]['frame_on_add']=True
receiver['par_energy_j']=460651224
receiver['wrong']=[dict(receiver['solution'][0],opening_percent=0)]
EASY_LEVELS[1]=receiver

# New examples use independent components; old explicitly saved feeds remain
# supported by the same generic wheel/pour builder.
for example in TEMPLATES:
    if example['id'] in ('water-wheel','water-opens-gate','finite-tank-wheel'):
        load='water gate' if example['id']=='water-opens-gate' else ''
        example['placements']=[dict(piece='water_wheel',side='off',load_part=load),
            dict(piece='water_tank',x_m=-.2,z_m=0,outlet_model='gravity',opening_percent=75)]
        example['description']='A separate finite tank feeds the wheel. Change its tap opening or move the outlet; only water hitting paddles turns the axle.'
    if example['id']=='finite-water':
        example['placements']=[dict(piece='water_tank',outlet_model='gravity',opening_percent=100)]
        example['description']='A separate four-litre gravity tank. Widen the tap to pour faster; falling head slows the flow as it drains.'

LEGACY_MODULAR_LEVELS={row['id']:copy.deepcopy(row) for row in EASY_LEVELS}
_pour=EASY_LEVELS[0]
_target=water_wheel('wheel target',dict(side='off'),dict(spec=_pour['machine']))
for key,value in _target.items():_pour['machine'].setdefault(key,[]).extend(value)
_pour['tray']=[_pour['tray'][1]]
_pour['solution']=[_pour['solution'][1]]
_pour['wrong']=[dict(_pour['solution'][0],opening_percent=0)]
_pour['goal'].pop('roles',None)
_pour['goal'].update(needs='Place a tank and aim its outlet at the waiting wheel.',focus=['wheel target'])
_pour['goal']['station']['done_when']={'turned_deg':{'joint':'wheel target hinge','deg':30}}
_pour['style_pieces']=1
_pour['par_energy_j']=460651224
_pour['brief']='A wheel is waiting in the dry channel. Place a separate tank, increase the tap opening and aim the pour at its left paddles.'
_pour['hints'][0]=_pour['brief']

for _row in (receiver,river_wheel):
    _g=_row['machine']['ground']
    _row['goal']['area']={
        'at_m':[0,.002,_g.get('trench_z_m',0)],
        'size_m':[(_g['nx']-1)*_g['cell_m'],.02,_g['trench_width_m']],
        'label':'Collect 3 L here' if _row['id']=='easy-water-receiver' else 'Put the paddles in this current'}


# Routing uses the ordinary falling-parcel contacts, not a chute-specific law.
# Precise compound bodies are mounted to grounded stands with real fix joints.
def _routing_bed(ctx,x,z):
    ground=ctx.get('spec',{}).get('ground') or {}
    if abs(z-ground.get('trench_z_m',0))>ground.get('trench_width_m',.6)/2:return 0
    x0=-(ground.get('nx',60)-1)*ground.get('cell_m',.1)/2
    bed=-ground.get('trench_depth_m',.35)-ground.get('trench_slope',.005)*(x-x0-.02)
    return math.ceil(bed/.02)*.02


def water_chute(name,k,ctx):
    if (ctx.get('spec',{}).get('ground') or {}).get('kind')!='flume':
        raise ValueError('A water chute needs the collection channel base. Open its example to create one.')
    x,z,h=k.get('x_m',0),k.get('z_m',.7),k.get('height_m',.85)
    length,width=k.get('length_m',1.5),k.get('width_m',.26)
    at=[x,h,z]
    bed=_routing_bed(ctx,x,z)
    stand=_box(name+' stand',[x,(h-.04+bed)/2,z],[.04,h-.04-bed,.04],'concrete',True)
    trough=dict(name=name,shape='compound',material=k.get('material','iron'),at_m=at,fixed=False,
        turn_deg=mw.turn_of(mw.heading(k.get('yaw_deg',0),-k.get('drop_deg',20),0)),parts=[
            dict(shape='box',at_m=[0,0,0],size_m=[length,.04,width],turn_deg=[0,0,0]),
            *[dict(shape='box',at_m=[0,.08,side*(width/2+.02)],size_m=[length,.16,.04],turn_deg=[0,0,0]) for side in (-1,1)]])
    return dict(parts=[stand,trough],joints=[dict(name=name+' mount',kind='fix',a=stand['name'],b=name,
        at_m=at,axis=[0,1,0])])


def water_collector(name,k,ctx):
    if (ctx.get('spec',{}).get('ground') or {}).get('kind')!='flume':
        raise ValueError('A water collector needs the collection channel base. Open its example to create one.')
    x,z,floor=k.get('x_m',1),k.get('z_m',.7),k.get('floor_m',.25)
    legs=[_box(name+f' leg {i}',[x+dx,(floor-.05+_routing_bed(ctx,x+dx,z+dz))/2,z+dz],
              [.04,floor-.05-_routing_bed(ctx,x+dx,z+dz),.04],'concrete',True)
          for i,(dx,dz) in enumerate(((-.34,-.17),(-.34,.17),(.34,-.17),(.34,.17)))]
    vessel=dict(name=name,shape='compound',material=k.get('material','glass'),at_m=[x,floor+.17,z],fixed=False,parts=[
        dict(shape='box',at_m=[0,-.17,0],size_m=[.8,.03,.5],turn_deg=[0,0,0]),
        *[dict(shape='box',at_m=[dx,0,0],size_m=[.03,.35,.5],turn_deg=[0,0,0]) for dx in (-.385,.385)],
        *[dict(shape='box',at_m=[0,0,dz],size_m=[.8,.35,.03],turn_deg=[0,0,0]) for dz in (-.235,.235)]])
    return dict(parts=legs+[vessel],joints=[dict(name=name+' mount',kind='fix',a=legs[0]['name'],b=name,
        at_m=[x-.34,floor-.02,z-.17],axis=[0,1,0])],water_regions=[dict(title=name,
        at_m=[x,floor+.17,z],size_m=[.72,.32,.42],target_l=3)])


TRAY.extend([
    dict(piece='water_chute',count=99,cost=0,turns=['yaw_deg'],knobs={
        'x_m':knob(-1.5,1.5,.02,0,'position (m)'), 'z_m':knob(-1,1.5,.02,.7,'across channel (m)'),
        'height_m':knob(.5,1.3,.05,.85,'mount height (m)'),
        'length_m':knob(.6,2,.1,1.5,'chute length (m)'), 'width_m':knob(.18,.4,.02,.26,'inside width (m)'),
        'drop_deg':knob(5,35,5,20,'downhill angle'),
        'yaw_deg':dict(knob(-180,180,5,0,'aim'),turning=True,free=True),
        'material':dict(choices=['iron','glass','oak'],default='iron',label='material')}),
    dict(piece='water_collector',count=99,cost=0,turns=[],knobs={
        'x_m':knob(-1.5,1.5,.02,1,'position (m)'), 'z_m':knob(-1,1.5,.02,.7,'across channel (m)'),
        'floor_m':knob(.25,.65,.05,.25,'floor height (m)'),
        'material':dict(choices=['glass','oak','iron'],default='glass',label='material')})])
PIECES.update(water_chute=water_chute,water_collector=water_collector)

ROUTING_BASE=copy.deepcopy(CHANNEL_BASE)
ROUTING_BASE['title']='Divert the water'
ROUTING_BASE['parts']=[
    _box('source post',[-.6,.65,1.02],[.08,1.3,.08],'concrete',True),
    _box('source arm',[-.6,1.31,.84],[.1,.04,.44],'iron',True),
    _box('source nozzle',[-.6,1.30,.7],[.08,.08,.08],'iron',True)]
# The outlet is below the nozzle; the source is a declared finite supply.
ROUTING_BASE['spouts']=[dict(name='water supply',at_m=[-.6,1.25,.7],direction=[0,-1,0],
    speed_m_s=.2,discharge_l_s=1,initial_volume_l=4)]
_collector=water_collector('receiving container',{},dict(spec=ROUTING_BASE))
for _key,_value in _collector.items():ROUTING_BASE.setdefault(_key,[]).extend(_value)
_region=ROUTING_BASE['water_regions'][0]
_collector_rule=dict(water_in_zone_l=dict(at_m=_region['at_m'],size_m=_region['size_m'],l=3,for_s=.5))
_chute_tray=copy.deepcopy(next(t for t in TRAY if t['piece']=='water_chute'))
_chute_tray.update(count=1,sandbox_builder=True,start_at_defaults=True,frame_on_add=True)
_chute_tray['knobs']['yaw_deg']['default']=90
_routing=dict(id='easy-divert-water',title='Divert the water',teaches='gravity and water routing',
    brief='Aim the chute from the source into the empty container. Tip it downhill to collect three litres.',
    machine=ROUTING_BASE,goal=dict(title='Three litres stay in the container',focus=['source nozzle','receiving container'],
        station=dict(done_when=_collector_rule)),tray=[_chute_tray],
    solution=[dict(piece='water_chute',drop_deg=20,yaw_deg=0)],wrong=[dict(piece='water_chute',drop_deg=20,yaw_deg=180)],
    time_s=8,budget=1000000,par=1000000,par_energy_j=6849819400,style_pieces=1,difficulty='easy',
    hints=['Water runs downhill. The raised end belongs under the source.',
           'Aim the lower end into the container. The meter counts water inside, not water that passes nearby.'],turning=False)
EASY_LEVELS.append(_routing)
_routing_sandbox=copy.deepcopy(ROUTING_BASE)
_routing_sandbox['parts']=[p for p in _routing_sandbox['parts'] if not p['name'].startswith('receiving container')]
_routing_sandbox['joints']=[]
_routing_sandbox['water_regions']=[]
TEMPLATES.append(dict(id='water-routing',name='Divert water into a container',
    description='A finite source, an adjustable chute and a separate fixed collector. Mis-aim or reverse the slope to miss.',
    base=_routing_sandbox,placements=[dict(piece='water_collector')]+copy.deepcopy(_routing['solution'])))

# The receiver lesson teaches flow rate against a deadline, with the same
# native parcel containment observation as the routing lesson. Earlier shares
# retain their cumulative channel-receipt goal and original apparatus.
LEGACY_RECEIVER_LEVEL=copy.deepcopy(receiver)
receiver['machine']=copy.deepcopy(CHANNEL_BASE)
receiver['machine']['title']='Fill the receiver'
_receiver_box=water_collector('receiving box',dict(x_m=0,z_m=0),dict(spec=receiver['machine']))
for _key,_value in _receiver_box.items():receiver['machine'].setdefault(_key,[]).extend(_value)
_receiver_region=receiver['machine']['water_regions'][0]
receiver['time_s']=5
receiver['teaches']='water flow and timing'
receiver['goal']=dict(title='Collect 3 L in 5 seconds',focus=['receiving box'],
    station=dict(title='Fill the box before time runs out',done_when=dict(water_in_zone_l=dict(
        at_m=_receiver_region['at_m'],size_m=_receiver_region['size_m'],l=3,for_s=.5))))
receiver['tray'][0]['focus_knob']='opening_percent'
receiver['tray'][0]['knobs']['opening_percent']['default']=10
for _key,_rule in receiver['tray'][0]['knobs'].items():
    if _key in ('x_m','z_m','opening_percent'):continue
    if 'choices' in _rule:_rule['choices']=[_rule['default']]
    else:_rule['min']=_rule['max']=_rule['default']
    _rule['hidden']=True
receiver['solution']=[dict(piece='water_tank',fill_l=4,outlet_model='gravity',opening_percent=100)]
receiver['wrong']=[dict(receiver['solution'][0],opening_percent=10)]
receiver['brief']='Fill the waiting box with 3 litres in 5 seconds. The source starts at a trickle: increase its tap opening to collect enough in time.'
receiver['hints']=[receiver['brief'],'Three litres must stay inside the box for half a second before the deadline. Water outside does not count.']
