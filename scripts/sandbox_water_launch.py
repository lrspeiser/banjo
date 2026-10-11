"""Fixed metered water supplies and a counterweight cradle launcher.

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
    x, z, y = k.get('x_m',0), g.get('trench_z_m',0), k.get('height_m',1.1)
    # The tank is above the bank. Its indicated fixed outlet lies over the
    # collection channel; the connection is a metered feed, not head pressure.
    bank = z + .5*g.get('trench_width_m',.6) + .22
    tank = dict(name=name+' tank',shape='compound',material='iron',at_m=[x,y+.12,bank],fixed=True,
        parts=[dict(shape='box',at_m=[0,-.11,0],size_m=[.28,.02,.28],turn_deg=[0,0,0]),
               dict(shape='box',at_m=[-.13,0,0],size_m=[.02,.24,.28],turn_deg=[0,0,0]),
               dict(shape='box',at_m=[.13,0,0],size_m=[.02,.24,.28],turn_deg=[0,0,0]),
               dict(shape='box',at_m=[0,0,-.13],size_m=[.24,.24,.02],turn_deg=[0,0,0]),
               dict(shape='box',at_m=[0,0,.13],size_m=[.24,.24,.02],turn_deg=[0,0,0])])
    parts = [_box(name+' frame',[x,y*.5,bank],[.08,y,.08],'concrete',True),
             tank,
             _box(name+' outlet',[x,y+.06,z],[.06,.10,.06],'iron',True),
             _box(name+' feed bridge',[x,y+.13,(z+bank)*.5],[.06,.04,bank-z+.12],'iron',True)]
    return dict(parts=parts, spouts=[dict(name=name+' outlet', at_m=[x,y,z], direction=[0,-1,0],
        speed_m_s=0, discharge_l_s=k.get('discharge_l_s',2), initial_volume_l=k.get('fill_l',4),
        valve_open=k.get('valve','open')=='open',receiver_bounds_m=[
            -.5*(g.get('nx',60)-1)*g.get('cell_m',.1),.5*(g.get('nx',60)-1)*g.get('cell_m',.1),
            z-.5*g.get('trench_width_m',.6),z+.5*g.get('trench_width_m',.6)])])


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
